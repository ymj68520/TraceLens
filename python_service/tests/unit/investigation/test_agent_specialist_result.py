"""P4A-1 tests: SpecialistResultV1 contract + deterministic validator.

Covers the §50 matrix: visible refs pass; real-but-invisible, cross-task,
malformed refs fail; question/delegation mismatch, duplicate ids, forbidden
review/graph/report state and scope expansion all fail closed.
"""

import pytest

from httpserver.services.investigation.agent_capabilities import (
    ArtifactFamilyRegistry,
    build_source_capability_manifest,
)
from httpserver.services.investigation.agent_context import (
    EvidenceDigestItem,
    ProfileDigest,
    SpecialistContextPack,
)
from httpserver.services.investigation.agent_runtime import ToolObservation
from httpserver.services.investigation.agent_skill_resolver import SkillResolution
from httpserver.services.investigation.agent_specialist_result import (
    SPECIALIST_RESULT_VERSION,
    AssertionClass,
    ExecutionDigest,
    ResultViolationCode,
    SpecialistClaimCandidate,
    SpecialistCorrelationCandidate,
    SpecialistCoverageObservation,
    SpecialistEntityCandidate,
    SpecialistFollowUpQuestion,
    SpecialistResultV1,
    SpecialistResultValidator,
)

pytestmark = pytest.mark.migration_matrix

TASK = {
    "id": "task-A",
    "scenarios": ["windows"],
    "scenario_databases": {"windows": "/fake/windows.db"},
}


def _manifest():
    return build_source_capability_manifest(
        TASK,
        "windows",
        ArtifactFamilyRegistry.with_defaults(),
        table_lister=lambda _p: frozenset(),
    )


def make_pack(**overrides) -> SpecialistContextPack:
    fields = dict(
        task_id="task-A",
        investigation_id="inv-A",
        run_id="run-A",
        delegation_id="deleg-A",
        question_id="q-1",
        question="unusual logons?",
        source_scope_id="windows",
        profile=ProfileDigest(
            profile_id="windows.specialist",
            version="1",
            platform="windows",
            mission="m",
        ),
        resolved_skills=SkillResolution(profile_id="windows.specialist"),
        capability_manifest=_manifest(),
        evidence_digests=(
            EvidenceDigestItem(evidence_key="file:C/initial.doc", kind="file"),
        ),
        allowed_tool_ids=("search_evidence",),
        working_state_revision=2,
        working_state_hash="abc",
        tool_schema_hash="hash",
    )
    fields.update(overrides)
    return SpecialistContextPack(**fields)


def make_result(**overrides) -> SpecialistResultV1:
    fields = dict(
        delegation_id="deleg-A",
        question_id="q-1",
        summary="specialist findings",
        evidence_refs=("file:C/observed.doc",),
        execution_digest=ExecutionDigest(
            model_name="deepseek-flash",
            request_count=2,
            input_tokens=100,
            output_tokens=50,
            tool_call_count=1,
            observation_count=1,
        ),
    )
    fields.update(overrides)
    return SpecialistResultV1(**fields)


def make_observation(refs=("file:C/observed.doc",)) -> ToolObservation:
    return ToolObservation(
        observation_id="obs-1",
        task_id="task-A",
        investigation_id="inv-A",
        run_id="run-A",
        delegation_id="deleg-A",
        tool_id="search_evidence",
        summary="s",
        result={},
        evidence_refs=tuple(refs),
        result_count=len(refs),
        truncated=False,
        created_at="2026-09-23T00:00:00",
    )


class _PayloadHolder:
    """Stands in for a candidate whose payload smuggled extra keys."""

    def __init__(self, dump):
        self._dump = dump

    def model_dump(self):
        return self._dump


def validate(result, *, pack=None, observations=None, cross_task=None):
    validator = SpecialistResultValidator(cross_task_ref_validator=cross_task)
    return validator.validate(
        pack or make_pack(),
        result,
        observations if observations is not None else [make_observation()],
    )


# ---------------------------------------------------------------------------
# contract basics (P4A-E2, E3)
# ---------------------------------------------------------------------------


def test_result_version_frozen_and_hash_deterministic():
    result = make_result()
    assert result.result_version == SPECIALIST_RESULT_VERSION == "specialist-result:v1"
    assert result.result_hash() == make_result().result_hash()
    changed = make_result(summary="different")
    assert changed.result_hash() != result.result_hash()
    with pytest.raises(ValueError):
        make_result(result_version="specialist-result:v0")


def test_candidates_are_proposals_only():
    claim = make_result(
        claim_candidates=(
            SpecialistClaimCandidate(
                candidate_id="c-1",
                text="actor logged in",
                assertion_class=AssertionClass.INFERENCE,
                evidence_refs=("file:C/observed.doc",),
            ),
        ),
    )
    validation = validate(claim)
    assert validation.valid
    # structural: a validated result is still only a proposal — the contract
    # carries no review/decision fields at all
    assert "review_status" not in claim.model_dump()
    assert claim.claim_candidates[0].assertion_class == AssertionClass.INFERENCE


# ---------------------------------------------------------------------------
# §50 matrix
# ---------------------------------------------------------------------------


def test_valid_visible_evidence_ref_passes():
    assert validate(make_result()).valid


def test_real_but_invisible_ref_is_invalid():
    result = make_result(evidence_refs=("file:C/never_exposed.doc",))
    validation = validate(result)
    assert not validation.valid
    assert ResultViolationCode.RESULT_EVIDENCE_NOT_VISIBLE in validation.codes


