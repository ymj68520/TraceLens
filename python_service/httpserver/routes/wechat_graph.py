"""
WeChat relationship graph and chat history routes.

Provides REST API endpoints for WeChat forensic analysis:
- Full relationship graph with PageRank, betweenness centrality, and communities
- Temporal message timeline (monthly/weekly aggregation)
- Community details
- Person ego network (contacts of a specific user)
- Private and group chat history
- Device owner info
- Contact list
- Cache invalidation
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ==============================================================================
# Response Models
# ==============================================================================


class GraphResponse(BaseModel):
    """Response model for the full relationship graph."""
    success: bool
    task_id: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    communities: List[List[str]]
    metadata: Dict[str, Any]
    timestamp: str


class TimelineResponse(BaseModel):
    """Response model for temporal timeline data."""
    success: bool
    task_id: str
    granularity: str
    intervals: List[Dict[str, Any]]
    timestamp: str


class CommunityResponse(BaseModel):
    """Response model for community details."""
    success: bool
    task_id: str
    communities: List[Dict[str, Any]]
    total_communities: int
    timestamp: str


class PersonEgoResponse(BaseModel):
    """Response model for a person's ego network."""
    success: bool
    task_id: str
    username: str
    node: Optional[Dict[str, Any]]
    connections: List[Dict[str, Any]]
    timestamp: str


class ChatMessage(BaseModel):
    """Single chat message."""
    id: Optional[int] = None
    sender: Optional[str] = None
    receiver: Optional[str] = None
    content: Optional[str] = None
    timestamp: Optional[int] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    msg_type: Optional[str] = None
    is_send: Optional[int] = None
    chatroom_name: Optional[str] = None
    sender_nickname: Optional[str] = None
    talker: Optional[str] = None


class ChatResponse(BaseModel):
    """Response model for chat history."""
    success: bool
    task_id: str
    messages: List[Dict[str, Any]]
    total: int
    page: int
    page_size: int
    total_pages: int
    timestamp: str


class OwnerResponse(BaseModel):
    """Response model for device owner info."""
    success: bool
    task_id: str
    owner: Optional[Dict[str, Any]] = None
    timestamp: str


class ContactItem(BaseModel):
    """Single contact entry."""
    username: str
    nickname: str
    remark: str
    avatar_path: str
    type: Optional[int] = None
    chatroom_flag: Optional[int] = None


class ContactsResponse(BaseModel):
    """Response model for contact list."""
    success: bool
    task_id: str
    contacts: List[Dict[str, Any]]
    total: int
    timestamp: str


class CacheInvalidateResponse(BaseModel):
    """Response model for cache invalidation."""
    success: bool
    task_id: str
    message: str
    timestamp: str


# ==============================================================================
# Helpers
# ==============================================================================


async def _resolve_android_db_path(task_id: str) -> str:
    """
    Resolve the _android.db path for a given task_id.

    Tries the C++ backend task metadata first (output_raw_db derived),
    then falls back to a glob search in common output directories.

    Args:
        task_id: The task identifier.

    Returns:
        Absolute path to the _android.db file.

    Raises:
        HTTPException: If the task is not found or the database cannot be located.
    """
    from ..services import get_service_manager
    service_manager = get_service_manager()

    # Try C++ backend task metadata
    task_info = await service_manager.cpp_backend.get_task(task_id)
    if task_info:
        # Check metadata for android_db first
        metadata = task_info.get("metadata", {})
        android_db = metadata.get("android_db") if isinstance(metadata, dict) else None
        if android_db and os.path.exists(android_db):
            return android_db

        # Derive from output_raw_db: replace .db suffix with _android.db
        raw_db = task_info.get("output_raw_db") or ""
        if raw_db:
            android_db = raw_db.rsplit(".", 1)[0] + "_android.db" if "." in raw_db else raw_db + "_android.db"
            if os.path.exists(android_db):
                return android_db

        # Derive from output_files_db
        files_db = task_info.get("output_files_db") or ""
        if files_db:
            android_db = files_db.replace("_files.db", "_android.db")
            if os.path.exists(android_db):
                return android_db

    # Fallback: glob search
    import glob
    search_patterns = [
        f"**/tasks/{task_id}/*_android.db",
        f"**/{task_id}*_android.db",
        f"**/output/{task_id}/*_android.db",
    ]
    for pattern in search_patterns:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            return matches[0]

    raise HTTPException(
        status_code=404,
        detail=f"Android database not found for task {task_id}. "
               "Ensure the task has completed Android analysis.",
    )


def _get_service():
    """Lazily import and return a WeChatGraphService instance."""
    from ..services.wechat_graph_service import WeChatGraphService
    return WeChatGraphService()


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now().isoformat()


