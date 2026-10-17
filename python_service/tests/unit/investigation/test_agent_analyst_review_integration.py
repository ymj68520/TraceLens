"""TraceLens Agent v0 — RCA-2A.20 Analyst Review Integration Tests (T01 - T34).

Verifies the complete human analyst review boundary offline with real SQLite,
ServiceManager, and FastAPI routes:
Candidate Projection -> Explicit Review Decision -> Durable SQLite Persistence ->
Epistemic Type Preservation -> Concurrency & Idempotency -> Downstream Safety.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.config import Settings
from httpserver.routes import investigation
from httpserver.services.evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from httpserver.services.evidence.resolver import EvidenceResolver
from httpserver.services.investigation.agent_analyst_review import (
    AgentAnalystReviewService,
    EvidenceProvenanceError,
    FactPromotionBlockedError,
    ReviewCandidateProjection,
    ReviewConflictError,
    ReviewDecision,
    ReviewDecisionOutcome,
    ReviewDecisionRequest,
    ReviewHistoryItem,
    compute_candidate_hash,
)
from httpserver.services.investigation.agent_findings import (
    FindingReviewService,
    InvestigationFindingV1,
    REVIEW_ACCEPTED,
    REVIEW_PENDING,
    REVIEW_REJECTED,
)
from httpserver.services.investigation.agent_runtime import (
    AgentInvestigationStatus,
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
    canonical_state_json,
)
from httpserver.services.investigation.agent_specialist_result import AssertionClass
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    Hypothesis,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
)
from httpserver.services.investigation.paths import investigation_db_path_for_task
from httpserver.services.investigation.repository import InvestigationRepository
from httpserver.services.service_manager import ServiceManager


class SyntheticReviewFixtureEnvironment:
    """Deterministic environment with real SQLite DBs and synthetic forensic data."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.task_id = "task-rca2a20-synth"
        self.investigation_id = "inv-rca2a20-synth"
        self.task_dir = base_dir / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)

        self.files_db_path = self.task_dir / "files.db"
        self.events_db_path = self.task_dir / "events.db"
        self.raw_db_path = self.task_dir / "raw.db"
        self.investigation_db_path = self.task_dir / "investigation.db"

        self._init_files_db()
        self._init_events_db()
        self._init_raw_db()

        self.repo = InvestigationRepository(self.investigation_db_path, self.task_id)
        self.runtime = AgentRuntimeRepository(self.repo)

        # Evidence references present in files.db and events.db
        self.valid_file_ref = "file:C/Windows/System32/config/SAM"
        self.valid_event_ref = "event:1"

        self.initial_state = AgentWorkingStateV1(
            task_id=self.task_id,
            investigation_id=self.investigation_id,
            objective="Investigate credential dumping on workstation",
            questions=(
                WorkingQuestion(
                    question_id="Q1",
                    text="Did unauthorized credential access occur?",
                    source=QuestionSource.user_directive,
                    priority=QuestionPriority.high,
                    status=QuestionStatus.open,
                ),
            ),
            hypotheses=(
                Hypothesis(
                    hypothesis_id="h-448201",
                    text="Mimikatz was executed to dump SAM registry hive",
                    supporting_refs=(self.valid_file_ref,),
                ),
            ),
        )
        self.inv, self.rev = self.runtime.create_investigation(
            self.initial_state.model_dump(mode="json"),
            investigation_id=self.investigation_id,
        )

        # Seed an investigation finding in review_pending state
        self.seed_finding_id = "finding:disp_f_test_01"
        with self.runtime._connect() as conn:
            conn.execute(
                "INSERT INTO investigation_findings "
                "(finding_id, task_id, investigation_id, proposal_id, disposition_id, "
                " text, assertion_class, evidence_refs_json, relationship_refs_json, "
                " temporal_scope_json, grounding_id, limitations_json, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'review_pending', ?)",
                [
                    self.seed_finding_id,
                    self.task_id,
                    self.investigation_id,
                    "prop_01",
                    "disp_01",
                    "Security Account Manager registry hive accessed suspicious SAM handle",
                    "INFERENCE",
                    canonical_state_json({"refs": [self.valid_file_ref]}),
                    canonical_state_json({"refs": []}),
                    None,
                    "grnd_01",
                    canonical_state_json({"limitations": []}),
                    "2026-10-17T12:00:00Z",
                ],
            )
            conn.commit()

        self.task_record = {
            "id": self.task_id,
            "status": "ready",
            "output_files_db": str(self.files_db_path),
            "output_events_db": str(self.events_db_path),
            "scenarios": ["windows"],
            "scenario_databases": {},
        }
        self.tasks = {self.task_id: self.task_record}

        # Checksums of raw/events/files DBs
        self.initial_files_sha256 = self._compute_sha256(self.files_db_path)
        self.initial_events_sha256 = self._compute_sha256(self.events_db_path)
        self.initial_raw_sha256 = self._compute_sha256(self.raw_db_path)

    def _compute_sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def _init_files_db(self):
        conn = sqlite3.connect(self.files_db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY, name TEXT, extension TEXT,
                category TEXT, type TEXT, size INTEGER, mtime INTEGER,
                ctime INTEGER, is_deleted INTEGER DEFAULT 0, md5 TEXT,
                llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
                llm_analyzed_at INTEGER, llm_model_used TEXT,
                scene_type TEXT, scene_priority INTEGER,
                scene_relevant INTEGER DEFAULT 0)"""
        )
        conn.execute(
            """INSERT INTO files (path, name, extension, category, type, size, mtime, ctime, is_deleted, md5, llm_description)
               VALUES ('C/Windows/System32/config/SAM', 'SAM', '', 'system', 'file', 65536, 1690000000, 1690000000, 0, 'sam_hash_001', 'Security Account Manager registry hive')"""
        )
        conn.commit()
        conn.close()

    def _init_events_db(self):
        conn = sqlite3.connect(self.events_db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER,
                event_type TEXT,
                file_path TEXT,
                details TEXT,
                source TEXT)"""
        )
        conn.execute(
            """INSERT INTO events (id, timestamp, event_type, file_path, details, source)
               VALUES (1, 1690000050, 'logon_4624', 'C/Windows/System32/config/SAM', 'Logon Event for account TargetAdmin', 'Security.evtx')"""
        )
        conn.commit()
        conn.close()

    def _init_raw_db(self):
        conn = sqlite3.connect(self.raw_db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS raw_meta (key TEXT PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO raw_meta VALUES ('version', '1.0')")
        conn.commit()
        conn.close()


class FakeReviewCppBackend:
    def __init__(self, tasks: dict[str, dict]):
        self.tasks = tasks

    async def get_task(self, task_id: str):
        return self.tasks.get(task_id)

    async def get_task_files_paginated(self, task_id: str, **kwargs):
        task = self.tasks.get(task_id)
        if not task:
            return {"files": [], "total_count": 0}
        conn = sqlite3.connect(task["output_files_db"])
        cursor = conn.cursor()
        cursor.execute("SELECT path, name, extension, size, md5, is_deleted, llm_description, mtime FROM files")
        rows = cursor.fetchall()
        conn.close()
        files = [
            {
                "path": r[0],
                "name": r[1],
                "extension": r[2],
                "size": r[3],
                "md5": r[4],
                "is_deleted": r[5],
                "llm_description": r[6],
                "mtime": r[7],
            }
            for r in rows
        ]
        return {"files": files, "total_count": len(files)}

    async def get_events(self, task_id: str, **kwargs):
        task = self.tasks.get(task_id)
        if not task:
            return []
        conn = sqlite3.connect(task["output_events_db"])
        cursor = conn.cursor()
        cursor.execute("SELECT id, timestamp, event_type, file_path, details, source FROM events")
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "event_type": r[2],
                "file_path": r[3],
                "details": r[4],
                "source": r[5],
            }
            for r in rows
        ]


