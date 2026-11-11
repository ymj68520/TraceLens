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
async def test_deterministic_returns_all_paths_ranked(tmp_path):
    """Without a cap every path is selected, ordered by forensic value
    (ties broken by path ascending)."""
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/c/notes.txt", "/a/report.pdf", "/b/photo.jpg"])

    f = _make_filter()
    result = await f._filter_files_deterministic(db, max_files=200, task_id="t1")

    assert result["model_used"] == "deterministic_cpp_filter"
    assert result["streaming_used"] is False
    # .pdf is a strong forensic format, .txt useful, .jpg scores nothing;
    # all three are selected but in value-ranked order.
    assert result["filtered_files"] == ["/a/report.pdf", "/c/notes.txt", "/b/photo.jpg"]
    assert result["total_files"] == 3
    assert result["selected_count"] == 3
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_deterministic_cap_takes_top_ranked(tmp_path):
    """Equal-score paths tie-break by path ascending, so a cap still takes
    the deterministic first N of that tie group."""
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/z", "/a", "/m"])

    f = _make_filter(cap=2)
    result = await f._filter_files_deterministic(db, max_files=200, task_id="t1")

    assert result["filtered_files"] == ["/a", "/m"]
    assert result["selected_count"] == 2
    assert result["total_files"] == 3
    assert result["truncated"] is True
    assert result["limit"] == 2
    assert result["limit_reason"] == "filter_max_files"


@pytest.mark.asyncio
async def test_deterministic_respects_request_max_files(tmp_path):
    """The request-level max_filter_files must bind in deterministic mode
    (previously it was logged and ignored)."""
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/p/one", "/p/two", "/p/three", "/p/four", "/p/five"])

    f = _make_filter(cap=0)  # settings cap unlimited
    result = await f._filter_files_deterministic(db, max_files=2, task_id="t1")

    assert result["selected_count"] == 2
    assert result["limit"] == 2
    assert result["limit_reason"] == "max_filter_files"
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_deterministic_cap_is_min_of_request_and_settings(tmp_path):
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/a", "/b", "/c", "/d"])

    # settings cap binds
    f = _make_filter(cap=2)
    result = await f._filter_files_deterministic(db, max_files=200, task_id="t1")
    assert result["selected_count"] == 2
    assert result["limit_reason"] == "filter_max_files"

    # request cap binds
    f = _make_filter(cap=10)
    result = await f._filter_files_deterministic(db, max_files=3, task_id="t1")
    assert result["selected_count"] == 3
    assert result["limit_reason"] == "max_filter_files"

    # both equal → both named
    f = _make_filter(cap=3)
    result = await f._filter_files_deterministic(db, max_files=3, task_id="t1")
    assert result["selected_count"] == 3
    assert result["limit_reason"] == "max_filter_files+filter_max_files"


@pytest.mark.asyncio
async def test_deterministic_value_ranking_excludes_noise(tmp_path):
    """A cap must not select an alphabetical prefix: $OrphanFiles residue,
    shredder remnants and pagefile.sys lose against real evidence files."""
    db = str(tmp_path / "files.db")
    paths = [
        "$OrphanFiles/OrphanFile-2331",
        "$OrphanFiles/OrphanFile-2332",
        "Q3JU6CPH.85PB",           # shredder remnant
        "0PA1ZXC2.9QD3",           # shredder remnant
        "/pagefile.sys",           # memory/page dump
        "/home/forensics/Documents/contract.pdf",
        "/var/lib/data/appdb.sqlite",
        "/etc/firewalld/zones/public.xml",
    ]
    _make_files_db(db, paths)

    f = _make_filter(cap=3)
    result = await f._filter_files_deterministic(db, max_files=3, task_id="t1")

    assert result["selected_count"] == 3
    assert set(result["filtered_files"]) == {
        "/home/forensics/Documents/contract.pdf",
        "/var/lib/data/appdb.sqlite",
        "/etc/firewalld/zones/public.xml",
    }
    # Highest-value file first
    assert result["filtered_files"][0] == "/home/forensics/Documents/contract.pdf"


@pytest.mark.asyncio
async def test_deterministic_ranked_order_is_deterministic(tmp_path):
    """Same input → same order; scores never ascend along the list."""
    db = str(tmp_path / "files.db")
    paths = [
        "/home/u/Downloads/report.docx",
        "/home/u/Downloads/img.png",
        "/var/www/html/index.php",
        "/srv/share/archive.zip",
        "/etc/app/config.ini",
        "/tmp/cache.dat",
    ]
    _make_files_db(db, paths)

    f = _make_filter(cap=4)
    r1 = await f._filter_files_deterministic(db, max_files=4, task_id="t1")
    r2 = await f._filter_files_deterministic(db, max_files=4, task_id="t1")

    assert r1["filtered_files"] == r2["filtered_files"]
    assert len(r1["filtered_files"]) == 4


