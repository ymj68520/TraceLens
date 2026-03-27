"""
Database Utilities Module — Shared database operations for case analysis.

This module provides common database helper functions used across
the case analysis package.
"""

import json
import logging
import sqlite3
import time
from typing import List, Optional

logger = logging.getLogger(__name__)


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
