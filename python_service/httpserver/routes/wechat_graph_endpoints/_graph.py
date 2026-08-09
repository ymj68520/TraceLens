"""WeChat-graph routes — graph / timeline / community / ego-network endpoints.

Part of the wechat_graph routes split (see wechat_graph.py). Endpoints use the
package-local APIRouter; parent mounts under /api/wechat.
"""

import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...config import Settings, get_settings

from ..wechat_graph_models import (
    CacheInvalidateResponse,
    CommunityResponse,
    GraphResponse,
    PersonEgoResponse,
    TimelineResponse,
    _get_service,
    _now_iso,
    _resolve_android_db_path,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/graph", response_model=GraphResponse, responses={
    200: {"description": "Full relationship graph returned successfully"},
    404: {"description": "Task or database not found"},
    500: {"description": "Internal server error"},
})
async def get_graph(
    task_id: str = Query(..., description="Task ID"),
    include_metrics: bool = Query(True, description="Include PageRank, betweenness, and community metrics"),
    settings: Settings = Depends(get_settings),
):
    """
    Get the full WeChat relationship graph.

    Returns nodes (contacts with analytics), edges (message flows),
    and community clusters. Data is cached for 30 minutes.
    """
    try:
        db_path = await _resolve_android_db_path(task_id)
        service = _get_service()
        result = await service.get_full_graph(task_id, db_path, include_metrics=include_metrics)

        if "error" in result and not result.get("nodes"):
            raise HTTPException(status_code=404, detail=result["error"])

        return GraphResponse(
            success=True,
            task_id=task_id,
            nodes=result.get("nodes", []),
            edges=result.get("edges", []),
            communities=result.get("communities", []),
            metadata=result.get("metadata", {}),
            timestamp=_now_iso(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get graph failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/graph/timeline", response_model=TimelineResponse, responses={
    200: {"description": "Timeline data returned successfully"},
    404: {"description": "Task or database not found"},
    500: {"description": "Internal server error"},
})
async def get_timeline(
    task_id: str = Query(..., description="Task ID"),
    interval: str = Query("month", description="Aggregation granularity: 'month' or 'week'"),
    settings: Settings = Depends(get_settings),
):
    """
    Get temporal message activity timeline.

    Aggregates message counts by month or week, showing active edges
    and top contacts per interval.
    """
    try:
        if interval not in ("month", "week"):
            raise HTTPException(status_code=400, detail="interval must be 'month' or 'week'")

        db_path = await _resolve_android_db_path(task_id)
        service = _get_service()
        result = await service.compute_timeline(task_id, db_path, granularity=interval)

        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])

        return TimelineResponse(
            success=True,
            task_id=task_id,
            granularity=result.get("granularity", interval),
            intervals=result.get("intervals", []),
            timestamp=_now_iso(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get timeline failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/graph/community", response_model=CommunityResponse, responses={
    200: {"description": "Community details returned successfully"},
    404: {"description": "Task or database not found"},
    500: {"description": "Internal server error"},
})
async def get_community(
    task_id: str = Query(..., description="Task ID"),
    settings: Settings = Depends(get_settings),
):
    """
    Get community detection details.

    Returns each community with its members, size, and aggregate
    message statistics.
    """
    try:
        db_path = await _resolve_android_db_path(task_id)
        service = _get_service()
        result = await service.get_full_graph(task_id, db_path, include_metrics=True)

        if "error" in result and not result.get("nodes"):
            raise HTTPException(status_code=404, detail=result["error"])

        # Build node lookup for enriching community data
        nodes = result.get("nodes", [])
        node_map = {n["id"]: n for n in nodes}
        raw_communities = result.get("communities", [])

        communities = []
        for idx, members in enumerate(raw_communities):
            member_details = []
            total_messages = 0
            for member_id in members:
                node_info = node_map.get(member_id, {})
                member_details.append({
                    "username": member_id,
                    "label": node_info.get("label", member_id),
                    "message_count": node_info.get("message_count", 0),
                    "pagerank": node_info.get("pagerank", 0.0),
                })
                total_messages += node_info.get("message_count", 0)

            communities.append({
                "community_id": idx,
                "members": member_details,
                "size": len(members),
                "total_messages": total_messages,
            })

        return CommunityResponse(
            success=True,
            task_id=task_id,
            communities=communities,
            total_communities=len(communities),
            timestamp=_now_iso(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get community failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/graph/person/{username}", response_model=PersonEgoResponse, responses={
    200: {"description": "Ego network returned successfully"},
    404: {"description": "Task, database, or person not found"},
    500: {"description": "Internal server error"},
})
async def get_person(
    username: str,
    task_id: str = Query(..., description="Task ID"),
    settings: Settings = Depends(get_settings),
):
    """
    Get the ego network for a specific person.

    Returns the person's node attributes and all direct connections
    (edges where the person is source or target).
    """
    try:
        db_path = await _resolve_android_db_path(task_id)
        service = _get_service()
        result = await service.get_full_graph(task_id, db_path, include_metrics=True)

        if "error" in result and not result.get("nodes"):
            raise HTTPException(status_code=404, detail=result["error"])

        nodes = result.get("nodes", [])
        edges = result.get("edges", [])
        node_map = {n["id"]: n for n in nodes}

        # Find the target node
        target_node = node_map.get(username)
        if not target_node:
            raise HTTPException(status_code=404, detail=f"Person '{username}' not found in graph")

        # Collect all edges involving this person
        connections = []
        for edge in edges:
            if edge.get("source") == username or edge.get("target") == username:
                peer = edge.get("target") if edge.get("source") == username else edge.get("source")
                peer_node = node_map.get(peer, {})
                connections.append({
                    "peer": peer,
                    "peer_label": peer_node.get("label", peer),
                    "weight": edge.get("weight", 0),
                    "edge_type": edge.get("edge_type", "private"),
                    "total_chars": edge.get("total_chars", 0),
                    "first_time": edge.get("first_time"),
                    "last_time": edge.get("last_time"),
                    "sent_count": edge.get("sent_count", 0),
                    "received_count": edge.get("received_count", 0),
                })

        return PersonEgoResponse(
            success=True,
            task_id=task_id,
            username=username,
            node=target_node,
            connections=connections,
            timestamp=_now_iso(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get person ego network failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/graph/invalidate", response_model=CacheInvalidateResponse, responses={
    200: {"description": "Cache invalidated successfully"},
    500: {"description": "Internal server error"},
})
async def invalidate_cache(
    task_id: str = Query(..., description="Task ID whose cache should be cleared"),
    settings: Settings = Depends(get_settings),
):
    """
    Invalidate cached graph data for a task.

    Forces the next graph request to rebuild from the database.
    """
    try:
        service = _get_service()
        service.invalidate_cache(task_id)

        return CacheInvalidateResponse(
            success=True,
            task_id=task_id,
            message=f"Cache invalidated for task {task_id}",
            timestamp=_now_iso(),
        )
    except Exception as e:
        logger.error(f"Cache invalidation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
