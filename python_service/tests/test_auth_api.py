"""
Tests for authentication API endpoints (``server.api.auth``).

These tests exercise the full HTTP path for the login, refresh, and current-user
endpoints through ``TestClient``:

* ``POST /api/auth/login``  - OAuth2 password flow (success / wrong password /
  unknown user / login-by-email / last_login update)
* ``POST /api/auth/refresh`` - fresh token issuance for an authenticated user
* ``GET  /api/auth/me``     - current-user profile
* protection of authenticated routes (missing token -> 401)

Strategy
--------
The database layer is stubbed with a :class:`~unittest.mock.MagicMock` session
so the tests do not require a live PostgreSQL instance (the ORM models use
PostgreSQL-native ``JSONB`` / ``UUID`` types). This mirrors the approach taken
in ``tests/test_auth_middleware.py``. The mock session is injected two ways:

* FastAPI ``app.dependency_overrides`` replaces the ``get_db`` dependency used
  by the login endpoint.
* ``server.db.session.get_db`` is monkeypatched so the middleware's lazy
  ``get_db`` import (used by ``get_current_user``) resolves to the same mock.

Both resolve to the same mock instance, so a user returned by login is also
resolved by the token-verification path.

Environment note
----------------
The auth service selects ``HS256`` only when ``ENVIRONMENT == "development"``.
``setdefault`` is used so token creation and verification share a symmetric
algorithm; an externally-configured value (e.g. an RS256 integration env) is
preserved.
"""
import os

# Select the HS256 development path so tokens created/verified here match.
os.environ.setdefault("ENVIRONMENT", "development")

import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.services.auth_service import hash_password, verify_token


# -----------------------------------------------------------------------------
# Shared fakes
# -----------------------------------------------------------------------------


class FakeUser:
    """Minimal stand-in for the ORM ``User`` carrying every attribute the auth
    endpoints and middleware touch."""

    def __init__(
        self,
        user_id=None,
        org_id=None,
        username="testuser",
        email="test@example.com",
        password=None,
        role="analyst",
    ):
        self.id = user_id or uuid.uuid4()
        self.org_id = org_id or uuid.uuid4()
        self.username = username
        self.email = email
        # Real bcrypt hash so verify_password exercises the real code path.
        self.password_hash = password or hash_password("testpass123")
        self.role = role
        self.created_at = datetime(2024, 1, 1, 0, 0, 0)
        self.last_login = None


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """A mock SQLAlchemy session shared across the endpoint and middleware
    within a single test. Tests configure its ``.query().filter().first()``
    return value to suit the scenario."""
    return MagicMock()


@pytest.fixture
def test_user():
    """A standalone test user (used both as the DB lookup result and as the
    source of identity for token creation)."""
    return FakeUser(role="analyst")


@pytest.fixture
def client(mock_db, monkeypatch):
    """TestClient with the DB dependency replaced by ``mock_db``.

    Patches both the FastAPI ``get_db`` dependency (for the login endpoint) and
    ``server.db.session.get_db`` (for the middleware's lazy lookup) so every
    code path resolves to the same mock session.
    """
    import server.db.session as session_module
    from server.api.auth import get_db as auth_get_db

    def _fake_get_db():
        yield mock_db

    monkeypatch.setattr(session_module, "get_db", _fake_get_db)
    app.dependency_overrides[auth_get_db] = _fake_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()


def _login(client, username="testuser", password="testpass123"):
    """Helper: POST credentials and return the response."""
    return client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )


# -----------------------------------------------------------------------------
# POST /api/auth/login
# -----------------------------------------------------------------------------


def test_login_success(client, mock_db, test_user):
    """Valid credentials -> 200 with a bearer token of the expected shape."""
    mock_db.query.return_value.filter.return_value.first.return_value = test_user

    response = _login(client)

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 3600

    # The issued token must verify and carry the authenticated user's identity.
    payload = verify_token(data["access_token"])
    assert payload is not None
    assert payload["user_id"] == str(test_user.id)
    assert payload["org_id"] == str(test_user.org_id)
    assert payload["role"] == "analyst"
    assert payload["type"] == "user"


def test_login_wrong_password(client, mock_db, test_user):
    """Wrong password -> 401 with a non-leaking error message."""
    mock_db.query.return_value.filter.return_value.first.return_value = test_user

    response = _login(client, password="wrongpass")

    assert response.status_code == 401
    body = response.json()
    assert "detail" in body
    # Error message must not reveal which field was wrong.
    assert body["detail"] == "Incorrect username or password"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_login_nonexistent_user(client, mock_db):
    """Unknown username -> 401 (same message as wrong password)."""
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = _login(client, username="nonexistent", password="testpass")

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"


def test_login_by_email(client, mock_db, test_user):
    """Login accepts the email address in the username field."""
    mock_db.query.return_value.filter.return_value.first.return_value = test_user

    response = _login(client, username="test@example.com")

    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_updates_last_login(client, mock_db, test_user):
    """A successful login stamps ``last_login`` and commits the session."""
    mock_db.query.return_value.filter.return_value.first.return_value = test_user
    assert test_user.last_login is None

    response = _login(client)

    assert response.status_code == 200
    assert test_user.last_login is not None
    mock_db.commit.assert_called_once()


# -----------------------------------------------------------------------------
# GET /api/auth/me
# -----------------------------------------------------------------------------


def test_get_current_user(client, mock_db, test_user):
    """An authenticated request returns the caller's profile."""
    mock_db.query.return_value.filter.return_value.first.return_value = test_user

    login_response = _login(client)
    token = login_response.json()["access_token"]

    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"
    assert data["role"] == "analyst"
    assert data["org_id"] == str(test_user.org_id)


def test_unauthorized_access(client):
    """No Authorization header -> 401 Unauthorized.

    The route is protected by HTTPBearer; Starlette returns 401 (with
    ``WWW-Authenticate: Bearer``) for missing bearer credentials.
    """
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


# -----------------------------------------------------------------------------
# POST /api/auth/refresh
# -----------------------------------------------------------------------------


def test_refresh_token(client, mock_db, test_user):
    """Refresh issues a new, distinct, valid token for the caller."""
    mock_db.query.return_value.filter.return_value.first.return_value = test_user

    login_response = _login(client)
    old_token = login_response.json()["access_token"]

    response = client.post(
        "/api/auth/refresh", headers={"Authorization": f"Bearer {old_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    new_token = data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 3600
    assert new_token != old_token

    # New token must still verify and identify the same user.
    payload = verify_token(new_token)
    assert payload is not None
    assert payload["user_id"] == str(test_user.id)


def test_refresh_requires_auth(client):
    """Refresh without a token -> 401."""
    response = client.post("/api/auth/refresh")

    assert response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
