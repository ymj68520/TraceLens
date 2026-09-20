"""File analysis schema and unified accessors (file-analysis SPEC §3).

The append-only ``file_analyses`` table is the truth source for LLM file
analysis; ``files.llm_*`` and ``file_descriptions`` are dual-write caches
consumed by the C++ HTTPServer, the report generator and Graphiti (readers
are NOT migrated). All NEW "current analysis" queries must go through the
accessors in this module — never a third ad-hoc SQL variant.
"""

import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...path_utils import normalize_evidence_path

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS file_analyses (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id              TEXT    NOT NULL,
    file_path            TEXT    NOT NULL,
    md5                  TEXT    NOT NULL DEFAULT '',
    summary              TEXT    NOT NULL DEFAULT '',
    description          TEXT    NOT NULL DEFAULT '',
    keywords             TEXT    NOT NULL DEFAULT '',
    model                TEXT    NOT NULL DEFAULT '',
    extraction_method    TEXT    NOT NULL DEFAULT '',
    trigger_source       TEXT    NOT NULL,
    analysis_id_upstream INTEGER,
    created_at           INTEGER NOT NULL,
    ingested_at          INTEGER
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_fa_path     ON file_analyses(file_path, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_fa_task     ON file_analyses(task_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_fa_path_md5 ON file_analyses(file_path, md5)",
)


def ensure_file_analysis_schema(db_path: str) -> None:
    """Idempotently create the append-only truth table and its indexes."""
    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.execute(DDL)
        for stmt in INDEXES:
            conn.execute(stmt)


def latest_analysis(db_path: str, file_path: str) -> Optional[Dict[str, Any]]:
    """The newest analysis record for a file (None when never analyzed).

    ``file_path`` is canonicalized with ``normalize_evidence_path`` so the
    lookup matches the identity persisted by ``persist_to_files_db``. A
    missing table (pre-Phase-2 database) counts as never analyzed.
    """
    if not db_path or not Path(db_path).exists():
        return None
    norm = normalize_evidence_path(file_path)
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM file_analyses WHERE file_path = ? "
                "ORDER BY id DESC LIMIT 1",
                (norm,),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return dict(row) if row else None


def latest_analyses_batch(db_path: str, file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """Batched :func:`latest_analysis`: {canonical_path: newest record}.

    One connection for the whole batch (chunked IN clauses) instead of one
    connect per path — the analysis-record list endpoint pays this once per
    page, not once per member file. A missing table (pre-Phase-2 database)
    yields {} like the single-path variant.
    """
    if not db_path or not Path(db_path).exists() or not file_paths:
        return {}
    wanted = [p for p in (normalize_evidence_path(p) for p in file_paths) if p]
    latest: Dict[str, Dict[str, Any]] = {}
    if not wanted:
        return latest
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            for i in range(0, len(wanted), 400):
                chunk = wanted[i:i + 400]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT * FROM file_analyses WHERE file_path IN ({placeholders}) "
                    "ORDER BY id DESC",
                    chunk,
                ).fetchall()
                # Rows arrive newest-first, so the first row seen per path wins.
                for row in rows:
                    record = dict(row)
                    latest.setdefault(record.get("file_path") or "", record)
    except sqlite3.OperationalError:
        return {}
    return latest


LATEST_ANALYSIS_JOIN = (
    "LEFT JOIN file_analyses fa ON fa.id = ("
    " SELECT MAX(id) FROM file_analyses WHERE file_path = fa.file_path)"
)


def mark_analyses_ingested(db_path: str, analysis_ids: List[int]) -> int:
    """Graphiti ingestion state machine (SPEC §9-L3): the ONLY allowed UPDATE
    on the append-only table — ``ingested_at`` NULL → timestamp, idempotent
    (already-marked rows are skipped). Returns the rows marked."""
    if not db_path or not Path(db_path).exists() or not analysis_ids:
        return 0
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            placeholders = ",".join("?" for _ in analysis_ids)
            cur = conn.execute(
                f"UPDATE file_analyses SET ingested_at = ? "
                f"WHERE ingested_at IS NULL AND id IN ({placeholders})",
                (int(time.time()), *analysis_ids),
            )
            conn.commit()
            return cur.rowcount
    except sqlite3.OperationalError:
        return 0


def list_analyses(
    db_path: str,
    task_id: str,
    file_path: Optional[str] = None,
    limit: int = 200,
) -> list:
    """Version chain for a file (or all records of a task), newest first."""
    if not db_path or not Path(db_path).exists():
        return []
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            if file_path:
                rows = conn.execute(
                    "SELECT * FROM file_analyses WHERE task_id = ? AND file_path = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (task_id, normalize_evidence_path(file_path), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM file_analyses WHERE task_id = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (task_id, limit),
                ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(row) for row in rows]


def file_forensic_time(db_path: str, file_path: str) -> Optional[datetime]:
    """The file's forensic time (mtime, fallback ctime) as naive datetime.

    Feeds episode reference_time (SPEC D12). None when the file row is
    absent or its timestamps are unusable — callers fall back to now().
    """
    if not db_path or not Path(db_path).exists():
        return None
    norm = normalize_evidence_path(file_path)
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            row = conn.execute(
                "SELECT mtime, ctime FROM files WHERE path = ? LIMIT 1", (norm,)
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    ts = row[0] or row[1]
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts))
    except (OverflowError, OSError, ValueError):
        return None


def analysis_stats(db_path: str) -> Dict[str, Any]:
    """Counts behind the estimate endpoint (SPEC §8.1).

    total / analyzed (files with at least one record) / pending / stale
    (latest record's md5 differs from the files row).
    """
    if not db_path or not Path(db_path).exists():
        return {"total": 0, "analyzed": 0, "pending": 0, "stale": 0}
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            total, analyzed = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(EXISTS("
                "  SELECT 1 FROM file_analyses fa WHERE fa.file_path = f.path)), 0) "
                "FROM files f"
            ).fetchone()
            stale = conn.execute(
                "SELECT COUNT(*) FROM file_analyses fa "
                "JOIN files f ON f.path = fa.file_path "
                "WHERE fa.id = (SELECT MAX(id) FROM file_analyses "
                "               WHERE file_path = fa.file_path) "
                "AND COALESCE(fa.md5, '') != COALESCE(f.md5, '')"
            ).fetchone()[0]
    except sqlite3.OperationalError:
        # analyses table absent (pre-Phase-2 database): nothing analyzed yet.
        return {"total": 0, "analyzed": 0, "pending": 0, "stale": 0}
    analyzed = analyzed or 0
    return {
        "total": total,
        "analyzed": analyzed,
        "pending": max(total - analyzed, 0),
        "stale": stale,
    }
