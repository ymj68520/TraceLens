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
        self._lifecycle_state = "new"
        self._lifecycle_lock = asyncio.Lock()
        self._shutdown_task: Optional[asyncio.Task[None]] = None
    
    async def initialize(self):
        """Initialize all services."""
        async with self._lifecycle_lock:
            if self._initialized:
                return
            self._lifecycle_state = "initializing"
            self._shutdown_task = None

            logger.info("Initializing services...")

            # Initialize C++ backend service
            try:
                from .cpp_backend import CppBackendService
                self._cpp_backend = CppBackendService(self.settings)
                await self._cpp_backend.initialize()
            except Exception as e:
                logger.warning(f"C++ backend service initialization failed: {e}")

            # Recover durable report records after the C++ backend is available.
            try:
                await self.forensic_report_service.initialize()
            except Exception as e:
                logger.warning(f"ForensicReportService initialization failed: {e}")

            # Initialize Graphiti service
            try:
                from .graphiti_service import GraphitiService
                self._graphiti_service = GraphitiService(self.settings)
                await self._graphiti_service.initialize()
            except Exception as e:
                logger.warning(f"Graphiti service initialization failed: {e}")

            # Initialize LLM service
            try:
                from .llm_service import LLMService
                self._llm_service = LLMService(self.settings)
                await self._llm_service.initialize()
            except Exception as e:
                logger.warning(f"LLM service initialization failed: {e}")

            # Initialize IngestionJobManager
            try:
                from .ingestion_job_manager import IngestionJobManager
                self._ingestion_job_manager = IngestionJobManager(self.settings)
                await self._ingestion_job_manager.initialize()
            except Exception as e:
                logger.warning(f"IngestionJobManager initialization failed: {e}")

            # Initialize MigrationManager (optional, requires Neo4j)
            try:
                # Import with absolute import path since graphiti_integration is sibling to httpserver
                import sys
                from pathlib import Path
                # Add python_service to path if not already there
                python_service_path = str(Path(__file__).parent.parent.parent)
                if python_service_path not in sys.path:
                    sys.path.insert(0, python_service_path)
                from graphiti_integration.migration import MigrationManager
                self._migration_manager = MigrationManager(
                    neo4j_uri=self.settings.neo4j_uri,
                    neo4j_user=self.settings.neo4j_user,
                    neo4j_password=self.settings.neo4j_password
                )
                await self._migration_manager.initialize()
            except ImportError as e:
                logger.warning(f"MigrationManager import failed: {e}")
            except Exception as e:
                logger.warning(f"MigrationManager initialization failed: {e}")

            self._initialized = True
            self._lifecycle_state = "running"
            logger.info("All services initialized successfully")
    
    async def shutdown(self):
        """Shutdown all services gracefully."""
        async with self._lifecycle_lock:
            if self._lifecycle_state == "stopped":
                return
            if self._shutdown_task is None:
                self._lifecycle_state = "shutting_down"
                self._shutdown_task = asyncio.create_task(self._drain_shutdown())
            shutdown_task = self._shutdown_task
        await asyncio.shield(shutdown_task)

    async def _drain_shutdown(self) -> None:
        logger.info("Shutting down services...")
        first_error: BaseException | None = None

        async def drain(service, method_name: str) -> None:
            nonlocal first_error
            if service is None:
                return
            try:
                await getattr(service, method_name)()
            except BaseException as error:
                if first_error is None:
                    first_error = error

        try:
            await drain(self._forensic_report_service, "shutdown")
            self._forensic_report_service = None
            await drain(self._cpp_backend, "shutdown")
            await drain(self._graphiti_service, "shutdown")
            await drain(self._llm_service, "shutdown")
            await drain(self._ingestion_job_manager, "shutdown")
            await drain(self._migration_manager, "close")
            if first_error is not None:
                raise first_error
        finally:
            self._forensic_report_service = None
            self._initialized = False
            self._lifecycle_state = "stopped"
            logger.info("All services shut down")
    
    @property
    def cpp_backend(self) -> "CppBackendService":
        """Get the C++ backend service."""
        if self._cpp_backend is None:
            from .cpp_backend import CppBackendService
            self._cpp_backend = CppBackendService(self.settings)
        return self._cpp_backend
    
    @property
    def forensic_report_service(self):
        """Get the durable forensic report generation service."""
        if self._lifecycle_state == "shutting_down":
            raise RuntimeError("ServiceManager is shutting down")
        if self._lifecycle_state == "stopped":
            raise RuntimeError("ServiceManager is not initialized")
        if self._forensic_report_service is None:
            from pathlib import Path

            from .forensic_report.repository import ReportRepository
            from .forensic_report.service import ForensicReportService
            from .forensic_report.snapshot_writer import SnapshotWriter
            from .forensic_report.source_resolver import SourceResolver

            root = Path(self.settings.report_output_dir)
            if not root.is_absolute():
                from ..config import get_project_root

                root = get_project_root() / root
            self._forensic_report_service = ForensicReportService(
                repository=ReportRepository(root / "reports.db"),
                resolver=SourceResolver(self.cpp_backend),
                writer=SnapshotWriter(
                    root / "snapshots", self.settings.report_generator_version
                ),
                adapters=[],
            )
        return self._forensic_report_service

    @property
    def graphiti_service(self) -> "GraphitiService":
        """Get the Graphiti service."""
        if self._graphiti_service is None:
            from .graphiti_service import GraphitiService
            self._graphiti_service = GraphitiService(self.settings)
        return self._graphiti_service
    
    @property
    def llm_service(self) -> "LLMService":
        """Get the LLM service."""
        if self._llm_service is None:
            from .llm_service import LLMService
            self._llm_service = LLMService(self.settings)
        return self._llm_service

    @property
    def ingestion_job_manager(self) -> Optional["IngestionJobManager"]:
        """Get the IngestionJobManager service."""
        return self._ingestion_job_manager

    @property
    def migration_manager(self) -> Optional["MigrationManager"]:
        """Get the MigrationManager service."""
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