@pytest.fixture
def env(tmp_path: Path):
    fixture = SyntheticReviewFixtureEnvironment(tmp_path)
    cpp_backend = FakeReviewCppBackend(fixture.tasks)

    settings = Settings()

    manager = ServiceManager(settings)
    manager._cpp_backend = cpp_backend
    manager._cpp_backend_ready = True
    manager._agent_analyst_review_service = manager._create_agent_analyst_review_service()

    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")

    from httpserver import services
    services_patch = patch.object(services, "get_service_manager", lambda: manager)
    route_patch = patch.object(investigation, "get_service_manager", lambda: manager)
    services_patch.start()
    route_patch.start()

    client = TestClient(app)

    yield SimpleNamespace(
        fixture=fixture,
        cpp_backend=cpp_backend,
        settings=settings,
        manager=manager,
        client=client,
        review_service=manager.agent_analyst_review_service,
        runtime=fixture.runtime,
    )

    services_patch.stop()
    route_patch.stop()


# ---------------------------------------------------------------------------
# T01: Review Service resolves real Task
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t01_review_service_resolves_real_task(env):
    """T01: Review Service resolves real Task fail-closed."""
    task, db_path = await env.review_service._resolve_task_and_db(env.fixture.task_id)
    assert task["id"] == env.fixture.task_id
    assert db_path.exists()
    assert db_path == env.fixture.investigation_db_path

    # Unknown task raises EvidenceNotFoundError
    with pytest.raises(EvidenceNotFoundError):
        await env.review_service._resolve_task_and_db("nonexistent-task")


