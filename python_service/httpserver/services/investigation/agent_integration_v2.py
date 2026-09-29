"""A1 supervisor integration contract v2 — handle-based proposals.

Model-facing contracts where the supervisor expresses SEMANTIC decisions
only: every identity field is either gone (task/investigation/run ids,
state revision+hash, attention hash, delegation UUID + result-hash echo)
or replaced by server-issued handles (E1/Q2/D3/COV1/F1/P1/H1/X1/A1).

The resolver in this module turns a v2 proposal into the CANONICAL v1
decision object (identity fields injected from the frozen context) which
then flows through the unchanged IntegrationDecisionValidator,
StateTransitionPolicy and commit path.  v2 is a model/runtime interface;
v1 stays the control-plane authority (A1 §12).

Fail-closed: unknown handles, wrong-kind handles, foreign tables and
unresolvable canonical refs reject the WHOLE proposal.  The resolver
never repairs, guesses, normalizes, auto-closes or fills basis handles.
"""

from __future__ import annotations

import enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .agent_attention import AttentionSet  # noqa: F401  (type re-export)
from .agent_integration import (
    FreshResultEnvelope,
    IntegrationContextPack,
    SupervisorIntegrationDecisionV1,
)
from .agent_reference_bindings import (
    BindingKind,
    ReferenceBindingTableV1,
)
from .agent_runtime import canonical_state_json, state_hash_of
from .agent_supervisor import (
    DelegateInvestigation,
    NoPlanAction,
    RequestFinalization,
    SupervisorPlanDecisionV1,
    SupervisorPlanningContextPack,
)
from .agent_transitions import (
    AddFindingReference,
    AddPendingProposalReference,
    ContradictionTransition,
    CoverageTransition,
    CreateContradiction,
    CreateHypothesis,
    CreateQuestion,
    EvidenceRelevanceTransition,
    HypothesisTransition,
    QuestionTransition,
)
from .agent_working_state import (
    AgentWorkingStateV1,
    Contradiction,
    ContradictionSeverity,
    ContradictionStatus,
    CoverageStatus,
    EvidenceRelevanceStatus,
    Hypothesis,
    HypothesisStatus,
    QuestionDisposition,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
)

INTEGRATION_DECISION_VERSION_V2 = "supervisor-integration-decision:v2"
# A1-H: typed model-facing handle contract epoch (kind-constrained
# operand fields + availability projection).  The supervisor CONTRACT
# version (env-selected v2 handle contract vs v1) is unchanged.
INTEGRATION_DECISION_VERSION_V3 = "supervisor-integration-decision:v3"
INTEGRATION_DECISION_VERSION = INTEGRATION_DECISION_VERSION_V3
PLAN_DECISION_VERSION_V2 = "supervisor-plan-decision:v2"


# ---------------------------------------------------------------------------
# A1-H typed model-facing handles (§11/§12): the schema itself restricts
# every operand to handles of the kind the resolver will accept.  Static
# kind discipline only — existence/context/canonical binding stay with
# the fail-closed ReferenceBindingResolver (§13/§14).
# ---------------------------------------------------------------------------

from typing import Annotated as _Annotated  # noqa: E402
from pydantic import StringConstraints as _StringConstraints  # noqa: E402

EvidenceHandle = _Annotated[str, _StringConstraints(pattern=r"^E\d+$")]
QuestionHandle = _Annotated[str, _StringConstraints(pattern=r"^Q\d+$")]
CoverageHandle = _Annotated[str, _StringConstraints(pattern=r"^COV\d+$")]
HypothesisHandle = _Annotated[str, _StringConstraints(pattern=r"^H\d+$")]
ContradictionHandle = _Annotated[str, _StringConstraints(pattern=r"^X\d+$")]
FindingHandle = _Annotated[str, _StringConstraints(pattern=r"^F\d+$")]
ProposalHandle = _Annotated[str, _StringConstraints(pattern=r"^P\d+$")]


# ---------------------------------------------------------------------------
# v2 integration actions (semantic choices; identity via handles only)
# ---------------------------------------------------------------------------


class _ActionV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class UpdateQuestionActionV2(_ActionV2):
    action_type: Literal["update_question"] = "update_question"
    question_handle: QuestionHandle
    to_status: QuestionStatus
    disposition: Optional[QuestionDisposition] = None
    basis_handles: Optional[tuple[EvidenceHandle, ...]] = None
    limitations: Optional[tuple[str, ...]] = None
    investigated_summary: Optional[str] = None
    blocker: Optional[str] = None
    superseded_by_handle: Optional[QuestionHandle] = None


