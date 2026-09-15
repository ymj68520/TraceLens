"""Schema/DDL tests for the cluster-analysis tables (SPEC §3)."""

import sqlite3

from httpserver.services.case_analysis.schema import (
    CLUSTER_ANALYSIS_DDL,
    ensure_cluster_analysis_schema,
    members_fingerprint,
    read_bucket_epoch_offset,
)


def test_ensure_schema_is_idempotent(tmp_path):
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as conn:
        # A task events db only guarantees the events table; the module must
        # not depend on anything else pre-existing.
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY)")
        conn.commit()

    ensure_cluster_analysis_schema(str(path))
    first = sqlite3.connect(path)
    shapes = first.execute(
        "SELECT name, sql FROM sqlite_master WHERE type IN ('table','index') ORDER BY name"
    ).fetchall()
    first.close()

    ensure_cluster_analysis_schema(str(path))
    second = sqlite3.connect(path)
    shapes_again = second.execute(
        "SELECT name, sql FROM sqlite_master WHERE type IN ('table','index') ORDER BY name"
    ).fetchall()
    second.close()

    assert shapes == shapes_again
    names = {name for name, _ in shapes}
    assert {"event_cluster_analyses", "cluster_analysis_runs", "analysis_meta"} <= names


def test_analyses_table_is_append_only_shaped(tmp_path):
    """Guard the SPEC §3.2 invariants that downstream code relies on."""
    path = tmp_path / "events.db"
    ensure_cluster_analysis_schema(str(path))
    conn = sqlite3.connect(path)
    columns = {
        row[1]: row for row in conn.execute("PRAGMA table_info(event_cluster_analyses)")
    }
    for required in (
        "id", "task_id", "bucket_epoch_offset", "bucket_seconds", "bucket_index",
        "event_type", "parent_directory", "member_count", "member_min_id",
        "member_max_id", "members_hash", "trigger_source", "analysis_id_upstream",
        "created_at", "ingested_at",
    ):
        assert required in columns, f"missing column {required}"
    notnull = {name for name, row in columns.items() if row[3]}
    assert {"task_id", "bucket_seconds", "bucket_index", "members_hash", "trigger_source"} <= notnull
    conn.close()


def test_read_bucket_epoch_offset_defaults_to_zero(tmp_path):
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY)")
        conn.commit()
    # No analysis_meta table at all (legacy database).
    assert read_bucket_epoch_offset(str(path)) == 0

    ensure_cluster_analysis_schema(str(path))
    assert read_bucket_epoch_offset(str(path)) == 0

    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO analysis_meta (key, value) VALUES ('bucket_epoch_offset', '57600')"
        )
        conn.commit()
    assert read_bucket_epoch_offset(str(path)) == 57600

    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE analysis_meta SET value = 'not-a-number'")
        conn.commit()
    assert read_bucket_epoch_offset(str(path)) == 0

    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE analysis_meta SET value = '99999'")
        conn.commit()
    assert read_bucket_epoch_offset(str(path)) == 0


def test_members_fingerprint_is_order_insensitive_and_strong():
    ordered = members_fingerprint([3, 1, 2])
    shuffled = members_fingerprint([2, 3, 1])
    assert ordered == shuffled
    assert ordered["member_count"] == 3
    assert ordered["member_min_id"] == 1
    assert ordered["member_max_id"] == 3
    assert len(ordered["members_hash"]) == 64

    import pytest

    with pytest.raises(ValueError):
        members_fingerprint([])


def test_ddl_constant_covers_all_objects():
    joined = "\n".join(CLUSTER_ANALYSIS_DDL)
    for object_name in (
        "event_cluster_analyses",
        "cluster_analysis_runs",
        "analysis_meta",
        "idx_eca_coord",
        "idx_eca_task_time",
        "idx_car_task",
    ):
        assert object_name in joined
