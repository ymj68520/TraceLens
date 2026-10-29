"""Tests for people-graph material reading on Android logical acquisitions.

Logical phone tasks point ``output_files_db`` at android.db, which has no
``files`` inventory; the discovery materials must come from the interpersonal
artifact tables instead of the file catalogue.
"""

import sqlite3

import pytest

from httpserver.services.people_graph import sources
from httpserver.services.people_graph.sources import (
    artifact_catalog,
    read_artifact_materials,
)


@pytest.fixture
def android_task(tmp_path):
    db_path = tmp_path / "android.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE contacts (id INTEGER PRIMARY KEY, display_name TEXT, phone TEXT);
        CREATE TABLE call_logs (id INTEGER PRIMARY KEY, number TEXT, type INTEGER,
            duration INTEGER, date INTEGER);
        CREATE TABLE sms_messages (id INTEGER PRIMARY KEY, address TEXT, body TEXT);
        CREATE TABLE system_logs (id INTEGER PRIMARY KEY, message TEXT);
        """
    )
    con.execute("INSERT INTO contacts VALUES (1, '张三', '13800138000')")
    con.execute("INSERT INTO contacts VALUES (2, '李四', '13900139000')")
    con.execute("INSERT INTO call_logs VALUES (1, '13800138000', 2, 65, 1395307310)")
    con.execute("INSERT INTO sms_messages VALUES (1, '13800138000', '明天见面聊')")
    con.execute("INSERT INTO system_logs VALUES (1, 'boot')")
    con.commit()
    con.close()
    return {"id": "task-android-1", "output_files_db": str(db_path)}


def test_artifact_catalog_lists_only_nonempty_interpersonal_tables(android_task):
    rows, total, revision = artifact_catalog(android_task, 10)
    names = {r["path"] for r in rows}
    assert names == {"android:contacts", "android:call_logs", "android:sms_messages"}
    assert total == 4          # system_logs deliberately excluded
    assert revision


def test_artifact_catalog_ignores_file_databases(tmp_path):
    plain = tmp_path / "files.db"
    con = sqlite3.connect(plain)
    con.execute("CREATE TABLE files (path TEXT)")
    con.commit()
    con.close()
    with pytest.raises(ValueError):
        artifact_catalog({"id": "t", "output_files_db": str(plain)}, 10)


@pytest.mark.asyncio
async def test_read_artifact_materials_builds_readable_projection(android_task):
    progress_calls = []

    async def progress(phase, value):
        progress_calls.append((phase, value))

    materials, coverage, revision, models = await read_artifact_materials(
        android_task, 10, progress)
    assert progress_calls
    by_path = {m["path"]: m for m in materials}
    contacts = by_path["android:contacts"]
    assert contacts["status"] == "complete"
    assert "张三 13800138000" in contacts["text"]
    assert contacts["source_hash"]
    assert coverage["selected_files"] == 3
    assert "手机工件投影" in coverage["scope"]
    assert models == []
    assert all(m["kind"] != "unavailable" for m in materials)
    # stable evidence keys so mentions can reference the projection
    assert contacts["evidence_key"] == "android:contacts"


@pytest.mark.asyncio
async def test_read_materials_dispatches_to_artifacts(android_task):
    materials, coverage, _revision, _models = await sources.read_materials(
        android_task, 10, None, None)
    assert materials and coverage["scope"].startswith("手机工件投影")
