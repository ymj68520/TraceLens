"""
Command queue management service.

The command queue is the backbone of the poll-based client/server protocol. The
server enqueues commands targeted at a specific client; the client polls every
``settings.DEFAULT_POLL_INTERVAL`` seconds, claims its pending commands, executes
them locally, and reports results back. Each command carries a TTL after which
it is expired and dropped (default 24h; 1h for ``critical`` commands per
``settings.CRITICAL_COMMAND_TTL_HOURS``).

Datetime policy
---------------
Every "now" computation uses timezone-aware UTC via :func:`_now`
(``datetime.now(timezone.utc)``), matching ``server.services.auth_service`` and
the rest of the codebase. A naive ``datetime.utcnow()`` would (a) be deprecated
on Python 3.12 and (b) raise a naive-vs-aware ``TypeError`` the moment it is
compared against a DB-stored aware timestamp (e.g. ``CommandQueue.ttl``).
"""
from datetime import datetime, timedelta, timezone
import uuid
from typing import List, Optional

from sqlalchemy import and_, case
from sqlalchemy.orm import Session

from server.config import settings
from server.db.session import SessionLocal
from server.models.database import Client, CommandQueue
from server.models.schemas import CommandCreate, CommandPollResponse, CommandResponse


def _now() -> datetime:
    """Aware-UTC "now". Centralized so every timestamp in this module is
    consistent and never naive."""
    return datetime.now(timezone.utc)


