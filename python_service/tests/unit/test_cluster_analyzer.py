import sqlite3

import pytest

from httpserver.config import Settings
from httpserver.services.case_analysis.cluster_analyzer import ClusterAnalyzer


def _db(tmp_path):
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, "
            "file_path TEXT, llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, "
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
