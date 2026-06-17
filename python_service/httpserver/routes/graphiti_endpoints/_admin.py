"""Graphiti routes — status / task-graph admin endpoints.

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
    GraphitiStatusResponse,
    TaskGraphsResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


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
