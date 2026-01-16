"""
Graphiti Service - Knowledge graph integration.

This service provides integration with the Graphiti knowledge graph:
- Data ingestion from forensic databases
- Entity and relationship search
- Graph statistics and status

Uses the existing graphiti_integration module for core functionality.
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
    
    Integrates with the existing graphiti_integration module
    and provides async wrappers for HTTP routes.
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize the Graphiti service.
        
        Args:
            settings: Application settings.
        """
        self.settings = settings
        self._initialized = False
        self._graphiti = None
        
        # Background job tracking
        self._jobs: Dict[str, Dict[str, Any]] = {}
    
    async def initialize(self):
        """Initialize the Graphiti connection."""
        if self._initialized:
            return
        
        try:
            # Try to import graphiti_integration
            from graphiti_integration import GraphitiIngestor
            
            self._graphiti = GraphitiIngestor(
                neo4j_uri=self.settings.neo4j_uri,
                neo4j_user=self.settings.neo4j_user,
                neo4j_password=self.settings.neo4j_password,
            )
            
            self._initialized = True
            logger.info("Graphiti service initialized")
        except ImportError as e:
            logger.warning(f"Graphiti integration not available: {e}")
            raise
        except Exception as e:
            logger.warning(f"Graphiti service initialization failed: {e}")
            raise
    
    async def shutdown(self):
        """Shutdown the Graphiti connection."""
        if self._graphiti:
            try:
                await self._graphiti.close()
            except Exception as e:
                logger.warning(f"Error closing Graphiti connection: {e}")
        self._initialized = False
    
    async def health_check(self) -> bool:
        """
        Check if Graphiti/Neo4j is healthy.
        
        Returns:
            True if healthy, False otherwise.
        """
        if not self._initialized:
            return False
        
        try:
            # Try a simple query to verify connection
            if hasattr(self._graphiti, 'check_connection'):
                return await self._graphiti.check_connection()
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
        Start background ingestion of forensic data.
        
        Args:
            task_id: Task ID to ingest data from.
            include_llm_descriptions: Include LLM descriptions.
            batch_size: Batch size for processing.
        
        Returns:
            Job ID for tracking progress.
        """
        job_id = str(uuid.uuid4())
        
        # Create job entry
        self._jobs[job_id] = {
            "status": "running",
            "task_id": task_id,
            "progress": 0.0,
            "entities_created": 0,
            "relationships_created": 0,
            "errors": [],
        }
        
        # Start background task
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
        """Run the actual ingestion in background."""
        try:
            if self._graphiti and hasattr(self._graphiti, 'ingest_task'):
                result = await self._graphiti.ingest_task(
                    task_id=task_id,
                    include_llm=include_llm_descriptions,
                    batch_size=batch_size,
                    progress_callback=lambda p: self._update_job_progress(job_id, p),
                )
                
                self._jobs[job_id].update({
                    "status": "completed",
                    "progress": 1.0,
                    "entities_created": result.get("entities", 0),
                    "relationships_created": result.get("relationships", 0),
                })
            else:
                # Simulate ingestion if graphiti not available
                self._jobs[job_id].update({
                    "status": "completed",
                    "progress": 1.0,
                    "message": "Graphiti not configured - simulated completion",
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
        entity_types: Optional[List[str]] = None,
        limit: int = 100,
        include_relationships: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Search the knowledge graph.
        
        Args:
            query: Search query.
            entity_types: Filter by entity types.
            limit: Maximum results.
            include_relationships: Include related entities.
        
        Returns:
            List of search results.
        """
        if not self._initialized or not self._graphiti:
            logger.warning("Graphiti not initialized, returning empty results")
            return []
        
        try:
            if hasattr(self._graphiti, 'search'):
                return await self._graphiti.search(
                    query=query,
                    entity_types=entity_types,
                    limit=limit,
                    include_relationships=include_relationships,
                )
            return []
        except Exception as e:
            logger.error(f"Graphiti search failed: {e}")
            raise
    
    async def list_entities(
        self,
        entity_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List entities in the knowledge graph.
        
        Args:
            entity_type: Filter by entity type.
            page: Page number.
            page_size: Page size.
        
        Returns:
            Tuple of (entities list, total count).
        """
        if not self._initialized or not self._graphiti:
            return [], 0
        
        try:
            if hasattr(self._graphiti, 'list_entities'):
                result = await self._graphiti.list_entities(
                    entity_type=entity_type,
                    skip=(page - 1) * page_size,
                    limit=page_size,
                )
                return result.get("entities", []), result.get("total", 0)
            return [], 0
        except Exception as e:
            logger.error(f"List entities failed: {e}")
            raise
    
    async def list_relationships(
        self,
        relationship_type: Optional[str] = None,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List relationships in the knowledge graph.
        
        Args:
            relationship_type: Filter by relationship type.
            source_id: Filter by source entity.
            target_id: Filter by target entity.
            page: Page number.
            page_size: Page size.
        
        Returns:
            Tuple of (relationships list, total count).
        """
        if not self._initialized or not self._graphiti:
            return [], 0
        
        try:
            if hasattr(self._graphiti, 'list_relationships'):
                result = await self._graphiti.list_relationships(
                    relationship_type=relationship_type,
                    source_id=source_id,
                    target_id=target_id,
                    skip=(page - 1) * page_size,
                    limit=page_size,
                )
                return result.get("relationships", []), result.get("total", 0)
            return [], 0
        except Exception as e:
            logger.error(f"List relationships failed: {e}")
            raise
    
    async def get_status(self) -> Dict[str, Any]:
        """
        Get the status of the Graphiti service.
        
        Returns:
            Status information dict.
        """
        if not self._initialized or not self._graphiti:
            return {
                "status": "not_initialized",
                "neo4j_connected": False,
                "total_entities": 0,
                "total_relationships": 0,
            }
        
        try:
            if hasattr(self._graphiti, 'get_stats'):
                stats = await self._graphiti.get_stats()
                return {
                    "status": "connected",
                    "neo4j_connected": True,
                    "total_entities": stats.get("entities", 0),
                    "total_relationships": stats.get("relationships", 0),
                }
            
            # Basic connected status
            connected = await self.health_check()
            return {
                "status": "connected" if connected else "disconnected",
                "neo4j_connected": connected,
                "total_entities": 0,
                "total_relationships": 0,
            }
        except Exception as e:
            logger.error(f"Get status failed: {e}")
            return {
                "status": "error",
                "neo4j_connected": False,
                "error": str(e),
                "total_entities": 0,
                "total_relationships": 0,
            }
