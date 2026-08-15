"""Snapshot acquisition: read the trusted source DB at capture time (Phase C4a).

Both file and cluster snapshots are acquired by re-reading the task's source
database (mode=ro) at the moment of capture, so a Snapshot always reflects
"source state at capture time" (symmetric for file/cluster). No LLM is ever
invoked; missing fields stay NULL. The candidate is fully built OUTSIDE the
investigation write transaction.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from ..evidence.models import ResolvedEvidence
from .models import ClusterSnapshotPayload, FileSnapshotPayload, SnapshotCandidate

logger = logging.getLogger(__name__)


def _connect_ro(path: str) -> sqlite3.Connection:
    """Open a read-only sqlite connection (mirrors evidence._connect_ro)."""
    candidate = Path(path)
    if not candidate.is_file():
        raise EvidenceStoreError(f"source database file not found: {path!r}")
    uri = f"file:{quote(str(candidate.resolve()), safe='/')}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10)


def canonical_json(payload) -> str:
    """Deterministic JSON serialization (S8)."""
    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


_FILE_COLUMNS = (
    "path, name, extension, category, type, size, mtime, ctime, is_deleted, md5, "
    "llm_summary, llm_description, llm_keywords, llm_analyzed_at, llm_model_used, "
    "scene_type, scene_priority, scene_relevant"
)


def _acquire_file(resolved: ResolvedEvidence) -> FileSnapshotPayload:
    try:
        conn = _connect_ro(resolved.source_db)
    except sqlite3.Error as exc:
        raise EvidenceStoreError(f"cannot open files.db {resolved.source_db!r}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            f"SELECT {_FILE_COLUMNS} FROM files WHERE path = ?",
            [resolved.normalized_path],
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise EvidenceStoreError(f"cannot query files table: {exc}") from exc
    finally:
        conn.close()
    if row is None:
        raise EvidenceNotFoundError(
            f"file evidence not found in task {resolved.task_id}: {resolved.normalized_path!r}"
        )
    return FileSnapshotPayload(
        normalized_path=row["path"],
        name=row["name"],
        extension=row["extension"],
        category=row["category"],
        type=row["type"],
        size=row["size"],
        md5=row["md5"],
        mtime=row["mtime"],
        ctime=row["ctime"],
        is_deleted=row["is_deleted"],
        initial_summary=row["llm_summary"],
        initial_description=row["llm_description"],
        initial_keywords=row["llm_keywords"],
        initial_model=row["llm_model_used"],
        initial_analyzed_at=row["llm_analyzed_at"],
        scene_type=row["scene_type"],
        scene_priority=row["scene_priority"],
        scene_relevant=row["scene_relevant"],
    )


def _acquire_cluster(resolved: ResolvedEvidence) -> ClusterSnapshotPayload:
    try:
        conn = _connect_ro(resolved.source_db)
    except sqlite3.Error as exc:
        raise EvidenceStoreError(f"cannot open events.db {resolved.source_db!r}: {exc}") from exc
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
            [resolved.unix_minute, resolved.event_type],
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise EvidenceStoreError(f"cannot query events table: {exc}") from exc
    finally:
        conn.close()
    if row is None:
        raise EvidenceNotFoundError(
            f"cluster evidence not found in task {resolved.task_id}: "
            f"(unix_minute={resolved.unix_minute}, event_type={resolved.event_type!r})"
        )
    return ClusterSnapshotPayload(
        unix_minute=resolved.unix_minute,
        event_type=resolved.event_type,
        cluster_start=row["cluster_start"],
        cluster_end=row["cluster_end"],
        event_count=row["event_count"],
        representative_timestamp=row["representative_timestamp"],
        # S7: no deterministic cluster-level AI value at 2-part granularity
        initial_summary=None,
        initial_description=None,
        initial_keywords=None,
    )


def build_snapshot_candidate(resolved: ResolvedEvidence) -> SnapshotCandidate:
    """Acquire current source state and build a complete, immutable candidate."""
    if resolved.evidence_type == "file":
        payload = _acquire_file(resolved)
        return SnapshotCandidate(
            task_id=resolved.task_id,
            evidence_key=resolved.evidence_key,
            evidence_type="file",
            captured_at=int(time.time()),
            payload=payload,
            normalized_path=payload.normalized_path,
        )
    payload = _acquire_cluster(resolved)
    return SnapshotCandidate(
        task_id=resolved.task_id,
        evidence_key=resolved.evidence_key,
        evidence_type="cluster",
        captured_at=int(time.time()),
        payload=payload,
        unix_minute=payload.unix_minute,
        event_type=payload.event_type,
    )
