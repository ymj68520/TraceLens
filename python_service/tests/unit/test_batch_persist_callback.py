"""Tests for FileAnalyzer._run_batch_analysis persist-callback handling (A6 / A7).

Validates the S0-5 fix:
  A6  a synchronous persist_callback is NOT awaited (no TypeError)
  A7  a single batch file never ends up in BOTH results AND errors

Strategy: monkeypatch analyze_file to a stub returning a fixed result, stub the
document-extractor locator (so no real file is opened), and drive a synchronous
persist_callback directly. Calls _run_batch_analysis directly (not via
asyncio.create_task) for deterministic completion.
"""

from types import SimpleNamespace

import pytest

from httpserver.services.llm.file_analyzer import FileAnalyzer


def _make_analyzer() -> FileAnalyzer:
    # _run_batch_analysis touches no settings attributes once analyze_file and the
    # document extractor are stubbed; an empty SimpleNamespace is sufficient.
    return FileAnalyzer(SimpleNamespace())


def _stub_extractor(monkeypatch):
    class FakeExtractor:
        async def extract_to_markdown(self, path):
            return "fake content"

    class FakeLocator:
        def get_extractor(self, path):
            return FakeExtractor()

    import httpserver.services.document_extractor as de_mod
    monkeypatch.setattr(de_mod, "get_document_extractor_locator", lambda: FakeLocator())


def _stub_analyze(fa: FileAnalyzer):
    async def fake_analyze(content, text_client, vision_client, model_type="text", **kwargs):
        return {"analysis": {"description": "DESC"}, "model": "test-model"}

    fa.analyze_file = fake_analyze  # instance attribute shadows the bound method


def _seed_job(fa: FileAnalyzer, job_id: str, files):
    # Mirror what start_batch_analysis sets up before _run_batch_analysis runs.
    fa._jobs[job_id] = {
        "status": "running",
        "progress": 0.0,
        "files_processed": 0,
        "files_total": len(files),
        "results": [],
        "errors": [],
    }


@pytest.mark.asyncio
async def test_A6_A7_sync_callback_success(monkeypatch):
    fa = _make_analyzer()
    _stub_extractor(monkeypatch)
    _stub_analyze(fa)

    import unittest.mock as um
    files = [{"path": "/x/file.txt"}]
    _seed_job(fa, "job1", files)
    cb = um.MagicMock(return_value=True)  # synchronous callback returning bool

    await fa._run_batch_analysis(
        "job1", files, None, None, "text",
        None, None, cb,
    )

    status = fa._jobs["job1"]
    assert status["status"] == "completed"
    assert status["errors"] == []                       # A6: no TypeError leaked
    assert cb.call_count == 1
    result_paths = [r["file_path"] for r in status["results"]]
    assert "/x/file.txt" in result_paths               # A7: in results...


@pytest.mark.asyncio
async def test_A7_persist_failure_puts_file_in_errors_not_results(monkeypatch):
    fa = _make_analyzer()
    _stub_extractor(monkeypatch)
    _stub_analyze(fa)

    import unittest.mock as um
    files = [{"path": "/x/file.txt"}]
    _seed_job(fa, "job2", files)
    cb = um.MagicMock(return_value=False)  # persistence "failed"

    await fa._run_batch_analysis(
        "job2", files, None, None, "text",
        None, None, cb,
    )

    status = fa._jobs["job2"]
    assert status["status"] == "completed"
    assert cb.call_count == 1
    result_paths = [r["file_path"] for r in status["results"]]
    assert "/x/file.txt" not in result_paths           # A7: ...not in both
    assert any("/x/file.txt" in e for e in status["errors"])
