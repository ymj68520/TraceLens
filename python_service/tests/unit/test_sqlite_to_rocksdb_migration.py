"""Parity tests for the SQLite → RocksDB migration (mvp-phase1-acceptance §8 R1).

A migrated store must carry every row (count parity), a byte-identical
content digest, and enough schema metadata (DDL/columns/keying) to be read
back without the SQLite file — including BLOB round-trips and WITHOUT ROWID
tables.
"""

import json
import sqlite3

import pytest

from storage.rocksdb_store import META_CF, RocksDBStore, available, decode_rowid
from storage.sqlite_migrate import decode_value, migrate, verify

pytestmark = pytest.mark.skipif(
    not available(), reason="rocksdict is not installed"
)


@pytest.fixture
def source_db(tmp_path):
    path = tmp_path / "source.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE files (
            id INTEGER PRIMARY KEY, path TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, crtime INTEGER, atime INTEGER,
            llm_summary TEXT, raw BLOB
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, file_path TEXT
        );
        CREATE TABLE case_keys (
            path TEXT, depth INTEGER, PRIMARY KEY (path)
        ) WITHOUT ROWID;
        INSERT INTO files VALUES
            (1, '/case/a.txt', 10, 100, 100, 100, 100, 'sum-a', X'00FF10'),
            (2, '/case/b.bin', 20, 250, 200, 150, 180, NULL, NULL),
            (3, '/case/c.txt', 30, 90, 300, 120, 140, 'sum-c', X'DEADBEEF');
        INSERT INTO events VALUES (1, 100, 'CREATED', '/case/a.txt'),
                                  (2, 150, 'MODIFIED', '/case/b.bin');
        INSERT INTO case_keys VALUES ('/case/a.txt', 2), ('/case/b.bin', 2);
        """
    )
    conn.commit()
    conn.close()
    return path


def test_migrate_reports_counts_and_verify_passes(source_db, tmp_path):
    rocks = tmp_path / "migrated.rocks"
    counts = migrate(source_db, rocks)
    assert counts == {"case_keys": 2, "events": 2, "files": 3}
    assert verify(source_db, rocks) == {"case_keys": True, "events": True, "files": True}


def test_rows_are_keyed_by_ordered_rowid(source_db, tmp_path):
    rocks = tmp_path / "migrated.rocks"
    migrate(source_db, rocks)
    store = RocksDBStore(rocks)
    try:
        keys = [key for key, _ in store.scan_prefix("files", b"")]
        assert [decode_rowid(k) for k in keys] == [1, 2, 3]
    finally:
        store.close()


def test_blob_roundtrip_and_null_preserved(source_db, tmp_path):
    rocks = tmp_path / "migrated.rocks"
    migrate(source_db, rocks)
    store = RocksDBStore(rocks)
    try:
        rows = {
            decode_rowid(key): dict(decode_value(value))
            for key, value in store.scan_prefix("files", b"")
        }
        assert rows[1]["raw"] == bytes.fromhex("00ff10")
        assert rows[3]["raw"] == bytes.fromhex("deadbeef")
        assert rows[2]["raw"] is None
        assert rows[2]["llm_summary"] is None
        assert rows[1]["llm_summary"] == "sum-a"
    finally:
        store.close()


def test_without_rowid_table_uses_pk_key(source_db, tmp_path):
    rocks = tmp_path / "migrated.rocks"
    migrate(source_db, rocks)
    store = RocksDBStore(rocks)
    try:
        pairs = list(store.scan_prefix("case_keys", b"pk:"))
        assert len(pairs) == 2
        first = dict(decode_value(pairs[0][1]))
        assert first["path"] == "/case/a.txt"
    finally:
        store.close()


def test_meta_carries_schema_for_sqlite_free_reads(source_db, tmp_path):
    rocks = tmp_path / "migrated.rocks"
    migrate(source_db, rocks)
    store = RocksDBStore(rocks)
    try:
        keying = json.loads(store.get(META_CF, b"table:files:keying").decode("utf-8"))
        assert keying == {"rowid_keyed": True, "pk": ["id"], "count": 3}
        ddl = store.get(META_CF, b"table:files:ddl").decode("utf-8")
        assert "CREATE TABLE files" in ddl
        assert store.get_meta("source_sqlite").endswith("source.db")
    finally:
        store.close()


def test_partial_table_subset(source_db, tmp_path):
    rocks = tmp_path / "migrated.rocks"
    counts = migrate(source_db, rocks, tables=["events"])
    assert counts == {"events": 2}
    assert set(verify(source_db, rocks)) == {"events"}


def test_cli_end_to_end(source_db, tmp_path, capsys):
    import sys

    from storage.sqlite_migrate import main

    rocks = tmp_path / "cli.rocks"
    rc = main([str(source_db), "--out", str(rocks), "--verify"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "files: 3 rows" in out
    assert "verify files: OK" in out
    _ = sys  # keep import local-use explicit
