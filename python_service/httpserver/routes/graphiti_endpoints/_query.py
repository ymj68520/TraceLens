"""Graphiti routes — search / list entities & relationships endpoints.

Part of the graphiti routes split (see graphiti.py). Endpoints are decorated
with the package-local APIRouter (``router``); the parent graphiti.py mounts
this router under ``/api/graphiti``.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks

from ...config import Settings, get_settings

from ..graphiti_models import (
    EntityListResponse,
    RelationshipListResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
)

logger = logging.getLogger(__name__)
router = APIRouter()


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
