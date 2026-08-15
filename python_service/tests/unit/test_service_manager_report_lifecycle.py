import asyncio
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from httpserver.config import Settings
from httpserver.services.service_manager import ServiceManager


class LifecycleService:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        initialize_gate: asyncio.Event | None = None,
        initialize_error: BaseException | None = None,
        shutdown_gate: asyncio.Event | None = None,
        shutdown_error: BaseException | None = None,
    ):
        self.name = name
        self.events = events
        self.initialize_gate = initialize_gate
        self.initialize_error = initialize_error
        self.shutdown_gate = shutdown_gate
        self.shutdown_error = shutdown_error
        self.initialize_started = asyncio.Event()
        self.shutdown_started = asyncio.Event()
        self.initialize_calls = 0
        self.shutdown_calls = 0

    async def initialize(self):
        self.initialize_calls += 1
        self.events.append(f"{self.name}.initialize")
        self.initialize_started.set()
        if self.initialize_gate is not None:
            await self.initialize_gate.wait()
        if self.initialize_error is not None:
            raise self.initialize_error

    async def shutdown(self):
        self.shutdown_calls += 1
        self.events.append(f"{self.name}.shutdown")
        self.shutdown_started.set()
        if self.shutdown_gate is not None:
            await self.shutdown_gate.wait()
        if self.shutdown_error is not None:
            raise self.shutdown_error

    async def close(self):
        await self.shutdown()


@contextmanager
def _patched_services(
    manager: ServiceManager,
    *,
    backend: LifecycleService,
    report: LifecycleService,
    graphiti: LifecycleService | None = None,
    llm: LifecycleService | None = None,
    ingestion: LifecycleService | None = None,
    migration: LifecycleService | None = None,
):
    events = backend.events
    graphiti = graphiti or LifecycleService("graphiti", events)
    llm = llm or LifecycleService("llm", events)
    ingestion = ingestion or LifecycleService("ingestion", events)
    migration = migration or LifecycleService("migration", events)
    with ExitStack() as stack:
        cpp_type = stack.enter_context(
            patch(
                "httpserver.services.cpp_backend.CppBackendService",
                return_value=backend,
            )
        )
        stack.enter_context(
            patch(
                "httpserver.services.graphiti_service.GraphitiService",
                return_value=graphiti,
            )
        )
        stack.enter_context(
            patch(
                "httpserver.services.llm_service.LLMService",
                return_value=llm,
            )
        )
        stack.enter_context(
            patch(
                "httpserver.services.ingestion_job_manager.IngestionJobManager",
                return_value=ingestion,
            )
        )
        migration_module = SimpleNamespace(MigrationManager=lambda **_: migration)
        stack.enter_context(
            patch.dict(sys.modules, {"graphiti_integration.migration": migration_module})
        )
        report_factory = stack.enter_context(
            patch.object(
                manager,
                "_create_forensic_report_service",
                return_value=report,
                create=True,
            )
        )
        yield SimpleNamespace(
            cpp_type=cpp_type,
            report_factory=report_factory,
            graphiti=graphiti,
            llm=llm,
            ingestion=ingestion,
            migration=migration,
        )


_SERVICE_PROPERTIES = (
    "cpp_backend",
    "graphiti_service",
    "llm_service",
    "ingestion_job_manager",
    "migration_manager",
    "forensic_report_service",
)


