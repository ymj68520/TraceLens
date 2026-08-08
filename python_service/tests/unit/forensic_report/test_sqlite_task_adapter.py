import sqlite3
from pathlib import Path

from httpserver.services.forensic_report.adapters.sqlite_task import SqliteTaskReportAdapter
from httpserver.services.forensic_report.models import AdapterContext, ScopeType


def _context(db_path: Path, task_id: str = "task-1") -> AdapterContext:
    return AdapterContext(
        scope_type=ScopeType.TASK,
        scope_id=task_id,
        evidence_id=task_id,
        task_id=task_id,
        evidence_name="evidence",
        db_paths={"files": str(db_path)},
        source_fingerprints={},
    )


def _db(path: Path, *, descriptions: bool = True) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE case_analysis (
                task_id TEXT, case_description TEXT, filtered_files TEXT,
                case_report TEXT, created_at INTEGER, updated_at INTEGER
            );
            CREATE TABLE files (
                id INTEGER PRIMARY KEY, name TEXT, path TEXT, size INTEGER,
                extension TEXT, category TEXT, type TEXT, mtime INTEGER,
                ctime INTEGER, is_deleted INTEGER, md5 TEXT, scene_type TEXT,
                scene_priority INTEGER, scene_relevant INTEGER
            );
            INSERT INTO case_analysis VALUES
                ('task-1', '案件描述', '["/evidence/a.txt"]', '# 研判结论', 1, 2);
            INSERT INTO files VALUES
                (1, 'a.txt', '/evidence/a.txt', 12, '.txt', 'Documents', 'REG',
                 10, 9, 0, 'abc', 'linux', 75, 1),
                (2, 'deleted.txt', '/evidence/deleted.txt', 4, '.txt', 'Documents',
                 'REG', 8, 7, 1, 'def', 'linux', 0, 0);
            """
        )
        if descriptions:
            conn.execute(
                """CREATE TABLE file_descriptions (
                    id INTEGER PRIMARY KEY, file_path TEXT, description TEXT,
                    summary TEXT, keywords TEXT, model_used TEXT,
                    is_relevant INTEGER, created_at INTEGER
                )"""
            )
            conn.execute(
                "INSERT INTO file_descriptions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (1, "/evidence/a.txt", "详细描述", "可疑文件", '["suspicious"]',
                 "test-model", 1, 3),
            )


def test_only_files_become_forensic_records_even_with_intelligence_tables(tmp_path: Path):
    db_path = tmp_path / "files.db"
    _db(db_path)
    adapter = SqliteTaskReportAdapter()
    context = _context(db_path)

    assert adapter.probe(context).available
    categories = adapter.categories(context)
    assert [item.category_id for item in categories] == ["evidence.files"]
    assert categories[0].source_table == "files"

    records = list(adapter.iter_records(context, categories[0]))
    assert len(records) == 2
    assert {record.source_table for record in records} == {"files"}
    assert all(record.category == "evidence.files" for record in records)
    assert records[0].record_id.startswith("rec_")


def test_deleted_files_are_included_and_marked(tmp_path: Path):
    db_path = tmp_path / "files.db"
    _db(db_path, descriptions=False)
    adapter = SqliteTaskReportAdapter()
    context = _context(db_path)

    category = adapter.categories(context)[0]
    records = list(adapter.iter_records(context, category))
    deleted = next(record for record in records if record.source_record_id == "2")
    assert deleted.data_state.value == "deleted"
    assert deleted.source_path == "/evidence/deleted.txt"


def test_missing_files_table_is_unavailable(tmp_path: Path):
    db_path = tmp_path / "files.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE case_analysis (task_id TEXT, case_report TEXT)")
    adapter = SqliteTaskReportAdapter()
    context = _context(db_path)

    result = adapter.probe(context)
    assert result.available is False
    assert adapter.categories(context) == []


def test_missing_database_is_unavailable(tmp_path: Path):
    adapter = SqliteTaskReportAdapter()
    context = _context(tmp_path / "missing.db")
    result = adapter.probe(context)
    assert result.available is False
    assert adapter.categories(context) == []
