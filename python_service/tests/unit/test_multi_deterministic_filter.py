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

    assert result["filtered_files"] == ["/a", "/m"]  # equal scores -> path tie-break
    assert result["selected_count"] == 2
    assert result["truncated"] is True
    assert result["limit"] == 2
    assert result["limit_reason"] == "filter_max_files"


@pytest.mark.asyncio
async def test_multi_respects_request_max_files(tmp_path):
    """The request-level max_filter_files must bind in deterministic mode."""
    db1 = str(tmp_path / "files1.db")
    _make_files_db(db1, [("/p/1", 1), ("/p/2", 2), ("/p/3", 3), ("/p/4", 4)])

    f = _make_filter(cap=0)  # settings unlimited
    result = await f.filter_files_multi(
        files_db_paths=[db1], case_description="case",
        max_files=3, task_ids=["t1"],
    )

    assert result["selected_count"] == 3
    assert result["limit"] == 3
    assert result["limit_reason"] == "max_filter_files"
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_multi_per_image_quota_stops_junk_crowd_out(tmp_path):
    """With a cap, one junk-heavy image must not crowd out other images:
    the cap is split into per-image quotas, each image contributing its
    best-ranked files."""
    db1 = str(tmp_path / "junk.db")
    db2 = str(tmp_path / "evidence_a.db")
    db3 = str(tmp_path / "evidence_b.db")
    _make_files_db(db1, [(f"$OrphanFiles/OrphanFile-{i:04d}", 1) for i in range(12)])
    _make_files_db(db2, [("/home/u/Documents/contract.pdf", 100),
                         ("/home/u/Pictures/photo.jpg", 50)])
    _make_files_db(db3, [("/var/www/html/index.php", 30)])

    f = _make_filter(cap=0)
    result = await f.filter_files_multi(
        files_db_paths=[db1, db2, db3], case_description="case",
        max_files=3, task_ids=["t1", "t2", "t3"],
    )

    # cap=3 over 3 images -> 1 slot each; the junk image gets exactly one
    assert result["selected_count"] == 3
    assert "/home/u/Documents/contract.pdf" in result["filtered_files"]
    assert "/var/www/html/index.php" in result["filtered_files"]
    orphan_selected = [p for p in result["filtered_files"] if "$OrphanFiles" in p]
    assert len(orphan_selected) == 1
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_multi_quota_redistributes_to_larger_pools(tmp_path):
    """An image with fewer files than its share leaves quota for the others."""
    db1 = str(tmp_path / "small.db")
    db2 = str(tmp_path / "big.db")
    _make_files_db(db1, [("/home/u/Notes/plan.txt", 5)])  # 1 file
    _make_files_db(db2, [(f"/home/u/Downloads/doc{i}.docx", 10 + i) for i in range(6)])

    f = _make_filter(cap=0)
    result = await f.filter_files_multi(
        files_db_paths=[db1, db2], case_description="case",
        max_files=5, task_ids=["t1", "t2"],
    )

    # water-filling: small image keeps 1 slot, big image gets the other 4
    assert result["selected_count"] == 5
    assert "/home/u/Notes/plan.txt" in result["filtered_files"]
    docx_selected = [p for p in result["filtered_files"] if p.endswith(".docx")]
    assert len(docx_selected) == 4


@pytest.mark.asyncio
async def test_multi_tolerates_non_utf8_paths(tmp_path):
    """A non-UTF-8 path must not zero out an image's contribution to the
    cross-image selection (the Aliyun files.db regression)."""
    db1 = str(tmp_path / "aliyun.db")
    db2 = str(tmp_path / "win.db")
    conn = sqlite3.connect(db1)
    conn.execute("CREATE TABLE files (path TEXT, type TEXT, size INTEGER)")
    conn.execute(
        "INSERT INTO files (path, type, size) VALUES (CAST(? AS TEXT), ?, ?)",
        (b"/etc/firewalld/ipsets/\xd2", "", 10),
    )
    conn.commit()
    conn.close()
    _make_files_db(db2, [("/home/u/Documents/contract.pdf", 100)])

    f = _make_filter()
    result = await f.filter_files_multi(
        files_db_paths=[db1, db2], case_description="case",
        max_files=0, task_ids=["t1", "t2"],
    )

    # aliyun.db still contributes its (replacement-decoded) path
    assert result["source_counts"][db1] == 1
    assert result["total_files"] == 2
    assert any("/etc/firewalld/ipsets/" in p for p in result["filtered_files"])
