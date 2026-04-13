"""
Multi-image analysis routes.

API:
  POST /api/llm/cases                          — create a Case record
  GET  /api/llm/cases                          — list all cases
  GET  /api/llm/cases/{case_id}               — get one case
  POST /api/llm/cases/{case_id}/tasks         — add task_ids to case
  POST /api/llm/multi-image-analysis          — start cross-image analysis
  GET  /api/llm/multi-image-analysis/{job_id} — poll job status
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory job store (same pattern as case_analysis.py)
_jobs: Dict[str, Dict[str, Any]] = {}


# ── Pydantic Models ───────────────────────────────────────────────────────────

class CreateCaseRequest(BaseModel):
    name: str              = Field(..., description="案件名称")
    description: str       = Field(default="", description="案情描述")
    task_ids: List[str]    = Field(default_factory=list)


class AddTasksRequest(BaseModel):
    task_ids: List[str] = Field(..., description="要添加的任务 ID 列表")


class MultiImageAnalysisRequest(BaseModel):
    case_id: str           = Field(..., description="案件 ID（C++ 后端）")
    task_ids: List[str]    = Field(..., description="所有任务 ID（顺序与 files_db_paths 对应）")
    files_db_paths: List[str] = Field(..., description="_files.db 路径列表")
    case_description: str  = Field(..., description="案情描述")
    max_filter_files: int  = Field(default=400, ge=1, le=2000)


# ── Case CRUD (proxy to C++ backend) ─────────────────────────────────────────

@router.post("/api/llm/cases", status_code=201)
async def create_case(
    req: CreateCaseRequest,
    settings: Settings = Depends(get_settings),
):
    """Create a ForensicCase via C++ backend and return the new case object."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{settings.cpp_backend_url}/api/cases",
            json=req.model_dump(),
        )
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


@router.get("/api/llm/cases")
async def list_cases(settings: Settings = Depends(get_settings)):
    """List all ForensicCases from C++ backend."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{settings.cpp_backend_url}/api/cases")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


@router.get("/api/llm/cases/{case_id}")
async def get_case(case_id: str, settings: Settings = Depends(get_settings)):
    """Get a single ForensicCase by ID."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{settings.cpp_backend_url}/api/cases/{case_id}")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Case not found")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


@router.post("/api/llm/cases/{case_id}/tasks")
async def add_tasks_to_case(
    case_id: str,
    req: AddTasksRequest,
    settings: Settings = Depends(get_settings),
):
    """Add task IDs to an existing case."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(
            f"{settings.cpp_backend_url}/api/cases/{case_id}/tasks",
            json=req.model_dump(),
        )
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


# ── Multi-Image Analysis ──────────────────────────────────────────────────────

@router.post("/api/llm/multi-image-analysis")
async def start_multi_image_analysis(
    req: MultiImageAnalysisRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Start cross-image LLM analysis for a ForensicCase.
    Returns a job_id for polling.
    """
    if len(req.task_ids) != len(req.files_db_paths):
        raise HTTPException(
            status_code=400,
            detail="task_ids and files_db_paths must have the same length",
        )

    from ..dependencies import get_case_analysis_service
    svc = get_case_analysis_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Case analysis service not ready")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id":    job_id,
        "case_id":   req.case_id,
        "status":    "running",
        "progress":  {},
        "result":    None,
        "error":     None,
        "created_at": datetime.utcnow().isoformat(),
    }

    # Update C++ case status to ANALYSING
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.put(
                f"{settings.cpp_backend_url}/api/cases/{req.case_id}/status",
                json={"status": "analysing", "cross_analysis_job_id": job_id},
            )
    except Exception:
        pass

    async def _run():
        async def progress_cb(stage: str, msg: str):
            _jobs[job_id]["progress"] = {"stage": stage, "message": msg}

        try:
            result = await svc.run_multi_image_analysis(
                case_id=req.case_id,
                task_ids=req.task_ids,
                files_db_paths=req.files_db_paths,
                case_description=req.case_description,
                max_filter_files=req.max_filter_files,
                progress_callback=progress_cb,
            )
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["result"] = result
            # Update C++ case status to COMPLETED
            async with httpx.AsyncClient(timeout=5) as client:
                await client.put(
                    f"{settings.cpp_backend_url}/api/cases/{req.case_id}/status",
                    json={"status": "completed"},
                )
        except Exception as e:
            logger.error(f"[MULTI_ANALYSIS] Job {job_id} failed: {e}", exc_info=True)
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"]  = str(e)
            async with httpx.AsyncClient(timeout=5) as client:
                await client.put(
                    f"{settings.cpp_backend_url}/api/cases/{req.case_id}/status",
                    json={"status": "failed"},
                )

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "running", "case_id": req.case_id}


@router.get("/api/llm/multi-image-analysis/{job_id}")
async def get_multi_analysis_status(job_id: str):
    """Poll the status of a multi-image analysis job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job
