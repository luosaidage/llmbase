"""Tests for tools.chunk_cache — content-hash-validated cache (v0.7.5, 议 C).

The bug this cache prevents (siwen 2026-04-20, 3 books corrupted):
chunking boundaries shifted, positional slot key stayed the same,
cache served stale output for the new content at that slot. Every
test below exercises that invariant: a content change at the same
cid MUST produce a miss.
"""

import os
import shutil
from pathlib import Path

import pytest

from tools.chunk_cache import ChunkCache


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    return tmp_path


# ─── core contract: get / put / miss ──────────────────────────────────


def test_get_unknown_cid_returns_none(cache_root):
    c = ChunkCache(cache_root)
    assert c.get("unseen", "any-hash") is None


def test_put_then_get_round_trips(cache_root):
    c = ChunkCache(cache_root)
    c.put("h3-緒論", "sha256abc", "LLM output text")
    assert c.get("h3-緒論", "sha256abc") == "LLM output text"


def test_put_preserves_utf8_content(cache_root):
    c = ChunkCache(cache_root)
    body = "夫道者，萬物之奧。善人之寶，不善人之所保。"
    c.put("cid", "h1", body)
    assert c.get("cid", "h1") == body


def test_put_accepts_empty_string(cache_root):
    """Empty output is a valid cache entry — distinguishable from miss."""
    c = ChunkCache(cache_root)
    c.put("cid", "h", "")
    assert c.get("cid", "h") == ""


def test_put_rejects_non_string(cache_root):
    c = ChunkCache(cache_root)
    with pytest.raises(TypeError):
        c.put("cid", "h", 42)


# ─── the core invariant: content-hash validation ───────────────────────


def test_same_cid_different_content_hash_is_miss(cache_root):
    """THE bug this cache exists to prevent — boundary shift invalidates
    the slot's content, cache MUST miss on the new hash."""
    c = ChunkCache(cache_root)
    c.put("chunks/05", "hash-of-old-content", "OLD LLM OUTPUT")
    # Chunking boundary moved — same slot, new content:
    assert c.get("chunks/05", "hash-of-new-content") is None
    # And the old hash still resolves (in case the pipeline rolls back):
    assert c.get("chunks/05", "hash-of-old-content") == "OLD LLM OUTPUT"


def test_different_cid_same_content_hash_isolated(cache_root):
    """Two slots happen to hold identical content: we still treat them
    as independent cache entries (different cids). Callers may choose
    to collapse via a content-addressed cid, but that's their choice."""
    c = ChunkCache(cache_root)
    c.put("slot-a", "same-hash", "output-a")
    c.put("slot-b", "same-hash", "output-b")
    assert c.get("slot-a", "same-hash") == "output-a"
    assert c.get("slot-b", "same-hash") == "output-b"


def test_overwrite_same_key(cache_root):
    """Writing twice to the same (cid, hash) is idempotent — last-wins.
    This happens when a pipeline retries after a partial failure."""
    c = ChunkCache(cache_root)
    c.put("cid", "h", "first")
    c.put("cid", "h", "second")
    assert c.get("cid", "h") == "second"


# ─── clear(cid) ───────────────────────────────────────────────────────


def test_clear_removes_all_hashes_for_cid(cache_root):
    c = ChunkCache(cache_root)
    c.put("cid-x", "hash-1", "output-1")
    c.put("cid-x", "hash-2", "output-2")
    c.put("cid-other", "hash-1", "other")
    c.clear("cid-x")
    assert c.get("cid-x", "hash-1") is None
    assert c.get("cid-x", "hash-2") is None
    # Other cids untouched:
    assert c.get("cid-other", "hash-1") == "other"


def test_clear_noop_on_unknown_cid(cache_root):
    """clear() must be idempotent — pipeline cleanup code shouldn't
    have to check existence first."""
    c = ChunkCache(cache_root)
    c.clear("never-written")  # must not raise


def test_put_after_clear_works(cache_root):
    c = ChunkCache(cache_root)
    c.put("cid", "h", "first")
    c.clear("cid")
    c.put("cid", "h", "second")
    assert c.get("cid", "h") == "second"


# ─── filesystem robustness ────────────────────────────────────────────


def test_cid_with_filesystem_unfriendly_chars(cache_root):
    """cids are sha-hashed before use, so slashes / CJK / NULs don't
    escape the cache dir or collide with FS semantics."""
    c = ChunkCache(cache_root)
    nasty = "../../etc/passwd"
    c.put(nasty, "h", "contained")
    assert c.get(nasty, "h") == "contained"
    # The cache root must still contain the file (not /etc/):
    assert (cache_root / ".chunk_cache").is_dir()


def test_content_hash_with_special_chars(cache_root):
    c = ChunkCache(cache_root)
    c.put("cid", "hash/with/slashes", "out")
    assert c.get("cid", "hash/with/slashes") == "out"


