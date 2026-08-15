"""Unit tests for the Investigation persistence layer."""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from httpserver.services.investigation_errors import VersionConflict
from httpserver.services.investigation_persistence import (
    BOOTSTRAP_VERSION,
    InvestigationPersistence,
    VersionConflict,
    get_investigation_db_path,
)


@pytest.fixture
def persistence(tmp_path):
    return InvestigationPersistence(tmp_path / "task1" / "investigation.db")


# ----------------------------------------------------------------------
# path derivation
# ----------------------------------------------------------------------

class TestDbPathDerivation:
    def test_fixed_name_layout(self):
        p = get_investigation_db_path("/data/tasks/abc/files.db")
        assert p.name == "investigation.db"
        assert p.parent.name == "abc"

    def test_legacy_suffix_layout(self):
        p = get_investigation_db_path("/out/服务器镜像_files.db")
        assert p.name == "服务器镜像_investigation.db"

    def test_fallback(self):
        p = get_investigation_db_path("/some/dir/other.db")
        assert p.name == "investigation.db"


# ----------------------------------------------------------------------
# schema
# ----------------------------------------------------------------------

class TestSchema:
    def test_idempotent_init(self, tmp_path):
        db = tmp_path / "investigation.db"
        InvestigationPersistence(db)
        InvestigationPersistence(db)  # second init must not raise
        with sqlite3.connect(db) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        expected = {
            "investigation_events",
            "investigation_event_evidence",
            "evidence_snapshots",
            "analyst_notes",
            "evidence_analysis_versions",
            "evidence_analysis_claims",
            "claim_evidence",
            "evidence_analysis_entities",
            "evidence_analysis_relations",
            "report_evidence",
            "investigation_meta",
        }
        assert expected <= tables

    def test_foreign_keys_enabled(self, persistence):
        with persistence._connect() as conn:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    def test_event_delete_cascades_evidence(self, persistence):
        event_id, _ = persistence.upsert_seed_event(
            "t1", "cluster:v1:100:CREATED", "t", "s", 6000, 6100
        )
        persistence.link_evidence(
            "t1", event_id, "file:/a.txt", "file", "primary", "cluster_seed"
        )
        with persistence._connect() as conn:
            conn.execute("DELETE FROM investigation_events WHERE id = ?", (event_id,))
            remaining = conn.execute(
                "SELECT COUNT(*) c FROM investigation_event_evidence WHERE event_id = ?",
                (event_id,),
            ).fetchone()["c"]
        assert remaining == 0

    def test_analysis_delete_cascades_children(self, persistence):
        analysis = persistence.create_analysis_version(
            "t1", "file:/a.txt", "file", None, None, None, "v1", None, []
        )
        claim_id = persistence.add_claim(
            analysis["id"], "text", "fact", "grounded", "evidence_derived"
        )
        persistence.add_claim_evidence(claim_id, "file:/a.txt", "supports")
        entity_id = persistence.add_entity(analysis["id"], "FILE", "/a.txt")
        persistence.add_relation(
            analysis["id"], entity_id, entity_id, "self", "observed"
        )
        with persistence._connect() as conn:
            conn.execute(
                "DELETE FROM evidence_analysis_versions WHERE id = ?",
                (analysis["id"],),
            )
            for table in (
                "evidence_analysis_claims",
                "claim_evidence",
                "evidence_analysis_entities",
                "evidence_analysis_relations",
            ):
                count = conn.execute(
                    f"SELECT COUNT(*) c FROM {table}"
                ).fetchone()["c"]
                assert count == 0, table


# ----------------------------------------------------------------------
# events & bootstrap idempotence
# ----------------------------------------------------------------------

