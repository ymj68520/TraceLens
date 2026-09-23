"""SpecialistResultV1 — the frozen structured output contract for one
Source Specialist delegation (P4A).

This replaces the P3 placeholder reference ``specialist-result:P4-placeholder``.
Everything in a result is a PROPOSAL: claim/entity/correlation candidates are
never canonical Claims/Entities/Correlations, never Findings, never accepted
semantic facts. Canonical state advancement stays behind the P2
StateTransitionPolicy and arrives in P4B.

Evidence-ref rule (frozen): every evidence ref anywhere in the result must be
inside the delegation's visible Evidence set —

    allowed_evidence_ids = ContextPack initial refs ∪ successful
                           ToolObservation refs

A real-but-never-exposed evidence key is INVALID; a guessed (but
well-formed) evidence key is INVALID; a cross-task key is INVALID. P4A never
auto-acquires Evidence to rescue a citation.
"""

from enum import Enum
from typing import Any, Iterable, Mapping, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from .agent_context import SpecialistContextPack
from .agent_runtime import ToolObservation, canonical_state_json, state_hash_of
from .agent_tools.visibility import reconstruct_allowed_evidence_ids

SPECIALIST_RESULT_VERSION = "specialist-result:v1"


class AssertionClass(str, Enum):
    """Proposed assertion ceiling only — real assertion policy is P5."""

    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"


class SpecialistClaimCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    text: str
    assertion_class: AssertionClass
    evidence_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class SpecialistEntityCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    raw_value: str
    normalized_candidate: Optional[str] = None
    entity_type_candidate: Optional[str] = None
    evidence_refs: tuple[str, ...] = ()


class SpecialistCorrelationCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    subject_ref: str
    object_ref: str
    relation_hint: str
    evidence_refs: tuple[str, ...] = ()
    assertion_hint: Optional[str] = None


class SpecialistFollowUpQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    follow_up_id: str
    text: str
    suggested_source_scope_ids: tuple[str, ...] = ()


class SpecialistCoverageObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str
    dimension_id: Optional[str] = None
    note: str
    evidence_refs: tuple[str, ...] = ()


class ExecutionDigest(BaseModel):
    """Agent-run usage facts. Missing metrics stay None — never fabricated."""

    model_config = ConfigDict(frozen=True)

    model_name: Optional[str] = None
    request_count: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    tool_call_count: int = 0
    observation_count: int = 0


