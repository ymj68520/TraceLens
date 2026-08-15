"""Public Investigation Snapshot + Secondary Analysis routes (Phase C3/C4b-2).

The only client-controlled fields are task_id and evidence_key. No client path
or database path is accepted or exposed.
"""

from __future__ import annotations

from typing import Optional

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
    AnalysisClaimsResponse,
    AnalysisReviewConflictError,
    EvidenceSnapshot,
    EvidenceSummary,
    EventEvidenceLink,
    EventRefresh,
    InvestigationCaptureService,
    InvestigationEvent,
    InvestigationEventConflictError,
    InvestigationEventService,
    InvestigationEventVersion,
    InvestigationGraphResponse,
    InvestigationGraphService,
    InvestigationReadService,
    InvestigationReviewService,
    SecondaryAnalysis,
    SecondaryAnalysisExecutor,
    SecondaryAnalysisStatus,
    AnalysisReviewDecision,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Snapshot routes (C3)
# ---------------------------------------------------------------------------

class CaptureEvidenceRequest(BaseModel):
    """Strict public boundary: exactly task_id + evidence_key."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)


def get_investigation_service() -> InvestigationCaptureService:
    """Resolve the ready capture service through ServiceManager."""
    try:
        return get_service_manager().investigation_service
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="investigation service is unavailable",
        ) from exc


@router.post("/snapshots", response_model=EvidenceSnapshot, status_code=200)
async def capture_snapshot(
    request: CaptureEvidenceRequest,
    service: InvestigationCaptureService = Depends(get_investigation_service),
) -> EvidenceSnapshot:
    try:
        return await service.capture(request.task_id, request.evidence_key)
    except InvalidEvidenceKeyError as exc:
        raise HTTPException(status_code=400, detail="invalid evidence key") from exc
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="evidence not found") from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


# ---------------------------------------------------------------------------
# Secondary Analysis routes (C4b-2)
# ---------------------------------------------------------------------------

class CreateAnalysisRequest(BaseModel):
    """Public boundary for Secondary Analysis with optional analyst context (C4c).

    analyst_note and case_context are plain text (CCTX1: Note != Evidence).
    related_evidence is a list of evidence_keys that will be canonicalized,
    deduplicated, and resolved + captured in the SAME task before analysis.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)
    analyst_note: Optional[str] = Field(default=None, max_length=20_000)
    case_context: Optional[str] = Field(default=None, max_length=20_000)
    related_evidence: list[str] = Field(
        default_factory=list, max_length=20,
        description="Canonical evidence_keys of related evidence (max 20)",
    )


def get_secondary_analysis_executor() -> SecondaryAnalysisExecutor:
    """Resolve the ready executor through ServiceManager."""
    try:
        return get_service_manager().secondary_analysis_executor
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="secondary analysis executor is unavailable",
        ) from exc


@router.post("/analyses", response_model=SecondaryAnalysis, status_code=202)
async def create_analysis(
    request: CreateAnalysisRequest,
    executor: SecondaryAnalysisExecutor = Depends(get_secondary_analysis_executor),
) -> SecondaryAnalysis:
    """Create a queued Secondary Analysis and start background LLM execution."""
    try:
        return await executor.submit(
            request.task_id,
            request.evidence_key,
            analyst_note=request.analyst_note,
            case_context=request.case_context,
            related_evidence=tuple(request.related_evidence),
        )
    except InvalidEvidenceKeyError as exc:
        raise HTTPException(status_code=400, detail="invalid evidence key") from exc
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="evidence not found") from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


class ReviewAnalysisRequest(BaseModel):
    """Strict analyst decision boundary for one analysis version."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    decision: AnalysisReviewDecision
    reviewer: str = Field(min_length=1, max_length=256)
    reason: Optional[str] = Field(default=None, max_length=4000)


def get_investigation_review_service() -> InvestigationReviewService:
    """Resolve the ready analyst review service through ServiceManager."""
    try:
        return get_service_manager().investigation_review_service
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="investigation review service is unavailable",
        ) from exc


@router.post(
    "/analyses/{analysis_id}/review",
    response_model=SecondaryAnalysis,
    status_code=200,
)
async def review_analysis(
    analysis_id: str,
    request: ReviewAnalysisRequest,
    service: InvestigationReviewService = Depends(get_investigation_review_service),
) -> SecondaryAnalysis:
    """Record one explicit analyst decision for an exact analysis version."""
    try:
        return await service.review(
            request.task_id,
            analysis_id,
            decision=request.decision,
            reviewer=request.reviewer,
            reason=request.reason,
        )
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="analysis not found") from exc
    except AnalysisReviewConflictError as exc:
        raise HTTPException(status_code=409, detail="analysis review conflict") from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


@router.get("/analyses/{analysis_id}", response_model=SecondaryAnalysis)
async def get_analysis(
    analysis_id: str,
    task_id: str = Query(..., min_length=1),
    executor: SecondaryAnalysisExecutor = Depends(get_secondary_analysis_executor),
) -> SecondaryAnalysis:
    """Query a single analysis from SQLite (DB is source of truth)."""
    analysis = await executor.get_analysis(task_id, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return analysis


@router.get("/analyses", response_model=list[SecondaryAnalysis])
async def list_analyses(
    task_id: str = Query(..., min_length=1),
    evidence_key: str = Query(..., min_length=1),
    status: Optional[str] = Query(None),
    executor: SecondaryAnalysisExecutor = Depends(get_secondary_analysis_executor),
) -> list[SecondaryAnalysis]:
    """List analyses for an evidence. Uses parse_evidence_key (no resolve).

    Historical analyses remain queryable even if the original Evidence later
    disappears from the source DB. Backslash/forward-slash variants canonicalize
    to the same key.
    """
    try:
        parsed = parse_evidence_key(evidence_key)
    except InvalidEvidenceKeyError as exc:
        raise HTTPException(status_code=400, detail="invalid evidence key") from exc

    analyses = await executor.list_analyses(task_id, parsed.canonical_key)
    if status is not None:
        try:
            status_enum = SecondaryAnalysisStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid status filter") from exc
        analyses = [a for a in analyses if a.status == status_enum]
    return analyses


# ---------------------------------------------------------------------------
# Investigation Event routes (C7a)
# ---------------------------------------------------------------------------

class CreateInvestigationEventRequest(BaseModel):
    """Strict boundary for creating one Investigation Event with its v1 narrative."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=500)
    summary: Optional[str] = Field(default=None, max_length=20_000)
    created_by: str = Field(min_length=1, max_length=256)


