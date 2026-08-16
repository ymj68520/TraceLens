"""Phase R1 Report Evidence: frozen explicit binding semantics (§19 matrix).

Identity is exactly (task_id, evidence_key) of a captured snapshot; the
optional analysis_id binding is an EXPLICIT frozen accepted version -- never
"latest accepted" -- and changes only through explicit analyst actions.
Cross-task binding attempts fail opaquely (not-found, never probeable).
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from httpserver.services.evidence import (
    EvidenceNotFoundError,
    EvidenceStoreError,
    ResolvedEvidence,
)
from httpserver.services.investigation import (
    AnalysisBindingConflictError,
    AnalysisReviewDecision,
    ClaimCandidate,
    InvestigationGraphReader,
    InvestigationRepository,
    ReportEvidenceConflictError,
    ReportEvidenceService,
    ReportEvidenceStatus,
    SecondaryAnalysisStatus,
    SUPPORTED_SCHEMA_VERSION,
)

PROMPT_V3 = "investigation-evidence-analysis:v3"
KEY = "file:/case/a.txt"
OTHER_KEY = "file:/case/b.txt"


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


def _make_files_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"""
    )
    conn.execute(
        "INSERT INTO files (path, llm_description, size) VALUES (?,?,?)",
        ("/case/a.txt", "d", 1),
    )
    conn.execute(
        "INSERT INTO files (path, llm_description, size) VALUES (?,?,?)",
        ("/case/b.txt", "d", 2),
    )
    conn.commit()
    conn.close()


def _repo_with_evidence(tmp_path: Path, task_id: str = "A", keys: tuple = (KEY,)):
    root = tmp_path / task_id
    root.mkdir(parents=True, exist_ok=True)
    files_db = str(root / "files.db")
    _make_files_db(files_db)
    repo = InvestigationRepository(root / "investigation.db", task_id)
    snapshots = {}
    for key in keys:
        normalized = key.removeprefix("file:")
        snapshots[key] = repo.capture_if_absent(ResolvedEvidence(
            task_id=task_id, evidence_key=key, evidence_type="file",
            normalized_path=normalized, source_db=files_db,
        ))
    return repo, snapshots


def _analysis_at(
    repo: InvestigationRepository,
    snapshot,
    *,
    decision: str | None,  # None = leave review_pending
):
    """Create one analysis version and drive it to the requested state."""
    analysis = repo.create_analysis(snapshot, prompt_version=PROMPT_V3)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis.analysis_id,
        description="d", summary="s", model="m",
        candidates=[ClaimCandidate(
            claim_type="FACT", claim_text="c", evidence_refs=(snapshot.evidence_key,),
        )],
    )
    if decision is not None:
        repo.review_analysis(
            analysis.analysis_id,
            decision=AnalysisReviewDecision(decision),
            reviewer="analyst-x",
        )
    return repo.get_analysis(analysis.analysis_id)


# ---------------------------------------------------------------------------
# §19: evidence without analysis -> main + analysis_id NULL
# ---------------------------------------------------------------------------

def test_add_without_analysis_is_main_with_null_binding(tmp_path):
    repo, _ = _repo_with_evidence(tmp_path)
    row = repo.add_report_evidence(KEY, report_status="main", added_by="analyst-x")

    assert row.report_status is ReportEvidenceStatus.main
    assert row.analysis_id is None
    assert row.added_by == "analyst-x"
    assert row.updated_by == "analyst-x"

    reader = InvestigationGraphReader(
        tmp_path / "A" / "investigation.db", "A"
    )
    items = reader.list_report_evidence()
    assert len(items) == 1
    assert items[0].analysis_id is None
    assert items[0].bound_analysis is None
    assert items[0].newer_accepted_available is False  # nothing accepted yet


# §17: no accepted analysis must still be reportable as Original Evidence.
def test_appendix_without_analysis_is_allowed(tmp_path):
    repo, _ = _repo_with_evidence(tmp_path)
    row = repo.add_report_evidence(KEY, report_status="appendix", added_by="a")
    assert row.report_status is ReportEvidenceStatus.appendix


