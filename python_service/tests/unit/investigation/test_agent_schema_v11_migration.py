"""P4A §58: investigation.db v10 -> v11 migration tests (agent_delegation_results).

Matrix: fresh v11, v10 -> v11, data preservation, result immutability,
one result per delegation, future version fail closed, legacy persistence
skip. Canonical Investigation semantics untouched.
"""

import sqlite3

import pytest

from httpserver.services.investigation.agent_runtime import AgentRuntimeRepository
from httpserver.services.investigation_persistence import (
    InvestigationPersistence,
)
from httpserver.services.investigation.repository import (
    SUPPORTED_SCHEMA_VERSION,
    InvestigationRepository,
)

pytestmark = pytest.mark.migration_matrix


def _user_version(path) -> int:
    return sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0]


def _seed(db_path):
    store = InvestigationRepository(db_path, "task-A")
    repo = AgentRuntimeRepository(store)
    investigation, _rev = repo.create_investigation({"objective": "v11"})
    run = repo.start_run(investigation.investigation_id)
    repo.mark_run_running(run.run_id)
    from httpserver.services.investigation.agent_runtime import DelegationSpec

    delegation = repo.admit_delegations(
        run.run_id,
        [DelegationSpec(question_ref="q-1", based_on_state_revision=1)],
    )[0]
    observation = repo.append_tool_observation(
        investigation.investigation_id,
        tool_id="t",
        summary="s",
        result={"schema_version": "tool-observation:v1"},
        evidence_refs=("file:C/keep.doc",),
        run_id=run.run_id,
        delegation_id=delegation.delegation_id,
    )
    repo.start_delegation(delegation.delegation_id)
    return repo, investigation.investigation_id, run.run_id, delegation.delegation_id, observation


def _downgrade_to_v10(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE agent_delegation_results")
        conn.execute("PRAGMA user_version = 10")
        conn.commit()
    finally:
        conn.close()


def test_fresh_db_initializes_v11(tmp_path):
    db = tmp_path / "investigation.db"
    InvestigationRepository(db, "A")
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION == 11
    conn = sqlite3.connect(db)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    conn.close()
    assert "agent_delegation_results" in tables


def test_v10_store_migrates_to_v11_preserving_everything(tmp_path):
    db = tmp_path / "investigation.db"
    repo, investigation_id, run_id, delegation_id, observation = _seed(db)
    before_events = repo.list_trajectory(investigation_id)

    _downgrade_to_v10(db)
    assert _user_version(db) == 10

    reopened = AgentRuntimeRepository(InvestigationRepository(db, "task-A"))
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION

    # every P1/P2 record survives untouched
    assert reopened.get_investigation(investigation_id) is not None
    assert reopened.get_run(run_id) is not None
    assert reopened.get_delegation(delegation_id).status.value == "running"
    observation_check = reopened.list_tool_observations(investigation_id)
    assert observation_check[0].observation_id == observation.observation_id
    assert observation_check[0].evidence_refs == ("file:C/keep.doc",)
    assert [t.seq for t in reopened.list_trajectory(investigation_id)] == [
        t.seq for t in before_events
    ]
    # no phantom results exist for a delegation that never completed on v10
    assert reopened.get_delegation_result(delegation_id) is None
    # and the new table is functional after the migration
    _stored, delegation = reopened.complete_delegation_with_result(
        delegation_id,
        result_version="specialist-result:v1",
        result={"summary": "post-migration"},
        result_hash="hash-post",
    )
    assert delegation.status.value == "completed"
    assert reopened.get_delegation_result(delegation_id).result_hash == "hash-post"


def test_result_immutability_and_one_per_delegation(tmp_path):
    db = tmp_path / "investigation.db"
    repo, _inv, _run, delegation_id, _obs = _seed(db)
    repo.complete_delegation_with_result(
        delegation_id,
        result_version="specialist-result:v1",
        result={"summary": "only"},
        result_hash="hash-1",
    )
    conn = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_delegation_results "
            "(task_id, investigation_id, run_id, delegation_id, result_version, "
            " result_json, result_hash, validation_status, created_at) "
            "VALUES ('task-A', (SELECT investigation_id FROM agent_investigations), "
            "(SELECT run_id FROM agent_runs), ?, 'specialist-result:v1', '{}', "
            "'h', 'valid', 'now')",
            (delegation_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE agent_delegation_results SET result_hash = 'x'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM agent_delegation_results")
    conn.close()
    assert repo.get_delegation_result(delegation_id).result_hash == "hash-1"


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


def test_legacy_persistence_skips_repository_owned_v11(tmp_path):
    db = tmp_path / "investigation.db"
    repo, investigation_id, _run, _delegation_id, _obs = _seed(db)
    persistence = InvestigationPersistence(db)
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION
    assert persistence.get_snapshot("task-A", "file:C/x.doc") in (None, {})
    assert repo.get_investigation(investigation_id) is not None
