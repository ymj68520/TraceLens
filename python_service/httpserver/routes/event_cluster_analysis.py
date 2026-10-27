"""Event-cluster analysis run endpoints (SPEC event-cluster-analysis-redesign §8.1).

Gives a single task the case-flow-independent entry the retired
``POST /api/llm/case-analysis`` used to provide:

- ``POST /event-cluster-analysis/estimate``  dry-run ladder scan (no LLM);
- ``POST /event-cluster-analysis/run``       background full-coverage run;
- ``GET  /event-cluster-analysis/run/{id}``  job progress/statistics;
- ``GET  /event-cluster-analyses``           analysis-record query (truth source).

Job status is persisted in the task events database; in-memory entries only
hold active asyncio tasks and compatibility observations.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Literal
from ..services.case_analysis import cluster_jobs

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..services.investigation_evidence import TIMELINE_MAX_BUCKET_SECONDS

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory job registry (single process; same convention as multi_analysis).
_run_jobs: Dict[str, Dict[str, Any]] = {}
_run_tasks: Dict[str, asyncio.Task] = {}


class EstimateRequest(BaseModel):
    task_id: str = Field(..., description="Task ID")


class RunRequest(BaseModel):
    trigger_source: Literal["task_run", "pipeline"] = "task_run"
    task_id: str = Field(..., description="Task ID")
    bucket_seconds: Optional[int] = Field(
        None, description="Force the window; omit for budget-driven adaptive selection"
    )


async def _resolve_events_db(service_manager, task_id: str) -> str:
    task_info = await service_manager.cpp_backend.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    events_db = task_info.get("output_events_db") or ""
    from pathlib import Path
    if not events_db or not Path(events_db).is_file():
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
            detail="当前配置已关闭事件簇智能分析",
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

    job,created=await asyncio.to_thread(cluster_jobs.create,events_db,request.task_id)
    job_id=job['job_id'];_run_jobs[job_id]=job

    async def _worker():
        active=asyncio.current_task()
        async def heartbeat():
            while True:
                await asyncio.sleep(10)
                state=await asyncio.to_thread(cluster_jobs.read,events_db,job_id)
                if state and state['status']=='cancel_requested':active.cancel();return
                await asyncio.to_thread(cluster_jobs.update,events_db,job_id)
        beat=asyncio.create_task(heartbeat())
        try:
            options={"case_description":case_description,"bucket_seconds":request.bucket_seconds}
            if request.trigger_source=="pipeline":options.update(trigger_source="pipeline",ingest=False)
            summary = await analyzer.run_analysis(request.task_id,events_db,**options)
            partial=bool(summary.get('failed') or summary.get('skipped_over_budget'))
            value=await asyncio.to_thread(cluster_jobs.update,events_db,job_id,
                status='partial' if partial else 'completed',
                detail=f"事件分析已落库：{summary['analyzed']} 个簇处理，{summary['skipped_fresh']} 个已最新，{summary['failed']} 个失败",
                summary={k:v for k,v in summary.items() if k!='results'},
                failures=[{'event_type':r.get('event_type'),'time_window':r.get('time_window'),'error':r.get('error')} for r in summary['results'] if not r.get('success')],
                finished_at=datetime.now().isoformat())
            _run_jobs[job_id]=value
        except asyncio.CancelledError:
            _run_jobs[job_id]=await asyncio.to_thread(cluster_jobs.update,events_db,job_id,
                status='interrupted',detail='事件分析已中断；已完成的规范记录保留',finished_at=datetime.now().isoformat())
        except Exception as exc:
            logger.error('Cluster analysis failed: %s',exc,exc_info=True)
            _run_jobs[job_id]=await asyncio.to_thread(cluster_jobs.update,events_db,job_id,
                status='failed',detail='事件簇分析失败，已完成结果保留',error=str(exc),finished_at=datetime.now().isoformat())
        finally:
            beat.cancel()
            try:
                outcomes = await asyncio.gather(beat, return_exceptions=True)
                if isinstance(outcomes[0], Exception):
                    logger.warning("事件分析心跳任务异常：%s", outcomes[0])
            finally:
                _run_tasks.pop(job_id,None)

    if created:_run_tasks[job_id]=asyncio.create_task(_worker())
    return {'success':True,'job_id':job_id,'task_id':request.task_id,'bucket_seconds':request.bucket_seconds,
            'message':'事件分析已启动' if created else '复用正在执行的事件分析','timestamp':datetime.now().isoformat()}


@router.get("/event-cluster-analysis/run/{job_id}")
async def get_event_cluster_run_status(job_id: str):
    from ..services import get_service_manager
    try:task_id=cluster_jobs.task_from_job(job_id)
    except ValueError:raise HTTPException(status_code=404,detail='事件分析运行不存在')
    database=await _resolve_events_db(get_service_manager(),task_id)
    job=await asyncio.to_thread(cluster_jobs.read,database,job_id)
    if not job:raise HTTPException(status_code=404,detail='事件分析运行不存在')
    return job


@router.post("/event-cluster-analysis/run/{job_id}/cancel")
async def cancel_event_cluster_run(job_id: str):
    job=await get_event_cluster_run_status(job_id)
    if job['status']=='running':
        from ..services import get_service_manager
        database=await _resolve_events_db(get_service_manager(),job['task_id'])
        await asyncio.to_thread(cluster_jobs.request_cancel,database,job_id)
        worker=_run_tasks.get(job_id)
        if worker:worker.cancel()
    return {'success':True,'job_id':job_id,'message':'已请求停止事件分析'}


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
        # 旧任务（MVP §4.1 跳过 Round C）可能从未建过记录表——按空列表处理，
        # 不能让缺表 500 打断研判中心/工作台的页面加载。
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_cluster_analyses'"
        ).fetchone()
        if not table_exists:
            return {
                "task_id": task_id,
                "records": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
            }
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
        from ..services.case_analysis.cluster_analyzer import related_file_summaries_batch

        task_info = await service_manager.cpp_backend.get_task(task_id)
        files_db = (task_info or {}).get("output_files_db") or ""
        # Batched attach: one connection per db for the whole page (the
        # per-record variant opens one files-db connection per member file,
        # which is a >40s N+1 on a 200-record page).
        for record, item_summaries in zip(
            records, related_file_summaries_batch(events_db, files_db, records)
        ):
            record["related_file_summaries"] = item_summaries

    return {
        "task_id": task_id,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "records": records,
    }


@router.get('/windows-activity/{task_id}')
async def windows_activity_coverage(task_id: str):
    from ..services import get_service_manager
    from ..services.windows_activity_reader import connect
    from contextlib import closing
    import json
    database=await _resolve_events_db(get_service_manager(),task_id)
    with closing(connect(database)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='windows_activity_current'").fetchone():return {'task_id':task_id,'coverage':None}
        row=conn.execute('SELECT coverage_json FROM windows_activity_import_runs WHERE task_id=? ORDER BY id DESC LIMIT 1',(task_id,)).fetchone()
        coverage=json.loads(row[0]) if row else None
        if coverage:coverage.pop('parser_outcomes',None)
    return {'task_id':task_id,'coverage':coverage}
