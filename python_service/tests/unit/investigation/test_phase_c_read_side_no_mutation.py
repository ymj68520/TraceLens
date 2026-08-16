"""Phase C cross-stage integration: GET read-side never mutates
(C10 §14, E13 — regression tests for the C10 strict-read fix).

Three guarantees, proven through the SAME service paths the HTTP GET
routes use:
  1. a missing investigation.db stays missing ([] / 404 / None — never
     created by a read);
  2. a healthy v7 store is byte-identical after every read projection;
  3. a store with an unsupported schema version fails closed (503
     semantics) and is NOT migrated or self-healed by the read.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from httpserver.services.evidence import EvidenceNotFoundError, EvidenceStoreError
from httpserver.services.investigation import (
    InvestigationEventService,
    InvestigationGraphReader,
    InvestigationRepository,
    SecondaryAnalysisExecutor,
)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_cpp(task_id: str, files_db: Path):
    cpp = Mock()
    cpp.get_task = AsyncMock(return_value={
        "id": task_id,
        "output_files_db": str(files_db),
    })
    return cpp


@pytest.fixture()
def populated_store(tmp_path: Path):
    """A v7 store with one accepted analysis, one dirty event, one refresh."""
    files_db = tmp_path / "files.db"
    conn = sqlite3.connect(files_db)
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
    conn.commit()
    conn.close()

    from httpserver.services.evidence import ResolvedEvidence
    from httpserver.services.investigation import (
        AnalysisReviewDecision,
        SecondaryAnalysisStatus,
    )

    repo = InvestigationRepository(tmp_path / "investigation.db", "t1")
    snapshot = repo.capture_if_absent(ResolvedEvidence(
        task_id="t1", evidence_key="file:/case/a.txt", evidence_type="file",
        normalized_path="/case/a.txt", source_db=str(files_db),
    ))
    analysis = repo.create_analysis(
        snapshot, prompt_version="investigation-evidence-analysis:v3"
    )
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis.analysis_id, description="d", summary="s",
        model="m", candidates=[],
    )
    repo.review_analysis(
        analysis.analysis_id, decision=AnalysisReviewDecision.accepted,
        reviewer="analyst",
    )
    event = repo.create_event("E1", created_by="a")
    repo.link_event_evidence(event.event_id, "file:/case/a.txt", linked_by="a")
    refresh = repo.create_event_refresh(event.event_id, requested_by="a")
    return repo, event, analysis, refresh, files_db


@pytest.mark.asyncio
async def test_missing_store_is_never_created_by_reads(tmp_path: Path):
    files_db = tmp_path / "files.db"
    files_db.write_bytes(b"placeholder")
    cpp = _fake_cpp("t1", files_db)
    events = InvestigationEventService(cpp, Mock())
    executor = SecondaryAnalysisExecutor(cpp, Mock(), Mock())
    reader_home = tmp_path / "investigation.db"
    assert not reader_home.exists()

    assert await events.list_events("t1") == []
    with pytest.raises(EvidenceNotFoundError):
        await events.get_event("t1", "ie_missing")
    assert await executor.get_analysis("t1", "sa_missing") is None
    assert await executor.list_analyses("t1", "file:/case/a.txt") == []

    # THE C10 P1-a regression: no GET path materialized the store.
    assert not reader_home.exists()


def test_healthy_store_is_byte_identical_after_all_read_projections(
    populated_store,
):
    repo, event, analysis, refresh, _ = populated_store
    db_path = Path(repo.db_path)
    before = _file_hash(db_path)

    reader = InvestigationGraphReader(db_path, "t1")
    reader.read()
    reader.list_evidence()
    reader.latest_snapshot("file:/case/a.txt")
    reader.claims_for_analysis(analysis.analysis_id)
    reader.list_events()
    reader.get_event(event.event_id)
    reader.list_event_versions(event.event_id)
    reader.list_event_evidence(event.event_id)
    reader.get_event_refresh(refresh.refresh_id)
    reader.list_event_refreshes(event.event_id)
    reader.get_analysis(analysis.analysis_id)
    reader.list_analyses("file:/case/a.txt")

    assert _file_hash(db_path) == before
    assert not Path(f"{db_path}-wal").exists()
    assert not Path(f"{db_path}-shm").exists()


@pytest.mark.asyncio
async def test_unsupported_version_fails_closed_without_migration(tmp_path: Path):
    files_db = tmp_path / "files.db"
    files_db.write_bytes(b"placeholder")
    cpp = _fake_cpp("t1", files_db)
    db_path = tmp_path / "investigation.db"
    db_path.write_bytes(b"")
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 6")
    before = _file_hash(db_path)

    events = InvestigationEventService(cpp, Mock())
    with pytest.raises(EvidenceStoreError):
        await events.list_events("t1")

    reader = InvestigationGraphReader(db_path, "t1")
    with pytest.raises(EvidenceStoreError):
        reader.get_analysis("sa_x")
    with pytest.raises(EvidenceStoreError):
        reader.list_event_refreshes("ie_x")

    # Not migrated, not healed: version and bytes untouched by reads.
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    assert _file_hash(db_path) == before


@pytest.mark.asyncio
async def test_tampered_v7_store_is_not_self_healed_by_reads(populated_store):
    """A dropped trigger (tamper evidence) survives reads unrepaired."""
    repo, _, _, _, _ = populated_store
    db_path = Path(repo.db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TRIGGER trg_secondary_legal_transition")
        conn.commit()
    before = _file_hash(db_path)

    reader = InvestigationGraphReader(db_path, "t1")
    assert reader.list_events() != []  # data still readable
    assert _file_hash(db_path) == before  # and nothing was repaired on read

    # The WRITE path still refuses the damaged store (fails closed).
    with pytest.raises(EvidenceStoreError):
        InvestigationRepository(db_path, "t1")
