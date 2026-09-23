"""P6A §60 invalidation matrix + §35 rejected-finding E2E foundation +
§36 accepted evolution."""

import pytest

from httpserver.services.investigation.agent_findings import (
    FindingReviewService,
    InvestigationFindingV1,
    finding_from_disposition,
)
from httpserver.services.investigation.agent_graph_admission import (
    GraphAdmissionDecision,
    GraphAdmissionPolicy,
    GraphReaderMode,
    retrieval_eligible,
)
from httpserver.services.investigation.agent_graph_candidate import (
    GraphCandidateBuilder,
)
from httpserver.services.investigation.agent_graph_manifest import (
    admit_graph_candidate,
    evaluate_graph_invalidation,
    propose_graph_candidate,
    supersede_graph_materialization,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "7" * 8

_BUILDER = GraphCandidateBuilder()
_REVIEW = FindingReviewService()


def _finding_row(status="review_pending", finding_id="finding:1",
                 verification_id="sver-1"):
    return {
        "finding_id": finding_id,
        "status": status,
        "evidence_refs": ("file:C/a.doc",),
        "semantic_verification_id": verification_id,
        "text": "logon cluster indicates shared use",
        "limitations": (),
    }


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
                objective="inv",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    return repo


def _materialize_verified_finding(repo, finding):
    """proposal -> admission -> episode -> queued -> running -> active."""
    candidate = _BUILDER.candidate_from_finding(
        finding, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    propose_graph_candidate(repo, INVESTIGATION_ID, candidate)
    findings = {finding["finding_id"]: finding}
    outcome = admit_graph_candidate(
        repo, INVESTIGATION_ID,
        candidate_id=candidate.candidate_id,
        finding_resolver=findings.get,
        source_revision=1, source_state_hash="s-hash",
    )
    assert outcome["decision"].decision is GraphAdmissionDecision.ADMIT
    manifest_id = outcome["materialization_id"]
    repo.advance_graph_materialization(
        INVESTIGATION_ID, manifest_id, to_status="running"
    )
    repo.advance_graph_materialization(
        INVESTIGATION_ID, manifest_id, to_status="active"
    )
    return candidate, manifest_id


def test_rejected_finding_invalidates_active_manifest(tmp_path):
    """§35 E2E foundation: review_pending finding materialized as active;
    Analyst rejects; invalidation sweep flips the manifest to invalidated
    while the physical graph object is left alone."""
    repo = _repo(tmp_path)
    finding = _finding_row()
    _candidate, manifest_id = _materialize_verified_finding(repo, finding)
    assert repo.get_graph_materialization(
        INVESTIGATION_ID, manifest_id
    )["status"] == "active"

    # Analyst Review -> rejected (the ONLY accepted/rejected writer)
    rejected = dict(finding, status="rejected")
    changes = evaluate_graph_invalidation(
        repo, INVESTIGATION_ID, finding_resolver=lambda ref: rejected
    )
    assert changes and changes[0]["to_status"] == "invalidated"
    stored = repo.get_graph_materialization(INVESTIGATION_ID, manifest_id)
    assert stored["status"] == "invalidated"
    assert stored["failure_code"] == "FINDING_REJECTED"
    # logical retrieval eligibility is false even though the physical
    # graph object is assumed to still exist
    assert retrieval_eligible("rejected", GraphReaderMode.INVESTIGATION) is False


def test_accepted_evolution_makes_old_slice_stale_requires_new_episode(tmp_path):
    """§36: accepting a review_pending finding marks the old
    materialization stale; the accepted status requires a NEW frozen
    episode, never an update of the old one."""
    repo = _repo(tmp_path)
    finding = _finding_row()
    _candidate, manifest_id = _materialize_verified_finding(repo, finding)

    accepted = dict(finding, status="accepted")
    changes = evaluate_graph_invalidation(
        repo, INVESTIGATION_ID, finding_resolver=lambda ref: accepted
    )
    assert changes and changes[0]["to_status"] == "stale"
    assert repo.get_graph_materialization(
        INVESTIGATION_ID, manifest_id
    )["status"] == "stale"

    # the accepted semantic unit is a NEW candidate/episode/manifest
    new_candidate = _BUILDER.candidate_from_finding(
        accepted, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    propose_graph_candidate(repo, INVESTIGATION_ID, new_candidate)
    findings = {accepted["finding_id"]: accepted}
    outcome = admit_graph_candidate(
        repo, INVESTIGATION_ID,
        candidate_id=new_candidate.candidate_id,
        finding_resolver=findings.get,
    )
    new_manifest_id = outcome["materialization_id"]
    assert new_manifest_id != manifest_id
    new_episode = repo.get_graph_episode(
        INVESTIGATION_ID, outcome["episode"]["episode_id"]
    )
    assert new_episode["review_statuses"] == {
        new_candidate.candidate_id: "accepted"
    }
    supersede_graph_materialization(
        repo, INVESTIGATION_ID,
        old_materialization_id=manifest_id,
        new_materialization_id=new_manifest_id,
    )
    assert repo.get_graph_materialization(
        INVESTIGATION_ID, manifest_id
    )["status"] == "superseded"
    assert (
        repo.get_graph_materialization(
            INVESTIGATION_ID, new_manifest_id
        )["supersedes_materialization_id"]
        == manifest_id
    )


def test_evidence_invalidation_sweep(tmp_path):
    repo = _repo(tmp_path)
    finding = _finding_row()
    _candidate, manifest_id = _materialize_verified_finding(repo, finding)
    changes = evaluate_graph_invalidation(
        repo, INVESTIGATION_ID,
        finding_resolver=lambda ref: _finding_row(),
        evidence_resolver=lambda ref: False,  # evidence gone/unavailable
    )
    assert changes and changes[0]["to_status"] == "invalidated"
    assert changes[0]["reason"] == "EVIDENCE_MISSING"


def test_unrelated_finding_changes_cause_no_invalidation(tmp_path):
    repo = _repo(tmp_path)
    finding = _finding_row()
    _candidate, manifest_id = _materialize_verified_finding(repo, finding)

    def unrelated_resolver(ref):
        if ref == finding["finding_id"]:
            return _finding_row()  # unchanged review_pending+verified
        return _finding_row(finding_id="finding:other")  # unrelated change

    changes = evaluate_graph_invalidation(
        repo, INVESTIGATION_ID, finding_resolver=unrelated_resolver
    )
    assert changes == []
    assert repo.get_graph_materialization(
        INVESTIGATION_ID, manifest_id
    )["status"] == "active"


def test_physical_cleanup_not_required_for_logical_filtering(tmp_path):
    """§34: the manifest reaches invalidated purely by SQLite state; no
    Graphiti/Neo4j call exists in the module at all."""
    import inspect
    import httpserver.services.investigation.agent_graph_manifest as mod

    source = inspect.getsource(mod)
    assert "add_episode" not in source
    for driver_token in ("Graphiti(", "driver", "execute_query",
                         "session(", "cypher"):
        assert driver_token not in source, driver_token
