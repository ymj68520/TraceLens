"""AgentOrchestrator: deterministic control-plane shell (P2).

P2 boundary: the orchestrator is NOT a Supervisor.  It decides nothing about
case investigation strategy — it owns the deterministic scaffolding:

    state load / policy evaluation / attention projection /
    action admission validation / transition integration /
    progress evaluation / finalization preflight+commit /
    restart recovery / lifecycle

No PydanticAI, no LLM call, no Supervisor/Specialist/Correlation/Verifier
agent, no Tool Registry, no real delegation execution (admitted actions only
mean "legal — executable by a future P4 executor").

Lifecycle follows the existing executor pattern (SecondaryAnalysisExecutor /
EventRefreshExecutor): ``ServiceManager._initialize_services()`` calls
``initialize()``, which sweeps every trusted task's investigation.db through
the P1 ``recover_interrupted_agent_runtime()`` primitive before the runtime
is marked ready.  Task stores are resolved exclusively through the trusted
``cpp_backend`` lookup — never filesystem scanning.
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Any, Optional, Sequence

from pydantic import BaseModel, ConfigDict

from ..evidence.keys import parse_evidence_key
from .agent_attention import (
    ATTENTION_POLICY_VERSION,
    AttentionBuilder,
    AttentionPolicyConfig,
    AttentionSet,
    DelegationRuntimeView,
)
from .agent_finalization import (
    FINALIZATION_POLICY_VERSION,
    CompletionMode,
    FinalizationDecision,
    FinalizationGate,
    FinalizationOutcome,
    FinalizationRequest,
    REVIEW_UNAVAILABLE,
    RuntimeFinalizationView,
    coverage_disposition_snapshot,
    finalization_input_hash,
    question_disposition_snapshot,
)
from .agent_progress import (
    NoProgressDetector,
    NoProgressPolicyConfig,
    NO_PROGRESS_POLICY_VERSION,
)
from .agent_runtime import (
    AgentInvestigationStatus,
    AgentRunStatus,
    AgentRuntimeConflictError,
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
    DelegationStatus,
    FinalizationRecord,
    InvestigationPauseReason,
    RunStopReason,
    WorkingStateRevisionConflictError,
)
from .agent_transitions import (
    STATE_REVISION_CONFLICT,
    EvidenceRefStatus,
    FindingRefCheck,
    StateTransitionPolicy,
    TransitionBatch,
    TransitionDecisionStatus,
    TransitionPolicyContext,
)
from .agent_working_state import (
    AgentWorkingStateV1,
    STATE_TRANSITION_POLICY_VERSION,
    working_state_from_json,
    working_state_to_json,
)
from .paths import investigation_db_path_for_task
from .repository import InvestigationRepository

logger = logging.getLogger(__name__)


class AgentOrchestratorError(RuntimeError):
    """The orchestrator could not perform a deterministic control action."""


class ControlActionType(str, Enum):
    """Investigation-level control-plane action families (P2 §42)."""

    delegate_source = "delegate_source"
    delegate_correlation = "delegate_correlation"
    request_verification = "request_verification"
    request_graph_admission = "request_graph_admission"
    direct_read = "direct_read"
    request_finalize = "request_finalize"


class ControlAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_type: ControlActionType
    question_id: Optional[str] = None
    payload: dict = {}


class RejectedAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: ControlAction
    violation_codes: tuple[str, ...] = ()


class ActionBatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    admitted: tuple[ControlAction, ...] = ()
    rejected: tuple[RejectedAction, ...] = ()
    state_revision: Optional[int] = None


class CyclePreparation(BaseModel):
    """Deterministic PLAN output boundary (supervisor input scaffold)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    investigation_id: str
    state: AgentWorkingStateV1
    state_revision: int
    attention_set: AttentionSet
    active_run_id: Optional[str]
    allowed_action_types: tuple[ControlActionType, ...]


class IntegrationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: TransitionDecisionStatus
    policy_version: str
    state_revision: Optional[int] = None
    violations: tuple = ()
    operation_key: Optional[str] = None


class ProgressEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    productive: bool
    reason_codes: tuple[str, ...] = ()
    consecutive_no_progress_cycles: int
    no_progress_detected: bool
    state_revision: int
    run_stopped: bool = False
    policy_version: str = NO_PROGRESS_POLICY_VERSION


class FinalizationCommitResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: FinalizationDecision
    record: Optional[FinalizationRecord] = None

    @property
    def finalized(self) -> bool:
        return self.record is not None


# actions that materialise as delegations (duplicate fingerprint checks apply)
_DELEGATION_ACTION_TYPES = frozenset(
    {ControlActionType.delegate_source, ControlActionType.delegate_correlation}
)

_ALLOWED_CONTROL_ACTIONS = frozenset(ControlActionType)


class AgentOrchestrator:
    """Deterministic control plane over the P1 agent runtime store."""

    def __init__(
        self,
        cpp_backend,
        *,
        attention_config: Optional[AttentionPolicyConfig] = None,
        no_progress_config: Optional[NoProgressPolicyConfig] = None,
    ):
        self._cpp_backend = cpp_backend
        self._attention_config = attention_config or AttentionPolicyConfig()
        self._no_progress_config = no_progress_config or NoProgressPolicyConfig()
        self._attention_builder = AttentionBuilder()
        self._policy = StateTransitionPolicy()
        self._detector = NoProgressDetector()
        self._gate = FinalizationGate()
        self._accepting = True
        # Run-level no-progress streak bookkeeping (P2 freeze follow-up F1):
        # the streak never touches the Working State — revisions grow only
        # through semantic mutations.  A restart terminalises the run
        # (failed/runtime_restart), so the streak is intentionally not
        # recovered across restarts; every no-progress cycle is audited in
        # the trajectory payload.
        self._no_progress_streaks: dict[tuple[str, str, str], int] = {}

    # =====================================================================
    # lifecycle (ServiceManager startup hook, P2 §44/§45)
    # =====================================================================

    async def initialize(self) -> None:
        """ServiceManager startup: run trusted task-owned runtime recovery
        before the orchestrator becomes usable."""
        await self._recover_all_tasks()

    async def shutdown(self) -> None:
        """P2 has no agent background tasks; establish the lifecycle owner
        and stop admitting new control work."""
        self._accepting = False

    async def _recover_all_tasks(self) -> None:
        page = 1
        while True:
            result = await self._cpp_backend.list_tasks(
                page=page,
                page_size=100,
                timeout=getattr(
                    self._cpp_backend.settings, "cpp_recovery_timeout", 8.0
                ),
                max_retries=1,
            )
            tasks = result.get("tasks") or result.get("data") or []
            if not isinstance(tasks, list) or not tasks:
                break
            for task_summary in tasks:
                await self._recover_task(task_summary)
            if len(tasks) < 100:
                break
            page += 1
        logger.info("Agent runtime restart recovery sweep complete")

    async def _recover_task(self, task_summary: dict[str, Any]) -> None:
        task_id = task_summary.get("id")
        if not task_id or not isinstance(task_id, str):
            return
        full_task = await self._cpp_backend.get_task(
            task_id,
            timeout=getattr(
                self._cpp_backend.settings, "cpp_recovery_timeout", 8.0
            ),
            max_retries=1,
        )
        if full_task is None:
            return
        try:
            db_path = investigation_db_path_for_task(full_task)
        except Exception:
            return  # no trusted store path for this task
        if not db_path.exists():
            return
        try:
            # existing-store-only: a vanished store is skipped, never recreated
            repo = await asyncio.to_thread(
                InvestigationRepository.open_existing, db_path, task_id
            )
        except Exception:
            return
        try:
            summary = await asyncio.to_thread(
                AgentRuntimeRepository(repo).recover_interrupted_agent_runtime
            )
            if any(summary.values()):
                logger.info("Agent runtime recovery for task %s: %s", task_id, summary)
        except Exception:
            logger.exception("Agent runtime recovery failed for task %s", task_id)

    # =====================================================================
    # store access (trusted task lookup only, P2 §2)
    # =====================================================================

    async def _open_runtime(
        self, task_id: str, *, existing_only: bool = True
    ) -> AgentRuntimeRepository:
        if not self._accepting:
            raise AgentOrchestratorError("orchestrator is shutting down")
        task = await self._cpp_backend.get_task(task_id)
        if task is None:
            raise AgentOrchestratorError(f"task not found: {task_id!r}")
        db_path = investigation_db_path_for_task(task)
        if existing_only:
            # terminal/control writes never create or resurrect a store
            repo = await asyncio.to_thread(
                InvestigationRepository.open_existing, db_path, task_id
            )
        else:
            # investigation creation entry point: the write-capable
            # constructor may establish the store (E1 pattern), from the
            # trusted task-owned path only
            repo = await asyncio.to_thread(
                InvestigationRepository, db_path, task_id
            )
        return AgentRuntimeRepository(repo)

    # ------------------------------------------------------------------
    # typed state creation
    # ------------------------------------------------------------------

    async def create_investigation(
        self, task_id: str, state: AgentWorkingStateV1
    ) -> tuple:
        """Create an investigation whose initial revision is a typed v1
        state (identity must match the task)."""
        if state.task_id != task_id:
            raise AgentOrchestratorError(
                f"typed state belongs to task {state.task_id!r}, not {task_id!r}"
            )
        runtime = await self._open_runtime(task_id, existing_only=False)
        return await asyncio.to_thread(
            self._create_investigation_sync, runtime, state
        )

    def _create_investigation_sync(self, runtime: AgentRuntimeRepository, state):
        return runtime.create_investigation(
            working_state_to_json(state),
            investigation_id=state.investigation_id,
        )

    # =====================================================================
    # PLAN (P2 §41)
    # =====================================================================

    async def prepare_cycle(
        self,
        task_id: str,
        investigation_id: str,
        *,
        attention_config: Optional[AttentionPolicyConfig] = None,
    ) -> CyclePreparation:
        runtime = await self._open_runtime(task_id)
        return await asyncio.to_thread(
            self._prepare_cycle_sync, runtime, investigation_id, attention_config
        )

    def _prepare_cycle_sync(
        self,
        runtime: AgentRuntimeRepository,
        investigation_id: str,
        attention_config: Optional[AttentionPolicyConfig],
    ) -> CyclePreparation:
        investigation = runtime.get_investigation(investigation_id)
        if investigation is None:
            raise ValueError(f"investigation not found: {investigation_id!r}")
        if investigation.status in (
            AgentInvestigationStatus.completed,
            AgentInvestigationStatus.cancelled,
        ):
            raise AgentRuntimeConflictError(
                f"investigation is terminal ({investigation.status.value!r})"
            )
        latest = runtime.get_latest_working_state(investigation_id)
        if latest is None:
            raise AgentOrchestratorError(
                "investigation has no committed working state"
            )
        state = working_state_from_json(
            runtime.task_id, investigation_id, latest.state
        )
        active_run = self._active_run(runtime, investigation_id)
        in_flight: tuple[str, ...] = ()
        if active_run is not None:
            in_flight = tuple(
                delegation.question_ref
                for delegation in runtime.list_delegations(active_run.run_id)
                if delegation.status in (DelegationStatus.queued, DelegationStatus.running)
                and delegation.question_ref
            )
        attention = self._attention_builder.build_full_set(
            state,
            state_revision=latest.revision,
            runtime=DelegationRuntimeView(
                run_active=active_run is not None,
                in_flight_question_refs=in_flight,
            ),
            config=attention_config or self._attention_config,
        )
        runtime.append_trajectory(
            investigation_id,
            AgentTrajectoryEventType.attention_compiled,
            run_id=active_run.run_id if active_run else None,
            payload={
                "attention_policy_version": ATTENTION_POLICY_VERSION,
                "state_revision": latest.revision,
                "attention_hash": attention.attention_hash,
                "item_count": len(attention.items),
            },
        )
        return CyclePreparation(
            investigation_id=investigation_id,
            state=state,
            state_revision=latest.revision,
            attention_set=attention,
            active_run_id=active_run.run_id if active_run else None,
            allowed_action_types=tuple(_ALLOWED_CONTROL_ACTIONS),
        )

    # =====================================================================
    # EXECUTE (admission validation only — no real agent work, P2 §42/§43)
    # =====================================================================

    async def validate_action_batch(
        self,
        task_id: str,
        investigation_id: str,
        actions: Sequence[ControlAction],
        *,
        expected_revision: int,
    ) -> ActionBatchResult:
        runtime = await self._open_runtime(task_id)
        return await asyncio.to_thread(
            self._validate_actions_sync,
            runtime, investigation_id, tuple(actions), expected_revision,
        )

    def _validate_actions_sync(
        self,
        runtime: AgentRuntimeRepository,
        investigation_id: str,
        actions: tuple[ControlAction, ...],
        expected_revision: int,
    ) -> ActionBatchResult:
        investigation = runtime.get_investigation(investigation_id)
        if investigation is None:
            raise ValueError(f"investigation not found: {investigation_id!r}")
        latest = runtime.get_latest_working_state(investigation_id)
        active_run = self._active_run(runtime, investigation_id)
        in_flight: set[str] = set()
        if active_run is not None:
            in_flight = {
                delegation.question_ref
                for delegation in runtime.list_delegations(active_run.run_id)
                if delegation.status in (DelegationStatus.queued, DelegationStatus.running)
                and delegation.question_ref
            }
        admitted: list[ControlAction] = []
        rejected: list[RejectedAction] = []
        batch_delegation_questions: set[str] = set(in_flight)
        for action in actions:
            codes: list[str] = []
            if investigation.status is not AgentInvestigationStatus.active:
                codes.append("INVESTIGATION_NOT_ACTIVE")
            if active_run is None:
                codes.append("NO_ACTIVE_RUN")
            if latest is None or latest.revision != expected_revision:
                codes.append(STATE_REVISION_CONFLICT)
            if action.action_type not in _ALLOWED_CONTROL_ACTIONS:
                codes.append("ACTION_TYPE_NOT_ALLOWED")
            if (
                action.question_id is not None
                and latest is not None
                and working_state_from_json(
                    runtime.task_id, investigation_id, latest.state
                ).question(action.question_id)
                is None
            ):
                codes.append("QUESTION_NOT_FOUND")
            if (
                action.action_type in _DELEGATION_ACTION_TYPES
                and action.question_id is not None
                and action.question_id in batch_delegation_questions
            ):
                codes.append("DUPLICATE_ACTIVE_DELEGATION")
            if codes:
                rejected.append(RejectedAction(
                    action=action, violation_codes=tuple(codes)
                ))
            else:
                admitted.append(action)
                if (
                    action.action_type in _DELEGATION_ACTION_TYPES
                    and action.question_id is not None
                ):
                    batch_delegation_questions.add(action.question_id)
        return ActionBatchResult(
            admitted=tuple(admitted),
            rejected=tuple(rejected),
            state_revision=latest.revision if latest else None,
        )

    # =====================================================================
    # INTEGRATE (P2 §41: policy + atomic working state commit)
    # =====================================================================

    async def integrate_transitions(
        self,
        task_id: str,
        investigation_id: str,
        batch: TransitionBatch,
        *,
        expected_revision: int,
        operation_key: Optional[str] = None,
    ) -> IntegrationResult:
        runtime = await self._open_runtime(task_id)
        return await asyncio.to_thread(
            self._integrate_sync,
            runtime, investigation_id, batch, expected_revision, operation_key,
        )

    def _integrate_sync(
        self,
        runtime: AgentRuntimeRepository,
        investigation_id: str,
        batch: TransitionBatch,
        expected_revision: int,
        operation_key: Optional[str],
    ) -> IntegrationResult:
        latest = runtime.get_latest_working_state(investigation_id)
        # crash-safe replay: an operation key already committed returns the
        # original revision without re-validating against a moved head
        if operation_key is not None:
            replayed = runtime.find_revision_by_operation_key(
                investigation_id, operation_key
            )
            if replayed is not None:
                return IntegrationResult(
                    status=TransitionDecisionStatus.accepted,
                    policy_version=self._policy.policy_version,
                    state_revision=replayed.revision,
                    operation_key=operation_key,
                )
        if latest is None or latest.revision != expected_revision:
            return self._reject_integration(
                runtime, investigation_id,
                (STATE_REVISION_CONFLICT,),
                expected_revision, operation_key,
            )
        state = working_state_from_json(
            runtime.task_id, investigation_id, latest.state
        )
        ctx = TransitionPolicyContext(
            task_id=runtime.task_id,
            investigation_id=investigation_id,
            evidence_ref_resolver=self._evidence_ref_resolver(runtime),
            finding_ref_validator=self._finding_ref_validator(runtime),
            verification_checker=lambda question_id: any(
                verification.target_ref == question_id
                and verification.status.value == "passed"
                for verification in state.pending_verifications
            ),
        )
        result = self._policy.evaluate_batch(state, batch, ctx)
        if result.status is TransitionDecisionStatus.rejected:
            return self._reject_integration(
                runtime, investigation_id,
                tuple(violation.code for violation in result.violations),
                expected_revision, operation_key,
            )
        if result.status is TransitionDecisionStatus.noop:
            return IntegrationResult(
                status=result.status,
                policy_version=result.policy_version,
                state_revision=latest.revision,
                operation_key=operation_key,
            )
        try:
            revision = runtime.commit_working_state(
                investigation_id,
                working_state_to_json(result.new_state),
                expected_revision=expected_revision,
                operation_key=operation_key,
            )
        except WorkingStateRevisionConflictError:
            return self._reject_integration(
                runtime, investigation_id,
                (STATE_REVISION_CONFLICT,),
                expected_revision, operation_key,
            )
        runtime.append_trajectory(
            investigation_id,
            AgentTrajectoryEventType.transition_decision_validated,
            run_id=self._active_run_id(runtime, investigation_id),
            payload={
                "policy_version": result.policy_version,
                "noop_count": result.noop_count,
            },
        )
        runtime.append_trajectory(
            investigation_id,
            AgentTrajectoryEventType.working_state_integrated,
            run_id=self._active_run_id(runtime, investigation_id),
            payload={
                "state_revision": revision.revision,
                "operation_key": operation_key,
            },
        )
        return IntegrationResult(
            status=result.status,
            policy_version=result.policy_version,
            state_revision=revision.revision,
            operation_key=operation_key,
        )

    def _reject_integration(
        self,
        runtime: AgentRuntimeRepository,
        investigation_id: str,
        codes: tuple[str, ...],
        expected_revision: int,
        operation_key: Optional[str],
    ) -> IntegrationResult:
        runtime.append_trajectory(
            investigation_id,
            AgentTrajectoryEventType.transition_decision_rejected,
            payload={
                "violation_codes": list(codes),
                "expected_revision": expected_revision,
                "operation_key": operation_key,
            },
        )
        return IntegrationResult(
            status=TransitionDecisionStatus.rejected,
            policy_version=self._policy.policy_version,
            violations=codes,
            operation_key=operation_key,
        )

    # =====================================================================
    # EVALUATE — progress (P2 §41)
    # =====================================================================

    async def evaluate_progress(
        self, task_id: str, investigation_id: str
    ) -> ProgressEvaluation:
        runtime = await self._open_runtime(task_id)
        return await asyncio.to_thread(
            self._evaluate_progress_sync, runtime, investigation_id
        )

    def _evaluate_progress_sync(
        self, runtime: AgentRuntimeRepository, investigation_id: str
    ) -> ProgressEvaluation:
        latest = runtime.get_latest_working_state(investigation_id)
        if latest is None:
            raise AgentOrchestratorError("investigation has no committed working state")
        state = working_state_from_json(
            runtime.task_id, investigation_id, latest.state
        )
        previous = (
            runtime.get_working_state_revision(investigation_id, latest.revision - 1)
            if latest.revision > 1
            else None
        )
        previous_state = (
            working_state_from_json(
                runtime.task_id, investigation_id, previous.state
            )
            if previous is not None
            else None
        )
        snapshot = self._detector.evaluate(
            previous_state,
            state,
            previous_revision=previous.revision if previous else None,
            current_revision=latest.revision,
        )
        active_run = self._active_run(runtime, investigation_id)
        # F1: the no-progress streak lives in run-level bookkeeping and is
        # audited through trajectory events — the Working State revision is
        # never consumed by progress bookkeeping.
        streak_key = (
            runtime.task_id, investigation_id,
            active_run.run_id if active_run else "-",
        )
        verdict = self._detector.verdict(
            snapshot,
            self._no_progress_config,
            consecutive_no_progress_cycles=self._no_progress_streaks.get(streak_key, 0),
        )
        if snapshot.productive or active_run is None:
            self._no_progress_streaks.pop(streak_key, None)
        else:
            self._no_progress_streaks[streak_key] = (
                verdict.consecutive_no_progress_cycles
            )
        run_stopped = False
        if verdict.no_progress_detected:
            runtime.append_trajectory(
                investigation_id,
                AgentTrajectoryEventType.no_progress_detected,
                run_id=active_run.run_id if active_run else None,
                payload={
                    "consecutive_no_progress_cycles": (
                        verdict.consecutive_no_progress_cycles
                    ),
                    "threshold": verdict.threshold,
                    "productive": snapshot.productive,
                    "state_revision": latest.revision,
                },
            )
            if active_run is not None:
                runtime.cancel_run(active_run.run_id, stop_reason=RunStopReason.no_progress)
                self._no_progress_streaks.pop(streak_key, None)
                run_stopped = True
        elif not snapshot.productive:
            # audit every no-progress cycle (not only the detecting one)
            runtime.append_trajectory(
                investigation_id,
                AgentTrajectoryEventType.no_progress_detected,
                run_id=active_run.run_id if active_run else None,
                payload={
                    "consecutive_no_progress_cycles": (
                        verdict.consecutive_no_progress_cycles
                    ),
                    "threshold": verdict.threshold,
                    "productive": snapshot.productive,
                    "state_revision": latest.revision,
                },
            )
        return ProgressEvaluation(
            productive=snapshot.productive,
            reason_codes=snapshot.reason_codes,
            consecutive_no_progress_cycles=verdict.consecutive_no_progress_cycles,
            no_progress_detected=verdict.no_progress_detected,
            state_revision=latest.revision,
            run_stopped=run_stopped,
        )

    # =====================================================================
    # EVALUATE + COMMIT — finalization (P2 §28/§37/§38)
    # =====================================================================

    async def evaluate_finalization(
        self,
        task_id: str,
        request: FinalizationRequest,
        *,
        transition_conflict_unresolved: bool = False,
        pause_on_required_review_unavailable: bool = False,
    ) -> FinalizationDecision:
        runtime = await self._open_runtime(task_id)
        return await asyncio.to_thread(
            self._evaluate_finalization_sync,
            runtime, request, transition_conflict_unresolved,
            pause_on_required_review_unavailable,
        )

    def _runtime_view(
        self, runtime: AgentRuntimeRepository, investigation_id: str
    ) -> RuntimeFinalizationView:
        investigation = runtime.get_investigation(investigation_id)
        active_run = self._active_run(runtime, investigation_id)
        delegations = runtime.list_delegations(
            active_run.run_id
        ) if active_run else []
        active_ids = tuple(
            d.delegation_id for d in delegations
            if d.status in (DelegationStatus.queued, DelegationStatus.running)
        )
        unintegrated = tuple(
            d.delegation_id
            for run in runtime.list_runs(investigation_id)
            for d in runtime.list_delegations(run.run_id)
            if d.status is DelegationStatus.completed and d.integrated_at is None
        )
        return RuntimeFinalizationView(
            investigation_status=(
                investigation.status.value if investigation else "missing"
            ),
            store_ok=True,
            active_run_id=active_run.run_id if active_run else None,
            active_run_status=(
                active_run.status.value if active_run else None
            ),
            active_delegation_ids=active_ids,
            completed_unintegrated_delegation_ids=unintegrated,
        )

    def _evaluate_finalization_sync(
        self,
        runtime: AgentRuntimeRepository,
        request: FinalizationRequest,
        transition_conflict_unresolved: bool,
        pause_on_required_review_unavailable: bool,
    ) -> FinalizationDecision:
        investigation = runtime.get_investigation(request.investigation_id)
        if investigation is None:
            raise ValueError(
                f"investigation not found: {request.investigation_id!r}"
            )
        runtime.append_trajectory(
            request.investigation_id,
            AgentTrajectoryEventType.finalization_requested,
            payload={
                "expected_state_revision": request.expected_state_revision,
                "review_mode": request.review_mode.value,
            },
        )
        latest = runtime.get_latest_working_state(request.investigation_id)
        stale = self._gate.evaluate_stale(
            latest.revision if latest else -1, request
        )
        if stale is not None:
            runtime.append_trajectory(
                request.investigation_id,
                AgentTrajectoryEventType.finalization_stale,
                payload={"violation_codes": list(stale.violation_codes)},
            )
            return stale
        state = working_state_from_json(
            runtime.task_id, request.investigation_id, latest.state
        )
        view = self._runtime_view(runtime, request.investigation_id)
        view = view.model_copy(
            update={"transition_conflict_unresolved": transition_conflict_unresolved}
        )
        decision = self._gate.evaluate(
            runtime.task_id, state, request, view
        )
        if decision.outcome is FinalizationOutcome.deny:
            runtime.append_trajectory(
                request.investigation_id,
                AgentTrajectoryEventType.finalization_denied,
                run_id=view.active_run_id,
                payload={"violation_codes": list(decision.violation_codes)},
            )
            if (
                pause_on_required_review_unavailable
                and REVIEW_UNAVAILABLE in decision.violation_codes
            ):
                runtime.pause_investigation(
                    request.investigation_id,
                    reason=InvestigationPauseReason.finalization_review_unavailable,
                )
        return decision

    async def finalize(
        self,
        task_id: str,
        request: FinalizationRequest,
        *,
        transition_conflict_unresolved: bool = False,
    ) -> FinalizationCommitResult:
        """Evaluate the gate freshly and, on PASS, run the atomic Finalization
        Commit.  The low-level P1 ``complete_investigation()`` primitive is
        never used as a finalization pathway (P2 §38 option A)."""
        runtime = await self._open_runtime(task_id)
        return await asyncio.to_thread(
            self._finalize_sync, runtime, request, transition_conflict_unresolved
        )

    def _finalize_sync(
        self,
        runtime: AgentRuntimeRepository,
        request: FinalizationRequest,
        transition_conflict_unresolved: bool,
    ) -> FinalizationCommitResult:
        decision = self._evaluate_finalization_sync(
            runtime, request, transition_conflict_unresolved, False
        )
        if decision.outcome is not FinalizationOutcome.pass_:
            return FinalizationCommitResult(decision=decision)
        latest = runtime.get_latest_working_state(request.investigation_id)
        state = working_state_from_json(
            runtime.task_id, request.investigation_id, latest.state
        )
        view = self._runtime_view(runtime, request.investigation_id)
        record = runtime.record_finalization(
            request.investigation_id,
            run_id=view.active_run_id,
            state_revision=latest.revision,
            state_hash=latest.state_hash,
            completion_mode=(
                decision.completion_mode or CompletionMode.complete
            ).value,
            question_dispositions=question_disposition_snapshot(state),
            coverage_dispositions=coverage_disposition_snapshot(state),
            unresolved_contradictions=[
                c.contradiction_id
                for c in state.contradictions
                if c.status.value == "unresolved"
            ],
            limitations=list(decision.limitations),
            remaining_nonblocking_questions=[
                q.question_id
                for q in state.questions
                if q.priority.value != "required"
                and q.status.value in ("open", "in_progress", "deferred")
            ],
            pending_analyst_review_refs=[
                verification.target_ref
                for verification in state.pending_verifications
                if verification.status.value == "pending"
                and not verification.blocking
            ],
            final_verification_status=(
                "unavailable"
                if request.final_semantic_review.status.value == "unavailable"
                else "passed"
            ),
            verifier_result_ref=request.final_semantic_review.result_ref,
            finalization_policy_version=self._gate.policy_version,
            input_hash=finalization_input_hash(state, request, view, decision),
        )
        return FinalizationCommitResult(decision=decision, record=record)

    # =====================================================================
    # pause / cancel / run admission
    # =====================================================================

    async def pause(
        self,
        task_id: str,
        investigation_id: str,
        *,
        reason: InvestigationPauseReason = InvestigationPauseReason.user_paused,
    ):
        runtime = await self._open_runtime(task_id)
        return await asyncio.to_thread(
            runtime.pause_investigation, investigation_id, reason=reason
        )

    async def cancel(self, task_id: str, investigation_id: str):
        runtime = await self._open_runtime(task_id)
        return await asyncio.to_thread(runtime.cancel_investigation, investigation_id)

    async def admit_run(
        self, task_id: str, investigation_id: str, *, idempotency_key: Optional[str] = None
    ):
        runtime = await self._open_runtime(task_id)
        return await asyncio.to_thread(
            lambda: runtime.start_run(investigation_id, idempotency_key=idempotency_key)
        )

    # =====================================================================
    # helpers
    # =====================================================================

    @staticmethod
    def _active_run(runtime: AgentRuntimeRepository, investigation_id: str):
        for run in runtime.list_runs(investigation_id):
            if run.status in (AgentRunStatus.queued, AgentRunStatus.running):
                return run
        return None

    def _active_run_id(
        self, runtime: AgentRuntimeRepository, investigation_id: str
    ) -> Optional[str]:
        active_run = self._active_run(runtime, investigation_id)
        return active_run.run_id if active_run else None

    @staticmethod
    def _evidence_ref_resolver(runtime: AgentRuntimeRepository):
        """Deterministic resolver backed by the EXISTING evidence store —
        not a second resolver (P2 §7)."""

        def resolve(key: str) -> EvidenceRefStatus:
            try:
                parse_evidence_key(key)
            except Exception:
                return EvidenceRefStatus.malformed
            snapshot = runtime._repo.get_snapshot(key)
            return (
                EvidenceRefStatus.resolved
                if snapshot is not None
                else EvidenceRefStatus.not_found
            )

        return resolve

    @staticmethod
    def _finding_ref_validator(runtime: AgentRuntimeRepository):
        """W6/W10 seam over existing canonical object reads."""

        def validate(ref: str) -> FindingRefCheck:
            if ref.startswith("review:"):
                return FindingRefCheck(found=False, kind="review")
            if ref.startswith("ie_"):
                return FindingRefCheck(
                    found=runtime._repo.get_event(ref) is not None, kind="event"
                )
            if ref.startswith("sa_"):
                analysis = runtime._repo.get_analysis(ref)
                accepted = (
                    analysis is not None
                    and analysis.status.value == "accepted"
                )
                return FindingRefCheck(found=accepted, kind="analysis")
            return FindingRefCheck(found=False, kind=None)

        return validate
