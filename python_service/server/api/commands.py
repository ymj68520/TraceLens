"""
Command queue API endpoints.

Exposes the server side of the poll-based command protocol:

* ``POST /api/commands``                    - enqueue a command for a client
  (user-authenticated, org-scoped)
* ``GET  /api/commands/poll``                - a client polls for its pending
  commands (client-authenticated); stamps ``last_poll`` then claims
* ``POST /api/commands/{command_id}/status`` - a client reports command status
  (client-authenticated, ownership-checked)
* ``GET  /api/commands/{command_id}``        - command details (user-auth,
  org-scoped)
* ``GET  /api/commands/client/{client_id}``  - list a client's commands
  (user-auth, org-scoped)
* ``POST /api/commands/expire``              - manually sweep past-TTL commands
  (super_admin only)

Access control
--------------
User endpoints (create / get / list / expire) enforce organization isolation:
``super_admin`` may act across orgs; every other role is scoped to its own
``org_id`` (403 on cross-org access). Client endpoints (poll / status) are gated
by a client JWT and ownership — a client may only touch its own commands.

Route ordering
--------------
``GET /poll`` is declared before ``GET /{command_id}`` so the literal ``poll``
segment is not captured by the ``{command_id}`` path parameter.

Datetime note
-------------
``last_poll`` is stamped with timezone-aware UTC (``datetime.now(timezone.utc)``),
matching ``server.services.command_queue`` and the rest of the codebase. The poll
endpoint sets ``last_poll`` *before* invoking
``CommandQueueService.get_commands_for_client`` so an actively-polling client
reads as online (see the Task 10 forward note).
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from server.db.session import get_db
from server.middleware.auth import get_current_client, get_current_user
from server.models.database import Client, CommandQueue, User
from server.models.schemas import (
    CommandCreate,
    CommandPollResponse,
    CommandResponse,
    TaskStatusUpdate,
)
from server.services.command_queue import CommandQueueService
from server.services.task_orchestrator import TaskOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/commands", tags=["Commands"])


def _propagate_command_status_to_task(
    command: CommandQueue, status_update: TaskStatusUpdate, db: Session
) -> None:
    """Forward a command status report to its originating analysis task.

    The link is the ``task_id`` stamped into ``command.parameters`` at task
    creation (``command_queue`` has no task FK — the soft link introduced for
    ``cancel_task``). Commands not tied to a task (``health_check``, a directly
    issued ``extract_file``) carry no ``task_id`` and are skipped.

    Command status -> task transition::

        in_progress -> running   (progress via update_task_progress)
        completed   -> completed (complete_task success)
        failed      -> failed    (complete_task failure; message -> error)

    The task lookup is scoped by ``command.client_id`` (passed as ``client_id``
    to the orchestrator). This is the defense-in-depth that enforces org
    isolation on this path: a client may only advance a task *assigned to it*.
    A user can plant an arbitrary ``task_id`` in an ad-hoc command's parameters
    (``POST /api/commands`` accepts free-form ``parameters``), but a planted id
    pointing at another client's task is simply not found by the scoped lookup
    and is treated as a missing task — no cross-tenant effect.

    Propagation is **best-effort**: the command status update (the primary,
    client-facing operation) has already committed. A missing or stale task
    (deleted between command creation and this report, or a scoped-out/planted
    id) raises ``ValueError`` from the orchestrator, which we log and swallow —
    the command report still returns 200. (Other, unexpected errors are *not*
    masked: they surface normally.) All transitions share the caller's session.
    """
    task_id_str = (command.parameters or {}).get("task_id")
    if not task_id_str:
        return  # Not a task-backed command.
    try:
        task_id = uuid.UUID(str(task_id_str))
    except (ValueError, TypeError):
        logger.warning(
            "Command %s carries an unparseable task_id %r; skipping task "
            "propagation.",
            command.id,
            task_id_str,
        )
        return

    try:
        if status_update.status == "in_progress":
            TaskOrchestrator.update_task_progress(
                task_id,
                progress=status_update.progress,
                message=status_update.message,
                client_id=command.client_id,
                db=db,
            )
        elif status_update.status == "completed":
            TaskOrchestrator.complete_task(
                task_id, success=True, client_id=command.client_id, db=db
            )
        elif status_update.status == "failed":
            TaskOrchestrator.complete_task(
                task_id,
                success=False,
                error_message=status_update.message,
                client_id=command.client_id,
                db=db,
            )
        # Other statuses (pending / assigned / expired) carry no task transition.
    except ValueError:
        # Task missing/stale/scoped-out — the command report already succeeded.
        logger.warning(
            "Command %s reports %s but its task %s is missing for client %s; "
            "command status updated, task propagation skipped.",
            command.id,
            status_update.status,
            task_id,
            command.client_id,
        )


@router.post("", response_model=CommandResponse)
async def create_command(
    command_data: CommandCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new command for a client.

    The caller must belong to the client's organization (or be ``super_admin``);
    cross-organization command creation is denied.

    Raises:
        HTTPException: 404 if the client does not exist; 403 on cross-org access.
    """
    # Org-scope check: a user may only command clients in its own org.
    client = db.query(Client).filter(Client.id == command_data.client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )
    if current_user.role != "super_admin" and current_user.org_id != client.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    try:
        return CommandQueueService.create_command(command_data, current_user.id, db)
    except ValueError as e:
        # Defensive: the client was just verified, but a race could delete it.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/poll", response_model=CommandPollResponse)
