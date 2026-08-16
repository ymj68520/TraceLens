"""Tests for Secondary Analysis persistence (Phase C4b-1): version state machine,
content-addressed input_hash, FK lifecycle, migration v1->v2, concurrency, restart.

Covers invariants A1-A14.  No LLM/Job/route wiring -- repository-level only.
"""

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from httpserver.services.investigation import (
    AnalysisReviewDecision,
    EvidenceSnapshot,
    FileSnapshotPayload,
    InvestigationRepository,
    SecondaryAnalysisStatus,
    SUPPORTED_SCHEMA_VERSION,
)
from httpserver.services.investigation.repository import (
    _CREATE_SECONDARY_ANALYSES_SQL,
    _INDEX_SECONDARY_SCOPE_VERSION_SQL,
    _INDEX_SECONDARY_STATUS_SQL,
    _TRIGGER_SECONDARY_LEGAL_TRANSITION_SQL,
)


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

def _make_files_db(db_path, rows):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"""
    )
    for r in rows:
        conn.execute(
            "INSERT INTO files (path,name,extension,category,type,size,mtime,ctime,is_deleted,md5,"
            "llm_summary,llm_description,llm_keywords,llm_analyzed_at,llm_model_used,"
            "scene_type,scene_priority,scene_relevant) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r.get("path"), r.get("name"), r.get("extension"), r.get("category"), r.get("type"),
                r.get("size"), r.get("mtime"), r.get("ctime"), r.get("is_deleted"), r.get("md5"),
                r.get("llm_summary"), r.get("llm_description"), r.get("llm_keywords"),
                r.get("llm_analyzed_at"), r.get("llm_model_used"),
                r.get("scene_type"), r.get("scene_priority"), r.get("scene_relevant"),
            ),
        )
    conn.commit()
    conn.close()


def _file_resolved(fdb, task_id="A", path="/case/report.docx"):
    from httpserver.services.evidence import ResolvedEvidence
    return ResolvedEvidence(
        task_id=task_id, evidence_key=f"file:{path}", evidence_type="file",
        normalized_path=path, source_db=fdb,
    )


def _setup(tmp_path):
    """Create files.db + investigation.db with one captured file snapshot."""
    fdb = str(tmp_path / "files.db")
    idb = str(tmp_path / "investigation.db")
    _make_files_db(fdb, [{"path": "/case/report.docx", "llm_description": "DESC", "size": 7}])
    repo = InvestigationRepository(idb, "A")
    snap = repo.capture_if_absent(_file_resolved(fdb))
    return fdb, idb, repo, snap


def _create_v1_db_with_snapshot(tmp_path):
    """Create a genuine v1 DB (evidence_snapshots + data, no secondary_analyses)."""
    fdb = str(tmp_path / "files.db")
    idb = str(tmp_path / "investigation.db")
    _make_files_db(fdb, [{"path": "/case/report.docx", "llm_description": "DESC", "size": 7}])
    repo = InvestigationRepository(idb, "A")
    snap = repo.capture_if_absent(_file_resolved(fdb))
    # Strip v2 objects to simulate a v1 database
    conn = sqlite3.connect(idb)
    conn.execute("DROP TRIGGER IF EXISTS trg_secondary_no_terminal_update")
    conn.execute("DROP TRIGGER IF EXISTS trg_secondary_legal_transition")
    conn.execute("DROP INDEX IF EXISTS idx_secondary_status")
    conn.execute("DROP INDEX IF EXISTS idx_secondary_scope_version")
    conn.execute("DROP TABLE IF EXISTS secondary_analyses")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    return fdb, idb, snap


def _count_secondary(idb):
    conn = sqlite3.connect(idb)
    n = conn.execute("SELECT COUNT(*) FROM secondary_analyses").fetchone()[0]
    conn.close()
    return n


EVIDENCE_KEY = "file:/case/report.docx"


# ---------------------------------------------------------------------------
# A3/A6: version continuity + immutability
# ---------------------------------------------------------------------------

def test_version_starts_at_1_and_increments(tmp_path):
    _, idb, repo, snap = _setup(tmp_path)

    v1 = repo.create_analysis(snap)
    v2 = repo.create_analysis(snap)

    assert v1.version == 1
    assert v2.version == 2
    assert v1.status == SecondaryAnalysisStatus.queued
    assert v2.status == SecondaryAnalysisStatus.queued
    assert v1.analysis_id != v2.analysis_id
    assert _count_secondary(idb) == 2


def test_existing_version_immutable_after_new_create(tmp_path):
    """A6: creating v2 does not change v1."""
    _, _, repo, snap = _setup(tmp_path)

    v1 = repo.create_analysis(snap)
    v1_hash = v1.input_hash
    v1_created = v1.created_at

    repo.create_analysis(snap)

    v1_after = repo.get_analysis(v1.analysis_id)
    assert v1_after.input_hash == v1_hash
    assert v1_after.created_at == v1_created
    assert v1_after.status == SecondaryAnalysisStatus.queued
    assert v1_after.version == 1


# ---------------------------------------------------------------------------
# A1/A2: binding to existing snapshot
# ---------------------------------------------------------------------------

def test_create_analysis_missing_snapshot_raises_no_write(tmp_path):
    idb = str(tmp_path / "investigation.db")
    repo = InvestigationRepository(idb, "A")
    fake = EvidenceSnapshot(
        task_id="A", evidence_key="file:/nonexistent", evidence_type="file",
        captured_at=123, payload=FileSnapshotPayload(normalized_path="/nonexistent"),
        snapshot_id=9999,
    )
    with pytest.raises(ValueError, match="snapshot not found"):
        repo.create_analysis(fake)
    assert _count_secondary(idb) == 0


def test_create_analysis_cross_task_rejected(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    cross = EvidenceSnapshot(
        task_id="B", evidence_key=snap.evidence_key, evidence_type="file",
        captured_at=snap.captured_at, payload=snap.payload, snapshot_id=snap.snapshot_id,
    )
    with pytest.raises(ValueError, match="different task"):
        repo.create_analysis(cross)


# ---------------------------------------------------------------------------
# A8/A11: content-addressed input_hash
# ---------------------------------------------------------------------------

def test_input_hash_reproducible_from_db_envelope(tmp_path):
    """A8: sha256(input_envelope_json) == stored input_hash."""
    _, idb, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap, analyst_note="note", case_context="ctx")

    conn = sqlite3.connect(idb)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT input_envelope_json, input_hash FROM secondary_analyses WHERE analysis_id=?",
        [a.analysis_id],
    ).fetchone()
    conn.close()

    recomputed = hashlib.sha256(row["input_envelope_json"].encode("utf-8")).hexdigest()
    assert recomputed == row["input_hash"]


def test_same_input_same_hash_different_version(tmp_path):
    """A8: same snapshot + same params -> same input_hash (different version)."""
    _, _, repo, snap = _setup(tmp_path)
    v1 = repo.create_analysis(snap, analyst_note="n", case_context="c")
    v2 = repo.create_analysis(snap, analyst_note="n", case_context="c")
    assert v1.input_hash == v2.input_hash


def test_different_input_different_hash(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap, analyst_note="alpha")
    b = repo.create_analysis(snap, analyst_note="beta")
    assert a.input_hash != b.input_hash


def test_hash_ignores_tampered_caller_snapshot(tmp_path):
    """A11: envelope/hash built from DB-trusted row, not caller's model."""
    _, _, repo, snap = _setup(tmp_path)
    original = repo.create_analysis(snap)

    # Tamper the caller-supplied snapshot payload -- must not affect the hash.
    tampered = EvidenceSnapshot(
        task_id=snap.task_id, evidence_key=snap.evidence_key, evidence_type="file",
        captured_at=snap.captured_at,
        payload=FileSnapshotPayload(normalized_path="/TAMPERED", name="hacked"),
        snapshot_id=snap.snapshot_id,
    )
    from_db = repo.create_analysis(tampered)

    assert from_db.input_hash == original.input_hash


