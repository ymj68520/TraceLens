"""P5B §73 schema v14 migration tests: five semantic-verification tables,
the canonical Finding state machine, review provenance guards, the five
P5B trajectory events, and P1-P5A data preservation."""

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

_P5B_TABLES = (
    "agent_semantic_verifications",
    "agent_semantic_verification_failures",
    "agent_claim_dispositions",
    "investigation_findings",
    "investigation_finding_reviews",
)

_FINDING_BASE_COLUMNS = (
    "finding_id, task_id, investigation_id, proposal_id, disposition_id, "
    "text, assertion_class, evidence_refs_json, relationship_refs_json, "
    "temporal_scope_json, grounding_id, semantic_verification_id, "
    "limitations_json, status, created_at"
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
    investigation_id = "inv-" + "9" * 8
    state = AgentWorkingStateV1(
        task_id="task-A", investigation_id=investigation_id, objective="v14"
    )
    investigation, _rev = repo.create_investigation(
        working_state_to_json(state), investigation_id=investigation_id
    )
    return repo, investigation.investigation_id, db


def test_fresh_db_initializes_v14_with_p5b_tables(tmp_path):
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
        for table in _P5B_TABLES:
            assert table in tables
        triggers = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        for table in _P5B_TABLES:
            if table == "investigation_findings":
                continue  # state machine, guarded by dedicated triggers
            assert f"trg_{table}_no_update" in triggers
            assert f"trg_{table}_no_delete" in triggers
        for trigger in (
            "trg_investigation_finding_no_identity_update",
            "trg_investigation_finding_legal_transition",
            "trg_investigation_finding_review_provenance",
        ):
            assert trigger in triggers
    finally:
        conn.close()


def test_finding_state_machine_guards(tmp_path):
    _repo, investigation_id, db = _seed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    base = (
        "INSERT INTO investigation_findings "
        f"({_FINDING_BASE_COLUMNS}) "
        "VALUES (?, 'task-A', ?, 'prop-1', 'disp-1', 'text', "
        "'INFERENCE', '[]', '[]', NULL, 'grnd-1', NULL, '[]', "
        "?, '2026-01-01')"
    )
    try:
        conn.execute(base, ("finding-1", investigation_id, "review_pending"))
        # identity is immutable
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE investigation_findings SET text = 'x' "
                "WHERE finding_id = 'finding-1'"
            )
        # review_pending -> accepted without provenance is refused
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE investigation_findings SET status = 'accepted' "
                "WHERE finding_id = 'finding-1'"
            )
        # with full review provenance it is the one legal edge
        conn.execute(
            "UPDATE investigation_findings SET status = 'accepted', "
            "reviewed_at = '2026-01-02', reviewer = 'analyst-1', "
            "review_id = 'review-1' WHERE finding_id = 'finding-1'"
        )
        # terminal: no outgoing edges
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE investigation_findings SET status = 'rejected' "
                "WHERE finding_id = 'finding-1'"
            )
        # review history rows are append-only
        conn.execute(
            "INSERT INTO investigation_finding_reviews "
            "(review_id, task_id, investigation_id, finding_id, decision, "
            " reviewer, note, created_at) "
            "VALUES ('review-1', 'task-A', ?, 'finding-1', 'accepted', "
            "'analyst-1', NULL, '2026-01-02')",
            [investigation_id],
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE investigation_finding_reviews "
                "SET decision = 'rejected'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM investigation_finding_reviews")
        # verification rows are append-only
        conn.execute(
            "INSERT INTO agent_semantic_verifications "
            "(verification_id, task_id, investigation_id, mode, proposal_id, "
            " proposal_hash, grounding_id, support_bundle_id, "
            " support_bundle_hash, status, result_json, result_hash, "
            " recommended_assertion_class, model, prompt_version, "
            " model_config_hash, input_hash, created_at) "
            "VALUES ('sver-1', 'task-A', ?, 'claim_sufficiency', 'prop-1', "
            "'ph', 'grnd-1', 'b', 'bh', 'sufficient', '{}', 'rh', "
            "'INFERENCE', NULL, 'pv', NULL, 'ih', '2026-01-01')",
            [investigation_id],
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE agent_semantic_verifications SET status = 'insufficient'"
            )
    finally:
        conn.rollback()
        conn.close()


def test_v13_store_migrates_to_v14_preserving_p1_p5a_data(tmp_path):
    repo, investigation_id, db = _seed(tmp_path)
    events_before = repo.list_trajectory(investigation_id)
    assert events_before

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN IMMEDIATE")
    for table in _P5B_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(
        "ALTER TABLE agent_trajectory_events "
        "RENAME TO agent_trajectory_events_v13_backup"
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
                'claim_grounding_recorded','claim_proposals_recorded')),
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
        "FROM agent_trajectory_events_v13_backup"
    )
    conn.execute("DROP TABLE agent_trajectory_events_v13_backup")
    conn.execute("PRAGMA user_version = 13")
    conn.commit()
    conn.close()

    reopened = AgentRuntimeRepository(InvestigationRepository(db, "task-A"))
    assert _user_version(db) == SUPPORTED_SCHEMA_VERSION == 15
    assert reopened.get_working_state_revision(investigation_id, 1) is not None
    assert reopened.list_trajectory(investigation_id) == events_before
    reopened.append_trajectory(
        investigation_id,
        AgentTrajectoryEventType.claim_semantic_verified,
        payload={"verification_id": "sver-x", "status": "sufficient"},
    )
    with pytest.raises(ValueError):
        reopened.append_trajectory(
            investigation_id, "made_up_v14_event", payload={}
        )


def test_future_v15_fails_closed(tmp_path):
    from httpserver.services.investigation.repository import EvidenceStoreError

    db = tmp_path / "investigation.db"
    InvestigationRepository(db, "A")
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(EvidenceStoreError):
        InvestigationRepository(db, "A")
