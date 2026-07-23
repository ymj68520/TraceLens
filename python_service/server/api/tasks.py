"""
Task management API endpoints.

User-facing surface for analysis tasks — the analogue of ``server.api.commands``
for the :class:`server.services.task_orchestrator.TaskOrchestrator`:

* ``POST /api/tasks``                 - create a task (user-auth, org-scoped)
* ``GET  /api/tasks``                 - list tasks in the caller's org
* ``GET  /api/tasks/{task_id}``       - get a task (user-auth, org-scoped)
* ``POST /api/tasks/{task_id}/cancel``- cancel a task (user-auth, org-scoped)

Access control
--------------
The orchestrator service *trusts* the ``org_id`` it is handed, so organization
isolation is enforced here, at the API boundary (the Task 12 reviewer forward
note): ``org_id`` is always derived from ``current_user.org_id``, never the
request body. ``super_admin`` may act across orgs; every other role is scoped to
its own org (403 "Access denied" on cross-org access).

On create, the target disk image is additionally verified to belong to the
target client — otherwise a caller could reference another org's disk image and
its ``path`` would leak into the command's ``image_path``. A mismatch is treated
as "not found" (no existence leak).
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from server.db.session import get_db
from server.middleware.auth import get_current_user
from server.models.database import Client, DiskImage, User
from server.models.schemas import AnalysisTaskCreate, AnalysisTaskResponse
from server.services.task_orchestrator import TaskOrchestrator

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


@router.post("", response_model=AnalysisTaskResponse)
async def create_task(
    task_data: AnalysisTaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new analysis task.

    ``org_id`` is derived from the authenticated user (never the body). The
    client must be in the caller's org, and the disk image must belong to that
    client.

    Raises:
        HTTPException: 404 if the client or disk image is not found (or the disk
            image does not belong to the client); 403 on cross-org access.
    """
    # Org-scope + existence on the client.
    client = db.query(Client).filter(Client.id == task_data.client_id).first()
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

    # The disk image must exist AND belong to this client (transitively
    # org-scoped). A mismatch is reported as not-found to avoid leaking that an
    # image exists under a different client.
    disk_image = db.query(DiskImage).filter(
        DiskImage.id == task_data.disk_image_id
    ).first()
    if not disk_image or disk_image.client_id != client.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disk image not found",
        )

    try:
        return TaskOrchestrator.create_analysis_task(
            org_id=current_user.org_id,
            user_id=current_user.id,
            client_id=task_data.client_id,
            disk_image_id=task_data.disk_image_id,
            task_name=task_data.task_name,
            analysis_type=task_data.analysis_type,
            priority=task_data.priority,
            ttl_hours=task_data.ttl_hours,
            db=db,
        )
    except ValueError as e:
        # Defensive: both resources were just verified, but a race could remove
        # one before the service re-checks.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("", response_model=List[AnalysisTaskResponse])
async def list_tasks(
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List tasks in the caller's organization, newest first.

    An optional ``status_filter`` narrows the result. Non-admin filtering to a
    user's own tasks is deferred to a later task.
    """
    return TaskOrchestrator.list_user_tasks(
        current_user.id, current_user.org_id, status_filter, db
    )


@router.get("/{task_id}", response_model=AnalysisTaskResponse)
async def get_task(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get a task's status and progress (org-scoped).

    Raises:
        HTTPException: 404 if the task does not exist; 403 on cross-org access.
    """
    task = TaskOrchestrator.get_task_status(task_id, db)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    if current_user.role != "super_admin" and current_user.org_id != task.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return task


@router.post("/{task_id}/cancel", response_model=AnalysisTaskResponse)
async def cancel_task(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Cancel a task (org-scoped). Fails the task's still-runnable command.

    Raises:
        HTTPException: 404 if the task does not exist; 403 on cross-org access;
            409 if the task is already in a terminal state.
    """
    task = TaskOrchestrator.get_task_status(task_id, db)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    if current_user.role != "super_admin" and current_user.org_id != task.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    try:
        return TaskOrchestrator.cancel_task(task_id, current_user.id, db)
    except ValueError:
        # Terminal state (completed/failed/cancelled) — existence was just checked.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict",
        )
