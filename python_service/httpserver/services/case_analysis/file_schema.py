"""File analysis schema and unified accessors (file-analysis SPEC §3).

The append-only ``file_analyses`` table is the truth source for LLM file
analysis; ``files.llm_*`` and ``file_descriptions`` are dual-write caches
consumed by the C++ HTTPServer, the report generator and Graphiti (readers
are NOT migrated). All NEW "current analysis" queries must go through the
accessors in this module — never a third ad-hoc SQL variant.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

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


LATEST_ANALYSIS_JOIN = (
    "LEFT JOIN file_analyses fa ON fa.id = ("
    " SELECT MAX(id) FROM file_analyses WHERE file_path = fa.file_path)"
)


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
