"""
Migration Manager - Handles migration from old to new Graphiti structure.

This module provides backwards compatibility and migration utilities for
transitioning from episode-centric to File-entity-centric knowledge graph.
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from neo4j import AsyncGraphDatabase
from neo4j.exceptions import ConstraintError
from graphiti_integration.file_entity_ingestor import FileEntityIngestor, EventRecord

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    """Result of a migration operation."""
    files_migrated: int = 0
    episodes_linked: int = 0
    entities_linked: int = 0
    events_attached: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.files_migrated + len(self.errors)
        return (self.files_migrated / total * 100) if total > 0 else 0


@dataclass
class DeduplicationResult:
    """Result of MD5 deduplication operation."""
    md5_groups_found: int = 0
    edges_created: int = 0
    files_processed: int = 0


@dataclass
class CleanupResult:
    """Result of cleanup operation."""
    episodes_cleaned: int = 0
    properties_removed: list[str] = field(default_factory=list)


class MigrationManager:
    """
    Manages migration from old episode-centric to new File-entity structure.

    Provides backwards compatibility layer and one-time migration utilities.
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        neo4j_connect_timeout: float = 5.0,
        neo4j_query_timeout: float = 5.0,
    ):
        """
        Initialize Migration Manager.

        Args:
            neo4j_uri: Neo4j connection URI.
            neo4j_user: Neo4j username.
            neo4j_password: Neo4j password.
        """
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.neo4j_connect_timeout = neo4j_connect_timeout
        self.neo4j_query_timeout = neo4j_query_timeout
        self._driver: Optional[AsyncGraphDatabase.driver] = None
        self._initialized = False

        # Dependencies
        self._file_ingestor: Optional[FileEntityIngestor] = None

    async def initialize(self):
        """Initialize Neo4j driver and dependencies."""
        if self._initialized:
            return

        self._driver = AsyncGraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password),
            connection_timeout=self.neo4j_connect_timeout,
        )

        try:
            # Initialize File Entity Ingestor
            self._file_ingestor = FileEntityIngestor(
                neo4j_uri=self.neo4j_uri,
                neo4j_user=self.neo4j_user,
                neo4j_password=self.neo4j_password,
                neo4j_connect_timeout=self.neo4j_connect_timeout,
                neo4j_query_timeout=self.neo4j_query_timeout,
            )
            await asyncio.wait_for(
                self._file_ingestor.initialize(),
                timeout=self.neo4j_query_timeout * 2 + self.neo4j_connect_timeout,
            )
        except BaseException:
            await self.close()
            raise

        self._initialized = True
        logger.info("MigrationManager initialized")

    async def close(self):
        """Close Neo4j driver and dependencies."""
        if self._file_ingestor:
            await self._file_ingestor.close()
        if self._driver:
            await self._driver.close()
        self._initialized = False

    async def _run_query(
        self,
        query: str,
        parameters: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """Run a Cypher query and return results.

        Retries ConstraintError from concurrent MERGE on uniquely-constrained
        write queries; the retry MATCHes the node the concurrent winner created.
        """
        if not self._initialized:
            await self.initialize()

        max_retries = 3
        last_exc: Optional[Exception] = None
        upper = query.upper()
        is_write = any(tok in upper for tok in ("MERGE", "CREATE", "SET ", "DELETE", "REMOVE"))
        for attempt in range(max_retries):
            try:
                async with self._driver.session() as session:
                    result = await session.run(query, parameters or {})
                    return [record.data() async for record in result]
            except ConstraintError as e:
                last_exc = e
                if attempt < max_retries - 1 and is_write:
                    logger.debug(
                        "ConstraintError on migration query (attempt %d/%d), retrying: %s",
                        attempt + 1, max_retries, str(e)[:120],
                    )
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    async def query_file_with_fallback(
        self,
        path_hash: str,
        filename: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Query File entity with fallback to old Episodic structure.

        This provides backwards compatibility for queries during migration.

        Args:
            path_hash: SHA-256 hash of the file path.
            filename: Optional filename for fallback search.

        Returns:
            File entity data or None.
        """
        # Try new File entity first
        result = await self._run_query("""
            MATCH (f:File {id: $id})
            RETURN f
        """, {"id": path_hash})

        if result:
            return result[0]["f"]

        # Fallback: find in old Episodic structure
        if filename:
            result = await self._run_query("""
                MATCH (e:Episodic)
                WHERE e.name CONTAINS $filename
                AND e.source_description = "forensics_file_analysis"
                RETURN e
                LIMIT 1
            """, {"filename": filename})

            if result:
                episode = result[0]["e"]
                logger.info(f"Found file in old structure: {filename}, triggering migration")

                # Trigger migration for this file
                await self.migrate_single_episode(episode, path_hash)

                # Retry query
                result = await self._run_query("""
                    MATCH (f:File {id: $id}) RETURN f
                """, {"id": path_hash})

                if result:
                    return result[0]["f"]

        return None

    async def is_migrated(self, task_id: str) -> bool:
        """
        Check if a task has been migrated to new structure.

        Args:
            task_id: Task ID to check.

        Returns:
            True if migrated (File entities exist), False otherwise.
        """
        result = await self._run_query("""
            MATCH (t:Task {id: $task_id})-[:CONTAINS_FILE]->(f:File)
            RETURN count(f) > 0 AS has_files
        """, {"task_id": task_id})

        return result[0]["has_files"] if result else False

    async def get_migration_status(self, task_id: str) -> dict[str, Any]:
        """
        Get detailed migration status for a task.

        Args:
            task_id: Task ID.

        Returns:
            Status dictionary with migration metrics.
        """
        # Count File entities
        files_result = await self._run_query("""
            MATCH (t:Task {id: $task_id})-[:CONTAINS_FILE]->(f:File)
            RETURN count(f) AS file_count
        """, {"task_id": task_id})

        # Count Episodic nodes
        episodes_result = await self._run_query("""
            MATCH (e:Episodic {group_id: $task_id})
            RETURN count(e) AS episode_count
        """, {"task_id": task_id})

        # Count linked episodes
        linked_result = await self._run_query("""
            MATCH (e:Episodic {group_id: $task_id})-[:SOURCE_FILE]->(:File)
            RETURN count(e) AS linked_count
        """, {"task_id": task_id})

        file_count = files_result[0]["file_count"] if files_result else 0
        episode_count = episodes_result[0]["episode_count"] if episodes_result else 0
        linked_count = linked_result[0]["linked_count"] if linked_result else 0

        is_migrated = file_count > 0
        migration_progress = (linked_count / episode_count * 100) if episode_count > 0 else 0

        return {
            "task_id": task_id,
            "is_migrated": is_migrated,
            "file_entities": file_count,
            "total_episodes": episode_count,
            "linked_episodes": linked_count,
            "migration_progress": migration_progress,
            "status": "completed" if is_migrated and linked_count >= episode_count else "pending"
        }

    async def migrate_task(self, task_id: str) -> MigrationResult:
        """
        Migrate a single task from old to new structure.

        Extracts file metadata from existing Episodic nodes and creates
        corresponding File entities with relationships.

        Args:
            task_id: Task ID to migrate.

        Returns:
            MigrationResult with statistics.
        """
        result = MigrationResult()

        try:
            # Step 1: Find all Episodic nodes for this task
            await self._get_and_log_step("Finding episodes", 1, 6)
            episodes = await self._get_task_episodes(task_id)

            if not episodes:
                logger.info(f"No episodes found for task {task_id}, may already be migrated")
                return result

            logger.info(f"Found {len(episodes)} episodes to migrate")

            # Step 2: Process each episode
            await self._get_and_log_step("Processing episodes", 2, 6)

            for i, episode in enumerate(episodes):
                try:
                    # Extract file metadata from episode_body
                    episode_data = self._parse_episode_body(episode.get("episode_body", "{}"))

                    if not episode_data.get("file_path"):
                        continue

                    path = episode_data["file_path"]
                    path_hash = hashlib.sha256(path.encode()).hexdigest()

                    # Step 3: Create File entity from episode data
                    await self._create_file_entity_from_episode(
                        episode,
                        path_hash,
                        task_id
                    )
                    result.files_migrated += 1

                    # Step 4: Link Episode → File
                    await self._run_query("""
                        MATCH (e:Episodic {uuid: $episode_uuid})
                        MATCH (f:File {id: $file_id})
                        MERGE (e)-[:SOURCE_FILE]->(f)
                    """, {
                        "episode_uuid": episode["uuid"],
                        "file_id": path_hash
                    })
                    result.episodes_linked += 1

                    # Step 5: Extract and link entities (will be done in batch after)
                    if (i + 1) % 100 == 0:
                        logger.info(f"Processed {i + 1}/{len(episodes)} episodes")

                except Exception as e:
                    error_msg = f"Episode {episode.get('uuid', 'unknown')}: {str(e)}"
                    result.errors.append(error_msg)
                    logger.error(f"Failed to migrate episode: {e}")

            # Step 6: Attach events from database
            await self._get_and_log_step("Attaching events", 3, 6)
            result.events_attached = await self._attach_events_to_files(task_id)

            # Step 7: Create Task node
            await self._get_and_log_step("Creating task relationships", 4, 6)
            await self._create_task_node(task_id)

            # Step 8: Create MENTIONED_IN edges
            await self._get_and_log_step("Creating entity relationships", 5, 6)
            result.entities_linked = await self._create_entity_relationships(task_id)

            await self._get_and_log_step("Migration complete", 6, 6)

            logger.info(
                f"Migration complete for task {task_id}: "
                f"{result.files_migrated} files, {result.episodes_linked} episodes linked, "
                f"{result.entities_linked} entities, {result.events_attached} events"
            )

        except Exception as e:
            logger.error(f"Migration failed for task {task_id}: {e}")
            result.errors.append(f"Migration failed: {str(e)}")

        return result

    async def _get_and_log_step(self, message: str, step: int, total: int):
        """Log migration step."""
        logger.info(f"Migration step {step}/{total}: {message}")

    async def _get_task_episodes(self, task_id: str) -> list[dict]:
        """Get all Episodic nodes for a task."""
        result = await self._run_query("""
            MATCH (e:Episodic {group_id: $task_id})
            WHERE e.source_description = "forensics_file_analysis"
            RETURN e.uuid AS uuid, e.name AS name, e.episode_body AS episode_body
            ORDER BY e.name
        """, {"task_id": task_id})
        return result

    def _parse_episode_body(self, body: str) -> dict:
        """Parse episode body JSON."""
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse episode body as JSON")
            return {}

    async def _create_file_entity_from_episode(
        self,
        episode: dict,
        path_hash: str,
        task_id: str,
    ):
        """Create File entity from episode data."""
        episode_data = self._parse_episode_body(episode.get("episode_body", "{}"))
        metadata = episode_data.get("metadata", {})
        analysis = episode_data.get("analysis", {})

        # Parse keywords
        keywords = analysis.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",") if k.strip()]

        # Convert timestamps
        created_at = None
        if metadata.get("created_at"):
            try:
                created_at = metadata["created_at"]
            except:
                created_at = datetime.utcnow().isoformat()

        # Build task list from episode
        tasks = [task_id]
        group_id = episode.get("group_id", task_id)
        if group_id and group_id != task_id:
            tasks.append(group_id)

        await self._run_query("""
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
                f.tasks = $tasks,
                f.events = [],
                f.llm_summary = $llm_summary,
                f.llm_description = $llm_description,
                f.llm_keywords = $llm_keywords,
                f.llm_model = $llm_model,
                f.created_at = coalesce(f.created_at, $created_at),
                f.updated_at = datetime()
            ON MATCH SET
                f.tasks = CASE WHEN $task_id IN f.tasks THEN f.tasks ELSE f.tasks + $task_id END,
                f.updated_at = datetime()
        """, {
            "id": path_hash,
            "path_hash": path_hash,
            "path": episode_data.get("file_path", ""),
            "filename": episode_data.get("file_name", ""),
            "extension": episode_data.get("file_extension", ""),
            "md5": metadata.get("md5_hash", ""),
            "inode": metadata.get("inode", 0),
            "size": metadata.get("size_bytes", 0),
            "category": episode_data.get("category", ""),
            "file_type": metadata.get("file_type", ""),
            "is_deleted": metadata.get("is_deleted", False),
            "tasks": tasks,
            "task_id": task_id,
            "llm_summary": analysis.get("summary"),
            "llm_description": analysis.get("description"),
            "llm_keywords": keywords,
            "llm_model": analysis.get("model"),
            "created_at": created_at,
        })

    async def _attach_events_to_files(self, task_id: str) -> int:
        """Attach events from database to File entities."""
        # This would require reading from SQLite events database
        # For now, return 0 as events are typically added during ingestion
        # In a full implementation, this would:
        # 1. Locate the events database for the task
        # 2. Read events using EventsDatabase
        # 3. Match events to files by path/inode
        # 4. Call file_ingestor.attach_event_to_file for each

        logger.info(f"Event attachment for task {task_id} skipped (requires database access)")
        return 0

    async def _create_task_node(self, task_id: str):
        """Create Task node with CONTAINS_FILE relationships."""
        await self._run_query("""
            MERGE (t:Task {id: $task_id})
            ON CREATE SET t.created_at = datetime()

            WITH t
            MATCH (f:File)
            WHERE $task_id IN f.tasks
            MERGE (t)-[:CONTAINS_FILE]->(f)
        """, {"task_id": task_id})

    async def _create_entity_relationships(self, task_id: str) -> int:
        """Create MENTIONED_IN edges from entities to files."""
        # Find all entities mentioned in episodes and link to files
        result = await self._run_query("""
            MATCH (en:Entity)<-[:MENTIONS]-(e:Episodic {group_id: $task_id})
            MATCH (e)-[:SOURCE_FILE]->(f:File)
            MERGE (en)-[r:MENTIONED_IN]->(f)
            ON CREATE SET r.first_seen = datetime(), r.frequency = 1
            ON MATCH SET r.frequency = coalesce(r.frequency, 0) + 1
            RETURN count(DISTINCT en) AS entity_count
        """, {"task_id": task_id})

        return result[0]["entity_count"] if result else 0

    async def migrate_single_episode(
        self,
        episode: dict,
        path_hash: str,
        task_id: Optional[str] = None,
    ):
        """Migrate a single episode from old structure."""
        if task_id is None:
            task_id = episode.get("group_id", "unknown")

        await self._create_file_entity_from_episode(episode, path_hash, task_id)

        await self._run_query("""
            MATCH (e:Episodic {uuid: $episode_uuid})
            MATCH (f:File {id: $file_id})
            MERGE (e)-[:SOURCE_FILE]->(f)
        """, {
            "episode_uuid": episode["uuid"],
            "file_id": path_hash
        })

    async def deduplicate_by_md5(self) -> DeduplicationResult:
        """
        Find and link files with identical MD5 across all tasks.

        Creates bidirectional SAME_CONTENT_AS edges between files
        with matching MD5 hashes.

        Returns:
            DeduplicationResult with statistics.
        """
        result = DeduplicationResult()

        # Find all MD5s with multiple files
        md5_groups = await self._run_query("""
            MATCH (f:File)
            WHERE f.md5 IS NOT NULL AND f.md5 <> ''
            WITH f.md5 AS md5, collect(f) AS files
            WHERE size(files) > 1
            RETURN md5, files
        """)

        result.md5_groups_found = len(md5_groups)

        for group in md5_groups:
            md5 = group["md5"]
            files = group["files"]

            result.files_processed += len(files)

            # Create bidirectional SAME_CONTENT_AS edges
            for i, f1 in enumerate(files):
                for f2 in files[i+1:]:
                    await self._run_query("""
                        MATCH (f1:File {id: $id1})
                        MATCH (f2:File {id: $id2})
                        MERGE (f1)-[:SAME_CONTENT_AS {confidence: 1.0}]->(f2)
                        MERGE (f2)-[:SAME_CONTENT_AS {confidence: 1.0}]->(f1)
                    """, {"id1": f1["id"], "id2": f2["id"]})
                    result.edges_created += 2

        logger.info(
            f"Deduplication complete: {result.md5_groups_found} MD5 groups, "
            f"{result.edges_created} edges created, {result.files_processed} files processed"
        )

        return result

    async def cleanup_old_structure(self, task_id: str) -> CleanupResult:
        """
        Cleanup redundant data from old structure after migration.

        WARNING: This modifies the graph! Only run after validating migration.

        Args:
            task_id: Task ID to cleanup.

        Returns:
            CleanupResult with statistics.
        """
        result = CleanupResult()

        # Mark episodes as migrated (add flag)
        episodes_result = await self._run_query("""
            MATCH (e:Episodic {group_id: $task_id})-[:SOURCE_FILE]->(:File)
            SET e.migrated = true
            RETURN count(e) AS count
        """, {"task_id": task_id})

        result.episodes_cleaned = episodes_result[0]["count"] if episodes_result else 0
        result.properties_removed.append("migrated flag added")

        logger.info(f"Cleanup complete for task {task_id}: {result.episodes_cleaned} episodes marked")

        return result

    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