class LinkEventEvidenceRequest(BaseModel):
    """Strict boundary for one explicit Event→Evidence relation."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)
    linked_by: str = Field(min_length=1, max_length=256)


class CreateEventRefreshRequest(BaseModel):
    """Strict boundary for explicit refresh admission (C7c-1)."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    requested_by: str = Field(min_length=1, max_length=256)


def get_investigation_event_service() -> InvestigationEventService:
    """Resolve the ready investigation event service through ServiceManager."""
    try:
        return get_service_manager().investigation_event_service
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="investigation event service is unavailable",
        ) from exc


@router.post("/events", response_model=InvestigationEvent, status_code=201)
async def create_investigation_event(
    request: CreateInvestigationEventRequest,
    service: InvestigationEventService = Depends(get_investigation_event_service),
) -> InvestigationEvent:
    """Create one Investigation Event with its immutable v1 narrative version."""
    try:
        return await service.create_event(
            request.task_id,
            title=request.title,
            summary=request.summary,
            created_by=request.created_by,
        )
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


@router.get("/events", response_model=list[InvestigationEvent])
async def list_investigation_events(
    task_id: str = Query(..., min_length=1),
    needs_refresh: Optional[bool] = Query(None),
    service: InvestigationEventService = Depends(get_investigation_event_service),
) -> list[InvestigationEvent]:
    """List events. Reading never creates investigation.db ([] if absent)."""
    try:
        return await service.list_events(task_id, needs_refresh=needs_refresh)
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


@router.get("/events/{event_id}", response_model=InvestigationEvent)
async def get_investigation_event(
    event_id: str,
    task_id: str = Query(..., min_length=1),
    service: InvestigationEventService = Depends(get_investigation_event_service),
) -> InvestigationEvent:
    """Return one event with its current (MAX version) narrative."""
    try:
        return await service.get_event(task_id, event_id)
    except EvidenceNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="investigation event not found"
        ) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


@router.get(
    "/events/{event_id}/versions", response_model=list[InvestigationEventVersion]
)
async def list_investigation_event_versions(
    event_id: str,
    task_id: str = Query(..., min_length=1),
    service: InvestigationEventService = Depends(get_investigation_event_service),
) -> list[InvestigationEventVersion]:
    """Return the immutable narrative version history of one event."""
    try:
        return await service.list_event_versions(task_id, event_id)
    except EvidenceNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="investigation event not found"
        ) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


@router.post(
    "/events/{event_id}/evidence", response_model=EventEvidenceLink, status_code=200
)
async def link_investigation_event_evidence(
    event_id: str,
    request: LinkEventEvidenceRequest,
    service: InvestigationEventService = Depends(get_investigation_event_service),
) -> EventEvidenceLink:
    """Link canonical evidence to an event (resolve + capture, INSERT-only)."""
    try:
        return await service.link_event_evidence(
            request.task_id,
            event_id,
            request.evidence_key,
            linked_by=request.linked_by,
        )
    except InvalidEvidenceKeyError as exc:
        raise HTTPException(status_code=400, detail="invalid evidence key") from exc
    except EvidenceNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="investigation event or evidence not found"
        ) from exc
    except InvestigationEventConflictError as exc:
        raise HTTPException(
            status_code=409, detail="event evidence link already exists"
        ) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


@router.get(
    "/events/{event_id}/evidence", response_model=list[EventEvidenceLink]
)
async def list_investigation_event_evidence(
    event_id: str,
    task_id: str = Query(..., min_length=1),
    service: InvestigationEventService = Depends(get_investigation_event_service),
) -> list[EventEvidenceLink]:
    """List the explicit Event→Evidence relations of one event."""
    try:
        return await service.list_event_evidence(task_id, event_id)
    except EvidenceNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="investigation event not found"
        ) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


