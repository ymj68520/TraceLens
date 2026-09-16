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
        """Query Neo4j for entity and relationship counts of a graph scope.

        Counts are index-direct on ``group_id`` (SPEC §A2): the previous
        MENTIONS-walk with a per-row existence probe grew with the number
        of episodes and ran on every page load. The direct count reports
        the graph scope's own nodes/edges (slightly broader: it includes
        entities shared across groups), which is the more accurate "size
        of this task's graph".
        """
        if task_id:
            entity_rows = await self._run_read_query(
                "MATCH (n:Entity {group_id: $gid}) RETURN count(n) AS cnt",
                {"gid": task_id},
            )
            rel_rows = await self._run_read_query(
                "MATCH ()-[r:RELATES_TO {group_id: $gid}]->() RETURN count(r) AS cnt",
                {"gid": task_id},
            )
        else:
            entity_rows = await self._run_read_query(
                "MATCH (n:Entity) RETURN count(n) AS cnt"
            )
            rel_rows = await self._run_read_query(
                "MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS cnt"
            )
        entity_count = entity_rows[0]["cnt"] if entity_rows else 0
        rel_count = rel_rows[0]["cnt"] if rel_rows else 0
        logger.info(
            f"Neo4j counts for task {task_id}: {entity_count} entities, {rel_count} relationships"
        )
        return entity_count, rel_count

    async def _check_neo4j_connection(self) -> bool:
        """Check Neo4j connectivity using the shared pooled driver."""
        try:
            driver = await self._get_shared_driver()

            async def _probe() -> None:
                async with driver.session() as session:
                    result = await session.run("RETURN 1")
                    await result.consume()

            await asyncio.wait_for(
                _probe(),
                timeout=getattr(self.settings, "neo4j_query_timeout", 5.0),
            )
            return True
        except Exception as e:
            logger.debug(f"Neo4j connection check failed: {e}")
            return False

    async def list_task_graphs(self) -> List[str]:
        """
        List all task IDs that have knowledge graph data.
        Queries Neo4j Episodic nodes to find distinct group_ids.

        Results are cached for 5 s (SPEC §A3): the DISTINCT scan ran on
        every KG page load; a short TTL keeps the list fresh enough for
        UI purposes while shielding Neo4j from burst traffic.
        """
        import time

        now = time.monotonic()
        if (
            self._task_graphs_cache is not None
            and now - self._task_graphs_cache_at < 5.0
        ):
            return list(self._task_graphs_cache)

        try:
            rows = await self._run_read_query(
                "MATCH (e:Episodic) WHERE e.group_id IS NOT NULL "
                "RETURN DISTINCT e.group_id AS gid LIMIT 1000"
            )
            task_ids = [row["gid"] for row in rows if row.get("gid")]
            self._task_graphs_cache = task_ids
            self._task_graphs_cache_at = now
            return list(task_ids)
        except Exception as e:
            logger.debug(f"list_task_graphs Neo4j query failed: {e}")
            return list(self._task_graphs.keys())

    async def delete_task_graph(self, task_id: str) -> bool:
        """Delete a task-specific graph and its data from Neo4j and cache."""
        deleted = False
        try:
            # DETACH DELETE of a whole task graph can outlast the default
            # read timeout; give it a bounded-but-generous ceiling.
            await self._run_read_query(
                "MATCH (n {group_id: $gid}) DETACH DELETE n",
                {"gid": task_id},
                timeout=60.0,
            )
            self._task_graphs_cache = None  # list changed; drop the cache
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

