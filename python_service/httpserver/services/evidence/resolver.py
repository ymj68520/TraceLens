"""EvidenceResolver: task-scoped, fail-closed, zero-write Evidence resolution.

Invariants (see Phase C plan):
  R1 task must exist                  R5 cluster recomputed from stable identity
  R2 DB paths only from get_task      R6 never cross-task
  R3 no client db paths               R7 not found -> fail closed
  R4 file exact in files.db           R8 zero persistence side effects (mode=ro)

The resolver only ever consults the databases returned by ``get_task(task_id)``
for the given task; it never writes (read-only connections), and on any kind of
"not found" it raises instead of returning a partial/fabricated result.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from .exceptions import EvidenceNotFoundError, EvidenceStoreError
from .keys import parse_evidence_key
from .models import ParsedEvidenceKey, ResolvedEvidence

logger = logging.getLogger(__name__)


def _connect_ro(path: str) -> sqlite3.Connection:
    """Open a read-only sqlite connection (mirrors SqliteTaskReportAdapter._connect).

    Raises EvidenceStoreError if the file does not exist (fail closed; never
    creates it). This is a store-level failure, not a not-found.
    """
    candidate = Path(path)
    if not candidate.is_file():
        raise EvidenceStoreError(f"database file not found: {path!r}")
    uri = f"file:{quote(str(candidate.resolve()), safe='/')}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10)


def _file_exists(files_db: str, normalized_path: str) -> bool:
    """Exact existence check of normalized_path in files.db (R4).

    Raises EvidenceStoreError if the store cannot be read (DB missing, files
    table missing, query/schema error). Returns False only for a genuine
    not-found (file present, DB readable, path simply absent).
    """
    try:
        conn = _connect_ro(files_db)
    except sqlite3.Error as exc:
        raise EvidenceStoreError(f"cannot open files.db {files_db!r}: {exc}") from exc
    try:
        row = conn.execute(
            "SELECT 1 FROM files WHERE path = ? LIMIT 1", [normalized_path]
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError as exc:
        raise EvidenceStoreError(f"cannot query files table in {files_db!r}: {exc}") from exc
    finally:
        conn.close()


def _cluster_lookup(events_db: str, unix_minute: int, event_type: str) -> Optional[dict]:
    """Recompute the cluster for (unix_minute, event_type) from events.db (R5).

    Raises EvidenceStoreError if the store cannot be read. Returns None only when
    the store is readable but the cluster genuinely does not exist (never
    fabricated).
    """
    try:
        conn = _connect_ro(events_db)
    except sqlite3.Error as exc:
        raise EvidenceStoreError(f"cannot open events.db {events_db!r}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT MIN(timestamp) AS cluster_start,
                   MAX(timestamp) AS cluster_end,
                   COUNT(*) AS event_count,
                   MIN(timestamp) AS representative_timestamp
            FROM events
            WHERE (timestamp / 60) = ? AND event_type = ?
            GROUP BY (timestamp / 60), event_type
            """,
            [unix_minute, event_type],
        ).fetchone()
        if row is None:
            return None
        return {
            "cluster_start": row["cluster_start"],
            "cluster_end": row["cluster_end"],
            "event_count": row["event_count"],
            "representative_timestamp": row["representative_timestamp"],
        }
    except sqlite3.OperationalError as exc:
        raise EvidenceStoreError(f"cannot query events table in {events_db!r}: {exc}") from exc
    finally:
        conn.close()


class EvidenceResolver:
    """Resolve an evidence_key within the scope of a single task.

    Constructed with a ``cpp_backend`` (injected, like ``SourceResolver``). Only
    the task's own databases (from ``get_task``) are consulted; nothing is
    written and the returned ``evidence_key`` is always canonical.
    """

    def __init__(self, cpp_backend):
        self._cpp_backend = cpp_backend

    async def resolve_evidence(self, task_id: str, evidence_key: str) -> ResolvedEvidence:
        parsed = parse_evidence_key(evidence_key)  # ValueError on malformed key

        # R1/R2/R3: task must exist; DB paths come ONLY from get_task.
        task = await self._cpp_backend.get_task(task_id)
        if not task:
            raise EvidenceNotFoundError(f"task not found: {task_id}")

        files_db = task.get("output_files_db") or ""
        events_db = task.get("output_events_db") or ""

        if parsed.evidence_type == "file":
            return await self._resolve_file(task_id, parsed, files_db)
        return await self._resolve_cluster(task_id, parsed, events_db)

    async def _resolve_file(
        self, task_id: str, parsed: ParsedEvidenceKey, files_db: str
    ) -> ResolvedEvidence:
        normalized_path = parsed.normalized_path
        # R4/R6: exact match inside THIS task's files.db only.
        exists = await asyncio.to_thread(_file_exists, files_db, normalized_path)
        if not exists:
            raise EvidenceNotFoundError(
                f"file evidence not found in task {task_id}: {normalized_path!r}"
            )
        return ResolvedEvidence(
            task_id=task_id,
            evidence_key=parsed.canonical_key,
            evidence_type="file",
            normalized_path=normalized_path,
            source_db=files_db,
        )

    async def _resolve_cluster(
        self, task_id: str, parsed: ParsedEvidenceKey, events_db: str
    ) -> ResolvedEvidence:
        # R5: recompute from stable identity (unix_minute, event_type); never fabricate.
        row = await asyncio.to_thread(
            _cluster_lookup, events_db, parsed.unix_minute, parsed.event_type
        )
        if row is None:
            raise EvidenceNotFoundError(
                f"cluster evidence not found in task {task_id}: "
                f"(unix_minute={parsed.unix_minute}, event_type={parsed.event_type!r})"
            )
        return ResolvedEvidence(
            task_id=task_id,
            evidence_key=parsed.canonical_key,
            evidence_type="cluster",
            version=parsed.version,
            unix_minute=parsed.unix_minute,
            event_type=parsed.event_type,
            cluster_start=row["cluster_start"],
            cluster_end=row["cluster_end"],
            event_count=row["event_count"],
            representative_timestamp=row["representative_timestamp"],
            source_db=events_db,
        )
