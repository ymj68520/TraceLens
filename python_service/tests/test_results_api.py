"""
Tests for the result upload/retrieval API endpoints (``server.api.results``).

Exercises the result sub-resource under ``/api/tasks/{task_id}``:

* ``POST /api/tasks/{task_id}/results``        - client uploads artifacts
  (success / task-404 / wrong-client-403)
* ``GET  /api/tasks/{task_id}/results``        - user lists artifacts
  (success / 404 / cross-org-403)
* ``GET  /api/tasks/{task_id}/llm-analyses``   - user lists LLM analyses
  (success / 404 / cross-org-403)

Strategy
--------
Mock-DB (MagicMock; ORM models use PostgreSQL-native JSONB/UUID, no live DB),
same as ``tests/test_commands_api.py``. Two auth overrides: ``client_as`` for
the upload endpoint (client-token) and ``auth_as`` for retrieval (user-token).

``_populate_defaults_on_refresh`` on ``db.refresh`` supplies the ``created_at``
server default so the freshly-created ``AnalysisResult`` rows serialize into
``AnalysisResultResponse`` (BaseSchema requires a non-None ``created_at``).
"""
import os

# Select the HS256 development path so any tokens created/verified match.
os.environ.setdefault("ENVIRONMENT", "development")

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.middleware.auth import get_current_client, get_current_user
from server.models.database import (
    AnalysisResult,
    AnalysisTask,
    Client,
    LLMAnalysis,
    User,
)


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