class CreateQuestionActionV2(_ActionV2):
    action_type: Literal["create_question"] = "create_question"
    text: str = Field(min_length=1)
    source: QuestionSource = QuestionSource.supervisor_discovery
    priority: QuestionPriority = QuestionPriority.high
    parent_question_handle: Optional[QuestionHandle] = None


class UpdateEvidenceRelevanceActionV2(_ActionV2):
    action_type: Literal["update_evidence_relevance"] = (
        "update_evidence_relevance"
    )
    evidence_handle: EvidenceHandle
    to_status: EvidenceRelevanceStatus
    related_question_handles: Optional[tuple[QuestionHandle, ...]] = None


class CreateHypothesisActionV2(_ActionV2):
    action_type: Literal["create_hypothesis"] = "create_hypothesis"
    text: str = Field(min_length=1)
    supporting_handles: tuple[EvidenceHandle, ...] = ()


class UpdateHypothesisActionV2(_ActionV2):
    action_type: Literal["update_hypothesis"] = "update_hypothesis"
    hypothesis_handle: HypothesisHandle
    to_status: HypothesisStatus


class CreateContradictionActionV2(_ActionV2):
    action_type: Literal["create_contradiction"] = "create_contradiction"
    severity: ContradictionSeverity
    refs_handles: tuple[EvidenceHandle, ...] = ()
    attempted_resolution: Optional[str] = None
    impact: Optional[str] = None
    limitation: Optional[str] = None


class UpdateContradictionActionV2(_ActionV2):
    action_type: Literal["update_contradiction"] = "update_contradiction"
    contradiction_handle: ContradictionHandle
    to_status: ContradictionStatus
    resolution_basis_handles: Optional[tuple[EvidenceHandle, ...]] = None
    attempted_resolution: Optional[str] = None
    impact: Optional[str] = None
    limitation: Optional[str] = None


class UpdateCoverageActionV2(_ActionV2):
    action_type: Literal["update_coverage"] = "update_coverage"
    coverage_handle: CoverageHandle
    to_status: CoverageStatus
    basis_handles: Optional[tuple[EvidenceHandle, ...]] = None
    limitation: Optional[str] = None
    capability_basis: Optional[str] = None
    related_question_handles: Optional[tuple[QuestionHandle, ...]] = None


class AddFindingReferenceActionV2(_ActionV2):
    action_type: Literal["add_finding_reference"] = "add_finding_reference"
    finding_handle: FindingHandle


class AddPendingProposalReferenceActionV2(_ActionV2):
    action_type: Literal["add_pending_proposal_reference"] = (
        "add_pending_proposal_reference"
    )
    proposal_handle: ProposalHandle


IntegrationActionV2 = Union[
    UpdateQuestionActionV2,
    CreateQuestionActionV2,
    UpdateEvidenceRelevanceActionV2,
    CreateHypothesisActionV2,
    UpdateHypothesisActionV2,
    CreateContradictionActionV2,
    UpdateContradictionActionV2,
    UpdateCoverageActionV2,
    AddFindingReferenceActionV2,
    AddPendingProposalReferenceActionV2,
]


class SupervisorIntegrationDecisionV2(BaseModel):
    """Model-facing integration proposal: semantic actions over handles.

    Structurally absent (spec §7/§30 — the server injects them):
    task_id, investigation_id, run_id, based_on_state_revision,
    based_on_state_hash, source_result_ids, source_result_hashes,
    attention_hash, plan canonical ids, working-state revision echoes,
    canonical evidence keys, question ids, coverage dimension names,
    delegation UUIDs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_version: str = INTEGRATION_DECISION_VERSION
    actions: tuple[IntegrationActionV2, ...] = ()
    integration_summary: str = ""
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# v2 plan actions
# ---------------------------------------------------------------------------


class DelegateInvestigationActionV2(_ActionV2):
    action_type: Literal["delegate_investigation"] = (
        "delegate_investigation"
    )
    action_id: str = ""  # server-assigned when empty (label, not identity)
    attention_handle: str
    question_handle: str
    source_scope_id: str
    time_scope: Optional[dict] = None
    investigation_intent: str = ""
    execution_group: Optional[str] = None


class RequestFinalizationActionV2(_ActionV2):
    action_type: Literal["request_finalization"] = "request_finalization"
    action_id: str = ""
    reason_code: str
    summary: str = ""


class NoPlanActionV2(_ActionV2):
    action_type: Literal["no_action"] = "no_action"
    action_id: str = ""
    reason_code: str


PlanActionV2 = Union[
    DelegateInvestigationActionV2,
    RequestFinalizationActionV2,
    NoPlanActionV2,
]


class SupervisorPlanDecisionV2(BaseModel):
    """Model-facing plan proposal: attention/question handles; no
    identity/revision/state-hash/attention-hash echo (A1 §20/§21)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_version: str = PLAN_DECISION_VERSION_V2
    actions: tuple[PlanActionV2, ...] = ()
    summary: str = ""
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# resolution failures (fail-closed; no repair, A1 §10/§11/§25)
# ---------------------------------------------------------------------------


