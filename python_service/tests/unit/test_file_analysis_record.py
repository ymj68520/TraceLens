"""POST /api/file-analysis/record — pipeline three-write entry (SPEC E).

The C++ pipeline posts each analysis here; the Python three-write
(``file_analyses`` truth row + display cache + file_descriptions) must run with
``trigger_source="pipeline"``. Bad task targets fail closed (404), persistence
failures surface as 500.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes.file_analysis import router


class _FakeBackend:
    def __init__(self, task):
        self._task = task

    async def get_task(self, task_id):
        return self._task


class _FakeLlm:
    """Records persist_to_files_db calls; signature mirrors LLMService."""

    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def persist_to_files_db(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class _FakeServices:
    def __init__(self, task, llm):
        self.cpp_backend = task
        self.llm_service = llm


@pytest.fixture()
def files_db(tmp_path):
    path = tmp_path / "files.db"
    path.write_text("")  # existence is all the endpoint checks
    return str(path)


@pytest.fixture()
def api(monkeypatch, files_db):
    fake_llm = _FakeLlm()
    fake_services = _FakeServices(
        _FakeBackend({"id": "98b650a0", "output_files_db": files_db}), fake_llm
    )
    monkeypatch.setattr(
        "httpserver.services.get_service_manager", lambda: fake_services
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    # No `with`: entering the TestClient context runs the app lifespan, which
    # initializes real services and installs the process-global episode gate —
    # none of which this route contract needs.
    client = TestClient(app)
    # Expose the fakes for per-test assertions.
    client.fake_llm = fake_llm
    client.fake_services = fake_services
    yield client


def _payload(**overrides):
    body = {
        "task_id": "98b650a0",
        "file_path": "/etc/motd",
        "description": "MESSAGE OF THE DAY file.",
        "summary": "motd",
        "keywords": "linux, motd",
        "model_used": "nvidia/nemotron-3-nano-omni",
        "extraction_method": "raw_text",
    }
    body.update(overrides)
    return body


def test_record_runs_three_write_with_pipeline_source(api):
    resp = api.post("/api/file-analysis/record", json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["persisted"] is True
    assert body["trigger_source"] == "pipeline"

    args = api.fake_llm.calls[0][0]
    assert args[0] == api.fake_services.cpp_backend._task["output_files_db"]
    assert args[1] == "/etc/motd"
    assert args[6] == "98b650a0"  # task_id
    assert args[7] == "pipeline"  # trigger_source
    assert args[8] == "raw_text"  # extraction_method


def test_record_missing_task_404s(api, monkeypatch):
    api.fake_services.cpp_backend = _FakeBackend(None)
    resp = api.post("/api/file-analysis/record", json=_payload())
    assert resp.status_code == 404


def test_record_task_without_db_400s(api, monkeypatch):
    api.fake_services.cpp_backend = _FakeBackend({"id": "t", "output_files_db": ""})
    resp = api.post("/api/file-analysis/record", json=_payload())
    assert resp.status_code == 400


def test_record_persist_failure_500s(api):
    api.fake_llm.result = False
    resp = api.post("/api/file-analysis/record", json=_payload())
    assert resp.status_code == 500
