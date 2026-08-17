"""Phase D2b: Office parser task/workspace contract tests."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException

from httpserver.config import Settings
from httpserver.routes import office


def _task_fixture(tmp_path, monkeypatch):
    workspace = tmp_path / "task"
    workspace.mkdir()
    files_db = workspace / "task_files.db"
    conn = sqlite3.connect(files_db)
    conn.execute("CREATE TABLE files (path TEXT)")
    known = workspace / "known.xlsx"
    known.write_bytes(b"not-real-xlsx")
    conn.execute("INSERT INTO files VALUES (?)", (str(known),))
    conn.commit()
    conn.close()

    class Backend:
        async def get_task(self, task_id):
            if task_id != "task-1":
                return None
            return {
                "id": task_id,
                "output_files_db": str(files_db),
                "extraction_directory": str(workspace / "extracted"),
            }

    class Manager:
        cpp_backend = Backend()

    monkeypatch.setattr(
        "httpserver.services.get_service_manager", lambda: Manager()
    )
    return workspace, files_db, known


@pytest.mark.asyncio
async def test_office_known_task_file_passes_membership_gate(tmp_path, monkeypatch):
    workspace, _, known = _task_fixture(tmp_path, monkeypatch)

    class Service:
        async def parse_file(self, path):
            return "# parsed"

    monkeypatch.setattr(office, "get_office_service", lambda: Service())
    response = await office.parse_office_file(
        office.ParseRequest(task_id="task-1", file_path=str(known))
    )
    assert response.success is True
    assert response.content == "# parsed"


@pytest.mark.asyncio
async def test_office_unknown_file_in_task_workspace_rejected(tmp_path, monkeypatch):
    workspace, _, _ = _task_fixture(tmp_path, monkeypatch)
    unknown = workspace / "unknown.xlsx"
    unknown.write_bytes(b"not-real-xlsx")

    with pytest.raises(HTTPException) as excinfo:
        await office.parse_office_file(
            office.ParseRequest(task_id="task-1", file_path=str(unknown))
        )
    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "file is not part of the current task"


@pytest.mark.asyncio
async def test_office_other_task_file_rejected(tmp_path, monkeypatch):
    workspace, _, _ = _task_fixture(tmp_path, monkeypatch)
    other = tmp_path / "other-task.xlsx"
    other.write_bytes(b"not-real-xlsx")

    with pytest.raises(HTTPException) as excinfo:
        await office.parse_office_file(
            office.ParseRequest(task_id="task-1", file_path=str(other))
        )
    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "file is not part of the current task"


@pytest.mark.asyncio
async def test_office_missing_task_is_opaque_not_found(tmp_path, monkeypatch):
    _task_fixture(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as excinfo:
        await office.parse_office_file(
            office.ParseRequest(task_id="missing", file_path="/tmp/a.xlsx")
        )
    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "task not found"
