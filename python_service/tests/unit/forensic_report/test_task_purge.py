"""Task-deletion cascade for the report store.

Deleting a task used to leave its report versions, published snapshot trees and
per-report lock files behind. Nothing in the product deletes report versions,
so those rows and directories were permanent garbage that no API could reach.
The purge must remove all of them while keeping the immutable
``report_generation_inputs`` audit rows untouched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import forensic_reports
from httpserver.services.forensic_report.ids import safe_segment
from httpserver.services.forensic_report.models import ScopeType
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.forensic_report.service import (
    ForensicReportService,
    ReportPurgeIncomplete,
)
from httpserver.services.forensic_report.snapshot_writer import SnapshotWriter
from httpserver.services.investigation.initial_analysis_translation import (
    InitialAnalysisTranslationCache,
)

TASK_ID = "11111111-2222-3333-4444-555555555555"
OTHER_TASK = "99999999-8888-7777-6666-555555555555"


def _service(tmp_path: Path) -> ForensicReportService:
    return ForensicReportService(
        repository=ReportRepository(tmp_path / "reports.db"),
        resolver=AsyncMock(),
        writer=SnapshotWriter(tmp_path / "snapshots", "test"),
        adapters=[],
    )


def _publish(service: ForensicReportService, task_id: str) -> tuple[str, Path]:
    """Create one ready narrative version plus its published snapshot tree."""
    version = service.repository.create_version(
        scope_type=ScopeType.TASK,
        scope_id=task_id,
        title="Task report",
        task_ids=[task_id],
    )
    root = Path(service.writer.report_root)
    final = root / "task" / safe_segment(task_id) / safe_segment(version.report_id)
    final.mkdir(parents=True)
    (final / "manifest.json").write_text("{}", "utf-8")
    service.repository.mark_generating(version.report_id, stage="writing")
    service.repository.mark_ready(
        version.report_id,
        manifest_path=str(final / "manifest.json"),
        warnings=[],
    )
    lock = root / ".locks" / f"{safe_segment(version.report_id)}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("1234", "utf-8")
    return version.report_id, final


def test_purge_removes_versions_snapshots_and_locks(tmp_path: Path):
    service = _service(tmp_path)
    report_id, final_dir = _publish(service, TASK_ID)
    other_id, other_dir = _publish(service, OTHER_TASK)

    result = service.purge_task(TASK_ID)

    assert result["deleted_versions"] == 1
    assert not final_dir.exists()
    assert (Path(service.writer.report_root) / ".locks"
            / f"{safe_segment(report_id)}.lock").exists() is False
    # The other task's report is untouched.
    assert other_dir.exists()
    assert service.repository.get(other_id) is not None
    # The now-empty per-task snapshot parent is reclaimed too.
    assert not (Path(service.writer.report_root) / "task"
                / safe_segment(TASK_ID)).exists()


def test_purge_removes_lock_beside_the_output_root(tmp_path: Path):
    """_ReportClaim writes <output>/.locks, one level above <output>/snapshots.

    The production service hands SnapshotWriter <output>/snapshots, so the
    purge must look one level up for locks or every deleted report leaks one.
    """
    output = tmp_path / "reports"
    service = ForensicReportService(
        repository=ReportRepository(output / "reports.db"),
        resolver=AsyncMock(),
        writer=SnapshotWriter(output / "snapshots", "test"),
        adapters=[],
    )
    report_id, final_dir = _publish(service, TASK_ID)
    # _publish wrote the lock beside the writer root; move it to the real
    # claim layout to prove the purge follows the production path.
    old_lock = Path(service.writer.report_root) / ".locks" / (
        f"{safe_segment(report_id)}.lock")
    new_lock = output / ".locks" / f"{safe_segment(report_id)}.lock"
    new_lock.parent.mkdir(parents=True, exist_ok=True)
    old_lock.replace(new_lock)

    service.purge_task(TASK_ID)

    assert not final_dir.exists()
    assert not new_lock.exists()


def test_purge_keeps_immutable_generation_inputs(tmp_path: Path):
    service = _service(tmp_path)
    _publish(service, TASK_ID)
    service.repository.create_generation_input(
        TASK_ID,
        requested_by="tester",
        input_schema_version=1,
        prompt_version="v1",
        input_envelope_json="{}",
        input_hash="deadbeef",
    )

    service.purge_task(TASK_ID)

    with sqlite3.connect(tmp_path / "reports.db") as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM report_generation_inputs WHERE task_id = ?",
            (TASK_ID,),
        ).fetchone()[0]
    assert remaining == 1


def test_purge_refuses_while_a_generation_is_in_progress(tmp_path: Path):
    service = _service(tmp_path)
    version = service.repository.create_version(
        scope_type=ScopeType.TASK,
        scope_id=TASK_ID,
        title="Task report",
        task_ids=[TASK_ID],
    )
    assert version.status.value == "queued"

    with pytest.raises(ValueError, match="still has reports in progress"):
        service.purge_task(TASK_ID)

    # Refusal must not have deleted the row it named.
    assert service.repository.get(version.report_id) is not None


def test_purge_ignores_manifest_paths_outside_the_root(tmp_path: Path):
    service = _service(tmp_path)
    report_id, final_dir = _publish(service, TASK_ID)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("evidence", "utf-8")
    with sqlite3.connect(tmp_path / "reports.db") as conn:
        conn.execute(
            "UPDATE report_versions SET manifest_path = ? WHERE report_id = ?",
            ("../../outside/manifest.json", report_id),
        )
        conn.commit()

    service.purge_task(TASK_ID)

    # The escaped target survives; the expected layout directory still goes.
    assert (outside / "keep.txt").exists()
    assert not final_dir.exists()


def test_purge_reports_unremovable_directories(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    _, final_dir = _publish(service, TASK_ID)

    import shutil

    def deny(*args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(shutil, "rmtree", deny)

    with pytest.raises(ReportPurgeIncomplete) as excinfo:
        service.purge_task(TASK_ID)
    assert any(str(final_dir) in error for error in excinfo.value.errors)
    # Rows are already gone even though the directory is not.
    assert service.repository.list_versions(ScopeType.TASK, TASK_ID) == []


def test_translation_cache_purge_is_task_scoped(tmp_path: Path):
    db_path = tmp_path / "initial_analysis_translations.db"
    cache = InitialAnalysisTranslationCache(db_path, None)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE initial_analysis_translations (
                task_id TEXT NOT NULL, evidence_key TEXT NOT NULL,
                source_hash TEXT NOT NULL, prompt_version TEXT NOT NULL,
                translated_text TEXT NOT NULL, model TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (task_id, evidence_key, source_hash, prompt_version))"""
        )
        conn.executemany(
            "INSERT INTO initial_analysis_translations VALUES (?,?,?,?,?,?,?)",
            [
                (TASK_ID, "k1", "h1", "v1", "text", "m", 1),
                (TASK_ID, "k2", "h2", "v1", "text", "m", 2),
                (OTHER_TASK, "k3", "h3", "v1", "text", "m", 3),
            ],
        )
        conn.commit()

    assert cache.purge_task(TASK_ID) == 2
    with sqlite3.connect(db_path) as conn:
        left = conn.execute(
            "SELECT task_id FROM initial_analysis_translations"
        ).fetchall()
    assert left == [(OTHER_TASK,)]


