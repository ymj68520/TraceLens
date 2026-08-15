"""Route-level tests for the Investigation Workbench API."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from httpserver.routes import investigation as investigation_routes
from httpserver.services.investigation_service import (
    InvestigationService,
    make_cluster_key,
    make_file_evidence_key,
)
from httpserver.services.report_dataset import DatasetValidation, ReportDataset


TASK_ID = "task-inv-1"


@pytest.fixture
def task_env(tmp_path):
    """Build a synthetic task: files.db + events.db + investigation service."""
    task_dir = tmp_path / TASK_ID
    task_dir.mkdir()
    files_db = task_dir / "files.db"
    events_db = task_dir / "events.db"

    with sqlite3.connect(files_db) as conn:
        conn.execute(
            """CREATE TABLE files (
                id INTEGER PRIMARY KEY, inode INTEGER, name TEXT, path TEXT,
                size INTEGER, extension TEXT, category TEXT, type TEXT,
                mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
                llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
                llm_analyzed_at INTEGER, llm_model_used TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE case_analysis (
                task_id TEXT PRIMARY KEY, case_description TEXT,
                filtered_files TEXT, case_report TEXT,
                created_at INTEGER, updated_at INTEGER
            )"""
        )
        conn.execute(
            "INSERT INTO files VALUES (1, 100, 'secret.xlsx', '/docs/secret.xlsx',"
            " 2048, '.xlsx', 'documents', 'application/xlsx', 1640000100, 1640000050,"
            " 0, 'md5abc', '敏感表格', '包含服务器IP的表格', 'ip,server', 1640000200, 'gpt')"
        )
        conn.execute(
            "INSERT INTO files VALUES (2, 101, 'notes.txt', '/docs/notes.txt',"
            " 512, '.txt', 'documents', 'text/plain', 1640000120, 1640000060,"
            " 0, 'md5def', NULL, NULL, NULL, NULL, NULL)"
        )
        conn.execute(
            "INSERT INTO case_analysis VALUES (?, '案件背景描述', '[]', NULL, 1, 1)",
            (TASK_ID,),
        )

    # cluster: time_window = 1640000100 // 60 = 27333335
    with sqlite3.connect(events_db) as conn:
        conn.execute(
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY, file_path TEXT, inode INTEGER,
                event_type TEXT, timestamp INTEGER, task_id TEXT,
                llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
                llm_analyzed_at INTEGER, llm_model_used TEXT, llm_is_relevant INTEGER
            )"""
        )
        conn.execute(
            "INSERT INTO events VALUES (1, '/docs/secret.xlsx', 100, 'MODIFIED',"
            " 1640000100, ?, '大量文件修改', '检测到密集文件修改活动', NULL, 1640000300,"
            " 'gpt', 1)",
            (TASK_ID,),
        )
        conn.execute(
            "INSERT INTO events VALUES (2, '/docs/notes.txt', 101, 'MODIFIED',"
            " 1640000110, ?, '大量文件修改', '检测到密集文件修改活动', NULL, 1640000300,"
            " 'gpt', 1)",
            (TASK_ID,),
        )

    cpp_backend = MagicMock()
    cpp_backend.get_task = AsyncMock(return_value={
        "id": TASK_ID,
        "output_files_db": str(files_db),
        "output_events_db": str(events_db),
        "output_raw_db": "",
    })

    async def analyze_mock(**kwargs):
        await asyncio.sleep(0)
        return {
            "analysis": {"description": json.dumps({
                "summary": "二次分析摘要",
                "description": "二次分析详细描述",
                "claims": [
                    {"text": "文件包含服务器IP", "type": "fact",
                     "evidence_refs": [make_file_evidence_key("/docs/secret.xlsx")]},
                    {"text": "可能用于远程登录", "type": "inference",
                     "evidence_refs": ["file:/nonexistent"]},
                ],
                "entities": [
                    {"local_id": "e1", "type": "FILE", "value": "secret.xlsx"},
                    {"local_id": "e2", "type": "IP", "value": "10.10.1.15"},
                ],
                "relations": [
                    {"source": "e1", "target": "e2", "type": "contains_ip", "kind": "observed"},
                ],
            }, ensure_ascii=False)},
            "model": "test-model",
        }

    llm_service = MagicMock()
    llm_service.analyze = AsyncMock(side_effect=analyze_mock)

    service = InvestigationService(
        cpp_backend=cpp_backend, llm_service=llm_service, graphiti_service=None
    )
    investigation_routes._service = service
    yield service
    investigation_routes._service = None


@pytest.fixture
def client(test_client, task_env):
    return test_client


BASE = f"/api/investigation/{TASK_ID}"
SECRET_KEY = make_file_evidence_key("/docs/secret.xlsx")


