"""Durable task content store — persistence invariants (content hydration).

Covers the frozen invariants of the evidence content hydration contract:
restart/content-equality (§32/§33), integrity fail-closed (§13/§37),
cross-task isolation (§35), same-content distinct identity (§36), path
normalization (§34), explicit binary/unsupported status (§38), bounded
large-content handling (§39), legacy honesty (§24), provenance binding
(§11/§14), locator idempotence (§54) and the task-deletion race guard (§31).
"""

import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from httpserver.services.evidence.content_store import (
    CONTENT_INTEGRITY_MISMATCH,
    CONTENT_NOT_PERSISTED_LEGACY,
    CONTENT_READ_FAILED,
    CONTENT_SOURCE_MISSING,
    CONTENT_UNSUPPORTED_TYPE,
    ContentUnavailableError,
    LocatedContent,
    TaskContentStore,
    decode_bounded_text,
)
from httpserver.services.investigation_evidence import (
    ResolvedEvidence,
    normalize_forensic_path,
)


FILES_SCHEMA = """
CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT, name TEXT, size INTEGER, category TEXT, type TEXT,
    mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT
)
"""


def _make_task(tmp_path: Path, task_id: str, rows: list[dict]) -> Path:
    """task dir with files.db rows: {path, content(bytes)}."""
    task_dir = tmp_path / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(task_dir / "files.db")
    conn.execute(FILES_SCHEMA)
    for row in rows:
        data = row["content"]
        conn.execute(
            "INSERT INTO files (path, name, size, is_deleted, md5) VALUES (?,?,?,?,0)",
            (
                row["path"],
                row["path"].rsplit("/", 1)[-1],
                len(data),
                hashlib.md5(data).hexdigest(),
            ),
        )
    conn.commit()
    conn.close()
    return task_dir


def _resolved(task_dir: Path, task_id: str, row: dict, content_path=None) -> ResolvedEvidence:
    return ResolvedEvidence(
        task_id=task_id,
        evidence_key=f"file:{normalize_forensic_path(row['path'])}",
        evidence_type="file",
        metadata={"path": row["path"], "md5": hashlib.md5(row["content"]).hexdigest(),
                  "size": len(row["content"])},
        source_files_db=str(task_dir / "files.db"),
        content_path=content_path,
    )


def _backend(materialize=None):
    backend = AsyncMock()
    if materialize is not None:
        backend.materialize_file = AsyncMock(side_effect=materialize)
    return backend


def _read_locator(files_db: Path, path: str):
    conn = sqlite3.connect(files_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT content_sha256, content_size, content_stored_at FROM files WHERE path = ?",
        (path,),
    ).fetchone()
    conn.close()
    return row


# ---------- §32/§33: content survives cleanup + restart, bytes exact ----------

async def test_content_survives_leftover_cleanup_and_restart(tmp_path):
    data = "贷款台账 account=8874, amount=30000\n".encode("utf-8")
    task_dir = _make_task(tmp_path, "t-restart", [{"path": "/data/ledger.txt", "content": data}])
    leftover = task_dir / "extracted_files" / "data" / "ledger.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(data)

    store = TaskContentStore(_backend())
    resolved = _resolved(task_dir, "t-restart", {"path": "/data/ledger.txt", "content": data},
                         content_path=str(leftover))
    first = await store.locate_for_resolved(resolved)
    assert first.persisted and first.provenance == "adopted"
    text, _ = decode_bounded_text(first.path, 8000)
    assert text == data.decode("utf-8")

    # parser cleanup removes the transient artifact; "restart" = new store
    # instance (no in-memory state) reading only task-owned durable state
    import shutil
    shutil.rmtree(task_dir / "extracted_files")
    store2 = TaskContentStore(_backend())
    second = await store2.locate_for_resolved(resolved)
    assert second.persisted and second.provenance == "locator"
    assert Path(second.path).read_bytes() == data
    assert hashlib.sha256(data).hexdigest() == second.sha256