class ResolutionViolationCode(str, enum.Enum):
    RESOLUTION_VERSION_UNSUPPORTED = "RESOLUTION_VERSION_UNSUPPORTED"
    HANDLE_UNKNOWN = "HANDLE_UNKNOWN"
    HANDLE_KIND_MISMATCH = "HANDLE_KIND_MISMATCH"
    HANDLE_CONTEXT_MISMATCH = "HANDLE_CONTEXT_MISMATCH"
    RESOLUTION_INTERNAL = "RESOLUTION_INTERNAL"


class ResolutionViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: ResolutionViolationCode
    message: str
    location: str = ""


class ResolutionRecord(BaseModel):
    """Audit artefact (A1 §22): what the model chose, what the server
    bound it to, per action.  Persisted beside the policy verdict."""

    model_config = ConfigDict(frozen=True)

    contract_version: str
    binding_table_id: str
    actions_total: int
    resolved_action_summaries: tuple[str, ...] = ()
    violations: tuple[ResolutionViolation, ...] = ()
    ok: bool = False


def _resolve_handles(
    table: ReferenceBindingTableV1,
    handles: tuple[str, ...],
    expected_kind: BindingKind,
    location: str,
    violations: list[ResolutionViolation],
) -> tuple[str, ...]:
    resolved: list[str] = []
    for index, handle in enumerate(handles):
        binding = table.by_handle(handle)
        if binding is None:
            violations.append(
                ResolutionViolation(
                    code=ResolutionViolationCode.HANDLE_UNKNOWN,
                    message=f"handle {handle!r} is not in the binding table",
                    location=f"{location}[{index}]",
                )
            )
            continue
        if binding.kind is not expected_kind:
            violations.append(
                ResolutionViolation(
                    code=ResolutionViolationCode.HANDLE_KIND_MISMATCH,
                    message=(
                        f"handle {handle!r} is a {binding.kind.value}, "
                        f"expected {expected_kind.value}"
                    ),
                    location=f"{location}[{index}]",
                )
            )
            continue
        resolved.append(binding.canonical_ref)
    return tuple(resolved)


def _resolve_one(
    table: ReferenceBindingTableV1,
    handle: str,
    expected_kind: BindingKind,
    location: str,
    violations: list[ResolutionViolation],
) -> Optional[str]:
    binding = table.by_handle(handle)
    if binding is None:
        violations.append(
            ResolutionViolation(
                code=ResolutionViolationCode.HANDLE_UNKNOWN,
                message=f"handle {handle!r} is not in the binding table",
                location=location,
            )
        )
        return None
    if binding.kind is not expected_kind:
        violations.append(
            ResolutionViolation(
                code=ResolutionViolationCode.HANDLE_KIND_MISMATCH,
                message=(
                    f"handle {handle!r} is a {binding.kind.value}, "
                    f"expected {expected_kind.value}"
                ),
                location=location,
            )
        )
        return None
    return binding.canonical_ref


def _server_assigned_id(prefix: str, payload: Any) -> str:
    return f"{prefix}-{state_hash_of(canonical_state_json(payload))[:8]}"


def _check_table_scope(
    table: ReferenceBindingTableV1,
    *,
    task_id: str,
    investigation_id: str,
    run_id: Optional[str],
    violations: list[ResolutionViolation],
) -> bool:
    if (
        table.task_id != task_id
        or table.investigation_id != investigation_id
        or table.run_id != run_id
    ):
        violations.append(
            ResolutionViolation(
                code=ResolutionViolationCode.HANDLE_CONTEXT_MISMATCH,
                message="binding table does not belong to this context",
                location="binding_table",
            )
        )
        return False
    return True


