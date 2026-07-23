"""
Tests for the command queue API endpoints (``server.api.commands``).

Exercises the full HTTP path for the command protocol:

* ``POST /api/commands``                     - create (success / 404 unknown
  client / 403 cross-org)
* ``GET  /api/commands/poll``                 - client poll (claims pending /
  empty)
* ``POST /api/commands/{id}/status``          - client reports status (success /
  404 / 403 wrong client)
* ``GET  /api/commands/{id}``                 - get (success / 404 / 403 cross-org)
* ``GET  /api/commands/client/{client_id}``   - list (success / 404 / 403 cross-org)
* ``POST /api/commands/expire``               - expire (success / 403 non-admin)

Strategy
--------
The DB layer is stubbed with a :class:`~unittest.mock.MagicMock` (ORM models use
PostgreSQL-native ``JSONB`` / ``UUID``, so no live DB) — the same approach as
``tests/test_organizations_api.py`` and ``tests/test_clients_api.py``.
Authentication identities are real ORM ``User`` / ``Client`` instances; the
``get_current_user`` / ``get_current_client`` dependencies are overridden per-test
via ``auth_as`` / ``client_as``.

``_populate_defaults_on_refresh`` is wired onto ``db.refresh`` to simulate the DB
applying server defaults (``created_at``, ``retry_count``) on commit+refresh —
exactly what a real session does, and what the create endpoint relies on to
serialize a freshly-created command into ``CommandResponse``.
"""
import os

# Select the HS256 development path so any tokens created/verified match.
os.environ.setdefault("ENVIRONMENT", "development")

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.middleware.auth import get_current_client, get_current_user
from server.models.database import AnalysisTask, Client, CommandQueue, User


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


def _command(
    client_id=None,
    command_type="analyze_disk",
    parameters=None,
    priority="normal",
    status="pending",
    ttl=None,
    created_at=None,
    retry_count=0,
):
    return CommandQueue(
        id=uuid.uuid4(),
        client_id=client_id or uuid.uuid4(),
        user_id=uuid.uuid4(),
        command_type=command_type,
        parameters=parameters if parameters is not None else {"image_path": "/x.E01"},
        priority=priority,
        status=status,
        ttl=ttl if ttl is not None else datetime.now(timezone.utc) + timedelta(hours=24),
        created_at=created_at or datetime(2024, 1, 1, tzinfo=timezone.utc),
        assigned_at=None,
        completed_at=None,
        result_message=None,
        retry_count=retry_count,
    )


def _populate_defaults_on_refresh(obj):
    """Simulate the DB applying server defaults on commit+refresh."""
    if getattr(obj, "created_at", None) is None:
        obj.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    if getattr(obj, "retry_count", None) is None:
        obj.retry_count = 0


