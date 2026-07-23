"""
Tests for the result aggregator service (``server.services.result_aggregator``).

Service-layer tests: they call ``ResultAggregator.<method>(..., db=mock_db)``
directly with a :class:`~unittest.mock.MagicMock` session — no FastAPI dependency
injection, no live DB (the ORM models use PostgreSQL-native ``JSONB`` /
``UUID``). Same mock-DB approach as ``tests/test_task_orchestrator.py``.

What is verified
----------------
* ``store_result`` / ``store_results`` persist ``AnalysisResult`` rows using the
  ``result_metadata`` attribute (the reserved ``metadata`` column is mapped to
  it), enforce the ``result_type`` CHECK-constraint set, and enforce task
  existence + client ownership.
* ``store_llm_analysis`` persists an ``LLMAnalysis`` row, enforcing task
  existence.
* ``get_task_results`` / ``get_task_llm_analyses`` return the rows newest-first.
* The ``owns_session`` / ``try`` / ``finally`` contract: a self-opened session
  (``db=None``) is always closed — including when validation raises *before* the
  query — and a provided session is never closed.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from server.models.database import AnalysisResult, AnalysisTask, LLMAnalysis
from server.services.result_aggregator import ResultAggregator


# -----------------------------------------------------------------------------
# ORM instance factories (transient — never added to a real session)
# -----------------------------------------------------------------------------


def _task(task_id=None, org_id=None, client_id=None, status="queued"):
    return AnalysisTask(
        id=task_id or uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        client_id=client_id or uuid.uuid4(),
        user_id=uuid.uuid4(),
        disk_image_id=uuid.uuid4(),
        task_name="Test Analysis",
        analysis_type="full",
        status=status,
        progress=0,
        task_metadata={},
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _populate_defaults_on_refresh(obj):
    """Simulate the DB applying the ``created_at`` server default on refresh."""
    if getattr(obj, "created_at", None) is None:
        obj.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _mock_db():
    db = MagicMock()
    db.refresh.side_effect = _populate_defaults_on_refresh
    return db


def _added_instances(mock_db):
    """Return the ORM objects passed to ``db.add``, in call order."""
    return [call.args[0] for call in mock_db.add.call_args_list]


# -----------------------------------------------------------------------------
# store_result
# -----------------------------------------------------------------------------


def test_store_result_success():
    db = _mock_db()
    client_id = uuid.uuid4()
    task = _task(client_id=client_id)
    db.query.return_value.filter.return_value.first.return_value = task

    result = ResultAggregator.store_result(
        task_id=task.id,
        client_id=client_id,
        result_type="database",
        file_path="/out/case.sqlite",
        file_size=4096,
        storage_location="s3://tracelens/case.sqlite",
        result_metadata={"table_count": 12},
        db=db,
    )

    assert result.task_id == task.id
    assert result.client_id == client_id
    assert result.result_type == "database"
    assert result.file_path == "/out/case.sqlite"
    assert result.file_size == 4096
    # The reserved ``metadata`` column is mapped to ``result_metadata``.
    assert result.result_metadata == {"table_count": 12}
    db.add.assert_called_once()
    db.commit.assert_called_once()
    db.close.assert_not_called()  # provided session is not owned


def test_store_result_invalid_type_raises_before_add():
    db = _mock_db()

    with pytest.raises(ValueError, match="Invalid result_type"):
        ResultAggregator.store_result(
            task_id=uuid.uuid4(),
            client_id=uuid.uuid4(),
            result_type="nonsense",
            db=db,
        )

    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_store_result_task_not_found():
    db = _mock_db()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(ValueError, match="Task not found"):
        ResultAggregator.store_result(
            task_id=uuid.uuid4(),
            client_id=uuid.uuid4(),
            result_type="file",
            db=db,
        )

    db.add.assert_not_called()


def test_store_result_client_mismatch():
    """A client posting into a task owned by a different client -> ValueError."""
    db = _mock_db()
    task = _task(client_id=uuid.uuid4())  # owned by someone else
    db.query.return_value.filter.return_value.first.return_value = task

    with pytest.raises(ValueError, match="Client does not own this task"):
        ResultAggregator.store_result(
            task_id=task.id,
            client_id=uuid.uuid4(),  # not the owner
            result_type="file",
            db=db,
        )

    db.add.assert_not_called()


def test_store_result_defaults_empty_metadata():
    """Omitting result_metadata stores an empty dict (DB default=dict)."""
    db = _mock_db()
    client_id = uuid.uuid4()
    task = _task(client_id=client_id)
    db.query.return_value.filter.return_value.first.return_value = task

    result = ResultAggregator.store_result(
        task_id=task.id,
        client_id=client_id,
        result_type="metadata",
        db=db,
    )

    assert result.result_metadata == {}


# -----------------------------------------------------------------------------
# store_results (bulk)
# -----------------------------------------------------------------------------


def test_store_results_bulk_single_commit():
    db = _mock_db()
    client_id = uuid.uuid4()
    task = _task(client_id=client_id)
    db.query.return_value.filter.return_value.first.return_value = task

    items = [
        {
            "result_type": "database",
            "file_path": "/out/case.sqlite",
            "result_metadata": {"t": 1},
        },
        {"result_type": "file", "file_path": "/out/carved/1.doc"},
        {"result_type": "metadata"},
    ]

    created = ResultAggregator.store_results(task.id, client_id, items, db=db)

    assert len(created) == 3
    assert [r.result_type for r in created] == ["database", "file", "metadata"]
    added = _added_instances(db)
    assert all(isinstance(o, AnalysisResult) for o in added)
    assert len(added) == 3
    # Single transaction for the whole batch.
    db.commit.assert_called_once()
    # Each row refreshed (for the created_at server default).
    assert db.refresh.call_count == 3


def test_store_results_invalid_type_aborts_before_add():
    db = _mock_db()

    with pytest.raises(ValueError, match="Invalid result_type"):
        ResultAggregator.store_results(
            uuid.uuid4(),
            uuid.uuid4(),
            [{"result_type": "database"}, {"result_type": "bogus"}],
            db=db,
        )

    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_store_results_task_not_found():
    db = _mock_db()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(ValueError, match="Task not found"):
        ResultAggregator.store_results(
            uuid.uuid4(),
            uuid.uuid4(),
            [{"result_type": "file"}],
            db=db,
        )

    db.add.assert_not_called()


def test_store_results_empty_list():
    """An empty list creates nothing and still commits (idempotent no-op)."""
    db = _mock_db()
    client_id = uuid.uuid4()
    task = _task(client_id=client_id)
    db.query.return_value.filter.return_value.first.return_value = task

    created = ResultAggregator.store_results(task.id, client_id, [], db=db)

    assert created == []
    db.add.assert_not_called()
    db.commit.assert_called_once()


# -----------------------------------------------------------------------------
# store_llm_analysis
# -----------------------------------------------------------------------------


def test_store_llm_analysis_success():
    db = _mock_db()
    task = _task()
    db.query.return_value.filter.return_value.first.return_value = task

    record = ResultAggregator.store_llm_analysis(
        task_id=task.id,
        analysis_result="This file is a Windows registry hive...",
        file_path="/out/carved/SYSTEM",
        input_text_hash="sha256:abc",
        model_used="claude-sonnet-5",
        tokens_used=1234,
        cost=Decimal("0.0123"),
        db=db,
    )

    assert record.task_id == task.id
    assert record.analysis_result == "This file is a Windows registry hive..."
    assert record.model_used == "claude-sonnet-5"
    assert record.tokens_used == 1234
    assert record.cost == Decimal("0.0123")
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_store_llm_analysis_task_not_found():
    db = _mock_db()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(ValueError, match="Task not found"):
        ResultAggregator.store_llm_analysis(
            task_id=uuid.uuid4(),
            analysis_result="x",
            db=db,
        )

    db.add.assert_not_called()


# -----------------------------------------------------------------------------
# Retrieval
# -----------------------------------------------------------------------------


def test_get_task_results():
    db = _mock_db()
    results = [
        AnalysisResult(
            id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            client_id=uuid.uuid4(),
            result_type="database",
            result_metadata={},
        ),
        AnalysisResult(
            id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            client_id=uuid.uuid4(),
            result_type="file",
            result_metadata={},
        ),
    ]
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = results

    got = ResultAggregator.get_task_results(uuid.uuid4(), db=db)

    assert got == results


def test_get_task_llm_analyses():
    db = _mock_db()
    records = [
        LLMAnalysis(
            id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            analysis_result="a",
        )
    ]
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = records

    got = ResultAggregator.get_task_llm_analyses(uuid.uuid4(), db=db)

    assert got == records


# -----------------------------------------------------------------------------
# owns_session / leak contract
# -----------------------------------------------------------------------------


def test_store_result_closes_owned_session(monkeypatch):
    fake = _mock_db()
    task = _task()
    fake.query.return_value.filter.return_value.first.return_value = task
    monkeypatch.setattr(
        "server.services.result_aggregator.SessionLocal", lambda: fake
    )

    ResultAggregator.store_result(
        task_id=task.id,
        client_id=task.client_id,
        result_type="database",
        db=None,
    )

    fake.close.assert_called_once()


def test_store_result_closes_owned_session_on_validation_error(monkeypatch):
    """Validation raises BEFORE the query, but the owned session is still closed."""
    fake = _mock_db()
    monkeypatch.setattr(
        "server.services.result_aggregator.SessionLocal", lambda: fake
    )

    with pytest.raises(ValueError, match="Invalid result_type"):
        ResultAggregator.store_result(
            task_id=uuid.uuid4(),
            client_id=uuid.uuid4(),
            result_type="bogus",
            db=None,
        )

    fake.close.assert_called_once()
    fake.query.assert_not_called()


def test_store_result_does_not_close_provided_session():
    db = _mock_db()
    task = _task()
    db.query.return_value.filter.return_value.first.return_value = task

    ResultAggregator.store_result(
        task_id=task.id,
        client_id=task.client_id,
        result_type="database",
        db=db,
    )

    db.close.assert_not_called()


def test_store_results_closes_owned_session(monkeypatch):
    fake = _mock_db()
    task = _task()
    fake.query.return_value.filter.return_value.first.return_value = task
    monkeypatch.setattr(
        "server.services.result_aggregator.SessionLocal", lambda: fake
    )

    ResultAggregator.store_results(
        task_id=task.id,
        client_id=task.client_id,
        results=[{"result_type": "file"}],
        db=None,
    )

    fake.close.assert_called_once()


def test_get_task_results_closes_owned_session(monkeypatch):
    fake = _mock_db()
    fake.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    monkeypatch.setattr(
        "server.services.result_aggregator.SessionLocal", lambda: fake
    )

    ResultAggregator.get_task_results(uuid.uuid4(), db=None)

    fake.close.assert_called_once()


if __name__ == "__main__":
    import pytest as _pytest

    _pytest.main([__file__, "-v"])