# ---------------------------------------------------------------------------
# A12: snapshot_id excluded from serialization
# ---------------------------------------------------------------------------

def test_snapshot_id_excluded_from_model_dump():
    snap = EvidenceSnapshot(
        task_id="A", evidence_key="file:/x", evidence_type="file",
        captured_at=123, payload=FileSnapshotPayload(normalized_path="/x"),
        snapshot_id=42,
    )
    d = snap.model_dump()
    assert "snapshot_id" not in d
    d_json = snap.model_dump(mode="json")
    assert "snapshot_id" not in d_json


# ---------------------------------------------------------------------------
# State machine: legal transitions + per-target field writes
# ---------------------------------------------------------------------------

def test_legal_chain_queued_to_accepted_with_fields(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap, prompt_version="investigation-evidence-analysis:v2")

    running = repo.transition(a.analysis_id, SecondaryAnalysisStatus.running)
    assert running.status == SecondaryAnalysisStatus.running
    assert running.started_at is not None
    assert running.review_pending_at is None

    review = repo.transition(
        a.analysis_id, SecondaryAnalysisStatus.review_pending,
        description="desc", summary="sum", model="m1",
    )
    assert review.status == SecondaryAnalysisStatus.review_pending
    assert review.review_pending_at is not None
    assert review.description == "desc"
    assert review.summary == "sum"
    assert review.model == "m1"

    accepted = repo.review_analysis(
        a.analysis_id,
        decision=AnalysisReviewDecision.accepted,
        reviewer="analyst1",
        reason="looks good",
    )
    assert accepted.status == SecondaryAnalysisStatus.accepted
    assert accepted.decided_at is not None
    assert accepted.decided_by == "analyst1"
    assert accepted.decision_reason == "looks good"


