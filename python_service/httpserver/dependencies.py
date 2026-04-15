"""
Dependency injection helpers for FastAPI routes.

Provides convenient accessor functions for services managed by ServiceManager.
"""

import logging

logger = logging.getLogger(__name__)

# Global service manager reference (set during app initialization)
_service_manager = None


def init_dependencies(service_manager):
    """Initialize the dependency injection system with the service manager."""
    global _service_manager
    _service_manager = service_manager
    logger.info("Dependency injection system initialized")


def get_service_manager():
    """Get the global service manager instance."""
    if _service_manager is None:
        raise RuntimeError("Service manager not initialized. Call init_dependencies() first.")
    return _service_manager


def get_case_analysis_service():
    """
    Get or create a CaseAnalysisService instance.

    Returns None if the service manager is not yet initialized.
    This allows the service to be lazy-loaded during app startup.
    """
    try:
        sm = get_service_manager()
    except RuntimeError:
        # Service manager not yet initialized (e.g., during module import)
        return None

    if not hasattr(sm, "_case_analysis_service"):
        from .services.case_analysis import CaseAnalysisService
        svc = CaseAnalysisService(sm.settings)
        svc.set_llm_service(sm.llm_service)
        svc.set_cpp_backend(sm.cpp_backend)
        # Inject Graphiti service if available (optional dependency)
        try:
            graphiti_svc = sm.graphiti_service
            if graphiti_svc:
                svc.set_graphiti_service(graphiti_svc)
                logger.info("Graphiti service injected into case analysis service")
        except Exception as e:
            logger.warning(f"Could not inject Graphiti service: {e}")
        sm._case_analysis_service = svc
    return sm._case_analysis_service
