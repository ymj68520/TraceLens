"""
Tests for the task orchestrator service (``server.services.task_orchestrator``).

These are service-layer tests: they call ``TaskOrchestrator.<method>(...,
db=mock_db)`` directly with a :class:`~unittest.mock.MagicMock` session. There
is no FastAPI dependency injection here (unlike the API tests) and no live DB —
the ORM models use PostgreSQL-native ``JSONB`` / ``UUID``. The same mock-DB
approach as ``tests/test_command_queue.py``.

What is verified
----------------
* ``create_analysis_task`` builds an ``AnalysisTask`` (status ``queued``) with a
  ``task_metadata`` payload, records a ``created`` history row, and enqueues a
  ``pending`` ``analyze_disk`` command with an aware-UTC TTL.
* Lookup / progress / complete / cancel / list behaviour and their error paths.
* The ``owns_session`` / ``try`` / ``finally`` contract: a self-opened session
  (``db=None``) is always closed — including when ``update_task_progress``
  raises on validation *before* querying — and a provided session is never
  closed.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from server.models.database import (
    AnalysisTask,
    Client,
    CommandQueue,
    DiskImage,
    TaskHistory,
)
from server.services.task_orchestrator import TaskOrchestrator


# -----------------------------------------------------------------------------
# ORM instance factories (transient — never added to a real session)
# -----------------------------------------------------------------------------


def _client(client_id=None, org_id=None):
    return Client(
        id=client_id or uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        hostname="station-01",
        status="online",
    )


def _disk_image(disk_image_id=None, path="/evidence/test.E01", fmt="E01"):
    return DiskImage(
        id=disk_image_id or uuid.uuid4(),
        client_id=uuid.uuid4(),
        path=path,
        size_bytes=1024 * 1024 * 100,
        format=fmt,
        md5_hash="abc123",
    )


def _task(
    task_id=None,
    org_id=None,
    client_id=None,
    user_id=None,
    disk_image_id=None,
    status="queued",
    progress=0,
    task_metadata=None,
    created_at=None,
):
    return AnalysisTask(
        id=task_id or uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        client_id=client_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        disk_image_id=disk_image_id or uuid.uuid4(),
        task_name="Test Analysis",
        analysis_type="full",
        status=status,
        progress=progress,
        task_metadata=task_metadata if task_metadata is not None else {},
        created_at=created_at or datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _command(command_id=None, client_id=None, status="pending"):
    return CommandQueue(
        id=command_id or uuid.uuid4(),
        client_id=client_id or uuid.uuid4(),
        user_id=uuid.uuid4(),
        command_type="analyze_disk",
        parameters={"image_path": "/x.E01"},
        priority="normal",
        status=status,
    )


def _added_instances(mock_db):
    """Return the ORM objects passed to ``db.add``, in call order."""
    return [call.args[0] for call in mock_db.add.call_args_list]


# -----------------------------------------------------------------------------
# create_analysis_task
# -----------------------------------------------------------------------------


def test_create_analysis_task_success():
    """Creating a task returns status queued, records history, enqueues a command."""
    db = MagicMock()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    client = _client(org_id=org_id)
    disk_image = _disk_image()
    # Two .first() calls: client, then disk image.
    db.query.return_value.filter.return_value.first.side_effect = [client, disk_image]

    task = TaskOrchestrator.create_analysis_task(
        org_id=org_id,
        user_id=user_id,
        client_id=client.id,
        disk_image_id=disk_image.id,
        task_name="Test Analysis",
        analysis_type="full",
        priority="normal",
        ttl_hours=24,
        db=db,
    )

    assert task.status == "queued"
    assert task.org_id == org_id
    assert task.client_id == client.id
    assert task.disk_image_id == disk_image.id
    assert task.task_name == "Test Analysis"
    assert task.analysis_type == "full"
    # The reserved ``metadata`` column is mapped to ``task_metadata``.
    assert task.task_metadata["disk_image_path"] == disk_image.path
    assert task.task_metadata["disk_image_format"] == disk_image.format

    added = _added_instances(db)
    # One task, one history row, one command.
    assert sum(1 for o in added if isinstance(o, AnalysisTask)) == 1
    histories = [o for o in added if isinstance(o, TaskHistory)]
    assert len(histories) == 1
    assert histories[0].action == "created"
    assert histories[0].user_id == user_id
    commands = [o for o in added if isinstance(o, CommandQueue)]
    assert len(commands) == 1
    assert commands[0].command_type == "analyze_disk"
    # Status set explicitly so the row is claimable on poll.
    assert commands[0].status == "pending"
    assert commands[0].priority == "normal"
    assert commands[0].client_id == client.id
    # Aware-UTC TTL (not the deprecated naive utcnow()).
    assert commands[0].ttl.tzinfo is not None
    # Soft link back to the task — how cancel_task targets THIS task's command
    # (command_queue has no task FK). Verified end-to-end in
    # test_cancel_targets_command_by_task_linkage.
    assert commands[0].parameters["task_id"] == str(task.id)

    db.commit.assert_called()
    db.close.assert_not_called()  # provided session is not owned


def test_create_analysis_task_invalid_client():
    """Missing client -> ValueError before any add."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(ValueError, match="Client not found"):
        TaskOrchestrator.create_analysis_task(
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            client_id=uuid.uuid4(),
            disk_image_id=uuid.uuid4(),
            task_name="Test",
            analysis_type="full",
            db=db,
        )

    db.add.assert_not_called()


