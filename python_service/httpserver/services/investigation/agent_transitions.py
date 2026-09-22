"""Typed transition proposals + deterministic StateTransitionPolicy (P2).

The policy is pure and deterministic: no LLM, no network, no Graphiti, no
agent calls, no DB writes.  It validates externally supplied transition
batches against the current typed Working State and folds them into the next
state.  One invalid semantic transition rejects the WHOLE batch (fail closed);
only safe normalization and idempotent duplicates (noop) are tolerated — the
policy never auto-corrects case semantics (P2 §16).

Enforced frozen authorities (W1–W12):
  W1  task/investigation identity immutable (structural: not transitionable)
  W2  required questions cannot disappear (no delete transition exists)
  W3  answered requires disposition
  W4  terminal coverage requires closure basis
  W5  every Evidence ref resolves inside the task (resolver callback)
  W6  Finding refs must point at canonical persisted objects (validator)
  W7  hypothesis never becomes canonical Finding (no such transition exists)
  W8  critical contradiction cannot silently disappear (no delete/reopen)
  W9  hard scope mutation always rejected in P2 (scope model is charter-TBD)
  W10 agent-origin transitions can never write review state
  W11 graph lifecycle cannot be mutated through Working State (no transition)
  W12 one semantic commit = exactly one revision increment (orchestrator)
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Callable, Optional, Union

from pydantic import BaseModel, ConfigDict

from .agent_working_state import (
    AgentWorkingStateV1,
    Contradiction,
    ContradictionSeverity,
    ContradictionStatus,
    CoverageDimension,
    CoverageStatus,
    EvidenceRelevanceStatus,
    EvidenceWorkingSetItem,
    Hypothesis,
    HypothesisStatus,
    QuestionDisposition,
    QuestionPriority,
    QuestionStatus,
    VerificationStatus,
    WorkingQuestion,
)

# ---------------------------------------------------------------------------
# evidence ref resolution seam (implemented by the orchestrator through the
# EXISTING Evidence resolver/read path — never a second resolver)
# ---------------------------------------------------------------------------


class EvidenceRefStatus(str, Enum):
    resolved = "resolved"
    not_found = "not_found"      # syntactically valid, absent from THIS task
    malformed = "malformed"


EvidenceRefResolver = Callable[[str], EvidenceRefStatus]


class FindingRefCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    found: bool
    kind: Optional[str] = None  # "event" | "analysis" | "review" | ...


FindingRefValidator = Callable[[str], FindingRefCheck]


class TransitionOrigin(str, Enum):
    agent = "agent"
    analyst = "analyst"
    orchestrator = "orchestrator"


class PolicyViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    transition_index: int


class TransitionDecisionStatus(str, Enum):
    accepted = "accepted"
    rejected = "rejected"
    noop = "noop"


# stable machine-readable violation codes (P2 §17)
QUESTION_NOT_FOUND = "QUESTION_NOT_FOUND"
QUESTION_ID_EXISTS = "QUESTION_ID_EXISTS"
QUESTION_ILLEGAL_STATUS_TRANSITION = "QUESTION_ILLEGAL_STATUS_TRANSITION"
QUESTION_DISPOSITION_REQUIRED = "QUESTION_DISPOSITION_REQUIRED"
QUESTION_CLOSURE_BASIS_REQUIRED = "QUESTION_CLOSURE_BASIS_REQUIRED"
QUESTION_CLOSURE_VERIFICATION_REQUIRED = "QUESTION_CLOSURE_VERIFICATION_REQUIRED"
QUESTION_BLOCKER_REQUIRED = "QUESTION_BLOCKER_REQUIRED"
REQUIRED_QUESTION_CANNOT_DEFER = "REQUIRED_QUESTION_CANNOT_DEFER"
QUESTION_SUPERSESSION_PROVENANCE_REQUIRED = "QUESTION_SUPERSESSION_PROVENANCE_REQUIRED"
EVIDENCE_REF_INVALID = "EVIDENCE_REF_INVALID"
EVIDENCE_REF_CROSS_TASK = "EVIDENCE_REF_CROSS_TASK"
COVERAGE_DIMENSION_NOT_FOUND = "COVERAGE_DIMENSION_NOT_FOUND"
COVERAGE_ILLEGAL_STATUS_TRANSITION = "COVERAGE_ILLEGAL_STATUS_TRANSITION"
COVERAGE_BASIS_REQUIRED = "COVERAGE_BASIS_REQUIRED"
COVERAGE_LIMITATION_REQUIRED = "COVERAGE_LIMITATION_REQUIRED"
COVERAGE_UNAVAILABLE_WITHOUT_CAPABILITY_BASIS = (
    "COVERAGE_UNAVAILABLE_WITHOUT_CAPABILITY_BASIS"
)
COVERAGE_NOT_APPLICABLE_BASIS_REQUIRED = "COVERAGE_NOT_APPLICABLE_BASIS_REQUIRED"
COVERAGE_QUESTION_NOT_FOUND = "COVERAGE_QUESTION_NOT_FOUND"
HYPOTHESIS_ID_EXISTS = "HYPOTHESIS_ID_EXISTS"
HYPOTHESIS_NOT_FOUND = "HYPOTHESIS_NOT_FOUND"
HYPOTHESIS_ILLEGAL_TRANSITION = "HYPOTHESIS_ILLEGAL_TRANSITION"
CONTRADICTION_ID_EXISTS = "CONTRADICTION_ID_EXISTS"
CONTRADICTION_NOT_FOUND = "CONTRADICTION_NOT_FOUND"
CONTRADICTION_ILLEGAL_TRANSITION = "CONTRADICTION_ILLEGAL_TRANSITION"
CONTRADICTION_REFS_REQUIRED = "CONTRADICTION_REFS_REQUIRED"
CONTRADICTION_RESOLUTION_BASIS_REQUIRED = "CONTRADICTION_RESOLUTION_BASIS_REQUIRED"
CRITICAL_CONTRADICTION_BASIS_REQUIRED = "CRITICAL_CONTRADICTION_BASIS_REQUIRED"
SCOPE_MUTATION_NOT_ALLOWED = "SCOPE_MUTATION_NOT_ALLOWED"
REVIEW_STATE_NOT_AGENT_WRITABLE = "REVIEW_STATE_NOT_AGENT_WRITABLE"
FINDING_REF_NOT_FOUND = "FINDING_REF_NOT_FOUND"
STATE_REVISION_CONFLICT = "STATE_REVISION_CONFLICT"

# reserved Evidence key prefixes validated through the resolver in P2
_EVIDENCE_KEY_PREFIXES = ("file:", "cluster:")

# frozen question status machine (deferral is temporary; superseded is the
# only exit from terminal statuses and requires explicit provenance)
_QUESTION_STATUS_TRANSITIONS: dict[QuestionStatus, frozenset[QuestionStatus]] = {
    QuestionStatus.open: frozenset(
        {
            QuestionStatus.in_progress,
            QuestionStatus.answered,
            QuestionStatus.unresolved,
            QuestionStatus.blocked,
            QuestionStatus.deferred,
            QuestionStatus.superseded,
        }
    ),
    QuestionStatus.in_progress: frozenset(
        {
            QuestionStatus.answered,
            QuestionStatus.unresolved,
            QuestionStatus.blocked,
            QuestionStatus.deferred,
            QuestionStatus.superseded,
        }
    ),
    QuestionStatus.deferred: frozenset(
        {QuestionStatus.open, QuestionStatus.in_progress, QuestionStatus.superseded}
    ),
    QuestionStatus.answered: frozenset({QuestionStatus.superseded}),
    QuestionStatus.unresolved: frozenset({QuestionStatus.superseded}),
    QuestionStatus.blocked: frozenset({QuestionStatus.superseded}),
    QuestionStatus.superseded: frozenset(),
}

_HYPOTHESIS_STATUS_TRANSITIONS: dict[HypothesisStatus, frozenset[HypothesisStatus]] = {
    HypothesisStatus.active: frozenset(
        {
            HypothesisStatus.supported,
            HypothesisStatus.weakened,
            HypothesisStatus.rejected,
            HypothesisStatus.retired,
        }
    ),
    HypothesisStatus.supported: frozenset({HypothesisStatus.retired}),
    HypothesisStatus.weakened: frozenset({HypothesisStatus.retired}),
    HypothesisStatus.rejected: frozenset(),
    HypothesisStatus.retired: frozenset(),
}

_CONTRADICTION_STATUS_TRANSITIONS: dict[
    ContradictionStatus, frozenset[ContradictionStatus]
] = {
    ContradictionStatus.open: frozenset(
        {
            ContradictionStatus.resolved,
            ContradictionStatus.explained,
            ContradictionStatus.unresolved,
        }
    ),
    ContradictionStatus.resolved: frozenset(),
    ContradictionStatus.explained: frozenset(),
    ContradictionStatus.unresolved: frozenset(),
}

_COVERAGE_STATUS_TRANSITIONS: dict[CoverageStatus, frozenset[CoverageStatus]] = {
    CoverageStatus.not_started: frozenset(
        {
            CoverageStatus.in_progress,
            CoverageStatus.covered,
            CoverageStatus.partial,
            CoverageStatus.unavailable,
            CoverageStatus.not_applicable,
        }
    ),
    CoverageStatus.in_progress: frozenset(
        {
            CoverageStatus.covered,
            CoverageStatus.partial,
            CoverageStatus.unavailable,
            CoverageStatus.not_applicable,
        }
    ),
    CoverageStatus.covered: frozenset(),
    CoverageStatus.partial: frozenset(),
    CoverageStatus.unavailable: frozenset(),
    CoverageStatus.not_applicable: frozenset(),
}


# ---------------------------------------------------------------------------
# typed transition family (frozen set; unknown types are structurally
# impossible through pydantic and rejected fail closed)
# ---------------------------------------------------------------------------


class _TransitionBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class QuestionTransition(_TransitionBase):
    question_id: str
    to_status: QuestionStatus
    disposition: Optional[QuestionDisposition] = None
    basis_refs: Optional[tuple[str, ...]] = None
    limitations: Optional[tuple[str, ...]] = None
    investigated_summary: Optional[str] = None
    blocker: Optional[str] = None
    superseded_by_ref: Optional[str] = None


class CreateQuestion(_TransitionBase):
    question: WorkingQuestion


class EvidenceRelevanceTransition(_TransitionBase):
    evidence_key: str
    to_status: EvidenceRelevanceStatus
    related_question_ids: Optional[tuple[str, ...]] = None


class AddEntityReference(_TransitionBase):
    entity_ref: str


class CreateHypothesis(_TransitionBase):
    hypothesis: Hypothesis


class HypothesisTransition(_TransitionBase):
    hypothesis_id: str
    to_status: HypothesisStatus


class CreateContradiction(_TransitionBase):
    contradiction: Contradiction


class ContradictionTransition(_TransitionBase):
    contradiction_id: str
    to_status: ContradictionStatus
    resolution_basis_refs: Optional[tuple[str, ...]] = None
    attempted_resolution: Optional[str] = None
    impact: Optional[str] = None
    limitation: Optional[str] = None


class CoverageTransition(_TransitionBase):
    dimension_id: str
    to_status: CoverageStatus
    basis_refs: Optional[tuple[str, ...]] = None
    limitation: Optional[str] = None
    capability_basis: Optional[str] = None
    related_question_ids: Optional[tuple[str, ...]] = None


class AddFindingReference(_TransitionBase):
    finding_ref: str


class AddPendingProposalReference(_TransitionBase):
    proposal_ref: str


class ModifyScope(_TransitionBase):
    """Contract-only placeholder: hard scope mutation is never allowed
    through Working State transitions (W9).  The canonical scope model lives
    in the Charter contract, which is still Architecture TBD; until it is
    frozen this transition is always rejected fail closed."""

    scope_patch: dict


Transition = Union[
    QuestionTransition,
    CreateQuestion,
    EvidenceRelevanceTransition,
    AddEntityReference,
    CreateHypothesis,
    HypothesisTransition,
    CreateContradiction,
    ContradictionTransition,
    CoverageTransition,
    AddFindingReference,
    AddPendingProposalReference,
    ModifyScope,
]


class TransitionBatch(BaseModel):
    """One atomic semantic decision: all-or-nothing (P2 §15)."""

    model_config = ConfigDict(frozen=True)

    transitions: tuple[Transition, ...] = ()


class TransitionPolicyContext(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    task_id: str
    investigation_id: str
    origin: TransitionOrigin = TransitionOrigin.agent
    policy_version: str = "state-transition:v1"
    # injected deterministic seams (backed by existing read paths)
    evidence_ref_resolver: EvidenceRefResolver
    finding_ref_validator: FindingRefValidator
    # state-bound verification lookup: question_id -> a passed verification
    # exists (deterministic; supplied by the orchestrator from the state)
    verification_checker: Optional[Callable[[str], bool]] = None


class TransitionPolicyResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    status: TransitionDecisionStatus
    policy_version: str
    violations: tuple[PolicyViolation, ...] = ()
    new_state: Optional[AgentWorkingStateV1] = None
    noop_count: int = 0


def _refute_evidence_refs(
    refs,
    ctx: TransitionPolicyContext,
    index: int,
    violations: list[PolicyViolation],
) -> None:
    """W5: evidence-shaped refs must resolve inside the task."""
    for ref in refs:
        if not isinstance(ref, str) or not ref.startswith(_EVIDENCE_KEY_PREFIXES):
            continue  # non-evidence refs stay opaque in P2
        status = ctx.evidence_ref_resolver(ref)
        if status == EvidenceRefStatus.malformed:
            violations.append(PolicyViolation(
                code=EVIDENCE_REF_INVALID,
                message=f"evidence ref is malformed: {ref!r}",
                transition_index=index,
            ))
        elif status == EvidenceRefStatus.not_found:
            violations.append(PolicyViolation(
                code=EVIDENCE_REF_CROSS_TASK,
                message=f"evidence ref does not resolve inside this task: {ref!r}",
                transition_index=index,
            ))


class StateTransitionPolicy:
    """Deterministic validator/folder for typed transition batches."""

    def __init__(
        self,
        *,
        policy_version: str = "state-transition:v1",
    ):
        self.policy_version = policy_version

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def evaluate_batch(
        self,
        current_state: AgentWorkingStateV1,
        batch: TransitionBatch,
        ctx: TransitionPolicyContext,
    ) -> TransitionPolicyResult:
        """Validate the whole batch against the current state.

        accepted  -> new_state is the folded next state (not yet committed)
        rejected  -> violations non-empty; new_state None; nothing committed
        noop      -> every transition was an idempotent duplicate
        """
        violations: list[PolicyViolation] = []
        state = current_state
        noop_count = 0
        for index, transition in enumerate(batch.transitions):
            outcome = self._apply_one(state, transition, ctx, index, violations)
            if outcome is None:
                continue
            state, was_noop = outcome
            if was_noop:
                noop_count += 1
        if violations:
            return TransitionPolicyResult(
                status=TransitionDecisionStatus.rejected,
                policy_version=self.policy_version,
                violations=tuple(violations),
                new_state=None,
            )
        if state == current_state:
            # every transition was an idempotent duplicate: nothing to commit
            return TransitionPolicyResult(
                status=TransitionDecisionStatus.noop,
                policy_version=self.policy_version,
                noop_count=len(batch.transitions),
            )
        return TransitionPolicyResult(
            status=TransitionDecisionStatus.accepted,
            policy_version=self.policy_version,
            new_state=state,
            noop_count=noop_count,
        )

    # ------------------------------------------------------------------
    # per-transition dispatch
    # ------------------------------------------------------------------

    def _apply_one(
        self,
        state: AgentWorkingStateV1,
        transition,
        ctx: TransitionPolicyContext,
        index: int,
        violations: list[PolicyViolation],
    ):
        """Apply one transition to ``state``.

        Returns ``(new_state, was_noop)``, or ``None`` when the transition is
        a pure no-op that does not change the state at all.
        """
        if isinstance(transition, ModifyScope):
            # W9: always rejected — P2 has no frozen scope model to mutate.
            violations.append(PolicyViolation(
                code=SCOPE_MUTATION_NOT_ALLOWED,
                message="hard scope mutation is not allowed through working state",
                transition_index=index,
            ))
            return None

        if isinstance(transition, CreateQuestion):
            return self._apply_create_question(state, transition, ctx, index, violations)
        if isinstance(transition, QuestionTransition):
            return self._apply_question_transition(
                state, transition, ctx, index, violations
            )
        if isinstance(transition, EvidenceRelevanceTransition):
            return self._apply_evidence_transition(
                state, transition, ctx, index, violations
            )
        if isinstance(transition, AddEntityReference):
            if transition.entity_ref in state.entity_refs:
                return None
            return (
                state.with_replacements(
                    entity_refs=state.entity_refs + (transition.entity_ref,)
                ),
                False,
            )
        if isinstance(transition, CreateHypothesis):
            return self._apply_create_hypothesis(
                state, transition, ctx, index, violations
            )
        if isinstance(transition, HypothesisTransition):
            return self._apply_hypothesis_transition(
                state, transition, index, violations
            )
        if isinstance(transition, CreateContradiction):
            return self._apply_create_contradiction(
                state, transition, ctx, index, violations
            )
        if isinstance(transition, ContradictionTransition):
            return self._apply_contradiction_transition(
                state, transition, index, violations
            )
        if isinstance(transition, CoverageTransition):
            return self._apply_coverage_transition(
                state, transition, ctx, index, violations
            )
        if isinstance(transition, AddFindingReference):
            return self._apply_add_finding_ref(state, transition, ctx, index, violations)
        if isinstance(transition, AddPendingProposalReference):
            if transition.proposal_ref in state.pending_proposal_refs:
                return None
            return (
                state.with_replacements(
                    pending_proposal_refs=state.pending_proposal_refs
                    + (transition.proposal_ref,)
                ),
                False,
            )
        # Unknown transition type: fail closed (unreachable with the frozen
        # pydantic union, kept as a defensive boundary).
        violations.append(PolicyViolation(
            code="TRANSITION_TYPE_NOT_RECOGNIZED",
            message=f"unsupported transition type: {type(transition).__name__}",
            transition_index=index,
        ))
        return None

    # ------------------------------------------------------------------
    # questions
    # ------------------------------------------------------------------

    def _apply_create_question(self, state, transition, ctx, index, violations):
        question = transition.question
        existing = state.question(question.question_id)
        if existing is not None:
            if existing == question:
                return None  # idempotent duplicate admission
            violations.append(PolicyViolation(
                code=QUESTION_ID_EXISTS,
                message=f"question already exists: {question.question_id!r}",
                transition_index=index,
            ))
            return None
        _refute_evidence_refs(question.basis_refs, ctx, index, violations)
        if violations:
            return None
        return (
            state.with_replacements(questions=state.questions + (question,)),
            False,
        )

    def _apply_question_transition(self, state, transition, ctx, index, violations):
        current = state.question(transition.question_id)
        if current is None:
            violations.append(PolicyViolation(
                code=QUESTION_NOT_FOUND,
                message=f"question not found: {transition.question_id!r}",
                transition_index=index,
            ))
            return None

        merged = {
            "status": transition.to_status,
            "disposition": (
                transition.disposition
                if transition.disposition is not None
                else current.disposition
            ),
            "basis_refs": (
                transition.basis_refs
                if transition.basis_refs is not None
                else current.basis_refs
            ),
            "limitations": (
                transition.limitations
                if transition.limitations is not None
                else current.limitations
            ),
            "investigated_summary": (
                transition.investigated_summary
                if transition.investigated_summary is not None
                else current.investigated_summary
            ),
            "blocker": (
                transition.blocker
                if transition.blocker is not None
                else current.blocker
            ),
            "superseded_by_ref": (
                transition.superseded_by_ref
                if transition.superseded_by_ref is not None
                else current.superseded_by_ref
            ),
        }
        candidate = current.model_copy(update=merged)

        if candidate == current:
            return None  # idempotent duplicate

        if transition.to_status != current.status:
            allowed = _QUESTION_STATUS_TRANSITIONS.get(current.status, frozenset())
            if transition.to_status not in allowed:
                violations.append(PolicyViolation(
                    code=QUESTION_ILLEGAL_STATUS_TRANSITION,
                    message=(
                        f"illegal question transition "
                        f"{current.status.value!r} -> {transition.to_status.value!r}"
                    ),
                    transition_index=index,
                ))
                return None
        # W2: a required question may be deferred only through the explicit
        # illegal-status check above; enforce it with a dedicated code.
        if (
            transition.to_status == QuestionStatus.deferred
            and current.priority == QuestionPriority.required
            and current.status != QuestionStatus.deferred
        ):
            violations.append(PolicyViolation(
                code=REQUIRED_QUESTION_CANNOT_DEFER,
                message="required questions cannot be deferred",
                transition_index=index,
            ))
            return None

        self._validate_question_closure(
            candidate, transition.to_status != current.status, ctx, index, violations
        )
        if violations:
            return None
        _refute_evidence_refs(candidate.basis_refs, ctx, index, violations)
        if violations:
            return None
        updated = tuple(
            candidate if q.question_id == candidate.question_id else q
            for q in state.questions
        )
        return (state.with_replacements(questions=updated), False)

    def _validate_question_closure(
        self,
        question: WorkingQuestion,
        status_changed: bool,
        ctx: TransitionPolicyContext,
        index: int,
        violations: list[PolicyViolation],
    ) -> None:
        status = question.status
        if status == QuestionStatus.answered:
            if question.disposition is None:
                violations.append(PolicyViolation(
                    code=QUESTION_DISPOSITION_REQUIRED,
                    message=f"question {question.question_id!r} answered without disposition",
                    transition_index=index,
                ))
            if not question.basis_refs:
                violations.append(PolicyViolation(
                    code=QUESTION_CLOSURE_BASIS_REQUIRED,
                    message=f"question {question.question_id!r} answered without basis refs",
                    transition_index=index,
                ))
            if (
                question.priority == QuestionPriority.required
                and status_changed
                and not self._has_passed_verification(ctx, question.question_id)
            ):
                violations.append(PolicyViolation(
                    code=QUESTION_CLOSURE_VERIFICATION_REQUIRED,
                    message=(
                        f"required question {question.question_id!r} cannot be "
                        "answered without a passed closure verification"
                    ),
                    transition_index=index,
                ))
        elif status == QuestionStatus.unresolved:
            if (
                not question.basis_refs
                or not question.limitations
                or not question.investigated_summary
            ):
                violations.append(PolicyViolation(
                    code=QUESTION_CLOSURE_BASIS_REQUIRED,
                    message=(
                        f"unresolved question {question.question_id!r} requires "
                        "investigation summary, basis refs and limitations"
                    ),
                    transition_index=index,
                ))
        elif status == QuestionStatus.blocked:
            if not question.blocker:
                violations.append(PolicyViolation(
                    code=QUESTION_BLOCKER_REQUIRED,
                    message=(
                        f"blocked question {question.question_id!r} requires a "
                        "verifiable blocker"
                    ),
                    transition_index=index,
                ))
        elif status == QuestionStatus.superseded:
            if not question.superseded_by_ref:
                violations.append(PolicyViolation(
                    code=QUESTION_SUPERSESSION_PROVENANCE_REQUIRED,
                    message=(
                        f"superseded question {question.question_id!r} requires "
                        "explicit contract/directive provenance"
                    ),
                    transition_index=index,
                ))

    @staticmethod
    def _has_passed_verification(
        ctx: TransitionPolicyContext, question_id: str
    ) -> bool:
        """Deterministic seam: the ORCHESTRATOR supplies the current state's
        verifications through the resolver-bound context.  P2's policy-level
        default inspects the state via the closure hook set at construction.
        """
        checker = getattr(ctx, "verification_checker", None)
        if checker is None:
            return False
        return bool(checker(question_id))

    # ------------------------------------------------------------------
    # evidence working set
    # ------------------------------------------------------------------

    def _apply_evidence_transition(self, state, transition, ctx, index, violations):
        status = ctx.evidence_ref_resolver(transition.evidence_key)
        if status == EvidenceRefStatus.malformed:
            violations.append(PolicyViolation(
                code=EVIDENCE_REF_INVALID,
                message=f"evidence ref is malformed: {transition.evidence_key!r}",
                transition_index=index,
            ))
            return None
        if status == EvidenceRefStatus.not_found:
            violations.append(PolicyViolation(
                code=EVIDENCE_REF_CROSS_TASK,
                message=(
                    f"evidence ref does not resolve inside this task: "
                    f"{transition.evidence_key!r}"
                ),
                transition_index=index,
            ))
            return None
        unknown = set(transition.related_question_ids or ()) - {
            q.question_id for q in state.questions
        }
        if unknown:
            violations.append(PolicyViolation(
                code=QUESTION_NOT_FOUND,
                message=f"related questions do not exist: {sorted(unknown)}",
                transition_index=index,
            ))
            return None
        existing = state.evidence_item(transition.evidence_key)
        if existing is None:
            item = EvidenceWorkingSetItem(
                evidence_key=transition.evidence_key,
                status=transition.to_status,
                related_question_ids=tuple(transition.related_question_ids or ()),
            )
            return (
                state.with_replacements(
                    evidence_working_set=state.evidence_working_set + (item,)
                ),
                False,
            )
        merged_related = (
            transition.related_question_ids
            if transition.related_question_ids is not None
            else existing.related_question_ids
        )
        candidate = existing.model_copy(
            update={
                "status": transition.to_status,
                "related_question_ids": tuple(merged_related),
            }
        )
        if candidate == existing:
            return None
        updated = tuple(
            candidate if i.evidence_key == candidate.evidence_key else i
            for i in state.evidence_working_set
        )
        return (state.with_replacements(evidence_working_set=updated), False)

    # ------------------------------------------------------------------
    # hypotheses
    # ------------------------------------------------------------------

    def _apply_create_hypothesis(self, state, transition, ctx, index, violations):
        hypothesis = transition.hypothesis
        if state.hypothesis(hypothesis.hypothesis_id) is not None:
            violations.append(PolicyViolation(
                code=HYPOTHESIS_ID_EXISTS,
                message=f"hypothesis already exists: {hypothesis.hypothesis_id!r}",
                transition_index=index,
            ))
            return None
        _refute_evidence_refs(
            tuple(hypothesis.supporting_refs) + tuple(hypothesis.contradicting_refs),
            ctx, index, violations,
        )
        if violations:
            return None
        return (
            state.with_replacements(hypotheses=state.hypotheses + (hypothesis,)),
            False,
        )

    def _apply_hypothesis_transition(self, state, transition, index, violations):
        current = state.hypothesis(transition.hypothesis_id)
        if current is None:
            violations.append(PolicyViolation(
                code=HYPOTHESIS_NOT_FOUND,
                message=f"hypothesis not found: {transition.hypothesis_id!r}",
                transition_index=index,
            ))
            return None
        if transition.to_status == current.status:
            return None
        allowed = _HYPOTHESIS_STATUS_TRANSITIONS.get(current.status, frozenset())
        if transition.to_status not in allowed:
            violations.append(PolicyViolation(
                code=HYPOTHESIS_ILLEGAL_TRANSITION,
                message=(
                    f"illegal hypothesis transition "
                    f"{current.status.value!r} -> {transition.to_status.value!r}"
                ),
                transition_index=index,
            ))
            return None
        candidate = current.model_copy(update={"status": transition.to_status})
        updated = tuple(
            candidate if h.hypothesis_id == candidate.hypothesis_id else h
            for h in state.hypotheses
        )
        return (state.with_replacements(hypotheses=updated), False)

    # ------------------------------------------------------------------
    # contradictions
    # ------------------------------------------------------------------

    def _apply_create_contradiction(self, state, transition, ctx, index, violations):
        contradiction = transition.contradiction
        if state.contradiction(contradiction.contradiction_id) is not None:
            violations.append(PolicyViolation(
                code=CONTRADICTION_ID_EXISTS,
                message=(
                    f"contradiction already exists: "
                    f"{contradiction.contradiction_id!r}"
                ),
                transition_index=index,
            ))
            return None
        if not contradiction.refs:
            violations.append(PolicyViolation(
                code=CONTRADICTION_REFS_REQUIRED,
                message="contradiction creation requires real refs",
                transition_index=index,
            ))
            return None
        _refute_evidence_refs(contradiction.refs, ctx, index, violations)
        if violations:
            return None
        return (
            state.with_replacements(
                contradictions=state.contradictions + (contradiction,)
            ),
            False,
        )

    def _apply_contradiction_transition(self, state, transition, index, violations):
        current = state.contradiction(transition.contradiction_id)
        if current is None:
            violations.append(PolicyViolation(
                code=CONTRADICTION_NOT_FOUND,
                message=f"contradiction not found: {transition.contradiction_id!r}",
                transition_index=index,
            ))
            return None
        if transition.to_status == current.status:
            return None
        allowed = _CONTRADICTION_STATUS_TRANSITIONS.get(current.status, frozenset())
        if transition.to_status not in allowed:
            violations.append(PolicyViolation(
                code=CONTRADICTION_ILLEGAL_TRANSITION,
                message=(
                    f"illegal contradiction transition "
                    f"{current.status.value!r} -> {transition.to_status.value!r}"
                ),
                transition_index=index,
            ))
            return None
        merged = {
            "status": transition.to_status,
            "resolution_basis_refs": (
                transition.resolution_basis_refs
                if transition.resolution_basis_refs is not None
                else current.resolution_basis_refs
            ),
            "attempted_resolution": (
                transition.attempted_resolution
                if transition.attempted_resolution is not None
                else current.attempted_resolution
            ),
            "impact": (
                transition.impact if transition.impact is not None else current.impact
            ),
            "limitation": (
                transition.limitation
                if transition.limitation is not None
                else current.limitation
            ),
        }
        candidate = current.model_copy(update=merged)
        if transition.to_status in (
            ContradictionStatus.resolved,
            ContradictionStatus.explained,
        ) and not candidate.resolution_basis_refs:
            violations.append(PolicyViolation(
                code=CONTRADICTION_RESOLUTION_BASIS_REQUIRED,
                message=(
                    f"contradiction {candidate.contradiction_id!r} "
                    f"{transition.to_status.value!r} requires resolution basis refs"
                ),
                transition_index=index,
            ))
        if (
            transition.to_status == ContradictionStatus.unresolved
            and current.severity == ContradictionSeverity.critical
            and (
                not candidate.resolution_basis_refs
                or not candidate.attempted_resolution
                or not candidate.impact
                or not candidate.limitation
            )
        ):
            violations.append(PolicyViolation(
                code=CRITICAL_CONTRADICTION_BASIS_REQUIRED,
                message=(
                    f"critical contradiction {candidate.contradiction_id!r} "
                    "cannot become unresolved without resolution basis, "
                    "attempted resolution, impact and limitation"
                ),
                transition_index=index,
            ))
        if violations:
            return None
        updated = tuple(
            candidate if c.contradiction_id == candidate.contradiction_id else c
            for c in state.contradictions
        )
        return (state.with_replacements(contradictions=updated), False)

    # ------------------------------------------------------------------
    # coverage
    # ------------------------------------------------------------------

    def _apply_coverage_transition(self, state, transition, ctx, index, violations):
        current = state.coverage_dimension(transition.dimension_id)
        if current is None:
            violations.append(PolicyViolation(
                code=COVERAGE_DIMENSION_NOT_FOUND,
                message=f"coverage dimension not found: {transition.dimension_id!r}",
                transition_index=index,
            ))
            return None
        unknown = set(transition.related_question_ids or ()) - {
            q.question_id for q in state.questions
        }
        if unknown:
            violations.append(PolicyViolation(
                code=COVERAGE_QUESTION_NOT_FOUND,
                message=f"related questions do not exist: {sorted(unknown)}",
                transition_index=index,
            ))
            return None
        if transition.to_status == current.status:
            return None
        allowed = _COVERAGE_STATUS_TRANSITIONS.get(current.status, frozenset())
        if transition.to_status not in allowed:
            violations.append(PolicyViolation(
                code=COVERAGE_ILLEGAL_STATUS_TRANSITION,
                message=(
                    f"illegal coverage transition "
                    f"{current.status.value!r} -> {transition.to_status.value!r}"
                ),
                transition_index=index,
            ))
            return None
        merged = {
            "status": transition.to_status,
            "basis_refs": (
                transition.basis_refs
                if transition.basis_refs is not None
                else current.basis_refs
            ),
            "limitation": (
                transition.limitation
                if transition.limitation is not None
                else current.limitation
            ),
            "capability_basis": (
                transition.capability_basis
                if transition.capability_basis is not None
                else current.capability_basis
            ),
            "related_question_ids": (
                transition.related_question_ids
                if transition.related_question_ids is not None
                else current.related_question_ids
            ),
        }
        candidate = current.model_copy(update=merged)
        # W4: terminal coverage requires a legal closure basis.
        if transition.to_status == CoverageStatus.covered and not candidate.basis_refs:
            violations.append(PolicyViolation(
                code=COVERAGE_BASIS_REQUIRED,
                message=(
                    f"coverage {candidate.dimension_id!r} cannot close as "
                    "covered without basis refs"
                ),
                transition_index=index,
            ))
        if transition.to_status == CoverageStatus.partial and (
            not candidate.basis_refs or not candidate.limitation
        ):
            violations.append(PolicyViolation(
                code=COVERAGE_LIMITATION_REQUIRED,
                message=(
                    f"coverage {candidate.dimension_id!r} partial requires "
                    "basis refs and an explicit limitation"
                ),
                transition_index=index,
            ))
        if transition.to_status == CoverageStatus.unavailable and (
            not candidate.capability_basis
        ):
            violations.append(PolicyViolation(
                code=COVERAGE_UNAVAILABLE_WITHOUT_CAPABILITY_BASIS,
                message=(
                    f"coverage {candidate.dimension_id!r} unavailable requires "
                    "a capability/system basis"
                ),
                transition_index=index,
            ))
        if transition.to_status == CoverageStatus.not_applicable and (
            not candidate.basis_refs
        ):
            violations.append(PolicyViolation(
                code=COVERAGE_NOT_APPLICABLE_BASIS_REQUIRED,
                message=(
                    f"coverage {candidate.dimension_id!r} not_applicable "
                    "requires an applicability rationale"
                ),
                transition_index=index,
            ))
        if violations:
            return None
        _refute_evidence_refs(candidate.basis_refs, ctx, index, violations)
        if violations:
            return None
        updated = tuple(
            candidate if c.dimension_id == candidate.dimension_id else c
            for c in state.coverage
        )
        return (state.with_replacements(coverage=updated), False)

    # ------------------------------------------------------------------
    # finding refs (W6/W10)
    # ------------------------------------------------------------------

    def _apply_add_finding_ref(self, state, transition, ctx, index, violations):
        check = ctx.finding_ref_validator(transition.finding_ref)
        if check.kind == "review":
            # W10: review records are never writable through agent-origin
            # working state transitions.
            violations.append(PolicyViolation(
                code=REVIEW_STATE_NOT_AGENT_WRITABLE,
                message=(
                    f"finding ref points at a review record: "
                    f"{transition.finding_ref!r}"
                ),
                transition_index=index,
            ))
            return None
        if not check.found:
            violations.append(PolicyViolation(
                code=FINDING_REF_NOT_FOUND,
                message=(
                    f"finding ref does not point at a canonical persisted "
                    f"object: {transition.finding_ref!r}"
                ),
                transition_index=index,
            ))
            return None
        if transition.finding_ref in state.finding_refs:
            return None
        return (
            state.with_replacements(
                finding_refs=state.finding_refs + (transition.finding_ref,)
            ),
            False,
        )
