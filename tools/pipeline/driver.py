"""``run_stage`` contextmanager — **driver guarantees terminal** (议 D).

The three-law stance of ``tools.pipeline``:

1. **Log is truth.** Append-only JSONL, never rewritten.
2. **State is view.** ``rebuild_state`` reconstructs it on demand.
3. **Driver guarantees terminal.** Every ``run_stage`` block ends with
   exactly one of ``ok`` / ``failed`` / ``partial`` written to the
   log, on every exit path — normal return, exception, or the
   next-acquire's ``interrupted`` event when the process died
   outright. ``rebuild_state`` can therefore always resolve a
   concrete ``status``; no run is stuck ``running`` forever.

Downstream writes their handler as plain code inside the ``with``
block; the driver handles acquire, start event, terminal event, and
release. If you find yourself calling the lower-level primitives
(``log.append``, ``StageLock.acquire``) directly, step back — the
guarantee above does not hold for hand-rolled pipelines.

Typical use (siwen wenguan)::

    with run_stage(base_dir, "wenguan", slug, ttl=7200) as ctx:
        chunks = split_by_heading(body, level=2)
        ctx.log({"event": "chunks_planned", "n": len(chunks)})
        ctx.meta_update(chunks_total=len(chunks))
        for i, section in enumerate(chunks):
            cid = section.title
            content_hash = sha256(section.content).hexdigest()
            if (cached := cache.get(cid, content_hash)) is not None:
                ctx.log({"event": "chunk_hit", "i": i, "cid": cid})
                continue
            try:
                out = llm_wenguan(section.content)
            except QuotaExceeded as e:
                ctx.mark_partial(f"quota at {i}/{len(chunks)}")
                break
            cache.put(cid, content_hash, out)
            ctx.log({"event": "chunk_ok", "i": i, "cid": cid,
                     "in": len(section.content), "out": len(out)})
            ctx.artifact(f"chunks/{cid}")
        # Terminal event auto-written:
        #   - "partial" if ctx.mark_partial was called (or
        #     StagePartialExit was raised)
        #   - "failed" if any other exception escaped the block
        #   - "ok" on clean completion
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import log as _log
from .lock import StageLock
from .state import RESERVED_EVENTS


def _safe_str(x: object) -> str:
    """Coerce ``x`` to ``str`` without letting a broken ``__str__`` /
    ``__repr__`` escape. The driver's terminal-write path calls
    ``str()`` on user-supplied values (exception args, partial
    reasons); a custom ``__str__`` that raises would otherwise skip
    the terminal event and leave the run stuck as ``running`` —
    violating "driver guarantees terminal" (Codex HIGH v0.7.7 r12)."""
    try:
        return str(x)
    except BaseException:
        try:
            return repr(x)
        except BaseException:
            return "<unrepresentable>"


class StageBusyError(Exception):
    """Raised by :func:`run_stage` when a live holder owns the lock.

    The caller should back off (another worker is actively running the
    same stage+key). Not a programmer error — ordinary runtime state.
    """


class StagePartialExit(Exception):
    """Handler-raised signal that the run completed work but should be
    recorded as ``partial`` rather than ``ok`` or ``failed``.

    Semantically equivalent to calling ``ctx.mark_partial(reason)``
    and returning normally — use whichever unwinds your code more
    cleanly. The driver catches this exception, writes the ``partial``
    terminal event, and **does not re-raise** it. The caller's ``with``
    block exits without an exception propagating outward; branch on
    ``rebuild_state(...).status == "partial"`` to detect this case.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class StageContext:
    """Handler-facing surface yielded by :func:`run_stage`.

    Every method on this class produces one log event. ``StageState``
    is rebuilt from that event stream, so anything you record here is
    recoverable after a crash.
    """

    def __init__(self, base_dir: Path, stage: str, key: str):
        self._base_dir = base_dir
        self._stage = stage
        self._key = key
        self._artifact_seen: set[str] = set()
        self._partial_marked = False
        self._partial_reason = ""

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def stage(self) -> str:
        return self._stage

    @property
    def key(self) -> str:
        return self._key

    def log(self, event: dict) -> None:
        """Append a free-form event to the log.

        The event dict must include an ``event`` key naming the event
        (e.g. ``"chunk_ok"``, ``"cache_hit"``). The name must not
        collide with a reserved driver event: ``start``, ``ok``,
        ``failed``, ``partial``, ``interrupted``, ``artifact``,
        ``meta_update``. Prefix custom events with ``chunk_``,
        ``cache_``, etc. to avoid the namespace.
        """
        name = event.get("event")
        if not isinstance(name, str) or not name:
            raise ValueError("ctx.log: event dict must include a non-empty 'event' key")
        if name in RESERVED_EVENTS:
            raise ValueError(
                f"ctx.log: event name {name!r} is reserved for driver internals; "
                f"prefix with chunk_/cache_/custom_ or choose another"
            )
        _log.append(self._base_dir, self._stage, self._key, event)

    def artifact(self, path: str) -> None:
        """Record an artifact path produced by this stage. Idempotent
        within a run — repeating the same path is a no-op. Paths are
        opaque strings (typically filesystem paths relative to
        ``base_dir``); the driver does not validate them."""
        if not isinstance(path, str) or not path:
            raise ValueError("ctx.artifact: path must be a non-empty string")
        if path in self._artifact_seen:
            return
        self._artifact_seen.add(path)
        _log.append(self._base_dir, self._stage, self._key, {
            "event": "artifact",
            "path": path,
        })

    def meta_update(self, **kwargs: Any) -> None:
        """Merge keyword arguments into the run's meta. Keys
        accumulate across calls (last-write-wins per key); the full
        result is visible on ``StageState.meta`` after
        ``rebuild_state``.

        Callers cannot inject a reserved event name or override the
        event timestamp by passing ``event=`` / ``ts=`` in kwargs —
        those keys are rejected. ``rebuild_state`` drops ``event`` /
        ``ts`` before folding the event into ``meta`` anyway, but
        rejecting at the ctx layer prevents the log from carrying
        confusing or actively malicious payloads at all.
        """
        if not kwargs:
            return
        for reserved in ("event", "ts"):
            if reserved in kwargs:
                raise ValueError(
                    f"ctx.meta_update: key {reserved!r} is reserved for the "
                    f"log record itself; choose another key"
                )
        event = {**kwargs, "event": "meta_update"}
        _log.append(self._base_dir, self._stage, self._key, event)

    def mark_partial(self, reason: str) -> None:
        """Flag this run as partial on normal exit. If called, the
        driver writes ``partial`` (not ``ok``) when the ``with`` block
        returns without exception. Last call wins.

        ``reason`` is coerced to ``str`` so a non-JSON-serializable
        object (e.g. a caught exception) cannot crash the driver's
        terminal-write path — ``"driver guarantees terminal"`` must
        hold regardless of the caller's ``reason`` shape.
        """
        self._partial_marked = True
        self._partial_reason = _safe_str(reason) if reason is not None else ""


