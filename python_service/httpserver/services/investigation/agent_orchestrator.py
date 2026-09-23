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

from pydantic import BaseModel, ConfigDict, Field

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
    DelegationSpec as _P4BDelegationSpec,
    DelegationStatus,
    FinalizationRecord,
    InvestigationPauseReason,
    RunStopReason,
    WorkingStateRevisionConflictError,
    canonical_state_json,
    state_hash_of,
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


class SupervisorCyclePolicy(BaseModel):
    """Provisional cycle/loop bounds — config, never architecture-frozen
    (P4B §26; P8 calibrates the numbers)."""

    model_config = ConfigDict(frozen=True)

    max_cycles_per_invocation: int = Field(default=1, ge=1)
    max_cycles_per_run: int = Field(default=20, ge=1)
    final_review_mode: str = "best_effort"  # P4B §31: no verifier exists yet


class DelegationExecutionSummary(BaseModel):
    """Terminal summary of one dispatched delegation (dispatcher contract)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    delegation_id: str
    question_id: Optional[str] = None
    source_scope_id: Optional[str] = None
    status: str  # completed / failed / cancelled
    result: Optional[Any] = None  # SpecialistResultV1 when completed
    result_hash: Optional[str] = None
    context_hash: Optional[str] = None
    failure_code: Optional[str] = None
    failure_summary: Optional[str] = None


class CycleOutcome(BaseModel):
    """Typed result of one PLAN→EXECUTE→INTEGRATE→EVALUATE cycle (P4B §27).

    Audit/reporting data only — never a second canonical Working State."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    cycle_id: str
    investigation_id: str
    run_id: Optional[str] = None

    starting_revision: int
    ending_revision: Optional[int] = None
    attention_hash: Optional[str] = None

    plan_decision_hash: Optional[str] = None
    plan_rejected_codes: tuple[str, ...] = ()

    delegation_ids: tuple[str, ...] = ()
    delegation_terminal_statuses: tuple[str, ...] = ()

    integration_status: str = "skipped"  # committed/replayed/rejected/skipped
    integration_revision: Optional[int] = None
    integration_violation_codes: tuple[str, ...] = ()
    stale_delegation_ids: tuple[str, ...] = ()
    failure_delegation_ids: tuple[str, ...] = ()

    progress: Optional[Any] = None
    finalization: Optional[Any] = None

    run_stop_reason: Optional[str] = None
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def pack_hash_key(pack) -> str:
    """Short stable key of a planning context (admission idempotency)."""
    return pack.input_hash()[:16]


