"""Tests for tools.pipeline — 议 D primitives (v0.7.7).

Three invariants exercised:

1. **Log is truth.** Every test path that leaves a ``rebuild_state``
   assertion verifies that what we wrote to the log is what we read
   back — no ``state.json`` cache in play.
2. **Driver guarantees terminal.** No ``run_stage`` block exits
   without exactly one of ``ok`` / ``failed`` / ``partial`` in the
   log. Every exception mode (custom, reserved-name, KeyboardInterrupt
   via BaseException) is verified to emit ``failed`` before unwinding.
3. **Stale ↔ live discrimination.** Dead-pid / cross-host / empty /
   malformed pidfiles all break cleanly; live-pid on same host is
   never broken automatically, even past TTL.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.pipeline import (
    RESERVED_EVENTS,
    StageBusyError,
    StagePartialExit,
    StageState,
    rebuild_state,
    run_stage,
)
from tools.pipeline import log as pipeline_log
from tools.pipeline.lock import StageLock


# ── helpers ───────────────────────────────────────────────────────────

def _find_dead_pid() -> int:
    """Return a PID that is currently not live on the host."""
    for candidate in range(999_999, 50, -1):
        try:
            os.kill(candidate, 0)
        except ProcessLookupError:
            return candidate
        except PermissionError:
            continue
    raise RuntimeError("no dead pid found — unusual environment")


def _write_pidfile(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ── happy path / basic contract ───────────────────────────────────────


def test_happy_path_writes_ok(tmp_path):
    with run_stage(tmp_path, "ingest", "doc-1") as ctx:
        ctx.log({"event": "doc_parsed", "n": 42})

    s = rebuild_state(tmp_path, "ingest", "doc-1")
    assert s.status == "ok"
    assert s.attempts == 1
    assert s.started_at is not None
    assert s.finished_at is not None
    assert s.last_err is None


def test_pending_when_no_log(tmp_path):
    s = rebuild_state(tmp_path, "ingest", "never-ran")
    assert s.status == "pending"
    assert s.attempts == 0
    assert s.started_at is None
    assert s.artifacts == []
    assert s.meta == {}


def test_reserved_event_names_rejected(tmp_path):
    """Every reserved name is refused by ctx.log — downstream cannot
    masquerade a free-form event as a driver signal."""
    for name in sorted(RESERVED_EVENTS):
        with pytest.raises(ValueError, match="reserved"):
            with run_stage(tmp_path, "s", f"key-{name}") as ctx:
                ctx.log({"event": name})

        # Failed-path terminal still written:
        s = rebuild_state(tmp_path, "s", f"key-{name}")
        assert s.status == "failed"
        assert "reserved" in (s.last_err or "")


def test_ctx_log_requires_event_field(tmp_path):
    with pytest.raises(ValueError, match="event"):
        with run_stage(tmp_path, "s", "no-event-key") as ctx:
            ctx.log({"data": "missing event key"})


# ── partial exit paths ────────────────────────────────────────────────


def test_mark_partial_writes_partial(tmp_path):
    with run_stage(tmp_path, "wenguan", "法華") as ctx:
        ctx.log({"event": "chunk_ok", "i": 0})
        ctx.mark_partial("quota at 1/3")
        # Normal return after mark → driver writes partial.

    s = rebuild_state(tmp_path, "wenguan", "法華")
    assert s.status == "partial"
    assert s.last_err == "partial: quota at 1/3"


def test_stage_partial_exit_is_swallowed(tmp_path):
    """Raising StagePartialExit exits the with-block cleanly — no
    exception propagates to the caller."""
    with run_stage(tmp_path, "wenguan", "金剛") as ctx:
        ctx.log({"event": "chunk_ok", "i": 0})
        raise StagePartialExit("LLM timeout")
    # If StagePartialExit had propagated, this line would not execute.

    s = rebuild_state(tmp_path, "wenguan", "金剛")
    assert s.status == "partial"
    assert s.last_err == "partial: LLM timeout"


def test_partial_reason_non_string_coerced(tmp_path):
    """Codex HIGH (v0.7.7 round 11): ``mark_partial`` /
    ``StagePartialExit`` accept any ``reason`` but the terminal
    log.append would crash on a non-JSON-serializable value (set,
    object, etc.) — breaking ``driver guarantees terminal``. The
    driver coerces via ``str()`` before logging; repr of the object
    ends up in the log, but the terminal is always written."""

    class Weird:
        def __repr__(self):
            return "Weird()"

    with run_stage(tmp_path, "s", "weird-partial-mark") as ctx:
        ctx.mark_partial(Weird())  # type: ignore[arg-type]

    s = rebuild_state(tmp_path, "s", "weird-partial-mark")
    assert s.status == "partial"
    assert "Weird()" in (s.last_err or "")

    # Same via exception path.
    with run_stage(tmp_path, "s", "weird-partial-exc") as ctx:
        raise StagePartialExit({1, 2, 3})  # type: ignore[arg-type]

    s = rebuild_state(tmp_path, "s", "weird-partial-exc")
    assert s.status == "partial"


def test_terminal_survives_broken_str_and_repr(tmp_path):
    """Codex HIGH (v0.7.7 round 12): ``str()`` on user-supplied
    values can itself raise if ``__str__`` is broken. The terminal-
    write path must still succeed so ``rebuild_state`` gets a real
    status, not ``running``."""

    class BadStr:
        def __str__(self):
            raise RuntimeError("__str__ raised")

        def __repr__(self):
            return "BadStr()"

    # Partial via mark.
    with run_stage(tmp_path, "s", "bad-str-mark") as ctx:
        ctx.mark_partial(BadStr())  # type: ignore[arg-type]
    assert rebuild_state(tmp_path, "s", "bad-str-mark").status == "partial"

    # Partial via exception.
    with run_stage(tmp_path, "s", "bad-str-exc") as ctx:
        raise StagePartialExit(BadStr())  # type: ignore[arg-type]
    assert rebuild_state(tmp_path, "s", "bad-str-exc").status == "partial"

    # Failed path: the exception's args include a BadStr.
    class BadException(Exception):
        def __str__(self):
            raise RuntimeError("__str__ raised on exception")

        def __repr__(self):
            return "BadException()"

    with pytest.raises(BadException):
        with run_stage(tmp_path, "s", "bad-str-fail"):
            raise BadException("ignored")
    assert rebuild_state(tmp_path, "s", "bad-str-fail").status == "failed"


def test_partial_reason_defaults_to_empty(tmp_path):
    with run_stage(tmp_path, "s", "k") as ctx:
        ctx.mark_partial("")

    s = rebuild_state(tmp_path, "s", "k")
    assert s.status == "partial"
    # last_err folds empty reason to plain "partial"
    assert s.last_err == "partial"


# ── failed path ───────────────────────────────────────────────────────


def test_exception_writes_failed_and_reraises(tmp_path):
    with pytest.raises(RuntimeError, match="disk full"):
        with run_stage(tmp_path, "sync", "slug") as ctx:
            ctx.log({"event": "write_started"})
            raise RuntimeError("disk full")

    s = rebuild_state(tmp_path, "sync", "slug")
    assert s.status == "failed"
    assert "RuntimeError: disk full" in (s.last_err or "")


def test_baseexception_still_writes_terminal(tmp_path):
    """KeyboardInterrupt / SystemExit (BaseException subclasses) must
    also get a terminal event — the driver cannot let a run hang."""
    with pytest.raises(KeyboardInterrupt):
        with run_stage(tmp_path, "s", "kbd") as ctx:
            raise KeyboardInterrupt()

    s = rebuild_state(tmp_path, "s", "kbd")
    assert s.status == "failed"
    assert "KeyboardInterrupt" in (s.last_err or "")


def test_failed_err_is_truncated(tmp_path):
    """The 'err' field on failed events is capped to keep log lines
    reasonable. The full traceback is never in-log anyway — callers
    who want it must capture separately."""
    giant = "x" * 2000
    with pytest.raises(RuntimeError):
        with run_stage(tmp_path, "s", "long-err") as ctx:
            raise RuntimeError(giant)

    s = rebuild_state(tmp_path, "s", "long-err")
    assert s.last_err is not None
    assert len(s.last_err) <= 500


# ── artifacts ─────────────────────────────────────────────────────────


def test_artifact_dedup_within_run(tmp_path):
    with run_stage(tmp_path, "s", "dup") as ctx:
        ctx.artifact("chunks/a")
        ctx.artifact("chunks/a")  # dup — one log event total
        ctx.artifact("chunks/b")

    events = list(pipeline_log.iter_events(tmp_path, "s", "dup"))
    artifact_events = [e for e in events if e.get("event") == "artifact"]
    assert len(artifact_events) == 2, "second artifact('chunks/a') should be no-op"

    s = rebuild_state(tmp_path, "s", "dup")
    assert s.artifacts == ["chunks/a", "chunks/b"]


def test_artifact_dedup_across_rounds(tmp_path):
    """artifacts field is a union across ALL rounds, set-deduped."""
    # Round 1 — fails after recording an artifact.
    with pytest.raises(RuntimeError):
        with run_stage(tmp_path, "s", "across") as ctx:
            ctx.artifact("chunks/a")
            raise RuntimeError("boom")
    # Round 2 — succeeds, records same + a new artifact.
    with run_stage(tmp_path, "s", "across") as ctx:
        ctx.artifact("chunks/a")
        ctx.artifact("chunks/b")

    s = rebuild_state(tmp_path, "s", "across")
    assert s.artifacts == ["chunks/a", "chunks/b"]
    assert s.attempts == 2
    assert s.status == "ok"


def test_artifact_requires_non_empty_string(tmp_path):
    with pytest.raises(ValueError):
        with run_stage(tmp_path, "s", "bad") as ctx:
            ctx.artifact("")


# ── meta ──────────────────────────────────────────────────────────────


def test_meta_init_populates_meta(tmp_path):
    with run_stage(tmp_path, "s", "m", meta_init={"source": "T", "doc": "0251"}):
        pass

    s = rebuild_state(tmp_path, "s", "m")
    assert s.meta == {"source": "T", "doc": "0251"}


def test_meta_update_last_write_wins(tmp_path):
    with run_stage(tmp_path, "s", "m", meta_init={"x": 1}) as ctx:
        ctx.meta_update(x=2, y=10)
        ctx.meta_update(y=20)

    s = rebuild_state(tmp_path, "s", "m")
    assert s.meta == {"x": 2, "y": 20}


def test_meta_only_last_round_applies(tmp_path):
    """Earlier rounds' meta is discarded on rebuild."""
    with pytest.raises(RuntimeError):
        with run_stage(tmp_path, "s", "meta-across",
                       meta_init={"round1_only": True}) as ctx:
            ctx.meta_update(shared="first")
            raise RuntimeError("fail round 1")

    with run_stage(tmp_path, "s", "meta-across",
                   meta_init={"round2_only": True}) as ctx:
        ctx.meta_update(shared="second")

    s = rebuild_state(tmp_path, "s", "meta-across")
    # round1_only is NOT present — earlier rounds' meta dropped.
    assert "round1_only" not in s.meta
    assert s.meta.get("round2_only") is True
    assert s.meta.get("shared") == "second"


