"""Interactive analyze routes auto-extract missing files before analysis.

The Files page "AI 分析" button must work on files that were never extracted
from the image: /api/llm/analyze and /api/llm/analyze/dll start a single-file
C++ extraction job, wait for it, then run the unchanged analysis chain. When
extraction cannot produce the file, the routes fail closed with 404.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from httpserver.config import Settings
from httpserver.services.llm.llm_service import LLMService


def _make_task_files_db(path: Path, rows) -> Path:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE files (
            id INTEGER PRIMARY KEY, path TEXT, name TEXT, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT)"""
    )
    for row in rows:
        conn.execute("INSERT INTO files(path, name) VALUES (?,?)", (row, Path(row).name))
    conn.commit()
    conn.close()
    return path


def _llm_description_of(db: Path, file_path: str):
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT llm_description FROM files WHERE path = ?", (file_path,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


class _FakeCppBackend:
    """get_task plus a scripted extraction job.

    ``materialize`` runs when the job is polled, simulating the C++ extractor
    writing the file under the task extraction directory.
    """

    def __init__(self, tasks, materialize=None, job_status="completed",
                 start_error=None, status_error=None):
        self._tasks = tasks
        self._materialize = materialize
        self._job_status = job_status
        self._start_error = start_error
        self._status_error = status_error
        self.extract_calls = []

    async def get_task(self, task_id):
        return self._tasks.get(task_id)

    async def extract_files(self, task_id, file_paths, output_dir=None, overwrite=False):
        self.extract_calls.append({
            "task_id": task_id,
            "file_paths": list(file_paths),
            "output_dir": output_dir,
            "overwrite": overwrite,
        })
        if self._start_error:
            return {"success": False, "error": self._start_error}
        return {"job_id": "job-1"}

    async def get_extraction_status(self, job_id):
        if self._status_error:
            return {"success": False, "error": self._status_error}
        if self._job_status == "completed" and self._materialize:
            self._materialize()
        return {"status": self._job_status, "extracted_files": 1,
                "error_details": "boom" if self._job_status == "failed" else ""}


class _FakeServiceManager:
    def __init__(self, tasks, llm_service, cpp_backend):
        self.cpp_backend = cpp_backend
        self.llm_service = llm_service


def _fake_llm_service():
    """Real persist_to_files_db, fake LLM call and text read."""
    service = LLMService.__new__(LLMService)

    async def fake_analyze(**kwargs):
        return {
            "analysis": {
                "description": "auto-extract injected description",
                "summary": "auto-extract summary",
                "keywords": ["k1"],
            },
            "model": "test-model",
            "tokens_used": 1,
        }

    async def fake_read_file_content(file_path):
        return Path(file_path).read_text(encoding="utf-8", errors="replace")

    service.analyze = fake_analyze
    service.read_file_content = fake_read_file_content
    return service


@pytest.fixture
def unextracted_task(tmp_path, monkeypatch):
    """Task A with /evidence/secret.txt present in files.db but not on host."""
    ws = tmp_path / "taskA"
    ws.mkdir()
    db = _make_task_files_db(ws / "a_files.db", ["/evidence/secret.txt"])
    tasks = {
        "A": {
            "id": "A",
            "output_files_db": str(db),
            "extraction_directory": str(ws),
        },
    }
    backend = _FakeCppBackend(tasks)
    sm = _FakeServiceManager(tasks, _fake_llm_service(), backend)
    monkeypatch.setattr("httpserver.services.get_service_manager", lambda: sm)
    return {"ws": ws, "db": db, "sm": sm, "backend": backend}


# ------------------------------------------------------ /api/llm/analyze


