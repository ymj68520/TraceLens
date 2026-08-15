from pathlib import Path
import sqlite3
import threading

import pytest

from httpserver.services.forensic_report.models import ReportStatus, ScopeType
from httpserver.services.forensic_report.repository import ReportRepository


def test_versions_increase_per_scope_and_not_globally(tmp_path: Path):
    repo = ReportRepository(tmp_path / "reports.db")
    one = repo.create_version(ScopeType.TASK, "task-a", "A", ["task-a"])
    two = repo.create_version(ScopeType.TASK, "task-a", "A", ["task-a"])
    other = repo.create_version(ScopeType.TASK, "task-b", "B", ["task-b"])
    assert (one.version, two.version, other.version) == (1, 2, 1)


def test_published_version_cannot_return_to_generating(tmp_path: Path):
    repo = ReportRepository(tmp_path / "reports.db")
    version = repo.create_version(ScopeType.TASK, "task-a", "A", ["task-a"])
    repo.mark_generating(version.report_id, "resolve-scope")
    repo.mark_ready(version.report_id, "task/task-a/report/manifest.json", [])
    with pytest.raises(ValueError, match="immutable"):
        repo.mark_generating(version.report_id, "retry")
    assert repo.get(version.report_id).status is ReportStatus.READY


@pytest.mark.concurrency
def test_concurrent_ready_transition_cannot_overwrite_terminal_state(tmp_path: Path):
    repo = ReportRepository(tmp_path / "reports.db")
    version = repo.create_version(ScopeType.TASK, "task-a", "A", ["task-a"])
    repo.mark_generating(version.report_id, "generate")

    entered = threading.Event()
    release = threading.Event()
    original_assert_mutable = ReportRepository._assert_mutable

    def pause_after_check(self, conn: sqlite3.Connection, report_id: str) -> None:
        original_assert_mutable(self, conn, report_id)
        if threading.current_thread().name == "failed-worker":
            entered.set()
            assert release.wait(timeout=5)

    errors: list[BaseException] = []
    ReportRepository._assert_mutable = pause_after_check
    try:
        def mark_failed() -> None:
            try:
                repo.mark_failed(version.report_id, "write", "worker failed")
            except BaseException as error:
                errors.append(error)

        failed = threading.Thread(target=mark_failed, name="failed-worker")
        failed.start()
        assert entered.wait(timeout=5)

        repo.mark_ready(version.report_id, "manifest.json", [])
        release.set()
        failed.join(timeout=5)
        assert not failed.is_alive()
    finally:
        ReportRepository._assert_mutable = original_assert_mutable
        release.set()

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert repo.get(version.report_id).status is ReportStatus.READY
