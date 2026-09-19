"""Startup reconciliation for combined-case cross-image jobs.

The multi-image job registry is in-memory; when the Python service restarts,
cases persisted as ANALYSING in the C++ backend would stay stuck forever with
every recovery action hidden. reconcile_orphan_analysis() converges those
orphans to FAILED at startup, skipping jobs this process still tracks.
"""

from __future__ import annotations

import httpx
import pytest

from httpserver.config import Settings
from httpserver.routes.multi_analysis import _jobs, reconcile_orphan_analysis


class _FakeRouter:
    """Minimal httpx.AsyncClient stand-in recording status PUTs."""

    def __init__(self, cases):
        self._cases = cases
        self.status_puts: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        if url.endswith("/api/cases"):
            return _Resp({"cases": self._cases})
        return _Resp({}, 404)

    async def put(self, url, json=None):
        if "/status" in url:
            case_id = url.rsplit("/", 2)[-2]
            self.status_puts.append((case_id, json or {}))
            return _Resp({"success": True})
        return _Resp({}, 404)


class _Resp:
    def __init__(self, payload, code=200):
        self._payload = payload
        self.code = code

    def raise_for_status(self):
        if self.code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._payload


@pytest.fixture
def fake_client(monkeypatch):
    holder = {}

    def _install(cases):
        router = _FakeRouter(cases)
        holder["router"] = router
        monkeypatch.setattr(
            "httpserver.routes.multi_analysis.httpx.AsyncClient",
            lambda timeout=5: router,
        )
        return router

    yield _install
    _jobs.clear()


@pytest.mark.unit
def test_reconciles_orphaned_analysing_case(fake_client):
    router = fake_client([
        {"id": "case-1", "name": "孤儿案件", "status": "analysing",
         "cross_analysis_job_id": "job-dead"},
        {"id": "case-2", "name": "正常", "status": "open",
         "cross_analysis_job_id": ""},
    ])

    reconciled = _run(reconcile_orphan_analysis(Settings()))

    assert reconciled == 1
    assert router.status_puts == [("case-1", {"status": "failed"})]


@pytest.mark.unit
def test_skips_live_running_job(fake_client):
    _jobs["job-live"] = {"job_id": "job-live", "status": "running"}
    router = fake_client([
        {"id": "case-live", "name": "进行中", "status": "analysing",
         "cross_analysis_job_id": "job-live"},
    ])

    reconciled = _run(reconcile_orphan_analysis(Settings()))

    assert reconciled == 0
    assert router.status_puts == []


@pytest.mark.unit
def test_skips_non_analysing_status(fake_client):
    router = fake_client([
        {"id": "case-done", "name": "完成", "status": "completed",
         "cross_analysis_job_id": "job-x"},
    ])

    assert _run(reconcile_orphan_analysis(Settings())) == 0
    assert router.status_puts == []


@pytest.mark.unit
def test_backend_unreachable_returns_zero(fake_client, monkeypatch):
    def _boom(timeout=5):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(
        "httpserver.routes.multi_analysis.httpx.AsyncClient", _boom
    )

    assert _run(reconcile_orphan_analysis(Settings())) == 0


def _run(coro):
    import asyncio
    return asyncio.run(coro)
