"""
Graphiti knowledge graph integration routes.

Provides endpoints for task-specific knowledge graphs:
- Ingesting forensic data into task-specific graph
- Searching entities and relationships within task scope
- Managing graph operations per task
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
    task_id: str = Field(..., description="Task ID to ingest data from (also used as graph namespace)")
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
    task_id: str = Field(..., description="Task ID to search within")
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
    task_id: str
    results: List[SearchResult]
    total_count: int
    timestamp: str


class EntityListResponse(BaseModel):
    """Response model for entity listing."""
    success: bool
    task_id: str
    entities: List[Dict[str, Any]]
    total_count: int
    page: int
    page_size: int
    timestamp: str


class RelationshipListResponse(BaseModel):
    """Response model for relationship listing."""
    success: bool
    task_id: str
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
    task_id: Optional[str] = None
    timestamp: str


class TaskGraphsResponse(BaseModel):
    """Response model for listing task graphs."""
    success: bool
    task_ids: List[str]
    count: int
    timestamp: str


# Routes

@router.post("/ingest", response_model=IngestResponse, responses={
    200: {"description": "Ingestion started successfully"},
    404: {"description": "Task not found"},
    500: {"description": "Internal server error during ingestion"}
})
async def ingest_data(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """
    Ingest forensic data from a task into the task-specific knowledge graph.
    
    Each task gets its own isolated graph namespace using task_id as group_id.
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
            message=f"Ingestion started for task {request.task_id}",
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", response_model=SearchResponse, responses={
    200: {"description": "Search executed successfully"},
    500: {"description": "Internal server error during search"}
})
async def search_graph(
    request: SearchRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Search the knowledge graph for a specific task.
    
    Only returns results from the task-specific graph namespace.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        results = await service_manager.graphiti_service.search(
            query=request.query,
            task_id=request.task_id,
            entity_types=request.entity_types,
            limit=request.limit,
            include_relationships=request.include_relationships,
        )
        
        return SearchResponse(
            success=True,
            query=request.query,
            task_id=request.task_id,
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


@router.get("/entities", response_model=EntityListResponse, responses={
    200: {"description": "Entities listed successfully"},
    500: {"description": "Internal server error during listing"}
})
async def list_entities(
    task_id: str = Query(..., description="Task ID to list entities from"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Page size"),
    settings: Settings = Depends(get_settings),
):
    """
    List entities in the knowledge graph for a specific task.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        entities, total_count = await service_manager.graphiti_service.list_entities(
            task_id=task_id,
            entity_type=entity_type,
            page=page,
            page_size=page_size,
        )
        
        return EntityListResponse(
            success=True,
            task_id=task_id,
            entities=entities,
            total_count=total_count,
            page=page,
            page_size=page_size,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"List entities failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/relationships", response_model=RelationshipListResponse, responses={
    200: {"description": "Relationships listed successfully"},
    500: {"description": "Internal server error during listing"}
})
async def list_relationships(
    task_id: str = Query(..., description="Task ID to list relationships from"),
    relationship_type: Optional[str] = Query(None, description="Filter by relationship type"),
    source_id: Optional[str] = Query(None, description="Filter by source entity ID"),
    target_id: Optional[str] = Query(None, description="Filter by target entity ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Page size"),
    settings: Settings = Depends(get_settings),
):
    """
    List relationships in the knowledge graph for a specific task.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        relationships, total_count = await service_manager.graphiti_service.list_relationships(
            task_id=task_id,
            relationship_type=relationship_type,
            source_id=source_id,
            target_id=target_id,
            page=page,
            page_size=page_size,
        )
        
        return RelationshipListResponse(
            success=True,
            task_id=task_id,
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
async def get_status(
    task_id: Optional[str] = Query(None, description="Task ID for task-specific status"),
    settings: Settings = Depends(get_settings),
):
    """
    Get the status of the Graphiti knowledge graph service.
    
    If task_id is provided, returns status for that specific task graph.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        status = await service_manager.graphiti_service.get_status(task_id=task_id)
        
        return GraphitiStatusResponse(
            status=status.get("status", "unknown"),
            neo4j_connected=status.get("neo4j_connected", False),
            total_entities=status.get("total_entities", 0),
            total_relationships=status.get("total_relationships", 0),
            task_id=task_id,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Get status failed: {e}", exc_info=True)
        return GraphitiStatusResponse(
            status="error",
            neo4j_connected=False,
            total_entities=0,
            total_relationships=0,
            task_id=task_id,
            timestamp=datetime.now().isoformat(),
        )


@router.get("/tasks", response_model=TaskGraphsResponse)
async def list_task_graphs(settings: Settings = Depends(get_settings)):
    """
    List all task IDs that have knowledge graph data.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        task_ids = await service_manager.graphiti_service.list_task_graphs()
        
        return TaskGraphsResponse(
            success=True,
            task_ids=task_ids,
            count=len(task_ids),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"List task graphs failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/{task_id}")
async def delete_task_graph(
    task_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    Delete a task-specific knowledge graph.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        deleted = await service_manager.graphiti_service.delete_task_graph(task_id)
        
        return {
            "success": deleted,
            "task_id": task_id,
            "message": f"Graph {'deleted' if deleted else 'not found'}",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Delete task graph failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph", responses={
    200: {"description": "Graph data for visualization"},
    500: {"description": "Internal server error"},
})
async def get_graph_data(
    task_id: str = Query(..., description="Task ID to get graph data for"),
    max_nodes: int = Query(200, ge=1, le=1000, description="Maximum nodes to return"),
    settings: Settings = Depends(get_settings),
):
    """
    Get graph data (nodes + links) for visual rendering of the knowledge graph.
    Returns a force-graph compatible format: { nodes: [...], links: [...] }  
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()

        nodes, links = await service_manager.graphiti_service.get_graph_data(
            task_id=task_id,
            max_nodes=max_nodes,
        )

        return {
            "success": True,
            "task_id": task_id,
            "nodes": nodes,
            "links": links,
            "node_count": len(nodes),
            "link_count": len(links),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Get graph data failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
