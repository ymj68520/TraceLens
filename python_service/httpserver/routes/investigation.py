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
    AgentAnalystReviewService,
    EvidenceProvenanceError,
    FactPromotionBlockedError,
    ReviewCandidateProjection,
    ReviewConflictError,
    ReviewDecisionOutcome,
    ReviewDecisionRequest,
    ReviewHistoryItem,
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


# ---------------------------------------------------------------------------
# Agent v0 Execution & State routes (RCA-2A.16)
# ---------------------------------------------------------------------------

import asyncio

_agent_task_locks: dict[str, asyncio.Lock] = {}
_agent_task_running: set[str] = set()


class AgentCycleRequest(BaseModel):
    """Strict public boundary for triggering one bounded Agent v0 cycle."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    investigation_id: Optional[str] = None
    expected_working_state_revision: Optional[int] = None
    request_id: Optional[str] = None
    source_scope_ids: list[str] = Field(default_factory=list)
    max_steps: Optional[int] = Field(default=None, ge=1)
    enable_experimental_guidance: Optional[bool] = None


class AgentCycleResponse(BaseModel):
    """Structured response from executing one bounded agent cycle."""

    model_config = ConfigDict(extra="forbid")

    cycle_id: str
    task_id: str
    investigation_id: str
    run_id: Optional[str] = None
    starting_revision: int
    ending_revision: Optional[int] = None
    integration_status: str
    integration_revision: Optional[int] = None
    delegation_ids: list[str] = Field(default_factory=list)
    run_stop_reason: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AgentQuestionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    status: str
    disposition: Optional[str] = None


class AgentStateResponse(BaseModel):
    """Read-only view of current agent working state and execution status."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    investigation_id: str
    working_state_revision: int
    working_state_hash: str
    objective: Optional[str] = None
    agent_execution_status: str
    questions_count: int
    questions_summary: list[AgentQuestionSummary] = Field(default_factory=list)
    findings_count: int
    hypotheses_count: int
    active_delegations_count: int
    latest_trajectory_ref: Optional[str] = None


def _get_agent_orchestrator():
    try:
        manager = get_service_manager()
        return manager.agent_orchestrator
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="agent orchestrator is unavailable",
        ) from exc


