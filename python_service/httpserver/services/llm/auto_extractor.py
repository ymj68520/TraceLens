"""On-demand extraction for interactive LLM analysis.

The Files page "AI 分析" button analyzes a file picked from the image file
list; that file may not have been extracted to the host yet. Instead of
failing with 404 and asking the user to run extraction first, the analyze
routes call :func:`ensure_extracted_for_analysis` to run a single-file C++
extraction job and wait for it — the same "extract, then analyze" chain the
case-analysis pipeline has always used (case_analysis_parts/_windows.py).

The C++ extract route only accepts an output_dir relative to the per-task
extract root, and ``"extracted_files"`` IS that root, so extracted bytes land
exactly where ``resolve_analysis_path`` looks for them.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from .file_analyzer import resolve_analysis_path

logger = logging.getLogger(__name__)

# Same budget as the case-analysis extraction wait (10 minutes, 2s polls).
POLL_INTERVAL_SECONDS = 2
DEFAULT_TIMEOUT_SECONDS = 600


class AutoExtractionError(Exception):
    """The evidence file could not be materialized on the host for analysis."""


def to_image_internal_path(path: str, extraction_dir: str) -> str:
    """Recover the image-internal path (files.db ``path``) for extraction.

    The Files page prepends the task extraction directory to non-absolute
    paths before calling /api/llm/analyze, while C++ ``mode=name`` extraction
    matches against the image-internal path (``/etc/motd``). Host paths under
    the extraction dir are converted back; image paths pass through as-is.
    """
    if extraction_dir:
        dir_norm = str(Path(extraction_dir))
        if path.startswith(dir_norm):
            relative = path[len(dir_norm):].lstrip("/\\")
            if relative:
                return "/" + relative.replace("\\", "/")
    return path


async def ensure_extracted_for_analysis(
    cpp_backend,
    task_id: str,
    file_path: str,
    extraction_dir: str,
    db_file_path: Optional[str] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Make sure the evidence file exists on the host, extracting it if needed.

    Args:
        cpp_backend: CppBackendService used to start/track the extraction job.
        task_id: Task owning the source image and the extract directory.
        file_path: Path as supplied by the analyze request (image-internal or
            host path under ``extraction_dir``).
        extraction_dir: The task's extraction_directory.
        db_file_path: The files.db ``path`` when the caller knows it; preferred
            for pattern matching because it is the authoritative image path.
        timeout_seconds: Max wait for the extraction job to finish.

    Returns:
        The host path of the available file.

    Raises:
        AutoExtractionError: The file could not be matched in the image, the
            extraction job failed, or the file is still missing afterwards.
            Callers keep their existing not-found failure behavior.
    """
    image_path = to_image_internal_path(db_file_path or file_path, extraction_dir)
    if not image_path or ".." in Path(image_path).parts:
        raise AutoExtractionError(f"no extractable image path for {file_path!r}")

    extract_result = await cpp_backend.extract_files(
        task_id=task_id,
        file_paths=[image_path],
        output_dir="extracted_files",
        overwrite=False,
    )
    job_id = extract_result.get("job_id")
    if not job_id:
        reason = extract_result.get("error") or "no job_id returned"
        raise AutoExtractionError(f"extraction job could not start: {reason}")

    logger.info(
        "Auto-extracting %s for task %s before LLM analysis (job %s)",
        image_path, task_id, job_id,
    )

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds
    while True:
        status = await cpp_backend.get_extraction_status(job_id)
        if status.get("success") is False and "status" not in status:
            raise AutoExtractionError(
                f"extraction status unavailable: {status.get('error')}"
            )
        state = status.get("status", "unknown")
        if state == "completed":
            break
        if state in ("failed", "cancelled"):
            reason = status.get("error_details") or state
            raise AutoExtractionError(f"extraction job {job_id} {state}: {reason}")
        if loop.time() > deadline:
            raise AutoExtractionError(
                f"extraction job {job_id} timed out after {timeout_seconds}s"
            )
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    resolved = (
        resolve_analysis_path(file_path, extraction_dir)
        or resolve_analysis_path(db_file_path or file_path, extraction_dir)
    )
    if not resolved:
        raise AutoExtractionError(
            f"extraction job {job_id} completed but {image_path} is still missing"
        )
    logger.info("Auto-extraction produced %s for task %s", resolved, task_id)
    return resolved
