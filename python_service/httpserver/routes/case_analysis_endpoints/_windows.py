"""Case-analysis routes — windows artifact analysis endpoints.

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
    CaseAnalysisRequest,
    CaseAnalysisResponse,
)
from ._helpers import (
    _analysis_jobs,
    get_case_analysis_service as _get_case_analysis_service,
    run_windows_analysis_background as _run_windows_analysis_background,
)

logger = logging.getLogger(__name__)
router = APIRouter()


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
        from ...services import get_service_manager
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
            "kind": "windows",
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
        raise HTTPException(status_code=500, detail="windows analysis could not be started")
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
        from ...services import get_service_manager
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
        raise HTTPException(status_code=500, detail="windows report is unavailable")
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
        from ...services import get_service_manager
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
        from ...services.windows_artifacts import WindowsArtifactTOONExporter
        exporter = WindowsArtifactTOONExporter()

        if artifact_type:
            toon_data = exporter.export_artifacts_toon(
                windows_db_path=windows_db_path,
                artifact_type=artifact_type,
                include_llm=True,
                limit=limit,
                severity=severity,
            )
        else:
            # Export all with LLM analysis, filtered by severity if specified
            toon_data = exporter.export_artifacts_toon(
                windows_db_path=windows_db_path,
                include_llm=True,
                limit=limit,
                severity=severity,
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
        raise HTTPException(status_code=500, detail="windows export failed")
