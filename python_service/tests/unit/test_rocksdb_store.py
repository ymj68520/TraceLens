"""Tests for the RocksDB storage foundation (mvp-phase1-acceptance §8 R1).

Skipped wholesale when rocksdict is not installed, mirroring the optional
graphiti-core pattern used elsewhere in this suite.
"""

import pytest

from storage.rocksdb_store import (
    META_CF,
    RocksDBStore,
    RocksDBUnavailable,
    available,
    decode_rowid,
    encode_rowid,
)

pytestmark = pytest.mark.skipif(
    not available(), reason="rocksdict is not installed"
)


@pytest.fixture
def store(tmp_path):
    s = RocksDBStore(tmp_path / "test.rocks", column_families=["files", "events"])
    yield s
    s.destroy()


def test_rowid_encoding_is_order_preserving():
    keys = [encode_rowid(n) for n in (0, 1, 9, 255, 256, 65535, 2**32, 2**63)]
    assert keys == sorted(keys)
    assert decode_rowid(encode_rowid(2**40)) == 2**40


def test_put_get_delete_roundtrip(store):
    store.put("files", b"\x01", b'{"a":1}')
    assert store.get("files", b"\x01") == b'{"a":1}'
    store.delete("files", b"\x01")
    assert store.get("files", b"\x01") is None


def test_unknown_column_family_rejected(store):
    with pytest.raises(KeyError, match="unknown column family"):
        store.put("nope", b"k", b"v")


def test_batch_is_atomic_and_supports_deletes(store):
    store.batch([
        ("files", b"\x01", b"a"),
        ("events", b"\x02", b"b"),
    ])
    assert store.get("files", b"\x01") == b"a"
    assert store.get("events", b"\x02") == b"b"
    store.batch([
        ("files", b"\x01", None),          # delete
        ("files", b"\x03", b"c"),
    ])
    assert store.get("files", b"\x01") is None
    assert store.get("files", b"\x03") == b"c"


def test_scan_prefix_is_ordered_and_filtered(store):
    rows = [(b"\x01", b"row1"), (b"\x02", b"row2"), (b"\x03", b"row3")]
    store.batch([("files", b"row:" + k, v) for k, v in rows])
    store.put("files", b"meta:count", b"3")
    store.put("events", b"row:\x01", b"other-cf")

    pairs = list(store.scan_prefix("files", b"row:"))
    assert pairs == [(b"row:" + k, v) for k, v in rows]
    assert store.count_prefix("files", b"row:") == 3
    assert store.count_prefix("files", b"meta:") == 1


def test_meta_bookkeeping(store):
    assert store.get_meta("missing") is None
    store.set_meta("schema_version", "1")
    assert store.get_meta("schema_version") == "1"
    assert META_CF in store.column_families()


def test_reopen_persists(tmp_path):
    s1 = RocksDBStore(tmp_path / "persist.rocks", column_families=["files"])
    s1.put("files", b"\x01", b"payload")
    s1.set_meta("migrated", "yes")
    s1.close()

    s2 = RocksDBStore(tmp_path / "persist.rocks", column_families=["files"])
    try:
        assert s2.get("files", b"\x01") == b"payload"
        assert s2.get_meta("migrated") == "yes"
    finally:
        s2.destroy()


def test_context_manager_closes(tmp_path):
    with RocksDBStore(tmp_path / "ctx.rocks", column_families=[]) as s:
        s.put(META_CF, b"k", b"v")
    # reopening after close must work
    s2 = RocksDBStore(tmp_path / "ctx.rocks", column_families=[])
    try:
        assert s2.get(META_CF, b"k") == b"v"
    finally:
        s2.destroy()


def test_requires_dependency(monkeypatch, tmp_path):
    import storage.rocksdb_store as mod

    monkeypatch.setattr(mod, "_HAS_ROCKSDB", False)
    with pytest.raises(RocksDBUnavailable):
        RocksDBStore(tmp_path / "nope.rocks", column_families=[])
