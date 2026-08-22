"""
TraceLens Server - FastAPI application entry point.

Assembles the API routers (authentication, and future modules) into a single
application and wires in the cross-cutting infrastructure:

* :mod:`server.config`      - environment-based settings
* CORS middleware            - browser access for the web UI
* a global exception handler - turns unhandled errors into a generic 500
* a lifespan handler         - initializes the database on startup
* ``/health`` and ``/``      - liveness / discovery endpoints

A module-level ``app`` is exposed for ASGI servers and for
``from server.main import app`` in tests::

    uvicorn server.main:app --reload

A ``create_app`` factory is also provided so callers (e.g. future wiring or
tests) can construct a fresh application instance with overridden settings.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.api.auth import router as auth_router
from server.api.clients import router as clients_router
from server.api.commands import router as commands_router
from server.api.organizations import router as organizations_router
from server.api.results import router as results_router
from server.api.tasks import router as tasks_router
from server.config import settings
from server.db.session import init_db

# Configure logging.
# DEBUG in development lets request/session logs surface; production keeps the
# noise down at INFO.
logging.basicConfig(
    level=logging.INFO if settings.ENVIRONMENT == "production" else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
_db_available = False
_db_error: str | None = None


async def initialize_database() -> bool:
    """Run synchronous schema creation without blocking the event loop."""
    global _db_available, _db_error
    try:
        await asyncio.wait_for(
            asyncio.to_thread(init_db),
            timeout=settings.DB_STARTUP_TIMEOUT,
        )
    except asyncio.TimeoutError:
        _db_available = False
        _db_error = "database initialization timed out"
        logger.error(
            "Database initialization exceeded DB_STARTUP_TIMEOUT=%ss; "
            "the driver timeout bounds the underlying connection attempt",
            settings.DB_STARTUP_TIMEOUT,
        )
        return False
    except Exception as exc:  # pragma: no cover - depends on external DB
        _db_available = False
        _db_error = type(exc).__name__
        logger.error("Database initialization failed", exc_info=True)
        return False
    _db_available = True
    _db_error = None
    logger.info("Database initialized successfully")
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    On startup it initializes the database (creating any missing tables). On
    shutdown it only logs; the SQLAlchemy engine's connection pool is reaped
    on interpreter exit.
    """
    # Startup
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")

    try:
        await initialize_database()
    except Exception:  # defensive: startup must remain bounded/degraded
        logger.error("Unexpected database startup failure", exc_info=True)

    yield

    # Shutdown
    logger.info("Shutting down application")


def create_app() -> FastAPI:
    """
    Create and configure the TraceLens FastAPI application.

    Returns:
        A configured :class:`~fastapi.FastAPI` instance with middleware,
        exception handlers, and all routers mounted.
    """
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Multi-tenant forensic analysis platform API. "
            "Authentication is provided via JWT bearer tokens."
        ),
        lifespan=lifespan,
    )

    # CORS middleware - allows the configured web UI origins to call the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handler.
    # Starlette's ExceptionMiddleware handles HTTPException / RequestValidationError
    # before this handler, so authentication 401/403 and validation 422 responses
    # pass through unchanged; only genuinely unhandled errors are masked as 500.
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Global exception handler - log the real error, return a generic 500."""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # Mount routers.
    # The auth router already declares ``prefix="/api/auth"``, so it is mounted
    # without an additional prefix to avoid a doubled ``/api/auth/api/auth/...``.
    # The organizations and clients routers likewise declare their own prefixes.
    app.include_router(auth_router)
    app.include_router(organizations_router)
    app.include_router(clients_router)
    app.include_router(commands_router)
    app.include_router(tasks_router)
    app.include_router(results_router)

    # Health check
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "database": "available" if _db_available else "degraded",
        }

    @app.get("/health/ready", tags=["Health"])
    async def readiness_check():
        """Report dependency readiness without affecting liveness."""
        if _db_available:
            return {"ready": True, "database": "available"}
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "ready": False,
                "database": "unavailable",
                "error": _db_error,
            },
        )

    # Root
    @app.get("/", tags=["Root"])
    async def root():
        """Root endpoint - service discovery."""
        return {
            "message": "TraceLens Server API",
            "version": settings.APP_VERSION,
            "docs": "/docs",
        }

    return app


# Module-level application instance for ASGI servers and test imports.
app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "server.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.ENVIRONMENT == "development",
        log_level="info",
    )
