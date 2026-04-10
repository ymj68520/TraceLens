"""
Case analysis routes.

Provides endpoints for:
- Starting a full case analysis pipeline
- Saving case descriptions
- Retrieving case reports
- Retrieving filtered file lists
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ------------------------------------------------------------------
# Request/Response Models
# ------------------------------------------------------------------

class CaseDescriptionRequest(BaseModel):
    """Request to save a case description."""
    task_id: str = Field(..., description="Task ID")
    case_description: str = Field(default="", description="案情描述")


class CaseDescriptionResponse(BaseModel):
    """Response for saving case description."""
    success: bool
    task_id: str
    message: str
    timestamp: str


class CaseAnalysisRequest(BaseModel):
    """Request to start full case analysis."""
    task_id: str = Field(..., description="Task ID")
    files_db_path: str = Field(..., description="Path to _files.db")
    case_description: str = Field(default="", description="案情描述")
    max_filter_files: int = Field(default=200, ge=1, le=2000, description="Max files to filter")
    run_filtering: bool = Field(default=False, description="是否重新运行 LLM 文件筛选")


class CaseAnalysisResponse(BaseModel):
    """Response for case analysis."""
    success: bool
    task_id: str
    job_id: str
    message: str
    timestamp: str


class CaseReportResponse(BaseModel):
    """Response containing the case report."""
    success: bool
    task_id: str
    case_description: Optional[str] = None
    report: Optional[str] = None
    filtered_files: Optional[List[str]] = None
    files_analyzed: Optional[int] = None
    generated_at: Optional[str] = None
    timestamp: str


class FilteredFilesResponse(BaseModel):
    """Response containing filtered files."""
    success: bool
    filtered_files: List[str]
    total_count: int
    timestamp: str


class AnalysisStatusResponse(BaseModel):
    """Response for analysis job status."""
    success: bool
    job_id: str
    status: str
    current_step: Optional[str] = None
    detail: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    timestamp: str


class ReanalyzeRequest(BaseModel):
    """Request to re-analyze files with user hints."""
    task_id: str = Field(..., description="Task ID")
    file_paths: List[str] = Field(..., min_length=1, description="要重新分析的文件路径列表")
    user_hint: str = Field(..., min_length=1, description="用户补充描述")
    files_db_path: str = Field(..., description="Path to _files.db")
    case_description: str = Field(default="", description="案情描述（可选，为空时自动获取）")


class ReanalyzeResponse(BaseModel):
    """Response for file re-analysis."""
    success: bool
    job_id: str
    file_count: int
    message: str
    timestamp: str


# ------------------------------------------------------------------
# Background job tracking
# ------------------------------------------------------------------
_analysis_jobs: Dict[str, Dict[str, Any]] = {}


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

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

    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()

        # Validate inputs
        logger.info(f"Starting case analysis for task {request.task_id}")
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
            "task_id": request.task_id,
            "result": None,
        }

        # Run analysis in background
        asyncio.create_task(
            _run_case_analysis_background(
                job_id=job_id,
                case_service=case_service,
                task_id=request.task_id,
                files_db_path=request.files_db_path,
                case_description=request.case_description,
                max_filter_files=request.max_filter_files,
                run_filtering=request.run_filtering,
            )
        )

        return CaseAnalysisResponse(
            success=True,
            task_id=request.task_id,
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


# ------------------------------------------------------------------
# Windows Artifacts Analysis Routes
# ------------------------------------------------------------------

@router.post("/windows-analysis", response_model=CaseAnalysisResponse, responses={
    200: {"description": "Windows artifacts analysis started successfully"},
    422: {"description": "Validation error"},
    500: {"description": "Internal server error"},
})
async def start_windows_analysis(
    request: CaseAnalysisRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Start Windows artifacts analysis pipeline.

    This operation runs in the background:
    1. Filters Windows artifacts by case description
    2. Generates LLM descriptions for filtered artifacts
    3. Includes results in knowledge graph

    Returns a job_id for tracking progress.
    """
    import uuid

    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()

        # Get Windows artifacts database path from task info
        task_info = await service_manager.cpp_backend.get_task(request.task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail=f"Task {request.task_id} not found")

        windows_db_path = task_info.get("output_windows_db", "")
        if not windows_db_path:
            raise HTTPException(
                status_code=404,
                detail="Task has no Windows artifacts database",
            )

        case_service = _get_case_analysis_service(service_manager)

        job_id = str(uuid.uuid4())
        _analysis_jobs[job_id] = {
            "status": "running",
            "current_step": "初始化",
            "detail": "正在启动Windows痕迹分析...",
            "task_id": request.task_id,
            "result": None,
        }

        # Run analysis in background
        asyncio.create_task(
            _run_windows_analysis_background(
                job_id=job_id,
                case_service=case_service,
                task_id=request.task_id,
                windows_db_path=windows_db_path,
                case_description=request.case_description,
            )
        )

        return CaseAnalysisResponse(
            success=True,
            task_id=request.task_id,
            job_id=job_id,
            message="Windows痕迹分析已启动",
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Start Windows analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/windows-report/{task_id}", responses={
    200: {"description": "Windows artifacts report retrieved successfully"},
    404: {"description": "Report not found"},
    500: {"description": "Internal server error"},
})
async def get_windows_report(
    task_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    Get the Windows artifacts analysis report for a task.

    Retrieves the persisted Windows artifact analysis from the _windows.db database.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()

        # Get task info to find _windows.db path
        task_info = await service_manager.cpp_backend.get_task(task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        windows_db_path = task_info.get("output_windows_db", "")
        if not windows_db_path:
            raise HTTPException(
                status_code=404,
                detail="Task has no Windows artifacts database",
            )

        case_service = _get_case_analysis_service(service_manager)
        report = case_service.get_windows_report(windows_db_path, task_id)

        if not report:
            raise HTTPException(
                status_code=404,
                detail="No Windows artifact analysis found for this task",
            )

        return {
            "success": True,
            "task_id": task_id,
            **report,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get Windows report failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/windows-export/{task_id}/toon", responses={
    200: {"description": "Windows artifacts exported to TOON format"},
    404: {"description": "Task not found"},
    500: {"description": "Internal server error"},
})
async def export_windows_toon(
    task_id: str,
    artifact_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 100,
    settings: Settings = Depends(get_settings),
):
    """
    Export Windows artifacts to TOON format.

    Query parameters:
    - artifact_type: Specific artifact type (None = all with LLM analysis)
    - severity: Filter by severity (low/medium/high/critical)
    - limit: Maximum records to export (default: 100)
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()

        # Get task info to find _windows.db path
        task_info = await service_manager.cpp_backend.get_task(task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        windows_db_path = task_info.get("output_windows_db", "")
        if not windows_db_path:
            raise HTTPException(
                status_code=404,
                detail="Task has no Windows artifacts database",
            )

        case_service = _get_case_analysis_service(service_manager)

        # Get filtered artifacts
        artifacts = case_service.get_filtered_windows_artifacts(
            windows_db_path=windows_db_path,
            artifact_type=artifact_type,
            severity=severity,
            limit=limit,
        )

        # Export to TOON format
        from ..services.windows_artifacts import WindowsArtifactTOONExporter
        exporter = WindowsArtifactTOONExporter()

        if artifact_type:
            toon_data = exporter.export_artifacts_toon(
                windows_db_path=windows_db_path,
                artifact_type=artifact_type,
                include_llm=True,
                limit=limit,
            )
        else:
            # Export all with LLM analysis, filtered by severity if specified
            where_clause = f"severity = '{severity}'" if severity else None
            toon_data = exporter.export_artifacts_toon(
                windows_db_path=windows_db_path,
                include_llm=True,
                limit=limit,
                where_clause=where_clause,
            )

        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content=toon_data,
            headers={"Content-Disposition": f"attachment; filename=windows_{task_id}.toon"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Export Windows TOON failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _get_case_analysis_service(service_manager):
    """Get or create a CaseAnalysisService instance."""
    if not hasattr(service_manager, "_case_analysis_service"):
        from ..services.case_analysis import CaseAnalysisService
        svc = CaseAnalysisService(service_manager.settings)
        svc.set_llm_service(service_manager.llm_service)
        svc.set_cpp_backend(service_manager.cpp_backend)  # Inject C++ backend service
        # Inject Graphiti service if available (optional dependency)
        # Always inject it if it exists - let modules handle availability at runtime
        try:
            graphiti_svc = service_manager.graphiti_service
            if graphiti_svc:
                svc.set_graphiti_service(graphiti_svc)
                logger.info("Graphiti service injected into case analysis service")
        except Exception as e:
            logger.warning(f"Could not inject Graphiti service: {e}")
            # Graphiti is optional; proceed without it
        service_manager._case_analysis_service = svc
    return service_manager._case_analysis_service


async def _run_case_analysis_background(
    job_id: str,
    case_service,
    task_id: str,
    files_db_path: str,
    case_description: str,
    max_filter_files: int,
    run_filtering: bool = True,
):
    """Run the full case analysis pipeline in the background."""
    try:
        async def progress_cb(step, detail=None, extra=None):
            # Handle variable arguments from different pipeline steps
            if extra is not None:
                # Step 3 (describing) sends: current, total, file_path
                current, total, file_path = step, detail, extra
                percentage = int((current / total) * 100) if total > 0 else 0
                _analysis_jobs[job_id]["current_step"] = "分析文件"
                _analysis_jobs[job_id]["detail"] = f"正在分析第 {current}/{total} 个文件: {file_path}"
                _analysis_jobs[job_id]["progress"] = percentage
            else:
                # Other steps send: step_name, detail_text
                _analysis_jobs[job_id]["current_step"] = step
                _analysis_jobs[job_id]["detail"] = detail or ""
                # Default progress
                if step == "filtering": _analysis_jobs[job_id]["progress"] = 10
                if step == "extracting": _analysis_jobs[job_id]["progress"] = 20
                if step == "reporting": _analysis_jobs[job_id]["progress"] = 90

        result = await case_service.run_full_analysis(
            task_id=task_id,
            files_db_path=files_db_path,
            case_description=case_description,
            max_filter_files=max_filter_files,
            run_filtering=run_filtering,
            progress_callback=progress_cb,
        )

        _analysis_jobs[job_id]["status"] = "completed"
        _analysis_jobs[job_id]["current_step"] = "完成"
        _analysis_jobs[job_id]["detail"] = "案情分析已完成"
        _analysis_jobs[job_id]["result"] = {
            "files_filtered": result.get("steps", {}).get("filter", {}).get("selected_count", 0),
            "files_analyzed": result.get("steps", {}).get("report", {}).get("files_analyzed", 0),
            "report_generated": bool(result.get("steps", {}).get("report", {}).get("report")),
        }
    except Exception as e:
        logger.error(f"Background case analysis failed: {e}", exc_info=True)
        _analysis_jobs[job_id]["status"] = "failed"
        _analysis_jobs[job_id]["current_step"] = "错误"
        _analysis_jobs[job_id]["detail"] = str(e)


async def _run_reanalyze_background(
    job_id: str,
    case_service,
    task_id: str,
    file_paths: List[str],
    user_hint: str,
    files_db_path: str,
    case_description: str,
):
    """Run file re-analysis in the background."""
    try:
        results = await case_service.reanalyze_files(
            task_id=task_id,
            file_paths=file_paths,
            user_hint=user_hint,
            files_db_path=files_db_path,
            case_description=case_description,
        )

        successful = sum(1 for r in results if r.get("success"))
        _analysis_jobs[job_id]["status"] = "completed"
        _analysis_jobs[job_id]["current_step"] = "完成"
        _analysis_jobs[job_id]["detail"] = f"重新分析完成: {successful}/{len(results)} 个文件成功"
        _analysis_jobs[job_id]["result"] = {
            "total": len(results),
            "successful": successful,
            "results": results,
        }
    except Exception as e:
        logger.error(f"Background re-analysis failed: {e}", exc_info=True)
        _analysis_jobs[job_id]["status"] = "failed"
        _analysis_jobs[job_id]["current_step"] = "错误"
        _analysis_jobs[job_id]["detail"] = str(e)


async def _run_windows_analysis_background(
    job_id: str,
    case_service,
    task_id: str,
    windows_db_path: str,
    case_description: str,
):
    """Run Windows artifacts analysis in the background."""
    try:
        async def progress_cb(step, detail=None, extra=None):
            if extra is not None:
                current, total, artifact_info = step, detail, extra
                percentage = int((current / total) * 100) if total > 0 else 0
                _analysis_jobs[job_id]["current_step"] = "分析Windows痕迹"
                _analysis_jobs[job_id]["detail"] = f"正在分析第 {current}/{total} 个: {artifact_info}"
                _analysis_jobs[job_id]["progress"] = percentage
            else:
                _analysis_jobs[job_id]["current_step"] = step
                _analysis_jobs[job_id]["detail"] = detail or ""

        result = await case_service.analyze_windows_artifacts(
            task_id=task_id,
            windows_db_path=windows_db_path,
            case_description=case_description,
            progress_callback=progress_cb,
        )

        _analysis_jobs[job_id]["status"] = "completed"
        _analysis_jobs[job_id]["current_step"] = "完成"
        _analysis_jobs[job_id]["detail"] = "Windows痕迹分析已完成"
        _analysis_jobs[job_id]["result"] = {
            "artifacts_filtered": result.get("filter", {}).get("selected_count", 0),
            "artifacts_analyzed": result.get("analysis", {}).get("analyzed_count", 0),
        }
    except Exception as e:
        logger.error(f"Background Windows analysis failed: {e}", exc_info=True)
        _analysis_jobs[job_id]["status"] = "failed"
        _analysis_jobs[job_id]["current_step"] = "错误"
        _analysis_jobs[job_id]["detail"] = str(e)