def resolve_integration_proposal_v2(
    decision: SupervisorIntegrationDecisionV2,
    table: ReferenceBindingTableV1,
    context: IntegrationContextPack,
    state: AgentWorkingStateV1,
) -> tuple[
    Optional[SupervisorIntegrationDecisionV1],
    ResolutionRecord,
]:
    """Resolve a v2 integration proposal into the CANONICAL v1 decision.

    Any violation rejects the whole proposal (fail-closed, all-or-
    nothing — same semantics as the v1 validator).  The resolver never
    picks dispositions and never fills basis handles (A1 §26): a
    basis-requiring closure with ``basis_handles=[]`` resolves to an
    empty ``basis_refs`` and still fails the unchanged
    QUESTION_CLOSURE_BASIS_REQUIRED gate.
    """
    violations: list[ResolutionViolation] = []
    summaries: list[str] = []

    if decision.decision_version != INTEGRATION_DECISION_VERSION:
        violations.append(
            ResolutionViolation(
                code=ResolutionViolationCode.RESOLUTION_VERSION_UNSUPPORTED,
                message="unsupported v2 integration decision version",
                location="decision_version",
            )
        )
    _check_table_scope(
        table,
        task_id=context.task_id,
        investigation_id=context.investigation_id,
        run_id=context.run_id,
        violations=violations,
    )
    if table.context_hash != context.input_hash():
        violations.append(
            ResolutionViolation(
                code=ResolutionViolationCode.HANDLE_CONTEXT_MISMATCH,
                message="binding table was not derived from this frozen "
                "integration context",
                location="binding_table",
            )
        )

    transitions: list[Any] = []
    for index, action in enumerate(decision.actions):
        location = f"actions[{index}]({action.action_type})"
        try:
            transition = _resolve_integration_action(
                action, table, state, location, violations
            )
        except Exception as exc:  # noqa: BLE001 — fail closed on surprises
            violations.append(
                ResolutionViolation(
                    code=ResolutionViolationCode.RESOLUTION_INTERNAL,
                    message=f"{type(exc).__name__}: {exc}"[:200],
                    location=location,
                )
            )
            transition = None
        if transition is not None:
            transitions.append(transition)
            summaries.append(str(action.action_type))

    record = ResolutionRecord(
        contract_version=decision.decision_version,
        binding_table_id=table.binding_table_id,
        actions_total=len(decision.actions),
        resolved_action_summaries=tuple(summaries),
        violations=tuple(violations),
        ok=not violations,
    )
    if violations:
        return None, record

    canonical = SupervisorIntegrationDecisionV1(
        # trusted identity injected from the frozen context (A1 §7/§12)
        task_id=context.task_id,
        investigation_id=context.investigation_id,
        run_id=context.run_id,
        based_on_state_revision=context.state_revision,
        based_on_state_hash=context.state_hash,
        source_result_ids=tuple(
            env.delegation_id
            for env in sorted(
                context.fresh_results, key=lambda e: e.delegation_id
            )
        ),
        source_result_hashes=tuple(
            env.result_hash
            for env in sorted(
                context.fresh_results, key=lambda e: e.delegation_id
            )
        ),
        transition_proposals=tuple(transitions),
        integration_summary=decision.integration_summary,
        limitations=decision.limitations,
        warnings=decision.warnings,
    )
    return canonical, record