def test_meta_update_noop_without_kwargs(tmp_path):
    with run_stage(tmp_path, "s", "empty-meta") as ctx:
        ctx.meta_update()  # no kwargs — no event

    events = list(pipeline_log.iter_events(tmp_path, "s", "empty-meta"))
    assert not any(e.get("event") == "meta_update" for e in events)


# ── multi-round rebuild contract ──────────────────────────────────────


def test_multi_round_last_terminal_wins(tmp_path):
    with run_stage(tmp_path, "s", "multi"):
        pass
    with pytest.raises(RuntimeError):
        with run_stage(tmp_path, "s", "multi"):
            raise RuntimeError("second round fails")

    s = rebuild_state(tmp_path, "s", "multi")
    assert s.status == "failed"
    assert s.attempts == 2
    assert "second round fails" in (s.last_err or "")


def test_multi_round_success_after_failure(tmp_path):
    with pytest.raises(RuntimeError):
        with run_stage(tmp_path, "s", "recover"):
            raise RuntimeError("first fails")
    with run_stage(tmp_path, "s", "recover"):
        pass

    s = rebuild_state(tmp_path, "s", "recover")
    assert s.status == "ok"
    assert s.attempts == 2
    assert s.last_err is None


# ── reserved event collision (direct log manipulation) ────────────────


