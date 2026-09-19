"""Integration tests for ``InvestigationService.bootstrap`` cluster seeding.

The route wiring is covered by ``test_investigation_workbench_routes.py``;
here the real seed service runs against real (temporary) task databases so
the event derivation, evidence linking, snapshotting, and idempotence are
exercised end to end.

Regression (defect: v3-seeded stores 503'd on the workbench read side):
bootstrap must always leave a repository-v7 store that the strict workbench
reader (``InvestigationGraphReader``) accepts, whether or not cluster
seeding ran.
"""

import sqlite3
from unittest.mock import AsyncMock, Mock

import pytest

from httpserver.services.evidence.exceptions import EvidenceStoreError
from httpserver.services.investigation.graph_reader import InvestigationGraphReader
from httpserver.services.investigation.repository import InvestigationRepository
from httpserver.services.investigation_evidence import make_cluster_key
from httpserver.services.investigation_persistence import (
    InvestigationPersistence,
    get_investigation_db_path,
)
from httpserver.services.investigation_service import InvestigationService

T0 = 1_700_000_000
MINUTE = T0 // 60


def _make_task_dbs(tmp_path):
    """Create files.db/events.db with two analyzed clusters plus noise."""
    files_db = tmp_path / "files.db"
    events_db = tmp_path / "events.db"

    conn = sqlite3.connect(files_db)
    conn.execute(
        """
        CREATE TABLE files (
            path TEXT PRIMARY KEY, name TEXT, mtime INTEGER, ctime INTEGER,
            size INTEGER, md5 TEXT, extension TEXT, is_deleted INTEGER,
            llm_summary TEXT, llm_description TEXT, llm_analyzed_at INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO files (path, name, mtime, ctime, size, md5, extension,"
        " is_deleted, llm_summary, llm_description, llm_analyzed_at)"
        " VALUES ('/case/a.txt', 'a.txt', ?, ?, 120, 'md5-a', 'txt', 0,"
        " NULL, NULL, NULL)",
        (T0, T0),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(events_db)
    conn.execute(
        """
        CREATE TABLE events (
            id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT,
            file_path TEXT, llm_analyzed_at INTEGER, llm_summary TEXT,
            llm_description TEXT
        )
        """
    )
    rows = [
        # cluster 1: CREATED @ MINUTE (two analyzed events, one linking a file)
        (T0, "CREATED", "/case/a.txt", 1, "created summary", "created desc"),
        (T0 + 10, "CREATED", "/case/missing.txt", 1, None, None),
        # cluster 2: MODIFIED @ MINUTE (analyzed)
        (T0 + 20, "MODIFIED", "/case/a.txt", 1, None, None),
        # noise: same window but never LLM-analyzed -> must be ignored
        (T0 + 30, "DELETED", "/case/a.txt", None, None, None),
    ]
    conn.executemany(
        "INSERT INTO events (timestamp, event_type, file_path,"
        " llm_analyzed_at, llm_summary, llm_description) VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return files_db, events_db


def _service(tmp_path, files_db, events_db):
    backend = Mock()
    backend.get_task = AsyncMock(
        return_value={
            "id": "T1",
            "output_files_db": str(files_db),
            "output_events_db": str(events_db),
            "output_raw_db": "",
            "extraction_directory": "",
        }
    )
    return InvestigationService(cpp_backend=backend)


@pytest.fixture(autouse=True)
def _enable_event_llm(monkeypatch):
    """These tests exercise cluster seeding itself; the default-off gate
    (EVENT_LLM_ANALYSIS_ENABLED, MVP §4.2) must be lifted for the seeding
    branch to run."""
    from httpserver.config import get_settings

    monkeypatch.setattr(get_settings(), "event_llm_analysis_enabled", True)


@pytest.fixture
async def seeded(tmp_path):
    files_db, events_db = _make_task_dbs(tmp_path)
    service = _service(tmp_path, files_db, events_db)
    overview = await service.bootstrap("T1")
    return service, overview, tmp_path / "investigation.db"


def _store_version(inv_db) -> int:
    with sqlite3.connect(inv_db) as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


async def test_bootstrap_seeds_one_event_per_analyzed_cluster(seeded):
    service, overview, _ = seeded
    assert overview["seeded_clusters"] == 2
    assert overview["new_events"] == 2
    assert overview["event_count"] == 2
    assert overview["initialized"] is True


async def test_bootstrap_leaves_v7_store_the_workbench_reader_accepts(seeded):
    service, _, inv_db = seeded
    assert inv_db.exists(), "investigation.db must be created next to files.db"
    assert _store_version(inv_db) == 7

    # The strict read side (mode=ro, fail-closed schema check) must accept
    # the store and return the seeded narratives.
    reader = InvestigationGraphReader(str(inv_db), "T1")
    events = {e.title: e for e in reader.list_events()}
    assert set(events) == {"created summary", "MODIFIED 活动聚类（1 个事件）"}

    created = events["created summary"]
    modified = events["MODIFIED 活动聚类（1 个事件）"]
    assert created.current_version == 1
    assert created.summary == "created desc"
    assert modified.event_id != created.event_id

    # Seed identity anchor: exactly one cluster Evidence link per Event,
    # recorded as an immutable v1 narrative by cluster_seed.
    versions = reader.list_event_versions(created.event_id)
    assert [(v.version, v.created_by) for v in versions] == [(1, "cluster_seed")]
    links = reader.list_event_evidence(created.event_id)
    assert [l.evidence_key for l in links] == [make_cluster_key(MINUTE, "CREATED")]


async def test_bootstrap_captures_cluster_snapshots(seeded):
    service, _, inv_db = seeded
    repository = InvestigationRepository.open_existing(str(inv_db), "T1")
    snapshot = repository.get_snapshot(make_cluster_key(MINUTE, "CREATED"))
    assert snapshot is not None
    assert snapshot.evidence_type == "cluster"
    assert snapshot.payload.event_count == 2


async def test_bootstrap_is_idempotent(seeded):
    service, first, inv_db = seeded
    second = await service.bootstrap("T1")
    assert second["new_events"] == 0
    assert second["seeded_clusters"] == 2
    assert second["event_count"] == first["event_count"] == 2
    assert _store_version(inv_db) == 7
    reader = InvestigationGraphReader(str(inv_db), "T1")
    assert len(reader.list_events()) == 2


async def test_event_presentation_derives_timeline_facts(seeded):
    """The Workbench presentation projection derives legacy-vocabulary fields
    (time bounds, link count, seed origin, link display) from the immutable
    overlay rows in one strict read."""
    service, _, inv_db = seeded
    reader = InvestigationGraphReader(str(inv_db), "T1")
    events = {e.title: e for e in reader.list_events()}
    presentation = reader.event_presentation()

    created = presentation[events["created summary"].event_id]
    assert created["evidence_count"] == 1
    assert created["cluster_seed"] is True
    # bounds come from the linked cluster snapshot's captured window
    assert created["start_time"] == T0
    assert created["end_time"] == T0 + 10
    link = created["links"][0]
    assert link["evidence_key"] == make_cluster_key(MINUTE, "CREATED")
    assert link["evidence_type"] == "event_cluster"
    assert link["title"] == "CREATED 聚类（2 个事件）"
    assert link["timestamp"] == T0
    assert link["analysis_status"] is None

    modified = presentation[events["MODIFIED 活动聚类（1 个事件）"].event_id]
    assert modified["cluster_seed"] is True
    assert modified["start_time"] == T0 + 20
    assert modified["end_time"] == T0 + 20


async def test_bootstrap_survives_legacy_persistence_open(seeded):
    """The legacy v3 writer must not downgrade a v7 store it opens.

    Other legacy code paths still construct ``InvestigationPersistence``
    against the task's investigation.db; its schema guard has to recognize
    the v7 store and leave it untouched, or the read side would fail closed
    again (the original defect)."""
    service, _, inv_db = seeded
    InvestigationPersistence(inv_db)
    assert _store_version(inv_db) == 7


async def test_bootstrap_derives_investigation_db_from_files_db(tmp_path):
    files_db, events_db = _make_task_dbs(tmp_path)
    service = _service(tmp_path, files_db, events_db)
    await service.bootstrap("T1")
    assert get_investigation_db_path(str(files_db)).exists()


async def test_bootstrap_without_llm_analysis_ensures_empty_v7_store(
    tmp_path, monkeypatch
):
    """MVP §4.2 default path: no seeding, but the store is still ensured in
    v7 form so the workbench reads succeed instead of 503."""
    from httpserver.config import get_settings

    monkeypatch.setattr(get_settings(), "event_llm_analysis_enabled", False)
    files_db, events_db = _make_task_dbs(tmp_path)
    service = _service(tmp_path, files_db, events_db)
    overview = await service.bootstrap("T1")
    inv_db = tmp_path / "investigation.db"
    assert _store_version(inv_db) == 7
    assert overview["seeded_clusters"] == 0
    assert overview["new_events"] == 0
    assert overview["event_count"] == 0
    reader = InvestigationGraphReader(str(inv_db), "T1")
    assert reader.list_events() == []


async def test_reader_rejects_v3_store(tmp_path):
    """Fail-closed contract on the read side: a legacy v3 store must raise
    EvidenceStoreError from the strict reader, never silently read."""
    import pathlib

    legacy = pathlib.Path(tmp_path) / "investigation.db"
    conn = sqlite3.connect(legacy)
    conn.execute("CREATE TABLE investigation_events (id TEXT PRIMARY KEY)")
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()
    reader = InvestigationGraphReader(str(legacy), "T1")
    with pytest.raises(EvidenceStoreError):
        reader.list_events()


def _poison_side_store(inv_db):
    """Recreate the legacy artifact: workbench side tables inside a
    user_version=0 file the v7 store was never built into (workbench reads
    used to materialize exactly this shape before bootstrap ran)."""
    conn = sqlite3.connect(inv_db)
    conn.executescript(
        """
        CREATE TABLE workbench_event_review (
            task_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            review_status TEXT NOT NULL,
            updated_by TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (task_id, event_id)
        );
        CREATE TABLE workbench_analyst_notes (
            task_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_key TEXT NOT NULL,
            content TEXT NOT NULL,
            author TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (task_id, target_type, target_key)
        );
        """
    )
    conn.execute(
        "INSERT INTO workbench_event_review VALUES"
        " ('T1', 'ev-1', 'confirmed', 'workbench', '2026-09-19T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()


async def test_bootstrap_heals_side_table_only_zero_version_store(tmp_path):
    """Regression: a user_version=0 file holding only workbench side tables
    made bootstrap raise "schema 0 requires manual migration" (503) even
    though no investigation data exists. Bootstrap must heal it into a v7
    store the workbench reader accepts, preserving the side rows."""
    files_db, events_db = _make_task_dbs(tmp_path)
    inv_db = tmp_path / "investigation.db"
    _poison_side_store(inv_db)
    service = _service(tmp_path, files_db, events_db)

    overview = await service.bootstrap("T1")

    assert overview["initialized"] is True
    assert _store_version(inv_db) == 7
    with sqlite3.connect(inv_db) as conn:
        status = conn.execute(
            "SELECT review_status FROM workbench_event_review"
        ).fetchone()[0]
    assert status == "confirmed"
    # The strict workbench reader accepts the healed store (seeding ran:
    # two analyzed clusters), and the side row survived the rebuild.
    reader = InvestigationGraphReader(str(inv_db), "T1")
    assert len(reader.list_events()) == 2


async def test_bootstrap_still_fails_closed_on_unknown_zero_version_store(tmp_path):
    """A version-0 file with non-side-table content is unknown provenance:
    keep failing closed instead of initializing over it."""
    conn = sqlite3.connect(tmp_path / "investigation.db")
    conn.execute("CREATE TABLE mystery (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    files_db, events_db = _make_task_dbs(tmp_path)
    service = _service(tmp_path, files_db, events_db)
    with pytest.raises(EvidenceStoreError):
        await service.bootstrap("T1")
