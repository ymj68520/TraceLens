"""P4B-3 tests: atomic semantic integration (§41/§42/§43) and the guarded
completed->stale primitive (§10.3)."""

import pytest

from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeConflictError,
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
    DelegationSpec,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    QuestionPriority,
    QuestionSource,
    WorkingQuestion,
    working_state_to_json,
)
from httpserver.services.investigation.repository import InvestigationRepository

pytestmark = pytest.mark.migration_matrix


INTEGRATION_POLICY = "supervisor-integration-policy:v1"


def _typed_state(task_id, investigation_id, question_id="q-1"):
    return AgentWorkingStateV1(
        task_id=task_id,
        investigation_id=investigation_id,
        objective="p4b",
        questions=(
            WorkingQuestion(
                question_id=question_id,
                text="unauthorized logons?",
                source=QuestionSource.charter,
                priority=QuestionPriority.required,
            ),
        ),
    )


@pytest.fixture()
def env(tmp_path):
    db = tmp_path / "investigation.db"
    store = InvestigationRepository(db, "task-A")
    repo = AgentRuntimeRepository(store)
    investigation_id = "inv-" + "a" * 8
    initial = _typed_state("task-A", investigation_id)
    investigation, _rev = repo.create_investigation(
        working_state_to_json(initial), investigation_id=investigation_id
    )
    run = repo.start_run(investigation.investigation_id)
    repo.mark_run_running(run.run_id)
    return repo, investigation.investigation_id, run.run_id


def _completed_delegation(repo, investigation_id, run_id, *, result_hash="hash-1"):
    delegation = repo.admit_delegations(
        run_id,
        [DelegationSpec(question_ref="q-1", based_on_state_revision=1)],
    )[0]
    repo.start_delegation(delegation.delegation_id)
    repo.complete_delegation_with_result(
        delegation.delegation_id,
        result_version="specialist-result:v1",
        result={"summary": "s"},
        result_hash=result_hash,
    )
    return delegation.delegation_id


def _integration_kwargs(repo, investigation_id, delegation_id, result_hash="hash-1"):
    latest = repo.get_latest_working_state(investigation_id)
    return dict(
        expected_revision=latest.revision,
        expected_state_hash=latest.state_hash,
        operation_key=f"integ:{latest.revision}:{result_hash}",
        integration_policy_version=INTEGRATION_POLICY,
        decision_payload={"summary": "integrate"},
        decision_hash="decision-hash-1",
        delegation_integrations=[
            {"delegation_id": delegation_id, "result_hash": result_hash}
        ],
    )


# ---------------------------------------------------------------------------
# happy path + revision semantics (P4B-E18/E19/E20)
# ---------------------------------------------------------------------------


async def test_semantic_integration_increments_revision_exactly_once(env):
    repo, investigation_id, run_id = env
    delegation_id = _completed_delegation(repo, investigation_id, run_id)
    latest = repo.get_latest_working_state(investigation_id)
    kwargs = _integration_kwargs(repo, investigation_id, delegation_id)
    next_state = _typed_state("task-A", investigation_id).model_copy(
        update={
            "pending_proposal_refs": (f"{delegation_id}:c-1",),
        }
    )
    commit = repo.commit_agent_integration(
        investigation_id,
        **kwargs,
        new_state=working_state_to_json(next_state),
        run_id=run_id,
    )
    assert commit.status == "committed"
    assert commit.state_revision == latest.revision + 1
    assert repo.get_latest_working_state(investigation_id).revision == (
        latest.revision + 1
    )
    delegation = repo.get_delegation(delegation_id)
    assert delegation.integrated_at is not None
    assert delegation.integrated_revision == latest.revision + 1
    events = [
        t
        for t in repo.list_trajectory(investigation_id)
        if t.event_type
        == AgentTrajectoryEventType.supervisor_integration_committed
    ]
    assert len(events) == 1
    assert events[0].payload["semantic_changed"] is True


async def test_noop_integration_consumes_result_without_revision(env):
    repo, investigation_id, run_id = env
    delegation_id = _completed_delegation(repo, investigation_id, run_id)
    latest = repo.get_latest_working_state(investigation_id)
    commit = repo.commit_agent_integration(
        investigation_id,
        **_integration_kwargs(repo, investigation_id, delegation_id),
        run_id=run_id,
    )
    assert commit.status == "committed"
    assert commit.state_revision == latest.revision
    assert repo.get_latest_working_state(investigation_id).revision == latest.revision
    delegation = repo.get_delegation(delegation_id)
    assert delegation.integrated_at is not None
    assert delegation.integrated_revision == latest.revision


# ---------------------------------------------------------------------------
# idempotency (P4B-E22, §43)
# ---------------------------------------------------------------------------


async def test_semantic_replay_returns_original_revision(env):
    repo, investigation_id, run_id = env
    delegation_id = _completed_delegation(repo, investigation_id, run_id)
    kwargs = _integration_kwargs(repo, investigation_id, delegation_id)
    next_state = _typed_state("task-A", investigation_id)
    first = repo.commit_agent_integration(
        investigation_id, **kwargs,
        new_state=working_state_to_json(next_state), run_id=run_id,
    )
    second = repo.commit_agent_integration(
        investigation_id, **kwargs,
        new_state=working_state_to_json(next_state), run_id=run_id,
    )
    assert first.status == "committed"
    assert second.status == "replayed"
    assert second.state_revision == first.state_revision
    assert repo.get_latest_working_state(investigation_id).revision == (
        first.state_revision
    )


