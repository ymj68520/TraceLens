"""C7a Investigation Event persistence tests: schema v5, DB-level
invariants (EV1-EV5), repository CRUD, and service ordering."""

from __future__ import annotations

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
    EventEvidenceLink,
    InvestigationEvent,
    InvestigationEventConflictError,
    InvestigationEventService,
    InvestigationRepository,
    SUPPORTED_SCHEMA_VERSION,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_files_db(path: str, file_path: str = "/case/a.txt") -> None:
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
        "INSERT INTO files (path,llm_description,size) VALUES (?,?,?)",
        (file_path, "d", 1),
    )
    conn.commit()
    conn.close()


def _setup_task(tmp_path: Path, task_id: str = "A"):
    """files.db + investigation.db (v5) with one captured file snapshot."""
    files_db = str(tmp_path / "files.db")
    investigation_db = str(tmp_path / "investigation.db")
    _make_files_db(files_db)
    repo = InvestigationRepository(investigation_db, task_id)
    snapshot = repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id, evidence_key="file:/case/a.txt", evidence_type="file",
        normalized_path="/case/a.txt", source_db=files_db,
    ))
    return investigation_db, repo, snapshot


def _backend(task_id: str, db_dir: Path) -> Mock:
    backend = Mock()
    backend.get_task = AsyncMock(return_value={
        "id": task_id,
        "output_files_db": str(db_dir / "files.db"),
    })
    return backend


def _strip_to_v5(idb: str) -> None:
    conn = sqlite3.connect(idb)
    for t in (
        "trg_inv_refresh_no_input_update", "trg_inv_refresh_legal_transition",
        "trg_inv_refresh_no_terminal_update",
    ):
        conn.execute(f"DROP TRIGGER IF EXISTS {t}")
    conn.execute("DROP TABLE IF EXISTS investigation_event_refreshes")
    conn.execute("DROP INDEX IF EXISTS idx_inv_refresh_one_active_per_event")
    conn.execute("DROP INDEX IF EXISTS idx_inv_refreshs_event")
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# migration / schema
# ---------------------------------------------------------------------------

def test_new_db_is_v6(tmp_path):
    idb = str(tmp_path / "investigation.db")
    InvestigationRepository(idb, "A")
    conn = sqlite3.connect(idb)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    conn.close()


def test_v5_to_v6_migration_preserves_existing_data(tmp_path):
    idb, repo, snapshot = _setup_task(tmp_path)
    analysis = repo.create_analysis(snapshot)
    _strip_to_v5(idb)

    reopened = InvestigationRepository(idb, "A")
    conn = sqlite3.connect(idb)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='investigation_event_refreshes'"
    ).fetchone() is not None
    conn.close()
    assert reopened.get_snapshot("file:/case/a.txt") is not None
    assert reopened.get_analysis(analysis.analysis_id).version == 1


def test_validator_fails_closed_on_missing_event_trigger(tmp_path):
    idb, _, _ = _setup_task(tmp_path)
    conn = sqlite3.connect(idb)
    conn.execute("DROP TRIGGER trg_inv_events_no_identity_update")
    conn.commit()
    conn.close()
    with pytest.raises(EvidenceStoreError, match="trg_inv_events_no_identity_update"):
        InvestigationRepository(idb, "A")


# ---------------------------------------------------------------------------
# EV1-EV5: DB-level constraints (direct SQL)
# ---------------------------------------------------------------------------

def test_EV3_child_task_id_mismatch_rejected_by_composite_fk(tmp_path):
    idb, repo, _ = _setup_task(tmp_path)
    event = repo.create_event("title", created_by="analyst")
    conn = sqlite3.connect(idb)
    conn.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO investigation_event_versions "
            "(task_id, event_id, version, title, created_at) VALUES ('B', ?, 1, 'x', 'now')",
            [event.event_id],
        )
    conn.close()


def test_EV2_link_to_uncaptured_evidence_rejected_by_composite_fk(tmp_path):
    idb, repo, _ = _setup_task(tmp_path)
    event = repo.create_event("title", created_by="analyst")
    conn = sqlite3.connect(idb)
    conn.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO investigation_event_evidence "
            "(task_id, event_id, evidence_key, linked_at) VALUES ('A', ?, 'file:/missing', 'now')",
            [event.event_id],
        )
    conn.close()