async def test_reacquisition_from_image_via_backend(tmp_path):
    data = "违规入金记录转账凭证".encode("utf-8")
    task_dir = _make_task(tmp_path, "t-reacq", [{"path": "/evidence.csv", "content": data}])
    resolved = _resolved(task_dir, "t-reacq", {"path": "/evidence.csv", "content": data})

    materialized = task_dir / "extracted_files" / "evidence.csv"

    def materialize(task_id, path):
        materialized.parent.mkdir(parents=True, exist_ok=True)
        materialized.write_bytes(data)
        return {"success": True, "materialized_path": str(materialized), "bytes": len(data)}

    store = TaskContentStore(_backend(materialize))
    located = await store.locate_for_resolved(resolved)
    assert located.persisted and located.provenance == "reacquired"
    assert Path(located.path).read_bytes() == data
    locator = _read_locator(task_dir / "files.db", "/evidence.csv")
    assert locator["content_sha256"] == hashlib.sha256(data).hexdigest()
    assert locator["content_size"] == len(data)
    # second read goes through the locator with no new backend call
    store.backend_calls = store._cpp_backend.materialize_file.call_count
    again = await store.locate_for_resolved(resolved)
    assert again.provenance == "locator"
    assert store._cpp_backend.materialize_file.call_count == store.backend_calls


async def test_reacquisition_failure_is_legacy_honest(tmp_path):
    task_dir = _make_task(tmp_path, "t-legacy", [{"path": "/gone.txt", "content": b"x"}])
    resolved = _resolved(task_dir, "t-legacy", {"path": "/gone.txt", "content": b"x"})
    store = TaskContentStore(_backend(lambda tid, p: {"success": False, "status": 404}))
    with pytest.raises(ContentUnavailableError) as excinfo:
        await store.locate_for_resolved(resolved)
    assert excinfo.value.reason == CONTENT_NOT_PERSISTED_LEGACY


async def test_no_backend_means_not_persisted_legacy(tmp_path):
    task_dir = _make_task(tmp_path, "t-nobackend", [{"path": "/a.txt", "content": b"x"}])
    resolved = _resolved(task_dir, "t-nobackend", {"path": "/a.txt", "content": b"x"})
    store = TaskContentStore(None)
    with pytest.raises(ContentUnavailableError) as excinfo:
        await store.locate_for_resolved(resolved)
    assert excinfo.value.reason == CONTENT_NOT_PERSISTED_LEGACY


# ---------- §13/§37: integrity fail-closed ----------

async def test_tampered_blob_fails_closed(tmp_path):
    data = b"tamper-check content\n"
    task_dir = _make_task(tmp_path, "t-tamper", [{"path": "/a.txt", "content": data}])
    leftover = task_dir / "extracted_files" / "a.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(data)
    store = TaskContentStore(_backend())
    located = await store.locate_for_resolved(
        _resolved(task_dir, "t-tamper", {"path": "/a.txt", "content": data}, str(leftover))
    )
    Path(located.path).write_bytes(b"tampered!\n")
    with pytest.raises(ContentUnavailableError) as excinfo:
        await store.locate_for_resolved(
            _resolved(task_dir, "t-tamper", {"path": "/a.txt", "content": data})
        )
    assert excinfo.value.reason == CONTENT_INTEGRITY_MISMATCH


async def test_hash_mismatched_artifact_is_never_adopted(tmp_path):
    data = b"truth\n"
    task_dir = _make_task(tmp_path, "t-mismatch", [{"path": "/a.txt", "content": data}])
    leftover = task_dir / "extracted_files" / "a.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"different bytes\n")
    store = TaskContentStore(_backend())
    with pytest.raises(ContentUnavailableError) as excinfo:
        await store.locate_for_resolved(
            _resolved(task_dir, "t-mismatch", {"path": "/a.txt", "content": data}, str(leftover))
        )
    assert excinfo.value.reason == CONTENT_INTEGRITY_MISMATCH
    assert not (task_dir / "content").exists()


async def test_row_without_parser_hash_prefers_reacquisition(tmp_path):
    data = b"unhashed row\n"
    task_dir = tmp_path / "t-nohash"
    task_dir.mkdir()
    conn = sqlite3.connect(task_dir / "files.db")
    conn.execute(FILES_SCHEMA)
    conn.execute(
        "INSERT INTO files (path, name, size, is_deleted, md5) VALUES ('/a.txt','a.txt',13,0,NULL)"
    )
    conn.commit()
    conn.close()
    leftover = task_dir / "extracted_files" / "a.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"possibly stale artifact\n")  # cannot be verified
    materialized = task_dir / "extracted_files" / "a.txt"

    def materialize(task_id, path):
        # image-derived bytes overwrite the artifact (same extractor)
        materialized.write_bytes(data)
        return {"success": True, "materialized_path": str(materialized), "bytes": len(data)}

    store = TaskContentStore(_backend(materialize))
    resolved = ResolvedEvidence(
        task_id="t-nohash", evidence_key="file:/a.txt", evidence_type="file",
        metadata={"path": "/a.txt", "md5": None, "size": 13},
        source_files_db=str(task_dir / "files.db"),
        content_path=str(leftover),
    )
    located = await store.locate_for_resolved(resolved)
    assert located.persisted and located.provenance == "reacquired"
    assert Path(located.path).read_bytes() == data
    store._cpp_backend.materialize_file.assert_awaited_once()


