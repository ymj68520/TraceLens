"""Phase D2b: standalone workspace and parameterized Windows severity checks."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException

from httpserver.routes import markitdown, office
from httpserver.services.windows_artifacts.windows_toon_exporter import (
    WindowsArtifactTOONExporter,
)


@pytest.mark.asyncio
async def test_markitdown_standalone_workspace_adapter_is_contained(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source_root = workspace / "input"
    output = workspace / "text"
    source_root.mkdir()
    source = source_root / "input.txt"
    source.write_text("standalone")

    locator = type("Locator", (), {"get_extractor": lambda self, path: None})()
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)

    response = await markitdown.convert_one(
        markitdown.ConvertOneRequest(
            workspace_root=str(workspace),
            input_root=str(source_root),
            input_file=str(source),
            output_root=str(output),
        )
    )
    assert response.status == "converted"
    assert (output / "input.txt.md").read_text() == "# input.txt\n\n```\nstandalone\n```\n"


@pytest.mark.asyncio
async def test_markitdown_standalone_outside_workspace_rejected(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "input.txt"
    source.write_text("outside")

    with pytest.raises(HTTPException) as excinfo:
        await markitdown.convert_one(
            markitdown.ConvertOneRequest(
                workspace_root=str(workspace),
                input_root=str(outside),
                input_file=str(source),
                output_root=str(workspace / "out"),
            )
        )
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_office_standalone_workspace_adapter_is_contained(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "sheet.xlsx"
    source.write_bytes(b"placeholder")

    class Service:
        async def parse_file(self, path):
            return "parsed"

    monkeypatch.setattr(office, "get_office_service", lambda: Service())
    response = await office.parse_office_file(
        office.ParseRequest(workspace_root=str(workspace), file_path=str(source))
    )
    assert response.success is True
    assert response.content == "parsed"


def test_windows_severity_is_bound_as_value(tmp_path):
    db = tmp_path / "windows.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE browser_history (id INTEGER PRIMARY KEY, url TEXT, title TEXT, visit_count INTEGER, last_visit TEXT, browser_name TEXT)"
    )
    conn.execute(
        "CREATE TABLE windows_artifact_descriptions (artifact_type TEXT, artifact_id INTEGER, summary TEXT, keywords TEXT, severity TEXT, description TEXT, relevance INTEGER)"
    )
    conn.execute(
        "INSERT INTO browser_history VALUES (1, 'https://a', 'A', 1, 'now', 'browser')"
    )
    conn.execute(
        "INSERT INTO windows_artifact_descriptions VALUES ('browser_history', 1, 'safe', 'k', 'low', 'd', 1)"
    )
    conn.commit()
    conn.close()

    exporter = WindowsArtifactTOONExporter()
    low = exporter.export_artifacts_toon(
        str(db), artifact_type="browser_history", severity="low"
    )
    injected = exporter.export_artifacts_toon(
        str(db), artifact_type="browser_history", severity="low' OR 1=1 --"
    )
    assert "# records[1]" in low
    assert "# No 浏览器历史 found" in injected
