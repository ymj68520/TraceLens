"""Event-cluster analysis run endpoints (SPEC event-cluster-analysis-redesign §8.1).

Gives a single task the case-flow-independent entry the retired
``POST /api/llm/case-analysis`` used to provide:

- ``POST /event-cluster-analysis/estimate``  dry-run ladder scan (no LLM);
- ``POST /event-cluster-analysis/run``       background full-coverage run;
- ``GET  /event-cluster-analysis/run/{id}``  job progress/statistics;
- ``GET  /event-cluster-analyses``           analysis-record query (truth source).

Job registry follows the in-memory pattern of multi_analysis.py: single
process, best-effort status.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..services.investigation_evidence import TIMELINE_MAX_BUCKET_SECONDS

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory job registry (single process; same convention as multi_analysis).
_run_jobs: Dict[str, Dict[str, Any]] = {}


class EstimateRequest(BaseModel):
    task_id: str = Field(..., description="Task ID")


class RunRequest(BaseModel):
    task_id: str = Field(..., description="Task ID")
    bucket_seconds: Optional[int] = Field(
        None, description="Force the window; omit for budget-driven adaptive selection"
    )


async def _resolve_events_db(service_manager, task_id: str) -> str:
    task_info = await service_manager.cpp_backend.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    events_db = task_info.get("output_events_db") or ""
    if not events_db:
        raise HTTPException(status_code=400, detail="No events database for this task")
    return events_db


@router.post("/event-cluster-analysis/estimate")
async def estimate_event_cluster_buckets(
    request: EstimateRequest,
    settings: Settings = Depends(get_settings),
):
    """Pure-SQL ladder scan: cluster counts per candidate window + recommendation."""
    from ..services import get_service_manager
    from ..services.case_analysis.adaptive import choose_bucket, estimate_bucket_ladder

    service_manager = get_service_manager()
    events_db = await _resolve_events_db(service_manager, request.task_id)

    scan = estimate_bucket_ladder(events_db, include_analyzed=True)
    budget = settings.llm_max_event_clusters
    choice = choose_bucket(scan["estimates"], budget)
    return {
        "task_id": request.task_id,
        "budget": budget,
        "bucket_epoch_offset": scan["bucket_epoch_offset"],
        "estimates": scan["estimates"],
        "recommended_bucket_seconds": choice["recommended_bucket_seconds"],
        "warning": choice["warning"],
        "timestamp": datetime.now().isoformat(),
    }


@router.post("/event-cluster-analysis/run")
async def run_event_cluster_analysis(
    request: RunRequest,
    settings: Settings = Depends(get_settings),
):
    """Start a background full-coverage cluster analysis for one task.

    Disabled in the phase-1 acceptance MVP (mvp-phase1-acceptance SPEC §4.1).
    """
    if not settings.event_llm_analysis_enabled:
        raise HTTPException(
            status_code=503,
            detail="Event LLM analysis is disabled in this build (MVP)",
        )
    if request.bucket_seconds is not None and not (
        1 <= request.bucket_seconds <= TIMELINE_MAX_BUCKET_SECONDS
    ):
        raise HTTPException(
            status_code=422,
            detail=f"bucket_seconds out of range (1..{TIMELINE_MAX_BUCKET_SECONDS})",
        )

    from ..services import get_service_manager
    from ..services.case_analysis.cluster_analyzer import ClusterAnalyzer

    service_manager = get_service_manager()
    events_db = await _resolve_events_db(service_manager, request.task_id)
    task_info = await service_manager.cpp_backend.get_task(request.task_id)
    case_description = (task_info or {}).get("case_description") or ""

    analyzer = ClusterAnalyzer(
        settings,
        service_manager.llm_service,
        getattr(service_manager, "graphiti_service", None),
    )

    job_id = str(uuid.uuid4())
    _run_jobs[job_id] = {
        "job_id": job_id,
        "task_id": request.task_id,
        "status": "running",
        "detail": "正在选择聚簇窗口并启动分析...",
        "summary": None,
        "error": None,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
    }

    async def _worker():
        try:
            summary = await analyzer.run_analysis(
                request.task_id,
                events_db,
                case_description=case_description,
                bucket_seconds=request.bucket_seconds,
            )
            _run_jobs[job_id].update({
                "status": "completed",
                "detail": (
                    f"分析完成：{summary['analyzed']} 个簇新分析，"
                    f"{summary['skipped_fresh']} 个已最新，{summary['failed']} 个失败"
                ),
                "summary": {k: v for k, v in summary.items() if k != "results"},
                "failures": [
                    {"event_type": r.get("event_type"), "time_window": r.get("time_window"),
                     "error": r.get("error")}
                    for r in summary["results"] if not r.get("success")
                ],
                "finished_at": datetime.now().isoformat(),
            })
        except Exception as exc:  # job must always terminate with a status
            logger.error(f"Cluster analysis run {job_id} failed: {exc}", exc_info=True)
            _run_jobs[job_id].update({
                "status": "failed",
                "detail": "任务级事件簇分析失败",
                "error": str(exc),
                "finished_at": datetime.now().isoformat(),
            })

    asyncio.create_task(_worker())
    return {
        "success": True,
        "job_id": job_id,
        "task_id": request.task_id,
        "bucket_seconds": request.bucket_seconds,
        "message": "Cluster analysis run started",
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/event-cluster-analysis/run/{job_id}")
async def get_event_cluster_run_status(job_id: str):
    job = _run_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Run job not found")
    return dict(job)


@router.get("/event-cluster-analyses")
async def list_event_cluster_analyses(
    task_id: str = Query(..., description="Task ID"),
    bucket_seconds: Optional[int] = Query(None, ge=1),
    bucket_index: Optional[int] = Query(None),
    event_type: Optional[str] = Query(None),
    parent_directory: Optional[str] = Query(None),
    latest_only: bool = Query(True, description="Only the newest version per coordinate"),
    include_file_summaries: bool = Query(
        False, description="C3-v0: attach related_file_summaries per record"
    ),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Query the append-only analysis records (Phase D page data source)."""
    import sqlite3

    from ..services import get_service_manager

    service_manager = get_service_manager()
    events_db = await _resolve_events_db(service_manager, task_id)

    where = ["task_id = ?"]
    params: list = [task_id]
    if bucket_seconds is not None:
        where.append("bucket_seconds = ?")
        params.append(bucket_seconds)
    if bucket_index is not None:
        where.append("bucket_index = ?")
        params.append(bucket_index)
    if event_type:
        where.append("event_type = ?")
        params.append(event_type)
    if parent_directory:
        where.append("parent_directory = ?")
        params.append(parent_directory)
    if latest_only:
        where.append(
            "id IN (SELECT MAX(id) FROM event_cluster_analyses "
            "WHERE task_id = ? GROUP BY bucket_epoch_offset, bucket_seconds, "
            "bucket_index, event_type, parent_directory)"
        )
        params.append(task_id)
    where_sql = " AND ".join(where)

    with sqlite3.connect(events_db, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            f"SELECT COUNT(*) FROM event_cluster_analyses WHERE {where_sql}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM event_cluster_analyses WHERE {where_sql} "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()

    records = [dict(row) for row in rows]
    if include_file_summaries:
        from ..services.case_analysis.cluster_analyzer import related_file_summaries

        task_info = await service_manager.cpp_backend.get_task(task_id)
        files_db = (task_info or {}).get("output_files_db") or ""
        for record in records:
            record["related_file_summaries"] = related_file_summaries(
                events_db, files_db,
                bucket_epoch_offset=record.get("bucket_epoch_offset") or 0,
                bucket_seconds=record.get("bucket_seconds") or 60,
                bucket_index=record.get("bucket_index") or 0,
                event_type=record.get("event_type") or "",
                parent_directory=record.get("parent_directory") or "",
            )

    return {
        "task_id": task_id,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "records": records,
    }
