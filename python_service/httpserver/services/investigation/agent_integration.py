"""Agent result merge + integration contracts (P4B-2).

MergeGuard — deterministic freshness verdict for a completed delegation's
result. A result is stale ONLY when a real semantic dependency changed:

    question no longer active
    source scope materially changed
    referenced Evidence invalidated (injected seam)
    relevant bound Directive changed
    recorded semantic assumption invalidated (bound hypothesis rejected)

``current revision != based_on revision`` is NEVER stale by itself — the
investigation may have moved for unrelated reasons while this delegation
was executing.

Everything here is proposal-side bookkeeping: no canonical Claim/Finding,
no review mutation, no Graph/Report write.
"""

import enum
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from .agent_runtime import canonical_state_json, state_hash_of
from .agent_specialist_result import SpecialistResultV1
from .agent_supervisor import QuestionIndexEntry, SupervisorPlanningContextPack

INTEGRATION_CONTEXT_VERSION = "integration-context:v1"
INTEGRATION_POLICY_VERSION = "supervisor-integration-policy:v1"


# ---------------------------------------------------------------------------
# FailureDigest (P4B §11)
# ---------------------------------------------------------------------------


class FailureDigest(BaseModel):
    """Compact deterministic digest of one terminal non-success worker.

    Not Evidence, not an Investigation fact: a runtime failure must never be
    dressed up as evidence absence. The supervisor may propose questions or
    coverage limitations from it — nothing canonical."""

    model_config = ConfigDict(frozen=True)

    delegation_id: str
    question_id: Optional[str] = None
    source_scope_id: Optional[str] = None
    terminal_status: str
    failure_code: Optional[str] = None
    failure_summary: Optional[str] = None
    context_hash: Optional[str] = None
    result_hash: Optional[str] = None

    def digest(self) -> str:
        return state_hash_of(canonical_state_json(self.model_dump()))


# ---------------------------------------------------------------------------
# MergeGuard
# ---------------------------------------------------------------------------


class MergeStaleReason(str, enum.Enum):
    QUESTION_INACTIVE = "MERGE_STALE_QUESTION_INACTIVE"
    QUESTION_UNKNOWN = "MERGE_STALE_QUESTION_UNKNOWN"
    SOURCE_SCOPE_CHANGED = "MERGE_STALE_SOURCE_SCOPE_CHANGED"
    EVIDENCE_INVALIDATED = "MERGE_STALE_EVIDENCE_INVALIDATED"
    DIRECTIVE_CHANGED = "MERGE_STALE_DIRECTIVE_CHANGED"
    ASSUMPTION_INVALIDATED = "MERGE_STALE_ASSUMPTION_INVALIDATED"


class MergeVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    fresh: bool
    reason_codes: tuple[str, ...] = ()
    details: str = ""

    @property
    def stale(self) -> bool:
        return not self.fresh


class FrozenDelegationDependencies(BaseModel):
    """What the delegation's result semantically depended on, frozen at
    dispatch (from the envelope / planning context)."""

    model_config = ConfigDict(frozen=True)

    delegation_id: str
    question_id: Optional[str] = None
    source_scope_ids: tuple[str, ...] = ()
    based_on_state_revision: Optional[int] = None
    directive_digests: tuple[str, ...] = ()
    hypothesis_refs: tuple[str, ...] = ()  # semantic assumptions in play
    evidence_refs: tuple[str, ...] = ()


