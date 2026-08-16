"""Public report generation API (Phase R2c).

Exact-ID admission and polling only. The request may carry nothing but
``task_id`` and ``requested_by`` -- the server builds the whole frozen
input from R1 bindings; clients can never submit evidence lists, analysis
IDs, citations, prompt versions, models, or envelopes. Polling is by exact
``generation_id``; there is no "latest generation" fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ..config import get_project_root, get_settings
from ..services.evidence.exceptions import (
    EvidenceNotFoundError,
    EvidenceStoreError,
)
from ..services.forensic_report.generation import (
    ReportGenerationAdmissionService,
    ReportGenerationInputError,
)
from ..services.forensic_report.generation_execution import (
    ReportGenerationExecutor,
    read_generation_strict,
)
from ..services.forensic_report.generation_writer import GenerationReportWriter
from ..services.service_manager import ServiceManager, get_service_manager

router = APIRouter()


def _get_service_manager() -> ServiceManager:
    return get_service_manager()


def get_report_generation_admission_service(
    manager: ServiceManager = Depends(_get_service_manager),
) -> ReportGenerationAdmissionService:
    try:
        return manager.report_generation_service
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def get_report_generation_executor(
    manager: ServiceManager = Depends(_get_service_manager),
) -> ReportGenerationExecutor:
    try:
        return manager.report_generation_executor
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class GenerateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=256)
    requested_by: str = Field(min_length=1, max_length=256)


class GenerationStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    generation_id: str
    task_id: str
    status: str
    requested_by: str
    prompt_version: str
    input_schema_version: int
    input_hash: str
    report_id: Optional[str] = None
    produced_version: Optional[int] = None
    model: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    failed_at: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    report: Optional[dict] = None


def _report_root() -> Path:
    root = Path(get_settings().report_output_dir)
    if not root.is_absolute():
        root = get_project_root() / root
    return root


@router.post("/generate", status_code=202, response_model=GenerationStatusResponse)
async def generate_report(
    request: GenerateReportRequest,
    service: ReportGenerationAdmissionService = Depends(
        get_report_generation_admission_service
    ),
    executor: ReportGenerationExecutor = Depends(get_report_generation_executor),
):
    """Admit one frozen generation from the task's Report Evidence (202)."""
    try:
        row = await service.admit(
            request.task_id, requested_by=request.requested_by
        )
    except ReportGenerationInputError as exc:
        if exc.code == "no_report_evidence":
            raise HTTPException(
                status_code=409, detail="task has no report evidence"
            ) from exc
        raise HTTPException(
            status_code=409, detail="report evidence binding is invalid"
        ) from exc
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except EvidenceStoreError as exc:
        raise HTTPException(
            status_code=503, detail="report generation store is unavailable"
        ) from exc
    await executor.submit(row.generation_id)
    refreshed = read_generation_strict(_report_root() / "reports.db", row.generation_id)
    current = refreshed or row
    return _status_response(current, include_report=False)


@router.get(
    "/generations/{generation_id}", response_model=GenerationStatusResponse
)
async def get_report_generation(
    generation_id: str,
    task_id: str = Query(min_length=1, max_length=256),
    manager: ServiceManager = Depends(_get_service_manager),
):
    """Exact-ID generation poll (strict read; task scope enforced)."""
    del manager  # dependency only pins lifecycle; the read itself is strict
    row = read_generation_strict(_report_root() / "reports.db", generation_id)
    if row is None or row.task_id != task_id:
        raise HTTPException(
            status_code=404, detail="report generation not found"
        )
    return _status_response(row, include_report=row.status == "completed")


def _status_response(row, *, include_report: bool) -> GenerationStatusResponse:
    report = None
    if include_report and row.report_id is not None:
        try:
            report = GenerationReportWriter(_report_root()).read_manifest(
                row.task_id, row.report_id
            )
        except (OSError, ValueError, KeyError):
            raise HTTPException(
                status_code=503,
                detail="report generation record is unavailable",
            )
    return GenerationStatusResponse(
        generation_id=row.generation_id,
        task_id=row.task_id,
        status=row.status,
        requested_by=row.requested_by,
        prompt_version=row.prompt_version,
        input_schema_version=row.input_schema_version,
        input_hash=row.input_hash,
        report_id=row.report_id,
        produced_version=row.produced_version,
        model=row.model,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        failed_at=row.failed_at,
        error_code=row.error_code,
        error_message=row.error_message,
        report=report,
    )
