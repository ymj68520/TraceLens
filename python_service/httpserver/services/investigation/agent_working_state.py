"""Typed Working State contract for the Agent control plane (P2).

``AgentWorkingStateV1`` is the versioned Pydantic projection persisted through
the P1 immutable revision store (``agent_working_state_revisions.state_json``
stays the storage envelope).  It holds investigation semantics and references
only — never Evidence content, canonical Claim/Event/Analysis copies, Graph
payloads, agent conversations, or model-private reasoning.

P2 boundary notes:
  - Directive canonical persistence is still Architecture TBD: the state keeps
    only ref/digest entries (§10 of the P2 work order).
  - Pending verifications are deterministic placeholders (§11): P2 never runs
    a verifier, it only lets deterministic policies reason about blocking.
  - Entity/correlation canonical pipelines are P5; the state only carries
    opaque entity/finding/proposal refs.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

WORKING_STATE_SCHEMA_VERSION = "agent-working-state:v1"

STATE_TRANSITION_POLICY_VERSION = "state-transition:v1"
ATTENTION_POLICY_VERSION = "attention-policy:v1"
FINALIZATION_POLICY_VERSION = "finalization-policy:v1"
NO_PROGRESS_POLICY_VERSION = "no-progress-policy:v1"


class QuestionSource(str, Enum):
    charter = "charter"
    user_directive = "user_directive"
    playbook = "playbook"
    supervisor_discovery = "supervisor_discovery"
    specialist_discovery = "specialist_discovery"


class QuestionPriority(str, Enum):
    required = "required"
    high = "high"
    normal = "normal"
    exploratory = "exploratory"


class QuestionStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    answered = "answered"
    unresolved = "unresolved"
    blocked = "blocked"
    deferred = "deferred"
    superseded = "superseded"


class QuestionDisposition(str, Enum):
    supported = "supported"
    not_supported = "not_supported"
    inconclusive = "inconclusive"
    unavailable = "unavailable"
    not_applicable = "not_applicable"


class QuestionRelationType(str, Enum):
    blocks = "blocks"
    supports = "supports"
    explores = "explores"


class WorkingQuestion(BaseModel):
    """One investigation question (refs + semantics only, no Evidence)."""

    model_config = ConfigDict(frozen=True)

    question_id: str
    text: str
    source: QuestionSource
    priority: QuestionPriority
    status: QuestionStatus = QuestionStatus.open
    disposition: Optional[QuestionDisposition] = None
    parent_question_id: Optional[str] = None
    relations: tuple["QuestionRelation", ...] = ()
    basis_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    # closure evidence per required-question finalization rules (P2 §30)
    investigated_summary: Optional[str] = None
    blocker: Optional[str] = None
    superseded_by_ref: Optional[str] = None

    def is_terminal(self) -> bool:
        return self.status in (
            QuestionStatus.answered,
            QuestionStatus.unresolved,
            QuestionStatus.blocked,
            QuestionStatus.superseded,
        )


class QuestionRelation(BaseModel):
    """Directed relation between questions.  Only ``blocks`` propagates
    attention priority (P2 §22); ``supports`` / ``explores`` never do."""

    model_config = ConfigDict(frozen=True)

    question_id: str
    relation_type: QuestionRelationType


class CoverageStatus(str, Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    covered = "covered"
    partial = "partial"
    unavailable = "unavailable"
    not_applicable = "not_applicable"


COVERAGE_TERMINAL_STATUSES = frozenset(
    {
        CoverageStatus.covered,
        CoverageStatus.partial,
        CoverageStatus.unavailable,
        CoverageStatus.not_applicable,
    }
)


class CoverageDimension(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension_id: str
    required: bool = False
    status: CoverageStatus = CoverageStatus.not_started
    related_question_ids: tuple[str, ...] = ()
    basis_refs: tuple[str, ...] = ()
    limitation: Optional[str] = None
    # system/capability basis required for ``unavailable`` closure
    capability_basis: Optional[str] = None


class EvidenceRelevanceStatus(str, Enum):
    candidate = "candidate"
    relevant = "relevant"
    high_value = "high_value"
    irrelevant = "irrelevant"


class EvidenceWorkingSetItem(BaseModel):
    """A canonical Evidence reference with investigation relevance only.

    Identity stays ``(task_id, evidence_key)`` resolved through the existing
    Evidence resolver — no Evidence content is copied into the state.
    """

    model_config = ConfigDict(frozen=True)

    evidence_key: str
    status: EvidenceRelevanceStatus = EvidenceRelevanceStatus.candidate
    related_question_ids: tuple[str, ...] = ()


class HypothesisStatus(str, Enum):
    active = "active"
    supported = "supported"
    weakened = "weakened"
    rejected = "rejected"
    retired = "retired"


class Hypothesis(BaseModel):
    """An investigation tool — never a canonical Finding (no transition from
    hypothesis to accepted finding exists in the typed transition family)."""

    model_config = ConfigDict(frozen=True)

    hypothesis_id: str
    text: str
    status: HypothesisStatus = HypothesisStatus.active
    supporting_refs: tuple[str, ...] = ()
    contradicting_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class ContradictionSeverity(str, Enum):
    low = "low"
    material = "material"
    critical = "critical"


class ContradictionStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    explained = "explained"
    unresolved = "unresolved"


class Contradiction(BaseModel):
    model_config = ConfigDict(frozen=True)

    contradiction_id: str
    severity: ContradictionSeverity
    status: ContradictionStatus = ContradictionStatus.open
    refs: tuple[str, ...] = ()
    resolution_basis_refs: tuple[str, ...] = ()
    attempted_resolution: Optional[str] = None
    impact: Optional[str] = None
    limitation: Optional[str] = None


class DirectiveDigest(BaseModel):
    """Directive ref/digest only — canonical Directive persistence is still
    Architecture TBD; P2 must not create a directive subsystem."""

    model_config = ConfigDict(frozen=True)

    directive_ref: str
    kind: Optional[str] = None
    applied: bool = False
    effect_digest: Optional[str] = None


class VerificationStatus(str, Enum):
    pending = "pending"
    passed = "passed"
    failed = "failed"
    unavailable = "unavailable"


class PendingVerification(BaseModel):
    """Deterministic verification placeholder (P5 provides the real
    SemanticVerifier).  Exists so policy can reason about blocking only."""

    model_config = ConfigDict(frozen=True)

    verification_id: str
    target_ref: str
    required: bool = False
    blocking: bool = False
    status: VerificationStatus = VerificationStatus.pending


class ProgressState(BaseModel):
    model_config = ConfigDict(frozen=True)

    completed_cycles: int = 0
    consecutive_no_progress_cycles: int = 0


class BudgetState(BaseModel):
    model_config = ConfigDict(frozen=True)

    exhausted: bool = False
    # calibration-era free digest; P2 defines no budget model
    limits_digest: Optional[str] = None


class AgentWorkingStateV1(BaseModel):
    """Minimal typed v1 investigation Working State."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["agent-working-state:v1"] = WORKING_STATE_SCHEMA_VERSION
    task_id: str
    investigation_id: str
    charter_ref: Optional[str] = None
    objective: Optional[str] = None

    questions: tuple[WorkingQuestion, ...] = ()
    coverage: tuple[CoverageDimension, ...] = ()
    evidence_working_set: tuple[EvidenceWorkingSetItem, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    contradictions: tuple[Contradiction, ...] = ()
    finding_refs: tuple[str, ...] = ()
    entity_refs: tuple[str, ...] = ()
    pending_proposal_refs: tuple[str, ...] = ()

    directive_refs: tuple[DirectiveDigest, ...] = ()
    pending_verifications: tuple[PendingVerification, ...] = ()

    progress_state: ProgressState = ProgressState()
    budget_state: BudgetState = BudgetState()

    @model_validator(mode="after")
    def _validate_integrity(self) -> "AgentWorkingStateV1":
        question_ids = [q.question_id for q in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("duplicate question_id in working state")
        dimension_ids = [c.dimension_id for c in self.coverage]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("duplicate dimension_id in working state")
        hypothesis_ids = [h.hypothesis_id for h in self.hypotheses]
        if len(hypothesis_ids) != len(set(hypothesis_ids)):
            raise ValueError("duplicate hypothesis_id in working state")
        contradiction_ids = [c.contradiction_id for c in self.contradictions]
        if len(contradiction_ids) != len(set(contradiction_ids)):
            raise ValueError("duplicate contradiction_id in working state")
        verification_ids = [v.verification_id for v in self.pending_verifications]
        if len(verification_ids) != len(set(verification_ids)):
            raise ValueError("duplicate verification_id in working state")
        evidence_keys = [e.evidence_key for e in self.evidence_working_set]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("duplicate evidence_key in working state")

        known_ids = set(question_ids)
        for question in self.questions:
            if question.parent_question_id is not None and (
                question.parent_question_id not in known_ids
            ):
                raise ValueError(
                    f"question {question.question_id!r} has unknown parent "
                    f"{question.parent_question_id!r}"
                )
            for relation in question.relations:
                if relation.question_id not in known_ids:
                    raise ValueError(
                        f"question {question.question_id!r} relation targets "
                        f"unknown question {relation.question_id!r}"
                    )
        for dimension in self.coverage:
            unknown = set(dimension.related_question_ids) - known_ids
            if unknown:
                raise ValueError(
                    f"coverage {dimension.dimension_id!r} references unknown "
                    f"questions {sorted(unknown)}"
                )
        for item in self.evidence_working_set:
            unknown = set(item.related_question_ids) - known_ids
            if unknown:
                raise ValueError(
                    f"evidence {item.evidence_key!r} references unknown "
                    f"questions {sorted(unknown)}"
                )
        return self

    # ------------------------------------------------------------------
    # lookup helpers (deterministic projections used by policies)
    # ------------------------------------------------------------------

    def question(self, question_id: str) -> Optional[WorkingQuestion]:
        for question in self.questions:
            if question.question_id == question_id:
                return question
        return None

    def coverage_dimension(self, dimension_id: str) -> Optional[CoverageDimension]:
        for dimension in self.coverage:
            if dimension.dimension_id == dimension_id:
                return dimension
        return None

    def hypothesis(self, hypothesis_id: str) -> Optional[Hypothesis]:
        for hypothesis in self.hypotheses:
            if hypothesis.hypothesis_id == hypothesis_id:
                return hypothesis
        return None

    def contradiction(self, contradiction_id: str) -> Optional[Contradiction]:
        for contradiction in self.contradictions:
            if contradiction.contradiction_id == contradiction_id:
                return contradiction
        return None

    def verification(self, verification_id: str) -> Optional[PendingVerification]:
        for verification in self.pending_verifications:
            if verification.verification_id == verification_id:
                return verification
        return None

    def evidence_item(self, evidence_key: str) -> Optional[EvidenceWorkingSetItem]:
        for item in self.evidence_working_set:
            if item.evidence_key == evidence_key:
                return item
        return None

    def with_replacements(self, **changes) -> "AgentWorkingStateV1":
        return self.model_copy(update=changes)


def working_state_from_json(
    task_id: str, investigation_id: str, state: dict
) -> AgentWorkingStateV1:
    """Validate a persisted revision payload as the v1 typed state."""
    if not isinstance(state, dict):
        raise ValueError("working state payload must be a JSON object")
    if state.get("schema_version") != WORKING_STATE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported working state schema_version: "
            f"{state.get('schema_version')!r}"
        )
    loaded = AgentWorkingStateV1.model_validate(state)
    if loaded.task_id != task_id or loaded.investigation_id != investigation_id:
        raise ValueError(
            "working state identity does not match the revision owner"
        )
    return loaded


def working_state_to_json(state: AgentWorkingStateV1) -> dict:
    """Canonical JSON-ready dict (mode=json; tuples become lists)."""
    return state.model_dump(mode="json")
