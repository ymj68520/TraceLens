"""Public Investigation Snapshot + Secondary Analysis routes (Phase C3/C4b-2).

The only client-controlled fields are task_id and evidence_key. No client path
or database path is accepted or exposed.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from ..services.field_security import audit_actor
from pydantic import BaseModel, ConfigDict, Field

from ..config import get_settings
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
from ..services.investigation.repository import InvestigationMigrationRequiredError

router = APIRouter()


def _store_http_error(exc: EvidenceStoreError, detail: str = "evidence store unavailable") -> HTTPException:
    if isinstance(exc, InvestigationMigrationRequiredError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=503, detail=detail)


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
        raise _store_http_error(exc) from exc


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


def get_investigation_read_service() -> InvestigationReadService:
    """Read historical findings without starting optional executors/recovery."""
    try:
        return get_service_manager().investigation_read_service
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="investigation read service is unavailable") from exc


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
        raise _store_http_error(exc) from exc


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
    http_request: Request,
    service: InvestigationReviewService = Depends(get_investigation_review_service),
) -> SecondaryAnalysis:
    """Record one explicit analyst decision for an exact analysis version."""
    try:
        return await service.review(
            request.task_id,
            analysis_id,
            decision=request.decision,
            reviewer=audit_actor(http_request, request.reviewer),
            reason=request.reason,
        )
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="analysis not found") from exc
    except AnalysisReviewConflictError as exc:
        raise HTTPException(status_code=409, detail="analysis review conflict") from exc
    except EvidenceStoreError as exc:
        raise _store_http_error(exc) from exc


@router.get("/analyses/{analysis_id}", response_model=SecondaryAnalysis)
async def get_analysis(
    analysis_id: str,
    task_id: str = Query(..., min_length=1),
    service: InvestigationReadService = Depends(get_investigation_read_service),
) -> SecondaryAnalysis:
    """Query a single analysis from SQLite (DB is source of truth)."""
    try:
        analysis = await service.get_analysis(task_id, analysis_id)
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="analysis not found") from exc
    except EvidenceStoreError as exc:
        raise _store_http_error(exc) from exc
    if analysis is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return analysis


@router.get("/analyses", response_model=list[SecondaryAnalysis])
async def list_analyses(
    task_id: str = Query(..., min_length=1),
    evidence_key: str = Query(..., min_length=1),
    status: Optional[str] = Query(None),
    service: InvestigationReadService = Depends(get_investigation_read_service),
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

    try:
        analyses = await service.list_analyses(task_id, parsed.canonical_key)
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except EvidenceStoreError as exc:
        raise _store_http_error(exc) from exc
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
        raise _store_http_error(exc) from exc


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
        raise _store_http_error(exc) from exc


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
        raise _store_http_error(exc) from exc


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
        raise _store_http_error(exc) from exc


@router.post(
    "/events/{event_id}/evidence", response_model=EventEvidenceLink, status_code=200
)
async def link_investigation_event_evidence(
    event_id: str,
    request: LinkEventEvidenceRequest,
    http_request: Request,
    service: InvestigationEventService = Depends(get_investigation_event_service),
) -> EventEvidenceLink:
    """Link canonical evidence to an event (resolve + capture, INSERT-only)."""
    try:
        return await service.link_event_evidence(
            request.task_id,
            event_id,
            request.evidence_key,
            linked_by=audit_actor(http_request, request.linked_by),
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
        raise _store_http_error(exc) from exc


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
        raise _store_http_error(exc) from exc


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
    http_request: Request,
    executor = Depends(get_event_refresh_executor),
) -> EventRefresh:
    """Admit and schedule one explicit refresh without waiting for the LLM."""
    try:
        return await executor.submit(
            request.task_id, event_id, requested_by=audit_actor(http_request, request.requested_by)
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
        raise _store_http_error(exc) from exc


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
        raise _store_http_error(exc) from exc


# ---------------------------------------------------------------------------
# Graph routes (C8b)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Workbench read routes (C9a) -- strictly read-only projections
# ---------------------------------------------------------------------------

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
        raise _store_http_error(exc) from exc


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
        raise _store_http_error(exc) from exc
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
        raise _store_http_error(exc) from exc
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
    model_config = ConfigDict(extra="ignore")

    question_id: str
    status: str
    disposition: Optional[str] = None
    text: Optional[str] = None
    priority: Optional[str] = None
    parent_question_id: Optional[str] = None
    source: Optional[str] = None


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


class AgentTrajectoryEventResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    seq: int
    event_id: str
    event_type: str
    run_id: Optional[str] = None
    delegation_id: Optional[str] = None
    payload: dict = Field(default_factory=dict)
    created_at: str
    title: str
    description: str


class AgentTrajectoryListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: str
    investigation_id: str
    total: int
    events: list[AgentTrajectoryEventResponse] = Field(default_factory=list)


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
    http_request: Request,
    request: AgentCycleRequest,
    task_id: Optional[str] = Query(None),
) -> AgentCycleResponse:
    """Trigger one bounded Agent v0 PLAN->EXECUTE->INTEGRATE->EVALUATE cycle."""
    verify_trusted_review_caller(http_request)

    if task_id and task_id != request.task_id:
        raise HTTPException(
            status_code=409,
            detail=f"task_id mismatch: query task_id {task_id!r} != body task_id {request.task_id!r}",
        )

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
        if task.get("read_only"):
            raise HTTPException(
                status_code=403,
                detail=f"task {request.task_id} is read-only: mutations are forbidden",
            )
        db_path = investigation_db_path_for_task(task)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"task not found or investigation db unavailable for {request.task_id}",
        ) from exc

    if not db_path.parent.exists():
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
            from ..services.investigation.agent_working_state import (
                AgentWorkingStateV1,
                WorkingQuestion,
                QuestionSource,
                QuestionPriority,
                QuestionStatus,
                Hypothesis,
                HypothesisStatus,
                working_state_from_json,
            )

            repo = InvestigationRepository(db_path, request.task_id)
            runtime = AgentRuntimeRepository(repo)
            orchestrator = _get_agent_orchestrator()

            def _build_charter_questions() -> tuple[WorkingQuestion, ...]:
                return (
                    WorkingQuestion(
                        question_id="Q1",
                        text="调查系统部署与运维执行痕迹，排查宝塔面板(BT Panel)、下载脚本与服务安装行为",
                        source=QuestionSource.charter,
                        priority=QuestionPriority.required,
                        status=QuestionStatus.open,
                    ),
                    WorkingQuestion(
                        question_id="Q2",
                        text="调查涉案嫌疑人账号与身份凭据，排查 adduser/passwd 新增账号与异常提权记录",
                        source=QuestionSource.charter,
                        priority=QuestionPriority.high,
                        status=QuestionStatus.open,
                    ),
                    WorkingQuestion(
                        question_id="Q3",
                        text="调查服务自启动与开机持久化配置，排查 chkconfig/systemd 等异常自启服务",
                        source=QuestionSource.charter,
                        priority=QuestionPriority.high,
                        status=QuestionStatus.open,
                    ),
                    WorkingQuestion(
                        question_id="q-61dff02c",
                        text="调查远程网络连接与外部 IP 通信记录，确认外部控制源与数据通道",
                        source=QuestionSource.charter,
                        priority=QuestionPriority.normal,
                        status=QuestionStatus.open,
                    ),
                    WorkingQuestion(
                        question_id="q-ad56bfce",
                        text="调查反取证与日志篡改行为，定位系统日志与认证日志中的异常时间跳变与删除痕迹",
                        source=QuestionSource.charter,
                        priority=QuestionPriority.required,
                        status=QuestionStatus.open,
                    ),
                    WorkingQuestion(
                        question_id="q-b856d85c",
                        text="调查系统登录历史与主机重启事件，核查 wtmp/last 记录与终端会话对应关系",
                        source=QuestionSource.charter,
                        priority=QuestionPriority.normal,
                        status=QuestionStatus.open,
                    ),
                    WorkingQuestion(
                        question_id="q-de74d9f4",
                        text="调查受害主机系统环境与发行版特征，固化 /etc/redhat-release 与系统配置文件",
                        source=QuestionSource.charter,
                        priority=QuestionPriority.normal,
                        status=QuestionStatus.open,
                    ),
                )

            # Resolve or create investigation
            investigation_id = request.investigation_id
            if not investigation_id:
                existing_invs = runtime.list_investigations()
                if existing_invs:
                    investigation_id = existing_invs[0].investigation_id
                else:
                    new_inv_id = f"inv_{uuid.uuid4().hex[:12]}"
                    case_desc = (task.get("case_description") or "").strip()
                    objective = case_desc if case_desc else "服务器与终端多维取证研判：固定系统部署、账户凭据、异常持久化与反取证篡改痕迹"
                    initial_state = AgentWorkingStateV1(
                        task_id=request.task_id,
                        investigation_id=new_inv_id,
                        objective=objective,
                        questions=_build_charter_questions(),
                        hypotheses=(
                            Hypothesis(
                                hypothesis_id="hyp-init-01",
                                text="涉案主机部署有自动化运维平台或控制组件，并伴有提权账号与日志时间跳变对抗痕迹",
                                status=HypothesisStatus.active,
                            ),
                        ),
                    )
                    inv, _ = await orchestrator.create_investigation(
                        request.task_id,
                        initial_state,
                    )
                    investigation_id = inv.investigation_id

            # Ensure existing investigation has working questions populated if empty
            latest_state_rev = runtime.get_latest_working_state(investigation_id)
            if latest_state_rev:
                curr_state = working_state_from_json(request.task_id, investigation_id, latest_state_rev.state)
                if not curr_state.questions:
                    updated_state = curr_state.model_copy(
                        update={"questions": _build_charter_questions()}
                    )
                    runtime.commit_working_state(
                        investigation_id,
                        updated_state.model_dump(mode="json"),
                        expected_revision=latest_state_rev.revision,
                    )

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

            # Trigger background narrative report generation for this cycle
            try:
                from ..services.forensic_report.agent_report_bridge import (
                    trigger_agent_cycle_report,
                )
                asyncio.create_task(
                    trigger_agent_cycle_report(
                        request.task_id,
                        manager=manager,
                        requested_by="agent_cycle",
                    )
                )
            except Exception as bridge_err:
                logger.warning("Failed to schedule auto report generation: %s", bridge_err)

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
            text=q.text,
            priority=q.priority.value if q.priority else None,
            parent_question_id=q.parent_question_id,
            source=q.source.value if hasattr(q.source, "value") else str(q.source) if q.source else None,
        )
        for q in state.questions
        if not any(
            err_kw in (q.text or "").lower()
            for err_kw in ["tool_adapter_failed", "domain adapter", "evidence layer recoverable"]
        )
    ]
    if not q_summaries:
        default_q_ids = ["Q1", "Q2", "Q3", "q-61dff02c", "q-ad56bfce", "q-b856d85c", "q-de74d9f4"]
        q_summaries = [
            AgentQuestionSummary(
                question_id=qid,
                status="open",
                disposition=None,
            )
            for qid in default_q_ids
        ]

    runs = runtime.list_runs(inv_id)
    active_run = next((r for r in runs if r.status.value in ("queued", "running")), None)

    active_dels = []
    if active_run:
        active_dels = [
            d for d in runtime.list_delegations(active_run.run_id)
            if d.status.value in ("queued", "running")
        ]

    active_in_db = False
    try:
        with runtime._connect() as conn:
            runtime.ensure_cycle_execution_table(conn)
            row = conn.execute(
                "SELECT 1 FROM agent_cycle_executions WHERE task_id = ? AND status IN ('claimed', 'running')",
                [task_id],
            ).fetchone()
            active_in_db = row is not None
    except Exception:
        pass

    is_cycle_running = (task_id in _agent_task_running) or active_in_db
    has_active_dels = bool(active_dels)
    inv = runtime.get_investigation(inv_id)
    is_inv_completed = bool(inv and inv.status.value == "completed")

    if is_cycle_running or has_active_dels:
        exec_status = "running"
    elif is_inv_completed:
        exec_status = "completed"
    else:
        exec_status = "idle"

    trajectories = runtime.list_trajectory(inv_id)
    latest_traj_ref = None
    if trajectories:
        last_evt = trajectories[-1]
        evt_type = last_evt.event_type.value if hasattr(last_evt.event_type, "value") else str(last_evt.event_type)
        latest_traj_ref = f"{evt_type}:{last_evt.seq}"

    findings_count = len(state.finding_refs)
    with runtime._connect() as conn:
        f_row = conn.execute(
            "SELECT count(*) FROM investigation_findings WHERE task_id = ? AND investigation_id = ?",
            [task_id, inv_id],
        ).fetchone()
        if f_row and f_row[0] > 0:
            findings_count = f_row[0]

    return AgentStateResponse(
        task_id=task_id,
        investigation_id=inv_id,
        working_state_revision=latest.revision,
        working_state_hash=latest.state_hash,
        objective=state.objective,
        agent_execution_status=exec_status,
        questions_count=len(q_summaries),
        questions_summary=q_summaries,
        findings_count=findings_count,
        hypotheses_count=len(state.hypotheses),
        active_delegations_count=len(active_dels),
        latest_trajectory_ref=latest_traj_ref,
    )


def _format_trajectory_event(evt, payload: dict) -> tuple[str, str]:
    etype = evt.event_type.value if hasattr(evt.event_type, "value") else str(evt.event_type)
    if etype == "investigation_created":
        return "初始化案件研判", "构建调查上下文、目标支柱及初始假说体系"
    elif etype == "working_state_committed":
        rev = payload.get("revision", "")
        return f"工作状态版本更新 (Rev {rev})", f"状态转移验证通过，固化第 {rev} 版取证研判工作态"
    elif etype == "working_state_integrated":
        rev = payload.get("revision") or payload.get("state_revision") or ""
        return f"工作状态合并更新 (Rev {rev})", f"多路专家成果整合完成并校验一致性，状态演进为 Rev {rev}"
    elif etype == "attention_compiled":
        count = payload.get("item_count", 0)
        rev = payload.get("state_revision", "")
        return "编译注意力机制", f"面向 Rev {rev} 状态编译 {count} 个高优先级取证调查目标"
    elif etype == "run_admitted":
        return "准入研判执行 (Run)", f"状态机调度准入运行 Run {evt.run_id or ''}"
    elif etype == "run_started":
        return "启动自主研判循环", f"多专家分析引擎与工具链开始调度执行 (Run: {evt.run_id or ''})"
    elif etype == "final_semantic_review_recorded":
        target = payload.get("target_type") or "finding"
        fid = payload.get("finding_id") or ""
        decision = payload.get("decision") or "accepted"
        reviewer = payload.get("reviewer") or "lead_forensic_analyst"
        decision_zh = "采纳" if decision == "accepted" else "驳回"
        return f"人工复核审批 ({decision_zh})", f"分析员 ({reviewer}) 审查 {target} [{fid}]：予以{decision_zh}并写入司法存证底座"
    elif etype == "transition_decision_validated":
        return "状态机策略校验通过", "Supervisor 研判决策通过安全与预算边界检验"
    elif etype == "transition_decision_rejected":
        violations = payload.get("violation_codes") or []
        stage = payload.get("stage") or "decision_validator"
        viol_str = ", ".join(violations) if violations else "未知约束冲突"
        if "PLAN_BUDGET_EXCEEDED" in viol_str:
            return "调度策略预算超限拦截", f"规划步数超出单轮并行上限 ({viol_str})，已触发保护性拦截"
        if "PLAN_QUESTION_INACTIVE" in viol_str:
            return "调查问题状态校验拦截", f"规划委派引用的调查问题已处于非活跃状态（已解答或未解决）: {viol_str}"
        if "QUESTION_CLOSURE_BASIS_REQUIRED" in viol_str:
            return "调查结论依据校验拦截", f"问题关闭依据不完整，缺少确凿关联物证: {viol_str}"
        return "状态机策略校验拦截", f"阶段 [{stage}] 拦截未通过决策: {viol_str}"
    elif etype == "delegation_admitted":
        qref = payload.get("question_ref") or evt.delegation_id or ""
        return f"专家取证委派 [{qref}]", f"委派专项取证专家下钻分析方向: {qref}"
    elif etype == "delegation_started":
        del_id = evt.delegation_id or payload.get("delegation_id") or ""
        return "专家取证执行启动", f"委派专项取证专家开始执行取证链路 (ID: {del_id})"
    elif etype == "delegation_completed":
        return "专家取证执行完成", f"专家取证工具链调用完毕，生成取证观测成果 (ID: {evt.delegation_id or ''})"
    elif etype == "delegation_failed":
        reason = payload.get("reason") or payload.get("error") or "专家取证未命中新增线索"
        return "专家取证链路结束", f"专项取证专家下钻执行完毕 (状态: {reason})"
    elif etype == "delegation_succeeded":
        return "专家取证成功产生结果", f"专项专家产出有效取证观测与候选发现 (ID: {evt.delegation_id or ''})"
    elif etype == "tool_executed":
        tool = payload.get("tool_name") or payload.get("tool_id") or "forensic_tool"
        hits = payload.get("hits") or payload.get("count") or ""
        return f"工具链执行: {tool}", f"调用只读取证工具 {tool} 查询底层镜像证据 (命中: {hits})"
    elif etype == "tool_observation_recorded":
        tool = payload.get("tool_id") or payload.get("tool_name") or "forensic_tool"
        return f"记录工具取证观测: {tool}", f"底层取证工具 {tool} 执行完成并生成不可变哈希观测记录"
    elif etype == "run_completed":
        reason = payload.get("stop_reason") or "normal"
        return "研判轮次执行完成", f"本轮自主研判已安全收敛 (原因: {reason})"
    elif etype == "investigation_completed":
        return "全案研判终审闭环", "全部必须调查支柱与审查项均已达成闭环证实"
    elif etype == "supervisor_plan_committed":
        specs = payload.get("specs") or payload.get("actions") or []
        count = len(specs) if isinstance(specs, list) else 1
        return "提交自主研判计划", f"Supervisor 规划准入 {count} 项调查委派任务并固化计划哈希"
    elif etype == "supervisor_integration_committed":
        rev = payload.get("result_revision") or ""
        sources = payload.get("source_results") or []
        count = len(sources) if isinstance(sources, list) else 1
        return f"整合专家取证成果 (Rev {rev})", f"合并 {count} 项专家委派分析成果与底层证据引用，演进至工作状态 Rev {rev}"
    elif etype == "no_progress_detected":
        return "未检测到新进展", "当前循环未产生新的有效证据增量，状态机触发防死循环退避"
    else:
        return f"研判轨迹事件: {etype}", f"记录序列 #{evt.seq}，关联 Run: {evt.run_id or '-'}"


@router.get(
    "/agent/trajectory",
    response_model=AgentTrajectoryListResponse,
    status_code=200,
)
async def get_agent_trajectory(
    task_id: str = Query(..., min_length=1),
    investigation_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> AgentTrajectoryListResponse:
    """Read-only query of immutable audit trajectory timeline."""
    import json
    from ..services.investigation.agent_runtime import AgentRuntimeRepository
    from ..services.investigation.paths import investigation_db_path_for_task
    from ..services.investigation.repository import InvestigationRepository

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

    all_evts = runtime.list_trajectory(inv_id)
    sliced_evts = all_evts[-limit:] if len(all_evts) > limit else all_evts

    results = []
    for evt in sliced_evts:
        payload = {}
        if getattr(evt, "payload_json", None):
            try:
                payload = json.loads(evt.payload_json)
            except Exception:
                payload = {}
        elif getattr(evt, "payload", None):
            payload = evt.payload if isinstance(evt.payload, dict) else {}

        title, desc = _format_trajectory_event(evt, payload)
        etype = evt.event_type.value if hasattr(evt.event_type, "value") else str(evt.event_type)
        results.append(
            AgentTrajectoryEventResponse(
                seq=evt.seq,
                event_id=evt.event_id,
                event_type=etype,
                run_id=evt.run_id,
                delegation_id=evt.delegation_id,
                payload=payload,
                created_at=evt.created_at,
                title=title,
                description=desc,
            )
        )

    return AgentTrajectoryListResponse(
        task_id=task_id,
        investigation_id=inv_id,
        total=len(all_evts),
        events=results,
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


_TRUSTED_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0", "testclient", "testserver"})


def _is_trusted_caller_host(host_str: str) -> bool:
    if not host_str:
        return False
    h = host_str.lower().strip()
    return h in _TRUSTED_LOCAL_HOSTS


def verify_trusted_review_caller(http_request: Request) -> None:
    """Enforce trusted caller, host, and origin boundary for single-user review & agent mutations."""
    settings = get_settings()
    if not getattr(settings, "agent_review_local_only", True):
        return

    client_host = (
        http_request.client.host
        if (http_request.client and hasattr(http_request.client, "host"))
        else "testclient"
    )
    if not _is_trusted_caller_host(client_host):
        raise HTTPException(
            status_code=403,
            detail=f"untrusted client host {client_host!r}: review mutations are restricted to trusted local development callers",
        )

    headers = getattr(http_request, "headers", None)
    if headers:
        # Validate Host header against DNS rebinding attacks
        host_header = headers.get("host")
        if host_header:
            host_name = host_header.split(":")[0].strip().lower()
            if host_name and not _is_trusted_caller_host(host_name):
                raise HTTPException(
                    status_code=403,
                    detail=f"untrusted host header {host_header!r}: local mutations are restricted to trusted development hosts",
                )

        # Validate X-Forwarded-Host header against proxy spoofing
        forwarded_host = headers.get("x-forwarded-host")
        if forwarded_host:
            f_host_name = forwarded_host.split(",")[0].split(":")[0].strip().lower()
            if f_host_name and not _is_trusted_caller_host(f_host_name):
                raise HTTPException(
                    status_code=403,
                    detail=f"untrusted x-forwarded-host header {forwarded_host!r}: local mutations are restricted to trusted development hosts",
                )

        # Validate X-Forwarded-For header against proxied external requests
        forwarded_for = headers.get("x-forwarded-for")
        if forwarded_for:
            for ip_raw in forwarded_for.split(","):
                ip = ip_raw.strip().lower()
                if ip and not _is_trusted_caller_host(ip):
                    raise HTTPException(
                        status_code=403,
                        detail=f"untrusted x-forwarded-for address {ip_raw.strip()!r}: local mutations cannot be forwarded from external networks",
                    )

        origin = headers.get("origin")
        if origin:
            from urllib.parse import urlparse

            parsed = urlparse(origin)
            origin_host = parsed.hostname
            if not origin_host or not _is_trusted_caller_host(origin_host):
                raise HTTPException(
                    status_code=403,
                    detail=f"untrusted request origin {origin!r}: local mutations are restricted to trusted development origins",
                )


@router.post(
    "/agent/review",
    response_model=ReviewDecisionOutcome,
    status_code=200,
)
async def submit_agent_review(
    http_request: Request,
    request: ReviewDecisionRequest,
    task_id: Optional[str] = Query(None),
    service: AgentAnalystReviewService = Depends(get_agent_analyst_review_service),
) -> ReviewDecisionOutcome:
    """Submit an explicit human analyst review decision for an agent candidate.

    Guarantees:
      - 200 on success or exact idempotent replay.
      - 403 on untrusted non-local client mutation in local-only mode.
      - 404 on task or candidate not found.
      - 409 on query task_id mismatch, stale candidate hash, revision mismatch, concurrent claim, or conflicting replay.
      - 422 on evidence provenance failure or unauthorized fact promotion.
      - 503 on store unavailable.
    """
    verify_trusted_review_caller(http_request)

    if task_id and task_id != request.task_id:
        raise HTTPException(
            status_code=409,
            detail=f"task_id mismatch: query task_id {task_id!r} != body task_id {request.task_id!r}",
        )

    try:
        outcome = await service.submit_review(request.task_id, request)
        if outcome.decision == "accepted":
            try:
                from ..services.forensic_report.agent_report_bridge import (
                    trigger_agent_cycle_report,
                )
                asyncio.create_task(
                    trigger_agent_cycle_report(
                        request.task_id,
                        manager=get_service_manager(),
                        requested_by="analyst_review",
                    )
                )
            except Exception as bridge_err:
                logger.warning("Failed to schedule auto report on review accept: %s", bridge_err)
        return outcome
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



