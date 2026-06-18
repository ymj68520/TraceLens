"""Graphiti routes — data ingestion endpoints.

Part of the graphiti routes split (see graphiti.py). Endpoints are decorated
with the package-local APIRouter (``router``); the parent graphiti.py mounts
this router under ``/api/graphiti``.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks

from ...config import Settings, get_settings

from ..graphiti_models import (
    EventSyncRequest,
    FileIngestRequest,
    IngestRequest,
    IngestionResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/ingest", response_model=IngestionResponse, responses={
    200: {"description": "Ingestion started successfully"},
    404: {"description": "Task not found"},
    500: {"description": "Internal server error during ingestion"}
})
async def ingest_data(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """
    Start Graphiti ingestion for a task.

    Modes:
    - full: Ingest files, events, and all platform data with File entities
    - files_only: Update file entities only (skip events)
    - events_only: Sync events to existing files
    - analyzed_only: Re-ingest only AI-analyzed files and event clusters (NEW)
        - Only processes files with llm_analyzed_at IS NOT NULL
        - Attaches events only for analyzed files
        - Creates MENTIONED_IN edges from existing episodes
        - Does NOT re-run LLM analysis
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        # Check if task exists via C++ backend
        task_exists = await service_manager.cpp_backend.check_task_exists(request.task_id)
        if not task_exists:
            raise HTTPException(status_code=404, detail=f"Task {request.task_id} not found")

        # Use new IngestionJobManager if available
        if hasattr(service_manager, 'ingestion_job_manager') and service_manager.ingestion_job_manager:
            job_id = await service_manager.ingestion_job_manager.queue_ingestion(
                task_id=request.task_id,
                mode=request.mode,
            )
            return IngestionResponse(
                job_id=job_id,
                status="PENDING",
                message=f"Ingestion queued for task {request.task_id} (mode: {request.mode.value})"
            )
        else:
            # Fallback to old GraphitiService
            job_id = await service_manager.graphiti_service.start_ingestion(
                task_id=request.task_id,
                include_llm_descriptions=request.include_llm_descriptions,
                batch_size=request.batch_size,
                max_episodes=request.max_episodes,
            )
            return IngestionResponse(
                job_id=job_id,
                status="PENDING",
                message=f"Ingestion started for task {request.task_id}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/ingest/file", response_model=IngestionResponse, responses={
    200: {"description": "File ingestion queued successfully"},
    404: {"description": "Task or file not found"},
    500: {"description": "Internal server error"}
})
async def ingest_file(
    request: FileIngestRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """
    Ingest or update a single file in the knowledge graph.

    Use cases:
    - New file analyzed: Create File entity + episode
    - File re-analyzed: Update in-place with new LLM analysis
    - Force re-analysis: Trigger LLM re-analysis before ingest
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        # Check if task exists
        task_exists = await service_manager.cpp_backend.check_task_exists(request.task_id)
        if not task_exists:
            raise HTTPException(status_code=404, detail=f"Task {request.task_id} not found")

        # Optionally trigger LLM re-analysis
        if request.update_analysis:
            # This would call the LLM service to re-analyze the file
            # For now, just log a warning
            logger.info(f"LLM re-analysis requested for file {request.file_id}")

        # Queue file ingestion
        if hasattr(service_manager, 'ingestion_job_manager') and service_manager.ingestion_job_manager:
            job_id = await service_manager.ingestion_job_manager.queue_file_update(
                file_id=request.file_id,
                task_id=request.task_id,
            )
            return IngestionResponse(
                job_id=job_id,
                status="PENDING",
                message=f"File {request.file_id} ingest queued"
            )
        else:
            raise HTTPException(
                status_code=501,
                detail="File ingestion not available (IngestionJobManager not initialized)"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File ingestion failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/ingest/events", response_model=IngestionResponse, responses={
    200: {"description": "Event sync queued successfully"},
    404: {"description": "Task not found"},
    500: {"description": "Internal server error"}
})
async def ingest_events(
    request: EventSyncRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """
    Sync timeline events to File entities.

    Events are attached to the events array property of File entities.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        # Check if task exists
        task_exists = await service_manager.cpp_backend.check_task_exists(request.task_id)
        if not task_exists:
            raise HTTPException(status_code=404, detail=f"Task {request.task_id} not found")

        # Queue event sync
        if hasattr(service_manager, 'ingestion_job_manager') and service_manager.ingestion_job_manager:
            job_id = await service_manager.ingestion_job_manager.queue_event_sync(
                task_id=request.task_id,
                events=request.events,
            )
            return IngestionResponse(
                job_id=job_id,
                status="PENDING",
                message=f"{len(request.events)} events queued for sync"
            )
        else:
            raise HTTPException(
                status_code=501,
                detail="Event sync not available (IngestionJobManager not initialized)"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Event sync failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
