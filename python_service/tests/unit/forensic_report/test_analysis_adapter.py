import sqlite3
from pathlib import Path

from httpserver.services.forensic_report.analysis_adapter import AnalysisChaptersAdapter


def test_load_task_keeps_existing_markdown_and_reference_tokens(tmp_path: Path):
    db = tmp_path / "files.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE case_analysis (
            task_id TEXT PRIMARY KEY, case_description TEXT, filtered_files TEXT,
            case_report TEXT, created_at INTEGER, updated_at INTEGER)""")
        conn.execute(
            "INSERT INTO case_analysis VALUES (?, ?, ?, ?, ?, ?)",
            (
                "task-1",
                "fraud",
                '["/data/a.db"]',
                "# 案件概述\n[[file:/data/a.db]]\n[[event:CREATE@1700000000/data]]",
                1,
                2,
            ),
        )

    analysis = AnalysisChaptersAdapter().load_task(str(db), "task-1")

    assert analysis["markdown"].startswith("# 案件概述")
    assert analysis["generated_at"] == "2"
    assert analysis["filtered_files"] == ["/data/a.db"]


def test_load_task_normalizes_malformed_filtered_files_and_missing_timestamp(monkeypatch):
    monkeypatch.setattr(
        "httpserver.services.forensic_report.analysis_adapter.get_case_report_from_db",
        lambda _path, _task_id: {
            "case_report": "[[file:/data/a.db]]",
            "updated_at": None,
            "filtered_files": '["/data/a.db"]',
        },
    )

    analysis = AnalysisChaptersAdapter().load_task("/readonly/files.db", "task-1")

    assert analysis == {
        "markdown": "[[file:/data/a.db]]",
        "generated_at": "",
        "filtered_files": [],
    }


def test_load_task_returns_empty_snapshot_when_no_legacy_analysis():
    assert AnalysisChaptersAdapter().load_task("", "task-1") == {
        "markdown": "",
        "generated_at": "",
        "filtered_files": [],
    }
