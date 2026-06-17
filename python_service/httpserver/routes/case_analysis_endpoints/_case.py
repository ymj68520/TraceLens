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
        from ..services import get_service_manager
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
        raise HTTPException(status_code=500, detail=str(e))
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
    import re

    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()

        # Extract task_id from files_db_path if not provided
        task_id = request.task_id
        if not task_id:
            # Extract task_id from path like: /path/to/tasks/{task_id}/files.db
            match = re.search(r'/tasks/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})/files\.db', request.files_db_path)
            if match:
                task_id = match.group(1)
                logger.info(f"Extracted task_id from files_db_path: {task_id}")
            else:
                logger.error("Cannot extract task_id from files_db_path and task_id not provided")
                raise HTTPException(
                    status_code=422,
                    detail="Cannot extract task_id from files_db_path. Please provide task_id explicitly."
                )

        # Validate inputs
        logger.info(f"Starting case analysis for task {task_id}")
        logger.info(f"files_db_path: '{request.files_db_path}'")
        logger.info(f"case_description length: {len(request.case_description)}")
        logger.info(f"max_filter_files: {request.max_filter_files}")
        logger.info(f"run_filtering: {request.run_filtering}")

        # Validate files_db_path is not empty
        if not request.files_db_path or not request.files_db_path.strip():
            logger.error("files_db_path is empty")
            raise HTTPException(
                status_code=422,
                detail="files_db_path cannot be empty. Please ensure the task has completed analysis."
            )

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
                files_db_path=request.files_db_path,
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
    except Exception as e:
        logger.error(f"Start case analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
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
        from ..services import get_service_manager
        service_manager = get_service_manager()

        case_service = _get_case_analysis_service(service_manager)

        job_id = str(uuid.uuid4())

        # Log request details
        logger.info(f"Reanalyze request received - task_id: {request.task_id}, "
                   f"files: {len(request.file_paths)}, "
                   f"files_db_path: {request.files_db_path!r}, "
                   f"user_hint: {request.user_hint[:50] if request.user_hint else ''}...")

        _analysis_jobs[job_id] = {
            "status": "running",
            "current_step": "重新分析",
            "detail": f"正在重新分析 {len(request.file_paths)} 个文件...",
            "task_id": request.task_id,
            "result": None,
        }

        # Get case description and files_db_path from task info if not provided
        case_desc = request.case_description
        files_db_path = request.files_db_path

        if not case_desc or not files_db_path:
            try:
                task_info = await service_manager.cpp_backend.get_task(request.task_id)
                if task_info:
                    if not case_desc:
                        case_desc = task_info.get("case_description", "")
                    if not files_db_path:
                        files_db_path = task_info.get("output_files_db") or task_info.get("output_files_db_path", "")
                        logger.info(f"Retrieved files_db_path from task info: {files_db_path!r}")
            except Exception as e:
                logger.warning(f"Failed to get task info: {e}")

        # Warn if files_db_path is still empty
        if not files_db_path:
            logger.warning(f"No files_db_path provided for task {request.task_id}. "
                         f"Results will NOT be persisted to database!")

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
    except Exception as e:
        logger.error(f"Start reanalyze failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
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
        from ..services import get_service_manager
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
        raise HTTPException(status_code=500, detail=str(e))
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
        from ..services import get_service_manager
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
        raise HTTPException(status_code=500, detail=str(e))
