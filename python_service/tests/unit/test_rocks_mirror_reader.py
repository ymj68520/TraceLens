"""Tests for the Python RocksDB mirror reader (mvp-phase1-acceptance §8 R4).

The fixtures are produced by the Python migration tool itself (same writer
that backs sqlite_migrate.verify), so these tests pin the reader against the
exact byte format the C++ RowCodec goldens lock on the other side.
"""

import sqlite3

import pytest

from storage.rocks_mirror_reader import (
    MirrorNotFound,
    RocksMirrorReader,
    mirrored_path_for,
    open_mirror_or_none,
)
from storage.rocksdb_store import available
from storage.sqlite_migrate import migrate

pytestmark = pytest.mark.skipif(not available(), reason="rocksdict is not installed")


@pytest.fixture
def mirrored_db(tmp_path):
    db = tmp_path / "raw.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE files (
            id INTEGER PRIMARY KEY, path TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, crtime INTEGER, atime INTEGER,
            llm_summary TEXT, is_deleted INTEGER DEFAULT 0);
        INSERT INTO files (path, size, mtime, ctime, crtime, atime, llm_summary) VALUES
            ('/case/small.txt', 10, 100, 100, 100, 100, 's'),
            ('/case/中文.bin', 90000, 250, 200, 150, 180, NULL),
            ('/case/mid.log', 5000, 90, 300, 120, 140, 'm');
        CREATE TABLE case_keys (path TEXT PRIMARY KEY) WITHOUT ROWID;
        INSERT INTO case_keys VALUES ('/case/small.txt');
        """
    )
    conn.commit()
    conn.close()
    migrate(db, mirrored_path_for(db))
    return db


def test_for_db_and_open_helper(mirrored_db):
    reader = RocksMirrorReader.for_db(mirrored_db)
    try:
        assert reader.has_table("files")
        assert not reader.has_table("nope")
        assert reader.table_names() == ["case_keys", "files"]
    finally:
        reader.close()
    assert open_mirror_or_none(mirrored_db) is not None
    assert open_mirror_or_none(mirrored_db.parent / "absent.db") is None


def test_point_lookup_and_scan(mirrored_db):
    reader = RocksMirrorReader.for_db(mirrored_db)
    try:
        row2 = reader.get_by_rowid("files", 2)
        assert row2 is not None
        assert row2["path"] == "/case/中文.bin"
        assert row2["size"] == 90000
        assert row2["llm_summary"] is None
        assert reader.get_by_rowid("files", 999) is None

        rows = list(reader.scan_table("files"))
        assert [rowid for rowid, _ in rows] == [1, 2, 3]
        assert rows[0][1]["path"] == "/case/small.txt"
        assert reader.count_rows("files") == 3
    finally:
        reader.close()


def test_in_memory_where(mirrored_db):
    reader = RocksMirrorReader.for_db(mirrored_db)
    try:
        big = reader.find_rows("files", lambda row: (row.get("size") or 0) > 1000)
        assert [row["path"] for _, row in big] == ["/case/中文.bin", "/case/mid.log"]
    finally:
        reader.close()


def test_missing_store_raises(tmp_path):
    with pytest.raises(MirrorNotFound):
        RocksMirrorReader(tmp_path / "nope.rocks")
    assert open_mirror_or_none(tmp_path / "nope.db") is None