async def test_noop_replay_does_not_double_consume(env):
    repo, investigation_id, run_id = env
    delegation_id = _completed_delegation(repo, investigation_id, run_id)
    kwargs = _integration_kwargs(repo, investigation_id, delegation_id)
    first = repo.commit_agent_integration(
        investigation_id, **kwargs, run_id=run_id
    )
    second = repo.commit_agent_integration(
        investigation_id, **kwargs, run_id=run_id
    )
    assert first.status == "committed"
    assert second.status == "replayed"
    events = [
        t
        for t in repo.list_trajectory(investigation_id)
        if t.event_type
        == AgentTrajectoryEventType.supervisor_integration_committed
    ]
    assert len(events) == 1


# ---------------------------------------------------------------------------
# failure injection (§42): all-or-nothing
# ---------------------------------------------------------------------------


async def test_head_moved_rejects_without_consuming(env):
    repo, investigation_id, run_id = env
    delegation_id = _completed_delegation(repo, investigation_id, run_id)
    kwargs = _integration_kwargs(repo, investigation_id, delegation_id)
    kwargs["expected_revision"] = kwargs["expected_revision"] - 1
    with pytest.raises(AgentRuntimeConflictError):
        repo.commit_agent_integration(
            investigation_id, **kwargs, run_id=run_id
        )
    assert repo.get_delegation(delegation_id).integrated_at is None
    assert (
        repo.get_delegation_result(delegation_id).validation_status == "valid"
    )


async def test_result_hash_mismatch_rejects_without_integrating(env):
    repo, investigation_id, run_id = env
    delegation_id = _completed_delegation(repo, investigation_id, run_id)
    kwargs = _integration_kwargs(
        repo, investigation_id, delegation_id, result_hash="WRONG"
    )
    with pytest.raises(AgentRuntimeConflictError):
        repo.commit_agent_integration(
            investigation_id, **kwargs, run_id=run_id
        )
    assert repo.get_delegation(delegation_id).integrated_at is None


async def test_revision_insert_failure_rolls_back_audit(env, monkeypatch):
    repo, investigation_id, run_id = env
    delegation_id = _completed_delegation(repo, investigation_id, run_id)
    kwargs = _integration_kwargs(repo, investigation_id, delegation_id)

    import httpserver.services.investigation.agent_runtime as runtime_module

    original = runtime_module.canonical_state_json

    def exploding_canonical(state):
        # explode only when the new working state revision is serialized
        if isinstance(state, dict) and state.get("pending_proposal_refs"):
            raise RuntimeError("disk full during revision insert")
        return original(state)

    monkeypatch.setattr(
        runtime_module, "canonical_state_json", exploding_canonical
    )
    next_state = _typed_state("task-A", investigation_id).model_copy(
        update={"pending_proposal_refs": ("x:y",)}
    )
    with pytest.raises(RuntimeError):
        repo.commit_agent_integration(
            investigation_id, **kwargs,
            new_state=working_state_to_json(next_state), run_id=run_id,
        )
    monkeypatch.setattr(runtime_module, "canonical_state_json", original)
    # nothing partial: no audit, no revision, no integrated_at
    events = [
        t
        for t in repo.list_trajectory(investigation_id)
        if t.event_type
        == AgentTrajectoryEventType.supervisor_integration_committed
    ]
    assert events == []
    assert repo.get_latest_working_state(investigation_id).revision == 1
    assert repo.get_delegation(delegation_id).integrated_at is None


async def test_state_head_conflict_keeps_results_unintegrated(env):
    """§41: policy-level rejection is simulated here as a head conflict —
    results remain unintegrated and can be re-integrated after re-plan."""
    repo, investigation_id, run_id = env
    delegation_id = _completed_delegation(repo, investigation_id, run_id)
    kwargs = _integration_kwargs(repo, investigation_id, delegation_id)
    kwargs["expected_state_hash"] = "drifted"
    with pytest.raises(AgentRuntimeConflictError):
        repo.commit_agent_integration(
            investigation_id, **kwargs, run_id=run_id
        )
    assert repo.get_delegation(delegation_id).integrated_at is None


# ---------------------------------------------------------------------------
# guarded completed -> stale (P4B-E11/E12 support, §10.3)
# ---------------------------------------------------------------------------


async def test_mark_stale_requires_completed_unintegrated_and_matching_hash(env):
    repo, investigation_id, run_id = env
    delegation_id = _completed_delegation(
        repo, investigation_id, run_id, result_hash="hash-stale"
    )
    with pytest.raises(AgentRuntimeConflictError):
        repo.mark_completed_delegation_stale(
            delegation_id, expected_result_hash="WRONG",
            reason_codes=("MERGE_STALE_QUESTION_INACTIVE",),
        )
    delegation = repo.mark_completed_delegation_stale(
        delegation_id,
        expected_result_hash="hash-stale",
        reason_codes=("MERGE_STALE_QUESTION_INACTIVE",),
    )
    assert delegation.status.value == "stale"
    # audit row preserved, result can never integrate afterwards
    assert repo.get_delegation_result(delegation_id) is not None
    with pytest.raises(AgentRuntimeConflictError):
        repo.mark_delegation_integrated(
            delegation_id, integrated_revision=1
        )
    events = [
        t
        for t in repo.list_trajectory(investigation_id)
        if t.event_type == AgentTrajectoryEventType.delegation_stale
    ]
    assert events and events[0].payload["reason_codes"] == [
        "MERGE_STALE_QUESTION_INACTIVE"
    ]
