"""
Service Manager - Central coordinator for all services.

This class provides a single point of access to all services
and manages their lifecycle (initialization, shutdown).

The design supports future extension to other communication protocols:
- Current: HTTP (REST API)
- Future: gRPC, WebSocket, Message Queue, etc.
"""

import asyncio
import logging
from functools import lru_cache
from typing import Optional

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)


class ServiceManager:
    """
    Central service manager for coordinating all backend services.
    
    Provides:
    - Service initialization and shutdown
    - Service access through properties
    - Health checking for all services
    
    The architecture is designed for future protocol extension:
    - Each service can be wrapped with different protocol adapters
    - New protocols can be added without changing service logic
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        """
        Initialize the service manager.
        
        Args:
            settings: Optional settings override.
        """
        self.settings = settings or get_settings()
        self._cpp_backend: Optional["CppBackendService"] = None
        self._graphiti_service: Optional["GraphitiService"] = None
        self._llm_service: Optional["LLMService"] = None
        self._ingestion_job_manager: Optional["IngestionJobManager"] = None
        self._migration_manager: Optional["MigrationManager"] = None
        self._forensic_report_service = None
        self._initialized = False
        self._cpp_backend_ready = False
        self._forensic_report_ready = False
        self._lifecycle_state = "new"
        self._lifecycle_lock = asyncio.Lock()
        self._initialization_task: Optional[asyncio.Task[None]] = None
        self._shutdown_task: Optional[asyncio.Task[None]] = None
    
    async def initialize(self):
        """Initialize all services through one shared, shielded transition."""
        while True:
            async with self._lifecycle_lock:
                if self._initialized and self._lifecycle_state == "running":
                    return
                shutdown_task = self._active_task(self._shutdown_task)
                if shutdown_task is None:
                    initialization_task = self._active_task(self._initialization_task)
                    if initialization_task is None:
                        self._lifecycle_state = "initializing"
                        initialization_task = asyncio.create_task(
                            self._run_initialization()
                        )
                        self._initialization_task = initialization_task
                else:
                    initialization_task = None

            if shutdown_task is not None:
                try:
                    await asyncio.shield(shutdown_task)
                except asyncio.CancelledError:
                    current = asyncio.current_task()
                    if current is not None and current.cancelling():
                        raise
                except BaseException:
                    # Cleanup errors belong to shutdown callers; once the drain has
                    # restored stopped state, initialization may start a clean cycle.
                    pass
                continue
            await asyncio.shield(initialization_task)
            return

    async def _run_initialization(self) -> None:
        logger.info("Initializing services...")
        try:
            await self._initialize_services()
        except BaseException:
            await self._rollback_initialization()
            raise
        else:
            async with self._lifecycle_lock:
                self._initialized = True
                if self._lifecycle_state == "initializing":
                    self._lifecycle_state = "running"
            logger.info("All services initialized successfully")

    async def _initialize_services(self) -> None:
        # Initialize C++ backend service. Its ordinary failures remain tolerated,
        # but cancellation and other BaseExceptions abort the whole transition.
        try:
            from .cpp_backend import CppBackendService

            self._cpp_backend = CppBackendService(self.settings)
            await self._cpp_backend.initialize()
            self._cpp_backend_ready = True
        except Exception as error:
            logger.warning(f"C++ backend service initialization failed: {error}")

        # Report recovery must never bind to a backend that failed initialization.
        if self._cpp_backend_ready:
            try:
                self._forensic_report_service = self._create_forensic_report_service()
                await self._forensic_report_service.initialize()
                self._forensic_report_ready = True
            except Exception as error:
                logger.warning(
                    f"ForensicReportService initialization failed: {error}"
                )

        # Initialize Graphiti service
        try:
            from .graphiti_service import GraphitiService

            self._graphiti_service = GraphitiService(self.settings)
            await self._graphiti_service.initialize()
        except Exception as error:
            logger.warning(f"Graphiti service initialization failed: {error}")

        # Initialize LLM service
        try:
            from .llm_service import LLMService

            self._llm_service = LLMService(self.settings)
            await self._llm_service.initialize()
        except Exception as error:
            logger.warning(f"LLM service initialization failed: {error}")

        # Initialize IngestionJobManager
        try:
            from .ingestion_job_manager import IngestionJobManager

            self._ingestion_job_manager = IngestionJobManager(self.settings)
            await self._ingestion_job_manager.initialize()
        except Exception as error:
            logger.warning(f"IngestionJobManager initialization failed: {error}")

        # Initialize MigrationManager (optional, requires Neo4j)
        try:
            import sys
            from pathlib import Path

            python_service_path = str(Path(__file__).parent.parent.parent)
            if python_service_path not in sys.path:
                sys.path.insert(0, python_service_path)
            from graphiti_integration.migration import MigrationManager

            self._migration_manager = MigrationManager(
                neo4j_uri=self.settings.neo4j_uri,
                neo4j_user=self.settings.neo4j_user,
                neo4j_password=self.settings.neo4j_password,
            )
            await self._migration_manager.initialize()
        except ImportError as error:
            logger.warning(f"MigrationManager import failed: {error}")
        except Exception as error:
            logger.warning(f"MigrationManager initialization failed: {error}")

    async def _rollback_initialization(self) -> None:
        cleanup_errors: list[BaseException] = []
        rollback_plan = (
            (self._migration_manager, "close"),
            (self._ingestion_job_manager, "shutdown"),
            (self._llm_service, "shutdown"),
            (self._graphiti_service, "shutdown"),
            (self._forensic_report_service, "shutdown"),
            (self._cpp_backend, "shutdown"),
        )
        for service, method_name in rollback_plan:
            if service is None:
                continue
            try:
                await getattr(service, method_name)()
            except BaseException as error:
                cleanup_errors.append(error)
                logger.error(
                    "Service cleanup failed during initialization rollback",
                    exc_info=(type(error), error, error.__traceback__),
                )
        async with self._lifecycle_lock:
            self._clear_services()
            self._initialized = False
            self._lifecycle_state = "stopped"
        if cleanup_errors:
            logger.warning(
                "Initialization rollback completed with %d cleanup error(s)",
                len(cleanup_errors),
            )
    
    async def shutdown(self):
        """Shutdown all services through one shared, shielded transition."""
        async with self._lifecycle_lock:
            shutdown_task = self._active_task(self._shutdown_task)
            if shutdown_task is None:
                if self._lifecycle_state == "stopped":
                    return
                self._lifecycle_state = "shutting_down"
                shutdown_task = asyncio.create_task(
                    self._coordinate_shutdown()
                )
                self._shutdown_task = shutdown_task
        await asyncio.shield(shutdown_task)

    async def _coordinate_shutdown(self) -> None:
        async with self._lifecycle_lock:
            initialization_task = self._active_task(self._initialization_task)
        if initialization_task is not None:
            try:
                await asyncio.shield(initialization_task)
            except BaseException:
                pass
        await self._drain_shutdown()

    async def _drain_shutdown(self) -> None:
        logger.info("Shutting down services...")
        first_error: BaseException | None = None

        for service, method_name in self._service_cleanup_plan():
            if service is None:
                continue
            try:
                await getattr(service, method_name)()
            except BaseException as error:
                if first_error is None:
                    first_error = error
            finally:
                if service is self._forensic_report_service:
                    self._forensic_report_service = None
                    self._forensic_report_ready = False
        async with self._lifecycle_lock:
            self._clear_services()
            self._initialized = False
            self._lifecycle_state = "stopped"
        logger.info("All services shut down")
        if first_error is not None:
            raise first_error

    @staticmethod
    def _active_task(task: Optional[asyncio.Task[None]]) -> Optional[asyncio.Task[None]]:
        if task is None or task.done():
            return None
        return task

    def _service_cleanup_plan(self) -> tuple[tuple[object | None, str], ...]:
        return (
            (self._forensic_report_service, "shutdown"),
            (self._cpp_backend, "shutdown"),
            (self._graphiti_service, "shutdown"),
            (self._llm_service, "shutdown"),
            (self._ingestion_job_manager, "shutdown"),
            (self._migration_manager, "close"),
        )

    def _clear_services(self) -> None:
        self._forensic_report_service = None
        self._cpp_backend = None
        self._graphiti_service = None
        self._llm_service = None
        self._ingestion_job_manager = None
        self._migration_manager = None
        self._cpp_backend_ready = False
        self._forensic_report_ready = False

    def _require_service_access(self) -> None:
        if self._lifecycle_state == "initializing":
            raise RuntimeError("ServiceManager is initializing")
        if self._lifecycle_state == "shutting_down":
            raise RuntimeError("ServiceManager is shutting down")
        if self._lifecycle_state == "stopped":
            raise RuntimeError("ServiceManager is not initialized")

    @property
    def cpp_backend(self) -> "CppBackendService":
        """Get the C++ backend service."""
        self._require_service_access()
        if self._cpp_backend is None:
            from .cpp_backend import CppBackendService
            self._cpp_backend = CppBackendService(self.settings)
        return self._cpp_backend
    
    def _create_forensic_report_service(self):
        from pathlib import Path

        from .forensic_report.repository import ReportRepository
        from .forensic_report.service import ForensicReportService
        from .forensic_report.snapshot_writer import SnapshotWriter
        from .forensic_report.source_resolver import SourceResolver

        if not self._cpp_backend_ready or self._cpp_backend is None:
            raise RuntimeError("C++ backend is not initialized")
        root = Path(self.settings.report_output_dir)
        if not root.is_absolute():
            from ..config import get_project_root

            root = get_project_root() / root
        return ForensicReportService(
            repository=ReportRepository(root / "reports.db"),
            resolver=SourceResolver(self._cpp_backend),
            writer=SnapshotWriter(
                root / "snapshots", self.settings.report_generator_version
            ),
            adapters=[],
        )

    @property
    def forensic_report_service(self):
        """Get the ready durable forensic report generation service."""
        self._require_service_access()
        if self._forensic_report_service is None:
            if self._lifecycle_state != "new":
                raise RuntimeError("Forensic report service is unavailable")
            self._forensic_report_service = self._create_forensic_report_service()
            self._forensic_report_ready = True
        if not self._forensic_report_ready:
            raise RuntimeError("Forensic report service is unavailable")
        return self._forensic_report_service

    @property
    def graphiti_service(self) -> "GraphitiService":
        """Get the Graphiti service."""
        self._require_service_access()
        if self._graphiti_service is None:
            from .graphiti_service import GraphitiService
            self._graphiti_service = GraphitiService(self.settings)
        return self._graphiti_service

    @property
    def llm_service(self) -> "LLMService":
        """Get the LLM service."""
        self._require_service_access()
        if self._llm_service is None:
            from .llm_service import LLMService
            self._llm_service = LLMService(self.settings)
        return self._llm_service

    @property
    def ingestion_job_manager(self) -> Optional["IngestionJobManager"]:
        """Get the IngestionJobManager service."""
        self._require_service_access()
        return self._ingestion_job_manager

    @property
    def migration_manager(self) -> Optional["MigrationManager"]:
        """Get the MigrationManager service."""
        self._require_service_access()
        return self._migration_manager

    async def health_check(self) -> dict:
        """
        Check health of all services.
        
        Returns:
            Dict with health status of each service.
        """
        result = {
            "overall": "healthy",
            "services": {},
        }
        
        # Check C++ backend
        try:
            cpp_healthy = await self.cpp_backend.health_check()
            result["services"]["cpp_backend"] = {
                "status": "healthy" if cpp_healthy else "unhealthy",
            }
        except Exception as e:
            result["services"]["cpp_backend"] = {
                "status": "error",
                "error": str(e),
            }
            result["overall"] = "degraded"
        
        # Check Graphiti
        try:
            graphiti_healthy = await self.graphiti_service.health_check()
            result["services"]["graphiti"] = {
                "status": "healthy" if graphiti_healthy else "unhealthy",
            }
        except Exception as e:
            result["services"]["graphiti"] = {
                "status": "unavailable",
                "error": str(e),
            }
        
        # Check LLM
        try:
            llm_healthy = await self.llm_service.health_check()
            result["services"]["llm"] = {
                "status": "healthy" if llm_healthy else "unhealthy",
            }
        except Exception as e:
            result["services"]["llm"] = {
                "status": "unavailable",
                "error": str(e),
            }
        
        return result


# Global service manager instance
_service_manager: Optional[ServiceManager] = None


def get_service_manager() -> ServiceManager:
    """
    Get the global service manager instance.
    
    Returns:
        ServiceManager instance.
    """
    global _service_manager
    if _service_manager is None:
        _service_manager = ServiceManager()
    return _service_manager