def _logical_snapshot(db_path):
    tables = {
        "events": "SELECT id, task_id, title, summary, needs_refresh, semantic_revision, review_status FROM investigation_events ORDER BY id",
        "event_evidence": "SELECT event_id, evidence_key, role, source, rationale FROM investigation_event_evidence ORDER BY event_id, evidence_key",
        "snapshots": "SELECT task_id, evidence_key, source_hash, source_size, source_mtime FROM evidence_snapshots ORDER BY task_id, evidence_key",
        "notes": "SELECT task_id, target_type, target_key, content, author FROM analyst_notes ORDER BY task_id, target_type, target_key",
        "analysis_versions": "SELECT id, task_id, evidence_key, version, status, grounding_status, input_analysis_ids, input_evidence_refs FROM evidence_analysis_versions ORDER BY id",
        "analysis_claims": "SELECT id, analysis_id, claim_text, claim_type, grounding_status FROM evidence_analysis_claims ORDER BY id",
        "claim_evidence": "SELECT claim_id, evidence_key, relation, rationale FROM claim_evidence ORDER BY claim_id, evidence_key",
        "event_versions": "SELECT id, task_id, event_id, version, status, source_revision, input_analysis_ids, input_evidence_refs, evidence_refs FROM investigation_event_versions ORDER BY id",
        "event_claims": "SELECT id, task_id, event_id, event_version_id, claim_text, claim_type, status, grounding_status FROM event_claims ORDER BY id",
        "event_claim_evidence": "SELECT claim_id, evidence_key, relation, rationale FROM event_claim_evidence ORDER BY claim_id, evidence_key",
        "report_evidence": "SELECT task_id, evidence_key, usage, analysis_id FROM report_evidence ORDER BY task_id, evidence_key",
    }
    with sqlite3.connect(db_path) as conn:
        return {name: conn.execute(sql).fetchall() for name, sql in tables.items()}


class TestCrossTaskOpaqueIsolation:
    def test_in_memory_job_lookup_is_task_scoped(self, task_env):
        service = task_env
        service._jobs["job-a"] = {"task_id": TASK_ID, "status": "running"}
        assert service.get_job(TASK_ID, "job-a")["status"] == "running"
        assert service.get_job("other-task", "job-a") is None


class TestBootstrapFlow:
    def test_overview_then_bootstrap_idempotent(self, client):
        resp = client.get(BASE)
        assert resp.status_code == 200
        overview = resp.json()
        assert overview["initialized"] is False

        resp = client.post(f"{BASE}/bootstrap", json={})
        assert resp.status_code == 200
        first = resp.json()
        assert first["initialized"] is True
        assert first["event_count"] == 1
        assert first["new_events"] == 1

        # second bootstrap must not duplicate the seed event
        resp = client.post(f"{BASE}/bootstrap", json={})
        second = resp.json()
        assert second["event_count"] == 1
        assert second["new_events"] == 0

    def test_events_and_evidence(self, client):
        client.post(f"{BASE}/bootstrap", json={})
        resp = client.get(f"{BASE}/events")
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) == 1
        event = events[0]
        assert event["source"] == "cluster_seed"
        assert event["review_status"] == "draft"
        assert event["evidence_counts"]["total"] >= 1

        resp = client.get(f"{BASE}/events/{event['id']}")
        assert resp.status_code == 200
        detail = resp.json()["event"]
        assert detail["seed_title"]

        resp = client.get(f"{BASE}/events/{event['id']}/evidence")
        assert resp.status_code == 200
        evidence = resp.json()["evidence"]
        keys = {e["evidence_key"] for e in evidence}
        assert SECRET_KEY in keys

    def test_event_review(self, client):
        client.post(f"{BASE}/bootstrap", json={})
        event = client.get(f"{BASE}/events").json()["events"][0]
        resp = client.post(
            f"{BASE}/events/{event['id']}/review", json={"status": "confirmed"}
        )
        assert resp.status_code == 200
        assert resp.json()["event"]["review_status"] == "confirmed"

        resp = client.post(
            f"{BASE}/events/{event['id']}/review", json={"status": "nope"}
        )
        assert resp.status_code == 422


