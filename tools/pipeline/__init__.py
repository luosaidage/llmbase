"""Pipeline primitives for multi-stage LLM workflows — 议 D (v0.7.7).

Three laws:

- **Log is truth.** Append-only JSONL, one per ``(stage, key)``.
- **State is view.** :func:`rebuild_state` reconstructs it on demand.
- **Driver guarantees terminal.** :func:`run_stage` writes exactly one
  of ``ok`` / ``failed`` / ``partial`` on every exit, and the next
  acquire after a SIGKILL logs ``interrupted`` before breaking the
  stale lock — no run is ever stuck ``running``.

Opaque by design: stage names and keys are strings chosen by the
caller; the meta payload is an opaque dict. No DAG, no scheduling,
no retry policy — those are downstream concerns. Compose by writing a
sequence of ``with run_stage(base, name, key): ...`` blocks, each
naming its own stage.

**Single-host scope.** Mutual exclusion relies on comparing the
pidfile's ``host`` to ``socket.gethostname()`` and the pidfile's
``pid`` to ``os.kill(..., 0)``. Both checks presuppose one machine
owning the ``base_dir`` filesystem. On shared storage with multiple
writing hosts you must wrap this layer in a cross-host mutex (etcd
/ consul / advisory ``flock`` over NFSv4), otherwise a live holder
on host A is seen as stale by host B.

Siwen's 5-stage wenguan pipeline (ingest / split / wenguan /
normalize / sync) running against 62 太虛 books + 14 判教原經 is the
primary exercise target.
"""

from .driver import (
    StageBusyError,
    StageContext,
    StagePartialExit,
    run_stage,
)
from .state import RESERVED_EVENTS, StageState, rebuild_state

__all__ = [
    "run_stage",
    "StageContext",
    "StagePartialExit",
    "StageBusyError",
    "StageState",
    "rebuild_state",
    "RESERVED_EVENTS",
]
