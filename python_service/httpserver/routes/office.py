"""
Office Document Parsing Routes.

Provides API endpoints for parsing Office documents:
- POST /api/office/parse - Parse a file and return Markdown content
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.office_service import get_office_service

logger = logging.getLogger(__name__)

router = APIRouter()


class ParseRequest(BaseModel):
    """Request model for parsing an Office file."""

    task_id: str | None = Field(None, description="Task ID owning the file (membership anchor)")
    workspace_root: str | None = Field(None, description="Deprecated standalone workspace anchor for C++ callers")
    file_path: str = Field(..., description="Absolute path to the Office file")


class ParseResponse(BaseModel):
    """Response model for parsed Office content."""

    success: bool = Field(..., description="Whether parsing was successful")
    content: str = Field(default="", description="Extracted content in Markdown format")
    file_type: str = Field(default="", description="Detected file type")
    error: Optional[str] = Field(default=None, description="Error message if failed")


@router.post("/parse", response_model=ParseResponse)
async def parse_office_file(request: ParseRequest) -> ParseResponse:
    """
    Parse an Office file and return its content as Markdown.

    Supports:
    - .xlsx (Excel 2007+)
    - .xls (Excel 97-2003)
    - .pptx (PowerPoint 2007+)
    - .ppt (PowerPoint 97-2003)

    Args:
        request: Request containing the file path.

    Returns:
        ParseResponse with extracted content or error message.
    """
    file_path = request.file_path

    # Task ownership gate (D2b): the file must be a known record of this
    # task (exact files.path match) or live in the C++ pipeline's shared
    # internal extraction scratch root. Never a bare host-existence check.
    from ..services import task_store

    try:
        if request.task_id:
            task = await task_store.get_task_record(request.task_id)
            workspace = task_store.workspace_from_record(task)
            files_db = task_store.files_db_from_record(task)
        elif request.workspace_root:
            task = {}
            workspace = Path(request.workspace_root).resolve(strict=False)
            files_db = None
        else:
            raise HTTPException(
                status_code=400, detail="task_id or workspace_root is required"
            )
    except task_store.TaskStoreError as exc:
        if exc.code == task_store.TASK_NOT_FOUND:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    known = False
    try:
        # A task workspace path is not automatically a known Evidence file.
        # Accept exact files.path membership, or the server-derived extraction
        # directory used by the C++ FileAnalyzer/OfficeAnalyzer pipeline.
        known = task_store.file_known_to_task(files_db, file_path) if files_db else False
        if not known:
            extraction_dir = task.get("extraction_directory") if task else None
            if extraction_dir:
                task_store.resolved_within(
                    extraction_dir, Path(file_path)
                )
                known = True
            elif request.workspace_root:
                task_store.resolved_within(workspace, Path(file_path))
                known = True
    except task_store.TaskStoreError as exc:
        if exc.code != task_store.PATH_OUTSIDE_WORKSPACE:
            raise HTTPException(
                status_code=400, detail="task files database is unavailable"
            ) from exc
    if not known:
        raise HTTPException(
            status_code=404, detail="file is not part of the current task"
        )

    # Validate file exists
    path = Path(file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    # Get file type
    suffix = path.suffix.lower()
    supported_types = [".xlsx", ".xls", ".pptx", ".ppt"]

    if suffix not in supported_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: {supported_types}"
        )

    try:
        service = get_office_service()
        content = await service.parse_file(file_path)

        return ParseResponse(
            success=True,
            content=content,
            file_type=suffix[1:].upper(),  # Remove dot, uppercase
            error=None
        )

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise HTTPException(status_code=404, detail="file not found")

    except ValueError as e:
        logger.error(f"Invalid file type: {e}")
        raise HTTPException(status_code=400, detail="unsupported file type")

    except Exception as e:
        logger.error(f"Error parsing file {file_path}: {e}")
        return ParseResponse(
            success=False,
            content="",
            file_type=suffix[1:].upper(),
            error="office parse failed"
        )


@router.get("/supported-types")
async def get_supported_types():
    """Get list of supported Office file types."""
    return {
        "supported_types": [
            {"extension": ".xlsx", "description": "Excel 2007+ Workbook"},
            {"extension": ".xls", "description": "Excel 97-2003 Workbook"},
            {"extension": ".pptx", "description": "PowerPoint 2007+ Presentation"},
            {"extension": ".ppt", "description": "PowerPoint 97-2003 Presentation"},
        ]
    }