def test_create_analysis_task_invalid_disk_image():
    """Client present, disk image missing -> ValueError after the client check."""
    db = MagicMock()
    client = _client()
    # First .first() -> client, second -> None (disk image missing).
    db.query.return_value.filter.return_value.first.side_effect = [client, None]

    with pytest.raises(ValueError, match="Disk image not found"):
        TaskOrchestrator.create_analysis_task(
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            client_id=client.id,
            disk_image_id=uuid.uuid4(),
            task_name="Test",
            analysis_type="full",
            db=db,
        )

    db.add.assert_not_called()


# -----------------------------------------------------------------------------
# get_task_status
# -----------------------------------------------------------------------------


def test_get_task_status_found():
    db = MagicMock()
    task = _task()
    db.query.return_value.filter.return_value.first.return_value = task

    retrieved = TaskOrchestrator.get_task_status(task.id, db)

    assert retrieved is task


def test_get_task_status_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    assert TaskOrchestrator.get_task_status(uuid.uuid4(), db) is None


# -----------------------------------------------------------------------------
# update_task_progress
# -----------------------------------------------------------------------------


def test_update_task_progress_with_message():
    """A message is appended to task_metadata['messages']."""
    db = MagicMock()
    task = _task(progress=0, task_metadata={})
    db.query.return_value.filter.return_value.first.return_value = task

    updated = TaskOrchestrator.update_task_progress(task.id, 50, "Halfway there", db)

    assert updated.progress == 50
    assert "messages" in updated.task_metadata
    assert len(updated.task_metadata["messages"]) == 1
    assert updated.task_metadata["messages"][0]["message"] == "Halfway there"
    db.commit.assert_called()


def test_update_task_progress_without_message():
    """No message -> progress updated, messages untouched."""
    db = MagicMock()
    task = _task(progress=10, task_metadata={})
    db.query.return_value.filter.return_value.first.return_value = task

    updated = TaskOrchestrator.update_task_progress(task.id, 25, None, db)

    assert updated.progress == 25
    assert "messages" not in updated.task_metadata


def test_update_task_invalid_progress():
    """Out-of-range progress -> ValueError before the task is queried."""
    db = MagicMock()

    with pytest.raises(ValueError, match="Progress must be between 0 and 100"):
        TaskOrchestrator.update_task_progress(uuid.uuid4(), 150, "Too high", db)

    db.query.assert_not_called()


def test_update_task_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(ValueError, match="Task not found"):
        TaskOrchestrator.update_task_progress(uuid.uuid4(), 50, db=db)


def test_update_task_progress_transitions_to_running():
    """First progress report moves a queued task to running + stamps started_at."""
    db = MagicMock()
    task = _task(status="queued", progress=0)
    db.query.return_value.filter.return_value.first.return_value = task

    updated = TaskOrchestrator.update_task_progress(task.id, 40, db=db)

    assert updated.status == "running"
    assert updated.progress == 40
    assert updated.started_at is not None
    assert updated.started_at.tzinfo is not None  # aware UTC


def test_update_task_progress_running_is_idempotent():
    """A later report on an already-running task keeps started_at unchanged."""
    db = MagicMock()
    started = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    task = _task(status="running", progress=40)
    task.started_at = started
    db.query.return_value.filter.return_value.first.return_value = task

    updated = TaskOrchestrator.update_task_progress(task.id, 70, db=db)

    assert updated.status == "running"
    assert updated.progress == 70
    # started_at is only stamped on the created/queued -> running transition.
    assert updated.started_at == started


def test_update_task_progress_terminal_task_is_noop():
    """A terminal task ignores progress reports (no reopen, no regress)."""
    db = MagicMock()
    task = _task(status="completed", progress=100)
    db.query.return_value.filter.return_value.first.return_value = task

    updated = TaskOrchestrator.update_task_progress(task.id, 50, "late report", db=db)

    assert updated.status == "completed"
    assert updated.progress == 100  # not regressed
    # No write performed.
    db.commit.assert_not_called()


