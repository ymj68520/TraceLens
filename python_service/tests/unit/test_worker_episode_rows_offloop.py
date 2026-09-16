"""KG hardening Phase A (SPEC docs/specs/kg-ingestion-hardening.md §A1).

The worker's episode-source reads used to run as whole-table ``fetchall()``
directly on the event loop with ``timeout=10``; under C++ write contention
each connect could busy-wait the full timeout, freezing every HTTP endpoint
(observed as a 46 s KG page load, 2026-09-15). These tests pin the new
contract: the reads live in a module-level sync helper with a 2 s
busy_timeout and are invoked via ``asyncio.to_thread``.
"""

import asyncio
import sqlite3
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from httpserver.services.ingestion_job_parts import _worker as worker_mod
from httpserver.services.ingestion_job_manager import IngestionJobManager


def _make_files_db(path: Path, rows: int = 2, with_descriptions: bool = True):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, name TEXT,
                            md5 TEXT, size INTEGER, category TEXT,
                            extension TEXT, type TEXT);
        """
    )
    if with_descriptions:
        conn.execute(
            "CREATE TABLE file_descriptions (file_path TEXT PRIMARY KEY,"
            " description TEXT, summary TEXT, keywords TEXT, is_relevant INTEGER)"
        )
    for i in range(rows):
        fpath = f"/evidence/file{i}.txt"
        conn.execute(
            "INSERT INTO files (path, name, md5, size, category, extension, type)"
            " VALUES (?,?,?,?,?,?,?)",
            (fpath, f"file{i}.txt", f"md5-{i}", 100 + i, "document", ".txt", "file"),
        )
        if with_descriptions:
            conn.execute(
                "INSERT INTO file_descriptions VALUES (?,?,?,?,?)",
                (fpath, f"desc-{i}", f"summary-{i}", "kw", 1),
            )
    conn.commit()
    conn.close()


def _make_events_db(path: Path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, file_path TEXT,"
        " event_type TEXT, timestamp INTEGER, llm_description TEXT,"
        " llm_summary TEXT)"
    )
    conn.execute(
        "INSERT INTO events (file_path, event_type, timestamp, llm_description,"
        " llm_summary) VALUES ('/evidence/file0.txt', 'CREATE', 1700000000,"
        " 'cluster desc', 'cluster summary')"
    )
    conn.commit()
    conn.close()


class TestReadEpisodeSourceRows:
    def test_parses_file_and_cluster_rows(self, tmp_path):
        files_db = tmp_path / "files.db"
        events_db = tmp_path / "events.db"
        _make_files_db(files_db)
        _make_events_db(events_db)

        file_descs, cluster_descs, error = worker_mod._read_episode_source_rows(
            str(files_db), str(events_db), analyzed_only=True
        )

        assert error is None
        assert len(file_descs) == 2
        assert file_descs[0]["file_path"] == "/evidence/file0.txt"
        assert file_descs[0]["description"] == "desc-0"
        assert file_descs[0]["category"] == "document"
        assert file_descs[0]["success"] is True
        assert len(cluster_descs) == 1
        assert cluster_descs[0]["event_type"] == "CREATE"
        assert cluster_descs[0]["analysis"]["description"] == "cluster desc"

    def test_missing_descriptions_table_is_nonfatal(self, tmp_path):
        files_db = tmp_path / "files.db"
        _make_files_db(files_db, with_descriptions=False)

        file_descs, cluster_descs, error = worker_mod._read_episode_source_rows(
            str(files_db), None, analyzed_only=True
        )

        assert file_descs == []
        assert cluster_descs == []
        assert error == "file_descriptions table missing"

    def test_analyzed_only_filters_empty_descriptions(self, tmp_path):
        files_db = tmp_path / "files.db"
        _make_files_db(files_db, rows=3)
        conn = sqlite3.connect(files_db)
        conn.execute(
            "INSERT INTO file_descriptions VALUES ('/evidence/empty.txt',"
            " '', '', '', 0)"
        )
        conn.commit()
        conn.close()

        file_descs, _, _ = worker_mod._read_episode_source_rows(
            str(files_db), None, analyzed_only=True
        )

        assert len(file_descs) == 3


class TestPathAUsesThread:
    @pytest.mark.asyncio
    async def test_reads_run_via_to_thread(self, tmp_path):
        files_db = tmp_path / "files.db"
        files_db.write_bytes(b"")  # existence check only; helper is mocked
        events_db = tmp_path / "events.db"
        events_db.write_bytes(b"")

        manager = IngestionJobManager(settings=mock.Mock())
        manager._update_job_status = mock.AsyncMock()

        sentinel = ([{"file_path": "/x", "description": "d", "success": True}], [], None)
        to_thread_calls = []

        real_to_thread = asyncio.to_thread

        async def spying_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "_mock_name", None) or getattr(fn, "__name__", str(fn))
            to_thread_calls.append(name)
            return await real_to_thread(fn, *args, **kwargs)

        async def fake_ingest(**kwargs):
            return {"successful": 1, "total": 1, "failed": 0}

        graphiti = mock.Mock()
        graphiti.ingest_task_episodes = mock.AsyncMock(side_effect=fake_ingest)
        svc_mgr = mock.Mock()
        svc_mgr.graphiti_service = graphiti

        with mock.patch.object(
            worker_mod, "_read_episode_source_rows", return_value=sentinel
        ) as read_spy, mock.patch.object(
            asyncio, "to_thread", side_effect=spying_to_thread
        ), mock.patch(
            "httpserver.dependencies.get_service_manager", return_value=svc_mgr
        ):
            stats = await manager._ingest_episodes_path_a(
                "job-1", "task-1", str(files_db), str(events_db), analyzed_only=True
            )

        assert to_thread_calls == ["_read_episode_source_rows"]
        read_spy.assert_called_once_with(str(files_db), str(events_db), True)
        assert stats["episodes_successful"] == 1
        assert stats["error"] is None

    @pytest.mark.asyncio
    async def test_read_error_is_preserved(self, tmp_path):
        files_db = tmp_path / "files.db"
        files_db.write_bytes(b"")

        manager = IngestionJobManager(settings=mock.Mock())
        manager._update_job_status = mock.AsyncMock()

        sentinel = ([], [], "file_descriptions table missing")

        async def fake_ingest(**kwargs):
            return {"successful": 1, "total": 1, "failed": 0}

        graphiti = mock.Mock()
        graphiti.ingest_task_episodes = mock.AsyncMock(side_effect=fake_ingest)
        svc_mgr = mock.Mock()
        svc_mgr.graphiti_service = graphiti

        with mock.patch.object(
            worker_mod, "_read_episode_source_rows", return_value=sentinel
        ), mock.patch(
            "httpserver.dependencies.get_service_manager", return_value=svc_mgr
        ):
            stats = await manager._ingest_episodes_path_a(
                "job-1", "task-1", str(files_db), None, analyzed_only=True
            )

        assert stats["error"] == "file_descriptions table missing"


class TestBusyTimeout:
    def test_helper_connects_with_two_second_timeout(self, tmp_path):
        """The helper must not wait 10 s on a locked database: pin timeout=2."""
        import inspect

        source = inspect.getsource(worker_mod._read_episode_source_rows)
        assert "timeout=2" in source
        assert "timeout=10" not in source
