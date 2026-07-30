from __future__ import annotations

import sqlite3
from collections.abc import Iterable
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

    @staticmethod
    def _document_values(document: dict[str, Any]) -> tuple[Any, ...]:
        return (
            document["kind"],
            document["title"],
            document["search_text"].casefold(),
            document.get("record_id"),
            document.get("evidence_id"),
            document.get("platform"),
            document.get("category_id"),
            document.get("page"),
        )

    def add_document(self, **document: Any) -> None:
        self.add_documents([document])

    def add_documents(self, documents: Iterable[dict[str, Any]]) -> list[int]:
        """Commit a completed category's staged documents as one transaction."""
        inserted_ids = []
        with self._connect() as conn:
            for document in documents:
                cursor = conn.execute(
                    """INSERT INTO search_documents
                       (kind, title, search_text, record_id, evidence_id, platform,
                        category_id, page) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    self._document_values(document),
                )
                inserted_ids.append(cursor.lastrowid)
        return inserted_ids

    def documents(self) -> list[dict[str, Any]]:
        """Return staged documents in insertion order for atomic category merge."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM search_documents ORDER BY id").fetchall()
        return [
            {
                "kind": row["kind"],
                "title": row["title"],
                "search_text": row["search_text"],
                "record_id": row["record_id"],
                "evidence_id": row["evidence_id"],
                "platform": row["platform"],
                "category_id": row["category_id"],
                "page": row["page"],
            }
            for row in rows
        ]

    def delete_documents(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            conn.execute(f"DELETE FROM search_documents WHERE id IN ({placeholders})", ids)

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
