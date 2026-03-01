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
                llm_base_url=self.settings.llm_text_base_url
                    if not self.settings.llm_text_base_url.endswith("/v1")
                    else self.settings.llm_text_base_url,
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
                llm_base_url=self.settings.llm_text_base_url
                    if not self.settings.llm_text_base_url.endswith("/v1")
                    else self.settings.llm_text_base_url,
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
                    base_name = task_data.get("image_name") or task_data.get("name")
                    output_dir = task_data.get("output_dir", output_dir)
                    any_db_path = task_data.get("db_path")

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
        
        Args:
            query: Search query.
            task_id: Task ID to search within.
            entity_types: Filter by entity types.
            limit: Maximum results.
            include_relationships: Include related entities.
        """
        if not self._initialized:
            logger.warning("Graphiti not initialized")
            return []
        
        try:
            graph = await self._get_task_graph(task_id)
            if graph and hasattr(graph, 'search'):
                return await graph.search(
                    query=query,
                    entity_types=entity_types,
                    limit=limit,
                    include_relationships=include_relationships,
                )
            return []
        except Exception as e:
            logger.error(f"Graphiti search failed for task {task_id}: {e}")
            raise
    
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
        if not self._initialized:
            return [], 0
        
        try:
            graph = await self._get_task_graph(task_id)
            if graph and hasattr(graph, 'list_entities'):
                result = await graph.list_entities(
                    entity_type=entity_type,
                    skip=(page - 1) * page_size,
                    limit=page_size,
                )
                return result.get("entities", []), result.get("total", 0)
            return [], 0
        except Exception as e:
            logger.error(f"List entities failed for task {task_id}: {e}")
            raise
    
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
        """
        if not self._initialized:
            return [], 0
        
        try:
            graph = await self._get_task_graph(task_id)
            if graph and hasattr(graph, 'list_relationships'):
                result = await graph.list_relationships(
                    relationship_type=relationship_type,
                    source_id=source_id,
                    target_id=target_id,
                    skip=(page - 1) * page_size,
                    limit=page_size,
                )
                return result.get("relationships", []), result.get("total", 0)
            return [], 0
        except Exception as e:
            logger.error(f"List relationships failed for task {task_id}: {e}")
            raise
    
    async def get_status(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get the status of the Graphiti service, optionally for a specific task.
        """
        if not self._initialized:
            return {
                "status": "not_initialized",
                "neo4j_connected": False,
                "total_entities": 0,
                "total_relationships": 0,
                "task_id": task_id,
            }
        
        try:
            if task_id:
                graph = await self._get_task_graph(task_id)
                if graph and hasattr(graph, 'get_stats'):
                    stats = await graph.get_stats()
                    return {
                        "status": "connected",
                        "neo4j_connected": True,
                        "total_entities": stats.get("entities", 0),
                        "total_relationships": stats.get("relationships", 0),
                        "task_id": task_id,
                    }
            
            connected = await self.health_check(task_id)
            return {
                "status": "connected" if connected else "disconnected",
                "neo4j_connected": connected,
                "total_entities": 0,
                "total_relationships": 0,
                "task_id": task_id,
            }
        except Exception as e:
            logger.error(f"Get status failed: {e}")
            return {
                "status": "error",
                "neo4j_connected": False,
                "error": str(e),
                "total_entities": 0,
                "total_relationships": 0,
                "task_id": task_id,
            }
    
    async def list_task_graphs(self) -> List[str]:
        """List all task IDs that have graph data."""
        return list(self._task_graphs.keys())
    
    async def delete_task_graph(self, task_id: str) -> bool:
        """Delete a task-specific graph and its data."""
        if task_id in self._task_graphs:
            try:
                graph = self._task_graphs[task_id]
                if hasattr(graph, 'clear_all'):
                    await graph.clear_all()
                if hasattr(graph, 'close'):
                    await graph.close()
                del self._task_graphs[task_id]
                logger.info(f"Deleted graph for task: {task_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete graph for task {task_id}: {e}")
                raise
        return False
