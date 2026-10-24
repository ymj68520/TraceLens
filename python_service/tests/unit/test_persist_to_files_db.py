"""Tests for LLMService.persist_to_files_db (A2 / A3 / A4 / A5).

Validates the S0-3 + S0-4 fixes against a real temporary SQLite _files.db:
  A2  basename-colliding Evidence rows are not cross-updated
  A3  backslash / duplicate-separator inputs match the canonical files.path
  A4  a missing path returns False and writes NEITHER files NOR file_descriptions
  A5  a missing DB fails closed and never touches a fallback DB
"""

import sqlite3
from pathlib import Path

from httpserver.services.llm.llm_service import LLMService


def _make_files_db(db_path: str, file_rows, with_descriptions: bool = True):
    """Create a minimal _files.db with a files table (incl. LLM columns).

    Pre-creating file_descriptions lets A4 assert row counts even though the
    fixed persist() returns before ensuring that schema on a miss.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE files (
            path TEXT,
            md5 TEXT,
            llm_summary TEXT,
            llm_description TEXT,
            llm_keywords TEXT,
            llm_analyzed_at INTEGER,
            llm_model_used TEXT
        )
        """
    )
    for r in file_rows:
        conn.execute("INSERT INTO files (path) VALUES (?)", (r,))
    if with_descriptions:
        conn.execute(
            """
            CREATE TABLE file_descriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE,
                description TEXT,
                summary TEXT,
                keywords TEXT,
                model_used TEXT,
                is_relevant INTEGER DEFAULT 1,
                created_at INTEGER
            )
            """
        )
    conn.commit()
    conn.close()


def _make_service() -> LLMService:
    # persist_to_files_db uses no instance state besides the class method
    # _ensure_file_descriptions_schema and the module-level normalize_evidence_path,
    # so bypass __init__ to avoid wiring up LLM clients / sub-analyzers.
    return LLMService.__new__(LLMService)


def test_A2_basename_siblings_not_cross_updated(tmp_path):
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/A/report.docx", "/B/report.docx"])

    ok = _make_service().persist_to_files_db(
        db_path=db, file_path="/A/report.docx",
        description="desc-A", summary="sum-A", keywords="k", model_used="m",
    )

    assert ok is True
    conn = sqlite3.connect(db)
    rows = {r[0]: r[1] for r in conn.execute("SELECT path, llm_description FROM files")}
    conn.close()
    assert rows["/A/report.docx"] == "desc-A"
    assert rows["/B/report.docx"] is None  # sibling untouched (was the old bug)


def test_A3_matches_via_normalization(tmp_path):
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/A/report.docx"])

    for raw in ("\\A\\report.docx", "//A//report.docx", "/A/report.docx/"):
        ok = _make_service().persist_to_files_db(
            db_path=db, file_path=raw,
            description="D", summary="S", keywords="k", model_used="m",
        )
        assert ok is True, f"expected match for {raw!r}"

    conn = sqlite3.connect(db)
    desc = conn.execute(
        "SELECT llm_description FROM files WHERE path='/A/report.docx'"
    ).fetchone()[0]
    conn.close()
    assert desc == "D"


def test_A4_missing_path_writes_neither_table(tmp_path):
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/A/report.docx"])

    ok = _make_service().persist_to_files_db(
        db_path=db, file_path="/missing/file.txt",
        description="D", summary="S", keywords="k", model_used="m",
    )

    assert ok is False
    conn = sqlite3.connect(db)
    existing_desc = conn.execute(
        "SELECT llm_description FROM files WHERE path='/A/report.docx'"
    ).fetchone()[0]
    desc_rows = conn.execute("SELECT COUNT(*) FROM file_descriptions").fetchone()[0]
    conn.close()
    assert existing_desc is None          # files table untouched
    assert desc_rows == 0                 # no orphan file_descriptions row


def test_A5_missing_db_fails_closed(tmp_path):
    db = str(tmp_path / "does_not_exist.db")

    ok = _make_service().persist_to_files_db(
        db_path=db, file_path="/A/report.docx",
        description="D", summary="S", keywords="k", model_used="m",
    )

    assert ok is False
    assert not Path(db).exists()          # must not create the target DB


def test_concurrent_writes_keep_a_single_complete_version_chain(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/A/report.docx"])
    barrier = Barrier(8)
    def write(index):
        barrier.wait(timeout=10)
        return _make_service().persist_to_files_db(
            db_path=db, file_path="/A/report.docx", task_id="T",
            description=f"revision-{index}", summary="S", keywords="k", model_used="m")
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(write, range(8)))
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT id, analysis_id_upstream FROM file_analyses ORDER BY id").fetchall()
        assert len(rows) == 8
        assert [r[1] for r in rows] == [None] + [r[0] for r in rows[:-1]]
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_busy_writer_is_retried_not_dropped(tmp_path, monkeypatch):
    """A locked database must delay the write, never discard it.

    On PC.E01 a 32-way fan-out hit "database is locked" 81 times and each
    result was lost: the old code had a 10s busy timeout and no retry. The
    first attempt here raises the same error; the retry must persist the row.
    """
    import sqlite3 as _sqlite3

    from httpserver.services.llm import llm_service as module

    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/A/report.docx"])
    real_connect = _sqlite3.connect
    calls = {"n": 0}

    def flaky_connect(*args, **kwargs):
        # Let the schema-ensure connection through, then fail the first
        # transaction with the exact error the production run produced.
        calls["n"] += 1
        if calls["n"] == 2:
            raise _sqlite3.OperationalError("database is locked")
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(module.sqlite3, "connect", flaky_connect)
    monkeypatch.setattr(module, "WRITE_RETRY_BASE_SLEEP_S", 0.0)

    ok = _make_service().persist_to_files_db(
        db_path=db, file_path="/A/report.docx", task_id="T",
        description="survives-a-busy-writer", summary="S",
        keywords="k", model_used="m",
    )

    assert ok is True
    with sqlite3.connect(db) as conn:
        desc = conn.execute(
            "SELECT llm_description FROM files WHERE path='/A/report.docx'"
        ).fetchone()[0]
    assert desc == "survives-a-busy-writer"


def test_non_busy_sqlite_error_is_not_retried(tmp_path, monkeypatch):
    """Only busy/locked errors are retryable; a real schema error must fail fast."""
    import sqlite3 as _sqlite3

    from httpserver.services.llm import llm_service as module

    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/A/report.docx"])
    calls = {"n": 0}

    def broken_schema(_db_path):
        calls["n"] += 1
        raise _sqlite3.OperationalError("no such table: files")

    # Patch the schema helper itself: it owns its own sqlite3 import, so
    # patching module.sqlite3 would not reach it.
    monkeypatch.setattr(module, "ensure_file_analysis_schema", broken_schema)
    monkeypatch.setattr(module, "WRITE_RETRY_BASE_SLEEP_S", 0.0)

    assert _make_service().persist_to_files_db(
        db_path=db, file_path="/A/report.docx", description="D",
        summary="S", keywords="k", model_used="m") is False
    # A non-busy error must not enter the retry loop.
    assert calls["n"] == 1
