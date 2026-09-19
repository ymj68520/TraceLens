"""Video content-analysis routes.

Provides a REST endpoint describing a video's content by segment-sampled
multi-image vision calls. Used by:
- the C++ backend via HTTP (task-pipeline file description), replacing the
  previous behaviour of feeding raw video bytes to the text model;
- interactive/case Python flows directly via ``services.llm.video_analyzer``
  (this endpoint is the C++-facing door of the same implementation).
"""

import logging
import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from ..services.llm.video_analyzer import VIDEO_EXTENSIONS, analyze_video_file

# Same workspace/task ownership gate as the markitdown conversion endpoints
# (task_id anchor, or standalone workspace_root for CLI callers).
from .markitdown import _assert_file_readable_for_task

logger = logging.getLogger(__name__)

router = APIRouter()


class VideoDescribeRequest(BaseModel):
    """Request model for video content description."""

    task_id: str | None = Field(None, description="Task ID owning the file (workspace anchor)")
    workspace_root: str | None = Field(
        None, description="Deprecated standalone workspace anchor for CLI callers"
    )
    file_path: str = Field(..., description="Absolute path to the video file")
    prompt: Optional[str] = Field(
        None, description="Optional analyst prompt woven into the synthesis stage"
    )


class VideoDescribeResponse(BaseModel):
    """Response model for video content description."""

    success: bool
    description: str = ""
    summary: str = ""
    keywords: List[str] = Field(default_factory=list)
    model: str = ""
    extraction_method: str = ""
    tokens_used: int = 0
    processing_time_ms: float = 0.0


@router.post(
    "/describe",
    response_model=VideoDescribeResponse,
    responses={
        200: {"description": "Video described (content analysis or metadata-only fallback)"},
        400: {"description": "Invalid request (not a video / outside workspace)"},
        404: {"description": "File not found"},
        500: {"description": "Video analysis failed"},
    },
)
async def describe_video(request: VideoDescribeRequest):
    """
    Describe a video file's content.

    Covers the whole duration below LLM_VIDEO_MAX_DURATION_SEC by sampling
    frames at LLM_VIDEO_FPS and describing each LLM_VIDEO_SEGMENT_SECONDS
    window with one multi-image vision call (serial), then synthesizes the
    final description. Longer videos return a metadata-only description
    marked for future backfill. The audio track is not analyzed.
    """
    start_time = time.time()

    await _assert_file_readable_for_task(
        request.task_id, request.workspace_root, request.file_path
    )

    file_path = Path(request.file_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {request.file_path}")

    if file_path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Not a supported video extension: {file_path.suffix}",
        )

    try:
        from ..services import get_service_manager

        llm_service = get_service_manager().llm_service
        result, extraction_method = await analyze_video_file(
            str(file_path),
            llm_service=llm_service,
            settings=get_settings(),
            user_prompt=request.prompt or "",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"video describe failed for {request.file_path}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="video analysis failed") from exc

    analysis = result.get("analysis", {})
    return VideoDescribeResponse(
        success=True,
        description=analysis.get("description", ""),
        summary=analysis.get("summary", ""),
        keywords=analysis.get("keywords", []) or [],
        model=result.get("model", ""),
        extraction_method=extraction_method,
        tokens_used=result.get("tokens_used", 0),
        processing_time_ms=(time.time() - start_time) * 1000,
    )