class CommandQueueService:
    """Service for managing the command queue."""

    @staticmethod
    def create_command(
        command_data: CommandCreate, user_id: uuid.UUID, db: Session
    ) -> CommandQueue:
        """
        Create a new command in the queue.

        Args:
            command_data: Command creation data
            user_id: User UUID creating the command
            db: Database session

        Returns:
            Created command

        Raises:
            ValueError: If the target client does not exist
        """
        # Verify the target client exists.
        client = db.query(Client).filter(Client.id == command_data.client_id).first()
        if not client:
            raise ValueError("Client not found")

        # TTL: critical commands always get the short window, regardless of the
        # caller-supplied ttl_hours.
        if command_data.priority == "critical":
            ttl_hours = settings.CRITICAL_COMMAND_TTL_HOURS
        else:
            ttl_hours = command_data.ttl_hours

        ttl = _now() + timedelta(hours=ttl_hours)

        # status is set explicitly ("pending") rather than relying on the DB
        # column default, so the returned object is well-formed even before a
        # flush populates server defaults.
        command = CommandQueue(
            id=uuid.uuid4(),
            client_id=command_data.client_id,
            user_id=user_id,
            command_type=command_data.command_type,
            parameters=command_data.parameters,
            priority=command_data.priority,
            status="pending",
            ttl=ttl,
        )

        db.add(command)
        db.commit()
        db.refresh(command)

        return command

    @staticmethod
    def get_pending_commands(client_id: uuid.UUID, db: Session) -> List[CommandQueue]:
        """
        Claim pending commands for a client.

        Returns pending, unexpired commands for ``client_id`` ordered by priority
        (critical > high > normal > low) then by creation time (oldest first),
        and atomically transitions each to ``assigned``.

        Args:
            client_id: Client UUID
            db: Database session

        Returns:
            List of claimed (now ``assigned``) commands
        """
        now = _now()

        # Priority ordering: critical first, then high, normal, low. Unknown
        # priorities sort last. Ties break by oldest created_at. ``case`` uses
        # the SQLAlchemy 2.0 positional-when form.
        priority_order = case(
            (CommandQueue.priority == "critical", 1),
            (CommandQueue.priority == "high", 2),
            (CommandQueue.priority == "normal", 3),
            (CommandQueue.priority == "low", 4),
            else_=5,
        )

        commands = (
            db.query(CommandQueue)
            .filter(
                and_(
                    CommandQueue.client_id == client_id,
                    CommandQueue.status == "pending",
                    CommandQueue.ttl > now,
                )
            )
            .order_by(priority_order, CommandQueue.created_at.asc())
            .all()
        )

        # Mark each as assigned to this polling client.
        for command in commands:
            command.status = "assigned"
            command.assigned_at = now

        db.commit()

        return commands

    @staticmethod
    def update_command_status(
        command_id: uuid.UUID,
        status: str,
        result_message: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> CommandQueue:
        """
        Update a command's status.

        ``completed`` and ``failed`` stamp ``completed_at``; ``failed`` also
        increments ``retry_count``. Any other status (e.g. ``in_progress``) only
        flips ``status``. ``result_message`` is overwritten only when a new value
        is supplied, so a progress update without a message does not clobber a
        prior result/error.

        Args:
            command_id: Command UUID
            status: New status
            result_message: Optional result/error message
            db: Database session (a fresh one is opened and closed if omitted)

        Returns:
            Updated command

        Raises:
            ValueError: If the command does not exist
        """
        # When no session is supplied we own the one we open and must close it,
        # so standalone/background callers (e.g. a TTL sweeper) do not leak
        # pooled connections.
        owns_session = db is None
        if owns_session:
            db = SessionLocal()

        try:
            command = db.query(CommandQueue).filter(
                CommandQueue.id == command_id
            ).first()

            if not command:
                raise ValueError("Command not found")

            command.status = status
            if result_message is not None:
                command.result_message = result_message

            if status == "completed":
                command.completed_at = _now()
            elif status == "failed":
                command.completed_at = _now()
                command.retry_count += 1
            # "in_progress" (and any other value) only changes status.

            db.commit()
            db.refresh(command)

            return command
        finally:
            if owns_session:
                db.close()

    @staticmethod
    def expire_commands(db: Optional[Session] = None) -> int:
        """
        Expire commands that have passed their TTL.

        Pending or assigned commands whose TTL is in the past are transitioned to
        ``expired``.

        Args:
            db: Database session (a fresh one is opened and closed if omitted)

        Returns:
            Number of commands expired
        """
        owns_session = db is None
        if owns_session:
            db = SessionLocal()

        try:
            now = _now()

            expired_commands = (
                db.query(CommandQueue)
                .filter(
                    and_(
                        CommandQueue.status.in_(["pending", "assigned"]),
                        CommandQueue.ttl < now,
                    )
                )
                .all()
            )

            for command in expired_commands:
                command.status = "expired"

            db.commit()

            return len(expired_commands)
        finally:
            if owns_session:
                db.close()

    @staticmethod
    def get_commands_for_client(
        client_id: uuid.UUID, db: Session
    ) -> CommandPollResponse:
        """
        Serve a client poll: refresh the client's presence, claim its pending
        commands, and return them.

        Updates ``last_seen``; derives online/offline from ``last_poll``
        (within the last minute => online). ``last_poll`` itself is stamped by
        the poll endpoint (Task 11) before it calls this method, so a client
        mid-poll reads as online.

        Args:
            client_id: Client UUID
            db: Database session

        Returns:
            Poll response with claimed commands and the server time
        """
        # Refresh presence.
        client = db.query(Client).filter(Client.id == client_id).first()
        if client:
            now = _now()
            client.last_seen = now
            # total_seconds (not .seconds) measures the full interval including
            # any days component.
            if client.last_poll and (now - client.last_poll).total_seconds() < 60:
                client.status = "online"
            else:
                client.status = "offline"

            db.commit()

        # Claim pending commands.
        commands = CommandQueueService.get_pending_commands(client_id, db)

        return CommandPollResponse(
            commands=[CommandResponse.model_validate(cmd) for cmd in commands],
            server_time=_now(),
        )

    @staticmethod
    def propagate_command_status(
        db: Session,
        command: CommandQueue,
        status: str,
        progress: Optional[int] = None,
        message: Optional[str] = None,
    ) -> None:
        """Bridge a command status update to its owning analysis task.

        Resolves the task via the ``task_id`` FK column (authoritative since
        migration 002); falls back to the legacy ``parameters->>'task_id'`` soft
        link only for pre-migration rows whose ``task_id`` column is NULL. The
        task lookup is scoped by ``command.client_id`` (passed through to the
        orchestrator) as defense-in-depth against a forged ``task_id`` planted
        in a command's parameters: a client can only advance a task assigned to
        it.

        Best-effort: the command status update (the primary, client-facing
        operation) has already committed. A missing/stale/scoped-out task raises
        ``ValueError`` from the orchestrator, which is logged and swallowed so a
        late or stale report does not surface to the client. Mirrors the
        behavior of the route-resident helper this replaces.

        ``TaskOrchestrator`` is imported lazily because
        :mod:`server.services.task_orchestrator` imports
        :class:`CommandQueueService` at module top — a top-level import here
        would be circular.

        Args:
            db: Caller-owned session (the route's request session).
            command: The command whose status was just updated.
            status: The new command status (``in_progress`` / ``completed`` /
                ``failed`` carry a task transition; others are no-ops).
            progress: Optional progress percentage for ``in_progress`` reports.
            message: Optional message — appended to task metadata for
                ``in_progress``, becomes the error message for ``failed``.
        """
        import logging

        from server.services.task_orchestrator import TaskOrchestrator

        logger = logging.getLogger(__name__)

        # FK column authoritative; JSONB soft link is a fallback for rows that
        # pre-date migration 002 (column NULL). ``parameters`` is non-nullable
        # but guard defensively, as the route helper did.
        tid = command.task_id or (command.parameters or {}).get("task_id")
        if not tid:
            return  # health_check / extract_file have no owning task.

        # Normalize a JSONB-string fallback to UUID; skip (as the route did) if
        # unparseable rather than crashing the propagation.
        if isinstance(tid, str):
            try:
                tid = uuid.UUID(tid)
            except (ValueError, AttributeError):
                logger.warning(
                    "Command %s carries an unparseable task_id %r; skipping "
                    "task propagation.",
                    command.id,
                    tid,
                )
                return

        try:
            if status == "in_progress":
                TaskOrchestrator.update_task_progress(
                    task_id=tid,
                    progress=progress or 0,
                    db=db,
                    client_id=command.client_id,
                )
            elif status in ("completed", "failed"):
                TaskOrchestrator.complete_task(
                    task_id=tid,
                    success=(status == "completed"),
                    error_message=message,
                    db=db,
                    client_id=command.client_id,
                )
            # Other statuses (pending / assigned / expired) carry no transition.
        except ValueError:
            # Task missing/stale/scoped-out — the command report already
            # succeeded; swallow so the client gets a 200.
            logger.warning(
                "Command %s reports %s but its task %s is missing for client "
                "%s; command status updated, task propagation skipped.",
                command.id,
                status,
                tid,
                command.client_id,
            )