def test_cross_task_ref_is_invalid():
    def cross_task(ref, task_id):
        known = {"file:C/observed.doc", "file:C/initial.doc"}
        if ref not in known:
            raise ValueError("outside task")

    result = make_result(evidence_refs=("file:C/other_task.doc",))
    validation = validate(result, cross_task=cross_task)
    assert not validation.valid
    assert ResultViolationCode.RESULT_EVIDENCE_CROSS_TASK in validation.codes


def test_malformed_ref_is_invalid():
    result = make_result(evidence_refs=("garbage-ref",))
    validation = validate(result)
    assert not validation.valid
    assert ResultViolationCode.RESULT_EVIDENCE_REF_INVALID in validation.codes


def test_question_mismatch_is_invalid():
    validation = validate(make_result(question_id="q-other"))
    assert not validation.valid
    assert ResultViolationCode.RESULT_QUESTION_MISMATCH in validation.codes


def test_delegation_mismatch_is_invalid():
    validation = validate(make_result(delegation_id="deleg-other"))
    assert not validation.valid
    assert ResultViolationCode.RESULT_DELEGATION_MISMATCH in validation.codes


def test_duplicate_candidate_id_is_invalid():
    result = make_result(
        claim_candidates=(
            SpecialistClaimCandidate(
                candidate_id="c-1", text="a",
                assertion_class=AssertionClass.FACT,
            ),
            SpecialistClaimCandidate(
                candidate_id="c-1", text="b",
                assertion_class=AssertionClass.FACT,
            ),
        ),
    )
    validation = validate(result)
    assert not validation.valid
    assert ResultViolationCode.RESULT_DUPLICATE_CANDIDATE_ID in validation.codes


def test_blank_candidate_text_is_invalid():
    result = make_result(
        claim_candidates=(
            SpecialistClaimCandidate(
                candidate_id="c-blank", text="   ",
                assertion_class=AssertionClass.FACT,
            ),
        ),
    )
    validation = validate(result)
    assert not validation.valid
    assert ResultViolationCode.RESULT_CANDIDATE_TEXT_INVALID in validation.codes


def test_forbidden_review_state_smuggling_is_invalid():
    validator = SpecialistResultValidator()
    payload = {
        "candidate_id": "c-1",
        "text": "a",
        "assertion_class": "FACT",
        "evidence_refs": [],
        "limitations": [],
        "review_status": "accepted",
    }
    violations = validator._check_forbidden_payload(
        "claim_candidates", "c-1", _PayloadHolder(payload)
    )
    assert ResultViolationCode.RESULT_REVIEW_STATE_FORBIDDEN in [
        v.code for v in violations
    ]


def test_graph_and_report_refs_forbidden():
    validator = SpecialistResultValidator()
    violations = validator._check_forbidden_payload(
        "correlation_candidates",
        "c-1",
        _PayloadHolder({"node_ref": "graph:node/1"}),
    )
    assert ResultViolationCode.RESULT_GRAPH_STATE_FORBIDDEN in [
        v.code for v in violations
    ]
    violations2 = validator._check_forbidden_payload(
        "correlation_candidates",
        "c-2",
        _PayloadHolder({"ref": "report-version:9"}),
    )
    assert ResultViolationCode.RESULT_REPORT_STATE_FORBIDDEN in [
        v.code for v in violations2
    ]


def test_scope_expansion_proposal_is_invalid():
    result = make_result(
        follow_up_questions=(
            SpecialistFollowUpQuestion(
                follow_up_id="f-1",
                text="check android too",
                suggested_source_scope_ids=("android",),
            ),
        ),
    )
    validation = validate(result)
    assert not validation.valid
    assert ResultViolationCode.RESULT_SCOPE_EXPANSION_NOT_ALLOWED in validation.codes


def test_scope_within_grant_is_allowed():
    result = make_result(
        follow_up_questions=(
            SpecialistFollowUpQuestion(
                follow_up_id="f-1",
                text="check windows services",
                suggested_source_scope_ids=("windows",),
            ),
        ),
    )
    assert validate(result).valid


def test_candidate_refs_must_also_be_visible():
    result = make_result(
        claim_candidates=(
            SpecialistClaimCandidate(
                candidate_id="c-1",
                text="hidden citation",
                assertion_class=AssertionClass.FACT,
                evidence_refs=("file:C/hidden.doc",),
            ),
        ),
    )
    validation = validate(result)
    assert not validation.valid
    assert ResultViolationCode.RESULT_EVIDENCE_NOT_VISIBLE in validation.codes


def test_validator_error_messages_carry_no_internals():
    validation = validate(make_result(evidence_refs=("garbage",)))
    text = str(validation.model_dump())
    for forbidden in ("/srv", ".db", "sqlite", "api_key", "Traceback"):
        assert forbidden not in text


def test_coverage_observation_refs_validated():
    result = make_result(
        coverage_observations=(
            SpecialistCoverageObservation(
                observation_id="o-1", note="n", evidence_refs=("file:C/observed.doc",)
            ),
        ),
    )
    assert validate(result).valid
    bad = make_result(
        coverage_observations=(
            SpecialistCoverageObservation(
                observation_id="o-2", note="n", evidence_refs=("file:C/nope.doc",)
            ),
        ),
    )
    validation = validate(bad)
    assert not validation.valid


def test_entity_and_correlation_candidates_accepted_as_proposals():
    result = make_result(
        entity_candidates=(
            SpecialistEntityCandidate(
                candidate_id="e-1",
                raw_value="tea",
                normalized_candidate="tea",
                entity_type_candidate="user",
                evidence_refs=("file:C/observed.doc",),
            ),
        ),
        correlation_candidates=(
            SpecialistCorrelationCandidate(
                candidate_id="x-1",
                subject_ref="e-1",
                object_ref="e-1",
                relation_hint="same_actor",
                evidence_refs=("file:C/observed.doc",),
            ),
        ),
    )
    assert validate(result).valid
