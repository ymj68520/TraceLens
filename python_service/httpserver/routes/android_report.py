"""Read-only third-party Android forensic report import and query API."""

import asyncio
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from ..services import android_report_import as reports
from ..services import get_service_manager

router = APIRouter()


@router.get("/candidates")
async def list_candidates():
    return {"success": True, "candidates": await asyncio.to_thread(reports.list_candidates)}


@router.post("/imports", status_code=201)
async def create_import(payload: dict = Body(...)):
    candidate_id = payload.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise HTTPException(status_code=400, detail="candidate_id is required")
    try:
        return {"success": True, "import": await asyncio.to_thread(
            reports.create_import_from_candidate, candidate_id,
        )}
    except (reports.InvalidReport, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/imports")
async def list_imports(task_id: str | None = Query(None, max_length=128)):
    return {"success": True, "imports": await asyncio.to_thread(reports.list_imports, task_id)}


@router.post("/imports/{import_id}/tasks")
async def attach_to_task(import_id: str, payload: dict = Body(...)):
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 128:
        raise HTTPException(status_code=400, detail="task_id is required")
    task = await get_service_manager().cpp_backend.get_task(task_id, timeout=5.0, max_retries=1)
    if not isinstance(task, dict) or task.get("id") != task_id:
        raise HTTPException(status_code=404, detail="task not found")
    try:
        meta = await asyncio.to_thread(reports.set_task_link, import_id, task_id, linked=True)
        return {"success": True, "import": meta}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/imports/{import_id}/tasks/{task_id}")
async def detach_from_task(import_id: str, task_id: str):
    try:
        meta = await asyncio.to_thread(reports.set_task_link, import_id, task_id, linked=False)
        return {"success": True, "import": meta}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/imports/{import_id}/overview")
async def overview(import_id: str):
    try:
        return {"success": True, "overview": await asyncio.to_thread(reports.overview, import_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/imports/{import_id}/manifest")
async def manifest(import_id: str):
    try:
        return {"success": True, "manifest": await asyncio.to_thread(reports.read_manifest, import_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/imports/{import_id}/coverage")
async def coverage(import_id: str):
    try:
        return {"success": True, "coverage": await asyncio.to_thread(reports.read_coverage, import_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/imports/{import_id}/records")
async def records(
    import_id: str,
    query: str = Query("", max_length=200),
    category: str = Query("", max_length=80),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    try:
        result = await asyncio.to_thread(
            reports.records, import_id, query=query, category=category,
            page=page, page_size=page_size,
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/imports/{import_id}/records/{record_id}")
async def record_detail(import_id: str, record_id: str):
    try:
        return {"success": True, "record": await asyncio.to_thread(reports.record_detail, import_id, record_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/imports/{import_id}/attachment")
async def attachment(import_id: str, path: str = Query(min_length=1)):
    try:
        source = await asyncio.to_thread(reports.attachment_file, import_id, path)
        return FileResponse(
            source, filename=Path(source).name,
            media_type="application/octet-stream",
            content_disposition_type="attachment",
            headers={"X-Content-Type-Options": "nosniff"},
        )
    except reports.InvalidReport as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/imports/{import_id}/source-page")
async def source_page(import_id: str, path: str = Query(min_length=1)):
    try:
        source = await asyncio.to_thread(reports.source_page_file, import_id, path)
        return FileResponse(
            source, filename=Path(source).name + ".txt", media_type="text/plain; charset=utf-8",
            content_disposition_type="attachment",
            headers={"X-Content-Type-Options": "nosniff"},
        )
    except reports.InvalidReport as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/imports/{import_id}/source-location/{record_id}")
async def source_location(import_id: str, record_id: str):
    try:
        content = await asyncio.to_thread(reports.source_location_html, import_id, record_id)
        return HTMLResponse(content, headers={
            "Content-Security-Policy": "default-src 'none'; base-uri 'none'; form-action 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        })
    except reports.InvalidReport as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
