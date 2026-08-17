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
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from ..config import Settings, get_settings
from ..dependencies import get_case_analysis_service

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


class AssociateTasksRequest(BaseModel):
    task_ids: List[str] = Field(..., description="要关联（通常已完成分析）的任务 ID 列表")


class MultiImageAnalysisRequest(BaseModel):
    case_id: str           = Field(..., description="案件 ID（C++ 后端）")
    task_ids: List[str]    = Field(..., description="所有任务 ID（顺序与 files_db_paths 对应）")
    files_db_paths: List[str] = Field(..., description="_files.db 路径列表")
    case_description: str  = Field(..., description="案情描述")
    max_filter_files: int  = Field(default=400, ge=1, le=2000)


# ── New Request Models for Incremental Analysis ───────────────────────────────────

class SmartCreateCaseRequest(BaseModel):
    name: str = Field(..., description="案件名称")
    description: str = Field(default="", description="案情描述")
    auto_associate: bool = Field(default=True, description="自动关联已完成任务")
    auto_analyze: bool = Field(default=True, description="自动执行分析")


class IncrementalAddTasksRequest(BaseModel):
    new_task_ids: List[str] = Field(..., description="新任务ID列表")
    auto_analyze: bool = Field(default=True, description="自动执行增量分析")


class IncrementalAnalysisRequest(BaseModel):
    force_reanalyze: bool = Field(default=False, description="强制重新分析所有任务")
    new_task_ids: List[str] = Field(default_factory=list, description="额外的新任务ID列表")


class TaskStatusItem(BaseModel):
    task_id: str
    analysis_status: str
    files_count: int = 0
    analyzed_files_count: int = 0
    last_analysis_time: Optional[int] = None
    error_message: Optional[str] = None


class CaseAnalysisStatusResponse(BaseModel):
    case_id: str
    total_tasks: int
    analyzed_tasks: int
    pending_tasks: int
    failed_tasks: int
    total_files: int
    analyzed_files: int
    tasks: List[TaskStatusItem]


# ── Case CRUD (proxy to C++ backend) ─────────────────────────────────────────

@router.post("/api/llm/cases", status_code=201)
async def create_case(
    req: CreateCaseRequest,
    settings: Settings = Depends(get_settings),
    raw_request: Request = None,
):
    """Create a ForensicCase via C++ backend and return the new case object."""
    try:
        logger.info(f"[CREATE_CASE] Received request: name={req.name}, description={req.description}, task_ids={req.task_ids}")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{settings.cpp_backend_url}/api/cases",
                json=req.model_dump(),
            )
        logger.info(f"[CREATE_CASE] C++ backend response: status={r.status_code}, body={r.text[:200]}")
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CREATE_CASE] Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="case creation failed")


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