def test_running_status_when_last_round_unterminated(tmp_path):
    """Hand-craft a log with a start but no terminal in the last
    round — rebuild must report ``running`` (the SIGKILL recovery
    path depends on this: if acquire doesn't run, status stays
    running; once acquire breaks the stale lock it becomes interrupted)."""
    pipeline_log.append(tmp_path, "s", "dangling", {"event": "start", "meta_init": {}})
    pipeline_log.append(tmp_path, "s", "dangling", {"event": "chunk_ok", "i": 0})

    s = rebuild_state(tmp_path, "s", "dangling")
    assert s.status == "running"
    assert s.attempts == 1
    assert s.finished_at is None


def test_interrupted_status_after_stale_break(tmp_path):
    """End-to-end: a run starts, dies (no terminal), the lockfile
    remains with a dead pid. Next ``run_stage`` sees the stale lock,
    writes an ``interrupted`` event, and runs to completion. The
    final state captures both: attempts=2 (one prior start, one
    recovered), status=ok (the recovery itself succeeded). Running
    ``rebuild_state`` partway through would have shown ``interrupted``."""
    # Craft the prior-run remnant: start event + live-looking lockfile
    # with a dead pid.
    pipeline_log.append(tmp_path, "s", "recov", {"event": "start", "meta_init": {}})
    pipeline_log.append(tmp_path, "s", "recov", {"event": "chunk_ok", "i": 0})
    lockpath = pipeline_log.log_path(tmp_path, "s", "recov").with_suffix(".lock")
    _write_pidfile(lockpath, {
        "pid": _find_dead_pid(),
        "host": socket.gethostname(),
        "started_at": "2020-01-01T00:00:00+00:00",
        "ttl": 3600,
        "key": "recov",
    })

    # Before recovery: status should be running (no terminal).
    s = rebuild_state(tmp_path, "s", "recov")
    assert s.status == "running"

    # Acquire via run_stage — should break stale, log interrupted, run.
    with run_stage(tmp_path, "s", "recov") as ctx:
        ctx.log({"event": "chunk_ok", "i": 1})

    s = rebuild_state(tmp_path, "s", "recov")
    assert s.status == "ok"
    assert s.attempts == 2  # original start + the recovery start

    # Verify interrupted event was recorded:
    events = list(pipeline_log.iter_events(tmp_path, "s", "recov"))
    assert any(e.get("event") == "interrupted" for e in events)


# ── lock: live / stale discrimination ─────────────────────────────────


def test_busy_lock_blocks_live_holder(tmp_path):
    first = StageLock(tmp_path, "s", "busy")
    assert first.acquire()
    try:
        with pytest.raises(StageBusyError):
            with run_stage(tmp_path, "s", "busy"):
                pass
    finally:
        first.release()

    # After release, a new run succeeds.
    with run_stage(tmp_path, "s", "busy"):
        pass
    s = rebuild_state(tmp_path, "s", "busy")
    assert s.status == "ok"


def test_dead_pid_lockfile_is_broken(tmp_path):
    lk = StageLock(tmp_path, "s", "dead")
    lockpath = lk.path
    _write_pidfile(lockpath, {
        "pid": _find_dead_pid(),
        "host": socket.gethostname(),
        "started_at": "2020-01-01T00:00:00+00:00",
        "ttl": 3600,
    })
    assert lk.acquire()
    lk.release()


def test_cross_host_lockfile_is_broken(tmp_path):
    """A pidfile from another host cannot have its pid validated —
    treated as stale."""
    lk = StageLock(tmp_path, "s", "xhost")
    _write_pidfile(lk.path, {
        "pid": os.getpid(),  # our pid, so alive if same host
        "host": "some-other-machine-that-isnt-us",
        "started_at": "2020-01-01T00:00:00+00:00",
        "ttl": 3600,
    })
    assert lk.acquire()
    lk.release()


