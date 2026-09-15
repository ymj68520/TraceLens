"""Tests for budget-driven adaptive bucketing and the task-level run (SPEC §5/§8.1)."""

import sqlite3

import pytest

from httpserver.config import Settings
from httpserver.services.case_analysis.adaptive import (
    BUCKET_LADDER,
    choose_bucket,
    estimate_bucket,
    estimate_bucket_ladder,
)
from httpserver.services.case_analysis.cluster_analyzer import ClusterAnalyzer
from httpserver.services.case_analysis.schema import (
    ensure_cluster_analysis_schema,
    find_latest_analysis,
)
from httpserver.services.investigation_evidence import (
    TIMELINE_MAX_BUCKET_SECONDS,
    validate_timeline_group_descriptor,
)


def _events_db(tmp_path, analyzed_ids=()):
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, "
            "file_path TEXT, description TEXT, llm_summary TEXT, llm_description TEXT, "
            "llm_keywords TEXT, llm_is_relevant INTEGER, llm_analyzed_at INTEGER, "
            "llm_model_used TEXT)"
        )
        rows = [
            (1, 120, "MODIFIED", "/foo/a.txt", "d"),
            (2, 130, "MODIFIED", "/foo/b.txt", "d"),
            (3, 5000, "MODIFIED", "/foo/c.txt", "d"),
            (4, 60000, "CREATED", "/bar/d.txt", "d"),
        ]
        for row in rows:
            marker = 777 if row[0] in analyzed_ids else None
            conn.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*row, marker, marker, marker, marker, marker, marker),
            )
        conn.commit()
    return str(path)


def test_bucket_ladder_spans_one_minute_to_thirty_days():
    assert BUCKET_LADDER[0] == 60
    assert BUCKET_LADDER[-1] == 2592000
    assert BUCKET_LADDER == sorted(set(BUCKET_LADDER))


def test_estimate_bucket_counts_clusters_per_window(tmp_path):
    events_db = _events_db(tmp_path)
    # At 60s: ids 1,2 share bucket 2 (/foo/ MODIFIED); id 3 lands in bucket 83;
    # id 4 (CREATED, /bar/) in bucket 1000 -> three clusters, largest has 2.
    at_60 = estimate_bucket(events_db, 60)
    assert at_60["cluster_count"] == 3
    assert at_60["max_members"] == 2
    # At 21600s (6 h): all /foo/ MODIFIED events merge into one cluster and
    # /bar/ CREATED forms its own.
    at_6h = estimate_bucket(events_db, 21600)
    assert at_6h["cluster_count"] == 2
    assert at_6h["max_members"] == 3


def test_estimate_respects_analyzed_filter(tmp_path):
    events_db = _events_db(tmp_path, analyzed_ids=(1, 2, 3))
    including = estimate_bucket(events_db, 60, include_analyzed=True)
    excluding = estimate_bucket(events_db, 60, include_analyzed=False)
    assert including["cluster_count"] == 3
    # Only id 4 (bucket 1000, /bar/ CREATED) remains unanalyzed.
    assert excluding["cluster_count"] == 1


def test_choose_bucket_picks_smallest_that_fits_budget():
    estimates = [
        {"bucket_seconds": 60, "cluster_count": 500, "max_members": 3},
        {"bucket_seconds": 300, "cluster_count": 150, "max_members": 9},
        {"bucket_seconds": 900, "cluster_count": 40, "max_members": 30},
    ]
    choice = choose_bucket(estimates, budget=200)
    assert choice["recommended_bucket_seconds"] == 300
    assert choice["warning"] is None


def test_choose_bucket_warns_when_budget_unreachable():
    estimates = [
        {"bucket_seconds": 60, "cluster_count": 900, "max_members": 3},
        {"bucket_seconds": 2592000, "cluster_count": 800, "max_members": 4},
    ]
    choice = choose_bucket(estimates, budget=200)
    assert choice["recommended_bucket_seconds"] == 2592000
    assert "budget" in choice["warning"]


