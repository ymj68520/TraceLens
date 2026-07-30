"""
Base reader for forensic SQLite databases with common connection logic.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterator, Optional

from graphiti_integration.exceptions import DatabaseError


class _BaseForensicsReader:
    """Base reader for forensic SQLite databases with common connection logic."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise DatabaseError(f"Database not found: {self.db_path}")

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            # Handle non-UTF-8 filenames (e.g. GBK filenames on Chinese Windows)
            def _text_factory(bytes_):
                if bytes_ is None:
                    return None
                if isinstance(bytes_, str):
                    return bytes_
                try:
                    return bytes_.decode('utf-8')
                except UnicodeDecodeError:
                    return bytes_.decode('gbk', errors='replace')
            conn.text_factory = _text_factory
            yield conn
        except sqlite3.Error as e:
            raise DatabaseError(f"Database connection error: {e}") from e
        finally:
            if conn:
                conn.close()

    def _table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        with self.connect() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            return cursor.fetchone() is not None

    def _count_rows(self, table_name: str) -> int:
        """Count rows in a table."""
        if not self._table_exists(table_name):
            return 0
        with self.connect() as conn:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            row = cursor.fetchone()
            return row[0] if row else 0

    def _query_table(
        self,
        table_name: str,
        columns: str = "*",
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        """Generic table query with pagination."""
        if not self._table_exists(table_name):
            return []
        query = f"SELECT {columns} FROM {table_name}"
        query += f" LIMIT {limit}" if limit else ""
        query += f" OFFSET {offset}" if offset > 0 else ""
        with self.connect() as conn:
            cursor = conn.execute(query)
            return cursor.fetchall()
