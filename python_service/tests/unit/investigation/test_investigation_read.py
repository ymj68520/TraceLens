"""Investigation Workbench read-service tests (Phase C9a).

Locks the read-only contract behind the Workbench shell: the evidence list
reuses the frozen C8b accepted-first selection, the Snapshot GET is the only
Initial Analysis source (never files.db re-read, never auto-capture), and
claims are the exact persisted rows of one exact analysis.  Reads go through
the mode=ro reader: zero bytes change on disk (B2), corrupt/unsupported
stores fail closed (B3), and a missing store is "no findings".
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3

import pytest

from httpserver.services.evidence import (
    EvidenceNotFoundError,
    EvidenceStoreError,
    ResolvedEvidence,
)
from httpserver.services.investigation import (
    AnalysisReviewDecision,
    ClaimType,
    InvestigationGraphReader,
    InvestigationReadService,
    InvestigationRepository,
    SecondaryAnalysisStatus,
)

KEY_A = "file:/case/a.txt"
KEY_B = "file:/case/b.txt"


def _make_files_db(path, paths):
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"""
    )
    for p, description in paths:
        conn.execute(
            "INSERT INTO files (path,llm_description,size,md5) VALUES (?,?,?,?)",
            (p, description, 1, "x" * 32),
        )
    conn.commit()
    conn.close()


def _store(tmp_path, task_id="A"):
    files_db = str(tmp_path / "files.db")
    _make_files_db(
        files_db,
        [
            ("/case/a.txt", "initial description A"),
            ("/case/b.txt", "initial description B"),
        ],
    )
    repo = InvestigationRepository(tmp_path / "investigation.db", task_id)
    return files_db, repo


def _capture(repo, files_db, key=KEY_A, task_id="A"):
    return repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id,
        evidence_key=key,
        evidence_type="file",
        normalized_path=key.removeprefix("file:"),
        source_db=files_db,
    ))


def _candidate(text="claim", refs=(KEY_A,)):
    from httpserver.services.investigation import ClaimCandidate

    return ClaimCandidate(
        claim_type=ClaimType.FACT, claim_text=text, evidence_refs=refs
    )


def _analysis(repo, snapshot, *, candidates=(_candidate(),), decision=None,
              summary="s"):
    analysis = repo.create_analysis(snapshot, prompt_version="investigation-evidence-analysis:v3")
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis.analysis_id,
        description="d", summary=summary, model="m",
        candidates=list(candidates),
    )
    if decision is not None:
        repo.review_analysis(
            analysis.analysis_id, decision=decision, reviewer="r", reason="ok"
        )
    return repo.get_analysis(analysis.analysis_id)


class _Backend:
    """Minimal trusted cpp_backend for read-service tests."""

    def __init__(self, task_dir, task_id="A", exists=True):
        self._task_dir = task_dir
        self._task_id = task_id
        self._exists = exists

    async def get_task(self, task_id):
        if not self._exists or task_id != self._task_id:
            return None
        return {
            "id": task_id,
            "output_files_db": str(self._task_dir / "files.db"),
            "output_events_db": str(self._task_dir / "events.db"),
        }


def _db_path(repo):
    return repo.db_path if hasattr(repo, "_db_path") else None


def _reader(repo, task_id="A"):
    # The repository owns the db path; reuse it for the read-only reader.
    return InvestigationGraphReader(repo.db_path, task_id)


# ---------------------------------------------------------------------------
# list_evidence
# ---------------------------------------------------------------------------

