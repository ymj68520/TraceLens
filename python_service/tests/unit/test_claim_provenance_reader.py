"""Tests for strict read-only historical Claim provenance access."""

from __future__ import annotations

import sqlite3

import pytest

from httpserver.services.claim_provenance_reader import ClaimProvenanceReader
from httpserver.services.investigation_persistence import InvestigationPersistence


def _claim_store(tmp_path):
    store = InvestigationPersistence(tmp_path / "investigation.db")
    event_id, _ = store.upsert_seed_event("task-a", "cluster:v1:1:X", "seed", None, None, None)
    version = store.create_event_version(
        "task-a", event_id, None, [], ["file:/a", "file:/b"], "hash", 0, False, "event-v1"
    )
    store.mark_event_version_running("task-a", event_id, version["id"])
    store.complete_event_version_bundle(
        "task-a", event_id, version["id"], "historical", "summary", ["file:/a", "file:/b"],
        "valid", [], "review_pending", "model", [{
            "text": "historical claim",
            "type": "fact",
            "status": "review_pending",
            "grounding_status": "grounded",
            "grounding_warnings": ["kept for audit"],
            "kept_refs": ["file:/a"],
            "relation": "supports",
            "origin": "event_refresh",
        }],
    )
    claim = store.list_event_claims("task-a", event_id, version["id"])[0]
    with store._connect() as connection:
        connection.execute(
            "UPDATE event_claim_evidence SET relation = ?, rationale = ? WHERE claim_id = ?",
            ("contradicts", "historical counter-evidence", claim["id"]),
        )
    return store, claim


def test_reader_returns_historical_claim_and_links_without_effective_selection(tmp_path):
    store, claim = _claim_store(tmp_path)

    result = ClaimProvenanceReader(store.db_path).get_claim("task-a", claim["id"])

    assert result["claim_id"] == claim["id"]
    assert result["event_id"] == claim["event_id"]
    assert result["event_version_id"] == claim["event_version_id"]
    assert result["claim_text"] == "historical claim"
    assert result["status"] == "review_pending"
    assert result["grounding_warnings"] == ["kept for audit"]
    assert result["evidence_links"] == [{
        "evidence_key": "file:/a",
        "relation": "contradicts",
        "rationale": "historical counter-evidence",
    }]
    assert store.effective_event_claims("task-a", claim["event_id"]) == []


def test_reader_task_scopes_claim_and_opens_database_read_only(tmp_path):
    store, claim = _claim_store(tmp_path)
    reader = ClaimProvenanceReader(store.db_path)

    before = store.db_path.read_bytes()
    assert reader.get_claim("task-b", claim["id"]) is None
    assert store.db_path.read_bytes() == before

    with reader._connect() as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE forbidden_write(id INTEGER)")

    assert reader.get_claim("task-a", "missing-claim") is None
    assert store.db_path.read_bytes() == before
