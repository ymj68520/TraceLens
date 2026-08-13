"""Tests for EvidenceResolver (C2 + C2.1): task-scoped, fail-closed, zero-write.

Covers R1-R8 plus the C2.1 error taxonomy: not-found (EvidenceNotFoundError,
also a LookupError) vs store failure (EvidenceStoreError, NOT a LookupError).
"""

import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from httpserver.services.evidence import (
    EvidenceNotFoundError,
    EvidenceResolver,
    EvidenceStoreError,
    ResolvedEvidence,
)


# ---------- fixtures ----------

def _make_files_db(db_path, paths):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE files (path TEXT)")
    for p in paths:
        conn.execute("INSERT INTO files (path) VALUES (?)", (p,))
    conn.commit()
    conn.close()


def _make_events_db(db_path, events):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE events (timestamp INTEGER, event_type TEXT, file_path TEXT)")
    for e in events:
        conn.execute(
            "INSERT INTO events (timestamp, event_type, file_path) VALUES (?, ?, ?)",
            (e["timestamp"], e["event_type"], e.get("file_path", "")),
        )
    conn.commit()
    conn.close()


def _backend(task_map):
    backend = AsyncMock()
    backend.get_task = AsyncMock(side_effect=lambda tid: task_map.get(tid))
    return backend