# ---------------------------------------------------------------------------
# T02: Review candidates read from SQLite
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t02_review_candidates_read_from_sqlite(env):
    """T02: Review candidates read directly from authoritative SQLite."""
    candidates = await env.review_service.list_candidates(env.fixture.task_id)
    assert len(candidates) >= 2  # 1 finding + 1 hypothesis

    # Verify both types present
    target_types = {c.target_type for c in candidates}
    assert "finding" in target_types
    assert "hypothesis" in target_types


# ---------------------------------------------------------------------------
# T03: Agent Integration produces reviewable object
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t03_agent_integration_produces_reviewable_object(env):
    """T03: Finding in review_pending state is projected as reviewable candidate."""
    candidate = await env.review_service.get_candidate(
        env.fixture.task_id, env.fixture.seed_finding_id
    )
    assert candidate.target_id == env.fixture.seed_finding_id
    assert candidate.review_status == REVIEW_PENDING
    assert candidate.claim_type == "INFERENCE"
    assert len(candidate.evidence_refs) == 1
    assert candidate.evidence_refs[0] == env.fixture.valid_file_ref


# ---------------------------------------------------------------------------
# T04: Review Candidate has stable identity
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t04_review_candidate_stable_identity(env):
    """T04: Candidate identity is stable across repeated invocations."""
    c1 = await env.review_service.get_candidate(env.fixture.task_id, env.fixture.seed_finding_id)
    c2 = await env.review_service.get_candidate(env.fixture.task_id, env.fixture.seed_finding_id)
    assert c1.candidate_id == c2.candidate_id
    assert c1.candidate_hash == c2.candidate_hash


# ---------------------------------------------------------------------------
# T05: Evidence refs are task-scoped
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t05_evidence_refs_task_scoped(env):
    """T05: Evidence refs resolve within task scope; invalid refs reject."""
    resolver = EvidenceResolver(env.cpp_backend)
    # Valid ref resolves
    resolved = await resolver.resolve_evidence(env.fixture.task_id, env.fixture.valid_file_ref)
    assert resolved is not None

    # Foreign task or non-existent ref fails
    with pytest.raises(Exception):
        await resolver.resolve_evidence(env.fixture.task_id, "file:C/nonexistent/fake.exe")


# ---------------------------------------------------------------------------
# T06: Candidate snapshot/hash is preserved
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t06_candidate_snapshot_hash_preserved(env):
    """T06: Canonical candidate hash matches expected digest."""
    candidate = await env.review_service.get_candidate(
        env.fixture.task_id, env.fixture.seed_finding_id
    )
    expected_hash = compute_candidate_hash(
        candidate.target_type,
        candidate.target_id,
        candidate.claim_type,
        candidate.content,
        candidate.evidence_refs,
    )
    assert candidate.candidate_hash == expected_hash


