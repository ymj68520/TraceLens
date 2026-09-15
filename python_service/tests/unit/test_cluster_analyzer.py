import sqlite3

import pytest

from httpserver.config import Settings
from httpserver.services.case_analysis.cluster_analyzer import ClusterAnalyzer
from httpserver.services.case_analysis.schema import (
    ensure_cluster_analysis_schema,
    members_fingerprint,
)


def _db(tmp_path):
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, "
            "file_path TEXT, description TEXT, llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, "
            "llm_is_relevant INTEGER, llm_analyzed_at INTEGER, llm_model_used TEXT)"
        )
        conn.executemany(
            "INSERT INTO events (id, timestamp, event_type, file_path) VALUES (?, ?, ?, ?)",
            [
                (1, 120, "MODIFIED", "/foo/a.txt"),
                (2, 121, "MODIFIED", "/foobar/b.txt"),
            ],
        )
        conn.commit()
    return path


def test_persist_cluster_analysis_targets_trusted_member_ids(tmp_path):
    path = _db(tmp_path)
    analyzer = ClusterAnalyzer(Settings(), None, None)
    analyzer.persist_cluster_analysis(
        str(path),
        {"time_window": 2, "event_type": "MODIFIED", "parent_directory": "/foo/", "member_ids": "1"},
        {"analysis": {"summary": "summary", "description": "description", "keywords": ["foo"]}, "model": "test"},
    )
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT id, llm_summary FROM events ORDER BY id").fetchall()
    assert rows[0][1] == "summary"
    assert rows[1][1] is None


def test_persist_cluster_analysis_rejects_empty_trusted_member_set(tmp_path):
    path = _db(tmp_path)
    analyzer = ClusterAnalyzer(Settings(), None, None)
    with pytest.raises(sqlite3.DatabaseError, match="no trusted member IDs"):
        analyzer.persist_cluster_analysis(
            str(path),
            {"time_window": 2, "event_type": "MODIFIED", "parent_directory": "/foo/", "member_ids": ""},
            {"analysis": {"summary": "summary"}, "model": "test"},
        )
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT llm_summary FROM events WHERE id = 1").fetchone()[0] is None


_CLUSTER = {
    "time_window": 2,
    "event_type": "MODIFIED",
    "parent_directory": "/foo/",
    "bucket_seconds": 60,
    "bucket_epoch_offset": 0,
    "member_ids": "1",
}


def test_persist_cluster_analysis_appends_analysis_row_and_dual_writes(tmp_path):
    path = _db(tmp_path)
    analyzer = ClusterAnalyzer(Settings(), None, None)
    analyzer.persist_cluster_analysis(
        str(path),
        dict(_CLUSTER),
        {"analysis": {"summary": "s", "description": "d", "keywords": ["k1", "k2"]}, "model": "m1"},
        task_id="task-1",
    )
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM event_cluster_analyses").fetchone()
        event = conn.execute("SELECT llm_summary, llm_analyzed_at, llm_model_used FROM events WHERE id = 1").fetchone()

    assert row["task_id"] == "task-1"
    assert row["trigger_source"] == "pipeline"
    assert row["bucket_seconds"] == 60
    assert row["bucket_index"] == 2
    assert row["member_count"] == 1
    assert row["members_hash"] == members_fingerprint([1])["members_hash"]
    assert row["ingested_at"] is None
    assert event["llm_summary"] == "s"
    assert event["llm_model_used"] == "m1"
    assert event["llm_analyzed_at"] is not None


def test_persist_cluster_analysis_rolls_back_analysis_row_when_member_update_incomplete(tmp_path):
    path = _db(tmp_path)
    analyzer = ClusterAnalyzer(Settings(), None, None)
    bogus = dict(_CLUSTER, member_ids="1,999")  # 999 does not exist -> rowcount mismatch
    with pytest.raises(sqlite3.DatabaseError, match="incomplete"):
        analyzer.persist_cluster_analysis(
            str(path), bogus, {"analysis": {"summary": "s"}, "model": "m"}, task_id="task-1"
        )
    with sqlite3.connect(path) as conn:
        # Atomic: neither the analysis record nor the event cache may survive.
        assert conn.execute("SELECT COUNT(*) FROM event_cluster_analyses").fetchone()[0] == 0
        assert conn.execute("SELECT llm_summary FROM events WHERE id = 1").fetchone()[0] is None


def test_persist_cluster_analysis_records_bucket_offset(tmp_path):
    path = _db(tmp_path)
    analyzer = ClusterAnalyzer(Settings(), None, None)
    shifted = dict(_CLUSTER, time_window=7, bucket_epoch_offset=57600)
    analyzer.persist_cluster_analysis(
        str(path), shifted, {"analysis": {"summary": "s"}, "model": "m"}, task_id="task-1"
    )
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT bucket_epoch_offset, bucket_index FROM event_cluster_analyses"
        ).fetchone()
    assert tuple(row) == (57600, 7)


async def test_fetch_event_clusters_uses_offset_and_canonical_expression(tmp_path):
    path = _db(tmp_path)
    with sqlite3.connect(path) as conn:
        ensure_cluster_analysis_schema(str(path))
        conn.execute(
            "INSERT INTO analysis_meta (key, value) VALUES ('bucket_epoch_offset', '60')"
        )
        conn.commit()

    analyzer = ClusterAnalyzer(Settings(), None, None)
    clusters = await analyzer.fetch_event_clusters(str(path))
    # Events at 120/121 minus offset 60 land in bucket 1. /foo/ and /foobar/
    # are distinct parent directories, so each stays its own cluster.
    by_key = {(c["time_window"], c["event_type"], c["parent_directory"]): c for c in clusters}
    assert (1, "MODIFIED", "/foo/") in by_key
    assert (1, "MODIFIED", "/foobar/") in by_key
    first = by_key[(1, "MODIFIED", "/foo/")]
    assert first["bucket_seconds"] == 60
    assert first["bucket_epoch_offset"] == 60
    assert first["first_event_id"] == 1
    assert first["last_event_id"] == 1


async def test_analyze_and_ingest_clusters_writes_analysis_rows(tmp_path):
    path = _db(tmp_path)

    class _FakeLLM:
        async def analyze_event_cluster(self, event_data, prompt=None):
            return {"analysis": {"summary": "s", "description": "d", "keywords": ["k"]}, "model": "fake"}

    analyzer = ClusterAnalyzer(Settings(), _FakeLLM(), None)
    results = await analyzer.analyze_and_ingest_clusters(str(path), "case", "task-9")

    assert len(results) == 2
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT task_id, trigger_source, event_type FROM event_cluster_analyses"
        ).fetchall()
        analyzed = conn.execute(
            "SELECT COUNT(*) FROM events WHERE llm_analyzed_at IS NOT NULL"
        ).fetchone()[0]
    assert {r[0] for r in rows} == {"task-9"}
    assert {r[1] for r in rows} == {"pipeline"}
    assert analyzed == 2