def test_add_requires_captured_snapshot(tmp_path):
    repo, _ = _repo_with_evidence(tmp_path)
    with pytest.raises(EvidenceNotFoundError):
        repo.add_report_evidence("file:/case/never-captured.txt",
                                 report_status="main", added_by="a")


def test_add_rejects_excluded_status(tmp_path):
    repo, _ = _repo_with_evidence(tmp_path)
    with pytest.raises(ValueError):
        repo.add_report_evidence(KEY, report_status="excluded", added_by="a")


def test_duplicate_add_conflicts(tmp_path):
    repo, _ = _repo_with_evidence(tmp_path)
    repo.add_report_evidence(KEY, report_status="main", added_by="a")
    with pytest.raises(ReportEvidenceConflictError):
        repo.add_report_evidence(KEY, report_status="appendix", added_by="a")


# ---------------------------------------------------------------------------
# §19: accepted A1 -> explicit binding
# ---------------------------------------------------------------------------

def test_explicit_binding_to_accepted_analysis(tmp_path):
    repo, snaps = _repo_with_evidence(tmp_path, keys=(KEY, OTHER_KEY))
    accepted = _analysis_at(repo, snaps[KEY], decision="accepted")
    other_accepted = _analysis_at(repo, snaps[OTHER_KEY], decision="accepted")

    row = repo.add_report_evidence(
        KEY, report_status="main", analysis_id=accepted.analysis_id, added_by="a"
    )
    assert row.analysis_id == accepted.analysis_id

    reader = InvestigationGraphReader(tmp_path / "A" / "investigation.db", "A")
    item = reader.get_report_evidence(KEY)
    assert item.bound_analysis.analysis_id == accepted.analysis_id
    assert item.bound_analysis.version == accepted.version
    assert item.bound_analysis.decided_by == "analyst-x"
    assert item.newer_accepted_available is False


# ---------------------------------------------------------------------------
# §19: review_pending / rejected / invalid cannot bind (add AND update)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("decision", ["rejected", "invalid"])
def test_non_accepted_terminal_cannot_bind(tmp_path, decision):
    repo, snaps = _repo_with_evidence(tmp_path)
    bad = _analysis_at(repo, snaps[KEY], decision=decision)
    with pytest.raises(AnalysisBindingConflictError):
        repo.add_report_evidence(
            KEY, report_status="main", analysis_id=bad.analysis_id, added_by="a"
        )
    repo.add_report_evidence(KEY, report_status="main", added_by="a")
    with pytest.raises(AnalysisBindingConflictError):
        repo.update_report_evidence(
            KEY, analysis_id=bad.analysis_id, bind_analysis=True, updated_by="a"
        )


def test_review_pending_cannot_bind(tmp_path):
    repo, snaps = _repo_with_evidence(tmp_path)
    pending = _analysis_at(repo, snaps[KEY], decision=None)
    with pytest.raises(AnalysisBindingConflictError):
        repo.add_report_evidence(
            KEY, report_status="main", analysis_id=pending.analysis_id, added_by="a"
        )


# ---------------------------------------------------------------------------
# §19: analysis of a different evidence / different task
# ---------------------------------------------------------------------------

def test_analysis_of_different_evidence_rejected(tmp_path):
    repo, snaps = _repo_with_evidence(tmp_path, keys=(KEY, OTHER_KEY))
    foreign = _analysis_at(repo, snaps[OTHER_KEY], decision="accepted")
    repo.add_report_evidence(KEY, report_status="main", added_by="a")
    with pytest.raises(AnalysisBindingConflictError):
        repo.update_report_evidence(
            KEY, analysis_id=foreign.analysis_id, bind_analysis=True, updated_by="a"
        )


