from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .models import SearchHit


class SnapshotSearchIndex:
    """SQLite-backed, snapshot-local case-insensitive substring search."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS search_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    record_id TEXT,
                    evidence_id TEXT,
                    platform TEXT,
                    category_id TEXT,
                    page INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_search_record
                    ON search_documents(record_id);
                CREATE INDEX IF NOT EXISTS idx_search_category
                    ON search_documents(category_id, page);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add_document(self, **document: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO search_documents
                   (kind, title, search_text, record_id, evidence_id, platform,
                    category_id, page) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    document["kind"],
                    document["title"],
                    document["search_text"].casefold(),
                    document.get("record_id"),
                    document.get("evidence_id"),
                    document.get("platform"),
                    document.get("category_id"),
                    document.get("page"),
                ),
            )

    def search(self, query: str, offset: int, limit: int) -> tuple[int, list[SearchHit]]:
        needle = query.strip().casefold()
        if not needle or offset < 0 or limit <= 0:
            return 0, []

        where = "instr(search_text, ?) > 0"
        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM search_documents WHERE {where}", (needle,)
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT * FROM search_documents WHERE {where}
                    ORDER BY id LIMIT ? OFFSET ?""",
                (needle, limit, offset),
            ).fetchall()

        return total, [
            SearchHit(
                record_id=row["record_id"],
                kind=row["kind"],
                title=row["title"],
                snippet=row["search_text"][:240],
                matched_field="search_text",
                evidence_id=row["evidence_id"],
                platform=row["platform"],
                category_id=row["category_id"],
                page=row["page"],
            )
            for row in rows
        ]
