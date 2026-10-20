"""QQ forensics (QQ 取证) routes.

Import/parse pipeline for an Android QQ (NTQQ) account ``nt_db`` directory.
Mounted under ``/api/qq``:

  POST   /forensics/imports                  create an import
  GET    /forensics/imports                  list imports
  GET    /forensics/imports/{id}             import summary
  DELETE /forensics/imports/{id}             remove an import
  GET    /forensics/imports/{id}/overview    forensic overview
  GET    /forensics/imports/{id}/sessions    chat sessions (peers/groups)
  GET    /forensics/imports/{id}/messages    paginated readable messages
  GET    /forensics/imports/{id}/contacts    readable contact list
  GET    /forensics/imports/{id}/chatrooms   group details

The imported dataset plugs into the existing relationship-analysis pipeline:
``/api/wechat/graph?task_id=qq_<import_id>`` resolves to the import's
normalized ``graph.db``.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query

from ..services.qq_import_service import get_qq_import_service
from .timeline_summary import qq_router as timeline_summary_router

logger = logging.getLogger(__name__)
router = APIRouter()
router.include_router(timeline_summary_router)


def _svc():
    return get_qq_import_service()


def _handle_error(e: Exception, what: str, code: int = 500) -> HTTPException:
    logger.error("%s failed: %s", what, e, exc_info=True)
    return HTTPException(status_code=code, detail=f"{what} failed: {e}")


@router.post("/forensics/imports")
async def create_import(payload: dict = Body(...)):
    """Create a QQ forensics import.

    Body fields:
      db_path      : absolute path to nt_msg.db (encrypted NTQQ or plaintext)
      password     : optional explicit database key (32-hex); if omitted it is
                     derived from key_material (nt_uid + header rand)
      key_material : {nt_uid, uin} for derivation & record
      name         : human label for the import
      backup_source: free-form origin description (e.g. MIUI backup path)
    """
    try:
        db_path = (payload.get("db_path") or "").strip()
        if not db_path:
            raise HTTPException(status_code=400, detail="db_path is required")
        result = await _svc().create_import(payload)
        return {"success": True, "import": result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise _handle_error(e, "import creation")


@router.get("/forensics/imports")
async def list_imports():
    try:
        from ..services.qq_import_service import list_imports as _list

        return {"success": True, "imports": await asyncio.to_thread(_list)}
    except Exception as e:
        raise _handle_error(e, "import listing")


@router.get("/forensics/imports/{import_id}")
async def get_import(import_id: str = Path(...)):
    try:
        return {"success": True, "import": await _svc().get_meta(import_id)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise _handle_error(e, "import lookup")


@router.delete("/forensics/imports/{import_id}")
async def delete_import(import_id: str = Path(...)):
    try:
        removed = await _svc().delete_import(import_id)
        return {"success": True, "removed": removed}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise _handle_error(e, "import deletion")


@router.get("/forensics/imports/{import_id}/overview")
async def overview(import_id: str = Path(...)):
    try:
        data = await _svc().overview(import_id)
        return {"success": True, **data}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise _handle_error(e, "overview")


@router.get("/forensics/imports/{import_id}/sessions")
async def sessions(import_id: str = Path(...)):
    try:
        return {"success": True, "sessions": await _svc().sessions(import_id)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise _handle_error(e, "sessions")


@router.get("/forensics/imports/{import_id}/messages")
async def messages(
    import_id: str = Path(...),
    talker: Optional[str] = Query(None, description="Filter by peer/group uin"),
    msg_type: Optional[int] = Query(None, description="Filter by outer message type (40011)"),
    keyword: Optional[str] = Query(None, description="Content keyword filter"),
    start_ts: Optional[int] = Query(None, description="Earliest timestamp (ms)"),
    end_ts: Optional[int] = Query(None, description="Latest timestamp (ms)"),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    try:
        result = await _svc().messages(
            import_id, talker=talker, msg_type=msg_type, keyword=keyword,
            start_ts=start_ts, end_ts=end_ts, limit=limit, offset=offset,
        )
        return {"success": True, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise _handle_error(e, "message query")


@router.get("/forensics/imports/{import_id}/contacts")
async def contacts(import_id: str = Path(...)):
    try:
        return {"success": True, "contacts": await _svc().contacts(import_id)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise _handle_error(e, "contacts")


@router.get("/forensics/imports/{import_id}/chatrooms")
async def chatrooms(import_id: str = Path(...)):
    try:
        return {"success": True, "chatrooms": await _svc().chatrooms(import_id)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise _handle_error(e, "chatrooms")
