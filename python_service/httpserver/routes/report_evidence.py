"""Report Evidence routes (Phase R1) -- explicit analyst Report bindings.

Identity is exactly ``task_id`` + canonical ``evidence_key`` of a captured
Investigation Evidence.  ``analysis_id`` is an optional FROZEN binding to one
accepted Secondary Analysis of the SAME evidence (R1 §7 triple check on the
server); the report never resolves "latest accepted" implicitly.  Evidence
identity travels in the request body/query (never the URL path -- canonical
keys contain slashes), and no client path or database path is accepted.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ..services import get_service_manager
from ..services.evidence import (
    EvidenceNotFoundError,
    EvidenceStoreError,
    InvalidEvidenceKeyError,
    parse_evidence_key,
)
from ..services.investigation import (
    AnalysisBindingConflictError,
    ReportEvidenceConflictError,
    ReportEvidenceItem,
    ReportEvidenceService,
)

router = APIRouter()


def get_report_evidence_service() -> ReportEvidenceService:
    """Resolve the ready Report Evidence service through ServiceManager."""
    try:
        return get_service_manager().report_evidence_service
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="report evidence service is unavailable",
        ) from exc


def _canonical_key(evidence_key: str) -> str:
    try:
        return parse_evidence_key(evidence_key).canonical_key
    except InvalidEvidenceKeyError as exc:
        raise HTTPException(status_code=400, detail="invalid evidence key") from exc


@router.get("/evidence", response_model=list[ReportEvidenceItem])
async def list_report_evidence(
    task_id: str = Query(..., min_length=1),
    service: ReportEvidenceService = Depends(get_report_evidence_service),
) -> list[ReportEvidenceItem]:
    """List every Report Evidence row of the task (exact frozen bindings).

    A task without an investigation.db yet simply has no report evidence
    ([]); the GET never captures or migrates anything.
    """
    try:
        return await service.list(task_id)
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="report evidence store unavailable") from exc


class AddReportEvidenceRequest(BaseModel):
    """Strict boundary for adding one captured evidence to the report.

    ``report_status`` is main/appendix at add time (excluded is reached via
    an explicit update -- it records considered-then-excluded, R1 §9).
    ``analysis_id`` is the optional explicit accepted-analysis binding.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)
    report_status: Literal["main", "appendix"]
    analysis_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    added_by: str = Field(min_length=1, max_length=256)


@router.post("/evidence", response_model=ReportEvidenceItem, status_code=200)
async def add_report_evidence(
    request: AddReportEvidenceRequest,
    service: ReportEvidenceService = Depends(get_report_evidence_service),
) -> ReportEvidenceItem:
    """Add one captured Evidence to the report with an optional frozen
    accepted-analysis binding (Original Evidence only when omitted)."""
    evidence_key = _canonical_key(request.evidence_key)
    try:
        return await service.add(
            request.task_id,
            evidence_key,
            report_status=request.report_status,
            analysis_id=request.analysis_id,
            added_by=request.added_by,
        )
    except EvidenceNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="task or evidence not found",
        ) from exc
    except AnalysisBindingConflictError as exc:
        raise HTTPException(
            status_code=409, detail="analysis binding conflict"
        ) from exc
    except ReportEvidenceConflictError as exc:
        raise HTTPException(
            status_code=409, detail="report evidence already exists"
        ) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="report evidence store unavailable") from exc


class UpdateReportEvidenceRequest(BaseModel):
    """Strict boundary for explicit report updates.

    ``report_status`` (excluded/main/appendix) and ``analysis_id`` are only
    applied when supplied; an omitted ``analysis_id`` keeps the current
    frozen binding (R1 defines no unbind).  At least one field is required.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)
    report_status: Optional[Literal["excluded", "main", "appendix"]] = None
    analysis_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    updated_by: str = Field(min_length=1, max_length=256)


@router.put("/evidence", response_model=ReportEvidenceItem, status_code=200)
async def update_report_evidence(
    request: UpdateReportEvidenceRequest,
    service: ReportEvidenceService = Depends(get_report_evidence_service),
) -> ReportEvidenceItem:
    """Explicitly set the report status and/or (re)bind the accepted analysis.

    The binding never follows newer accepted versions automatically; rebinding
    is always this explicit analyst action (R1 §3/§11).
    """
    if request.report_status is None and request.analysis_id is None:
        raise HTTPException(
            status_code=422,
            detail="report_status or analysis_id is required",
        )
    evidence_key = _canonical_key(request.evidence_key)
    try:
        return await service.update(
            request.task_id,
            evidence_key,
            report_status=request.report_status,
            analysis_id=request.analysis_id,
            bind_analysis=request.analysis_id is not None,
            updated_by=request.updated_by,
        )
    except EvidenceNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="task or report evidence not found",
        ) from exc
    except AnalysisBindingConflictError as exc:
        raise HTTPException(
            status_code=409, detail="analysis binding conflict"
        ) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="report evidence store unavailable") from exc
