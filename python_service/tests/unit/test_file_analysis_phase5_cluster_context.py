"""
Phase 5 (C3-v0) regression tests: related_file_summaries derivation —
member files ordered by activity, deduplicated, capped, summary-only,
tolerant of missing files/records.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from httpserver.services.case_analysis.cluster_analyzer import (
    related_file_summaries,
)
from httpserver.services.case_analysis.file_schema import (
    ensure_file_analysis_schema,
)


def _make_events_db(tmp_path, members):
    """events db with one cluster's members (path, count) at window 10×60."""
    db = str(tmp_path / "t_events.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER,"
        " event_type TEXT, file_path TEXT, llm_description TEXT)"
    )
    ts = 10 * 60
    for path, count in members:
        for i in range(count):
            conn.execute(
                "INSERT INTO events (timestamp, event_type, file_path)"
                " VALUES (?, 'FILE_CREATE', ?)",
                (ts + i, path),
            )
    conn.commit()
    conn.close()
    return db


def _add_analysis(files_db, path, summary, description=""):
    with sqlite3.connect(files_db) as conn:
        conn.execute(
            "INSERT INTO file_analyses (task_id, file_path, md5, summary,"
            " description, keywords, model, extraction_method,"
            " trigger_source, created_at)"
            " VALUES ('t1', ?, '', ?, ?, '', 'm', '', 'pipeline', 1)",
            (path, summary, description or summary),
        )
        conn.commit()


class TestRelatedFileSummaries:
    def _fixture(self, tmp_path, members, analyses=()):
        events_db = _make_events_db(tmp_path, members)
        files_db = str(tmp_path / "t_files.db")
        ensure_file_analysis_schema(files_db)
        import sqlite3
        with sqlite3.connect(files_db) as conn:
            conn.execute(
                "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT,"
                " md5 TEXT, mtime INTEGER, ctime INTEGER)"
            )
            for path, _count in members:
                conn.execute("INSERT INTO files (path) VALUES (?)", (path,))
            conn.commit()
        for path, summary, description in analyses:
            _add_analysis(files_db, path, summary, description)
        return events_db, files_db

    def _query(self, events_db, files_db, limit=20):
        return related_file_summaries(
            events_db, files_db,
            bucket_epoch_offset=0, bucket_seconds=60, bucket_index=10,
            event_type="FILE_CREATE", parent_directory="/data/",
            limit=limit,
        )

    async def test_order_dedupe_and_summary(self, tmp_path):
        events_db, files_db = self._fixture(
            tmp_path,
            members=[("/data/busy.txt", 5), ("/data/quiet.txt", 1)],
            analyses=[
                ("/data/busy.txt", "busy 摘要", ""),
                ("/data/quiet.txt", "quiet 摘要", ""),
            ],
        )
        # event counts: busy=5 quiet=1 → busy first; INSERT loop adds i=0..4
        result = self._query(events_db, files_db)
        assert [r["file_path"] for r in result][0] == "/data/busy.txt"
        assert len(result) == 2
        assert result[0]["summary"] == "busy 摘要"
        assert all(r["model"] == "m" for r in result)

    async def test_unanalyzed_files_skipped(self, tmp_path):
        events_db, files_db = self._fixture(
            tmp_path, members=[("/data/a.txt", 2)],
        )
        assert self._query(events_db, files_db) == []

    async def test_cap_at_limit(self, tmp_path):
        members = [(f"/data/f{i}.txt", 1) for i in range(30)]
        events_db, files_db = self._fixture(
            tmp_path, members, [(p, "s", "") for p, _c in members]
        )
        result = self._query(events_db, files_db, limit=20)
        assert len(result) == 20

    async def test_missing_dbs_tolerated(self, tmp_path):
        assert self._query(str(tmp_path / "nope.db"), "") == []
        events_db = _make_events_db(tmp_path, [("/a", 1)])
        assert self._query(events_db, "") == []

    async def test_coordinate_miss_is_empty(self, tmp_path):
        events_db, files_db = self._fixture(
            tmp_path, members=[("/data/a.txt", 2)],
            analyses=[("/data/a.txt", "s", "")],
        )
        result = related_file_summaries(
            events_db, files_db,
            bucket_epoch_offset=0, bucket_seconds=60, bucket_index=999,
            event_type="FILE_CREATE", parent_directory="/data/",
        )
        assert result == []