class AgentOrchestrator:
    """Deterministic control plane over the P1 agent runtime store."""

    def __init__(
        self,
        cpp_backend,
        *,
        attention_config: Optional[AttentionPolicyConfig] = None,
        no_progress_config: Optional[NoProgressPolicyConfig] = None,
        supervisor=None,
        delegation_dispatcher=None,
        source_scope_provider=None,
        directive_digest_provider=None,
        cycle_policy=None,
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
        # P4B investigation loop wiring (all optional; P2 behaviour is
        # unchanged when absent):
        self._supervisor = supervisor          # InvestigationSupervisor
        self._delegation_dispatcher = delegation_dispatcher  # async callable
        self._source_scope_provider = source_scope_provider  # callable
        self._directive_digest_provider = directive_digest_provider  # callable
        self._cycle_policy = cycle_policy or SupervisorCyclePolicy()
        # run-level directive baseline (directive re-plan seam, P4B §23) and
        # cycle bookkeeping — in-memory only, restart restarts the run
        self._run_directive_baselines: dict[tuple[str, str, str], dict[str, str]] = {}
        self._run_cycle_counts: dict[tuple[str, str, str], int] = {}
        # unresolved integration conflicts (§21): recorded when the
        # StateTransitionPolicy rejects a batch; blocks finalization until
        # an integration resolves them
        self._transition_conflicts: dict[str, set[str]] = {}

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
    # P4B: the real agent investigation loop (PLAN→EXECUTE→INTEGRATE→EVALUATE)
    # =====================================================================

    def _source_scopes(self, task_id: str) -> tuple[str, ...]:
        if self._source_scope_provider is not None:
            return tuple(self._source_scope_provider(task_id))
        return ()

    def _directive_digests(self) -> dict[str, str]:
        if self._directive_digest_provider is not None:
            return dict(self._directive_digest_provider())
        return {}

    def _failure_digest(self, summary: DelegationExecutionSummary):
        from .agent_integration import FailureDigest

        return FailureDigest(
            delegation_id=summary.delegation_id,
            question_id=summary.question_id,
            source_scope_id=summary.source_scope_id,
            terminal_status=summary.status,
            failure_code=summary.failure_code,
            failure_summary=summary.failure_summary,
            context_hash=summary.context_hash,
            result_hash=summary.result_hash,
        )

    async def execute_cycle(
        self,
        task_id: str,
        investigation_id: str,
        *,
        source_scope_ids: Sequence[str] = (),
        attention_config: Optional[AttentionPolicyConfig] = None,
    ) -> CycleOutcome:
        """One full PLAN→EXECUTE→INTEGRATE→EVALUATE cycle (P4B §25).

        The supervisor proposes; deterministic validators and the P2
        StateTransitionPolicy dispose. PLAN/EXECUTE/EVALUATE bookkeeping
        never consumes a Working State revision — only an accepted semantic
        integration does (exactly +1)."""
        import hashlib
        import uuid

        # deferred: keeps the pydantic_ai import off the ServiceManager
        # initialization path (P4A/P4B freeze lessons)
        from .agent_integration import (
            FailureDigest,
            FreshResultEnvelope,
            FrozenDelegationDependencies,
            IntegrationContextPack,
            IntegrationDecisionValidator,
            INTEGRATION_POLICY_VERSION,
            MergeGuard,
            StaleResultDigest,
            build_integration_context,
        )
        from .agent_supervisor import build_supervisor_planning_context

        cycle_id = f"cycle_{uuid.uuid4().hex[:12]}"
        runtime = await self._open_runtime(task_id)
        preparation = await self.prepare_cycle(
            task_id, investigation_id, attention_config=attention_config
        )
        starting_revision = preparation.state_revision
        run_id = preparation.active_run_id
        if run_id is None:
            run = await self.admit_run(task_id, investigation_id)
            run_id = run.run_id
        run_key = (task_id, investigation_id, run_id)
        warnings: list[str] = []
        limitations: list[str] = []

        def _outcome(**fields) -> CycleOutcome:
            latest = runtime.get_latest_working_state(investigation_id)
            fields.setdefault("ending_revision", latest.revision)
            return CycleOutcome(
                cycle_id=cycle_id,
                investigation_id=investigation_id,
                run_id=run_id,
                starting_revision=starting_revision,
                **fields,
            )

        # ---- directive re-plan boundary (P4B §23) --------------------
        digests_now = self._directive_digests()
        baseline = self._run_directive_baselines.get(run_key)
        if baseline is None:
            self._run_directive_baselines[run_key] = digests_now
        elif digests_now != baseline:
            for delegation in runtime.list_delegations(run_id):
                if delegation.status in (
                    DelegationStatus.queued, DelegationStatus.running
                ):
                    runtime.request_delegation_cancel(delegation.delegation_id)
            runtime.fail_run(
                run_id,
                stop_reason=RunStopReason.directive_replan,
                error_code=RunStopReason.directive_replan.value,
                error_message="directive digests changed during the run",
            )
            return _outcome(
                run_stop_reason=RunStopReason.directive_replan.value,
                warnings=("directive digests changed; cooperative re-plan",),
            )

        # ---- cycle budget (deterministic, P4B §26/§29) ---------------
        cycles_done = self._run_cycle_counts.get(run_key, 0)
        if cycles_done >= self._cycle_policy.max_cycles_per_run:
            runtime.fail_run(
                run_id,
                stop_reason=RunStopReason.budget_exhausted,
                error_code=RunStopReason.budget_exhausted.value,
                error_message="run cycle budget exhausted",
            )
            return _outcome(
                run_stop_reason=RunStopReason.budget_exhausted.value,
                warnings=("run cycle budget exhausted",),
            )

        # ---- PLAN -----------------------------------------------------
        if self._supervisor is None:
            return _outcome(
                warnings=("no supervisor wired; cycle skipped",),
            )
        state = preparation.state
        delegations = runtime.list_delegations(run_id)
        active_digests = [
            {
                "delegation_id": d.delegation_id,
                "question_ref": d.question_ref,
                "status": d.status.value,
            }
            for d in delegations
            if d.status in (DelegationStatus.queued, DelegationStatus.running)
        ]
        terminal_digests = [
            {
                "delegation_id": d.delegation_id,
                "question_ref": d.question_ref,
                "status": d.status.value,
                "failure_code": d.failure_code,
            }
            for d in delegations
            if d.status in (DelegationStatus.completed, DelegationStatus.failed,
                            DelegationStatus.cancelled, DelegationStatus.stale)
        ]
        planning_context = build_supervisor_planning_context(
            state,
            state_revision=preparation.state_revision,
            state_hash=self._state_hash(runtime, investigation_id),
            attention_set=preparation.attention_set,
            task_id=task_id,
            run_id=run_id,
            source_scope_ids=source_scope_ids or self._source_scopes(task_id),
            active_delegations=active_digests,
            recent_terminal_delegations=terminal_digests,
        )
        try:
            decision = await self._supervisor.plan(planning_context)
        except Exception as exc:  # noqa: BLE001 - supervisor failure is a
            # first-class cycle outcome; never an empty decision
            from .agent_specialist_executor import (
                map_provider_exception as _map,
                safe_failure_message as _safe,
            )

            code = _map(exc)
            runtime.append_trajectory(
                investigation_id,
                AgentTrajectoryEventType.transition_decision_rejected,
                run_id=run_id,
                payload={
                    "supervisor_failure": code.value,
                    "message": _safe(exc, code),
                },
            )
            return _outcome(
                warnings=(f"supervisor plan failed: {code.value}",),
            )
        from .agent_supervisor import SupervisorPlanDecisionValidator

        validation = SupervisorPlanDecisionValidator().validate(
            planning_context, decision
        )
        if not validation.valid:
            runtime.append_trajectory(
                investigation_id,
                AgentTrajectoryEventType.transition_decision_rejected,
                run_id=run_id,
                payload={
                    "violation_codes": list(validation.codes),
                    "decision_hash": decision.decision_hash(),
                },
            )
            return _outcome(
                plan_decision_hash=decision.decision_hash(),
                plan_rejected_codes=validation.codes,
                warnings=("supervisor plan rejected by validator",),
            )

        # ---- finalization request path (P4B §30/§31) ------------------
        finalize_actions = [
            action
            for action in decision.actions
            if getattr(action, "action_kind", "") == "request_finalization"
        ]
        delegate_actions = decision.delegate_actions()
        if finalize_actions and not delegate_actions:
            from .agent_finalization import (
                FinalReviewMode,
                FinalSemanticReview,
                FinalSemanticReviewStatus,
                FinalizationRequest,
            )

            if self._cycle_policy.final_review_mode == "required":
                review = FinalSemanticReview(status=FinalSemanticReviewStatus.unavailable)
                mode = FinalReviewMode.required
            else:
                review = FinalSemanticReview(
                    status=FinalSemanticReviewStatus.unavailable,
                    result_ref="semantic verifier not available in P4B",
                )
                mode = FinalReviewMode.best_effort
            request = FinalizationRequest(
                investigation_id=investigation_id,
                expected_state_revision=preparation.state_revision,
                review_mode=mode,
                final_semantic_review=review,
                run_id=run_id,
                requested_by="supervisor",
            )
            conflict = bool(self._transition_conflicts.get(investigation_id))
            result = await self.finalize(
                task_id, request, transition_conflict_unresolved=conflict
            )
            stop = None
            if result.finalized:
                stop = RunStopReason.finalized.value
            return _outcome(
                finalization=result,
                run_stop_reason=stop,
                warnings=(
                    tuple()
                    if result.finalized
                    else (
                        "finalization denied by the P2 gate; blockers recorded "
                        "for the next PLAN",
                    )
                ),
            )

        if not delegate_actions:
            return _outcome(
                plan_decision_hash=decision.decision_hash(),
                warnings=("supervisor proposed no delegations",),
            )

        # ---- atomic admission (decision + queued intents, ONE commit) --
        scopes = source_scope_ids or self._source_scopes(task_id)
        specs = []
        for action in delegate_actions:
            idem_source = (
                f"{investigation_id}:{pack_hash_key(planning_context)}:"
                f"{action.question_id}:{action.source_scope_id}"
            )
            specs.append(
                _P4BDelegationSpec(
                    question_ref=action.question_id,
                    based_on_state_revision=preparation.state_revision,
                    idempotency_key="plan:" + hashlib.sha256(
                        idem_source.encode("utf-8")
                    ).hexdigest()[:24],
                )
            )
        _event, admitted = await asyncio.to_thread(
            runtime.commit_supervisor_plan,
            run_id,
            decision_payload=decision.model_dump(),
            decision_hash=decision.decision_hash(),
            model_name=getattr(self._supervisor, "model_name", None),
            model_config_hash=getattr(self._supervisor, "model_config_hash", None),
            prompt_version="supervisor-plan-decision:v1",
            specs=specs,
        )
        # executor dispatch only AFTER the admission commit (P4B-E8)

        # ---- EXECUTE (P4A executor; all_terminal, not all_successful) --
        summaries: list[DelegationExecutionSummary] = []
        if self._delegation_dispatcher is not None:
            dispatched = await self._delegation_dispatcher(
                planning_context, decision, admitted
            )
            summaries = list(dispatched)
        else:
            warnings.append("no delegation dispatcher wired; delegations stay queued")

        # ---- MergeGuard (P4B §10) --------------------------------------
        latest = runtime.get_latest_working_state(investigation_id)
        current_state = working_state_from_json(
            task_id, investigation_id, latest.state
        )
        current_directives = {
            f"directive-{index}": digest
            for index, digest in enumerate(
                sorted(
                    state_hash_of(canonical_state_json(d.model_dump()))
                    for d in current_state.directive_refs
                )
            )
        }
        granted = scopes
        guard = MergeGuard(
            evidence_invalidation_checker=getattr(
                self, "_evidence_invalidation_checker", None
            )
        )
        fresh_envelopes = []
        stale_digests = []
        stale_ids = []
        failure_ids = []
        for summary in summaries:
            if summary.status == "completed" and summary.result is not None:
                deps = FrozenDelegationDependencies(
                    delegation_id=summary.delegation_id,
                    question_id=summary.question_id,
                    source_scope_ids=(
                        (summary.source_scope_id,) if summary.source_scope_id else ()
                    ),
                    based_on_state_revision=preparation.state_revision,
                    directive_digests=tuple(current_directives.values()),
                    evidence_refs=tuple(summary.result.iter_evidence_refs()),
                )
                verdict = guard.evaluate(
                    deps,
                    current_state=current_state,
                    current_state_revision=latest.revision,
                    current_directive_digests=current_directives,
                    granted_scope_ids=granted,
                )
                if verdict.fresh:
                    fresh_envelopes.append(
                        FreshResultEnvelope(
                            delegation_id=summary.delegation_id,
                            question_id=summary.question_id,
                            source_scope_id=summary.source_scope_id,
                            result=summary.result,
                            result_hash=summary.result_hash or "",
                            context_hash=summary.context_hash,
                        )
                    )
                else:
                    runtime.mark_completed_delegation_stale(
                        summary.delegation_id,
                        expected_result_hash=summary.result_hash or "",
                        reason_codes=verdict.reason_codes,
                    )
                    stale_digests.append(
                        StaleResultDigest(
                            delegation_id=summary.delegation_id,
                            result_hash=summary.result_hash,
                            reason_codes=verdict.reason_codes,
                        )
                    )
                    stale_ids.append(summary.delegation_id)
            else:
                failure_ids.append(summary.delegation_id)

        if not fresh_envelopes:
            return _outcome(
                plan_decision_hash=decision.decision_hash(),
                delegation_ids=tuple(s.delegation_id for s in summaries),
                delegation_terminal_statuses=tuple(s.status for s in summaries),
                stale_delegation_ids=tuple(stale_ids),
                failure_delegation_ids=tuple(failure_ids),
                integration_status="skipped",
                warnings=(
                    "no fresh results survived the MergeGuard; failure "
                    "digests recorded for the next PLAN",
                )
                + (tuple(warnings)),
            )

        # ---- INTEGRATE (supervisor proposes, policy disposes) ----------
        integration_context = build_integration_context(
            task_id=task_id,
            investigation_id=investigation_id,
            run_id=run_id,
            state=current_state,
            state_revision=latest.revision,
            state_hash=latest.state_hash,
            fresh_results=fresh_envelopes,
            stale_result_digests=stale_digests,
            failure_digests=[
                self._failure_digest(s)
                for s in summaries
                if s.status != "completed"
            ],
            attention_refs=tuple(
                action.attention_item_id for action in delegate_actions
            ),
            current_directive_digests=current_directives,
        )
        integration_decision = await self._supervisor.integrate(
            integration_context
        )
        integration_validator = IntegrationDecisionValidator(
            evidence_ref_validator=getattr(
                self, "_integration_evidence_validator", None
            )
        )
        iv = integration_validator.validate(integration_context, integration_decision)
        if not iv.valid:
            runtime.append_trajectory(
                investigation_id,
                AgentTrajectoryEventType.transition_decision_rejected,
                run_id=run_id,
                payload={
                    "violation_codes": list(iv.codes),
                    "decision_hash": integration_decision.decision_hash(),
                },
            )
            return _outcome(
                plan_decision_hash=decision.decision_hash(),
                delegation_ids=tuple(s.delegation_id for s in summaries),
                delegation_terminal_statuses=tuple(s.status for s in summaries),
                stale_delegation_ids=tuple(stale_ids),
                failure_delegation_ids=tuple(failure_ids),
                integration_status="rejected",
                integration_violation_codes=iv.codes,
                warnings=("integration decision rejected by validator",),
            )

        batch = TransitionBatch(transitions=integration_decision.transition_proposals)
        policy_result = await asyncio.to_thread(
            self._policy.evaluate_batch,
            current_state,
            batch,
            TransitionPolicyContext(
                task_id=task_id,
                investigation_id=investigation_id,
                evidence_ref_resolver=self._evidence_ref_resolver(runtime),
                finding_ref_validator=self._finding_ref_validator(runtime),
                verification_checker=lambda question_id: any(
                    verification.target_ref == question_id
                    and verification.status.value == "passed"
                    for verification in current_state.pending_verifications
                ),
            ),
        )
        if policy_result.status is TransitionDecisionStatus.rejected:
            # §21: results remain unintegrated; the conflict is explicit
            self._transition_conflicts.setdefault(investigation_id, set()).update(
                violation.code for violation in policy_result.violations
            )
            runtime.append_trajectory(
                investigation_id,
                AgentTrajectoryEventType.transition_decision_rejected,
                run_id=run_id,
                payload={
                    "violation_codes": [
                        v.code for v in policy_result.violations
                    ],
                    "stage": "state_transition_policy",
                },
            )
            return _outcome(
                plan_decision_hash=decision.decision_hash(),
                delegation_ids=tuple(s.delegation_id for s in summaries),
                delegation_terminal_statuses=tuple(s.status for s in summaries),
                stale_delegation_ids=tuple(stale_ids),
                failure_delegation_ids=tuple(failure_ids),
                integration_status="rejected",
                integration_violation_codes=tuple(
                    v.code for v in policy_result.violations
                ),
                warnings=("StateTransitionPolicy rejected the batch",),
            )

        operation_key = "integ:" + hashlib.sha256(
            (
                f"{investigation_id}:{latest.revision}:"
                + ",".join(sorted(env.result_hash for env in fresh_envelopes))
                + f":{INTEGRATION_POLICY_VERSION}"
            ).encode("utf-8")
        ).hexdigest()[:32]
        commit = await asyncio.to_thread(
            runtime.commit_agent_integration,
            investigation_id,
            expected_revision=latest.revision,
            expected_state_hash=latest.state_hash,
            operation_key=operation_key,
            integration_policy_version=INTEGRATION_POLICY_VERSION,
            decision_payload=integration_decision.model_dump(
                mode="json", exclude={"transition_proposals"}
            ),
            decision_hash=integration_decision.decision_hash(),
            delegation_integrations=[
                {
                    "delegation_id": env.delegation_id,
                    "result_hash": env.result_hash,
                }
                for env in fresh_envelopes
            ],
            new_state=(
                working_state_to_json(policy_result.new_state)
                if policy_result.status is TransitionDecisionStatus.accepted
                else None
            ),
            run_id=run_id,
        )

        # ---- EVALUATE (deterministic; never consumes a revision) -------
        progress = await self.evaluate_progress(task_id, investigation_id)
        self._run_cycle_counts[run_key] = cycles_done + 1

        return _outcome(
            plan_decision_hash=decision.decision_hash(),
            delegation_ids=tuple(s.delegation_id for s in summaries),
            delegation_terminal_statuses=tuple(s.status for s in summaries),
            stale_delegation_ids=tuple(stale_ids),
            failure_delegation_ids=tuple(failure_ids),
            integration_status=(
                "committed"
                if commit.status == "committed"
                and policy_result.status is TransitionDecisionStatus.accepted
                else "noop"
            ),
            integration_revision=commit.state_revision,
            progress=progress,
        )

    def _state_hash(self, runtime, investigation_id: str) -> str:
        latest = runtime.get_latest_working_state(investigation_id)
        return latest.state_hash if latest is not None else ""

    async def run_loop(
        self,
        task_id: str,
        investigation_id: str,
        *,
        source_scope_ids: Sequence[str] = (),
        max_cycles: Optional[int] = None,
    ) -> list[CycleOutcome]:
        """Bounded autonomous loop (P4B §26). Never `while True`: the cycle
        count is configurable and stops on terminal runs."""
        outcomes: list[CycleOutcome] = []
        budget = max_cycles or self._cycle_policy.max_cycles_per_invocation
        for _ in range(budget):
            outcome = await self.execute_cycle(
                task_id,
                investigation_id,
                source_scope_ids=source_scope_ids,
            )
            outcomes.append(outcome)
            if outcome.run_stop_reason is not None:
                break
            if outcome.finalization is not None and outcome.finalization.finalized:
                break
        return outcomes

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
