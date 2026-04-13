"""
Database Utilities Module — Shared database operations for case analysis.

This module provides common database helper functions used across
the case analysis package.
"""

import json
import logging
import sqlite3
import time
from typing import List, Optional, Dict, Any
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class TaskAnalysisState(Enum):
    """任务分析状态枚举"""
    PENDING = "pending"           # 待分析
    ANALYZED = "analyzed"         # 已分析
    NEEDS_UPDATE = "needs_update" # 需要更新
    FAILED = "failed"             # 分析失败


def ensure_file_descriptions_schema(conn: sqlite3.Connection):
    """Ensure file_descriptions table and its columns exist."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS file_descriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE,
            description TEXT,
            summary TEXT,
            keywords TEXT,
            model_used TEXT,
            is_relevant INTEGER DEFAULT 1,
            created_at INTEGER
        )
    """)
    conn.commit()


def ensure_case_analysis_table(db_path: str):
    """Create case_analysis table if it doesn't exist."""
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS case_analysis (
                    task_id TEXT PRIMARY KEY,
                    case_description TEXT,
                    filtered_files TEXT,
                    case_report TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                )
            """)
            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to create case_analysis table: {e}")


def persist_filtered_files(db_path: str, task_id: str, filtered_files: List[str]):
    """Persist the filtered file list to database using the correct task_id."""
    ensure_case_analysis_table(db_path)
    now = int(time.time())
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO case_analysis
                    (task_id, filtered_files, created_at, updated_at)
                VALUES
                    (?, ?, ?, ?)
            """, (task_id, json.dumps(filtered_files), now, now))
            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to persist filtered files for task {task_id}: {e}")


def persist_case_report(db_path: str, task_id: str, case_description: str, report: str):
    """Persist the case report to database."""
    ensure_case_analysis_table(db_path)
    now = int(time.time())
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO case_analysis
                    (task_id, case_description, filtered_files, case_report, created_at, updated_at)
                VALUES
                    (?, ?, COALESCE(
                        (SELECT filtered_files FROM case_analysis WHERE task_id = ?),
                        '[]'
                    ), ?, ?, ?)
            """, (task_id, case_description, task_id, report, now, now))
            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to persist case report: {e}")


def get_case_report_from_db(db_path: str, task_id: str) -> Optional[dict]:
    """Retrieve a persisted case report from the database."""
    if not db_path:
        return None

    try:
        from pathlib import Path
        if not Path(db_path).exists():
            return None

        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM case_analysis WHERE task_id = ?",
                (task_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "task_id": row["task_id"],
                    "case_description": row["case_description"],
                    "filtered_files": json.loads(row["filtered_files"] or "[]"),
                    "case_report": row["case_report"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
    except Exception as e:
        logger.warning(f"Failed to retrieve case report: {e}")
    return None


def get_filtered_files_from_db(db_path: str, task_id: str = "") -> List[str]:
    """Retrieve the list of case-relevant files from database."""
    if not db_path:
        return []

    try:
        from pathlib import Path
        if not Path(db_path).exists():
            return []

        with sqlite3.connect(db_path, timeout=10) as conn:
            cur = conn.cursor()

            # Ensure file_descriptions table exists before querying
            ensure_file_descriptions_schema(conn)

            # 1. First, get files that have been analyzed (dynamic evidence)
            # Exclude explicitly marked irrelevant files
            cur.execute("SELECT DISTINCT file_path FROM file_descriptions WHERE is_relevant IS NOT 0")
            analyzed_files = [row[0] for row in cur.fetchall()]

            # 2. Also get files from the initial filter list
            cur.execute(
                "SELECT filtered_files FROM case_analysis WHERE task_id = ?",
                (task_id,)
            )
            row = cur.fetchone()
            initial_filtered = json.loads(row[0]) if row and row[0] else []

            # Combine and deduplicate
            all_relevant = list(dict.fromkeys(analyzed_files + initial_filtered))
            return all_relevant

    except Exception as e:
        logger.warning(f"Failed to retrieve case-relevant files: {e}")
    return []


# =============================================================================
# Case Task Status - 案件任务状态跟踪
# =============================================================================

def ensure_case_task_status_table(db_path: str):
    """
    Create case_task_status table if it doesn't exist.

    This table tracks the analysis status of each task within a case,
    enabling incremental analysis by identifying which tasks have
    already been analyzed.
    """
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS case_task_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    analysis_status TEXT DEFAULT 'pending',
                    files_count INTEGER DEFAULT 0,
                    analyzed_files_count INTEGER DEFAULT 0,
                    last_analysis_time INTEGER,
                    error_message TEXT,
                    created_at INTEGER,
                    updated_at INTEGER,
                    UNIQUE(case_id, task_id)
                )
            """)
            # Create index for faster queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_case_task_status_case_id
                ON case_task_status(case_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_case_task_status_task_id
                ON case_task_status(task_id)
            """)
            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to create case_task_status table: {e}")


def update_task_analysis_status(
    db_path: str,
    case_id: str,
    task_id: str,
    status: str,
    files_count: int = 0,
    analyzed_files_count: int = 0,
    error_message: str = None,
) -> bool:
    """
    Update the analysis status of a task within a case.

    Args:
        db_path: Path to the case database
        case_id: Case identifier
        task_id: Task identifier
        status: One of 'pending', 'analyzed', 'needs_update', 'failed'
        files_count: Total number of files in the task
        analyzed_files_count: Number of analyzed files
        error_message: Error message if status is 'failed'

    Returns:
        True if successful, False otherwise
    """
    ensure_case_task_status_table(db_path)
    now = int(time.time())
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("""
                INSERT INTO case_task_status
                    (case_id, task_id, analysis_status, files_count,
                     analyzed_files_count, error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id, task_id) DO UPDATE SET
                    analysis_status = excluded.analysis_status,
                    files_count = excluded.files_count,
                    analyzed_files_count = excluded.analyzed_files_count,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
            """, (case_id, task_id, status, files_count,
                  analyzed_files_count, error_message, now, now))
            conn.commit()
        return True
    except Exception as e:
        logger.warning(f"Failed to update task analysis status: {e}")
        return False


def get_task_analysis_status(
    db_path: str, case_id: str, task_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get the analysis status of a specific task within a case.

    Returns:
        Dict with keys: case_id, task_id, analysis_status, files_count,
        analyzed_files_count, last_analysis_time, error_message, etc.
        Returns None if not found.
    """
    if not db_path:
        return None

    try:
        if not Path(db_path).exists():
            return None

        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM case_task_status
                WHERE case_id = ? AND task_id = ?
            """, (case_id, task_id))
            row = cur.fetchone()
            if row:
                return dict(row)
    except Exception as e:
        logger.warning(f"Failed to get task analysis status: {e}")
    return None


def get_case_all_task_status(db_path: str, case_id: str) -> List[Dict[str, Any]]:
    """
    Get all task statuses within a case.

    Returns:
        List of dicts, each containing task status information
    """
    if not db_path:
        return []

    try:
        if not Path(db_path).exists():
            return []

        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM case_task_status
                WHERE case_id = ?
                ORDER BY created_at ASC
            """, (case_id,))
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.warning(f"Failed to get case task statuses: {e}")
    return []


