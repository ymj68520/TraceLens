import asyncio
import sqlite3

import pytest

from httpserver.services.investigation_evidence import (
    EvidenceResolver,
    compute_analysis_input_hash,
    expand_timeline_group_rows,
    make_cluster_key,
    make_file_evidence_key,
    parse_cluster_key,
    read_timeline_group_members,
    validate_timeline_group_descriptor,
)


def _make_task_dbs(tmp_path):
    files_db = tmp_path / "files.db"
    events_db = tmp_path / "events.db"
    with sqlite3.connect(files_db) as conn:
        conn.execute("CREATE TABLE files (path TEXT, name TEXT, size INTEGER, mtime INTEGER, ctime INTEGER, md5 TEXT, llm_summary TEXT, llm_description TEXT, llm_analyzed_at INTEGER)")
        conn.execute("INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ("/evidence/a.txt", "a.txt", 12, 100, 99, "hash-a", "initial a", "description a", 101))
        conn.commit()
    with sqlite3.connect(events_db) as conn:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, file_path TEXT, inode INTEGER, description TEXT, llm_summary TEXT, llm_description TEXT)")
        conn.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            (1, 120, "MODIFIED", "/evidence/a.txt", 1, "changed", "cluster summary", "cluster description"),
            (2, 121, "MODIFIED", "/evidence/a.txt", 1, "changed again", "cluster summary", "cluster description"),
            (3, 180, "CREATED", "/evidence/a.txt", 1, "other", None, None),
        ])
        conn.commit()
    return files_db, events_db


@pytest.mark.asyncio
async def test_cluster_resolver_is_bounded_and_task_scoped(tmp_path):
    files_db, events_db = _make_task_dbs(tmp_path)

    async def load(_task_id):
        return {"output_files_db": str(files_db), "output_events_db": str(events_db)}

    resolver = EvidenceResolver(load)
    key = make_cluster_key(2, "MODIFIED")
    resolved = await resolver.resolve("task-a", key)
    assert resolved is not None
    assert resolved.evidence_type == "event_cluster"
    assert resolved.metadata["event_count"] == 2
    assert resolved.metadata["sampled_event_count"] == 2
    assert resolved.related_evidence_keys == [make_file_evidence_key("/evidence/a.txt")]
    assert key in resolved.evidence_key

    async def other_task(_task_id):
        return {"output_files_db": str(tmp_path / "missing-files.db"), "output_events_db": str(tmp_path / "missing-events.db")}

    assert await EvidenceResolver(other_task).resolve("task-b", key) is None


def test_cluster_key_roundtrip_and_invalid_key():
    key = make_cluster_key(123, "TYPE:with/slash")
    assert parse_cluster_key(key) == (123, "TYPE:with/slash")
    with pytest.raises(ValueError):
        parse_cluster_key("cluster:v1:not-a-minute:TYPE")


@pytest.mark.asyncio
async def test_file_resolver_allows_same_key_across_tasks_with_distinct_sources(tmp_path):
    task_a = tmp_path / "task-a"
    task_b = tmp_path / "task-b"
    task_a.mkdir()
    task_b.mkdir()
    files_a, events_a = _make_task_dbs(task_a)
    files_b, events_b = _make_task_dbs(task_b)
    with sqlite3.connect(files_b) as conn:
        conn.execute("UPDATE files SET md5 = 'hash-b' WHERE path = '/evidence/a.txt'")
        conn.commit()
    extract_a = tmp_path / "extract-a" / "evidence"
    extract_b = tmp_path / "extract-b" / "evidence"
    extract_a.mkdir(parents=True)
    extract_b.mkdir(parents=True)
    (extract_a / "a.txt").write_text("content-a", encoding="utf-8")
    (extract_b / "a.txt").write_text("content-b", encoding="utf-8")
    task_map = {
        "task-a": {"output_files_db": str(files_a), "output_events_db": str(events_a), "extraction_directory": str(extract_a.parent)},
        "task-b": {"output_files_db": str(files_b), "output_events_db": str(events_b), "extraction_directory": str(extract_b.parent)},
    }

    async def load(task_id):
        return task_map[task_id]

    resolver = EvidenceResolver(load)
    key = make_file_evidence_key("/evidence/a.txt")
    resolved_a = await resolver.resolve("task-a", key)
    resolved_b = await resolver.resolve("task-b", key)
    assert resolved_a is not None and resolved_b is not None
    assert resolved_a.task_id == "task-a"
    assert resolved_b.task_id == "task-b"
    assert resolved_a.evidence_key == resolved_b.evidence_key == key
    assert resolved_a.source_hash == "hash-a"
    assert resolved_b.source_hash == "hash-b"
    assert resolved_a.source_hash != resolved_b.source_hash
    assert await resolver.bounded_content(resolved_a) == "content-a"
    assert await resolver.bounded_content(resolved_b) == "content-b"
    assert resolved_a.content_path != resolved_b.content_path


@pytest.mark.asyncio
async def test_full_cluster_digest_changes_beyond_sample_boundary(tmp_path):
    files_db, events_db = _make_task_dbs(tmp_path)
    with sqlite3.connect(events_db) as conn:
        conn.executemany(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(index, 120 + index, "MODIFIED", "/evidence/a.txt", index, f"event {index}", None, None) for index in range(4, 56)],
        )
        conn.commit()

    async def load(_task_id):
        return {"output_files_db": str(files_db), "output_events_db": str(events_db)}

    resolver = EvidenceResolver(load)
    key = make_cluster_key(2, "MODIFIED")
    before = await resolver.resolve("task-a", key)
    assert before.metadata["truncated"] is True
    assert before.metadata["snapshot_digest_kind"] == "full_cluster_events"
    assert before.metadata["cluster_digest_algorithm"] == "cluster-members-immutable-v1"
    with sqlite3.connect(events_db) as conn:
        conn.execute("UPDATE events SET description = 'changed beyond sample' WHERE id = 55")
        conn.commit()
    after = await resolver.resolve("task-a", key)
    assert after.source_hash != before.source_hash
    assert after.metadata["sampled_event_count"] == 50


