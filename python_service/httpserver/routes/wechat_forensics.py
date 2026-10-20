"""WeChat forensics (微信取证) routes.

Direct import/parse pipeline for a decrypted (or encrypted) Android WeChat
account database. Mounted under ``/api/wechat`` alongside the existing
relationship-graph endpoints:

  POST   /forensics/imports                  create an import
  GET    /forensics/imports                  list imports
  GET    /forensics/imports/{id}             import summary
  DELETE /forensics/imports/{id}             remove an import
  GET    /forensics/imports/{id}/overview    forensic overview
  GET    /forensics/imports/{id}/sessions    chat sessions (talkers)
  GET    /forensics/imports/{id}/messages    paginated readable messages
  GET    /forensics/imports/{id}/contacts    readable contact list
  GET    /forensics/imports/{id}/chatrooms   group details + members
  GET    /forensics/imports/{id}/media/{path}  media files (thumbnails)
"""

import asyncio
import logging
import mimetypes
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query
from fastapi.responses import FileResponse

from ..services.wechat_import_service import get_wechat_import_service
from .timeline_summary import wechat_router as timeline_summary_router

logger = logging.getLogger(__name__)
router = APIRouter()
router.include_router(timeline_summary_router)


def _svc():
    return get_wechat_import_service()


def _handle_error(e: Exception, what: str, code: int = 500) -> HTTPException:
    logger.error("%s failed: %s", what, e, exc_info=True)
    return HTTPException(status_code=code, detail=f"{what} failed: {e}")


@router.post("/forensics/imports")
async def create_import(payload: dict = Body(...)):
    """Create a WeChat forensics import.

    Body fields:
      db_path      : absolute path to EnMicroMsg.db (encrypted or plaintext)
      wal_path     : optional explicit -wal path (auto-detected next to db)
      password     : optional SQLCipher password; if omitted it is derived
                     from key_material (UIN/IMEI/wxid)
      media_dir    : optional account directory containing image2/ etc.
      key_material : {uin, imei, wxid, account_dir} for derivation & record
      name         : human label for the import
      backup_source: free-form origin description (e.g. MIUI backup path)
    """
    try:
        db_path = (payload.get("db_path") or "").strip()
        if not db_path:
            raise HTTPException(status_code=400, detail="db_path is required")
        result = await _svc().create_import(
            db_path=db_path,
            name=(payload.get("name") or "").strip(),
            password=(payload.get("password") or "").strip(),
            wal_path=(payload.get("wal_path") or "").strip() or None,
            media_dir=(payload.get("media_dir") or "").strip() or None,
            key_material=payload.get("key_material") or {},
            backup_source=(payload.get("backup_source") or "").strip(),
        )
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
        return {"success": True, "imports": await _import_list()}
    except Exception as e:
        raise _handle_error(e, "import listing")


async def _import_list():
    from ..services.wechat_import_service import list_imports as _list
    return await asyncio.to_thread(_list)


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
    talker: Optional[str] = Query(None, description="Filter by session talker"),
    msg_type: Optional[int] = Query(None, description="Filter by base message type (1/3/47/49/...)"),
    keyword: Optional[str] = Query(None, description="Content keyword filter"),
    start_ts: Optional[int] = Query(None, description="Earliest createTime (ms)"),
    end_ts: Optional[int] = Query(None, description="Latest createTime (ms)"),
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


@router.get("/forensics/imports/{import_id}/media/{rel_path:path}")
async def media(import_id: str = Path(...), rel_path: str = Path(...)):
    try:
        path = _svc().media_path(import_id, rel_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if path is None:
        raise HTTPException(status_code=404, detail="media not found")
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return FileResponse(path, media_type=mime)
