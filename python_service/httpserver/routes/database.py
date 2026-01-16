"""
Database access routes.

Provides endpoints for:
- Querying forensic databases
- Retrieving task files and events
- Exporting data in various formats
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


# Request/Response Models

class FileRecord(BaseModel):
    """File record from database."""
    id: int
    name: str
    path: str
    size: int
    file_type: str
    extension: Optional[str] = None
    md5: Optional[str] = None
    created_time: Optional[str] = None
    modified_time: Optional[str] = None
    accessed_time: Optional[str] = None
    is_deleted: bool = False
    llm_description: Optional[str] = None


class FileListResponse(BaseModel):
    """Response model for file listing."""
    success: bool
    files: List[FileRecord]
    total_count: int
    page: int
    page_size: int
    timestamp: str


class EventRecord(BaseModel):
    """Event record from database."""
    id: int
    event_type: str
    file_path: str
    timestamp: str
    details: Optional[Dict[str, Any]] = None


class EventListResponse(BaseModel):
    """Response model for event listing."""
    success: bool
    events: List[EventRecord]
    total_count: int
    page: int
    page_size: int
    timestamp: str


class QueryRequest(BaseModel):
    """Request model for custom queries."""
    task_id: str = Field(..., description="Task ID to query")
    database_type: str = Field(..., description="Database type: 'files', 'events', 'android', 'windows', 'linux'")
    table: Optional[str] = Field(None, description="Table name")
    sql: Optional[str] = Field(None, description="Custom SQL query (SELECT only)")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Query parameters")
    limit: int = Field(default=1000, ge=1, le=10000, description="Maximum results")


class QueryResponse(BaseModel):
    """Response model for custom queries."""
    success: bool
    columns: List[str]
    rows: List[List[Any]]
    row_count: int
    timestamp: str


class ExportResponse(BaseModel):
    """Response model for export operations."""
    success: bool
    format: str
    size_bytes: int
    timestamp: str


class TaskDatabasesResponse(BaseModel):
    """Response model for task databases listing."""
    success: bool
    task_id: str
    databases: List[Dict[str, Any]]
    timestamp: str


# Routes

@router.get("/tasks", response_model=Dict[str, Any])
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Page size"),
    settings: Settings = Depends(get_settings),
):
    """
    List all analysis tasks from the C++ backend.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        result = await service_manager.cpp_backend.list_tasks(
            status=status,
            page=page,
            page_size=page_size,
        )
        
        return {
            "success": True,
            "tasks": result.get("tasks", []),
            "total_count": result.get("total_count", 0),
            "page": page,
            "page_size": page_size,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"List tasks failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}", response_model=Dict[str, Any])