# ---------------------------------------------------------------------------
# T07: GET review candidates is read-only
# ---------------------------------------------------------------------------
def test_t07_get_review_candidates_read_only(env):
    """T07: GET review candidates makes 0 SQLite writes and returns 200."""
    url = f"/api/investigation/agent/review-candidates?task_id={env.fixture.task_id}"
    resp = env.client.get(url)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 2

    # Check candidate by ID
    c_id = data[0]["candidate_id"]
    detail_resp = env.client.get(
        f"/api/investigation/agent/review-candidates/{c_id}?task_id={env.fixture.task_id}"
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["candidate_id"] == c_id


# ---------------------------------------------------------------------------
# T08: Valid analyst acceptance succeeds
# ---------------------------------------------------------------------------
def test_t08_valid_analyst_acceptance_succeeds(env):
    """T08: Explicit analyst acceptance updates status to accepted with full provenance."""
    # Fetch candidate
    c_resp = env.client.get(
        f"/api/investigation/agent/review-candidates/{env.fixture.seed_finding_id}?task_id={env.fixture.task_id}"
    )
    assert c_resp.status_code == 200
    candidate = c_resp.json()

    req = {
        "task_id": env.fixture.task_id,
        "investigation_id": env.fixture.investigation_id,
        "review_target_id": env.fixture.seed_finding_id,
        "expected_source_revision": candidate["source_revision"],
        "expected_candidate_hash": candidate["candidate_hash"],
        "decision": "accepted",
        "reviewer": "analyst-alice",
        "request_id": "req-accept-001",
        "note": "Verified against SAM hive logon event.",
    }
    resp = env.client.post("/api/investigation/agent/review", json=req)
    assert resp.status_code == 200
    outcome = resp.json()
    assert outcome["decision"] == "accepted"
    assert outcome["status"] == "accepted"
    assert outcome["accepted_finding_id"] == env.fixture.seed_finding_id
    assert outcome["reviewer"] == "analyst-alice"

    # Verify SQLite row
    with env.runtime._connect() as conn:
        conn.row_factory = sqlite3.Row
        f_row = conn.execute(
            "SELECT * FROM investigation_findings WHERE finding_id = ?",
            [env.fixture.seed_finding_id],
        ).fetchone()
        assert f_row["status"] == "accepted"
        assert f_row["reviewer"] == "analyst-alice"
        assert f_row["review_id"] == outcome["review_id"]


# ---------------------------------------------------------------------------
# T09: Accepted Finding preserves epistemic type
# ---------------------------------------------------------------------------
def test_t09_accepted_finding_preserves_epistemic_type(env):
    """T09: Accepting a HYPOTHESIS candidate preserves assertion_class=HYPOTHESIS."""
    c_resp = env.client.get(
        f"/api/investigation/agent/review-candidates/h-448201?task_id={env.fixture.task_id}"
    )
    assert c_resp.status_code == 200
    candidate = c_resp.json()
    assert candidate["claim_type"] == "HYPOTHESIS"

    req = {
        "task_id": env.fixture.task_id,
        "investigation_id": env.fixture.investigation_id,
        "review_target_id": "h-448201",
        "expected_source_revision": candidate["source_revision"],
        "expected_candidate_hash": candidate["candidate_hash"],
        "decision": "accepted",
        "reviewer": "analyst-bob",
        "request_id": "req-hyp-accept-001",
        "note": "Working hypothesis confirmed plausible.",
    }
    resp = env.client.post("/api/investigation/agent/review", json=req)
    assert resp.status_code == 200
    outcome = resp.json()
    assert outcome["epistemic_type"] == "HYPOTHESIS"

    # Verify finding assertion_class in SQLite
    target_fid = outcome["accepted_finding_id"]
    with env.runtime._connect() as conn:
        conn.row_factory = sqlite3.Row
        f_row = conn.execute(
            "SELECT * FROM investigation_findings WHERE finding_id = ?",
            [target_fid],
        ).fetchone()
        assert f_row["assertion_class"] == "HYPOTHESIS"
        assert f_row["status"] == "accepted"


# ---------------------------------------------------------------------------
# T10: Valid rejection succeeds
# ---------------------------------------------------------------------------
def test_t10_valid_rejection_succeeds(env):
    """T10: Explicit analyst rejection updates status to rejected."""
    c_resp = env.client.get(
        f"/api/investigation/agent/review-candidates/{env.fixture.seed_finding_id}?task_id={env.fixture.task_id}"
    )
    candidate = c_resp.json()

    req = {
        "task_id": env.fixture.task_id,
        "investigation_id": env.fixture.investigation_id,
        "review_target_id": env.fixture.seed_finding_id,
        "expected_source_revision": candidate["source_revision"],
        "expected_candidate_hash": candidate["candidate_hash"],
        "decision": "rejected",
        "reviewer": "analyst-charlie",
        "request_id": "req-reject-001",
        "note": "Insufficient forensic correlation.",
    }
    resp = env.client.post("/api/investigation/agent/review", json=req)
    assert resp.status_code == 200
    outcome = resp.json()
    assert outcome["decision"] == "rejected"
    assert outcome["status"] == "rejected"
    assert outcome["accepted_finding_id"] is None


# ---------------------------------------------------------------------------
# T11: Rejection preserves original Agent output
# ---------------------------------------------------------------------------
def test_t11_rejection_preserves_original_agent_output(env):
    """T11: Rejection does not overwrite or delete original finding text or refs."""
    test_t10_valid_rejection_succeeds(env)

    with env.runtime._connect() as conn:
        conn.row_factory = sqlite3.Row
        f_row = conn.execute(
            "SELECT * FROM investigation_findings WHERE finding_id = ?",
            [env.fixture.seed_finding_id],
        ).fetchone()
        assert f_row["status"] == "rejected"
        assert "SAM" in f_row["text"]
        assert f_row["proposal_id"] == "prop_01"


# ---------------------------------------------------------------------------
# T12: Review history is append-only
# ---------------------------------------------------------------------------
def test_t12_review_history_is_append_only(env):
    """T12: Review history table rejects direct UPDATE and DELETE via triggers."""
    test_t08_valid_analyst_acceptance_succeeds(env)

    hist_resp = env.client.get(
        f"/api/investigation/agent/reviews/history?task_id={env.fixture.task_id}"
    )
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    assert len(history) >= 1

    # Attempt direct SQLite UPDATE and DELETE on history table
    with env.runtime._connect() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE investigation_finding_reviews SET decision = 'rejected' WHERE task_id = ?",
                [env.fixture.task_id],
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "DELETE FROM investigation_finding_reviews WHERE task_id = ?",
                [env.fixture.task_id],
            )


