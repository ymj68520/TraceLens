"""P5A §55 ProposedClaim / ProposalNormalizer tests plus the §45
AddPendingProposalReference resolver seam."""

import pytest

from httpserver.services.investigation.agent_claims import (
    ProposedClaimV1,
    ProposalNormalizer,
    build_proposals_from_specialist_result,
    claim_from_correlation_candidate,
)
from httpserver.services.investigation.agent_correlation import (
    CorrelationAssertionHint,
    CorrelationCandidateV1,
    CorrelationDerivation,
    CausalStatus,
)
from httpserver.services.investigation.agent_entities import (
    EntityOccurrenceV1,
)
from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
    SpecialistClaimCandidate,
    SpecialistResultV1,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "e" * 8

_NORMALIZER = ProposalNormalizer()


def _candidate(
    text="observed logon",
    assertion=AssertionClass.INFERENCE,
    refs=("file:C/a.doc",),
    candidate_id="c-1",
) -> SpecialistClaimCandidate:
    return SpecialistClaimCandidate(
        candidate_id=candidate_id,
        text=text,
        assertion_class=assertion,
        evidence_refs=refs,
    )


def _result(*candidates) -> SpecialistResultV1:
    return SpecialistResultV1(
        delegation_id="deleg-1",
        summary="s",
        claim_candidates=candidates,
    )


def _normalize(candidate):
    return _NORMALIZER.normalize_claim_candidate(
        candidate,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        delegation_id="deleg-1",
        result_hash="hash-1",
    )


def test_specialist_claim_candidate_becomes_proposed_claim():
    report = build_proposals_from_specialist_result(
        _result(_candidate()), task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
    )
    assert len(report.proposals) == 1
    proposal = report.proposals[0]
    assert proposal.proposal_id.startswith("prop:")
    assert proposal.text == "observed logon"
    assert proposal.assertion_class is AssertionClass.INFERENCE
    assert proposal.source_delegation_id == "deleg-1"
    assert proposal.source_candidate_id == "c-1"
    assert proposal.evidence_refs == ("file:C/a.doc",)


def test_proposal_id_is_stable_and_content_bound():
    _first, _ = _normalize(_candidate())
    _second, _ = _normalize(_candidate())
    other_text, _ = _normalize(_candidate(text="different finding"))
    assert _first[0].proposal_id == _second[0].proposal_id
    assert _first[0].proposal_id != other_text[0].proposal_id


def test_evidence_ref_order_does_not_change_id():
    _a, _ = _normalize(_candidate(refs=("file:C/a.doc", "file:C/b.doc")))
    _b, _ = _normalize(_candidate(refs=("file:C/b.doc", "file:C/a.doc")))
    assert _a[0].proposal_id == _b[0].proposal_id
    assert _a[0].evidence_refs == ("file:C/a.doc", "file:C/b.doc")


def test_assertion_classes_are_preserved():
    for assertion in (
        AssertionClass.FACT,
        AssertionClass.INFERENCE,
        AssertionClass.HYPOTHESIS,
    ):
        proposals, warnings = _normalize(
            _candidate(assertion=assertion, refs=("file:C/a.doc",))
        )
        assert proposals[0].assertion_class is assertion
        assert "FACT_DOWNGRADED_NO_EVIDENCE" not in warnings


def test_fact_without_evidence_downgrades_to_hypothesis():
    proposals, warnings = _normalize(
        _candidate(assertion=AssertionClass.FACT, refs=())
    )
    assert proposals[0].assertion_class is AssertionClass.HYPOTHESIS
    assert warnings == ("FACT_DOWNGRADED_NO_EVIDENCE",)
    assert proposals[0].normalization_warnings == (
        "FACT_DOWNGRADED_NO_EVIDENCE",
    )


def test_compound_safe_split_on_independent_statements():
    proposals, warnings = _normalize(
        _candidate(text="A logged in at 09:00; file X was transferred at "
                        "09:05")
    )
    assert len(proposals) == 2
    assert warnings == ("COMPOUND_SPLIT_EVIDENCE_NOT_REATTRIBUTED",)
    for proposal in proposals:
        assert "compound split" in " ".join(proposal.limitations)
        # evidence is inherited in full, never re-attributed or invented
        assert proposal.evidence_refs == ("file:C/a.doc",)


def test_unsafe_compound_claim_retained_with_warning():
    text = "User A logged in and exfiltrated file X"
    proposals, warnings = _normalize(_candidate(text=text))
    assert len(proposals) == 1
    assert proposals[0].text == text  # never rewritten
    assert warnings == ("COMPOUND_CLAIM_RETAINED_UNSAFE_SPLIT",)
    assert proposals[0].assertion_class is AssertionClass.INFERENCE


def test_normalizer_never_invents_evidence():
    proposals, _ = _normalize(_candidate(text="one finding; another finding"))
    assert len(proposals) == 2
    assert all(p.evidence_refs == ("file:C/a.doc",) for p in proposals)


