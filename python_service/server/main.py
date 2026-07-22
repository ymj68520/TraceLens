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
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.api.auth import router as auth_router
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
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:  # pragma: no cover - depends on a live DB
        logger.error(f"Database initialization failed: {e}")
        raise

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
    app.include_router(auth_router)

    # Health check
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
        }

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