async def test_row_without_hash_and_without_image_adopts_legacy_artifact(tmp_path):
    data = b"legacy artifact bytes\n"
    task_dir = tmp_path / "t-nohash-legacy"
    task_dir.mkdir()
    conn = sqlite3.connect(task_dir / "files.db")
    conn.execute(FILES_SCHEMA)
    conn.execute(
        "INSERT INTO files (path, name, size, is_deleted, md5) VALUES ('/a.txt','a.txt',22,0,NULL)"
    )
    conn.commit()
    conn.close()
    leftover = task_dir / "extracted_files" / "a.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(data)
    store = TaskContentStore(_backend(lambda tid, p: {"success": False, "status": 404}))
    resolved = ResolvedEvidence(
        task_id="t-nohash-legacy", evidence_key="file:/a.txt", evidence_type="file",
        metadata={"path": "/a.txt", "md5": None, "size": 22},
        source_files_db=str(task_dir / "files.db"),
        content_path=str(leftover),
    )
    located = await store.locate_for_resolved(resolved)
    assert located.persisted and located.provenance == "adopted-legacy"
    assert Path(located.path).read_bytes() == data


# ---------- §35: cross-task isolation ----------

async def test_cross_task_same_path_different_content(tmp_path):
    data_a = b"task A secret\n"
    data_b = b"task B other\n"
    dir_a = _make_task(tmp_path, "11111111", [{"path": "/same/path.txt", "content": data_a}])
    dir_b = _make_task(tmp_path, "22222222", [{"path": "/same/path.txt", "content": data_b}])
    for task_dir, data, tid in ((dir_a, data_a, "11111111"), (dir_b, data_b, "22222222")):
        leftover = task_dir / "extracted_files" / "same" / "path.txt"
        leftover.parent.mkdir(parents=True)
        leftover.write_bytes(data)
    store = TaskContentStore(_backend())
    row = {"path": "/same/path.txt"}
    got_a = await store.locate_for_resolved(
        _resolved(dir_a, "11111111", {**row, "content": data_a},
                  content_path=str(dir_a / "extracted_files" / "same" / "path.txt"))
    )
    got_b = await store.locate_for_resolved(
        _resolved(dir_b, "22222222", {**row, "content": data_b},
                  content_path=str(dir_b / "extracted_files" / "same" / "path.txt"))
    )
    assert Path(got_a.path).read_bytes() == data_a
    assert Path(got_b.path).read_bytes() == data_b
    assert got_a.path != got_b.path  # blobs never cross the task boundary


# ---------- §36: same bytes, distinct evidence identities ----------

async def test_same_content_two_rows_dedup_blob_keep_identity(tmp_path):
    data = b"shared bytes\n"
    task_dir = _make_task(
        tmp_path, "t-dedup",
        [{"path": "/one.txt", "content": data}, {"path": "/two.txt", "content": data}],
    )
    for name in ("one.txt", "two.txt"):
        leftover = task_dir / "extracted_files" / name
        leftover.parent.mkdir(parents=True, exist_ok=True)
        leftover.write_bytes(data)
    store = TaskContentStore(_backend())
    one = await store.locate_for_resolved(
        _resolved(task_dir, "t-dedup", {"path": "/one.txt", "content": data},
                  content_path=str(task_dir / "extracted_files" / "one.txt"))
    )
    two = await store.locate_for_resolved(
        _resolved(task_dir, "t-dedup", {"path": "/two.txt", "content": data},
                  content_path=str(task_dir / "extracted_files" / "two.txt"))
    )
    assert one.path == two.path  # same bytes -> same blob within the task
    loc1 = _read_locator(task_dir / "files.db", "/one.txt")
    loc2 = _read_locator(task_dir / "files.db", "/two.txt")
    assert loc1["content_sha256"] == loc2["content_sha256"]


# ---------- §31: task deletion race ----------

