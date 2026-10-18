"""P5B §65-§67 Finding / review / AddFindingReference tests, §60
no-auto-review, and §74 atomicity."""

import pytest

from httpserver.services.investigation.agent_assertion_policy import (
    AssertionPolicy,
    AssertionSemanticType,
    VerificationAvailability,
)
from httpserver.services.investigation.agent_claims import ProposedClaimV1
from httpserver.services.investigation.agent_findings import (
    FindingReviewService,
    InvestigationFindingV1,
    finding_from_disposition,
)
from httpserver.services.investigation.agent_grounding import (
    GroundingResultV1,
    GroundingStatus,
)
from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "b" * 8

_REVIEW_SERVICE = FindingReviewService()


def _proposal(assertion=AssertionClass.INFERENCE, text="same sha256 digest"):
    return ProposedClaimV1(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal_id="",
        text=text,
        assertion_class=assertion,
        evidence_refs=("file:C/1.iso", "file:D/2.iso"),
        input_hash="",
    )


def _grounding():
    return GroundingResultV1(
        grounding_id="grnd-1",
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal_id="prop-x",
        input_assertion_class=AssertionClass.INFERENCE,
        effective_assertion_class=AssertionClass.INFERENCE,
        status=GroundingStatus.GROUNDED,
        valid_evidence_refs=("file:C/1.iso", "file:D/2.iso"),
        validator_version="v",
        input_hash="gh",
    )


def _policy_path(assertion=AssertionClass.INFERENCE):
    """Run a deterministic claim through policy with a sufficient verifier
    result, producing an eligible disposition."""
    policy = AssertionPolicy()
    proposal = _proposal(assertion=assertion)
    grounding = _grounding()
    disposition = policy.finalize(
        proposal, grounding,
        semantic_type=AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT,
        verification_availability=VerificationAvailability.UNAVAILABLE,
    )
    return policy, proposal, grounding, disposition


def _repo(tmp_path):
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
                objective="findings",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    # durable proposal + grounding so the atomic commit can revalidate
    proposal = _proposal()
    repo.record_claim_proposals(
        INVESTIGATION_ID, [proposal.to_row()]
    )
    repo.record_grounding_results(
        INVESTIGATION_ID, [{
            "grounding_id": "grnd-1",
            "proposal_id": proposal.proposal_id,
            "grounding_policy_version": 1,
            "input_assertion_class": "INFERENCE",
            "effective_assertion_class": "INFERENCE",
            "status": "grounded",
            "valid_evidence_refs": ("file:C/1.iso", "file:D/2.iso"),
            "invalid_evidence_refs": (),
            "invisible_evidence_refs": (),
            "disallowed_ref_types": (),
            "warnings": (),
            "limitations": (),
            "validator_version": "v",
            "input_hash": "gh",
        }]
    )
    return repo, proposal


def test_eligible_disposition_creates_one_review_pending_finding(tmp_path):
    repo, proposal = _repo(tmp_path)
    policy, proposal, grounding, disposition = _policy_path()
    finding = finding_from_disposition(
        disposition, proposal=proposal, grounding_id=grounding.grounding_id,
        semantic_verification_id=None,
        effective_assertion_class=disposition.effective_assertion_class,
    )
    outcome = repo.commit_claim_disposition(
        INVESTIGATION_ID,
        disposition_row=disposition.to_row(),
        finding_row=finding.to_row(),
    )
    assert outcome["disposition_inserted"] is True
    assert outcome["finding_inserted"] is True

    findings = repo.list_investigation_findings(INVESTIGATION_ID)
    assert len(findings) == 1
    assert findings[0]["status"] == "review_pending"
    # full provenance retained (§65)
    assert findings[0]["proposal_id"] == proposal.proposal_id
    assert findings[0]["disposition_id"] == disposition.disposition_id
    assert findings[0]["grounding_id"] == grounding.grounding_id
    assert findings[0]["evidence_refs"] == ("file:C/1.iso", "file:D/2.iso")


