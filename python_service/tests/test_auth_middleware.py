"""
Tests for JWT authentication middleware (``server.middleware.auth``).

These tests verify the FastAPI dependency-injection helpers:

* ``get_current_user``  - user-token resolution + 401 on invalid/wrong-type/missing-user
* ``get_current_client`` - client-token resolution + 401 on wrong-type/missing-client
* ``get_optional_user``  - degrades to ``None`` when absent/invalid
* ``require_permission`` - permission dependency factory

Strategy
--------
A minimal FastAPI application is built with one route per dependency and driven
through ``TestClient`` so the full HTTP path (Authorization header parsing,
HTTPBearer auto-error behaviour, dependency resolution) is exercised. The
database layer is stubbed by monkeypatching ``server.db.session.get_db`` to yield
a :class:`~unittest.mock.MagicMock` session, so no real PostgreSQL instance is
required.

A second group of tests calls the async dependencies directly with constructed
:class:`HTTPAuthorizationCredentials` and an injected mock session, isolating
the auth logic from the HTTP layer.

Environment note
----------------
The auth service selects ``HS256`` only when ``ENVIRONMENT == "development"``.
Tests set this before importing the middleware so token creation and
verification use a consistent symmetric algorithm.
"""
import os

# Select the HS256 development path so tokens created here verify correctly.
os.environ.setdefault("ENVIRONMENT", "development")

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from server.middleware.auth import (
    get_current_client,
    get_current_user,
    get_optional_user,
    require_permission,
)
from server.services.auth_service import (
    create_client_token,
    create_user_token,
    jwt,
    JWT_SECRET_KEY,
)


# -----------------------------------------------------------------------------
# Shared fakes
# -----------------------------------------------------------------------------


class FakeUser:
    """Minimal stand-in for the ORM ``User`` with the attributes the
    middleware / test routes touch."""

    def __init__(self, user_id=None, role="analyst"):
        self.id = user_id or uuid.uuid4()
        self.role = role


class FakeClient:
    """Minimal stand-in for the ORM ``Client``."""

    def __init__(self, client_id=None):
        self.id = client_id or uuid.uuid4()


def _make_db(return_value):
    """Build a mock DB session whose ``query(...).filter(...).first()`` chain
    resolves to ``return_value`` (a User, a Client, or ``None``).

    ``auth_service.get_user_from_token`` does
    ``db.query(User).filter(User.id == ...).first()``
    and the client variant is analogous, so a single generic chain suffices.
    """
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = return_value
    return db


# -----------------------------------------------------------------------------
# Test app + fixtures
# -----------------------------------------------------------------------------


def _build_app():
    """Create a minimal FastAPI app exposing one route per dependency."""
    app = FastAPI()

    @app.get("/user")
    async def user_route(user=Depends(get_current_user)):
        return {"id": str(user.id), "role": user.role}

    @app.get("/client")
    async def client_route(client=Depends(get_current_client)):
        return {"id": str(client.id)}

    @app.get("/optional")
    async def optional_route(user=Depends(get_optional_user)):
        return {"user": str(user.id) if user else None}

    @app.get("/perm")
    async def perm_route(user=Depends(require_permission("manage_users"))):
        return {"id": str(user.id), "role": user.role}

    return app


@pytest.fixture
def fake_user():
    return FakeUser(role="analyst")


@pytest.fixture
def fake_client():
    return FakeClient()


@pytest.fixture
def patched_db(monkeypatch):
    """Monkeypatch ``server.db.session.get_db`` to yield a mock DB session and
    return the mock so individual tests can configure its return value.

    The middleware imports ``get_db`` lazily inside each dependency, so
    patching the module attribute is sufficient.
    """
    import server.db.session as session_module

    db = MagicMock()

    def _fake_get_db():
        yield db

    monkeypatch.setattr(session_module, "get_db", _fake_get_db)
    return db


@pytest.fixture
def client():
    """TestClient for the minimal auth app (no DB override; routes that hit the
    DB should be used together with ``patched_db``)."""
    return TestClient(_build_app())


# -----------------------------------------------------------------------------
# get_current_user
# -----------------------------------------------------------------------------


