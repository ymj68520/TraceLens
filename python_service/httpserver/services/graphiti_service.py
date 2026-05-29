"""
Graphiti Service - Task-specific knowledge graph integration.

This service provides integration with the Graphiti knowledge graph:
- Task-specific graph namespaces (group_id = task_id)
- Data ingestion from forensic databases
- Entity and relationship search within task scope
- Graph statistics and status per task
"""

import asyncio
import logging
import uuid
import os
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from ..config import Settings

logger = logging.getLogger(__name__)


class GraphitiService:
    """
    Service for Graphiti knowledge graph operations.
    
    Each task has its own graph namespace using task_id as group_id.
    """
    
    def __init__(self, settings: Settings):
        """Initialize the Graphiti service."""
        self.settings = settings
        self._initialized = False
        self._graphiti = None
        
        # Background job tracking
        self._jobs: Dict[str, Dict[str, Any]] = {}
        
        # Cache for task-specific graph instances
        self._task_graphs: Dict[str, Any] = {}
    
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
            from graphiti_integration.config import GraphitiConfig

            # Build GraphitiConfig from server Settings
            config = GraphitiConfig(
                neo4j_uri=self.settings.neo4j_uri,
                neo4j_user=self.settings.neo4j_user,
                neo4j_password=self.settings.neo4j_password,
                llm_base_url=(
                    self.settings.llm_text_base_url.rstrip("/") + "/v1"
                    if not self.settings.llm_text_base_url.endswith("/v1")
                    else self.settings.llm_text_base_url
                ),
                llm_model=self.settings.llm_text_model,
                llm_api_key=self.settings.llm_api_key or "local",
                batch_size=self.settings.graphiti_batch_size,
                max_retries=self.settings.graphiti_max_retries,
                group_id=task_id,  # Per-image isolation
                use_local_llm=self.settings.graphiti_use_local_llm,
            )

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
            from graphiti_integration.config import GraphitiConfig

            # Build GraphitiConfig from server Settings
            config = GraphitiConfig(
                neo4j_uri=self.settings.neo4j_uri,
                neo4j_user=self.settings.neo4j_user,
                neo4j_password=self.settings.neo4j_password,
                llm_base_url=(
                    self.settings.llm_text_base_url.rstrip("/") + "/v1"
                    if not self.settings.llm_text_base_url.endswith("/v1")
                    else self.settings.llm_text_base_url
                ),
                llm_model=self.settings.llm_text_model,
                llm_api_key=self.settings.llm_api_key or "local",
                batch_size=self.settings.graphiti_batch_size,
                max_retries=self.settings.graphiti_max_retries,
                group_id=case_id,  # Case-level isolation for cross-image analysis
                use_local_llm=self.settings.graphiti_use_local_llm,
            )

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
    
    async def start_ingestion(
        self,
        task_id: str,
        include_llm_descriptions: bool = True,
        batch_size: int = 50,
        max_episodes: int = 100,
    ) -> str:
        """
        Start background ingestion of forensic data for a specific task.
        Uses task_id as the graph namespace.
        """
        job_id = str(uuid.uuid4())
        
        self._jobs[job_id] = {
            "status": "running",
            "task_id": task_id,
            "progress": 0.0,
            "entities_created": 0,
            "relationships_created": 0,
            "errors": [],
        }
        
        asyncio.create_task(self._run_ingestion(
            job_id, task_id, include_llm_descriptions, batch_size, max_episodes
        ))
        
        return job_id
    
    async def _run_ingestion(
        self,
        job_id: str,
        task_id: str,
        include_llm_descriptions: bool,
        batch_size: int,
        max_episodes: int,
    ):
        """Run the actual ingestion using MultiSourcePipeline."""
        try:
            # Get task info from C++ backend to find database paths
            from ..services import get_service_manager
            service_manager = get_service_manager()

            # Try to get database info for this task
            task_data = None
            try:
                task_data = await service_manager.cpp_backend.get_task(task_id)
            except Exception as e:
                logger.warning(f"Could not fetch task data from C++ backend: {e}")

            # Build config for multi-source pipeline
            from graphiti_integration.config import GraphitiConfig
            from graphiti_integration.pipeline import MultiSourcePipeline

            config = GraphitiConfig(
                neo4j_uri=self.settings.neo4j_uri,
                neo4j_user=self.settings.neo4j_user,
                neo4j_password=self.settings.neo4j_password,
                llm_base_url=(
                    self.settings.llm_text_base_url.rstrip("/") + "/v1"
                    if not self.settings.llm_text_base_url.endswith("/v1")
                    else self.settings.llm_text_base_url
                ),
                llm_model=self.settings.llm_text_model,
                llm_api_key=self.settings.llm_api_key or "local",
                batch_size=batch_size,
                max_episodes=max_episodes,
                group_id=task_id,
                use_local_llm=self.settings.graphiti_use_local_llm,
                filter_analyzed_only=not include_llm_descriptions,
            )

            # Determine the output_dir and base_name from task data
            # New structure: build/data/tasks/<uuid>/files.db
            output_dir = self.settings.db_output_dir
            base_name = "forensics"
            any_db_path = None

            if task_data:
                # 1. Use the explicit files.db path if available
                any_db_path = task_data.get("output_files_db")
                
                # 2. Extract base_name from image path for potential other databases
                img_path = task_data.get("image_path", "")
                if img_path:
                    base_name = os.path.basename(img_path).split('.')[0]
                
                # 3. If any_db_path is set, ensure output_dir is its parent
                if any_db_path:
                    output_dir = os.path.dirname(any_db_path)
                else:
                    # Fallback to task-specific directory
                    t_out_dir = task_data.get("db_output_dir")
                    if t_out_dir:
                        output_dir = t_out_dir

            # Safe globbing: only use relative patterns
            try:
                # We only need to check if directory exists, MultiSourcePipeline will handle the rest
                if not any_db_path and output_dir and os.path.exists(output_dir):
                    # Only glob if we don't have a direct path, and ensure pattern is simple
                    safe_pattern = f"*{base_name}*.db"
                    logger.info(f"Searching for databases in {output_dir} with pattern {safe_pattern}")
            except Exception as e:
                logger.warning(f"Database discovery warning: {e}")

            pipeline = MultiSourcePipeline(config)

            def progress_cb(source, phase, current, total):
                self._update_job_progress(job_id, current / total if total > 0 else 0)

            result = await pipeline.run(
                base_name=base_name,
                output_dir=output_dir,
                any_db_path=any_db_path,
                group_id=task_id,
                dry_run=False,
                progress_callback=progress_cb,
            )

            self._jobs[job_id].update({
                "status": "completed",
                "progress": 1.0,
                "entities_created": result.total_ingested,
                "relationships_created": 0,
                "sources_processed": result.sources_processed,
                "summary": result.summary(),
            })

        except Exception as e:
            import traceback
            logger.error(f"Ingestion job {job_id} failed: {e}")
            logger.error(traceback.format_exc())
            self._jobs[job_id].update({
                "status": "failed",
                "message": str(e),
            })

    
    def _update_job_progress(self, job_id: str, progress: float):
        """Update job progress."""
        if job_id in self._jobs:
            self._jobs[job_id]["progress"] = progress
    
    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of an ingestion job."""
        return self._jobs.get(job_id)

    async def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a running ingestion job.

        Note: This marks the job as cancelled but doesn't actually stop
        the background task. The task will check the job status on completion.
        """
        if job_id in self._jobs:
            job = self._jobs[job_id]
            if job.get("status") == "running":
                job["status"] = "cancelled"
                job["message"] = "Job cancelled by user"
                logger.info(f"Ingestion job {job_id} marked as cancelled")
                return True
        return False
    
    async def search(
        self,
        query: str,
        task_id: str,
        entity_types: Optional[List[str]] = None,
        limit: int = 100,
        include_relationships: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Search the knowledge graph for a specific task.

        Uses COMBINED_HYBRID_SEARCH_RRF to retrieve edges (facts), nodes (entity summaries),
        and episodes (raw content), then formats them with meaningful text for report generation.

        Each result's ``properties`` dict contains a ``body`` key with the primary text:
          - Edges   → ``fact`` (LLM-extracted relationship text)
          - Nodes   → ``summary`` (entity region summary) or ``name``
          - Episodes → ``content`` (raw episode data)
        """
        if not self._initialized:
            # Fallback: Neo4j full-text search
            return await self._neo4j_text_search(query, task_id, limit)

        try:
            graph_entry = self._task_graphs.get(task_id)
            if graph_entry and isinstance(graph_entry, dict):
                ingestor = graph_entry.get("ingestor")
                if ingestor and ingestor._client:
                    # Use combined hybrid search to get edges + nodes + episodes
                    # (search() only returns edges; search_() returns all layers)
                    from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF
                    from graphiti_core.search.search_filters import SearchFilters

                    config = COMBINED_HYBRID_SEARCH_RRF.model_copy(update={'limit': limit})
                    search_results = await ingestor._client.search_(
                        query=query,
                        config=config,
                        group_ids=[task_id],
                        search_filter=SearchFilters(),
                    )

                    formatted: List[Dict[str, Any]] = []

                    # --- Edges: LLM-extracted facts (relationships) ---
                    edge_scores = getattr(search_results, 'edge_reranker_scores', []) or []
                    for i, edge in enumerate(search_results.edges or []):
                        fact = getattr(edge, 'fact', '') or ''
                        if not fact:
                            continue
                        score = edge_scores[i] if i < len(edge_scores) else 0.5
                        formatted.append({
                            "id": str(getattr(edge, 'uuid', '') or ''),
                            "name": getattr(edge, 'name', '') or '',
                            "type": "relationship",
                            "properties": {
                                "body": fact,
                                "fact": fact,
                                "source": getattr(edge, 'source_node_uuid', ''),
                                "target": getattr(edge, 'target_node_uuid', ''),
                            },
                            "score": score,
                        })

                    # --- Nodes: entity summaries ---
                    node_scores = getattr(search_results, 'node_reranker_scores', []) or []
                    for i, node in enumerate(search_results.nodes or []):
                        summary = getattr(node, 'summary', '') or ''
                        name = getattr(node, 'name', '') or ''
                        text = summary or name
                        if not text:
                            continue
                        score = node_scores[i] if i < len(node_scores) else 0.5
                        formatted.append({
                            "id": str(getattr(node, 'uuid', '') or ''),
                            "name": name,
                            "type": "entity",
                            "properties": {
                                "body": text,
                                "summary": summary,
                                "labels": getattr(node, 'labels', []) or [],
                            },
                            "score": score,
                        })

                    # --- Episodes: raw content ---
                    ep_scores = getattr(search_results, 'episode_reranker_scores', []) or []
                    for i, episode in enumerate(search_results.episodes or []):
                        content = getattr(episode, 'content', '') or ''
                        if not content:
                            continue
                        score = ep_scores[i] if i < len(ep_scores) else 0.5
                        formatted.append({
                            "id": str(getattr(episode, 'uuid', '') or ''),
                            "name": getattr(episode, 'name', '') or '',
                            "type": "episode",
                            "properties": {
                                "body": content,
                                "content": content,
                                "source_description": getattr(episode, 'source_description', ''),
                            },
                            "score": score,
                        })

                    # Sort by score descending, then limit
                    formatted.sort(key=lambda x: x.get('score', 0), reverse=True)
                    return formatted[:limit]

            # Fallback to Neo4j text search
            return await self._neo4j_text_search(query, task_id, limit)
        except Exception as e:
            logger.error(f"Graphiti search failed for task {task_id}: {e}")
            return await self._neo4j_text_search(query, task_id, limit)

    async def _neo4j_text_search(
        self, query: str, task_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fallback text search using Neo4j CONTAINS through Episodic nodes."""
        try:
            from neo4j import AsyncGraphDatabase
            driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            try:
                async with driver.session() as session:
                    result = await session.run(
                        "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) "
                        "WHERE toLower(n.name) CONTAINS toLower($q) "
                        "   OR toLower(coalesce(n.summary, '')) CONTAINS toLower($q) "
                        "RETURN DISTINCT n.uuid AS id, n.name AS name, labels(n)[0] AS type "
                        "LIMIT $lim",
                        gid=task_id, q=query, lim=limit,
                    )
                    rows = [dict(r) async for r in result]
                return [
                    {
                        "id": r.get("id", ""),
                        "name": r.get("name", ""),
                        "type": r.get("type", "unknown"),
                        "properties": {},
                        "score": 0.8,
                    }
                    for r in rows
                ]
            finally:
                await driver.close()
        except Exception as e:
            logger.error(f"Neo4j text search failed: {e}")
            return []

    async def list_entities(
        self,
        task_id: str,
        entity_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List entities in the knowledge graph for a specific task.
        """
        try:
            from neo4j import AsyncGraphDatabase
            driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            try:
                async with driver.session() as session:
                    skip = (page - 1) * page_size
                    if entity_type:
                        count_res = await session.run(
                            "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) WHERE $et IN labels(n) "
                            "RETURN count(DISTINCT n) AS cnt",
                            gid=task_id, et=entity_type,
                        )
                        data_res = await session.run(
                            "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) WHERE $et IN labels(n) "
                            "RETURN DISTINCT n.uuid AS id, n.name AS name, labels(n) AS type "
                            "SKIP $skip LIMIT $lim",
                            gid=task_id, et=entity_type, skip=skip, lim=page_size,
                        )
                    else:
                        count_res = await session.run(
                            "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) "
                            "RETURN count(DISTINCT n) AS cnt",
                            gid=task_id,
                        )
                        data_res = await session.run(
                            "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) "
                            "RETURN DISTINCT n.uuid AS id, n.name AS name, labels(n) AS type "
                            "SKIP $skip LIMIT $lim",
                            gid=task_id, skip=skip, lim=page_size,
                        )
                    count_row = await count_res.single()
                    total = count_row["cnt"] if count_row else 0
                    entities = [dict(record) async for record in data_res]
                return entities, total
            finally:
                await driver.close()
        except Exception as e:
            logger.error(f"List entities failed for task {task_id}: {e}")
            return [], 0

    async def list_relationships(
        self,
        task_id: str,
        relationship_type: Optional[str] = None,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List relationships in the knowledge graph for a specific task.
        In Graphiti, relationships are between entities mentioned in episodes of the task.
        """
        try:
            from neo4j import AsyncGraphDatabase
            driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            try:
                async with driver.session() as session:
                    skip = (page - 1) * page_size

                    # Build match clause - relationships between entities mentioned in task's episodes
                    match_clause = "MATCH (e:Episodic {group_id: $gid})-[m1:MENTIONS]->(s:Entity)-[r:RELATES_TO]->(t:Entity)"

                    # Build where conditions - ensure target entity is also mentioned in task's episodes
                    where_clauses = ["(e)-[:MENTIONS]->(t)"]

                    params = {"gid": task_id, "skip": skip, "lim": page_size}

                    if relationship_type:
                        where_clauses.append("r.name = $rt")
                        params["rt"] = relationship_type
                    if source_id:
                        where_clauses.append("s.uuid = $sid")
                        params["sid"] = source_id
                    if target_id:
                        where_clauses.append("t.uuid = $tid")
                        params["tid"] = target_id

                    where_str = " WHERE " + " AND ".join(where_clauses)

                    # Count query
                    count_res = await session.run(
                        f"{match_clause} {where_str} RETURN count(DISTINCT r) AS cnt",
                        **params
                    )

                    # Data query
                    data_res = await session.run(
                        f"{match_clause} {where_str} "
                        "RETURN DISTINCT s.uuid AS source_id, s.name AS source_name, "
                        "       t.uuid AS target_id, t.name AS target_name, r.name AS type, "
                        "       r.uuid AS id "
                        "SKIP $skip LIMIT $lim",
                        **params
                    )

                    count_row = await count_res.single()
                    total = count_row["cnt"] if count_row else 0
                    rels = [dict(record) async for record in data_res]
                return rels, total
            finally:
                await driver.close()
        except Exception as e:
            logger.error(f"List relationships failed for task {task_id}: {e}")
            return [], 0

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

    async def _check_neo4j_connection(self) -> bool:
        """Check Neo4j connectivity without initializing graphiti."""
        try:
            from neo4j import AsyncGraphDatabase
            uri = self.settings.neo4j_uri
            user = self.settings.neo4j_user
            password = self.settings.neo4j_password
            driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
            async with driver.session() as session:
                await session.run("RETURN 1")
            await driver.close()
            return True
        except Exception as e:
            logger.debug(f"Neo4j connection check failed: {e}")
            return False

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

    async def get_graph_data(
        self,
        task_id: str,
        max_nodes: int = 200,
    ) -> tuple:
        """
        Get graph data for visualization filtered by task_id.
        """
        from neo4j import AsyncGraphDatabase
        driver = AsyncGraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
        )
        try:
            async with driver.session() as session:
                # Fetch entities linked to episodes of this task
                node_result = await session.run(
                    "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) "
                    "RETURN DISTINCT n.uuid AS id, n.name AS name, "
                    "       labels(n) AS labels, n.summary AS summary "
                    "LIMIT $lim",
                    gid=task_id, lim=max_nodes,
                )
                node_rows = [dict(r) async for r in node_result]

                node_ids = {r["id"] for r in node_rows}

                # Fetch relationships between those nodes
                rel_result = await session.run(
                    "MATCH (s:Entity)-[r:RELATES_TO]->(t:Entity) "
                    "WHERE s.uuid IN $ids AND t.uuid IN $ids "
                    "RETURN s.uuid AS source, t.uuid AS target, "
                    "       r.name AS label "
                    "LIMIT $lim",
                    ids=list(node_ids), lim=max_nodes * 3,
                )
                rel_rows = [dict(r) async for r in rel_result]

            nodes = [
                {
                    "id": r["id"],
                    "name": r["name"] or r["id"],
                    "label": (r["labels"][0] if isinstance(r.get("labels"), list) and r["labels"] else "Entity"),
                    "summary": r.get("summary") or "",
                }
                for r in node_rows
                if r.get("id")
            ]

            links = [
                {
                    "source": r["source"],
                    "target": r["target"],
                    "label": r.get("label", "RELATES_TO"),
                }
                for r in rel_rows
                if r.get("source") and r.get("target")
            ]

            return nodes, links
        finally:
            await driver.close()

    async def ingest_case_data(
        self,
        case_id: str,
        task_ids: List[str],
        files_db_paths: List[str],
        events_db_paths: Optional[List[str]] = None,
        progress_callback=None,
    ) -> bool:
        """
        Ingest data from multiple tasks into a case-level knowledge graph.

        This method aggregates file descriptions and event clusters from all images
        in a case and ingests them into a unified case-level graph for cross-image analysis.

        Args:
            case_id: Case identifier (used as group_id for case-level graph)
            task_ids: List of task IDs for the images in this case
            files_db_paths: List of _files.db paths
            events_db_paths: Optional list of _events.db paths
            progress_callback: Optional progress callback

        Returns:
            True if ingestion succeeded, False otherwise
        """
        if not self._initialized:
            await self.initialize()

        if not events_db_paths:
            events_db_paths = []

        try:
            from graphiti_integration.toon_transformer import EpisodeData
            from datetime import datetime
            import sqlite3
            import json

            # Get or create case-level graph
            graph_entry = await self._get_case_graph(case_id)
            if not graph_entry or not isinstance(graph_entry, dict):
                logger.error(f"Could not get case graph for {case_id}")
                return False

            ingestor = graph_entry.get("ingestor")
            if not ingestor:
                logger.error(f"No ingestor available for case {case_id}")
                return False

            episodes = []
            total_files = 0
            total_clusters = 0

            # Aggregate file descriptions from all images
            for idx, (task_id, files_db) in enumerate(zip(task_ids, files_db_paths)):
                try:
                    if not Path(files_db).exists():
                        logger.warning(f"[{case_id}] Files database {idx+1} not found: {files_db}")
                        continue

                    with sqlite3.connect(files_db, timeout=10) as conn:
                        conn.row_factory = sqlite3.Row

                        # Get file descriptions
                        from ..services.case_analysis.db_utils import ensure_file_descriptions_schema
                        ensure_file_descriptions_schema(conn)

                        cur = conn.execute(
                            "SELECT file_path, description FROM file_descriptions WHERE is_relevant = 1 AND description IS NOT NULL"
                        )
                        rows = cur.fetchall()

                        for row in rows:
                            file_path = row["file_path"]
                            description = row["description"]

                            # Tag with source image
                            tagged_path = f"[IMG{idx+1}] {file_path}"

                            # Chunk long descriptions
                            chunks = self._chunk_text_for_graph(description, max_chars=3000)
                            for j, chunk in enumerate(chunks):
                                ep_name = f"文件分析: {tagged_path}"
                                if len(chunks) > 1:
                                    ep_name += f" (第{j+1}部分)"

                                episodes.append(EpisodeData(
                                    name=ep_name,
                                    episode_body=json.dumps({
                                        "file_path": file_path,
                                        "source_image": f"IMG{idx+1}",
                                        "task_id": task_id,
                                        "analysis": chunk
                                    }, ensure_ascii=False),
                                    source_description=f"LLM分析结果 - 镜像{idx+1} - {file_path}",
                                    reference_time=datetime.now(),
                                    file_path=file_path,
                                    file_id=0,
                                    category="file_description"
                                ))
                                total_files += 1

                    if progress_callback:
                        await progress_callback("aggregating_files", f"已聚合镜像{idx+1}的文件分析结果")

                except Exception as e:
                    logger.warning(f"[{case_id}] Failed to aggregate files from image {idx+1}: {e}")

            # Aggregate event clusters from all images
            for idx, (task_id, events_db) in enumerate(zip(task_ids, events_db_paths)):
                try:
                    if not events_db or not Path(events_db).exists():
                        continue

                    with sqlite3.connect(events_db, timeout=10) as conn:
                        conn.row_factory = sqlite3.Row

                        # Get event clusters with LLM analysis
                        cur = conn.execute("""
                            SELECT DISTINCT event_type, llm_description, llm_summary,
                                   (timestamp / 60) as time_window
                            FROM events
                            WHERE llm_description IS NOT NULL
                            GROUP BY event_type, time_window
                        """)
                        rows = cur.fetchall()

                        for row in rows:
                            description = row["llm_description"] or row["llm_summary"] or ""
                            event_type = row["event_type"]
                            time_window = row["time_window"]

                            if description:
                                # Chunk long descriptions
                                chunks = self._chunk_text_for_graph(description, max_chars=3000)
                                for j, chunk in enumerate(chunks):
                                    ep_name = f"事件簇分析: 镜像{idx+1} - {event_type} @ {time_window}"
                                    if len(chunks) > 1:
                                        ep_name += f" (第{j+1}部分)"

                                    episodes.append(EpisodeData(
                                        name=ep_name,
                                        episode_body=json.dumps({
                                            "event_type": event_type,
                                            "time_window": time_window,
                                            "source_image": f"IMG{idx+1}",
                                            "task_id": task_id,
                                            "analysis": chunk
                                        }, ensure_ascii=False),
                                        source_description=f"事件簇LLM分析 - 镜像{idx+1} - {event_type}",
                                        reference_time=datetime.now(),
                                        file_path="",
                                        file_id=0,
                                        category="event_cluster_description"
                                    ))
                                    total_clusters += 1

                    if progress_callback:
                        await progress_callback("aggregating_clusters", f"已聚合镜像{idx+1}的事件簇分析结果")

                except Exception as e:
                    logger.warning(f"[{case_id}] Failed to aggregate clusters from image {idx+1}: {e}")

            if not episodes:
                logger.info(f"[{case_id}] No episodes to ingest into case graph")
                return True

            # Batch ingest all episodes
            logger.info(f"[{case_id}] Ingesting {len(episodes)} episodes ({total_files} files + {total_clusters} clusters) into case-level graph")
            if progress_callback:
                await progress_callback("ingesting", f"正在摄入 {len(episodes)} 个分析结果到知识图谱...")

            result = await ingestor.batch_ingest(
                episodes=episodes,
                group_id=case_id,
            )

            success_count = getattr(result, 'successful', 0)
            total_count = getattr(result, 'total_episodes', len(episodes))

            logger.info(f"[{case_id}] Case-level graph ingestion complete: {success_count}/{total_count} successful")

            if progress_callback:
                await progress_callback("completed", f"知识图谱摄入完成：{success_count}/{total_count} 成功")

            return success_count > 0

        except Exception as e:
            logger.error(f"[{case_id}] Case-level graph ingestion failed: {e}", exc_info=True)
            return False

    @staticmethod
    def _chunk_text_for_graph(text: str, max_chars: int = 3000) -> List[str]:
        """Split text into chunks for graph ingestion."""
        if len(text) <= max_chars:
            return [text]

        chunks = []
        paragraphs = text.split("\n\n")
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 2 > max_chars and current:
                chunks.append(current.strip())
                current = para
            else:
                current = current + "\n\n" + para if current else para
        if current.strip():
            chunks.append(current.strip())
        return chunks if chunks else [text]

    # ─────────────────────────────────────────────────────────────────────────────
    # Incremental Case Graph Ingestion
    # ─────────────────────────────────────────────────────────────────────────────

    async def ingest_case_data_incremental(
        self,
        case_id: str,
        new_task_ids: List[str],
        existing_task_ids: List[str],
        files_db_paths: List[str],
        events_db_paths: Optional[List[str]] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        增量摄入案件数据到知识图谱

        Unlike ingest_case_data which processes ALL tasks, this method
        only ingests data from new tasks while establishing relationships
        with existing tasks' data in the graph.

        Args:
            case_id: Case identifier (used as group_id)
            new_task_ids: List of new task IDs to ingest
            existing_task_ids: List of existing task IDs (for relationship linking)
            files_db_paths: List of _files.db paths (for all tasks)
            events_db_paths: Optional list of _events.db paths
            progress_callback: Optional progress callback (stage, message)

        Returns:
            Dict with ingestion statistics
        """
        if not self._initialized:
            await self.initialize()

        if not self._graphiti_class:
            logger.warning(f"[{case_id}] Graphiti not available, skipping incremental ingestion")
            return {"skipped": True, "reason": "Graphiti not available"}

        if events_db_paths is None:
            events_db_paths = []

        episodes = []
        total_files = 0
        total_clusters = 0

        logger.info(f"[{case_id}] Starting incremental graph ingestion: "
                    f"{len(new_task_ids)} new tasks, {len(existing_task_ids)} existing tasks")

        try:
            from graphiti_integration import GraphitiIngestor

            ingestor = GraphitiIngestor(
                neo4j_uri=self.settings.neo4j_uri,
                neo4j_user=self.settings.neo4j_user,
                neo4j_password=self.settings.neo4j_password,
                llm_base_url=self.settings.llm_text_base_url.rstrip("/") + "/v1",
                llm_model=self.settings.llm_text_model,
                llm_api_key=self.settings.llm_api_key or "local",
                group_id=case_id,  # Case-level graph
            )

            # Only process NEW tasks (not existing ones)
            for idx, task_id in enumerate(new_task_ids):
                if idx >= len(files_db_paths):
                    break

                files_db = files_db_paths[idx]

                # Aggregate file descriptions from new tasks only
                try:
                    if not files_db or not Path(files_db).exists():
                        continue

                    with sqlite3.connect(files_db, timeout=10) as conn:
                        conn.row_factory = sqlite3.Row

                        # Get analyzed files from this task
                        cur = conn.execute("""
                            SELECT DISTINCT file_path, description, summary
                            FROM file_descriptions
                            WHERE description IS NOT NULL AND description != ''
                            LIMIT 500
                        """)
                        rows = cur.fetchall()

                        for row in rows:
                            file_path = row["file_path"]
                            description = row["description"] or row["summary"] or ""

                            if description:
                                # Chunk long descriptions
                                chunks = self._chunk_text_for_graph(description, max_chars=3000)
                                for j, chunk in enumerate(chunks):
                                    ep_name = f"文件分析: {Path(file_path).name}"
                                    if len(chunks) > 1:
                                        ep_name += f" (第{j+1}部分)"

                                    episodes.append(EpisodeData(
                                        name=ep_name,
                                        episode_body=json.dumps({
                                            "file_path": file_path,
                                            "task_id": task_id,
                                            "source_image": f"NEW",
                                            "related_tasks": existing_task_ids,  # Link to existing
                                            "analysis": chunk
                                        }, ensure_ascii=False),
                                        source_description=f"LLM分析结果 - 新任务 {task_id[:8]} - {file_path}",
                                        reference_time=datetime.now(),
                                        file_path=file_path,
                                        file_id=0,
                                        category="file_description"
                                    ))
                                    total_files += 1

                        if progress_callback:
                            await progress_callback("aggregating_new", f"已聚合新任务{idx+1}的文件分析结果")

                except Exception as e:
                    logger.warning(f"[{case_id}] Failed to aggregate files from new task {task_id[:8]}: {e}")

            # Aggregate event clusters from new tasks only
            for idx, task_id in enumerate(new_task_ids):
                if idx >= len(events_db_paths):
                    break

                events_db = events_db_paths[idx]

                try:
                    if not events_db or not Path(events_db).exists():
                        continue

                    with sqlite3.connect(events_db, timeout=10) as conn:
                        conn.row_factory = sqlite3.Row

                        # Get event clusters with LLM analysis
                        cur = conn.execute("""
                            SELECT DISTINCT event_type, llm_description, llm_summary,
                                   (timestamp / 60) as time_window
                            FROM events
                            WHERE llm_description IS NOT NULL
                            GROUP BY event_type, time_window
                        """)
                        rows = cur.fetchall()

                        for row in rows:
                            description = row["llm_description"] or row["llm_summary"] or ""
                            event_type = row["event_type"]
                            time_window = row["time_window"]

                            if description:
                                # Chunk long descriptions
                                chunks = self._chunk_text_for_graph(description, max_chars=3000)
                                for j, chunk in enumerate(chunks):
                                    ep_name = f"事件簇分析: 新任务 {task_id[:8]} - {event_type} @ {time_window}"
                                    if len(chunks) > 1:
                                        ep_name += f" (第{j+1}部分)"

                                    episodes.append(EpisodeData(
                                        name=ep_name,
                                        episode_body=json.dumps({
                                            "event_type": event_type,
                                            "time_window": time_window,
                                            "task_id": task_id,
                                            "source_image": "NEW",
                                            "related_tasks": existing_task_ids,
                                            "analysis": chunk
                                        }, ensure_ascii=False),
                                        source_description=f"事件簇LLM分析 - 新任务 {task_id[:8]} - {event_type}",
                                        reference_time=datetime.now(),
                                        file_path="",
                                        file_id=0,
                                        category="event_cluster_description"
                                    ))
                                    total_clusters += 1

                    if progress_callback:
                        await progress_callback("aggregating_clusters_new", f"已聚合新任务{idx+1}的事件簇分析结果")

                except Exception as e:
                    logger.warning(f"[{case_id}] Failed to aggregate clusters from new task {task_id[:8]}: {e}")

            if not episodes:
                logger.info(f"[{case_id}] No new episodes to ingest into case graph")
                return {
                    "success": True,
                    "episodes_ingested": 0,
                    "files": 0,
                    "clusters": 0,
                }

            # Batch ingest all new episodes
            logger.info(f"[{case_id}] Incrementally ingesting {len(episodes)} new episodes "
                        f"({total_files} files + {total_clusters} clusters) into case-level graph")
            if progress_callback:
                await progress_callback("ingesting", f"正在摄入 {len(episodes)} 个新分析结果到知识图谱...")

            result = await ingestor.batch_ingest(
                episodes=episodes,
                group_id=case_id,
            )

            success_count = getattr(result, 'successful', 0)
            total_count = getattr(result, 'total_episodes', len(episodes))

            logger.info(f"[{case_id}] Incremental case-level graph ingestion complete: "
                        f"{success_count}/{total_count} successful")

            if progress_callback:
                await progress_callback("completed", f"增量知识图谱摄入完成：{success_count}/{total_count} 成功")

            return {
                "success": success_count > 0,
                "episodes_ingested": success_count,
                "total_episodes": total_count,
                "files": total_files,
                "clusters": total_clusters,
            }

        except Exception as e:
            logger.error(f"[{case_id}] Incremental case-level graph ingestion failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }
