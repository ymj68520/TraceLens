"""
Markitdown conversion routes.

Provides a REST endpoint for converting files to markdown using
Microsoft's markitdown library. Used by the C++ backend via HTTP.
"""

import logging
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class ConvertRequest(BaseModel):
    """Request model for file-to-markdown conversion."""
    file_path: str = Field(..., description="Absolute path to the file to convert")


class ConvertResponse(BaseModel):
    """Response model for file-to-markdown conversion."""
    success: bool
    content: str = ""
    title: str = ""
    processing_time_ms: float = 0.0


@router.post(
    "/convert",
    response_model=ConvertResponse,
    responses={
        200: {"description": "File converted successfully"},
        400: {"description": "Invalid request"},
        404: {"description": "File not found"},
        500: {"description": "Conversion failed"},
    },
)
async def convert_file(request: ConvertRequest):
    """
    Convert a file to markdown using markitdown.

    Supports: PDF, DOCX, DOC, XLSX, XLS, PPTX, PPT, HTML, CSV, JSON,
    XML, EPUB, IPYNB, images (EXIF+OCR), audio (transcription), and more.

    This endpoint is primarily used by the C++ backend to convert files
    to markdown before sending to LLM for analysis.
    """
    start_time = time.time()

    # Validate file exists
    file_path = Path(request.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {request.file_path}"
        )

    if not file_path.is_file():
        raise HTTPException(
            status_code=400,
            detail=f"Path is not a file: {request.file_path}"
        )

    try:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(str(file_path))

        markdown = result.markdown if result else ""
        title = getattr(result, 'title', None) or ""

        processing_time = (time.time() - start_time) * 1000

        logger.info(
            f"markitdown converted {request.file_path}: "
            f"{len(markdown)} chars in {processing_time:.1f}ms"
        )

        return ConvertResponse(
            success=True,
            content=markdown,
            title=title,
            processing_time_ms=processing_time,
        )

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="markitdown library is not installed. Install with: pip install 'markitdown[all]'"
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {request.file_path}"
        )
    except Exception as e:
        processing_time = (time.time() - start_time) * 1000
        logger.error(f"markitdown conversion failed for {request.file_path}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Conversion failed: {str(e)}"
        )


@router.get("/status")
async def markitdown_status():
    """Check if markitdown is available and list supported formats."""
    try:
        import markitdown
        version = getattr(markitdown, '__version__', 'unknown')
        return {
            "available": True,
            "version": version,
            "supported_formats": [
                "pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt",
                "html", "htm", "csv", "json", "xml", "epub", "ipynb",
                "rss", "jpg", "jpeg", "png", "gif", "bmp", "webp",
                "tiff", "tif", "mp3", "wav",
            ],
        }
    except ImportError:
        return {
            "available": False,
            "error": "markitdown library is not installed",
        }