def test_queued_to_failed_writes_error_fields(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap)

    failed = repo.transition(
        a.analysis_id, SecondaryAnalysisStatus.failed,
        error_code="TIMEOUT", error_message="timed out",
    )
    assert failed.status == SecondaryAnalysisStatus.failed
    assert failed.failed_at is not None
    assert failed.error_code == "TIMEOUT"
    assert failed.error_message == "timed out"


def test_review_pending_to_rejected_and_invalid(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap, prompt_version="investigation-evidence-analysis:v2")
    repo.transition(a.analysis_id, SecondaryAnalysisStatus.running)
    repo.transition(a.analysis_id, SecondaryAnalysisStatus.review_pending)

    rejected = repo.review_analysis(
        a.analysis_id,
        decision=AnalysisReviewDecision.rejected,
        reviewer="x",
        reason="no",
    )
    assert rejected.status == SecondaryAnalysisStatus.rejected
    assert rejected.decided_by == "x"

    # Separate analysis for invalid
    b = repo.create_analysis(snap, prompt_version="investigation-evidence-analysis:v2")
    repo.transition(b.analysis_id, SecondaryAnalysisStatus.running)
    repo.transition(b.analysis_id, SecondaryAnalysisStatus.review_pending)
    invalid = repo.review_analysis(
        b.analysis_id,
        decision=AnalysisReviewDecision.invalid,
        reviewer="y",
        reason="bad input",
    )
    assert invalid.status == SecondaryAnalysisStatus.invalid


# ---------------------------------------------------------------------------
# State machine: illegal transitions
# ---------------------------------------------------------------------------

def test_illegal_queued_to_accepted(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap)
    # P1: review-terminal targets are reserved for review_analysis().
    with pytest.raises(ValueError, match="requires review_analysis"):
        repo.transition(a.analysis_id, SecondaryAnalysisStatus.accepted, decided_by="x")
    assert repo.get_analysis(a.analysis_id).status == SecondaryAnalysisStatus.queued


def test_illegal_queued_to_review_pending(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap)
    with pytest.raises(ValueError, match="illegal transition"):
        repo.transition(a.analysis_id, SecondaryAnalysisStatus.review_pending)


def test_illegal_running_to_accepted(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap)
    repo.transition(a.analysis_id, SecondaryAnalysisStatus.running)
    with pytest.raises(ValueError, match="requires review_analysis"):
        repo.transition(a.analysis_id, SecondaryAnalysisStatus.accepted, decided_by="x")
    assert repo.get_analysis(a.analysis_id).status == SecondaryAnalysisStatus.running


def test_illegal_review_pending_to_queued(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap)
    repo.transition(a.analysis_id, SecondaryAnalysisStatus.running)
    repo.transition(a.analysis_id, SecondaryAnalysisStatus.review_pending)
    # 'queued' is never a transition target (only the initial create state)
    with pytest.raises(ValueError, match="non-targetable|illegal transition"):
        repo.transition(a.analysis_id, SecondaryAnalysisStatus.queued)


# ---------------------------------------------------------------------------
# transition: per-target field validation
# ---------------------------------------------------------------------------

