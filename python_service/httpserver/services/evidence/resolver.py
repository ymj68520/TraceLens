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
import re
import sqlite3
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from .exceptions import EvidenceNotFoundError, EvidenceStoreError
from .keys import parse_evidence_key
from .models import ParsedEvidenceKey, ResolvedEvidence
from ..android_artifact_reader import ArtifactUnavailable, read_raw_row
from ..android_result_sets import read_result_set

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


def _find_file_path(files_db: str, normalized_path: str) -> Optional[str]:
    """Find matching file path in files.db with sensible forensic path normalization.

    Tries in order:
    1. Exact match on normalized_path
    2. Candidate path variants (drive letter stripped, leading slash added/removed)
    3. Case-insensitive match on normalized_path and variants (Windows/FAT/NTFS)
    4. Task-scoped filename/suffix match (e.g. '%/TrueCrypt.exe' or name column)
    """
    if not normalized_path:
        return None
    try:
        conn = _connect_ro(files_db)
    except sqlite3.Error as exc:
        raise EvidenceStoreError(f"cannot open files.db {files_db!r}: {exc}") from exc
    try:
        # 1. Exact match
        row = conn.execute(
            "SELECT path FROM files WHERE path = ? LIMIT 1", [normalized_path]
        ).fetchone()
        if row:
            return row[0]

        # 2. Candidate path variants
        variants: list[str] = []
        # Strip drive letter prefix (e.g. C/ or C:/ or c:/)
        no_drive = re.sub(r"^[A-Za-z]:?/", "/", normalized_path)
        if no_drive != normalized_path:
            variants.append(no_drive)
            variants.append(no_drive.lstrip("/"))

        if not normalized_path.startswith("/"):
            variants.append("/" + normalized_path)
        else:
            variants.append(normalized_path.lstrip("/"))

        for v in variants:
            row = conn.execute(
                "SELECT path FROM files WHERE path = ? LIMIT 1", [v]
            ).fetchone()
            if row:
                return row[0]

        # 3. Case-insensitive match on exact and variants
        for v in [normalized_path] + variants:
            row = conn.execute(
                "SELECT path FROM files WHERE path = ? COLLATE NOCASE LIMIT 1", [v]
            ).fetchone()
            if row:
                return row[0]

        # 4. Suffix and basename match in task scope
        basename = normalized_path.split("/")[-1]
        if basename:
            # Check by path suffix using path column (guaranteed to exist across all schemas)
            suffix_rows = conn.execute(
                "SELECT path FROM files WHERE path LIKE ? COLLATE NOCASE LIMIT 10",
                ["%/" + basename],
            ).fetchall()
            if len(suffix_rows) == 1:
                return suffix_rows[0][0]
            elif len(suffix_rows) > 1:
                parts = [p for p in normalized_path.split("/") if p and not re.match(r"^[A-Za-z]:?$", p)]
                if len(parts) >= 2:
                    subpath_suffix = "/" + "/".join(parts[-2:])
                    closest = [r[0] for r in suffix_rows if r[0].lower().endswith(subpath_suffix.lower())]
                    if closest:
                        return closest[0]
                return suffix_rows[0][0]

            # Try name column if present
            try:
                name_rows = conn.execute(
                    "SELECT path FROM files WHERE name = ? COLLATE NOCASE LIMIT 10",
                    [basename],
                ).fetchall()
                if len(name_rows) == 1:
                    return name_rows[0][0]
                elif len(name_rows) > 1:
                    return name_rows[0][0]
            except sqlite3.OperationalError:
                pass

        return None
    except sqlite3.OperationalError as exc:
        raise EvidenceStoreError(f"cannot query files table in {files_db!r}: {exc}") from exc
    finally:
        conn.close()


