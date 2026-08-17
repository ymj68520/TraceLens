"""
Markitdown conversion routes.

Provides a REST endpoint for converting files to markdown using
Microsoft's markitdown library. Used by the C++ backend via HTTP.
"""

import asyncio
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.document_extractor import get_document_extractor_locator

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level singleton MarkItDown instance.
# Creating a new MarkItDown() per request reloads the magika ONNX model
# every time (~0.5s overhead), wastes memory, and can cause transient
# failures under concurrent load — which makes the C++ backend fall back
# to its legacy local parsers.  Reuse one instance instead.
_md_instance = None
_md_lock = threading.Lock()


def _get_markitdown():
    """Return a process-wide singleton MarkItDown instance (lazy init)."""
    global _md_instance
    if _md_instance is None:
        with _md_lock:
            if _md_instance is None:
                from markitdown import MarkItDown
                _md_instance = MarkItDown()
                logger.info("MarkItDown singleton initialised for /convert endpoint")
    return _md_instance


class ConvertRequest(BaseModel):
    """Request model for file-to-markdown conversion."""
    task_id: str | None = Field(None, description="Task ID owning the file (workspace anchor)")
    workspace_root: str | None = Field(None, description="Deprecated standalone workspace anchor for CLI callers")
    file_path: str = Field(..., description="Absolute path to the file to convert")


async def _task_conversion_anchors(
    task_id: str | None, workspace_root: str | None
):
    """Resolve task or explicit standalone workspace conversion anchors."""
    from ..services import task_store

    if task_id:
        try:
            task = await task_store.get_task_record(task_id)
            workspace = task_store.workspace_from_record(task)
            files_db = task_store.files_db_from_record(task)
        except task_store.TaskStoreError as exc:
            if exc.code == task_store.TASK_NOT_FOUND:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return workspace, task_store.internal_extract_root(), files_db

    if not workspace_root:
        raise HTTPException(
            status_code=400, detail="task_id or workspace_root is required"
        )
    return Path(workspace_root).resolve(strict=False), None, None


async def _assert_file_readable_for_task(
    task_id: str | None, workspace_root: str | None, file_path: str
) -> None:
    """Gate /convert reads using task or explicit standalone workspace."""
    from ..services import task_store

    workspace, extract_root, files_db = await _task_conversion_anchors(
        task_id, workspace_root
    )
    candidate = Path(file_path)
    try:
        task_store.resolved_within(workspace, candidate)
        return
    except task_store.TaskStoreError:
        pass
    if extract_root is not None:
        try:
            task_store.resolved_within(extract_root, candidate)
            return
        except task_store.TaskStoreError:
            pass
    if files_db is not None:
        try:
            if task_store.file_known_to_task(files_db, file_path):
                return
        except task_store.TaskStoreError:
            raise HTTPException(
                status_code=400, detail="task files database is unavailable"
            ) from None
    raise HTTPException(
        status_code=400, detail="file is outside the task workspace"
    )


async def _task_workspace_or_400(
    task_id: str | None, workspace_root: str | None
) -> Path:
    """Resolve the task workspace or standalone CLI workspace anchor."""
    from ..services import task_store

    if not task_id:
        if not workspace_root:
            raise HTTPException(
                status_code=400, detail="task_id or workspace_root is required"
            )
        return Path(workspace_root).resolve(strict=False)
    try:
        return await task_store.resolve_task_workspace(task_id)
    except task_store.TaskStoreError as exc:
        if exc.code == task_store.TASK_NOT_FOUND:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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

    # Task ownership gate: the file must belong to the requesting task.
    await _assert_file_readable_for_task(
        request.task_id, request.workspace_root, request.file_path
    )

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
        md = _get_markitdown()

        # Offload the synchronous, IO/CPU-heavy conversion so it doesn't block
        # the event loop (and stall every other request) for large files.
        result = await asyncio.to_thread(md.convert, str(file_path))

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
            detail="conversion failed"
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


# ---------------------------------------------------------------------------
# Batch conversion — convert an entire directory of extracted files to text.
# Unlike the single-file /convert endpoint (which only uses the markitdown
# library), this endpoint routes each file through ExtractorLocator so that
# specialized extractors (evtx, registry, PE/ELF, archives, databases, ...)
# are used too. This gives the broadest coverage for offline field testing.
# ---------------------------------------------------------------------------