def test_analysis_of_different_task_is_opaque_not_found(tmp_path):
    repo_a, _ = _repo_with_evidence(tmp_path / "isolation", task_id="A")
    repo_b, _ = _repo_with_evidence(tmp_path / "isolation", task_id="B")
    accepted_a = _analysis_at(repo_a, repo_a.get_snapshot(KEY), decision="accepted")
    # Direct cross-task attempt at repository level: the foreign analysis_id
    # simply does not exist in B's store (opaque not-found, no probing).
    repo_b.add_report_evidence(KEY, report_status="main", added_by="b")
    with pytest.raises(EvidenceNotFoundError):
        repo_b.update_report_evidence(
            KEY, analysis_id=accepted_a.analysis_id,
            bind_analysis=True, updated_by="b",
        )


# ---------------------------------------------------------------------------
# §16: version-freeze scenario (the core R1 test)
# ---------------------------------------------------------------------------

def test_binding_stays_frozen_until_explicit_rebind(tmp_path):
    repo, snaps = _repo_with_evidence(tmp_path)
    a1 = _analysis_at(repo, snaps[KEY], decision="accepted")
    repo.add_report_evidence(
        KEY, report_status="main", analysis_id=a1.analysis_id, added_by="a"
    )
    reader = InvestigationGraphReader(tmp_path / "A" / "investigation.db", "A")

    # A2 review_pending -> report still A1
    _analysis_at(repo, snaps[KEY], decision=None)
    item = reader.get_report_evidence(KEY)
    assert item.analysis_id == a1.analysis_id
    assert item.newer_accepted_available is False  # pending never counts

    # A2 accepted -> report STILL A1, but the hint appears
    a2 = _analysis_at(repo, snaps[KEY], decision="accepted")
    item = reader.get_report_evidence(KEY)
    assert item.analysis_id == a1.analysis_id
    assert item.bound_analysis.version == a1.version
    assert item.newer_accepted_available is True

    # Explicit rebind (analyst action only) -> becomes A2, hint clears
    row = repo.update_report_evidence(
        KEY, analysis_id=a2.analysis_id, bind_analysis=True, updated_by="a2-owner"
    )
    assert row.analysis_id == a2.analysis_id
    item = reader.get_report_evidence(KEY)
    assert item.bound_analysis.version == a2.version
    assert item.newer_accepted_available is False


# §17/§11: binding NULL + accepted exists -> bindable hint, no auto-switch.
def test_null_binding_with_accepted_shows_hint_without_autobind(tmp_path):
    repo, snaps = _repo_with_evidence(tmp_path)
    _analysis_at(repo, snaps[KEY], decision="accepted")
    repo.add_report_evidence(KEY, report_status="main", added_by="a")

    reader = InvestigationGraphReader(tmp_path / "A" / "investigation.db", "A")
    item = reader.get_report_evidence(KEY)
    assert item.analysis_id is None
    assert item.newer_accepted_available is True


# ---------------------------------------------------------------------------
# §19: excluded <-> main <-> appendix transitions
# ---------------------------------------------------------------------------

def test_status_transitions_are_explicit_and_audited(tmp_path):
    repo, _ = _repo_with_evidence(tmp_path)
    row = repo.add_report_evidence(KEY, report_status="main", added_by="adder")
    created_at = row.created_at

    for status, actor in (("excluded", "u1"), ("appendix", "u2"), ("main", "u3")):
        row = repo.update_report_evidence(
            KEY, report_status=status, updated_by=actor
        )
        assert row.report_status is ReportEvidenceStatus(status)
        assert row.updated_by == actor
        assert row.added_by == "adder"        # immutable audit field
        assert row.created_at == created_at   # immutable audit field


def test_update_missing_row_not_found(tmp_path):
    repo, _ = _repo_with_evidence(tmp_path)
    with pytest.raises(EvidenceNotFoundError):
        repo.update_report_evidence(KEY, report_status="main", updated_by="a")


def test_update_requires_an_explicit_change(tmp_path):
    repo, _ = _repo_with_evidence(tmp_path)
    repo.add_report_evidence(KEY, report_status="main", added_by="a")
    with pytest.raises(ValueError):
        repo.update_report_evidence(KEY, updated_by="a")