@router.delete("/api/llm/cases/{case_id}")
async def delete_case(case_id: str, settings: Settings = Depends(get_settings)):
    """Delete a ForensicCase via C++ backend. Does NOT delete associated tasks."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.delete(f"{settings.cpp_backend_url}/api/cases/{case_id}")
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="Case not found")
        if r.status_code not in (200, 204):
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[DELETE_CASE] Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="case deletion failed")


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


@router.post("/api/llm/cases/{case_id}/associate-tasks")
async def associate_tasks_to_case(
    case_id: str,
    req: AssociateTasksRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Associate already-completed tasks to a case, correctly pre-populating the
    case-level analysis-state row for each.

    Unlike POST /api/llm/cases/{case_id}/tasks (which only edits the case's
    task_ids list), this endpoint inspects each task's real _files.db and
    writes an 'analyzed' / 'pending' state row so a subsequent cross-image
    analysis REUSES already-analyzed tasks instead of re-analyzing them.

    Returns a per-task breakdown:
      - associated:       task IDs newly added to the case
      - reused:           associated tasks that already have descriptions
      - pending_analysis: associated tasks without descriptions yet
      - skipped:          task IDs already present in the case
      - not_found:        task IDs that could not be resolved
      - not_completed:    task IDs not yet finished analyzing
    """
    if not req.task_ids:
        raise HTTPException(status_code=400, detail="task_ids cannot be empty")

    svc = get_case_analysis_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Case analysis service not ready")

    try:
        result = await svc.associate_tasks_to_case(case_id, req.task_ids)
        return {"case_id": case_id, **result}
    except Exception as e:
        logger.error(f"[ASSOCIATE_TASKS] Failed for case {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="case task association failed")


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

    # Each analysis target is resolved server-side from its own task_id
    # (D2b); the parallel files_db_paths entries are deprecated exact-
    # validated hints, never the authority.
    from ..services import task_store

    trusted_paths = []
    for task_id, supplied_path in zip(req.task_ids, req.files_db_paths):
        try:
            trusted = await task_store.resolve_task_files_db(task_id)
            task_store.validate_legacy_db_path(supplied_path, trusted)
        except task_store.TaskStoreError as exc:
            if exc.code == task_store.TASK_NOT_FOUND:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        trusted_paths.append(str(trusted))

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
                files_db_paths=trusted_paths,
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
            _jobs[job_id]["error"] = "multi-image analysis failed"
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


# ── Incremental Analysis Endpoints ────────────────────────────────────────────────

@router.post("/api/llm/cases/smart-create", status_code=201)
async def smart_create_case(
    req: SmartCreateCaseRequest,
    settings: Settings = Depends(get_settings),
):
    """
    智能创建案件 - 自动发现并关联已完成任务

    Flow:
    1. 创建案件
    2. 扫描所有已完成的任务
    3. 自动关联到案件
    4. （可选）执行增量分析
    """
    svc = get_case_analysis_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Case analysis service not ready")

    async def progress_cb(stage: str, msg: str):
        # Could emit WebSocket event here for real-time updates
        pass

    result = await svc.run_smart_case_analysis(
        case_name=req.name,
        case_description=req.description,
        auto_associate=req.auto_associate,
        auto_analyze=req.auto_analyze,
        progress_callback=progress_cb,
    )

    return {
        "case_id": result.get("case_id"),
        "name": req.name,
        "description": req.description,
        "steps": result.get("steps", {}),
    }


@router.post("/api/llm/cases/{case_id}/tasks/incremental")
async def incremental_add_tasks(
    case_id: str,
    req: IncrementalAddTasksRequest,
    settings: Settings = Depends(get_settings),
):
    """
    增量添加任务到案件并执行增量分析

    仅分析新增的任务，复用已有任务的分析结果。
    """
    svc = get_case_analysis_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Case analysis service not ready")

    # First add tasks to case (C++ backend)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            for task_id in req.new_task_ids:
                await client.put(
                    f"{settings.cpp_backend_url}/api/cases/{case_id}/tasks",
                    json={"task_ids": [task_id]},
                )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add tasks to case: {e}")

    # Then run incremental analysis if requested
    if req.auto_analyze:
        result = await svc.run_incremental_analysis(
            case_id=case_id,
            new_task_ids=req.new_task_ids,
        )
        return {"case_id": case_id, "steps": result.get("steps", {})}

    return {"case_id": case_id, "message": "Tasks added, analysis not requested"}


@router.get("/api/llm/cases/{case_id}/analysis-status")
async def get_case_analysis_status(
    case_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    查询案件分析状态

    返回每个任务的分析状态、文件数量等详细信息。
    """
    svc = get_case_analysis_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Case analysis service not ready")

    if not svc._case_aggregation:
        raise HTTPException(status_code=503, detail="Case aggregation manager not initialized")

    status = await svc._case_aggregation.get_case_analysis_status(case_id)
    return status


@router.post("/api/llm/cases/{case_id}/incremental-analysis")
async def trigger_incremental_analysis(
    case_id: str,
    req: IncrementalAnalysisRequest,
    settings: Settings = Depends(get_settings),
):
    """
    手动触发增量分析

    可以选择强制重新分析所有任务。
    """
    svc = get_case_analysis_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Case analysis service not ready")

    # Run incremental analysis in background
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "case_id": case_id,
        "status": "running",
        "result": None,
        "error": None,
        "created_at": datetime.utcnow().isoformat(),
    }

    async def _run():
        try:
            result = await svc.run_incremental_analysis(
                case_id=case_id,
                new_task_ids=req.new_task_ids if req.new_task_ids else None,
                force_reanalyze=req.force_reanalyze,
            )
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["result"] = result
        except Exception as e:
            logger.error(f"[INCREMENTAL_ANALYSIS] Job {job_id} failed: {e}", exc_info=True)
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = "incremental analysis failed"

    asyncio.create_task(_run())

    return {"job_id": job_id, "status": "running", "case_id": case_id}
