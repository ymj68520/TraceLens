"""
File Entity Ingestor module for managing File nodes in the knowledge graph.

This module provides functionality to create and update File entities in Graphiti,
establishing first-class file nodes with bi-directional relationships to episodes
and entities.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from neo4j import AsyncGraphDatabase
from ..database_reader.raw_reader import FileRecord

logger = logging.getLogger(__name__)


@dataclass
class EventRecord:
    """Represents a timeline event."""
    file_inode: int
    file_path: str
    event_type: str  # CREATED, MODIFIED, ACCESSED, CHANGED, DELETED
    timestamp: int  # Unix timestamp
    task_id: str


@dataclass
class FileIngestionResult:
    """Result of a file ingestion operation."""
    files_created: int = 0
    files_updated: int = 0
    events_attached: int = 0
    episodes_linked: int = 0
    duplicates_merged: int = 0
    errors: list[str] = field(default_factory=list)


class FileEntityIngestor:
    """
    Manages File entity creation and updates in the knowledge graph.

    File entities use SHA-256 hash of the full path as their ID, ensuring
    uniqueness while preserving the original path for human readability.
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
    ):
        """
        Initialize File Entity Ingestor.

        Args:
            neo4j_uri: Neo4j connection URI.
            neo4j_user: Neo4j username.
            neo4j_password: Neo4j password.
        """
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self._driver: Optional[AsyncGraphDatabase.driver] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize Neo4j driver and create constraints/indexes."""
        if self._initialized:
            return

        self._driver = AsyncGraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password)
        )

        # Create unique constraint on File.id
        await self._run_query(
            "CREATE CONSTRAINT file_id_unique IF NOT EXISTS FOR (f:File) REQUIRE f.id IS UNIQUE"
        )

        # Create indexes for common queries
        indexes = [
            "CREATE INDEX file_md5_index IF NOT EXISTS FOR (f:File) ON (f.md5)",
            "CREATE INDEX file_path_hash_index IF NOT EXISTS FOR (f:File) ON (f.path_hash)",
            "CREATE INDEX file_category_index IF NOT EXISTS FOR (f:File) ON (f.category)",
            "CREATE INDEX file_llm_analyzed_index IF NOT EXISTS FOR (f:File) ON (f.llm_analyzed_at)",
        ]

        for index_query in indexes:
            await self._run_query(index_query)

        self._initialized = True
        logger.info("FileEntityIngestor initialized with constraints and indexes")

    async def close(self) -> None:
        """Close Neo4j driver connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            self._initialized = False

    def _generate_path_hash(self, path: str) -> str:
        """
        Generate SHA-256 hash of file path for use as ID.

        Args:
            path: Full file path.

        Returns:
            Hex-encoded SHA-256 hash.
        """
        return hashlib.sha256(path.encode('utf-8')).hexdigest()

    async def _run_query(
        self,
        query: str,
        parameters: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """Run a Cypher query and return results."""
        if not self._initialized:
            await self.initialize()

        async with self._driver.session() as session:
            result = await session.run(query, parameters or {})
            return [record.data() async for record in result]

    async def _get_file_entity(self, file_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve existing File entity.

        Args:
            file_id: Path hash of the file.

        Returns:
            File entity data or None if not found.
        """
        query = """
            MATCH (f:File {id: $file_id})
            RETURN f
        """
        result = await self._run_query(query, {"file_id": file_id})
        return result[0]["f"] if result else None

    async def ensure_file_entity(
        self,
        file: FileRecord,
        task_id: str,
    ) -> str:
        """
        Create or update a File entity in the knowledge graph.

        Uses MERGE to ensure idempotency - can be called multiple times
        with the same file without creating duplicates.

        Args:
            file: FileRecord from database.
            task_id: Task ID for associating with the file.

        Returns:
            The path_hash ID of the File entity.
        """
        path_hash = self._generate_path_hash(file.path)

        # Build keywords list from comma-separated string
        keywords = file.keywords_list if file.has_llm_analysis else []

        # Create or update File entity
        query = """
            MERGE (f:File {id: $id})
            ON CREATE SET
                f.path_hash = $path_hash,
                f.path = $path,
                f.filename = $filename,
                f.extension = $extension,
                f.md5 = $md5,
                f.inode = $inode,
                f.size_bytes = $size,
                f.category = $category,
                f.file_type = $file_type,
                f.is_deleted = $is_deleted,
                f.tasks = [$task_id],
                f.events = [],
                f.created_at = datetime(),
                f.updated_at = datetime()
            ON MATCH SET
                f.tasks = CASE WHEN $task_id IN f.tasks THEN f.tasks ELSE f.tasks + $task_id END,
                f.md5 = CASE WHEN f.md5 IS NULL OR f.md5 = '' THEN $md5 ELSE f.md5 END,
                f.size_bytes = CASE WHEN f.size_bytes = 0 THEN $size ELSE f.size_bytes END,
                f.llm_summary = $llm_summary,
                f.llm_description = $llm_description,
                f.llm_keywords = $llm_keywords,
                f.llm_analyzed_at = $llm_analyzed_at,
                f.llm_model = $llm_model,
                f.updated_at = datetime()
            RETURN f.id AS id, size(f.tasks) > 1 AS is_update
        """

        # Convert timestamps to ISO format if present
        llm_analyzed_at = None
        if file.llm_analyzed_at and file.llm_analyzed_at > 0:
            llm_analyzed_at = datetime.fromtimestamp(file.llm_analyzed_at).isoformat()

        result = await self._run_query(query, {
            "id": path_hash,
            "path_hash": path_hash,
            "path": file.path,
            "filename": file.name,
            "extension": file.extension,
            "md5": file.md5 or "",
            "inode": file.inode,
            "size": file.size,
            "category": file.category,
            "file_type": file.file_type,
            "is_deleted": file.is_deleted,
            "task_id": task_id,
            "llm_summary": file.llm_summary,
            "llm_description": file.llm_description,
            "llm_keywords": keywords,
            "llm_analyzed_at": llm_analyzed_at,
            "llm_model": file.llm_model_used,
        })

        # Create Task node and CONTAINS_FILE relationship
        await self._run_query("""
            MERGE (t:Task {id: $task_id})
            ON CREATE SET t.created_at = datetime()
            MERGE (t)-[:CONTAINS_FILE]->(f:File {id: $file_id})
        """, {"task_id": task_id, "file_id": path_hash})

        is_update = result[0].get("is_update", False)
        logger.debug(f"{'Updated' if is_update else 'Created'} File entity: {path_hash} ({file.path})")

        return path_hash

    async def attach_event_to_file(
        self,
        file_path: str,
        event: EventRecord,
    ) -> bool:
        """
        Attach an event to a File entity's events array.

        Args:
            file_path: Full path to the file.
            event: EventRecord to attach.

        Returns:
            True if event was attached, False if file not found.
        """
        path_hash = self._generate_path_hash(file_path)

        # Build event object
        event_data = {
            "type": event.event_type,
            "timestamp": datetime.fromtimestamp(event.timestamp).isoformat(),
            "task_id": event.task_id
        }

        query = """
            MATCH (f:File {id: $file_id})
            SET f.events = coalesce(f.events, []) + $event
            RETURN f
        """

        result = await self._run_query(query, {
            "file_id": path_hash,
            "event": event_data
        })

        if result:
            logger.debug(f"Attached event {event.event_type} to file {file_path}")
            return True

        logger.warning(f"File not found for event attachment: {file_path}")
        return False

    async def attach_events_batch(
        self,
        events: list[tuple[str, EventRecord]],
    ) -> int:
        """
        Attach multiple events to files in batch.

        Args:
            events: List of (file_path, EventRecord) tuples.

        Returns:
            Number of events successfully attached.
        """
        attached = 0
        for file_path, event in events:
            if await self.attach_event_to_file(file_path, event):
                attached += 1
        return attached

    async def link_episode_to_file(
        self,
        episode_uuid: str,
        file_path: str,
    ) -> bool:
        """
        Create SOURCE_FILE relationship from Episode to File.

        Args:
            episode_uuid: UUID of the Episodic node.
            file_path: Path to the file (will be hashed).

        Returns:
            True if link created, False if file or episode not found.
        """
        path_hash = self._generate_path_hash(file_path)

        query = """
            MATCH (e:Episodic {uuid: $episode_uuid})
            MATCH (f:File {id: $file_id})
            MERGE (e)-[:SOURCE_FILE]->(f)
            RETURN e
        """

        result = await self._run_query(query, {
            "episode_uuid": episode_uuid,
            "file_id": path_hash
        })

        if result:
            logger.debug(f"Linked episode {episode_uuid} to file {file_path}")
            return True

        logger.warning(f"Failed to link episode: episode={episode_uuid}, file={file_path}")
        return False

    async def merge_duplicate_files(self, task_id: str) -> int:
        """
        Create SAME_CONTENT_AS edges between files with identical MD5.

        Processes all files in the given task and creates bidirectional
        edges between files with matching MD5 hashes.

        Args:
            task_id: Task ID to process.

        Returns:
            Number of duplicate groups found.
        """
        # Find all MD5s with multiple files in this task
        query = """
            MATCH (t:Task {id: $task_id})-[:CONTAINS_FILE]->(f:File)
            WHERE f.md5 IS NOT NULL AND f.md5 <> ''
            WITH f.md5 AS md5, collect(f) AS files
            WHERE size(files) > 1
            RETURN md5, files
        """

        results = await self._run_query(query, {"task_id": task_id})
        groups_found = len(results)

        for group in results:
            md5 = group["md5"]
            files = group["files"]

            # Create bidirectional SAME_CONTENT_AS edges
            for i, f1 in enumerate(files):
                for f2 in files[i+1:]:
                    await self._run_query("""
                        MATCH (f1:File {id: $id1})
                        MATCH (f2:File {id: $id2})
                        MERGE (f1)-[:SAME_CONTENT_AS {confidence: 1.0}]->(f2)
                        MERGE (f2)-[:SAME_CONTENT_AS {confidence: 1.0}]->(f1)
                    """, {"id1": f1["id"], "id2": f2["id"]})

        if groups_found > 0:
            logger.info(f"Found {groups_found} duplicate MD5 groups in task {task_id}")

        return groups_found

    async def get_file_by_id(self, file_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve File entity by ID.

        Args:
            file_id: Path hash ID.

        Returns:
            File entity data or None.
        """
        query = """
            MATCH (f:File {id: $file_id})
            OPTIONAL MATCH (f)<-[r:SOURCE_FILE]-(e:Episodic)
            OPTIONAL MATCH (en:Entity)-[mr:MENTIONED_IN]->(f)
            RETURN f,
                   collect(DISTINCT e.uuid) AS episode_uuids,
                   collect(DISTINCT {uuid: en.uuid, name: en.name, frequency: mr.frequency}) AS entities
        """

        result = await self._run_query(query, {"file_id": file_id})
        if result:
            return result[0]
        return None

    async def get_files_by_task(
        self,
        task_id: str,
        category: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve all File entities for a task.

        Args:
            task_id: Task ID.
            category: Optional category filter.

        Returns:
            List of File entities.
        """
        if category:
            query = """
                MATCH (t:Task {id: $task_id})-[:CONTAINS_FILE]->(f:File {category: $category})
                RETURN f
                ORDER BY f.path
            """
            params = {"task_id": task_id, "category": category}
        else:
            query = """
                MATCH (t:Task {id: $task_id})-[:CONTAINS_FILE]->(f:File)
                RETURN f
                ORDER BY f.path
            """
            params = {"task_id": task_id}

        return await self._run_query(query, params)

    async def batch_ensure_files(
        self,
        files: list[FileRecord],
        task_id: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> FileIngestionResult:
        """
        Create/update multiple File entities in batch.

        Args:
            files: List of FileRecord objects.
            task_id: Task ID for association.
            progress_callback: Optional callback(current, total) for progress.

        Returns:
            FileIngestionResult with statistics.
        """
        result = FileIngestionResult()

        for i, file in enumerate(files):
            try:
                # Check if this is an update (file already exists)
                path_hash = self._generate_path_hash(file.path)
                existing = await self._get_file_entity(path_hash)

                await self.ensure_file_entity(file, task_id)

                if existing:
                    result.files_updated += 1
                else:
                    result.files_created += 1

            except Exception as e:
                error_msg = f"Error processing file {file.path}: {str(e)}"
                result.errors.append(error_msg)
                logger.error(error_msg)

            if progress_callback:
                progress_callback(i + 1, len(files))

        logger.info(
            f"Batch file ingestion complete: "
            f"{result.files_created} created, {result.files_updated} updated"
        )

        return result

    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