@pytest.mark.parametrize("bad_content", [
    "",                                       # empty
    "{not valid json",                        # malformed
    '{"pid": 1}',                             # missing host, started_at
    '["list instead of dict"]',               # wrong shape
    '{"pid": "string", "host": "x", "started_at": "y"}',  # wrong pid type
    '{"pid": -1, "host": "x", "started_at": "y"}',        # non-positive pid
    '{"pid": 0, "host": "x", "started_at": "y"}',         # zero pid
    '{"pid": 1.5, "host": "x", "started_at": "y"}',       # float pid
    '{"pid": null, "host": "x", "started_at": "y"}',      # null pid
])
def test_malformed_pidfile_is_broken(tmp_path, bad_content):
    lk = StageLock(tmp_path, "s", f"bad-{hash(bad_content)}")
    lk.path.parent.mkdir(parents=True, exist_ok=True)
    lk.path.write_text(bad_content, encoding="utf-8")
    assert lk.acquire(), f"should have broken malformed lock: {bad_content!r}"
    lk.release()


@pytest.mark.parametrize("pid_value,reason", [
    ("true",       "bool subclass of int — Codex round 3 HIGH"),
    ("false",      "False also bool"),
    ("99999999999999999999", "oversized pid raises OverflowError in os.kill"),
])
def test_pathological_pid_types_are_stale(tmp_path, pid_value, reason):
    """Same-host pidfile whose pid field is something perverse:
    ``true`` (JSON bool, an ``int`` subclass — would otherwise probe
    PID 1 / init), or an oversized integer (OverflowError from
    os.kill). Both must classify as stale so the slot is reclaimable.

    These must use the REAL hostname to defeat the cross-host check;
    we want to exercise the PID-level validation."""
    lk = StageLock(tmp_path, "s", f"weird-{reason}")
    lk.path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        '{"pid": ' + pid_value + ', "host": ' + json.dumps(socket.gethostname())
        + ', "started_at": "2020-01-01T00:00:00+00:00", "ttl": 3600}'
    )
    lk.path.write_text(payload, encoding="utf-8")
    assert lk.acquire(), f"pid={pid_value!r} must be treated as stale ({reason})"
    lk.release()


def test_live_pid_lock_NEVER_broken_even_past_ttl(tmp_path):
    """The strongest invariant: a live PID on the same host is never
    auto-broken, even if the recorded TTL is far in the past. Operator
    must call ``force_break`` after verifying via ``ps``."""
    lk = StageLock(tmp_path, "s", "live-hang")
    _write_pidfile(lk.path, {
        "pid": os.getpid(),  # definitely alive — it's us
        "host": socket.gethostname(),
        "started_at": "2000-01-01T00:00:00+00:00",  # ~25 years ago
        "ttl": 1,  # "expired" 25 years ago
    })
    assert lk.acquire() is False, "must refuse live-pid even past TTL"

    # force_break is the operator escape hatch.
    lk.force_break()
    assert lk.acquire()
    lk.release()


def test_release_is_idempotent(tmp_path):
    """Release after failed acquire and after a successful release
    must both no-op."""
    lk = StageLock(tmp_path, "s", "idem")
    lk.release()  # never acquired
    assert lk.acquire()
    lk.release()
    lk.release()  # second release


# ── log.py: append / iter_events / torn writes ────────────────────────


def test_append_adds_timestamp(tmp_path):
    pipeline_log.append(tmp_path, "s", "k", {"event": "x"})
    events = list(pipeline_log.iter_events(tmp_path, "s", "k"))
    assert len(events) == 1
    assert "ts" in events[0]
    # ISO-8601 with +00:00 suffix for UTC.
    assert events[0]["ts"].endswith("+00:00") or "Z" in events[0]["ts"]


def test_server_ts_overwrites_caller_ts(tmp_path):
    """Callers cannot forge a timestamp — append() is authoritative."""
    fake_ts = "1999-12-31T23:59:59+00:00"
    pipeline_log.append(tmp_path, "s", "k", {"event": "x", "ts": fake_ts})
    events = list(pipeline_log.iter_events(tmp_path, "s", "k"))
    assert events[0]["ts"] != fake_ts


def test_torn_line_is_skipped(tmp_path):
    """Simulate a crash mid-write: a partial JSON line at end of
    file. iter_events skips it; a subsequent complete append works."""
    pipeline_log.append(tmp_path, "s", "torn", {"event": "first"})

    path = pipeline_log.log_path(tmp_path, "s", "torn")
    with open(path, "ab") as f:
        f.write(b'{"event": "partial line with no newline or close')

    # Mid-file state: one good line, one torn line.
    events = list(pipeline_log.iter_events(tmp_path, "s", "torn"))
    assert len(events) == 1
    assert events[0]["event"] == "first"

    # New append still works — starts on a fresh line.
    pipeline_log.append(tmp_path, "s", "torn", {"event": "second"})
    events = list(pipeline_log.iter_events(tmp_path, "s", "torn"))
    assert [e["event"] for e in events] == ["first", "second"]


