import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from httpserver.config import Settings
from httpserver.services.service_manager import ServiceManager


@pytest.mark.asyncio
async def test_report_service_is_rejected_while_cpp_backend_shutdown_is_pending(
    tmp_path: Path,
):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    backend_shutdown_started = asyncio.Event()
    release_backend_shutdown = asyncio.Event()

    async def shutdown_backend():
        backend_shutdown_started.set()
        await release_backend_shutdown.wait()

    backend = SimpleNamespace(shutdown=shutdown_backend)
    manager._cpp_backend = backend
    first_report_service = manager.forensic_report_service

    shutdown = asyncio.create_task(manager.shutdown())
    await backend_shutdown_started.wait()

    with pytest.raises(RuntimeError, match="shutting down"):
        manager.forensic_report_service
    assert manager._forensic_report_service is None

    release_backend_shutdown.set()
    await shutdown
    assert manager._forensic_report_service is None


@pytest.mark.asyncio
async def test_report_service_is_rejected_after_shutdown_until_reinitialize(
    tmp_path: Path,
):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    first_backend = SimpleNamespace(shutdown=AsyncMock())
    manager._cpp_backend = first_backend
    manager.forensic_report_service

    await manager.shutdown()

    with pytest.raises(RuntimeError, match="not initialized"):
        manager.forensic_report_service
    assert manager._forensic_report_service is None


@pytest.mark.asyncio
async def test_reinitialize_recreates_report_service_with_current_cpp_backend(
    tmp_path: Path,
):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    first_backend = SimpleNamespace(shutdown=AsyncMock())
    manager._cpp_backend = first_backend

    first_report_service = manager.forensic_report_service
    first_db_path = first_report_service.repository.db_path
    first_report_root = first_report_service.writer.report_root

    await manager.shutdown()

    second_backend = SimpleNamespace(initialize=AsyncMock(), shutdown=AsyncMock())
    with (
        patch(
            "httpserver.services.cpp_backend.CppBackendService",
            return_value=second_backend,
        ),
        patch("httpserver.services.graphiti_service.GraphitiService") as graphiti_type,
        patch("httpserver.services.llm_service.LLMService") as llm_type,
        patch(
            "httpserver.services.ingestion_job_manager.IngestionJobManager"
        ) as ingestion_type,
    ):
        graphiti_type.return_value.initialize = AsyncMock()
        llm_type.return_value.initialize = AsyncMock()
        ingestion_type.return_value.initialize = AsyncMock()

        await manager.initialize()

    second_report_service = manager.forensic_report_service
    assert second_report_service is not first_report_service
    assert second_report_service.resolver.cpp_backend is second_backend
    assert second_report_service.repository.db_path == first_db_path
    assert second_report_service.writer.report_root == first_report_root


@pytest.mark.asyncio
async def test_concurrent_shutdowns_share_one_manager_transition(tmp_path: Path):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)

    class Backend:
        def __init__(self):
            self.shutdown_calls = 0

        async def shutdown(self):
            self.shutdown_calls += 1
            await asyncio.sleep(0)

    backend = Backend()
    manager._cpp_backend = backend
    manager.forensic_report_service

    await asyncio.gather(manager.shutdown(), manager.shutdown())

    assert backend.shutdown_calls == 1
    assert manager._forensic_report_service is None


@pytest.mark.asyncio
async def test_cancelled_shutdown_completes_transition_and_allows_reinitialize(
    tmp_path: Path,
):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    backend_shutdown_started = asyncio.Event()
    release_backend_shutdown = asyncio.Event()

    async def shutdown_backend():
        backend_shutdown_started.set()
        await release_backend_shutdown.wait()

    first_backend = SimpleNamespace(shutdown=shutdown_backend)
    manager._cpp_backend = first_backend
    manager.forensic_report_service

    shutdown = asyncio.create_task(manager.shutdown())
    await backend_shutdown_started.wait()
    shutdown.cancel()
    with pytest.raises(asyncio.CancelledError):
        await shutdown

    with pytest.raises(RuntimeError, match="shutting down"):
        manager.forensic_report_service

    release_backend_shutdown.set()
    for _ in range(20):
        if manager._lifecycle_state == "stopped":
            break
        await asyncio.sleep(0)
    assert manager._lifecycle_state == "stopped"
    assert manager._forensic_report_service is None

    second_backend = SimpleNamespace(initialize=AsyncMock(), shutdown=AsyncMock())
    with (
        patch(
            "httpserver.services.cpp_backend.CppBackendService",
            return_value=second_backend,
        ),
        patch("httpserver.services.graphiti_service.GraphitiService") as graphiti_type,
        patch("httpserver.services.llm_service.LLMService") as llm_type,
        patch(
            "httpserver.services.ingestion_job_manager.IngestionJobManager"
        ) as ingestion_type,
    ):
        graphiti_type.return_value.initialize = AsyncMock()
        graphiti_type.return_value.shutdown = AsyncMock()
        llm_type.return_value.initialize = AsyncMock()
        llm_type.return_value.shutdown = AsyncMock()
        ingestion_type.return_value.initialize = AsyncMock()
        ingestion_type.return_value.shutdown = AsyncMock()
        await manager.initialize()

    assert manager.forensic_report_service.resolver.cpp_backend is second_backend
    await manager.shutdown()
    second_backend.shutdown.assert_awaited_once()
    with pytest.raises(RuntimeError, match="not initialized"):
        manager.forensic_report_service


@pytest.mark.asyncio
async def test_report_shutdown_failure_cannot_leave_a_reusable_service(tmp_path: Path):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    backend = SimpleNamespace(shutdown=AsyncMock())
    later_service = SimpleNamespace(shutdown=AsyncMock())
    manager._cpp_backend = backend
    manager._graphiti_service = later_service
    manager._forensic_report_service = SimpleNamespace(
        shutdown=AsyncMock(side_effect=RuntimeError("report shutdown failed"))
    )

    with pytest.raises(RuntimeError, match="report shutdown failed"):
        await manager.shutdown()

    assert manager._lifecycle_state == "stopped"
    assert manager._forensic_report_service is None
    backend.shutdown.assert_awaited_once()
    later_service.shutdown.assert_awaited_once()
    with pytest.raises(RuntimeError, match="not initialized"):
        manager.forensic_report_service
