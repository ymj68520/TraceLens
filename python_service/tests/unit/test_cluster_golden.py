"""Golden fixture for clustering coordinates (SPEC §4.4, Python side).

Two independent Python implementations of the clustering semantics must agree
on the same fixture database:

1. ``ClusterAnalyzer.fetch_event_clusters`` — the pipeline GROUP BY;
2. ``read_timeline_group_members`` — the descriptor-driven member lookup.

The C++ implementations join the golden contract in Phase C; the fixture row
list below is the shared truth both sides must reproduce.
"""

import sqlite3

from httpserver.config import Settings
from httpserver.services.case_analysis.cluster_analyzer import ClusterAnalyzer
from httpserver.services.investigation_evidence import read_timeline_group_members

# (id, timestamp, event_type, file_path)
FIXTURE_ROWS = [
    (1, 0, "MODIFIED", "/etc/a.conf"),        # epoch zero pile-up
    (2, 30, "MODIFIED", "/etc/b.conf"),       # same 60s bucket + dir as id 1
    (3, 59, "CREATED", "/etc/c.conf"),        # same bucket, other type
    (4, 60, "MODIFIED", "/etc/d.conf"),       # next bucket
    (5, -1, "MODIFIED", "/var/log/w.log"),    # negative: SQL truncates -1/60 -> 0
    (6, 86399, "DELETED", "/tmp/x"),          # last second of day (UTC)
    (7, 86405, "DELETED", "/tmp/y"),          # next day, same dir+type as 6
    (8, 57600, "MODIFIED", "/opt/z"),         # 57600 == offset bucket boundary
]

OFFSET_57600 = 57600  # UTC+8 local-midnight alignment


def _fixture_db(tmp_path, offset=None):
    path = tmp_path / "golden_events.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, "
            "event_type TEXT, file_path TEXT, description TEXT, inode INTEGER, "
            "llm_summary TEXT, llm_analyzed_at INTEGER)"
        )
        conn.executemany(
            "INSERT INTO events (id, timestamp, event_type, file_path) VALUES (?, ?, ?, ?)",
            FIXTURE_ROWS,
        )
        if offset is not None:
            conn.execute(
                "CREATE TABLE analysis_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO analysis_meta VALUES ('bucket_epoch_offset', ?)", (str(offset),)
            )
        conn.commit()
    return str(path)


def _parse_member_ids(concatenated):
    return sorted(int(v) for v in str(concatenated or "").split(",") if v)


async def test_pipeline_groups_and_member_lookup_agree_offset_zero(tmp_path):
    events_db = _fixture_db(tmp_path)
    analyzer = ClusterAnalyzer(Settings(), None, None)
    clusters = await analyzer.fetch_event_clusters(events_db)

    assert clusters, "fixture must produce clusters"
    for cluster in clusters:
        descriptor = {
            "bucket_index": cluster["time_window"],
            "bucket_seconds": cluster["bucket_seconds"],
            "event_type": cluster["event_type"],
            "parent_directory": cluster["parent_directory"],
            "bucket_epoch_offset": cluster["bucket_epoch_offset"],
        }
        members = read_timeline_group_members(events_db, descriptor)
        assert [row["id"] for row in members] == _parse_member_ids(cluster["member_ids"])


async def test_pipeline_groups_and_member_lookup_agree_with_local_offset(tmp_path):
    events_db = _fixture_db(tmp_path, offset=OFFSET_57600)
    analyzer = ClusterAnalyzer(Settings(), None, None)
    clusters = await analyzer.fetch_event_clusters(events_db)

    assert all(c["bucket_epoch_offset"] == OFFSET_57600 for c in clusters)
    for cluster in clusters:
        descriptor = {
            "bucket_index": cluster["time_window"],
            "bucket_seconds": cluster["bucket_seconds"],
            "event_type": cluster["event_type"],
            "parent_directory": cluster["parent_directory"],
            "bucket_epoch_offset": OFFSET_57600,
        }
        members = read_timeline_group_members(events_db, descriptor)
        assert [row["id"] for row in members] == _parse_member_ids(cluster["member_ids"])

    # Full expected coordinate set under offset 57600. Truncation toward zero
    # matters below the offset: (30-57600)/60 = -959.5 -> -959, so id 2 shares
    # a bucket with id 4 (ts 60) rather than id 1 (ts 0, exactly -960).
    expected = {
        (-960, "MODIFIED", "/etc/"): [1],
        (-959, "MODIFIED", "/etc/"): [2, 4],
        (-959, "CREATED", "/etc/"): [3],
        (-960, "MODIFIED", "/var/log/"): [5],
        (479, "DELETED", "/tmp/"): [6],
        (480, "DELETED", "/tmp/"): [7],
        (0, "MODIFIED", "/opt/"): [8],
    }
    actual = {
        (c["time_window"], c["event_type"], c["parent_directory"]): sorted(
            _parse_member_ids(c["member_ids"])
        )
        for c in clusters
    }
    assert actual == expected


def test_zero_and_negative_timestamps_keep_sql_truncation_semantics(tmp_path):
    """-1/60 must group into bucket 0 (toward zero), matching SQLite's `/`."""
    events_db = _fixture_db(tmp_path)
    rows = read_timeline_group_members(
        events_db,
        {
            "bucket_index": 0,
            "bucket_seconds": 60,
            "event_type": "MODIFIED",
            "parent_directory": "/var/log/",
        },
    )
    assert [row["id"] for row in rows] == [5]