class TestEvents:
    def test_seed_event_idempotent(self, persistence):
        id1, created1 = persistence.upsert_seed_event(
            "t1", "cluster:v1:100:CREATED", "title", "summary", 6000, 6100
        )
        id2, created2 = persistence.upsert_seed_event(
            "t1", "cluster:v1:100:CREATED", "title2", "summary2", 6000, 6100
        )
        assert created1 is True
        assert created2 is False
        assert id1 == id2
        event = persistence.get_event("t1", id1)
        assert event["title"] == "title"  # not overwritten
        assert event["seed_title"] == "title"

    def test_analyst_events_allow_null_cluster_key(self, persistence):
        a = persistence.create_event("t1", "e1", None, "analyst")
        b = persistence.create_event("t1", "e2", None, "analyst")
        assert a != b
        events = persistence.list_events("t1")
        assert len(events) == 2
        assert all(e["source_cluster_key"] is None for e in events)

    def test_review_status_validation(self, persistence):
        event_id, _ = persistence.upsert_seed_event(
            "t1", "cluster:v1:1:X", "t", None, None, None
        )
        persistence.set_event_review_status("t1", event_id, "confirmed")
        assert persistence.get_event("t1", event_id)["review_status"] == "confirmed"
        with pytest.raises(ValueError):
            persistence.set_event_review_status("t1", event_id, "bogus")
        with pytest.raises(KeyError):
            persistence.set_event_review_status("t1", "missing", "confirmed")

    def test_link_evidence_idempotent_and_role_validation(self, persistence):
        event_id, _ = persistence.upsert_seed_event(
            "t1", "cluster:v1:1:X", "t", None, None, None
        )
        assert persistence.link_evidence(
            "t1", event_id, "file:/a", "file", "primary", "cluster_seed"
        ) is True
        assert persistence.link_evidence(
            "t1", event_id, "file:/a", "file", "primary", "cluster_seed"
        ) is False
        with pytest.raises(ValueError):
            persistence.link_evidence(
                "t1", event_id, "file:/b", "file", "owner", "analyst"
            )
        counts = persistence.event_evidence_counts(event_id)
        assert counts["primary"] == 1 and counts["total"] == 1

    def test_unlink_evidence(self, persistence):
        event_id, _ = persistence.upsert_seed_event(
            "t1", "cluster:v1:1:X", "t", None, None, None
        )
        persistence.link_evidence(
            "t1", event_id, "file:/a", "file", "supporting", "analyst"
        )
        assert persistence.unlink_evidence(event_id, "file:/a") is True
        assert persistence.unlink_evidence(event_id, "file:/a") is False

    def test_mark_events_needing_refresh(self, persistence):
        event_id, _ = persistence.upsert_seed_event(
            "t1", "cluster:v1:1:X", "t", None, None, None
        )
        persistence.link_evidence(
            "t1", event_id, "file:/a", "file", "primary", "cluster_seed"
        )
        assert persistence.mark_events_needing_refresh("t1", "file:/a") == 1
        assert persistence.get_event("t1", event_id)["needs_refresh"] == 1


# ----------------------------------------------------------------------
# snapshots
# ----------------------------------------------------------------------

class TestSnapshots:
    def test_capture_only_once(self, persistence):
        assert persistence.capture_snapshot_if_absent(
            "t1", "file:/a.txt", "file",
            {"path": "/a.txt"}, "desc A", "sum A",
            source_hash="abc", source_size=10, source_mtime=100,
        ) is True
        # Second capture with different content must be ignored
        assert persistence.capture_snapshot_if_absent(
            "t1", "file:/a.txt", "file",
            {"path": "/a.txt"}, "desc B", "sum B",
            source_hash="def", source_size=20, source_mtime=200,
        ) is False
        snap = persistence.get_snapshot("t1", "file:/a.txt")
        assert snap["initial_description"] == "desc A"
        assert snap["source_hash"] == "abc"
        assert snap["source_size"] == 10
        assert snap["source_mtime"] == 100


# ----------------------------------------------------------------------
# notes
# ----------------------------------------------------------------------

class TestNotes:
    def test_upsert(self, persistence):
        id1 = persistence.upsert_note("t1", "evidence", "file:/a", "first")
        id2 = persistence.upsert_note("t1", "evidence", "file:/a", "second")
        assert id1 == id2
        note = persistence.get_note("t1", "evidence", "file:/a")
        assert note["content"] == "second"

    def test_targets_isolated(self, persistence):
        persistence.upsert_note("t1", "evidence", "file:/a", "ev note")
        persistence.upsert_note("t1", "investigation_event", "file:/a", "event note")
        assert persistence.get_note("t1", "evidence", "file:/a")["content"] == "ev note"


# ----------------------------------------------------------------------
# analysis versions
# ----------------------------------------------------------------------

