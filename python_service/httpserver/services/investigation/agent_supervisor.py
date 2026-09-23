"""InvestigationSupervisor (P4B) — the ONE investigation-level control-plane
agent (plan + integration modes; never per-platform supervisor classes).

PLAN mode (P4B-1):
    Tools = none. The supervisor reads only the frozen
    SupervisorPlanningContextPack and returns a validated
    SupervisorPlanDecisionV1. Real Evidence queries happen exclusively in
    Specialist delegations; the supervisor never touches the
    ForensicToolRegistry / EvidenceResolver / SQLite / filesystem / Graphiti.

The supervisor is a proposer, never an authority: it cannot mutate Working
State, cannot change scopes, cannot close questions, cannot accept/reject,
and cannot create canonical findings — every effect goes through
deterministic validators and the P2 StateTransitionPolicy.
"""

import enum
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .agent_attention import AttentionItem, AttentionSet
from .agent_model_adapter import build_chat_model
from .agent_runtime import canonical_state_json, state_hash_of
from .agent_working_state import AgentWorkingStateV1

SUPERVISOR_PLANNING_CONTEXT_VERSION = "supervisor-planning-context:v1"
SUPERVISOR_PLAN_DECISION_VERSION = "supervisor-plan-decision:v1"

PLAN_PHASE_CAPABILITIES: tuple[str, ...] = (
    "delegate_investigation",
    "request_finalization",
    "no_action",
)


# ---------------------------------------------------------------------------
# planning context (frozen, versioned, hashable)
# ---------------------------------------------------------------------------


class AttentionItemDigest(BaseModel):
    """One attention item projected into the planning context (no evidence
    bodies — refs and digests only)."""

    model_config = ConfigDict(frozen=True)

    item_id: str
    band: str
    eligibility: str
    title: str = ""
    related_question_ids: tuple[str, ...] = ()
    related_coverage_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    eligible_action_types: tuple[str, ...] = ()


class DelegationDigest(BaseModel):
    model_config = ConfigDict(frozen=True)

    delegation_id: str
    question_ref: Optional[str] = None
    status: str
    failure_code: Optional[str] = None


class QuestionIndexEntry(BaseModel):
    """Question identity + lifecycle status (authoritative, from state)."""

    model_config = ConfigDict(frozen=True)

    question_id: str
    status: str


class SupervisorPlanningContextPack(BaseModel):
    """Everything the PLAN supervisor may read. Raw evidence bodies, full
    tool observations, chat history and private reasoning are structurally
    absent."""

    model_config = ConfigDict(frozen=True)

    context_version: str = SUPERVISOR_PLANNING_CONTEXT_VERSION

    task_id: str
    investigation_id: str
    run_id: Optional[str] = None

    state_revision: int
    state_hash: str

    objective_digest: str = ""
    directive_digests: tuple[str, ...] = ()

    attention_policy_version: str
    attention_hash: str
    attention_items: tuple[AttentionItemDigest, ...] = ()

    question_digests: tuple[str, ...] = ()
    question_index: tuple[QuestionIndexEntry, ...] = ()
    coverage_digests: tuple[str, ...] = ()
    contradiction_digests: tuple[str, ...] = ()

    source_scope_ids: tuple[str, ...] = ()

    active_delegation_digests: tuple[DelegationDigest, ...] = ()
    recent_terminal_delegation_digests: tuple[DelegationDigest, ...] = ()

    capability_summaries: tuple[str, ...] = ()
    progress_digest: Optional[str] = None
    budget_digest: Optional[str] = None
    last_finalization_denial_digest: Optional[str] = None

    phase_capabilities: tuple[str, ...] = PLAN_PHASE_CAPABILITIES

    def input_hash(self) -> str:
        return state_hash_of(canonical_state_json(self.model_dump()))


def _state_section_digests(state: AgentWorkingStateV1) -> tuple[
    tuple[str, ...], tuple[str, ...], tuple[str, ...]
]:
    questions = tuple(
        state_hash_of(canonical_state_json(question.model_dump()))
        for question in sorted(state.questions, key=lambda q: q.question_id)
    )
    coverage = tuple(
        state_hash_of(canonical_state_json(dimension.model_dump()))
        for dimension in sorted(state.coverage, key=lambda d: d.dimension_id)
    )
    contradictions = tuple(
        state_hash_of(canonical_state_json(c.model_dump()))
        for c in sorted(
            state.contradictions, key=lambda c: c.contradiction_id
        )
    )
    return questions, coverage, contradictions