def get_file_description_stats(db_path: str) -> Dict[str, int]:
    """
    Get statistics about file descriptions in a database.

    Returns:
        Dict with keys: total_files, analyzed_files, relevant_files
    """
    stats = {
        "total_files": 0,
        "analyzed_files": 0,
        "relevant_files": 0
    }

    if not db_path:
        return stats

    try:
        if not Path(db_path).exists():
            return stats

        with sqlite3.connect(db_path, timeout=10) as conn:
            # Ensure table exists
            ensure_file_descriptions_schema(conn)

            cur = conn.cursor()

            # Count total files in database (from files table if available)
            try:
                cur.execute("SELECT COUNT(*) FROM files")
                stats["total_files"] = cur.fetchone()[0]
            except sqlite3.OperationalError:
                pass

            # Count analyzed files (have description)
            cur.execute("""
                SELECT COUNT(*) FROM file_descriptions
                WHERE description IS NOT NULL AND description != ''
            """)
            stats["analyzed_files"] = cur.fetchone()[0]

            # Count relevant files
            cur.execute("""
                SELECT COUNT(*) FROM file_descriptions
                WHERE is_relevant IS NOT 0
            """)
            stats["relevant_files"] = cur.fetchone()[0]

    except Exception as e:
        logger.warning(f"Failed to get file description stats: {e}")

    return stats


def get_case_db_path(case_id: str, base_dir: str = None) -> str:
    """
    Get the database path for a case.

    Args:
        case_id: Case identifier
        base_dir: Base directory for case data (default: data/cases)

    Returns:
        Path to the case database file
    """
    if base_dir is None:
        # Use default location relative to project root
        base_dir = "build/data/cases"

    case_dir = Path(base_dir) / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    return str(case_dir / f"{case_id}.db")
