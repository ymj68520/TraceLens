"""P6A §62 schema v15 migration tests."""

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

_P6A_TABLES = (
    "agent_graph_candidates",
    "agent_graph_admission_decisions",
    "agent_graph_episodes",
    "agent_graph_materializations",
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
    investigation_id = "inv-" + "6" * 8
    state = AgentWorkingStateV1(
        task_id="task-A", investigation_id=investigation_id, objective="v15"
    )
    investigation, _rev = repo.create_investigation(
        working_state_to_json(state), investigation_id=investigation_id
    )
    return repo, investigation.investigation_id, db


def test_fresh_db_initializes_v15_with_graph_tables(tmp_path):
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
        for table in _P6A_TABLES:
            assert table in tables
        triggers = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        for table in _P6A_TABLES[:3]:
            assert f"trg_{table}_no_update" in triggers
            assert f"trg_{table}_no_delete" in triggers
        assert "trg_agent_graph_manifest_legal_transition" in triggers
        assert "trg_agent_graph_manifest_no_identity_update" in triggers
    finally:
        conn.close()


def test_graph_tables_append_only_and_manifest_guarded(tmp_path):
    _repo, investigation_id, db = _seed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            "INSERT INTO agent_graph_candidates "
            "(candidate_id, task_id, investigation_id, candidate_version, "
            " candidate_kind, subject_refs_json, relation_refs_json, "
            " object_refs_json, evidence_refs_json, finding_refs_json, "
            " correlation_refs_json, occurrence_refs_json, "
            " semantic_summary, review_status, verification_refs_json, "
            " limitations_json, input_hash, created_at) "
            "VALUES ('gcand:x','task-A',?,'graph-candidate:v1',"
            "'evidence_derived_context','[]','[]','[]','[]','[]','[]',"
            "'[]','s','not_applicable','[]','[]','h','2026-01-01')",
            [investigation_id],
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE agent_graph_candidates SET semantic_summary = 'y'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM agent_graph_candidates")

        conn.execute(
            "INSERT INTO agent_graph_materializations "
            "(materialization_id, task_id, investigation_id, episode_id, "
            " episode_hash, backend_kind, status, queued_at, input_hash, "
            " created_at, updated_at) "
            "VALUES ('gm:1','task-A',?,'episode:1','eh','graphiti',"
            "'queued','2026-01-01','ih','2026-01-01','2026-01-01')",
            [investigation_id],
        )
        # queued -> active skips running: refused
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE agent_graph_materializations SET status = 'active' "
                "WHERE materialization_id = 'gm:1'"
            )
        # legal: queued -> running
        conn.execute(
            "UPDATE agent_graph_materializations SET status = 'running', "
            "started_at = '2026-01-02' WHERE materialization_id = 'gm:1'"
        )
        # running -> invalidated (logical invalidation independent of run)
        conn.execute(
            "UPDATE agent_graph_materializations SET status = 'invalidated',"
            " terminal_at = '2026-01-03' WHERE materialization_id = 'gm:1'"
        )
        # terminal: no outgoing edges
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE agent_graph_materializations SET status = 'running' "
                "WHERE materialization_id = 'gm:1'"
            )
    finally:
        conn.rollback()
        conn.close()


def test_v15_trajectory_events_accepted(tmp_path):
    repo, investigation_id, _db = _seed(tmp_path)
    for event_type in (
        AgentTrajectoryEventType.graph_candidate_recorded,
        AgentTrajectoryEventType.graph_admission_decided,
        AgentTrajectoryEventType.graph_episode_frozen,
        AgentTrajectoryEventType.graph_materialization_queued,
        AgentTrajectoryEventType.graph_materialization_invalidated,
    ):
        event = repo.append_trajectory(investigation_id, event_type, payload={})
        assert event.event_type.value == event_type.value
    with pytest.raises(ValueError):
        repo.append_trajectory(
            investigation_id, "made_up_v15_event", payload={}
        )


def test_v14_store_migrates_to_v15_preserving_p1_p5_data(tmp_path):
    repo, investigation_id, db = _seed(tmp_path)
    events_before = repo.list_trajectory(investigation_id)
    assert events_before

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN IMMEDIATE")
    for table in _P6A_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(
        "ALTER TABLE agent_trajectory_events "
        "RENAME TO agent_trajectory_events_v14_backup"
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
                'supervisor_plan_decided','supervisor_integration_committed',
                'entity_occurrences_recorded','correlation_candidates_recorded',
                'claim_grounding_recorded','claim_proposals_recorded',
                'correlation_semantic_verified','claim_semantic_verified',
                'claim_disposition_recorded','finding_review_pending_created',
                'final_semantic_review_recorded')),
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
        "FROM agent_trajectory_events_v14_backup"
    )
    conn.execute("DROP TABLE agent_trajectory_events_v14_backup")
    conn.execute("PRAGMA user_version = 14")
    conn.commit()
    conn.close()

    reopened = AgentRuntimeRepository(InvestigationRepository(db, "task-A"))
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION == 15
    assert reopened.get_working_state_revision(investigation_id, 1) is not None
    assert reopened.list_trajectory(investigation_id) == events_before


def test_future_v16_fails_closed(tmp_path):
    from httpserver.services.investigation.repository import EvidenceStoreError

    db = tmp_path / "investigation.db"
    InvestigationRepository(db, "A")
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(EvidenceStoreError):
        InvestigationRepository(db, "A")