def _correlation_candidate(family, subject, object_, refs, *,
                           temporal=None):
    return CorrelationCandidateV1(
        correlation_id=f"corr-{family}",
        relation_family=family,
        subject_ref=subject.occurrence_id,
        object_ref=object_.occurrence_id,
        derivation=CorrelationDerivation.DETERMINISTIC_MATCH,
        assertion_hint=CorrelationAssertionHint.INFERENCE,
        evidence_refs=refs,
        support_types=("exact_hash",),
        temporal_relation=temporal,
        limitations=(),
        causal_status=CausalStatus.NOT_ASSESSED,
        input_hash="h",
    )


def _occ(oid, entity_type, value, ref):
    return EntityOccurrenceV1(
        occurrence_id=oid,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        source_scope_id="s",
        evidence_ref=ref,
        entity_type=entity_type,
        raw_value=value,
        normalized_value=value,
        match_key=f"k|{value}",
        namespace="hash:sha256",
        role="mention",
        source_field="t",
    )


def test_correlation_hash_match_maps_to_inference_claim():
    subject = _occ("o-1", "file_hash", "ab" * 32, "file:C/1.iso")
    object_ = _occ("o-2", "file_hash", "ab" * 32, "file:D/2.iso")
    candidate = _correlation_candidate(
        "same_content_hash", subject, object_,
        ("file:C/1.iso", "file:D/2.iso"),
    )
    proposal = claim_from_correlation_candidate(
        candidate, task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
        occurrences={"o-1": subject, "o-2": object_},
    )
    assert proposal is not None
    assert proposal.assertion_class is AssertionClass.INFERENCE
    assert "same sha256 digest" in proposal.text
    assert "copied" not in proposal.text and "transferred" not in proposal.text
    assert proposal.relationship_refs == ("corr-same_content_hash",)


def test_correlation_co_occurrence_maps_to_fact_and_temporal_to_hypothesis():
    from httpserver.services.investigation.agent_correlation import (
        TemporalRelation,
    )

    email = _occ("o-3", "email", "a@x.com", "file:C/doc.txt")
    phone = _occ("o-4", "phone", "1555010", "file:C/doc.txt")
    co = _correlation_candidate(
        "structured_co_occurrence", email, phone, ("file:C/doc.txt",),
    )
    co_proposal = claim_from_correlation_candidate(
        co, task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
        occurrences={"o-3": email, "o-4": phone},
    )
    assert co_proposal.assertion_class is AssertionClass.FACT

    temporal = _correlation_candidate(
        "temporal_overlap", email, phone,
        ("file:C/doc.txt",),
        temporal=TemporalRelation(
            kind="overlap", gap_seconds=0, window_seconds=3600
        ),
    )
    temporal_proposal = claim_from_correlation_candidate(
        temporal, task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
        occurrences={"o-3": email, "o-4": phone},
    )
    assert temporal_proposal.assertion_class is AssertionClass.HYPOTHESIS


def test_correlation_mapping_fails_closed_without_occurrences():
    subject = _occ("o-1", "file_hash", "ab" * 32, "file:C/1.iso")
    object_ = _occ("o-2", "file_hash", "ab" * 32, "file:D/2.iso")
    candidate = _correlation_candidate(
        "same_content_hash", subject, object_, ("file:C/1.iso",),
    )
    assert claim_from_correlation_candidate(
        candidate, task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
        occurrences={},
    ) is None