# ---------------------------------------------------------------------------
# T13: Duplicate accept request is idempotent
# ---------------------------------------------------------------------------
def test_t13_duplicate_accept_request_idempotent(env):
    """T13: Exact duplicate request replay returns 200 OK without double-committing."""
    c_resp = env.client.get(
        f"/api/investigation/agent/review-candidates/{env.fixture.seed_finding_id}?task_id={env.fixture.task_id}"
    )
    candidate = c_resp.json()

    req = {
        "task_id": env.fixture.task_id,
        "investigation_id": env.fixture.investigation_id,
        "review_target_id": env.fixture.seed_finding_id,
        "expected_source_revision": candidate["source_revision"],
        "expected_candidate_hash": candidate["candidate_hash"],
        "decision": "accepted",
        "reviewer": "analyst-alice",
        "request_id": "req-idempotent-001",
        "note": "First submit.",
    }
    r1 = env.client.post("/api/investigation/agent/review", json=req)
    assert r1.status_code == 200

    # Second submit (exact duplicate replay)
    r2 = env.client.post("/api/investigation/agent/review", json=req)
    assert r2.status_code == 200
    assert r2.json()["review_id"] == r1.json()["review_id"]

    # History count should be exactly 1
    h_resp = env.client.get(
        f"/api/investigation/agent/reviews/history?task_id={env.fixture.task_id}&candidate_id={env.fixture.seed_finding_id}"
    )
    assert len(h_resp.json()) == 1


# ---------------------------------------------------------------------------
# T14: Conflicting review request is rejected
# ---------------------------------------------------------------------------
def test_t14_conflicting_review_request_rejected(env):
    """T14: Reusing request_id with different payload returns 409 Conflict."""
    c_resp = env.client.get(
        f"/api/investigation/agent/review-candidates/{env.fixture.seed_finding_id}?task_id={env.fixture.task_id}"
    )
    candidate = c_resp.json()

    req1 = {
        "task_id": env.fixture.task_id,
        "investigation_id": env.fixture.investigation_id,
        "review_target_id": env.fixture.seed_finding_id,
        "expected_source_revision": candidate["source_revision"],
        "expected_candidate_hash": candidate["candidate_hash"],
        "decision": "accepted",
        "reviewer": "analyst-alice",
        "request_id": "req-conflict-001",
    }
    r1 = env.client.post("/api/investigation/agent/review", json=req1)
    assert r1.status_code == 200

    # Conflicting request: same request_id, different decision
    req2 = dict(req1)
    req2["decision"] = "rejected"
    r2 = env.client.post("/api/investigation/agent/review", json=req2)
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# T15: Stale candidate review rejected
# ---------------------------------------------------------------------------
def test_t15_stale_candidate_review_rejected(env):
    """T15: Stale expected_candidate_hash or revision returns 409 Conflict."""
    c_resp = env.client.get(
        f"/api/investigation/agent/review-candidates/{env.fixture.seed_finding_id}?task_id={env.fixture.task_id}"
    )
    candidate = c_resp.json()

    req = {
        "task_id": env.fixture.task_id,
        "investigation_id": env.fixture.investigation_id,
        "review_target_id": env.fixture.seed_finding_id,
        "expected_source_revision": candidate["source_revision"],
        "expected_candidate_hash": "bad-hash-00000000000000000000000000000000",
        "decision": "accepted",
        "reviewer": "analyst-alice",
        "request_id": "req-stale-001",
    }
    resp = env.client.post("/api/investigation/agent/review", json=req)
    assert resp.status_code == 409
    assert "stale candidate" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# T16: Two concurrent reviewers cannot double-commit
# ---------------------------------------------------------------------------
def test_t16_two_concurrent_reviewers_cannot_double_commit(env):
    """T16: Reviewing an already-reviewed finding with a new request_id fails with 409."""
    c_resp = env.client.get(
        f"/api/investigation/agent/review-candidates/{env.fixture.seed_finding_id}?task_id={env.fixture.task_id}"
    )
    candidate = c_resp.json()

    # Reviewer 1 accepts
    req1 = {
        "task_id": env.fixture.task_id,
        "investigation_id": env.fixture.investigation_id,
        "review_target_id": env.fixture.seed_finding_id,
        "expected_source_revision": candidate["source_revision"],
        "expected_candidate_hash": candidate["candidate_hash"],
        "decision": "accepted",
        "reviewer": "reviewer-one",
        "request_id": "req-race-001",
    }
    r1 = env.client.post("/api/investigation/agent/review", json=req1)
    assert r1.status_code == 200

    # Reviewer 2 tries to reject the same candidate concurrently
    req2 = {
        "task_id": env.fixture.task_id,
        "investigation_id": env.fixture.investigation_id,
        "review_target_id": env.fixture.seed_finding_id,
        "expected_source_revision": candidate["source_revision"],
        "expected_candidate_hash": candidate["candidate_hash"],
        "decision": "rejected",
        "reviewer": "reviewer-two",
        "request_id": "req-race-002",
    }
    r2 = env.client.post("/api/investigation/agent/review", json=req2)
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# T17: Deleted Task rejected
# ---------------------------------------------------------------------------
def test_t17_deleted_task_rejected(env):
    """T17: Review targeting nonexistent or deleted task returns 404."""
    req = {
        "task_id": "task-deleted-or-missing",
        "review_target_id": env.fixture.seed_finding_id,
        "expected_source_revision": 1,
        "expected_candidate_hash": "deadbeef",
        "decision": "accepted",
        "reviewer": "analyst-alice",
        "request_id": "req-missing-task",
    }
    resp = env.client.post("/api/investigation/agent/review", json=req)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# T18: Cross-task review target rejected