def test_torn_multibyte_line_is_skipped(tmp_path):
    """Codex HIGH (v0.7.7 round 8): a torn write that slices through
    a multi-byte UTF-8 sequence (realistic with ``ensure_ascii=False``
    on CJK payloads) would raise ``UnicodeDecodeError`` in strict
    text mode and abort iter_events entirely — breaking the
    crash-recovery contract. Per-line decode with except-and-skip
    isolates the damage to that one line."""
    pipeline_log.append(tmp_path, "s", "mb-torn", {"event": "first", "x": "中"})

    path = pipeline_log.log_path(tmp_path, "s", "mb-torn")
    with open(path, "ab") as f:
        # First two bytes of a 3-byte UTF-8 sequence (U+4E2D 中 is
        # E4 B8 AD). No terminator — realistic mid-write crash.
        f.write(b"\xe4\xb8")

    # Despite the torn multi-byte trailer, iter_events must yield
    # the earlier complete event without crashing.
    events = list(pipeline_log.iter_events(tmp_path, "s", "mb-torn"))
    assert [e["event"] for e in events] == ["first"]

    # Append heals as usual — the leading-\n recovery applies.
    pipeline_log.append(tmp_path, "s", "mb-torn", {"event": "second"})
    events = list(pipeline_log.iter_events(tmp_path, "s", "mb-torn"))
    assert [e["event"] for e in events] == ["first", "second"]


def test_binary_garbage_line_is_skipped(tmp_path):
    """A stray binary line in the JSONL (manual edit gone wrong, or
    another tool's trash landed in the file) must not crash
    iteration — ``UnicodeDecodeError`` handling is a general
    safeguard, not a corner case."""
    path = pipeline_log.log_path(tmp_path, "s", "bin")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b'{"event": "ok", "ts": "t1"}\n'
        b'\x00\x01\x02\xff\xfe\n'
        b'{"event": "ok", "ts": "t2"}\n'
    )
    events = list(pipeline_log.iter_events(tmp_path, "s", "bin"))
    assert [e["event"] for e in events] == ["ok", "ok"]


def test_non_utf8_pidfile_is_stale(tmp_path):
    """Codex HIGH (v0.7.7 round 8): pidfile with non-UTF-8 bytes
    must classify as malformed/stale instead of crashing
    ``acquire()`` with ``UnicodeDecodeError``."""
    lk = StageLock(tmp_path, "s", "nonutf8-pid")
    lk.path.parent.mkdir(parents=True, exist_ok=True)
    lk.path.write_bytes(b"\xff\xfe\xfd\xfc")  # definitely not UTF-8
    assert lk.acquire(), "non-UTF-8 pidfile must be treated as stale"
    lk.release()


def test_blank_lines_skipped(tmp_path):
    path = pipeline_log.log_path(tmp_path, "s", "blank")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\n\n{"event": "x", "ts": "t"}\n\n')
    events = list(pipeline_log.iter_events(tmp_path, "s", "blank"))
    assert len(events) == 1
    assert events[0]["event"] == "x"


def test_tail_limit(tmp_path):
    for i in range(10):
        pipeline_log.append(tmp_path, "s", "tail", {"event": "e", "i": i})

    assert [e["i"] for e in pipeline_log.tail(tmp_path, "s", "tail", limit=3)] == [7, 8, 9]
    assert pipeline_log.tail(tmp_path, "s", "tail", limit=0) == []
    assert len(pipeline_log.tail(tmp_path, "s", "tail", limit=100)) == 10


# ── concurrency: flock prevents interleave ────────────────────────────


def _worker_append(args):
    base, stage, key, worker_id, count = args
    from tools.pipeline import log as _log  # fresh import in child
    for i in range(count):
        _log.append(Path(base), stage, key, {
            "event": "work",
            "worker": worker_id,
            "i": i,
        })


def test_concurrent_append_no_interleave(tmp_path):
    """4 processes × 100 events: every line must be complete JSON, no
    interleaving within a line."""
    ctx = multiprocessing.get_context("spawn")
    args = [(str(tmp_path), "s", "conc", wid, 100) for wid in range(4)]
    with ctx.Pool(4) as pool:
        pool.map(_worker_append, args)

    events = list(pipeline_log.iter_events(tmp_path, "s", "conc"))
    assert len(events) == 400, f"expected 400 clean events, got {len(events)}"
    # Every worker's contribution is entirely present.
    by_worker: dict[int, set[int]] = {}
    for e in events:
        by_worker.setdefault(e["worker"], set()).add(e["i"])
    for wid in range(4):
        assert by_worker[wid] == set(range(100)), f"worker {wid} lost events"


# ── key encoding / filesystem layout ──────────────────────────────────


def test_key_hashed_to_full_sha256(tmp_path):
    """Codex HIGH round 7: key must be hashed to full 64-hex sha256
    (not a 16-hex prefix). Truncation creates a bounded-collision
    window where two unrelated (stage, key) pairs share a jsonl and
    lock — that's semantic state contamination, not just a spurious
    busy. ``chunk_cache`` set the precedent in v0.7.5."""
    with run_stage(tmp_path, "stage", "some-long-key-中文"):
        pass
    files = list((tmp_path / ".pipeline" / "stage").iterdir())
    jsonl = [f for f in files if f.suffix == ".jsonl"]
    assert len(jsonl) == 1
    stem = jsonl[0].stem
    assert len(stem) == 64, f"key must be full sha256 (64 hex), got {len(stem)}"
    assert all(c in "0123456789abcdef" for c in stem)


def test_fs_unsafe_key_contained(tmp_path):
    """Keys with slashes / traversal must hash — never escape."""
    with run_stage(tmp_path, "s", "../../../etc/passwd"):
        pass
    assert (tmp_path / ".pipeline" / "s").is_dir()
    # No escape:
    assert not (tmp_path.parent.parent.parent / "etc" / "passwd").exists() or \
        (tmp_path.parent.parent.parent / "etc" / "passwd").is_file()  # pre-existing system file ok


