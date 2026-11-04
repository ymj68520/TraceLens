"""WhatsApp forensics (WhatsApp 取证) routes.

Import/parse pipeline for an iOS WhatsApp backup. Mounted under ``/api/whatsapp``:

  POST   /forensics/imports                  create an import
  GET    /forensics/imports                  list imports
  GET    /forensics/imports/{id}             import summary
  DELETE /forensics/imports/{id}             remove an import
  GET    /forensics/imports/{id}/overview    forensic overview
  GET    /forensics/imports/{id}/sessions    chat sessions (peers/groups)
  GET    /forensics/imports/{id}/messages    paginated readable messages
  GET    /forensics/imports/{id}/contacts    readable contact list
  GET    /forensics/imports/{id}/chatrooms   group details

The route surface mirrors ``/api/qq`` and ``/api/wechat`` so the shared IM
panels and the relationship-analysis pipeline can treat WhatsApp as a third
platform rather than a one-off screen.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query

from ..services.whatsapp_import_service import (
    get_whatsapp_import_service,
    list_imports as list_whatsapp_imports,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _svc():
    return get_whatsapp_import_service()


def _handle_error(error: Exception, what: str, code: int = 500) -> HTTPException:
    logger.error("%s failed: %s", what, error, exc_info=True)
    return HTTPException(status_code=code, detail=f"{what} failed: {error}")


@router.post("/forensics/imports")
async def create_import(payload: dict = Body(...)):
    """Create a WhatsApp import.

    Body fields:
      db_path      : absolute path to ChatStorage.sqlite, or the directory that
                     contains it (ContactsV2.sqlite / CallHistory.sqlite are
                     picked up automatically when present)
      name         : human label for the import
      backup_source: free-form origin description
    """
    try:
        if not (payload.get("db_path") or "").strip():
            raise HTTPException(status_code=400, detail="db_path is required")
        result = await asyncio.to_thread(_svc().create_import, payload)
        return {"success": True, "import": result}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except HTTPException:
        raise
    except Exception as error:
        raise _handle_error(error, "import creation")


@router.get("/forensics/imports")
async def list_imports():
    try:
        return {"success": True, "imports": await asyncio.to_thread(list_whatsapp_imports)}
    except Exception as error:
        raise _handle_error(error, "import listing")


@router.get("/forensics/imports/{import_id}")
async def get_import(import_id: str = Path(..., max_length=32)):
    try:
        return {"success": True, "import": await asyncio.to_thread(_svc().get_import, import_id)}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        raise _handle_error(error, "import lookup")


@router.delete("/forensics/imports/{import_id}")
async def delete_import(import_id: str = Path(..., max_length=32)):
    try:
        await asyncio.to_thread(_svc().delete_import, import_id)
        return {"success": True}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        raise _handle_error(error, "import deletion")


@router.get("/forensics/imports/{import_id}/overview")
async def overview(import_id: str = Path(..., max_length=32)):
    try:
        return {"success": True, "overview": await asyncio.to_thread(_svc().overview, import_id)}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        raise _handle_error(error, "overview")


@router.get("/forensics/imports/{import_id}/sessions")
async def sessions(import_id: str = Path(..., max_length=32)):
    try:
        return {"success": True, "sessions": await asyncio.to_thread(_svc().sessions, import_id)}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        raise _handle_error(error, "sessions")


@router.get("/forensics/imports/{import_id}/messages")
async def messages(
    import_id: str = Path(..., max_length=32),
    talker: str = Query("", max_length=256),
    msg_type: Optional[int] = Query(None),
    keyword: str = Query("", max_length=200),
    start: Optional[int] = Query(None),
    end: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    try:
        result = await asyncio.to_thread(
            _svc().messages, import_id,
            talker=talker, msg_type=msg_type, keyword=keyword,
            start=start, end=end, page=page, page_size=page_size,
        )
        return {"success": True, **result}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        raise _handle_error(error, "messages")


@router.get("/forensics/imports/{import_id}/contacts")
async def contacts(import_id: str = Path(..., max_length=32)):
    try:
        return {"success": True, "contacts": await asyncio.to_thread(_svc().contacts, import_id)}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        raise _handle_error(error, "contacts")


@router.get("/forensics/imports/{import_id}/chatrooms")
async def chatrooms(import_id: str = Path(..., max_length=32)):
    try:
        return {"success": True, "chatrooms": await asyncio.to_thread(_svc().chatrooms, import_id)}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        raise _handle_error(error, "chatrooms")