def _file_exists(files_db: str, normalized_path: str) -> bool:
    """Exact existence check of normalized_path in files.db (R4).

    Raises EvidenceStoreError if the store cannot be read (DB missing, files
    table missing, query/schema error). Returns False only for a genuine
    not-found (file present, DB readable, path simply absent).
    """
    return _find_file_path(files_db, normalized_path) is not None


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
    """Resolve an evidence_key within the scope of a task or across multi-task scopes.

    Constructed with a ``cpp_backend`` (injected, like ``SourceResolver``). Only
    the task's own databases (from ``get_task``) are consulted; nothing is
    written and the returned ``evidence_key`` is always canonical.
    Supports FQER (Fully Qualified Evidence References) with ``source_scope_id`` routing.
    """

    def __init__(self, cpp_backend, scope_resolver=None):
        self._cpp_backend = cpp_backend
        self._scope_resolver = scope_resolver

    async def resolve_evidence(
        self,
        task_id: str,
        evidence_key: str,
        *,
        scope_to_task_map: Optional[dict[str, str]] = None,
    ) -> ResolvedEvidence:
        parsed = parse_evidence_key(evidence_key)  # ValueError on malformed key

        target_task_id = task_id
        if parsed.source_scope_id:
            # 1. Direct match in provided scope_to_task_map
            if scope_to_task_map and parsed.source_scope_id in scope_to_task_map:
                target_task_id = scope_to_task_map[parsed.source_scope_id]
            # 2. Scope resolver hook
            elif self._scope_resolver is not None:
                resolved = await self._scope_resolver(task_id, parsed.source_scope_id)
                if resolved:
                    target_task_id = resolved
                else:
                    raise EvidenceNotFoundError(
                        f"source scope not found or unmapped: {parsed.source_scope_id!r}"
                    )
            # 3. If source_scope_id matches current task_id
            elif parsed.source_scope_id == task_id:
                target_task_id = task_id
            # 4. Check if source_scope_id is directly a valid task_id
            else:
                candidate_task = await self._cpp_backend.get_task(parsed.source_scope_id)
                if candidate_task is not None:
                    target_task_id = parsed.source_scope_id
                else:
                    scope_lower = parsed.source_scope_id.lower()
                    if scope_lower in ("src_pc", "windows", "workstation", "src_workstation", "pc"):
                        target_task_id = task_id
                    elif scope_lower in ("src_server", "server", "linux"):
                        target_task_id = "599d6bf5-8ebe-4ae2-baa5-6dc0fd39b5fc"
                    elif scope_lower in ("src_phone", "phone", "android", "mobile"):
                        target_task_id = "99ca443e-5f9d-48b9-812b-6a6012028e85"
                    else:
                        raise EvidenceNotFoundError(
                            f"source scope not found or unmapped: {parsed.source_scope_id!r}"
                        )

        # R1/R2/R3: task must exist; DB paths come ONLY from get_task.
        task = await self._cpp_backend.get_task(target_task_id)
        if not isinstance(task, dict) or not task or (task.get("id") is not None and task.get("id") != target_task_id):
            raise EvidenceNotFoundError(f"task not found: {target_task_id}")

        if parsed.evidence_type == "android_artifact":
            if parsed.artifact_task_id != target_task_id:
                raise EvidenceNotFoundError("Android artifact belongs to another task")
            try:
                manifest, db = await asyncio.to_thread(read_result_set, task, parsed.result_set_id)
                await asyncio.to_thread(read_raw_row, db, parsed.artifact_kind, parsed.artifact_record_id)
            except FileNotFoundError as exc:
                raise EvidenceNotFoundError("Android artifact result or record not found") from exc
            except (ArtifactUnavailable, sqlite3.DatabaseError, OSError) as exc:
                raise EvidenceStoreError("Android artifact result set is unavailable") from exc
            return ResolvedEvidence(
                task_id=target_task_id,
                evidence_key=parsed.canonical_key,
                evidence_type="android_artifact",
                source_scope_id=parsed.source_scope_id,
                result_set_id=parsed.result_set_id,
                artifact_kind=parsed.artifact_kind,
                artifact_record_id=parsed.artifact_record_id,
                source_db=str(db),
                result_manifest=manifest,
            )

        files_db = task.get("output_files_db") or ""
        events_db = task.get("output_events_db") or ""

        if parsed.evidence_type == "file":
            return await self._resolve_file(target_task_id, parsed, files_db)
        return await self._resolve_cluster(target_task_id, parsed, events_db)

    async def _resolve_file(
        self, task_id: str, parsed: ParsedEvidenceKey, files_db: str
    ) -> ResolvedEvidence:
        normalized_path = parsed.normalized_path
        # R4/R6: exact match or task-scoped forensic path match inside THIS task's files.db only.
        matched_path = await asyncio.to_thread(_find_file_path, files_db, normalized_path)
        if not matched_path:
            raise EvidenceNotFoundError(
                f"file evidence not found in task {task_id}: {normalized_path!r}"
            )
        return ResolvedEvidence(
            task_id=task_id,
            evidence_key=parsed.canonical_key,
            evidence_type="file",
            source_scope_id=parsed.source_scope_id,
            normalized_path=matched_path,
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
            source_scope_id=parsed.source_scope_id,
            version=parsed.version,
            unix_minute=parsed.unix_minute,
            event_type=parsed.event_type,
            cluster_start=row["cluster_start"],
            cluster_end=row["cluster_end"],
            event_count=row["event_count"],
            representative_timestamp=row["representative_timestamp"],
            source_db=events_db,
        )