# ── StageState dataclass direct ──────────────────────────────────────


@pytest.mark.parametrize("bad_meta", [
    [],                    # JSON-serializable but not a dict
    [("a", 1)],            # dict-constructible but not a dict
    "not a dict",          # string
    42,                    # int
    None,                  # wait, None is the default — skipped via special case below
])
def test_meta_init_non_dict_rejected(tmp_path, bad_meta):
    """Codex (v0.7.7 round 10): a non-dict meta_init that happens
    to be JSON-serializable (``[]``, ``"x"``, a list of tuples) used
    to pass the serializability pre-check, get the lock, then crash
    at ``dict(meta_init)`` with no terminal. Type check added."""
    if bad_meta is None:
        return  # None is the valid default — skip
    with pytest.raises(TypeError, match="dict"):
        with run_stage(tmp_path, "s", f"bad-mi-{type(bad_meta).__name__}",
                       meta_init=bad_meta):
            pass
    assert rebuild_state(tmp_path, "s",
                         f"bad-mi-{type(bad_meta).__name__}").status == "pending"


def test_unreadable_pidfile_returns_busy_not_break(tmp_path):
    """Codex HIGH (v0.7.7 round 10): a pidfile we cannot read due
    to permissions must NOT be classified as stale — we can't
    verify the holder's liveness, so breaking the lock would be
    unsafe. acquire must return False (busy) so the caller backs
    off; force_break remains the operator escape hatch."""
    lk = StageLock(tmp_path, "s", "no-read-perm")
    lk.path.parent.mkdir(parents=True, exist_ok=True)
    # Write a legitimate-looking pidfile, then chmod 000 so our
    # read_bytes raises PermissionError.
    _write_pidfile(lk.path, {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "started_at": "2026-01-01T00:00:00+00:00",
        "ttl": 3600,
    })
    original_mode = lk.path.stat().st_mode
    try:
        os.chmod(lk.path, 0o000)

        # Must NOT raise, must NOT log interrupted — just refuse.
        assert lk.acquire() is False, (
            "unreadable pidfile is ambiguous — acquire must return busy, "
            "not stale-break a potentially live holder"
        )

        events = list(pipeline_log.iter_events(tmp_path, "s", "no-read-perm"))
        assert not any(e.get("event") == "interrupted" for e in events), (
            "acquire must not log spurious interrupted on permission error"
        )
    finally:
        os.chmod(lk.path, original_mode)
        lk.force_break()


def test_meta_init_unserializable_rejected_without_side_effects(tmp_path):
    """Codex HIGH (v0.7.7 round 9): a non-JSON-serializable
    ``meta_init`` would crash ``_log.append`` mid-driver and leave
    the stage in state ``running`` with a held lock — violating
    "driver guarantees terminal". Pre-validate: raise TypeError
    before acquire, no lock taken, no log event written."""

    class Uncool:
        pass

    with pytest.raises(TypeError, match="JSON-serializable"):
        with run_stage(tmp_path, "s", "bad-mi", meta_init={"x": Uncool()}):
            pass

    # No side effects on the slot at all:
    assert rebuild_state(tmp_path, "s", "bad-mi").status == "pending"
    # A follow-up acquire must work (lock was never taken).
    with run_stage(tmp_path, "s", "bad-mi"):
        pass
    assert rebuild_state(tmp_path, "s", "bad-mi").status == "ok"


def test_iter_events_drops_non_object_lines(tmp_path):
    """Codex round 4: a valid-JSON but non-object line (``[]``,
    ``"s"``, ``123``) in the log would break ``rebuild_state.get``
    with AttributeError. iter_events must filter to dicts only."""
    path = pipeline_log.log_path(tmp_path, "s", "nonobj")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b'{"event": "start", "ts": "t1"}\n'
        b'[]\n'                  # valid JSON, wrong shape
        b'"just a string"\n'     # valid JSON, wrong shape
        b'12345\n'               # valid JSON number
        b'{"event": "ok", "ts": "t2"}\n'
    )
    events = list(pipeline_log.iter_events(tmp_path, "s", "nonobj"))
    assert [e.get("event") for e in events] == ["start", "ok"]

    # And rebuild_state should work without crashing.
    s = rebuild_state(tmp_path, "s", "nonobj")
    assert s.status == "ok"


def test_rebuild_tolerates_non_dict_meta_init(tmp_path):
    """If a start event's ``meta_init`` is malformed (string, list,
    number), rebuild falls back to empty meta rather than raising."""
    path = pipeline_log.log_path(tmp_path, "s", "bad-mi")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b'{"event": "start", "meta_init": "not a dict", "ts": "t1"}\n'
        b'{"event": "ok", "ts": "t2"}\n'
    )
    s = rebuild_state(tmp_path, "s", "bad-mi")
    assert s.status == "ok"
    assert s.meta == {}


def test_stagestate_default_construction():
    s = StageState(stage="x", key="y")
    assert s.status == "pending"
    assert s.attempts == 0
    assert s.artifacts == []
    assert s.meta == {}


# ── sanity: same stage, different keys are independent ────────────────


def test_meta_update_cannot_inject_reserved_event(tmp_path):
    """Codex HIGH (v0.7.7): ``ctx.meta_update(event='ok')`` used to
    overwrite the driver-set event name via ``**kwargs``, letting a
    caller forge a terminal from inside meta_update. Rejected now."""
    with pytest.raises(ValueError, match="reserved"):
        with run_stage(tmp_path, "s", "inject-event") as ctx:
            ctx.meta_update(event="ok")

    # The attempted injection landed us in failed territory, not ok.
    s = rebuild_state(tmp_path, "s", "inject-event")
    assert s.status == "failed"


