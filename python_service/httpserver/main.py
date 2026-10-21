"""
FastAPI HTTP Server for ForensicsProject Python Service.

This is the main entry point for the Python HTTP service.
It configures the FastAPI application, middleware, and routes.

The architecture is designed for extensibility:
- Routes are modular and can be easily added
- Services layer abstracts business logic
- Middleware handles cross-cutting concerns
- Communication protocols can be extended (HTTP, gRPC, WebSocket)
"""

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .config import Settings, get_settings
from .services.field_security import (
    FieldAuthenticationError, authorize,
    load_policy, principal, valid_internal,
)
from .release_info import RELEASE_ID

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# Global app instance
_app: Optional[FastAPI] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    settings = get_settings()
    logger.info(f"Starting Python HTTP Service on port {settings.python_http_port}")
    logger.info(f"C++ Backend URL: {settings.cpp_backend_url}")
    logger.info("Neo4j endpoint configured: %s", bool(settings.neo4j_uri))
    
    # Startup: Initialize services
    try:
        # Import services here to avoid circular imports
        from .services import get_service_manager
        service_manager = get_service_manager()
        await service_manager.initialize()
        # Initialize dependency injection system
        from .dependencies import init_dependencies
        init_dependencies(service_manager)
        # Register the episode gate hook (llm-throughput-hardening SPEC A):
        # ingestion pauses between episodes while the pipeline hammers the LLM.
        from .services.ingestion_gate import install_episode_gate
        install_episode_gate(settings, service_manager.cpp_backend.list_tasks)
    except Exception as e:
        logger.warning(f"Some services failed to initialize: {e}")

    # Reconcile combined-case records left in ANALYSING by a previous process
    # (the cross-image job registry is in-memory; SPEC §4.3 robustness).
    try:
        from .routes.multi_analysis import reconcile_orphan_analysis
        asyncio.create_task(reconcile_orphan_analysis(settings))
    except Exception as e:
        logger.warning(f"Case analysis reconciliation failed to start: {e}")

    yield

    # Shutdown: Cleanup services
    logger.info("Shutting down Python HTTP Service")
    try:
        # Release the process-global gate first so nothing in shutdown (or a
        # subsequent app in the same process, e.g. tests) uses a dead backend.
        from .services.ingestion_gate import uninstall_episode_gate
        uninstall_episode_gate()
    except Exception as e:
        logger.warning(f"Error releasing episode gate: {e}")
    try:
        from .services import get_service_manager
        service_manager = get_service_manager()
        await service_manager.shutdown()
    except Exception as e:
        logger.warning(f"Error during shutdown: {e}")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Args:
        settings: Optional settings override. Uses default settings if None.
    
    Returns:
        Configured FastAPI application instance.
    """
    global _app
    
    if settings is None:
        settings = get_settings()

    # In field mode, missing/weak credentials abort app creation. Never turn a
    # failed authentication configuration into anonymous service access.
    field_policy = load_policy()
    if field_policy.enabled and os.environ.get("TRACELENS_REQUIRE_RELEASE_LAYOUT") == "1":
        configured_root = os.environ.get("TRACELENS_RELEASE_ROOT", "")
        configured_python = os.environ.get("TRACELENS_PYTHON_BIN", "")
        if (RELEASE_ID == "UNFROZEN_WORKTREE" or
                os.environ.get("TRACELENS_RELEASE_ID") != RELEASE_ID or
                not configured_root or not configured_python or
                Path(configured_root).resolve(strict=False) != Path(__file__).resolve().parents[2] or
                not Path(configured_python).is_file()):
            raise RuntimeError("field release identity or Python layout is not loaded")
    
    app = FastAPI(
        title="ForensicsProject Python Service",
        description="""
Python HTTP Service for ForensicsProject digital forensics tool.

## Features

- **Graphiti Integration**: Knowledge graph operations for forensic data
- **LLM Analysis**: AI-powered file analysis and description generation
- **Database Access**: Query forensic databases and export data
- **Health Monitoring**: Service health and readiness checks

## Architecture