class TestAnalysisVersions:
    def test_version_increments(self, persistence):
        v1 = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, "m", "p1", "h1", []
        )
        v2 = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, "m", "p1", "h2", []
        )
        assert v1["version"] == 1
        assert v2["version"] == 2
        assert v1["status"] == "queued"

    def test_concurrent_version_allocation(self, persistence):
        """Concurrent creators must never collide on (task, evidence, version)."""
        results = []
        errors = []

        def create():
            try:
                results.append(
                    persistence.create_analysis_version(
                        "t1", "file:/shared", "file", None, None, None, None, None, []
                    )
                )
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=create) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        versions = sorted(r["version"] for r in results)
        assert versions == list(range(1, 9))

    def test_note_snapshot_and_input_hash_persisted(self, persistence):
        note_id = persistence.upsert_note("t1", "evidence", "file:/a", "note A")
        analysis = persistence.create_analysis_version(
            "t1", "file:/a", "file", note_id, "note A", "model-x", "v1",
            "hash123", ["file:/a"],
        )
        assert analysis["analyst_note_snapshot"] == "note A"
        assert analysis["input_hash"] == "hash123"

    def test_complete_and_fail(self, persistence):
        analysis = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        persistence.mark_analysis_running(analysis["id"])
        persistence.complete_analysis(
            analysis["id"], "desc", "sum", "valid", [], status="review_pending"
        )
        row = persistence.get_analysis(analysis["id"])
        assert row["status"] == "review_pending"
        assert row["grounding_status"] == "valid"
        assert row["completed_at"] is not None

        analysis2 = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        persistence.fail_analysis(analysis2["id"], "boom")
        row2 = persistence.get_analysis(analysis2["id"])
        assert row2["status"] == "failed"
        assert row2["error_message"] == "boom"

    def test_accept_replaces_previous_accepted(self, persistence):
        v1 = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        persistence.mark_analysis_running(v1["id"])
        persistence.complete_analysis(v1["id"], None, None, "valid", [])
        persistence.accept_analysis("t1", v1["id"])
        assert persistence.get_analysis(v1["id"])["status"] == "accepted"

        v2 = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        persistence.mark_analysis_running(v2["id"])
        persistence.complete_analysis(v2["id"], None, None, "valid", [])
        persistence.accept_analysis("t1", v2["id"])

        assert persistence.get_analysis(v1["id"])["status"] == "review_pending"
        assert persistence.get_analysis(v2["id"])["status"] == "accepted"
        accepted = persistence.get_accepted_analysis("t1", "file:/a")
        assert accepted["id"] == v2["id"]

    def test_accept_guards(self, persistence):
        # running analysis cannot be accepted
        running = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        with pytest.raises(ValueError):
            persistence.accept_analysis("t1", running["id"])

        # failed cannot be accepted
        failed = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        persistence.fail_analysis(failed["id"], "x")
        with pytest.raises(ValueError):
            persistence.accept_analysis("t1", failed["id"])

        # invalid grounding cannot be accepted
        inv = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        persistence.mark_analysis_running(inv["id"])
        persistence.complete_analysis(
            inv["id"], None, None, "invalid", ["bad ref"], status="invalid"
        )
        with pytest.raises(ValueError):
            persistence.accept_analysis("t1", inv["id"], acknowledge_warnings=True)

        # partially grounded requires acknowledgement
        part = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        persistence.mark_analysis_running(part["id"])
        persistence.complete_analysis(
            part["id"], None, None, "partially_grounded", ["dropped ref"]
        )
        with pytest.raises(ValueError):
            persistence.accept_analysis("t1", part["id"])
        persistence.accept_analysis("t1", part["id"], acknowledge_warnings=True)
        assert persistence.get_analysis(part["id"])["status"] == "accepted"

    def test_reject(self, persistence):
        analysis = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        persistence.mark_analysis_running(analysis["id"])
        persistence.complete_analysis(analysis["id"], None, None, "valid", [])
        persistence.reject_analysis("t1", analysis["id"])
        assert persistence.get_analysis(analysis["id"])["status"] == "rejected"
        with pytest.raises(KeyError):
            persistence.reject_analysis("t1", analysis["id"])  # already rejected

    def test_recover_interrupted_jobs(self, persistence):
        a1 = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        a2 = persistence.create_analysis_version(
            "t1", "file:/b", "file", None, None, None, None, None, []
        )
        persistence.mark_analysis_running(a2["id"])
        a3 = persistence.create_analysis_version(
            "t1", "file:/c", "file", None, None, None, None, None, []
        )
        persistence.mark_analysis_running(a3["id"])
        persistence.complete_analysis(a3["id"], None, None, "valid", [])

        recovered = persistence.recover_interrupted_jobs()
        assert recovered == 2
        assert persistence.get_analysis(a1["id"])["status"] == "failed"
        assert persistence.get_analysis(a2["id"])["status"] == "failed"
        assert persistence.get_analysis(a3["id"])["status"] == "review_pending"

    def test_effective_analysis_prefers_accepted(self, persistence):
        v1 = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        persistence.mark_analysis_running(v1["id"])
        persistence.complete_analysis(v1["id"], None, None, "valid", [])
        persistence.accept_analysis("t1", v1["id"])
        v2 = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        persistence.mark_analysis_running(v2["id"])
        persistence.complete_analysis(v2["id"], None, None, "valid", [])
        effective = persistence.get_effective_analysis("t1", "file:/a")
        assert effective["id"] == v1["id"]  # accepted wins over newer pending


