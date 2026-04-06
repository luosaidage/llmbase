"""Atomic file writes — prevents corruption from concurrent/interrupted writes.

Usage:
    from .atomic import atomic_write_json

    atomic_write_json(path, data)  # temp file + rename = always consistent
"""

import json
import tempfile
from pathlib import Path


def atomic_write_json(path: Path, data: dict, ensure_ascii: bool = False):
    """Write JSON atomically using temp file + rename.

    If the process crashes mid-write, the original file is untouched.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file in same directory (same filesystem for atomic rename)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=f".{path.stem}_"
    )
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=ensure_ascii)
        # Atomic rename
        Path(tmp_path).replace(path)
    except Exception:
        # Clean up temp file on failure
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass
        raise
