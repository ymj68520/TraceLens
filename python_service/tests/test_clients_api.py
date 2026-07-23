"""
Tests for client registration and management API endpoints (``server.api.clients``).

These tests exercise the full HTTP path for the client lifecycle through
``TestClient``:

* ``POST   /api/clients/register``              - enroll via registration token
  (success / invalid token / expired / max-clients / duplicate hostname)
* ``GET    /api/clients``                        - list (super_admin all, org_admin
  own-org, a client sees only itself)
* ``GET    /api/clients/{client_id}``            - get one (success / 404 / 403
  cross-org / client-self / client-other)
* ``DELETE /api/clients/{client_id}``            - delete (insufficient role /
  404 / success / cross-org 403)
* ``POST   /api/clients/{client_id}/index-images`` - index (wrong client 403 /
  new images / update existing)
* ``GET    /api/clients/{client_id}/images``     - list images (404 / success)

Strategy
--------
The DB layer is stubbed with a :class:`~unittest.mock.MagicMock` session (the ORM
models use PostgreSQL-native ``JSONB`` / ``UUID`` types, so no live DB is
available) — the same approach as ``tests/test_organizations_api.py`` and
``tests/test_auth_api.py``.

Authentication identities are real ORM ``User`` / ``Client`` instances so the
endpoints' ``isinstance(current_user, Client/User)`` checks resolve truthfully.
The ``get_current_user`` / ``get_current_client`` dependencies are overridden
per-test via ``auth_as`` / ``client_as``.

``register`` is unauthenticated; its two DB lookups (token, then existing client)
are sequenced via a ``side_effect`` list so each query returns the right value.
"""
import os

# Select the HS256 development path so client tokens created/verified here match.
os.environ.setdefault("ENVIRONMENT", "development")

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.middleware.auth import get_current_client, get_current_user
from server.models.database import Client, DiskImage, RegistrationToken, User
from server.services.auth_service import verify_token


# -----------------------------------------------------------------------------
# ORM instance factories (transient — never added to a real session)
# -----------------------------------------------------------------------------


def _user(role="super_admin", org_id=None):
    return User(
        id=uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        username="admin",
        email="admin@example.com",
        password_hash="x",
        role=role,
    )


