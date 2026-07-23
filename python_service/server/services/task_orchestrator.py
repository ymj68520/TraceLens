"""
Task orchestrator service for creating and managing analysis tasks.

Sits above the command queue: creating an analysis task also enqueues the
``analyze_disk`` command the target client will poll for, and every state
transition is recorded in ``task_history`` for audit.

Every public method accepts an optional ``db`` session. When ``db`` is ``None``
the method opens (and, crucially, closes) its own session via :data:`SessionLocal`
— the ``owns_session`` / ``try`` / ``finally`` pattern established in
:mod:`server.services.command_queue`, so background callers cannot exhaust the
connection pool.

Datetime note
-------------
All timestamps use timezone-aware UTC (``datetime.now(timezone.utc)``); the
``datetime.utcnow()`` form from the task brief is deprecated on Python 3.12 and
produces a naive value that ``TypeError``s against the aware values the DB
stores. This is the codebase standard since the Task 4 auth fix.

Org scope note
--------------
This service trusts the ``org_id`` it is handed and does NOT re-derive it from
the caller. Organization isolation is enforced at the API layer (the endpoint
passes ``current_user.org_id``), mirroring how :mod:`server.api.commands`
wraps :class:`server.services.command_queue.CommandQueueService`.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import uuid

from server.db.session import SessionLocal
from server.models.database import (
    AnalysisTask,
    Client,
    CommandQueue,
    DiskImage,
    TaskHistory,
)


class TaskOrchestrator:
    """Service for orchestrating analysis tasks across clients."""

    @staticmethod
    def create_analysis_task(
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        client_id: uuid.UUID,
        disk_image_id: uuid.UUID,
        task_name: str,
        analysis_type: str,
        priority: str = "normal",
        ttl_hours: int = 24,
        db=None,
    ) -> AnalysisTask:
        """
        Create a new analysis task and its associated ``analyze_disk`` command.

        Args:
            org_id: Organization the task belongs to.
            user_id: User creating the task.
            client_id: Client that will execute the task.
            disk_image_id: Disk image to analyze.
            task_name: Human-readable task name.
            analysis_type: One of full / quick / windows / android / linux.
            priority: Command priority (low / normal / high / critical).
            ttl_hours: Time-to-live for the associated command.
            db: Optional database session.

        Returns:
            The created analysis task (status ``queued``).

        Raises:
            ValueError: If the client or disk image does not exist.
        """
        owns_session = db is None
        if owns_session:
            db = SessionLocal()
        try:
            # Verify client exists.
            client = db.query(Client).filter(Client.id == client_id).first()
            if not client:
                raise ValueError("Client not found")

            # Verify disk image exists.
            disk_image = db.query(DiskImage).filter(
                DiskImage.id == disk_image_id
            ).first()
            if not disk_image:
                raise ValueError("Disk image not found")

            # ``metadata`` is reserved in SQLAlchemy; the AnalysisTask column is
            # mapped to the ``task_metadata`` attribute.
            task = AnalysisTask(
                id=uuid.uuid4(),
                org_id=org_id,
                client_id=client_id,
                user_id=user_id,
                disk_image_id=disk_image_id,
                task_name=task_name,
                analysis_type=analysis_type,
                status="created",
                task_metadata={
                    "disk_image_path": disk_image.path,
                    "disk_image_format": disk_image.format,
                },
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            # Audit trail (committed by the command commit below).
            TaskOrchestrator._record_history(
                task.id, user_id, "created", {"priority": priority}, db
            )

            # The command the client will claim on its next poll. ``status`` is
            # set explicitly (the model default is also "pending") so the row is
            # claimable regardless of how it is constructed. ``task_id`` is
            # stamped into the ``parameters`` JSONB as a soft link back to this
            # task — ``command_queue`` has no task FK, so this is how
            # ``cancel_task`` targets *this* task's command rather than any
            # pending command for the same client.
            command_params = {
                "task_id": str(task.id),
                "image_path": disk_image.path,
                "analysis_type": analysis_type,
                "output_format": "sqlite",
                "options": {
                    "file_carving": True,
                    "llm_text_extraction": True,
                },
            }
            command_data = CommandQueue(
                id=uuid.uuid4(),
                client_id=client_id,
                user_id=user_id,
                command_type="analyze_disk",
                parameters=command_params,
                priority=priority,
                status="pending",
                ttl=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
            )
            db.add(command_data)
            db.commit()

            # The task is now queued behind its command.
            task.status = "queued"
            db.commit()
            db.refresh(task)

            return task
        finally:
            if owns_session:
                db.close()

    @staticmethod
    def get_task_status(task_id: uuid.UUID, db=None) -> Optional[AnalysisTask]:
        """
        Get task status and progress.

        Args:
            task_id: Task UUID.
            db: Optional database session.

        Returns:
            The analysis task, or ``None`` if not found.
        """
        owns_session = db is None
        if owns_session:
            db = SessionLocal()
        try:
            return db.query(AnalysisTask).filter(
                AnalysisTask.id == task_id
            ).first()
        finally:
            if owns_session:
                db.close()

    @staticmethod
    def update_task_progress(
        task_id: uuid.UUID,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        db=None,
        client_id: Optional[uuid.UUID] = None,
    ) -> Optional[AnalysisTask]:
        """
        Record a progress report for a task, transitioning it into ``running``.

        This is the entry point the command-status endpoint uses when a client
        reports a command ``in_progress``: it stamps progress, and on the first
        such report moves the task out of its pre-execution state
        (``created``/``queued``) into ``running`` with a ``started_at`` timestamp.

        ``progress`` is optional so the method can be used for a transition-only
        "the client has started" signal; when supplied it is validated to 0-100.

        ``client_id`` optionally scopes the task lookup. The client-status
        propagation supplies the *reporting command's* ``client_id`` so a client
        can only advance a task assigned to it — this is the defense-in-depth that
        blocks a user-planted ``task_id`` (in an ad-hoc command's parameters) from
        reaching another org's task: the scoped lookup simply does not find it.
        User-authenticated callers omit it (the API layer enforces org scope).

        A task already in a terminal state (``completed``/``failed``/``cancelled``)
        ignores the report — progress updates cannot reopen or regress a finished
        task (a stray/late report from a client must not, e.g., reset progress on
        a completed task).

        Args:
            task_id: Task UUID.
            progress: Progress percentage (0-100), or ``None`` to transition only.
            message: Optional status message, appended to ``task_metadata``.
            client_id: Optional owning-client scope for the task lookup.
            db: Optional database session.

        Returns:
            The updated task.

        Raises:
            ValueError: If ``progress`` is out of range or the task is not found.
        """
        owns_session = db is None
        if owns_session:
            db = SessionLocal()
        try:
            # Validate inside the try so an owned session is still closed on raise.
            # ``progress`` may be None (transition-only); only validate when given.
            if progress is not None and not 0 <= progress <= 100:
                raise ValueError("Progress must be between 0 and 100")

            # Scope by owning client when supplied (client-report path). A single
            # ``.filter(*conditions)`` call keeps the lookup on one mock chain.
            conditions = [AnalysisTask.id == task_id]
            if client_id is not None:
                conditions.append(AnalysisTask.client_id == client_id)
            task = db.query(AnalysisTask).filter(*conditions).first()
            if not task:
                raise ValueError("Task not found")

            # Terminal tasks ignore further progress reports.
            if task.status in ("completed", "failed", "cancelled"):
                return task

            if progress is not None:
                task.progress = progress

            # First execution report transitions the task into "running".
            if task.status in ("created", "queued"):
                task.status = "running"
                task.started_at = datetime.now(timezone.utc)

            if message:
                # Reassign the JSONB dict rather than mutating in place: plain
                # ``Column(JSONB)`` (no MutableDict) does not flag in-place
                # mutation as dirty, so the change would be silently lost on
                # commit under a live DB. Reassignment is detected as a change.
                metadata = dict(task.task_metadata or {})
                messages = list(metadata.get("messages", []))
                messages.append(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "message": message,
                    }
                )
                metadata["messages"] = messages
                task.task_metadata = metadata

            db.commit()
            db.refresh(task)
            return task
        finally:
            if owns_session:
                db.close()

    @staticmethod
    def complete_task(
        task_id: uuid.UUID,
        success: bool = True,
        error_message: Optional[str] = None,
        db=None,
        client_id: Optional[uuid.UUID] = None,
    ) -> Optional[AnalysisTask]:
        """
        Mark a task completed or failed and record the transition.

        ``client_id`` optionally scopes the task lookup to the reporting command's
        client (see :meth:`update_task_progress` for the cross-tenant rationale).

        A task already in a terminal state (``completed``/``failed``/``cancelled``)
        is returned unchanged: a late/duplicate client report must not re-stamp
        ``completed_at``, double-record history, flip one terminal state to
        another, or resurrect a task a user explicitly cancelled. This guard
        matters now that the client-status path reaches this method.

        Args:
            task_id: Task UUID.
            success: Whether the task completed successfully.
            error_message: Error message if failed.
            client_id: Optional owning-client scope for the task lookup.
            db: Optional database session.

        Returns:
            The updated task.

        Raises:
            ValueError: If the task is not found.
        """
        owns_session = db is None
        if owns_session:
            db = SessionLocal()
        try:
            conditions = [AnalysisTask.id == task_id]
            if client_id is not None:
                conditions.append(AnalysisTask.client_id == client_id)
            task = db.query(AnalysisTask).filter(*conditions).first()
            if not task:
                raise ValueError("Task not found")

            # Terminal tasks are immutable from this path.
            if task.status in ("completed", "failed", "cancelled"):
                return task

            if success:
                task.status = "completed"
                task.progress = 100
            else:
                task.status = "failed"
                task.error_message = error_message

            task.completed_at = datetime.now(timezone.utc)

            TaskOrchestrator._record_history(
                task.id,
                task.user_id,
                "completed" if success else "failed",
                {"error": error_message} if not success else {},
                db,
            )

            db.commit()
            db.refresh(task)
            return task
        finally:
            if owns_session:
                db.close()

    @staticmethod
    def cancel_task(
        task_id: uuid.UUID,
        user_id: uuid.UUID,
        db=None,
    ) -> Optional[AnalysisTask]:
        """
        Cancel a task and fail its still-pending command.

        Args:
            task_id: Task UUID.
            user_id: User requesting cancellation.
            db: Optional database session.

        Returns:
            The cancelled task.

        Raises:
            ValueError: If the task is not found or cannot be cancelled.
        """
        owns_session = db is None
        if owns_session:
            db = SessionLocal()
        try:
            task = db.query(AnalysisTask).filter(
                AnalysisTask.id == task_id
            ).first()
            if not task:
                raise ValueError("Task not found")

            if task.status in ("completed", "failed", "cancelled"):
                raise ValueError(f"Cannot cancel task with status: {task.status}")

            task.status = "cancelled"
            task.completed_at = datetime.now(timezone.utc)

            # Fail this task's own command if it has not been picked up yet.
            # The ``task_id`` soft link (stamped into ``parameters`` at
            # creation) scopes the lookup so cancelling one task cannot fail a
            # concurrently-running sibling task's command for the same client.
            command = db.query(CommandQueue).filter(
                CommandQueue.client_id == task.client_id,
                CommandQueue.status.in_(["pending", "assigned"]),
                CommandQueue.parameters["task_id"].astext == str(task.id),
            ).first()
            if command:
                command.status = "failed"
                command.result_message = "Task cancelled by user"

            TaskOrchestrator._record_history(task.id, user_id, "cancelled", {}, db)

            db.commit()
            db.refresh(task)
            return task
        finally:
            if owns_session:
                db.close()

    @staticmethod
    def list_user_tasks(
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        status_filter: Optional[str] = None,
        db=None,
    ) -> List[AnalysisTask]:
        """
        List tasks for an organization, newest first.

        Args:
            user_id: User requesting the list (the API layer further filters
                non-admins to their own tasks).
            org_id: Organization to list within.
            status_filter: Optional status to filter by.
            db: Optional database session.

        Returns:
            List of analysis tasks.
        """
        owns_session = db is None
        if owns_session:
            db = SessionLocal()
        try:
            query = db.query(AnalysisTask).filter(AnalysisTask.org_id == org_id)
            if status_filter:
                query = query.filter(AnalysisTask.status == status_filter)
            return query.order_by(AnalysisTask.created_at.desc()).all()
        finally:
            if owns_session:
                db.close()

    @staticmethod
    def _record_history(
        task_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        details: dict,
        db,
    ):
        """
        Append a ``task_history`` row. Does not commit — the caller's next
        ``db.commit()`` persists it (keeps the audit entry in the same
        transaction as the state change it describes).
        """
        history = TaskHistory(
            id=uuid.uuid4(),
            task_id=task_id,
            user_id=user_id,
            action=action,
            details=details,
        )
        db.add(history)
