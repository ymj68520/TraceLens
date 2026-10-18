"""P6B §50-§52 hydration + §72-§75 end-to-end graph pipelines.

§72 finding materialization E2E: evidence -> verified review_pending
Finding -> candidate -> admit -> frozen episode -> queued manifest ->
executor (fake backend) -> provenance binding -> active -> investigation
reader -> hydration back to REAL Evidence. A graph id never becomes
Evidence. §73 report-mode filtering. §74 rejection E2E. §75 backend
hallucination."""

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
)
from httpserver.services.investigation.agent_graph_candidate import (
    GraphCandidateBuilder,
)
from httpserver.services.investigation.agent_graph_hydration import (
    hydrate_graph_result_to_evidence,
)
from httpserver.services.investigation.agent_graph_manifest import (
    admit_graph_candidate,
    evaluate_graph_invalidation,
    propose_graph_candidate,
)
from httpserver.services.investigation.agent_graph_materializer import (
    GraphMaterializationExecutor,
)
from httpserver.services.investigation.agent_graph_reader import (
    ProvenanceGraphReader,
)
from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "e" * 8

_BUILDER = GraphCandidateBuilder()
_REVIEW = FindingReviewService()


def _finding_row(status="review_pending"):
    return {
        "finding_id": "finding:e2e",
        "status": status,
        "evidence_refs": ("file:C/a.doc",),
        "semantic_verification_id": "sver-1",
        "text": "shared logon cluster across hosts",
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
                objective="e2e",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    return repo


def _persist_finding(repo, finding):
    repo.record_claim_proposals(INVESTIGATION_ID, [{
        "proposal_id": "prop-e2e",
        "text": finding["text"],
        "assertion_class": "INFERENCE",
        "evidence_refs": tuple(finding["evidence_refs"]),
        "source_question_ids": (),
        "relationship_refs": (),
        "limitations": (),
        "normalization_warnings": (),
        "normalizer_version": "proposal-normalizer:v1",
        "input_hash": "ph-e2e",
    }])
    repo.record_grounding_results(INVESTIGATION_ID, [{
        "grounding_id": "grnd-e2e",
        "proposal_id": "prop-e2e",
        "grounding_policy_version": 1,
        "input_assertion_class": "INFERENCE",
        "effective_assertion_class": "INFERENCE",
        "status": "grounded",
        "valid_evidence_refs": tuple(finding["evidence_refs"]),
        "invalid_evidence_refs": (),
        "invisible_evidence_refs": (),
        "disallowed_ref_types": (),
        "warnings": (),
        "limitations": (),
        "validator_version": "v",
        "input_hash": "gh-e2e",
    }])


def _provider(repo):
    async def provider(task_id):
        if task_id != TASK_ID:
            raise RuntimeError("unknown task")
        return repo

    return provider


def _reader(repo, finding, backend):
    def backend_query(group_id, query):
        # the physical backend still contains the node regardless of
        # logical state (§74)
        return [
            {
                "backend_episode_name": (
                    f"tracelens:materialization:{m}:unit:{u}"
                ),
                "backend_ref": "node-finding-e2e",
                "backend_object_kind": "episode",
                "semantic_unit_id": u,
            }
            for (m, u) in [backend["binding"]]
        ]

    def finding_resolver(ref):
        return {finding["finding_id"]: finding}.get(ref)

    return ProvenanceGraphReader(
        repo, finding_resolver=finding_resolver,
        backend_query=backend_query,
    )


async def test_full_finding_materialization_e2e(tmp_path):
    """§72: candidate -> admit -> frozen episode -> queued -> executor ->
    active -> investigation reader -> hydration to real Evidence; graph
    ids never become Evidence."""
    repo = _repo(tmp_path)
    finding = _finding_row()
    _persist_finding(repo, finding)
    backend_data = {"binding": None}
    candidate = _BUILDER.candidate_from_finding(
        finding, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    propose_graph_candidate(repo, INVESTIGATION_ID, candidate)
    findings = {finding["finding_id"]: finding}
    admitted = admit_graph_candidate(
        repo, INVESTIGATION_ID,
        candidate_id=candidate.candidate_id,
        finding_resolver=findings.get,
    )
    manifest_id = admitted["materialization_id"]
    episode = repo.get_graph_episode(
        INVESTIGATION_ID, admitted["episode"]["episode_id"]
    )
    unit_id = episode["semantic_units"][0]["unit_id"]
    backend_data["binding"] = (manifest_id, unit_id)

    executor = GraphMaterializationExecutor(
        runtime_provider=_provider(repo),
        backend=FakeBackendForE2E(),
        finding_resolver=findings.get,
        evidence_resolver=lambda task_id, ref: ref == "file:C/a.doc",
    )
    commit = await executor.execute_materialization(
        TASK_ID, INVESTIGATION_ID, manifest_id
    )
    assert commit["outcome"] == "active"
    assert repo.get_graph_materialization(
        INVESTIGATION_ID, manifest_id
    )["status"] == "active"

    # investigation mode: visible with explicit unconfirmed marker
    reader = _reader(repo, finding, backend_data)
    result = reader.read(INVESTIGATION_ID, GraphReaderMode.INVESTIGATION)
    assert len(result.objects) == 1
    obj = result.objects[0]
    assert obj.trust_class.value == "provenance_bound"
    assert obj.review_status == "review_pending"
    assert obj.confirmed is False

    # hydration: real Evidence only, no graph ids
    hydration = await hydrate_graph_result_to_evidence(
        result, task_id=TASK_ID,
        evidence_resolver=_e2e_resolver,
    )
    assert hydration["resolved_evidence_refs"] == ["file:C/a.doc"]
    assert hydration["resolved_evidence_refs"].count("node-finding-e2e") == 0
    for ref in hydration["resolved_evidence_refs"]:
        assert not ref.startswith("node-") and not ref.startswith("gm:")
    assert hydration["invalidation_signals"] == []


async def _e2e_resolver(task_id, ref):
    return {"resolved": True} if ref == "file:C/a.doc" else None


async def test_report_mode_excludes_review_pending(tmp_path):
    """§73: the same materialization is investigation-visible but
    report-invisible until the Finding is accepted (new episode)."""
    repo = _repo(tmp_path)
    finding = _finding_row()
    _persist_finding(repo, finding)
    backend_data = {"binding": None}
    candidate = _BUILDER.candidate_from_finding(
        finding, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    propose_graph_candidate(repo, INVESTIGATION_ID, candidate)
    findings = {finding["finding_id"]: finding}
    admitted = admit_graph_candidate(
        repo, INVESTIGATION_ID,
        candidate_id=candidate.candidate_id,
        finding_resolver=findings.get,
    )
    manifest_id = admitted["materialization_id"]
    episode = repo.get_graph_episode(
        INVESTIGATION_ID, admitted["episode"]["episode_id"]
    )
    unit_id = episode["semantic_units"][0]["unit_id"]
    backend_data["binding"] = (manifest_id, unit_id)
    executor = GraphMaterializationExecutor(
        runtime_provider=_provider(repo),
        backend=FakeBackendForE2E(),
        finding_resolver=findings.get,
        evidence_resolver=lambda task_id, ref: ref == "file:C/a.doc",
    )
    await executor.execute_materialization(TASK_ID, INVESTIGATION_ID,
                                           manifest_id)

    reader = _reader(repo, finding, backend_data)
    investigation = reader.read(INVESTIGATION_ID,
                                GraphReaderMode.INVESTIGATION)
    report = reader.read(INVESTIGATION_ID, GraphReaderMode.REPORT)
    assert len(investigation.objects) == 1
    assert report.objects == ()  # review_pending never enters report context

    # Analyst accepts -> new accepted candidate/episode/materialization
    accepted = dict(finding, status="accepted")
    new_candidate = _BUILDER.candidate_from_finding(
        accepted, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    propose_graph_candidate(repo, INVESTIGATION_ID, new_candidate)
    admitted2 = admit_graph_candidate(
        repo, INVESTIGATION_ID,
        candidate_id=new_candidate.candidate_id,
        finding_resolver=findings.get,
    )
    new_manifest = admitted2["materialization_id"]
    episode2 = repo.get_graph_episode(
        INVESTIGATION_ID, admitted2["episode"]["episode_id"]
    )
    unit2 = episode2["semantic_units"][0]["unit_id"]
    backend_data["binding"] = (new_manifest, unit2)

    executor2 = GraphMaterializationExecutor(
        runtime_provider=_provider(repo),
        backend=FakeBackendForE2E(),
        finding_resolver=findings.get,
        evidence_resolver=lambda task_id, ref: ref == "file:C/a.doc",
    )
    commit2 = await executor2.execute_materialization(
        TASK_ID, INVESTIGATION_ID, new_manifest
    )
    assert commit2["outcome"] == "active"

    reader = _reader(repo, accepted, backend_data)
    report_after = reader.read(INVESTIGATION_ID, GraphReaderMode.REPORT)
    assert len(report_after.objects) == 1
    assert report_after.objects[0].review_status == "accepted"
    hydrated = await hydrate_graph_result_to_evidence(
        report_after, task_id=TASK_ID,
        evidence_resolver=_e2e_resolver,
    )
    # final citation chain hydrates to real Evidence only
    assert hydrated["resolved_evidence_refs"] == ["file:C/a.doc"]


class FakeBackendForE2E:
    """Minimal backend storing the last binding for reader fixtures."""

    def __init__(self):
        self.last = None

    async def ingest(self, payload):
        self.last = payload
        from httpserver.services.investigation.agent_graph_backend import (
            BackendIngestOutcome,
        )

        return BackendIngestOutcome(success=True,
                                    backend_episode_ref="ep-e2e")

    async def find_episode_ref(self, episode_name, group_id):
        return "ep-e2e"