def test_meta_update_cannot_inject_ts(tmp_path):
    with pytest.raises(ValueError, match="reserved"):
        with run_stage(tmp_path, "s", "inject-ts") as ctx:
            ctx.meta_update(ts="1999-12-31T23:59:59+00:00")


def test_meta_update_event_key_always_wins(tmp_path):
    """Defense in depth: even if the reservation check is somehow
    bypassed, the event key is set AFTER kwargs so the log record
    always carries event=meta_update. This test verifies the ordering
    by inspecting the on-disk event directly."""
    with run_stage(tmp_path, "s", "ordering") as ctx:
        ctx.meta_update(x=1, y=2)

    events = list(pipeline_log.iter_events(tmp_path, "s", "ordering"))
    meta_events = [e for e in events if e.get("event") == "meta_update"]
    assert len(meta_events) == 1
    assert meta_events[0]["event"] == "meta_update"
    assert meta_events[0]["x"] == 1
    assert meta_events[0]["y"] == 2


@pytest.mark.parametrize("bad_stage", [
    "../escape",
    "..",
    ".",
    "a/b",
    "a\\b",
    "",
    ".hidden",
    "x\x00y",
    "a b",  # whitespace
    "中文/路径",
])
def test_stage_name_rejects_path_traversal(tmp_path, bad_stage):
    """Codex HIGH (v0.7.7): stage lands on disk as a directory name.
    Traversal segments (``../x``, absolute paths, NULs, separators)
    must be rejected before touching the filesystem."""
    with pytest.raises(ValueError, match="invalid stage name"):
        with run_stage(tmp_path, bad_stage, "key"):
            pass


def test_stage_name_accepts_reasonable_values(tmp_path):
    """The allowed set covers siwen's realistic stage vocabulary."""
    for ok in ["wenguan", "sync_partial", "ingest-v2", "s.1", "_internal"]:
        with run_stage(tmp_path, ok, "k"):
            pass


def test_concurrent_stale_break_no_overlap(tmp_path):
    """Codex HIGH (v0.7.7 rounds 1, 6): two acquirers both classifying
    the same stale pidfile must not end up simultaneously holding the
    lock. The original test only asserted result counts; the round-6
    race slips through that assertion because both racers return
    ``"acquired"`` from their own perspective even though they were
    inside the critical section at the same time.

    Detect overlap directly: each worker, upon acquiring, attempts
    to create a shared marker file with ``O_CREAT|O_EXCL``. If any
    other worker is currently inside the ``with run_stage`` block,
    ``FileExistsError`` fires and the worker reports overlap. The
    assertion rejects any overlap report."""
    lock_path = pipeline_log.log_path(tmp_path, "s", "race").with_suffix(".lock")
    _write_pidfile(lock_path, {
        "pid": _find_dead_pid(),
        "host": socket.gethostname(),
        "started_at": "2000-01-01T00:00:00+00:00",
        "ttl": 3600,
        "key": "race",
    })

    marker_dir = tmp_path / ".overlap-marker"
    marker_dir.mkdir()
    marker = marker_dir / "in-progress"

    ctx = multiprocessing.get_context("spawn")
    workers = 8
    with ctx.Pool(workers) as pool:
        results = pool.map(
            _race_worker,
            [(str(tmp_path), i, str(marker)) for i in range(workers)],
        )

    overlaps = [r for r in results if r.startswith("overlap:")]
    assert not overlaps, (
        f"mutual exclusion violated — concurrent holders detected: {overlaps}. "
        f"all results: {results}"
    )

    wins = sum(1 for r in results if r == "acquired")
    assert wins >= 1, f"no worker ever acquired: {results}"

    # Post-condition: lock is free, interrupted event was logged.
    from tools.pipeline.lock import StageLock as _L
    final = _L(tmp_path, "s", "race")
    assert final.acquire(), "lock should be free after all workers exit"
    final.release()

    events = list(pipeline_log.iter_events(tmp_path, "s", "race"))
    assert any(e.get("event") == "interrupted" for e in events), \
        "at least one worker should have logged the interrupted recovery"


def _race_worker(args):
    base, worker_id, marker_str = args
    from pathlib import Path as _P
    from tools.pipeline import run_stage as _run
    from tools.pipeline.driver import StageBusyError as _Busy
    import os as _os
    import time as _time
    marker = _P(marker_str)
    try:
        with _run(_P(base), "s", "race") as ctx:
            # Claim the marker file — if another worker is already in
            # the critical section, this raises FileExistsError.
            try:
                fd = _os.open(str(marker), _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY, 0o644)
            except FileExistsError:
                return f"overlap:w{worker_id}"
            _os.write(fd, str(_os.getpid()).encode())
            _os.close(fd)
            # Hold briefly to widen the overlap window if the bug
            # were present. 10 ms is enough that the bug would be
            # detected; small enough to keep the test fast.
            _time.sleep(0.01)
            # Release the marker BEFORE releasing the run_stage lock.
            try:
                marker.unlink()
            except FileNotFoundError:
                pass
            ctx.log({"event": "worker_active", "w": worker_id})
        return "acquired"
    except _Busy:
        return "busy"


