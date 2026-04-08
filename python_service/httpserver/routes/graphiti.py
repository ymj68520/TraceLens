"""
Graphiti knowledge graph integration routes.

Provides endpoints for task-specific knowledge graphs:
- Ingesting forensic data into task-specific graph
- Searching entities and relationships within task scope
- Managing graph operations per task
"""

import logging
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ==============================================================================
# Enums
# ==============================================================================

class IngestionMode(str, Enum):
    """Ingestion operation modes."""
    FULL = "full"
    FILES_ONLY = "files_only"
    EVENTS_ONLY = "events_only"
    SINGLE_FILE = "single_file"


# ==============================================================================
# Request/Response Models
# ==============================================================================

class IngestRequest(BaseModel):
    """Request model for data ingestion."""
    task_id: str = Field(..., description="Task ID to ingest data from (also used as graph namespace)")
    mode: IngestionMode = Field(default=IngestionMode.FULL, description="Ingestion mode")
    include_llm_descriptions: bool = Field(default=True, description="Include LLM-generated descriptions")
    batch_size: int = Field(default=50, ge=1, le=500, description="Batch size for processing")
    max_episodes: int = Field(default=100, ge=0, le=10000, description="Maximum episodes to process (0 = unlimited)")


class FileIngestRequest(BaseModel):
    """Request model for single file ingestion."""
    file_id: int = Field(..., description="Database ID of the file")
    task_id: str = Field(..., description="Task ID")
    update_analysis: bool = Field(default=False, description="Force LLM re-analysis before ingest")


class EventSyncRequest(BaseModel):
    """Request model for event synchronization."""
    task_id: str = Field(..., description="Task ID")
    events: List[Dict[str, Any]] = Field(..., description="List of event dictionaries")


class IngestionResponse(BaseModel):
    """Response model for ingestion operation."""
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    """Response model for job status query."""
    job_id: str
    status: str
    progress: int
    current_phase: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class IngestResponse(BaseModel):
    """Response model for ingestion operation."""
    success: bool
    task_id: str
    job_id: Optional[str] = None
    message: str
    entities_created: int = 0
    relationships_created: int = 0
    timestamp: str


class SearchRequest(BaseModel):
    """Request model for graph search."""
    query: str = Field(..., min_length=1, description="Search query")
    task_id: str = Field(..., description="Task ID to search within")
    entity_types: Optional[List[str]] = Field(default=None, description="Filter by entity types")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results")
    include_relationships: bool = Field(default=True, description="Include related entities")


class SearchResult(BaseModel):
    """Single search result."""
    entity_id: str
    entity_type: str
    name: str
    properties: Dict[str, Any]
    score: float
    relationships: Optional[List[Dict[str, Any]]] = None


class SearchResponse(BaseModel):
    """Response model for search operation."""
    success: bool
    query: str
    task_id: str
    results: List[SearchResult]
    total_count: int
    timestamp: str


class EntityListResponse(BaseModel):
    """Response model for entity listing."""
    success: bool
    task_id: str
    entities: List[Dict[str, Any]]
    total_count: int
    page: int
    page_size: int
    timestamp: str


class RelationshipListResponse(BaseModel):
    """Response model for relationship listing."""
    success: bool
    task_id: str
    relationships: List[Dict[str, Any]]
    total_count: int
    page: int
    page_size: int
    timestamp: str


class GraphitiStatusResponse(BaseModel):
    """Response model for Graphiti service status."""
    status: str
    neo4j_connected: bool
    total_entities: int
    total_relationships: int
    task_id: Optional[str] = None
    timestamp: str


class TaskGraphsResponse(BaseModel):
    """Response model for listing task graphs."""
    success: bool
    task_ids: List[str]
    count: int
    timestamp: str