# ==============================================================================
# Endpoints
# ==============================================================================


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


@router.get("/chat", response_model=ChatResponse, responses={
    200: {"description": "Chat history returned successfully"},
    404: {"description": "Task or database not found"},
    500: {"description": "Internal server error"},
})
async def get_chat(
    task_id: str = Query(..., description="Task ID"),
    user1: str = Query(..., description="First participant username (typically the owner)"),
    user2: str = Query(..., description="Second participant username (the contact)"),
    offset: int = Query(0, ge=0, description="Number of messages to skip"),
    limit: int = Query(50, ge=1, le=500, description="Maximum messages to return"),
    settings: Settings = Depends(get_settings),
):
    """
    Get private chat history between two users.

    Returns paginated messages ordered by timestamp ascending.
    Use offset/limit for pagination (converted to page/page_size internally).
    """
    try:
        db_path = await _resolve_android_db_path(task_id)
        service = _get_service()

        # Convert offset/limit to page/page_size
        page_size = limit
        page = (offset // page_size) + 1 if page_size > 0 else 1

        result = await service.get_chat_history(
            db_path=db_path,
            contact_username=user2,
            owner_username=user1,
            page=page,
            page_size=page_size,
        )

        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])

        return ChatResponse(
            success=True,
            task_id=task_id,
            messages=result.get("messages", []),
            total=result.get("total", 0),
            page=result.get("page", page),
            page_size=result.get("page_size", page_size),
            total_pages=result.get("total_pages", 0),
            timestamp=_now_iso(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get chat history failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/group", response_model=ChatResponse, responses={
    200: {"description": "Group chat history returned successfully"},
    404: {"description": "Task, database, or chatroom not found"},
    500: {"description": "Internal server error"},
})
async def get_group_chat(
    task_id: str = Query(..., description="Task ID"),
    chatroom: str = Query(..., description="Chatroom name/ID"),
    offset: int = Query(0, ge=0, description="Number of messages to skip"),
    limit: int = Query(50, ge=1, le=500, description="Maximum messages to return"),
    settings: Settings = Depends(get_settings),
):
    """
    Get group chat history for a chatroom.

    Returns paginated messages ordered by timestamp ascending.
    Use offset/limit for pagination.
    """
    try:
        db_path = await _resolve_android_db_path(task_id)
        service = _get_service()

        # Convert offset/limit to page/page_size
        page_size = limit
        page = (offset // page_size) + 1 if page_size > 0 else 1

        result = await service.get_group_chat_history(
            db_path=db_path,
            chatroom_name=chatroom,
            page=page,
            page_size=page_size,
        )

        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])

        return ChatResponse(
            success=True,
            task_id=task_id,
            messages=result.get("messages", []),
            total=result.get("total", 0),
            page=result.get("page", page),
            page_size=result.get("page_size", page_size),
            total_pages=result.get("total_pages", 0),
            timestamp=_now_iso(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get group chat history failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/owner", response_model=OwnerResponse, responses={
    200: {"description": "Owner info returned successfully"},
    404: {"description": "Task or database not found"},
    500: {"description": "Internal server error"},
})
async def get_owner(
    task_id: str = Query(..., description="Task ID"),
    settings: Settings = Depends(get_settings),
):
    """
    Get the WeChat device owner information.

    Returns username, nickname, UIN, and IMEI from wechat_owner_info.
    """
    try:
        db_path = await _resolve_android_db_path(task_id)
        service = _get_service()
        result = await service.get_owner_info(db_path)

        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])

        return OwnerResponse(
            success=True,
            task_id=task_id,
            owner=result.get("owner"),
            timestamp=_now_iso(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get owner info failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/contacts", response_model=ContactsResponse, responses={
    200: {"description": "Contacts list returned successfully"},
    404: {"description": "Task or database not found"},
    500: {"description": "Internal server error"},
})
async def get_contacts(
    task_id: str = Query(..., description="Task ID"),
    include_chatrooms: bool = Query(False, description="Include chatroom entries in the list"),
    settings: Settings = Depends(get_settings),
):
    """
    Get the WeChat contact list.

    Returns all contacts from wechat_contacts. Set include_chatrooms=true
    to also include group chat entries.
    """
    try:
        db_path = await _resolve_android_db_path(task_id)
        service = _get_service()
        result = await service.get_contacts_list(db_path, include_chatrooms=include_chatrooms)

        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])

        return ContactsResponse(
            success=True,
            task_id=task_id,
            contacts=result.get("contacts", []),
            total=result.get("total", 0),
            timestamp=_now_iso(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get contacts failed: {e}", exc_info=True)
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
