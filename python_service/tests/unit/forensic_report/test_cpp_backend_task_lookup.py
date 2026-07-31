from types import SimpleNamespace
from unittest.mock import AsyncMock

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
async def test_get_task_returns_none_for_direct_lookup_404():
    service = CppBackendService(SimpleNamespace(cpp_backend_url="http://example.test"))
    service._request = AsyncMock(
        return_value={"success": False, "error": "Task not found", "status": 404}
    )

    assert await service.get_task("missing") is None