def test_update_without_analysis_field_keeps_binding(tmp_path):
    repo, snaps = _repo_with_evidence(tmp_path)
    accepted = _analysis_at(repo, snaps[KEY], decision="accepted")
    repo.add_report_evidence(
        KEY, report_status="main", analysis_id=accepted.analysis_id, added_by="a"
    )
    row = repo.update_report_evidence(KEY, report_status="excluded", updated_by="b")
    assert row.analysis_id == accepted.analysis_id  # untouched, not cleared


# ---------------------------------------------------------------------------
# DB guards: identity immutability, no-delete, composite FKs
# ---------------------------------------------------------------------------

def test_identity_and_delete_triggers(tmp_path):
    repo, _ = _repo_with_evidence(tmp_path)
    repo.add_report_evidence(KEY, report_status="main", added_by="a")
    db = str(tmp_path / "A" / "investigation.db")
    with sqlite3.connect(db) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE report_evidence SET evidence_key='file:/x' "
                "WHERE task_id='A'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="excluded"):
            conn.execute("DELETE FROM report_evidence")


def test_composite_fk_blocks_uncaptured_and_unknown_analysis(tmp_path):
    repo, _ = _repo_with_evidence(tmp_path)
    db = str(tmp_path / "A" / "investigation.db")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO report_evidence (task_id, evidence_key, report_status,"
                " added_by, created_at, updated_at)"
                " VALUES ('A','file:/uncaptured.txt','main','x','n','n')"
            )
        # An analysis_id that exists in no store row fails the composite FK.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO report_evidence (task_id, evidence_key, report_status,"
                " analysis_id, added_by, created_at, updated_at)"
                " VALUES ('A',?, 'main','sa_does_not_exist','x','n','n')",
                (KEY,),
            )


# ---------------------------------------------------------------------------
# Cross-task isolation (§19 evidence integrity)
# ---------------------------------------------------------------------------

def test_report_evidence_is_task_scoped(tmp_path):
    repo_a, _ = _repo_with_evidence(tmp_path / "iso", task_id="A")
    repo_b, _ = _repo_with_evidence(tmp_path / "iso", task_id="B")

    repo_a.add_report_evidence(KEY, report_status="main", added_by="a")
    repo_b.add_report_evidence(KEY, report_status="appendix", added_by="b")

    reader_a = InvestigationGraphReader(tmp_path / "iso" / "A" / "investigation.db", "A")
    reader_b = InvestigationGraphReader(tmp_path / "iso" / "B" / "investigation.db", "B")
    items_a = reader_a.list_report_evidence()
    items_b = reader_b.list_report_evidence()
    assert [i.report_status for i in items_a] == [ReportEvidenceStatus.main]
    assert [i.report_status for i in items_b] == [ReportEvidenceStatus.appendix]

    # Same normalized-looking path, different task: no cross-task binding.
    with pytest.raises(EvidenceNotFoundError):
        repo_b.update_report_evidence(
            "file:/case/only-in-a.txt", report_status="main", updated_by="b"
        )


# ---------------------------------------------------------------------------
# Schema compatibility: report_evidence is an optional v7 extension (R1)
# ---------------------------------------------------------------------------

