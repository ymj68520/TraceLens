"""Graphiti routes — background-job endpoints.

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
    JobStatusResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobStatusResponse, responses={
    200: {"description": "Job status retrieved successfully"},
    404: {"description": "Job not found"},
    500: {"description": "Internal server error"}
})
async def get_job_status(
    job_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    Query ingestion job status.

    Poll this endpoint to track progress.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        # Try IngestionJobManager first
        if hasattr(service_manager, 'ingestion_job_manager') and service_manager.ingestion_job_manager:
            status = await service_manager.ingestion_job_manager.get_job_status(job_id)
            if status:
                return JobStatusResponse(**status)

        # Fallback to old GraphitiService
        status = await service_manager.graphiti_service.get_job_status(job_id)
        if status:
            return JobStatusResponse(
                job_id=job_id,
                status=status.get("status", "unknown"),
                progress=int(status.get("progress", 0) * 100),
                current_phase=status.get("current_phase", "unknown"),
                created_at=status.get("created_at", ""),
                started_at=status.get("started_at"),
                completed_at=status.get("completed_at"),
                error=status.get("error"),
                result=status.get("result"),
            )

        raise HTTPException(status_code=404, detail="Job not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get job status failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.delete("/jobs/{job_id}", responses={
    200: {"description": "Job cancelled successfully"},
    404: {"description": "Job not found"},
    400: {"description": "Job cannot be cancelled"},
    500: {"description": "Internal server error"}
})
async def cancel_job(
    job_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    Cancel a running or pending ingestion job.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        # Try IngestionJobManager first
        if hasattr(service_manager, 'ingestion_job_manager') and service_manager.ingestion_job_manager:
            success = await service_manager.ingestion_job_manager.cancel_job(job_id)
            if not success and job_id not in [j.get("job_id") for j in await service_manager.ingestion_job_manager.list_jobs()]:
                raise HTTPException(status_code=404, detail="Job not found")
            return {
                "success": success,
                "job_id": job_id,
                "message": "Job cancelled" if success else "Job cannot be cancelled (already completed/failed)",
                "timestamp": datetime.now().isoformat(),
            }

        # Fallback to old GraphitiService
        cancelled = await service_manager.graphiti_service.cancel_job(job_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail="Job not found or not running")

        return {
            "success": True,
            "job_id": job_id,
            "message": "Job cancelled",
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cancel job failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/jobs", responses={
    200: {"description": "Jobs listed successfully"},
    500: {"description": "Internal server error"}
})
async def list_jobs(
    task_id: Optional[str] = Query(None, description="Filter by task ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of jobs to return"),
    settings: Settings = Depends(get_settings),
):
    """
    List ingestion jobs with optional filtering.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        # Try IngestionJobManager first
        if hasattr(service_manager, 'ingestion_job_manager') and service_manager.ingestion_job_manager:
            jobs = await service_manager.ingestion_job_manager.list_jobs(
                task_id=task_id,
                status=status,
                limit=limit,
            )
            return {
                "success": True,
                "jobs": jobs,
                "count": len(jobs),
                "timestamp": datetime.now().isoformat(),
            }

        # Fallback: return empty list
        return {
            "success": True,
            "jobs": [],
            "count": 0,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"List jobs failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
