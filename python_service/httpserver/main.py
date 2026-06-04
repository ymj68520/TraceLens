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

import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .config import Settings, get_settings

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
    logger.info(f"Neo4j URI: {settings.neo4j_uri}")
    
    # Startup: Initialize services
    try:
        # Import services here to avoid circular imports
        from .services import get_service_manager
        service_manager = get_service_manager()
        await service_manager.initialize()
        # Initialize dependency injection system
        from .dependencies import init_dependencies
        init_dependencies(service_manager)
    except Exception as e:
        logger.warning(f"Some services failed to initialize: {e}")
    
    yield
    
    # Shutdown: Cleanup services
    logger.info("Shutting down Python HTTP Service")
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
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
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
            logger.error(
                f"{request.method} {request.url.path} - "
                f"ERROR - {duration:.2f}ms - {client_ip}: {str(e)}"
            )
            raise
    
    # Add global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle all unhandled exceptions."""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Internal server error",
                "error": str(exc) if settings.log_level == "DEBUG" else "An unexpected error occurred",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    # Add validation error handler for detailed logging
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handle Pydantic validation errors with detailed logging."""
        logger.error(f"[VALIDATION_ERROR] Path: {request.url.path}")
        logger.error(f"[VALIDATION_ERROR] Body: {await request.body()}")
        logger.error(f"[VALIDATION_ERROR] Errors: {exc.errors()}")
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "message": "Validation error",
                "errors": exc.errors(),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    
    # Register routes
    _register_routes(app)
    
    _app = app
    return app


def _register_routes(app: FastAPI):
    """Register all route modules."""
    from .routes import health, graphiti, llm, database, office, case_analysis, system, associations, oss_analysis, multi_analysis, dll, markitdown

    # Health routes (no prefix)
    app.include_router(health.router, tags=["Health"])

    # API routes
    app.include_router(graphiti.router, prefix="/api/graphiti", tags=["Graphiti"])
    app.include_router(llm.router, prefix="/api/llm", tags=["LLM"])
    app.include_router(case_analysis.router, prefix="/api/llm", tags=["Case Analysis"])
    app.include_router(multi_analysis.router, tags=["Multi-Image Analysis"])
    app.include_router(associations.router, prefix="/api/associations", tags=["Associations"])
    app.include_router(database.router, prefix="/api/db", tags=["Database"])
    app.include_router(office.router, prefix="/api/office", tags=["Office"])
    app.include_router(oss_analysis.router, tags=["OSS Analysis"])
    app.include_router(system.router, prefix="/api/system", tags=["System"])
    app.include_router(dll.router, prefix="/api/llm", tags=["DLL"])
    app.include_router(markitdown.router, prefix="/api/markitdown", tags=["Markitdown"])


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