@pytest.mark.asyncio
async def test_analyze_auto_extracts_missing_file(unextracted_task):
    from httpserver.routes.llm_endpoints import _analysis
    from httpserver.routes.llm_models import AnalyzeRequest

    ws, db = unextracted_task["ws"], unextracted_task["db"]
    assert not (ws / "evidence" / "secret.txt").exists()

    def materialize():
        target = ws / "evidence" / "secret.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("secret content")

    unextracted_task["backend"]._materialize = materialize

    request = AnalyzeRequest(
        task_id="A",
        file_path="/evidence/secret.txt",
        db_file_path="/evidence/secret.txt",
    )
    response = await _analysis.analyze_content(request, Settings(_env_file=None))

    assert response.success
    calls = unextracted_task["backend"].extract_calls
    assert calls == [{
        "task_id": "A",
        "file_paths": ["/evidence/secret.txt"],
        "output_dir": "extracted_files",
        "overwrite": False,
    }]
    assert _llm_description_of(db, "/evidence/secret.txt") == (
        "auto-extract injected description"
    )


@pytest.mark.asyncio
async def test_analyze_converts_host_path_back_to_image_path(unextracted_task):
    """A path already prefixed with the extraction dir still extracts."""
    from httpserver.routes.llm_endpoints import _analysis
    from httpserver.routes.llm_models import AnalyzeRequest

    ws = unextracted_task["ws"]

    def materialize():
        target = ws / "evidence" / "secret.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("secret content")

    unextracted_task["backend"]._materialize = materialize

    request = AnalyzeRequest(
        task_id="A",
        file_path=str(ws / "evidence" / "secret.txt"),
        db_file_path="/evidence/secret.txt",
    )
    response = await _analysis.analyze_content(request, Settings(_env_file=None))

    assert response.success
    assert unextracted_task["backend"].extract_calls[0]["file_paths"] == [
        "/evidence/secret.txt"
    ]


@pytest.mark.asyncio
async def test_analyze_extraction_job_failure_fails_closed(unextracted_task):
    from httpserver.routes.llm_endpoints import _analysis
    from httpserver.routes.llm_models import AnalyzeRequest

    unextracted_task["backend"]._job_status = "failed"

    request = AnalyzeRequest(
        task_id="A",
        file_path="/evidence/secret.txt",
        db_file_path="/evidence/secret.txt",
    )
    with pytest.raises(HTTPException) as excinfo:
        await _analysis.analyze_content(request, Settings(_env_file=None))
    assert excinfo.value.status_code == 404
    assert "Automatic extraction" in excinfo.value.detail
    assert unextracted_task["backend"].extract_calls


@pytest.mark.asyncio
async def test_analyze_extraction_completed_but_file_still_missing(unextracted_task):
    from httpserver.routes.llm_endpoints import _analysis
    from httpserver.routes.llm_models import AnalyzeRequest

    # Job reports completed but never writes the file (pattern matched nothing).
    request = AnalyzeRequest(
        task_id="A",
        file_path="/evidence/secret.txt",
        db_file_path="/evidence/secret.txt",
    )
    with pytest.raises(HTTPException) as excinfo:
        await _analysis.analyze_content(request, Settings(_env_file=None))
    assert excinfo.value.status_code == 404
    assert "Automatic extraction" in excinfo.value.detail


@pytest.mark.asyncio
async def test_analyze_extraction_start_refused_fails_closed(unextracted_task):
    from httpserver.routes.llm_endpoints import _analysis
    from httpserver.routes.llm_models import AnalyzeRequest

    unextracted_task["backend"]._start_error = "task extraction inputs are not ready"

    request = AnalyzeRequest(
        task_id="A",
        file_path="/evidence/secret.txt",
        db_file_path="/evidence/secret.txt",
    )
    with pytest.raises(HTTPException) as excinfo:
        await _analysis.analyze_content(request, Settings(_env_file=None))
    assert excinfo.value.status_code == 404
    assert "Automatic extraction" in excinfo.value.detail


