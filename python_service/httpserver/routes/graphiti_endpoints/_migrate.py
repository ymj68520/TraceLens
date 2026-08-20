"""Graphiti routes — migration / cleanup endpoints.

Part of the graphiti routes split (see graphiti.py). Endpoints are decorated
with the package-local APIRouter (``router``); the parent graphiti.py mounts
this router under ``/api/graphiti``.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks

from ...config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/migrate/task/{task_id}", responses={
    200: {"description": "Migration started/completed successfully"},
    404: {"description": "Task not found"},
    500: {"description": "Internal server error"}
})
async def migrate_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """
    Migrate a task from old to new Graphiti structure.

    Extracts file metadata from existing Episodic nodes and creates
    corresponding File entities with relationships.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        # Check if task exists
        task_exists = await service_manager.cpp_backend.check_task_exists(task_id)
        if not task_exists:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        # Check if migration manager is available
        if not hasattr(service_manager, 'migration_manager') or not service_manager.migration_manager:
            raise HTTPException(
                status_code=501,
                detail="Migration not available (MigrationManager not initialized)"
            )

        # Run migration
        result = await service_manager.migration_manager.migrate_task(task_id)

        return {
            "success": True,
            "task_id": task_id,
            "files_migrated": result.files_migrated,
            "episodes_linked": result.episodes_linked,
            "entities_linked": result.entities_linked,
            "events_attached": result.events_attached,
            "errors": result.errors,
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/migrate/deduplicate", responses={
    200: {"description": "Deduplication completed successfully"},
    500: {"description": "Internal server error"}
})
async def deduplicate_all(
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """
    Deduplicate files by MD5 across all tasks.

    Finds files with identical MD5 and creates SAME_CONTENT_AS edges.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        if not hasattr(service_manager, 'migration_manager') or not service_manager.migration_manager:
            raise HTTPException(
                status_code=501,
                detail="Deduplication not available (MigrationManager not initialized)"
            )

        result = await service_manager.migration_manager.deduplicate_by_md5()

        return {
            "success": True,
            "md5_groups_found": result.md5_groups_found,
            "edges_created": result.edges_created,
            "files_processed": result.files_processed,
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Deduplication failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/migrate/status/{task_id}", responses={
    200: {"description": "Migration status retrieved successfully"},
    404: {"description": "Task not found"},
    500: {"description": "Internal server error"}
})
async def get_migration_status(
    task_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    Check migration status for a task.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        if not hasattr(service_manager, 'migration_manager') or not service_manager.migration_manager:
            raise HTTPException(
                status_code=501,
                detail="Migration status not available (MigrationManager not initialized)"
            )

        is_migrated = await service_manager.migration_manager.is_migrated(task_id)
        detailed_status = await service_manager.migration_manager.get_migration_status(task_id)

        return {
            "success": True,
            "task_id": task_id,
            "is_migrated": is_migrated,
            "status": detailed_status,
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get migration status failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/migrate/cleanup/{task_id}", responses={
    200: {"description": "Cleanup completed successfully"},
    400: {"description": "Confirmation required"},
    404: {"description": "Task not found"},
    500: {"description": "Internal server error"}
})
async def cleanup_task(
    task_id: str,
    confirm: bool = Query(False, description="Must be true to proceed with cleanup"),
    settings: Settings = Depends(get_settings),
):
    """
    Cleanup old structure after migration.

    WARNING: This is irreversible! Only run after confirming migration success.
    """
    try:
        from ...services import get_service_manager
        service_manager = get_service_manager()

        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Must set confirm=true to proceed with cleanup. This operation is irreversible!"
            )

        if not hasattr(service_manager, 'migration_manager') or not service_manager.migration_manager:
            raise HTTPException(
                status_code=501,
                detail="Cleanup not available (MigrationManager not initialized)"
            )

        result = await service_manager.migration_manager.cleanup_old_structure(task_id)

        return {
            "success": True,
            "task_id": task_id,
            "episodes_cleaned": result.episodes_cleaned,
            "properties_removed": result.properties_removed,
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
