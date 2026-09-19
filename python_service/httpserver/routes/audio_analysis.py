"""Audio transcription/analysis routes.

Provides a REST endpoint transcribing an audio file (SenseVoice STT) and
synthesizing a forensic description. Used by the C++ backend via HTTP
(task-pipeline file description — replacing the previous raw-read/metadata
paths), while interactive/case Python flows call the analyzer directly.
"""

import logging
import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from ..services.llm.audio_analyzer import AUDIO_EXTENSIONS, analyze_audio_file

# Same workspace/task ownership gate as the markitdown conversion endpoints
# (task_id anchor, or standalone workspace_root for CLI callers).
from .markitdown import _assert_file_readable_for_task

logger = logging.getLogger(__name__)

router = APIRouter()


class AudioTranscribeRequest(BaseModel):
    """Request model for audio transcription + description."""

    task_id: str | None = Field(None, description="Task ID owning the file (workspace anchor)")
    workspace_root: str | None = Field(
        None, description="Deprecated standalone workspace anchor for CLI callers"
    )
    file_path: str = Field(..., description="Absolute path to the audio file")
    prompt: Optional[str] = Field(
        None, description="Optional analyst prompt woven into the synthesis stage"
    )


class AudioTranscribeResponse(BaseModel):
    """Response model for audio transcription + description."""

    success: bool
    description: str = ""
    summary: str = ""
    keywords: List[str] = Field(default_factory=list)
    model: str = ""
    extraction_method: str = ""
    processing_time_ms: float = 0.0


@router.post(
    "/transcribe",
    response_model=AudioTranscribeResponse,
    responses={
        200: {"description": "Audio transcribed (or metadata-only fallback)"},
        400: {"description": "Invalid request (not audio / outside workspace)"},
        404: {"description": "File not found"},
        500: {"description": "Audio analysis failed"},
    },
)
async def transcribe_audio(request: AudioTranscribeRequest):
    """
    Transcribe an audio file and produce its forensic description.

    SenseVoice-small STT (CPU) with silero VAD chunking; the full transcript
    is stored in the task files DB ``audio_transcripts`` table, the
    description carries the analysis plus duration-banded key excerpts.
    Audio over LLM_AUDIO_MAX_DURATION_SEC (default 60min) yields a
    pending_backfill row and a metadata-only description.
    """
    start_time = time.time()

    await _assert_file_readable_for_task(
        request.task_id, request.workspace_root, request.file_path
    )

    file_path = Path(request.file_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {request.file_path}")

    if file_path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Not a supported audio extension: {file_path.suffix}",
        )

    files_db_path = ""
    if request.task_id:
        from ..services import task_store

        try:
            trusted_db = await task_store.resolve_task_files_db(request.task_id)
            files_db_path = str(trusted_db)
        except Exception as exc:
            logger.warning(f"audio transcribe: files db resolve failed for {request.task_id}: {exc}")

    try:
        from ..services import get_service_manager

        llm_service = get_service_manager().llm_service
        result, extraction_method = await analyze_audio_file(
            str(file_path),
            llm_service=llm_service,
            settings=get_settings(),
            user_prompt=request.prompt or "",
            files_db_path=files_db_path,
            task_id=request.task_id or "",
            trigger_source="pipeline",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"audio transcribe failed for {request.file_path}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="audio analysis failed") from exc

    analysis = result.get("analysis", {})
    return AudioTranscribeResponse(
        success=True,
        description=analysis.get("description", ""),
        summary=analysis.get("summary", ""),
        keywords=analysis.get("keywords", []) or [],
        model=result.get("model", ""),
        extraction_method=extraction_method,
        processing_time_ms=(time.time() - start_time) * 1000,
    )
