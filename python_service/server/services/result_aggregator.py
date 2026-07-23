"""
Result aggregator service for storing and retrieving analysis artifacts.

Sits on the result side of the pipeline: when a client finishes an
``analyze_disk`` command it produces artifacts (a forensic SQLite database,
carved files, metadata) and LLM-analyzable text. This service persists those as
``analysis_results`` / ``llm_analysis`` rows attached to the originating task.
It is the result-side analogue of :mod:`server.services.task_orchestrator`.

Every public method accepts an optional ``db`` session. When ``db`` is ``None``
the method opens (and closes) its own session via :data:`SessionLocal` — the
``owns_session`` / ``try`` / ``finally`` pattern from
:mod:`server.services.command_queue`, so background callers cannot exhaust the
connection pool.

Org scope note
--------------
Like the orchestrator, this service trusts the ids it is handed and does NOT
re-derive organization. Organization isolation is enforced at the API layer
(Task 15 ``api/results.py``): a client-token caller may only post results for
its own tasks; a user-token caller fetching results must be org-scoped to the
task's org. What this service *does* enforce is data integrity — the task must
exist, and a result's ``client_id`` must match the task's owner (so one client
cannot inject results into a sibling task).

Datetime note
-------------
Neither model is timestamped by this service: ``created_at`` is a
``server_default=func.now()`` column, so the DB applies it. There is therefore
no ``utcnow`` here — the service never sets a timestamp.
"""
import uuid
from typing import List, Optional

from sqlalchemy.orm import Session

from server.db.session import SessionLocal
from server.models.database import AnalysisResult, AnalysisTask, LLMAnalysis

# The DB CHECK constraint allows exactly these result types.
_VALID_RESULT_TYPES = ("database", "file", "metadata")