class MergeGuard:
    """Deterministic post-execution freshness check (P4B §10).

    Version provenance (profile/skill/registry hashes — P4A) is never a
    staleness input: it proves how the result was generated, and a catalog
    upgrade after execution does not invalidate it. Only real semantic
    dependency invalidation does.
    """

    def __init__(
        self,
        *,
        evidence_invalidation_checker: Optional[Callable[[str], bool]] = None,
    ):
        # seam: ref -> True when the evidence it cites was invalidated
        # (snapshot invalidated / source materially changed). Injected from
        # the existing evidence read path; default: nothing invalidated.
        self._evidence_checker = evidence_invalidation_checker

    def evaluate(
        self,
        dependencies: FrozenDelegationDependencies,
        *,
        current_state: Any,
        current_state_revision: int,
        current_directive_digests: Optional[Mapping[str, str]] = None,
        granted_scope_ids: Sequence[str] = (),
    ) -> MergeVerdict:
        current_directive_digests = current_directive_digests or {}
        reasons: list[str] = []

        # question lifecycle
        if dependencies.question_id is not None:
            status = self._question_status(current_state, dependencies.question_id)
            if status is None:
                reasons.append(MergeStaleReason.QUESTION_UNKNOWN.value)
            elif status not in ("open", "in_progress"):
                reasons.append(MergeStaleReason.QUESTION_INACTIVE.value)

        # source scope materially changed: a scope the delegation ran on is
        # no longer granted to the investigation. Unrelated scope changes
        # (new scopes added) keep the result fresh.
        if dependencies.source_scope_ids and granted_scope_ids:
            missing = [
                scope
                for scope in dependencies.source_scope_ids
                if scope not in set(granted_scope_ids)
            ]
            if missing:
                reasons.append(MergeStaleReason.SOURCE_SCOPE_CHANGED.value)

        # referenced Evidence invalidated (seam)
        if self._evidence_checker is not None:
            for ref in dependencies.evidence_refs:
                try:
                    if self._evidence_checker(ref):
                        reasons.append(
                            MergeStaleReason.EVIDENCE_INVALIDATED.value
                        )
                        break
                except Exception:  # noqa: BLE001 - fail closed on seam errors
                    reasons.append(MergeStaleReason.EVIDENCE_INVALIDATED.value)
                    break

        # bound Directive changed (only directives bound at dispatch matter;
        # new unrelated directives keep the result fresh — §24)
        for digest in dependencies.directive_digests:
            if digest not in set(current_directive_digests.values()):
                reasons.append(MergeStaleReason.DIRECTIVE_CHANGED.value)
                break

        # recorded semantic assumption invalidated (bound hypothesis rejected)
        for hypothesis_ref in dependencies.hypothesis_refs:
            status = self._hypothesis_status(current_state, hypothesis_ref)
            if status == "rejected":
                reasons.append(
                    MergeStaleReason.ASSUMPTION_INVALIDATED.value
                )
                break

        # NOTE: current_state_revision != dependencies.based_on_state_revision
        # is deliberately NOT a staleness reason (P4B §10.1).

        return MergeVerdict(
            fresh=not reasons,
            reason_codes=tuple(dict.fromkeys(reasons)),
            details=(
                "stale: semantic dependencies changed"
                if reasons
                else "fresh: all semantic dependencies unchanged"
            ),
        )

    @staticmethod
    def _question_status(current_state, question_id: str) -> Optional[str]:
        for question in getattr(current_state, "questions", ()):
            if question.question_id == question_id:
                return question.status.value
        return None

    @staticmethod
    def _hypothesis_status(current_state, hypothesis_id: str) -> Optional[str]:
        for hypothesis in getattr(current_state, "hypotheses", ()):
            if hypothesis.hypothesis_id == hypothesis_id:
                return hypothesis.status.value
        return None


# ---------------------------------------------------------------------------
# IntegrationContextPack (P4B §12)
# ---------------------------------------------------------------------------


class FreshResultEnvelope(BaseModel):
    """One fresh, MergeGuard-validated SpecialistResult + its provenance."""

    model_config = ConfigDict(frozen=True)

    delegation_id: str
    question_id: Optional[str] = None
    source_scope_id: Optional[str] = None
    result: SpecialistResultV1
    result_hash: str
    context_hash: Optional[str] = None


class StaleResultDigest(BaseModel):
    model_config = ConfigDict(frozen=True)

    delegation_id: str
    result_hash: Optional[str] = None
    reason_codes: tuple[str, ...] = ()


class IntegrationContextPack(BaseModel):
    """Only validated/terminal inputs. Raw provider conversations, chat
    history, full tool observation bodies and unvalidated agent output are
    structurally absent."""

    model_config = ConfigDict(frozen=True)

    context_version: str = INTEGRATION_CONTEXT_VERSION
    integration_policy_version: str = INTEGRATION_POLICY_VERSION

    task_id: str
    investigation_id: str
    run_id: Optional[str] = None

    state_revision: int
    state_hash: str

    state_slice_digests: tuple[str, ...] = ()

    fresh_results: tuple[FreshResultEnvelope, ...] = ()
    stale_result_digests: tuple[StaleResultDigest, ...] = ()
    failure_digests: tuple[FailureDigest, ...] = ()

    source_result_hashes: tuple[str, ...] = ()
    relevant_evidence_refs: tuple[str, ...] = ()
    attention_refs: tuple[str, ...] = ()
    directive_digests: tuple[str, ...] = ()

    phase_capabilities: tuple[str, ...] = (
        "typed_transition_proposals",
        "pending_proposal_references",
        "hypothesis_creation",
    )

    def input_hash(self) -> str:
        return state_hash_of(canonical_state_json(self.model_dump()))

    def source_result_ids(self) -> tuple[str, ...]:
        return tuple(env.delegation_id for env in self.fresh_results)

    def source_result_hashes(self) -> tuple[str, ...]:
        return tuple(env.result_hash for env in self.fresh_results)


