"""P6B §67-§71 ProvenanceGraphReader tests: logical-state filtering,
modes, current canonical re-check, provenance chains, degradation."""

import pytest

from httpserver.services.investigation.agent_graph_admission import (
    GraphAdmissionDecision,
    GraphAdmissionPolicy,
    GraphReaderMode,
)
from httpserver.services.investigation.agent_graph_candidate import (
    GraphCandidateBuilder,
)
from httpserver.services.investigation.agent_graph_manifest import (
    admit_graph_candidate,
    propose_graph_candidate,
)
from httpserver.services.investigation.agent_graph_materializer import (
    GraphMaterializationExecutor,
)
from httpserver.services.investigation.agent_graph_reader import (
    GraphReaderMode as ReaderModeAlias,
    ProvenanceGraphReader,
    TrustClass,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "c" * 8

_BUILDER = GraphCandidateBuilder()


def _finding(status="review_pending", verification_id="sver-1",
             finding_id="finding:1"):
    return {
        "finding_id": finding_id,
        "status": status,
        "evidence_refs": ("file:C/a.doc",),
        "semantic_verification_id": verification_id,
        "text": "shared logon cluster",
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
                objective="reader",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    return repo


def _materialize_active(repo, finding):
    candidate = _BUILDER.candidate_from_finding(
        finding, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    propose_graph_candidate(repo, INVESTIGATION_ID, candidate)
    findings = {finding["finding_id"]: finding}
    outcome = admit_graph_candidate(
        repo, INVESTIGATION_ID,
        candidate_id=candidate.candidate_id,
        finding_resolver=findings.get,
    )
    manifest_id = outcome["materialization_id"]
    repo.advance_graph_materialization(
        INVESTIGATION_ID, manifest_id, to_status="running"
    )
    repo.advance_graph_materialization(
        INVESTIGATION_ID, manifest_id, to_status="active"
    )
    episode = outcome["episode"]
    unit_id = episode["semantic_units"][0]["unit_id"]
    backend_name = f"tracelens:materialization:{manifest_id}:unit:{unit_id}"
    return manifest_id, backend_name, unit_id


def _backend_rows(rows):
    return lambda group_id, query: rows


def _reader(repo, finding=None, backend_rows=()):
    # backend_rows is the RAW row list; _backend_rows wraps it once
    return ProvenanceGraphReader(
        repo,
        finding_resolver=(
            (lambda ref: {finding["finding_id"]: finding}.get(ref))
            if finding else None
        ),
        backend_query=_backend_rows(backend_rows),
    )


async def _active_fixture(tmp_path, status="review_pending",
                          verification_id="sver-1"):
    repo = _repo(tmp_path)
    finding = _finding(status=status, verification_id=verification_id)
    manifest_id, backend_name, unit_id = _materialize_active(repo, finding)
    rows = [{
        "backend_episode_name": backend_name,
        "backend_ref": "node-1",
        "backend_object_kind": "episode",
        "semantic_unit_id": unit_id,
    }]
    return repo, finding, manifest_id, rows


async def test_active_manifest_returns_provenance_bound_unit(tmp_path):
    repo, finding, manifest_id, rows = await _active_fixture(tmp_path)
    result = _reader(repo, _finding(), rows).read(
        INVESTIGATION_ID, GraphReaderMode.INVESTIGATION
    )
    assert len(result.objects) == 1
    obj = result.objects[0]
    assert obj.trust_class is TrustClass.PROVENANCE_BOUND
    assert obj.materialization_id == manifest_id
    assert obj.review_status == "review_pending"
    assert obj.confirmed is False  # §44: unconfirmed marker preserved
    assert obj.evidence_refs == ("file:C/a.doc",)
    assert result.evidence_refs == ("file:C/a.doc",)


async def test_non_active_states_are_filtered(tmp_path):
    """§37: only ACTIVE manifests are trusted; queued/running/failed/
    stale/invalidated/superseded are all filtered immediately."""
    repo = _repo(tmp_path)
    finding = _finding()

    counter = {"n": 0}

    def _new_queued():
        counter["n"] += 1
        indexed = _finding(finding_id=f"finding:multi-{counter['n']}")
        candidate = _BUILDER.candidate_from_finding(
            indexed, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
        )
        propose_graph_candidate(repo, INVESTIGATION_ID, candidate)
        findings = {indexed["finding_id"]: indexed}
        outcome = admit_graph_candidate(
            repo, INVESTIGATION_ID,
            candidate_id=candidate.candidate_id,
            finding_resolver=findings.get,
        )
        manifest_id = outcome["materialization_id"]
        episode = outcome["episode"]
        unit_id = episode["semantic_units"][0]["unit_id"]
        return manifest_id, {
            "backend_episode_name":
                f"tracelens:materialization:{manifest_id}:unit:{unit_id}",
            "backend_ref": f"node-{manifest_id}",
            "backend_object_kind": "episode",
            "semantic_unit_id": unit_id,
        }

    def _to_active(manifest_id):
        repo.claim_graph_materialization(INVESTIGATION_ID, manifest_id)
        repo.advance_graph_materialization(
            INVESTIGATION_ID, manifest_id, to_status="active"
        )

    failed_id, failed_rows = _new_queued()
    repo.claim_graph_materialization(INVESTIGATION_ID, failed_id)
    repo.fail_graph_materialization(
        INVESTIGATION_ID, failed_id,
        expected_status="running",
        failure_code="GRAPH_BACKEND_UNAVAILABLE",
    )
    stale_id, stale_rows = _new_queued()
    _to_active(stale_id)
    repo.advance_graph_materialization(
        INVESTIGATION_ID, stale_id, to_status="stale"
    )
    invalidated_id, invalidated_rows = _new_queued()
    _to_active(invalidated_id)
    repo.advance_graph_materialization(
        INVESTIGATION_ID, invalidated_id, to_status="invalidated"
    )
    superseded_id, superseded_rows = _new_queued()
    _to_active(superseded_id)
    repo.advance_graph_materialization(
        INVESTIGATION_ID, superseded_id, to_status="superseded"
    )
    queued_id, queued_rows = _new_queued()
    queued_id2, queued_rows2 = _new_queued()
    running_id, running_rows = _new_queued()
    repo.claim_graph_materialization(INVESTIGATION_ID, running_id)

    all_rows = [
        failed_rows, stale_rows, invalidated_rows, superseded_rows,
        queued_rows, running_rows, queued_rows2,
    ]
    reader = _reader(repo, finding, backend_rows=all_rows)
    result = reader.read(INVESTIGATION_ID, GraphReaderMode.INVESTIGATION)
    assert result.objects == ()
    assert len(result.locator_refs) == 0  # named bindings, simply filtered


async def test_investigation_vs_report_modes(tmp_path):
    """§45: the SAME review_pending materialization is visible in
    investigation mode and invisible in report mode."""
    repo, finding, _mid, rows = await _active_fixture(tmp_path)
    reader = _reader(repo, _finding(), rows)
    investigation = reader.read(
        INVESTIGATION_ID, GraphReaderMode.INVESTIGATION
    )
    report = reader.read(INVESTIGATION_ID, GraphReaderMode.REPORT)
    assert len(investigation.objects) == 1
    assert investigation.objects[0].confirmed is False
    assert report.objects == ()


async def test_current_rejected_finding_excluded_even_if_sweep_pending(tmp_path):
    """§47: race protection — the reader checks CURRENT canonical status."""
    repo = _repo(tmp_path)
    finding = _finding(status="rejected")
    manifest_id, backend_name, unit_id = _materialize_active(
        repo, _finding()
    )
    # manifest active, but canonical finding is now rejected:
    rows = [{
        "backend_episode_name": backend_name,
        "backend_ref": "node-1",
        "backend_object_kind": "episode",
        "semantic_unit_id": unit_id,
    }]
    result = _reader(repo, finding, rows).read(
        INVESTIGATION_ID, GraphReaderMode.INVESTIGATION
    )
    assert result.objects == ()


async def test_currently_accepted_review_pending_stays_eligible(tmp_path):
    """§48: accepted evolution does not cause a false rejection — the
    frozen provenance is retained and eligibility follows current state."""
    repo = _repo(tmp_path)
    finding = _finding_row = _finding(status="accepted")
    manifest_id, backend_name, unit_id = _materialize_active(
        repo, _finding()
    )
    rows = [{
        "backend_episode_name": backend_name,
        "backend_ref": "node-1",
        "backend_object_kind": "episode",
        "semantic_unit_id": unit_id,
    }]
    result = _reader(repo, finding, rows).read(
        INVESTIGATION_ID, GraphReaderMode.INVESTIGATION
    )
    assert len(result.objects) == 1
    assert result.objects[0].review_status == "accepted"
    assert result.objects[0].confirmed is True


async def test_missing_and_cross_task_provenance_dropped(tmp_path):
    repo = _repo(tmp_path)
    reader = _reader(
        repo,
        backend_rows=[
            {"backend_episode_name": "unrelated-backend-name",
             "backend_ref": "node-x",
             "backend_object_kind": "episode"},
            {"backend_episode_name":
                 "tracelens:materialization:gm:ghost:unit:u1",
             "backend_ref": "node-y",
             "backend_object_kind": "episode",
             "semantic_unit_id": "u1"},
        ],
    )
    result = reader.read(INVESTIGATION_ID, GraphReaderMode.INVESTIGATION)
    assert result.objects == ()
    assert set(result.locator_refs) == {"node-x", "node-y"}


async def test_backend_unavailable_degrades_gracefully(tmp_path):
    repo = _repo(tmp_path)

    def broken_query(group_id, query):
        raise ConnectionError("neo4j down")

    reader = ProvenanceGraphReader(
        repo, backend_query=broken_query
    )
    result = reader.read(INVESTIGATION_ID, GraphReaderMode.INVESTIGATION)
    assert result.objects == ()
    assert any(
        item.startswith("GRAPH_BACKEND_UNAVAILABLE")
        for item in result.limitations
    )


async def test_backend_hallucinated_causality_is_not_canonical(tmp_path):
    """§75: a backend edge claiming 'CAUSED' stays a derived navigation
    relation — the reader returns it only with the frozen episode's
    evidence provenance and never upgrades semantic authority."""
    repo, finding, _mid, rows = await _active_fixture(tmp_path)
    # fake backend returns a causality edge built from our unit
    rows = [dict(rows[0], backend_object_kind="edge",
                 backend_ref="edge-caused-1")]
    result = _reader(repo, _finding(), rows).read(
        INVESTIGATION_ID, GraphReaderMode.INVESTIGATION
    )
    obj = result.objects[0]
    # semantic authority stays bound to the canonical finding layer
    assert obj.semantic_authority in ("canonical_finding",
                                      "graph_derived_locator")
    assert obj.evidence_refs == ("file:C/a.doc",)  # frozen refs only
