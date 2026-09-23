"""P6B §63-§65 materialization executor tests: frozen-input execution,
claim atomicity, completion-time revalidation, retry/restart."""

import pytest

from httpserver.services.investigation.agent_graph_admission import (
    GraphAdmissionDecision,
    GraphAdmissionPolicy,
)
from httpserver.services.investigation.agent_graph_backend import (
    FakeGraphBackend,
    GraphMaterializationAdapter,
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

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "b" * 8

_BUILDER = GraphCandidateBuilder()


def _finding(status="review_pending", verification_id="sver-1"):
    return {
        "finding_id": "finding:1",
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
                objective="exec",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    return repo


def _queue_verified_finding(repo, finding=None, resolver=None):
    finding = finding or _finding()
    candidate = _BUILDER.candidate_from_finding(
        finding, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    propose_graph_candidate(repo, INVESTIGATION_ID, candidate)
    findings = resolver or {finding["finding_id"]: finding}
    outcome = admit_graph_candidate(
        repo, INVESTIGATION_ID,
        candidate_id=candidate.candidate_id,
        finding_resolver=findings.get,
        source_revision=1, source_state_hash="s-hash",
    )
    assert outcome["decision"].decision is GraphAdmissionDecision.ADMIT
    return repo, outcome["materialization_id"], finding


def _executor(repo, backend=None, finding_resolver=None,
              evidence_resolver=None):
    async def provider(task_id):
        if task_id != TASK_ID:
            raise RuntimeError("unknown task store")
        return repo

    return GraphMaterializationExecutor(
        runtime_provider=provider,
        backend=backend or FakeGraphBackend(),
        finding_resolver=finding_resolver,
        evidence_resolver=evidence_resolver,
    )


async def test_execute_happy_path_active_with_bindings(tmp_path):
    repo = _repo(tmp_path)
    _repo2, materialization_id, _finding = _queue_verified_finding(repo)
    backend = FakeGraphBackend()
    executor = _executor(repo, backend)
    outcome = await executor.execute_materialization(
        TASK_ID, INVESTIGATION_ID, materialization_id
    )
    assert outcome["outcome"] == "active"
    manifest = repo.get_graph_materialization(
        INVESTIGATION_ID, materialization_id
    )
    assert manifest["status"] == "active"
    assert manifest["activated_at"] is not None
    bindings = repo.list_graph_backend_bindings(
        INVESTIGATION_ID, materialization_id=materialization_id
    )
    assert bindings and bindings[0]["backend_episode_ref"] == (
        outcome["backend_episode_ref"]
    )
    assert backend.calls  # backend actually ingested


async def test_double_dispatch_claim_is_atomic(tmp_path):
    repo = _repo(tmp_path)
    _queued, materialization_id, _f = _queue_verified_finding(repo)
    executor = _executor(repo)
    first = await executor.execute_materialization(
        TASK_ID, INVESTIGATION_ID, materialization_id
    )
    assert first["outcome"] == "active"
    # a late second dispatch conflicts instead of re-ingesting
    second = await executor.execute_materialization(
        TASK_ID, INVESTIGATION_ID, materialization_id
    )
    assert second["outcome"] == "conflict"


async def test_backend_failure_marks_failed(tmp_path):
    repo = _repo(tmp_path)
    _queued, materialization_id, _f = _queue_verified_finding(repo)
    outcome = await _executor(
        repo, FakeGraphBackend(fail_ingest=True)
    ).execute_materialization(TASK_ID, INVESTIGATION_ID, materialization_id)
    assert outcome["outcome"] == "failed"
    assert outcome["failure_code"] == "GRAPH_BACKEND_INGEST_FAILED"
    stored = repo.get_graph_materialization(
        INVESTIGATION_ID, materialization_id
    )
    assert stored["status"] == "failed"


async def test_provenance_unresolvable_fails_closed(tmp_path):
    repo = _repo(tmp_path)
    _queued, materialization_id, _f = _queue_verified_finding(repo)
    outcome = await _executor(
        repo, FakeGraphBackend(fail_lookup=True)
    ).execute_materialization(TASK_ID, INVESTIGATION_ID, materialization_id)
    assert outcome["outcome"] == "failed"
    assert outcome["failure_code"] == "GRAPH_PROVENANCE_UNRESOLVED"
    # never active, even though ingest "succeeded"
    assert repo.get_graph_materialization(
        INVESTIGATION_ID, materialization_id
    )["status"] == "failed"


async def test_finding_rejected_during_ingest_invalidates(tmp_path):
    repo = _repo(tmp_path)
    _queued, materialization_id, finding = _queue_verified_finding(repo)
    rejected = dict(finding, status="rejected")
    executor = _executor(
        repo, finding_resolver=lambda ref: rejected
    )
    outcome = await executor.execute_materialization(
        TASK_ID, INVESTIGATION_ID, materialization_id
    )
    assert outcome["outcome"] == "invalidated"
    assert repo.get_graph_materialization(
        INVESTIGATION_ID, materialization_id
    )["status"] == "invalidated"


async def test_finding_accepted_during_ingest_makes_stale(tmp_path):
    repo = _repo(tmp_path)
    _queued, materialization_id, finding = _queue_verified_finding(repo)
    accepted = dict(finding, status="accepted")
    executor = _executor(repo, finding_resolver=lambda ref: accepted)
    outcome = await executor.execute_materialization(
        TASK_ID, INVESTIGATION_ID, materialization_id
    )
    assert outcome["outcome"] == "stale"
    assert repo.get_graph_materialization(
        INVESTIGATION_ID, materialization_id
    )["status"] == "stale"


async def test_evidence_invalid_during_ingest_invalidates(tmp_path):
    repo = _repo(tmp_path)
    _queued, materialization_id, _f = _queue_verified_finding(repo)
    executor = _executor(
        repo, evidence_resolver=lambda task_id, ref: False
    )
    outcome = await executor.execute_materialization(
        TASK_ID, INVESTIGATION_ID, materialization_id
    )
    assert outcome["outcome"] == "invalidated"


async def test_retry_creates_new_attempt_never_reuses_row(tmp_path):
    repo = _repo(tmp_path)
    _queued, materialization_id, _f = _queue_verified_finding(repo)
    executor = _executor(repo, FakeGraphBackend(fail_ingest=True))
    outcome = await executor.execute_materialization(
        TASK_ID, INVESTIGATION_ID, materialization_id
    )
    assert outcome["outcome"] == "failed"
    retry = repo.retry_graph_materialization(
        INVESTIGATION_ID, materialization_id
    )
    assert retry["attempt_no"] == 2
    assert retry["retry_of"] == materialization_id
    # old failed row unchanged
    assert repo.get_graph_materialization(
        INVESTIGATION_ID, materialization_id
    )["status"] == "failed"
    # retry replay -> same attempt id, no duplicate
    again = repo.retry_graph_materialization(
        INVESTIGATION_ID, materialization_id
    )
    assert again["materialization_id"] == retry["materialization_id"]
    manifests = [
        m for m in repo.list_graph_materializations(INVESTIGATION_ID)
        if m["status"] == "queued"
    ]
    assert len(manifests) == 1


async def test_invalidated_manifest_retry_denied(tmp_path):
    repo = _repo(tmp_path)
    _queued, materialization_id, _f = _queue_verified_finding(repo)
    repo.advance_graph_materialization(
        INVESTIGATION_ID, materialization_id, to_status="invalidated",
        failure_code="FINDING_REJECTED",
    )
    with pytest.raises(Exception):
        repo.retry_graph_materialization(
            INVESTIGATION_ID, materialization_id
        )


async def test_restart_fails_running_keeps_queued(tmp_path):
    repo = _repo(tmp_path)
    _queued, materialization_id, _f = _queue_verified_finding(repo)
    backend = FakeGraphBackend()
    executor = _executor(repo, backend)
    # simulate a running execution at restart
    repo.claim_graph_materialization(INVESTIGATION_ID, materialization_id)
    recovery = await executor.initialize([TASK_ID])
    assert recovery["running_failed"] == 1
    assert recovery["ingested"] == 0
    stored = repo.get_graph_materialization(
        INVESTIGATION_ID, materialization_id
    )
    assert stored["status"] == "failed"
    assert stored["failure_code"] == "GRAPH_RUNTIME_RESTART"
    assert backend.calls == []  # no auto-ingest on initialize

    # queued manifests remain queued through recovery; a different
    # finding gives a different episode -> a genuinely new queued manifest
    other = _finding(status="review_pending", verification_id="sver-9")
    other["finding_id"] = "finding:2"
    candidate2 = _BUILDER.candidate_from_finding(
        other, task_id=TASK_ID, investigation_id=INVESTIGATION_ID
    )
    propose_graph_candidate(repo, INVESTIGATION_ID, candidate2)
    findings2 = {other["finding_id"]: other}
    admitted = admit_graph_candidate(
        repo, INVESTIGATION_ID,
        candidate_id=candidate2.candidate_id,
        finding_resolver=findings2.get,
        source_revision=1, source_state_hash="s-hash",
    )
    second_id = admitted["materialization_id"]
    assert second_id != materialization_id
    await executor.initialize([TASK_ID])
    assert repo.get_graph_materialization(
        INVESTIGATION_ID, second_id
    )["status"] == "queued"
    # explicit dispatch still works after recovery
    outcome = await executor.execute_materialization(
        TASK_ID, INVESTIGATION_ID, second_id
    )
    assert outcome["outcome"] == "active"


async def test_execution_consumes_zero_working_state_revision(tmp_path):
    repo = _repo(tmp_path)
    _queued, materialization_id, _f = _queue_verified_finding(repo)
    await _executor(repo).execute_materialization(
        TASK_ID, INVESTIGATION_ID, materialization_id
    )
    assert repo.get_working_state_revision(INVESTIGATION_ID, 1) is not None
    assert repo.get_working_state_revision(INVESTIGATION_ID, 2) is None