@router.post(
    "/agent/cycle",
    response_model=AgentCycleResponse,
    status_code=200,
)
async def execute_agent_cycle(
    request: AgentCycleRequest,
) -> AgentCycleResponse:
    """Trigger one bounded Agent v0 PLAN->EXECUTE->INTEGRATE->EVALUATE cycle."""
    manager = get_service_manager()
    settings = manager.settings

    if not getattr(settings, "agent_execution_enabled", False):
        raise HTTPException(
            status_code=403,
            detail="agent execution is disabled by configuration",
        )

    from ..services.investigation.agent_runtime import (
        AgentRuntimeConflictError,
        AgentRuntimeRepository,
        WorkingStateRevisionConflictError,
    )
    from ..services.investigation.paths import investigation_db_path_for_task

    try:
        task = await manager.cpp_backend.get_task(request.task_id)
        if not isinstance(task, dict) or task.get("id") != request.task_id:
            raise HTTPException(
                status_code=404,
                detail=f"task not found or investigation db unavailable for {request.task_id}",
            )
        db_path = investigation_db_path_for_task(task)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"task not found or investigation db unavailable for {request.task_id}",
        ) from exc

    if not db_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"task not found or investigation db unavailable for {request.task_id}",
        )

    # Concurrency control: task-scoped claim/lock
    if request.task_id in _agent_task_running:
        raise HTTPException(
            status_code=409,
            detail=f"agent cycle is already running for task {request.task_id}",
        )

    lock = _agent_task_locks.setdefault(request.task_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(
            status_code=409,
            detail=f"agent cycle is already running for task {request.task_id}",
        )

    import hashlib
    import json
    import uuid

    request_id = request.request_id or f"req_{uuid.uuid4().hex[:16]}"

    async with lock:
        _agent_task_running.add(request.task_id)
        execution_id = None
        runtime = None
        try:
            from ..services.investigation.repository import InvestigationRepository

            repo = InvestigationRepository(db_path, request.task_id)
            runtime = AgentRuntimeRepository(repo)
            orchestrator = _get_agent_orchestrator()

            # Resolve or create investigation
            investigation_id = request.investigation_id
            if not investigation_id:
                existing_invs = runtime.list_investigations()
                if existing_invs:
                    investigation_id = existing_invs[0].investigation_id
                else:
                    from ..services.investigation.agent_working_state import (
                        AgentWorkingStateV1,
                    )

                    new_inv_id = f"inv_{uuid.uuid4().hex[:12]}"
                    initial_state = AgentWorkingStateV1(
                        task_id=request.task_id,
                        investigation_id=new_inv_id,
                        objective="Automated Agent Investigation",
                    )
                    inv, _ = await orchestrator.create_investigation(
                        request.task_id,
                        initial_state,
                    )
                    investigation_id = inv.investigation_id

            # Canonical input fingerprint for durable idempotency
            effective_guidance = (
                request.enable_experimental_guidance
                if request.enable_experimental_guidance is not None
                else getattr(settings, "agent_experimental_guidance_enabled", False)
            )
            supervisor_prompt_version = (
                "supervisor-v2-vocabulary-guidance-v1"
                if effective_guidance
                else "supervisor-v2"
            )
            fingerprint_data = {
                "task_id": request.task_id,
                "investigation_id": investigation_id,
                "expected_working_state_revision": request.expected_working_state_revision,
                "source_scope_ids": sorted(request.source_scope_ids or []),
                "max_steps": request.max_steps,
                "effective_execution_options": {
                    "enable_experimental_guidance": bool(effective_guidance),
                    "supervisor_prompt_version": supervisor_prompt_version,
                },
            }
            input_fingerprint = hashlib.sha256(
                json.dumps(fingerprint_data, sort_keys=True).encode("utf-8")
            ).hexdigest()

            # Atomic claim in SQLite
            try:
                execution, is_replayed = runtime.claim_cycle_execution(
                    investigation_id=investigation_id,
                    request_id=request_id,
                    input_fingerprint=input_fingerprint,
                    expected_revision=request.expected_working_state_revision,
                )
            except (AgentRuntimeConflictError, WorkingStateRevisionConflictError) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

            # If replayed and already completed, return cached response directly
            if is_replayed and execution.cycle_outcome_json:
                return AgentCycleResponse.model_validate_json(execution.cycle_outcome_json)

            execution_id = execution.execution_id
            runtime.mark_cycle_execution_running(execution_id)

            # Re-verify task before running cycle (Task deletion safety)
            task_check = await manager.cpp_backend.get_task(request.task_id)
            if not isinstance(task_check, dict) or task_check.get("id") != request.task_id:
                runtime.fail_cycle_execution(execution_id, "task was deleted before execution", status="failed")
                raise HTTPException(
                    status_code=404,
                    detail=f"task not found or investigation db unavailable for {request.task_id}",
                )

            outcome = await orchestrator.execute_cycle(
                request.task_id,
                investigation_id,
                source_scope_ids=request.source_scope_ids,
            )

            # Re-verify task before marking completed (Task deletion safety)
            task_post_check = await manager.cpp_backend.get_task(request.task_id)
            if not isinstance(task_post_check, dict) or task_post_check.get("id") != request.task_id:
                runtime.fail_cycle_execution(execution_id, "task was deleted during execution", status="failed")
                raise HTTPException(
                    status_code=404,
                    detail=f"task not found or investigation db unavailable for {request.task_id}",
                )

            response = AgentCycleResponse(
                cycle_id=outcome.cycle_id,
                task_id=request.task_id,
                investigation_id=outcome.investigation_id,
                run_id=outcome.run_id,
                starting_revision=outcome.starting_revision,
                ending_revision=outcome.ending_revision,
                integration_status=outcome.integration_status,
                integration_revision=outcome.integration_revision,
                delegation_ids=list(outcome.delegation_ids),
                run_stop_reason=outcome.run_stop_reason,
                warnings=list(outcome.warnings),
                limitations=list(outcome.limitations),
            )

            # Persist completed cycle outcome for durable idempotency
            runtime.complete_cycle_execution(
                execution_id,
                response.model_dump_json(),
            )

            return response
        except HTTPException:
            raise
        except Exception as exc:
            if runtime is not None and execution_id is not None:
                try:
                    runtime.fail_cycle_execution(execution_id, str(exc), status="failed")
                except Exception:
                    pass
            raise HTTPException(
                status_code=500,
                detail=f"agent cycle execution failed: {type(exc).__name__}: {exc}"[:300],
            ) from exc
        finally:
            _agent_task_running.discard(request.task_id)


@router.get(
    "/agent/state",
    response_model=AgentStateResponse,
    status_code=200,
)
async def get_agent_state(
    task_id: str = Query(..., min_length=1),
    investigation_id: Optional[str] = Query(None),
) -> AgentStateResponse:
    """Read-only query of current agent working state. Zero LLM calls or mutations."""
    from ..services.investigation.agent_runtime import AgentRuntimeRepository
    from ..services.investigation.agent_working_state import working_state_from_json
    from ..services.investigation.paths import investigation_db_path_for_task

    manager = get_service_manager()
    try:
        task = await manager.cpp_backend.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise HTTPException(
                status_code=404,
                detail=f"task not found or investigation db unavailable for {task_id}",
            )
        db_path = investigation_db_path_for_task(task)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"task not found or investigation db unavailable for {task_id}",
        ) from exc

    if not db_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"task not found or investigation db unavailable for {task_id}",
        )

    from ..services.investigation.repository import InvestigationRepository

    repo = InvestigationRepository(db_path, task_id)
    runtime = AgentRuntimeRepository(repo)


    inv_id = investigation_id
    if not inv_id:
        existing_invs = runtime.list_investigations()
        if not existing_invs:
            raise HTTPException(
                status_code=404,
                detail=f"no investigation found for task {task_id}",
            )
        inv_id = existing_invs[0].investigation_id

    latest = runtime.get_latest_working_state(inv_id)
    if latest is None:
        raise HTTPException(
            status_code=404,
            detail=f"no working state found for investigation {inv_id}",
        )

    state = working_state_from_json(task_id, inv_id, latest.state)
    q_summaries = [
        AgentQuestionSummary(
            question_id=q.question_id,
            status=q.status.value,
            disposition=q.disposition.value if q.disposition else None,
        )
        for q in state.questions
    ]

    runs = runtime.list_runs(inv_id)
    active_run = next((r for r in runs if r.status.value in ("queued", "running")), None)
    exec_status = "running" if active_run and active_run.status.value == "running" else "idle"

    trajectories = runtime.list_trajectory(inv_id)
    latest_traj_ref = None
    if trajectories:
        last_evt = trajectories[-1]
        evt_type = last_evt.event_type.value if hasattr(last_evt.event_type, "value") else str(last_evt.event_type)
        latest_traj_ref = f"{evt_type}:{last_evt.seq}"

    active_dels = []
    if active_run:
        active_dels = [
            d for d in runtime.list_delegations(active_run.run_id)
            if d.status.value in ("queued", "running")
        ]

    return AgentStateResponse(
        task_id=task_id,
        investigation_id=inv_id,
        working_state_revision=latest.revision,
        working_state_hash=latest.state_hash,
        objective=state.objective,
        agent_execution_status=exec_status,
        questions_count=len(state.questions),
        questions_summary=q_summaries,
        findings_count=len(state.finding_refs),
        hypotheses_count=len(state.hypotheses),
        active_delegations_count=len(active_dels),
        latest_trajectory_ref=latest_traj_ref,
    )


