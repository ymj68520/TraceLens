"""Part of GraphitiService (split for maintainability).

This mixin contributes a group of methods to the GraphitiService class. It is
mixed into GraphitiService in services/graphiti_service.py and relies on the
instance attributes defined there (self.settings, self._initialized,
self._task_graphs, self._jobs, ...).
"""

import asyncio
import logging
import uuid
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GraphitiStatusMixin:
    """Auto-extracted method group; see module docstring."""

    async def get_status(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get the status of the Graphiti service, optionally for a specific task.
        Does NOT create or initialize a task graph - only reads existing data.
        """
        # Check basic Neo4j connectivity without initializing graphiti
        try:
            connected = await self._check_neo4j_connection()
        except Exception:
            connected = False

        if not connected:
            return {
                "status": "disconnected",
                "neo4j_connected": False,
                "message": "Neo4j is not available. Please check Neo4j is running and credentials are correct.",
                "total_entities": 0,
                "total_relationships": 0,
                "task_id": task_id,
            }

        # For new tasks with no data, return a helpful message
        if task_id:
            try:
                entity_count, rel_count = await self._query_neo4j_counts(task_id)
                if entity_count == 0 and rel_count == 0:
                    return {
                        "status": "empty",
                        "neo4j_connected": True,
                        "message": f"Task '{task_id}' has no graph data yet. Run file analysis and ingestion first.",
                        "total_entities": 0,
                        "total_relationships": 0,
                        "task_id": task_id,
                    }
                return {
                    "status": "active",
                    "neo4j_connected": True,
                    "total_entities": entity_count,
                    "total_relationships": rel_count,
                    "task_id": task_id,
                }
            except Exception as e:
                logger.error(f"Get status query failed: {e}")
                return {
                    "status": "error",
                    "neo4j_connected": True,
                    "message": f"Error querying task data: {str(e)}",
                    "total_entities": 0,
                    "total_relationships": 0,
                    "task_id": task_id,
                }
        else:
            # Overall status (no specific task)
            try:
                entity_count, rel_count = await self._query_neo4j_counts(None)
                return {
                    "status": "connected",
                    "neo4j_connected": True,
                    "total_entities": entity_count,
                    "total_relationships": rel_count,
                    "task_id": task_id,
                }
            except Exception as e:
                logger.error(f"Get status query failed: {e}")
                return {
                    "status": "connected",
                    "neo4j_connected": True,
                    "total_entities": 0,
                    "total_relationships": 0,
                    "task_id": task_id,
                }

    async def _query_neo4j_counts(
        self, task_id: Optional[str] = None
    ) -> tuple:
        """Query Neo4j directly for entity and relationship counts with correct grouping."""
        from neo4j import AsyncGraphDatabase
        uri = self.settings.neo4j_uri
        user = self.settings.neo4j_user
        password = self.settings.neo4j_password
        driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        try:
            async with driver.session() as session:
                if task_id:
                    # Entities are linked to Episodic nodes which have the group_id
                    entity_res = await session.run(
                        "MATCH (e:Episodic {group_id: $gid})-[r:MENTIONS]->(n:Entity) "
                        "RETURN count(DISTINCT n) AS cnt",
                        gid=task_id,
                    )
                    rel_res = await session.run(
                        "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(s:Entity)-[r:RELATES_TO]->(t:Entity) "
                        "WHERE (e)-[:MENTIONS]->(t) "
                        "RETURN count(DISTINCT r) AS cnt",
                        gid=task_id,
                    )
                    
                    entity_row = await entity_res.single()
                    rel_row = await rel_res.single()
                    entity_count = entity_row["cnt"] if entity_row else 0
                    rel_count = rel_row["cnt"] if rel_row else 0
                    
                    logger.info(f"Neo4j counts for task {task_id}: {entity_count} entities, {rel_count} relationships")
                else:
                    entity_res = await session.run("MATCH (n:Entity) RETURN count(n) AS cnt")
                    rel_res = await session.run("MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS cnt")
                    entity_row = await entity_res.single()
                    rel_row = await rel_res.single()
                    entity_count = entity_row["cnt"] if entity_row else 0
                    rel_count = rel_row["cnt"] if rel_row else 0
            return entity_count, rel_count
        finally:
            await driver.close()

    async def _check_neo4j_connection(self) -> bool:
        """Check Neo4j connectivity without initializing graphiti."""
        try:
            from neo4j import AsyncGraphDatabase
            uri = self.settings.neo4j_uri
            user = self.settings.neo4j_user
            password = self.settings.neo4j_password
            driver = AsyncGraphDatabase.driver(
                uri,
                auth=(user, password),
                connection_timeout=getattr(self.settings, "neo4j_connect_timeout", 5.0),
            )
            try:
                async with driver.session() as session:
                    result = await asyncio.wait_for(
                        session.run("RETURN 1"),
                        timeout=getattr(self.settings, "neo4j_query_timeout", 5.0),
                    )
                    await asyncio.wait_for(
                        result.consume(),
                        timeout=getattr(self.settings, "neo4j_query_timeout", 5.0),
                    )
            finally:
                await driver.close()
            return True
        except Exception as e:
            logger.debug(f"Neo4j connection check failed: {e}")
            return False

    async def list_task_graphs(self) -> List[str]:
        """
        List all task IDs that have knowledge graph data.
        Queries Neo4j Episodic nodes to find distinct group_ids.
        """
        try:
            from neo4j import AsyncGraphDatabase
            driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            try:
                async with driver.session() as session:
                    # Query Episodic nodes which contain the group_id
                    result = await session.run(
                        "MATCH (e:Episodic) WHERE e.group_id IS NOT NULL "
                        "RETURN DISTINCT e.group_id AS gid"
                    )
                    task_ids = [record["gid"] async for record in result]
                return task_ids
            finally:
                await driver.close()
        except Exception as e:
            logger.debug(f"list_task_graphs Neo4j query failed: {e}")
            return list(self._task_graphs.keys())

    async def delete_task_graph(self, task_id: str) -> bool:
        """Delete a task-specific graph and its data from Neo4j and cache."""
        deleted = False
        try:
            from neo4j import AsyncGraphDatabase
            driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            async with driver.session() as session:
                await session.run(
                    "MATCH (n {group_id: $gid}) DETACH DELETE n",
                    gid=task_id,
                )
            await driver.close()
            deleted = True
            logger.info(f"Deleted Neo4j data for task: {task_id}")
        except Exception as e:
            logger.error(f"Failed to delete Neo4j data for task {task_id}: {e}")

        if task_id in self._task_graphs:
            try:
                graph = self._task_graphs[task_id]
                if isinstance(graph, dict) and "ingestor" in graph:
                    await graph["ingestor"].close()
                elif hasattr(graph, "close"):
                    await graph.close()
                del self._task_graphs[task_id]
            except Exception as e:
                logger.warning(f"Error closing cached graph for {task_id}: {e}")

        return deleted

