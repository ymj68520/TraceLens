"""
Tests for the task management API endpoints (``server.api.tasks``).

Exercises the full HTTP path for the task surface:

* ``POST /api/tasks``                   - create (success / client-404 /
  cross-org-403 / same-org-allowed / disk-image-404 / disk-image-mismatch-404)
* ``GET  /api/tasks``                   - list (success / status_filter)
* ``GET  /api/tasks/{task_id}``         - get (success / 404 / cross-org-403)
* ``POST /api/tasks/{task_id}/cancel``  - cancel (success / cannot-cancel-409 /
  404 / cross-org-403)

Strategy
--------
The DB layer is stubbed with a :class:`~unittest.mock.MagicMock` (ORM models use
PostgreSQL-native ``JSONB`` / ``UUID``, so no live DB) — the same approach as
``tests/test_commands_api.py`` and ``tests/test_organizations_api.py``.
Authentication identities are real ORM ``User`` instances; ``get_current_user``
is overridden per-test via ``auth_as``.

``_populate_defaults_on_refresh`` is wired onto ``db.refresh`` to simulate the DB
applying server defaults on commit+refresh. The create flow needs this for
``created_at`` (``func.now()``) and ``progress`` (``default=0``) so a freshly
created task serializes into ``AnalysisTaskResponse`` (``BaseSchema`` requires a
non-None ``created_at``; the response schema requires ``progress: int``).
"""
import os