def _client(client_id=None, org_id=None):
    return Client(
        id=client_id or uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        hostname="station-01",
        status="online",
        last_poll=None,
        last_seen=None,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _task(task_id=None, org_id=None, client_id=None, status="completed"):
    return AnalysisTask(
        id=task_id or uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        client_id=client_id or uuid.uuid4(),
        user_id=uuid.uuid4(),
        disk_image_id=uuid.uuid4(),
        task_name="Test Analysis",
        analysis_type="full",
        status=status,
        progress=100,
        task_metadata={},
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _result(result_id=None, task_id=None, client_id=None, result_type="database"):
    return AnalysisResult(
        id=result_id or uuid.uuid4(),
        task_id=task_id or uuid.uuid4(),
        client_id=client_id or uuid.uuid4(),
        result_type=result_type,
        file_path="/out/case.sqlite",
        file_size=4096,
        storage_location="s3://tracelens/case.sqlite",
        result_metadata={"table_count": 12},
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _llm(llm_id=None, task_id=None, analysis_result="A Windows registry hive."):
    return LLMAnalysis(
        id=llm_id or uuid.uuid4(),
        task_id=task_id or uuid.uuid4(),
        file_path="/out/carved/SYSTEM",
        input_text_hash="sha256:abc",
        analysis_result=analysis_result,
        model_used="claude-sonnet-5",
        tokens_used=1234,
        cost=Decimal("1.5"),
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _populate_defaults_on_refresh(obj):
    """Simulate the DB applying the ``created_at`` server default on refresh."""
    if getattr(obj, "created_at", None) is None:
        obj.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _upload_payload():
    return {
        "artifacts": [
            {
                "result_type": "database",
                "file_path": "/out/case.sqlite",
                "file_size": 4096,
                "storage_location": "s3://tracelens/case.sqlite",
                "result_metadata": {"table_count": 12},
            },
            {"result_type": "file", "file_path": "/out/carved/1.doc"},
        ]
    }


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    db = MagicMock()
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
    """Install ``user`` (a User) as the authenticated user identity."""
    async def _override():
        return user

    app.dependency_overrides[get_current_user] = _override


def client_as(cli):
    """Install ``cli`` (a Client) as the authenticated client identity."""
    async def _override():
        return cli

    app.dependency_overrides[get_current_client] = _override


# -----------------------------------------------------------------------------
# POST /api/tasks/{task_id}/results  (client-auth)
# -----------------------------------------------------------------------------


def test_upload_results_success(client, mock_db):
    """The owning client uploads artifacts -> 200, two results stored."""
    cli = _client()
    task = _task(client_id=cli.id)
    client_as(cli)
    # Endpoint task lookup, then the service's ownership re-check.
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        task, task,
    ]

    response = client.post(
        f"/api/tasks/{task.id}/results", json=_upload_payload()
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert [r["result_type"] for r in data] == ["database", "file"]
    assert data[0]["client_id"] == str(cli.id)
    # Single transaction for the batch.
    mock_db.commit.assert_called_once()
    # Two rows added + refreshed (created_at server default applied).
    assert mock_db.add.call_count == 2
    assert mock_db.refresh.call_count == 2


def test_upload_results_task_not_found(client, mock_db):
    """Unknown task -> 404 before any write."""
    client_as(_client())
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.post(
        f"/api/tasks/{uuid.uuid4()}/results", json=_upload_payload()
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()


def test_upload_results_wrong_client_forbidden(client, mock_db):
    """A client uploading into a task owned by another client -> 403."""
    me = _client()
    task = _task(client_id=uuid.uuid4())  # owned by someone else
    client_as(me)
    mock_db.query.return_value.filter.return_value.first.return_value = task

    response = client.post(
        f"/api/tasks/{task.id}/results", json=_upload_payload()
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()


def test_upload_results_empty_batch(client, mock_db):
    """An empty artifact list is a no-op store that still returns 200."""
    cli = _client()
    task = _task(client_id=cli.id)
    client_as(cli)
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        task, task,
    ]

    response = client.post(
        f"/api/tasks/{task.id}/results", json={"artifacts": []}
    )

    assert response.status_code == 200
    assert response.json() == []
    mock_db.add.assert_not_called()


def test_upload_results_invalid_result_type_rejected(client, mock_db):
    """Pydantic pattern validation rejects a bad result_type at the boundary."""
    cli = _client()
    task = _task(client_id=cli.id)
    client_as(cli)
    mock_db.query.return_value.filter.return_value.first.return_value = task

    response = client.post(
        f"/api/tasks/{task.id}/results",
        json={"artifacts": [{"result_type": "bogus"}]},
    )

    assert response.status_code == 422
    mock_db.add.assert_not_called()


# -----------------------------------------------------------------------------
# GET /api/tasks/{task_id}/results  (user-auth, org-scoped)
# -----------------------------------------------------------------------------


def test_get_task_results_success(client, mock_db):
    """super_admin lists a task's artifacts -> 200."""
    task = _task()
    results = [_result(task_id=task.id), _result(task_id=task.id, result_type="file")]
    auth_as(_user(role="super_admin"))
    # Endpoint org-scope gate (.first) + service get (.order_by().all) coexist.
    chain = mock_db.query.return_value.filter.return_value
    chain.first.return_value = task
    chain.order_by.return_value.all.return_value = results

    response = client.get(f"/api/tasks/{task.id}/results")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["result_type"] == "database"
    assert data[0]["result_metadata"] == {"table_count": 12}


def test_get_task_results_same_org_allowed(client, mock_db):
    """An analyst reads results for a task in their own org -> 200."""
    org_id = uuid.uuid4()
    task = _task(org_id=org_id)
    auth_as(_user(role="analyst", org_id=org_id))
    chain = mock_db.query.return_value.filter.return_value
    chain.first.return_value = task
    chain.order_by.return_value.all.return_value = []

    response = client.get(f"/api/tasks/{task.id}/results")

    assert response.status_code == 200


def test_get_task_results_not_found(client, mock_db):
    """Unknown task -> 404."""
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.get(f"/api/tasks/{uuid.uuid4()}/results")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_get_task_results_cross_org_forbidden(client, mock_db):
    """A non-super_admin reading another org's task results -> 403."""
    task = _task(org_id=uuid.uuid4())
    auth_as(_user(role="analyst", org_id=uuid.uuid4()))
    mock_db.query.return_value.filter.return_value.first.return_value = task

    response = client.get(f"/api/tasks/{task.id}/results")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


# -----------------------------------------------------------------------------
# GET /api/tasks/{task_id}/llm-analyses  (user-auth, org-scoped)
# -----------------------------------------------------------------------------


def test_get_task_llm_analyses_success(client, mock_db):
    """super_admin lists a task's LLM analyses -> 200 (Decimal cost round-trips)."""
    task = _task()
    records = [_llm(task_id=task.id)]
    auth_as(_user(role="super_admin"))
    chain = mock_db.query.return_value.filter.return_value
    chain.first.return_value = task
    chain.order_by.return_value.all.return_value = records

    response = client.get(f"/api/tasks/{task.id}/llm-analyses")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["analysis_result"] == "A Windows registry hive."
    assert data[0]["model_used"] == "claude-sonnet-5"
    # Numeric(10,4) cost: Pydantic v2 serializes Decimal as a JSON string to
    # preserve precision (no float loss).
    assert data[0]["cost"] == "1.5"


def test_get_task_llm_analyses_not_found(client, mock_db):
    """Unknown task -> 404."""
    auth_as(_user(role="super_admin"))
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.get(f"/api/tasks/{uuid.uuid4()}/llm-analyses")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_get_task_llm_analyses_cross_org_forbidden(client, mock_db):
    """A non-super_admin reading another org's LLM analyses -> 403."""
    task = _task(org_id=uuid.uuid4())
    auth_as(_user(role="analyst", org_id=uuid.uuid4()))
    mock_db.query.return_value.filter.return_value.first.return_value = task

    response = client.get(f"/api/tasks/{task.id}/llm-analyses")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


if __name__ == "__main__":
    import pytest as _pytest

    _pytest.main([__file__, "-v"])
