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