async def test_deletion_race_never_recreates_store(tmp_path):
    data = b"race\n"
    task_dir = _make_task(tmp_path, "t-race", [{"path": "/a.txt", "content": data}])
    resolved = _resolved(task_dir, "t-race", {"path": "/a.txt", "content": data})
    leftover = task_dir / "extracted_files" / "a.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(data)
    files_db = task_dir / "files.db"

    original = TaskContentStore._write_blob_atomic

    def racing_write(blob, artifact_path):
        files_db.unlink()  # task deleted mid-persistence
        original(blob, artifact_path)

    store = TaskContentStore(_backend())
    store._write_blob_atomic = staticmethod(racing_write)
    with pytest.raises(ContentUnavailableError) as excinfo:
        await store.locate_for_resolved(
            _resolved(task_dir, "t-race", {"path": "/a.txt", "content": data},
                      content_path=str(task_dir / "extracted_files" / "a.txt"))
        )
    assert excinfo.value.reason == CONTENT_SOURCE_MISSING
    assert not (task_dir / "content").exists()


# ---------- §34: path normalization ----------

async def test_windows_style_row_path_resolves(tmp_path):
    data = b"win path content\n"
    task_dir = _make_task(tmp_path, "t-winpath", [{"path": "/Users/test/notes.txt", "content": data}])
    # row stored with Windows separators and doubled slashes
    conn = sqlite3.connect(task_dir / "files.db")
    conn.execute("UPDATE files SET path = ? WHERE path = ?", ("\\Users\\test\\notes.txt", "/Users/test/notes.txt"))
    conn.commit()
    conn.close()
    leftover = task_dir / "extracted_files" / "notes.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(data)
    store = TaskContentStore(_backend())
    resolved = ResolvedEvidence(
        task_id="t-winpath",
        evidence_key="file:" + normalize_forensic_path("\\Users\\test\\notes.txt"),
        evidence_type="file",
        metadata={"path": "\\Users\\test\\notes.txt",
                  "md5": hashlib.md5(data).hexdigest(), "size": len(data)},
        source_files_db=str(task_dir / "files.db"),
        content_path=str(leftover),
    )
    located = await store.locate_for_resolved(resolved)
    assert Path(located.path).read_bytes() == data


# ---------- §38: binary content explicit ----------

async def test_binary_payload_persisted_raw_but_not_force_decoded(tmp_path):
    data = b"PK\x03\x04\x00\x00binary\x00\x01"
    task_dir = _make_task(tmp_path, "t-binary", [{"path": "/blob.bin", "content": data}])
    leftover = task_dir / "extracted_files" / "blob.bin"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(data)
    store = TaskContentStore(_backend())
    # raw bytes persist (§10); the text layer refuses to decode them (§20)
    located = await store.locate_for_resolved(
        _resolved(task_dir, "t-binary", {"path": "/blob.bin", "content": data}, str(leftover))
    )
    assert located.persisted and Path(located.path).read_bytes() == data
    with pytest.raises(ContentUnavailableError) as excinfo:
        decode_bounded_text(located.path, 8000)
    assert excinfo.value.reason == CONTENT_UNSUPPORTED_TYPE


async def test_decode_chain_utf8_gb18030_replacement(tmp_path):
    import os

    utf8 = tmp_path / "utf8.txt"
    utf8.write_bytes("台账账目".encode("utf-8"))
    text, enc = decode_bounded_text(str(utf8), 8000)
    assert (text, enc) == ("台账账目", "utf-8")

    gb = tmp_path / "gb.txt"
    gb.write_bytes("台账账目".encode("gb18030"))
    text, enc = decode_bounded_text(str(gb), 8000)
    assert text == "台账账目" and enc == "gb18030"

    binary = tmp_path / "b.bin"
    binary.write_bytes(b"abc\x00def")
    with pytest.raises(ContentUnavailableError) as excinfo:
        decode_bounded_text(str(binary), 8000)
    assert excinfo.value.reason == CONTENT_UNSUPPORTED_TYPE

    broken = tmp_path / "broken.txt"
    broken.write_bytes(b"\xff\xfe\xfa broken")
    text, enc = decode_bounded_text(str(broken), 8000)
    assert enc == "utf-8+replace" and isinstance(text, str)


# ---------- §39: large content bounded, not retained ----------

