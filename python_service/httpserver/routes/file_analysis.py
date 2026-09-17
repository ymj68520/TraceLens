"""Task-level file-analysis endpoints (SPEC file-analysis D18 / §8.1).

Mirrors the event-cluster-analysis endpoint family: an estimate (read-only
budget preview), a background run (job convention of the newest route
modules — a module-level registry), run status, and the analysis-record
version chain.
"""

import asyncio
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Background run jobs (module-level registry, event-cluster-analysis style).
_run_jobs = {}


class FileAnalysisEstimateRequest(BaseModel):
    task_id: str


class FileAnalysisRunRequest(BaseModel):
    task_id: str
    file_paths: Optional[List[str]] = None
    case_description: str = ""


async def _resolve_task_files(service_manager, task_id: str):
    task_info = await service_manager.cpp_backend.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    files_db = task_info.get("output_files_db") or ""
    if not files_db:
        raise HTTPException(status_code=400, detail="No files database for this task")
    return task_info, files_db


@router.post("/file-analysis/estimate")
async def estimate_file_analysis(
    request: FileAnalysisEstimateRequest,
    settings=Depends(get_settings),
):
    """Read-only budget preview (SPEC §8.1): candidate counts + cost estimate.

    ``pending`` counts the filtered files without an analysis record — the
    exact workload a subsequent ``run`` would execute.
    """
    from ..services import get_service_manager
    from ..services.case_analysis.db_utils import get_filtered_files_from_db
    from ..services.case_analysis.file_schema import (
        analysis_stats,
        latest_analysis,
    )

    service_manager = get_service_manager()
    _task_info, files_db = await _resolve_task_files(service_manager, request.task_id)

    filtered = get_filtered_files_from_db(files_db, request.task_id)
    pending_paths = [
        path for path in filtered
        if latest_analysis(files_db, path) is None
    ]
    stats = analysis_stats(files_db)

    return {
        "task_id": request.task_id,
        "filtered_total": len(filtered),
        "analyzed": len(filtered) - len(pending_paths),
        "pending": len(pending_paths),
        "stale": stats.get("stale", 0),
        "estimated_llm_calls": len(pending_paths),
        "estimated_chars": len(pending_paths) * max(
            int(getattr(settings, "file_analysis_max_content", 10000) or 10000), 0
        ),
    }


@router.post("/file-analysis/run")
async def run_file_analysis(request: FileAnalysisRunRequest):
    """Run the case-driven file-description round as a background job.

    Targets ``file_paths`` when given, otherwise the task's filtered file
    list. Skip/analysis semantics are the pipeline's (§4): files with a
    truth record are skipped.
    """
    from .case_analysis_endpoints._helpers import get_case_analysis_service
    from ..services import get_service_manager
    from ..services.case_analysis.db_utils import get_filtered_files_from_db

    service_manager = get_service_manager()
    task_info, files_db = await _resolve_task_files(service_manager, request.task_id)

    paths = list(request.file_paths or []) or get_filtered_files_from_db(
        files_db, request.task_id
    )
    if not paths:
        raise HTTPException(
            status_code=400,
            detail="no candidate files: run case filtering first or pass file_paths",
        )

    case_service = get_case_analysis_service(service_manager)
    extraction_dir = task_info.get("extraction_directory") or ""

    job_id = str(uuid.uuid4())
    _run_jobs[job_id] = {
        "status": "running",
        "task_id": request.task_id,
        "processed": 0,
        "total": len(paths),
        "results": [],
        "errors": [],
    }

    def _progress(processed, total, file_path):
        job = _run_jobs.get(job_id)
        if job is not None:
            job["processed"] = processed
            job["total"] = total
            job["current_file"] = file_path

    async def _worker():
        job = _run_jobs.get(job_id)
        try:
            results = await case_service.generate_file_descriptions(
                files_db, paths, request.case_description,
                extraction_dir=extraction_dir, progress_callback=_progress,
                task_id=request.task_id,
            )
            job["results"] = results
            job["processed"] = len(results)
            job["status"] = "completed"
        except Exception as e:
            logger.error(f"file-analysis run {job_id} failed: {e}", exc_info=True)
            job["status"] = "failed"
            job["errors"].append(str(e))

    asyncio.create_task(_worker())

    return {
        "job_id": job_id,
        "task_id": request.task_id,
        "total": len(paths),
        "status": "running",
    }


@router.get("/file-analysis/run/{job_id}")
async def get_file_analysis_run_status(job_id: str):
    job = _run_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Run job not found")
    return dict(job)


@router.get("/file-analyses")
async def list_file_analyses(
    task_id: str = Query(..., description="Task ID"),
    file_path: Optional[str] = Query(None, description="Version chain of one file"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Query the append-only file analysis records (version chain)."""
    from ..services import get_service_manager
    from ..services.case_analysis.file_schema import list_analyses

    service_manager = get_service_manager()
    _task_info, files_db = await _resolve_task_files(service_manager, task_id)

    records = list_analyses(files_db, task_id, file_path=file_path, limit=limit)
    return {
        "task_id": task_id,
        "file_path": file_path,
        "total": len(records),
        "records": records,
    }


class FileAnalysisRecordRequest(BaseModel):
    """One pipeline file-analysis result, persisted through the SPEC three-write.

    llm-throughput-hardening SPEC E: the C++ pipeline previously maintained a
    hand-synced copy of the display-cache writes and skipped the append-only
    ``file_analyses`` truth row entirely. It now POSTs each result here so the
    tested Python three-write path stays the single writer.
    """

    task_id: str
    file_path: str
    description: str
    summary: str = ""
    keywords: str = ""  # comma-separated
    model_used: str = ""
    extraction_method: str = ""  # markitdown / raw_text / vision / metadata_only


@router.post("/file-analysis/record")
async def record_file_analysis(request: FileAnalysisRecordRequest):
    """Persist one pipeline analysis via the atomic three-write (SPEC E).

    ``files_db_path`` is resolved from the task record (D2b trust source), so
    the caller cannot redirect writes at an arbitrary database.
    """
    from ..services import get_service_manager

    service_manager = get_service_manager()
    _task_info, files_db = await _resolve_task_files(service_manager, request.task_id)

    llm_service = getattr(service_manager, "llm_service", None)
    if llm_service is None:
        raise HTTPException(status_code=503, detail="LLM service unavailable")

    persisted = await asyncio.to_thread(
        llm_service.persist_to_files_db,
        files_db,
        request.file_path,
        request.description,
        request.summary,
        request.keywords,
        request.model_used,
        request.task_id,
        "pipeline",
        request.extraction_method,
    )
    if not persisted:
        raise HTTPException(
            status_code=500,
            detail=f"persist_to_files_db failed for {request.file_path!r}",
        )
    return {
        "persisted": True,
        "task_id": request.task_id,
        "file_path": request.file_path,
        "trigger_source": "pipeline",
    }