def test_transition_rejects_irrelevant_fields(tmp_path):
    """transition(running, decision_reason=..., error_message=...) -> ValueError, DB untouched."""
    _, _, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap)
    with pytest.raises(ValueError, match="unexpected fields"):
        repo.transition(
            a.analysis_id, SecondaryAnalysisStatus.running,
            decision_reason="nope", error_message="nope",
        )
    # DB unchanged
    assert repo.get_analysis(a.analysis_id).status == SecondaryAnalysisStatus.queued


def test_transition_rejects_summary_for_failed(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap)
    with pytest.raises(ValueError, match="unexpected fields"):
        repo.transition(
            a.analysis_id, SecondaryAnalysisStatus.failed,
            error_code="E", error_message="m", summary="not allowed",
        )


# ---------------------------------------------------------------------------
# accepted != latest
# ---------------------------------------------------------------------------

def test_latest_vs_latest_accepted(tmp_path):
    _, _, repo, snap = _setup(tmp_path)

    v1 = repo.create_analysis(snap, prompt_version="investigation-evidence-analysis:v2")
    repo.transition(v1.analysis_id, SecondaryAnalysisStatus.running)
    repo.transition(v1.analysis_id, SecondaryAnalysisStatus.review_pending)
    repo.review_analysis(
        v1.analysis_id, decision=AnalysisReviewDecision.accepted, reviewer="x"
    )

    v2 = repo.create_analysis(snap)  # new queued version

    latest = repo.get_latest_analysis(EVIDENCE_KEY)
    latest_accepted = repo.get_latest_accepted_analysis(EVIDENCE_KEY)
    assert latest.version == 2
    assert latest.status == SecondaryAnalysisStatus.queued
    assert latest_accepted.version == 1
    assert latest_accepted.status == SecondaryAnalysisStatus.accepted


def test_latest_accepted_none_when_no_accept(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    repo.create_analysis(snap)
    assert repo.get_latest_accepted_analysis(EVIDENCE_KEY) is None
    assert repo.get_latest_analysis(EVIDENCE_KEY) is not None


def test_list_analyses_ordered_by_version_desc(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    repo.create_analysis(snap)
    repo.create_analysis(snap)
    repo.create_analysis(snap)
    lst = repo.list_analyses(EVIDENCE_KEY)
    versions = [a.version for a in lst]
    assert versions == [3, 2, 1]


def test_list_analyses_filtered_by_status(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap)
    repo.transition(a.analysis_id, SecondaryAnalysisStatus.running)
    repo.create_analysis(snap)  # queued
    queued = repo.list_analyses(EVIDENCE_KEY, status=SecondaryAnalysisStatus.queued)
    assert len(queued) == 1
    assert queued[0].version == 2


# ---------------------------------------------------------------------------
# A9: terminal immutability
# ---------------------------------------------------------------------------

def test_terminal_transition_raises(tmp_path):
    _, _, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap, prompt_version="investigation-evidence-analysis:v2")
    repo.transition(a.analysis_id, SecondaryAnalysisStatus.running)
    repo.transition(a.analysis_id, SecondaryAnalysisStatus.review_pending)
    repo.review_analysis(
        a.analysis_id, decision=AnalysisReviewDecision.accepted, reviewer="x"
    )

    with pytest.raises(ValueError, match="terminal"):
        repo.transition(a.analysis_id, SecondaryAnalysisStatus.running)


def test_terminal_sql_update_aborts(tmp_path):
    """A9: direct SQL UPDATE on a terminal row is ABORTed by trigger."""
    _, idb, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap)
    repo.transition(a.analysis_id, SecondaryAnalysisStatus.failed,
                    error_code="E", error_message="m")

    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute(
            "UPDATE secondary_analyses SET summary='hacked' WHERE analysis_id=?",
            [a.analysis_id],
        )
    row = conn.execute(
        "SELECT summary FROM secondary_analyses WHERE analysis_id=?", [a.analysis_id]
    ).fetchone()
    conn.close()
    assert row[0] is None  # unchanged


def test_db_trigger_aborts_illegal_transition(tmp_path):
    """DB guard: illegal status transition is ABORTed even via raw SQL."""
    _, idb, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap)  # queued

    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute(
            "UPDATE secondary_analyses SET status='accepted' WHERE analysis_id=?",
            [a.analysis_id],
        )
    conn.close()