def build_supervisor_planning_context(
    state: AgentWorkingStateV1,
    *,
    state_revision: int,
    state_hash: str,
    attention_set: AttentionSet,
    task_id: str,
    run_id: Optional[str] = None,
    source_scope_ids: Sequence[str] = (),
    active_delegations: Iterable[Mapping[str, Any]] = (),
    recent_terminal_delegations: Iterable[Mapping[str, Any]] = (),
    capability_summaries: Sequence[str] = (),
    progress_digest: Optional[str] = None,
    budget_digest: Optional[str] = None,
    last_finalization_denial_digest: Optional[str] = None,
) -> SupervisorPlanningContextPack:
    """Deterministically project the current investigation into the frozen
    PLAN input. Attention remains a projection — never a second canonical
    state."""
    attention_items = tuple(
        AttentionItemDigest(
            item_id=item.item_id,
            band=item.band.value,
            eligibility=item.eligibility.value,
            title=item.title,
            related_question_ids=item.related_question_ids,
            related_coverage_refs=item.related_coverage_refs,
            evidence_refs=item.evidence_refs,
            eligible_action_types=tuple(
                action.value for action in item.eligible_action_types
            ),
        )
        for item in attention_set.items
    )
    questions, coverage, contradictions = _state_section_digests(state)
    question_index = tuple(
        QuestionIndexEntry(
            question_id=question.question_id,
            status=question.status.value,
        )
        for question in sorted(state.questions, key=lambda q: q.question_id)
    )
    return SupervisorPlanningContextPack(
        task_id=task_id,
        investigation_id=state.investigation_id,
        run_id=run_id,
        state_revision=state_revision,
        state_hash=state_hash,
        objective_digest=state.objective or "",
        directive_digests=tuple(
            state_hash_of(canonical_state_json(directive.model_dump()))
            for directive in sorted(
                state.directive_refs, key=lambda d: d.directive_ref
            )
        ),
        attention_policy_version=attention_set.policy_version,
        attention_hash=attention_set.attention_hash,
        attention_items=attention_items,
        question_digests=questions,
        question_index=question_index,
        coverage_digests=coverage,
        contradiction_digests=contradictions,
        source_scope_ids=tuple(sorted(set(source_scope_ids))),
        active_delegation_digests=tuple(
            DelegationDigest(
                delegation_id=str(d.get("delegation_id") or ""),
                question_ref=d.get("question_ref"),
                status=str(d.get("status") or ""),
                failure_code=d.get("failure_code"),
            )
            for d in sorted(
                active_delegations, key=lambda d: str(d.get("delegation_id"))
            )
        ),
        recent_terminal_delegation_digests=tuple(
            DelegationDigest(
                delegation_id=str(d.get("delegation_id") or ""),
                question_ref=d.get("question_ref"),
                status=str(d.get("status") or ""),
                failure_code=d.get("failure_code"),
            )
            for d in sorted(
                recent_terminal_delegations,
                key=lambda d: str(d.get("delegation_id")),
            )
        ),
        capability_summaries=tuple(capability_summaries),
        progress_digest=progress_digest,
        budget_digest=budget_digest,
        last_finalization_denial_digest=last_finalization_denial_digest,
    )


# ---------------------------------------------------------------------------
# structured PLAN decision
# ---------------------------------------------------------------------------