async def poll_commands(
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Client endpoint to poll for pending commands.

    Stamps ``last_poll`` (aware UTC) before claiming so an actively-polling
    client reads as online.
    """
    current_client.last_poll = datetime.now(timezone.utc)
    db.commit()

    return CommandQueueService.get_commands_for_client(current_client.id, db)


@router.post("/{command_id}/status")
async def update_command_status(
    command_id: uuid.UUID,
    status_update: TaskStatusUpdate,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Client endpoint to report a command's status.

    A client may only update its own commands. After the command status is
    recorded, the report is propagated to the command's originating analysis
    task (if any) via the ``task_id`` soft link — see
    :func:`_propagate_command_status_to_task`.

    Raises:
        HTTPException: 404 if the command does not exist; 403 if the command
            belongs to a different client.
    """
    command = db.query(CommandQueue).filter(CommandQueue.id == command_id).first()

    if not command:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Command not found",
        )

    if command.client_id != current_client.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    try:
        CommandQueueService.update_command_status(
            command_id,
            status_update.status,
            status_update.message,
            db,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # Best-effort: advance the originating analysis task's lifecycle. A missing
    # task is logged and ignored (the command report already succeeded).
    _propagate_command_status_to_task(command, status_update, db)

    return {"updated": True}


@router.get("/{command_id}", response_model=CommandResponse)
async def get_command(
    command_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get command details (org-scoped).

    Raises:
        HTTPException: 404 if the command (or its owning client) does not exist;
            403 on cross-org access.
    """
    command = db.query(CommandQueue).filter(CommandQueue.id == command_id).first()

    if not command:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Command not found",
        )

    client = db.query(Client).filter(Client.id == command.client_id).first()
    if client is None:
        # Orphaned command (owning client gone); treat as not found.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Command not found",
        )

    if current_user.role != "super_admin" and current_user.org_id != client.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return command


@router.get("/client/{client_id}", response_model=List[CommandResponse])
async def list_client_commands(
    client_id: uuid.UUID,
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List commands for a client (org-scoped), newest first.

    Raises:
        HTTPException: 404 if the client does not exist; 403 on cross-org access.
    """
    client = db.query(Client).filter(Client.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )

    if current_user.role != "super_admin" and current_user.org_id != client.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    query = db.query(CommandQueue).filter(CommandQueue.client_id == client_id)
    if status_filter:
        query = query.filter(CommandQueue.status == status_filter)

    return query.order_by(CommandQueue.created_at.desc()).all()


@router.post("/expire")
async def trigger_expiration(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Manually trigger command expiration (super_admin only).

    Raises:
        HTTPException: 403 if the caller is not a super_admin.
    """
    if current_user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return {"expired_commands": CommandQueueService.expire_commands(db)}