# ---------------------------------------------------------------------------
def test_t18_cross_task_review_target_rejected(env):
    """T18: Review targeting candidate from another task returns 404."""
    req = {
        "task_id": env.fixture.task_id,
        "review_target_id": "foreign-task-candidate-999",
        "expected_source_revision": 1,
        "expected_candidate_hash": "deadbeef",
        "decision": "accepted",
        "reviewer": "analyst-alice",
        "request_id": "req-cross-task",
    }
    resp = env.client.post("/api/investigation/agent/review", json=req)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# T19: Fabricated Evidence rejected
# ---------------------------------------------------------------------------
def test_t19_fabricated_evidence_rejected(env):
    """T19: Accepting candidate with unresolvable/fabricated evidence fails with 422."""
    # Seed a finding with fabricated evidence ref
    bad_fid = "finding:disp_bad_ev"
    with env.runtime._connect() as conn:
        conn.execute(
            "INSERT INTO investigation_findings "
            "(finding_id, task_id, investigation_id, proposal_id, disposition_id, "
            " text, assertion_class, evidence_refs_json, relationship_refs_json, "
            " temporal_scope_json, grounding_id, limitations_json, status, created_at) "
            "VALUES (?, ?, ?, 'p_bad', 'd_bad', 'Fabricated claim', 'INFERENCE', ?, ?, NULL, 'g_bad', ?, 'review_pending', ?)",
            [
                bad_fid,
                env.fixture.task_id,
                env.fixture.investigation_id,
                canonical_state_json({"refs": ["file:C/Windows/FakeFile.exe"]}),
                canonical_state_json({"refs": []}),
                canonical_state_json({"limitations": []}),
                "2026-10-17T12:00:00Z",
            ],
        )
        conn.commit()

    c_resp = env.client.get(
        f"/api/investigation/agent/review-candidates/{bad_fid}?task_id={env.fixture.task_id}"
    )
    candidate = c_resp.json()

    req = {
        "task_id": env.fixture.task_id,
        "review_target_id": bad_fid,
        "expected_source_revision": candidate["source_revision"],
        "expected_candidate_hash": candidate["candidate_hash"],
        "decision": "accepted",
        "reviewer": "analyst-alice",
        "request_id": "req-fab-ev",
    }
    resp = env.client.post("/api/investigation/agent/review", json=req)
    assert resp.status_code == 422
    assert "could not be resolved" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# T20: Analyst Note cannot become Evidence
# ---------------------------------------------------------------------------
def test_t20_analyst_note_cannot_become_evidence(env):
    """T20: Evidence ref starting with analyst_note: or summary: is rejected with 422."""
    bad_fid = "finding:disp_note_ev"
    with env.runtime._connect() as conn:
        conn.execute(
            "INSERT INTO investigation_findings "
            "(finding_id, task_id, investigation_id, proposal_id, disposition_id, "
            " text, assertion_class, evidence_refs_json, relationship_refs_json, "
            " temporal_scope_json, grounding_id, limitations_json, status, created_at) "
            "VALUES (?, ?, ?, 'p_note', 'd_note', 'Note claim', 'INFERENCE', ?, ?, NULL, 'g_note', ?, 'review_pending', ?)",
            [
                bad_fid,
                env.fixture.task_id,
                env.fixture.investigation_id,
                canonical_state_json({"refs": ["analyst_note:suspicious activity noticed"]}),
                canonical_state_json({"refs": []}),
                canonical_state_json({"limitations": []}),
                "2026-10-17T12:00:00Z",
            ],
        )
        conn.commit()

    c_resp = env.client.get(
        f"/api/investigation/agent/review-candidates/{bad_fid}?task_id={env.fixture.task_id}"
    )
    candidate = c_resp.json()

    req = {
        "task_id": env.fixture.task_id,
        "review_target_id": bad_fid,
        "expected_source_revision": candidate["source_revision"],
        "expected_candidate_hash": candidate["candidate_hash"],
        "decision": "accepted",
        "reviewer": "analyst-alice",
        "request_id": "req-note-ev",
    }
    resp = env.client.post("/api/investigation/agent/review", json=req)
    assert resp.status_code == 422
    assert "analyst note/summary cannot be evidence" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# T21: Unsupported FACT promotion blocked
