"""WeChat-graph routes — chat / owner / contacts / cache endpoints.

Part of the wechat_graph routes split (see wechat_graph.py). Endpoints use the
package-local APIRouter; parent mounts under /api/wechat.
"""

import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...config import Settings, get_settings

from ..wechat_graph_models import (
    ChatResponse,
    ContactsResponse,
    OwnerResponse,
    _get_service,
    _now_iso,
    _resolve_android_db_path,
)

logger = logging.getLogger(__name__)
router = APIRouter()


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
