"""
Tests for organization management API endpoints (``server.api.organizations``).

These tests exercise the full HTTP path for organization CRUD and registration
token management through ``TestClient``:

* ``POST   /api/organizations``                              - create org (success / duplicate -> 409)
* ``GET    /api/organizations``                              - list (super_admin sees all, others see own)
* ``GET    /api/organizations/{org_id}``                     - get one (success / cross-org -> 403 / missing -> 404)
* ``POST   /api/organizations/{org_id}/registration-tokens`` - issue token (success / missing org -> 404 / cross-org -> 403)
* ``GET    /api/organizations/{org_id}/registration-tokens`` - list tokens
* ``DELETE /api/organizations/registration-tokens/{token_id}`` - delete (success / missing -> 404 / cross-org -> 403)

Strategy
--------
The DB layer is stubbed with a :class:`~unittest.mock.MagicMock` session (the ORM
models use PostgreSQL-native ``JSONB`` / ``UUID`` types, so a live PostgreSQL
instance is not available in the test environment). This mirrors the approach in
``tests/test_auth_api.py`` and ``tests/test_auth_middleware.py``.

Authentication is short-circuited by overriding the ``get_current_user``
dependency with a configurable fake user. Because ``require_permission`` is a
factory whose closure depends on ``get_current_user``, the override also flows
through the permission-protected endpoints (create org, issue token, delete
token). This isolates these tests to the organizations endpoint logic; the auth
path itself is covered by ``tests/test_auth_api.py``.

The ``db.refresh`` mock has a side effect that simulates the database assigning
column defaults (``id``, ``created_at``, ``used_count``) after an insert, so that
newly-created ORM objects serialize cleanly through their response models.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.middleware.auth import get_current_user


# -----------------------------------------------------------------------------
# Shared fakes
# -----------------------------------------------------------------------------


class FakeUser:
    """Minimal stand-in for the ORM ``User`` carrying the attributes the
    organizations endpoints touch (``id``, ``org_id``, ``role``)."""

    def __init__(self, user_id=None, org_id=None, role="super_admin"):
        self.id = user_id or uuid.uuid4()
        self.org_id = org_id or uuid.uuid4()
        self.role = role


class FakeOrg:
    """Stand-in for an existing ``Organization`` row."""

    def __init__(self, org_id=None, name="Existing Org", subscription_tier="enterprise"):
        self.id = org_id or uuid.uuid4()
        self.name = name
        self.subscription_tier = subscription_tier
        self.settings = {}
        self.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)


class FakeToken:
    """Stand-in for an existing ``RegistrationToken`` row."""

    def __init__(self, token_id=None, org_id=None, token="reg-token-abc"):
        self.id = token_id or uuid.uuid4()
        self.org_id = org_id or uuid.uuid4()
        self.token = token
        self.max_clients = 10
        self.used_count = 0
        self.expires_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        self.created_by = uuid.uuid4()
        self.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)


_SENTINEL = object()


def _populate_defaults_on_refresh(obj):
    """``side_effect`` for the mocked ``db.refresh``.

    Simulates PostgreSQL assigning column defaults (Python/DB-side ``uuid.uuid4``,
    ``server_default=now()``, and ``used_count``) when a row is inserted. Without
    this, a newly-constructed ORM object would carry ``None`` for ``id`` /
    ``created_at`` / ``used_count`` and fail response-model validation.
    """
    if getattr(obj, "id", _SENTINEL) is None:
        obj.id = uuid.uuid4()
    if getattr(obj, "created_at", _SENTINEL) is None:
        obj.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    if getattr(obj, "used_count", _SENTINEL) is None:
        obj.used_count = 0


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """A mock SQLAlchemy session. Tests configure its query chains and attach the
    ``refresh`` default-populating side effect."""
    db = MagicMock()
    db.refresh.side_effect = _populate_defaults_on_refresh
    return db


@pytest.fixture
def client(mock_db):
    """TestClient with the DB dependency replaced by ``mock_db``.

    Authentication is intentionally left un-overridden here; each test installs
    the desired identity via :func:`auth_as` so the active user is explicit at
    the call site.
    """
    from server.db.session import get_db

    def _fake_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _fake_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()


def auth_as(user):
    """Install ``user`` as the authenticated identity by overriding
    ``get_current_user``. Also gates ``require_permission``-protected endpoints
    because their dependency closure resolves through ``get_current_user``."""
    async def _fake_current_user():
        return user

    app.dependency_overrides[get_current_user] = _fake_current_user


# -----------------------------------------------------------------------------
# POST /api/organizations
# -----------------------------------------------------------------------------


def test_create_organization_success(client, mock_db):
    """super_admin creates a new org -> 200 with id and echoed fields."""
    auth_as(FakeUser(role="super_admin"))
    # No existing org with this name.
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.post(
        "/api/organizations",
        json={"name": "Test Org", "subscription_tier": "enterprise"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Org"
    assert data["subscription_tier"] == "enterprise"
    assert "id" in data
    assert "created_at" in data
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once()


def test_create_duplicate_organization(client, mock_db):
    """Creating an org whose name already exists -> 409."""
    auth_as(FakeUser(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = FakeOrg(name="Dup Org")

    response = client.post(
        "/api/organizations",
        json={"name": "Dup Org", "subscription_tier": "enterprise"},
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
    mock_db.add.assert_not_called()


# -----------------------------------------------------------------------------
# GET /api/organizations
# -----------------------------------------------------------------------------


def test_list_organizations_super_admin(client, mock_db):
    """super_admin sees every organization (unfiltered query)."""
    auth_as(FakeUser(role="super_admin"))
    mock_db.query.return_value.all.return_value = [FakeOrg(name="Org A"), FakeOrg(name="Org B")]

    response = client.get("/api/organizations")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    # Unfiltered path: .all() is called directly on the query (no .filter()).
    mock_db.query.return_value.all.assert_called_once()


def test_list_organizations_scoped_to_own_org(client, mock_db):
    """A non-super_admin only sees their own organization."""
    org_id = uuid.uuid4()
    auth_as(FakeUser(org_id=org_id, role="org_admin"))
    mock_db.query.return_value.filter.return_value.all.return_value = [FakeOrg(org_id=org_id)]

    response = client.get("/api/organizations")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    # Scoped path: .all() is called on the filtered query.
    mock_db.query.return_value.filter.return_value.all.assert_called_once()


# -----------------------------------------------------------------------------
# GET /api/organizations/{org_id}
# -----------------------------------------------------------------------------


def test_get_organization_success(client, mock_db):
    """super_admin fetches an org by id -> 200."""
    org = FakeOrg(name="Fetchable Org")
    auth_as(FakeUser(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = org

    response = client.get(f"/api/organizations/{org.id}")

    assert response.status_code == 200
    assert response.json()["name"] == "Fetchable Org"


def test_get_organization_cross_org_forbidden(client, mock_db):
    """A non-super_admin fetching another org -> 403 before any DB lookup."""
    auth_as(FakeUser(org_id=uuid.uuid4(), role="org_admin"))

    response = client.get(f"/api/organizations/{uuid.uuid4()}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


def test_get_organization_not_found(client, mock_db):
    """super_admin fetching a missing org -> 404."""
    auth_as(FakeUser(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.get(f"/api/organizations/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Organization not found"


# -----------------------------------------------------------------------------
# POST /api/organizations/{org_id}/registration-tokens
# -----------------------------------------------------------------------------


def test_create_registration_token_success(client, mock_db):
    """super_admin issues a registration token -> 200 with token + max_clients."""
    org = FakeOrg()
    auth_as(FakeUser(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = org

    response = client.post(
        f"/api/organizations/{org.id}/registration-tokens",
        json={"org_id": str(org.id), "max_clients": 10, "expires_in_hours": 720},
    )

    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert len(data["token"]) > 0
    assert data["max_clients"] == 10
    assert "expires_at" in data
    assert data["used_count"] == 0
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


def test_create_registration_token_org_not_found(client, mock_db):
    """Issuing a token for a missing org -> 404."""
    auth_as(FakeUser(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    org_id = uuid.uuid4()
    response = client.post(
        f"/api/organizations/{org_id}/registration-tokens",
        json={"org_id": str(org_id), "max_clients": 5, "expires_in_hours": 168},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Organization not found"


def test_create_registration_token_cross_org_forbidden(client, mock_db):
    """A non-super_admin issuing a token for another org -> 403."""
    auth_as(FakeUser(org_id=uuid.uuid4(), role="org_admin"))

    response = client.post(
        f"/api/organizations/{uuid.uuid4()}/registration-tokens",
        json={"org_id": str(uuid.uuid4()), "max_clients": 5, "expires_in_hours": 168},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


# -----------------------------------------------------------------------------
# GET /api/organizations/{org_id}/registration-tokens
# -----------------------------------------------------------------------------


def test_list_registration_tokens(client, mock_db):
    """Listing tokens for an org returns the org's tokens."""
    org = FakeOrg()
    auth_as(FakeUser(org_id=org.id, role="org_admin"))
    mock_db.query.return_value.filter.return_value.all.return_value = [FakeToken(org_id=org.id)]

    response = client.get(f"/api/organizations/{org.id}/registration-tokens")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert "token" in data[0]


# -----------------------------------------------------------------------------
# DELETE /api/organizations/registration-tokens/{token_id}
# -----------------------------------------------------------------------------


def test_delete_registration_token_success(client, mock_db):
    """super_admin deletes a token -> 200 success message."""
    token = FakeToken()
    auth_as(FakeUser(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = token

    response = client.delete(f"/api/organizations/registration-tokens/{token.id}")

    assert response.status_code == 200
    assert response.json()["message"] == "Registration token deleted"
    mock_db.delete.assert_called_once_with(token)
    mock_db.commit.assert_called_once()


def test_delete_registration_token_not_found(client, mock_db):
    """Deleting a missing token -> 404."""
    auth_as(FakeUser(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.delete(f"/api/organizations/registration-tokens/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Registration token not found"


def test_delete_registration_token_cross_org_forbidden(client, mock_db):
    """A non-super_admin deleting another org's token -> 403."""
    token = FakeToken(org_id=uuid.uuid4())
    auth_as(FakeUser(org_id=uuid.uuid4(), role="org_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = token

    response = client.delete(f"/api/organizations/registration-tokens/{token.id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"
    mock_db.delete.assert_not_called()


if __name__ == "__main__":
    import pytest as _pytest

    _pytest.main([__file__, "-v"])
