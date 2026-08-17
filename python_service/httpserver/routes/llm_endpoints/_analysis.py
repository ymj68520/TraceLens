"""LLM routes — LLM content analysis & batch jobs endpoints.

Part of the llm routes split (see llm.py). Endpoints are decorated with the
package-local APIRouter; the parent mounts it under /api/llm.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Path, BackgroundTasks

from ...config import Settings, get_settings

from ..llm_models import (
    AnalyzeRequest,
    AnalyzeResponse,
    BatchAnalyzeRequest,
    BatchAnalyzeResponse,
    BatchStatusResponse,
    EventClusterAnalyzeRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/analyze-event-cluster")
async def analyze_event_cluster(
    request: EventClusterAnalyzeRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Analyze an event cluster using LLM.
    
    This endpoint replaces the legacy C++ EventClusterAnalyzer LLM logic.
    It aggregates events for the given cluster and generates an AI summary.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()
        
        # 1. Get database path
        task_info = await service_manager.cpp_backend.get_task(request.task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail="Task not found")
            
        events_db = task_info.get("output_events_db") or ""
        if not events_db:
            raise HTTPException(status_code=400, detail="No events database for this task")

        # 2. Extract event data for the cluster
        # Using the same logic as C++ for consistency. bucket_seconds must match
        # the window used to produce the cluster, otherwise the cluster boundary
        # would be off. Default 60 keeps backward compatibility.
        import sqlite3
        bucket_seconds = request.bucket_seconds or 60
        events_summary = ""
        try:
            with sqlite3.connect(events_db) as conn:
                conn.row_factory = sqlite3.Row
                sql = "SELECT timestamp, event_type, file_path, description FROM events WHERE (timestamp / ?) = ? AND event_type = ?"
                params = [bucket_seconds, request.time_window, request.event_type]
                
                if request.parent_directory:
                    sql += " AND file_path LIKE ?"
                    params.append(f"{request.parent_directory}%")
                
                sql += " LIMIT 50"
                cur = conn.execute(sql, params)
                rows = cur.fetchall()
                
                if not rows:
                    raise HTTPException(status_code=404, detail="No events found in this cluster")
                    
                lines = [f"- {r['timestamp']}: {r['event_type']} | {r['file_path']} | {r['description'] or ''}" for r in rows]
                events_summary = "\n".join(lines)
        except Exception as e:
            logger.error(f"Failed to read events for cluster: {e}")
            raise HTTPException(status_code=500, detail="database query failed")

        # 3. Call LLM for analysis
        result = await service_manager.llm_service.analyze_event_cluster(
            event_data={
                "event_type": request.event_type,
                "description": events_summary,
                "time_window": request.time_window
            },
            prompt=request.prompt
        )
        
        analysis = result.get("analysis", {})
        
        # 4. Persist result back to _events.db using the cluster identifier
        # Note: We update ALL events in this cluster. The window divisor must
        # match the bucket used when the cluster was created (default 60).
        sql_update = """
            UPDATE events SET
                llm_summary = ?,
                llm_description = ?,
                llm_keywords = ?,
                llm_analyzed_at = ?,
                llm_model_used = ?,
                llm_is_relevant = ?
            WHERE (timestamp / ?) = ? AND event_type = ?
        """
        # Use full summary/description without truncation for database storage
        summary_value = analysis.get("summary") or analysis.get("description", "")
        update_params = [
            summary_value,  # Store full summary, no truncation
            analysis.get("description", ""),
            ", ".join(analysis.get("keywords", [])) if isinstance(analysis.get("keywords"), list) else "",
            int(datetime.now().timestamp()),
            result.get("model", "unknown"),
            1 if analysis.get("is_relevant", True) else 0,
            bucket_seconds,
            request.time_window,
            request.event_type
        ]

        if request.parent_directory:
            sql_update += " AND file_path LIKE ?"
            update_params.append(f"{request.parent_directory}%")

        try:
            with sqlite3.connect(events_db) as conn:
                cur = conn.execute(sql_update, update_params)
                conn.commit()
                logger.info(f"Updated {cur.rowcount} events in cluster {request.time_window}")
        except Exception as e:
            logger.warning(f"Failed to persist cluster analysis: {e}")

        return {
            "success": True,
            "analysis": analysis,
            "model_used": result.get("model"),
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Event cluster analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="event cluster analysis failed")
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

    if request.files_db_path and not request.task_id:
        raise HTTPException(
            status_code=400,
            detail="task_id is required to persist analysis results",
        )

    try:
        from ...services import get_service_manager, get_document_extractor_locator
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
                        detail="image analysis failed"
                    )
            else:
                doc_locator = get_document_extractor_locator()
                extractor = doc_locator.get_extractor(request.file_path)
                
                if extractor:
                    logger.info(f"Auto-detected document file: {request.file_path}, using document extractor")
                    try:
                        content = await extractor.extract_to_markdown(request.file_path)
                        result = await service_manager.llm_service.analyze(
                            content=content,
                            model_type=request.model_type or "text",
                            prompt=request.prompt,
                            max_tokens=request.max_tokens,
                            temperature=request.temperature,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to extract document {request.file_path}: {e}")
                        raise HTTPException(
                            status_code=400,
                            detail="document content extraction failed"
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

        # Persist to the task-owned _files.db. The persistence target is
        # resolved server-side from task_id (D2b); a supplied files_db_path
        # is a deprecated exact-validated hint, never the authority.
        if (request.files_db_path or request.task_id) and (
            request.db_file_path or request.file_path
        ) and description:
            from ...services import task_store

            if not request.task_id:
                raise HTTPException(
                    status_code=400,
                    detail="task_id is required to persist analysis results",
                )
            try:
                trusted_files_db = await task_store.resolve_task_files_db(
                    request.task_id
                )
                task_store.validate_legacy_db_path(
                    request.files_db_path, trusted_files_db
                )
            except task_store.TaskStoreError as exc:
                if exc.code == task_store.TASK_NOT_FOUND:
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            keywords_list = analysis.get("keywords", [])
            keywords_str = ", ".join(keywords_list) if isinstance(keywords_list, list) else str(keywords_list)

            db_path_to_save = request.db_file_path or request.file_path
            service_manager.llm_service.persist_to_files_db(
                db_path=str(trusted_files_db),
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
        logger.error(f"Analysis file not found: {e}")
        raise HTTPException(status_code=404, detail="file not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="file analysis failed")
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
        from ...services import get_service_manager, get_document_extractor_locator
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
            doc_locator = get_document_extractor_locator()
            extractor = doc_locator.get_extractor(file.filename) if getattr(file, "filename", None) else None
            
            if extractor:
                import tempfile
                import os
                from pathlib import Path
                
                logger.info(f"Auto-detected document file upload: {file.filename}, using document extractor")
                
                temp_fd, temp_path = tempfile.mkstemp(suffix=Path(file.filename).suffix)
                try:
                    with os.fdopen(temp_fd, 'wb') as temp_file:
                        temp_file.write(content)
                    
                    extracted_text = await extractor.extract_to_markdown(temp_path)
                    result = await service_manager.llm_service.analyze(
                        content=extracted_text,
                        model_type="text",
                        prompt=prompt,
                    )
                finally:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
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
        raise HTTPException(status_code=400, detail="file validation failed")
    except Exception as e:
        logger.error(f"File analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="file analysis failed")
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
        from ...services import get_service_manager
        service_manager = get_service_manager()
        
        # Get task info to find the _files.db path for result persistence
        task_info = await service_manager.cpp_backend.get_task(request.task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail=f"Task {request.task_id} not found")
        
        # Extract the _files.db path for persisting LLM results
        files_db_path: str = task_info.get("output_files_db") or ""
        
        # Get files to analyze
        if request.file_paths:
            # Use explicit file paths provided by user
            files = [{"path": p} for p in request.file_paths]
            logger.info(f"Starting targeted batch analysis for {len(files)} selected files")
        else:
            # Fallback to automatic discovery based on types/limit
            files = await service_manager.cpp_backend.get_task_files(
                task_id=request.task_id,
                file_types=request.file_types,
                limit=request.limit,
            )
            logger.info(f"Starting automatic batch analysis for {len(files)} discovered files")
        
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
        raise HTTPException(status_code=500, detail="batch analysis failed")
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
        from ...services import get_service_manager
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
        raise HTTPException(status_code=500, detail="batch status is unavailable")