@pytest.mark.asyncio
async def test_all_service_properties_reject_after_shutdown_cleanup_plan_snapshot(
    tmp_path: Path,
):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    events: list[str] = []
    release_report_shutdown = asyncio.Event()
    report = LifecycleService(
        "report", events, shutdown_gate=release_report_shutdown
    )
    manager._forensic_report_service = report
    manager._forensic_report_ready = True
    manager._initialized = True
    manager._lifecycle_state = "running"

    with (
        patch("httpserver.services.cpp_backend.httpx.AsyncClient") as client_type,
        patch("httpserver.services.graphiti_service.GraphitiService") as graphiti_type,
        patch("httpserver.services.llm_service.LLMService") as llm_type,
    ):
        shutdown = asyncio.create_task(manager.shutdown())
        await report.shutdown_started.wait()

        try:
            with pytest.raises(RuntimeError, match="shutting down"):
                manager.cpp_backend.client
            client_type.assert_not_called()

            for property_name in _SERVICE_PROPERTIES:
                with pytest.raises(RuntimeError, match="shutting down"):
                    getattr(manager, property_name)

            graphiti_type.assert_not_called()
            llm_type.assert_not_called()
            assert manager._cpp_backend is None
            assert manager._graphiti_service is None
            assert manager._llm_service is None
            assert manager._ingestion_job_manager is None
            assert manager._migration_manager is None
            assert manager._forensic_report_service is report
        finally:
            release_report_shutdown.set()
            await shutdown

    assert report.shutdown_calls == 1
    assert all(
        getattr(manager, field_name) is None
        for field_name in (
            "_cpp_backend",
            "_graphiti_service",
            "_llm_service",
            "_ingestion_job_manager",
            "_migration_manager",
            "_forensic_report_service",
        )
    )


@pytest.mark.asyncio
async def test_external_service_properties_reject_during_manager_initialization(
    tmp_path: Path,
):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    events: list[str] = []
    release_backend = asyncio.Event()
    backend = LifecycleService(
        "backend", events, initialize_gate=release_backend
    )
    report = LifecycleService("report", events)

    with _patched_services(manager, backend=backend, report=report) as services:
        initialize = asyncio.create_task(manager.initialize())
        await backend.initialize_started.wait()

        try:
            for property_name in _SERVICE_PROPERTIES:
                with pytest.raises(RuntimeError, match="initializing"):
                    getattr(manager, property_name)
        finally:
            release_backend.set()
            await initialize

    assert services.cpp_type.call_count == 1
    assert services.report_factory.call_count == 1
    assert manager.cpp_backend is backend
    assert manager.graphiti_service is services.graphiti
    assert manager.llm_service is services.llm
    assert manager.ingestion_job_manager is services.ingestion
    assert manager.migration_manager is services.migration
    assert manager.forensic_report_service is report


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_initialize_waits_for_active_shutdown_then_starts_clean_lifecycle(
    tmp_path: Path,
):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    events: list[str] = []
    release_shutdown = asyncio.Event()
    first_backend = LifecycleService(
        "first_backend", events, shutdown_gate=release_shutdown
    )
    first_report = LifecycleService("first_report", events)
    manager._cpp_backend = first_backend
    manager._forensic_report_service = first_report
    manager._initialized = True
    manager._lifecycle_state = "running"

    second_backend = LifecycleService("second_backend", events)
    second_report = LifecycleService("second_report", events)
    with _patched_services(
        manager, backend=second_backend, report=second_report
    ):
        shutdown = asyncio.create_task(manager.shutdown())
        await first_backend.shutdown_started.wait()

        initialize = asyncio.create_task(manager.initialize())
        await asyncio.sleep(0)
        assert not initialize.done()
        assert second_backend.initialize_calls == 0

        release_shutdown.set()
        await shutdown
        await initialize

    assert first_backend.shutdown_calls == 1
    assert first_report.shutdown_calls == 1
    assert second_backend.initialize_calls == 1
    assert second_report.initialize_calls == 1
    assert second_backend.shutdown_calls == 0
    assert second_report.shutdown_calls == 0
    assert manager._cpp_backend is second_backend
    assert manager.forensic_report_service is second_report
    assert manager._lifecycle_state == "running"


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_initialize_continues_after_active_shutdown_reports_cleanup_error(
    tmp_path: Path,
):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    events: list[str] = []
    release_shutdown = asyncio.Event()
    first_backend = LifecycleService(
        "first_backend",
        events,
        shutdown_gate=release_shutdown,
        shutdown_error=RuntimeError("old shutdown failed"),
    )
    manager._cpp_backend = first_backend
    manager._initialized = True
    manager._lifecycle_state = "running"

    second_backend = LifecycleService("second_backend", events)
    second_report = LifecycleService("second_report", events)
    with _patched_services(
        manager, backend=second_backend, report=second_report
    ):
        shutdown = asyncio.create_task(manager.shutdown())
        await first_backend.shutdown_started.wait()
        initialize = asyncio.create_task(manager.initialize())

        release_shutdown.set()
        with pytest.raises(RuntimeError, match="old shutdown failed"):
            await shutdown
        await initialize

    assert second_backend.initialize_calls == 1
    assert second_report.initialize_calls == 1
    assert manager._lifecycle_state == "running"


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_concurrent_initialize_callers_share_one_transition(tmp_path: Path):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    events: list[str] = []
    release_backend = asyncio.Event()
    backend = LifecycleService(
        "backend", events, initialize_gate=release_backend
    )
    report = LifecycleService("report", events)

    with _patched_services(manager, backend=backend, report=report) as services:
        first = asyncio.create_task(manager.initialize())
        await backend.initialize_started.wait()
        second = asyncio.create_task(manager.initialize())
        await asyncio.sleep(0)

        assert services.cpp_type.call_count == 1
        assert backend.initialize_calls == 1

        release_backend.set()
        await asyncio.gather(first, second)

    assert report.initialize_calls == 1
    assert services.report_factory.call_count == 1
    assert manager._lifecycle_state == "running"


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_cancelling_one_initialize_waiter_does_not_cancel_transition(
    tmp_path: Path,
):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    events: list[str] = []
    release_backend = asyncio.Event()
    backend = LifecycleService(
        "backend", events, initialize_gate=release_backend
    )
    report = LifecycleService("report", events)

    with _patched_services(manager, backend=backend, report=report):
        cancelled_waiter = asyncio.create_task(manager.initialize())
        await backend.initialize_started.wait()
        surviving_waiter = asyncio.create_task(manager.initialize())
        await asyncio.sleep(0)

        cancelled_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_waiter
        assert not surviving_waiter.done()
        assert backend.shutdown_calls == 0

        release_backend.set()
        await surviving_waiter

    assert backend.initialize_calls == 1
    assert report.initialize_calls == 1
    assert manager._lifecycle_state == "running"
    assert manager.forensic_report_service is report