def test_list_evidence_reuses_c8b_accepted_first_selection(tmp_path):
    files_db, repo = _store(tmp_path)
    snap_a = _capture(repo, files_db, KEY_A)
    _capture(repo, files_db, KEY_B)

    accepted = _analysis(repo, snap_a, decision=AnalysisReviewDecision.accepted)
    pending_newer = _analysis(repo, snap_a)  # review_pending, higher version

    rows = _reader(repo).list_evidence()
    by_key = {row.evidence_key: row for row in rows}
    assert set(by_key) == {KEY_A, KEY_B}
    selected = by_key[KEY_A].selected_analysis
    # accepted wins over the newer review_pending version (G3/G5)
    assert selected.analysis_id == accepted.analysis_id
    assert selected.review_state == "accepted"
    assert selected.version == accepted.version
    # an evidence without any selected analysis carries None, not a fallback
    assert by_key[KEY_B].selected_analysis is None
    assert by_key[KEY_A].captured_at == snap_a.captured_at


def test_list_evidence_pending_fallback_is_review_pending(tmp_path):
    files_db, repo = _store(tmp_path)
    snap_a = _capture(repo, files_db, KEY_A)
    pending = _analysis(repo, snap_a)  # stays review_pending

    rows = _reader(repo).list_evidence()
    selected = rows[0].selected_analysis
    assert selected.analysis_id == pending.analysis_id
    assert selected.review_state == "review_pending"


def test_read_service_list_evidence(tmp_path):
    files_db, repo = _store(tmp_path)
    _capture(repo, files_db, KEY_A)
    service = InvestigationReadService(_Backend(tmp_path))

    rows = asyncio.run(service.list_evidence("A"))
    assert [row.evidence_key for row in rows] == [KEY_A]


def test_read_service_missing_store_is_empty_never_created(tmp_path):
    # A task directory that only has files.db: no capture ever happened.
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    _make_files_db(str(empty_dir / "files.db"), [])
    service = InvestigationReadService(_Backend(empty_dir))

    assert asyncio.run(service.list_evidence("A")) == []
    assert asyncio.run(service.get_snapshot("A", KEY_A)) is None
    assert asyncio.run(service.list_analysis_claims("A", "sa_1")) is None
    # no investigation.db materialized by the reads
    assert not (empty_dir / "investigation.db").exists()


def test_read_service_unknown_task_404(tmp_path):
    service = InvestigationReadService(_Backend(tmp_path, exists=False))
    with pytest.raises(EvidenceNotFoundError):
        asyncio.run(service.list_evidence("nope"))


# ---------------------------------------------------------------------------
# latest_snapshot
# ---------------------------------------------------------------------------

def test_snapshot_returns_frozen_initial_analysis_from_store(tmp_path):
    files_db, repo = _store(tmp_path)
    _capture(repo, files_db, KEY_A)

    snapshot = _reader(repo).latest_snapshot(KEY_A)
    assert snapshot is not None
    assert snapshot.payload.initial_description == "initial description A"
    assert snapshot.evidence_key == KEY_A


def test_snapshot_read_does_not_re_read_files_db(tmp_path):
    files_db, repo = _store(tmp_path)
    _capture(repo, files_db, KEY_A)

    # The source DB changes after the capture; the snapshot stays frozen.
    conn = sqlite3.connect(files_db)
    conn.execute("UPDATE files SET llm_description='rewritten later'")
    conn.commit()
    conn.close()

    snapshot = _reader(repo).latest_snapshot(KEY_A)
    assert snapshot.payload.initial_description == "initial description A"


def test_snapshot_unknown_evidence_is_none(tmp_path):
    files_db, repo = _store(tmp_path)
    _capture(repo, files_db, KEY_A)
    assert _reader(repo).latest_snapshot(KEY_B) is None


def test_snapshot_corrupt_payload_fails_closed(tmp_path):
    files_db, repo = _store(tmp_path)
    _capture(repo, files_db, KEY_A)
    # The production immutability trigger forbids UPDATEs; dropping it in a
    # test-owned store simulates bit-rot corruption of the payload column.
    conn = sqlite3.connect(repo.db_path)
    conn.execute("DROP TRIGGER trg_evsnap_no_update")
    conn.execute("UPDATE evidence_snapshots SET snapshot_json='{not json'")
    conn.commit()
    conn.close()

    with pytest.raises(EvidenceStoreError):
        _reader(repo).latest_snapshot(KEY_A)


