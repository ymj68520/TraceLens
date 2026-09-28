"""Release startup must not rewrite an existing report store."""

import hashlib
import sqlite3

import pytest

from httpserver.services.forensic_report.models import ScopeType
from httpserver.services.forensic_report.repository import ReportRepository


def test_existing_report_store_is_readable_without_schema_or_recovery_writes(tmp_path):
    path = tmp_path / "reports.db"
    prior = ReportRepository(path).create_version(
        ScopeType.TASK, "synthetic-task", "synthetic historical report", ["synthetic-task"])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    readonly = ReportRepository(path, readonly=True)
    assert [item.report_id for item in readonly.list_versions(ScopeType.TASK, "synthetic-task")] == [prior.report_id]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with pytest.raises(sqlite3.OperationalError):
        readonly.create_version(ScopeType.TASK, "synthetic-task", "test", ["synthetic-task"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        ReportRepository(missing, readonly=True)
    assert not missing.exists()