def get_event_refresh_executor():
    try:
        return get_service_manager().event_refresh_executor
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="event refresh executor is unavailable",
        ) from exc


@router.post(
    "/events/{event_id}/refresh", response_model=EventRefresh, status_code=201
)
async def create_event_refresh(
    event_id: str,
    request: CreateEventRefreshRequest,
    executor = Depends(get_event_refresh_executor),
) -> EventRefresh:
    """Admit and schedule one explicit refresh without waiting for the LLM."""
    try:
        return await executor.submit(
            request.task_id, event_id, requested_by=request.requested_by
        )
    except EvidenceNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="investigation event not found"
        ) from exc
    except InvestigationEventConflictError as exc:
        raise HTTPException(
            status_code=409, detail="event refresh already in progress"
        ) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


@router.get(
    "/events/{event_id}/refreshes", response_model=list[EventRefresh]
)
async def list_event_refreshes(
    event_id: str,
    task_id: str = Query(..., min_length=1),
    service: InvestigationEventService = Depends(get_investigation_event_service),
) -> list[EventRefresh]:
    """Return admitted refresh history for one event."""
    try:
        return await service.list_event_refreshes(task_id, event_id)
    except EvidenceNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="investigation event not found"
        ) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


# ---------------------------------------------------------------------------
# Graph routes (C8b)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Workbench read routes (C9a) -- strictly read-only projections
# ---------------------------------------------------------------------------

def get_investigation_read_service() -> InvestigationReadService:
    """Resolve the read-only Workbench data service via ServiceManager."""
    try:
        return get_service_manager().investigation_read_service
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="investigation read service is unavailable",
        ) from exc


@router.get("/evidence", response_model=list[EvidenceSummary])
async def list_investigation_evidence(
    task_id: str = Query(..., min_length=1),
    service: InvestigationReadService = Depends(get_investigation_read_service),
) -> list[EvidenceSummary]:
    """List every captured evidence of the task with its C8b selection state.

    A task without an investigation.db yet simply has no findings ([]); the
    GET never captures or migrates anything.
    """
    try:
        return await service.list_evidence(task_id)
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


@router.get(
    "/evidence/snapshot",
    response_model=EvidenceSnapshot,
    responses={404: {"description": "task/evidence not found"}},
)
async def get_investigation_evidence_snapshot(
    task_id: str = Query(..., min_length=1),
    evidence_key: str = Query(..., min_length=1),
    service: InvestigationReadService = Depends(get_investigation_read_service),
) -> EvidenceSnapshot:
    """Return the captured Snapshot of one evidence (the Initial Analysis source).

    Read-only: never captures on demand, never re-reads files.db.  The
    Workbench's Initial Analysis comes exclusively from this frozen payload.
    """
    try:
        parsed = parse_evidence_key(evidence_key)
    except InvalidEvidenceKeyError as exc:
        raise HTTPException(status_code=400, detail="invalid evidence key") from exc
    try:
        snapshot = await service.get_snapshot(task_id, parsed.canonical_key)
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc
    if snapshot is None:
        raise HTTPException(status_code=404, detail="evidence snapshot not found")
    return snapshot


@router.get(
    "/analyses/{analysis_id}/claims",
    response_model=AnalysisClaimsResponse,
    responses={404: {"description": "analysis not found"}},
)
async def list_investigation_analysis_claims(
    analysis_id: str,
    task_id: str = Query(..., min_length=1),
    service: InvestigationReadService = Depends(get_investigation_read_service),
) -> AnalysisClaimsResponse:
    """Return the exact persisted claims of one exact analysis version.

    Claims are immutable rows -- never re-derived, never a current/effective
    claim projection, and no fallback to any other analysis version.
    """
    try:
        claims = await service.list_analysis_claims(task_id, analysis_id)
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc
    if claims is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return AnalysisClaimsResponse(
        task_id=task_id, analysis_id=analysis_id, claims=tuple(claims)
    )


def get_investigation_graph_service() -> InvestigationGraphService:
    """Resolve the read-only graph composition service via ServiceManager."""
    try:
        return get_service_manager().investigation_graph_service
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="investigation graph service is unavailable",
        ) from exc


@router.get("/graph", response_model=InvestigationGraphResponse)
async def get_investigation_graph(
    task_id: str = Query(..., min_length=1),
    max_base_nodes: int = Query(default=200, ge=1, le=1000),
    service: InvestigationGraphService = Depends(get_investigation_graph_service),
) -> InvestigationGraphResponse:
    """Compose the Base KG with the derived Investigation Overlay (read-only).

    Base KG failure degrades gracefully (``base_graph_available=false`` +
    warning); Investigation store corruption fails closed (503) instead of
    masquerading as an empty overlay.  ``max_base_nodes`` bounds only the
    Base KG read, never the overlay.
    """
    try:
        return await service.get_graph(task_id, max_base_nodes=max_base_nodes)
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except EvidenceStoreError as exc:
        raise HTTPException(
            status_code=503, detail="investigation store is unavailable"
        ) from exc
