"""LLM routes — models / status / relevance toggles endpoints.

Part of the llm routes split (see llm.py). Endpoints are decorated with the
package-local APIRouter; the parent mounts it under /api/llm.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Path, BackgroundTasks

from ...config import Settings, get_settings

from ..llm_models import (
    LLMStatusResponse,
    ModelInfo,
    ModelsResponse,
    ToggleClusterRelevanceRequest,
    ToggleRelevanceRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/models", response_model=ModelsResponse, responses={
    200: {"description": "Models listed successfully"},
    500: {"description": "Internal server error"}
})
async def list_models(settings: Settings = Depends(get_settings)):
    """
    List available LLM models and their configurations.
    """
    try:
        from ...services import get_service_manager
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
@router.post("/toggle-relevance")
async def toggle_relevance(
    request: ToggleRelevanceRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Toggle the relevance of a file description.
    Irrelevant files will be excluded from the final case report.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()
        
        task_info = await service_manager.cpp_backend.get_task(request.task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail=f"Task {request.task_id} not found")
            
        db_path = task_info.get("output_files_db") or ""
        success = service_manager.llm_service.set_file_relevance(
            db_path, request.file_path, request.is_relevant
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to update relevance. File description may not exist.")

        return {"success": True, "message": f"File relevance updated to {request.is_relevant}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling relevance: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/toggle-cluster-relevance")
async def toggle_cluster_relevance(
    request: ToggleClusterRelevanceRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Toggle the relevance of an event cluster.
    Irrelevant clusters will be excluded from the final case report.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        task_info = await service_manager.cpp_backend.get_task(request.task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail=f"Task {request.task_id} not found")

        events_db = task_info.get("output_events_db") or ""
        if not events_db:
            raise HTTPException(status_code=400, detail="No events database for this task")

        # Update all events in this cluster
        import sqlite3
        try:
            with sqlite3.connect(events_db) as conn:
                sql_update = """
                    UPDATE events SET
                        llm_is_relevant = ?
                    WHERE (timestamp / 60) = ? AND event_type = ?
                """
                params = [1 if request.is_relevant else 0, request.time_window, request.event_type]

                cur = conn.execute(sql_update, params)
                conn.commit()
                logger.info(f"Updated {cur.rowcount} events in cluster {request.time_window} for relevance to {request.is_relevant}")

        except Exception as e:
            logger.warning(f"Failed to persist cluster relevance: {e}")
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

        return {"success": True, "message": f"Event cluster relevance updated to {request.is_relevant}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling cluster relevance: {e}")
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
        from ...services import get_service_manager
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