def test_retry_creates_no_duplicate_finding(tmp_path):
    repo, proposal = _repo(tmp_path)
    policy, proposal, grounding, disposition = _policy_path()
    finding = finding_from_disposition(
        disposition, proposal=proposal, grounding_id=grounding.grounding_id,
        semantic_verification_id=None,
        effective_assertion_class=disposition.effective_assertion_class,
    )
    first = repo.commit_claim_disposition(
        INVESTIGATION_ID,
        disposition_row=disposition.to_row(),
        finding_row=finding.to_row(),
    )
    second = repo.commit_claim_disposition(
        INVESTIGATION_ID,
        disposition_row=disposition.to_row(),
        finding_row=finding.to_row(),
    )
    assert first["finding_inserted"] is True
    assert second["finding_inserted"] is False
    assert len(repo.list_investigation_findings(INVESTIGATION_ID)) == 1


def test_finding_creation_consumes_zero_working_state_revision(tmp_path):
    repo, _proposal_row = _repo(tmp_path)
    policy, proposal, grounding, disposition = _policy_path()
    finding = finding_from_disposition(
        disposition, proposal=proposal, grounding_id=grounding.grounding_id,
        semantic_verification_id=None,
        effective_assertion_class=disposition.effective_assertion_class,
    )
    repo.commit_claim_disposition(
        INVESTIGATION_ID,
        disposition_row=disposition.to_row(),
        finding_row=finding.to_row(),
    )
    assert repo.get_working_state_revision(INVESTIGATION_ID, 1) is not None
    assert repo.get_working_state_revision(INVESTIGATION_ID, 2) is None


def test_agent_pipeline_cannot_write_accepted_or_rejected(tmp_path):
    """§60: the Finding model hard-refuses any status other than
    review_pending, and the review service is the only writer."""
    fields = dict(
        task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
        proposal_id="p", disposition_id="d", text="t",
        assertion_class=AssertionClass.INFERENCE, grounding_id="g",
    )
    with pytest.raises(ValueError):
        InvestigationFindingV1(**fields, status="accepted")
    with pytest.raises(ValueError):
        InvestigationFindingV1(**fields, status="rejected")


def test_analyst_review_handoff_and_history(tmp_path):
    repo, _ = _repo(tmp_path)
    policy, proposal, grounding, disposition = _policy_path()
    finding = finding_from_disposition(
        disposition, proposal=proposal, grounding_id=grounding.grounding_id,
        semantic_verification_id=None,
        effective_assertion_class=disposition.effective_assertion_class,
    )
    repo.commit_claim_disposition(
        INVESTIGATION_ID,
        disposition_row=disposition.to_row(),
        finding_row=finding.to_row(),
    )

    outcome = _REVIEW_SERVICE.review_finding(
        repo, investigation_id=INVESTIGATION_ID,
        finding_id=finding.finding_id, decision="accepted",
        reviewer="analyst-7", note="confirmed by log times",
    )
    stored = repo.get_investigation_finding(
        INVESTIGATION_ID, finding.finding_id
    )
    assert stored["status"] == "accepted"
    assert stored["reviewer"] == "analyst-7"
    assert stored["review_id"] == outcome["review_id"]

    # terminal: no second review
    with pytest.raises(ValueError):
        _REVIEW_SERVICE.review_finding(
            repo, investigation_id=INVESTIGATION_ID,
            finding_id=finding.finding_id, decision="rejected",
            reviewer="analyst-8",
        )


def test_rejected_finding_is_not_referenceable_but_not_deleted(tmp_path):
    repo, _ = _repo(tmp_path)
    policy, proposal, grounding, disposition = _policy_path()
    finding = finding_from_disposition(
        disposition, proposal=proposal, grounding_id=grounding.grounding_id,
        semantic_verification_id=None,
        effective_assertion_class=disposition.effective_assertion_class,
    )
    repo.commit_claim_disposition(
        INVESTIGATION_ID,
        disposition_row=disposition.to_row(),
        finding_row=finding.to_row(),
    )
    _REVIEW_SERVICE.review_finding(
        repo, investigation_id=INVESTIGATION_ID,
        finding_id=finding.finding_id, decision="rejected",
        reviewer="analyst-7",
    )
    # the row stays (audit), but no longer resolves as referenceable
    stored = repo.get_investigation_finding(
        INVESTIGATION_ID, finding.finding_id
    )
    assert stored is not None and stored["status"] == "rejected"

    from httpserver.services.investigation.agent_orchestrator import (
        AgentOrchestrator,
    )

    validate = AgentOrchestrator._finding_ref_validator(
        repo, INVESTIGATION_ID
    )
    check = validate(finding.finding_id)
    assert check.found is False
    assert check.kind == "finding"