# ---------------------------------------------------------------------------
# Agent Analyst Review routes (RCA-2A.20)
# ---------------------------------------------------------------------------

def get_agent_analyst_review_service() -> AgentAnalystReviewService:
    """Resolve the ready AgentAnalystReviewService through ServiceManager."""
    try:
        return get_service_manager().agent_analyst_review_service
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="agent analyst review service is unavailable",
        ) from exc


@router.get(
    "/agent/review-candidates",
    response_model=list[ReviewCandidateProjection],
    status_code=200,
)
async def list_agent_review_candidates(
    task_id: str = Query(..., min_length=1),
    investigation_id: Optional[str] = Query(None),
    service: AgentAnalystReviewService = Depends(get_agent_analyst_review_service),
) -> list[ReviewCandidateProjection]:
    """Read-only query of all review candidates for a task. 0 LLM calls, 0 writes."""
    try:
        return await service.list_candidates(task_id, investigation_id=investigation_id)
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


@router.get(
    "/agent/review-candidates/{candidate_id:path}",
    response_model=ReviewCandidateProjection,
    status_code=200,
)
async def get_agent_review_candidate(
    candidate_id: str,
    task_id: str = Query(..., min_length=1),
    investigation_id: Optional[str] = Query(None),
    service: AgentAnalystReviewService = Depends(get_agent_analyst_review_service),
) -> ReviewCandidateProjection:
    """Read-only query of a specific review candidate by id. 0 LLM calls, 0 writes."""
    try:
        return await service.get_candidate(task_id, candidate_id, investigation_id=investigation_id)
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


@router.get(
    "/agent/reviews/history",
    response_model=list[ReviewHistoryItem],
    status_code=200,
)
async def get_agent_review_history(
    task_id: str = Query(..., min_length=1),
    candidate_id: Optional[str] = Query(None),
    investigation_id: Optional[str] = Query(None),
    service: AgentAnalystReviewService = Depends(get_agent_analyst_review_service),
) -> list[ReviewHistoryItem]:
    """Read-only query of append-only review history."""
    try:
        return await service.get_history(task_id, candidate_id=candidate_id, investigation_id=investigation_id)
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc


@router.post(
    "/agent/review",
    response_model=ReviewDecisionOutcome,
    status_code=200,
)
async def submit_agent_review(
    request: ReviewDecisionRequest,
    service: AgentAnalystReviewService = Depends(get_agent_analyst_review_service),
) -> ReviewDecisionOutcome:
    """Submit an explicit human analyst review decision for an agent candidate.

    Guarantees:
      - 200 on success or exact idempotent replay.
      - 404 on task or candidate not found.
      - 409 on stale candidate hash, revision mismatch, concurrent claim, or conflicting replay.
      - 422 on evidence provenance failure or unauthorized fact promotion.
      - 503 on store unavailable.
    """
    try:
        return await service.submit_review(request.task_id, request)
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (EvidenceProvenanceError, FactPromotionBlockedError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="evidence store unavailable") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"review submission failed: {exc}") from exc