# ---------------------------------------------------------------------------
# claims_for_analysis
# ---------------------------------------------------------------------------

def test_claims_exact_analysis_with_refs(tmp_path):
    files_db, repo = _store(tmp_path)
    snap_a = _capture(repo, files_db, KEY_A)
    analysis = _analysis(repo, snap_a, candidates=(
        _candidate("first", (KEY_A,)),
        _candidate("second", (KEY_A,)),
    ))

    claims = _reader(repo).claims_for_analysis(analysis.analysis_id)
    assert claims is not None
    assert [c.claim_text for c in claims] == ["first", "second"]
    assert all(c.evidence_refs == (KEY_A,) for c in claims)
    assert claims[0].analysis_id == analysis.analysis_id


def test_claims_scoped_to_task_not_analysis_id_collision(tmp_path):
    files_db, repo = _store(tmp_path)
    snap_a = _capture(repo, files_db, KEY_A)
    analysis = _analysis(repo, snap_a)

    other_reader = InvestigationGraphReader(repo.db_path, "OTHER")
    assert other_reader.claims_for_analysis(analysis.analysis_id) is None


def test_claims_unknown_analysis_is_none(tmp_path):
    files_db, repo = _store(tmp_path)
    assert _reader(repo).claims_for_analysis("sa_missing") is None


def test_claims_analysis_without_claims_is_empty_tuple(tmp_path):
    files_db, repo = _store(tmp_path)
    snap_a = _capture(repo, files_db, KEY_A)
    analysis = _analysis(repo, snap_a, candidates=())

    claims = _reader(repo).claims_for_analysis(analysis.analysis_id)
    assert claims == ()


def test_read_service_claims(tmp_path):
    files_db, repo = _store(tmp_path)
    snap_a = _capture(repo, files_db, KEY_A)
    analysis = _analysis(repo, snap_a)
    service = InvestigationReadService(_Backend(tmp_path))

    claims = asyncio.run(service.list_analysis_claims("A", analysis.analysis_id))
    assert claims is not None and len(claims) == 1
    assert asyncio.run(
        service.list_analysis_claims("A", "sa_other")
    ) is None


# ---------------------------------------------------------------------------
# zero-write + fail-closed discipline
# ---------------------------------------------------------------------------

def test_workbench_reads_never_modify_store_bytes(tmp_path):
    files_db, repo = _store(tmp_path)
    snap_a = _capture(repo, files_db, KEY_A)
    _analysis(repo, snap_a)
    db_file = repo.db_path
    before = hashlib.sha256(db_file.read_bytes()).hexdigest()

    reader = _reader(repo)
    reader.list_evidence()
    reader.latest_snapshot(KEY_A)
    reader.claims_for_analysis(
        asyncio.run(_first_analysis_id(repo, snap_a))
    )

    assert hashlib.sha256(db_file.read_bytes()).hexdigest() == before


async def _first_analysis_id(repo, snapshot):
    return repo.list_analyses(snapshot.evidence_key)[0].analysis_id


def test_workbench_reads_fail_closed_on_unsupported_version(tmp_path):
    files_db, repo = _store(tmp_path)
    _capture(repo, files_db, KEY_A)
    conn = sqlite3.connect(repo.db_path)
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()

    reader = _reader(repo)
    with pytest.raises(EvidenceStoreError):
        reader.list_evidence()
    with pytest.raises(EvidenceStoreError):
        reader.latest_snapshot(KEY_A)
    with pytest.raises(EvidenceStoreError):
        reader.claims_for_analysis("sa_1")


def test_workbench_reads_fail_closed_on_corrupt_store(tmp_path):
    corrupt = tmp_path / "investigation.db"
    corrupt.write_bytes(b"this is not sqlite")
    reader = InvestigationGraphReader(corrupt, "A")
    with pytest.raises(EvidenceStoreError):
        reader.list_evidence()