# ----------------------------------------------------------------------
# report evidence
# ----------------------------------------------------------------------

class TestReportEvidence:
    def _accepted_analysis(self, persistence, key="file:/a"):
        analysis = persistence.create_analysis_version(
            "t1", key, "file", None, None, None, None, None, []
        )
        persistence.mark_analysis_running(analysis["id"])
        persistence.complete_analysis(analysis["id"], None, None, "valid", [])
        persistence.accept_analysis("t1", analysis["id"])
        return analysis

    def test_add_update_remove(self, persistence):
        entry_id = persistence.set_report_evidence(
            "t1", "file:/a", "file", "main", role="primary", report_note="note"
        )
        entry = persistence.get_report_evidence("t1", "file:/a")
        assert entry["id"] == entry_id
        assert entry["usage"] == "main"
        assert entry["analysis_id"] is None  # no accepted analysis

        persistence.set_report_evidence("t1", "file:/a", "file", "appendix")
        entry = persistence.get_report_evidence("t1", "file:/a")
        assert entry["usage"] == "appendix"
        assert entry["id"] == entry_id  # same row updated

        assert persistence.remove_report_evidence("t1", "file:/a") is True
        assert persistence.get_report_evidence("t1", "file:/a") is None

    def test_analysis_binding_rules(self, persistence):
        accepted = self._accepted_analysis(persistence)
        persistence.set_report_evidence(
            "t1", "file:/a", "file", "main", analysis_id=accepted["id"]
        )
        entry = persistence.get_report_evidence("t1", "file:/a")
        assert entry["analysis_id"] == accepted["id"]

        # pending analysis cannot be bound
        pending = persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        persistence.mark_analysis_running(pending["id"])
        persistence.complete_analysis(pending["id"], None, None, "valid", [])
        with pytest.raises(ValueError):
            persistence.set_report_evidence(
                "t1", "file:/a", "file", "main", analysis_id=pending["id"]
            )

        # unknown analysis id
        with pytest.raises(KeyError):
            persistence.set_report_evidence(
                "t1", "file:/a", "file", "main", analysis_id="nope"
            )

    def test_invalid_usage(self, persistence):
        with pytest.raises(ValueError):
            persistence.set_report_evidence("t1", "file:/a", "file", "featured")


# ----------------------------------------------------------------------
# overview
# ----------------------------------------------------------------------

class TestOverview:
    def test_overview_counts(self, persistence):
        ov = persistence.overview("t1")
        assert ov["initialized"] is False
        assert ov["event_count"] == 0

        persistence.set_meta("bootstrap_version", str(BOOTSTRAP_VERSION))
        event_id, _ = persistence.upsert_seed_event(
            "t1", "cluster:v1:1:X", "t", None, None, None
        )
        persistence.set_event_review_status("t1", event_id, "confirmed")
        persistence.create_analysis_version(
            "t1", "file:/a", "file", None, None, None, None, None, []
        )
        persistence.set_report_evidence("t1", "file:/a", "file", "main")

        ov = persistence.overview("t1")
        assert ov["initialized"] is True
        assert ov["bootstrap_version"] == BOOTSTRAP_VERSION
        assert ov["event_count"] == 1
        assert ov["confirmed_event_count"] == 1
        assert ov["analysis_count"] == 1
        assert ov["report_evidence_count"] == 1


