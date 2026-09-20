"""
Office Document Parsing Routes.

Provides API endpoints for parsing Office documents:
- POST /api/office/parse - Parse a file and return Markdown content
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from ..services.office_service import get_office_service

logger = logging.getLogger(__name__)

router = APIRouter()


async def _materialize_from_image(task_id: str | None, file_path: str) -> Path:
    """Ask the C++ backend to extract one image file into the task's
    extracted_files directory. Returns the (possibly nonexistent) candidate
    path so callers can fall through to their own error handling."""
    candidate = Path(file_path)
    if not task_id:
        return candidate
    try:
        from ..services import get_service_manager

        service = get_service_manager().cpp_backend
        await service.initialize()
        response = await service.client.post(
            "/api/forensics/files/materialize",
            json={"task_id": task_id, "path": file_path},
            timeout=120.0,
        )
        if response.status_code == 200:
            data = response.json()
            materialized = data.get("materialized_path")
            if materialized:
                candidate = Path(materialized)
        else:
            logger.info(
                "materialize failed for %s (task %s): HTTP %s %s",
                file_path,
                task_id,
                response.status_code,
                response.text[:200],
            )
    except Exception as exc:  # noqa: BLE001 - preview must degrade gracefully
        logger.warning("materialize request failed for %s: %s", file_path, exc)
    return candidate


class ParseRequest(BaseModel):
    """Request model for parsing an Office file."""

    task_id: str | None = Field(None, description="Task ID owning the file (membership anchor)")
    workspace_root: str | None = Field(None, description="Deprecated standalone workspace anchor for C++ callers")
    file_path: str = Field(..., description="Absolute path to the Office file")


class Slide(BaseModel):
    """One PPTX slide for the rich web preview."""

    title: str = ""
    texts: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list, description="base64 data URIs")
    table: Optional[list[list[str]]] = None


class Sheet(BaseModel):
    """One worksheet for the rich web preview."""

    name: str = ""
    data: list[list[str]] = Field(default_factory=list)
    total_rows: int = 0


class ParseResponse(BaseModel):
    """Response model for parsed Office content."""

    success: bool = Field(..., description="Whether parsing was successful")
    content: str = Field(default="", description="Extracted content in Markdown format")
    file_type: str = Field(default="", description="Detected file type")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    slides: Optional[list[Slide]] = Field(default=None, description="PPTX slides")
    sheets: Optional[list[Sheet]] = Field(default=None, description="Excel sheets")


@router.post("/parse", response_model=ParseResponse)
async def parse_office_file(request: ParseRequest) -> ParseResponse:
    """
    Parse an Office file and return its content as Markdown.

    Supports:
    - .docx (Word 2007+)
    - .doc (Word 97-2003)
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
    path = await _resolve_task_file(request.task_id, request.workspace_root, file_path)

    # Get file type
    suffix = path.suffix.lower()

    try:
        service = get_office_service()
        content = await service.parse_file(str(path))
        slides: Optional[list[Slide]] = None
        sheets: Optional[list[Sheet]] = None

        if suffix == ".pptx":
            slides = [Slide(**s) for s in await service.extract_slides(str(path))]
        elif suffix in (".xlsx", ".xls"):
            sheets = [Sheet(**s) for s in await service.extract_sheets(str(path))]

        return ParseResponse(
            success=True,
            content=content,
            file_type=suffix[1:].upper(),  # Remove dot, uppercase
            error=None,
            slides=slides,
            sheets=sheets,
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


@router.get("/file")
async def get_office_file(
    file_path: str = "",
    task_id: Optional[str] = None,
    workspace_root: Optional[str] = None,
):
    """Serve the (on-demand materialized) Office file bytes for client-side
    rendering, e.g. the full-fidelity docx viewer in the web preview."""
    if not file_path:
        raise HTTPException(status_code=400, detail="file_path is required")
    path = await _resolve_task_file(task_id, workspace_root, file_path)

    media_types = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".ppt": "application/vnd.ms-powerpoint",
    }
    media_type = media_types.get(path.suffix.lower(), "application/octet-stream")

    # HTTP headers are latin-1; non-ASCII filenames need RFC 5987 encoding.
    name = path.name
    try:
        name.encode("latin-1")
        disposition = f'inline; filename="{name}"'
    except UnicodeEncodeError:
        from urllib.parse import quote

        disposition = f"inline; filename*=UTF-8''{quote(name)}"

    return Response(
        content=path.read_bytes(),
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


async def _resolve_task_file(
    task_id: Optional[str], workspace_root: Optional[str], file_path: str
) -> Path:
    """Apply the task-membership gate and resolve to a host path, extracting
    the file from the image on demand. Shared by /parse and /file."""
    # Task ownership gate (D2b): the file must be a known record of this
    # task (exact files.path match) or live in the C++ pipeline's shared
    # internal extraction scratch root. Never a bare host-existence check.
    from ..services import task_store

    try:
        if task_id:
            task = await task_store.get_task_record(task_id)
            workspace = task_store.workspace_from_record(task)
            files_db = task_store.files_db_from_record(task)
        elif workspace_root:
            task = {}
            workspace = Path(workspace_root).resolve(strict=False)
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
            elif workspace_root:
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

    # Validate file exists. The raw image-internal path usually does not exist
    # on the host; fall back to the copy materialized by the extraction pipeline
    # under the task's extraction directory, the LLM analysis scratch copy, or
    # ask the C++ backend to extract the file from the image on demand.
    path = Path(file_path)
    if not path.exists() and task.get("extraction_directory"):
        candidate = Path(task["extraction_directory"]) / file_path.lstrip("/")
        if candidate.exists():
            path = candidate
    if not path.exists():
        scratch_candidate = (
            Path(tempfile.gettempdir())
            / "forensics_llm_extract"
            / (task_id or "")
            / file_path.replace("/", "_").replace("\\", "_")
        )
        if task_id and scratch_candidate.exists():
            path = scratch_candidate
    if not path.exists():
        path = await _materialize_from_image(task_id, file_path)

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    # Get file type
    suffix = path.suffix.lower()
    supported_types = [".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"]

    if suffix not in supported_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: {supported_types}"
        )
    return path


@router.get("/supported-types")
async def get_supported_types():
    """Get list of supported Office file types."""
    return {
        "supported_types": [
            {"extension": ".docx", "description": "Word 2007+ Document"},
            {"extension": ".doc", "description": "Word 97-2003 Document"},
            {"extension": ".xlsx", "description": "Excel 2007+ Workbook"},
            {"extension": ".xls", "description": "Excel 97-2003 Workbook"},
            {"extension": ".pptx", "description": "PowerPoint 2007+ Presentation"},
            {"extension": ".ppt", "description": "PowerPoint 97-2003 Presentation"},
        ]
    }