def test_empty_pidfile_never_breaks_live_lock(tmp_path):
    """Codex HIGH (v0.7.7 round 2): with O_EXCL-then-write pidfile
    init, a racing acquirer could observe the still-empty file,
    classify it as stale, and break an in-progress-but-winning
    holder. With atomic tempfile+link, the pidfile is never
    observable as empty — so an ``acquire`` that wins cannot be
    broken by a concurrent stale-breaker.

    This test can't easily simulate the exact O_EXCL timing window,
    but it does verify the replacement strategy: after a successful
    acquire, the pidfile contains complete JSON with all required
    fields — never empty."""
    lk = StageLock(tmp_path, "s", "atomic-pub")
    assert lk.acquire()
    try:
        content = lk.path.read_text(encoding="utf-8")
        assert content, "pidfile must not be empty after acquire"
        data = json.loads(content)
        assert data["pid"] == os.getpid()
        assert data["host"] == socket.gethostname()
        assert "started_at" in data
        assert "key" in data
    finally:
        lk.release()


def test_interrupted_event_precedes_new_start_in_log(tmp_path):
    """Codex HIGH (v0.7.7 round 2): interrupted must be logged BEFORE
    the stale pidfile is freed — otherwise a fast new acquirer can
    write start + run + ok into the log before the slow stale-breaker
    finally appends interrupted, poisoning the new run's round and
    making rebuild_state report the wrong status.

    This test verifies the ordering at the log level: after a
    stale-break + new run, the ``interrupted`` event appears BEFORE
    the new round's ``start``."""
    # Prime a stale pidfile.
    lock_path = pipeline_log.log_path(tmp_path, "s", "ordering-hi").with_suffix(".lock")
    _write_pidfile(lock_path, {
        "pid": _find_dead_pid(),
        "host": socket.gethostname(),
        "started_at": "2020-01-01T00:00:00+00:00",
        "ttl": 3600,
        "key": "ordering-hi",
    })
    pipeline_log.append(tmp_path, "s", "ordering-hi",
                        {"event": "start", "meta_init": {}})
    pipeline_log.append(tmp_path, "s", "ordering-hi",
                        {"event": "chunk_ok", "i": 0})

    with run_stage(tmp_path, "s", "ordering-hi"):
        pass

    events = list(pipeline_log.iter_events(tmp_path, "s", "ordering-hi"))
    interrupted_idx = next(i for i, e in enumerate(events)
                           if e.get("event") == "interrupted")
    # Last start is the new run's start — it must come AFTER interrupted.
    start_indices = [i for i, e in enumerate(events) if e.get("event") == "start"]
    new_start_idx = start_indices[-1]
    assert interrupted_idx < new_start_idx, (
        "interrupted must precede the new run's start; otherwise rebuild_state "
        "would fold it into the new round and report the wrong status"
    )

    # End state is clean:
    s = rebuild_state(tmp_path, "s", "ordering-hi")
    assert s.status == "ok"


def test_release_race_does_not_log_spurious_interrupted(tmp_path, monkeypatch):
    """Codex HIGH (v0.7.7 round 5): the acquire loop saw
    ``FileExistsError`` from ``os.link``, then read the pidfile and
    got ``FileNotFoundError`` (because the prior holder released
    between the two syscalls). The old code treated ``None`` holder
    as stale and logged ``interrupted`` — corrupting the prior run's
    round, since last-terminal-wins would flip its ``ok`` to
    ``interrupted``. The fix distinguishes "file missing now" (race
    with release — retry link silently) from "file malformed"
    (truly stale — log interrupted and break)."""
    import os as _os

    # First, a normal run completes cleanly so the log carries a
    # legitimate "ok" terminal.
    with run_stage(tmp_path, "s", "race-rel") as ctx:
        ctx.log({"event": "chunk_ok", "i": 0})

    # Pre-check: baseline state is ok.
    assert rebuild_state(tmp_path, "s", "race-rel").status == "ok"

    # Now simulate the race on the next acquire: os.link raises
    # FileExistsError once (as if someone's pidfile was there),
    # but no pidfile is actually on disk — equivalent to the holder
    # having just unlinked. The fix must retry, NOT log interrupted.
    real_link = _os.link
    call_count = {"n": 0}

    def flaky_link(src, dst):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise FileExistsError(17, "File exists", dst)
        return real_link(src, dst)

    monkeypatch.setattr("os.link", flaky_link)

    with run_stage(tmp_path, "s", "race-rel"):
        pass

    # The prior round's "ok" must not have been corrupted by a
    # spurious interrupted event glued before the new round's start.
    events = list(pipeline_log.iter_events(tmp_path, "s", "race-rel"))
    # Count interrupted events; the race should have produced ZERO.
    interrupted_count = sum(1 for e in events if e.get("event") == "interrupted")
    assert interrupted_count == 0, (
        "transient FileNotFoundError during acquire (release race) must NOT "
        "log interrupted"
    )
    assert rebuild_state(tmp_path, "s", "race-rel").status == "ok"


def test_stage_and_key_isolation(tmp_path):
    with run_stage(tmp_path, "wenguan", "book-a"):
        pass
    with pytest.raises(RuntimeError):
        with run_stage(tmp_path, "wenguan", "book-b"):
            raise RuntimeError("b fails")

    assert rebuild_state(tmp_path, "wenguan", "book-a").status == "ok"
    assert rebuild_state(tmp_path, "wenguan", "book-b").status == "failed"
    # Cross-stage also isolated:
    assert rebuild_state(tmp_path, "ingest", "book-a").status == "pending"