def test_update_task_progress_none_only_transitions():
    """progress=None transitions to running without touching the progress value."""
    db = MagicMock()
    task = _task(status="queued", progress=10)
    db.query.return_value.filter.return_value.first.return_value = task

    updated = TaskOrchestrator.update_task_progress(task.id, progress=None, db=db)

    assert updated.status == "running"
    assert updated.progress == 10  # unchanged
    assert updated.started_at is not None


def test_update_task_progress_scoped_by_client_id():
    """client_id adds a second filter condition (cross-tenant defense)."""
    db = MagicMock()
    task = _task(status="queued", client_id=uuid.uuid4())
    db.query.return_value.filter.return_value.first.return_value = task

    TaskOrchestrator.update_task_progress(
        task.id, 40, client_id=task.client_id, db=db
    )

    # The single .filter() carried both the id and the client_id conditions.
    assert len(db.query.return_value.filter.call_args[0]) == 2
    assert task.status == "running"


def test_update_task_progress_client_scope_miss_is_not_found():
    """A task not owned by client_id is treated as not found (planted-id defense)."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(ValueError, match="Task not found"):
        TaskOrchestrator.update_task_progress(
            uuid.uuid4(), 40, client_id=uuid.uuid4(), db=db
        )


# -----------------------------------------------------------------------------
# complete_task
# -----------------------------------------------------------------------------


def test_complete_task_success():
    db = MagicMock()
    task = _task(status="running", progress=42)
    db.query.return_value.filter.return_value.first.return_value = task

    completed = TaskOrchestrator.complete_task(task.id, success=True, db=db)

    assert completed.status == "completed"
    assert completed.progress == 100
    assert completed.completed_at is not None
    assert completed.completed_at.tzinfo is not None  # aware UTC
    histories = [o for o in _added_instances(db) if isinstance(o, TaskHistory)]
    assert len(histories) == 1
    assert histories[0].action == "completed"


def test_complete_task_failure():
    db = MagicMock()
    task = _task(status="running")
    db.query.return_value.filter.return_value.first.return_value = task

    failed = TaskOrchestrator.complete_task(
        task.id, success=False, error_message="Disk corrupted", db=db
    )

    assert failed.status == "failed"
    assert failed.error_message == "Disk corrupted"
    assert failed.completed_at is not None
    histories = [o for o in _added_instances(db) if isinstance(o, TaskHistory)]
    assert histories[0].action == "failed"


def test_complete_task_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(ValueError, match="Task not found"):
        TaskOrchestrator.complete_task(uuid.uuid4(), db=db)


def test_complete_task_scoped_by_client_id():
    """client_id adds a second filter condition (cross-tenant defense)."""
    db = MagicMock()
    task = _task(status="running", client_id=uuid.uuid4())
    db.query.return_value.filter.return_value.first.return_value = task

    TaskOrchestrator.complete_task(
        task.id, success=True, client_id=task.client_id, db=db
    )

    assert len(db.query.return_value.filter.call_args[0]) == 2
    assert task.status == "completed"


def test_complete_task_terminal_guard():
    """An already-terminal task is returned unchanged: no flip, re-stamp, or
    double history row (matters now that clients reach this method)."""
    db = MagicMock()
    task = _task(status="completed", progress=100)
    task.completed_at = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    task.error_message = None
    db.query.return_value.filter.return_value.first.return_value = task

    result = TaskOrchestrator.complete_task(
        task.id, success=False, error_message="late report", db=db
    )

    assert result.status == "completed"  # not flipped to failed
    assert result.error_message is None  # no stale error written
    # completed_at not re-stamped to "now".
    assert result.completed_at == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    db.commit.assert_not_called()
    # No audit row appended for a no-op.
    assert not any(
        isinstance(c.args[0], TaskHistory) for c in db.add.call_args_list
    )


# -----------------------------------------------------------------------------
# cancel_task
# -----------------------------------------------------------------------------


def test_cancel_task_fails_associated_command():
    """Cancelling a queued task also fails its still-pending command."""
    db = MagicMock()
    client_id = uuid.uuid4()
    task = _task(status="queued", client_id=client_id)
    command = _command(client_id=client_id, status="pending")
    # First .first() -> task; second .first() -> command.
    db.query.return_value.filter.return_value.first.side_effect = [task, command]

    cancelled = TaskOrchestrator.cancel_task(task.id, task.user_id, db)

    assert cancelled.status == "cancelled"
    assert cancelled.completed_at is not None
    assert command.status == "failed"
    assert command.result_message == "Task cancelled by user"
    histories = [o for o in _added_instances(db) if isinstance(o, TaskHistory)]
    assert histories[0].action == "cancelled"


def test_cancel_task_no_pending_command():
    """Cancelling when there is no pending/assigned command still succeeds."""
    db = MagicMock()
    task = _task(status="queued")
    # task found, command lookup -> None.
    db.query.return_value.filter.return_value.first.side_effect = [task, None]

    cancelled = TaskOrchestrator.cancel_task(task.id, task.user_id, db)

    assert cancelled.status == "cancelled"


def test_cancel_targets_command_by_task_linkage():
    """cancel_task fails the command whose parameters carry this task's id.

    ``command_queue`` has no task FK, so the link lives in
    ``parameters['task_id']`` (stamped by ``create_analysis_task``). This test
    pins the contract: the command matched at creation (task_id in parameters)
    is the one cancel fails — not an arbitrary pending command for the client.
    """
    db = MagicMock()
    task = _task(status="queued")
    # Mirror what create_analysis_task builds: the command carries the task_id.
    command = _command(client_id=task.client_id, status="pending")
    command.parameters = {"task_id": str(task.id), "image_path": "/x.E01"}
    db.query.return_value.filter.return_value.first.side_effect = [task, command]

    TaskOrchestrator.cancel_task(task.id, task.user_id, db)

    assert command.status == "failed"
    assert command.result_message == "Task cancelled by user"


def test_cancel_completed_task_raises():
    db = MagicMock()
    task = _task(status="completed")
    db.query.return_value.filter.return_value.first.return_value = task

    with pytest.raises(ValueError, match="Cannot cancel task"):
        TaskOrchestrator.cancel_task(task.id, task.user_id, db)


def test_cancel_task_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(ValueError, match="Task not found"):
        TaskOrchestrator.cancel_task(uuid.uuid4(), uuid.uuid4(), db)


# -----------------------------------------------------------------------------
# list_user_tasks
# -----------------------------------------------------------------------------


def test_list_user_tasks():
    db = MagicMock()
    tasks = [_task(status="completed"), _task(status="queued")]
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = tasks

    result = TaskOrchestrator.list_user_tasks(uuid.uuid4(), uuid.uuid4(), db=db)

    assert result == tasks


def test_list_user_tasks_with_status_filter():
    """The status_filter branch adds another .filter() to the chain.

    The chain is ``query().filter(org).filter(status).order_by().all()`` — two
    ``.filter()`` calls — so the terminal ``.all()`` sits one ``.filter()``
    deeper than the no-filter case.
    """
    db = MagicMock()
    tasks = [_task(status="queued")]
    db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = tasks

    result = TaskOrchestrator.list_user_tasks(
        uuid.uuid4(), uuid.uuid4(), status_filter="queued", db=db
    )

    assert result == tasks


# -----------------------------------------------------------------------------
# owns_session / leak contract
# -----------------------------------------------------------------------------


def test_create_task_closes_owned_session(monkeypatch):
    """db=None opens a session that is closed on return."""
    fake = MagicMock()
    client = _client()
    disk_image = _disk_image()
    fake.query.return_value.filter.return_value.first.side_effect = [client, disk_image]
    monkeypatch.setattr(
        "server.services.task_orchestrator.SessionLocal", lambda: fake
    )

    TaskOrchestrator.create_analysis_task(
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        client_id=client.id,
        disk_image_id=disk_image.id,
        task_name="Test",
        analysis_type="full",
        db=None,
    )

    fake.close.assert_called_once()


def test_create_task_does_not_close_provided_session():
    """A caller-provided session is left open for the caller to manage."""
    db = MagicMock()
    client = _client()
    disk_image = _disk_image()
    db.query.return_value.filter.return_value.first.side_effect = [client, disk_image]

    TaskOrchestrator.create_analysis_task(
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        client_id=client.id,
        disk_image_id=disk_image.id,
        task_name="Test",
        analysis_type="full",
        db=db,
    )

    db.close.assert_not_called()


def test_update_progress_closes_owned_session_on_validation_error(monkeypatch):
    """Validation raises BEFORE the query, but the owned session is still closed."""
    fake = MagicMock()
    monkeypatch.setattr(
        "server.services.task_orchestrator.SessionLocal", lambda: fake
    )

    with pytest.raises(ValueError, match="Progress must be between 0 and 100"):
        TaskOrchestrator.update_task_progress(uuid.uuid4(), 150, db=None)

    # The ordering fix: owns_session is set first, so finally closes even on raise.
    fake.close.assert_called_once()
    fake.query.assert_not_called()


def test_cancel_closes_owned_session(monkeypatch):
    """A self-opened session is closed even when cancel succeeds."""
    fake = MagicMock()
    task = _task(status="queued")
    fake.query.return_value.filter.return_value.first.side_effect = [task, None]
    monkeypatch.setattr(
        "server.services.task_orchestrator.SessionLocal", lambda: fake
    )

    TaskOrchestrator.cancel_task(task.id, task.user_id, db=None)

    fake.close.assert_called_once()


if __name__ == "__main__":
    import pytest as _pytest

    _pytest.main([__file__, "-v"])