def test_root_property_exposes_dir(cache_root):
    c = ChunkCache(cache_root)
    assert c.root == cache_root / ".chunk_cache"


def test_custom_subdir(cache_root):
    c = ChunkCache(cache_root, subdir=".custom-cache")
    c.put("cid", "h", "x")
    assert (cache_root / ".custom-cache").is_dir()
    assert not (cache_root / ".chunk_cache").exists()


def test_cid_and_content_hashes_use_full_sha256(cache_root):
    """Codex MEDIUM (v0.7.5): truncated hashes bound collision probability
    at the ~10^9 scale for cid (16-hex) and ~10^19 for content (32-hex).
    Full sha256 (64 hex) drives collision effectively to zero. Structural
    check — a regression from full to truncated would re-open the window."""
    c = ChunkCache(cache_root)
    c.put("any-cid", "any-hash", "out")
    # Walk into the on-disk layout and confirm the path segments are
    # full-length sha256 prefixes (64 hex chars each).
    entries = list((cache_root / ".chunk_cache").rglob("*.md"))
    assert len(entries) == 1
    cid_dir_name = entries[0].parent.name
    content_file_stem = entries[0].stem
    assert len(cid_dir_name) == 64 and all(ch in "0123456789abcdef" for ch in cid_dir_name)
    assert len(content_file_stem) == 64 and all(ch in "0123456789abcdef" for ch in content_file_stem)


def test_clear_propagates_non_enoent_errors(cache_root, monkeypatch):
    """Codex MEDIUM (v0.7.5): ``shutil.rmtree(..., ignore_errors=True)``
    silently swallowed real I/O failures, leaving stale entries behind
    while the caller believed the cache had been cleared. A permission
    / disk failure must surface so the caller can react."""
    c = ChunkCache(cache_root)
    c.put("cid", "h", "x")

    def boom(path, *args, **kwargs):
        raise PermissionError("simulated EACCES")

    monkeypatch.setattr(shutil, "rmtree", boom)
    with pytest.raises(PermissionError):
        c.clear("cid")


# ─── atomic write: no partial files visible under failure ─────────────


def test_atomic_write_no_partial_on_exception(cache_root, monkeypatch):
    """Simulate a mid-write failure: the previous cached value must
    still be fully readable after the failed put (no torn file)."""
    c = ChunkCache(cache_root)
    c.put("cid", "h", "stable-value")

    from tools import atomic
    original = atomic.atomic_write_text

    def boom(path, content):
        raise IOError("disk full (simulated)")

    monkeypatch.setattr("tools.chunk_cache.atomic_write_text", boom)
    with pytest.raises(IOError):
        c.put("cid", "h", "would-corrupt")
    # Previous value still intact:
    assert c.get("cid", "h") == "stable-value"

    # Restore for any subsequent tests in the same session:
    monkeypatch.setattr("tools.chunk_cache.atomic_write_text", original)


def test_no_tmp_leak_after_successful_put(cache_root):
    """atomic_write_text creates a tempfile in the target dir — verify
    it doesn't remain after a successful write."""
    c = ChunkCache(cache_root)
    c.put("cid", "h", "content")
    # Walk the cache dir: only the .md file should remain.
    tmp_leaks = [
        p for p in (cache_root / ".chunk_cache").rglob("*")
        if p.suffix == ".tmp" or p.name.startswith(".")
    ]
    assert tmp_leaks == [], f"leaked tempfiles: {tmp_leaks}"


# ─── end-to-end: simulated wenguan chunking-boundary shift ────────────


def test_boundary_shift_scenario(cache_root):
    """The concrete failure mode from siwen 2026-04-20: a chunk's
    content changes (splitter rule tuned), but the positional cid
    stays the same. Old cache entry must NOT be served."""
    import hashlib

    def h(s: str) -> str:
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    c = ChunkCache(cache_root)
    # Run 1: splitter produces chunk-05 with content A.
    content_a = "第五章 甲乙丙。..."
    output_a = "LLM summary of A"
    c.put("chunks/05", h(content_a), output_a)
    assert c.get("chunks/05", h(content_a)) == output_a

    # Run 2: splitter tuned — chunk-05 now holds content B (boundary moved).
    content_b = "第五章 戊己庚。..."
    assert c.get("chunks/05", h(content_b)) is None, \
        "boundary-shift bug: stale output served for new content"

    # After recompute for run 2, both eras coexist (cache is
    # additive; the caller is free to clear if disk pressure matters).
    output_b = "LLM summary of B"
    c.put("chunks/05", h(content_b), output_b)
    assert c.get("chunks/05", h(content_b)) == output_b
    assert c.get("chunks/05", h(content_a)) == output_a