# ---------------------------------------------------------------------------
# SupervisorIntegrationDecisionV1 (P4B §14)
# ---------------------------------------------------------------------------


class SupervisorIntegrationDecisionV1(BaseModel):
    """Structured integration proposal. Typed P2 transition models only —
    never a complete Working State, JSON patch, SQL, canonical claim, review
    acceptance or Graph/Report mutation."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    decision_version: str = "supervisor-integration-decision:v1"
    task_id: str
    investigation_id: str
    run_id: Optional[str] = None

    based_on_state_revision: int
    based_on_state_hash: str

    source_result_ids: tuple[str, ...] = ()
    source_result_hashes: tuple[str, ...] = ()

    transition_proposals: tuple[Any, ...] = ()  # typed P2 transition models

    integration_summary: str = ""
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def decision_hash(self) -> str:
        return state_hash_of(canonical_state_json(self.model_dump()))


# ---------------------------------------------------------------------------
# Integration decision validator (P4B §17)
# ---------------------------------------------------------------------------


class IntegrationViolationCode(str, enum.Enum):
    INTEGRATION_VERSION_UNSUPPORTED = "INTEGRATION_VERSION_UNSUPPORTED"
    INTEGRATION_IDENTITY_MISMATCH = "INTEGRATION_IDENTITY_MISMATCH"
    INTEGRATION_STATE_REVISION_STALE = "INTEGRATION_STATE_REVISION_STALE"
    INTEGRATION_SOURCE_RESULT_UNKNOWN = "INTEGRATION_SOURCE_RESULT_UNKNOWN"
    INTEGRATION_SOURCE_RESULT_HASH_MISMATCH = "INTEGRATION_SOURCE_RESULT_HASH_MISMATCH"
    INTEGRATION_SOURCE_RESULT_NOT_FRESH = "INTEGRATION_SOURCE_RESULT_NOT_FRESH"
    INTEGRATION_TRANSITION_TYPE_NOT_ALLOWED = "INTEGRATION_TRANSITION_TYPE_NOT_ALLOWED"
    INTEGRATION_BASIS_REF_UNKNOWN = "INTEGRATION_BASIS_REF_UNKNOWN"
    INTEGRATION_EVIDENCE_REF_INVALID = "INTEGRATION_EVIDENCE_REF_INVALID"
    INTEGRATION_SCOPE_MUTATION_FORBIDDEN = "INTEGRATION_SCOPE_MUTATION_FORBIDDEN"
    INTEGRATION_REVIEW_MUTATION_FORBIDDEN = "INTEGRATION_REVIEW_MUTATION_FORBIDDEN"
    INTEGRATION_GRAPH_MUTATION_FORBIDDEN = "INTEGRATION_GRAPH_MUTATION_FORBIDDEN"
    INTEGRATION_REPORT_MUTATION_FORBIDDEN = "INTEGRATION_REPORT_MUTATION_FORBIDDEN"


# P4B allowed typed proposal set (reuses P2 models; no second contract).
# AddEntityReference / AddFindingReference / ModifyScope are P5+ and are
# rejected here by name even though the P2 contract defines them.
P4B_ALLOWED_TRANSITION_TYPES: tuple[str, ...] = (
    "QuestionTransition",
    "CreateQuestion",
    "EvidenceRelevanceTransition",
    "CreateHypothesis",
    "HypothesisTransition",
    "CreateContradiction",
    "ContradictionTransition",
    "CoverageTransition",
    "AddPendingProposalReference",
)
_FORBIDDEN_TRANSITION_TYPES = {
    "AddEntityReference": "graph/identity pipeline arrives in P5",
    "AddFindingReference": "canonical findings arrive in P5",
    "ModifyScope": "hard scope mutation is never agent-reachable",
}


class IntegrationDecisionValidator:
    """Structural accept/reject gate in front of the P2
    StateTransitionPolicy. It cannot repair semantic intent; it checks
    bindings, provenance and the frozen P4B capability envelope."""

    def __init__(
        self,
        *,
        evidence_ref_validator: Optional[Callable[[str], None]] = None,
    ):
        self._evidence_ref_validator = evidence_ref_validator

    def validate(
        self,
        context: IntegrationContextPack,
        decision: SupervisorIntegrationDecisionV1,
    ) -> "IntegrationValidation":
        from .agent_transitions import ModifyScope

        violations: list[tuple[IntegrationViolationCode, str, str]] = []

        if decision.decision_version != "supervisor-integration-decision:v1":
            violations.append((
                IntegrationViolationCode.INTEGRATION_VERSION_UNSUPPORTED,
                "unsupported integration decision version",
                "decision_version",
            ))
        if (
            decision.task_id != context.task_id
            or decision.investigation_id != context.investigation_id
            or decision.run_id != context.run_id
        ):
            violations.append((
                IntegrationViolationCode.INTEGRATION_IDENTITY_MISMATCH,
                "decision identity does not match the integration context",
                "identity",
            ))
        if (
            decision.based_on_state_revision != context.state_revision
            or decision.based_on_state_hash != context.state_hash
        ):
            violations.append((
                IntegrationViolationCode.INTEGRATION_STATE_REVISION_STALE,
                "decision is bound to a different working state",
                "based_on_state_revision",
            ))

        known_hashes = {
            env.delegation_id: env.result_hash
            for env in context.fresh_results
        }
        for delegation_id, claimed_hash in zip(
            decision.source_result_ids, decision.source_result_hashes
        ):
            actual = known_hashes.get(delegation_id)
            if actual is None:
                violations.append((
                    IntegrationViolationCode.INTEGRATION_SOURCE_RESULT_UNKNOWN,
                    "source result is not a fresh validated result",
                    f"source_result_ids[{delegation_id}]",
                ))
            elif actual != claimed_hash:
                violations.append((
                    IntegrationViolationCode.INTEGRATION_SOURCE_RESULT_HASH_MISMATCH,
                    "source result hash does not match the persisted record",
                    f"source_result_ids[{delegation_id}]",
                ))

        state_questions = set(context_state_question_ids(context))

        allowed = set(P4B_ALLOWED_TRANSITION_TYPES)
        from .agent_transitions import (
            QuestionTransition as _QT,
            CreateQuestion as _CQ,
            EvidenceRelevanceTransition as _ERT,
            CreateHypothesis as _CH,
            HypothesisTransition as _HT,
            CreateContradiction as _CC,
            ContradictionTransition as _CT,
            CoverageTransition as _CVT,
            AddPendingProposalReference as _APP,
        )

        typed_members = (_QT, _CQ, _ERT, _CH, _HT, _CC, _CT, _CVT, _APP)
        for index, proposal in enumerate(decision.transition_proposals):
            location = f"transition_proposals[{index}]"
            type_name = type(proposal).__name__
            if type_name == "ModifyScope":
                violations.append((
                    IntegrationViolationCode.INTEGRATION_SCOPE_MUTATION_FORBIDDEN,
                    "hard scope mutation is never agent-reachable",
                    location,
                ))
                continue
            if not isinstance(proposal, typed_members):
                # generic dict / patch payloads are structurally rejected
                violations.append((
                    IntegrationViolationCode.INTEGRATION_TRANSITION_TYPE_NOT_ALLOWED,
                    "transition proposals must be typed P2 transition models",
                    location,
                ))
                continue
            if type_name not in allowed:
                message = f"transition type {type_name!r} is not a P4B capability"
                if type_name in _FORBIDDEN_TRANSITION_TYPES:
                    message = (
                        f"transition type {type_name!r} is forbidden in P4B: "
                        + _FORBIDDEN_TRANSITION_TYPES[type_name]
                    )
                violations.append((
                    IntegrationViolationCode.INTEGRATION_TRANSITION_TYPE_NOT_ALLOWED,
                    message,
                    location,
                ))
                continue
            # basis/evidence refs must be task-scoped
            for ref in _transition_evidence_refs(proposal):
                from .evidence.exceptions import InvalidEvidenceKeyError
                from .evidence.keys import parse_evidence_key

                try:
                    parse_evidence_key(ref)
                except InvalidEvidenceKeyError:
                    violations.append((
                        IntegrationViolationCode.INTEGRATION_EVIDENCE_REF_INVALID,
                        "proposal carries a malformed evidence reference",
                        location,
                    ))
                if self._evidence_ref_validator is not None:
                    try:
                        self._evidence_ref_validator(ref)
                    except Exception:
                        violations.append((
                            IntegrationViolationCode.INTEGRATION_EVIDENCE_REF_INVALID,
                            "proposal evidence reference failed task scoping",
                            location,
                        ))
            # question-binding refs must belong to the context state
            for question_ref in _transition_question_refs(proposal):
                if question_ref and question_ref not in state_questions:
                    violations.append((
                        IntegrationViolationCode.INTEGRATION_BASIS_REF_UNKNOWN,
                        "proposal references a question outside the "
                        "integration context",
                        location,
                    ))

        return IntegrationValidation(
            valid=not violations,
            violations=tuple(
                IntegrationViolation(code=code, message=message, location=loc)
                for code, message, loc in violations
            ),
        )


class IntegrationViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: IntegrationViolationCode
    message: str
    location: str = ""


class IntegrationValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    violations: tuple[IntegrationViolation, ...] = ()

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(v.code.value for v in self.violations)


def context_state_question_ids(context: IntegrationContextPack) -> set[str]:
    """Question ids inside the integration context's state slice digest set
    (the pack records question identity entries alongside digests)."""
    ids = set()
    for entry in context.state_slice_digests:
        if entry.startswith("question:"):
            ids.add(entry.split(":", 1)[1])
    return ids


def _transition_evidence_refs(proposal: Any) -> tuple[str, ...]:
    refs = getattr(proposal, "evidence_refs", None) or ()
    basis = getattr(proposal, "basis_refs", None) or ()
    return tuple(ref for ref in tuple(refs) + tuple(basis) if isinstance(ref, str))


def _transition_question_refs(proposal: Any) -> tuple[str, ...]:
    refs: list[str] = []
    question_id = getattr(proposal, "question_id", None)
    if question_id:
        refs.append(str(question_id))
    related = getattr(proposal, "related_question_ids", None) or ()
    refs.extend(str(ref) for ref in related if ref)
    return tuple(refs)


def build_integration_context(
    *,
    task_id: str,
    investigation_id: str,
    run_id: Optional[str],
    state,
    state_revision: int,
    state_hash: str,
    fresh_results: Sequence[FreshResultEnvelope] = (),
    stale_result_digests: Sequence[StaleResultDigest] = (),
    failure_digests: Sequence[FailureDigest] = (),
    attention_refs: Sequence[str] = (),
    current_directive_digests: Mapping[str, str] = {},
) -> IntegrationContextPack:
    """Deterministically assemble the frozen integration input (§12).

    The state slice records question identity entries (``question:<id>``)
    so the decision validator can bind proposal refs to the context."""
    relevant_refs: set[str] = set()
    for env in fresh_results:
        relevant_refs.update(env.result.iter_evidence_refs())
    question_entries = tuple(
        f"question:{question.question_id}"
        for question in sorted(state.questions, key=lambda q: q.question_id)
    )
    state_slice = tuple(
        sorted(
            question_entries
            + tuple(
                f"directive:{ref}"
                for ref in sorted(current_directive_digests)
            )
        )
    )
    return IntegrationContextPack(
        task_id=task_id,
        investigation_id=investigation_id,
        run_id=run_id,
        state_revision=state_revision,
        state_hash=state_hash,
        state_slice_digests=state_slice,
        fresh_results=tuple(
            sorted(fresh_results, key=lambda env: env.delegation_id)
        ),
        stale_result_digests=tuple(
            sorted(stale_result_digests, key=lambda d: d.delegation_id)
        ),
        failure_digests=tuple(
            sorted(failure_digests, key=lambda d: d.delegation_id)
        ),
        source_result_hashes=tuple(env.result_hash for env in sorted(
            fresh_results, key=lambda env: env.delegation_id
        )),
        relevant_evidence_refs=tuple(sorted(relevant_refs)),
        attention_refs=tuple(sorted(set(attention_refs))),
        directive_digests=tuple(
            current_directive_digests[ref] for ref in sorted(current_directive_digests)
        ),
    )


__all__ = [
    "FailureDigest",
    "FreshResultEnvelope",
    "FrozenDelegationDependencies",
    "INTEGRATION_CONTEXT_VERSION",
    "INTEGRATION_POLICY_VERSION",
    "IntegrationContextPack",
    "IntegrationDecisionValidator",
    "IntegrationViolation",
    "IntegrationViolationCode",
    "IntegrationValidation",
    "MergeGuard",
    "MergeStaleReason",
    "MergeVerdict",
    "P4B_ALLOWED_TRANSITION_TYPES",
    "StaleResultDigest",
    "SupervisorIntegrationDecisionV1",
]