# Select the HS256 development path so any tokens created/verified match.
os.environ.setdefault("ENVIRONMENT", "development")

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.middleware.auth import get_current_user
from server.models.database import AnalysisTask, Client, DiskImage, User


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
        last_poll=None,
        last_seen=None,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _disk_image(disk_image_id=None, client_id=None, path="/evidence/case1.E01",
                fmt="E01"):
    return DiskImage(
        id=disk_image_id or uuid.uuid4(),
        client_id=client_id or uuid.uuid4(),
        path=path,
        size_bytes=1024 * 1024 * 100,
        format=fmt,
        md5_hash="abc123",
        image_metadata={},
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _task(
    task_id=None,
    org_id=None,
    client_id=None,
    user_id=None,
    disk_image_id=None,
    task_name="Test Analysis",
    analysis_type="full",
    status="queued",
    progress=0,
    created_at=None,
):
    return AnalysisTask(
        id=task_id or uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        client_id=client_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        disk_image_id=disk_image_id or uuid.uuid4(),
        task_name=task_name,
        analysis_type=analysis_type,
        status=status,
        progress=progress,
        task_metadata={},
        created_at=created_at or datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _populate_defaults_on_refresh(obj):
    """Simulate the DB applying server defaults on commit+refresh.

    Only ever invoked with an ``AnalysisTask`` in this suite. ``created_at``
    (``func.now()``) and ``progress`` (``default=0``) are the two server-applied
    defaults the create flow relies on.
    """
    if getattr(obj, "created_at", None) is None:
        obj.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    if getattr(obj, "progress", None) is None:
        obj.progress = 0


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    db = MagicMock()
    # Simulate server defaults on refresh (matters for create_task).
    db.refresh.side_effect = _populate_defaults_on_refresh
    return db


@pytest.fixture
def client(mock_db):
    """TestClient with the DB dependency replaced by ``mock_db``."""
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


def _create_payload(client_id, disk_image_id):
    return {
        "client_id": str(client_id),
        "disk_image_id": str(disk_image_id),
        "task_name": "Full Disk Analysis",
        "analysis_type": "full",
        "priority": "normal",
        "ttl_hours": 24,
    }


# -----------------------------------------------------------------------------
# POST /api/tasks
# -----------------------------------------------------------------------------


def test_create_task_success(client, mock_db):
    """super_admin creates a task -> 200, status queued, command enqueued.

    Four ``.first()`` calls under the mock: endpoint client lookup, endpoint
    disk-image lookup, then the service's two existence re-checks.
    """
    cli = _client()
    img = _disk_image(client_id=cli.id)
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        cli, img, cli, img,
    ]

    response = client.post("/api/tasks", json=_create_payload(cli.id, img.id))

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["client_id"] == str(cli.id)
    assert data["disk_image_id"] == str(img.id)
    assert data["analysis_type"] == "full"
    # One AnalysisTask, one TaskHistory, one CommandQueue.
    assert len(mock_db.add.call_args_list) == 3
    mock_db.commit.assert_called()


def test_create_task_client_not_found(client, mock_db):
    """Unknown client -> 404 before any write."""
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.post(
        "/api/tasks", json=_create_payload(uuid.uuid4(), uuid.uuid4())
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Client not found"
    mock_db.add.assert_not_called()


def test_create_task_cross_org_forbidden(client, mock_db):
    """A non-super_admin targeting another org's client -> 403."""
    auth_as(_user(role="analyst", org_id=uuid.uuid4()))
    mock_db.query.return_value.filter.return_value.first.return_value = _client(
        org_id=uuid.uuid4()
    )

    response = client.post(
        "/api/tasks", json=_create_payload(uuid.uuid4(), uuid.uuid4())
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"
    mock_db.add.assert_not_called()


def test_create_task_same_org_allowed(client, mock_db):
    """An analyst can create a task for a client in their own org."""
    org_id = uuid.uuid4()
    cli = _client(org_id=org_id)
    img = _disk_image(client_id=cli.id)
    auth_as(_user(role="analyst", org_id=org_id))
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        cli, img, cli, img,
    ]

    response = client.post("/api/tasks", json=_create_payload(cli.id, img.id))

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_create_task_disk_image_not_found(client, mock_db):
    """Client valid, disk image missing -> 404 after the client check."""
    cli = _client()
    auth_as(_user(role="super_admin"))
    # Endpoint client lookup -> cli; endpoint disk-image lookup -> None.
    mock_db.query.return_value.filter.return_value.first.side_effect = [cli, None]

    response = client.post(
        "/api/tasks", json=_create_payload(cli.id, uuid.uuid4())
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Disk image not found"
    mock_db.add.assert_not_called()


def test_create_task_disk_image_mismatch_forbidden(client, mock_db):
    """Disk image exists but belongs to ANOTHER client -> 404, no existence leak.

    Without the ``disk_image.client_id == client.id`` check a caller could
    reference another org's disk image and its ``path`` would land in the
    command's ``image_path``. The mismatch is reported as not-found.
    """
    cli = _client()
    # Belongs to a different client.
    other_image = _disk_image(client_id=uuid.uuid4())
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        cli, other_image,
    ]

    response = client.post(
        "/api/tasks", json=_create_payload(cli.id, other_image.id)
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Disk image not found"
    mock_db.add.assert_not_called()


# -----------------------------------------------------------------------------
# GET /api/tasks
# -----------------------------------------------------------------------------


def test_list_tasks_success(client, mock_db):
    """super_admin lists tasks in an org -> 200."""
    auth_as(_user(role="super_admin"))
    tasks = [_task(status="queued"), _task(status="completed")]
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = tasks

    response = client.get("/api/tasks")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_list_tasks_with_status_filter(client, mock_db):
    """A status_filter adds another .filter() to the chain (one deeper .all())."""
    auth_as(_user(role="super_admin"))
    tasks = [_task(status="queued")]
    mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = tasks

    response = client.get("/api/tasks?status_filter=queued")

    assert response.status_code == 200
    assert len(response.json()) == 1


# -----------------------------------------------------------------------------
# GET /api/tasks/{task_id}
# -----------------------------------------------------------------------------


def test_get_task_success(client, mock_db):
    """super_admin fetches a task -> 200."""
    org_id = uuid.uuid4()
    task = _task(org_id=org_id)
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = task

    response = client.get(f"/api/tasks/{task.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(task.id)


def test_get_task_not_found(client, mock_db):
    """Unknown task -> 404."""
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.get(f"/api/tasks/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_get_task_cross_org_forbidden(client, mock_db):
    """A non-super_admin fetching another org's task -> 403."""
    task = _task(org_id=uuid.uuid4())
    auth_as(_user(role="analyst", org_id=uuid.uuid4()))
    mock_db.query.return_value.filter.return_value.first.return_value = task

    response = client.get(f"/api/tasks/{task.id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


# -----------------------------------------------------------------------------
# POST /api/tasks/{task_id}/cancel
# -----------------------------------------------------------------------------


def test_cancel_task_success(client, mock_db):
    """Cancelling a queued task -> 200, status cancelled, command failed.

    Three ``.first()`` calls: endpoint get_task_status, cancel_task's task
    lookup, then cancel_task's command lookup (the soft-link match).
    """
    org_id = uuid.uuid4()
    task = _task(org_id=org_id, status="queued")
    command = MagicMock()
    command.status = "pending"
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        task, task, command,
    ]

    response = client.post(f"/api/tasks/{task.id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    # The task's still-runnable command was failed.
    assert command.status == "failed"


def test_cancel_task_cannot_cancel_conflict(client, mock_db):
    """Cancelling an already-terminal task -> 409."""
    org_id = uuid.uuid4()
    task = _task(org_id=org_id, status="completed")
    auth_as(_user(role="super_admin"))
    # get_task_status -> task; cancel_task task lookup -> task (raises before
    # the command lookup).
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        task, task,
    ]

    response = client.post(f"/api/tasks/{task.id}/cancel")

    assert response.status_code == 409
    assert response.json()["detail"] == "Conflict"


def test_cancel_task_not_found(client, mock_db):
    """Unknown task -> 404."""
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.post(f"/api/tasks/{uuid.uuid4()}/cancel")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_cancel_task_cross_org_forbidden(client, mock_db):
    """A non-super_admin cancelling another org's task -> 403."""
    task = _task(org_id=uuid.uuid4(), status="queued")
    auth_as(_user(role="analyst", org_id=uuid.uuid4()))
    mock_db.query.return_value.filter.return_value.first.return_value = task

    response = client.post(f"/api/tasks/{task.id}/cancel")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


if __name__ == "__main__":
    import pytest as _pytest

    _pytest.main([__file__, "-v"])