class TestEvidenceDetailAndNotes:
    def test_detail_captures_snapshot(self, client):
        client.post(f"{BASE}/bootstrap", json={})
        resp = client.get(f"{BASE}/evidence/detail", params={"evidence_key": SECRET_KEY})
        assert resp.status_code == 200
        detail = resp.json()["evidence"]
        assert detail["snapshot"]["initial_description"] == "包含服务器IP的表格"
        assert detail["snapshot"]["source_hash"] == "md5abc"
        assert detail["snapshot"]["source_size"] == 2048

    def test_detail_unknown_evidence_404(self, client):
        client.post(f"{BASE}/bootstrap", json={})
        resp = client.get(
            f"{BASE}/evidence/detail",
            params={"evidence_key": make_file_evidence_key("/ghost.txt")},
        )
        assert resp.status_code == 404

    def test_note_roundtrip(self, client):
        client.post(f"{BASE}/bootstrap", json={})
        resp = client.post(f"{BASE}/notes", json={
            "target_type": "evidence",
            "target_key": SECRET_KEY,
            "content": "该IP是核心受攻击服务器",
        })
        assert resp.status_code == 200
        resp = client.get(
            f"{BASE}/notes",
            params={"target_type": "evidence", "target_key": SECRET_KEY},
        )
        assert resp.json()["note"]["content"] == "该IP是核心受攻击服务器"


class TestSecondaryAnalysis:
    def test_analyze_job_and_grounding(self, client):
        client.post(f"{BASE}/bootstrap", json={})
        events = client.get(f"{BASE}/events").json()["events"]

        resp = client.post(f"{BASE}/evidence/analyze", json={
            "evidence_key": SECRET_KEY,
            "analyst_note": "请重点判断是否为凭据清单",
            "event_id": events[0]["id"],
        })
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        # TestClient runs the asyncio task inline; poll job
        job = client.get(f"{BASE}/analysis-jobs/{job_id}").json()["job"]
        assert job["status"] in ("completed", "running", "queued")

        versions = client.get(
            f"{BASE}/evidence/analysis", params={"evidence_key": SECRET_KEY}
        ).json()["versions"]
        assert len(versions) == 1
        version = versions[0]
        assert version["version"] == 1
        # LLM referenced one unknown evidence → partially grounded
        assert version["grounding_status"] == "partially_grounded"
        assert version["analyst_note_snapshot"] == "请重点判断是否为凭据清单"
        assert version["input_hash"]
        assert version["claims"]
        by_text = {c["claim_text"]: c for c in version["claims"]}
        assert by_text["文件包含服务器IP"]["grounding_status"] == "grounded"
        assert by_text["可能用于远程登录"]["grounding_status"] == "ungrounded"
        assert by_text["可能用于远程登录"]["type"] == "inference"
        assert len(version["entities"]) == 2
        assert len(version["relations"]) == 1

        # partially grounded requires acknowledgement
        resp = client.post(f"{BASE}/analysis/{version['id']}/accept", json={})
        assert resp.status_code == 422
        resp = client.post(
            f"{BASE}/analysis/{version['id']}/accept",
            json={"acknowledge_warnings": True},
        )
        assert resp.status_code == 200
        assert resp.json()["analysis"]["status"] == "accepted"

        # reject flow on a new version
        resp = client.post(f"{BASE}/evidence/analyze", json={
            "evidence_key": SECRET_KEY,
        })
        v2_id = resp.json()["analysis_id"]
        resp = client.post(f"{BASE}/analysis/{v2_id}/reject")
        assert resp.status_code == 200

    def test_analyze_unknown_evidence_422(self, client):
        client.post(f"{BASE}/bootstrap", json={})
        resp = client.post(f"{BASE}/evidence/analyze", json={
            "evidence_key": make_file_evidence_key("/ghost.txt"),
        })
        assert resp.status_code == 422


    def test_event_refresh_without_related_keeps_only_primary(self, client, task_env):
        store = asyncio.run(task_env._persistence(TASK_ID))
        event_id = store.create_event(TASK_ID, "manual", "manual", "analyst")
        store.link_evidence_for_task(TASK_ID, event_id, "file:/docs/secret.xlsx", "file", "primary", "analyst")
        store.link_evidence_for_task(TASK_ID, event_id, "file:/docs/notes.txt", "file", "supporting", "analyst")
        result = asyncio.run(task_env.start_event_refresh(TASK_ID, event_id, include_related_evidence=False))
        version = store.get_event_version(TASK_ID, event_id, result["version_id"])
        refs = set(json.loads(version["input_evidence_refs"]))
        assert "file:/docs/secret.xlsx" in refs
        assert "file:/docs/notes.txt" not in refs
        assert json.loads(version["input_analysis_ids"]) == []

    def test_stale_semantic_version_returns_conflict(self, client):
        client.post(f"{BASE}/bootstrap", json={})
        event = client.get(f"{BASE}/events").json()["events"][0]
        persistence = investigation_routes.get_investigation_service()
        # Create a completed candidate then invalidate its semantic input.
        store = asyncio.run(persistence._persistence(TASK_ID))
        version = store.create_event_version(TASK_ID, event["id"], None, [], [], "hash", 0, False, "event-v1")
        store.mark_event_version_running(TASK_ID, event["id"], version["id"])
        store.complete_event_version(TASK_ID, event["id"], version["id"], "candidate", "summary", [], "valid", [], "review_pending", "model")
        store.invalidate_event_semantics(TASK_ID, event["id"])
        response = client.post(f"{BASE}/events/{event['id']}/versions/{version['id']}/accept")
        assert response.status_code == 409


