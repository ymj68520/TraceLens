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

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field




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