class DelegateInvestigation(BaseModel):
    """One Question × One Source Scope × bounded capability set. The
    supervisor never picks tools, skill versions, profile implementations,
    DB paths or budget internals — deterministic resolution owns those."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_kind: str = "delegate_investigation"
    action_id: str
    attention_item_id: str
    question_id: str
    source_scope_id: str
    time_scope: Optional[dict] = None
    investigation_intent: str = ""
    execution_group: Optional[str] = None


class RequestFinalization(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_kind: str = "request_finalization"
    action_id: str
    reason_code: str
    summary: str = ""


class NoPlanAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_kind: str = "no_action"
    action_id: str
    reason_code: str


PlanAction = Union[DelegateInvestigation, RequestFinalization, NoPlanAction]


class SupervisorPlanDecisionV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_version: str = SUPERVISOR_PLAN_DECISION_VERSION
    task_id: str
    investigation_id: str
    run_id: Optional[str] = None

    based_on_state_revision: int
    based_on_state_hash: str
    attention_hash: str

    actions: tuple[PlanAction, ...] = ()
    summary: str = ""
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @field_validator("actions")
    @classmethod
    def _check_actions(cls, value):
        for action in value:
            if not str(getattr(action, "action_id", "")).strip():
                raise ValueError("plan actions require a non-empty action_id")
        return value

    def decision_hash(self) -> str:
        return state_hash_of(canonical_state_json(self.model_dump()))

    def delegate_actions(self) -> tuple[DelegateInvestigation, ...]:
        return tuple(
            action
            for action in self.actions
            if isinstance(action, DelegateInvestigation)
        )


# ---------------------------------------------------------------------------
# deterministic decision validation
# ---------------------------------------------------------------------------


class PlanViolationCode(str, enum.Enum):
    PLAN_VERSION_UNSUPPORTED = "PLAN_VERSION_UNSUPPORTED"
    PLAN_IDENTITY_MISMATCH = "PLAN_IDENTITY_MISMATCH"
    PLAN_STATE_REVISION_STALE = "PLAN_STATE_REVISION_STALE"
    PLAN_ATTENTION_HASH_MISMATCH = "PLAN_ATTENTION_HASH_MISMATCH"
    PLAN_ATTENTION_ITEM_UNKNOWN = "PLAN_ATTENTION_ITEM_UNKNOWN"
    PLAN_ATTENTION_ITEM_INELIGIBLE = "PLAN_ATTENTION_ITEM_INELIGIBLE"
    PLAN_QUESTION_UNKNOWN = "PLAN_QUESTION_UNKNOWN"
    PLAN_QUESTION_INACTIVE = "PLAN_QUESTION_INACTIVE"
    PLAN_SOURCE_SCOPE_NOT_ALLOWED = "PLAN_SOURCE_SCOPE_NOT_ALLOWED"
    PLAN_DUPLICATE_DELEGATION = "PLAN_DUPLICATE_DELEGATION"
    PLAN_ACTION_NOT_ALLOWED = "PLAN_ACTION_NOT_ALLOWED"
    PLAN_BUDGET_EXCEEDED = "PLAN_BUDGET_EXCEEDED"


class PlanViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: PlanViolationCode
    message: str
    location: str = ""


class SupervisorPlanValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    violations: tuple[PlanViolation, ...] = ()

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(v.code.value for v in self.violations)


class SupervisorPlanPolicy(BaseModel):
    """Configurable admission knobs (provisional defaults; P8 calibrates)."""

    model_config = ConfigDict(frozen=True)

    max_admissions_per_cycle: int = Field(default=4, ge=1)
    allowed_action_kinds: tuple[str, ...] = (
        "delegate_investigation",
        "request_finalization",
        "no_action",
    )


class SupervisorPlanDecisionValidator:
    """Deterministic gate between the supervisor's proposal and admission.

    Rejects unsupported versions, stale state/attention bindings, unknown
    questions, cross-scope proposals, duplicate delegation fingerprints and
    any action kind outside the frozen P4B phase capabilities. It never
    corrects the supervisor's intent — accept or reject only.
    """

    def __init__(self, policy: Optional[SupervisorPlanPolicy] = None):
        self._policy = policy or SupervisorPlanPolicy()

    def validate(
        self,
        pack: SupervisorPlanningContextPack,
        decision: SupervisorPlanDecisionV1,
    ) -> SupervisorPlanValidation:
        violations: list[PlanViolation] = []

        if decision.decision_version != SUPERVISOR_PLAN_DECISION_VERSION:
            violations.append(PlanViolation(
                code=PlanViolationCode.PLAN_VERSION_UNSUPPORTED,
                message="unsupported plan decision version",
                location="decision_version",
            ))
        if (
            decision.task_id != pack.task_id
            or decision.investigation_id != pack.investigation_id
            or decision.run_id != pack.run_id
        ):
            violations.append(PlanViolation(
                code=PlanViolationCode.PLAN_IDENTITY_MISMATCH,
                message="decision identity does not match the planning context",
                location="identity",
            ))
        if (
            decision.based_on_state_revision != pack.state_revision
            or decision.based_on_state_hash != pack.state_hash
        ):
            violations.append(PlanViolation(
                code=PlanViolationCode.PLAN_STATE_REVISION_STALE,
                message="decision is bound to a different working state",
                location="based_on_state_revision",
            ))
        if decision.attention_hash != pack.attention_hash:
            violations.append(PlanViolation(
                code=PlanViolationCode.PLAN_ATTENTION_HASH_MISMATCH,
                message="decision attention hash does not match the window",
                location="attention_hash",
            ))

        items = {item.item_id: item for item in pack.attention_items}
        active_pairs = {
            (d.question_ref, None)
            for d in pack.active_delegation_digests
        }
        fingerprint_pairs = {
            (d.question_ref, d.status)
            for d in pack.active_delegation_digests
        } | {
            (d.question_ref, d.status)
            for d in pack.recent_terminal_delegation_digests
        }
        admitted_fingerprints = {
            (d.question_ref, d.delegation_id)
            for d in pack.active_delegation_digests
        }
        seen_plan_fingerprints: set[tuple[str, str]] = set()
        delegate_count = 0
        active_count = len(pack.active_delegation_digests)

        for index, action in enumerate(decision.actions):
            location = f"actions[{index}]"
            kind = getattr(action, "action_kind", None)
            if kind not in self._policy.allowed_action_kinds:
                violations.append(PlanViolation(
                    code=PlanViolationCode.PLAN_ACTION_NOT_ALLOWED,
                    message=f"action kind {kind!r} is not a P4B capability",
                    location=location,
                ))
                continue
            if kind == "delegate_investigation":
                delegate_count += 1
                item = items.get(action.attention_item_id)
                if item is None:
                    violations.append(PlanViolation(
                        code=PlanViolationCode.PLAN_ATTENTION_ITEM_UNKNOWN,
                        message="delegation references an attention item "
                        "outside this window",
                        location=location,
                    ))
                else:
                    if item.eligibility != "eligible":
                        violations.append(PlanViolation(
                            code=PlanViolationCode.PLAN_ATTENTION_ITEM_INELIGIBLE,
                            message="attention item is blocked or suppressed",
                            location=location,
                        ))
                    if "delegate_source" not in item.eligible_action_types:
                        violations.append(PlanViolation(
                            code=PlanViolationCode.PLAN_ATTENTION_ITEM_INELIGIBLE,
                            message="attention item does not admit source "
                            "delegation",
                            location=location,
                        ))
                question_status = self._question_status(pack, action.question_id)
                if question_status is None:
                    violations.append(PlanViolation(
                        code=PlanViolationCode.PLAN_QUESTION_UNKNOWN,
                        message="delegation references an unknown question",
                        location=location,
                    ))
                elif question_status not in ("open", "in_progress"):
                    violations.append(PlanViolation(
                        code=PlanViolationCode.PLAN_QUESTION_INACTIVE,
                        message="delegation references an inactive question",
                        location=location,
                    ))
                if (
                    pack.source_scope_ids
                    and action.source_scope_id not in pack.source_scope_ids
                ):
                    violations.append(PlanViolation(
                        code=PlanViolationCode.PLAN_SOURCE_SCOPE_NOT_ALLOWED,
                        message="proposed source scope is outside this "
                        "investigation's grant",
                        location=location,
                    ))
                fingerprint = (action.question_id, action.source_scope_id)
                if fingerprint in seen_plan_fingerprints:
                    violations.append(PlanViolation(
                        code=PlanViolationCode.PLAN_DUPLICATE_DELEGATION,
                        message="duplicate question x scope in one plan",
                        location=location,
                    ))
                seen_plan_fingerprints.add(fingerprint)
                if any(
                    pair[0] == action.question_id
                    for pair in active_pairs
                    if pair[0]
                ):
                    violations.append(PlanViolation(
                        code=PlanViolationCode.PLAN_DUPLICATE_DELEGATION,
                        message="a delegation for this question is already "
                        "in flight",
                        location=location,
                    ))
            elif kind == "request_finalization":
                if not str(getattr(action, "reason_code", "")).strip():
                    violations.append(PlanViolation(
                        code=PlanViolationCode.PLAN_ACTION_NOT_ALLOWED,
                        message="request_finalization requires a reason code",
                        location=location,
                    ))
            elif kind == "no_action":
                if not str(getattr(action, "reason_code", "")).strip():
                    violations.append(PlanViolation(
                        code=PlanViolationCode.PLAN_ACTION_NOT_ALLOWED,
                        message="no_action requires a reason code",
                        location=location,
                    ))

        if delegate_count and (
            active_count + delegate_count
            > self._policy.max_admissions_per_cycle
        ):
            violations.append(PlanViolation(
                code=PlanViolationCode.PLAN_BUDGET_EXCEEDED,
                message="admission budget exceeded for this cycle",
                location="actions",
            ))

        return SupervisorPlanValidation(
            valid=not violations, violations=tuple(violations)
        )

    @staticmethod
    def _question_status(
        pack: SupervisorPlanningContextPack, question_id: str
    ) -> Optional[str]:
        for entry in pack.question_index:
            if entry.question_id == question_id:
                return entry.status
        return None


# ---------------------------------------------------------------------------
# the one logical supervisor (plan + integration modes)
# ---------------------------------------------------------------------------


class SupervisorAgentFactory:
    """Builds the PLAN-mode PydanticAI agent for the single logical
    supervisor. Tools = none in every mode."""

    def __init__(self, *, model=None, settings=None):
        if model is not None:
            self._model = model
        elif settings is not None:
            self._model = build_chat_model(settings)
        else:
            raise ValueError(
                "SupervisorAgentFactory requires an explicit model or settings"
            )

    def build_plan_agent(self, planning_context) -> Any:
        from pydantic_ai import Agent

        return Agent(
            self._model,
            output_type=SupervisorPlanDecisionV1,
            instructions=[_planning_instructions(planning_context)],
        )

    def build_integration_agent(self, integration_context) -> Any:
        """Integration mode: same logical supervisor, Tools = none, typed
        SupervisorIntegrationDecisionV1 output (P4B §13)."""
        from pydantic_ai import Agent

        from .agent_integration import SupervisorIntegrationDecisionV1

        return Agent(
            self._model,
            output_type=SupervisorIntegrationDecisionV1,
            instructions=[_integration_instructions(integration_context)],
        )


def _integration_instructions(context) -> str:
    from .agent_integration import INTEGRATION_POLICY_VERSION

    return (
        "You are the investigation supervisor in INTEGRATION mode. You have "
        "NO tools. Read the frozen integration context (fresh validated "
        "specialist results, stale digests, failure digests) and return one "
        "structured integration decision with typed transition proposals "
        "only.\n\n"
        f"{canonical_state_json(context.model_dump())}\n\n"
        "Rules: never emit a complete working state, JSON patch, SQL, "
        "canonical claim, review decision, graph or report mutation. Bind "
        "every proposal to the current state revision."
    )


def _planning_instructions(pack: SupervisorPlanningContextPack) -> str:
    return (
        "You are the investigation supervisor. You have NO tools.\n"
        "Read the frozen planning context and return one structured "
        "supervisor plan decision.\n\n"
        f"{canonical_state_json(pack.model_dump())}\n\n"
        "Rules: delegate_investigation actions must reference an eligible "
        "attention item, an active question and an allowed source scope. "
        "request_finalization and no_action require a reason code. Return "
        "proposals only."
    )


class InvestigationSupervisor:
    """The single investigation-level supervisor (PLAN mode here; the
    integration mode joins in P4B-2 through the same object)."""

    def __init__(
        self,
        *,
        model=None,
        settings=None,
        validator: Optional[SupervisorPlanDecisionValidator] = None,
    ):
        if model is not None:
            self._model = model
        elif settings is not None:
            self._model = build_chat_model(settings)
        else:
            raise ValueError("supervisor requires an explicit model or settings")
        self._validator = validator or SupervisorPlanDecisionValidator()

    async def plan(
        self, planning_context: SupervisorPlanningContextPack
    ) -> SupervisorPlanDecisionV1:
        agent = SupervisorAgentFactory(model=self._model).build_plan_agent(
            planning_context
        )
        result = await agent.run(planning_context.objective_digest or "plan")
        return result.output

    async def integrate(self, context):
        agent = SupervisorAgentFactory(model=self._model).build_integration_agent(
            context
        )
        result = await agent.run(
            f"integrate at state revision {context.state_revision}"
        )
        return result.output

    def validate(
        self,
        pack: SupervisorPlanningContextPack,
        decision: SupervisorPlanDecisionV1,
    ) -> SupervisorPlanValidation:
        return self._validator.validate(pack, decision)


__all__ = [
    "DelegateInvestigation",
    "InvestigationSupervisor",
    "NoPlanAction",
    "PLAN_PHASE_CAPABILITIES",
    "PlanViolation",
    "PlanViolationCode",
    "RequestFinalization",
    "SUPERVISOR_PLAN_DECISION_VERSION",
    "SUPERVISOR_PLANNING_CONTEXT_VERSION",
    "SupervisorAgentFactory",
    "SupervisorPlanDecisionV1",
    "SupervisorPlanDecisionValidator",
    "SupervisorPlanPolicy",
    "SupervisorPlanValidation",
    "SupervisorPlanningContextPack",
    "build_supervisor_planning_context",
]
