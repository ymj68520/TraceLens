"""
Events database reader module for fetching timeline events from SQLite database.
"""

from pathlib import Path
from typing import Iterator, Optional

from graphiti_integration.exceptions import DatabaseError
from .base_reader import _BaseForensicsReader


# =============================================================================
# Events Database Reader (_events.db)
# =============================================================================

class EventsDatabase(_BaseForensicsReader):
    """Reader for the events/timeline database ({image}_events.db)."""

    def get_events(
        self,
        event_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list:
        """Fetch timeline events."""
        from graphiti_integration.forensic_data_types import TimelineEvent

        where = f"WHERE event_type = '{event_type}'" if event_type else ""
        query = f"""
            SELECT id, timestamp, event_type, file_path, inode,
                   description, file_size, file_type
            FROM events {where}
            ORDER BY timestamp
        """
        query += f" LIMIT {limit}" if limit else ""
        query += f" OFFSET {offset}" if offset > 0 else ""

        with self.connect() as conn:
            cursor = conn.execute(query)
            return [
                TimelineEvent(
                    id=r["id"],
                    timestamp=r["timestamp"] or 0,
                    event_type=r["event_type"] or "",
                    file_path=r["file_path"] or "",
                    inode=r["inode"] or 0,
                    description=r["description"] or "",
                    file_size=r["file_size"] or 0,
                    file_type=r["file_type"] or "",
                )
                for r in cursor.fetchall()
            ]

    def get_event_clusters(
        self,
        analyzed_only: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list:
        """Fetch event clusters with AI analysis."""
        from graphiti_integration.forensic_data_types import EventCluster

        where_clause = ""
        if analyzed_only:
            where_clause = "WHERE llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0"

        query = f"""
            SELECT id, timestamp, event_type, file_path, inode,
                   description, file_size, file_type,
                   llm_summary, llm_description, llm_keywords,
                   llm_analyzed_at, llm_model_used, llm_is_relevant
            FROM events {where_clause}
            ORDER BY timestamp
        """
        query += f" LIMIT {limit}" if limit else ""
        query += f" OFFSET {offset}" if offset > 0 else ""

        with self.connect() as conn:
            cursor = conn.execute(query)
            return [
                EventCluster(
                    id=r["id"],
                    timestamp=r["timestamp"] or 0,
                    event_type=r["event_type"] or "",
                    file_path=r["file_path"] or "",
                    inode=r["inode"] or 0,
                    description=r["description"] or "",
                    file_size=r["file_size"] or 0,
                    file_type=r["file_type"] or "",
                    llm_summary=r["llm_summary"],
                    llm_description=r["llm_description"],
                    llm_keywords=r["llm_keywords"],
                    llm_analyzed_at=r["llm_analyzed_at"],
                    llm_model_used=r["llm_model_used"],
                    llm_is_relevant=bool(r["llm_is_relevant"]),
                )
                for r in cursor.fetchall()
            ]

    def iter_event_clusters_batched(
        self, batch_size: int = 100, analyzed_only: bool = False
    ) -> Iterator[list]:
        """Iterate over event clusters in batches."""
        offset = 0
        while True:
            batch = self.get_event_clusters(
                analyzed_only=analyzed_only,
                limit=batch_size,
                offset=offset
            )
            if not batch:
                break
            yield batch
            offset += len(batch)

    def get_event_cluster_stats(self) -> dict:
        """Get event cluster analysis statistics."""
        if not self._table_exists("events"):
            return {}
        with self.connect() as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total_clusters,
                    SUM(CASE WHEN llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0 THEN 1 ELSE 0 END) as analyzed_clusters,
                    SUM(CASE WHEN llm_is_relevant = 1 THEN 1 ELSE 0 END) as relevant_clusters
                FROM events
            """)
            row = cursor.fetchone()
            if row:
                return {
                    "total_clusters": row["total_clusters"],
                    "analyzed_clusters": row["analyzed_clusters"],
                    "relevant_clusters": row["relevant_clusters"],
                    "analysis_percentage": (
                        row["analyzed_clusters"] / row["total_clusters"] * 100
                        if row["total_clusters"] > 0 else 0
                    ),
                }
            return {
                "total_clusters": 0,
                "analyzed_clusters": 0,
                "relevant_clusters": 0,
                "analysis_percentage": 0
            }

    def iter_events_batched(
        self, batch_size: int = 200, event_type: Optional[str] = None
    ) -> Iterator[list]:
        offset = 0
        while True:
            batch = self.get_events(event_type=event_type, limit=batch_size, offset=offset)
            if not batch:
                break
            yield batch
            offset += len(batch)

    def count_events(self) -> int:
        return self._count_rows("events")

    def get_event_stats(self) -> dict:
        """Get event count by type."""
        if not self._table_exists("events"):
            return {}
        with self.connect() as conn:
            cursor = conn.execute(
                "SELECT event_type, COUNT(*) as cnt FROM events GROUP BY event_type"
            )
            return {r["event_type"]: r["cnt"] for r in cursor.fetchall()}


def read_events_database(db_path: str | Path) -> EventsDatabase:
    """
    Convenience function to read events database.

    Args:
        db_path: Path to the events database file.

    Returns:
        EventsDatabase instance.
    """
    return EventsDatabase(db_path)


def get_timeline_events(
    db_path: str | Path,
    event_type: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list:
    """
    Convenience function to fetch timeline events from events database.

    Args:
        db_path: Path to the events database file.
        event_type: Filter by event type.
        limit: Maximum number of records to fetch.
        offset: Number of records to skip.

    Returns:
        List of TimelineEvent objects.
    """
    db = EventsDatabase(db_path)
    return db.get_events(event_type=event_type, limit=limit, offset=offset)
