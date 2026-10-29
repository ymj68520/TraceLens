"""Synchronous pipeline-tail report gate for the initial analysis flow.

The C++ task pipeline calls these endpoints after the knowledge-graph
ingestion gate: POST starts (or attaches to) the task's first-stage
材料自主研判 report tail — evidence-copy extraction, evidence seeding,
admission and generation — and GET reports its progress. A task may only
be marked COMPLETED once this tail reaches a completed state.
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..services import get_service_manager
from ..services.field_security import audit_actor

router = APIRouter()
logger = logging.getLogger(__name__)

GENERATION_TIMEOUT_S = 3600
POLL_INTERVAL_S = 10
# A "running" entry whose generation stopped advancing is a zombie: the
# in-memory record survives, but nothing is executing behind it. Without this
# check the status endpoint reported "running" forever, so the C++ completion
# gate could only fail the task after its own 60-minute timeout, and every
# retry reused the same dead generation (observed on PC.E01).
STALE_RUNNING_S = 900

_TAILS: dict[str, dict] = {}


def _is_stale(entry: dict) -> bool:
    """True when a running entry has not progressed for STALE_RUNNING_S."""
    if entry.get("state") != "running":
        return False
    updated = entry.get("updated_at")
    if not updated:
        return True
    return (time.time() - updated) > STALE_RUNNING_S


def _reset_stale_entry(task_id: str, entry: dict) -> None:
    logger.warning(
        "Pipeline tail for task %s was stale (generation %s idle > %ss); resetting",
        task_id, entry.get("generation_id"), STALE_RUNNING_S,
    )
    entry.update({"state": "idle", "generation_id": None, "report_id": None,
                  "error_code": "stale_generation_reset", "updated_at": time.time()})


class TailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, max_length=256)
    requested_by: str = Field(default="pipeline", min_length=1, max_length=256)


def _state(task_id: str) -> dict:
    return _TAILS.setdefault(task_id, {"state": "idle", "generation_id": None,
                                       "report_id": None, "error_code": None,
                                       "updated_at": None})


async def _wait_generation(task_id: str, generation_id: str) -> dict:
    from pathlib import Path

    from ..services.forensic_report.generation_execution import read_generation_strict

    settings = get_service_manager().settings
    root = Path(settings.report_output_dir)
    if not root.is_absolute():
        from ..config import get_project_root
        root = get_project_root() / root
    deadline = time.monotonic() + GENERATION_TIMEOUT_S
    while time.monotonic() < deadline:
        row = read_generation_strict(root / "reports.db", generation_id)
        if row is not None and row.task_id == task_id:
            if row.status == "completed":
                return {"state": "completed", "generation_id": generation_id,
                        "report_id": row.report_id, "error_code": None}
            if row.status in ("failed", "cancelled"):
                return {"state": "failed", "generation_id": generation_id,
                        "report_id": None, "error_code": row.error_code or "report_failed"}
        # This loop is the only thing proving the tail is alive; refresh the
        # timestamp so the staleness check does not reset a healthy wait.
        entry = _TAILS.get(task_id)
        if entry is not None and entry.get("state") == "running":
            entry["updated_at"] = time.time()
        await asyncio.sleep(POLL_INTERVAL_S)
    return {"state": "failed", "generation_id": generation_id,
            "report_id": None, "error_code": "report_tail_timeout"}


async def _run_tail(task_id: str, requested_by: str) -> None:
    entry = _state(task_id)
    manager = get_service_manager()
    try:
        evidence_service = manager.report_evidence_service
        admission = manager.report_generation_service
        executor = manager.report_generation_executor
        cpp_backend = manager.cpp_backend
        from ..services.forensic_report.auto_report import auto_generate_pipeline_report

        summary = await auto_generate_pipeline_report(
            task_id,
            evidence_service=evidence_service,
            admission=admission,
            executor=executor,
            cpp_backend=cpp_backend,
        )
        # Any skip means "nothing to generate", not "generation in progress":
        # settling as failed would make the C++ completion gate fail a task
        # whose analysis actually succeeded (logical mobile sources have no
        # `files` table, so there is nothing to seed).
        if summary.get("skipped"):
            entry.update({"state": "completed", "report_id": None,
                          "generation_id": None,
                          "error_code": summary.get("skipped"),
                          "updated_at": time.time()})
            return
        generation_id = summary.get("generation_id")
        entry.update({"state": "running", "generation_id": generation_id,
                      "updated_at": time.time()})
        result = await _wait_generation(task_id, generation_id)
        entry.update({**result, "updated_at": time.time()})
        logger.info("Pipeline report tail for task %s settled: %s", task_id, result)
    except Exception as exc:
        logger.exception("Pipeline report tail failed for task %s", task_id)
        entry.update({"state": "failed", "error_code": "report_tail_error",
                      "error_message": str(exc)[:300], "updated_at": time.time()})


@router.post("/pipeline-tail", status_code=202)
async def start_pipeline_tail(payload: TailRequest, request: Request):
    actor = audit_actor(request, payload.requested_by)
    manager = get_service_manager()
    try:
        executor = manager.report_generation_executor
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not manager.settings.report_auto_generate_enabled:
        raise HTTPException(status_code=503, detail="report tail generation is disabled")
    entry = _state(payload.task_id)
    if _is_stale(entry):
        # Reset instead of reporting the dead generation as still running.
        _reset_stale_entry(payload.task_id, entry)
    if entry["state"] == "running":
        return {"task_id": payload.task_id, "state": "running",
                "generation_id": entry["generation_id"]}
    if executor.has_report_version(payload.task_id, analysis_mode="evidence_only"):
        entry.update({"state": "completed", "error_code": None, "report_id": None,
                      "updated_at": time.time()})
        return {"task_id": payload.task_id, "state": "completed"}
    entry.update({"state": "running", "generation_id": None, "report_id": None,
                  "error_code": None, "updated_at": time.time()})
    asyncio.create_task(_run_tail(payload.task_id, actor))
    return {"task_id": payload.task_id, "state": "running"}


@router.get("/pipeline-tail/status")
async def pipeline_tail_status(task_id: str):
    entry = _TAILS.get(task_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="pipeline tail not started for this task")
    if _is_stale(entry):
        _reset_stale_entry(task_id, entry)
    return {"task_id": task_id, **entry}