# Routes

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
    """
    try:
        from ..services import get_service_manager
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
        from ..services import get_service_manager
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
        from ..services import get_service_manager
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
        from ..services import get_service_manager
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
        from ..services import get_service_manager
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
        from ..services import get_service_manager
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


# ==============================================================================
# Migration Endpoints
# ==============================================================================

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
        from ..services import get_service_manager
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
        from ..services import get_service_manager
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
        from ..services import get_service_manager
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
        from ..services import get_service_manager
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


@router.post("/search", response_model=SearchResponse, responses={
    200: {"description": "Search executed successfully"},
    500: {"description": "Internal server error during search"}
})
async def search_graph(
    request: SearchRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Search the knowledge graph for a specific task.
    
    Only returns results from the task-specific graph namespace.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        results = await service_manager.graphiti_service.search(
            query=request.query,
            task_id=request.task_id,
            entity_types=request.entity_types,
            limit=request.limit,
            include_relationships=request.include_relationships,
        )
        
        return SearchResponse(
            success=True,
            query=request.query,
            task_id=request.task_id,
            results=[
                SearchResult(
                    entity_id=r.get("id", ""),
                    entity_type=r.get("type", "unknown"),
                    name=r.get("name", ""),
                    properties=r.get("properties", {}),
                    score=r.get("score", 0.0),
                    relationships=r.get("relationships"),
                )
                for r in results
            ],
            total_count=len(results),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities", response_model=EntityListResponse, responses={
    200: {"description": "Entities listed successfully"},
    500: {"description": "Internal server error during listing"}
})
async def list_entities(
    task_id: str = Query(..., description="Task ID to list entities from"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Page size"),
    settings: Settings = Depends(get_settings),
):
    """
    List entities in the knowledge graph for a specific task.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        entities, total_count = await service_manager.graphiti_service.list_entities(
            task_id=task_id,
            entity_type=entity_type,
            page=page,
            page_size=page_size,
        )
        
        return EntityListResponse(
            success=True,
            task_id=task_id,
            entities=entities,
            total_count=total_count,
            page=page,
            page_size=page_size,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"List entities failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/relationships", response_model=RelationshipListResponse, responses={
    200: {"description": "Relationships listed successfully"},
    500: {"description": "Internal server error during listing"}
})
async def list_relationships(
    task_id: str = Query(..., description="Task ID to list relationships from"),
    relationship_type: Optional[str] = Query(None, description="Filter by relationship type"),
    source_id: Optional[str] = Query(None, description="Filter by source entity ID"),
    target_id: Optional[str] = Query(None, description="Filter by target entity ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Page size"),
    settings: Settings = Depends(get_settings),
):
    """
    List relationships in the knowledge graph for a specific task.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        relationships, total_count = await service_manager.graphiti_service.list_relationships(
            task_id=task_id,
            relationship_type=relationship_type,
            source_id=source_id,
            target_id=target_id,
            page=page,
            page_size=page_size,
        )
        
        return RelationshipListResponse(
            success=True,
            task_id=task_id,
            relationships=relationships,
            total_count=total_count,
            page=page,
            page_size=page_size,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"List relationships failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", response_model=GraphitiStatusResponse)
async def get_status(
    task_id: Optional[str] = Query(None, description="Task ID for task-specific status"),
    settings: Settings = Depends(get_settings),
):
    """
    Get the status of the Graphiti knowledge graph service.
    
    If task_id is provided, returns status for that specific task graph.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        status = await service_manager.graphiti_service.get_status(task_id=task_id)
        
        return GraphitiStatusResponse(
            status=status.get("status", "unknown"),
            neo4j_connected=status.get("neo4j_connected", False),
            total_entities=status.get("total_entities", 0),
            total_relationships=status.get("total_relationships", 0),
            task_id=task_id,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Get status failed: {e}", exc_info=True)
        return GraphitiStatusResponse(
            status="error",
            neo4j_connected=False,
            total_entities=0,
            total_relationships=0,
            task_id=task_id,
            timestamp=datetime.now().isoformat(),
        )


@router.get("/tasks", response_model=TaskGraphsResponse)
async def list_task_graphs(settings: Settings = Depends(get_settings)):
    """
    List all task IDs that have knowledge graph data.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        task_ids = await service_manager.graphiti_service.list_task_graphs()
        
        return TaskGraphsResponse(
            success=True,
            task_ids=task_ids,
            count=len(task_ids),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"List task graphs failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/{task_id}")
async def delete_task_graph(
    task_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    Delete a task-specific knowledge graph.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        deleted = await service_manager.graphiti_service.delete_task_graph(task_id)
        
        return {
            "success": deleted,
            "task_id": task_id,
            "message": f"Graph {'deleted' if deleted else 'not found'}",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Delete task graph failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph", responses={
    200: {"description": "Graph data for visualization"},
    500: {"description": "Internal server error"},
})
async def get_graph_data(
    task_id: str = Query(..., description="Task ID to get graph data for"),
    max_nodes: int = Query(200, ge=1, le=1000, description="Maximum nodes to return"),
    settings: Settings = Depends(get_settings),
):
    """
    Get graph data (nodes + links) for visual rendering of the knowledge graph.
    Returns a force-graph compatible format: { nodes: [...], links: [...] }  
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()

        nodes, links = await service_manager.graphiti_service.get_graph_data(
            task_id=task_id,
            max_nodes=max_nodes,
        )

        return {
            "success": True,
            "task_id": task_id,
            "nodes": nodes,
            "links": links,
            "node_count": len(nodes),
            "link_count": len(links),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Get graph data failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