def test_timeline_descriptor_expands_trusted_rows_deterministically_and_rejects_negative():
    descriptor = {
        "bucket_index": 10,
        "bucket_seconds": 300,
        "event_type": "MODIFIED",
        "parent_directory": "/evidence/",
        "bucket_start_timestamp": 3000,
    }
    rows = [
        {"id": 3, "timestamp": 659, "event_type": "MODIFIED"},
        {"id": 2, "timestamp": 121, "event_type": "MODIFIED"},
        {"id": 1, "timestamp": 120, "event_type": "MODIFIED"},
        {"id": 4, "timestamp": 659, "event_type": "MODIFIED"},
    ]
    assert validate_timeline_group_descriptor(descriptor) == descriptor
    assert expand_timeline_group_rows(descriptor, rows) == [
        make_cluster_key(2, "MODIFIED"),
        make_cluster_key(10, "MODIFIED"),
    ]
    with pytest.raises(ValueError, match="negative"):
        expand_timeline_group_rows(descriptor, [{"timestamp": -1, "event_type": "MODIFIED"}])
    with pytest.raises(ValueError, match="bucket_start"):
        validate_timeline_group_descriptor({**descriptor, "bucket_start_timestamp": 1})


@pytest.mark.asyncio
async def test_cluster_resolver_uses_half_open_nonnegative_bounds_and_legacy_negative(tmp_path):
    files_db = tmp_path / "files.db"
    events_db = tmp_path / "events.db"
    with sqlite3.connect(files_db) as conn:
        conn.execute("CREATE TABLE files (path TEXT)")
        conn.commit()
    with sqlite3.connect(events_db) as conn:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, file_path TEXT, description TEXT)")
        conn.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?)", [
            (1, -61, "MODIFIED", "/evidence/a.txt", "neg-a"),
            (2, -1, "MODIFIED", "/evidence/a.txt", "neg-b"),
            (3, 0, "MODIFIED", "/evidence/a.txt", "zero"),
            (4, 59, "MODIFIED", "/evidence/a.txt", "upper"),
            (5, 60, "MODIFIED", "/evidence/a.txt", "next"),
        ])
        conn.commit()

    async def load(_task_id):
        return {"output_files_db": str(files_db), "output_events_db": str(events_db)}

    resolver = EvidenceResolver(load)
    nonnegative = await resolver.resolve("task-a", make_cluster_key(0, "MODIFIED"))
    assert [row["id"] for row in nonnegative.metadata["events"]] == [3, 4]
    legacy_negative = await resolver.resolve("task-a", make_cluster_key(-1, "MODIFIED"))
    assert legacy_negative.metadata["event_count"] == 1
    assert legacy_negative.metadata["events"][0]["id"] == 1


@pytest.mark.asyncio
async def test_cluster_digest_ignores_mutable_llm_annotations(tmp_path):
    files_db, events_db = _make_task_dbs(tmp_path)

    async def load(_task_id):
        return {"output_files_db": str(files_db), "output_events_db": str(events_db)}

    resolver = EvidenceResolver(load)
    key = make_cluster_key(2, "MODIFIED")
    before = await resolver.resolve("task-a", key)
    with sqlite3.connect(events_db) as conn:
        conn.execute("UPDATE events SET llm_summary = 'changed', llm_description = 'changed' WHERE id = 1")
        conn.commit()
    after = await resolver.resolve("task-a", key)
    assert after.source_hash == before.source_hash


def test_read_timeline_group_members_uses_exact_backend_scope(tmp_path):
    events_db = tmp_path / "events.db"
    with sqlite3.connect(events_db) as conn:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, file_path TEXT, description TEXT, inode INTEGER)")
        conn.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)", [
            (1, 600, "MODIFIED", "/foo/a.txt", "foo", 1),
            (2, 601, "MODIFIED", "/foobar/b.txt", "foobar", 2),
            (3, 602, "MODIFIED", "/foo/c.txt", "foo-2", 3),
            (4, 603, "CREATED", "/foo/d.txt", "other-type", 4),
        ])
        conn.commit()
    descriptor = {
        "bucket_index": 10,
        "bucket_seconds": 60,
        "event_type": "MODIFIED",
        "parent_directory": "/foo/",
    }
    rows = read_timeline_group_members(str(events_db), descriptor)
    assert [row["id"] for row in rows] == [1, 3]


def test_analysis_input_hash_is_content_canonical():
    base = {
        "evidence_snapshot": {"evidence_type": "file", "source_hash": "abc"},
        "evidence_context": {"title": "a"},
        "analyst_note": "note",
        "case_context": "case",
        "related_evidence": [{"evidence_key": "file:/b"}, {"evidence_key": "file:/a"}],
        "prompt_version": "v1",
    }
    reordered = {"prompt_version": "v1", "related_evidence": list(reversed(base["related_evidence"])), "case_context": "case", "analyst_note": "note", "evidence_context": {"title": "a"}, "evidence_snapshot": {"source_hash": "abc", "evidence_type": "file"}}
    assert compute_analysis_input_hash(base) == compute_analysis_input_hash(reordered)
    changed = dict(base)
    changed["analyst_note"] = "changed"
    assert compute_analysis_input_hash(base) != compute_analysis_input_hash(changed)
    assert "snapshot-id" not in compute_analysis_input_hash(base)