class BatchConvertRequest(BaseModel):
    """Request model for batch directory-to-markdown conversion."""
    task_id: str | None = Field(None, description="Task ID owning the conversion roots")
    workspace_root: str | None = Field(None, description="Deprecated standalone workspace anchor for CLI callers")
    input_dir: str = Field(..., description="Absolute path to the directory of files to convert")
    output_dir: str = Field(..., description="Absolute path to the output directory for .md files")


class BatchConvertResponse(BaseModel):
    """Response model for batch conversion."""
    success: bool
    total_files: int = 0
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    errors: List[str] = Field(default_factory=list)
    output_dir: str = ""


ConversionStatus = Literal["converted", "skipped", "failed"]


@dataclass(frozen=True)
class FileConversionOutcome:
    """The result of converting one input file to its mirrored Markdown file."""
    status: ConversionStatus
    input_path: Path
    output_path: Optional[Path] = None
    output_size: int = 0
    error: str = ""


class ConvertOneRequest(BaseModel):
    """Request model for converting one file beneath an input root."""
    task_id: str | None = Field(None, description="Task ID owning the conversion roots")
    workspace_root: str | None = Field(None, description="Deprecated standalone workspace anchor for CLI callers")
    input_root: str
    input_file: str
    output_root: str


def _exception_text(exc: BaseException) -> str:
    # Exception class only: conversion/library errors can embed resolved
    # server paths in their message text and this reaches client responses.
    return type(exc).__name__


class ConvertOneResponse(BaseModel):
    """Response model for a single atomic file conversion."""
    success: bool
    status: ConversionStatus
    input_path: str
    output_path: str = ""
    output_size: int = 0
    error: str = ""


