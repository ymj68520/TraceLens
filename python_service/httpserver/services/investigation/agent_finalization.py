"""Deterministic FinalizationGate + atomic finalization service (P2).

The gate is pure and deterministic.  It never runs a SemanticVerifier: the
final semantic review arrives as an external ``FinalSemanticReview`` input
(P5 will supply real verifier results; P2 tests supply manual outcomes).

Pipeline (P2 §28):

    FinalizationRequest
      -> integrity / runtime preflight      (runtime view facts)
      -> investigation closure preflight    (questions / coverage /
                                             contradictions / verifications)
      -> capability failure policy          (integrity_critical /
                                             semantic_required / optional)
      -> final semantic review policy       (best_effort / required)
      -> PASS / DENY / STALE decision
      -> atomic Finalization Commit         (AgentRuntimeRepository
                                             .record_finalization)

``completed`` stays a no-outgoing terminal (P1); a completed investigation
cannot finalize again.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .agent_working_state import (
    AgentWorkingStateV1,
    ContradictionStatus,
    CoverageStatus,
    FINALIZATION_POLICY_VERSION,
    QuestionStatus,
    VerificationStatus,
)


class FinalizationOutcome(str, Enum):
    pass_ = "pass"
    deny = "deny"
    stale = "stale"


class CompletionMode(str, Enum):
    complete = "complete"
    complete_with_limitations = "complete_with_limitations"


class FinalReviewMode(str, Enum):
    best_effort = "best_effort"
    required = "required"


class FinalSemanticReviewStatus(str, Enum):
    passed = "passed"
    issues_found = "issues_found"
    unavailable = "unavailable"


class FinalSemanticReview(BaseModel):
    """External input contract — P2 never produces this itself."""

    model_config = ConfigDict(frozen=True)

    status: FinalSemanticReviewStatus
    result_ref: Optional[str] = None


class CapabilityFailureCategory(str, Enum):
    integrity_critical = "integrity_critical"
    semantic_required = "semantic_required"
    optional_enhancement = "optional_enhancement"


class CapabilityFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: CapabilityFailureCategory
    capability: str
    degraded: bool = False
    detail: Optional[str] = None


class FinalizationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    investigation_id: str
    expected_state_revision: int
    review_mode: FinalReviewMode = FinalReviewMode.required
    final_semantic_review: FinalSemanticReview
    capability_failures: tuple[CapabilityFailure, ...] = ()
    run_id: Optional[str] = None
    requested_by: Optional[str] = None


class RuntimeFinalizationView(BaseModel):
    """Deterministic runtime facts the gate cannot derive from state alone
    (supplied by the orchestrator from the P1 repository reads)."""

    model_config = ConfigDict(frozen=True)

    investigation_status: str
    store_ok: bool = True
    transition_conflict_unresolved: bool = False
    active_run_id: Optional[str] = None
    active_delegation_ids: tuple[str, ...] = ()
    completed_unintegrated_delegation_ids: tuple[str, ...] = ()


class FinalizationDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: FinalizationOutcome
    policy_version: str
    violation_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    completion_mode: Optional[CompletionMode] = None


# stable denial / limitation codes
IDENTITY_INVALID = "IDENTITY_INVALID"
STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
STATE_REVISION_STALE = "STATE_REVISION_STALE"
INVESTIGATION_NOT_ACTIVE = "INVESTIGATION_NOT_ACTIVE"
TRANSITION_CONFLICT_UNRESOLVED = "TRANSITION_CONFLICT_UNRESOLVED"
UNAPPLIED_DIRECTIVE_PRESENT = "UNAPPLIED_DIRECTIVE_PRESENT"
ACTIVE_DELEGATION_PRESENT = "ACTIVE_DELEGATION_PRESENT"
UNINTEGRATED_COMPLETED_DELEGATION = "UNINTEGRATED_COMPLETED_DELEGATION"
MANDATORY_VERIFICATION_BLOCKING = "MANDATORY_VERIFICATION_BLOCKING"
REQUIRED_QUESTION_OPEN = "REQUIRED_QUESTION_OPEN"
REQUIRED_QUESTION_IN_PROGRESS = "REQUIRED_QUESTION_IN_PROGRESS"
REQUIRED_QUESTION_DEFERRED = "REQUIRED_QUESTION_DEFERRED"
QUESTION_DISPOSITION_REQUIRED = "QUESTION_DISPOSITION_REQUIRED"
QUESTION_CLOSURE_BASIS_REQUIRED = "QUESTION_CLOSURE_BASIS_REQUIRED"
QUESTION_BLOCKER_REQUIRED = "QUESTION_BLOCKER_REQUIRED"
QUESTION_SUPERSESSION_PROVENANCE_REQUIRED = "QUESTION_SUPERSESSION_PROVENANCE_REQUIRED"
COVERAGE_NOT_TERMINAL = "COVERAGE_NOT_TERMINAL"
COVERAGE_BASIS_REQUIRED = "COVERAGE_BASIS_REQUIRED"
COVERAGE_LIMITATION_REQUIRED = "COVERAGE_LIMITATION_REQUIRED"
COVERAGE_UNAVAILABLE_WITHOUT_CAPABILITY_BASIS = (
    "COVERAGE_UNAVAILABLE_WITHOUT_CAPABILITY_BASIS"
)
CRITICAL_CONTRADICTION_OPEN = "CRITICAL_CONTRADICTION_OPEN"
CRITICAL_CONTRADICTION_BASIS_REQUIRED = "CRITICAL_CONTRADICTION_BASIS_REQUIRED"
INTEGRITY_CRITICAL_FAILURE = "INTEGRITY_CRITICAL_FAILURE"
SEMANTIC_REQUIRED_NOT_DEGRADED = "SEMANTIC_REQUIRED_NOT_DEGRADED"
REVIEW_ISSUES_FOUND = "REVIEW_ISSUES_FOUND"
REVIEW_UNAVAILABLE = "REVIEW_UNAVAILABLE"
LIMITATION_REVIEW_UNAVAILABLE = "final semantic review unavailable (best_effort)"
LIMITATION_UNRESOLVED_QUESTION = "question unresolved: {question_id}"
LIMITATION_BLOCKED_QUESTION = "question blocked: {question_id}"
LIMITATION_PARTIAL_COVERAGE = "coverage partial: {dimension_id}"
LIMITATION_UNAVAILABLE_COVERAGE = "coverage unavailable: {dimension_id}"
LIMITATION_UNRESOLVED_CONTRADICTION = (
    "critical contradiction unresolved: {contradiction_id}"
)
LIMITATION_OPEN_CONTRADICTION = "open contradiction: {contradiction_id}"
LIMITATION_DEGRADED_CAPABILITY = "degraded capability: {capability}"


class FinalizationGate:
    """Deterministic hard-blocker evaluation (P2 §29-§34)."""

    def __init__(self, *, policy_version: str = FINALIZATION_POLICY_VERSION):
        self.policy_version = policy_version

    def evaluate(
        self,
        task_id: str,
        state: AgentWorkingStateV1,
        request: FinalizationRequest,
        runtime: RuntimeFinalizationView,
    ) -> FinalizationDecision:
        violations: list[str] = []
        limitations: list[str] = []

        # -- integrity / runtime preflight --------------------------------
        if state.task_id != task_id or state.investigation_id != request.investigation_id:
            violations.append(IDENTITY_INVALID)
        if not runtime.store_ok:
            violations.append(STORE_UNAVAILABLE)
        if runtime.investigation_status != "active":
            violations.append(INVESTIGATION_NOT_ACTIVE)
        if runtime.transition_conflict_unresolved:
            violations.append(TRANSITION_CONFLICT_UNRESOLVED)
        if runtime.active_delegation_ids:
            violations.append(ACTIVE_DELEGATION_PRESENT)
        if runtime.completed_unintegrated_delegation_ids:
            violations.append(UNINTEGRATED_COMPLETED_DELEGATION)
        if any(not directive.applied for directive in state.directive_refs):
            violations.append(UNAPPLIED_DIRECTIVE_PRESENT)

        # -- mandatory verifications --------------------------------------
        for verification in state.pending_verifications:
            if not verification.required:
                continue
            if verification.status in (
                VerificationStatus.pending,
                VerificationStatus.failed,
                VerificationStatus.unavailable,
            ):
                violations.append(MANDATORY_VERIFICATION_BLOCKING)

        # -- required questions -------------------------------------------
        for question in state.questions:
            if question.priority.value != "required":
                continue
            if question.status == QuestionStatus.open:
                violations.append(REQUIRED_QUESTION_OPEN)
            elif question.status == QuestionStatus.in_progress:
                violations.append(REQUIRED_QUESTION_IN_PROGRESS)
            elif question.status == QuestionStatus.deferred:
                violations.append(REQUIRED_QUESTION_DEFERRED)
            elif question.status == QuestionStatus.answered:
                if question.disposition is None:
                    violations.append(QUESTION_DISPOSITION_REQUIRED)
            elif question.status == QuestionStatus.unresolved:
                if (
                    not question.basis_refs
                    or not question.limitations
                    or not question.investigated_summary
                ):
                    violations.append(QUESTION_CLOSURE_BASIS_REQUIRED)
                else:
                    limitations.append(
                        LIMITATION_UNRESOLVED_QUESTION.format(
                            question_id=question.question_id
                        )
                    )
            elif question.status == QuestionStatus.blocked:
                if not question.blocker:
                    violations.append(QUESTION_BLOCKER_REQUIRED)
                else:
                    limitations.append(
                        LIMITATION_BLOCKED_QUESTION.format(
                            question_id=question.question_id
                        )
                    )
            elif question.status == QuestionStatus.superseded:
                if not question.superseded_by_ref:
                    violations.append(QUESTION_SUPERSESSION_PROVENANCE_REQUIRED)

        # -- required coverage --------------------------------------------
        for dimension in state.coverage:
            if not dimension.required:
                continue
            if dimension.status in (CoverageStatus.not_started, CoverageStatus.in_progress):
                violations.append(COVERAGE_NOT_TERMINAL)
            elif dimension.status == CoverageStatus.partial:
                if not dimension.basis_refs or not dimension.limitation:
                    violations.append(COVERAGE_LIMITATION_REQUIRED)
                limitations.append(
                    LIMITATION_PARTIAL_COVERAGE.format(dimension_id=dimension.dimension_id)
                )
            elif dimension.status == CoverageStatus.unavailable:
                if not dimension.capability_basis:
                    violations.append(COVERAGE_UNAVAILABLE_WITHOUT_CAPABILITY_BASIS)
                limitations.append(
                    LIMITATION_UNAVAILABLE_COVERAGE.format(
                        dimension_id=dimension.dimension_id
                    )
                )
            elif dimension.status == CoverageStatus.covered:
                if not dimension.basis_refs:
                    violations.append(COVERAGE_BASIS_REQUIRED)
            # not_applicable: legal closure, never an automatic limitation

        # -- contradictions ------------------------------------------------
        for contradiction in state.contradictions:
            if contradiction.status == ContradictionStatus.open:
                if contradiction.severity.value == "critical":
                    violations.append(CRITICAL_CONTRADICTION_OPEN)
                else:
                    limitations.append(
                        LIMITATION_OPEN_CONTRADICTION.format(
                            contradiction_id=contradiction.contradiction_id
                        )
                    )
            elif contradiction.status == ContradictionStatus.unresolved:
                if contradiction.severity.value == "critical":
                    if (
                        not contradiction.resolution_basis_refs
                        or not contradiction.attempted_resolution
                        or not contradiction.impact
                        or not contradiction.limitation
                    ):
                        violations.append(CRITICAL_CONTRADICTION_BASIS_REQUIRED)
                    limitations.append(
                        LIMITATION_UNRESOLVED_CONTRADICTION.format(
                            contradiction_id=contradiction.contradiction_id
                        )
                    )

        # -- capability failure policy (P2 §33) ----------------------------
        for failure in request.capability_failures:
            if failure.category == CapabilityFailureCategory.integrity_critical:
                violations.append(INTEGRITY_CRITICAL_FAILURE)
            elif failure.category == CapabilityFailureCategory.semantic_required:
                if not failure.degraded:
                    violations.append(SEMANTIC_REQUIRED_NOT_DEGRADED)
                else:
                    limitations.append(
                        LIMITATION_DEGRADED_CAPABILITY.format(capability=failure.capability)
                    )
            # optional_enhancement failures never block finalization

        # -- final semantic review policy (P2 §34) --------------------------
        review = request.final_semantic_review
        review_unavailable_limitation = False
        if review.status == FinalSemanticReviewStatus.issues_found:
            violations.append(REVIEW_ISSUES_FOUND)
        elif review.status == FinalSemanticReviewStatus.unavailable:
            if request.review_mode == FinalReviewMode.required:
                violations.append(REVIEW_UNAVAILABLE)
            else:
                # best_effort: pass with a material limitation, provided all
                # other mandatory semantics above are satisfied
                limitations.append(LIMITATION_REVIEW_UNAVAILABLE)
                review_unavailable_limitation = True

        if violations:
            return FinalizationDecision(
                outcome=FinalizationOutcome.deny,
                policy_version=self.policy_version,
                violation_codes=tuple(violations),
                limitations=tuple(limitations),
            )
        completion_mode = (
            CompletionMode.complete_with_limitations
            if limitations
            else CompletionMode.complete
        )
        return FinalizationDecision(
            outcome=FinalizationOutcome.pass_,
            policy_version=self.policy_version,
            limitations=tuple(limitations),
            completion_mode=completion_mode,
        )

    def evaluate_stale(
        self,
        current_state_revision: int,
        request: FinalizationRequest,
    ) -> Optional[FinalizationDecision]:
        """Deterministic STALE check: the request must target the current
        committed revision."""
        if request.expected_state_revision != current_state_revision:
            return FinalizationDecision(
                outcome=FinalizationOutcome.stale,
                policy_version=self.policy_version,
                violation_codes=(STATE_REVISION_STALE,),
            )
        return None


def question_disposition_snapshot(
    state: AgentWorkingStateV1,
) -> dict:
    """Deterministic dispositions snapshot persisted with the record."""
    return {
        question.question_id: {
            "status": question.status.value,
            "disposition": (
                question.disposition.value if question.disposition else None
            ),
            "priority": question.priority.value,
        }
        for question in state.questions
    }


def coverage_disposition_snapshot(state: AgentWorkingStateV1) -> dict:
    return {
        dimension.dimension_id: {
            "status": dimension.status.value,
            "required": dimension.required,
        }
        for dimension in state.coverage
    }


def finalization_input_hash(
    state: AgentWorkingStateV1,
    request: FinalizationRequest,
    runtime: RuntimeFinalizationView,
    decision: FinalizationDecision,
) -> str:
    """Deterministic hash over the exact finalization inputs."""
    payload = json.dumps(
        {
            "state_revision": request.expected_state_revision,
            "state_hash": _state_content_hash(state),
            "request": request.model_dump(mode="json"),
            "runtime": runtime.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _state_content_hash(state: AgentWorkingStateV1) -> str:
    from .agent_runtime import canonical_state_json

    return hashlib.sha256(
        canonical_state_json(state.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()