def _task(
    task_id=None,
    org_id=None,
    client_id=None,
    user_id=None,
    status="queued",
    progress=0,
):
    """A transient ``AnalysisTask`` for propagation tests."""
    return AnalysisTask(
        id=task_id or uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        client_id=client_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        disk_image_id=uuid.uuid4(),
        task_name="Test Analysis",
        analysis_type="full",
        status=status,
        progress=progress,
        task_metadata={},
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    db = MagicMock()
    # By default, simulate server defaults on refresh (matters for create_command).
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


def client_as(cli):
    """Install ``cli`` (a Client) as the authenticated client identity."""
    async def _override():
        return cli

    app.dependency_overrides[get_current_client] = _override


def _create_payload(client_id, priority="normal"):
    return {
        "client_id": str(client_id),
        "command_type": "analyze_disk",
        "parameters": {"image_path": "/test/image.E01"},
        "priority": priority,
        "ttl_hours": 24,
    }


# -----------------------------------------------------------------------------
# POST /api/commands
# -----------------------------------------------------------------------------


def test_create_command_success(client, mock_db):
    """super_admin creates a command for an existing client -> 200, status pending."""
    cli = _client()
    auth_as(_user(role="super_admin"))
    # Endpoint scope-check .first() and service existence-check .first() both -> cli.
    mock_db.query.return_value.filter.return_value.first.return_value = cli

    response = client.post("/api/commands", json=_create_payload(cli.id))

    assert response.status_code == 200
    data = response.json()
    assert data["command_type"] == "analyze_disk"
    assert data["status"] == "pending"
    assert data["client_id"] == str(cli.id)
    assert data["priority"] == "normal"
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


def test_create_command_client_not_found(client, mock_db):
    """Unknown client -> 404 before any write."""
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.post("/api/commands", json=_create_payload(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["detail"] == "Client not found"
    mock_db.add.assert_not_called()


def test_create_command_cross_org_forbidden(client, mock_db):
    """A non-super_admin commanding another org's client -> 403."""
    auth_as(_user(role="analyst", org_id=uuid.uuid4()))
    mock_db.query.return_value.filter.return_value.first.return_value = _client(
        org_id=uuid.uuid4()
    )

    response = client.post("/api/commands", json=_create_payload(uuid.uuid4()))

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"
    mock_db.add.assert_not_called()


def test_create_command_same_org_allowed(client, mock_db):
    """An analyst can command a client in their own org."""
    org_id = uuid.uuid4()
    cli = _client(org_id=org_id)
    auth_as(_user(role="analyst", org_id=org_id))
    mock_db.query.return_value.filter.return_value.first.return_value = cli

    response = client.post("/api/commands", json=_create_payload(cli.id))

    assert response.status_code == 200
    assert response.json()["status"] == "pending"


# -----------------------------------------------------------------------------
# GET /api/commands/poll
# -----------------------------------------------------------------------------


def test_poll_commands_claims_pending(client, mock_db):
    """A client poll returns pending commands (claimed -> assigned) and server_time."""
    cli = _client()
    client_as(cli)
    pending = _command(client_id=cli.id, status="pending")
    chain = mock_db.query.return_value.filter.return_value
    chain.first.return_value = cli  # client re-lookup inside get_commands_for_client
    chain.order_by.return_value.all.return_value = [pending]

    response = client.get("/api/commands/poll")

    assert response.status_code == 200
    data = response.json()
    assert "server_time" in data
    assert len(data["commands"]) == 1
    # Claimed during the poll.
    assert data["commands"][0]["status"] == "assigned"
    # The endpoint stamped last_poll before claiming.
    assert cli.last_poll is not None
    assert cli.status == "online"


def test_poll_commands_empty(client, mock_db):
    """A poll with no pending commands -> empty list."""
    cli = _client()
    client_as(cli)
    chain = mock_db.query.return_value.filter.return_value
    chain.first.return_value = cli
    chain.order_by.return_value.all.return_value = []

    response = client.get("/api/commands/poll")

    assert response.status_code == 200
    assert response.json()["commands"] == []


# -----------------------------------------------------------------------------
# POST /api/commands/{command_id}/status
# -----------------------------------------------------------------------------


def test_update_command_status_success(client, mock_db):
    """A client reports status on its own command -> 200 updated."""
    cli = _client()
    client_as(cli)
    command = _command(client_id=cli.id, status="assigned")
    mock_db.query.return_value.filter.return_value.first.return_value = command

    response = client.post(
        f"/api/commands/{command.id}/status",
        json={
            "command_id": str(command.id),
            "status": "completed",
            "message": "done",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"updated": True}
    assert command.status == "completed"
    assert command.result_message == "done"


def test_update_command_status_not_found(client, mock_db):
    """Unknown command -> 404."""
    client_as(_client())
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.post(
        f"/api/commands/{uuid.uuid4()}/status",
        json={"command_id": str(uuid.uuid4()), "status": "completed"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Command not found"


def test_update_command_status_wrong_client_forbidden(client, mock_db):
    """A client reporting on another client's command -> 403."""
    me = _client()
    client_as(me)
    # Belongs to someone else.
    command = _command(client_id=uuid.uuid4(), status="assigned")
    mock_db.query.return_value.filter.return_value.first.return_value = command

    response = client.post(
        f"/api/commands/{command.id}/status",
        json={"command_id": str(command.id), "status": "completed"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


# -----------------------------------------------------------------------------
# POST /api/commands/{command_id}/status  — task propagation (Task 15b)
#
# A command whose ``parameters`` carry a ``task_id`` (the soft link stamped by
# create_analysis_task) forwards its status report to the originating task. The
# mock chain is consumed in order: endpoint command lookup, then the
# update_command_status re-fetch, then the orchestrator's task lookup — so each
# propagation test supplies a 3-element ``.first.side_effect``.
# -----------------------------------------------------------------------------


def test_status_in_progress_propagates_to_task(client, mock_db):
    """in_progress + progress -> task transitions to running with the progress."""
    cli = _client()
    client_as(cli)
    task = _task(status="queued", client_id=cli.id, progress=0)
    command = _command(
        client_id=cli.id,
        status="assigned",
        parameters={"task_id": str(task.id), "image_path": "/x.E01"},
    )
    # endpoint command, update_command_status re-fetch, orchestrator task lookup.
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        command, command, task,
    ]

    response = client.post(
        f"/api/commands/{command.id}/status",
        json={
            "command_id": str(command.id),
            "status": "in_progress",
            "progress": 42,
            "message": "carving files",
        },
    )

    assert response.status_code == 200
    # Command advanced...
    assert command.status == "in_progress"
    # ...and the task followed: queued -> running, progress stamped, started_at set.
    assert task.status == "running"
    assert task.progress == 42
    assert task.started_at is not None
    assert task.started_at.tzinfo is not None  # aware UTC


def test_status_completed_propagates_to_task(client, mock_db):
    """completed -> task completed (progress 100, completed_at set)."""
    cli = _client()
    client_as(cli)
    task = _task(status="running", client_id=cli.id, progress=80)
    command = _command(
        client_id=cli.id,
        status="assigned",
        parameters={"task_id": str(task.id), "image_path": "/x.E01"},
    )
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        command, command, task,
    ]

    response = client.post(
        f"/api/commands/{command.id}/status",
        json={"command_id": str(command.id), "status": "completed", "progress": 100},
    )

    assert response.status_code == 200
    assert task.status == "completed"
    assert task.progress == 100
    assert task.completed_at is not None


def test_status_failed_propagates_to_task(client, mock_db):
    """failed + message -> task failed with the message as error_message."""
    cli = _client()
    client_as(cli)
    task = _task(status="running", client_id=cli.id)
    command = _command(
        client_id=cli.id,
        status="assigned",
        parameters={"task_id": str(task.id), "image_path": "/x.E01"},
    )
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        command, command, task,
    ]

    response = client.post(
        f"/api/commands/{command.id}/status",
        json={
            "command_id": str(command.id),
            "status": "failed",
            "message": "E01 checksum mismatch",
        },
    )

    assert response.status_code == 200
    assert task.status == "failed"
    assert task.error_message == "E01 checksum mismatch"


def test_status_without_task_id_skips_propagation(client, mock_db):
    """A command with no task_id reports normally and never touches a task.

    Proven by a finite 2-element side_effect: only the endpoint lookup and the
    update_command_status re-fetch consume ``.first()``. If propagation wrongly
    ran, the orchestrator's task lookup would exhaust the side_effect
    (StopIteration) and the request would 500.
    """
    cli = _client()
    client_as(cli)
    # Default parameters carry no task_id.
    command = _command(client_id=cli.id, status="assigned")
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        command, command,
    ]

    response = client.post(
        f"/api/commands/{command.id}/status",
        json={"command_id": str(command.id), "status": "completed"},
    )

    assert response.status_code == 200
    assert response.json() == {"updated": True}
    assert command.status == "completed"


def test_status_task_missing_still_succeeds(client, mock_db):
    """A stale task_id (task deleted) does not fail the command report.

    The command update is primary and already committed; the orchestrator raises
    ValueError("Task not found"), which the wiring logs and swallows -> 200.
    """
    cli = _client()
    client_as(cli)
    orphan_task_id = uuid.uuid4()
    command = _command(
        client_id=cli.id,
        status="assigned",
        parameters={"task_id": str(orphan_task_id), "image_path": "/x.E01"},
    )
    # endpoint command, update_command_status re-fetch, then task lookup -> None.
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        command, command, None,
    ]

    response = client.post(
        f"/api/commands/{command.id}/status",
        json={"command_id": str(command.id), "status": "completed"},
    )

    assert response.status_code == 200
    # The command still advanced despite the missing task.
    assert command.status == "completed"


# -----------------------------------------------------------------------------
# GET /api/commands/{command_id}
# -----------------------------------------------------------------------------


def test_get_command_success(client, mock_db):
    """super_admin fetches a command -> 200."""
    cli = _client()
    command = _command(client_id=cli.id)
    auth_as(_user(role="super_admin"))
    # Two .first() calls: command, then its owning client.
    mock_db.query.return_value.filter.return_value.first.side_effect = [command, cli]

    response = client.get(f"/api/commands/{command.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(command.id)


def test_get_command_not_found(client, mock_db):
    """Unknown command -> 404."""
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.get(f"/api/commands/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Command not found"


def test_get_command_cross_org_forbidden(client, mock_db):
    """A non-super_admin fetching another org's command -> 403."""
    command = _command(client_id=uuid.uuid4())
    other_org_client = _client(org_id=uuid.uuid4())
    auth_as(_user(role="analyst", org_id=uuid.uuid4()))
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        command,
        other_org_client,
    ]

    response = client.get(f"/api/commands/{command.id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


# -----------------------------------------------------------------------------
# GET /api/commands/client/{client_id}
# -----------------------------------------------------------------------------


def test_list_client_commands_success(client, mock_db):
    """super_admin lists a client's commands -> 200."""
    cli = _client()
    auth_as(_user(role="super_admin"))
    cmds = [
        _command(client_id=cli.id, status="completed"),
        _command(client_id=cli.id, status="pending"),
    ]
    chain = mock_db.query.return_value.filter.return_value
    chain.first.return_value = cli  # client lookup
    chain.order_by.return_value.all.return_value = cmds  # commands

    response = client.get(f"/api/commands/client/{cli.id}")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_list_client_commands_client_not_found(client, mock_db):
    """Unknown client -> 404."""
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.get(f"/api/commands/client/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Client not found"


def test_list_client_commands_cross_org_forbidden(client, mock_db):
    """A non-super_admin listing another org's client commands -> 403."""
    other_org_client = _client(org_id=uuid.uuid4())
    auth_as(_user(role="analyst", org_id=uuid.uuid4()))
    mock_db.query.return_value.filter.return_value.first.return_value = other_org_client

    response = client.get(f"/api/commands/client/{other_org_client.id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


# -----------------------------------------------------------------------------
# POST /api/commands/expire
# -----------------------------------------------------------------------------


def test_trigger_expiration_success(client, mock_db):
    """super_admin triggers expiration -> 200 with expired count."""
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.all.return_value = [
        _command(status="pending", ttl=datetime.now(timezone.utc) - timedelta(hours=1)),
        _command(status="assigned", ttl=datetime.now(timezone.utc) - timedelta(hours=1)),
    ]

    response = client.post("/api/commands/expire")

    assert response.status_code == 200
    assert response.json() == {"expired_commands": 2}


def test_trigger_expiration_non_admin_forbidden(client, mock_db):
    """A non-super_admin -> 403 before any DB work."""
    auth_as(_user(role="org_admin"))

    response = client.post("/api/commands/expire")

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"
    mock_db.query.assert_not_called()


if __name__ == "__main__":
    import pytest as _pytest

    _pytest.main([__file__, "-v"])