def test_get_current_user_valid_token(client, patched_db, fake_user):
    """A valid user token resolves to the authenticated user."""
    token = create_user_token(fake_user.id, uuid.uuid4(), "analyst", ["view"])
    patched_db.query.return_value.filter.return_value.first.return_value = fake_user

    resp = client.get("/user", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(fake_user.id)
    assert body["role"] == "analyst"


def test_get_current_user_no_credentials(client):
    """Missing Authorization header -> 401 (HTTPBearer rejects unauthenticated).

    Newer Starlette returns 401 Unauthorized (with WWW-Authenticate) for missing
    bearer credentials rather than the legacy 403; both indicate the route is
    protected, so we assert the unauthenticated status here.
    """
    resp = client.get("/user")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_get_current_user_invalid_token(client, patched_db):
    """A malformed token -> 401 invalid credentials."""
    resp = client.get("/user", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid authentication credentials"
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_get_current_user_wrong_token_type(client, patched_db, fake_client):
    """A client token presented to a user route -> 401 'User token required'."""
    token = create_client_token(fake_client.id, uuid.uuid4(), {})
    resp = client.get("/user", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "User token required"


def test_get_current_user_not_found(client, patched_db, fake_user):
    """Valid user token but user missing from DB -> 401 'User not found'."""
    token = create_user_token(fake_user.id, uuid.uuid4(), "analyst", [])
    patched_db.query.return_value.filter.return_value.first.return_value = None

    resp = client.get("/user", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "User not found"


def test_get_current_user_expired_token(client, patched_db):
    """An expired token -> 401 invalid credentials (verify_token returns None)."""
    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "user_id": str(uuid.uuid4()),
        "org_id": str(uuid.uuid4()),
        "role": "analyst",
        "permissions": [],
        "iat": (now - dt.timedelta(hours=2)).timestamp(),
        "exp": (now - dt.timedelta(hours=1)).timestamp(),
        "type": "user",
    }
    expired = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")

    resp = client.get("/user", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid authentication credentials"


# -----------------------------------------------------------------------------
# get_current_client
# -----------------------------------------------------------------------------


def test_get_current_client_valid_token(client, patched_db, fake_client):
    """A valid client token resolves to the authenticated client."""
    token = create_client_token(fake_client.id, uuid.uuid4(), {"max_concurrent_tasks": 2})
    patched_db.query.return_value.filter.return_value.first.return_value = fake_client

    resp = client.get("/client", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["id"] == str(fake_client.id)


def test_get_current_client_wrong_token_type(client, patched_db, fake_user):
    """A user token presented to a client route -> 401 'Client token required'."""
    token = create_user_token(fake_user.id, uuid.uuid4(), "analyst", [])
    resp = client.get("/client", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Client token required"


def test_get_current_client_not_found(client, patched_db, fake_client):
    """Valid client token but client missing from DB -> 401 'Client not found'."""
    token = create_client_token(fake_client.id, uuid.uuid4(), {})
    patched_db.query.return_value.filter.return_value.first.return_value = None

    resp = client.get("/client", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Client not found"


def test_get_current_client_invalid_token(client, patched_db):
    """A malformed token on a client route -> 401 invalid credentials."""
    resp = client.get("/client", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid authentication credentials"


# -----------------------------------------------------------------------------
# get_optional_user
# -----------------------------------------------------------------------------


def test_get_optional_user_no_credentials(client):
    """No Authorization header -> 200 with user null (never raises)."""
    resp = client.get("/optional")
    assert resp.status_code == 200
    assert resp.json() == {"user": None}


def test_get_optional_user_valid_token(client, patched_db, fake_user):
    """Valid user token -> user resolved."""
    token = create_user_token(fake_user.id, uuid.uuid4(), "analyst", [])
    patched_db.query.return_value.filter.return_value.first.return_value = fake_user

    resp = client.get("/optional", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user"] == str(fake_user.id)


def test_get_optional_user_invalid_token(client, patched_db):
    """Invalid token is swallowed -> 200 with user null."""
    resp = client.get("/optional", headers={"Authorization": "Bearer bad-token"})
    assert resp.status_code == 200
    assert resp.json() == {"user": None}


def test_get_optional_user_wrong_token_type(client, patched_db, fake_client):
    """A client token is rejected by get_current_user but the optional helper
    degrades to None instead of raising."""
    token = create_client_token(fake_client.id, uuid.uuid4(), {})
    resp = client.get("/optional", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"user": None}


# -----------------------------------------------------------------------------
# require_permission
# -----------------------------------------------------------------------------


def test_require_permission_super_admin(client, patched_db):
    """A super_admin satisfies any permission requirement."""
    admin = FakeUser(role="super_admin")
    token = create_user_token(admin.id, uuid.uuid4(), "super_admin", ["*"])
    patched_db.query.return_value.filter.return_value.first.return_value = admin

    resp = client.get("/perm", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "super_admin"


def test_require_permission_requires_user_token(client, patched_db, fake_user):
    """require_permission builds on get_current_user, so a client token is
    rejected with 401 before the permission check runs."""
    token = create_client_token(uuid.uuid4(), uuid.uuid4(), {})
    resp = client.get("/perm", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# -----------------------------------------------------------------------------
# Direct unit tests (bypass HTTP, call the async deps directly)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_direct(fake_user):
    """Calling the dependency directly with constructed credentials and an
    injected mock db returns the user (no get_db lookup needed)."""
    token = create_user_token(fake_user.id, uuid.uuid4(), "analyst", ["x"])
    db = _make_db(fake_user)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(creds, db)
    assert user is fake_user


@pytest.mark.asyncio
async def test_get_current_user_direct_wrong_type_raises():
    """Direct call with a client token raises fastapi.HTTPException (401)."""
    from fastapi import HTTPException

    token = create_client_token(uuid.uuid4(), uuid.uuid4(), {})
    db = _make_db(None)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc:
        await get_current_user(creds, db)
    assert exc.value.status_code == 401
    assert exc.value.detail == "User token required"


@pytest.mark.asyncio
async def test_get_current_client_direct(fake_client):
    """Direct call resolves a client token to the client object."""
    token = create_client_token(fake_client.id, uuid.uuid4(), {})
    db = _make_db(fake_client)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    client_obj = await get_current_client(creds, db)
    assert client_obj is fake_client


@pytest.mark.asyncio
async def test_get_optional_user_direct_none():
    """Direct call with no credentials returns None."""
    user = await get_optional_user(None, None)
    assert user is None


@pytest.mark.asyncio
async def test_require_permission_dependency_returns_user():
    """The generated permission dependency returns the user it depends on."""
    admin = FakeUser(role="super_admin")
    dep = require_permission("do_anything")
    result = await dep(current_user=admin)
    assert result is admin


# -----------------------------------------------------------------------------
# Header / scheme behaviour
# -----------------------------------------------------------------------------


def test_wrong_auth_scheme_rejected(client, patched_db):
    """HTTPBearer only accepts the 'Bearer' scheme -> 401 for other schemes."""
    resp = client.get("/user", headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"
