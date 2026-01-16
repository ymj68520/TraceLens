"""
Health check routes.

Provides endpoints for monitoring service health and readiness.
"""

import time
from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import Settings, get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    timestamp: str
    version: str
    uptime_seconds: float


class ReadinessResponse(BaseModel):
    """Readiness check response model."""
    ready: bool
    checks: Dict[str, Any]
    timestamp: str


class SystemInfoResponse(BaseModel):
    """System information response model."""
    service: str
    version: str
    python_version: str
    config: Dict[str, Any]
    timestamp: str


# Track server start time
_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Basic health check endpoint.
    
    Returns a simple health status indicating the service is running.
    """
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        version="1.0.0",
        uptime_seconds=time.time() - _start_time,
    )


@router.get("/health/live", response_model=HealthResponse)
async def liveness_check():
    """
    Kubernetes liveness probe endpoint.
    
    Returns healthy if the service process is running.
    Used by orchestrators to determine if a restart is needed.
    """
    return HealthResponse(
        status="alive",
        timestamp=datetime.now().isoformat(),
        version="1.0.0",
        uptime_seconds=time.time() - _start_time,
    )


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness_check(settings: Settings = Depends(get_settings)):
    """
    Kubernetes readiness probe endpoint.
    
    Checks if the service is ready to handle requests by verifying
    connectivity to dependent services.
    """
    checks = {}
    all_ready = True
    
    # Check C++ backend connectivity
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        cpp_status = await service_manager.cpp_backend.health_check()
        checks["cpp_backend"] = {
            "status": "connected" if cpp_status else "disconnected",
            "url": settings.cpp_backend_url,
        }
        if not cpp_status:
            all_ready = False
    except Exception as e:
        checks["cpp_backend"] = {
            "status": "error",
            "error": str(e),
        }
        all_ready = False
    
    # Check Neo4j connectivity (if graphiti is enabled)
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        neo4j_status = await service_manager.graphiti_service.health_check()
        checks["neo4j"] = {
            "status": "connected" if neo4j_status else "disconnected",
            "uri": settings.neo4j_uri,
        }
    except Exception as e:
        checks["neo4j"] = {
            "status": "unavailable",
            "error": str(e),
        }
        # Neo4j is optional, don't fail readiness
    
    # Check LLM service availability
    try:
        from ..services import get_service_manager
        service_manager = get_service_manager()
        llm_status = await service_manager.llm_service.health_check()
        checks["llm"] = {
            "status": "available" if llm_status else "unavailable",
            "url": settings.llm_text_base_url,
        }
    except Exception as e:
        checks["llm"] = {
            "status": "unavailable",
            "error": str(e),
        }
        # LLM is optional, don't fail readiness
    
    return ReadinessResponse(
        ready=all_ready,
        checks=checks,
        timestamp=datetime.now().isoformat(),
    )


@router.get("/api/system/info", response_model=SystemInfoResponse)
async def system_info(settings: Settings = Depends(get_settings)):
    """
    Get system and configuration information.
    
    Returns detailed information about the service configuration
    and runtime environment.
    """
    import sys
    import platform
    
    return SystemInfoResponse(
        service="ForensicsProject Python Service",
        version="1.0.0",
        python_version=sys.version,
        config={
            "http_port": settings.python_http_port,
            "http_host": settings.python_http_host,
            "cpp_backend_url": settings.cpp_backend_url,
            "neo4j_uri": settings.neo4j_uri,
            "llm_text_model": settings.llm_text_model,
            "llm_vision_model": settings.llm_vision_model,
            "log_level": settings.log_level,
            "platform": platform.platform(),
        },
        timestamp=datetime.now().isoformat(),
    )
