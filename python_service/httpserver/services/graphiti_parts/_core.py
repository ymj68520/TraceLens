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


class GraphitiCoreMixin:
    """Auto-extracted method group; see module docstring."""

    async def _get_shared_driver(self):
        """Lazily create the pooled read-path Neo4j driver (SPEC §A2).

        Every read endpoint previously built a fresh driver per request;
        a single shared driver reuses the connection pool and applies the
        connect timeout consistently.
        """
        if self._neo_driver is None:
            from neo4j import AsyncGraphDatabase
            self._neo_driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
                connection_timeout=getattr(self.settings, "neo4j_connect_timeout", 5.0),
            )
        return self._neo_driver

    async def _run_read_query(self, query: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> List[Any]:
        """Run one read query on the shared driver with a hard timeout.

        No read path may wait on Neo4j without a ceiling: a stalled query
        must surface as an error (HTTP 5xx / degraded status) rather than
        hang the page's spinner forever.
        """
        driver = await self._get_shared_driver()

        async def _run() -> List[Any]:
            async with driver.session() as session:
                result = await session.run(query, **(params or {}))
                return [record async for record in result]

        effective_timeout = timeout if timeout is not None else getattr(
            self.settings, "neo4j_query_timeout", 5.0
        )
        return await asyncio.wait_for(_run(), timeout=effective_timeout)

    def lock_for_group(self, group_id: str) -> asyncio.Lock:
        """Single-flight lock for one graph group (SPEC §B1).

        Graphiti assumes sequential ``add_episode`` within a group. Three
        ingestion streams exist (pipeline KG phase, job worker, re-analysis
        fire-and-forget) and used to overlap on the same group — racing the
        dedup layer into duplicate entities and piling up on the single-slot
        LLM. Every add_episode entry point wraps its batch region with this
        lock keyed by group_id.
        """
        lock = self._ingest_locks.get(group_id)
        if lock is None:
            lock = asyncio.Lock()
            self._ingest_locks[group_id] = lock
        return lock

    async def initialize(self):
        """Initialize the Graphiti service with graceful fallback."""
        if self._initialized:
            return

        # First check if Neo4j is available
        neo4j_available = await self._check_neo4j_connection()
        if not neo4j_available:
            logger.warning("Neo4j is not available. Graphiti service will be disabled.")
            logger.warning("To enable Graphiti: 1) Ensure Neo4j is running, 2) Check NEO4J_URI/USER/PASSWORD in .env")
            self._initialized = True  # Mark as initialized but disabled
            return

        try:
            from graphiti_integration import GraphitiIngestor

            self._graphiti_class = GraphitiIngestor
            self._initialized = True
            logger.info("Graphiti service initialized successfully")
        except ImportError as e:
            logger.warning(f"Graphiti integration not available: {e}")
            logger.warning("To enable Graphiti: pip install graphiti-core>=0.3.0")
            self._initialized = True  # Mark as initialized but disabled
        except Exception as e:
            logger.error(f"Graphiti service initialization failed: {e}")
            self._initialized = True  # Mark as initialized but disabled

    def _build_graphiti_config(self, group_id: str):
        """
        Build a GraphitiConfig from server Settings.

        Centralised so every entry point (task graph, case graph, pipeline)
        honours the same .env settings — including include_full_description and
        max_episode_tokens, which were previously dropped (leaving episodes
        without the llm_description the entity-extraction LLM needs).
        """
        from graphiti_integration.config import GraphitiConfig

        base = self.settings.llm_text_base_url.rstrip("/")
        llm_base_url = base if base.endswith("/v1") else base + "/v1"

        return GraphitiConfig(
            neo4j_uri=self.settings.neo4j_uri,
            neo4j_user=self.settings.neo4j_user,
            neo4j_password=self.settings.neo4j_password,
            llm_base_url=llm_base_url,
            llm_model=self.settings.llm_text_model,
            llm_api_key=self.settings.llm_api_key or "local",
            batch_size=self.settings.graphiti_batch_size,
            max_retries=self.settings.graphiti_max_retries,
            group_id=group_id,
            use_local_llm=self.settings.graphiti_use_local_llm,
            include_full_description=self.settings.graphiti_include_full_desc,
            max_episode_tokens=self.settings.graphiti_max_episode_tokens,
        )

    async def _get_task_graph(self, task_id: str):
        """
        Get or create a Graphiti instance for a specific task.
        Each task uses its task_id as the group_id for graph isolation.
        """
        if task_id in self._task_graphs:
            return self._task_graphs[task_id]

        if not self._initialized:
            await self.initialize()

        try:
            # Build GraphitiConfig from server Settings
            config = self._build_graphiti_config(group_id=task_id)

            # Create ingestor with proper config
            from graphiti_integration import GraphitiIngestor
            ingestor = GraphitiIngestor(config)
            await ingestor.initialize()

            self._task_graphs[task_id] = {
                "config": config,
                "ingestor": ingestor,
            }
            logger.info(f"Created Graphiti graph for task: {task_id}")
            return self._task_graphs[task_id]
        except Exception as e:
            logger.error(f"Failed to create task graph for {task_id}: {e}")
            raise

    async def _get_case_graph(self, case_id: str):
        """
        Get or create a Graphiti instance for a case (cross-image analysis).
        Uses case_id as the group_id for case-level graph isolation.
        """
        if case_id in self._task_graphs:
            return self._task_graphs[case_id]

        if not self._initialized:
            await self.initialize()

        try:
            # Build GraphitiConfig from server Settings
            config = self._build_graphiti_config(group_id=case_id)

            # Create ingestor with proper config
            from graphiti_integration import GraphitiIngestor
            ingestor = GraphitiIngestor(config)
            await ingestor.initialize()

            self._task_graphs[case_id] = {
                "config": config,
                "ingestor": ingestor,
            }
            logger.info(f"Created Graphiti graph for case: {case_id}")
            return self._task_graphs[case_id]
        except Exception as e:
            logger.error(f"Failed to create case graph for {case_id}: {e}")
            raise

    async def shutdown(self):
        """Shutdown all Graphiti connections."""
        for task_id, graph in self._task_graphs.items():
            try:
                if isinstance(graph, dict) and "ingestor" in graph:
                    await graph["ingestor"].close()
                elif hasattr(graph, 'close'):
                    await graph.close()
            except Exception as e:
                logger.warning(f"Error closing graph for task {task_id}: {e}")
        self._task_graphs.clear()

        if self._neo_driver is not None:
            try:
                await self._neo_driver.close()
            except Exception as e:
                logger.warning(f"Error closing shared Neo4j driver: {e}")
            finally:
                self._neo_driver = None

        self._initialized = False

    async def health_check(self, task_id: Optional[str] = None) -> bool:
        """Check if Graphiti/Neo4j is healthy."""
        if not self._initialized:
            return False

        # Check basic Neo4j connectivity
        try:
            if not await self._check_neo4j_connection():
                return False
        except Exception:
            return False

        # If task_id specified, check if task graph exists
        if task_id:
            try:
                entity_count, rel_count = await self._query_neo4j_counts(task_id)
                # Consider healthy if we can query (even if empty)
                return True
            except Exception as e:
                logger.debug(f"Task graph health check for {task_id}: {e}")
                return False

        return True