def _resolve_integration_action(
    action: IntegrationActionV2,
    table: ReferenceBindingTableV1,
    state: AgentWorkingStateV1,
    location: str,
    violations: list[ResolutionViolation],
) -> Optional[Any]:
    if isinstance(action, UpdateQuestionActionV2):
        question_id = _resolve_one(
            table, action.question_handle, BindingKind.question,
            f"{location}.question_handle", violations,
        )
        # None (omitted) keeps the current basis; an EXPLICIT empty list
        # resolves to () so the unchanged CLOSURE_BASIS_REQUIRED fires.
        basis: Optional[tuple[str, ...]] = None
        if action.basis_handles is not None:
            basis = _resolve_handles(
                table, action.basis_handles, BindingKind.evidence,
                f"{location}.basis_handles", violations,
            )
        superseded_by = None
        if action.superseded_by_handle is not None:
            superseded_by = _resolve_one(
                table, action.superseded_by_handle, BindingKind.question,
                f"{location}.superseded_by_handle", violations,
            )
        if violations:
            return None
        return QuestionTransition(
            question_id=question_id,
            to_status=action.to_status,
            disposition=action.disposition,
            basis_refs=basis,
            limitations=action.limitations,
            investigated_summary=action.investigated_summary,
            blocker=action.blocker,
            superseded_by_ref=superseded_by,
        )

    if isinstance(action, CreateQuestionActionV2):
        parent_id = None
        if action.parent_question_handle is not None:
            parent_id = _resolve_one(
                table, action.parent_question_handle, BindingKind.question,
                f"{location}.parent_question_handle", violations,
            )
        if violations:
            return None
        question_id = _server_assigned_id(
            "q",
            {
                "text": action.text,
                "source": action.source.value,
                "priority": action.priority.value,
                "parent": parent_id,
            },
        )
        if state.question(question_id) is not None:  # pragma: no cover
            violations.append(
                ResolutionViolation(
                    code=ResolutionViolationCode.RESOLUTION_INTERNAL,
                    message="server-assigned question id collision",
                    location=location,
                )
            )
            return None
        return CreateQuestion(
            question=WorkingQuestion(
                question_id=question_id,
                text=action.text,
                source=action.source,
                priority=action.priority,
                parent_question_id=parent_id,
            )
        )

    if isinstance(action, UpdateEvidenceRelevanceActionV2):
        evidence_key = _resolve_one(
            table, action.evidence_handle, BindingKind.evidence,
            f"{location}.evidence_handle", violations,
        )
        related: Optional[tuple[str, ...]] = None
        if action.related_question_handles is not None:
            related = _resolve_handles(
                table, action.related_question_handles,
                BindingKind.question,
                f"{location}.related_question_handles", violations,
            )
        if violations:
            return None
        return EvidenceRelevanceTransition(
            evidence_key=evidence_key,
            to_status=action.to_status,
            related_question_ids=related,
        )

    if isinstance(action, CreateHypothesisActionV2):
        supporting = _resolve_handles(
            table, action.supporting_handles, BindingKind.evidence,
            f"{location}.supporting_handles", violations,
        )
        if violations:
            return None
        hypothesis_id = _server_assigned_id("h", {"text": action.text})
        return CreateHypothesis(
            hypothesis=Hypothesis(
                hypothesis_id=hypothesis_id,
                text=action.text,
                supporting_refs=supporting,
            )
        )

    if isinstance(action, UpdateHypothesisActionV2):
        hypothesis_id = _resolve_one(
            table, action.hypothesis_handle, BindingKind.hypothesis,
            f"{location}.hypothesis_handle", violations,
        )
        if violations:
            return None
        return HypothesisTransition(
            hypothesis_id=hypothesis_id, to_status=action.to_status
        )

    if isinstance(action, CreateContradictionActionV2):
        refs = _resolve_handles(
            table, action.refs_handles, BindingKind.evidence,
            f"{location}.refs_handles", violations,
        )
        if violations:
            return None
        contradiction_id = _server_assigned_id(
            "x", {"refs": refs, "impact": action.impact}
        )
        return CreateContradiction(
            contradiction=Contradiction(
                contradiction_id=contradiction_id,
                severity=action.severity,
                refs=refs,
                attempted_resolution=action.attempted_resolution,
                impact=action.impact,
                limitation=action.limitation,
            )
        )

    if isinstance(action, UpdateContradictionActionV2):
        contradiction_id = _resolve_one(
            table, action.contradiction_handle, BindingKind.contradiction,
            f"{location}.contradiction_handle", violations,
        )
        basis: Optional[tuple[str, ...]] = None
        if action.resolution_basis_handles is not None:
            basis = _resolve_handles(
                table, action.resolution_basis_handles,
                BindingKind.evidence,
                f"{location}.resolution_basis_handles", violations,
            )
        if violations:
            return None
        return ContradictionTransition(
            contradiction_id=contradiction_id,
            to_status=action.to_status,
            resolution_basis_refs=basis,
            attempted_resolution=action.attempted_resolution,
            impact=action.impact,
            limitation=action.limitation,
        )

    if isinstance(action, UpdateCoverageActionV2):
        dimension_id = _resolve_one(
            table, action.coverage_handle, BindingKind.coverage,
            f"{location}.coverage_handle", violations,
        )
        basis: Optional[tuple[str, ...]] = None
        if action.basis_handles is not None:
            basis = _resolve_handles(
                table, action.basis_handles, BindingKind.evidence,
                f"{location}.basis_handles", violations,
            )
        related: Optional[tuple[str, ...]] = None
        if action.related_question_handles is not None:
            related = _resolve_handles(
                table, action.related_question_handles,
                BindingKind.question,
                f"{location}.related_question_handles", violations,
            )
        if violations:
            return None
        return CoverageTransition(
            dimension_id=dimension_id,
            to_status=action.to_status,
            basis_refs=basis,
            limitation=action.limitation,
            capability_basis=action.capability_basis,
            related_question_ids=related or None,
        )

    if isinstance(action, AddFindingReferenceActionV2):
        finding_ref = _resolve_one(
            table, action.finding_handle, BindingKind.finding,
            f"{location}.finding_handle", violations,
        )
        if violations:
            return None
        return AddFindingReference(finding_ref=finding_ref)

    if isinstance(action, AddPendingProposalReferenceActionV2):
        proposal_ref = _resolve_one(
            table, action.proposal_handle, BindingKind.claim_proposal,
            f"{location}.proposal_handle", violations,
        )
        if violations:
            return None
        return AddPendingProposalReference(proposal_ref=proposal_ref)

    violations.append(
        ResolutionViolation(
            code=ResolutionViolationCode.RESOLUTION_INTERNAL,
            message=f"unhandled v2 action type {type(action).__name__}",
            location=location,
        )
    )
    return None