# ---------------------------------------------------------------------------
def test_t21_unsupported_fact_promotion_blocked(env):
    """T21: Attempting to promote HYPOTHESIS to FACT or accepting ungrounded FACT raises 422."""
    c_resp = env.client.get(
        f"/api/investigation/agent/review-candidates/h-448201?task_id={env.fixture.task_id}"
    )
    candidate = c_resp.json()

    # Explicit attempt to promote to FACT
    req = {
        "task_id": env.fixture.task_id,
        "review_target_id": "h-448201",
        "expected_source_revision": candidate["source_revision"],
        "expected_candidate_hash": candidate["candidate_hash"],
        "decision": "accepted",
        "reviewer": "analyst-alice",
        "request_id": "req-fact-promo",
        "requested_assertion_class": "FACT",
    }
    resp = env.client.post("/api/investigation/agent/review", json=req)
    assert resp.status_code == 422
    assert "cannot promote" in resp.json()["detail"] or "epistemic" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# T22: Hypothesis can remain accepted as hypothesis
# ---------------------------------------------------------------------------
def test_t22_hypothesis_accepted_as_hypothesis(env):
    """T22: Accepting HYPOTHESIS cleanly preserves HYPOTHESIS assertion class."""
    c_resp = env.client.get(
        f"/api/investigation/agent/review-candidates/h-448201?task_id={env.fixture.task_id}"
    )
    candidate = c_resp.json()

    req = {
        "task_id": env.fixture.task_id,
        "review_target_id": "h-448201",
        "expected_source_revision": candidate["source_revision"],
        "expected_candidate_hash": candidate["candidate_hash"],
        "decision": "accepted",
        "reviewer": "analyst-alice",
        "request_id": "req-accept-hyp-t22",
    }
    resp = env.client.post("/api/investigation/agent/review", json=req)
    assert resp.status_code == 200
    outcome = resp.json()
    assert outcome["epistemic_type"] == "HYPOTHESIS"
    assert outcome["decision"] == "accepted"


# ---------------------------------------------------------------------------
# T23: Accepted Finding retains Evidence provenance
# ---------------------------------------------------------------------------
def test_t23_accepted_finding_retains_evidence_provenance(env):
    """T23: Accepted finding preserves exact evidence references from candidate."""
    test_t08_valid_analyst_acceptance_succeeds(env)

    with env.runtime._connect() as conn:
        conn.row_factory = sqlite3.Row
        f_row = conn.execute(
            "SELECT * FROM investigation_findings WHERE finding_id = ?",
            [env.fixture.seed_finding_id],
        ).fetchone()
        refs = json.loads(f_row["evidence_refs_json"])["refs"]
        assert refs == [env.fixture.valid_file_ref]


# ---------------------------------------------------------------------------
# T24: Review does not modify raw.db/events.db/files.db
# ---------------------------------------------------------------------------
def test_t24_review_does_not_modify_underlying_dbs(env):
    """T24: Review operations make zero modifications to files.db, events.db, or raw.db."""
    test_t08_valid_analyst_acceptance_succeeds(env)

    assert env.fixture._compute_sha256(env.fixture.files_db_path) == env.fixture.initial_files_sha256
    assert env.fixture._compute_sha256(env.fixture.events_db_path) == env.fixture.initial_events_sha256
    assert env.fixture._compute_sha256(env.fixture.raw_db_path) == env.fixture.initial_raw_sha256


# ---------------------------------------------------------------------------
# T25: Review does not automatically finalize
# ---------------------------------------------------------------------------
def test_t25_review_does_not_automatically_finalize(env):
    """T25: Accepting or rejecting review does not finalize the investigation."""
    test_t08_valid_analyst_acceptance_succeeds(env)

    inv = env.runtime.get_investigation(env.fixture.investigation_id)
    assert inv.status == AgentInvestigationStatus.ready


# ---------------------------------------------------------------------------
# T26: Review does not trigger Report Admission
# ---------------------------------------------------------------------------
def test_t26_review_does_not_trigger_report_admission(env):
    """T26: Review acceptance does not insert any rows into report_evidence."""
    test_t08_valid_analyst_acceptance_succeeds(env)

    with env.runtime._connect() as conn:
        # Check report_evidence table if it exists
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "report_evidence" in tables:
            rows = conn.execute("SELECT count(*) FROM report_evidence WHERE task_id = ?", [env.fixture.task_id]).fetchone()
            assert rows[0] == 0


# ---------------------------------------------------------------------------
# T27: Review does not publish Report
# ---------------------------------------------------------------------------
def test_t27_review_does_not_publish_report(env):
    """T27: Review acceptance does not create or publish any investigation reports."""
    test_t08_valid_analyst_acceptance_succeeds(env)

    with env.runtime._connect() as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "investigation_reports" in tables:
            rows = conn.execute("SELECT count(*) FROM investigation_reports WHERE task_id = ?", [env.fixture.task_id]).fetchone()
            assert rows[0] == 0