@pytest.mark.asyncio
async def test_cancelled_initialization_transition_rolls_back_and_can_retry(
    tmp_path: Path,
):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    events: list[str] = []
    cancelled_graphiti = LifecycleService(
        "graphiti", events, initialize_error=asyncio.CancelledError()
    )
    first_backend = LifecycleService("backend", events)
    first_report = LifecycleService("report", events)

    with _patched_services(
        manager,
        backend=first_backend,
        report=first_report,
        graphiti=cancelled_graphiti,
    ):
        with pytest.raises(asyncio.CancelledError):
            await manager.initialize()

    assert events == [
        "backend.initialize",
        "report.initialize",
        "graphiti.initialize",
        "graphiti.shutdown",
        "report.shutdown",
        "backend.shutdown",
    ]
    assert manager._lifecycle_state == "stopped"
    assert manager._initialized is False
    assert manager._cpp_backend is None
    assert manager._forensic_report_service is None
    assert manager._graphiti_service is None
    with pytest.raises(RuntimeError, match="not initialized"):
        manager.forensic_report_service

    retry_events: list[str] = []
    retry_backend = LifecycleService("retry_backend", retry_events)
    retry_report = LifecycleService("retry_report", retry_events)
    with _patched_services(
        manager, backend=retry_backend, report=retry_report
    ):
        await manager.initialize()

    assert manager._lifecycle_state == "running"
    assert manager.forensic_report_service is retry_report