class TestPhase2EHardening:
    def _event_version(self, persistence, event_id, source_revision=0):
        version = persistence.create_event_version(
            "t1", event_id, None, [], ["file:/a"], "hash", source_revision,
            False, "event-v1",
        )
        persistence.mark_event_version_running("t1", event_id, version["id"])
        persistence.complete_event_version(
            "t1", event_id, version["id"], "title", "summary", ["file:/a"],
            "valid", [], "review_pending", "model",
        )
        return version

    def test_fresh_schema_has_v3_event_claims(self, tmp_path):
        db = tmp_path / "fresh.db"
        InvestigationPersistence(db)
        with sqlite3.connect(db) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
            columns = {row[1] for row in conn.execute("PRAGMA table_info(investigation_events)")}
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "semantic_revision" in columns
        assert {"investigation_event_versions", "event_claims", "event_claim_evidence"} <= tables

    def test_future_schema_version_is_not_downgraded(self, tmp_path):
        db = tmp_path / "future.db"
        with sqlite3.connect(db) as conn:
            conn.execute("PRAGMA user_version = 4")
        with pytest.raises(RuntimeError):
            InvestigationPersistence(db)
        with sqlite3.connect(db) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 4

    def test_v1_migration_preserves_event_and_adds_revision(self, tmp_path):
        db = tmp_path / "v1.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE investigation_events (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, title TEXT NOT NULL, summary TEXT, seed_title TEXT, seed_summary TEXT, start_time INTEGER, end_time INTEGER, evidence_start_time INTEGER, evidence_end_time INTEGER, category TEXT, importance TEXT, source TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'draft', confidence REAL, source_cluster_key TEXT, needs_refresh INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, UNIQUE(task_id, source_cluster_key))")
            conn.execute("INSERT INTO investigation_events(id, task_id, title, source, created_at, updated_at) VALUES ('e1', 't1', 'old', 'analyst', 1, 1)")
            conn.execute("PRAGMA user_version = 1")
        persistence = InvestigationPersistence(db)
        assert persistence.get_event("t1", "e1")["title"] == "old"
        assert persistence.get_event("t1", "e1")["semantic_revision"] == 0
        with sqlite3.connect(db) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 3

    def test_link_unlink_and_event_note_revision_changes_are_atomic(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:1:X", "t", None, None, None)
        assert persistence.link_evidence_for_task("t1", event_id, "file:/a", "file", "primary", "analyst")
        assert persistence.get_event("t1", event_id)["semantic_revision"] == 1
        assert not persistence.link_evidence_for_task("t1", event_id, "file:/a", "file", "primary", "analyst")
        assert persistence.get_event("t1", event_id)["semantic_revision"] == 1
        persistence.upsert_event_note_and_invalidate("t1", event_id, "context")
        assert persistence.get_event("t1", event_id)["semantic_revision"] == 2
        persistence.upsert_event_note_and_invalidate("t1", event_id, "context")
        assert persistence.get_event("t1", event_id)["semantic_revision"] == 2
        assert persistence.upsert_event_note_and_invalidate("t1", event_id, "") is None
        assert persistence.get_note("t1", "investigation_event", event_id) is None
        assert persistence.get_event("t1", event_id)["semantic_revision"] == 3
        assert persistence.unlink_evidence_for_task("t1", event_id, "file:/a")
        assert persistence.get_event("t1", event_id)["semantic_revision"] == 4

    def test_accepted_event_versions_remain_accepted_and_same_revision_is_single_effective(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:1:X", "seed", None, None, None)
        v1 = self._event_version(persistence, event_id)
        persistence.accept_event_version("t1", event_id, v1["id"])
        v2 = self._event_version(persistence, event_id)
        with pytest.raises(VersionConflict, match="another effective"):
            persistence.accept_event_version("t1", event_id, v2["id"])
        assert persistence.get_event_version("t1", event_id, v1["id"])["status"] == "accepted"
        assert persistence.get_event_version("t1", event_id, v2["id"])["status"] == "review_pending"
        effective, _ = persistence.effective_event_version("t1", event_id)
        assert effective["id"] == v1["id"]

    def test_event_claim_bundle_and_effective_selection(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:1:X", "seed", None, None, None)
        version = persistence.create_event_version("t1", event_id, None, [], ["file:/a"], "hash", 0, False, "event-v1")
        persistence.mark_event_version_running("t1", event_id, version["id"])
        persistence.complete_event_version_bundle(
            "t1", event_id, version["id"], "title", "summary", ["file:/a"],
            "valid", [], "review_pending", "model", [{
                "text": "fact", "type": "fact", "status": "review_pending",
                "grounding_status": "grounded", "kept_refs": ["file:/a"],
                "relation": "supports", "origin": "evidence_derived",
            }],
        )
        claims = persistence.list_event_claims("t1", event_id, version["id"])
        assert claims[0]["event_version_id"] == version["id"]
        assert claims[0]["status"] == "review_pending"
        assert claims[0]["evidence_refs"][0]["evidence_key"] == "file:/a"
        persistence.accept_event_version("t1", event_id, version["id"])
        assert persistence.effective_event_claims("t1", event_id) == []
        accepted = persistence.review_event_claim("t1", event_id, version["id"], claims[0]["id"], "accepted")
        assert accepted["status"] == "accepted"
        assert persistence.effective_event_claims("t1", event_id)[0]["id"] == claims[0]["id"]

    def test_event_claim_review_requires_current_version(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:1:X", "seed", None, None, None)
        v1 = persistence.create_event_version("t1", event_id, None, [], ["file:/a"], "hash", 0, False, "event-v1")
        persistence.mark_event_version_running("t1", event_id, v1["id"])
        persistence.complete_event_version_bundle("t1", event_id, v1["id"], "t1", "s1", ["file:/a"], "valid", [], "review_pending", "model", [{"text": "c1", "type": "fact", "status": "review_pending", "grounding_status": "grounded", "kept_refs": ["file:/a"]}])
        persistence.accept_event_version("t1", event_id, v1["id"])
        claim = persistence.list_event_claims("t1", event_id, v1["id"])[0]
        persistence.invalidate_event_semantics("t1", event_id)
        v2 = persistence.create_event_version("t1", event_id, None, [], ["file:/a"], "hash", 1, False, "event-v1")
        persistence.mark_event_version_running("t1", event_id, v2["id"])
        persistence.complete_event_version_bundle("t1", event_id, v2["id"], "t2", "s2", ["file:/a"], "valid", [], "review_pending", "model", [])
        persistence.accept_event_version("t1", event_id, v2["id"])
        with pytest.raises(VersionConflict):
            persistence.review_event_claim("t1", event_id, v1["id"], claim["id"], "accepted")

    def test_event_claim_bundle_rolls_back_prior_claims_on_late_failure(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:1:X", "seed", None, None, None)
        version = persistence.create_event_version("t1", event_id, None, [], ["file:/a"], "hash", 0, False, "event-v1")
        persistence.mark_event_version_running("t1", event_id, version["id"])
        with pytest.raises(ValueError, match="allowlist"):
            persistence.complete_event_version_bundle(
                "t1", event_id, version["id"], "title", "summary", ["file:/a"],
                "valid", [], "review_pending", "model", [
                    {"text": "good", "type": "fact", "status": "review_pending", "grounding_status": "grounded", "kept_refs": ["file:/a"]},
                    {"text": "bad", "type": "fact", "status": "invalid", "grounding_status": "ungrounded", "kept_refs": ["file:/foreign"]},
                ],
            )
        assert persistence.list_event_claims("t1", event_id, version["id"]) == []
        assert persistence.get_event_version("t1", event_id, version["id"])["status"] == "running"

    def test_event_version_allowlist_snapshot_is_not_rewritten(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:1:X", "seed", None, None, None)
        version = persistence.create_event_version("t1", event_id, None, [], ["file:/b", "file:/a"], "hash", 0, False, "event-v1")
        persistence.mark_event_version_running("t1", event_id, version["id"])
        persistence.complete_event_version_bundle("t1", event_id, version["id"], "title", "summary", ["file:/b"], "valid", [], "review_pending", "model", [{"text": "c", "type": "fact", "status": "review_pending", "grounding_status": "grounded", "kept_refs": ["file:/b"]}])
        persistence.unlink_evidence_for_task("t1", event_id, "file:/b")
        stored = persistence.get_event_version("t1", event_id, version["id"])
        assert json.loads(stored["input_evidence_refs"]) == ["file:/a", "file:/b"]
        assert persistence.list_event_claims("t1", event_id, version["id"])[0]["evidence_refs"][0]["evidence_key"] == "file:/b"

    def test_event_claim_grounding_statuses_and_allowlist(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:1:X", "seed", None, None, None)
        version = persistence.create_event_version("t1", event_id, None, [], ["file:/a"], "hash", 0, False, "event-v1")
        persistence.mark_event_version_running("t1", event_id, version["id"])
        with pytest.raises(ValueError, match="allowlist"):
            persistence.complete_event_version_bundle(
                "t1", event_id, version["id"], "title", "summary", ["file:/a"],
                "valid", [], "review_pending", "model", [{
                    "text": "bad", "type": "fact", "status": "invalid",
                    "grounding_status": "partially_grounded", "kept_refs": ["file:/not-allowed"],
                }],
            )
        assert persistence.list_event_claims("t1", event_id, version["id"]) == []

    def test_needs_refresh_matches_accepted_source_revision(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:1:X", "seed", None, None, None)
        version = self._event_version(persistence, event_id)
        persistence.accept_event_version("t1", event_id, version["id"])
        event = persistence.get_event("t1", event_id)
        assert event["needs_refresh"] == 0
        assert version["source_revision"] == event["semantic_revision"]
        persistence.invalidate_event_semantics("t1", event_id)
        event = persistence.get_event("t1", event_id)
        assert event["needs_refresh"] == 1
        assert version["source_revision"] < event["semantic_revision"]

    def test_stale_event_version_cannot_accept(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:1:X", "seed", None, None, None)
        version = self._event_version(persistence, event_id)
        persistence.invalidate_event_semantics("t1", event_id)
        with pytest.raises(ValueError, match="stale"):
            persistence.accept_event_version("t1", event_id, version["id"])
        assert persistence.get_event_version("t1", event_id, version["id"])["status"] == "review_pending"

    def test_event_version_requires_accepted_inputs_by_default(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:1:X", "seed", None, None, None)
        analysis = persistence.create_analysis_version("t1", "file:/a", "file", None, None, None, None, None, [])
        persistence.mark_analysis_running(analysis["id"])
        persistence.complete_analysis(analysis["id"], "d", "s", "valid", [])
        version = persistence.create_event_version("t1", event_id, None, [analysis["id"]], ["file:/a"], "hash", 0, False, "event-v1")
        persistence.mark_event_version_running("t1", event_id, version["id"])
        persistence.complete_event_version("t1", event_id, version["id"], "title", "summary", ["file:/a"], "valid", [], "review_pending", "model")
        with pytest.raises(ValueError, match="input analysis"):
            persistence.accept_event_version("t1", event_id, version["id"])
        persistence.accept_analysis("t1", analysis["id"])
        with pytest.raises(VersionConflict, match="stale"):
            persistence.accept_event_version("t1", event_id, version["id"])

    def test_event_version_created_after_analysis_acceptance_is_acceptable(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:1:X", "seed", None, None, None)
        analysis = persistence.create_analysis_version("t1", "file:/a", "file", None, None, None, None, None, [])
        persistence.mark_analysis_running(analysis["id"])
        persistence.complete_analysis(analysis["id"], "d", "s", "valid", [])
        persistence.accept_analysis("t1", analysis["id"])
        event = persistence.get_event("t1", event_id)
        version = persistence.create_event_version(
            "t1", event_id, None, [analysis["id"]], ["file:/a"], "hash",
            event["semantic_revision"], False, "event-v1",
        )
        persistence.mark_event_version_running("t1", event_id, version["id"])
        persistence.complete_event_version("t1", event_id, version["id"], "title", "summary", ["file:/a"], "valid", [], "review_pending", "model")
        assert persistence.accept_event_version("t1", event_id, version["id"])["status"] == "accepted"

    def test_event_version_numbers_are_task_scoped(self, tmp_path):
        event_id = "event-same"
        db_a = InvestigationPersistence(tmp_path / "a.db")
        db_b = InvestigationPersistence(tmp_path / "b.db")
        db_a.upsert_seed_event("task-a", "cluster:v1:1:X", "a", None, None, None)
        db_b.upsert_seed_event("task-b", "cluster:v1:1:X", "b", None, None, None)
        with db_a._connect() as conn:
            conn.execute("INSERT INTO investigation_events(id, task_id, title, source, created_at, updated_at) VALUES (?, ?, ?, 'analyst', 1, 1)", (event_id, "task-a", "a"))
        with db_b._connect() as conn:
            conn.execute("INSERT INTO investigation_events(id, task_id, title, source, created_at, updated_at) VALUES (?, ?, ?, 'analyst', 1, 1)", (event_id, "task-b", "b"))
        version_a = db_a.create_event_version("task-a", event_id, None, [], [], "a", 0, False, "v")
        version_b = db_b.create_event_version("task-b", event_id, None, [], [], "b", 0, False, "v")
        assert version_a["version"] == version_b["version"] == 1

    def test_new_event_requires_refresh(self, persistence):
        event_id = persistence.create_event("t1", "new", None, "analyst")
        event = persistence.get_event("t1", event_id)
        assert event["needs_refresh"] == 1
        assert persistence.effective_event_version("t1", event_id)[0] is None

    def test_analysis_rejection_invalidates_exact_dependent_event(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:2:X", "seed", None, None, None)
        analysis = persistence.create_analysis_version("t1", "file:/a", "file", None, None, None, None, None, [])
        persistence.mark_analysis_running(analysis["id"])
        persistence.complete_analysis(analysis["id"], "d", "s", "valid", [])
        persistence.accept_analysis("t1", analysis["id"])
        persistence.link_evidence_for_task("t1", event_id, "file:/a", "file", "primary", "analyst")
        event = persistence.get_event("t1", event_id)
        version = persistence.create_event_version("t1", event_id, None, [analysis["id"]], ["file:/a"], "hash", event["semantic_revision"], False, "event-v1")
        persistence.mark_event_version_running("t1", event_id, version["id"])
        persistence.complete_event_version("t1", event_id, version["id"], "title", "summary", ["file:/a"], "valid", [], "review_pending", "model")
        persistence.accept_event_version("t1", event_id, version["id"])
        before = persistence.get_event("t1", event_id)
        persistence.reject_analysis("t1", analysis["id"])
        after = persistence.get_event("t1", event_id)
        assert after["semantic_revision"] == before["semantic_revision"] + 1
        assert after["needs_refresh"] == 1
        assert persistence.get_event_version("t1", event_id, version["id"])["status"] == "accepted"
        assert persistence.effective_event_version("t1", event_id)[0] is None

    def test_pending_event_input_cannot_be_accepted_after_replacement(self, persistence):
        event_id, _ = persistence.upsert_seed_event("t1", "cluster:v1:1:X", "seed", None, None, None)
        pending = persistence.create_analysis_version("t1", "file:/a", "file", None, None, None, None, None, [])
        persistence.mark_analysis_running(pending["id"])
        persistence.complete_analysis(pending["id"], "d", "s", "valid", [])
        version = persistence.create_event_version("t1", event_id, None, [pending["id"]], ["file:/a"], "hash", 0, True, "event-v1")
        persistence.mark_event_version_running("t1", event_id, version["id"])
        persistence.complete_event_version("t1", event_id, version["id"], "title", "summary", ["file:/a"], "valid", [], "review_pending", "model")
        replacement = persistence.create_analysis_version("t1", "file:/a", "file", None, None, None, None, None, [])
        persistence.mark_analysis_running(replacement["id"])
        persistence.complete_analysis(replacement["id"], "d2", "s2", "valid", [])
        persistence.accept_analysis("t1", replacement["id"])
        with pytest.raises(ValueError, match="replaced"):
            persistence.accept_event_version("t1", event_id, version["id"])