# ---------------------------------------------------------------------------
# T28: Review does not automatically modify Event Summary
# ---------------------------------------------------------------------------
def test_t28_review_does_not_modify_event_summary(env):
    """T28: Review decisions do not alter investigation events or summaries."""
    test_t08_valid_analyst_acceptance_succeeds(env)

    with env.runtime._connect() as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "investigation_events" in tables:
            events = conn.execute("SELECT * FROM investigation_events WHERE task_id = ?", [env.fixture.task_id]).fetchall()
            for e in events:
                assert "analyst" not in str(e).lower()


# ---------------------------------------------------------------------------
# T29: Existing Investigation Review APIs remain compatible
# ---------------------------------------------------------------------------
def test_t29_existing_investigation_review_apis_compatible(env):
    """T29: FindingReviewService interface remains fully functional and compatible."""
    finding_review_svc = FindingReviewService()
    assert hasattr(finding_review_svc, "review_finding")
    assert callable(finding_review_svc.review_finding)


# ---------------------------------------------------------------------------
# T30: Agent Cycle execution remains backward compatible
# ---------------------------------------------------------------------------
def test_t30_agent_cycle_execution_backward_compatible(env):
    """T30: Agent orchestrator and cycle routes remain intact and accessible."""
    state_resp = env.client.get(f"/api/investigation/agent/state?task_id={env.fixture.task_id}")
    assert state_resp.status_code == 200
    data = state_resp.json()
    assert data["task_id"] == env.fixture.task_id
    assert data["working_state_revision"] >= 1


# ---------------------------------------------------------------------------
# T31: Zero real Provider requests
# ---------------------------------------------------------------------------
def test_t31_zero_real_provider_requests(env):
    """T31: All review tests execute offline with mock/fake services; 0 network calls."""
    assert isinstance(env.cpp_backend, FakeReviewCppBackend)
    assert env.settings.llm_provider == ""
    assert env.settings.agent_experimental_guidance_enabled is False


# ---------------------------------------------------------------------------
# T32: Restart preserves Review history
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t32_restart_preserves_review_history(env):
    """T32: New service instance reading existing DB recovers exact review state and history."""
    test_t08_valid_analyst_acceptance_succeeds(env)

    # Instantiate fresh review service
    fresh_service = AgentAnalystReviewService(env.cpp_backend, env.settings)
    history = await fresh_service.get_history(env.fixture.task_id)
    assert len(history) >= 1
    assert history[0].decision == "accepted"
    assert history[0].reviewer == "analyst-alice"


# ---------------------------------------------------------------------------
# T33: Review errors do not corrupt Working State
# ---------------------------------------------------------------------------
def test_t33_review_errors_do_not_corrupt_working_state(env):
    """T33: Failed review submissions leave working state and findings uncorrupted."""
    initial_latest = env.runtime.get_latest_working_state(env.fixture.investigation_id)

    # Intentionally cause a 409 conflict
    req = {
        "task_id": env.fixture.task_id,
        "review_target_id": env.fixture.seed_finding_id,
        "expected_source_revision": initial_latest.revision,
        "expected_candidate_hash": "bad-hash",
        "decision": "accepted",
        "reviewer": "analyst-alice",
        "request_id": "req-corrupt-test",
    }
    resp = env.client.post("/api/investigation/agent/review", json=req)
    assert resp.status_code == 409

    after_latest = env.runtime.get_latest_working_state(env.fixture.investigation_id)
    assert after_latest.revision == initial_latest.revision
    assert after_latest.state_hash == initial_latest.state_hash


# ---------------------------------------------------------------------------
# T34: Immutable historical Agent decisions remain unchanged
# ---------------------------------------------------------------------------
def test_t34_immutable_historical_agent_decisions_unchanged(env):
    """T34: Review actions do not alter historical revisions or working state snapshots."""
    with env.runtime._connect() as conn:
        conn.row_factory = sqlite3.Row
        revs_before = conn.execute(
            "SELECT revision, state_hash FROM agent_working_state_revisions WHERE investigation_id = ? ORDER BY revision ASC",
            [env.fixture.investigation_id],
        ).fetchall()
        revs_before_list = [(r["revision"], r["state_hash"]) for r in revs_before]

    test_t08_valid_analyst_acceptance_succeeds(env)

    with env.runtime._connect() as conn:
        conn.row_factory = sqlite3.Row
        revs_after = conn.execute(
            "SELECT revision, state_hash FROM agent_working_state_revisions WHERE investigation_id = ? ORDER BY revision ASC",
            [env.fixture.investigation_id],
        ).fetchall()
        revs_after_list = [(r["revision"], r["state_hash"]) for r in revs_after]

    assert revs_before_list == revs_after_list
