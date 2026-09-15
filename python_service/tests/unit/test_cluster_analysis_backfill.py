"""Backfill tests: migrate per-event llm_* into analysis rows (SPEC §3.3)."""

import sqlite3

from httpserver.services.case_analysis.backfill import backfill_events_db
from httpserver.services.case_analysis.schema import members_fingerprint


def _analyzed_db(tmp_path):
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, "
            "file_path TEXT, description TEXT, llm_summary TEXT, llm_description TEXT, "
            "llm_keywords TEXT, llm_is_relevant INTEGER, llm_analyzed_at INTEGER, "
            "llm_model_used TEXT)"
        )
        # Group A: two members at 60s bucket 2, /foo/; latest analysis on id 2.
        # Group B: single member in another directory. Id 5 stays unanalyzed.
        conn.executemany(
            "INSERT INTO events (id, timestamp, event_type, file_path, llm_summary, "
            "llm_description, llm_keywords, llm_analyzed_at, llm_model_used) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, 120, "MODIFIED", "/foo/a.txt", "old summary", "old desc", "k0", 100, "m0"),
                (2, 150, "MODIFIED", "/foo/b.txt", "new summary", "new desc", "k1", 200, "m1"),
                (3, 130, "CREATED", "/bar/c.txt", "bar summary", "bar desc", "k2", 150, "m2"),
                (5, 999, "MODIFIED", "/foo/d.txt", None, None, None, None, None),
            ],
        )
        conn.commit()
    return path


def test_backfill_reconstructs_migrated_rows(tmp_path):
    path = _analyzed_db(tmp_path)
    summary = backfill_events_db(str(path), task_id="task-bf")
    assert summary == {"status": "backfilled", "rows": 2}

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = {
            (row["bucket_index"], row["event_type"], row["parent_directory"]): row
            for row in conn.execute("SELECT * FROM event_cluster_analyses")
        }

    group_a = rows[(2, "MODIFIED", "/foo/")]
    assert group_a["trigger_source"] == "migrated"
    assert group_a["task_id"] == "task-bf"
    assert group_a["bucket_epoch_offset"] == 0
    assert group_a["bucket_seconds"] == 60
    assert group_a["member_count"] == 2
    assert group_a["member_min_id"] == 1
    assert group_a["member_max_id"] == 2
    assert group_a["members_hash"] == members_fingerprint([1, 2])["members_hash"]
    # Text comes from the latest-analyzed member of the group.
    assert group_a["summary"] == "new summary"
    assert group_a["created_at"] == 200

    group_b = rows[(2, "CREATED", "/bar/")]
    assert group_b["member_count"] == 1
    assert group_b["summary"] == "bar summary"


def test_backfill_is_idempotent_and_skips_databases_with_any_rows(tmp_path):
    path = _analyzed_db(tmp_path)
    assert backfill_events_db(str(path))["status"] == "backfilled"
    # Second run: rows already exist -> untouched.
    again = backfill_events_db(str(path))
    assert again["status"] == "skipped"
    with sqlite3.connect(path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM event_cluster_analyses").fetchone()[0]
    assert count == 2

    # Even a database holding only migrated rows is never re-touched.
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM event_cluster_analyses WHERE rowid > 1")
        conn.commit()
    assert backfill_events_db(str(path))["status"] == "skipped"
    with sqlite3.connect(path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM event_cluster_analyses").fetchone()[0]
    assert count == 1


def test_backfill_empty_database_backfills_zero(tmp_path):
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, "
            "file_path TEXT, llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, "
            "llm_analyzed_at INTEGER, llm_model_used TEXT)"
        )
        conn.commit()
    summary = backfill_events_db(str(path))
    assert summary == {"status": "backfilled", "rows": 0}
