"""Tests for immutable Final Report versions and publications."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from httpserver.services.final_report_assembly import (
    FINAL_REPORT_ASSEMBLED,
    FINAL_REPORT_VALID,
    FinalReportParagraph,
    FinalReportSection,
    FinalReportVersion,
)
from httpserver.services.final_report_repository import FinalReportRepository


def _report():
    return FinalReportVersion(
        task_id="task-a",
        report_dataset_hash="dataset",
        citation_graph_hash="graph",
        section_plan_hash="plan",
        sections=[FinalReportSection(
            section_id="SEC-001",
            section_type="analysis.overview",
            title="Overview",
            order=1,
            paragraphs=[FinalReportParagraph(text="text")],
        )],
        status=FINAL_REPORT_ASSEMBLED,
        validation_status=FINAL_REPORT_VALID,
    ).with_hash()


def test_successful_versions_allocate_per_task(tmp_path):
    repo = FinalReportRepository(tmp_path / "investigation.db")
    first = repo.create_assembled(_report())
    second = repo.create_assembled(_report())

    assert first.report_version == 1
    assert second.report_version == 2
    assert first.final_report_hash == second.final_report_hash
    assert [item.report_version for item in repo.list_reports("task-a")] == [2, 1]


def test_invalid_report_cannot_be_persisted(tmp_path):
    repo = FinalReportRepository(tmp_path / "investigation.db")
    invalid = _report().model_copy(update={
        "status": "invalid",
        "validation_status": "invalid",
    })

    with pytest.raises(ValueError):
        repo.create_assembled(invalid)
    assert repo.list_reports("task-a") == []


def test_publication_is_separate_and_idempotent(tmp_path):
    repo = FinalReportRepository(tmp_path / "investigation.db")
    report = repo.create_assembled(_report())
    first = repo.publish(
        "task-a", report.report_id, final_report_hash=report.final_report_hash
    )
    second = repo.publish(
        "task-a", report.report_id, final_report_hash=report.final_report_hash
    )

    assert first.publication_id == second.publication_id
    assert first.status == "published"
    assert repo.get_for_task("task-a", report.report_id).status == "assembled"
    assert repo.get_publication("task-a", report.report_id).report_version == 1


def test_publication_is_version_scoped_and_does_not_inherit(tmp_path):
    repo = FinalReportRepository(tmp_path / "investigation.db")
    first = repo.create_assembled(_report())
    second = repo.create_assembled(_report())

    publication = repo.publish(
        "task-a", first.report_id, final_report_hash=first.final_report_hash
    )

    assert publication.report_id == first.report_id
    assert repo.get_publication("task-a", first.report_id).report_version == 1
    assert repo.get_publication("task-a", second.report_id) is None


    repo = FinalReportRepository(tmp_path / "investigation.db")
    report = repo.create_assembled(_report())

    with pytest.raises(ValueError, match="hash mismatch"):
        repo.publish("task-a", report.report_id, final_report_hash="wrong")


def test_report_versions_are_immutable_at_repository_boundary(tmp_path):
    repo = FinalReportRepository(tmp_path / "investigation.db")
    report = repo.create_assembled(_report())
    before = repo.get(report.report_id).to_response_dict()

    with sqlite3.connect(tmp_path / "investigation.db") as conn:
        row = conn.execute(
            "SELECT final_report_hash, status, markdown_text FROM final_report_versions "
            "WHERE report_id = ?",
            (report.report_id,),
        ).fetchone()
    assert row == (
        before["final_report_hash"],
        "assembled",
        before["markdown_text"],
    )


def test_read_only_list_does_not_create_report_tables(tmp_path):
    db_path = tmp_path / "investigation.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 37")
        conn.commit()

    repo = FinalReportRepository.read_only(db_path)
    assert repo.list_reports("task-a") == []
    assert repo.get_for_task("task-a", "missing") is None
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='final_report_versions'"
        ).fetchone() is None


def test_get_publication_preserves_missing_table_error(tmp_path):
    db_path = tmp_path / "investigation.db"
    repo = FinalReportRepository(db_path)
    report = repo.create_assembled(_report())
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE final_report_publications")
        connection.commit()

    repo = FinalReportRepository.read_only(db_path)
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        repo.get_publication("task-a", report.report_id)


def test_read_only_connection_rejects_writes(tmp_path):
    db_path = tmp_path / "investigation.db"
    FinalReportRepository(db_path)
    repo = FinalReportRepository.read_only(db_path)
    before = db_path.read_bytes()

    with repo._connect() as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE forbidden_write (id INTEGER)")
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO final_report_versions VALUES ("
                              "'id', 'task-a', 1, 'schema', 'assembly', 'dataset', "
                              "'graph', 'plan', '[]', '[]', '[]', 'valid', '[]', '[]', "
                              "'hash', 'assembled', '', 1)")

    assert db_path.read_bytes() == before


def test_concurrent_report_version_allocation(tmp_path):
    db_path = tmp_path / "investigation.db"
    errors = []
    versions = []
    lock = threading.Lock()

    def allocate():
        try:
            report = FinalReportRepository(db_path).create_assembled(_report())
            with lock:
                versions.append(report.report_version)
        except Exception as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=allocate) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(versions) == list(range(1, 9))