async def get_task(
    task_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    Get details of a specific task.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        task = await service_manager.cpp_backend.get_task(task_id)
        
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        return {
            "success": True,
            "task": task,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get task failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/databases", response_model=TaskDatabasesResponse)
async def list_task_databases(
    task_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    List all databases associated with a task.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        databases = await service_manager.cpp_backend.get_task_databases(task_id)
        
        return TaskDatabasesResponse(
            success=True,
            task_id=task_id,
            databases=databases,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"List databases failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/files", response_model=FileListResponse)
async def get_task_files(
    task_id: str,
    file_type: Optional[str] = Query(None, description="Filter by file type"),
    extension: Optional[str] = Query(None, description="Filter by extension"),
    deleted_only: bool = Query(False, description="Show only deleted files"),
    include_llm: bool = Query(True, description="Include LLM descriptions"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Page size"),
    settings: Settings = Depends(get_settings),
):
    """
    Get files from a task's database.
    
    Supports filtering by file type, extension, and deletion status.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        result = await service_manager.cpp_backend.get_task_files_paginated(
            task_id=task_id,
            file_type=file_type,
            extension=extension,
            deleted_only=deleted_only,
            include_llm=include_llm,
            page=page,
            page_size=page_size,
        )
        
        files = [
            FileRecord(
                id=f.get("id", 0),
                name=f.get("name", ""),
                path=f.get("path", ""),
                size=f.get("size", 0),
                file_type=f.get("file_type", "unknown"),
                extension=f.get("extension"),
                md5=f.get("md5"),
                created_time=f.get("created_time"),
                modified_time=f.get("modified_time"),
                accessed_time=f.get("accessed_time"),
                is_deleted=f.get("is_deleted", False),
                llm_description=f.get("llm_description") if include_llm else None,
            )
            for f in result.get("files", [])
        ]
        
        return FileListResponse(
            success=True,
            files=files,
            total_count=result.get("total_count", len(files)),
            page=page,
            page_size=page_size,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Get files failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/events", response_model=EventListResponse)
async def get_task_events(
    task_id: str,
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    start_time: Optional[str] = Query(None, description="Start time filter (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time filter (ISO format)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Page size"),
    settings: Settings = Depends(get_settings),
):
    """
    Get timeline events from a task's database.
    
    Supports filtering by event type and time range.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        result = await service_manager.cpp_backend.get_task_events(
            task_id=task_id,
            event_type=event_type,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size,
        )
        
        events = [
            EventRecord(
                id=e.get("id", 0),
                event_type=e.get("event_type", ""),
                file_path=e.get("file_path", ""),
                timestamp=e.get("timestamp", ""),
                details=e.get("details"),
            )
            for e in result.get("events", [])
        ]
        
        return EventListResponse(
            success=True,
            events=events,
            total_count=result.get("total_count", len(events)),
            page=page,
            page_size=page_size,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Get events failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query", response_model=QueryResponse)
async def execute_query(
    request: QueryRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Execute a custom query on a task's database.
    
    Only SELECT queries are allowed for security.
    """
    # Validate SQL if provided
    if request.sql:
        sql_upper = request.sql.strip().upper()
        if not sql_upper.startswith("SELECT"):
            raise HTTPException(
                status_code=400,
                detail="Only SELECT queries are allowed"
            )
        
        # Check for dangerous keywords
        dangerous_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE"]
        for keyword in dangerous_keywords:
            if keyword in sql_upper:
                raise HTTPException(
                    status_code=400,
                    detail=f"Query contains forbidden keyword: {keyword}"
                )
    
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        result = await service_manager.cpp_backend.execute_query(
            task_id=request.task_id,
            database_type=request.database_type,
            table=request.table,
            sql=request.sql,
            parameters=request.parameters,
            limit=request.limit,
        )
        
        return QueryResponse(
            success=True,
            columns=result.get("columns", []),
            rows=result.get("rows", []),
            row_count=len(result.get("rows", [])),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/export/toon")
async def export_toon(
    task_id: str,
    include_llm: bool = Query(True, description="Include LLM descriptions"),
    settings: Settings = Depends(get_settings),
):
    """
    Export task data in TOON format.
    
    Returns a TOON-formatted document containing all file records
    with their metadata and optional LLM descriptions.
    """
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        # Generate TOON export
        toon_content = await service_manager.cpp_backend.export_toon(
            task_id=task_id,
            include_llm=include_llm,
        )
        
        return StreamingResponse(
            iter([toon_content.encode("utf-8")]),
            media_type="application/x-toon",
            headers={
                "Content-Disposition": f"attachment; filename={task_id}_export.toon"
            }
        )
    except Exception as e:
        logger.error(f"TOON export failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/export/json")
async def export_json(
    task_id: str,
    database_type: str = Query("files", description="Database type to export"),
    include_llm: bool = Query(True, description="Include LLM descriptions"),
    settings: Settings = Depends(get_settings),
):
    """
    Export task data in JSON format.
    """
    import json
    
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        
        # Get data from C++ backend
        data = await service_manager.cpp_backend.export_json(
            task_id=task_id,
            database_type=database_type,
            include_llm=include_llm,
        )
        
        json_content = json.dumps(data, indent=2, ensure_ascii=False)
        
        return StreamingResponse(
            iter([json_content.encode("utf-8")]),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={task_id}_{database_type}.json"
            }
        )
    except Exception as e:
        logger.error(f"JSON export failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
