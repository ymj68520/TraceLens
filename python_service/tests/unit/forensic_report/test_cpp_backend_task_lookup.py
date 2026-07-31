from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from httpserver.services.cpp_backend import CppBackendService


@pytest.mark.asyncio
async def test_get_task_uses_direct_lookup_without_first_page_limit():
    service = CppBackendService(SimpleNamespace(cpp_backend_url="http://example.test"))
    service._request = AsyncMock(
        return_value={"id": "task-1001", "image_path": "/evidence/1001.E01"}
    )

    task = await service.get_task("task-1001")

    assert task["id"] == "task-1001"
    assert task["image_name"] == "/evidence/1001.E01"
    service._request.assert_awaited_once_with("GET", "/api/tasks/task-1001")


@pytest.mark.asyncio
async def test_get_task_encodes_confusing_id_as_one_path_segment():
    requested_urls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(request.url)
        return httpx.Response(404, json={"error": "Task not found"})

    service = CppBackendService(SimpleNamespace(cpp_backend_url="http://example.test"))
    service._client = httpx.AsyncClient(
        base_url=service.base_url,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await service.get_task("../health") is None
    finally:
        await service.shutdown()

    assert requested_urls[0].raw_path == b"/api/tasks/..%2Fhealth"


@pytest.mark.asyncio
@pytest.mark.parametrize("task_id", [".", ".."])
async def test_get_task_rejects_pure_dot_segments_without_requesting(task_id: str):
    requested_urls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(request.url)
        return httpx.Response(200, json={"id": task_id})

    service = CppBackendService(SimpleNamespace(cpp_backend_url="http://example.test"))
    service._client = httpx.AsyncClient(
        base_url=service.base_url,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await service.get_task(task_id) is None
    finally:
        await service.shutdown()

    assert requested_urls == []


@pytest.mark.asyncio
async def test_get_task_rejects_successful_non_task_or_mismatched_id_response():
    service = CppBackendService(SimpleNamespace(cpp_backend_url="http://example.test"))
    service._request = AsyncMock(side_effect=[{"status": "ok"}, {"id": "other-task"}])

    assert await service.get_task("../health") is None
    assert await service.get_task("expected-task") is None


@pytest.mark.asyncio
async def test_get_task_returns_none_for_direct_lookup_404():
    service = CppBackendService(SimpleNamespace(cpp_backend_url="http://example.test"))
    service._request = AsyncMock(
        return_value={"success": False, "error": "Task not found", "status": 404}
    )

    assert await service.get_task("missing") is None
