"""Task-level file-analysis endpoints (SPEC file-analysis D18 / §8.1).

Mirrors the event-cluster-analysis endpoint family: an estimate (read-only
budget preview), a background run (job convention of the newest route
modules — a module-level registry), run status, and the analysis-record
version chain.
"""

import asyncio
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Background run jobs (module-level registry, event-cluster-analysis style).
_run_jobs = {}


class FileAnalysisEstimateRequest(BaseModel):
    task_id: str


class FileAnalysisRunRequest(BaseModel):
    task_id: str
    file_paths: Optional[List[str]] = None
    case_description: str = ""


async def _resolve_task_files(service_manager, task_id: str):
    task_info = await service_manager.cpp_backend.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    files_db = task_info.get("output_files_db") or ""
    if not files_db:
        raise HTTPException(status_code=400, detail="No files database for this task")
    return task_info, files_db


@router.post("/file-analysis/estimate")
async def estimate_file_analysis(
    request: FileAnalysisEstimateRequest,
    settings=Depends(get_settings),
):
    """Read-only budget preview (SPEC §8.1): candidate counts + cost estimate.

    ``pending`` counts the filtered files without an analysis record — the
    exact workload a subsequent ``run`` would execute.
    """
    from ..services import get_service_manager
    from ..services.case_analysis.db_utils import get_filtered_files_from_db
    from ..services.case_analysis.file_schema import (
        analysis_stats,
        latest_analysis,
    )

    service_manager = get_service_manager()
    _task_info, files_db = await _resolve_task_files(service_manager, request.task_id)

    filtered = get_filtered_files_from_db(files_db, request.task_id)
    pending_paths = [
        path for path in filtered
        if latest_analysis(files_db, path) is None
    ]
    stats = analysis_stats(files_db)

    return {
        "task_id": request.task_id,
        "filtered_total": len(filtered),
        "analyzed": len(filtered) - len(pending_paths),
        "pending": len(pending_paths),
        "stale": stats.get("stale", 0),
        "estimated_llm_calls": len(pending_paths),
        "estimated_chars": len(pending_paths) * max(
            int(getattr(settings, "file_analysis_max_content", 10000) or 10000), 0
        ),
    }


@router.post("/file-analysis/run")
async def run_file_analysis(request: FileAnalysisRunRequest):
    """Run the case-driven file-description round as a background job.

    Targets ``file_paths`` when given, otherwise the task's filtered file
    list. Skip/analysis semantics are the pipeline's (§4): files with a
    truth record are skipped.
    """
    from .case_analysis_endpoints._helpers import get_case_analysis_service
    from ..services import get_service_manager
    from ..services.case_analysis.db_utils import get_filtered_files_from_db

    service_manager = get_service_manager()
    task_info, files_db = await _resolve_task_files(service_manager, request.task_id)

    paths = list(request.file_paths or []) or get_filtered_files_from_db(
        files_db, request.task_id
    )
    if not paths:
        raise HTTPException(
            status_code=400,
            detail="no candidate files: run case filtering first or pass file_paths",
        )

    case_service = get_case_analysis_service(service_manager)
    extraction_dir = task_info.get("extraction_directory") or ""

    job_id = str(uuid.uuid4())
    _run_jobs[job_id] = {
        "status": "running",
        "task_id": request.task_id,
        "processed": 0,
        "total": len(paths),
        "results": [],
        "errors": [],
    }

    def _progress(processed, total, file_path):
        job = _run_jobs.get(job_id)
        if job is not None:
            job["processed"] = processed
            job["total"] = total
            job["current_file"] = file_path

    async def _worker():
        job = _run_jobs.get(job_id)
        try:
            results = await case_service.generate_file_descriptions(
                files_db, paths, request.case_description,
                extraction_dir=extraction_dir, progress_callback=_progress,
                task_id=request.task_id,
            )
            job["results"] = results
            job["processed"] = len(results)
            job["status"] = "completed"
        except Exception as e:
            logger.error(f"file-analysis run {job_id} failed: {e}", exc_info=True)
            job["status"] = "failed"
            job["errors"].append(str(e))

    asyncio.create_task(_worker())

    return {
        "job_id": job_id,
        "task_id": request.task_id,
        "total": len(paths),
        "status": "running",
    }


@router.get("/file-analysis/run/{job_id}")
async def get_file_analysis_run_status(job_id: str):
    job = _run_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Run job not found")
    return dict(job)