# ---------------------------------------------------------------------------
# A4/A5: concurrency
# ---------------------------------------------------------------------------

@pytest.mark.concurrency
def test_concurrent_create_distinct_versions(tmp_path):
    _, idb, repo, snap = _setup(tmp_path)

    def worker(_):
        return InvestigationRepository(idb, "A").create_analysis(snap)

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(worker, range(16)))

    versions = sorted(r.version for r in results)
    assert versions == list(range(1, 17))  # exactly 1..16, no gaps/dupes
    assert _count_secondary(idb) == 16


@pytest.mark.concurrency
def test_concurrent_different_evidence_each_from_1(tmp_path):
    _, idb, repo, snap = _setup(tmp_path)

    keys = [f"file:/case/f{i}.txt" for i in range(4)]
    snaps = {}
    for k in keys:
        fdb = str(tmp_path / f"files_{k.replace('/', '_')}.db")
        _make_files_db(fdb, [{"path": k.replace("file:", "")}])
        snaps[k] = repo.capture_if_absent(_file_resolved(fdb, path=k.replace("file:", "")))

    def worker(key):
        return InvestigationRepository(idb, "A").create_analysis(snaps[key])

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(worker, keys * 3))  # 3 creates per key

    by_key = {}
    for r in results:
        by_key.setdefault(r.evidence_key, set()).add(r.version)
    for k in keys:
        assert by_key[k] == {1, 2, 3}  # each evidence versioning is independent


# ---------------------------------------------------------------------------
# A10: restart-safe
# ---------------------------------------------------------------------------

def test_restart_preserves_state(tmp_path):
    _, idb, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap)
    repo.transition(a.analysis_id, SecondaryAnalysisStatus.running)
    repo.transition(a.analysis_id, SecondaryAnalysisStatus.review_pending, description="d")

    # Discard repo, reopen from the same DB file
    repo2 = InvestigationRepository(idb, "A")
    restored = repo2.get_analysis(a.analysis_id)
    assert restored.version == 1
    assert restored.status == SecondaryAnalysisStatus.review_pending
    assert restored.input_hash == a.input_hash
    assert restored.input_envelope_json == a.input_envelope_json
    assert restored.description == "d"


# ---------------------------------------------------------------------------
# A13: migration v1->v2
# ---------------------------------------------------------------------------

@pytest.mark.migration_matrix
def test_migration_v1_to_v3_success_preserves_data(tmp_path):
    fdb, idb, snap = _create_v1_db_with_snapshot(tmp_path)

    conn = sqlite3.connect(idb)
    conn.row_factory = sqlite3.Row
    orig = conn.execute("SELECT * FROM evidence_snapshots WHERE id=?", [snap.snapshot_id]).fetchone()
    conn.close()

    repo = InvestigationRepository(idb, "A")  # triggers v1->v3 migration

    conn = sqlite3.connect(idb)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SUPPORTED_SCHEMA_VERSION
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='secondary_analyses'"
    ).fetchone() is not None
    conn.row_factory = sqlite3.Row
    snap_after = conn.execute(
        "SELECT * FROM evidence_snapshots WHERE id=?", [snap.snapshot_id]
    ).fetchone()
    conn.close()
    assert snap_after["snapshot_json"] == orig["snapshot_json"]
    assert snap_after["evidence_key"] == orig["evidence_key"]

    # Secondary analysis works on migrated DB
    snap_model = repo.get_snapshot(EVIDENCE_KEY)
    a = repo.create_analysis(snap_model)
    assert a.version == 1


@pytest.mark.migration_matrix
def test_migration_failure_rolls_back(tmp_path):
    """A13: migration fault after CREATE TABLE rolls back; user_version stays 1."""
    _, idb, _ = _create_v1_db_with_snapshot(tmp_path)

    def failing_migrate(self):
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_CREATE_SECONDARY_ANALYSES_SQL)
            conn.execute(_INDEX_SECONDARY_SCOPE_VERSION_SQL)
            conn.execute(_INDEX_SECONDARY_STATUS_SQL)
            conn.execute(_TRIGGER_SECONDARY_LEGAL_TRANSITION_SQL)
            raise RuntimeError("injected migration failure")

    # Monkeypatch the method on the class before instantiation
    original = InvestigationRepository._migrate_v1_to_v4
    InvestigationRepository._migrate_v1_to_v4 = failing_migrate
    try:
        with pytest.raises(RuntimeError, match="injected"):
            InvestigationRepository(idb, "A")
    finally:
        InvestigationRepository._migrate_v1_to_v4 = original

    conn = sqlite3.connect(idb)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='secondary_analyses'"
    ).fetchone() is None
    conn.close()