@pytest.mark.asyncio
async def test_analyze_missing_file_without_task_id_skips_extraction(unextracted_task):
    from httpserver.routes.llm_endpoints import _analysis
    from httpserver.routes.llm_models import AnalyzeRequest

    request = AnalyzeRequest(file_path="/evidence/secret.txt")
    with pytest.raises(HTTPException) as excinfo:
        await _analysis.analyze_content(request, Settings(_env_file=None))
    assert excinfo.value.status_code == 404
    assert unextracted_task["backend"].extract_calls == []


# ------------------------------------------------------ helper units


def test_to_image_internal_path_variants():
    from httpserver.services.llm.auto_extractor import to_image_internal_path

    assert to_image_internal_path("/etc/motd", "/data/task/extracted_files") == "/etc/motd"
    assert to_image_internal_path(
        "/data/task/extracted_files/etc/motd", "/data/task/extracted_files"
    ) == "/etc/motd"
    assert to_image_internal_path("/other/place/file.txt", "/data/task/extracted_files") == (
        "/other/place/file.txt"
    )
    assert to_image_internal_path("/etc/motd", "") == "/etc/motd"


@pytest.mark.asyncio
async def test_ensure_extracted_rejects_traversal(unextracted_task):
    from httpserver.services.llm.auto_extractor import (
        AutoExtractionError,
        ensure_extracted_for_analysis,
    )

    with pytest.raises(AutoExtractionError):
        await ensure_extracted_for_analysis(
            unextracted_task["backend"],
            task_id="A",
            file_path="/../secret.txt",
            extraction_dir=str(unextracted_task["ws"]),
        )
    assert unextracted_task["backend"].extract_calls == []


# ------------------------------------------------------ /api/llm/analyze/dll


@pytest.mark.asyncio
async def test_dll_auto_extracts_missing_file(unextracted_task, monkeypatch):
    from httpserver.routes import dll as dll_routes

    ws, db = unextracted_task["ws"], unextracted_task["db"]

    def materialize():
        target = ws / "evidence" / "evil.dll"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"MZ evil")

    unextracted_task["backend"]._materialize = materialize

    class FakeDLLClient:
        def __init__(self, url):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def analyze_dll(self, file_path):
            assert file_path == str(ws / "evidence" / "evil.dll")
            return {"threat_score": 10, "file_path": file_path}

    monkeypatch.setattr(dll_routes, "DLLAnalyzerClient", FakeDLLClient)
    monkeypatch.setattr(
        dll_routes, "get_service_manager", lambda: unextracted_task["sm"]
    )

    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO files(path, name) VALUES (?,?)", ("/evidence/evil.dll", "evil.dll"))
    conn.commit()
    conn.close()

    request = dll_routes.DLLAnalysisRequest(
        task_id="A", file_path="/evidence/evil.dll"
    )
    response = await dll_routes.analyze_dll(request, Settings(_env_file=None))

    assert response.success
    assert unextracted_task["backend"].extract_calls[0]["file_paths"] == [
        "/evidence/evil.dll"
    ]
    assert _llm_description_of(db, "/evidence/evil.dll")


@pytest.mark.asyncio
async def test_dll_auto_extraction_failure_returns_404(unextracted_task, monkeypatch):
    from httpserver.routes import dll as dll_routes

    unextracted_task["backend"]._start_error = "task extraction inputs are not ready"

    class FakeDLLClient:
        def __init__(self, url):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def analyze_dll(self, file_path):
            raise AssertionError("C++ parser must not be reached when extraction failed")

    monkeypatch.setattr(dll_routes, "DLLAnalyzerClient", FakeDLLClient)
    monkeypatch.setattr(
        dll_routes, "get_service_manager", lambda: unextracted_task["sm"]
    )

    request = dll_routes.DLLAnalysisRequest(
        task_id="A", file_path="/evidence/never.dll"
    )
    with pytest.raises(HTTPException) as excinfo:
        await dll_routes.analyze_dll(request, Settings(_env_file=None))
    assert excinfo.value.status_code == 404
    assert "Automatic extraction" in excinfo.value.detail
