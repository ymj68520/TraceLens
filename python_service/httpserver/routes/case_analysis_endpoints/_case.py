"""Case-analysis routes — core case-analysis endpoints.

Part of the case_analysis routes split (see case_analysis.py). Endpoints are
decorated with the package-local APIRouter; the parent mounts it under
/api/llm.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from ...config import Settings, get_settings

from ..case_analysis_models import (
    AnalysisStatusResponse,
    CaseAnalysisRequest,
    CaseAnalysisResponse,
    CaseDescriptionRequest,
    CaseDescriptionResponse,
    CaseReportResponse,
    FilteredFilesResponse,
    ReanalyzeRequest,
    ReanalyzeResponse,
)
from ._helpers import (
    _analysis_jobs,
    get_case_analysis_service as _get_case_analysis_service,
    run_case_analysis_background as _run_case_analysis_background,
    run_reanalyze_background as _run_reanalyze_background,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/case-description", response_model=CaseDescriptionResponse, responses={
    200: {"description": "Case description saved successfully"},
    500: {"description": "Internal server error"},
})
async def save_case_description(
    request: CaseDescriptionRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Save case description.

    The case description is persisted through the C++ task system (tasks.json).
    This endpoint also forwards the description to the C++ backend.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        # Forward to C++ backend to persist in tasks.json
        try:
            cpp_url = settings.cpp_backend_url
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.put(
                    f"{cpp_url}/api/tasks/{request.task_id}",
                    json={"case_description": request.case_description},
                )
                if resp.status_code not in (200, 204):
                    logger.warning(f"C++ backend returned {resp.status_code} for case description update")
        except Exception as e:
            logger.warning(f"Could not forward case description to C++ backend: {e}")

        return CaseDescriptionResponse(
            success=True,
            task_id=request.task_id,
            message="案情描述已保存",
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Save case description failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="save case description failed")
@router.post("/case-analysis", response_model=CaseAnalysisResponse, responses={
    200: {"description": "Case analysis started successfully"},
    422: {"description": "Validation error"},
    500: {"description": "Internal server error"},
})
async def start_case_analysis(
    request: CaseAnalysisRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Start the full case analysis pipeline.

    This operation runs in the background:
    1. LLM filters relevant files based on case description
    2. Generates per-file descriptions for filtered files
    3. Generates a comprehensive case report

    Returns a job_id for tracking progress.
    """
    import uuid

    try:
        from ...services import get_service_manager, task_store
        service_manager = get_service_manager()

        # The task identity comes from the request; the analysis target is
        # the task-owned files database resolved server-side (D2b). A supplied
        # files_db_path is a deprecated exact-validated hint — task identity
        # is never derived from a client path.
        task_id = request.task_id
        try:
            trusted_files_db = await task_store.resolve_task_files_db(task_id)
            task_store.validate_legacy_db_path(
                request.files_db_path, trusted_files_db
            )
        except task_store.TaskStoreError as exc:
            if exc.code == task_store.TASK_NOT_FOUND:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Validate inputs
        logger.info(f"Starting case analysis for task {task_id}")
        logger.info(f"trusted files_db_path: '{trusted_files_db}'")
        logger.info(f"case_description length: {len(request.case_description)}")
        logger.info(f"max_filter_files: {request.max_filter_files}")
        logger.info(f"run_filtering: {request.run_filtering}")

        # Get or create case analysis service
        case_service = _get_case_analysis_service(service_manager)

        job_id = str(uuid.uuid4())
        _analysis_jobs[job_id] = {
            "status": "running",
            "current_step": "初始化",
            "detail": "正在启动案情分析...",
            "task_id": task_id,
            "result": None,
        }

        # Run analysis in background
        asyncio.create_task(
            _run_case_analysis_background(
                job_id=job_id,
                case_service=case_service,
                task_id=task_id,
                files_db_path=str(trusted_files_db),
                case_description=request.case_description,
                max_filter_files=request.max_filter_files,
                run_filtering=request.run_filtering,
                report_only=request.report_only,
            )
        )

        return CaseAnalysisResponse(
            success=True,
            task_id=task_id,
            job_id=job_id,
            message="案情分析已启动",
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Start case analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="case analysis could not be started")
@router.post("/reanalyze-files", response_model=ReanalyzeResponse, responses={
    200: {"description": "Re-analysis started successfully"},
    400: {"description": "Invalid request"},
    500: {"description": "Internal server error"},
})
async def reanalyze_files(
    request: ReanalyzeRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Re-analyze files with additional user context.

    Used for secondary analysis when the user is unsatisfied with
    the initial description. Combines case description + knowledge
    graph context + user hint for improved results.

    Supports multiple files with the same user hint.
    """
    import uuid

    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        case_service = _get_case_analysis_service(service_manager)

        job_id = str(uuid.uuid4())

        # Log request details
        logger.info(f"Reanalyze request received - task_id: {request.task_id}, "
                   f"files: {len(request.file_paths)}, "
                   f"user_hint: {request.user_hint[:50] if request.user_hint else ''}...")

        # The persistence target is the task-owned files database resolved
        # server-side (D2b); a supplied files_db_path is an exact-validated
        # deprecated hint. Case description still falls back to task info.
        from ...services import task_store

        case_desc = request.case_description
        try:
            task_info = await task_store.get_task_record(request.task_id)
            trusted_files_db = await task_store.resolve_task_files_db(request.task_id)
            task_store.validate_legacy_db_path(
                request.files_db_path, trusted_files_db
            )
            if not case_desc:
                case_desc = task_info.get("case_description", "")
        except task_store.TaskStoreError as exc:
            if exc.code == task_store.TASK_NOT_FOUND:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        files_db_path = str(trusted_files_db)
        logger.info(f"Reanalyze persistence target resolved from task: {files_db_path!r}")

        _analysis_jobs[job_id] = {
            "status": "running",
            "current_step": "重新分析",
            "detail": f"正在重新分析 {len(request.file_paths)} 个文件...",
            "task_id": request.task_id,
            "result": None,
        }

        asyncio.create_task(
            _run_reanalyze_background(
                job_id=job_id,
                case_service=case_service,
                task_id=request.task_id,
                file_paths=request.file_paths,
                user_hint=request.user_hint,
                files_db_path=files_db_path,
                case_description=case_desc,
            )
        )

        return ReanalyzeResponse(
            success=True,
            job_id=job_id,
            file_count=len(request.file_paths),
            message=f"已启动 {len(request.file_paths)} 个文件的重新分析",
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Start reanalyze failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="reanalyze could not be started")
@router.get("/case-analysis/{job_id}", response_model=AnalysisStatusResponse, responses={
    200: {"description": "Status retrieved successfully"},
    404: {"description": "Job not found"},
})
async def get_analysis_status(job_id: str):
    """Get the status of a case analysis job."""
    job = _analysis_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return AnalysisStatusResponse(
        success=True,
        job_id=job_id,
        status=job.get("status", "unknown"),
        current_step=job.get("current_step"),
        detail=job.get("detail"),
        result=job.get("result"),
        timestamp=datetime.now().isoformat(),
    )
@router.get("/case-report/{task_id}", response_model=CaseReportResponse, responses={
    200: {"description": "Report retrieved successfully"},
    404: {"description": "Report not found"},
    500: {"description": "Internal server error"},
})
async def get_case_report(
    task_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    Get the case analysis report for a task.

    Retrieves the persisted report from the _files.db database.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        # Get task info to find _files.db path
        task_info = await service_manager.cpp_backend.get_task(task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        files_db_path = task_info.get("output_files_db", "")
        if not files_db_path:
            raise HTTPException(
                status_code=404,
                detail="Task has no associated files database",
            )

        case_service = _get_case_analysis_service(service_manager)
        report = case_service.get_case_report(files_db_path, task_id)

        if not report:
            raise HTTPException(
                status_code=404,
                detail="No case report found for this task",
            )

        return CaseReportResponse(
            success=True,
            task_id=task_id,
            case_description=report.get("case_description"),
            report=report.get("case_report"),
            filtered_files=report.get("filtered_files", []),
            generated_at=str(report.get("updated_at", "")),
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get case report failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="case report is unavailable")

@router.get("/case-report-by-case/{case_id}", response_model=CaseReportResponse, responses={
    200: {"description": "Cross-image report retrieved successfully"},
    404: {"description": "Report not found"},
    500: {"description": "Internal server error"},
})
async def get_case_report_by_case(
    case_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    Get the cross-image analysis report for a ForensicCase.

    Unlike /case-report/{task_id} (single-task, keyed on a task's _files.db),
    this endpoint retrieves the cross-image report that is persisted to the
    case-level database (data/cases/{case_id}/{case_id}.db) keyed by case_id.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        case_service = _get_case_analysis_service(service_manager)
        report = case_service.get_cross_image_report(case_id)

        if not report:
            raise HTTPException(
                status_code=404,
                detail="No cross-image report found for this case. "
                       "Ensure cross-image analysis has completed.",
            )

        return CaseReportResponse(
            success=True,
            task_id=case_id,
            case_description=report.get("case_description"),
            report=report.get("case_report"),
            filtered_files=report.get("filtered_files", []),
            generated_at=str(report.get("updated_at", "")),
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get cross-image case report failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="case report is unavailable")

@router.get("/filtered-files/{task_id}", response_model=FilteredFilesResponse, responses={
    200: {"description": "Filtered files retrieved"},
    404: {"description": "Task not found"},
})
async def get_filtered_files(
    task_id: str,
    settings: Settings = Depends(get_settings),
):
    """Get the LLM-filtered file list for a task."""
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        task_info = await service_manager.cpp_backend.get_task(task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        files_db_path = task_info.get("output_files_db", "")
        case_service = _get_case_analysis_service(service_manager)
        filtered = case_service.get_filtered_files(files_db_path)

        return FilteredFilesResponse(
            success=True,
            filtered_files=filtered,
            total_count=len(filtered),
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get filtered files failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="filtered files are unavailable")
