"""Additive Workbench state: event review status and analyst notes.

The v7 investigation store is append-only for events, versions, evidence and
analyses. The Workbench still needs small current-state values that analysts
change interactively: the review status of an event (确认/待复核/排除) and
Analyst Notes (explicitly *not* evidence). Both live in dedicated side
tables next to the frozen v7 schema; this module never reads or writes any
v7 table.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ALLOWED_EVENT_REVIEW_STATUSES = ("draft", "review_pending", "confirmed", "rejected")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workbench_event_review (
    task_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    review_status TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (task_id, event_id)
);
CREATE TABLE IF NOT EXISTS workbench_analyst_notes (
    task_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_key TEXT NOT NULL,
    content TEXT NOT NULL,
    author TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (task_id, target_type, target_key)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    return conn


def _row_to_note(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "target_type": row["target_type"],
        "target_key": row["target_key"],
        "content": row["content"],
        "author": row["author"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def set_event_review_status_sync(
    db_path: Path, task_id: str, event_id: str, status: str,
    updated_by: str = "workbench",
) -> Dict[str, Any]:
    if status not in ALLOWED_EVENT_REVIEW_STATUSES:
        raise ValueError(f"invalid event review status: {status}")
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO workbench_event_review
               (task_id, event_id, review_status, updated_by, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(task_id, event_id) DO UPDATE SET
                 review_status = excluded.review_status,
                 updated_by = excluded.updated_by,
                 updated_at = excluded.updated_at""",
            (task_id, event_id, status, updated_by, now),
        )
    return {
        "task_id": task_id,
        "event_id": event_id,
        "review_status": status,
        "updated_by": updated_by,
        "updated_at": now,
    }


def event_review_statuses_sync(db_path: Path, task_id: str) -> Dict[str, str]:
    """One row per reviewed event: event_id -> review_status."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT event_id, review_status FROM workbench_event_review "
            "WHERE task_id = ?",
            (task_id,),
        ).fetchall()
    return {row["event_id"]: row["review_status"] for row in rows}


def upsert_note_sync(
    db_path: Path, task_id: str, target_type: str, target_key: str,
    content: str, author: Optional[str] = None,
) -> Dict[str, Any]:
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO workbench_analyst_notes
               (task_id, target_type, target_key, content, author,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(task_id, target_type, target_key) DO UPDATE SET
                 content = excluded.content,
                 author = excluded.author,
                 updated_at = excluded.updated_at""",
            (task_id, target_type, target_key, content, author, now, now),
        )
        row = conn.execute(
            "SELECT * FROM workbench_analyst_notes WHERE task_id = ? "
            "AND target_type = ? AND target_key = ?",
            (task_id, target_type, target_key),
        ).fetchone()
    return _row_to_note(row)


def get_note_sync(
    db_path: Path, task_id: str, target_type: str, target_key: str
) -> Optional[Dict[str, Any]]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM workbench_analyst_notes WHERE task_id = ? "
            "AND target_type = ? AND target_key = ?",
            (task_id, target_type, target_key),
        ).fetchone()
    return _row_to_note(row) if row else None


async def set_event_review_status(
    db_path: Path, task_id: str, event_id: str, status: str,
    updated_by: str = "workbench",
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        set_event_review_status_sync, db_path, task_id, event_id, status, updated_by
    )


async def event_review_statuses(db_path: Path, task_id: str) -> Dict[str, str]:
    return await asyncio.to_thread(event_review_statuses_sync, db_path, task_id)


async def upsert_note(
    db_path: Path, task_id: str, target_type: str, target_key: str,
    content: str, author: Optional[str] = None,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        upsert_note_sync, db_path, task_id, target_type, target_key,
        content, author,
    )


async def get_note(
    db_path: Path, task_id: str, target_type: str, target_key: str
) -> Optional[Dict[str, Any]]:
    return await asyncio.to_thread(
        get_note_sync, db_path, task_id, target_type, target_key
    )
