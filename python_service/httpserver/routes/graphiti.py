"""
Graphiti knowledge graph integration routes.

Provides endpoints for:
- Ingesting forensic data into the knowledge graph
- Searching entities and relationships
- Managing graph operations
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


# Request/Response Models

class IngestRequest(BaseModel):
    """Request model for data ingestion."""
    task_id: str = Field(..., description="Task ID to ingest data from")
    include_llm_descriptions: bool = Field(default=True, description="Include LLM-generated descriptions")
    batch_size: int = Field(default=50, ge=1, le=500, description="Batch size for processing")


class IngestResponse(BaseModel):
    """Response model for ingestion operation."""
    success: bool
    task_id: str
    job_id: Optional[str] = None
    message: str
    entities_created: int = 0
    relationships_created: int = 0
    timestamp: str


class SearchRequest(BaseModel):
    """Request model for graph search."""
    query: str = Field(..., min_length=1, description="Search query")
    entity_types: Optional[List[str]] = Field(default=None, description="Filter by entity types")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results")
    include_relationships: bool = Field(default=True, description="Include related entities")


class SearchResult(BaseModel):
    """Single search result."""
    entity_id: str
    entity_type: str
    name: str
    properties: Dict[str, Any]
    score: float
    relationships: Optional[List[Dict[str, Any]]] = None


class SearchResponse(BaseModel):
    """Response model for search operation."""
    success: bool
    query: str
    results: List[SearchResult]
    total_count: int
    timestamp: str


class EntityListResponse(BaseModel):
    """Response model for entity listing."""
    success: bool
    entities: List[Dict[str, Any]]
    total_count: int
    page: int
    page_size: int
    timestamp: str


class RelationshipListResponse(BaseModel):
    """Response model for relationship listing."""
    success: bool
    relationships: List[Dict[str, Any]]
    total_count: int
    page: int
    page_size: int
    timestamp: str


class GraphitiStatusResponse(BaseModel):
    """Response model for Graphiti service status."""
    status: str
    neo4j_connected: bool
    total_entities: int
    total_relationships: int
    group_id: str
    timestamp: str


# Routes

@router.post("/ingest", response_model=IngestResponse)
async def ingest_data(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """
    Ingest forensic data from a task into the knowledge graph.
    
    This operation runs in the background and returns immediately
    with a job ID that can be used to track progress.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        # Check if task exists via C++ backend
        task_exists = await service_manager.cpp_backend.check_task_exists(request.task_id)
        if not task_exists:
            raise HTTPException(status_code=404, detail=f"Task {request.task_id} not found")
        
        # Start background ingestion
        job_id = await service_manager.graphiti_service.start_ingestion(
            task_id=request.task_id,
            include_llm_descriptions=request.include_llm_descriptions,
            batch_size=request.batch_size,
        )
        
        return IngestResponse(
            success=True,
            task_id=request.task_id,
            job_id=job_id,
            message="Ingestion started in background",
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", response_model=SearchResponse)
async def search_graph(
    request: SearchRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Search the knowledge graph for entities and relationships.
    
    Supports natural language queries and filtering by entity types.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        results = await service_manager.graphiti_service.search(
            query=request.query,
            entity_types=request.entity_types,
            limit=request.limit,
            include_relationships=request.include_relationships,
        )
        
        return SearchResponse(
            success=True,
            query=request.query,
            results=[
                SearchResult(
                    entity_id=r.get("id", ""),
                    entity_type=r.get("type", "unknown"),
                    name=r.get("name", ""),
                    properties=r.get("properties", {}),
                    score=r.get("score", 0.0),
                    relationships=r.get("relationships"),
                )
                for r in results
            ],
            total_count=len(results),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities", response_model=EntityListResponse)
async def list_entities(
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Page size"),
    settings: Settings = Depends(get_settings),
):
    """
    List entities in the knowledge graph.
    
    Supports pagination and filtering by entity type.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        entities, total_count = await service_manager.graphiti_service.list_entities(
            entity_type=entity_type,
            page=page,
            page_size=page_size,
        )
        
        return EntityListResponse(
            success=True,
            entities=entities,
            total_count=total_count,
            page=page,
            page_size=page_size,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"List entities failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/relationships", response_model=RelationshipListResponse)
async def list_relationships(
    relationship_type: Optional[str] = Query(None, description="Filter by relationship type"),
    source_id: Optional[str] = Query(None, description="Filter by source entity ID"),
    target_id: Optional[str] = Query(None, description="Filter by target entity ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Page size"),
    settings: Settings = Depends(get_settings),
):
    """
    List relationships in the knowledge graph.
    
    Supports pagination and filtering by relationship type, source, or target.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        relationships, total_count = await service_manager.graphiti_service.list_relationships(
            relationship_type=relationship_type,
            source_id=source_id,
            target_id=target_id,
            page=page,
            page_size=page_size,
        )
        
        return RelationshipListResponse(
            success=True,
            relationships=relationships,
            total_count=total_count,
            page=page,
            page_size=page_size,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"List relationships failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", response_model=GraphitiStatusResponse)
async def get_status(settings: Settings = Depends(get_settings)):
    """
    Get the status of the Graphiti knowledge graph service.
    
    Returns connection status, entity/relationship counts, and configuration.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        status = await service_manager.graphiti_service.get_status()
        
        return GraphitiStatusResponse(
            status=status.get("status", "unknown"),
            neo4j_connected=status.get("neo4j_connected", False),
            total_entities=status.get("total_entities", 0),
            total_relationships=status.get("total_relationships", 0),
            group_id=settings.graphiti_group_id,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Get status failed: {e}", exc_info=True)
        return GraphitiStatusResponse(
            status="error",
            neo4j_connected=False,
            total_entities=0,
            total_relationships=0,
            group_id=settings.graphiti_group_id,
            timestamp=datetime.now().isoformat(),
        )
