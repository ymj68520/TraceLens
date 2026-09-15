"""Cluster-analysis schema for a task's ``_events.db`` (SPEC: event-cluster-analysis-redesign §3).

The statements here are the canonical Python copy of the DDL. The C++ side
keeps a verbatim copy (see TimelineRoutes.cpp); the golden tests assert the two
stays in lockstep. All statements are idempotent — safe to run on every entry
into a code path that reads or writes these tables.

Nothing in this module ever rewrites existing rows: ``event_cluster_analyses``
is append-only (the sole permitted UPDATE is ``ingested_at``), and this module
only creates tables/indexes.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Keep verbatim in sync with the C++ copy (golden-tested via sqlite_master).
CLUSTER_ANALYSIS_DDL: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS event_cluster_analyses (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id              TEXT    NOT NULL,
        bucket_epoch_offset  INTEGER NOT NULL DEFAULT 0,
        bucket_seconds       INTEGER NOT NULL,
        bucket_index         INTEGER NOT NULL,
        event_type           TEXT    NOT NULL,
        parent_directory     TEXT    NOT NULL,
        member_count         INTEGER NOT NULL,
        member_min_id        INTEGER NOT NULL,
        member_max_id        INTEGER NOT NULL,
        members_hash         TEXT    NOT NULL,
        summary              TEXT    NOT NULL DEFAULT '',
        description          TEXT    NOT NULL DEFAULT '',
        keywords             TEXT    NOT NULL DEFAULT '',
        model                TEXT    NOT NULL DEFAULT '',
        trigger_source       TEXT    NOT NULL,
        analysis_id_upstream INTEGER,
        created_at           INTEGER NOT NULL,
        ingested_at          INTEGER
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_eca_coord
        ON event_cluster_analyses(task_id, bucket_epoch_offset, bucket_seconds,
                                  bucket_index, event_type, parent_directory)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_eca_task_time
        ON event_cluster_analyses(task_id, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS cluster_analysis_runs (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id             TEXT    NOT NULL,
        trigger_source      TEXT    NOT NULL,
        bucket_seconds      INTEGER,
        bucket_epoch_offset INTEGER NOT NULL DEFAULT 0,
        budget              INTEGER,
        status              TEXT    NOT NULL DEFAULT 'running',
        cluster_total       INTEGER,
        cluster_failed      INTEGER,
        map_calls           INTEGER,
        reduce_calls        INTEGER,
        model               TEXT,
        started_at          INTEGER NOT NULL,
        finished_at         INTEGER,
        detail              TEXT    NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_car_task
        ON cluster_analysis_runs(task_id, started_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
]

BUCKET_EPOCH_OFFSET_META_KEY = "bucket_epoch_offset"


def ensure_cluster_analysis_schema(events_db: str) -> None:
    """Idempotently create the cluster-analysis tables in ``events_db``."""
    with sqlite3.connect(events_db, timeout=10) as conn:
        for statement in CLUSTER_ANALYSIS_DDL:
            conn.execute(statement)
        conn.commit()


def read_bucket_epoch_offset(events_db: str) -> int:
    """Resolve the task's window-alignment offset; 0 when absent/invalid.

    Legacy databases predate ``analysis_meta`` and legitimately resolve to 0
    (UTC-aligned windows) — the same value the SQL used before offsets existed.
    """
    try:
        with sqlite3.connect(f"file:{events_db}?mode=ro", uri=True, timeout=10) as conn:
            row = conn.execute(
                "SELECT value FROM analysis_meta WHERE key = ?",
                (BUCKET_EPOCH_OFFSET_META_KEY,),
            ).fetchone()
    except sqlite3.Error:
        return 0
    if not row:
        return 0
    try:
        offset = int(row[0])
    except (TypeError, ValueError):
        return 0
    return offset if 0 <= offset < 86400 else 0


def mark_analysis_ingested(events_db: str, analysis_ids: Sequence[int], when: int | None = None) -> int:
    """Record successful Graphiti ingestion for analysis rows (SPEC §9).

    The only UPDATE ever permitted on ``event_cluster_analyses``. Returns the
    number of rows transitioned from NULL to the ingestion timestamp; already
    ingested rows are skipped, so retries stay idempotent.
    """
    ids = sorted({int(value) for value in analysis_ids})
    if not ids:
        return 0
    import time as _time

    timestamp = int(when if when is not None else _time.time())
    placeholders = ", ".join("?" for _ in ids)
    with sqlite3.connect(events_db, timeout=10) as conn:
        cursor = conn.execute(
            f"UPDATE event_cluster_analyses SET ingested_at = ? "
            f"WHERE ingested_at IS NULL AND id IN ({placeholders})",
            (timestamp, *ids),
        )
        conn.commit()
        return cursor.rowcount


def find_latest_analysis(
    events_db: str,
    bucket_epoch_offset: int,
    bucket_seconds: int,
    bucket_index: int,
    event_type: str,
    parent_directory: str,
) -> Optional[Dict[str, Any]]:
    """Latest analysis record for a cluster coordinate, or None (SPEC §7)."""
    with sqlite3.connect(events_db, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM event_cluster_analyses "
            "WHERE bucket_epoch_offset=? AND bucket_seconds=? AND bucket_index=? "
            "AND event_type=? AND parent_directory=? "
            "ORDER BY id DESC LIMIT 1",
            (bucket_epoch_offset, bucket_seconds, bucket_index, event_type, parent_directory),
        ).fetchone()
    return dict(row) if row else None


def create_analysis_run(
    events_db: str,
    task_id: str,
    trigger_source: str,
    bucket_seconds: Optional[int],
    bucket_epoch_offset: int,
    budget: Optional[int],
) -> int:
    """Open a ``cluster_analysis_runs`` row (status=running); returns its id."""
    import time as _time

    with sqlite3.connect(events_db, timeout=10) as conn:
        cursor = conn.execute(
            "INSERT INTO cluster_analysis_runs (task_id, trigger_source, bucket_seconds, "
            "bucket_epoch_offset, budget, status, started_at) VALUES (?, ?, ?, ?, ?, 'running', ?)",
            (task_id, trigger_source, bucket_seconds, bucket_epoch_offset, budget, int(_time.time())),
        )
        conn.commit()
        return cursor.lastrowid


def finalize_analysis_run(
    events_db: str,
    run_id: int,
    status: str,
    cluster_total: int,
    cluster_failed: int,
    map_calls: int,
    reduce_calls: int,
    model: str = "",
    detail: str = "{}",
) -> None:
    """Close a run row with final statistics (SPEC §3.1)."""
    import json as _json
    import time as _time

    with sqlite3.connect(events_db, timeout=10) as conn:
        conn.execute(
            "UPDATE cluster_analysis_runs SET status=?, cluster_total=?, cluster_failed=?, "
            "map_calls=?, reduce_calls=?, model=?, finished_at=?, detail=? WHERE id=?",
            (
                status, cluster_total, cluster_failed, map_calls, reduce_calls, model,
                int(_time.time()), detail if isinstance(detail, str) else _json.dumps(detail),
                run_id,
            ),
        )
        conn.commit()


def members_fingerprint(member_ids: Sequence[int]) -> Dict[str, object]:
    """Count/min/max trio (SQL-computable) plus sha256 hash (strong check)."""
    ids = sorted(int(value) for value in member_ids)
    if not ids:
        raise ValueError("members_fingerprint requires at least one member id")
    joined = ",".join(str(value) for value in ids)
    return {
        "member_count": len(ids),
        "member_min_id": ids[0],
        "member_max_id": ids[-1],
        "members_hash": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
    }


__all__ = [
    "BUCKET_EPOCH_OFFSET_META_KEY",
    "CLUSTER_ANALYSIS_DDL",
    "ensure_cluster_analysis_schema",
    "mark_analysis_ingested",
    "members_fingerprint",
    "read_bucket_epoch_offset",
]
