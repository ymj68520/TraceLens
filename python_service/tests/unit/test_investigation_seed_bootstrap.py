"""Integration tests for ``InvestigationService.bootstrap`` cluster seeding.

The route wiring is covered by ``test_investigation_workbench_routes.py``;
here the real seed service runs against real (temporary) task databases so
the event derivation, evidence linking, snapshotting, and idempotence are
exercised end to end.
"""

import sqlite3
from unittest.mock import AsyncMock, Mock

import pytest

from httpserver.services.investigation_evidence import make_cluster_key
from httpserver.services.investigation_service import InvestigationService
from httpserver.services.investigation_persistence import (
    BOOTSTRAP_VERSION,
    InvestigationPersistence,
    get_investigation_db_path,
)

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


@pytest.fixture
async def seeded(tmp_path):
    files_db, events_db = _make_task_dbs(tmp_path)
    service = _service(tmp_path, files_db, events_db)
    overview = await service.bootstrap("T1")
    return service, overview, tmp_path / "investigation.db"


async def test_bootstrap_seeds_one_event_per_analyzed_cluster(seeded):
    service, overview, _ = seeded
    assert overview["seeded_clusters"] == 2
    assert overview["new_events"] == 2
    assert overview["event_count"] == 2
    assert overview["initialized"] is True


async def test_bootstrap_persists_seed_titles_and_cluster_links(seeded):
    service, _, inv_db = seeded
    assert inv_db.exists(), "investigation.db must be created next to files.db"
    persistence = InvestigationPersistence(inv_db)
    events = persistence.list_events("T1", limit=10)
    by_key = {e["source_cluster_key"]: e for e in events}

    created = by_key[make_cluster_key(MINUTE, "CREATED")]
    modified = by_key[make_cluster_key(MINUTE, "MODIFIED")]
    assert created["title"] == "created summary"
    assert created["source"] == "cluster_seed"

    links = persistence.list_event_evidence(created["id"], limit=10)
    roles = {(link["evidence_key"], link["role"]) for link in links}
    assert (make_cluster_key(MINUTE, "CREATED"), "primary") in roles
    # /case/a.txt exists in files.db -> linked as supporting cluster member
    assert ("file:/case/a.txt", "supporting") in roles
    # /case/missing.txt is not in files.db -> never linked
    assert all("missing" not in key for key, _ in roles)
    assert persistence.get_snapshot("T1", make_cluster_key(MINUTE, "CREATED"))
    assert modified["id"] != created["id"]


async def test_bootstrap_is_idempotent(seeded):
    service, first, _ = seeded
    second = await service.bootstrap("T1")
    assert second["new_events"] == 0
    assert second["seeded_clusters"] == 2
    assert second["event_count"] == first["event_count"] == 2
    assert second["bootstrap_version"] == BOOTSTRAP_VERSION


async def test_bootstrap_derives_investigation_db_from_files_db(tmp_path):
    files_db, events_db = _make_task_dbs(tmp_path)
    service = _service(tmp_path, files_db, events_db)
    await service.bootstrap("T1")
    assert get_investigation_db_path(str(files_db)).exists()
