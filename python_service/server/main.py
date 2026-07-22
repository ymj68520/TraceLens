"""
FastAPI application entry point for the TraceLens server.

Assembles the API routers (authentication, and future modules) into a single
application. A module-level ``app`` is exposed for ASGI servers and for
``from server.main import app`` in tests:

    uvicorn server.main:app --reload

A ``create_app`` factory is also provided so callers (e.g. future wiring or
tests) can construct a fresh application instance with overridden settings.
"""
from fastapi import FastAPI

from server.api.auth import router as auth_router


def create_app() -> FastAPI:
    """
    Create and configure the TraceLens FastAPI application.

    Returns:
        A configured :class:`~fastapi.FastAPI` instance with all routers
        mounted.
    """
    app = FastAPI(
        title="TraceLens API",
        description=(
            "Multi-tenant forensic analysis platform API. "
            "Authentication is provided via JWT bearer tokens."
        ),
        version="0.1.0",
    )

    # Mount routers
    app.include_router(auth_router)

    return app


# Module-level application instance for ASGI servers and test imports.
app = create_app()
