"""Task-owned store/path resolution for HTTP task mode (Phase D2b).

The task record returned by ``cpp_backend.get_task(task_id)`` is the ONLY
authority for which databases and directories belong to a task. Client
request fields (``files_db_path``, conversion input/output dirs, ...) are
non-authoritative: at most they may be exact-validated against the trusted
resolution, never used to pick the target.

Design notes:
- Reuses the ``investigation/paths.py`` discipline: trusted DB paths only,
  ``resolve(strict=False)`` for syntactic normalization, fail-closed errors.
- ``validate_legacy_db_path`` compares *resolved* targets exactly. No
  basename / suffix / parent / case-insensitive matching.
- Workspace containment is component-aware (``Path.relative_to`` on resolved
  paths), never ``str.startswith``; sibling prefixes (``/t/a`` vs ``/t/abc``)
  are rejected.
- The internal extraction root (``<tempdir>/forensics_llm_extract``) mirrors
  the C++ ``LLMAnalysisService::resolveFileForAnalysis`` scratch directory —
  the shared internal contract for files the C++ pipeline extracts before
  asking this service to convert them.
- Evidence identity (``normalize_evidence_path``) is a DIFFERENT semantic
  layer and is deliberately not used here.

This module is a small Facade, not a repository: no caching, no writes.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import quote

TASK_NOT_FOUND = "task_not_found"
TASK_STORE_UNAVAILABLE = "task_store_unavailable"
PATH_MISMATCH = "path_mismatch"
PATH_OUTSIDE_WORKSPACE = "path_outside_workspace"
INPUT_OUTPUT_OVERLAP = "input_output_overlap"


class TaskStoreError(Exception):
    """Typed task-store resolution failure (``code`` is a stable machine code)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _get_service_manager():
    from . import get_service_manager

    return get_service_manager()


async def get_task_record(task_id: str) -> dict:
    """Return the trusted task record or raise ``task_not_found``."""
    if not task_id or not str(task_id).strip():
        raise TaskStoreError(TASK_NOT_FOUND, "task_id is required")
    service_manager = _get_service_manager()
    task = await service_manager.cpp_backend.get_task(str(task_id))
    if not task:
        raise TaskStoreError(TASK_NOT_FOUND, "task not found")
    return task


async def resolve_task_files_db(task_id: str) -> Path:
    """Resolve the task-owned ``_files.db`` path (the only persistence target)."""
    task = await get_task_record(task_id)
    return files_db_from_record(task)


def files_db_from_record(task: dict) -> Path:
    files_db = task.get("output_files_db") or task.get("output_files_db_path")
    if not files_db:
        raise TaskStoreError(
            TASK_STORE_UNAVAILABLE, "task has no files database"
        )
    return Path(str(files_db))


async def resolve_task_workspace(task_id: str) -> Path:
    """Resolve the task workspace root (the directory holding the task DBs)."""
    task = await get_task_record(task_id)
    return workspace_from_record(task)


def workspace_from_record(task: dict) -> Path:
    parents = []
    for key in ("output_files_db", "output_events_db", "output_raw_db"):
        value = task.get(key)
        if value:
            parents.append(Path(str(value)).resolve(strict=False).parent)
    if not parents:
        raise TaskStoreError(
            TASK_STORE_UNAVAILABLE, "task has no trusted database path"
        )
    if len(set(parents)) != 1:
        raise TaskStoreError(
            TASK_STORE_UNAVAILABLE, "task database directories are inconsistent"
        )
    return parents[0]


def validate_legacy_db_path(supplied_path, trusted_path) -> None:
    """Exact-validate a deprecated client-supplied DB path, if present.

    Absent/empty -> pass. Present -> both sides resolved (``strict=False``)
    and compared exactly; anything else is a contract error (fail closed,
    never rewritten to the "nearest" match).
    """
    if supplied_path is None or not str(supplied_path).strip():
        return
    resolved_supplied = Path(str(supplied_path)).resolve(strict=False)
    resolved_trusted = Path(str(trusted_path)).resolve(strict=False)
    if resolved_supplied != resolved_trusted:
        raise TaskStoreError(
            PATH_MISMATCH,
            "files_db_path does not match the task files database",
        )


def resolved_within(root, candidate) -> Path:
    """Component-aware containment: return the resolved candidate if it lives
    under ``root`` (inclusive), else raise ``path_outside_workspace``.

    Both sides are resolved first, so sibling-prefix tricks (``/t/a`` vs
    ``/t/abc``) and ``..`` segments cannot pass as children.
    """
    resolved_root = Path(str(root)).resolve(strict=False)
    resolved_candidate = Path(str(candidate)).resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise TaskStoreError(
            PATH_OUTSIDE_WORKSPACE, "path is outside the task workspace"
        ) from exc
    return resolved_candidate


def has_symlink_component(path) -> bool:
    """Return whether an existing component of ``path`` is a symlink.

    This intentionally inspects the lexical path before containment resolution;
    resolving first would erase the symlink boundary and allow an otherwise
    valid in-root path to bypass the conversion route's symlink contract.
    """
    candidate = Path(str(path))
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    current = Path(candidate.anchor)
    for component in candidate.parts[1:]:
        current = current / component
        if current.is_symlink():
            return True
    return False


def internal_extract_root() -> Path:
    """The C++ pipeline's shared extraction scratch directory (read anchor)."""
    return Path(tempfile.gettempdir()) / "forensics_llm_extract"


def file_known_to_task(files_db, file_path: str) -> bool:
    """Exact ``files.path`` membership check (read-only, fail-closed).

    Raises ``TaskStoreError(TASK_STORE_UNAVAILABLE)`` when the store cannot
    be opened/read; returns False only for a genuine "not a known file".
    """
    candidate = Path(str(files_db))
    if not candidate.is_file():
        raise TaskStoreError(
            TASK_STORE_UNAVAILABLE, "task files database is unavailable"
        )
    uri = f"file:{quote(str(candidate.resolve()), safe='/')}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=10)
    except sqlite3.Error as exc:
        raise TaskStoreError(
            TASK_STORE_UNAVAILABLE, "task files database is unavailable"
        ) from exc
    try:
        cur = conn.execute(
            "SELECT 1 FROM files WHERE path = ? LIMIT 1", (file_path,)
        )
        return cur.fetchone() is not None
    except sqlite3.Error as exc:
        raise TaskStoreError(
            TASK_STORE_UNAVAILABLE, "task files database is unavailable"
        ) from exc
    finally:
        conn.close()
