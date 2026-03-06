"""
LLM analysis routes.

Provides endpoints for:
- File content analysis using LLM
- Batch analysis operations
- Model information and status
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File
from pydantic import BaseModel, Field

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


# Request/Response Models

class AnalyzeRequest(BaseModel):
    """Request model for file analysis."""
    file_path: Optional[str] = Field(None, description="Path to file to analyze")
    db_file_path: Optional[str] = Field(None, description="Path to file in DB (for persistence)")
    content: Optional[str] = Field(None, description="Direct content to analyze")
    model_type: str = Field(default="text", description="Model type: 'text' or 'vision'")
    prompt: Optional[str] = Field(None, description="Custom analysis prompt")
    max_tokens: Optional[int] = Field(None, ge=1, le=8192, description="Max response tokens")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Model temperature")
    files_db_path: Optional[str] = Field(None, description="Path to _files.db for persisting result")


class AnalyzeResponse(BaseModel):
    """Response model for analysis."""
    success: bool
    analysis: Dict[str, Any]
    model_used: str
    tokens_used: int
    processing_time_ms: float
    timestamp: str


class BatchAnalyzeRequest(BaseModel):
    """Request model for batch analysis."""
    task_id: str = Field(..., description="Task ID to analyze files from")
    file_types: Optional[List[str]] = Field(None, description="Filter by file types")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum files to analyze")
    model_type: str = Field(default="text", description="Model type: 'text' or 'vision'")


class BatchAnalyzeResponse(BaseModel):
    """Response model for batch analysis."""
    success: bool
    task_id: str
    job_id: str
    message: str
    total_files: int
    timestamp: str


class BatchStatusResponse(BaseModel):
    """Response model for batch job status."""
    success: bool
    job_id: str
    status: str
    progress: float
    files_processed: int
    files_total: int
    errors: List[str]
    results: List[Dict[str, Any]] = []
    timestamp: str


class ModelInfo(BaseModel):
    """Model information."""
    name: str
    type: str
    base_url: str
    max_tokens: int
    temperature: float
    status: str


class ModelsResponse(BaseModel):
    """Response model for models listing."""
    success: bool
    models: List[ModelInfo]
    timestamp: str


class LLMStatusResponse(BaseModel):
    """Response model for LLM service status."""
    status: str
    text_model: Dict[str, Any]
    vision_model: Dict[str, Any]
    timestamp: str


# Routes

@router.post("/analyze", response_model=AnalyzeResponse, responses={
    200: {"description": "Content analyzed successfully"},
    400: {"description": "Invalid request parameters"},
    404: {"description": "File not found"},
    500: {"description": "Internal server error during analysis"}
})
async def analyze_content(
    request: AnalyzeRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Analyze content using LLM.

    Provide either a file path or direct content for analysis.
    Supports both text and vision models with auto-detection.
    """
    import time
    from pathlib import Path
    start_time = time.time()

    if not request.file_path and not request.content:
        raise HTTPException(
            status_code=400,
            detail="Either file_path or content must be provided"
        )

    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()

        # Image file extensions for auto-detection
        IMAGE_EXTENSIONS = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif',
            '.svg', '.ico', '.heic', '.heif', '.raw', '.cr2', '.nef', '.arw'
        }

        result = None

        # Handle file path
        if request.file_path:
            # Check if file exists before attempting to read
            from pathlib import Path as FilePath
            file_path_obj = FilePath(request.file_path)

            if not file_path_obj.exists():
                error_msg = (
                    f"File not found: {request.file_path}\n\n"
                    f"Files must be extracted from the disk image before AI analysis.\n"
                    f"Suggestion: Use the file extraction feature first via the Files page, "
                    f"or ensure the extraction directory is correctly configured."
                )
                raise HTTPException(
                    status_code=404,
                    detail=error_msg
                )

            file_ext = Path(request.file_path).suffix.lower()
            is_image = file_ext in IMAGE_EXTENSIONS

            if is_image:
                # Read as binary and use vision model
                logger.info(f"Auto-detected image file: {request.file_path}, using vision model")
                try:
                    with open(request.file_path, 'rb') as f:
                        image_data = f.read()
                    result = await service_manager.llm_service.analyze_image(
                        image_data=image_data,
                        prompt=request.prompt,
                    )
                except Exception as e:
                    logger.warning(f"Failed to analyze {request.file_path} as image: {e}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to analyze image: {str(e)}"
                    )
            else:
                # Read as text
                content = await service_manager.llm_service.read_file_content(request.file_path)
                result = await service_manager.llm_service.analyze(
                    content=content,
                    model_type=request.model_type or "text",
                    prompt=request.prompt,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                )
        else:
            # Direct content analysis (text only)
            result = await service_manager.llm_service.analyze(
                content=request.content,
                model_type=request.model_type or "text",
                prompt=request.prompt,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )

        processing_time = (time.time() - start_time) * 1000
        analysis = result.get("analysis", {})
        description = analysis.get("description", "")

        # Persist to C++ SQLite _files.db if db path and file path are provided
        if request.files_db_path and (request.db_file_path or request.file_path) and description:
            keywords_list = analysis.get("keywords", [])
            keywords_str = ", ".join(keywords_list) if isinstance(keywords_list, list) else str(keywords_list)

            db_path_to_save = request.db_file_path or request.file_path
            service_manager.llm_service.persist_to_files_db(
                db_path=request.files_db_path,
                file_path=db_path_to_save,
                description=description,
                summary=analysis.get("summary") or description[:200],
                keywords=keywords_str,
                model_used=result.get("model", "unknown")
            )

        return AnalyzeResponse(
            success=True,
            analysis=analysis,
            model_used=result.get("model", "unknown"),
            tokens_used=result.get("tokens_used", 0),
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/analyze/file", 
    response_model=AnalyzeResponse,
    responses={
        200: {"description": "File analyzed successfully"},
        500: {"description": "Internal server error during analysis"}
    }
)
async def analyze_uploaded_file(
    file: UploadFile = File(...),
    model_type: str = Query("text", description="Model type: 'text' or 'vision'"),
    prompt: Optional[str] = Query(None, description="Custom analysis prompt"),
    settings: Settings = Depends(get_settings),
):
    """
    Analyze an uploaded file using LLM.

    Accepts file uploads and returns analysis results.
    """
    import time
    start_time = time.time()

    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()

        # Read file content
        content = await file.read()
        file_size_kb = len(content) / 1024

        logger.info(f"Analyzing uploaded file: {file.filename}, size: {file_size_kb:.2f} KB, type: {file.content_type}, model: {model_type}")

        # Determine content type
        if model_type == "vision" or file.content_type.startswith("image/"):
            # Handle as image (let vision model determine if image is valid)
            result = await service_manager.llm_service.analyze_image(
                image_data=content,
                prompt=prompt,
            )
        else:
            # Handle as text
            text_content = content.decode("utf-8", errors="replace")
            result = await service_manager.llm_service.analyze(
                content=text_content,
                model_type="text",
                prompt=prompt,
            )

        processing_time = (time.time() - start_time) * 1000

        return AnalyzeResponse(
            success=True,
            analysis=result.get("analysis", {}),
            model_used=result.get("model", "unknown"),
            tokens_used=result.get("tokens_used", 0),
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except ValueError as e:
        # Handle specific validation errors (like image too large)
        logger.error(f"File validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"File analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"File analysis failed: {str(e)}")


@router.post("/batch", response_model=BatchAnalyzeResponse, responses={
    200: {"description": "Batch analysis started successfully"},
    404: {"description": "Task not found"},
    500: {"description": "Internal server error during batch analysis"}
})
async def batch_analyze(
    request: BatchAnalyzeRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """
    Start batch analysis of files from a task.
    
    This operation runs in the background and returns immediately
    with a job ID that can be used to track progress.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        # Get task info to find the _files.db path for result persistence
        task_info = await service_manager.cpp_backend.get_task(request.task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail=f"Task {request.task_id} not found")
        
        # Extract the _files.db path for persisting LLM results
        files_db_path: str = task_info.get("output_files_db") or ""
        
        # Get files to analyze
        files = await service_manager.cpp_backend.get_task_files(
            task_id=request.task_id,
            file_types=request.file_types,
            limit=request.limit,
        )
        
        # Extract the extraction_directory for resolving relative file paths
        extraction_dir: str = task_info.get("extraction_directory") or ""
        
        # Start background batch analysis (results will be persisted to _files.db)
        job_id = await service_manager.llm_service.start_batch_analysis(
            files=files,
            model_type=request.model_type,
            files_db_path=files_db_path or None,
            extraction_dir=extraction_dir or None,
        )
        
        return BatchAnalyzeResponse(
            success=True,
            task_id=request.task_id,
            job_id=job_id,
            message="Batch analysis started in background",
            total_files=len(files),
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batch/{job_id}", response_model=BatchStatusResponse, responses={
    200: {"description": "Status retrieved successfully"},
    404: {"description": "Job not found"},
    500: {"description": "Internal server error"}
})
async def get_batch_status(
    job_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    Get the status of a batch analysis job.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        status = await service_manager.llm_service.get_batch_status(job_id)
        
        if not status:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        return BatchStatusResponse(
            success=True,
            job_id=job_id,
            status=status.get("status", "unknown"),
            progress=status.get("progress", 0.0),
            files_processed=status.get("files_processed", 0),
            files_total=status.get("files_total", 0),
            errors=status.get("errors", []),
            results=status.get("results", []),
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get batch status failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models", response_model=ModelsResponse, responses={
    200: {"description": "Models listed successfully"},
    500: {"description": "Internal server error"}
})
async def list_models(settings: Settings = Depends(get_settings)):
    """
    List available LLM models and their configurations.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        # Get model status
        text_status = await service_manager.llm_service.check_model_status("text")
        vision_status = await service_manager.llm_service.check_model_status("vision")
        
        models = [
            ModelInfo(
                name=settings.llm_text_model,
                type="text",
                base_url=settings.llm_text_base_url,
                max_tokens=settings.llm_text_max_tokens,
                temperature=settings.llm_text_temperature,
                status="available" if text_status else "unavailable",
            ),
            ModelInfo(
                name=settings.llm_vision_model,
                type="vision",
                base_url=settings.llm_vision_base_url,
                max_tokens=settings.llm_vision_max_tokens,
                temperature=settings.llm_vision_temperature,
                status="available" if vision_status else "unavailable",
            ),
        ]
        
        return ModelsResponse(
            success=True,
            models=models,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"List models failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", response_model=LLMStatusResponse, responses={
    200: {"description": "Status retrieved successfully"},
    500: {"description": "Internal server error"}
})
async def get_status(settings: Settings = Depends(get_settings)):
    """
    Get the status of LLM services.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        status = await service_manager.llm_service.get_status()
        
        return LLMStatusResponse(
            status=status.get("status", "unknown"),
            text_model=status.get("text_model", {}),
            vision_model=status.get("vision_model", {}),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Get status failed: {e}", exc_info=True)
        return LLMStatusResponse(
            status="error",
            text_model={"error": str(e)},
            vision_model={"error": str(e)},
            timestamp=datetime.now().isoformat(),
        )
