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
        """Initialize the Graphiti connection."""
        if self._initialized:
            return
        
        try:
            from graphiti_integration import GraphitiIngestor
            
            self._graphiti_class = GraphitiIngestor
            self._initialized = True
            logger.info("Graphiti service initialized")
        except ImportError as e:
            logger.warning(f"Graphiti integration not available: {e}")
            raise
        except Exception as e:
            logger.error(f"Graphiti service initialization failed: {e}")
            raise
    
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
        
        try:
            if task_id:
                graph = await self._get_task_graph(task_id)
                if isinstance(graph, dict) and "ingestor" in graph:
                    return True
                if hasattr(graph, 'check_connection'):
                    return await graph.check_connection()
            return True
        except Exception as e:
            logger.warning(f"Graphiti health check failed: {e}")
            return False
    
    async def start_ingestion(
        self,
        task_id: str,
        include_llm_descriptions: bool = True,
        batch_size: int = 50,
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
            job_id, task_id, include_llm_descriptions, batch_size
        ))
        
        return job_id
    
    async def _run_ingestion(
        self,
        job_id: str,
        task_id: str,
        include_llm_descriptions: bool,
        batch_size: int,
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
                group_id=task_id,
                use_local_llm=self.settings.graphiti_use_local_llm,
                filter_analyzed_only=not include_llm_descriptions,
            )

            # Determine the output_dir and base_name from task data
            output_dir = self.settings.db_output_dir
            base_name = None
            any_db_path = None

            if task_data:
                # Try to extract image name from task data
                if isinstance(task_data, dict):
                    base_name = task_data.get("image_name") or task_data.get("image_path") or task_data.get("name")
                    if base_name and "." in base_name:
                        base_name = base_name.rsplit(".", 1)[0]
                        
                    t_out_dir = task_data.get("db_output_dir") or task_data.get("output_dir")
                    if t_out_dir:
                        output_dir = t_out_dir
                        
                    # Also try to search in build directory as a fallback
                    if not any(Path(output_dir).glob(f"{base_name}*.db")):
                        if any(Path("build").glob(f"{base_name}*.db")):
                            output_dir = "build"
                            
                    any_db_path = task_data.get("output_files_db") or task_data.get("db_path")

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
            logger.error(f"Ingestion job {job_id} failed: {e}")
            self._jobs[job_id].update({
                "status": "failed",
                "errors": [str(e)],
            })
    
    def _update_job_progress(self, job_id: str, progress: float):
        """Update job progress."""
        if job_id in self._jobs:
            self._jobs[job_id]["progress"] = progress
    
    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of an ingestion job."""
        return self._jobs.get(job_id)
    
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
        Uses graphiti ingestor's search if initialized, else falls back to Neo4j text search.
        """
        if not self._initialized:
            # Fallback: Neo4j full-text search
            return await self._neo4j_text_search(query, task_id, limit)
        
        try:
            graph_entry = self._task_graphs.get(task_id)
            if graph_entry and isinstance(graph_entry, dict):
                ingestor = graph_entry.get("ingestor")
                if ingestor and ingestor._client:
                    results = await ingestor._client.search(
                        query=query,
                        group_ids=[task_id],
                        num_results=limit,
                    )
                    return [
                        {
                            "id": str(getattr(r, "uuid", "") or ""),
                            "name": getattr(r, "name", "") or "",
                            "type": getattr(r, "entity_type", "unknown") or "unknown",
                            "properties": {},
                            "score": getattr(r, "score", 0.5) or 0.5,
                        }
                        for r in (results or [])
                    ]
            # Fallback to Neo4j text search
            return await self._neo4j_text_search(query, task_id, limit)
        except Exception as e:
            logger.error(f"Graphiti search failed for task {task_id}: {e}")
            return await self._neo4j_text_search(query, task_id, limit)

    async def _neo4j_text_search(
        self, query: str, task_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fallback text search using Neo4j CONTAINS."""
        try:
            from neo4j import AsyncGraphDatabase
            driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            try:
                async with driver.session() as session:
                    result = await session.run(
                        "MATCH (n:Entity {group_id: $gid}) "
                        "WHERE toLower(n.name) CONTAINS toLower($q) "
                        "   OR toLower(coalesce(n.summary, '')) CONTAINS toLower($q) "
                        "RETURN n.uuid AS id, n.name AS name, n.entity_type AS type "
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
        Queries Neo4j directly instead of through graphiti ingestor.
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
                            "MATCH (n:Entity {group_id: $gid}) WHERE $et IN n.labels "
                            "RETURN count(n) AS cnt",
                            gid=task_id, et=entity_type,
                        )
                        data_res = await session.run(
                            "MATCH (n:Entity {group_id: $gid}) WHERE $et IN n.labels "
                            "RETURN n.uuid AS id, n.name AS name, n.labels AS type "
                            "SKIP $skip LIMIT $lim",
                            gid=task_id, et=entity_type, skip=skip, lim=page_size,
                        )
                    else:
                        count_res = await session.run(
                            "MATCH (n:Entity {group_id: $gid}) RETURN count(n) AS cnt",
                            gid=task_id,
                        )
                        data_res = await session.run(
                            "MATCH (n:Entity {group_id: $gid}) "
                            "RETURN n.uuid AS id, n.name AS name, n.labels AS type "
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
        Queries Neo4j directly.
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
                    count_res = await session.run(
                        "MATCH (s:Entity {group_id: $gid})-[r:RELATES_TO]->(t:Entity {group_id: $gid}) "
                        "RETURN count(r) AS cnt",
                        gid=task_id,
                    )
                    data_res = await session.run(
                        "MATCH (s:Entity {group_id: $gid})-[r:RELATES_TO]->(t:Entity {group_id: $gid}) "
                        "RETURN s.uuid AS source_id, s.name AS source_name, "
                        "       r.uuid AS id, r.name AS type, "
                        "       t.uuid AS target_id, t.name AS target_name "
                        "SKIP $skip LIMIT $lim",
                        gid=task_id, skip=skip, lim=page_size,
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
                "total_entities": 0,
                "total_relationships": 0,
                "task_id": task_id,
            }

        # Query Neo4j directly for counts (no LLM involved)
        try:
            entity_count, rel_count = await self._query_neo4j_counts(task_id)
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
        """Query Neo4j directly for entity and relationship counts."""
        from neo4j import AsyncGraphDatabase
        uri = self.settings.neo4j_uri
        user = self.settings.neo4j_user
        password = self.settings.neo4j_password
        driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        try:
            async with driver.session() as session:
                if task_id:
                    entity_res = await session.run(
                        "MATCH (n:Entity {group_id: $gid}) RETURN count(n) AS cnt",
                        gid=task_id,
                    )
                    rel_res = await session.run(
                        "MATCH (s:Entity {group_id: $gid})-[r:RELATES_TO]->(t:Entity {group_id: $gid}) "
                        "RETURN count(r) AS cnt",
                        gid=task_id,
                    )
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
        Queries Neo4j directly to find distinct group_ids.
        """
        try:
            from neo4j import AsyncGraphDatabase
            driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            try:
                async with driver.session() as session:
                    result = await session.run(
                        "MATCH (n:Entity) WHERE n.group_id IS NOT NULL "
                        "RETURN DISTINCT n.group_id AS gid"
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
        Get graph data for visualization as (nodes, links) tuple.
        Returns react-force-graph-2d compatible format.
        """
        from neo4j import AsyncGraphDatabase
        driver = AsyncGraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
        )
        try:
            async with driver.session() as session:
                # Fetch entity nodes with summary
                node_result = await session.run(
                    "MATCH (n:Entity {group_id: $gid}) "
                    "RETURN n.uuid AS id, n.name AS name, "
                    "       n.labels AS labels, n.summary AS summary "
                    "LIMIT $lim",
                    gid=task_id, lim=max_nodes,
                )
                node_rows = [dict(r) async for r in node_result]

                # Collect node IDs to filter edges
                node_ids = {r["id"] for r in node_rows}

                # Fetch relationships between those nodes
                rel_result = await session.run(
                    "MATCH (s:Entity {group_id: $gid})-[r:RELATES_TO]->(t:Entity {group_id: $gid}) "
                    "WHERE s.uuid IN $ids AND t.uuid IN $ids "
                    "RETURN s.uuid AS source, t.uuid AS target, "
                    "       coalesce(r.name, 'RELATES_TO') AS label "
                    "LIMIT $lim",
                    gid=task_id, ids=list(node_ids), lim=max_nodes * 3,
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
                   and r["source"] in node_ids and r["target"] in node_ids
            ]

            return nodes, links
        finally:
            await driver.close()