def test_proposal_persistence_idempotent_with_roundtrip(tmp_path):
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        working_state_to_json,
    )
    from httpserver.services.investigation.repository import (
        InvestigationRepository,
    )

    db = tmp_path / "investigation.db"
    repo = AgentRuntimeRepository(InvestigationRepository(db, TASK_ID))
    repo.create_investigation(
        working_state_to_json(
            AgentWorkingStateV1(
                task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
                objective="claims",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )

    report = build_proposals_from_specialist_result(
        _result(_candidate()), task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
    )
    rows = [proposal.to_row() for proposal in report.proposals]
    first = repo.record_claim_proposals(INVESTIGATION_ID, rows)
    assert first["inserted_count"] == 1
    second = repo.record_claim_proposals(INVESTIGATION_ID, rows)
    assert second["inserted_count"] == 0

    stored = repo.get_claim_proposal(
        INVESTIGATION_ID, report.proposals[0].proposal_id
    )
    assert stored is not None
    restored = ProposedClaimV1.from_row({**stored, **{
        "task_id": TASK_ID, "investigation_id": INVESTIGATION_ID,
    }})
    assert restored == report.proposals[0]

    events = repo.list_trajectory(INVESTIGATION_ID)
    recorded = [
        event for event in events
        if event.event_type.value == "claim_proposals_recorded"
    ]
    assert len(recorded) == 2
    assert "text" not in recorded[0].payload


# ---------------------------------------------------------------------------
# §45 resolver seam
# ---------------------------------------------------------------------------


def test_integration_validator_resolves_proposal_refs(tmp_path):
    """With a resolver wired (production path), a proposal_ref that has no
    durable row fails closed; a persisted proposal passes."""
    from httpserver.services.investigation.agent_integration import (
        FreshResultEnvelope,
        IntegrationDecisionValidator,
        SupervisorIntegrationDecisionV1,
        build_integration_context,
    )
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )
    from httpserver.services.investigation.agent_transitions import (
        AddPendingProposalReference,
    )
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        QuestionPriority,
        QuestionSource,
        WorkingQuestion,
        working_state_to_json,
    )
    from httpserver.services.investigation.repository import (
        InvestigationRepository,
    )
    from httpserver.services.investigation.agent_specialist_result import (
        SpecialistResultV1,
    )

    db = tmp_path / "investigation.db"
    repo = AgentRuntimeRepository(InvestigationRepository(db, "task-A"))
    state = AgentWorkingStateV1(
        task_id="task-A",
        investigation_id="inv-A",
        objective="seam",
        questions=(
            WorkingQuestion(
                question_id="q-1",
                text="q",
                source=QuestionSource.charter,
                priority=QuestionPriority.required,
            ),
        ),
    )
    repo.create_investigation(
        working_state_to_json(state), investigation_id="inv-A"
    )
    persisted_revision = repo.get_working_state_revision("inv-A", 1)

    context = build_integration_context(
        task_id="task-A",
        investigation_id="inv-A",
        run_id="run-A",
        state=state,
        state_revision=1,
        state_hash=persisted_revision.state_hash,
        fresh_results=[
            FreshResultEnvelope(
                delegation_id="deleg-A",
                question_id="q-1",
                source_scope_id="windows",
                result=SpecialistResultV1(
                    delegation_id="deleg-A", summary="s"
                ),
                result_hash="hash-a",
            ),
        ],
    )
    decision = SupervisorIntegrationDecisionV1(
        task_id="task-A",
        investigation_id="inv-A",
        run_id="run-A",
        based_on_state_revision=1,
        based_on_state_hash=persisted_revision.state_hash,
        source_result_ids=("deleg-A",),
        source_result_hashes=("hash-a",),
        transition_proposals=(
            AddPendingProposalReference(proposal_ref="prop-unknown"),
        ),
    )

    def resolver(ref: str) -> bool:
        return repo.get_claim_proposal("inv-A", ref) is not None

    strict = IntegrationDecisionValidator(
        proposal_ref_resolver=resolver
    ).validate(context, decision)
    assert not strict.valid
    assert "INTEGRATION_PROPOSAL_REF_UNRESOLVED" in strict.codes

    # persist the proposal -> a decision referencing its real id resolves
    proposal = ProposedClaimV1(
        task_id="task-A",
        investigation_id="inv-A",
        proposal_id="",
        text="persisted finding",
        assertion_class=AssertionClass.HYPOTHESIS,
        evidence_refs=("file:C/a.doc",),
        input_hash="",
    )
    repo.record_claim_proposals("inv-A", [proposal.to_row()])
    resolved_decision = decision.model_copy(
        update={"transition_proposals": (
            AddPendingProposalReference(proposal_ref=proposal.proposal_id),
        )}
    )
    ok = IntegrationDecisionValidator(
        proposal_ref_resolver=resolver
    ).validate(context, resolved_decision)
    assert ok.valid, ok.codes

    # no resolver wired (direct P2/P4B module use) keeps P4B behaviour
    legacy = IntegrationDecisionValidator().validate(context, decision)
    assert legacy.valid


def test_orchestrator_resolver_closure_is_strict(tmp_path):
    """The exact closure the orchestrator wires: persisted proposal -> True,
    unknown ref -> False."""
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        working_state_to_json,
    )
    from httpserver.services.investigation.repository import (
        InvestigationRepository,
    )

    db = tmp_path / "investigation.db"
    repo = AgentRuntimeRepository(InvestigationRepository(db, "task-A"))
    repo.create_investigation(
        working_state_to_json(
            AgentWorkingStateV1(
                task_id="task-A", investigation_id="inv-A", objective="x"
            )
        ),
        investigation_id="inv-A",
    )
    proposal = ProposedClaimV1(
        task_id="task-A",
        investigation_id="inv-A",
        proposal_id="",
        text="finding",
        assertion_class=AssertionClass.HYPOTHESIS,
        evidence_refs=("file:C/a.doc",),
        input_hash="",
    )
    repo.record_claim_proposals("inv-A", [proposal.to_row()])

    def orchestrator_resolver(ref, _rid="inv-A", _runtime=repo):
        return _runtime.get_claim_proposal(_rid, ref) is not None

    assert orchestrator_resolver(proposal.proposal_id) is True
    assert orchestrator_resolver("prop-does-not-exist") is False
