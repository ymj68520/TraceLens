"""P6A §59/§61 manifest tests + §66 explicit admission pipeline."""

import pytest

from httpserver.services.investigation.agent_graph_admission import (
    GraphAdmissionDecision,
    GraphAdmissionPolicy,
)
from httpserver.services.investigation.agent_graph_candidate import (
    GraphCandidateBuilder,
)
from httpserver.services.investigation.agent_graph_manifest import (
    ManifestStateMachine,
    ManifestTransitionError,
    admit_graph_candidate,
    propose_graph_candidate,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "4" * 8

_BUILDER = GraphCandidateBuilder()


def _evidence_candidate(summary="identical payload"):
    return _BUILDER.candidate_from_evidence_context(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        summary=summary,
        evidence_refs=("file:C/1.iso",),
    )


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
                objective="manifest",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    return repo


def _propose(repo) -> dict:
    outcome = propose_graph_candidate(
        repo, INVESTIGATION_ID, _evidence_candidate()
    )
    assert outcome["violations"] == ()
    return outcome


async def test_admit_creates_exactly_one_queued_manifest(tmp_path):
    repo = _repo(tmp_path)
    _propose(repo)
    outcome = admit_graph_candidate(
        repo, INVESTIGATION_ID,
        candidate_id=_evidence_candidate().candidate_id,
        source_revision=1, source_state_hash="s-hash",
    )
    assert outcome["decision"].decision is GraphAdmissionDecision.ADMIT
    assert outcome["commit"]["episode_inserted"] is True
    assert outcome["commit"]["manifest_inserted"] is True
    manifests = repo.list_graph_materializations(INVESTIGATION_ID)
    assert len(manifests) == 1
    assert manifests[0]["status"] == "queued"
    assert manifests[0]["episode_id"] == outcome["episode"]["episode_id"]


async def test_replay_does_not_duplicate_manifest(tmp_path):
    repo = _repo(tmp_path)
    _propose(repo)
    candidate_id = _evidence_candidate().candidate_id
    first = admit_graph_candidate(
        repo, INVESTIGATION_ID, candidate_id=candidate_id
    )
    second = admit_graph_candidate(
        repo, INVESTIGATION_ID, candidate_id=candidate_id
    )
    assert first["commit"]["manifest_inserted"] is True
    assert second["commit"]["manifest_inserted"] is False
    assert first["materialization_id"] == second["materialization_id"]
    assert len(repo.list_graph_materializations(INVESTIGATION_ID)) == 1


async def test_defer_creates_no_manifest(tmp_path):
    repo = _repo(tmp_path)
    # unverified review_pending finding defers under the starter policy
    finding = {
        "finding_id": "finding:u",
        "status": "review_pending",
        "evidence_refs": ("file:C/a.doc",),
        "semantic_verification_id": None,
        "text": "finding",
        "limitations": (),
    }
    candidate = _BUILDER.candidate_from_finding(
        finding, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    repo.record_graph_candidates(INVESTIGATION_ID, [candidate.to_row()])
    findings = {finding["finding_id"]: finding}
    outcome = admit_graph_candidate(
        repo, INVESTIGATION_ID,
        candidate_id=candidate.candidate_id,
        finding_resolver=findings.get,
    )
    assert outcome["decision"].decision is GraphAdmissionDecision.DEFER
    assert outcome["episode"] is None
    assert outcome["materialization_id"] is None
    # the immutable decision still persists (§27)
    decisions = repo.list_graph_admission_decisions(
        INVESTIGATION_ID, candidate_id=candidate.candidate_id
    )
    assert len(decisions) == 1
    assert repo.list_graph_materializations(INVESTIGATION_ID) == []


async def test_not_admitted_creates_no_manifest(tmp_path):
    repo = _repo(tmp_path)
    # candidate whose finding is rejected -> not_admitted
    finding = {
        "finding_id": "finding:r",
        "status": "rejected",
        "evidence_refs": ("file:C/a.doc",),
        "semantic_verification_id": None,
        "text": "finding",
        "limitations": (),
    }
    candidate = _BUILDER.candidate_from_finding(
        {
            **finding,
            "status": "review_pending",
            "semantic_verification_id": "sver-1",
        },
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
    )
    repo.record_graph_candidates(INVESTIGATION_ID, [candidate.to_row()])
    findings = {finding["finding_id"]: finding}
    outcome = admit_graph_candidate(
        repo, INVESTIGATION_ID,
        candidate_id=candidate.candidate_id,
        finding_resolver=findings.get,
    )
    assert outcome["decision"].decision is GraphAdmissionDecision.NOT_ADMITTED
    assert outcome["materialization_id"] is None
    assert repo.list_graph_materializations(INVESTIGATION_ID) == []


def test_manifest_state_machine_guards():
    ManifestStateMachine.assert_transition("queued", "running")
    ManifestStateMachine.assert_transition("running", "active")
    with pytest.raises(ManifestTransitionError):
        ManifestStateMachine.assert_transition("queued", "active")
    with pytest.raises(ManifestTransitionError):
        ManifestStateMachine.assert_transition("active", "running")
    with pytest.raises(ManifestTransitionError):
        ManifestStateMachine.assert_transition("invalidated", "running")


async def test_manifest_state_changes_consume_zero_revision(tmp_path):
    repo = _repo(tmp_path)
    _propose(repo)
    candidate_id = _evidence_candidate().candidate_id
    admit_graph_candidate(repo, INVESTIGATION_ID, candidate_id=candidate_id)
    manifest = repo.list_graph_materializations(INVESTIGATION_ID)[0]
    repo.advance_graph_materialization(
        INVESTIGATION_ID, manifest["materialization_id"],
        to_status="running",
    )
    repo.advance_graph_materialization(
        INVESTIGATION_ID, manifest["materialization_id"],
        to_status="active",
    )
    assert repo.get_working_state_revision(INVESTIGATION_ID, 1) is not None
    assert repo.get_working_state_revision(INVESTIGATION_ID, 2) is None


async def test_failed_manifest_does_not_touch_finding_or_evidence(tmp_path):
    repo = _repo(tmp_path)
    _propose(repo)
    candidate_id = _evidence_candidate().candidate_id
    admit_graph_candidate(repo, INVESTIGATION_ID, candidate_id=candidate_id)
    manifest = repo.list_graph_materializations(INVESTIGATION_ID)[0]
    repo.advance_graph_materialization(
        INVESTIGATION_ID, manifest["materialization_id"],
        to_status="running",
    )
    repo.advance_graph_materialization(
        INVESTIGATION_ID, manifest["materialization_id"],
        to_status="failed",
        failure_code="graphiti_unavailable",
        failure_summary="neo4j connection refused",
    )
    stored = repo.get_graph_materialization(
        INVESTIGATION_ID, manifest["materialization_id"]
    )
    assert stored["status"] == "failed"
    assert stored["failure_code"] == "graphiti_unavailable"
    # the underlying candidate/episode rows stay untouched
    assert repo.list_graph_candidates(INVESTIGATION_ID)
    assert repo.list_graph_episodes(INVESTIGATION_ID)


async def test_decision_insert_failure_rolls_back_unit(tmp_path):
    repo = _repo(tmp_path)
    _propose(repo)
    candidate_id = _evidence_candidate().candidate_id
    episode_row = {
        "episode_id": "gepis:x",
        "episode_version": "forensic-graph-episode:v1",
        "candidate_ids": [candidate_id],
        "admission_decision_ids": ["gadm:x"],
        "semantic_units": [],
        "evidence_refs": ("file:C/1.iso",),
        "finding_refs": (),
        "correlation_refs": (),
        "occurrence_refs": (),
        "review_statuses": {},
        "provenance_manifest": [],
        "policy_version": "p",
        "policy_hash": "ph",
        "input_hash": "ih",
    }
    bad_decision = {
        "decision_id": "gadm:x",
        "candidate_id": candidate_id,
        "candidate_hash": "h",
        "decision": "maybe",  # CHECK violation
        "reason_codes": (),
        "limitations": (),
        "policy_version": "p",
        "policy_hash": "ph",
        "resolved_provenance": {},
        "input_hash": "ih",
    }
    with pytest.raises(Exception):
        repo.commit_graph_admission(
            INVESTIGATION_ID,
            decision_row=bad_decision,
            episode_row=episode_row,
            manifest={
                "materialization_id": "gm:x",
                "episode_id": "gepis:x",
                "episode_hash": "ih",
                "backend_kind": "graphiti",
                "input_hash": "ih",
            },
        )
    assert repo.list_graph_admission_decisions(INVESTIGATION_ID) == []
    assert repo.list_graph_episodes(INVESTIGATION_ID) == []
    assert repo.list_graph_materializations(INVESTIGATION_ID) == []


async def test_episode_without_decision_rolls_back(tmp_path):
    repo = _repo(tmp_path)
    _propose(repo)
    candidate_id = _evidence_candidate().candidate_id
    # mismatched manifest: episode id differs from the manifest binding
    with pytest.raises(ValueError):
        repo.commit_graph_admission(
            INVESTIGATION_ID,
            decision_row={
                "decision_id": "gadm:ok",
                "candidate_id": candidate_id,
                "candidate_hash": "h",
                "decision": "admit",
                "reason_codes": (),
                "limitations": (),
                "policy_version": "p",
                "policy_hash": "ph",
                "resolved_provenance": {},
                "input_hash": "ih",
            },
            episode_row={
                "episode_id": "gepis:real",
                "episode_version": "forensic-graph-episode:v1",
                "candidate_ids": [candidate_id],
                "admission_decision_ids": ["gadm:ok"],
                "semantic_units": [],
                "evidence_refs": ("file:C/1.iso",),
                "finding_refs": (),
                "correlation_refs": (),
                "occurrence_refs": (),
                "review_statuses": {},
                "provenance_manifest": [],
                "policy_version": "p",
                "policy_hash": "ph",
                "input_hash": "ih",
            },
            manifest={
                "materialization_id": "gm:other-episode",
                "episode_id": "gepis:OTHER",
                "episode_hash": "ih",
                "backend_kind": "graphiti",
                "input_hash": "ih",
            },
        )
    assert repo.list_graph_episodes(INVESTIGATION_ID) == []