@router.get("/file-analyses")
async def list_file_analyses(
    task_id: str = Query(..., description="Task ID"),
    file_path: Optional[str] = Query(None, description="Version chain of one file"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Query the append-only file analysis records (version chain)."""
    from ..services import get_service_manager
    from ..services.case_analysis.file_schema import list_analyses

    service_manager = get_service_manager()
    _task_info, files_db = await _resolve_task_files(service_manager, task_id)

    records = list_analyses(files_db, task_id, file_path=file_path, limit=limit)
    return {
        "task_id": task_id,
        "file_path": file_path,
        "total": len(records),
        "records": records,
    }


class FileAnalysisRecordRequest(BaseModel):
    """One pipeline file-analysis result, persisted through the SPEC three-write.

    llm-throughput-hardening SPEC E: the C++ pipeline previously maintained a
    hand-synced copy of the display-cache writes and skipped the append-only
    ``file_analyses`` truth row entirely. It now POSTs each result here so the
    tested Python three-write path stays the single writer.
    """

    task_id: str
    file_path: str
    description: str
    summary: str = ""
    keywords: str = ""  # comma-separated
    model_used: str = ""
    extraction_method: str = ""  # markitdown / raw_text / vision / metadata_only


@router.post("/file-analysis/record")
async def record_file_analysis(request: FileAnalysisRecordRequest):
    """Persist one pipeline analysis via the atomic three-write (SPEC E).

    ``files_db_path`` is resolved from the task record (D2b trust source), so
    the caller cannot redirect writes at an arbitrary database.
    """
    from ..services import get_service_manager

    service_manager = get_service_manager()
    _task_info, files_db = await _resolve_task_files(service_manager, request.task_id)

    llm_service = getattr(service_manager, "llm_service", None)
    if llm_service is None:
        raise HTTPException(status_code=503, detail="LLM service unavailable")

    persisted = await asyncio.to_thread(
        llm_service.persist_to_files_db,
        files_db,
        request.file_path,
        request.description,
        request.summary,
        request.keywords,
        request.model_used,
        request.task_id,
        "pipeline",
        request.extraction_method,
    )
    if not persisted:
        raise HTTPException(
            status_code=500,
            detail=f"persist_to_files_db failed for {request.file_path!r}",
        )

    # File-centric investigation event, generated in the same pass as the file
    # analysis so the workbench's left column is populated without a separate
    # cluster run. Best-effort by design: an event-side failure must never
    # lose the analysis we just committed, and the bootstrap sweep re-seeds
    # any file this hook misses.
    event_result = await _seed_file_event(service_manager, _task_info, request, llm_service)

    return {
        "persisted": True,
        "task_id": request.task_id,
        "file_path": request.file_path,
        "trigger_source": "pipeline",
        "investigation_event": event_result,
    }


async def _seed_file_event(service_manager, task_info, request, llm_service):
    """Build and persist the file's investigation event node."""
    from ..services.investigation.file_events import (
        build_file_event_node,
        read_file_artifacts,
        read_macb_events,
    )
    from ..services.investigation.file_events import _NARRATIVE_PROMPT

    try:
        artifacts = await asyncio.to_thread(
            read_file_artifacts, task_info, request.file_path
        )
        macb = await asyncio.to_thread(read_macb_events, task_info, request.file_path)
        node = build_file_event_node(
            task_info,
            {"path": request.file_path, "name": request.file_path.rsplit("/", 1)[-1]},
            artifacts,
            macb,
        )

        # One short LLM call turns the collected rows into an investigative
        # narrative. It runs only when there is something beyond the bare
        # MACB timestamps the panel already shows.
        if artifacts and llm_service is not None:
            try:
                response = await llm_service.analyze(
                    node["summary"], prompt=_NARRATIVE_PROMPT, max_tokens=400
                )
                # analyze() returns {"analysis": {"summary", "description"}, ...}
                analysis = (response or {}).get("analysis") or {}
                narrative = (analysis.get("summary") or analysis.get("description") or "").strip()
                if narrative:
                    node["summary"] = narrative[:4000]
            except Exception as exc:  # noqa: BLE001 - narrative is optional
                logger.warning("event narrative failed for %s: %s", request.file_path, exc)

        seed = await _persist_event(service_manager, request.task_id, node, request.file_path)
        return seed
    except Exception as exc:  # noqa: BLE001 - never fail the analysis write
        logger.warning("investigation event seed failed for %s: %s", request.file_path, exc)
        return {"seeded": False, "error": str(exc)[:200]}


async def _persist_event(service_manager, task_id: str, node, file_path: str):
    """Write one file-seeded event through the repository-v7 module.

    Reuses ``bulk_seed_cluster_events`` so the snapshot + link + event rows
    commit as one transaction, exactly like bootstrap. The seed marker is the
    file path, which is what makes a re-run idempotent.
    """
    from ..services.evidence.resolver import EvidenceResolver
    from ..services.investigation.acquisition import build_snapshot_candidate
    from ..services.investigation.paths import investigation_db_path_for_task
    from ..services.investigation.repository import InvestigationRepository

    task = await service_manager.cpp_backend.get_task(task_id)
    if not isinstance(task, dict) or task.get("id") != task_id:
        return {"seeded": False, "reason": "task_not_available"}

    db_path = investigation_db_path_for_task(task)
    repository = InvestigationRepository(db_path, task_id)
    existing = await asyncio.to_thread(repository.list_seed_markers)
    marker = f"file_seed:{file_path}"
    if marker in existing:
        return {"seeded": False, "reason": "already_seeded", "marker": marker}

    resolver = EvidenceResolver(service_manager.cpp_backend)
    candidates = {}
    for key in node["evidence_keys"]:
        try:
            resolved = await resolver.resolve_evidence(task_id, key)
        except Exception:  # noqa: BLE001 - unresolved evidence is skipped
            continue
        candidates[key] = await asyncio.to_thread(build_snapshot_candidate, resolved)

    plan = {
        "seed_marker": marker,
        "title": node["title"],
        "summary": node["summary"],
        "evidence_keys": [k for k in node["evidence_keys"] if k in candidates],
    }
    result = await asyncio.to_thread(
        repository.bulk_seed_cluster_events, [plan], candidates
    )
    return {"seeded": True, "marker": marker, **result}