def test_translation_cache_purge_is_safe_without_a_store(tmp_path: Path):
    cache = InitialAnalysisTranslationCache(tmp_path / "absent.db", None)
    assert cache.purge_task(TASK_ID) == 0


def test_route_purges_reports_and_translations(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    _, final_dir = _publish(service, TASK_ID)
    cache_path = tmp_path.parent / "initial_analysis_translations.db"
    cache_path.write_bytes(b"")

    class _Executor:
        async def cancel_task(self, task_id, *, reason):
            assert task_id == TASK_ID
            return 1

    class _Manager:
        def __init__(self):
            self.forensic_report_service = service
            self.report_generation_executor = _Executor()

    monkeypatch.setattr(
        forensic_reports, "get_service_manager", lambda: _Manager()
    )
    monkeypatch.setattr(
        forensic_reports, "_translation_cache_path", lambda: cache_path
    )
    monkeypatch.setattr(
        forensic_reports, "get_report_service", lambda: service
    )

    app = FastAPI()
    app.include_router(forensic_reports.router, prefix="/api/reports")
    client = TestClient(app)

    response = client.delete(f"/api/reports/tasks/{TASK_ID}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted_versions"] == 1
    assert body["cancelled_generations"] == 1
    assert not final_dir.exists()


def test_route_maps_in_progress_generation_to_409(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)

    class _Manager:
        forensic_report_service = service
        report_generation_executor = None

    monkeypatch.setattr(
        forensic_reports, "get_service_manager", lambda: _Manager()
    )
    monkeypatch.setattr(
        forensic_reports, "get_report_service", lambda: service
    )
    # Queue a version so the purge refuses.
    service.repository.create_version(
        scope_type=ScopeType.TASK,
        scope_id=TASK_ID,
        title="Task report",
        task_ids=[TASK_ID],
    )

    app = FastAPI()
    app.include_router(forensic_reports.router, prefix="/api/reports")
    client = TestClient(app)

    response = client.delete(f"/api/reports/tasks/{TASK_ID}")

    assert response.status_code == 409, response.text