async def test_oversized_content_served_but_not_persisted(tmp_path, monkeypatch):
    from httpserver.services.evidence import content_store as cs

    monkeypatch.setenv("EVIDENCE_CONTENT_PERSISTENCE_LIMIT_BYTES", "16")
    data = b"A" * 64
    task_dir = _make_task(tmp_path, "t-big", [{"path": "/big.txt", "content": data}])
    leftover = task_dir / "extracted_files" / "big.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(data)
    resolved = _resolved(task_dir, "t-big", {"path": "/big.txt", "content": data},
                         content_path=str(leftover))
    store = TaskContentStore(_backend())
    located = await store.locate_for_resolved(resolved)
    assert located.persisted is False
    assert located.size == len(data)
    assert Path(located.path).read_bytes() == data
    assert not (task_dir / "content" / "blobs").exists()
    conn = sqlite3.connect(task_dir / "files.db")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(files)")}
    stored = None
    if "content_sha256" in cols:
        stored = conn.execute(
            "SELECT content_sha256 FROM files WHERE path = '/big.txt'"
        ).fetchone()[0]
    conn.close()
    assert stored is None  # nothing retained above the persistence cap
    monkeypatch.delenv("EVIDENCE_CONTENT_PERSISTENCE_LIMIT_BYTES")


# ---------- §54: locator columns idempotent ----------

async def test_locator_columns_idempotent(tmp_path):
    data = b"idem\n"
    task_dir = _make_task(tmp_path, "t-idem", [{"path": "/a.txt", "content": data}])
    leftover = task_dir / "extracted_files" / "a.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(data)
    store = TaskContentStore(_backend())
    for _ in range(2):
        await store.locate_for_resolved(
            _resolved(task_dir, "t-idem", {"path": "/a.txt", "content": data}, str(leftover))
        )
    conn = sqlite3.connect(task_dir / "files.db")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(files)")}
    conn.close()
    assert {"content_sha256", "content_size", "content_stored_at"} <= cols


async def test_stale_locator_rederives(tmp_path):
    data = b"stale\n"
    task_dir = _make_task(tmp_path, "t-stale", [{"path": "/a.txt", "content": data}])
    leftover = task_dir / "extracted_files" / "a.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(data)
    store = TaskContentStore(_backend())
    first = await store.locate_for_resolved(
        _resolved(task_dir, "t-stale", {"path": "/a.txt", "content": data}, str(leftover))
    )
    Path(first.path).unlink()  # blob lost; locator remains
    again = await store.locate_for_resolved(
        _resolved(task_dir, "t-stale", {"path": "/a.txt", "content": data},
                  content_path=str(leftover))
    )
    assert again.persisted and Path(again.path).read_bytes() == data


# ---------- §14: identity untouched ----------

async def test_identity_fields_untouched_by_persistence(tmp_path):
    data = b"identity\n"
    task_dir = _make_task(tmp_path, "t-ident", [{"path": "/a.txt", "content": data}])
    before = sqlite3.connect(task_dir / "files.db").execute(
        "SELECT path, md5, size, is_deleted FROM files"
    ).fetchall()
    leftover = task_dir / "extracted_files" / "a.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(data)
    store = TaskContentStore(_backend())
    await store.locate_for_resolved(
        _resolved(task_dir, "t-ident", {"path": "/a.txt", "content": data}, str(leftover))
    )
    after = sqlite3.connect(task_dir / "files.db").execute(
        "SELECT path, md5, size, is_deleted FROM files"
    ).fetchall()
    assert before == after


# ---------- model helpers ----------

def test_resolved_evidence_from_dict_roundtrip_and_extra_keys():
    base = ResolvedEvidence(
        task_id="t", evidence_key="file:/a", evidence_type="file",
        metadata={"path": "/a"}, source_files_db="/x/files.db",
    ).to_dict()
    base["size"] = 123  # legacy extra key from resolve_evidence
    ref = ResolvedEvidence.from_dict(base)
    assert ref.source_files_db == "/x/files.db"
    assert ref.metadata == {"path": "/a"}


async def test_concurrent_first_hydration_locator_race(tmp_path):
    """Two simultaneous first hydrations must not lose locators to the
    ALTER TABLE race (found by the runtime-v3 qualification canary)."""
    import asyncio as _aio

    data = b"race-migration\n"
    task_dir = _make_task(tmp_path, "t-race2", [{"path": "/a.txt", "content": data}])
    leftover = task_dir / "extracted_files" / "a.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(data)

    store = TaskContentStore(_backend())

    async def hydrate():
        return await store.locate_for_resolved(
            _resolved(task_dir, "t-race2", {"path": "/a.txt", "content": data},
                      content_path=str(leftover))
        )

    first, second = await _aio.gather(hydrate(), hydrate())
    assert first.persisted and second.persisted
    conn = sqlite3.connect(task_dir / "files.db")
    row = conn.execute(
        "SELECT content_sha256 FROM files WHERE path = '/a.txt'"
    ).fetchone()
    conn.close()
    assert row is not None and row[0] == hashlib.sha256(data).hexdigest()