def test_cross_task_and_unknown_finding_reviews_rejected(tmp_path):
    repo, _ = _repo(tmp_path)
    with pytest.raises(ValueError):
        _REVIEW_SERVICE.review_finding(
            repo, investigation_id=INVESTIGATION_ID,
            finding_id="finding:does-not-exist", decision="accepted",
            reviewer="analyst-1",
        )


def test_no_auto_review_import_path_exists():
    """§60: no production agent component imports the review authority."""
    import inspect

    import httpserver.services.investigation.agent_verification as ver
    import httpserver.services.investigation.agent_assertion_policy as pol
    import httpserver.services.investigation.agent_supervisor as sup
    import httpserver.services.investigation.agent_specialist_executor as exe
    import httpserver.services.investigation.agent_correlation_agent as corr
    import httpserver.services.investigation.agent_orchestrator as orch

    for module in (ver, pol, sup, exe, corr, orch):
        source = inspect.getsource(module)
        assert "FindingReviewService" not in source, module.__name__
        assert "review_finding" not in source, module.__name__
        assert "commit_finding_review" not in source, module.__name__


def test_add_finding_reference_resolves_through_orchestrator_seam(tmp_path):
    """§67: the production seam resolves persisted reviewable findings
    only; the StateTransitionPolicy validator stays the final authority
    (P2 review-record refusals untouched)."""
    from httpserver.services.investigation.agent_orchestrator import (
        AgentOrchestrator,
    )

    repo, _ = _repo(tmp_path)
    policy, proposal, grounding, disposition = _policy_path()
    finding = finding_from_disposition(
        disposition, proposal=proposal, grounding_id=grounding.grounding_id,
        semantic_verification_id=None,
        effective_assertion_class=disposition.effective_assertion_class,
    )
    repo.commit_claim_disposition(
        INVESTIGATION_ID,
        disposition_row=disposition.to_row(),
        finding_row=finding.to_row(),
    )
    validate = AgentOrchestrator._finding_ref_validator(
        repo, INVESTIGATION_ID
    )
    check = validate(finding.finding_id)
    assert check.found is True and check.kind == "finding"
    assert validate("finding:unknown").found is False
    # cross-task: a different investigation of the same repo cannot see it
    other = AgentOrchestrator._finding_ref_validator(repo, "inv-" + "c" * 8)
    assert other(finding.finding_id).found is False


def test_disposition_without_proposal_rolls_back(tmp_path):
    repo, _ = _repo(tmp_path)
    policy, _proposal_obj, _grounding_obj, disposition = _policy_path()
    # no proposal persisted under the disposition's binding for this run:
    # forge a mismatch by pointing at an unknown proposal id
    row = dict(disposition.to_row())
    row["proposal_id"] = "prop-ghost"
    with pytest.raises(ValueError):
        repo.commit_claim_disposition(
            INVESTIGATION_ID, disposition_row=row
        )
    assert repo.list_claim_dispositions(INVESTIGATION_ID) == []
    assert repo.list_investigation_findings(INVESTIGATION_ID) == []


def test_finding_insert_failure_rolls_back_disposition(tmp_path):
    repo, _ = _repo(tmp_path)
    policy, proposal, grounding, disposition = _policy_path()
    finding = finding_from_disposition(
        disposition, proposal=proposal, grounding_id=grounding.grounding_id,
        semantic_verification_id=None,
        effective_assertion_class=disposition.effective_assertion_class,
    )
    bad_finding = finding.to_row()
    bad_finding["status"] = "accepted"  # CHECK violation inside the tx
    with pytest.raises(Exception):
        repo.commit_claim_disposition(
            INVESTIGATION_ID,
            disposition_row=disposition.to_row(),
            finding_row=bad_finding,
        )
    assert repo.list_claim_dispositions(INVESTIGATION_ID) == []
    assert repo.list_investigation_findings(INVESTIGATION_ID) == []
