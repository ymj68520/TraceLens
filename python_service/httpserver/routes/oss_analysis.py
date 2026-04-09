"""OSS Analysis routes - AI-powered analysis for cloud storage objects."""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..services.oss_filter_service import OSSFilterService
from ..services.oss_analysis_service import OSSAnalysisService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/forensics/oss/ai", tags=["OSS Analysis"])


class OSSFilterRequest(BaseModel):
    task_id: str
    oss_db_path: str
    case_description: str
    bucket: Optional[str] = None
    max_objects: int = Field(default=200, ge=1, le=2000)


class OSSAnalyzeRequest(BaseModel):
    task_id: str
    object_ids: List[int]
    oss_db_path: str
    download_dir: str
    model_type: str = Field(default="text", pattern="^(text|vision)$")


class OSSFilterResponse(BaseModel):
    """Response for OSS object filtering."""
    success: bool
    task_id: str
    filtered_objects: List[int]
    selected_count: int
    total_objects: int
    reasoning: str
    timestamp: str


class OSSAnalyzeResponse(BaseModel):
    """Response for OSS object analysis."""
    success: bool
    task_id: str
    job_id: str
    total_objects: int
    timestamp: str


@router.post("/filter", response_model=OSSFilterResponse, responses={
    200: {"description": "OSS objects filtered successfully"},
    500: {"description": "Internal server error"},
})
async def filter_oss_objects(
    request: OSSFilterRequest,
    settings: Settings = Depends(get_settings)
):
    """Filter OSS objects using LLM based on case description."""
    from ..services import get_service_manager

    try:
        service_manager = get_service_manager()
        filter_service = _get_oss_filter_service(service_manager)

        result = await filter_service.filter_oss_objects(
            oss_db_path=request.oss_db_path,
            case_description=request.case_description,
            bucket=request.bucket,
            max_objects=request.max_objects,
            task_id=request.task_id
        )

        return OSSFilterResponse(
            success=True,
            task_id=request.task_id,
            filtered_objects=result.get("filtered_objects", []),
            selected_count=result.get("selected_count", 0),
            total_objects=result.get("total_objects", 0),
            reasoning=result.get("reasoning", ""),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"OSS filter failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze", response_model=OSSAnalyzeResponse, responses={
    200: {"description": "OSS analysis started successfully"},
    500: {"description": "Internal server error"},
})
async def analyze_oss_objects(
    request: OSSAnalyzeRequest,
    settings: Settings = Depends(get_settings)
):
    """Analyze downloaded OSS objects using LLM."""
    from ..services import get_service_manager

    try:
        service_manager = get_service_manager()
        analysis_service = _get_oss_analysis_service(service_manager)

        job_id = await analysis_service.start_analysis(
            task_id=request.task_id,
            object_ids=request.object_ids,
            oss_db_path=request.oss_db_path,
            download_dir=request.download_dir,
            model_type=request.model_type
        )

        return OSSAnalyzeResponse(
            success=True,
            task_id=request.task_id,
            job_id=job_id,
            total_objects=len(request.object_ids),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"OSS analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _get_oss_filter_service(service_manager):
    """Get or create an OSSFilterService instance."""
    if not hasattr(service_manager, "_oss_filter_service"):
        from ..services.llm.llm_service import LLMService
        from ..services.cpp_backend import CppBackendService

        llm_service = service_manager.llm_service
        cpp_backend = service_manager.cpp_backend
        filter_service = OSSFilterService(service_manager.settings, llm_service, cpp_backend)
        service_manager._oss_filter_service = filter_service
    return service_manager._oss_filter_service


def _get_oss_analysis_service(service_manager):
    """Get or create an OSSAnalysisService instance."""
    if not hasattr(service_manager, "_oss_analysis_service"):
        from ..services.llm.llm_service import LLMService
        from ..services.cpp_backend import CppBackendService

        llm_service = service_manager.llm_service
        cpp_backend = service_manager.cpp_backend
        analysis_service = OSSAnalysisService(service_manager.settings, llm_service, cpp_backend)
        service_manager._oss_analysis_service = analysis_service
    return service_manager._oss_analysis_service
