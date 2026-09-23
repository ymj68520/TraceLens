"""P5A §49/§59 schema v13 migration tests: the six append-only grounding-
foundation tables, the three P5A trajectory audit events, and provenance
durability across restarts."""

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

_P5A_TABLES = (
    "agent_entity_occurrences",
    "agent_correlation_candidates",
    "agent_claim_proposals",
    "agent_grounding_results",
    "agent_evidence_support_bundles",
    "agent_delegation_evidence_scopes",
)


def _user_version(path) -> int:
    return sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0]


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
        task_id="task-A", investigation_id=investigation_id, objective="v13"
    )
    investigation, _rev = repo.create_investigation(
        working_state_to_json(state), investigation_id=investigation_id
    )
    return repo, investigation.investigation_id, db


def test_fresh_db_initializes_v13_with_p5a_tables(tmp_path):
    db = tmp_path / "investigation.db"
    InvestigationRepository(db, "A")
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION == 15

    conn = sqlite3.connect(db)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for table in _P5A_TABLES:
            assert table in tables
        triggers = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        for table in _P5A_TABLES:
            assert f"trg_{table}_no_update" in triggers
            assert f"trg_{table}_no_delete" in triggers
    finally:
        conn.close()


def test_p5a_tables_are_append_only(tmp_path):
    _repo, investigation_id, db = _seed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            "INSERT INTO agent_entity_occurrences "
            "(occurrence_id, task_id, investigation_id, source_scope_id, "
            " evidence_ref, entity_type, raw_value, normalized_value, "
            " match_key, namespace, role, source_field, extraction_method, "
            " verification_status, input_hash, created_at) "
            "VALUES ('x','task-A',?,'s','file:C/a','file_hash','a','a',"
            "'k','ns','role','f','m','verified','h','2026-01-01')",
            [investigation_id],
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE agent_entity_occurrences SET raw_value = 'b'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM agent_entity_occurrences")
    finally:
        conn.rollback()
        conn.close()


def test_v13_trajectory_events_accepted(tmp_path):
    repo, investigation_id, db = _seed(tmp_path)
    for event_type in (
        AgentTrajectoryEventType.entity_occurrences_recorded,
        AgentTrajectoryEventType.correlation_candidates_recorded,
        AgentTrajectoryEventType.claim_grounding_recorded,
    ):
        event = repo.append_trajectory(investigation_id, event_type, payload={})
        assert event.event_type.value == event_type.value
    with pytest.raises(ValueError):
        repo.append_trajectory(
            investigation_id, "made_up_v13_event", payload={}
        )


def test_v12_store_migrates_to_v13_preserving_p1_p4_data(tmp_path):
    """Hand-downgrade a live store to v12 (drop P5A tables, restore the v12
    trajectory enum) with P1-P4 rows present; reopening must migrate and
    preserve every durable row."""
    repo, investigation_id, db = _seed(tmp_path)

    # durable pre-migration state: one revision + one trajectory event
    events_before = repo.list_trajectory(investigation_id)
    assert events_before

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN IMMEDIATE")
    for table in _P5A_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    # a genuine v12 store still carries its trajectory rows: rename, rebuild
    # the v12-shaped table, copy the rows in, drop the backup
    conn.execute(
        "ALTER TABLE agent_trajectory_events "
        "RENAME TO agent_trajectory_events_v12_backup"
    )
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
                'tool_observation_recorded',
                'supervisor_plan_decided','supervisor_integration_committed')),
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(task_id, event_id)
        )
        """
    )
    conn.execute(
        "INSERT INTO agent_trajectory_events "
        "(seq, event_id, task_id, investigation_id, run_id, delegation_id, "
        " event_type, payload_json, created_at) "
        "SELECT seq, event_id, task_id, investigation_id, run_id, "
        "delegation_id, event_type, payload_json, created_at "
        "FROM agent_trajectory_events_v12_backup"
    )
    conn.execute("DROP TABLE agent_trajectory_events_v12_backup")
    conn.execute("PRAGMA user_version = 12")
    conn.commit()
    conn.close()

    reopened = AgentRuntimeRepository(InvestigationRepository(db, "task-A"))
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION == 15

    # P1-P4 data preserved: the working state revision and the trajectory
    # rows survived the rebuild verbatim.
    revision = reopened.get_working_state_revision(investigation_id, 1)
    assert revision is not None
    assert reopened.list_trajectory(investigation_id) == events_before

    # P5A tables are back and the new trajectory events are accepted.
    assert reopened.list_entity_occurrences(investigation_id) == []
    reopened.append_trajectory(
        investigation_id,
        AgentTrajectoryEventType.entity_occurrences_recorded,
        payload={"occurrence_count": 0},
    )


def test_future_v14_fails_closed(tmp_path):
    from httpserver.services.investigation.repository import EvidenceStoreError

    db = tmp_path / "investigation.db"
    InvestigationRepository(db, "A")
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(EvidenceStoreError):
        InvestigationRepository(db, "A")


def test_delegation_evidence_scope_is_durable_across_restart(tmp_path):
    from httpserver.services.investigation.agent_runtime import DelegationSpec

    repo, investigation_id, db = _seed(tmp_path)
    run = repo.start_run(investigation_id)
    repo.mark_run_running(run.run_id)
    delegation = repo.admit_delegations(
        run.run_id, [DelegationSpec(question_ref="q-1")]
    )[0]

    scope = repo.record_delegation_evidence_scope(
        investigation_id,
        delegation.delegation_id,
        initial_evidence_refs=("file:C/b.doc", "file:C/a.doc", "file:C/a.doc"),
        input_hash="hash-1",
    )
    assert scope.initial_evidence_refs == ("file:C/a.doc", "file:C/b.doc")

    # identical replay returns the durable row unchanged
    replayed = repo.record_delegation_evidence_scope(
        investigation_id,
        delegation.delegation_id,
        initial_evidence_refs=("file:C/a.doc", "file:C/b.doc"),
        input_hash="hash-1",
    )
    assert replayed == scope

    # replay under a different input hash fails closed
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeConflictError,
    )

    with pytest.raises(AgentRuntimeConflictError):
        repo.record_delegation_evidence_scope(
            investigation_id,
            delegation.delegation_id,
            initial_evidence_refs=("file:C/a.doc",),
            input_hash="hash-2",
        )

    # restart: same scope reconstructs from durable rows
    reopened = AgentRuntimeRepository(InvestigationRepository(db, "task-A"))
    assert reopened.get_delegation_evidence_scope(
        delegation.delegation_id
    ) == scope