class SpecialistResultV1(BaseModel):
    """One delegation's structured proposal set (version-frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result_version: str = SPECIALIST_RESULT_VERSION
    delegation_id: str
    question_id: Optional[str] = None

    summary: str

    claim_candidates: tuple[SpecialistClaimCandidate, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    entity_candidates: tuple[SpecialistEntityCandidate, ...] = ()
    correlation_candidates: tuple[SpecialistCorrelationCandidate, ...] = ()

    follow_up_questions: tuple[SpecialistFollowUpQuestion, ...] = ()
    coverage_observations: tuple[SpecialistCoverageObservation, ...] = ()

    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    execution_digest: ExecutionDigest = ExecutionDigest()

    @field_validator("result_version")
    @classmethod
    def _check_version(cls, value: str) -> str:
        if value != SPECIALIST_RESULT_VERSION:
            raise ValueError(
                f"unsupported result version {value!r} "
                f"(expected {SPECIALIST_RESULT_VERSION!r})"
            )
        return value

    def result_hash(self) -> str:
        """Deterministic content hash (same result -> same hash)."""
        return state_hash_of(canonical_state_json(self.model_dump()))

    def iter_evidence_refs(self) -> Iterable[str]:
        """Every evidence ref carried anywhere in the result."""
        yield from self.evidence_refs
        for candidate in self.claim_candidates:
            yield from candidate.evidence_refs
        for candidate in self.entity_candidates:
            yield from candidate.evidence_refs
        for candidate in self.correlation_candidates:
            yield from candidate.evidence_refs
        for observation in self.coverage_observations:
            yield from observation.evidence_refs


# ---------------------------------------------------------------------------
# deterministic validation (no case-semantics judgement)
# ---------------------------------------------------------------------------


class ResultViolationCode(str, Enum):
    RESULT_VERSION_UNSUPPORTED = "RESULT_VERSION_UNSUPPORTED"
    RESULT_DELEGATION_MISMATCH = "RESULT_DELEGATION_MISMATCH"
    RESULT_QUESTION_MISMATCH = "RESULT_QUESTION_MISMATCH"

    RESULT_EVIDENCE_REF_INVALID = "RESULT_EVIDENCE_REF_INVALID"
    RESULT_EVIDENCE_NOT_VISIBLE = "RESULT_EVIDENCE_NOT_VISIBLE"
    RESULT_EVIDENCE_CROSS_TASK = "RESULT_EVIDENCE_CROSS_TASK"

    RESULT_DUPLICATE_CANDIDATE_ID = "RESULT_DUPLICATE_CANDIDATE_ID"

    RESULT_CANDIDATE_TEXT_INVALID = "RESULT_CANDIDATE_TEXT_INVALID"

    RESULT_SCOPE_EXPANSION_NOT_ALLOWED = "RESULT_SCOPE_EXPANSION_NOT_ALLOWED"

    RESULT_REVIEW_STATE_FORBIDDEN = "RESULT_REVIEW_STATE_FORBIDDEN"
    RESULT_GRAPH_STATE_FORBIDDEN = "RESULT_GRAPH_STATE_FORBIDDEN"
    RESULT_REPORT_STATE_FORBIDDEN = "RESULT_REPORT_STATE_FORBIDDEN"


class ResultViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: ResultViolationCode
    message: str
    location: str = ""


class SpecialistResultValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    violations: tuple[ResultViolation, ...] = ()

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(v.code.value for v in self.violations)


# candidate payload keys that would smuggle in canonical/review semantics
_FORBIDDEN_PAYLOAD_KEYS = {
    "review_status",
    "review_state",
    "accepted",
    "rejected",
    "decision",
    "decision_status",
    "finding_id",
    "finding_ref",
    "graph_ref",
    "graph_node",
    "graph_node_id",
    "report_ref",
    "report_section",
    "canonical_claim_id",
    "canonical_entity_id",
}
# value prefixes that would reference Graph/Report state
_GRAPH_REF_PREFIXES = ("graph:", "neo4j:", "graphiti:")
_REPORT_REF_PREFIXES = ("report:", "report-version:")


class SpecialistResultValidator:
    """Deterministic output validator (P4A §7).

    Checks identity bindings, output version, Evidence visibility, candidate
    hygiene and forbidden-state smuggling. Never judges case semantics.
    """

    def __init__(
        self,
        *,
        cross_task_ref_validator: Optional[Any] = None,
    ):
        # optional injected seam: callable(ref, task_id) raising on
        # cross-task refs (same pattern as the tool registry seam)
        self._cross_task_ref_validator = cross_task_ref_validator

    def validate(
        self,
        pack: SpecialistContextPack,
        result: SpecialistResultV1,
        observations: Iterable[ToolObservation],
    ) -> SpecialistResultValidation:
        violations: list[ResultViolation] = []

        # identity / version bindings
        if result.result_version != SPECIALIST_RESULT_VERSION:
            violations.append(
                ResultViolation(
                    code=ResultViolationCode.RESULT_VERSION_UNSUPPORTED,
                    message=f"unsupported result version {result.result_version!r}",
                    location="result_version",
                )
            )
        if pack.delegation_id and result.delegation_id != pack.delegation_id:
            violations.append(
                ResultViolation(
                    code=ResultViolationCode.RESULT_DELEGATION_MISMATCH,
                    message="result delegation identity does not match the "
                    "delegation executing it",
                    location="delegation_id",
                )
            )
        if (
            pack.question_id
            and result.question_id is not None
            and result.question_id != pack.question_id
        ):
            violations.append(
                ResultViolation(
                    code=ResultViolationCode.RESULT_QUESTION_MISMATCH,
                    message="result question identity does not match the "
                    "delegation's bound question",
                    location="question_id",
                )
            )

        # Evidence visibility
        allowed = reconstruct_allowed_evidence_ids(
            (item.evidence_key for item in pack.evidence_digests),
            observations,
            delegation_id=pack.delegation_id,
            run_id=pack.run_id,
        )
        seen_refs: set[str] = set()
        for ref in result.iter_evidence_refs():
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            violation = self._check_evidence_ref(ref, pack.task_id, allowed)
            if violation is not None:
                violations.append(violation)

        # candidate hygiene
        violations.extend(self._check_candidates(pack, result))

        # follow-up scope expansion proposals
        granted_scopes = {
            pack.source_scope_id,
            *pack.source_scope_ids,
        }
        for question in result.follow_up_questions:
            for scope in question.suggested_source_scope_ids:
                if scope not in granted_scopes:
                    violations.append(
                        ResultViolation(
                            code=ResultViolationCode.RESULT_SCOPE_EXPANSION_NOT_ALLOWED,
                            message="follow-up proposes a source scope outside "
                            "the delegation's grant",
                            location=f"follow_up_questions[{question.follow_up_id}]",
                        )
                    )

        return SpecialistResultValidation(
            valid=not violations, violations=tuple(violations)
        )

    def _check_evidence_ref(self, ref, task_id, allowed):
        from ..evidence.exceptions import InvalidEvidenceKeyError
        from ..evidence.keys import parse_evidence_key

        if not isinstance(ref, str) or not ref.strip():
            return ResultViolation(
                code=ResultViolationCode.RESULT_EVIDENCE_REF_INVALID,
                message="result carries an empty evidence reference",
            )
        try:
            parse_evidence_key(ref)
        except InvalidEvidenceKeyError:
            return ResultViolation(
                code=ResultViolationCode.RESULT_EVIDENCE_REF_INVALID,
                message="result carries a malformed evidence reference",
            )
        if self._cross_task_ref_validator is not None:
            try:
                self._cross_task_ref_validator(ref, task_id)
            except Exception:
                return ResultViolation(
                    code=ResultViolationCode.RESULT_EVIDENCE_CROSS_TASK,
                    message="result references evidence outside this task",
                )
        if ref not in allowed:
            return ResultViolation(
                code=ResultViolationCode.RESULT_EVIDENCE_NOT_VISIBLE,
                message="result cites evidence never exposed to this delegation",
            )
        return None

    def _check_candidates(
        self, pack: SpecialistContextPack, result: SpecialistResultV1
    ) -> list[ResultViolation]:
        violations: list[ResultViolation] = []
        seen_ids: set[str] = set()

        collections = (
            ("claim_candidates", result.claim_candidates),
            ("entity_candidates", result.entity_candidates),
            ("correlation_candidates", result.correlation_candidates),
            ("follow_up_questions", result.follow_up_questions),
            ("coverage_observations", result.coverage_observations),
        )
        for collection_name, candidates in collections:
            for candidate in candidates:
                candidate_id = getattr(candidate, "candidate_id", None) or getattr(
                    candidate, "follow_up_id", None
                ) or getattr(candidate, "observation_id", None)
                if candidate_id:
                    if candidate_id in seen_ids:
                        violations.append(
                            ResultViolation(
                                code=ResultViolationCode.RESULT_DUPLICATE_CANDIDATE_ID,
                                message="duplicate candidate identifier",
                                location=f"{collection_name}[{candidate_id}]",
                            )
                        )
                    seen_ids.add(candidate_id)
                text = getattr(candidate, "text", None) or getattr(
                    candidate, "note", None
                )
                if text is not None and not str(text).strip():
                    violations.append(
                        ResultViolation(
                            code=ResultViolationCode.RESULT_CANDIDATE_TEXT_INVALID,
                            message="candidate text is empty",
                            location=f"{collection_name}[{candidate_id}]",
                        )
                    )
                violations.extend(
                    self._check_forbidden_payload(
                        collection_name, candidate_id, candidate
                    )
                )
        return violations

    def _check_forbidden_payload(
        self, collection_name, candidate_id, candidate
    ) -> list[ResultViolation]:
        """Scan the candidate payload for canonical/review/graph/report
        semantics the output contract must never carry."""
        violations: list[ResultViolation] = []
        location = f"{collection_name}[{candidate_id}]"
        payload = _flattened_keys(candidate.model_dump())
        for key in payload:
            if key in _FORBIDDEN_PAYLOAD_KEYS:
                code = ResultViolationCode.RESULT_REVIEW_STATE_FORBIDDEN
                if "graph" in key:
                    code = ResultViolationCode.RESULT_GRAPH_STATE_FORBIDDEN
                elif "report" in key or "finding" in key:
                    code = ResultViolationCode.RESULT_REPORT_STATE_FORBIDDEN
                violations.append(
                    ResultViolation(
                        code=code,
                        message="candidate carries forbidden canonical state",
                        location=location,
                    )
                )
        serialized = canonical_state_json(candidate.model_dump()).casefold()
        if any(prefix in serialized for prefix in _GRAPH_REF_PREFIXES):
            violations.append(
                ResultViolation(
                    code=ResultViolationCode.RESULT_GRAPH_STATE_FORBIDDEN,
                    message="candidate references graph state",
                    location=location,
                )
            )
        if any(prefix in serialized for prefix in _REPORT_REF_PREFIXES):
            violations.append(
                ResultViolation(
                    code=ResultViolationCode.RESULT_REPORT_STATE_FORBIDDEN,
                    message="candidate references report state",
                    location=location,
                )
            )
        return violations


def _flattened_keys(payload: Mapping[str, Any]) -> Iterable[str]:
    """Yield every mapping key at any depth of the payload."""
    stack = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, value in current.items():
                yield key
                stack.append(value)
        elif isinstance(current, (list, tuple)):
            stack.extend(current)


__all__ = [
    "AssertionClass",
    "ExecutionDigest",
    "ResultViolation",
    "ResultViolationCode",
    "SPECIALIST_RESULT_VERSION",
    "SpecialistClaimCandidate",
    "SpecialistContextPack",
    "SpecialistCorrelationCandidate",
    "SpecialistCoverageObservation",
    "SpecialistEntityCandidate",
    "SpecialistFollowUpQuestion",
    "SpecialistResultV1",
    "SpecialistResultValidation",
    "SpecialistResultValidator",
]
