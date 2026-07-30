from pathlib import Path

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