class TestHistoricalClaimProvenance:
    def test_exact_claim_lookup_is_read_only_and_not_effective(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        event = client.get(f"{BASE}/events").json()["events"][0]
        store = asyncio.run(task_env._persistence(TASK_ID))
        version = store.create_event_version(
            TASK_ID, event["id"], None, [], [SECRET_KEY], "claim-route", 0, False, "event-v1"
        )
        store.mark_event_version_running(TASK_ID, event["id"], version["id"])
        store.complete_event_version_bundle(
            TASK_ID, event["id"], version["id"], "historical", "summary", [SECRET_KEY],
            "valid", [], "review_pending", "model", [{
                "text": "historical route claim",
                "type": "fact",
                "status": "review_pending",
                "grounding_status": "grounded",
                "kept_refs": [SECRET_KEY],
                "relation": "supports",
            }],
        )
        claim = store.list_event_claims(TASK_ID, event["id"], version["id"])[0]
        with store._connect() as connection:
            connection.execute(
                "UPDATE event_claim_evidence SET relation = ?, rationale = ? WHERE claim_id = ?",
                ("contradicts", "route rationale", claim["id"]),
            )
        before = store.db_path.read_bytes()

        response = client.get(f"{BASE}/claims/{claim['id']}")

        assert response.status_code == 200
        returned = response.json()["claim"]
        assert returned["claim_id"] == claim["id"]
        assert returned["claim_text"] == "historical route claim"
        assert returned["event_version_id"] == version["id"]
        assert returned["evidence_links"] == [{
            "evidence_key": SECRET_KEY,
            "relation": "contradicts",
            "rationale": "route rationale",
        }]
        assert store.effective_event_claims(TASK_ID, event["id"]) == []
        assert store.db_path.read_bytes() == before

    def test_event_claims_get_is_version_scoped(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        event = client.get(f"{BASE}/events").json()["events"][0]
        store = asyncio.run(task_env._persistence(TASK_ID))
        version = store.create_event_version(
            TASK_ID, event["id"], None, [], [SECRET_KEY], "claims-get", 0, False, "event-v1"
        )
        store.mark_event_version_running(TASK_ID, event["id"], version["id"])
        store.complete_event_version_bundle(
            TASK_ID, event["id"], version["id"], "candidate", "summary", [SECRET_KEY],
            "valid", [], "review_pending", "model", [{
                "text": "version-scoped claim",
                "type": "fact",
                "status": "review_pending",
                "grounding_status": "grounded",
                "kept_refs": [SECRET_KEY],
                "relation": "supports",
            }],
        )

        response = client.get(
            f"{BASE}/events/{event['id']}/versions/{version['id']}/claims"
        )

        assert response.status_code == 200
        assert response.json()["success"] is True
        claims = response.json()["claims"]
        assert len(claims) == 1
        assert claims[0]["claim_text"] == "version-scoped claim"
        assert claims[0]["evidence_refs"] == [{
            "evidence_key": SECRET_KEY,
            "relation": "supports",
            "rationale": None,
        }]

        assert client.get(
            f"{BASE}/events/{event['id']}/versions/missing-version/claims"
        ).status_code == 404
        assert client.get(
            f"{BASE}/events/missing-event/versions/{version['id']}/claims"
        ).status_code == 404
        assert client.get(
            f"/api/investigation/other-task/events/{event['id']}/versions/{version['id']}/claims"
        ).status_code == 404

        client.post(f"{BASE}/bootstrap", json={})
        missing = client.get(f"{BASE}/claims/not-a-claim")
        cross_task = client.get(f"/api/investigation/other-task/claims/not-a-claim")

        assert missing.status_code == 404
        assert cross_task.status_code == 404
        assert missing.json()["detail"] == "claim provenance not found"
        assert cross_task.json()["detail"] == missing.json()["detail"]


class TestLinkUnlinkAndReport:
    def test_link_unlink(self, client):
        client.post(f"{BASE}/bootstrap", json={})
        event = client.get(f"{BASE}/events").json()["events"][0]
        notes_key = make_file_evidence_key("/docs/notes.txt")

        resp = client.post(
            f"{BASE}/events/{event['id']}/evidence/link",
            json={"evidence_key": notes_key, "role": "primary"},
        )
        assert resp.status_code == 200

        resp = client.post(
            f"{BASE}/events/{event['id']}/evidence/unlink",
            json={"evidence_key": notes_key},
        )
        assert resp.status_code == 200
        assert resp.json()["unlinked"] is True

        # linking an unresolvable evidence fails
        resp = client.post(
            f"{BASE}/events/{event['id']}/evidence/link",
            json={"evidence_key": make_file_evidence_key("/ghost.txt"), "role": "primary"},
        )
        assert resp.status_code == 422

    def test_report_evidence_binding(self, client):
        client.post(f"{BASE}/bootstrap", json={})

        # without accepted analysis → analysis_id NULL
        resp = client.put(f"{BASE}/report-evidence", json={
            "evidence_key": SECRET_KEY, "usage": "main", "report_note": "关键证据",
        })
        assert resp.status_code == 200
        entry = resp.json()["report_evidence"]
        assert entry["analysis_id"] is None

        # after accepted analysis → rebound to accepted id
        client.post(f"{BASE}/evidence/analyze", json={"evidence_key": SECRET_KEY})
        version = client.get(
            f"{BASE}/evidence/analysis", params={"evidence_key": SECRET_KEY}
        ).json()["versions"][0]
        client.post(
            f"{BASE}/analysis/{version['id']}/accept",
            json={"acknowledge_warnings": True},
        )
        resp = client.put(f"{BASE}/report-evidence", json={
            "evidence_key": SECRET_KEY, "usage": "main",
        })
        assert resp.json()["report_evidence"]["analysis_id"] == version["id"]

        resp = client.post(
            f"{BASE}/report-evidence/remove", json={"evidence_key": SECRET_KEY}
        )
        assert resp.json()["removed"] is True

    def test_report_dataset_returns_blocked_projection_without_writing(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        before = client.get(f"{BASE}/report-dataset")
        assert before.status_code == 200
        assert before.json()["validation"]["status"] == "valid"

        client.put(f"{BASE}/report-evidence", json={
            "evidence_key": SECRET_KEY, "usage": "main",
        })
        persistence = task_env._persistence_cache[TASK_ID]
        event = persistence.list_events(TASK_ID)[0]
        persistence.set_event_review_status(TASK_ID, event["id"], "confirmed")
        version = persistence.create_event_version(
            TASK_ID, event["id"], None, [], [SECRET_KEY], "route-dataset", event["semantic_revision"], False, "event-v1"
        )
        persistence.mark_event_version_running(TASK_ID, event["id"], version["id"])
        persistence.complete_event_version_bundle(
            TASK_ID, event["id"], version["id"], "title", "summary", [SECRET_KEY],
            "valid", [], "review_pending", "model", [{
                "text": "missing provenance", "type": "fact", "status": "review_pending",
                "grounding_status": "ungrounded", "kept_refs": [],
            }],
        )
        persistence.accept_event_version(TASK_ID, event["id"], version["id"])
        claim = persistence.list_event_claims(TASK_ID, event["id"], version["id"])[0]
        persistence.review_event_claim(TASK_ID, event["id"], version["id"], claim["id"], "accepted")

        response = client.get(f"{BASE}/report-dataset")

        assert response.status_code == 200
        body = response.json()
        assert {"events", "report_evidence", "validation", "report_dataset_hash"} <= body.keys()
        assert body["validation"]["status"] == "blocked"
        assert any(
            error["code"] == "CLAIM_EVIDENCE_LINK_MISSING"
            for error in body["validation"]["errors"]
        )

        citations = client.get(f"{BASE}/report-citations")
        assert citations.status_code == 200
        citation_body = citations.json()
        assert citation_body["validation"]["status"] == "blocked"
        assert citation_body["allowed_citation_ids"] == []
        assert any(
            error["code"] == "UPSTREAM_DATASET_BLOCKED"
            for error in citation_body["validation"]["errors"]
        )

    def test_report_citations_returns_read_only_valid_graph(self, client):
        client.post(f"{BASE}/bootstrap", json={})

        response = client.get(f"{BASE}/report-citations")

        assert response.status_code == 200
        body = response.json()
        assert body["dataset_hash"]
        assert body["citation_graph_hash"]
        assert body["validation"]["status"] == "valid"
        assert body["allowed_citation_ids"] == []

    def test_report_section_render_returns_pending_candidate(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        raw = json.dumps({
            "section_id": "SEC-001",
            "used_claim_ids": [],
            "paragraphs": [],
        })
        task_env._llm_service.analyze = AsyncMock(return_value={
            "analysis": {"description": raw},
            "model": "render-model",
        })

        response = client.post(
            f"{BASE}/report-section-render", json={"section_id": "SEC-001"}
        )

        assert response.status_code == 200
        candidate = response.json()["candidate"]
        assert candidate["status"] == "render_pending_validation"
        assert candidate["render_version"] == 1
        assert candidate["render_output_hash"]
        task_env._llm_service.analyze.assert_awaited_once()

    def test_report_section_render_invalid_output_is_persisted(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        raw = json.dumps({
            "section_id": "SEC-001",
            "used_claim_ids": ["CLAIM-NOT-ALLOWED"],
            "paragraphs": [{
                "text": "越界",
                "claim_ids": ["CLAIM-NOT-ALLOWED"],
                "citation_ids": [],
            }],
        })
        task_env._llm_service.analyze = AsyncMock(return_value={
            "analysis": {"description": raw},
            "model": "render-model",
        })

        response = client.post(
            f"{BASE}/report-section-render", json={"section_id": "SEC-001"}
        )

        assert response.status_code == 200
        candidate = response.json()["candidate"]
        assert candidate["status"] == "invalid"
        assert any(
            error["code"] == "RENDER_CLAIM_NOT_ALLOWED"
            for error in candidate["validation_errors"]
        )

    def test_report_section_render_llm_failure_is_persisted(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        task_env._llm_service.analyze = AsyncMock(
            side_effect=RuntimeError("render service unavailable")
        )

        response = client.post(
            f"{BASE}/report-section-render", json={"section_id": "SEC-001"}
        )

        assert response.status_code == 200
        candidate = response.json()["candidate"]
        assert candidate["status"] == "failed"
        assert candidate["error_message"] == "render service unavailable"

    def test_blocked_section_plan_returns_409_without_candidate(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        blocked = ReportDataset(
            task_id=TASK_ID,
            generated_at="2026-08-13T00:00:00+00:00",
            validation=DatasetValidation(status="blocked"),
            report_dataset_hash="",
        )
        blocked.report_dataset_hash = blocked.compute_hash()
        task_env._report_dataset_builder.build = AsyncMock(return_value=blocked)

        response = client.post(
            f"{BASE}/report-section-render", json={"section_id": "SEC-001"}
        )

        assert response.status_code == 409
        assert any(
            error["code"] == "SECTION_UPSTREAM_DATASET_BLOCKED"
            for error in response.json()["detail"]
        )
        task_env._llm_service.analyze.assert_not_awaited()
        db_path = task_env._persistence_cache[TASK_ID].db_path
        with sqlite3.connect(db_path) as conn:
            assert conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'section_render_candidates'"
            ).fetchone() is None
    def test_report_section_validation_is_independent_and_does_not_mutate_candidate(
        self, client, task_env
    ):
        client.post(f"{BASE}/bootstrap", json={})
        raw = json.dumps({
            "section_id": "SEC-001",
            "used_claim_ids": [],
            "paragraphs": [],
        })
        task_env._llm_service.analyze = AsyncMock(return_value={
            "analysis": {"description": raw},
            "model": "render-model",
        })
        rendered = client.post(
            f"{BASE}/report-section-render", json={"section_id": "SEC-001"}
        )
        assert rendered.status_code == 200
        before = rendered.json()["candidate"]

        response = client.post(
            f"{BASE}/report-section-validations",
            json={"candidate_id": before["candidate_id"]},
        )

        assert response.status_code == 200
        validation = response.json()["validation"]
        assert validation["status"] == "valid"
        assert validation["validation_version"] == 1
        assert validation["validation_rule_version"] == "report-final-validation-v1"
        assert validation["observed_dataset_hash"]
        assert validation["observed_citation_graph_hash"]
        assert validation["observed_section_plan_hash"]
        assert validation["observed_render_input_hash"] == before["render_input_hash"]
        assert validation["observed_render_output_hash"] == before["render_output_hash"]
        task_env._llm_service.analyze.assert_awaited_once()

        after = task_env._render_repository_cache[TASK_ID].get(before["candidate_id"])
        assert after.to_response_dict() == before
        assert after.status == "render_pending_validation"

    def test_report_section_validation_missing_candidate_is_404(self, client):
        client.post(f"{BASE}/bootstrap", json={})

        response = client.post(
            f"{BASE}/report-section-validations",
            json={"candidate_id": "missing-candidate"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "render candidate not found"
    def test_final_report_empty_sections_assemble_and_publish(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})

        response = client.post(f"{BASE}/final-reports", json={"sections": []})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "valid"
        report = body["report"]
        assert report["status"] == "assembled"
        assert report["report_version"] == 1
        assert [section["section_id"] for section in report["sections"]] == [
            "SEC-001", "SEC-002", "SEC-003", "SEC-004", "SEC-005"
        ]
        assert task_env._llm_service.analyze.await_count == 0

        listed = client.get(f"{BASE}/final-reports")
        assert listed.status_code == 200
        assert [item["report_id"] for item in listed.json()["reports"]] == [
            report["report_id"]
        ]

        detail = client.get(f"{BASE}/final-reports/{report['report_id']}")
        assert detail.status_code == 200
        assert detail.json()["report"]["final_report_hash"] == report["final_report_hash"]

        published = client.post(
            f"{BASE}/final-reports/{report['report_id']}/publish"
        )
        assert published.status_code == 200
        publication = published.json()["publication"]
        assert publication["status"] == "published"
        repeated = client.post(
            f"{BASE}/final-reports/{report['report_id']}/publish"
        )
        assert repeated.status_code == 200
        assert repeated.json()["publication"]["publication_id"] == publication["publication_id"]

        publication_read = client.get(
            f"{BASE}/final-reports/{report['report_id']}/publication"
        )
        assert publication_read.status_code == 200
        assert publication_read.json()["publication"] == publication

    def test_final_report_publication_missing_is_explicit_null(self, client):
        client.post(f"{BASE}/bootstrap", json={})
        response = client.post(f"{BASE}/final-reports", json={"sections": []})
        report = response.json()["report"]

        publication = client.get(f"{BASE}/final-reports/{report['report_id']}/publication")

        assert publication.status_code == 200
        assert publication.json() == {"success": True, "publication": None}
        assert "Unpublished" not in publication.text

    def test_final_report_publication_is_scoped_to_exact_report_version(self, client):
        client.post(f"{BASE}/bootstrap", json={})
        first = client.post(f"{BASE}/final-reports", json={"sections": []}).json()["report"]
        second = client.post(f"{BASE}/final-reports", json={"sections": []}).json()["report"]
        published = client.post(f"{BASE}/final-reports/{first['report_id']}/publish")

        assert published.status_code == 200
        first_read = client.get(f"{BASE}/final-reports/{first['report_id']}/publication")
        second_read = client.get(f"{BASE}/final-reports/{second['report_id']}/publication")

        assert first_read.status_code == 200
        assert first_read.json()["publication"]["report_id"] == first["report_id"]
        assert first_read.json()["publication"]["report_version"] == first["report_version"]
        assert first_read.json()["publication"]["final_report_hash"] == first["final_report_hash"]
        assert second_read.status_code == 200
        assert second_read.json()["publication"] is None

    def test_final_report_publication_missing_report_is_opaque_404(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})

        response = client.get(f"{BASE}/final-reports/missing-report/publication")

        assert response.status_code == 404
        assert response.json()["detail"] == "final report not found"

    def test_final_report_publication_unknown_and_cross_task_are_opaque_404(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        report = client.post(f"{BASE}/final-reports", json={"sections": []}).json()["report"]
        client.post(f"{BASE}/final-reports/{report['report_id']}/publish")

        unknown_task = client.get(
            f"/api/investigation/unknown-task/final-reports/{report['report_id']}/publication"
        )
        cross_task = client.get(
            f"/api/investigation/other-task/final-reports/{report['report_id']}/publication"
        )

        assert unknown_task.status_code == 404
        assert cross_task.status_code == 404
        assert unknown_task.json()["detail"] == "final report not found"
        assert cross_task.json()["detail"] == unknown_task.json()["detail"]

    def test_final_report_publication_missing_database_is_opaque_404(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        db_path = task_env._persistence_cache[TASK_ID].db_path
        db_path.unlink()

        response = client.get(f"{BASE}/final-reports/report-id/publication")

        assert response.status_code == 404
        assert response.json()["detail"] == "final report not found"

    def test_final_report_publication_read_does_not_mutate_database(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        response = client.post(f"{BASE}/final-reports", json={"sections": []})
        report = response.json()["report"]
        db_path = task_env._persistence_cache[TASK_ID].db_path

        def database_bytes():
            with open(db_path, "rb") as database:
                return database.read()

        before = database_bytes()
        publication = client.get(f"{BASE}/final-reports/{report['report_id']}/publication")
        after = database_bytes()

        assert publication.status_code == 200
        assert publication.json()["publication"] is None
        assert after == before

    def test_final_report_publication_storage_failure_is_not_null(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        response = client.post(f"{BASE}/final-reports", json={"sections": []})
        report = response.json()["report"]
        db_path = task_env._persistence_cache[TASK_ID].db_path
        with sqlite3.connect(db_path) as connection:
            connection.execute("DROP TABLE final_report_publications")
            connection.commit()

        publication = client.get(f"{BASE}/final-reports/{report['report_id']}/publication")

        assert publication.status_code == 503
        assert publication.json()["detail"] == "publication storage could not be read"
        with sqlite3.connect(db_path) as connection:
            assert connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='final_report_publications'"
            ).fetchone() is None

    def test_final_report_publication_malformed_report_storage_fails_closed(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        response = client.post(f"{BASE}/final-reports", json={"sections": []})
        assert response.status_code == 200
        db_path = task_env._persistence_cache[TASK_ID].db_path
        with sqlite3.connect(db_path) as connection:
            connection.execute("DROP TABLE final_report_versions")
            connection.execute("CREATE TABLE final_report_versions (report_id TEXT PRIMARY KEY)")
            connection.commit()

        publication = client.get(f"{BASE}/final-reports/report-id/publication")

        assert publication.status_code == 503
        assert publication.json()["detail"] == "publication storage could not be read"

    def test_invalid_final_report_does_not_allocate_version(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})

        response = client.post(
            f"{BASE}/final-reports",
            json={
                "sections": [{
                    "section_id": "SEC-001",
                    "candidate_id": "candidate-not-allowed-for-empty-section",
                    "validation_id": "validation-not-allowed-for-empty-section",
                }]
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "invalid"
        assert body["report"] is None
        db_path = task_env._persistence_cache[TASK_ID].db_path
        with sqlite3.connect(db_path) as conn:
            assert conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='final_report_versions'"
            ).fetchone() is None

    def test_final_report_presentation_routes_are_exact_and_read_only(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        response = client.post(f"{BASE}/final-reports", json={"sections": []})
        report = response.json()["report"]
        db_path = task_env._persistence_cache[TASK_ID].db_path
        before = db_path.read_bytes()

        for representation, expected_type in (
            ("markdown", "text/markdown"),
            ("html", "text/html"),
            ("print", "text/html"),
        ):
            result = client.get(
                f"{BASE}/final-reports/{report['report_id']}/{representation}"
            )
            assert result.status_code == 200
            assert result.headers["content-type"].startswith(expected_type)
            assert result.headers["x-tracelens-presentation-version"] == "report-presentation-v1"
            assert result.headers["x-tracelens-final-report-hash"] == report["final_report_hash"]
            assert result.headers["x-tracelens-presentation-sha256"] == __import__("hashlib").sha256(result.content).hexdigest()
            assert result.headers["x-content-type-options"] == "nosniff"
            assert result.headers["referrer-policy"] == "no-referrer"
            if representation == "markdown":
                assert result.headers["content-disposition"].startswith("attachment;")
            else:
                assert result.headers["content-disposition"].startswith("inline;")
            if representation == "print":
                assert b"@media print" in result.content

        assert db_path.read_bytes() == before

    def test_final_report_presentation_is_opaque_for_missing_and_cross_task(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        report = client.post(f"{BASE}/final-reports", json={"sections": []}).json()["report"]
        missing = client.get(f"{BASE}/final-reports/missing/markdown")
        cross_task = client.get(
            f"/api/investigation/other-task/final-reports/{report['report_id']}/html"
        )
        assert missing.status_code == 404
        assert cross_task.status_code == 404
        assert missing.json()["detail"] == "final report not found"
        assert cross_task.json()["detail"] == missing.json()["detail"]

    def test_final_report_presentation_fails_closed_for_tampered_hash(self, client, task_env):
        client.post(f"{BASE}/bootstrap", json={})
        report = client.post(f"{BASE}/final-reports", json={"sections": []}).json()["report"]
        db_path = task_env._persistence_cache[TASK_ID].db_path
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE final_report_versions SET final_report_hash = ? WHERE report_id = ?",
                ("tampered", report["report_id"]),
            )
            connection.commit()
        result = client.get(f"{BASE}/final-reports/{report['report_id']}/markdown")
        assert result.status_code == 422
        assert result.json()["detail"] == "final report presentation integrity check failed"
        client.post(f"{BASE}/bootstrap", json={})

        response = client.get(f"{BASE}/final-reports/missing-report")

        assert response.status_code == 404
        assert response.json()["detail"] == "final report not found"


class TestLocalGraph:
    def test_graph_degrades_without_graphiti(self, client):
        client.post(f"{BASE}/bootstrap", json={})
        client.post(f"{BASE}/evidence/analyze", json={"evidence_key": SECRET_KEY})
        resp = client.get(
            f"{BASE}/graph/local", params={"evidence_key": SECRET_KEY}
        )
        assert resp.status_code == 200
        graph = resp.json()
        assert graph["base_available"] is False  # graphiti_service=None
        labels = {n["label"] for n in graph["nodes"]}
        assert "secret.xlsx" in labels
        assert "10.10.1.15" in labels
        assert any(l["relation_type"] == "contains_ip" for l in graph["links"])
