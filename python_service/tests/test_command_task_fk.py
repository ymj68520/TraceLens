"""Task 4: command_queue.task_id is a real FK, not just a JSONB soft link.

Note on deviations from the brief's literal test sketch (all three are
schema-validity fixes required against the migration-001 schema; none change
what the cascade test verifies):
  * ``AnalysisTask.status`` uses ``"running"`` (a valid analysis_tasks status),
    not ``"in_progress"`` (which is a command_queue status and violates the
    analysis_tasks_status_check constraint).
  * ``CommandQueue.priority`` uses ``"normal"`` (a valid priority), not ``0``
    (integer violates the command_queue_priority_check constraint).
  * ``CommandQueue.ttl`` is set explicitly because the column is NOT NULL with
    no default.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import inspect

from server.models.database import AnalysisTask, CommandQueue


def test_command_queue_has_task_id_column():
    cols = {c.name for c in inspect(CommandQueue).columns}
    assert "task_id" in cols


def test_command_queue_has_task_relationship():
    rels = {r.key for r in inspect(CommandQueue).relationships}
    assert "task" in rels


def test_task_has_commands_backref():
    rels = {r.key for r in inspect(AnalysisTask).relationships}
    assert "commands" in rels


def test_deleting_a_task_cascades_to_its_command(db_session, org_and_client):
    """ON DELETE CASCADE must remove a command when its task is deleted.

    Tests the FK constraint at the DB level only — rows inserted directly, no
    orchestrator involved (the orchestrator wiring that sets task_id on create
    is Task 5). Requires the test DB to enforce foreign keys (PostgreSQL)."""
    org, client, disk_image, user = org_and_client
    task = AnalysisTask(
        id=uuid.uuid4(), org_id=org.id, client_id=client.id,
        disk_image_id=disk_image.id, task_name="cascade-test",
        analysis_type="full", status="running",
    )
    db_session.add(task)
    db_session.flush()
    cmd = CommandQueue(
        id=uuid.uuid4(), client_id=client.id, user_id=user.id,
        command_type="analyze_disk", parameters={"image_path": "/tmp/x.raw"},
        priority="normal", status="in_progress", task_id=task.id,
        ttl=datetime.utcnow() + timedelta(hours=1),
    )
    db_session.add(cmd)
    db_session.commit()
    cmd_id = cmd.id
    db_session.delete(task)
    db_session.commit()
    assert db_session.query(CommandQueue).filter_by(id=cmd_id).first() is None


# ---------------------------------------------------------------------------
# Task 5: the orchestrator must stamp the FK column, cancel via it, and the
# command→task propagation must resolve the task through it (not the JSONB
# soft link). The signatures below match the real orchestrator methods
# (db/user_id/client_id keyword params), not the brief's literal sketch.
# ---------------------------------------------------------------------------


def test_command_inherits_task_id_when_created_via_orchestrator(db_session, org_and_client):
    """Creating a task must stamp the spawned command's task_id column."""
    from server.services.task_orchestrator import TaskOrchestrator

    org, client, disk_image, user = org_and_client
    task = TaskOrchestrator.create_analysis_task(
        db=db_session,
        org_id=org.id,
        client_id=client.id,
        user_id=user.id,
        disk_image_id=disk_image.id,
        task_name="fk-test",
        analysis_type="full",
    )
    cmd = db_session.query(CommandQueue).filter_by(task_id=task.id).one()
    assert cmd.task_id == task.id
    # JSONB soft link kept for one release as backward-compat; column is authoritative.
    assert cmd.parameters["task_id"] == str(task.id)


def test_cancel_task_fails_its_command_via_fk(db_session, org_and_client):
    """cancel_task must find the command via the task_id FK column, not JSONB."""
    from server.services.task_orchestrator import TaskOrchestrator

    org, client, disk_image, user = org_and_client
    task = TaskOrchestrator.create_analysis_task(
        db=db_session, org_id=org.id, client_id=client.id, user_id=user.id,
        disk_image_id=disk_image.id, task_name="cancel-test", analysis_type="full",
    )
    # Real signature: cancel_task(task_id, user_id, db=None) — no org_id param.
    TaskOrchestrator.cancel_task(task_id=task.id, user_id=user.id, db=db_session)
    cmd = db_session.query(CommandQueue).filter_by(task_id=task.id).one()
    assert cmd.status == "failed"


def test_propagate_uses_task_id_column_not_jsonb(db_session, org_and_client):
    """A command whose parameters lack task_id must still resolve its task
    via the task_id column."""
    from server.services.command_queue import CommandQueueService
    from server.services.task_orchestrator import TaskOrchestrator

    org, client, disk_image, user = org_and_client
    task = TaskOrchestrator.create_analysis_task(
        db=db_session, org_id=org.id, client_id=client.id, user_id=user.id,
        disk_image_id=disk_image.id, task_name="prop-test", analysis_type="full",
    )
    cmd = db_session.query(CommandQueue).filter_by(task_id=task.id).one()
    cmd.parameters = {k: v for k, v in cmd.parameters.items() if k != "task_id"}  # strip JSONB
    db_session.flush()
    CommandQueueService.propagate_command_status(db_session, cmd, "completed", 100, "ok")
    db_session.refresh(task)
    assert task.status == "completed"
