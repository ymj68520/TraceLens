"""Task-scoped path resolution for investigation.db (Phase C4a).

Derives the investigation.db path ONLY from trusted server-side task database
paths returned by ``cpp_backend.get_task``. Never accepts a client-supplied
path. Fail-closed: no trusted path, or inconsistent directories, -> error
(never silently produces ``./investigation.db``).
"""

from __future__ import annotations

from pathlib import Path

from ..evidence.exceptions import EvidenceStoreError


def investigation_db_path_for_task(task: dict) -> Path:
    """Return the investigation.db path for a task.

    Uses whichever trusted DB paths are present (files.db, events.db or raw.db);
    they must agree on the parent directory. ``resolve(strict=False)`` normalizes
    syntactic differences (e.g. ``data/tasks/A`` vs ``./data/tasks/A``).
    """
    if isinstance(task, str):
        raise EvidenceStoreError(
            f"expected task dict, got task_id string: {task!r}. Call cpp_backend.get_task first."
        )
    if not isinstance(task, dict):
        raise EvidenceStoreError(
            f"expected task dict from cpp_backend.get_task, got {type(task).__name__}"
        )
    parents = []
    files_db = task.get("output_files_db")
    events_db = task.get("output_events_db")
    raw_db = task.get("output_raw_db")
    if files_db:
        parents.append(Path(files_db).resolve(strict=False).parent)
    if events_db:
        parents.append(Path(events_db).resolve(strict=False).parent)
    if raw_db:
        parents.append(Path(raw_db).resolve(strict=False).parent)

    if not parents:
        raise EvidenceStoreError("task has no trusted database path")
    if len(set(parents)) != 1:
        raise EvidenceStoreError(
            f"task database directories are inconsistent: {parents!r}"
        )
    return parents[0] / "investigation.db"