# ---------------------------------------------------------------------------
# A14: FK lifecycle
# ---------------------------------------------------------------------------

def test_fk_restrict_prevents_snapshot_delete(tmp_path):
    _, idb, repo, snap = _setup(tmp_path)
    repo.create_analysis(snap)

    conn = sqlite3.connect(idb)
    conn.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM evidence_snapshots WHERE id=?", [snap.snapshot_id])
    conn.close()
    assert repo.get_snapshot(EVIDENCE_KEY) is not None


def test_fk_definition_validated_at_init(tmp_path):
    """_validate_v2_schema checks the FK exists; if missing, init fails closed."""
    idb = str(tmp_path / "investigation.db")
    InvestigationRepository(idb, "A")  # succeeds -> FK validated
    conn = sqlite3.connect(idb)
    fks = conn.execute("PRAGMA foreign_key_list(secondary_analyses)").fetchall()
    conn.close()
    assert any(
        fk[2] == "evidence_snapshots" and fk[3] == "snapshot_id" and fk[4] == "id"
        for fk in fks
    )


# ---------------------------------------------------------------------------
# New DB + future version
# ---------------------------------------------------------------------------

def test_new_db_is_v7_with_report_extension(tmp_path):
    idb = str(tmp_path / "investigation.db")
    InvestigationRepository(idb, "A")
    assert SUPPORTED_SCHEMA_VERSION == 7
    conn = sqlite3.connect(idb)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SUPPORTED_SCHEMA_VERSION
    for table in (
        "evidence_snapshots", "secondary_analyses", "analysis_claims", "claim_evidence_refs",
        "investigation_events", "investigation_event_versions", "investigation_event_evidence",
        "investigation_event_refreshes", "report_evidence",
    ):
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]
        ).fetchone() is not None
    for trigger in (
        "trg_evsnap_no_update", "trg_secondary_legal_transition",
        "trg_secondary_no_terminal_update", "trg_secondary_no_input_update",
        "trg_claims_no_update", "trg_claims_no_delete",
        "trg_claim_refs_no_update", "trg_claim_refs_no_delete",
        "trg_inv_events_no_identity_update",
        "trg_inv_event_versions_no_update", "trg_inv_event_versions_no_delete",
        "trg_inv_event_evidence_no_update", "trg_inv_event_evidence_no_delete",
        "trg_inv_refresh_no_input_update", "trg_inv_refresh_legal_transition",
        "trg_inv_refresh_no_terminal_update",
        "trg_report_evidence_no_identity_update", "trg_report_evidence_no_delete",
    ):
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?", [trigger]
        ).fetchone() is not None
    conn.close()


@pytest.mark.migration_matrix
def test_future_version_fail_closed(tmp_path):
    idb = str(tmp_path / "investigation.db")
    InvestigationRepository(idb, "A")
    conn = sqlite3.connect(idb)
    conn.execute("PRAGMA user_version = 9")
    conn.commit()
    conn.close()
    with pytest.raises(Exception, match="unsupported"):
        InvestigationRepository(idb, "A")


# ---------------------------------------------------------------------------
# DB trigger: legal_transition guard (queued->running via raw SQL succeeds)
# ---------------------------------------------------------------------------

def test_db_trigger_allows_legal_transition(tmp_path):
    """DB guard does not block legal transitions via raw SQL."""
    _, idb, repo, snap = _setup(tmp_path)
    a = repo.create_analysis(snap)  # queued

    conn = sqlite3.connect(idb)
    conn.execute(
        "UPDATE secondary_analyses SET status='running', started_at=? WHERE analysis_id=?",
        ["2026-01-01T00:00:00Z", a.analysis_id],
    )
    conn.commit()
    status = conn.execute(
        "SELECT status FROM secondary_analyses WHERE analysis_id=?", [a.analysis_id]
    ).fetchone()[0]
    conn.close()
    assert status == "running"
