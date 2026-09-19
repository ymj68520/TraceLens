"""Integration tests for ``InvestigationService.bootstrap`` cluster seeding.

The route wiring is covered by ``test_investigation_workbench_routes.py``;
here the real seed service runs against real (temporary) task databases and
asserts through the repository-v7 store the workbench read side consumes:
event derivation, evidence linking + snapshots, and idempotence. Seeding is
flag-independent — it runs identically with the default MVP settings because
it reuses the clusters' existing LLM analysis and never calls an LLM.
"""

import sqlite3
from unittest.mock import AsyncMock, Mock

import pytest

from httpserver.services.investigation_evidence import make_cluster_key
from httpserver.services.investigation.graph_reader import InvestigationGraphReader
from httpserver.services.investigation.repository import InvestigationRepository
from httpserver.services.investigation_service import InvestigationService
from httpserver.services.investigation_persistence import get_investigation_db_path

T0 = 1_700_000_000
MINUTE = T0 // 60


def _make_task_dbs(tmp_path):
    """Create files.db/events.db with two analyzed clusters plus noise."""
    files_db = tmp_path / "files.db"
    events_db = tmp_path / "events.db"

    conn = sqlite3.connect(files_db)
    # Column set mirrors the production files table the v7 snapshot
    # acquisition reads (services/investigation/acquisition.py).
    conn.execute(
        """
        CREATE TABLE files (
            path TEXT PRIMARY KEY, name TEXT, extension TEXT, category TEXT,
            type TEXT, size INTEGER, mtime INTEGER, ctime INTEGER,
            is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO files (path, name, extension, category, type, size,"
        " mtime, ctime, is_deleted, md5, llm_summary, llm_description,"
        " llm_keywords, llm_analyzed_at, llm_model_used, scene_type,"
        " scene_priority, scene_relevant)"
        " VALUES ('/case/a.txt', 'a.txt', 'txt', 'document', 'file', 120,"
        " ?, ?, 0, 'md5-a', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)",
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
        # cluster 2: MODIFIED @ MINUTE (analyzed, no summary -> fallback title)
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


@pytest.fixture
async def seeded(tmp_path):
    files_db, events_db = _make_task_dbs(tmp_path)
    service = _service(tmp_path, files_db, events_db)
    overview = await service.bootstrap("T1")
    repository = InvestigationRepository(
        tmp_path / "investigation.db", "T1"
    )
    return service, overview, repository


async def test_bootstrap_seeds_one_event_per_analyzed_cluster(seeded):
    service, overview, repository = seeded
    assert overview["seeded_clusters"] == 2
    assert overview["new_events"] == 2
    assert overview["event_count"] == 2
    assert overview["initialized"] is True
    assert len(repository.list_events()) == 2


async def test_bootstrap_persists_seed_titles_and_cluster_links(seeded):
    _, _, repository = seeded
    events = {e.title: e for e in repository.list_events()}

    created = events["created summary"]
    modified = events["MODIFIED 活动聚类（1 个事件）"]
    assert created.summary == "created desc"
    assert not modified.summary

    # Provenance on the v1 version doubles as the bootstrap dedup key.
    versions = repository.list_event_versions(created.event_id)
    assert versions[0].created_by == (
        f"cluster_seed:{make_cluster_key(MINUTE, 'CREATED')}"
    )

    links = {
        link.evidence_key
        for link in repository.list_event_evidence(created.event_id)
    }
    assert make_cluster_key(MINUTE, "CREATED") in links
    # /case/a.txt exists in files.db inside the cluster window -> linked
    assert "file:/case/a.txt" in links
    # /case/missing.txt is not in files.db -> never linked
    assert all("missing" not in key for key in links)

    assert repository.get_snapshot(make_cluster_key(MINUTE, "CREATED"))
    assert repository.get_snapshot("file:/case/a.txt")
    assert modified.event_id != created.event_id


async def test_bootstrap_is_idempotent(seeded):
    service, first, repository = seeded
    second = await service.bootstrap("T1")
    assert second["new_events"] == 0
    assert second["seeded_clusters"] == 2
    assert second["event_count"] == first["event_count"] == 2
    assert len(repository.list_events()) == 2


async def test_reader_derives_event_times_and_card_views(seeded):
    """Timeline clocks and evidence cards derive from linked snapshots —
    the v7 event model has no time columns of its own."""
    _, _, repository = seeded
    reader = InvestigationGraphReader(repository.db_path, "T1")
    events = {e.title: e for e in repository.list_events()}
    created_id = events["created summary"].event_id

    bounds = reader.event_time_bounds()
    # CREATED cluster spans [T0, T0+10]; the linked file (mtime=ctime=T0)
    # falls inside, so the derived window is exactly the cluster span.
    assert bounds[created_id] == {"start_time": T0, "end_time": T0 + 10}

    views = {v["evidence_key"]: v for v in reader.describe_event_evidence(created_id)}
    cluster_key = make_cluster_key(MINUTE, "CREATED")
    assert views[cluster_key]["evidence_type"] == "event_cluster"
    assert views[cluster_key]["timestamp"] == T0
    assert views[cluster_key]["role"] == "primary"
    file_view = views["file:/case/a.txt"]
    assert file_view["evidence_type"] == "file"
    assert file_view["title"] == "/case/a.txt"
    assert file_view["timestamp"] == T0
    assert file_view["role"] == "supporting"


async def test_bootstrap_derives_investigation_db_from_files_db(tmp_path):
    files_db, events_db = _make_task_dbs(tmp_path)
    service = _service(tmp_path, files_db, events_db)
    await service.bootstrap("T1")
    assert get_investigation_db_path(str(files_db)).exists()