def _output_path_for(input_file: Path, input_root: Path, output_root: Path) -> Path:
    """Validate paths and return the mirrored Markdown output destination."""
    try:
        if input_root.is_symlink():
            raise ValueError(f"Input root must not be a symlink: {input_root}")
        if input_file.is_symlink():
            raise ValueError(f"Input file must not be a symlink: {input_file}")

        resolved_root = input_root.resolve(strict=True)
        if not resolved_root.is_dir():
            raise ValueError(f"Input root is not a directory: {input_root}")
        resolved_input = input_file.resolve(strict=True)
        try:
            relative_input = resolved_input.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"Input file is outside input root: {input_file}") from exc
        if not resolved_input.is_file():
            raise ValueError(f"Input path is not a regular file: {input_file}")
    except OSError as exc:
        raise ValueError(f"Invalid input path: {input_file}: {exc}") from exc

    if output_root.is_symlink():
        raise ValueError(f"Output root must not be a symlink: {output_root}")
    if output_root.exists() and not output_root.is_dir():
        raise ValueError(f"Output root is not a directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    if output_root.is_symlink():
        raise ValueError(f"Output root must not be a symlink: {output_root}")
    if not output_root.is_dir():
        raise ValueError(f"Output root is not a directory: {output_root}")

    output_path = output_root / (str(relative_input) + ".md")
    current = output_root
    for component in output_path.relative_to(output_root).parts[:-1]:
        if current.is_symlink():
            raise ValueError(f"Output path contains a symlink: {current}")
        current = current / component
        if current.is_symlink():
            raise ValueError(f"Output path contains a symlink: {current}")
        current.mkdir(exist_ok=True)
    if output_path.is_symlink():
        raise ValueError(f"Output file must not be a symlink: {output_path}")
    return output_path


def _write_markdown_atomic(output_path: Path, markdown: str) -> int:
    """Write Markdown through a reserved same-directory temporary file."""
    temp_path = output_path.parent / (
        f".tracelens-textdump-tmp-{uuid.uuid4().hex}-{output_path.name}"
    )
    try:
        temp_path.write_text(markdown, encoding="utf-8")
        os.replace(temp_path, output_path)
        return output_path.stat().st_size
    finally:
        temp_path.unlink(missing_ok=True)


async def _convert_file_to_output(
    file_path: Path, input_root: Path, output_root: Path
) -> FileConversionOutcome:
    """Convert one validated file and atomically write its Markdown output."""
    output_path = _output_path_for(file_path, input_root, output_root)
    try:
        locator = get_document_extractor_locator()
        extractor = locator.get_extractor(str(file_path))
        if extractor is not None:
            markdown = await extractor.extract_to_markdown(str(file_path))
        else:
            raw = file_path.read_bytes()
            if not raw or _is_likely_binary(raw):
                return FileConversionOutcome("skipped", file_path)
            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                text = raw.decode("latin-1", errors="replace")
            markdown = f"# {file_path.name}\n\n```\n{text}\n```\n"
    except Exception as exc:
        return FileConversionOutcome("failed", file_path, error=_exception_text(exc))
    if not markdown or not markdown.strip():
        return FileConversionOutcome("skipped", file_path)
    output_size = _write_markdown_atomic(output_path, markdown)
    return FileConversionOutcome(
        "converted", file_path, output_path=output_path, output_size=output_size
    )


@router.post("/convert-one", response_model=ConvertOneResponse)
async def convert_one(request: ConvertOneRequest):
    """Convert one file under input_root into a mirrored Markdown file."""
    # Both roots must live inside the task workspace (write anchor).
    from ..services import task_store

    workspace = await _task_workspace_or_400(
        request.task_id, request.workspace_root
    )
    try:
        if task_store.has_symlink_component(request.input_root) or task_store.has_symlink_component(request.input_file) or task_store.has_symlink_component(request.output_root):
            raise HTTPException(
                status_code=400,
                detail="conversion paths must not contain symlinks",
            )
        input_root = task_store.resolved_within(workspace, Path(request.input_root))
        input_file = task_store.resolved_within(workspace, Path(request.input_file))
        output_root = task_store.resolved_within(workspace, Path(request.output_root))
    except task_store.TaskStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # The conversion primitive requires the input file to be beneath the
    # declared input root. Resolve that relationship before calculating the
    # mirrored output path so malformed roots fail as a stable 400.
    try:
        relative_input = input_file.relative_to(input_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="input file is outside the input root"
        ) from exc

    # A conversion output must never overwrite its own input (§D2b), and an
    # output tree nested in (or containing) the input tree would turn the
    # source Evidence tree into a write target.
    try:
        if (
            output_root == input_root
            or output_root.is_relative_to(input_root)
            or input_root.is_relative_to(output_root)
        ):
            raise HTTPException(
                status_code=400,
                detail="output tree overlaps the input tree",
            )
    except AttributeError:  # Python < 3.9 compatibility for Path.is_relative_to
        try:
            output_root.relative_to(input_root)
            output_overlaps = True
        except ValueError:
            try:
                input_root.relative_to(output_root)
                output_overlaps = True
            except ValueError:
                output_overlaps = output_root == input_root
        if output_overlaps:
            raise HTTPException(
                status_code=400,
                detail="output tree overlaps the input tree",
            )

    expected_output = output_root / (str(relative_input) + ".md")
    if expected_output.resolve(strict=False) == input_file.resolve(strict=False):
        raise HTTPException(
            status_code=400,
            detail="output path overlaps the input file",
        )

    try:
        outcome = await _convert_file_to_output(
            input_file, input_root, output_root
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Output write failed: {_exception_text(exc)}",
        ) from exc
    return ConvertOneResponse(
        success=outcome.status == "converted",
        status=outcome.status,
        input_path=str(outcome.input_path),
        output_path=str(outcome.output_path or ""),
        output_size=outcome.output_size,
        error=outcome.error,
    )


async def _convert_one(file_path: Path, input_root: Path, output_root: Path,
                       sem: asyncio.Semaphore):
    """Run the shared conversion primitive under the batch concurrency bound."""
    async with sem:
        try:
            outcome = await _convert_file_to_output(file_path, input_root, output_root)
            rel = file_path.relative_to(input_root)
            if outcome.status == "failed":
                detail = f"{rel}: {outcome.error}"
            else:
                detail = str(rel)
            return (outcome.status, detail)
        except Exception as exc:
            try:
                rel = file_path.relative_to(input_root)
            except ValueError:
                rel = file_path
            return ("failed", f"{rel}: {_exception_text(exc)}")


def _is_likely_binary(data: bytes, sample_size: int = 8192) -> bool:
    """
    Heuristic: if the sample contains a NUL byte or too many non-text bytes,
    treat it as binary and skip raw-text conversion.
    """
    sample = data[:sample_size]
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    # Count non-printable, non-whitespace bytes.
    non_text = sum(1 for b in sample if b < 9 or (13 < b < 32))
    return (non_text / len(sample)) > 0.30


@router.post(
    "/batch-convert",
    response_model=BatchConvertResponse,
    responses={
        200: {"description": "Batch conversion completed"},
        400: {"description": "Invalid input directory"},
        500: {"description": "Batch conversion failed"},
    },
)
async def batch_convert(request: BatchConvertRequest):
    """
    Convert every file in a directory to markdown.

    Walks `input_dir` recursively, routes each file through ExtractorLocator
    (so specialized extractors for evtx, registry, PE, archives, etc. are
    used — not just markitdown), and writes one .md file per source file to
    `output_dir`, mirroring the relative directory structure.

    Files with no matching extractor are skipped (counted in `skipped`).
    Individual conversion failures are counted in `failed` and recorded in
    `errors`; they do not abort the batch.
    """
    start_time = time.time()

    # Both roots must live inside the task workspace (write anchor) and the
    # mirrored output tree must never overwrite any input file (§D2b).
    from ..services import task_store

    workspace = await _task_workspace_or_400(
        request.task_id, request.workspace_root
    )
    try:
        if task_store.has_symlink_component(request.input_dir) or task_store.has_symlink_component(request.output_dir):
            raise HTTPException(
                status_code=400,
                detail="conversion paths must not contain symlinks",
            )
        input_dir = task_store.resolved_within(workspace, Path(request.input_dir))
        output_dir = task_store.resolved_within(workspace, Path(request.output_dir))
    except task_store.TaskStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Validate input directory
    if input_dir.is_symlink():
        raise HTTPException(
            status_code=400,
            detail=f"Input directory must not be a symlink: {request.input_dir}"
        )
    if not input_dir.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Input directory not found: {request.input_dir}"
        )
    if not input_dir.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Input path is not a directory: {request.input_dir}"
        )

    # Create output directory
    if output_dir.is_symlink():
        raise HTTPException(
            status_code=400,
            detail=f"Output directory must not be a symlink: {request.output_dir}"
        )
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Cannot create output directory {request.output_dir}: "
                f"{_exception_text(exc)}"
            ),
        ) from exc

    # Collect all regular files (recursive)
    all_files = [f for f in input_dir.rglob("*") if f.is_file()]
    total = len(all_files)

    # Mirrored output names must never overwrite a source file: converting
    # input "x" writes "x.md", which collides with a sibling input "x.md".
    if total:
        resolved_inputs = {f.resolve(strict=False) for f in all_files}
        for f in all_files:
            candidate = output_dir / (str(f.relative_to(input_dir)) + ".md")
            if candidate.resolve(strict=False) in resolved_inputs:
                raise HTTPException(
                    status_code=400,
                    detail="output tree overlaps an input file",
                )

    if total == 0:
        logger.info(f"batch-convert: input dir {input_dir} is empty")
        return BatchConvertResponse(
            success=True, total_files=0, output_dir=str(output_dir)
        )

    logger.info(
        f"batch-convert: {total} files in {input_dir} -> {output_dir}"
    )

    # Limit concurrency to avoid exhausting memory on large directories.
    sem = asyncio.Semaphore(4)
    results = await asyncio.gather(
        *[_convert_one(f, input_dir, output_dir, sem) for f in all_files]
    )

    converted = sum(1 for status, _ in results if status == "converted")
    skipped = sum(1 for status, _ in results if status == "skipped")
    failed = sum(1 for status, _ in results if status == "failed")
    errors = [detail for status, detail in results if status == "failed"]
    # Cap the error list to avoid a huge response payload.
    if len(errors) > 50:
        errors = errors[:50] + [f"... and {failed - 50} more failures"]

    elapsed = (time.time() - start_time) * 1000
    logger.info(
        f"batch-convert done: {converted} converted, {skipped} skipped, "
        f"{failed} failed of {total} in {elapsed:.0f}ms"
    )

    return BatchConvertResponse(
        success=True,
        total_files=total,
        converted=converted,
        skipped=skipped,
        failed=failed,
        errors=errors,
        output_dir=str(output_dir),
    )
