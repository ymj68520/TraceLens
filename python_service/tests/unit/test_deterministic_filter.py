"""Tests for deterministic (non-LLM) file selection in FileFilter."""

import sqlite3
from types import SimpleNamespace

import pytest

from httpserver.services.case_analysis.file_filter import FileFilter


def _make_files_db(db_path: str, paths):
    """Create a minimal files.db with a files table."""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE files (path TEXT, type TEXT, size INTEGER)")
    conn.executemany(
        "INSERT INTO files (path, type, size) VALUES (?, ?, ?)",
        [(p, "", 0) for p in paths],
    )
    conn.commit()
    conn.close()


def _make_filter(mode="deterministic", cap=0):
    settings = SimpleNamespace(file_filter_mode=mode, filter_max_files=cap)
    # SimpleNamespace has no llm_filter_config attr, so FileMatcher /
    # FilterResultValidator hasattr-guards fall back to defaults.
    return FileFilter(settings, llm_service=None, cpp_backend=None)


@pytest.mark.asyncio
async def test_deterministic_returns_all_paths_sorted(tmp_path):
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/c/log", "/a/doc", "/b/img"])

    f = _make_filter()
    result = await f._filter_files_deterministic(db, max_files=200, task_id="t1")

    assert result["model_used"] == "deterministic_cpp_filter"
    assert result["streaming_used"] is False
    assert result["filtered_files"] == ["/a/doc", "/b/img", "/c/log"]
    assert result["total_files"] == 3
    assert result["selected_count"] == 3


@pytest.mark.asyncio
async def test_deterministic_cap_takes_first_n_sorted(tmp_path):
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/z", "/a", "/m"])

    f = _make_filter(cap=2)
    result = await f._filter_files_deterministic(db, max_files=200, task_id="t1")

    assert result["filtered_files"] == ["/a", "/m"]
    assert result["selected_count"] == 2
    assert result["total_files"] == 3


@pytest.mark.asyncio
async def test_deterministic_empty_db_returns_empty(tmp_path):
    db = str(tmp_path / "files.db")
    _make_files_db(db, [])

    f = _make_filter()
    result = await f._filter_files_deterministic(db, max_files=200, task_id="t1")

    assert result["filtered_files"] == []
    assert result["total_files"] == 0
    assert result["selected_count"] == 0


@pytest.mark.asyncio
async def test_filter_files_by_case_dispatches_deterministic(tmp_path):
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/x"])

    f = _make_filter(mode="deterministic")
    result = await f.filter_files_by_case(db, "case desc", max_files=200, task_id="t1")

    assert result["model_used"] == "deterministic_cpp_filter"


@pytest.mark.asyncio
async def test_filter_files_by_case_llm_mode_does_not_call_deterministic(tmp_path):
    """In llm mode the deterministic path is skipped (LLM service is None -> raises)."""
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/x"])

    f = _make_filter(mode="llm")
    with pytest.raises(RuntimeError, match="LLM service not initialized"):
        await f.filter_files_by_case(db, "case desc", max_files=200, task_id="t1")