@pytest.mark.asyncio
async def test_get_file_list_tolerates_non_utf8_paths(tmp_path):
    """Regression: one non-UTF-8 TEXT path used to raise
    "Could not decode to UTF-8 column 'path'" and zero out the whole image."""
    db = str(tmp_path / "files.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE files (path TEXT, type TEXT, size INTEGER)")
    # CAST(BLOB AS TEXT) mirrors the C++ writer binding raw bytes as TEXT.
    conn.execute(
        "INSERT INTO files (path, type, size) VALUES (CAST(? AS TEXT), ?, ?)",
        (b"/etc/firewalld/ipsets/\xd2\xff", "", 10),
    )
    conn.execute(
        "INSERT INTO files (path, type, size) VALUES (?, ?, ?)",
        ("/home/u/Documents/notes.txt", "", 20),
    )
    conn.commit()
    conn.close()

    f = _make_filter()
    result = await f._filter_files_deterministic(db, max_files=0, task_id="t1")

    # Both rows survive; the undecodable bytes become U+FFFD replacement chars.
    assert result["total_files"] == 2
    bad = [p for p in result["filtered_files"] if p.startswith("/etc/firewalld")]
    assert len(bad) == 1 and "\ufffd" in bad[0]


@pytest.mark.asyncio
async def test_get_file_list_reads_ranking_columns_when_present(tmp_path):
    """A real FileClassifier files.db carries category/scene columns; the
    reader must pick them up instead of failing on the richer schema."""
    db = str(tmp_path / "files.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE files (id INTEGER PRIMARY KEY, inode INTEGER, name TEXT,
            path TEXT, size INTEGER, extension TEXT, category TEXT, type TEXT,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            partition_num INTEGER DEFAULT 0, scene_type TEXT,
            scene_priority INTEGER DEFAULT 0, scene_relevant INTEGER DEFAULT 0)"""
    )
    conn.execute(
        "INSERT INTO files (path, type, size, category, extension, scene_priority, scene_relevant) "
        "VALUES (?, 'REG', 500, 'Databases', 'db', 100, 1)",
        ("/data/data/com.android.providers.contacts/contacts.db",),
    )
    conn.commit()
    conn.close()

    f = _make_filter()
    records = f._get_file_list_from_db(db)

    assert len(records) == 1
    rec = records[0]
    assert rec["category"] == "Databases"
    assert rec["extension"] == "db"
    assert rec["scene_priority"] == 100
    assert rec["scene_relevant"] == 1


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
async def test_deterministic_extracts_task_id_from_db_path(tmp_path):
    """When task_id is None, the deterministic path must extract the UUID from
    files_db_path (mirroring the LLM path) instead of defaulting to '_latest'.

    Regression guard: a silent data-placement divergence where the deterministic
    path persisted under '_latest' while the LLM path persisted under the real
    UUID.
    """
    import uuid

    task_uuid = str(uuid.uuid4())
    # Mirror production layout: .../tasks/<uuid>/files.db
    task_dir = tmp_path / "tasks" / task_uuid
    task_dir.mkdir(parents=True)
    db = str(task_dir / "files.db")
    _make_files_db(db, ["/a/doc", "/b/img"])

    f = _make_filter()
    await f._filter_files_deterministic(db, max_files=200, task_id=None)

    # The persisted case_analysis row must use the extracted UUID, not "_latest".
    conn = sqlite3.connect(db)
    cur = conn.execute("SELECT task_id FROM case_analysis WHERE task_id = ?", (task_uuid,))
    row = cur.fetchone()
    conn.close()
    assert row is not None, (
        "task_id should be extracted from files_db_path, but no case_analysis "
        "row was found under the expected UUID"
    )
    assert row[0] == task_uuid


@pytest.mark.asyncio
async def test_filter_files_by_case_llm_mode_does_not_call_deterministic(tmp_path):
    """In llm mode the deterministic path is skipped (LLM service is None -> raises)."""
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/x"])

    f = _make_filter(mode="llm")
    with pytest.raises(RuntimeError, match="LLM service not initialized"):
        await f.filter_files_by_case(db, "case desc", max_files=200, task_id="t1")