def _file_hash(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---------- error taxonomy (C2.1) ----------

def test_C21_taxonomy_notfound_is_lookuperror_store_is_not():
    assert issubclass(EvidenceNotFoundError, LookupError)
    assert not issubclass(EvidenceStoreError, LookupError)


# ---------- file resolution ----------

@pytest.mark.asyncio
async def test_resolve_file_hit(tmp_path):
    fdb, edb = str(tmp_path / "files.db"), str(tmp_path / "events.db")
    _make_files_db(fdb, ["/case/report.docx"])
    _make_events_db(edb, [])
    r = EvidenceResolver(_backend({"A": {"output_files_db": fdb, "output_events_db": edb}}))

    res = await r.resolve_evidence("A", "file:/case/report.docx")

    assert res.evidence_type == "file"
    assert res.normalized_path == "/case/report.docx"
    assert res.evidence_key == "file:/case/report.docx"  # canonical
    assert res.source_db == fdb


@pytest.mark.asyncio
async def test_resolve_file_miss_raises_not_found(tmp_path):
    fdb, edb = str(tmp_path / "files.db"), str(tmp_path / "events.db")
    _make_files_db(fdb, ["/other/file.txt"])
    _make_events_db(edb, [])
    r = EvidenceResolver(_backend({"A": {"output_files_db": fdb, "output_events_db": edb}}))

    with pytest.raises(EvidenceNotFoundError):
        await r.resolve_evidence("A", "file:/case/report.docx")


@pytest.mark.asyncio
async def test_resolve_canonical_key_for_backslash_input(tmp_path):
    fdb, edb = str(tmp_path / "files.db"), str(tmp_path / "events.db")
    _make_files_db(fdb, ["/case/report.docx"])
    _make_events_db(edb, [])
    r = EvidenceResolver(_backend({"A": {"output_files_db": fdb, "output_events_db": edb}}))

    res = await r.resolve_evidence("A", r"file:\case\report.docx")
    assert res.evidence_key == "file:/case/report.docx"
    assert res.normalized_path == "/case/report.docx"


# ---------- cluster resolution ----------

@pytest.mark.asyncio
async def test_resolve_cluster_hit_recomputed(tmp_path):
    fdb, edb = str(tmp_path / "files.db"), str(tmp_path / "events.db")
    _make_files_db(fdb, [])
    _make_events_db(edb, [
        {"timestamp": 6000, "event_type": "CREATED"},
        {"timestamp": 6010, "event_type": "CREATED"},
        {"timestamp": 6030, "event_type": "CREATED"},
    ])
    r = EvidenceResolver(_backend({"A": {"output_files_db": fdb, "output_events_db": edb}}))

    res = await r.resolve_evidence("A", "cluster:v1:100:CREATED")

    assert res.evidence_type == "cluster"
    assert (res.unix_minute, res.event_type, res.version) == (100, "CREATED", "v1")
    assert res.cluster_start == 6000
    assert res.cluster_end == 6030
    assert res.event_count == 3
    assert res.representative_timestamp == 6000
    assert res.source_db == edb


@pytest.mark.asyncio
async def test_resolve_cluster_miss_raises_not_found(tmp_path):
    fdb, edb = str(tmp_path / "files.db"), str(tmp_path / "events.db")
    _make_files_db(fdb, [])
    _make_events_db(edb, [{"timestamp": 6000, "event_type": "MODIFIED"}])
    r = EvidenceResolver(_backend({"A": {"output_files_db": fdb, "output_events_db": edb}}))

    with pytest.raises(EvidenceNotFoundError):  # not fabricated
        await r.resolve_evidence("A", "cluster:v1:100:CREATED")


# ---------- task boundary / fail-closed ----------

@pytest.mark.asyncio
async def test_R1_task_not_found_raises_not_found():
    r = EvidenceResolver(_backend({}))
    with pytest.raises(EvidenceNotFoundError):
        await r.resolve_evidence("nope", "file:/x")


@pytest.mark.asyncio
async def test_malformed_key_raises_value_error(tmp_path):
    fdb, edb = str(tmp_path / "files.db"), str(tmp_path / "events.db")
    _make_files_db(fdb, [])
    _make_events_db(edb, [])
    r = EvidenceResolver(_backend({"A": {"output_files_db": fdb, "output_events_db": edb}}))

    with pytest.raises(ValueError):
        await r.resolve_evidence("A", "unknown:x")


@pytest.mark.asyncio
async def test_R6_cross_task_isolation(tmp_path):
    fa, fb = str(tmp_path / "a_files.db"), str(tmp_path / "b_files.db")
    ea, eb = str(tmp_path / "a_events.db"), str(tmp_path / "b_events.db")
    _make_files_db(fa, ["/case/report.docx"])
    _make_files_db(fb, ["/other/file.txt"])  # task B does NOT have the path
    _make_events_db(ea, [])
    _make_events_db(eb, [])
    backend = _backend({
        "A": {"output_files_db": fa, "output_events_db": ea},
        "B": {"output_files_db": fb, "output_events_db": eb},
    })
    r = EvidenceResolver(backend)

    res_a = await r.resolve_evidence("A", "file:/case/report.docx")
    assert res_a.source_db == fa  # resolved from A's DB only

    with pytest.raises(EvidenceNotFoundError):  # B must not see A's evidence
        await r.resolve_evidence("B", "file:/case/report.docx")


@pytest.mark.asyncio
async def test_db_missing_raises_store_error_and_no_create(tmp_path):
    missing_files = str(tmp_path / "nope_files.db")
    missing_events = str(tmp_path / "nope_events.db")
    r = EvidenceResolver(_backend({
        "A": {"output_files_db": missing_files, "output_events_db": missing_events},
    }))

    # DB file missing is a STORE failure (not a not-found), and never creates the DB.
    with pytest.raises(EvidenceStoreError):
        await r.resolve_evidence("A", "file:/case/report.docx")
    assert not Path(missing_files).exists()


@pytest.mark.asyncio
async def test_table_missing_raises_store_error(tmp_path):
    fdb, edb = str(tmp_path / "files.db"), str(tmp_path / "events.db")
    conn = sqlite3.connect(fdb)
    conn.execute("CREATE TABLE other (x TEXT)")  # files.db exists but has no files table
    conn.commit()
    conn.close()
    Path(edb).write_bytes(b"")  # empty events db (no tables)
    r = EvidenceResolver(_backend({"A": {"output_files_db": fdb, "output_events_db": edb}}))

    with pytest.raises(EvidenceStoreError):
        await r.resolve_evidence("A", "file:/case/report.docx")
    with pytest.raises(EvidenceStoreError):
        await r.resolve_evidence("A", "cluster:v1:100:CREATED")


# ---------- R8: zero persistence ----------

@pytest.mark.asyncio
async def test_R8_no_write_hash_unchanged(tmp_path):
    fdb, edb = str(tmp_path / "files.db"), str(tmp_path / "events.db")
    _make_files_db(fdb, ["/case/report.docx"])
    _make_events_db(edb, [{"timestamp": 6000, "event_type": "CREATED"}])
    h_f_before, h_e_before = _file_hash(fdb), _file_hash(edb)
    r = EvidenceResolver(_backend({"A": {"output_files_db": fdb, "output_events_db": edb}}))

    await r.resolve_evidence("A", "file:/case/report.docx")
    await r.resolve_evidence("A", "cluster:v1:100:CREATED")

    assert _file_hash(fdb) == h_f_before
    assert _file_hash(edb) == h_e_before


# ---------- model: source_db excluded from serialization ----------

def test_source_db_excluded_from_serialization():
    r = ResolvedEvidence(
        task_id="A",
        evidence_key="file:/x",
        evidence_type="file",
        normalized_path="/x",
        source_db="/secret/path.db",
    )
    dumped = r.model_dump()
    assert "source_db" not in dumped
    assert r.source_db == "/secret/path.db"  # still accessible internally