def resolve_plan_proposal_v2(
    decision: SupervisorPlanDecisionV2,
    table: ReferenceBindingTableV1,
    pack: SupervisorPlanningContextPack,
) -> tuple[Optional[SupervisorPlanDecisionV1], ResolutionRecord]:
    """Resolve a v2 plan proposal into the CANONICAL v1 plan decision
    (identity/revision/attention-hash injected).  Item eligibility,
    question activity, scope allow-list and duplicate fingerprints are
    re-checked by the UNCHANGED SupervisorPlanDecisionValidator on the
    resolved decision."""
    violations: list[ResolutionViolation] = []
    summaries: list[str] = []

    if decision.decision_version != PLAN_DECISION_VERSION_V2:
        violations.append(
            ResolutionViolation(
                code=ResolutionViolationCode.RESOLUTION_VERSION_UNSUPPORTED,
                message="unsupported v2 plan decision version",
                location="decision_version",
            )
        )
    _check_table_scope(
        table,
        task_id=pack.task_id,
        investigation_id=pack.investigation_id,
        run_id=pack.run_id,
        violations=violations,
    )

    actions: list[Any] = []
    for index, action in enumerate(decision.actions):
        location = f"actions[{index}]({action.action_type})"
        action_id = action.action_id or f"act-{index + 1}"
        if isinstance(action, DelegateInvestigationActionV2):
            item_id = _resolve_one(
                table, action.attention_handle, BindingKind.attention_item,
                f"{location}.attention_handle", violations,
            )
            question_id = _resolve_one(
                table, action.question_handle, BindingKind.question,
                f"{location}.question_handle", violations,
            )
            if violations:
                continue
            actions.append(
                DelegateInvestigation(
                    action_id=action_id,
                    attention_item_id=item_id,
                    question_id=question_id,
                    source_scope_id=action.source_scope_id,
                    time_scope=action.time_scope,
                    investigation_intent=action.investigation_intent,
                    execution_group=action.execution_group,
                )
            )
            summaries.append("delegate_investigation:ok")
        elif isinstance(action, RequestFinalizationActionV2):
            actions.append(
                RequestFinalization(
                    action_id=action_id,
                    reason_code=action.reason_code,
                    summary=action.summary,
                )
            )
            summaries.append("request_finalization:ok")
        elif isinstance(action, NoPlanActionV2):
            actions.append(
                NoPlanAction(action_id=action_id, reason_code=action.reason_code)
            )
            summaries.append("no_action:ok")
        else:  # pragma: no cover
            violations.append(
                ResolutionViolation(
                    code=ResolutionViolationCode.RESOLUTION_INTERNAL,
                    message=(
                        f"unhandled v2 plan action {type(action).__name__}"
                    ),
                    location=location,
                )
            )

    record = ResolutionRecord(
        contract_version=decision.decision_version,
        binding_table_id=table.binding_table_id,
        actions_total=len(decision.actions),
        resolved_action_summaries=tuple(summaries),
        violations=tuple(violations),
        ok=not violations,
    )
    if violations:
        return None, record

    canonical = SupervisorPlanDecisionV1(
        task_id=pack.task_id,
        investigation_id=pack.investigation_id,
        run_id=pack.run_id,
        based_on_state_revision=pack.state_revision,
        based_on_state_hash=pack.state_hash,
        attention_hash=pack.attention_hash,
        actions=tuple(actions),
        summary=decision.summary,
        warnings=decision.warnings,
        limitations=decision.limitations,
    )
    return canonical, record


# ---------------------------------------------------------------------------
# v2 prompt projections (handles + semantic content; no canonical identity)
# ---------------------------------------------------------------------------


def _project_refs(obj: Any, ref_to_handle: Mapping[str, str]) -> Any:
    if isinstance(obj, str):
        return ref_to_handle.get(obj, obj)
    if isinstance(obj, list):
        return [_project_refs(item, ref_to_handle) for item in obj]
    if isinstance(obj, tuple):
        return [_project_refs(item, ref_to_handle) for item in obj]
    if isinstance(obj, dict):
        return {
            key: _project_refs(value, ref_to_handle)
            for key, value in obj.items()
        }
    return obj


def _question_projection(
    table: ReferenceBindingTableV1, question
) -> dict:
    basis_handles = [
        table.handle_of(BindingKind.evidence, ref) or ref
        for ref in (question.basis_refs or ())
    ]
    return {
        "handle": table.handle_of(BindingKind.question, question.question_id),
        "text": question.text,
        "source": question.source.value,
        "priority": question.priority.value,
        "status": question.status.value,
        "disposition": (
            question.disposition.value if question.disposition else None
        ),
        "basis_handles": basis_handles,
        "limitations": list(question.limitations or ()),
        "investigated_summary": question.investigated_summary,
        "blocker": question.blocker,
    }