class ResultAggregator:
    """Persists and retrieves the artifacts an analysis task produces."""

    # -------------------------------------------------------------------------
    # Result (artifact) storage
    # -------------------------------------------------------------------------

    @staticmethod
    def store_result(
        task_id: uuid.UUID,
        client_id: uuid.UUID,
        result_type: str,
        file_path: Optional[str] = None,
        file_size: Optional[int] = None,
        storage_location: Optional[str] = None,
        result_metadata: Optional[dict] = None,
        db: Optional[Session] = None,
    ) -> AnalysisResult:
        """
        Store a single analysis artifact.

        Args:
            task_id: Task the artifact belongs to.
            client_id: Client that produced it (must own the task).
            result_type: One of database / file / metadata.
            file_path: Optional path the artifact is known by on the client.
            file_size: Optional size in bytes.
            storage_location: Optional server-side storage handle.
            result_metadata: Optional freeform metadata (JSONB).
            db: Optional database session.

        Returns:
            The created analysis result.

        Raises:
            ValueError: If ``result_type`` is invalid, the task is not found,
                or ``client_id`` does not own the task.
        """
        owns_session = db is None
        if owns_session:
            db = SessionLocal()
        try:
            if result_type not in _VALID_RESULT_TYPES:
                raise ValueError(
                    f"Invalid result_type: {result_type!r} "
                    f"(must be one of {_VALID_RESULT_TYPES})"
                )

            task = ResultAggregator._get_task_or_raise(task_id, client_id, db)

            # ``metadata`` is reserved in SQLAlchemy; the column is mapped to
            # the ``result_metadata`` attribute.
            result = AnalysisResult(
                id=uuid.uuid4(),
                task_id=task.id,
                client_id=task.client_id,
                result_type=result_type,
                file_path=file_path,
                file_size=file_size,
                storage_location=storage_location,
                result_metadata=result_metadata or {},
            )
            db.add(result)
            db.commit()
            db.refresh(result)
            return result
        finally:
            if owns_session:
                db.close()

    @staticmethod
    def store_results(
        task_id: uuid.UUID,
        client_id: uuid.UUID,
        results: List[dict],
        db: Optional[Session] = None,
    ) -> List[AnalysisResult]:
        """
        Store several artifacts for a task in a single transaction.

        Args:
            task_id: Task the artifacts belong to.
            client_id: Client that produced them (must own the task).
            results: Each dict may carry ``result_type`` (required),
                ``file_path``, ``file_size``, ``storage_location``,
                ``result_metadata``.
            db: Optional database session.

        Returns:
            The created analysis results, in input order.

        Raises:
            ValueError: If any result has an invalid ``result_type``, the task
                is not found, or ``client_id`` does not own the task.
        """
        owns_session = db is None
        if owns_session:
            db = SessionLocal()
        try:
            # Validate every type up front so a bad item fails before any write.
            for item in results:
                rtype = item.get("result_type")
                if rtype not in _VALID_RESULT_TYPES:
                    raise ValueError(
                        f"Invalid result_type: {rtype!r} "
                        f"(must be one of {_VALID_RESULT_TYPES})"
                    )

            task = ResultAggregator._get_task_or_raise(task_id, client_id, db)

            created: List[AnalysisResult] = []
            for item in results:
                result = AnalysisResult(
                    id=uuid.uuid4(),
                    task_id=task.id,
                    client_id=task.client_id,
                    result_type=item["result_type"],
                    file_path=item.get("file_path"),
                    file_size=item.get("file_size"),
                    storage_location=item.get("storage_location"),
                    result_metadata=item.get("result_metadata") or {},
                )
                db.add(result)
                created.append(result)

            db.commit()
            for result in created:
                db.refresh(result)
            return created
        finally:
            if owns_session:
                db.close()

    # -------------------------------------------------------------------------
    # LLM analysis storage
    # -------------------------------------------------------------------------

    @staticmethod
    def store_llm_analysis(
        task_id: uuid.UUID,
        analysis_result: str,
        file_path: Optional[str] = None,
        input_text_hash: Optional[str] = None,
        model_used: Optional[str] = None,
        tokens_used: Optional[int] = None,
        cost=None,
        file_id: Optional[uuid.UUID] = None,
        db: Optional[Session] = None,
    ) -> LLMAnalysis:
        """
        Store a single LLM-produced analysis record for a task.

        Args:
            task_id: Task the analysis belongs to.
            analysis_result: The LLM output text (non-nullable in the model).
            file_path: Optional path of the analyzed file on the client.
            input_text_hash: Optional hash of the submitted text (dedup key).
            model_used: Optional model identifier.
            tokens_used: Optional token count.
            cost: Optional cost (Numeric(10,4)).
            file_id: Optional client-side file id.
            db: Optional database session.

        Returns:
            The created LLM analysis record.

        Raises:
            ValueError: If the task is not found.
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

            record = LLMAnalysis(
                id=uuid.uuid4(),
                task_id=task.id,
                file_id=file_id,
                file_path=file_path,
                input_text_hash=input_text_hash,
                analysis_result=analysis_result,
                model_used=model_used,
                tokens_used=tokens_used,
                cost=cost,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record
        finally:
            if owns_session:
                db.close()

    # -------------------------------------------------------------------------
    # Retrieval
    # -------------------------------------------------------------------------

    @staticmethod
    def get_task_results(
        task_id: uuid.UUID,
        db: Optional[Session] = None,
    ) -> List[AnalysisResult]:
        """List a task's artifacts, newest first."""
        owns_session = db is None
        if owns_session:
            db = SessionLocal()
        try:
            return (
                db.query(AnalysisResult)
                .filter(AnalysisResult.task_id == task_id)
                .order_by(AnalysisResult.created_at.desc())
                .all()
            )
        finally:
            if owns_session:
                db.close()

    @staticmethod
    def get_task_llm_analyses(
        task_id: uuid.UUID,
        db: Optional[Session] = None,
    ) -> List[LLMAnalysis]:
        """List a task's LLM analyses, newest first."""
        owns_session = db is None
        if owns_session:
            db = SessionLocal()
        try:
            return (
                db.query(LLMAnalysis)
                .filter(LLMAnalysis.task_id == task_id)
                .order_by(LLMAnalysis.created_at.desc())
                .all()
            )
        finally:
            if owns_session:
                db.close()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _get_task_or_raise(
        task_id: uuid.UUID,
        client_id: uuid.UUID,
        db: Session,
    ) -> AnalysisTask:
        """
        Fetch a task, enforcing existence and client ownership.

        Raises:
            ValueError: If the task is not found, or ``client_id`` does not own
                it (a client must not post results into another client's task).
        """
        task = db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()
        if not task:
            raise ValueError("Task not found")
        if task.client_id != client_id:
            raise ValueError("Client does not own this task")
        return task
