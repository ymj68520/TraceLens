"""
Entity Relation Builder module for creating relationships in the knowledge graph.

This module provides functionality to create bi-directional relationships between
entities and files, and resolve cross-task entity references.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from neo4j import AsyncGraphDatabase

logger = logging.getLogger(__name__)


@dataclass
class RelationBuildResult:
    """Result of a relation building operation."""
    mentioned_in_edges_created: int = 0
    entities_resolved: int = 0
    cross_task_links: int = 0
    errors: list[str] = field(default_factory=list)


class EntityRelationBuilder:
    """
    Manages entity-to-file relationships in the knowledge graph.

    Creates MENTIONED_IN back-links from entities to files, enabling
    queries like "which files mention this entity?".
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        neo4j_connect_timeout: float = 5.0,
        neo4j_query_timeout: float = 5.0,
    ):
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.neo4j_connect_timeout = neo4j_connect_timeout
        self.neo4j_query_timeout = neo4j_query_timeout
        self._driver: Optional[AsyncGraphDatabase.driver] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize Neo4j driver."""
        if self._initialized:
            return

        self._driver = AsyncGraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password),
            connection_timeout=self.neo4j_connect_timeout,
        )

        # Mark as initialized before running queries to prevent recursion
        self._initialized = True

        try:
            # Create index for MENTIONED_IN relationship queries
            await asyncio.wait_for(
                self._run_query("""
                    CREATE INDEX entity_name_index IF NOT EXISTS FOR (e:Entity) ON (e.name)
                """),
                timeout=self.neo4j_query_timeout,
            )
        except BaseException:
            await self.close()
            raise

        logger.info("EntityRelationBuilder initialized")

    async def close(self) -> None:
        """Close Neo4j driver connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            self._initialized = False

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

    async def create_mentioned_in_edges(
        self,
        file_id: str,
        entity_uuids: list[str],
    ) -> int:
        """
        Create MENTIONED_IN edges from entities to a file.

        Creates bi-directional awareness: entities know which files
        they appear in, and files know which entities they contain.

        Args:
            file_id: Path hash ID of the File entity.
            entity_uuids: List of entity UUIDs to link.

        Returns:
            Number of edges created.
        """
        if not entity_uuids:
            return 0

        edges_created = 0

        for entity_uuid in entity_uuids:
            query = """
                MATCH (en:Entity {uuid: $entity_uuid})
                MATCH (f:File {id: $file_id})
                MERGE (en)-[r:MENTIONED_IN]->(f)
                ON CREATE SET
                    r.first_seen = datetime(),
                    r.frequency = 1,
                    r.created_at = datetime()
                ON MATCH SET
                    r.frequency = coalesce(r.frequency, 0) + 1,
                    r.last_seen = datetime()
                RETURN en.name AS entity_name, f.path AS file_path
            """

            result = await self._run_query(query, {
                "entity_uuid": entity_uuid,
                "file_id": file_id
            })

            if result:
                edges_created += 1
                logger.debug(
                    f"Created MENTIONED_IN edge: {result[0]['entity_name']} -> {result[0]['file_path']}"
                )

        return edges_created

    async def create_mentioned_in_edges_from_episodes(
        self,
        episode_uuids: list[str],
        file_ids: dict[str, str],  # episode_uuid -> file_id mapping
    ) -> int:
        """
        Create MENTIONED_IN edges by extracting entities from episodes.

        For each episode, finds all entities mentioned and creates
        MENTIONED_IN edges to the associated file.

        Args:
            episode_uuids: List of episode UUIDs to process.
            file_ids: Mapping from episode UUID to file ID.

        Returns:
            Number of edges created.
        """
        total_edges = 0

        for episode_uuid in episode_uuids:
            file_id = file_ids.get(episode_uuid)
            if not file_id:
                logger.warning(f"No file ID found for episode {episode_uuid}")
                continue

            # Get all entities mentioned in this episode
            query = """
                MATCH (e:Episodic {uuid: $episode_uuid})-[r:MENTIONS]->(en:Entity)
                RETURN DISTINCT en.uuid AS entity_uuid, en.name AS entity_name
            """

            results = await self._run_query(query, {"episode_uuid": episode_uuid})

            entity_uuids = [r["entity_uuid"] for r in results]
            if entity_uuids:
                edges = await self.create_mentioned_in_edges(file_id, entity_uuids)
                total_edges += edges

        return total_edges

    async def get_entities_for_file(self, file_id: str) -> list[dict[str, Any]]:
        """
        Get all entities mentioned in a file with relationship details.

        Args:
            file_id: Path hash ID of the File entity.

        Returns:
            List of entities with mention frequency and other metadata.
        """
        query = """
            MATCH (en:Entity)-[r:MENTIONED_IN]->(f:File {id: $file_id})
            RETURN
                en.uuid AS uuid,
                en.name AS name,
                en.summary AS summary,
                en.labels AS labels,
                r.frequency AS frequency,
                r.first_seen AS first_seen,
                r.last_seen AS last_seen
            ORDER BY r.frequency DESC
        """

        return await self._run_query(query, {"file_id": file_id})

    async def get_files_for_entity(
        self,
        entity_name: str,
        task_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Get all files that mention an entity.

        Args:
            entity_name: Name of the entity.
            task_id: Optional task ID filter.

        Returns:
            List of files with mention details.
        """
        if task_id:
            query = """
                MATCH (en:Entity {name: $entity_name})-[r:MENTIONED_IN]->(f:File)
                MATCH (t:Task {id: $task_id})-[:CONTAINS_FILE]->(f)
                RETURN
                    f.id AS file_id,
                    f.path AS path,
                    f.filename AS filename,
                    f.category AS category,
                    f.tasks AS tasks,
                    r.frequency AS frequency
                ORDER BY r.frequency DESC
            """
            params = {"entity_name": entity_name, "task_id": task_id}
        else:
            query = """
                MATCH (en:Entity {name: $entity_name})-[r:MENTIONED_IN]->(f:File)
                RETURN
                    f.id AS file_id,
                    f.path AS path,
                    f.filename AS filename,
                    f.category AS category,
                    f.tasks AS tasks,
                    r.frequency AS frequency
                ORDER BY r.frequency DESC
            """
            params = {"entity_name": entity_name}

        return await self._run_query(query, params)

    async def resolve_cross_task_entities(
        self,
        task_id: str,
    ) -> int:
        """
        Merge identical entities across tasks.

        Finds entities with the same name (case-insensitive) and creates
        cross-references, enabling queries that span multiple tasks.

        Args:
            task_id: Task ID to process.

        Returns:
            Number of entity groups resolved.
        """
        # Find entities with same name across different tasks
        query = """
            MATCH (t:Task {id: $task_id})-[:CONTAINS_FILE]->(f:File)<-[r:MENTIONED_IN]-(e:Entity)
            WITH e.name AS entity_name, collect(DISTINCT e) AS entities
            WHERE size(entities) > 1
            RETURN entity_name, entities
        """

        results = await self._run_query(query, {"task_id": task_id})
        resolved = 0

        for group in results:
            entity_name = group["entity_name"]
            entities = group["entities"]

            if len(entities) > 1:
                # Create SAME_ENTITY relationships between duplicate entities
                for i, e1 in enumerate(entities):
                    for e2 in entities[i+1:]:
                        await self._run_query("""
                            MATCH (e1:Entity {uuid: $uuid1})
                            MATCH (e2:Entity {uuid: $uuid2})
                            MERGE (e1)-[:SAME_ENTITY]->(e2)
                            MERGE (e2)-[:SAME_ENTITY]->(e1)
                        """, {"uuid1": e1["uuid"], "uuid2": e2["uuid"]})

                resolved += 1
                logger.info(f"Resolved {len(entities)} duplicate entities for: {entity_name}")

        return resolved

    async def batch_create_mentioned_in_edges(
        self,
        file_entity_ids: dict[str, str],  # file_record_id -> file_entity_id
        episode_file_map: dict[str, str],  # episode_uuid -> file_entity_id
    ) -> RelationBuildResult:
        """
        Create MENTIONED_IN edges for all files in a task.

        Args:
            file_entity_ids: Mapping from database file ID to File entity ID.
            episode_file_map: Mapping from episode UUID to File entity ID.

        Returns:
            RelationBuildResult with statistics.
        """
        result = RelationBuildResult()

        # Process each file's episodes
        for file_entity_id in set(episode_file_map.values()):
            try:
                # Find episodes for this file
                episode_uuids = [
                    ep_id for ep_id, ep_file_id in episode_file_map.items()
                    if ep_file_id == file_entity_id
                ]

                # Create edges from entities mentioned in these episodes
                edges = await self.create_mentioned_in_edges_from_episodes(
                    episode_uuids,
                    episode_file_map
                )
                result.mentioned_in_edges_created += edges

            except Exception as e:
                error_msg = f"Error creating edges for file {file_entity_id}: {str(e)}"
                result.errors.append(error_msg)
                logger.error(error_msg)

        logger.info(f"Created {result.mentioned_in_edges_created} MENTIONED_IN edges")
        return result

    async def find_orphan_entities(self, task_id: Optional[str] = None) -> list[dict[str, Any]]:
        """
        Find entities not linked to any File entity.

        Useful for identifying entities that only exist in old-style
        episodes without the new MENTIONED_IN edges.

        Args:
            task_id: Optional task ID filter.

        Returns:
            List of orphan entities.
        """
        if task_id:
            query = """
                MATCH (e:Entity)
                WHERE NOT (e)-[:MENTIONED_IN]->(:File)
                AND EXISTS {
                    MATCH (e)<-[:MENTIONS]-(:Episodic {group_id: $task_id})
                }
                RETURN DISTINCT e.uuid AS uuid, e.name AS name
                LIMIT 1000
            """
            params = {"task_id": task_id}
        else:
            query = """
                MATCH (e:Entity)
                WHERE NOT (e)-[:MENTIONED_IN]->(:File)
                RETURN DISTINCT e.uuid AS uuid, e.name AS name
                LIMIT 1000
            """
            params = {}

        return await self._run_query(query, params)

    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
