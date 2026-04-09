"""OSS Analysis routes - AI-powered analysis for cloud storage objects."""

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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


@router.post("/filter")
async def filter_oss_objects(
    request: OSSFilterRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Filter OSS objects using LLM based on case description."""
    from ..services.llm.llm_service import LLMService
    from ..services.cpp_backend import CppBackendService

    llm_service = LLMService(settings)
    cpp_backend = CppBackendService(settings)
    filter_service = OSSFilterService(settings, llm_service, cpp_backend)

    result = await filter_service.filter_oss_objects(
        oss_db_path=request.oss_db_path,
        case_description=request.case_description,
        bucket=request.bucket,
        max_objects=request.max_objects,
        task_id=request.task_id
    )

    return {
        "success": True,
        "task_id": request.task_id,
        "filtered_objects": result.get("filtered_objects", []),
        "selected_count": result.get("selected_count", 0),
        "total_objects": result.get("total_objects", 0),
        "reasoning": result.get("reasoning", "")
    }


@router.post("/analyze")
async def analyze_oss_objects(
    request: OSSAnalyzeRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Analyze downloaded OSS objects using LLM."""
    from ..services.llm.llm_service import LLMService
    from ..services.cpp_backend import CppBackendService

    llm_service = LLMService(settings)
    cpp_backend = CppBackendService(settings)
    analysis_service = OSSAnalysisService(settings, llm_service, cpp_backend)

    job_id = await analysis_service.start_analysis(
        task_id=request.task_id,
        object_ids=request.object_ids,
        oss_db_path=request.oss_db_path,
        download_dir=request.download_dir,
        model_type=request.model_type
    )

    return {
        "success": True,
        "task_id": request.task_id,
        "job_id": job_id,
        "total_objects": len(request.object_ids)
    }