@pytest.mark.asyncio
async def test_report_property_rejects_partially_initialized_service(tmp_path: Path):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    events: list[str] = []
    release_report = asyncio.Event()
    backend = LifecycleService("backend", events)
    report = LifecycleService("report", events, initialize_gate=release_report)

    with _patched_services(manager, backend=backend, report=report):
        initialize = asyncio.create_task(manager.initialize())
        await report.initialize_started.wait()

        with pytest.raises(RuntimeError, match="initializing"):
            manager.forensic_report_service

        release_report.set()
        await initialize

    assert manager.forensic_report_service is report


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_shutdown_during_initialize_waits_then_drains_without_deadlock(
    tmp_path: Path,
):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    events: list[str] = []
    release_backend = asyncio.Event()
    backend = LifecycleService(
        "backend", events, initialize_gate=release_backend
    )
    report = LifecycleService("report", events)

    with _patched_services(manager, backend=backend, report=report):
        initialize = asyncio.create_task(manager.initialize())
        await backend.initialize_started.wait()
        shutdown = asyncio.create_task(manager.shutdown())
        await asyncio.sleep(0)

        assert not shutdown.done()
        assert backend.shutdown_calls == 0

        release_backend.set()
        await asyncio.wait_for(asyncio.gather(initialize, shutdown), timeout=1)

    assert report.initialize_calls == 1
    assert report.shutdown_calls == 1
    assert backend.shutdown_calls == 1
    assert manager._lifecycle_state == "stopped"
    assert manager._cpp_backend is None
    assert manager._forensic_report_service is None


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_cancelled_shutdown_waiter_during_initialize_does_not_abandon_drain(
    tmp_path: Path,
):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    events: list[str] = []
    release_backend = asyncio.Event()
    backend = LifecycleService(
        "backend", events, initialize_gate=release_backend
    )
    report = LifecycleService("report", events)

    with _patched_services(manager, backend=backend, report=report):
        initialize = asyncio.create_task(manager.initialize())
        await backend.initialize_started.wait()
        shutdown_waiter = asyncio.create_task(manager.shutdown())
        await asyncio.sleep(0)

        shutdown_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await shutdown_waiter

        release_backend.set()
        await initialize
        for _ in range(20):
            if manager._lifecycle_state == "stopped":
                break
            await asyncio.sleep(0)

    assert report.shutdown_calls == 1
    assert backend.shutdown_calls == 1
    assert manager._lifecycle_state == "stopped"
    assert manager._cpp_backend is None
    assert manager._forensic_report_service is None
    assert manager._shutdown_task is not None
    assert manager._shutdown_task.done()


@pytest.mark.asyncio
async def test_report_is_not_constructed_before_backend_initializes(tmp_path: Path):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    events: list[str] = []
    release_backend = asyncio.Event()
    backend = LifecycleService(
        "backend", events, initialize_gate=release_backend
    )
    report = LifecycleService("report", events)

    with _patched_services(manager, backend=backend, report=report) as services:
        initialize = asyncio.create_task(manager.initialize())
        await backend.initialize_started.wait()

        assert services.report_factory.call_count == 0

        release_backend.set()
        await initialize

    assert events.index("backend.initialize") < events.index("report.initialize")


@pytest.mark.asyncio
async def test_fatal_initialization_failure_keeps_primary_and_continues_rollback(
    tmp_path: Path,
):
    class FatalInitializationError(BaseException):
        pass

    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    events: list[str] = []
    primary = FatalInitializationError("fatal graphiti initialization")
    graphiti = LifecycleService(
        "graphiti", events, initialize_error=primary
    )
    backend = LifecycleService("backend", events)
    report = LifecycleService(
        "report",
        events,
        shutdown_error=RuntimeError("report rollback failed"),
    )

    with _patched_services(
        manager, backend=backend, report=report, graphiti=graphiti
    ):
        with pytest.raises(FatalInitializationError) as raised:
            await manager.initialize()

    assert raised.value is primary
    assert report.shutdown_calls == 1
    assert backend.shutdown_calls == 1
    assert manager._lifecycle_state == "stopped"
    assert manager._cpp_backend is None
    assert manager._forensic_report_service is None
    assert manager._graphiti_service is None


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
    manager._cpp_backend_ready = True
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
    manager._cpp_backend_ready = True
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
    manager._cpp_backend_ready = True

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


@pytest.mark.concurrency
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
    manager._cpp_backend_ready = True
    manager.forensic_report_service

    await asyncio.gather(manager.shutdown(), manager.shutdown())

    assert backend.shutdown_calls == 1
    assert manager._forensic_report_service is None


@pytest.mark.concurrency
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
    manager._cpp_backend_ready = True
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