def availability_projection(table: ReferenceBindingTableV1) -> dict:
    """Deterministic A1-H admissibility projection (§17/§18): handle
    counts per kind and the action variants whose operand domains are
    non-empty.  Pure function of the frozen table — no semantic
    reasoning; branches with empty domains are not offered."""
    counts = {
        "E": 0, "Q": 0, "COV": 0, "D": 0, "F": 0, "P": 0, "H": 0, "X": 0,
    }
    for binding in table.bindings:
        handle = binding.handle
        if handle.startswith("COV"):
            counts["COV"] += 1
        else:
            counts[handle[0]] = counts.get(handle[0], 0) + 1
    available = ["update_question", "create_question"]
    if counts["E"]:
        available.append("update_evidence_relevance")
    available.append("create_hypothesis")
    if counts["H"]:
        available.append("update_hypothesis")
    available.append("create_contradiction")
    if counts["X"]:
        available.append("update_contradiction")
    if counts["COV"]:
        available.append("update_coverage")
    if counts["F"]:
        available.append("add_finding_reference")
    if counts["P"]:
        available.append("add_pending_proposal_reference")
    return {
        "handle_counts_by_kind": counts,
        "available_actions": available,
    }


def render_integration_context_v2(
    context: IntegrationContextPack,
    state: AgentWorkingStateV1,
    table: ReferenceBindingTableV1,
) -> dict:
    """Deterministic v2 view of the integration context: handles instead
    of canonical identity; semantic content preserved.  The canonical
    64-hex state hash, task/investigation/run UUIDs, delegation UUIDs
    and raw evidence keys are structurally absent."""
    e_map = {
        binding.canonical_ref: binding.handle
        for binding in table.bindings
        if binding.kind is BindingKind.evidence
    }
    d_map = {
        binding.canonical_ref: binding.handle
        for binding in table.bindings
        if binding.kind is BindingKind.delegation_result
    }
    q_map = {
        binding.canonical_ref: binding.handle
        for binding in table.bindings
        if binding.kind is BindingKind.question
    }

    fresh = []
    for env in sorted(context.fresh_results, key=lambda e: e.delegation_id):
        result_dump = _project_refs(env.result.model_dump(), e_map)
        fresh.append(
            {
                "handle": d_map.get(env.delegation_id),
                "status": "completed",
                "result": result_dump,
            }
        )

    stale = [
        {
            "delegation": d_map.get(d.delegation_id, "unbound"),
            "reason_codes": list(d.reason_codes),
        }
        for d in context.stale_result_digests
    ]
    failures = [
        {
            "delegation": d_map.get(d.delegation_id, "unbound"),
            "terminal_status": d.terminal_status,
            "failure_code": d.failure_code,
            "failure_summary": d.failure_summary,
        }
        for d in context.failure_digests
    ]

    questions = [
        _question_projection(table, q)
        for q in sorted(state.questions, key=lambda x: x.question_id)
        if q.question_id in q_map
    ]

    coverage = [
        {
            "handle": table.handle_of(
                BindingKind.coverage, dim.dimension_id
            ),
            "dimension": dim.dimension_id,
            "required": dim.required,
            "status": dim.status.value,
            "basis_handles": [
                e_map.get(ref, ref) for ref in (dim.basis_refs or ())
            ],
            "limitation": dim.limitation,
        }
        for dim in sorted(state.coverage, key=lambda d: d.dimension_id)
    ]

    hypotheses = [
        {
            "handle": table.handle_of(
                BindingKind.hypothesis, hyp.hypothesis_id
            ),
            "text": hyp.text,
            "status": hyp.status.value,
        }
        for hyp in sorted(state.hypotheses, key=lambda h: h.hypothesis_id)
    ]
    contradictions = [
        {
            "handle": table.handle_of(
                BindingKind.contradiction, con.contradiction_id
            ),
            "severity": con.severity.value,
            "status": con.status.value,
            "impact": con.impact,
            "limitation": con.limitation,
        }
        for con in sorted(
            state.contradictions, key=lambda c: c.contradiction_id
        )
    ]
    findings = [
        {
            "handle": binding.handle,
            "display_digest": binding.display_digest,
        }
        for binding in table.bindings
        if binding.kind is BindingKind.finding
    ]
    pending_proposals = [
        {
            "handle": binding.handle,
            "display_digest": binding.display_digest,
        }
        for binding in table.bindings
        if binding.kind is BindingKind.claim_proposal
    ]
    evidence_working_set = [
        {
            "handle": e_map.get(item.evidence_key),
            "relevance": item.status.value,
        }
        for item in state.evidence_working_set
        if item.evidence_key in e_map
    ]

    availability = availability_projection(table)
    return {
        "projection_version": "integration-context-v2-projection:v2",
        "binding_table_id": table.binding_table_id,
        "handle_kinds": {
            binding.handle: binding.kind.value for binding in table.bindings
        },
        # A1-H §17/§18: the model chooses ONLY from these action variants
        # and ONLY among the handles listed in handle_kinds.
        **availability,
        "fresh_results": fresh,
        "stale_results": stale,
        "failure_digests": failures,
        "questions": questions,
        "coverage_dimensions": coverage,
        "hypotheses": hypotheses,
        "contradictions": contradictions,
        "findings": findings,
        "pending_proposals": pending_proposals,
        "evidence_working_set": evidence_working_set,
        "directive_digests": list(context.directive_digests),
        "phase_capabilities": list(context.phase_capabilities),
    }


