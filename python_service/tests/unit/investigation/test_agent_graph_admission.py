"""P6A §56/§57 GraphCandidate + GraphAdmissionPolicy tests."""

import pytest

from httpserver.services.investigation.agent_graph_admission import (
    GraphAdmissionDecision,
    GraphAdmissionPolicy,
    GraphBudgetState,
    GraphBudgetPolicy,
    GraphProvenanceEnvelope,
    GraphReaderMode,
    ReasonCode,
    retrieval_eligible,
)
from httpserver.services.investigation.agent_graph_candidate import (
    CandidateViolationCode,
    GraphCandidateBuilder,
    GraphCandidateKind,
    GraphCandidateKindRegistry,
    GraphCandidateValidator,
    GraphCandidateV1,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "1" * 8

_BUILDER = GraphCandidateBuilder()
_VALIDATOR = GraphCandidateValidator()


def _finding(status="review_pending", verification_id="sver-1",
             finding_id="finding:abc"):
    return {
        "finding_id": finding_id,
        "status": status,
        "evidence_refs": ("file:C/a.doc",),
        "semantic_verification_id": verification_id,
        "text": "logon cluster indicates shared use",
        "limitations": (),
    }


def _finding_candidate(finding=None):
    return _BUILDER.candidate_from_finding(
        finding or _finding(), task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
    )


def _evidence_candidate():
    return _BUILDER.candidate_from_evidence_context(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        summary="both images carry the identical sha256 payload",
        evidence_refs=("file:C/1.iso", "file:D/2.iso"),
        occurrence_refs=("entocc:abc",),
    )


def test_same_source_yields_same_candidate_id_and_hash():
    first = _finding_candidate()
    second = _finding_candidate()
    assert first.candidate_id == second.candidate_id
    assert first.input_hash == second.input_hash


def test_candidate_is_proposal_never_authority():
    candidate = _finding_candidate()
    # the candidate object carries no admission field at all
    assert not hasattr(candidate, "decision")
    assert not hasattr(candidate, "admitted")


def test_evidence_derived_candidate_structurally_valid():
    candidate = _evidence_candidate()
    assert candidate.candidate_kind == (
        GraphCandidateKind.EVIDENCE_DERIVED_CONTEXT.value
    )
    violations = _VALIDATOR.validate(
        candidate, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    assert violations == ()


def test_review_pending_finding_retains_review_status():
    candidate = _finding_candidate()
    assert candidate.review_status == "review_pending"
    assert candidate.candidate_kind == "verified_finding"


def test_rejected_finding_cannot_even_be_proposed():
    with pytest.raises(ValueError):
        _BUILDER.candidate_from_finding(
            _finding(status="rejected"), task_id=TASK_ID,
            investigation_id=INVESTIGATION_ID,
        )


def test_cross_task_refs_rejected():
    candidate = _finding_candidate()
    violations = _VALIDATOR.validate(
        candidate, task_id="task-OTHER",
        investigation_id=INVESTIGATION_ID,
    )
    assert CandidateViolationCode.CANDIDATE_IDENTITY_MISMATCH in violations


def test_missing_provenance_rejected():
    candidate = GraphCandidateV1(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        candidate_id="",
        candidate_kind="evidence_derived_context",
        semantic_summary="a summary with no provenance",
        review_status="not_applicable",
        input_hash="",
    )
    violations = _VALIDATOR.validate(
        candidate, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    assert CandidateViolationCode.CANDIDATE_PROVENANCE_MISSING in violations


def test_analyst_note_only_candidate_rejected():
    candidate = GraphCandidateV1(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        candidate_id="",
        candidate_kind="evidence_derived_context",
        evidence_refs=("file:C/a.doc",),
        semantic_summary="analyst said so",
        review_status="not_applicable",
        source_component="analyst_note",
        input_hash="",
    )
    violations = _VALIDATOR.validate(
        candidate, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    assert CandidateViolationCode.CANDIDATE_FORBIDDEN_SOURCE in violations


def test_case_context_and_agent_reasoning_sources_rejected():
    for source in ("case_context", "agent_reasoning"):
        candidate = GraphCandidateV1(
            task_id=TASK_ID,
            investigation_id=INVESTIGATION_ID,
            candidate_id="",
            candidate_kind="evidence_derived_context",
            evidence_refs=("file:C/a.doc",),
            semantic_summary="x",
            review_status="not_applicable",
            source_component=source,
            input_hash="",
        )
        violations = _VALIDATOR.validate(
            candidate, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
        )
        assert CandidateViolationCode.CANDIDATE_FORBIDDEN_SOURCE in violations


def test_ungrounded_hypothesis_not_admitted():
    """A candidate whose only backing is an ungrounded hypothesis (no
    finding object, no evidence) fails the policy, not the guess."""
    policy = GraphAdmissionPolicy()
    candidate = GraphCandidateV1(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        candidate_id="",
        candidate_kind="evidence_derived_context",
        entity_occurrence_refs=("entocc:guess",),
        semantic_summary="maybe the attacker returned",
        review_status="not_applicable",
        input_hash="",
    )
    decision = policy.evaluate(candidate)
    assert decision.decision is GraphAdmissionDecision.NOT_ADMITTED
    assert ReasonCode.PROVENANCE_MISSING in decision.reason_codes


def test_malformed_evidence_ref_rejected():
    candidate = _evidence_candidate()
    violations = _VALIDATOR.validate(
        candidate, task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
        evidence_ref_parser=lambda ref: (_ for _ in ()).throw(
            ValueError("bad key")
        ),
    )
    assert CandidateViolationCode.CANDIDATE_EVIDENCE_REF_MALFORMED in violations


# ---------------------------------------------------------------------------
# §57 admission policy
# ---------------------------------------------------------------------------


_POLICY = GraphAdmissionPolicy()


def test_valid_evidence_derived_admitted():
    decision = _POLICY.evaluate(_evidence_candidate())
    assert decision.decision is GraphAdmissionDecision.ADMIT
    assert ReasonCode.ADMITTED in decision.reason_codes


def test_verified_review_pending_finding_admitted_with_unconfirmed():
    findings = {_finding()["finding_id"]: _finding()}
    decision = _POLICY.evaluate(
        _finding_candidate(), finding_resolver=findings.get
    )
    assert decision.decision is GraphAdmissionDecision.ADMIT
    assert (
        decision.resolved_provenance[
            f"finding_status:{_finding()['finding_id']}"
        ]
        == "review_pending"
    )


def test_review_pending_without_verification_defers():
    unverified = _finding(verification_id=None)
    findings = {unverified["finding_id"]: unverified}
    decision = _POLICY.evaluate(
        _finding_candidate(unverified), finding_resolver=findings.get
    )
    assert decision.decision is GraphAdmissionDecision.DEFER
    assert ReasonCode.REVIEW_PENDING_UNVERIFIED in decision.reason_codes


def test_accepted_finding_admitted():
    findings = {_finding()["finding_id"]: _finding(status="accepted")}
    decision = _POLICY.evaluate(
        _finding_candidate(), finding_resolver=findings.get
    )
    assert decision.decision is GraphAdmissionDecision.ADMIT


def test_rejected_finding_not_admitted():
    findings = {_finding()["finding_id"]: _finding(status="rejected")}
    decision = _POLICY.evaluate(
        _finding_candidate(), finding_resolver=findings.get
    )
    assert decision.decision is GraphAdmissionDecision.NOT_ADMITTED
    assert ReasonCode.FINDING_REJECTED in decision.reason_codes


def test_unknown_finding_status_not_admitted():
    decision = _POLICY.evaluate(_finding_candidate())
    assert decision.decision is GraphAdmissionDecision.NOT_ADMITTED
    assert ReasonCode.FINDING_UNKNOWN in decision.reason_codes


def test_budget_exhaustion_defers_never_refuses():
    policy = GraphAdmissionPolicy(
        budget=GraphBudgetPolicy(max_active_materializations=0)
    )
    decision = policy.evaluate(
        _evidence_candidate(),
        budget_state=GraphBudgetState(active_or_queued_materializations=0),
    )
    assert decision.decision is GraphAdmissionDecision.DEFER
    assert ReasonCode.BUDGET_EXHAUSTED in decision.reason_codes


def test_policy_deterministic_and_version_sensitive():
    candidate = _evidence_candidate()
    first = _POLICY.evaluate(candidate)
    second = _POLICY.evaluate(candidate)
    assert first.decision_id == second.decision_id
    assert first.input_hash == second.input_hash

    hardened = GraphAdmissionPolicy(
        budget=GraphBudgetPolicy(max_active_materializations=1)
    )
    assert hardened.policy_hash() != _POLICY.policy_hash()


def test_admission_vocabulary_never_confused_with_review():
    decision = _POLICY.evaluate(_evidence_candidate())
    assert decision.decision.value in ("admit", "defer", "not_admitted")


def test_retrieval_mode_classification_frozen():
    """§51: report mode NEVER sees review_pending; investigation mode
    sees verified review_pending."""
    assert retrieval_eligible("accepted", GraphReaderMode.REPORT) is True
    assert retrieval_eligible("accepted", GraphReaderMode.INVESTIGATION)
    assert retrieval_eligible(
        "review_pending", GraphReaderMode.REPORT
    ) is False
    assert retrieval_eligible(
        "review_pending", GraphReaderMode.INVESTIGATION, verified=True
    ) is True
    assert retrieval_eligible(
        "review_pending", GraphReaderMode.INVESTIGATION, verified=False
    ) is False
    assert retrieval_eligible(
        "rejected", GraphReaderMode.INVESTIGATION
    ) is False


def test_provenance_envelope_required_fields():
    envelope = GraphProvenanceEnvelope(
        materialization_id="gm:1",
        episode_id="episode:1",
        candidate_id="gcand:1",
        admission_decision_id="gadm:1",
        evidence_refs=("file:C/a.doc",),
        finding_refs=("finding:abc",),
        review_status="review_pending",
    )
    assert envelope.evidence_refs == ("file:C/a.doc",)
    # without materialization provenance the envelope cannot even exist
    with pytest.raises(Exception):
        GraphProvenanceEnvelope()


def test_kind_registry_versioned():
    registry = GraphCandidateKindRegistry()
    assert registry.knows("verified_finding")
    assert not registry.knows("real_world_person")
    assert registry.registry_hash() == GraphCandidateKindRegistry().registry_hash()
