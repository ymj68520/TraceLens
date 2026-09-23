"""Phase 1 (Agent Architecture v0) runtime persistence foundation tests.

Covers the frozen P1 semantics on the task-owned investigation.db (v8/v9):

- schema: fresh init, v7 -> v8 migration (additive, data preserved),
  idempotent reopen, unsupported future version fail closed
- Investigation / Agent Run / Delegation lifecycle state machines
- one-active-run invariant enforced at the DB boundary (partial unique index)
- Working State revisions: sequential, immutable, hash chained, optimistic
  conflict fail closed, idempotent operation keys
- Trajectory: INSERT-only Action Trace with deterministic ordering
- Tool Observation storage boundary (immutable rows)
- restart recovery reaching deterministic terminal/pause states
- task isolation / cross-task lookups / vanished-store fail closed
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from httpserver.services.evidence import EvidenceStoreError
from httpserver.services.investigation import (
    AgentInvestigationStatus,
    AgentRuntimeConflictError,
    AgentRuntimeRepository,
    AgentRunStatus,
    DelegationSpec,
    DelegationStatus,
    InvestigationPauseReason,
    InvestigationRepository,
    RunStopReason,
    SUPPORTED_SCHEMA_VERSION,
    canonical_state_json,
    state_hash_of,
)
from httpserver.services.investigation.agent_runtime import (
    WorkingStateRevisionConflictError,
)


# ---------- fixtures / helpers ----------

@pytest.fixture()
def store(tmp_path) -> InvestigationRepository:
    return InvestigationRepository(tmp_path / "investigation.db", "A")


@pytest.fixture()
def agent(store) -> AgentRuntimeRepository:
    return AgentRuntimeRepository(store)


def _user_version(path) -> int:
    return sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0]


def _active_investigation(agent: AgentRuntimeRepository):
    investigation, revision = agent.create_investigation({"objective": "demo"})
    run = agent.start_run(investigation.investigation_id)
    agent.mark_run_running(run.run_id)
    return investigation, revision, run


def _expect_integrity_error(agent: AgentRuntimeRepository, sql: str, params: list):
    """A raw rejected write must abort and leave no open transaction."""
    with closing(agent._connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, params)
        conn.rollback()


# ---------- schema ----------

def test_fresh_db_initializes_current_version_with_agent_tables(tmp_path):
    db = tmp_path / "investigation.db"
    InvestigationRepository(db, "A")
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION == 15
    conn = sqlite3.connect(db)
    for table in (
        "agent_investigations", "agent_runs", "agent_working_state_revisions",
        "agent_delegations", "agent_trajectory_events", "agent_tool_observations",
    ):
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]
        ).fetchone() is not None
    conn.close()


def test_v7_store_migrates_additively_and_preserves_canonical_data(tmp_path):
    db = tmp_path / "investigation.db"
    repo = InvestigationRepository(db, "A")
    event = repo.create_event("narrative")

    # Simulate a true v7 store: no agent objects, user_version = 7.
    conn = sqlite3.connect(db)
    for table in (
        "agent_tool_observations", "agent_trajectory_events",
        "agent_delegations", "agent_working_state_revisions",
        "agent_runs", "agent_investigations",
    ):
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 7")
    conn.commit()
    conn.close()

    reopened = InvestigationRepository(db, "A")
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION
    assert reopened.get_event(event.event_id).title == "narrative"
    agent = AgentRuntimeRepository(reopened)
    investigation, revision = agent.create_investigation({"objective": "post-migration"})
    assert revision.revision == 1


def test_migration_is_idempotent_on_reopen(tmp_path):
    db = tmp_path / "investigation.db"
    first = InvestigationRepository(db, "A")
    agent = AgentRuntimeRepository(first)
    investigation, _ = agent.create_investigation({"objective": "keep"})

    InvestigationRepository(db, "A")          # version == current branch
    again = InvestigationRepository(db, "A")  # reopen twice
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION
    assert AgentRuntimeRepository(again).get_investigation(
        investigation.investigation_id
    ) is not None


def test_unsupported_future_schema_fails_closed(tmp_path):
    db = tmp_path / "investigation.db"
    db.write_bytes(b"")
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(EvidenceStoreError):
        InvestigationRepository(db, "A")
    with pytest.raises(EvidenceStoreError):
        InvestigationRepository.open_existing(db, "A")


# ---------- investigation lifecycle ----------

def test_investigation_full_legal_lifecycle(agent):
    investigation, revision = agent.create_investigation({"objective": "demo"})
    assert investigation.status is AgentInvestigationStatus.ready

    run = agent.start_run(investigation.investigation_id)
    assert run.status is AgentRunStatus.queued
    assert agent.get_investigation(
        investigation.investigation_id
    ).status is AgentInvestigationStatus.active

    agent.mark_run_running(run.run_id)
    paused = agent.pause_investigation(
        investigation.investigation_id, reason=InvestigationPauseReason.user_paused
    )
    assert paused.status is AgentInvestigationStatus.paused
    assert paused.pause_reason is InvestigationPauseReason.user_paused
    # pausing cancels the active run cooperatively
    assert agent.get_run(run.run_id).status is AgentRunStatus.cancelled
    assert agent.get_run(run.run_id).stop_reason is RunStopReason.user_paused

    resumed_run = agent.start_run(investigation.investigation_id)
    assert agent.get_investigation(
        investigation.investigation_id
    ).status is AgentInvestigationStatus.active
    agent.mark_run_running(resumed_run.run_id)
    agent.finish_run(resumed_run.run_id, stop_reason=RunStopReason.finalized)
    completed = agent.complete_investigation(investigation.investigation_id)
    assert completed.status is AgentInvestigationStatus.completed
    assert completed.completed_at is not None


def test_completed_investigation_cannot_reopen(agent):
    investigation, _, run = _active_investigation(agent)
    agent.finish_run(run.run_id, stop_reason=RunStopReason.finalized)
    agent.complete_investigation(investigation.investigation_id)

    with pytest.raises(AgentRuntimeConflictError):
        agent.start_run(investigation.investigation_id)
    with pytest.raises(AgentRuntimeConflictError):
        agent.complete_investigation(investigation.investigation_id)
    with pytest.raises(AgentRuntimeConflictError):
        agent.cancel_investigation(investigation.investigation_id)
    # even raw SQL cannot flip a terminal investigation (DB backstop)
    _expect_integrity_error(
        agent,
        "UPDATE agent_investigations SET status = 'active' "
        "WHERE task_id = ? AND investigation_id = ?",
        ["A", investigation.investigation_id],
    )


def test_cancelled_investigation_is_terminal(agent):
    investigation, _ = agent.create_investigation({"objective": "demo"})
    cancelled = agent.cancel_investigation(investigation.investigation_id)
    assert cancelled.status is AgentInvestigationStatus.cancelled
    assert cancelled.cancelled_at is not None
    with pytest.raises(AgentRuntimeConflictError):
        agent.start_run(investigation.investigation_id)
    with pytest.raises(AgentRuntimeConflictError):
        agent.cancel_investigation(investigation.investigation_id)


def test_complete_requires_active_and_no_active_run(agent):
    investigation, _ = agent.create_investigation({"objective": "demo"})
    with pytest.raises(AgentRuntimeConflictError):
        agent.complete_investigation(investigation.investigation_id)  # still ready
    agent.start_run(investigation.investigation_id)
    with pytest.raises(AgentRuntimeConflictError):
        agent.complete_investigation(investigation.investigation_id)  # active run


# ---------- run lifecycle ----------

def test_single_active_run_invariant_at_db_boundary(agent, store):
    investigation, _ = agent.create_investigation({"objective": "demo"})
    agent.start_run(investigation.investigation_id)

    # application check
    with pytest.raises(AgentRuntimeConflictError):
        agent.start_run(investigation.investigation_id)
    # DB boundary: even a raw INSERT cannot create a second active run
    _expect_integrity_error(
        agent,
        "INSERT INTO agent_runs (run_id, task_id, investigation_id, status, "
        "created_at) VALUES ('run_x', 'A', ?, 'queued', '2026-01-01')",
        [investigation.investigation_id],
    )


def test_run_admission_failure_leaves_no_rows(agent):
    investigation, _ = agent.create_investigation({"objective": "demo"})
    agent.cancel_investigation(investigation.investigation_id)
    with pytest.raises(AgentRuntimeConflictError):
        agent.start_run(investigation.investigation_id)
    assert agent.list_runs(investigation.investigation_id) == []
    with sqlite3.connect(agent._repo.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 0


def test_run_stop_reason_persistence(agent):
    investigation, _, run = _active_investigation(agent)
    finished = agent.finish_run(run.run_id, stop_reason=RunStopReason.budget_exhausted)
    assert finished.status is AgentRunStatus.completed
    assert finished.stop_reason is RunStopReason.budget_exhausted

    investigation2, _, run2 = _active_investigation(agent)
    failed = agent.fail_run(
        run2.run_id, error_code="llm_timeout",
        error_message="LLM timed out", stop_reason=RunStopReason.internal_failure,
    )
    assert failed.status is AgentRunStatus.failed
    assert failed.stop_reason is RunStopReason.internal_failure
    assert failed.error_code == "llm_timeout"

    investigation3, _, run3 = _active_investigation(agent)
    cancelled = agent.cancel_run(run3.run_id, stop_reason=RunStopReason.no_progress)
    assert cancelled.status is AgentRunStatus.cancelled
    assert cancelled.stop_reason is RunStopReason.no_progress

    # unknown stop reasons are rejected by the enum, not silently persisted
    with pytest.raises(ValueError):
        RunStopReason("made_up")
    investigation4, _, run4 = _active_investigation(agent)
    with pytest.raises(ValueError):
        agent.finish_run(run4.run_id, stop_reason="made_up")


def test_run_transitions_are_legal_only(agent):
    investigation, _ = agent.create_investigation({"objective": "demo"})
    run = agent.start_run(investigation.investigation_id)
    with pytest.raises(AgentRuntimeConflictError):
        agent.finish_run(run.run_id, stop_reason=RunStopReason.finalized)  # queued
    agent.mark_run_running(run.run_id)
    with pytest.raises(AgentRuntimeConflictError):
        agent.mark_run_running(run.run_id)  # already running
    agent.finish_run(run.run_id, stop_reason=RunStopReason.finalized)
    with pytest.raises(AgentRuntimeConflictError):
        agent.fail_run(run.run_id, error_code="x", error_message="y")  # terminal


# ---------- delegation lifecycle ----------

def test_delegation_admission_and_idempotent_replay(agent):
    investigation, revision, run = _active_investigation(agent)
    specs = [
        DelegationSpec(
            question_ref="q-1", based_on_state_revision=revision.revision,
            context_hash="ctx-1", idempotency_key="d-key-1",
        ),
        DelegationSpec(question_ref="q-2"),
    ]
    admitted = agent.admit_delegations(run.run_id, specs)
    assert [d.status for d in admitted] == [DelegationStatus.queued] * 2
    assert admitted[0].based_on_state_revision == revision.revision

    replay = agent.admit_delegations(run.run_id, specs[:1])
    assert replay[0].delegation_id == admitted[0].delegation_id
    assert len(agent.list_delegations(run.run_id)) == 2


def test_delegation_admission_requires_active_run(agent):
    investigation, _ = agent.create_investigation({"objective": "demo"})
    run = agent.start_run(investigation.investigation_id)
    agent.cancel_run(run.run_id)
    with pytest.raises(AgentRuntimeConflictError):
        agent.admit_delegations(run.run_id, [DelegationSpec(question_ref="q")])


def test_delegation_admission_is_atomic_on_duplicate_key(agent):
    investigation, _, run = _active_investigation(agent)
    # same key bound to a different request fails closed and rolls back
    specs = [
        DelegationSpec(question_ref="q-1", idempotency_key="dup"),
        DelegationSpec(question_ref="q-2", idempotency_key="dup"),
    ]
    with pytest.raises(AgentRuntimeConflictError):
        agent.admit_delegations(run.run_id, specs)
    assert agent.list_delegations(run.run_id) == []

    # retrying the identical request replays the same delegation
    (delegation,) = agent.admit_delegations(
        run.run_id, [DelegationSpec(question_ref="q-1", idempotency_key="dup")]
    )
    replay = agent.admit_delegations(
        run.run_id, [DelegationSpec(question_ref="q-1", idempotency_key="dup")]
    )
    assert replay[0].delegation_id == delegation.delegation_id
    assert len(agent.list_delegations(run.run_id)) == 1


def test_delegation_terminal_transitions(agent):
    investigation, _, run = _active_investigation(agent)
    d1, d2, d3 = agent.admit_delegations(
        run.run_id,
        [DelegationSpec(question_ref="q-1"), DelegationSpec(question_ref="q-2"),
         DelegationSpec(question_ref="q-3")],
    )
    agent.start_delegation(d1.delegation_id)
    completed = agent.transition_delegation_terminal(
        d1.delegation_id, DelegationStatus.completed
    )
    assert completed.status is DelegationStatus.completed
    with pytest.raises(AgentRuntimeConflictError):
        agent.transition_delegation_terminal(
            d1.delegation_id, DelegationStatus.completed
        )

    with pytest.raises(ValueError):
        agent.transition_delegation_terminal(
            d2.delegation_id, DelegationStatus.failed  # missing failure_code
        )
    failed = agent.transition_delegation_terminal(
        d2.delegation_id, DelegationStatus.failed,
        failure_code="llm_timeout", failure_message="timed out",
    )
    assert failed.failure_code == "llm_timeout"
    assert failed.failed_at is not None

    # stale is a terminal audit state: kept, never integrated
    stale = agent.transition_delegation_terminal(
        d3.delegation_id, DelegationStatus.stale
    )
    assert stale.status is DelegationStatus.stale
    assert stale.stale_at is not None
    with pytest.raises(AgentRuntimeConflictError):
        agent.mark_delegation_integrated(d3.delegation_id, integrated_revision=1)


def test_delegation_integration_bookkeeping_is_one_shot(agent):
    investigation, revision, run = _active_investigation(agent)
    (delegation,) = agent.admit_delegations(
        run.run_id, [DelegationSpec(question_ref="q")]
    )
    agent.start_delegation(delegation.delegation_id)
    agent.transition_delegation_terminal(
        delegation.delegation_id, DelegationStatus.completed
    )
    rev2 = agent.commit_working_state(
        investigation.investigation_id, {"objective": "demo", "n": 1},
        expected_revision=revision.revision,
    )
    integrated = agent.mark_delegation_integrated(
        delegation.delegation_id, integrated_revision=rev2.revision
    )
    assert integrated.integrated_at is not None
    assert integrated.integrated_revision == rev2.revision

    # the bookkeeping write is allowed exactly once (DB trigger backstop)
    _expect_integrity_error(
        agent,
        "UPDATE agent_delegations SET integrated_revision = 99 "
        "WHERE task_id = ? AND delegation_id = ?",
        ["A", delegation.delegation_id],
    )
    # and it must reference an existing revision (composite FK)
    (delegation2,) = agent.admit_delegations(
        run.run_id, [DelegationSpec(question_ref="q-9")]
    )
    agent.start_delegation(delegation2.delegation_id)
    agent.transition_delegation_terminal(
        delegation2.delegation_id, DelegationStatus.completed
    )
    with pytest.raises(ValueError):
        agent.mark_delegation_integrated(
            delegation2.delegation_id, integrated_revision=999
        )


def test_cancel_requested_semantics(agent):
    investigation, _, run = _active_investigation(agent)
    d1, d2 = agent.admit_delegations(
        run.run_id, [DelegationSpec(question_ref="q-1"), DelegationSpec(question_ref="q-2")]
    )
    requested = agent.request_delegation_cancel(d1.delegation_id)
    assert requested.cancel_requested_at is not None
    # idempotent
    again = agent.request_delegation_cancel(d1.delegation_id)
    assert again.cancel_requested_at == requested.cancel_requested_at
    # cancel_requested does not block an explicit terminal transition
    cancelled = agent.transition_delegation_terminal(
        d1.delegation_id, DelegationStatus.cancelled
    )
    assert cancelled.cancel_requested_at is not None
    assert cancelled.status is DelegationStatus.cancelled
    # d2 stays queued without a cancel request
    assert agent.get_delegation(d2.delegation_id).cancel_requested_at is None


def test_pause_requests_delegation_cancellation(agent):
    investigation, _, run = _active_investigation(agent)
    (delegation,) = agent.admit_delegations(
        run.run_id, [DelegationSpec(question_ref="q")]
    )
    agent.pause_investigation(
        investigation.investigation_id, reason=InvestigationPauseReason.user_paused
    )
    assert agent.get_delegation(delegation.delegation_id).cancel_requested_at \
        is not None
    # cooperative: the executor still owns the terminal transition
    assert agent.get_delegation(delegation.delegation_id).status \
        is DelegationStatus.queued


# ---------- working state revisions ----------

def test_working_state_revisions_monotonic_and_hash_chained(agent):
    investigation, rev1 = agent.create_investigation({"objective": "a"})
    assert rev1.revision == 1  # P1 convention: initial revision is 1
    assert rev1.previous_state_hash is None
    assert rev1.state_hash == state_hash_of({"objective": "a"})

    rev2 = agent.commit_working_state(
        investigation.investigation_id, {"objective": "a", "n": 2},
        expected_revision=rev1.revision,
    )
    assert rev2.revision == 2
    assert rev2.previous_state_hash == rev1.state_hash
    rev3 = agent.commit_working_state(
        investigation.investigation_id, {"objective": "a", "n": 3},
        expected_revision=rev2.revision,
    )
    assert rev3.revision == 3
    assert rev3.previous_state_hash == rev2.state_hash
    assert agent.get_latest_working_state(
        investigation.investigation_id
    ).revision == 3


def test_state_hash_is_deterministic():
    assert state_hash_of({"a": 1, "b": [1, 2]}) == state_hash_of({"b": [1, 2], "a": 1})
    assert canonical_state_json({"a": 1}) == '{"a":1}'


def test_optimistic_revision_conflict_fails_closed(agent):
    investigation, rev1 = agent.create_investigation({"objective": "a"})
    agent.commit_working_state(
        investigation.investigation_id, {"objective": "a", "n": 2},
        expected_revision=rev1.revision,
    )
    with pytest.raises(WorkingStateRevisionConflictError):
        agent.commit_working_state(
            investigation.investigation_id, {"objective": "stale"},
            expected_revision=rev1.revision,  # stale expectation
        )
    with pytest.raises(WorkingStateRevisionConflictError):
        agent.commit_working_state(
            investigation.investigation_id, {"objective": "skip"},
            expected_revision=99,
        )
    # nothing was written by the rejected commits
    assert agent.get_latest_working_state(investigation.investigation_id).revision == 2


def test_historical_revision_immutable_at_db_level(agent):
    investigation, rev1 = agent.create_investigation({"objective": "a"})
    _expect_integrity_error(
        agent,
        "UPDATE agent_working_state_revisions SET state_json = '{}' "
        "WHERE task_id = ? AND investigation_id = ? AND revision = 1",
        ["A", investigation.investigation_id],
    )
    _expect_integrity_error(
        agent,
        "DELETE FROM agent_working_state_revisions "
        "WHERE task_id = ? AND investigation_id = ?",
        ["A", investigation.investigation_id],
    )


def test_revision_triggers_enforce_sequence_and_chain(agent):
    investigation, rev1 = agent.create_investigation({"objective": "a"})
    # skipping revision 2 is rejected
    _expect_integrity_error(
        agent,
        "INSERT INTO agent_working_state_revisions "
        "(task_id, investigation_id, revision, state_json, state_hash, "
        " previous_state_hash, created_at) VALUES (?, ?, 7, '{}', 'h', NULL, 't')",
        ["A", investigation.investigation_id],
    )
    # a broken previous hash is rejected
    _expect_integrity_error(
        agent,
        "INSERT INTO agent_working_state_revisions "
        "(task_id, investigation_id, revision, state_json, state_hash, "
        " previous_state_hash, created_at) VALUES (?, ?, 2, '{}', 'h2', 'wrong', 't')",
        ["A", investigation.investigation_id],
    )


def test_operation_key_idempotent_commit(agent):
    investigation, rev1 = agent.create_investigation({"objective": "a"})
    state = {"objective": "a", "integrated": True}
    first = agent.commit_working_state(
        investigation.investigation_id, state,
        expected_revision=rev1.revision, operation_key="op-1",
    )
    replay = agent.commit_working_state(
        investigation.investigation_id, state,
        expected_revision=rev1.revision, operation_key="op-1",
    )
    assert replay.revision == first.revision
    assert agent.get_latest_working_state(
        investigation.investigation_id
    ).revision == 2

    with pytest.raises(WorkingStateRevisionConflictError):
        agent.commit_working_state(
            investigation.investigation_id, {"objective": "different"},
            expected_revision=rev1.revision, operation_key="op-1",
        )


# ---------- trajectory ----------

def test_trajectory_is_append_only(agent):
    investigation, _ = agent.create_investigation({"objective": "a"})
    agent.append_trajectory(
        investigation.investigation_id, "investigation_created", payload={}
    )
    _expect_integrity_error(
        agent,
        "UPDATE agent_trajectory_events SET payload_json = '{}' WHERE task_id = ?",
        ["A"],
    )
    _expect_integrity_error(
        agent,
        "DELETE FROM agent_trajectory_events WHERE task_id = ?",
        ["A"],
    )


def test_trajectory_deterministic_ordering(agent):
    investigation, _, run = _active_investigation(agent)
    (delegation,) = agent.admit_delegations(
        run.run_id, [DelegationSpec(question_ref="q")]
    )
    agent.start_delegation(delegation.delegation_id)
    agent.transition_delegation_terminal(
        delegation.delegation_id, DelegationStatus.completed
    )

    first = agent.list_trajectory(investigation.investigation_id)
    second = agent.list_trajectory(investigation.investigation_id)
    assert [e.seq for e in first] == [e.seq for e in second]
    assert [e.seq for e in first] == sorted(e.seq for e in first)
    types = [e.event_type.value for e in first]
    assert types == [
        "investigation_created", "run_admitted", "run_started",
        "delegation_admitted", "delegation_started", "delegation_completed",
    ]
    # no model-private reasoning is stored: payloads are structured dicts
    assert all(isinstance(e.payload, dict) for e in first)


def test_trajectory_validates_scope(agent):
    investigation, _ = agent.create_investigation({"objective": "a"})
    run = agent.start_run(investigation.investigation_id)
    other, _ = agent.create_investigation({"objective": "b"})
    with pytest.raises(ValueError):
        agent.append_trajectory(
            other.investigation_id, "run_admitted", run_id=run.run_id
        )
    with pytest.raises(ValueError):
        agent.append_trajectory("inv_missing", "run_admitted")


# ---------- tool observations ----------

def test_tool_observation_storage_boundary(agent):
    investigation, _, run = _active_investigation(agent)
    observation = agent.append_tool_observation(
        investigation.investigation_id,
        tool_id="search_evidence", summary="two hits",
        result={"rows": [1, 2]}, evidence_refs=("file:/a", "file:/b"),
        run_id=run.run_id, truncated=False,
    )
    assert observation.result_count == 2
    assert observation.evidence_refs == ("file:/a", "file:/b")
    assert agent.list_tool_observations(investigation.investigation_id) == [observation]
    _expect_integrity_error(
        agent,
        "UPDATE agent_tool_observations SET summary = 'x' WHERE task_id = ?",
        ["A"],
    )


# ---------- restart recovery ----------

def test_runtime_restart_recovery_reaches_deterministic_states(agent):
    # active investigation with running run + running delegation
    investigation1, rev1, run1 = _active_investigation(agent)
    (d_running,) = agent.admit_delegations(
        run1.run_id, [DelegationSpec(question_ref="q-running")]
    )
    agent.start_delegation(d_running.delegation_id)
    # a ready investigation with a queued run
    investigation2, _ = agent.create_investigation({"objective": "b"})
    run2 = agent.start_run(investigation2.investigation_id)

    summary = agent.recover_interrupted_agent_runtime()
    assert summary == {
        "runs_failed": 2, "delegations_failed": 1, "investigations_paused": 2,
        "obligations_expired": 0,
    }

    failed_run = agent.get_run(run1.run_id)
    assert failed_run.status is AgentRunStatus.failed
    assert failed_run.stop_reason is RunStopReason.runtime_restart
    assert failed_run.error_code == "runtime_restart"
    assert agent.get_run(run2.run_id).stop_reason is RunStopReason.runtime_restart

    failed_delegation = agent.get_delegation(d_running.delegation_id)
    assert failed_delegation.status is DelegationStatus.failed
    assert failed_delegation.failure_code == "runtime_restart"

    paused = agent.get_investigation(investigation1.investigation_id)
    assert paused.status is AgentInvestigationStatus.paused
    assert paused.pause_reason is InvestigationPauseReason.runtime_restart
    # every active investigation pauses deterministically -- including one
    # that only had a queued run admitted
    assert agent.get_investigation(
        investigation2.investigation_id
    ).status is AgentInvestigationStatus.paused
    assert agent.get_investigation(
        investigation2.investigation_id
    ).pause_reason is InvestigationPauseReason.runtime_restart

    # last committed working state survives untouched
    latest = agent.get_latest_working_state(investigation1.investigation_id)
    assert latest.revision == rev1.revision
    assert latest.state == {"objective": "demo"}
    assert latest.state_hash == rev1.state_hash

    # recovery is idempotent
    assert agent.recover_interrupted_agent_runtime() == {
        "runs_failed": 0, "delegations_failed": 0, "investigations_paused": 0,
        "obligations_expired": 0,
    }

    # trajectory records the recovery action trace deterministically
    types = [
        e.event_type.value
        for e in agent.list_trajectory(investigation1.investigation_id)
    ]
    assert types == [
        "investigation_created", "run_admitted", "run_started",
        "delegation_admitted", "delegation_started",
        "run_failed", "delegation_failed", "investigation_paused",
        "runtime_recovered",
    ]

    # a recovered investigation resumes with a fresh run from the same state
    agent.start_run(investigation1.investigation_id)
    assert agent.get_investigation(
        investigation1.investigation_id
    ).status is AgentInvestigationStatus.active
    assert agent.get_latest_working_state(
        investigation1.investigation_id
    ).revision == rev1.revision


# ---------- task isolation / boundary ----------

def test_cross_task_lookup_is_rejected(store, tmp_path):
    agent_a = AgentRuntimeRepository(store)
    investigation, _ = agent_a.create_investigation({"objective": "a"})

    other_store = InvestigationRepository(tmp_path / "other.db", "B")
    agent_b = AgentRuntimeRepository(other_store)
    assert agent_b.get_investigation(investigation.investigation_id) is None
    with pytest.raises(ValueError):
        agent_b.start_run(investigation.investigation_id)
    with pytest.raises(ValueError):
        agent_b.commit_working_state(
            investigation.investigation_id, {"x": 1}, expected_revision=1
        )
    assert agent_b.list_trajectory(investigation.investigation_id) == []

    # a repository bound to the wrong task id cannot see the rows even when
    # pointed at the same store file
    wrong_binding = AgentRuntimeRepository(
        InvestigationRepository(store.db_path, "B")
    )
    assert wrong_binding.get_investigation(investigation.investigation_id) is None


def test_agent_runtime_writes_cannot_resurrect_vanished_store(tmp_path):
    db = tmp_path / "investigation.db"
    repo = InvestigationRepository(db, "A")
    agent = AgentRuntimeRepository(repo)
    agent.create_investigation({"objective": "a"})
    del repo, agent

    Path(db).unlink()
    with pytest.raises(EvidenceStoreError):
        InvestigationRepository.open_existing(db, "A")