def _strip_report_extension(db_path: Path) -> None:
    """Simulate a C10-era v7 store: same version, no R1 extension objects."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TRIGGER trg_report_evidence_no_identity_update")
        conn.execute("DROP TRIGGER trg_report_evidence_no_delete")
        conn.execute("DROP INDEX idx_secondary_task_analysis")
        conn.execute("DROP TABLE report_evidence")


def test_c10_v7_store_reads_empty_and_is_never_mutated_by_report_gets(tmp_path):
    repo, _ = _repo_with_evidence(tmp_path)
    db_path = tmp_path / "A" / "investigation.db"
    _strip_report_extension(db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    # Strict reader GET: a v7 store without the extension simply has no
    # report evidence; nothing is created or migrated (C10 §14/E13).
    reader = InvestigationGraphReader(db_path, "A")
    assert reader.list_report_evidence() == []
    assert reader.get_report_evidence(KEY) is None
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_v7_store_keeps_version_and_report_write_path_works(tmp_path):
    repo, snaps = _repo_with_evidence(tmp_path)
    accepted = _analysis_at(repo, snaps[KEY], decision="accepted")
    db_path = tmp_path / "A" / "investigation.db"
    _strip_report_extension(db_path)

    # Reopening a v7 store keeps user_version=7 and every pre-existing row.
    reopened = InvestigationRepository(db_path, "A")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    assert reopened.get_analysis(accepted.analysis_id).analysis_id == accepted.analysis_id

    # The first explicit Report write builds the extension and works.
    added = reopened.add_report_evidence(
        KEY, report_status="main", analysis_id=accepted.analysis_id, added_by="a"
    )
    assert added.analysis_id == accepted.analysis_id
    row = reopened.update_report_evidence(KEY, report_status="appendix", updated_by="m")
    assert row.analysis_id == accepted.analysis_id
    reader = InvestigationGraphReader(db_path, "A")
    item = reader.get_report_evidence(KEY)
    assert item.bound_analysis.version == accepted.version


def test_fresh_store_initializes_at_v7_with_extension(tmp_path):
    _repo_with_evidence(tmp_path)
    with sqlite3.connect(tmp_path / "A" / "investigation.db") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_evidence'"
        ).fetchone() is not None
    assert SUPPORTED_SCHEMA_VERSION == 7


# ---------------------------------------------------------------------------
# Service layer (HTTP-adjacent semantics)
# ---------------------------------------------------------------------------

def _fake_cpp(task_id: str, files_db: Path):
    cpp = Mock()
    cpp.get_task = AsyncMock(return_value={
        "id": task_id,
        "output_files_db": str(files_db),
    })
    return cpp


def _service_with_store(tmp_path: Path, task_id: str = "A"):
    """One task dir whose files.db/store are shared by repo and service."""
    repo, snaps = _repo_with_evidence(tmp_path, task_id=task_id)
    files_db = tmp_path / task_id / "files.db"
    service = ReportEvidenceService(_fake_cpp(task_id, files_db))
    return service, repo, snaps


def _service_without_store(tmp_path: Path, task_id: str = "A"):
    root = tmp_path / task_id
    root.mkdir(parents=True, exist_ok=True)
    files_db = root / "files.db"
    _make_files_db(str(files_db))
    return ReportEvidenceService(_fake_cpp(task_id, files_db))


def test_service_list_missing_store_returns_empty_and_never_creates(tmp_path):
    service = _service_without_store(tmp_path)
    assert asyncio_run(service.list("A")) == []
    assert not (tmp_path / "A" / "investigation.db").exists()


def test_service_add_update_list_roundtrip(tmp_path):
    service, repo, snaps = _service_with_store(tmp_path)
    accepted = _analysis_at(repo, snaps[KEY], decision="accepted")

    added = asyncio_run(service.add(
        "A", KEY, report_status="main",
        analysis_id=accepted.analysis_id, added_by="analyst-x",
    ))
    assert added.analysis_id == accepted.analysis_id
    updated = asyncio_run(service.update(
        "A", KEY, report_status="excluded", updated_by="analyst-y",
    ))
    assert updated.report_status is ReportEvidenceStatus.excluded
    items = asyncio_run(service.list("A"))
    assert [i.evidence_key for i in items] == [KEY]


def test_service_unknown_task_fails_opaquely(tmp_path):
    service = _service_without_store(tmp_path)
    cpp = Mock()
    cpp.get_task = AsyncMock(return_value=None)
    service._cpp_backend = cpp
    with pytest.raises(EvidenceNotFoundError):
        asyncio_run(service.add("ghost", KEY, report_status="main", added_by="a"))
    with pytest.raises(EvidenceNotFoundError):
        asyncio_run(service.list("ghost"))


def test_service_list_on_unsupported_store_fails_closed(tmp_path):
    service, _, _ = _service_with_store(tmp_path)
    db_path = tmp_path / "A" / "investigation.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 6")
    with pytest.raises(EvidenceStoreError):
        asyncio_run(service.list("A"))
