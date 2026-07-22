"""
Integration tests for the assembled FastAPI application (``server.main``).

These tests verify Task 7 wiring - that all the authentication components built
in Tasks 4-6 are correctly mounted into a single runnable application:

* ``GET /health`` and ``GET /``          - liveness / discovery endpoints
* CORS middleware                        - preflight responses for the web UI
* the auth router is mounted             - ``/api/auth/login`` exists (not 404)
* the global exception handler           - unhandled errors -> generic 500
* app identity comes from ``settings``   - title / version

None of these tests require a live database: ``/health`` and ``/`` do not touch
the DB, the auth-route presence check relies on FastAPI's 422 form-validation
response (issued before the DB session is opened), and the exception-handler
test builds a throwaway app with an intentionally broken route. ``TestClient`` is
constructed without a ``with`` block so the application lifespan (which calls
``init_db``) is not triggered.
"""
import os

# Select the HS256 development path so any token creation/verification is
# consistent with the rest of the auth test-suite.
os.environ.setdefault("ENVIRONMENT", "development")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from server.config import settings
from server.main import app, create_app


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def client():
    """TestClient for the module-level app.

    No ``with`` block: we deliberately avoid running the lifespan so that
    ``init_db`` (which connects to PostgreSQL) is never called.
    """
    return TestClient(app)


# -----------------------------------------------------------------------------
# Health & discovery endpoints
# -----------------------------------------------------------------------------


def test_health_check(client):
    """``GET /health`` reports healthy status with app identity."""
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["app"] == settings.APP_NAME
    assert body["version"] == settings.APP_VERSION


def test_root_endpoint(client):
    """``GET /`` returns service discovery metadata."""
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "TraceLens Server API"
    assert body["version"] == settings.APP_VERSION
    assert body["docs"] == "/docs"


# -----------------------------------------------------------------------------
# App identity
# -----------------------------------------------------------------------------


def test_app_identity_from_settings():
    """The FastAPI app's title/version are driven by the settings instance."""
    assert app.title == settings.APP_NAME
    assert app.version == settings.APP_VERSION


def test_openapi_docs_available(client):
    """The OpenAPI schema is published (auth router is reflected in paths)."""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == settings.APP_NAME
    assert schema["info"]["version"] == settings.APP_VERSION
    # The auth router is wired in, so its endpoints must appear in the schema.
    assert "/api/auth/login" in schema["paths"]
    assert "/api/auth/refresh" in schema["paths"]
    assert "/api/auth/me" in schema["paths"]


# -----------------------------------------------------------------------------
# Auth router integration
# -----------------------------------------------------------------------------


def test_auth_login_route_exists(client):
    """``POST /api/auth/login`` is mounted - returns 422 (missing form fields),
    not 404.

    The 422 is produced by FastAPI validating the OAuth2PasswordRequestForm
    before any database session is opened, so no PostgreSQL connection is
    needed to confirm the route exists.
    """
    response = client.post("/api/auth/login")

    assert response.status_code != 404
    assert response.status_code == 422


# -----------------------------------------------------------------------------
# CORS
# -----------------------------------------------------------------------------


def test_cors_preflight_allows_configured_origin():
    """A preflight from a whitelisted origin is accepted with permissive CORS
    headers."""
    origin = settings.CORS_ORIGINS[0]
    transport = TestClient(app)

    response = transport.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "GET" in response.headers["access-control-allow-methods"]
    # allow-credentials is reflected because we configured allow_credentials=True
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_simple_request_sets_allow_origin():
    """A simple GET from a whitelisted origin receives an allow-origin header."""
    origin = settings.CORS_ORIGINS[0]
    transport = TestClient(app)

    response = transport.get("/health", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


# -----------------------------------------------------------------------------
# Global exception handler
# -----------------------------------------------------------------------------


def test_global_exception_handler_masks_unhandled_errors():
    """An unhandled exception in a route is logged and returned as a generic
    500 with a non-revealing body.

    Uses a throwaway app (so the broken route is not registered globally) built
    via ``create_app`` to prove the handler is wired up by the factory.
    """
    broken = create_app()

    @broken.get("/_boom")
    async def _boom():
        raise RuntimeError("something exploded internally")

    transport = TestClient(broken, raise_server_exceptions=False)

    response = transport.get("/_boom")

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error"
    # The internal error message must never leak to the client.
    assert "something exploded" not in response.text


def test_global_exception_handler_preserves_http_exceptions():
    """``HTTPException`` raised by routes is handled by Starlette's HTTP
    exception handler (status + detail preserved), NOT swallowed by the generic
    500 handler. This is what keeps auth 401 responses working."""
    app2 = create_app()

    @app2.get("/_forbidden")
    async def _forbidden():
        raise HTTPException(status_code=403, detail="Not allowed")

    transport = TestClient(app2)

    response = transport.get("/_forbidden")

    assert response.status_code == 403
    assert response.json()["detail"] == "Not allowed"