def render_plan_context_v2(
    pack: SupervisorPlanningContextPack,
    table: ReferenceBindingTableV1,
) -> dict:
    """Deterministic v2 view of the planning context: attention/question
    handles; scope ids stay raw (small closed semantic set); no
    identity/revision/hash echo."""
    q_map = {
        binding.canonical_ref: binding.handle
        for binding in table.bindings
        if binding.kind is BindingKind.question
    }
    d_map = {
        binding.canonical_ref: binding.handle
        for binding in table.bindings
        if binding.kind is BindingKind.delegation_result
    }

    attention_items = []
    for item in sorted(pack.attention_items, key=lambda i: i.item_id):
        attention_items.append(
            {
                "handle": table.handle_of(
                    BindingKind.attention_item, item.item_id
                ),
                "band": item.band,
                "eligibility": item.eligibility,
                "title": item.title,
                "reason_codes": list(getattr(item, "reason_codes", ())),
                "eligible_action_types": list(
                    getattr(item, "eligible_action_types", ())
                ),
                "related_question_handles": [
                    q_map.get(qid, qid)
                    for qid in item.related_question_ids
                ],
            }
        )

    def _delegation_rows(digests):
        return [
            {
                "delegation": d_map.get(d.delegation_id, "unbound"),
                "question_handle": q_map.get(d.question_ref, d.question_ref),
                "status": d.status,
                "failure_code": d.failure_code,
            }
            for d in digests
        ]

    return {
        "projection_version": "plan-context-v2-projection:v1",
        "binding_table_id": table.binding_table_id,
        "objective": pack.objective_digest,
        "attention_items": attention_items,
        "questions": [
            {
                "handle": q_map.get(entry.question_id, entry.question_id),
                "status": entry.status,
            }
            for entry in pack.question_index
        ],
        "coverage_digests": list(pack.coverage_digests),
        "contradiction_digests": list(pack.contradiction_digests),
        "source_scopes": list(pack.source_scope_ids),
        "active_delegations": _delegation_rows(
            pack.active_delegation_digests
        ),
        "recent_terminal_delegations": _delegation_rows(
            pack.recent_terminal_delegation_digests
        ),
        "capability_summaries": list(pack.capability_summaries),
        "progress_digest": pack.progress_digest,
        "budget_digest": pack.budget_digest,
        "last_finalization_denial": pack.last_finalization_denial_digest,
        "phase_capabilities": list(pack.phase_capabilities),
    }


__all__ = [
    "INTEGRATION_DECISION_VERSION_V2",
    "INTEGRATION_DECISION_VERSION_V3",
    "INTEGRATION_DECISION_VERSION",
    "availability_projection",
    "PLAN_DECISION_VERSION_V2",
    "AddFindingReferenceActionV2",
    "AddPendingProposalReferenceActionV2",
    "CreateContradictionActionV2",
    "CreateHypothesisActionV2",
    "CreateQuestionActionV2",
    "DelegateInvestigationActionV2",
    "NoPlanActionV2",
    "RequestFinalizationActionV2",
    "ResolutionRecord",
    "ResolutionViolation",
    "ResolutionViolationCode",
    "SupervisorIntegrationDecisionV2",
    "SupervisorPlanDecisionV2",
    "UpdateContradictionActionV2",
    "UpdateCoverageActionV2",
    "UpdateEvidenceRelevanceActionV2",
    "UpdateHypothesisActionV2",
    "UpdateQuestionActionV2",
    "render_integration_context_v2",
    "render_plan_context_v2",
    "resolve_integration_proposal_v2",
    "resolve_plan_proposal_v2",
]
