"""Tests for deterministic multi-image file selection."""

import sqlite3
from types import SimpleNamespace

import pytest

from httpserver.services.case_analysis.multi_image_filter import MultiImageFilter


def _make_files_db(db_path: str, rows):
    """rows: list of (path, size)."""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE files (path TEXT, type TEXT, size INTEGER)")
    conn.executemany(
        "INSERT INTO files (path, type, size) VALUES (?, ?, ?)",
        [(p, "", s) for p, s in rows],
    )
    conn.commit()
    conn.close()


def _make_filter(cap=0):
    settings = SimpleNamespace(file_filter_mode="deterministic", filter_max_files=cap)
    return MultiImageFilter(settings, llm_service=None, cpp_backend=None)


@pytest.mark.asyncio
async def test_multi_deterministic_aggregates_and_dedups(tmp_path):
    db1 = str(tmp_path / "files1.db")
    db2 = str(tmp_path / "files2.db")
    _make_files_db(db1, [("/a/doc", 100), ("/shared/dup.log", 500)])
    _make_files_db(db2, [("/b/img", 200), ("/shared/dup.log", 500)])  # dup by (name,size)

    f = _make_filter()
    result = await f.filter_files_multi(
        files_db_paths=[db1, db2], case_description="case",
        max_files=400, task_ids=["t1", "t2"],
    )

    assert result["model_used"] == "deterministic_cpp_filter"
    assert result["total_files"] == 3          # 4 rows - 1 cross-image dup
    assert result["dedup_removed"] == 1
    assert set(result["filtered_files"]) == {"/a/doc", "/shared/dup.log", "/b/img"}
    assert result["source_counts"] == {db1: 2, db2: 2}


@pytest.mark.asyncio
async def test_multi_deterministic_cap(tmp_path):
    db1 = str(tmp_path / "files1.db")
    _make_files_db(db1, [("/z", 1), ("/a", 2), ("/m", 3)])

    f = _make_filter(cap=2)
    result = await f.filter_files_multi(
        files_db_paths=[db1], case_description="case",
        max_files=400, task_ids=["t1"],
    )

    assert result["filtered_files"] == ["/a", "/m"]
    assert result["selected_count"] == 2
