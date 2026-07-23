"""
Result upload and retrieval API endpoints.

The result sub-resource under ``/api/tasks/{task_id}``, wrapping the Task 14
:class:`server.services.result_aggregator.ResultAggregator`. Two distinct auth
models meet here:

* **Upload** (``POST /api/tasks/{task_id}/results``) is **client-auth** — a
  client posts the artifacts it produced for a task it owns
  (``task.client_id == current_client.id``).
* **Retrieval** (``GET .../results``, ``GET .../llm-analyses``) is **user-auth,
  org-scoped** — the web UI reads a task's results within its own org
  (``task.org_id == current_user.org_id``, super_admin cross-org).

Prefix note
-----------
This router declares ``prefix="/api/tasks"`` — the same prefix as
:mod:`server.api.tasks` (Task 13). That is intentional and safe: FastAPI matches
routes by full method + path, and the sub-paths here (``/{task_id}/results``,
``/{task_id}/llm-analyses``) do not collide with Task 13's ``/``,
``/{task_id}``, ``/{task_id}/cancel``. Results are a sub-resource of tasks, so
nesting under the tasks prefix is the natural shape.

Org isolation + ownership are enforced here, at the API boundary; the service
trusts the ids it is handed (the Task 14 forward note).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from server.db.session import get_db
from server.middleware.auth import get_current_client, get_current_user
from server.models.database import AnalysisTask, Client, User
from server.models.schemas import (
    AnalysisResultResponse,
    LLMAnalysisResponse,
    ResultUploadRequest,
)
from server.services.result_aggregator import ResultAggregator

router = APIRouter(prefix="/api/tasks", tags=["Results"])


def _get_task_owned_by_org(
    task_id: uuid.UUID, current_user: User, db: Session
) -> AnalysisTask:
    """Fetch a task for a user-token caller, enforcing org isolation.

    Raises:
        HTTPException: 404 if the task does not exist; 403 on cross-org access.
    """
    task = db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()
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


@router.post(
    "/{task_id}/results", response_model=list[AnalysisResultResponse]
)
async def upload_results(
    task_id: uuid.UUID,
    payload: ResultUploadRequest,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Upload the artifacts a client produced for a task (client-auth).

    The authenticated client must own the task. The aggregator re-verifies this
    at the service layer (defense in depth).

    Raises:
        HTTPException: 404 if the task does not exist; 403 if the client does not
            own it.
    """
    # Ownership gate (the service re-checks; the accepted double-query).
    task = db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    if task.client_id != current_client.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return ResultAggregator.store_results(
        task_id=task_id,
        client_id=current_client.id,
        results=[artifact.model_dump() for artifact in payload.artifacts],
        db=db,
    )


@router.get(
    "/{task_id}/results", response_model=list[AnalysisResultResponse]
)
async def get_task_results(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List a task's artifacts (user-auth, org-scoped).

    Raises:
        HTTPException: 404 if the task does not exist; 403 on cross-org access.
    """
    _get_task_owned_by_org(task_id, current_user, db)
    return ResultAggregator.get_task_results(task_id, db)


@router.get(
    "/{task_id}/llm-analyses", response_model=list[LLMAnalysisResponse]
)
async def get_task_llm_analyses(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List a task's LLM analyses (user-auth, org-scoped).

    Raises:
        HTTPException: 404 if the task does not exist; 403 on cross-org access.
    """
    _get_task_owned_by_org(task_id, current_user, db)
    return ResultAggregator.get_task_llm_analyses(task_id, db)
