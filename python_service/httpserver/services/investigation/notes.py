"""Versioned analyst context in the canonical task store, separate from evidence."""
from contextlib import closing
from datetime import datetime, timezone

from ..evidence.exceptions import EvidenceNotFoundError
from .graph_reader import InvestigationGraphReader

TABLE = "investigation_analyst_notes"
DDL = """
CREATE TABLE IF NOT EXISTS investigation_analyst_notes (
    task_id TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK(target_type IN ('evidence','event')),
    target_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    content TEXT NOT NULL,
    author TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(task_id, target_type, target_key, version)
)
"""


def _validate_target(conn, task_id, target_type, target_key):
    if target_type == "evidence":
        found = conn.execute(
            "SELECT 1 FROM evidence_snapshots WHERE task_id=? AND evidence_key=?",
            (task_id, target_key),
        ).fetchone()
    elif target_type == "event":
        found = conn.execute(
            "SELECT 1 FROM investigation_events WHERE task_id=? AND event_id=?",
            (task_id, target_key),
        ).fetchone()
    else:
        raise ValueError("unsupported note target")
    if not found:
        raise EvidenceNotFoundError("note target not found")


def save_note(repo, target_type, target_key, content, author):
    with closing(repo._connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        _validate_target(conn, repo.task_id, target_type, target_key)
        conn.execute(DDL)
        version = conn.execute(
            f"SELECT COALESCE(MAX(version),0)+1 FROM {TABLE} "
            "WHERE task_id=? AND target_type=? AND target_key=?",
            (repo.task_id, target_type, target_key),
        ).fetchone()[0]
        note = dict(task_id=repo.task_id, target_type=target_type, target_key=target_key,
                    version=version, content=content, author=author,
                    updated_at=datetime.now(timezone.utc).isoformat())
        conn.execute(
            f"INSERT INTO {TABLE} VALUES (?,?,?,?,?,?,?)",
            tuple(note[k] for k in ("task_id", "target_type", "target_key", "version",
                                    "content", "author", "updated_at")),
        )
        return note


def read_note(db_path, task_id, target_type, target_key):
    if not db_path.is_file():
        return None
    def read(conn):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone():
            return None
        row = conn.execute(
            f"SELECT * FROM {TABLE} WHERE task_id=? AND target_type=? AND target_key=? "
            "ORDER BY version DESC LIMIT 1", (task_id, target_type, target_key),
        ).fetchone()
        return dict(row) if row else None
    return InvestigationGraphReader(db_path, task_id)._run(read)