def _client(client_id=None, org_id=None, hostname="station-01", status="online"):
    return Client(
        id=client_id or uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        hostname=hostname,
        status=status,
        capabilities={"max_concurrent_tasks": 2, "supported_formats": ["E01", "DD"]},
        version="1.0.0",
        last_poll=None,
        last_seen=None,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _token(org_id=None, expires_in_hours=720, used_count=0, max_clients=10):
    return RegistrationToken(
        id=uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        token=secrets.token_urlsafe(32),
        max_clients=max_clients,
        used_count=used_count,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=expires_in_hours),
        created_by=uuid.uuid4(),
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _disk_image(client_id=None, path="/images/disk.e01"):
    return DiskImage(
        id=uuid.uuid4(),
        client_id=client_id or uuid.uuid4(),
        path=path,
        size_bytes=1024,
        format="E01",
        md5_hash="a" * 32,
        image_metadata={"fs": "ntfs"},
        indexed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def client(mock_db):
    """TestClient with the DB dependency replaced by ``mock_db``. Authentication
    is intentionally left un-overridden; tests install identities via
    :func:`auth_as` / :func:`client_as`."""
    from server.db.session import get_db

    def _fake_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _fake_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()


def auth_as(user):
    """Install ``user`` (a User) as the authenticated identity."""
    async def _override():
        return user

    app.dependency_overrides[get_current_user] = _override


def client_as(cli):
    """Install ``cli`` (a Client) as the authenticated client identity."""
    async def _override():
        return cli

    app.dependency_overrides[get_current_client] = _override


def _register_payload(token, hostname="forensic-station-01"):
    return {
        "registration_token": token,
        "hostname": hostname,
        "capabilities": {
            "max_concurrent_tasks": 2,
            "supported_formats": ["E01", "DD"],
            "version": "1.0.0",
        },
    }


# -----------------------------------------------------------------------------
# POST /api/clients/register
# -----------------------------------------------------------------------------


def test_register_client_success(client, mock_db):
    """Valid token + new hostname -> 200 with client_id, a real client JWT, and
    poll_interval 10. Token usage is incremented."""
    token = _token()
    # First .first() -> token; second .first() -> no existing client.
    mock_db.query.return_value.filter.return_value.first.side_effect = [token, None]

    response = client.post("/api/clients/register", json=_register_payload(token.token))

    assert response.status_code == 200
    data = response.json()
    assert "client_id" in data
    assert "jwt_token" in data
    assert data["poll_interval"] == 10
    assert "server_url" in data

    # The issued JWT is a real, verifiable client token carrying our identity.
    payload = verify_token(data["jwt_token"])
    assert payload is not None
    assert payload["type"] == "client"
    assert payload["client_id"] == data["client_id"]

    # Token usage was incremented and the client was persisted.
    assert token.used_count == 1
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


def test_register_client_invalid_token(client, mock_db):
    """Unknown registration token -> 401."""
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.post("/api/clients/register", json=_register_payload("bogus"))

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid registration token"
    mock_db.add.assert_not_called()


def test_register_client_expired_token(client, mock_db):
    """Expired token -> 401 with 'expired' in the detail."""
    token = _token(expires_in_hours=-1)  # already expired
    mock_db.query.return_value.filter.return_value.first.return_value = token

    response = client.post("/api/clients/register", json=_register_payload(token.token))

    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()
    mock_db.add.assert_not_called()


def test_register_client_max_clients_reached(client, mock_db):
    """Token at its client cap -> 401."""
    token = _token(used_count=10, max_clients=10)
    mock_db.query.return_value.filter.return_value.first.return_value = token

    response = client.post("/api/clients/register", json=_register_payload(token.token))

    assert response.status_code == 401
    assert "maximum" in response.json()["detail"].lower()
    mock_db.add.assert_not_called()


def test_register_duplicate_client(client, mock_db):
    """Same hostname already registered in the org -> 409."""
    token = _token()
    # First .first() -> token; second .first() -> existing client collision.
    mock_db.query.return_value.filter.return_value.first.side_effect = [token, _client(org_id=token.org_id)]

    response = client.post("/api/clients/register", json=_register_payload(token.token))

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
    mock_db.add.assert_not_called()


# -----------------------------------------------------------------------------
# GET /api/clients
# -----------------------------------------------------------------------------


def test_list_clients_super_admin(client, mock_db):
    """super_admin lists all clients (unfiltered query)."""
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.all.return_value = [_client(hostname="a"), _client(hostname="b")]

    response = client.get("/api/clients")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    mock_db.query.return_value.all.assert_called_once()


def test_list_clients_org_admin_scoped(client, mock_db):
    """org_admin is scoped to their own org (filtered query)."""
    org_id = uuid.uuid4()
    auth_as(_user(role="org_admin", org_id=org_id))
    mock_db.query.return_value.filter.return_value.all.return_value = [_client(org_id=org_id)]

    response = client.get("/api/clients")

    assert response.status_code == 200
    assert len(response.json()) == 1
    mock_db.query.return_value.filter.return_value.all.assert_called_once()


def test_list_clients_client_sees_only_self(client, mock_db):
    """When the authenticated identity is a Client, it sees only its own record.

    Note: ``list_clients`` depends on ``get_current_user`` (user-token only), so
    the ``isinstance(current_user, Client)`` branch is exercised here by
    overriding ``get_current_user`` to return a Client. Under real auth a client
    token is rejected by ``get_current_user`` before reaching this branch — see
    the report's forward observation.
    """
    cli = _client(hostname="me")
    auth_as(cli)

    response = client.get("/api/clients")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["hostname"] == "me"
    mock_db.query.assert_not_called()


# -----------------------------------------------------------------------------
# GET /api/clients/{client_id}
# -----------------------------------------------------------------------------


def test_get_client_success(client, mock_db):
    """super_admin fetches a client -> 200."""
    target = _client(hostname="target")
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = target

    response = client.get(f"/api/clients/{target.id}")

    assert response.status_code == 200
    assert response.json()["hostname"] == "target"


def test_get_client_not_found(client, mock_db):
    """Missing client -> 404."""
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.get(f"/api/clients/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Client not found"


def test_get_client_cross_org_forbidden(client, mock_db):
    """org_admin fetching another org's client -> 403."""
    target = _client(org_id=uuid.uuid4())
    auth_as(_user(role="org_admin", org_id=uuid.uuid4()))
    mock_db.query.return_value.filter.return_value.first.return_value = target

    response = client.get(f"/api/clients/{target.id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


def test_get_client_other_client_forbidden(client, mock_db):
    """A client identity fetching a different client -> 403.

    See ``test_list_clients_client_sees_only_self`` for why ``get_current_user``
    is overridden with a Client identity here.
    """
    target = _client(hostname="other")
    auth_as(_client(client_id=uuid.uuid4(), hostname="me"))
    mock_db.query.return_value.filter.return_value.first.return_value = target

    response = client.get(f"/api/clients/{target.id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


def test_get_client_self_for_client(client, mock_db):
    """A client identity fetching itself -> 200."""
    cli = _client(hostname="me")
    auth_as(cli)
    mock_db.query.return_value.filter.return_value.first.return_value = cli

    response = client.get(f"/api/clients/{cli.id}")

    assert response.status_code == 200
    assert response.json()["hostname"] == "me"


# -----------------------------------------------------------------------------
# DELETE /api/clients/{client_id}
# -----------------------------------------------------------------------------


def test_delete_client_insufficient_role(client, mock_db):
    """analyst lacks delete rights -> 403 before any DB lookup."""
    auth_as(_user(role="analyst"))

    response = client.delete(f"/api/clients/{uuid.uuid4()}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permissions"
    mock_db.query.assert_not_called()


def test_delete_client_not_found(client, mock_db):
    """Missing client -> 404."""
    auth_as(_user(role="org_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.delete(f"/api/clients/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Client not found"


def test_delete_client_cross_org_forbidden(client, mock_db):
    """org_admin deleting another org's client -> 403."""
    target = _client(org_id=uuid.uuid4())
    auth_as(_user(role="org_admin", org_id=uuid.uuid4()))
    mock_db.query.return_value.filter.return_value.first.return_value = target

    response = client.delete(f"/api/clients/{target.id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"
    mock_db.delete.assert_not_called()


def test_delete_client_success(client, mock_db):
    """org_admin deletes a client in their org -> 200."""
    org_id = uuid.uuid4()
    target = _client(org_id=org_id)
    auth_as(_user(role="org_admin", org_id=org_id))
    mock_db.query.return_value.filter.return_value.first.return_value = target

    response = client.delete(f"/api/clients/{target.id}")

    assert response.status_code == 200
    assert response.json()["message"] == "Client deleted successfully"
    mock_db.delete.assert_called_once_with(target)
    mock_db.commit.assert_called_once()


# -----------------------------------------------------------------------------
# POST /api/clients/{client_id}/index-images
# -----------------------------------------------------------------------------


def test_index_images_wrong_client_forbidden(client, mock_db):
    """A client indexing for a different client_id -> 403."""
    client_as(_client(client_id=uuid.uuid4(), hostname="me"))

    response = client.post(
        f"/api/clients/{uuid.uuid4()}/index-images",
        json=[{"path": "/img/a.e01", "size_bytes": 100, "format": "E01"}],
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Clients can only index images for themselves"


def test_index_images_creates_new(client, mock_db):
    """Indexing new images reports them as indexed."""
    cli = _client(hostname="me")
    client_as(cli)
    # No existing image for any path.
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.post(
        f"/api/clients/{cli.id}/index-images",
        json=[
            {"path": "/img/a.e01", "size_bytes": 100, "format": "E01"},
            {"path": "/img/b.dd", "size_bytes": 200, "format": "DD"},
        ],
    )

    assert response.status_code == 200
    data = response.json()
    assert data == {"indexed": 2, "updated": 0, "total": 2}
    assert mock_db.add.call_count == 2
    mock_db.commit.assert_called_once()


def test_index_images_updates_existing(client, mock_db):
    """Re-indexing an existing path updates it instead of duplicating."""
    cli = _client(hostname="me")
    client_as(cli)
    existing = _disk_image(client_id=cli.id, path="/img/a.e01")
    assert existing.image_metadata == {"fs": "ntfs"}  # set by _disk_image
    mock_db.query.return_value.filter.return_value.first.return_value = existing

    response = client.post(
        f"/api/clients/{cli.id}/index-images",
        json=[{
            "path": "/img/a.e01",
            "size_bytes": 999,
            "format": "E01",
            "image_metadata": {"fs": "ext4", "label": "data"},
        }],
    )

    assert response.status_code == 200
    data = response.json()
    assert data == {"indexed": 0, "updated": 1, "total": 1}
    # Existing row was mutated, not re-added.
    assert existing.size_bytes == 999
    # Guards the image_metadata fix: the update must flow through the
    # ``image_metadata`` attribute (NOT the reserved ``metadata`` name). If the
    # line were reverted to ``existing.metadata = ...``, this assertion fails
    # because the real column attribute stays unchanged.
    assert existing.image_metadata == {"fs": "ext4", "label": "data"}
    mock_db.add.assert_not_called()


# -----------------------------------------------------------------------------
# GET /api/clients/{client_id}/images
# -----------------------------------------------------------------------------


def test_list_client_images_not_found(client, mock_db):
    """Unknown client -> 404."""
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.get(f"/api/clients/{uuid.uuid4()}/images")

    assert response.status_code == 404
    assert response.json()["detail"] == "Client not found"


def test_list_client_images_success(client, mock_db):
    """super_admin lists a client's images -> 200."""
    target = _client(hostname="target")
    auth_as(_user(role="super_admin"))
    images = [_disk_image(client_id=target.id), _disk_image(client_id=target.id, path="/img/b.dd")]
    # Client lookup via .first(); images via .all() on the same filtered mock.
    chain = mock_db.query.return_value.filter.return_value
    chain.first.return_value = target
    chain.all.return_value = images

    response = client.get(f"/api/clients/{target.id}/images")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_list_client_images_cross_org_forbidden(client, mock_db):
    """A non-super_admin listing another org's client images -> 403."""
    target = _client(org_id=uuid.uuid4())
    auth_as(_user(role="org_admin", org_id=uuid.uuid4()))
    mock_db.query.return_value.filter.return_value.first.return_value = target

    response = client.get(f"/api/clients/{target.id}/images")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


if __name__ == "__main__":
    import pytest as _pytest

    _pytest.main([__file__, "-v"])
