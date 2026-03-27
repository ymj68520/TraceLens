"""
Raw database reader module for fetching file metadata from SQLite database.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Generator, Iterator, Optional

from ..exceptions import DatabaseError


@dataclass
class FileRecord:
    """
    Represents a file record from the database with LLM analysis.
    Mirrors the C++ FileRecordWithLLM structure from TOONExporter.
    """

    # Core file metadata
    id: int
    inode: int
    name: str
    path: str
    size: int
    extension: str
    category: str
    file_type: str
    mtime: int  # Unix timestamp
    ctime: int  # Unix timestamp
    is_deleted: bool
    md5: str

    # LLM analysis fields
    llm_summary: Optional[str] = None
    llm_description: Optional[str] = None
    llm_keywords: Optional[str] = None
    llm_analyzed_at: Optional[int] = None  # Unix timestamp
    llm_model_used: Optional[str] = None

    @property
    def has_llm_analysis(self) -> bool:
        """Check if this record has LLM analysis."""
        return self.llm_analyzed_at is not None and self.llm_analyzed_at > 0

    @property
    def mtime_datetime(self) -> Optional[datetime]:
        """Get modification time as datetime."""
        if self.mtime and self.mtime > 0:
            return datetime.fromtimestamp(self.mtime)
        return None

    @property
    def ctime_datetime(self) -> Optional[datetime]:
        """Get creation time as datetime."""
        if self.ctime and self.ctime > 0:
            return datetime.fromtimestamp(self.ctime)
        return None

    @property
    def keywords_list(self) -> list[str]:
        """Parse keywords string into list."""
        if not self.llm_keywords:
            return []
        # Keywords may be comma-separated or JSON array
        keywords = self.llm_keywords.strip()
        if keywords.startswith("["):
            import json
            try:
                return json.loads(keywords)
            except json.JSONDecodeError:
                pass
        return [k.strip() for k in keywords.split(",") if k.strip()]


class ForensicsDatabase:
    """
    Database reader for forensics SQLite database.
    Provides methods to fetch file records with LLM analysis.
    """

    # SQL query to fetch files with LLM data
    SELECT_FILES_SQL = """
        SELECT
            id, inode, name, path, size, extension, category, type,
            mtime, ctime, is_deleted, md5,
            llm_summary, llm_description, llm_keywords,
            llm_analyzed_at, llm_model_used
        FROM files
        {where_clause}
        ORDER BY path
        {limit_clause}
        {offset_clause}
    """

    COUNT_FILES_SQL = """
        SELECT COUNT(*) FROM files {where_clause}
    """

    def __init__(self, db_path: str | Path):
        """
        Initialize database reader.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise DatabaseError(f"Database not found: {self.db_path}")

        self._connection: Optional[sqlite3.Connection] = None

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connection.

        Yields:
            SQLite connection object.
        """
        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            yield conn
        except sqlite3.Error as e:
            raise DatabaseError(f"Database connection error: {e}") from e
        finally:
            if conn:
                conn.close()

    def _build_where_clause(
        self,
        analyzed_only: bool = False,
        categories: Optional[list[str]] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
    ) -> tuple[str, list]:
        """
        Build WHERE clause and parameters for query.

        Returns:
            Tuple of (where_clause_string, parameters_list).
        """
        conditions = []
        params = []

        if analyzed_only:
            conditions.append("llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0")

        if categories:
            placeholders = ", ".join("?" for _ in categories)
            conditions.append(f"category IN ({placeholders})")
            params.extend(categories)

        if min_size is not None:
            conditions.append("size >= ?")
            params.append(min_size)

        if max_size is not None:
            conditions.append("size <= ?")
            params.append(max_size)

        if conditions:
            return "WHERE " + " AND ".join(conditions), params
        return "", params

    def count_files(
        self,
        analyzed_only: bool = False,
        categories: Optional[list[str]] = None,
    ) -> int:
        """
        Count files matching the given criteria.

        Args:
            analyzed_only: Only count files with LLM analysis.
            categories: Filter by category names.

        Returns:
            Number of matching files.
        """
        where_clause, params = self._build_where_clause(
            analyzed_only=analyzed_only,
            categories=categories,
        )

        query = self.COUNT_FILES_SQL.format(where_clause=where_clause)

        with self.connect() as conn:
            cursor = conn.execute(query, params)
            result = cursor.fetchone()
            return result[0] if result else 0

    def get_files(
        self,
        analyzed_only: bool = False,
        categories: Optional[list[str]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[FileRecord]:
        """
        Fetch file records from database.

        Args:
            analyzed_only: Only fetch files with LLM analysis.
            categories: Filter by category names.
            limit: Maximum number of records to fetch.
            offset: Number of records to skip.

        Returns:
            List of FileRecord objects.
        """
        where_clause, params = self._build_where_clause(
            analyzed_only=analyzed_only,
            categories=categories,
        )

        limit_clause = f"LIMIT {limit}" if limit else ""
        offset_clause = f"OFFSET {offset}" if offset > 0 else ""

        query = self.SELECT_FILES_SQL.format(
            where_clause=where_clause,
            limit_clause=limit_clause,
            offset_clause=offset_clause,
        )

        with self.connect() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]

    def iter_files_batched(
        self,
        batch_size: int = 100,
        analyzed_only: bool = False,
        categories: Optional[list[str]] = None,
    ) -> Iterator[list[FileRecord]]:
        """
        Iterate over files in batches.

        Args:
            batch_size: Number of records per batch.
            analyzed_only: Only fetch files with LLM analysis.
            categories: Filter by category names.

        Yields:
            Lists of FileRecord objects.
        """
        offset = 0
        while True:
            batch = self.get_files(
                analyzed_only=analyzed_only,
                categories=categories,
                limit=batch_size,
                offset=offset,
            )
            if not batch:
                break
            yield batch
            offset += len(batch)

    def _row_to_record(self, row: sqlite3.Row) -> FileRecord:
        """Convert a database row to FileRecord."""
        return FileRecord(
            id=row["id"],
            inode=row["inode"] or 0,
            name=row["name"] or "",
            path=row["path"] or "",
            size=row["size"] or 0,
            extension=row["extension"] or "",
            category=row["category"] or "",
            file_type=row["type"] or "",
            mtime=row["mtime"] or 0,
            ctime=row["ctime"] or 0,
            is_deleted=bool(row["is_deleted"]),
            md5=row["md5"] or "",
            llm_summary=row["llm_summary"],
            llm_description=row["llm_description"],
            llm_keywords=row["llm_keywords"],
            llm_analyzed_at=row["llm_analyzed_at"],
            llm_model_used=row["llm_model_used"],
        )

    def get_categories(self) -> list[str]:
        """
        Get list of unique categories in the database.

        Returns:
            List of category names.
        """
        query = "SELECT DISTINCT category FROM files WHERE category IS NOT NULL ORDER BY category"
        with self.connect() as conn:
            cursor = conn.execute(query)
            return [row[0] for row in cursor.fetchall()]

    def get_analysis_stats(self) -> dict:
        """
        Get statistics about LLM analysis in the database.

        Returns:
            Dictionary with statistics.
        """
        query = """
            SELECT
                COUNT(*) as total_files,
                SUM(CASE WHEN llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0 THEN 1 ELSE 0 END) as analyzed_files,
                SUM(size) as total_size
            FROM files
        """
        with self.connect() as conn:
            cursor = conn.execute(query)
            row = cursor.fetchone()
            if row:
                return {
                    "total_files": row["total_files"],
                    "analyzed_files": row["analyzed_files"],
                    "total_size": row["total_size"],
                    "analysis_percentage": (
                        row["analyzed_files"] / row["total_files"] * 100
                        if row["total_files"] > 0 else 0
                    ),
                }
            return {"total_files": 0, "analyzed_files": 0, "total_size": 0, "analysis_percentage": 0}


def read_raw_database(db_path: str | Path) -> ForensicsDatabase:
    """
    Convenience function to read raw database.

    Args:
        db_path: Path to the raw database file.

    Returns:
        ForensicsDatabase instance.
    """
    return ForensicsDatabase(db_path)


def get_files_metadata(
    db_path: str | Path,
    analyzed_only: bool = False,
    categories: Optional[list[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list[FileRecord]:
    """
    Convenience function to fetch file metadata from raw database.

    Args:
        db_path: Path to the raw database file.
        analyzed_only: Only fetch files with LLM analysis.
        categories: Filter by category names.
        limit: Maximum number of records to fetch.
        offset: Number of records to skip.

    Returns:
        List of FileRecord objects.
    """
    db = ForensicsDatabase(db_path)
    return db.get_files(
        analyzed_only=analyzed_only,
        categories=categories,
        limit=limit,
        offset=offset,
    )