@contextmanager
def run_stage(
    base_dir: Path | str,
    stage: str,
    key: str,
    *,
    ttl: int = 3600,
    meta_init: dict | None = None,
) -> Iterator[StageContext]:
    """Enter a stage run. The **only** public entry point to
    ``tools.pipeline``.

    Guarantees on exit:

    - Exactly one of ``start`` → ``{ok | failed | partial}`` is
      written to the log for this run.
    - The per-(stage, key) lock is released, regardless of exit path.
    - If the caller raises :class:`StagePartialExit`, the driver
      swallows it after logging ``partial``; any other exception is
      logged as ``failed`` and re-raised to the caller.

    :param base_dir: Root directory for ``.pipeline/`` bookkeeping.
    :param stage: Opaque stage name (``"wenguan"``, ``"ingest"``, …).
    :param key: Opaque per-run key (typically a slug); hashed for the
        on-disk filename.
    :param ttl: Informational TTL recorded in the lockfile; does not
        enforce a time bound on the run itself.
    :param meta_init: Dict merged into the ``start`` event's
        ``meta_init`` field — seed values for :attr:`StageState.meta`.
        Must be JSON-serializable; validated before lock acquire so
        a bad payload raises ``TypeError`` with no side effects.
    :raises StageBusyError: if a live holder owns the lock.
    :raises TypeError: if ``meta_init`` is not JSON-serializable.
    """
    base_path = Path(base_dir)
    # Validate meta_init BEFORE acquire: if it can't be converted
    # to a dict or JSON-serialized, ``_log.append`` would raise
    # mid-driver and the driver would never write a terminal event.
    # Pre-flight the check so the caller sees a clean TypeError
    # with no lock taken and no state change (Codex v0.7.7 rounds
    # 9 & 10). Two distinct failure modes to guard:
    #   - non-dict types like ``[]`` or ``"x"`` are JSON-serializable
    #     but fail at ``dict(meta_init)`` further down.
    #   - dicts containing non-JSON-serializable values (sets,
    #     classes) fail at ``json.dumps`` inside log.append.
    if meta_init is not None:
        if not isinstance(meta_init, dict):
            raise TypeError(
                f"run_stage: meta_init must be a dict, got "
                f"{type(meta_init).__name__}"
            )
        try:
            json.dumps(meta_init)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"run_stage: meta_init must be JSON-serializable ({exc})"
            ) from exc
    lock = StageLock(base_path, stage, key)
    if not lock.acquire(ttl=ttl):
        raise StageBusyError(
            f"stage={stage!r} key={key!r} is held by a live process"
        )
    try:
        _log.append(base_path, stage, key, {
            "event": "start",
            "meta_init": dict(meta_init) if meta_init else {},
        })
        ctx = StageContext(base_path, stage, key)
        try:
            yield ctx
        except StagePartialExit as exc:
            _log.append(base_path, stage, key, {
                "event": "partial",
                "reason": _safe_str(exc.reason) if exc.reason is not None else "",
            })
            # Swallowed — partial is a successful-but-incomplete exit.
        except BaseException as exc:  # noqa: BLE001 — terminal must be written for every failure mode
            _log.append(base_path, stage, key, {
                "event": "failed",
                "err": (f"{type(exc).__name__}: {_safe_str(exc)}")[:500],
            })
            raise
        else:
            if ctx._partial_marked:
                _log.append(base_path, stage, key, {
                    "event": "partial",
                    "reason": ctx._partial_reason,
                })
            else:
                _log.append(base_path, stage, key, {"event": "ok"})
    finally:
        lock.release()
