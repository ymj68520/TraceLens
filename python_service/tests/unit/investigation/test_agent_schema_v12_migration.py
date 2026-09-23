"""P4B §35 minimal v12 migration tests: supervisor audit trajectory events
plus the sanctioned completed->stale delegation edge."""

import sqlite3

import pytest

from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
)
from httpserver.services.investigation.repository import (
    SUPPORTED_SCHEMA_VERSION,
    InvestigationRepository,
)

pytestmark = pytest.mark.migration_matrix


def _user_version(path) -> int:
    return sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0]


def test_fresh_db_initializes_v12(tmp_path):
    db = tmp_path / "investigation.db"
    InvestigationRepository(db, "A")
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION == 14


def _seed(tmp_path):
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        working_state_to_json,
    )

    db = tmp_path / "investigation.db"
    store = InvestigationRepository(db, "task-A")
    repo = AgentRuntimeRepository(store)
    investigation_id = "inv-" + "b" * 8
    state = AgentWorkingStateV1(
        task_id="task-A", investigation_id=investigation_id, objective="v12"
    )
    investigation, _rev = repo.create_investigation(
        working_state_to_json(state), investigation_id=investigation_id
    )
    return repo, investigation.investigation_id


def test_v11_store_migrates_to_v12_with_widened_guards(tmp_path):
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        working_state_to_json,
    )
    from httpserver.services.investigation.agent_runtime import DelegationSpec

    db = tmp_path / "investigation.db"
    repo, investigation_id = _seed(tmp_path)
    run = repo.start_run(investigation_id)
    repo.mark_run_running(run.run_id)
    delegation = repo.admit_delegations(
        run.run_id, [DelegationSpec(question_ref="q-1")]
    )[0]

    # hand-downgrade to a genuine v11 store: old trajectory CHECK, old
    # delegation guards (drop the widened trigger definitions explicitly —
    # exactly what the migration will reinstall)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("DROP TRIGGER IF EXISTS trg_agent_delegation_no_terminal_update")
    conn.execute("DROP TRIGGER IF EXISTS trg_agent_delegation_state_fields")
    conn.execute("DROP TRIGGER IF EXISTS trg_agent_delegation_legal_transition")
    conn.execute("DROP TABLE agent_trajectory_events")
    conn.execute(
        """
        CREATE TABLE agent_trajectory_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            investigation_id TEXT NOT NULL,
            run_id TEXT,
            delegation_id TEXT,
            event_type TEXT NOT NULL CHECK(event_type IN (
                'investigation_created','run_admitted','run_started','run_completed',
                'run_failed','run_cancelled','delegation_admitted','delegation_started',
                'delegation_completed','delegation_failed','delegation_cancelled',
                'delegation_stale','working_state_committed','runtime_recovered',
                'investigation_paused','investigation_completed','investigation_cancelled',
                'attention_compiled','transition_decision_validated',
                'transition_decision_rejected','working_state_integrated',
                'no_progress_detected','finalization_requested','finalization_denied',
                'finalization_stale','finalization_completed',
                'tool_observation_recorded')),
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(task_id, event_id)
        )
        """
    )
    conn.execute("PRAGMA user_version = 11")
    conn.commit()
    conn.close()

    reopened = AgentRuntimeRepository(InvestigationRepository(db, "task-A"))
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION

    # the widened guards were reinstalled by the migration: the full
    # lifecycle runs and completed->stale is the one sanctioned terminal
    # edge, executed through the guarded primitive
    repo2 = reopened
    repo2.start_delegation(delegation.delegation_id)
    repo2.complete_delegation_with_result(
        delegation.delegation_id,
        result_version="specialist-result:v1",
        result={"summary": "s2"},
        result_hash="hash-v12b",
    )
    stale_delegation = repo2.mark_completed_delegation_stale(
        delegation.delegation_id,
        expected_result_hash="hash-v12b",
        reason_codes=("MERGE_STALE_QUESTION_INACTIVE",),
    )
    assert stale_delegation.status.value == "stale"

    # new supervisor audit events accepted
    event = repo2.append_trajectory(
        investigation_id,
        AgentTrajectoryEventType.supervisor_plan_decided,
        payload={"decision_hash": "h"},
    )
    assert event.event_type.value == "supervisor_plan_decided"
    with pytest.raises(ValueError):
        repo2.append_trajectory(
            investigation_id, "made_up_v12_event", payload={}
        )
