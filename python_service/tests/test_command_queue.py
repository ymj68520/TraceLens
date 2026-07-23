"""
Tests for the command queue service (``server.services.command_queue``).

These tests exercise the queue's lifecycle operations:

* ``create_command``                - enqueue with TTL (normal vs critical), 404
  on unknown client
* ``get_pending_commands``          - claim: pending -> assigned, stamps
  assigned_at, commits
* ``update_command_status``         - completed/failed/in_progress transitions,
  retry_count on failure, 404 on unknown command
* ``expire_commands``               - past-TTL pending/assigned -> expired,
  returns count
* ``get_commands_for_client``       - poll: presence refresh (online/offline) +
  claim + poll response

Strategy
--------
The DB layer is stubbed with a :class:`~unittest.mock.MagicMock` session. The ORM
models use PostgreSQL-native ``JSONB`` / ``UUID`` types, so no live database is
available in the test environment (the same approach as
``tests/test_organizations_api.py`` and ``tests/test_clients_api.py``). The query
chains (``.filter(...).order_by(...).all()`` / ``.first()``) are terminal-stubbed
to return real ORM instances built by the factories below, so the service's state
mutations and TTL math — the real business logic — are verified directly.

Note: the SQL ``filter``/``order_by`` predicates themselves cannot be asserted
through a mock (they are never compiled); correctness of those is exercised once
a live DB exists. The status transitions, TTL computation, retry accounting, and
presence logic are all verified here.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from server.config import settings
from server.models.database import Client, CommandQueue
from server.models.schemas import CommandCreate
from server.services.command_queue import CommandQueueService


# -----------------------------------------------------------------------------
# ORM instance factories (transient — never added to a real session)
# -----------------------------------------------------------------------------


def _client(
    client_id=None,
    org_id=None,
    hostname="test-client",
    status="online",
    last_poll=None,
    last_seen=None,
):
    return Client(
        id=client_id or uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        hostname=hostname,
        status=status,
        last_poll=last_poll,
        last_seen=last_seen,
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


@pytest.fixture
def db():
    """A MagicMock session standing in for the SQLAlchemy Session."""
    return MagicMock()


# -----------------------------------------------------------------------------
# create_command
# -----------------------------------------------------------------------------


def test_create_command_normal(db):
    """A normal-priority command is enqueued with status pending and a ~ttl_hours TTL."""
    cli = _client()
    db.query.return_value.filter.return_value.first.return_value = cli

    data = CommandCreate(
        client_id=cli.id,
        command_type="analyze_disk",
        parameters={"image_path": "/test/image.E01"},
        priority="normal",
        ttl_hours=24,
    )
    user_id = uuid.uuid4()
    before = datetime.now(timezone.utc)
    command = CommandQueueService.create_command(data, user_id, db)
    after = datetime.now(timezone.utc)

    assert command.client_id == cli.id
    assert command.user_id == user_id
    assert command.command_type == "analyze_disk"
    assert command.priority == "normal"
    # status set explicitly so the object is well-formed pre-flush.
    assert command.status == "pending"
    # TTL = now + 24h (within the [before, after] execution window).
    assert before + timedelta(hours=24) <= command.ttl <= after + timedelta(hours=24)

    db.add.assert_called_once_with(command)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(command)


def test_create_command_critical_uses_short_ttl(db):
    """Critical priority overrides ttl_hours with CRITICAL_COMMAND_TTL_HOURS (1h)."""
    cli = _client()
    db.query.return_value.filter.return_value.first.return_value = cli

    # Caller asks for a week, but critical commands get the 1-hour window.
    data = CommandCreate(
        client_id=cli.id,
        command_type="health_check",
        parameters={},
        priority="critical",
        ttl_hours=168,
    )
    before = datetime.now(timezone.utc)
    command = CommandQueueService.create_command(data, uuid.uuid4(), db)
    after = datetime.now(timezone.utc)

    assert command.priority == "critical"
    assert settings.CRITICAL_COMMAND_TTL_HOURS == 1
    assert before + timedelta(hours=1) <= command.ttl <= after + timedelta(hours=1)


def test_create_command_client_not_found(db):
    """Unknown client -> ValueError, no DB writes."""
    db.query.return_value.filter.return_value.first.return_value = None

    data = CommandCreate(
        client_id=uuid.uuid4(),
        command_type="analyze_disk",
        parameters={"path": "/test"},
        priority="normal",
        ttl_hours=24,
    )
    with pytest.raises(ValueError, match="Client not found"):
        CommandQueueService.create_command(data, uuid.uuid4(), db)

    db.add.assert_not_called()
    db.commit.assert_not_called()


# -----------------------------------------------------------------------------
# get_pending_commands
# -----------------------------------------------------------------------------


def test_get_pending_commands_marks_assigned(db):
    """Claimed commands transition pending -> assigned and get assigned_at."""
    cli_id = uuid.uuid4()
    cmd1 = _command(client_id=cli_id, priority="critical")
    cmd2 = _command(client_id=cli_id, priority="normal")
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        cmd1,
        cmd2,
    ]

    result = CommandQueueService.get_pending_commands(cli_id, db)

    assert result == [cmd1, cmd2]
    assert all(cmd.status == "assigned" for cmd in result)
    assert all(cmd.assigned_at is not None for cmd in result)
    db.commit.assert_called_once()


def test_get_pending_commands_empty(db):
    """No pending commands -> empty list, commit still issued."""
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

    result = CommandQueueService.get_pending_commands(uuid.uuid4(), db)

    assert result == []
    db.commit.assert_called_once()


# -----------------------------------------------------------------------------
# update_command_status
# -----------------------------------------------------------------------------


def test_update_command_completed(db):
    """completed stamps completed_at; retry_count untouched."""
    cmd = _command(status="assigned", retry_count=0)
    db.query.return_value.filter.return_value.first.return_value = cmd

    before = datetime.now(timezone.utc)
    updated = CommandQueueService.update_command_status(
        cmd.id, "completed", "done", db=db
    )
    after = datetime.now(timezone.utc)

    assert updated is cmd
    assert cmd.status == "completed"
    assert cmd.result_message == "done"
    assert before <= cmd.completed_at <= after
    assert cmd.retry_count == 0
    db.commit.assert_called_once()


def test_update_command_failed_increments_retry(db):
    """failed stamps completed_at and increments retry_count."""
    cmd = _command(status="in_progress", retry_count=2)
    db.query.return_value.filter.return_value.first.return_value = cmd

    CommandQueueService.update_command_status(cmd.id, "failed", "boom", db=db)

    assert cmd.status == "failed"
    assert cmd.result_message == "boom"
    assert cmd.completed_at is not None
    assert cmd.retry_count == 3


def test_update_command_in_progress_no_timestamp(db):
    """in_progress only flips status; no completed_at, no retry bump."""
    cmd = _command(status="assigned", retry_count=1)
    db.query.return_value.filter.return_value.first.return_value = cmd

    CommandQueueService.update_command_status(cmd.id, "in_progress", db=db)

    assert cmd.status == "in_progress"
    assert cmd.completed_at is None
    assert cmd.retry_count == 1


def test_update_command_not_found(db):
    """Unknown command -> ValueError."""
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(ValueError, match="Command not found"):
        CommandQueueService.update_command_status(uuid.uuid4(), "completed", db=db)


# -----------------------------------------------------------------------------
# expire_commands
# -----------------------------------------------------------------------------


def test_expire_commands_marks_expired(db):
    """Past-TTL pending/assigned commands -> expired; count returned."""
    cli_id = uuid.uuid4()
    expired1 = _command(
        client_id=cli_id,
        status="pending",
        ttl=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    expired2 = _command(
        client_id=cli_id,
        status="assigned",
        ttl=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db.query.return_value.filter.return_value.all.return_value = [expired1, expired2]

    count = CommandQueueService.expire_commands(db=db)

    assert count == 2
    assert expired1.status == "expired"
    assert expired2.status == "expired"
    db.commit.assert_called_once()


def test_expire_commands_none(db):
    """Nothing past TTL -> 0, commit still issued."""
    db.query.return_value.filter.return_value.all.return_value = []

    count = CommandQueueService.expire_commands(db=db)

    assert count == 0
    db.commit.assert_called_once()


# -----------------------------------------------------------------------------
# get_commands_for_client (poll)
# -----------------------------------------------------------------------------


def _wire_poll(db, client, commands):
    """Stub the two query chains a poll performs.

    1. ``db.query(Client).filter().first()``     -> client
    2. ``db.query(CommandQueue).filter().order_by().all()`` -> commands

    Both share ``db.query.return_value.filter.return_value``; ``.first`` and
    ``.order_by().all`` are distinct sub-attributes, so both can be set together.
    """
    chain = db.query.return_value.filter.return_value
    chain.first.return_value = client
    chain.order_by.return_value.all.return_value = commands


def test_get_commands_for_client_online(db):
    """A client whose last_poll is recent is marked online; pending commands are claimed."""
    cli = _client(last_poll=datetime.now(timezone.utc))
    pending = _command(client_id=cli.id, status="pending")
    _wire_poll(db, cli, [pending])

    response = CommandQueueService.get_commands_for_client(cli.id, db)

    assert cli.status == "online"
    assert cli.last_seen is not None
    # The claimed command is now assigned.
    assert pending.status == "assigned"
    assert len(response.commands) == 1
    assert response.commands[0].status == "assigned"
    assert response.server_time is not None


def test_get_commands_for_client_offline_when_stale(db):
    """A client whose last_poll is older than 60s is marked offline."""
    cli = _client(last_poll=datetime.now(timezone.utc) - timedelta(hours=1))
    _wire_poll(db, cli, [])

    response = CommandQueueService.get_commands_for_client(cli.id, db)

    assert cli.status == "offline"
    assert response.commands == []


def test_get_commands_for_client_offline_when_never_polled(db):
    """A client that never polled (last_poll None) is marked offline."""
    cli = _client(last_poll=None)
    _wire_poll(db, cli, [])

    CommandQueueService.get_commands_for_client(cli.id, db)

    assert cli.status == "offline"


def test_get_commands_for_client_unknown_client(db):
    """An unknown client does not raise; empty commands are returned."""
    _wire_poll(db, None, [])

    response = CommandQueueService.get_commands_for_client(uuid.uuid4(), db)

    assert response.commands == []
    assert response.server_time is not None


if __name__ == "__main__":
    import pytest as _pytest

    _pytest.main([__file__, "-v"])