async def test_run_analysis_is_idempotent_per_coordinate(tmp_path):
    events_db = _events_db(tmp_path)

    class _FakeLLM:
        async def analyze_event_cluster(self, event_data, prompt=None):
            return {"analysis": {"summary": "s", "description": "d", "keywords": ["k"]}, "model": "fake"}

    analyzer = ClusterAnalyzer(Settings(), _FakeLLM(), None)

    first = await analyzer.run_analysis("task-r", events_db, case_description="case")
    assert first["cluster_total"] == 3
    assert first["analyzed"] == 3
    assert first["skipped_fresh"] == 0

    # Second run: every coordinate has a fresh analysis record -> nothing to do.
    second = await analyzer.run_analysis("task-r", events_db, case_description="case")
    assert second["analyzed"] == 0
    assert second["skipped_fresh"] == 3

    with sqlite3.connect(events_db) as conn:
        runs = conn.execute(
            "SELECT status, cluster_total, cluster_failed FROM cluster_analysis_runs ORDER BY id"
        ).fetchall()
        records = conn.execute("SELECT COUNT(*) FROM event_cluster_analyses").fetchone()[0]
    assert runs == [("completed", 3, 0), ("completed", 3, 0)]
    assert records == 3


async def test_run_analysis_rejects_out_of_range_bucket(tmp_path):
    events_db = _events_db(tmp_path)
    analyzer = ClusterAnalyzer(Settings(), None, None)
    with pytest.raises(ValueError, match="out of range"):
        await analyzer.run_analysis("task-r", events_db, bucket_seconds=TIMELINE_MAX_BUCKET_SECONDS + 1)


def test_pipeline_fetch_keeps_skip_filter_but_run_fetch_covers_all(tmp_path):
    events_db = _events_db(tmp_path, analyzed_ids=(1, 2))

    async def _fetch(include):
        analyzer = ClusterAnalyzer(Settings(), None, None)
        clusters = await analyzer.fetch_event_clusters(events_db, include_analyzed=include)
        return sum(c["cluster_count"] for c in clusters)

    import asyncio

    # Pipeline (D9): analyzed events stay out. Run: everything is covered.
    assert asyncio.run(_fetch(False)) == 2
    assert asyncio.run(_fetch(True)) == 4


def test_descriptor_validation_accepts_analysis_windows_up_to_thirty_days():
    base = {"bucket_index": 1, "bucket_seconds": 2592000, "event_type": "MODIFIED",
            "parent_directory": "/x/"}
    assert validate_timeline_group_descriptor(base)["bucket_seconds"] == 2592000
    assert validate_timeline_group_descriptor(
        {**base, "bucket_seconds": 604800}
    )["bucket_seconds"] == 604800
    with pytest.raises(ValueError, match="out of range"):
        validate_timeline_group_descriptor({**base, "bucket_seconds": 2592001})


def test_find_latest_analysis_returns_newest_version(tmp_path):
    events_db = _events_db(tmp_path)
    ensure_cluster_analysis_schema(events_db)
    with sqlite3.connect(events_db) as conn:
        for summary in ("v1", "v2"):
            conn.execute(
                "INSERT INTO event_cluster_analyses (task_id, bucket_seconds, bucket_index, "
                "event_type, parent_directory, member_count, member_min_id, member_max_id, "
                "members_hash, summary, trigger_source, created_at) VALUES "
                "('t', 60, 2, 'MODIFIED', '/foo/', 2, 1, 2, 'h', ?, 'pipeline', 1)",
                (summary,),
            )
        conn.commit()
    latest = find_latest_analysis(events_db, 0, 60, 2, "MODIFIED", "/foo/")
    assert latest["summary"] == "v2"
    assert find_latest_analysis(events_db, 0, 300, 2, "MODIFIED", "/foo/") is None