This service works alongside the C++ HTTP server to provide
comprehensive forensic analysis capabilities. It communicates
with the C++ backend for task management and file system operations.
        """,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.field_policy = field_policy
    
    # Configure CORS. Origins come from PYTHON_CORS_ORIGINS (default ["*"]).
    # A wildcard origin cannot be combined with credentials per the CORS spec
    # (browsers reject it), so only enable credentials when origins are explicit.
    _cors_origins = ([field_policy.browser_origin] if field_policy.browser_origin else []) \
        if field_policy.enabled else settings.cors_origins
    _allow_credentials = _cors_origins != ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def field_authentication(request: Request, call_next):
        policy = request.app.state.field_policy
        if not policy.enabled:
            return await call_next(request)
        path = request.url.path
        if request.method == "OPTIONS":
            # Let the explicit-origin CORS middleware answer preflight. The
            # subsequent real request still passes through this auth guard.
            return await call_next(request)
        if path == "/health/live":
            return JSONResponse({"status": "alive"})
        if path in {"/api/field-auth/login", "/api/field-auth/introspect"}:
            return await call_next(request)
        peer = request.client.host if request.client else ""
        service_token = request.headers.get("x-tracelens-service-token", "")
        if service_token and valid_internal(policy, service_token, direction="cpp_to_python", peer=peer):
            if not (path == "/health" or path.startswith("/api/graphiti/")
                    or path == "/api/graphiti/ingest" or path == "/api/llm/file-analysis/record"):
                return JSONResponse(status_code=403, content={"detail": "service scope denied"})
            request.state.principal = {"id": "cpp-service", "role": "service", "kind": "service"}
        else:
            try:
                subject = principal(policy, request.headers.get("authorization", ""))
                authorize(subject, request.method, path)
                request.state.principal = subject
            except FieldAuthenticationError:
                return JSONResponse(status_code=401, content={"detail": "authentication required"},
                                    headers={"WWW-Authenticate": "Bearer"})
            except PermissionError:
                return JSONResponse(status_code=403, content={"detail": "insufficient permission"})
        if policy.outbound_mode == "disabled" and (
            path.startswith("/api/graphiti") or path.startswith("/api/llm/")
            or "oss" in path.lower() or "embedding" in path.lower()
        ):
            return JSONResponse(status_code=503, content={"detail": "optional intelligence services disabled"})
        return await call_next(request)

    @app.middleware("http")
    async def field_response_headers(request: Request, call_next):
        response = await call_next(request)
        if request.app.state.field_policy.enabled:
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            )
            response.headers["Cache-Control"] = "no-store"
        return response
    
    # Add request logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log all requests with timing information."""
        start_time = time.time()
        
        # Get client IP
        client_ip = request.client.host if request.client else "unknown"
        
        # Process request
        try:
            response = await call_next(request)
            duration = (time.time() - start_time) * 1000
            
            logger.info(
                f"{request.method} {request.url.path} - "
                f"{response.status_code} - {duration:.2f}ms - {client_ip}"
            )
            
            return response
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            # Exception messages can contain report text, paths, tokens or
            # request bodies. Ordinary access logs only need the error class.
            logger.error(
                f"{request.method} {request.url.path} - "
                f"ERROR - {duration:.2f}ms - {client_ip}: {type(e).__name__}"
            )
            raise
    
    # Add global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle all unhandled exceptions."""
        # Do not log exception text or traceback in ordinary operation:
        # either can contain evidence content, paths, credentials or prompts.
        logger.error("Unhandled exception class: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Internal server error",
                "error": "An unexpected error occurred",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    # Add validation error handler for detailed logging
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handle Pydantic validation errors with detailed logging."""
        logger.error(f"[VALIDATION_ERROR] Path: {request.url.path}")
        # Request bodies can contain one-time archive passwords. Pydantic's
        # `input` field can echo them too, so never log/return raw values.
        safe_errors = [
            {key: value for key, value in error.items() if key in {"loc", "msg", "type"}}
            for error in exc.errors()
        ]
        logger.error(f"[VALIDATION_ERROR] Errors: {safe_errors}")
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "message": "Validation error",
                "errors": safe_errors,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    
    # Register routes
    _register_routes(app)
    
    _app = app
    return app


def _register_routes(app: FastAPI):
    """Register all route modules."""
    from .routes import health, graphiti, llm, database, office, case_analysis, system, associations, oss_analysis, multi_analysis, dll, markitdown, wechat_graph, qq_forensics, android_report, evidence_intake, forensic_reports, investigation, investigation_workbench, report_evidence, report_generation, report_narrative, report_pipeline_tail, event_cluster_analysis, video_analysis, audio_analysis, field_auth

    # Health routes (no prefix)
    app.include_router(health.router, tags=["Health"])
    app.include_router(field_auth.router, prefix="/api/field-auth", tags=["Field Authentication"])

    # API routes
    app.include_router(graphiti.router, prefix="/api/graphiti", tags=["Graphiti"])
    app.include_router(llm.router, prefix="/api/llm", tags=["LLM"])
    app.include_router(case_analysis.router, prefix="/api/llm", tags=["Case Analysis"])
    app.include_router(event_cluster_analysis.router, prefix="/api/llm", tags=["Event Cluster Analysis"])
    app.include_router(
        report_pipeline_tail.router,
        prefix="/api/reports",
        tags=["Forensic Reports"],
    )
    app.include_router(
        forensic_reports.router,
        prefix="/api/reports",
        tags=["Forensic Reports"],
    )
    app.include_router(
        report_evidence.router,
        prefix="/api/reports",
        tags=["Report Evidence"],
    )
    app.include_router(
        report_generation.router,
        prefix="/api/reports",
        tags=["Report Generation"],
    )
    app.include_router(
        report_narrative.router,
        prefix="/api/reports",
        tags=["Report Narrative"],
    )
    app.include_router(
        investigation_workbench.router,
        prefix="/api/investigation/workbench",
        tags=["Investigation Workbench"],
    )
    app.include_router(
        investigation.router,
        prefix="/api/investigation",
        tags=["Investigation"],
    )
    app.include_router(multi_analysis.router, tags=["Multi-Image Analysis"])
    app.include_router(associations.router, prefix="/api/associations", tags=["Associations"])
    app.include_router(database.router, prefix="/api/db", tags=["Database"])
    app.include_router(office.router, prefix="/api/office", tags=["Office"])
    app.include_router(oss_analysis.router, tags=["OSS Analysis"])
    app.include_router(system.router, prefix="/api/system", tags=["System"])
    app.include_router(dll.router, prefix="/api/llm", tags=["DLL"])
    app.include_router(markitdown.router, prefix="/api/markitdown", tags=["Markitdown"])
    app.include_router(video_analysis.router, prefix="/api/video-analysis", tags=["Video Analysis"])
    app.include_router(audio_analysis.router, prefix="/api/audio-analysis", tags=["Audio Analysis"])
    app.include_router(wechat_graph.router, prefix="/api/wechat", tags=["WeChat Analysis"])
    app.include_router(qq_forensics.router, prefix="/api/qq", tags=["QQ Forensics"])
    app.include_router(android_report.router, prefix="/api/android-report", tags=["Android Offline Reports"])
    app.include_router(evidence_intake.router, prefix="/api/evidence-intake", tags=["Evidence Intake"])
    from .routes import raid_task_intake
    app.include_router(raid_task_intake.router, prefix="/api/evidence-intake", tags=["Evidence Intake"])


def get_app() -> FastAPI:
    """Get the global FastAPI application instance."""
    global _app
    if _app is None:
        _app = create_app()
    return _app


def run_server(
    host: Optional[str] = None,
    port: Optional[int] = None,
    reload: bool = False,
    workers: int = 1,
):
    """
    Run the HTTP server.

    Args:
        host: Server host. Uses settings if None.
        port: Server port. Uses settings if None.
        reload: Enable auto-reload for development.
        workers: Number of worker processes.
    """
    settings = get_settings()

    host = host or settings.python_http_host
    port = port or settings.python_http_port

    logger.info(f"Starting server at http://{host}:{port}")

    # Get app instance directly to avoid module import issues
    app = get_app()

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        workers=workers,
    )


if __name__ == "__main__":
    run_server()
