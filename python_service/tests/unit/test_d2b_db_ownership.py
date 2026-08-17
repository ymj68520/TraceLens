"""Phase D2b: HTTP task mode persistence is bound to the task-owned files.db.

The §28 matrix: task A + task B stores; a request may never redirect the
persistence target to another task's database, and the legacy files_db_path
field is an exact-validated hint only. Also covers the removal of the dead
/api/db/query proxy.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from httpserver.config import Settings
from httpserver.services.llm.llm_service import LLMService


def _make_task_files_db(path: Path, rows) -> Path:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE files (
            id INTEGER PRIMARY KEY, path TEXT, name TEXT,
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


def _bytes_of(db: Path) -> bytes:
    return db.read_bytes()


class _RecordingCppBackend:
    def __init__(self, tasks):
        self._tasks = tasks

    async def get_task(self, task_id):
        return self._tasks.get(task_id)


class _FakeServiceManager:
    def __init__(self, tasks, llm_service):
        self.cpp_backend = _RecordingCppBackend(tasks)
        self.llm_service = llm_service


def _fake_llm_service():
    """Real persist_to_files_db, fake LLM call."""
    service = LLMService.__new__(LLMService)

    async def fake_analyze(**kwargs):
        return {
            "analysis": {
                "description": "d2b injected description",
                "summary": "d2b summary",
                "keywords": ["k1"],
            },
            "model": "test-model",
            "tokens_used": 1,
        }

    service.analyze = fake_analyze
    return service


@pytest.fixture
def two_task_stores(tmp_path, monkeypatch):
    ws_a = tmp_path / "taskA"
    ws_b = tmp_path / "taskB"
    ws_a.mkdir()
    ws_b.mkdir()
    source_a = ws_a / "shared.txt"
    source_b = ws_b / "shared.txt"
    source_a.write_text("task A evidence")
    source_b.write_text("task B evidence")
    dll_a = ws_a / "sample.dll"
    dll_a.write_bytes(b"MZ task A")
    db_a = _make_task_files_db(
        ws_a / "a_files.db", ["/evidence/shared.txt", str(dll_a)]
    )
    db_b = _make_task_files_db(
        ws_b / "b_files.db", ["/evidence/shared.txt", str(dll_a)]
    )
    tasks = {
        "A": {
            "id": "A",
            "output_files_db": str(db_a),
            "extraction_directory": str(ws_a),
        },
        "B": {
            "id": "B",
            "output_files_db": str(db_b),
            "extraction_directory": str(ws_b),
        },
    }
    service_manager = _FakeServiceManager(tasks, _fake_llm_service())
    monkeypatch.setattr(
        "httpserver.services.get_service_manager", lambda: service_manager
    )
    return {"A": db_a, "B": db_b, "sm": service_manager}


# ------------------------------------------------------ /api/llm/analyze


@pytest.mark.asyncio
async def test_analyze_rejects_other_task_db_and_touches_nothing(two_task_stores):
    from httpserver.routes.llm_endpoints import _analysis
    from httpserver.routes.llm_models import AnalyzeRequest

    db_a, db_b = two_task_stores["A"], two_task_stores["B"]
    before_a, before_b = _bytes_of(db_a), _bytes_of(db_b)

    shared_a = str(Path(two_task_stores["A"].parent) / "shared.txt")
    request = AnalyzeRequest(
        task_id="A",
        file_path=shared_a,
        files_db_path=str(db_b),
    )
    with pytest.raises(HTTPException) as excinfo:
        await _analysis.analyze_content(request, Settings(_env_file=None))
    assert excinfo.value.status_code == 400
    assert _bytes_of(db_a) == before_a
    assert _bytes_of(db_b) == before_b


@pytest.mark.asyncio
async def test_analyze_legacy_path_matching_task_passes(two_task_stores):
    from httpserver.routes.llm_endpoints import _analysis
    from httpserver.routes.llm_models import AnalyzeRequest

    db_a = two_task_stores["A"]
    shared_a = str(db_a.parent / "shared.txt")
    request = AnalyzeRequest(
        task_id="A",
        file_path=shared_a,
        db_file_path="/evidence/shared.txt",
        files_db_path=str(db_a),
    )
    response = await _analysis.analyze_content(request, Settings(_env_file=None))
    assert response.success
    assert _llm_description_of(db_a, "/evidence/shared.txt") == (
        "d2b injected description"
    )


@pytest.mark.asyncio
async def test_analyze_without_legacy_path_uses_trusted_store(two_task_stores):
    from httpserver.routes.llm_endpoints import _analysis
    from httpserver.routes.llm_models import AnalyzeRequest

    db_a = two_task_stores["A"]
    shared_a = str(db_a.parent / "shared.txt")
    request = AnalyzeRequest(task_id="A", file_path=shared_a, db_file_path="/evidence/shared.txt")
    response = await _analysis.analyze_content(request, Settings(_env_file=None))
    assert response.success
    assert _llm_description_of(db_a, "/evidence/shared.txt") == (
        "d2b injected description"
    )


@pytest.mark.asyncio
async def test_analyze_legacy_path_without_task_id_rejected(two_task_stores):
    from httpserver.routes.llm_endpoints import _analysis
    from httpserver.routes.llm_models import AnalyzeRequest

    db_a = two_task_stores["A"]
    shared_a = str(db_a.parent / "shared.txt")
    before_a = _bytes_of(db_a)
    request = AnalyzeRequest(
        file_path=shared_a,
        files_db_path=str(db_a),
    )
    with pytest.raises(HTTPException) as excinfo:
        await _analysis.analyze_content(request, Settings(_env_file=None))
    assert excinfo.value.status_code == 400
    assert "task_id is required" in excinfo.value.detail
    assert _bytes_of(db_a) == before_a


# ------------------------------------------------------ /api/llm/analyze/dll


@pytest.mark.asyncio
async def test_dll_persistence_bound_to_task_store(two_task_stores, monkeypatch, tmp_path):
    from httpserver.routes import dll as dll_routes

    db_a, db_b = two_task_stores["A"], two_task_stores["B"]

    dll_file = db_a.parent / "sample.dll"
    assert dll_file.is_file()

    class FakeDLLClient:
        def __init__(self, url):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def analyze_dll(self, file_path):
            return {"threat_score": 10, "file_path": file_path}

    monkeypatch.setattr(dll_routes, "DLLAnalyzerClient", FakeDLLClient)
    monkeypatch.setattr(
        dll_routes, "get_service_manager", lambda: two_task_stores["sm"]
    )

    # Cross-task hint rejected, both stores untouched.
    before_b = _bytes_of(db_b)
    request = dll_routes.DLLAnalysisRequest(
        task_id="A", file_path=str(dll_file), files_db_path=str(db_b)
    )
    with pytest.raises(HTTPException) as excinfo:
        await dll_routes.analyze_dll(request, Settings(_env_file=None))
    assert excinfo.value.status_code == 400
    assert _bytes_of(db_b) == before_b

    # Task-owned hint passes and persists into A only.
    request = dll_routes.DLLAnalysisRequest(
        task_id="A", file_path=str(dll_file), files_db_path=str(db_a)
    )
    response = await dll_routes.analyze_dll(request, Settings(_env_file=None))
    assert response.success
    assert _llm_description_of(db_a, str(dll_file)) == "d2b injected description"
    assert _llm_description_of(db_b, str(dll_file)) is None


# ----------------------------------------------- /api/llm/case-analysis (Chain B)


@pytest.mark.asyncio
async def test_case_analysis_requires_explicit_task_id(two_task_stores):
    from httpserver.routes.case_analysis_models import CaseAnalysisRequest

    # task_id is now a required field — the path→task_id regex is gone.
    with pytest.raises(ValidationError):
        CaseAnalysisRequest(files_db_path=str(two_task_stores["A"]))


@pytest.mark.asyncio
async def test_case_analysis_unknown_task_rejected_even_with_valid_path(
    two_task_stores, monkeypatch
):
    from httpserver.routes.case_analysis_endpoints import _case

    db_a = two_task_stores["A"]
    # Old behaviour: task identity regex-extracted from the path. Now the
    # explicit unknown task wins -> 404, no job spawned.
    recorded = []
    monkeypatch.setattr(_case, "_run_case_analysis_background", recorded.append)
    monkeypatch.setattr(
        _case,
        "_get_case_analysis_service",
        lambda sm: object(),
    )
    request = _case.CaseAnalysisRequest(task_id="ghost", files_db_path=str(db_a))
    with pytest.raises(HTTPException) as excinfo:
        await _case.start_case_analysis(request, Settings(_env_file=None))
    assert excinfo.value.status_code == 404
    assert recorded == []


@pytest.mark.asyncio
async def test_case_analysis_background_receives_trusted_store(
    two_task_stores, monkeypatch
):
    from httpserver.routes.case_analysis_endpoints import _case

    db_a = two_task_stores["A"]
    recorded = []

    async def recorder(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(_case, "_run_case_analysis_background", recorder)
    monkeypatch.setattr(_case, "_get_case_analysis_service", lambda sm: object())

    request = _case.CaseAnalysisRequest(task_id="A", files_db_path=str(db_a))
    response = await _case.start_case_analysis(request, Settings(_env_file=None))
    await asyncio.sleep(0)
    assert response.task_id == "A"
    assert recorded[0]["files_db_path"] == str(db_a)

    # No legacy path at all -> trusted resolution still feeds the pipeline.
    recorded.clear()
    request = _case.CaseAnalysisRequest(task_id="A")
    await _case.start_case_analysis(request, Settings(_env_file=None))
    await asyncio.sleep(0)
    assert recorded[0]["files_db_path"] == str(db_a)


@pytest.mark.asyncio
async def test_case_analysis_rejects_cross_task_path(two_task_stores, monkeypatch):
    from httpserver.routes.case_analysis_endpoints import _case

    db_b = two_task_stores["B"]
    recorded = []
    monkeypatch.setattr(_case, "_run_case_analysis_background", recorded.append)
    monkeypatch.setattr(_case, "_get_case_analysis_service", lambda sm: object())

    request = _case.CaseAnalysisRequest(task_id="A", files_db_path=str(db_b))
    with pytest.raises(HTTPException) as excinfo:
        await _case.start_case_analysis(request, Settings(_env_file=None))
    assert excinfo.value.status_code == 400
    assert recorded == []


# ------------------------------------------------------ /api/llm/reanalyze-files


@pytest.mark.asyncio
async def test_reanalyze_persistence_bound_to_task_store(two_task_stores, monkeypatch):
    from httpserver.routes.case_analysis_endpoints import _case

    db_a, db_b = two_task_stores["A"], two_task_stores["B"]
    recorded = []

    async def recorder(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(_case, "_run_reanalyze_background", recorder)
    monkeypatch.setattr(_case, "_get_case_analysis_service", lambda sm: object())

    request = _case.ReanalyzeRequest(
        task_id="A",
        file_paths=["/evidence/shared.txt"],
        user_hint="hint",
        files_db_path=str(db_b),
    )
    with pytest.raises(HTTPException) as excinfo:
        await _case.reanalyze_files(request, Settings(_env_file=None))
    assert excinfo.value.status_code == 400
    assert recorded == []

    request = _case.ReanalyzeRequest(
        task_id="A",
        file_paths=["/evidence/shared.txt"],
        user_hint="hint",
    )
    await _case.reanalyze_files(request, Settings(_env_file=None))
    await asyncio.sleep(0)
    assert recorded[0]["files_db_path"] == str(db_a)


# ------------------------------------------------------ multi-image analysis


@pytest.mark.asyncio
async def test_multi_image_resolves_each_task_pair(two_task_stores, monkeypatch):
    from httpserver.routes import multi_analysis

    db_a, db_b = two_task_stores["A"], two_task_stores["B"]
    recorded = {}

    class FakeSvc:
        async def run_multi_image_analysis(self, **kwargs):
            recorded.update(kwargs)
            return {"ok": True}

    monkeypatch.setattr(multi_analysis, "get_case_analysis_service", lambda: FakeSvc())

    request = multi_analysis.MultiImageAnalysisRequest(
        case_id="case-1",
        task_ids=["A", "B"],
        files_db_paths=[str(db_a), str(db_b)],
        case_description="desc",
    )
    await multi_analysis.start_multi_image_analysis(
        request, Settings(_env_file=None)
    )
    await asyncio.sleep(0)
    assert recorded["files_db_paths"] == [str(db_a), str(db_b)]

    # Swapped pair: task A with task B's db -> rejected before any run.
    with pytest.raises(HTTPException) as excinfo:
        request = multi_analysis.MultiImageAnalysisRequest(
            case_id="case-1",
            task_ids=["A", "B"],
            files_db_paths=[str(db_b), str(db_a)],
            case_description="desc",
        )
        await multi_analysis.start_multi_image_analysis(
            request, Settings(_env_file=None)
        )
    assert excinfo.value.status_code == 400


# ------------------------------------------------------ dead /api/db/query removal


def test_db_query_proxy_removed_from_app_and_client():
    from httpserver.main import create_app
    from httpserver.services.cpp_backend import CppBackendService

    # Route registration is owned by the application factory; this unit test
    # only asserts the deleted API has no request model or client forwarding
    # method left behind.
    from httpserver.routes import database
    assert not hasattr(database, "QueryRequest")
    assert not hasattr(CppBackendService, "execute_query")
