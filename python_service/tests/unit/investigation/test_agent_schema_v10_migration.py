"""P3 freeze follow-up F2.1: investigation.db schema v9 -> v10 migration tests.

Covers the required matrix: fresh v10, real v9 -> v10 rebuild, data
preservation (P1/P2/P3 rows, observations, trajectory order/AUTOINCREMENT),
new event accepted / unknown rejected, idempotency, future-version fail
closed, and the legacy persistence layer still skipping repository-owned
stores.
"""

import sqlite3

import pytest

from httpserver.services.investigation import agent_runtime as agent_runtime_module
from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
)
from httpserver.services.investigation_persistence import (
    InvestigationPersistence,
)
from httpserver.services.investigation.repository import (
    SUPPORTED_SCHEMA_VERSION,
    InvestigationRepository,
    _CREATE_AGENT_TRAJECTORY_EVENTS_V9_REBUILD_SQL,
)

pytestmark = pytest.mark.migration_matrix


def _user_version(path) -> int:
    return sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0]


def _seed_agent_data(db_path):
    """Insert P1/P2-era rows and return ids for preservation checks."""
    store = InvestigationRepository(db_path, "task-A")
    repo = AgentRuntimeRepository(store)
    investigation, _rev = repo.create_investigation({"objective": "migrate"})
    run = repo.start_run(investigation.investigation_id)
    repo.mark_run_running(run.run_id)
    observation = repo.append_tool_observation(
        investigation.investigation_id,
        tool_id="legacy_tool",
        summary="pre-migration observation",
        result={"schema_version": "tool-observation:v1"},
        evidence_refs=("file:C/keep.doc",),
        run_id=run.run_id,
    )
    repo.append_trajectory(
        investigation.investigation_id,
        AgentTrajectoryEventType.runtime_recovered,
        run_id=run.run_id,
        payload={"note": "before migration"},
    )
    return repo, investigation.investigation_id, run.run_id, observation


def test_fresh_db_initializes_v10(tmp_path):
    db = tmp_path / "investigation.db"
    InvestigationRepository(db, "A")
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION == 13


def _downgrade_trajectory_table_to_v9(db_path):
    """Turn a v10 store into a genuine v9-shaped store (old CHECK + rows)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(_CREATE_AGENT_TRAJECTORY_EVENTS_V9_REBUILD_SQL)
        conn.execute(
            "INSERT INTO agent_trajectory_events_v9_rebuild "
            "(seq, event_id, task_id, investigation_id, run_id, delegation_id, "
            " event_type, payload_json, created_at) "
            "SELECT seq, event_id, task_id, investigation_id, run_id, "
            "delegation_id, event_type, payload_json, created_at "
            "FROM agent_trajectory_events"
        )
        conn.execute("DROP TABLE agent_trajectory_events")
        conn.execute(
            "ALTER TABLE agent_trajectory_events_v9_rebuild "
            "RENAME TO agent_trajectory_events"
        )
        conn.execute("PRAGMA user_version = 9")
        conn.commit()
    finally:
        conn.close()


def test_v9_store_migrates_to_v10_preserving_everything(tmp_path):
    db = tmp_path / "investigation.db"
    repo, investigation_id, run_id, observation = _seed_agent_data(db)
    before_events = repo.list_trajectory(investigation_id)
    max_seq_before = max(t.seq for t in before_events)

    _downgrade_trajectory_table_to_v9(db)
    assert _user_version(db) == 9

    reopened = AgentRuntimeRepository(InvestigationRepository(db, "task-A"))
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION

    # P1/P2/P3 rows preserved
    investigation = reopened.get_investigation(investigation_id)
    assert investigation is not None
    assert reopened.get_run(run_id) is not None
    observations = reopened.list_tool_observations(investigation_id)
    assert [o.observation_id for o in observations] == [observation.observation_id]
    assert observations[0].evidence_refs == ("file:C/keep.doc",)

    # trajectory rows preserved in order, AUTOINCREMENT continues
    after_events = reopened.list_trajectory(investigation_id)
    assert [t.seq for t in after_events] == [t.seq for t in before_events]
    new_event = reopened.append_trajectory(
        investigation_id,
        AgentTrajectoryEventType.tool_observation_recorded,
        run_id=run_id,
        payload={"observation_id": observation.observation_id},
    )
    assert new_event.seq > max_seq_before


def test_new_event_type_accepted_and_unknown_rejected(tmp_path):
    db = tmp_path / "investigation.db"
    repo, investigation_id, run_id, _obs = _seed_agent_data(db)
    event = repo.append_trajectory(
        investigation_id,
        AgentTrajectoryEventType.tool_observation_recorded,
        run_id=run_id,
        payload={"observation_id": "obs_x"},
    )
    assert event.event_type == AgentTrajectoryEventType.tool_observation_recorded

    conn = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_trajectory_events "
            "(event_id, task_id, investigation_id, run_id, event_type, "
            " payload_json, created_at) VALUES "
            "('e_bad', 'task-A', ?, NULL, 'made_up_event', '{}', 'now')",
            (investigation_id,),
        )
    conn.close()


def test_migration_is_idempotent_on_reopen(tmp_path):
    db = tmp_path / "investigation.db"
    repo, investigation_id, _run_id, _obs = _seed_agent_data(db)
    for _ in range(3):
        reopened = AgentRuntimeRepository(InvestigationRepository(db, "task-A"))
        assert _user_version(db) == SUPPORTED_SCHEMA_VERSION
        assert reopened.get_investigation(investigation_id) is not None


def test_future_version_fails_closed(tmp_path):
    db = tmp_path / "investigation.db"
    InvestigationRepository(db, "A")
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(Exception, match="unsupported"):
        InvestigationRepository(db, "A")
    with pytest.raises(Exception, match="unsupported"):
        InvestigationRepository.open_existing(db, "A")


def test_legacy_persistence_skips_repository_owned_v10(tmp_path):
    db = tmp_path / "investigation.db"
    repo, investigation_id, _run_id, _obs = _seed_agent_data(db)
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION
    persistence = InvestigationPersistence(db)  # must not migrate or raise
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION
    assert persistence.get_snapshot("task-A", "file:C/x.doc") in (None, {})
    assert repo.get_investigation(investigation_id) is not None