def test_EV4_direct_delete_on_event_evidence_aborts(tmp_path):
    idb, repo, snapshot = _setup_task(tmp_path)
    event = repo.create_event("title", created_by="analyst")
    repo.link_event_evidence(event.event_id, snapshot.evidence_key)
    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        conn.execute("DELETE FROM investigation_event_evidence")
    remaining = conn.execute("SELECT COUNT(*) FROM investigation_event_evidence").fetchone()[0]
    conn.close()
    assert remaining == 1


def test_EV4_direct_update_on_event_version_aborts(tmp_path):
    idb, repo, _ = _setup_task(tmp_path)
    event = repo.create_event("title", created_by="analyst")
    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        conn.execute(
            "UPDATE investigation_event_versions SET title='hacked' WHERE event_id=?",
            [event.event_id],
        )
    conn.close()


def test_EV5_event_identity_immutable_but_state_columns_writable(tmp_path):
    idb, repo, _ = _setup_task(tmp_path)
    event = repo.create_event("title", created_by="analyst")
    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.DatabaseError, match="identity"):
        conn.execute(
            "UPDATE investigation_events SET task_id='B' WHERE event_id=?",
            [event.event_id],
        )
    # C7b/C7c seam: needs_refresh/updated_at remain writable.
    conn.execute(
        "UPDATE investigation_events SET needs_refresh=1, updated_at='later' WHERE event_id=?",
        [event.event_id],
    )
    conn.commit()
    row = conn.execute(
        "SELECT needs_refresh FROM investigation_events WHERE event_id=?", [event.event_id]
    ).fetchone()
    conn.close()
    assert row[0] == 1


# ---------------------------------------------------------------------------
# repository CRUD
# ---------------------------------------------------------------------------

def test_create_event_writes_event_and_v1_atomically(tmp_path):
    _, repo, _ = _setup_task(tmp_path)
    event = repo.create_event("Título", summary="resumen", created_by="analyst-1")
    assert event.event_id.startswith("ie_")
    assert event.task_id == "A"
    assert event.needs_refresh is False
    assert event.current_version == 1  # derived via MAX(version)
    assert event.title == "Título"
    assert event.summary == "resumen"
    assert event.created_at == event.updated_at
    versions = repo.list_event_versions(event.event_id)
    assert len(versions) == 1
    assert versions[0].version == 1
    assert versions[0].created_by == "analyst-1"


def test_create_event_rejects_empty_title(tmp_path):
    _, repo, _ = _setup_task(tmp_path)
    with pytest.raises(ValueError):
        repo.create_event("")


def test_get_and_list_events_are_task_scoped(tmp_path):
    _, repo, _ = _setup_task(tmp_path)
    event = repo.create_event("t1")
    other = InvestigationRepository(repo.db_path, "B")
    assert other.get_event(event.event_id) is None
    assert other.list_events() == []

    repo.create_event("t2")
    assert len(repo.list_events()) == 2


def test_list_events_filters_needs_refresh(tmp_path):
    _, repo, _ = _setup_task(tmp_path)
    e1 = repo.create_event("t1")
    repo.create_event("t2")
    conn = sqlite3.connect(repo.db_path)
    conn.execute(
        "UPDATE investigation_events SET needs_refresh=1 WHERE event_id=?",
        [e1.event_id],
    )
    conn.commit()
    conn.close()

    dirty = repo.list_events(needs_refresh=True)
    clean = repo.list_events(needs_refresh=False)
    assert [e.event_id for e in dirty] == [e1.event_id]
    assert len(clean) == 1
    assert dirty[0].needs_refresh is True


def test_link_requires_captured_snapshot_and_event(tmp_path):
    _, repo, _ = _setup_task(tmp_path)
    event = repo.create_event("t1")
    with pytest.raises(EvidenceNotFoundError, match="investigation event"):
        repo.link_event_evidence("ie_missing", "file:/case/a.txt")
    with pytest.raises(EvidenceNotFoundError, match="snapshot"):
        repo.link_event_evidence(event.event_id, "file:/not/captured.txt")

    link = repo.link_event_evidence(event.event_id, "file:/case/a.txt", linked_by="a1")
    assert isinstance(link, EventEvidenceLink)
    assert link.evidence_key == "file:/case/a.txt"
    assert link.linked_by == "a1"

    with pytest.raises(InvestigationEventConflictError):
        repo.link_event_evidence(event.event_id, "file:/case/a.txt")


def test_list_event_evidence_and_reverse_lookup(tmp_path):
    _, repo, _ = _setup_task(tmp_path)
    e1 = repo.create_event("t1")
    e2 = repo.create_event("t2")
    repo.link_event_evidence(e1.event_id, "file:/case/a.txt")
    repo.link_event_evidence(e2.event_id, "file:/case/a.txt")

    keys = [l.evidence_key for l in repo.list_event_evidence(e1.event_id)]
    assert keys == ["file:/case/a.txt"]

    for_evidence = repo.list_events_for_evidence("file:/case/a.txt")
    assert {e.event_id for e in for_evidence} == {e1.event_id, e2.event_id}


# ---------------------------------------------------------------------------
# service: GET-no-create + link ordering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_events_returns_empty_without_creating_db(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    _make_files_db(str(task_dir / "files.db"))
    db_path = task_dir / "investigation.db"
    service = InvestigationEventService(_backend("A", task_dir), Mock())

    assert await service.list_events("A") == []
    assert not db_path.exists()  # read path: no DB creation


@pytest.mark.asyncio
async def test_get_event_not_found_without_creating_db(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    _make_files_db(str(task_dir / "files.db"))
    db_path = task_dir / "investigation.db"
    service = InvestigationEventService(_backend("A", task_dir), Mock())

    with pytest.raises(EvidenceNotFoundError):
        await service.get_event("A", "ie_missing")
    with pytest.raises(EvidenceNotFoundError):
        await service.list_event_versions("A", "ie_missing")
    with pytest.raises(EvidenceNotFoundError):
        await service.list_event_evidence("A", "ie_missing")
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_link_nonexistent_event_does_not_capture(tmp_path):
    _, repo, _ = _setup_task(tmp_path)
    capture = Mock()
    capture.capture = AsyncMock()
    service = InvestigationEventService(_backend("A", Path(repo.db_path).parent), capture)

    with pytest.raises(EvidenceNotFoundError, match="investigation event"):
        await service.link_event_evidence(
            "A", "ie_missing", "file:/case/a.txt", linked_by="x"
        )
    capture.capture.assert_not_called()  # no persistence side effect


@pytest.mark.asyncio
async def test_link_resolves_and_captures_before_insert(tmp_path):
    _, repo, snapshot = _setup_task(tmp_path)
    event = repo.create_event("t1")
    capture = Mock()
    capture.capture = AsyncMock(return_value=snapshot)
    service = InvestigationEventService(_backend("A", Path(repo.db_path).parent), capture)

    link = await service.link_event_evidence(
        "A", event.event_id, snapshot.evidence_key, linked_by="analyst"
    )
    capture.capture.assert_awaited_once_with("A", snapshot.evidence_key)
    assert link.evidence_key == snapshot.evidence_key
    assert len(repo.list_event_evidence(event.event_id)) == 1


@pytest.mark.asyncio
async def test_link_evidence_missing_in_task_propagates_not_found(tmp_path):
    _, repo, _ = _setup_task(tmp_path)
    event = repo.create_event("t1")
    capture = Mock()
    capture.capture = AsyncMock(side_effect=EvidenceNotFoundError("no such evidence"))
    service = InvestigationEventService(_backend("A", Path(repo.db_path).parent), capture)

    with pytest.raises(EvidenceNotFoundError):
        await service.link_event_evidence(
            "A", event.event_id, "file:/other/task/b.txt", linked_by="x"
        )
    assert repo.list_event_evidence(event.event_id) == []  # 0 links


@pytest.mark.asyncio
async def test_create_and_read_roundtrip_through_service(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    _make_files_db(str(task_dir / "files.db"))
    service = InvestigationEventService(_backend("A", task_dir), Mock())

    created = await service.create_event(
        "A", title="事件", summary="叙述", created_by="analyst-1"
    )
    assert isinstance(created, InvestigationEvent)
    fetched = await service.get_event("A", created.event_id)
    assert fetched == created
    versions = await service.list_event_versions("A", created.event_id)
    assert len(versions) == 1
    assert await service.list_event_evidence("A", created.event_id) == []


@pytest.mark.asyncio
async def test_corrupt_store_maps_to_store_error(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "investigation.db").write_bytes(b"not sqlite")
    service = InvestigationEventService(_backend("A", task_dir), Mock())
    with pytest.raises(EvidenceStoreError):
        await service.get_event("A", "ie_any")
