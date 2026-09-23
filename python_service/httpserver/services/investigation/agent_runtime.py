"""Agent Investigation Runtime persistence (Agent Architecture v0, Phase 1).

Deterministic lifecycle foundation only: Investigation / Agent Run /
Delegation state machines, append-only Working State revisions, append-only
Trajectory (Action Trace, never model Chain-of-Thought), the Tool Observation
storage boundary, admission/idempotency primitives, and restart recovery.

Scope guards (P1):
  - the task-owned investigation.db stays the only runtime store; every row
    is task-scoped and composite-FKed onto ``agent_investigations``.
  - no LLM, no PydanticAI, no executor: callers drive lifecycle transitions
    explicitly (tests use fake/manual transitions).
  - canonical Investigation objects (Evidence Snapshot, Secondary Analysis,
    Claims, Review, Report Evidence) are NOT touched; the runtime only
    persists its own state plus opaque references.

DB-level guarantees live in ``repository.py`` (v8 DDL): one active run per
investigation via partial unique index, legal-transition and state-field
triggers, sequential hash-chained revisions, INSERT-only trajectory.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class AgentRuntimeConflictError(RuntimeError):
    """The row exists but the requested transition conflicts."""


class WorkingStateRevisionConflictError(AgentRuntimeConflictError):
    """Optimistic revision guard failed or the operation key is bound to
    different content; the commit is rejected (fail closed)."""


class AgentInvestigationStatus(str, Enum):
    ready = "ready"
    active = "active"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"


class AgentRunStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class RunStopReason(str, Enum):
    finalized = "finalized"
    budget_exhausted = "budget_exhausted"
    user_paused = "user_paused"
    no_progress = "no_progress"
    directive_replan = "directive_replan"
    runtime_restart = "runtime_restart"
    cancelled = "cancelled"
    internal_failure = "internal_failure"


class DelegationStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    stale = "stale"


class InvestigationPauseReason(str, Enum):
    user_paused = "user_paused"
    runtime_restart = "runtime_restart"
    finalization_review_unavailable = "finalization_review_unavailable"


class AgentTrajectoryEventType(str, Enum):
    investigation_created = "investigation_created"
    run_admitted = "run_admitted"
    run_started = "run_started"
    run_completed = "run_completed"
    run_failed = "run_failed"
    run_cancelled = "run_cancelled"
    delegation_admitted = "delegation_admitted"
    delegation_started = "delegation_started"
    delegation_completed = "delegation_completed"
    delegation_failed = "delegation_failed"
    delegation_cancelled = "delegation_cancelled"
    delegation_stale = "delegation_stale"
    working_state_committed = "working_state_committed"
    runtime_recovered = "runtime_recovered"
    investigation_paused = "investigation_paused"
    investigation_completed = "investigation_completed"
    investigation_cancelled = "investigation_cancelled"
    # P2 deterministic control plane
    attention_compiled = "attention_compiled"
    transition_decision_validated = "transition_decision_validated"
    transition_decision_rejected = "transition_decision_rejected"
    working_state_integrated = "working_state_integrated"
    no_progress_detected = "no_progress_detected"
    finalization_requested = "finalization_requested"
    finalization_denied = "finalization_denied"
    finalization_stale = "finalization_stale"
    finalization_completed = "finalization_completed"
    # P3 freeze follow-up (F2): tool action audit event (schema v10).
    # Observation = what the tool returned; this event = that the runtime
    # performed the action. One atomic INSERT pair per successful call.
    tool_observation_recorded = "tool_observation_recorded"
    # P4B (§35 minimal v12): supervisor decision audit events.
    supervisor_plan_decided = "supervisor_plan_decided"
    supervisor_integration_committed = "supervisor_integration_committed"


# Application-side transition tables; the identically-shaped DB triggers are
# the enforcing backstop.  completed/cancelled investigations and terminal
# runs/delegations have no outgoing transitions (never re-opened).
INVESTIGATION_TRANSITIONS: dict[
    AgentInvestigationStatus, frozenset[AgentInvestigationStatus]
] = {
    AgentInvestigationStatus.ready: frozenset(
        {AgentInvestigationStatus.active, AgentInvestigationStatus.cancelled}
    ),
    AgentInvestigationStatus.active: frozenset(
        {
            AgentInvestigationStatus.paused,
            AgentInvestigationStatus.completed,
            AgentInvestigationStatus.cancelled,
        }
    ),
    AgentInvestigationStatus.paused: frozenset(
        {AgentInvestigationStatus.active, AgentInvestigationStatus.cancelled}
    ),
    AgentInvestigationStatus.completed: frozenset(),
    AgentInvestigationStatus.cancelled: frozenset(),
}

RUN_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.queued: frozenset(
        {
            AgentRunStatus.running,
            AgentRunStatus.failed,
            AgentRunStatus.cancelled,
        }
    ),
    AgentRunStatus.running: frozenset(
        {
            AgentRunStatus.completed,
            AgentRunStatus.failed,
            AgentRunStatus.cancelled,
        }
    ),
    AgentRunStatus.completed: frozenset(),
    AgentRunStatus.failed: frozenset(),
    AgentRunStatus.cancelled: frozenset(),
}

DELEGATION_TRANSITIONS: dict[DelegationStatus, frozenset[DelegationStatus]] = {
    DelegationStatus.queued: frozenset(
        {
            DelegationStatus.running,
            DelegationStatus.failed,
            DelegationStatus.cancelled,
            DelegationStatus.stale,
        }
    ),
    DelegationStatus.running: frozenset(
        {
            DelegationStatus.completed,
            DelegationStatus.failed,
            DelegationStatus.cancelled,
            DelegationStatus.stale,
        }
    ),
    DelegationStatus.completed: frozenset(),
    DelegationStatus.failed: frozenset(),
    DelegationStatus.cancelled: frozenset(),
    DelegationStatus.stale: frozenset(),
}

_TERMINAL_INVESTIGATION_STATUSES = frozenset(
    {AgentInvestigationStatus.completed, AgentInvestigationStatus.cancelled}
)
_TERMINAL_RUN_STATUSES = frozenset(
    {
        AgentRunStatus.completed,
        AgentRunStatus.failed,
        AgentRunStatus.cancelled,
    }
)
_TERMINAL_DELEGATION_STATUSES = frozenset(
    {
        DelegationStatus.completed,
        DelegationStatus.failed,
        DelegationStatus.cancelled,
        DelegationStatus.stale,
    }
)

_DELEGATION_TRAJECTORY_EVENT = {
    DelegationStatus.completed: AgentTrajectoryEventType.delegation_completed,
    DelegationStatus.failed: AgentTrajectoryEventType.delegation_failed,
    DelegationStatus.cancelled: AgentTrajectoryEventType.delegation_cancelled,
    DelegationStatus.stale: AgentTrajectoryEventType.delegation_stale,
}

# Pause reasons without a direct RunStopReason counterpart cancel the active
# run with the generic ``cancelled`` stop reason (the frozen stop-reason list
# has no finalization-specific value).
_PAUSE_RUN_STOP_REASON = {
    InvestigationPauseReason.user_paused: RunStopReason.user_paused,
    InvestigationPauseReason.runtime_restart: RunStopReason.runtime_restart,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_investigation_id() -> str:
    return f"inv_{uuid.uuid4().hex}"


def _new_run_id() -> str:
    return f"run_{uuid.uuid4().hex}"


def _new_delegation_id() -> str:
    return f"del_{uuid.uuid4().hex}"


def _new_trajectory_event_id() -> str:
    return f"trj_{uuid.uuid4().hex}"


def _new_observation_id() -> str:
    return f"obs_{uuid.uuid4().hex}"


def canonical_state_json(state: Mapping[str, Any]) -> str:
    """Deterministic JSON serialization for working state (same rules as
    ``acquisition.canonical_json``: sorted keys, compact separators)."""
    return json.dumps(
        state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def state_hash_of(state: Mapping[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(canonical_state_json(state).encode("utf-8")).hexdigest()


class AgentInvestigation(BaseModel):
    model_config = ConfigDict(frozen=True)

    investigation_id: str
    task_id: str
    status: AgentInvestigationStatus
    pause_reason: Optional[InvestigationPauseReason]
    created_at: str
    updated_at: str
    completed_at: Optional[str]
    cancelled_at: Optional[str]


class AgentRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    task_id: str
    investigation_id: str
    status: AgentRunStatus
    stop_reason: Optional[RunStopReason]
    error_code: Optional[str]
    error_message: Optional[str]
    idempotency_key: Optional[str]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    failed_at: Optional[str]
    cancelled_at: Optional[str]


class DelegationSpec(BaseModel):
    """Caller-supplied admission unit (One Question x One Source Scope).

    Identity/binding fields are frozen at admission; ``idempotency_key`` is
    optional and enables crash-safe retries without duplicate rows.
    """

    model_config = ConfigDict(frozen=True)

    question_ref: Optional[str] = None
    based_on_state_revision: Optional[int] = None
    context_hash: Optional[str] = None
    idempotency_key: Optional[str] = None


class AgentDelegation(BaseModel):
    model_config = ConfigDict(frozen=True)

    delegation_id: str
    task_id: str
    investigation_id: str
    run_id: str
    status: DelegationStatus
    question_ref: Optional[str]
    based_on_state_revision: Optional[int]
    context_hash: Optional[str]
    cancel_requested_at: Optional[str]
    failure_code: Optional[str]
    failure_message: Optional[str]
    idempotency_key: Optional[str]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    failed_at: Optional[str]
    cancelled_at: Optional[str]
    stale_at: Optional[str]
    integrated_at: Optional[str]
    integrated_revision: Optional[int]


class WorkingStateRevision(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    investigation_id: str
    revision: int
    state: dict
    state_hash: str
    previous_state_hash: Optional[str]
    operation_key: Optional[str]
    created_at: str


class TrajectoryEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    event_id: str
    task_id: str
    investigation_id: str
    run_id: Optional[str]
    delegation_id: Optional[str]
    event_type: AgentTrajectoryEventType
    payload: dict
    created_at: str


class ToolObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str
    task_id: str
    investigation_id: str
    run_id: Optional[str]
    delegation_id: Optional[str]
    tool_id: str
    summary: str
    result: dict
    evidence_refs: tuple[str, ...]
    result_count: int
    truncated: bool
    created_at: str


class DelegationResult(BaseModel):
    """Immutable terminal result of one delegation (P4A §17)."""

    model_config = ConfigDict(frozen=True)

    result_id: int
    task_id: str
    investigation_id: str
    run_id: str
    delegation_id: str
    result_version: str
    result: dict
    result_hash: str
    context_hash: Optional[str]
    tool_registry_hash: Optional[str]
    model_name: Optional[str]
    model_config_hash: Optional[str]
    usage: Optional[dict]
    validation_status: str
    created_at: str


class FinalizationRecord(BaseModel):
    """Immutable successful-finalization record (P2 §36)."""

    model_config = ConfigDict(frozen=True)

    finalization_id: str
    task_id: str
    investigation_id: str
    run_id: Optional[str]
    state_revision: int
    state_hash: str
    completion_mode: str
    question_dispositions: dict
    coverage_dispositions: dict
    unresolved_contradictions: list
    limitations: list
    remaining_nonblocking_questions: list
    pending_analyst_review_refs: list
    final_verification_status: str
    verifier_result_ref: Optional[str]
    finalization_policy_version: str
    input_hash: str
    completed_at: str


class AgentRuntimeRepository:
    """P1 domain primitives for the agent runtime state plane.

    Bound to a task-scoped :class:`InvestigationRepository` and shares its
    connection policy (``PRAGMA foreign_keys=ON``, ``mode=rw`` for
    existing-only stores).  Every statement is task-scoped; cross-task ids
    are opaque not-found results.
    """

    def __init__(self, repository: InvestigationRepository):
        self._repo = repository
        self.task_id = repository.task_id

    def _connect(self) -> sqlite3.Connection:
        return self._repo._connect()

    # =====================================================================
    # row mappers
    # =====================================================================

    @staticmethod
    def _row_to_investigation(row: sqlite3.Row) -> AgentInvestigation:
        return AgentInvestigation(
            investigation_id=row["investigation_id"],
            task_id=row["task_id"],
            status=AgentInvestigationStatus(row["status"]),
            pause_reason=(
                InvestigationPauseReason(row["pause_reason"])
                if row["pause_reason"]
                else None
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            cancelled_at=row["cancelled_at"],
        )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> AgentRun:
        return AgentRun(
            run_id=row["run_id"],
            task_id=row["task_id"],
            investigation_id=row["investigation_id"],
            status=AgentRunStatus(row["status"]),
            stop_reason=(
                RunStopReason(row["stop_reason"]) if row["stop_reason"] else None
            ),
            error_code=row["error_code"],
            error_message=row["error_message"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            failed_at=row["failed_at"],
            cancelled_at=row["cancelled_at"],
        )

    @staticmethod
    def _row_to_delegation(row: sqlite3.Row) -> AgentDelegation:
        return AgentDelegation(
            delegation_id=row["delegation_id"],
            task_id=row["task_id"],
            investigation_id=row["investigation_id"],
            run_id=row["run_id"],
            status=DelegationStatus(row["status"]),
            question_ref=row["question_ref"],
            based_on_state_revision=row["based_on_state_revision"],
            context_hash=row["context_hash"],
            cancel_requested_at=row["cancel_requested_at"],
            failure_code=row["failure_code"],
            failure_message=row["failure_message"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            failed_at=row["failed_at"],
            cancelled_at=row["cancelled_at"],
            stale_at=row["stale_at"],
            integrated_at=row["integrated_at"],
            integrated_revision=row["integrated_revision"],
        )

    @staticmethod
    def _row_to_revision(row: sqlite3.Row) -> WorkingStateRevision:
        try:
            state = json.loads(row["state_json"])
        except (TypeError, ValueError) as exc:
            raise AgentRuntimeConflictError(
                "working state revision payload is corrupt"
            ) from exc
        return WorkingStateRevision(
            task_id=row["task_id"],
            investigation_id=row["investigation_id"],
            revision=row["revision"],
            state=state,
            state_hash=row["state_hash"],
            previous_state_hash=row["previous_state_hash"],
            operation_key=row["operation_key"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_trajectory(row: sqlite3.Row) -> TrajectoryEvent:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError) as exc:
            raise AgentRuntimeConflictError(
                "trajectory event payload is corrupt"
            ) from exc
        return TrajectoryEvent(
            seq=row["seq"],
            event_id=row["event_id"],
            task_id=row["task_id"],
            investigation_id=row["investigation_id"],
            run_id=row["run_id"],
            delegation_id=row["delegation_id"],
            event_type=AgentTrajectoryEventType(row["event_type"]),
            payload=payload,
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_observation(row: sqlite3.Row) -> ToolObservation:
        try:
            result = json.loads(row["result_json"])
            refs = json.loads(row["evidence_refs_json"])
        except (TypeError, ValueError) as exc:
            raise AgentRuntimeConflictError(
                "tool observation payload is corrupt"
            ) from exc
        return ToolObservation(
            observation_id=row["observation_id"],
            task_id=row["task_id"],
            investigation_id=row["investigation_id"],
            run_id=row["run_id"],
            delegation_id=row["delegation_id"],
            tool_id=row["tool_id"],
            summary=row["summary"],
            result=result,
            evidence_refs=tuple(refs),
            result_count=row["result_count"],
            truncated=bool(row["truncated"]),
            created_at=row["created_at"],
        )

    # =====================================================================
    # trajectory
    # =====================================================================

    def _append_trajectory_with_conn(
        self,
        conn: sqlite3.Connection,
        investigation_id: str,
        event_type: AgentTrajectoryEventType,
        *,
        run_id: Optional[str] = None,
        delegation_id: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
        now: Optional[str] = None,
    ) -> TrajectoryEvent:
        """Caller-owned transaction append (deterministic seq ordering)."""
        payload_json = canonical_state_json(dict(payload or {}))
        event_id = _new_trajectory_event_id()
        cursor = conn.execute(
            "INSERT INTO agent_trajectory_events "
            "(event_id, task_id, investigation_id, run_id, delegation_id, "
            " event_type, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                event_id, self.task_id, investigation_id, run_id, delegation_id,
                event_type.value, payload_json, now or _now_iso(),
            ],
        )
        row = conn.execute(
            "SELECT * FROM agent_trajectory_events WHERE seq = ?",
            [cursor.lastrowid],
        ).fetchone()
        return self._row_to_trajectory(row)

    def append_trajectory(
        self,
        investigation_id: str,
        event_type: AgentTrajectoryEventType | str,
        *,
        run_id: Optional[str] = None,
        delegation_id: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> TrajectoryEvent:
        """Append one Action Trace event (INSERT-only table)."""
        if not isinstance(event_type, AgentTrajectoryEventType):
            try:
                event_type = AgentTrajectoryEventType(event_type)
            except ValueError as exc:
                raise ValueError(f"unknown trajectory event type: {event_type!r}") from exc
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_investigation_with_conn(conn, investigation_id)
            if run_id is not None:
                self._require_run_with_conn(conn, run_id, investigation_id)
            if delegation_id is not None:
                self._require_delegation_with_conn(
                    conn, delegation_id, investigation_id
                )
            event = self._append_trajectory_with_conn(
                conn, investigation_id, event_type,
                run_id=run_id, delegation_id=delegation_id, payload=payload,
            )
            conn.commit()
        return event

    def list_trajectory(
        self,
        investigation_id: str,
        *,
        event_type: Optional[AgentTrajectoryEventType] = None,
    ) -> list[TrajectoryEvent]:
        """Deterministic insertion order (ascending ``seq``)."""
        sql = (
            "SELECT * FROM agent_trajectory_events "
            "WHERE task_id = ? AND investigation_id = ?"
        )
        params: list = [self.task_id, investigation_id]
        if event_type is not None:
            sql += " AND event_type = ?"
            params.append(event_type.value)
        sql += " ORDER BY seq"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_trajectory(r) for r in rows]

    # =====================================================================
    # investigation lifecycle
    # =====================================================================

    def _require_investigation_with_conn(
        self, conn: sqlite3.Connection, investigation_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM agent_investigations "
            "WHERE task_id = ? AND investigation_id = ?",
            [self.task_id, investigation_id],
        ).fetchone()
        if row is None:
            raise ValueError(f"investigation not found: {investigation_id!r}")
        return row

    def _require_run_with_conn(
        self, conn: sqlite3.Connection, run_id: str, investigation_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM agent_runs WHERE task_id = ? AND run_id = ?",
            [self.task_id, run_id],
        ).fetchone()
        if row is None or row["investigation_id"] != investigation_id:
            raise ValueError(f"run not found: {run_id!r}")
        return row

    def _require_delegation_with_conn(
        self, conn: sqlite3.Connection, delegation_id: str, investigation_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM agent_delegations WHERE task_id = ? AND delegation_id = ?",
            [self.task_id, delegation_id],
        ).fetchone()
        if row is None or row["investigation_id"] != investigation_id:
            raise ValueError(f"delegation not found: {delegation_id!r}")
        return row

    def create_investigation(
        self,
        initial_state: Mapping[str, Any],
        *,
        investigation_id: Optional[str] = None,
    ) -> tuple[AgentInvestigation, WorkingStateRevision]:
        """Create a ``ready`` Investigation with its initial Working State
        revision (revision 1) and the ``investigation_created`` trace event,
        atomically."""
        investigation_id = investigation_id or _new_investigation_id()
        now = _now_iso()
        state_json = canonical_state_json(initial_state)
        state_hash = state_hash_of(initial_state)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO agent_investigations "
                "(investigation_id, task_id, status, created_at, updated_at) "
                "VALUES (?, ?, 'ready', ?, ?)",
                [investigation_id, self.task_id, now, now],
            )
            revision = self._insert_revision_with_conn(
                conn,
                investigation_id,
                state_json=state_json,
                state_hash=state_hash,
                previous_state_hash=None,
                now=now,
            )
            self._append_trajectory_with_conn(
                conn, investigation_id,
                AgentTrajectoryEventType.investigation_created, now=now,
            )
            row = conn.execute(
                "SELECT * FROM agent_investigations "
                "WHERE task_id = ? AND investigation_id = ?",
                [self.task_id, investigation_id],
            ).fetchone()
            conn.commit()
        return self._row_to_investigation(row), revision

    def get_investigation(self, investigation_id: str) -> Optional[AgentInvestigation]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_investigations "
                "WHERE task_id = ? AND investigation_id = ?",
                [self.task_id, investigation_id],
            ).fetchone()
        return self._row_to_investigation(row) if row is not None else None

    def list_investigations(self) -> list[AgentInvestigation]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_investigations WHERE task_id = ? "
                "ORDER BY created_at, investigation_id",
                [self.task_id],
            ).fetchall()
        return [self._row_to_investigation(r) for r in rows]

    def pause_investigation(
        self,
        investigation_id: str,
        *,
        reason: InvestigationPauseReason | str = InvestigationPauseReason.user_paused,
    ) -> AgentInvestigation:
        """Pause an active Investigation (cooperative cancellation).

        The active run (if any) is cancelled with the mapped stop reason and
        its queued/running delegations get ``cancel_requested_at`` set, all in
        the same transaction; a later executor observes the request and moves
        each delegation to its terminal state explicitly.
        """
        if not isinstance(reason, InvestigationPauseReason):
            reason = InvestigationPauseReason(reason)
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_investigation_with_conn(conn, investigation_id)
            current = AgentInvestigationStatus(row["status"])
            if current != AgentInvestigationStatus.active:
                raise AgentRuntimeConflictError(
                    f"only an active investigation can be paused (current: {current.value!r})"
                )
            self._cancel_active_run_with_conn(
                conn, investigation_id,
                stop_reason=_PAUSE_RUN_STOP_REASON.get(reason, RunStopReason.cancelled),
                now=now,
            )
            conn.execute(
                "UPDATE agent_investigations "
                "SET status = 'paused', pause_reason = ?, updated_at = ? "
                "WHERE task_id = ? AND investigation_id = ?",
                [reason.value, now, self.task_id, investigation_id],
            )
            self._append_trajectory_with_conn(
                conn, investigation_id,
                AgentTrajectoryEventType.investigation_paused,
                payload={"pause_reason": reason.value}, now=now,
            )
            updated = conn.execute(
                "SELECT * FROM agent_investigations "
                "WHERE task_id = ? AND investigation_id = ?",
                [self.task_id, investigation_id],
            ).fetchone()
            result = self._row_to_investigation(updated)
            conn.commit()
        return result

    def complete_investigation(self, investigation_id: str) -> AgentInvestigation:
        """Mark an active Investigation ``completed`` (immutable terminal).

        P1 provides the deterministic transition only; FinalizationGate
        semantic preflight is a later phase.  A queued/running run blocks
        completion (fail closed).
        """
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_investigation_with_conn(conn, investigation_id)
            current = AgentInvestigationStatus(row["status"])
            if current != AgentInvestigationStatus.active:
                raise AgentRuntimeConflictError(
                    f"only an active investigation can be completed (current: {current.value!r})"
                )
            active_run = conn.execute(
                "SELECT run_id FROM agent_runs "
                "WHERE task_id = ? AND investigation_id = ? "
                "AND status IN ('queued','running')",
                [self.task_id, investigation_id],
            ).fetchone()
            if active_run is not None:
                raise AgentRuntimeConflictError(
                    "investigation still has an active run; cancel it first"
                )
            conn.execute(
                "UPDATE agent_investigations "
                "SET status = 'completed', completed_at = ?, updated_at = ? "
                "WHERE task_id = ? AND investigation_id = ?",
                [now, now, self.task_id, investigation_id],
            )
            self._append_trajectory_with_conn(
                conn, investigation_id,
                AgentTrajectoryEventType.investigation_completed, now=now,
            )
            updated = conn.execute(
                "SELECT * FROM agent_investigations "
                "WHERE task_id = ? AND investigation_id = ?",
                [self.task_id, investigation_id],
            ).fetchone()
            result = self._row_to_investigation(updated)
            conn.commit()
        return result

    def cancel_investigation(self, investigation_id: str) -> AgentInvestigation:
        """Cancel a non-terminal Investigation (terminal, no reopen)."""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_investigation_with_conn(conn, investigation_id)
            current = AgentInvestigationStatus(row["status"])
            if current in _TERMINAL_INVESTIGATION_STATUSES:
                raise AgentRuntimeConflictError(
                    f"investigation is terminal ({current.value!r})"
                )
            self._cancel_active_run_with_conn(
                conn, investigation_id,
                stop_reason=RunStopReason.cancelled, now=now,
            )
            conn.execute(
                "UPDATE agent_delegations SET cancel_requested_at = ? "
                "WHERE task_id = ? AND investigation_id = ? "
                "AND status IN ('queued','running') AND cancel_requested_at IS NULL",
                [now, self.task_id, investigation_id],
            )
            conn.execute(
                "UPDATE agent_investigations "
                "SET status = 'cancelled', cancelled_at = ?, updated_at = ? "
                "WHERE task_id = ? AND investigation_id = ?",
                [now, now, self.task_id, investigation_id],
            )
            self._append_trajectory_with_conn(
                conn, investigation_id,
                AgentTrajectoryEventType.investigation_cancelled, now=now,
            )
            updated = conn.execute(
                "SELECT * FROM agent_investigations "
                "WHERE task_id = ? AND investigation_id = ?",
                [self.task_id, investigation_id],
            ).fetchone()
            result = self._row_to_investigation(updated)
            conn.commit()
        return result

    def _cancel_active_run_with_conn(
        self,
        conn: sqlite3.Connection,
        investigation_id: str,
        *,
        stop_reason: RunStopReason,
        now: str,
    ) -> Optional[AgentRun]:
        """Cancel the investigation's active run + request delegation
        cancellation inside the caller's transaction."""
        run_row = conn.execute(
            "SELECT * FROM agent_runs "
            "WHERE task_id = ? AND investigation_id = ? "
            "AND status IN ('queued','running')",
            [self.task_id, investigation_id],
        ).fetchone()
        if run_row is None:
            return None
        run_id = run_row["run_id"]
        cancelled = self._transition_run_with_conn(
            conn, run_row, AgentRunStatus.cancelled,
            stop_reason=stop_reason, now=now,
        )
        conn.execute(
            "UPDATE agent_delegations SET cancel_requested_at = ? "
            "WHERE task_id = ? AND run_id = ? "
            "AND status IN ('queued','running') AND cancel_requested_at IS NULL",
            [now, self.task_id, run_id],
        )
        self._append_trajectory_with_conn(
            conn, investigation_id,
            AgentTrajectoryEventType.run_cancelled,
            run_id=run_id,
            payload={"stop_reason": stop_reason.value}, now=now,
        )
        return cancelled

    # =====================================================================
    # run lifecycle
    # =====================================================================

    def start_run(
        self,
        investigation_id: str,
        *,
        idempotency_key: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> AgentRun:
        """Run Admission (P1 §8): one transaction validates the Investigation
        state, inserts a ``queued`` run, moves the investigation to ``active``
        and appends the trace event.

        The one-active-run invariant is enforced by the partial unique index
        ``idx_agent_run_one_active_per_investigation`` at the DB boundary.
        Re-admission with a used ``idempotency_key`` returns the original run
        without duplicating rows.
        """
        run_id = run_id or _new_run_id()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                existing = conn.execute(
                    "SELECT * FROM agent_runs "
                    "WHERE task_id = ? AND idempotency_key = ?",
                    [self.task_id, idempotency_key],
                ).fetchone()
                if existing is not None:
                    conn.commit()
                    return self._row_to_run(existing)
            row = self._require_investigation_with_conn(conn, investigation_id)
            current = AgentInvestigationStatus(row["status"])
            if current in _TERMINAL_INVESTIGATION_STATUSES:
                raise AgentRuntimeConflictError(
                    f"investigation is terminal ({current.value!r}); "
                    "a follow-up investigation must be a new row"
                )
            active = conn.execute(
                "SELECT 1 FROM agent_runs "
                "WHERE task_id = ? AND investigation_id = ? "
                "AND status IN ('queued','running')",
                [self.task_id, investigation_id],
            ).fetchone()
            if active is not None:
                raise AgentRuntimeConflictError(
                    "investigation already has an active run"
                )
            try:
                conn.execute(
                    "INSERT INTO agent_runs "
                    "(run_id, task_id, investigation_id, status, idempotency_key, "
                    " created_at) VALUES (?, ?, ?, 'queued', ?, ?)",
                    [run_id, self.task_id, investigation_id, idempotency_key, now],
                )
            except sqlite3.IntegrityError as exc:
                raise AgentRuntimeConflictError(
                    "run admission conflicts with an existing row"
                ) from exc
            if current != AgentInvestigationStatus.active:
                conn.execute(
                    "UPDATE agent_investigations "
                    "SET status = 'active', pause_reason = NULL, updated_at = ? "
                    "WHERE task_id = ? AND investigation_id = ?",
                    [now, self.task_id, investigation_id],
                )
            self._append_trajectory_with_conn(
                conn, investigation_id,
                AgentTrajectoryEventType.run_admitted,
                run_id=run_id,
                payload={"idempotency_key": idempotency_key}, now=now,
            )
            result_row = conn.execute(
                "SELECT * FROM agent_runs WHERE task_id = ? AND run_id = ?",
                [self.task_id, run_id],
            ).fetchone()
            result = self._row_to_run(result_row)
            conn.commit()
        return result

    def get_run(self, run_id: str) -> Optional[AgentRun]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_runs WHERE task_id = ? AND run_id = ?",
                [self.task_id, run_id],
            ).fetchone()
        return self._row_to_run(row) if row is not None else None

    def list_runs(self, investigation_id: str) -> list[AgentRun]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_runs "
                "WHERE task_id = ? AND investigation_id = ? "
                "ORDER BY created_at, run_id",
                [self.task_id, investigation_id],
            ).fetchall()
        return [self._row_to_run(r) for r in rows]

    def mark_run_running(self, run_id: str) -> AgentRun:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_run_row_with_conn(conn, run_id)
            result = self._transition_run_with_conn(
                conn, row, AgentRunStatus.running, now=now,
            )
            self._append_trajectory_with_conn(
                conn, result.investigation_id,
                AgentTrajectoryEventType.run_started, run_id=run_id, now=now,
            )
            conn.commit()
        return result

    def finish_run(self, run_id: str, *, stop_reason: RunStopReason | str) -> AgentRun:
        """Complete a running run.  Run completion never completes the
        Investigation (independent lifecycles)."""
        if not isinstance(stop_reason, RunStopReason):
            stop_reason = RunStopReason(stop_reason)
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_run_row_with_conn(conn, run_id)
            result = self._transition_run_with_conn(
                conn, row, AgentRunStatus.completed,
                stop_reason=stop_reason, now=now,
            )
            self._append_trajectory_with_conn(
                conn, result.investigation_id,
                AgentTrajectoryEventType.run_completed,
                run_id=run_id,
                payload={"stop_reason": stop_reason.value}, now=now,
            )
            conn.commit()
        return result

    def fail_run(
        self,
        run_id: str,
        *,
        error_code: str,
        error_message: str,
        stop_reason: RunStopReason | str = RunStopReason.internal_failure,
    ) -> AgentRun:
        if not isinstance(stop_reason, RunStopReason):
            stop_reason = RunStopReason(stop_reason)
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_run_row_with_conn(conn, run_id)
            result = self._transition_run_with_conn(
                conn, row, AgentRunStatus.failed,
                stop_reason=stop_reason, now=now,
                error_code=error_code, error_message=error_message,
            )
            self._append_trajectory_with_conn(
                conn, result.investigation_id,
                AgentTrajectoryEventType.run_failed,
                run_id=run_id,
                payload={
                    "stop_reason": stop_reason.value,
                    "error_code": error_code,
                },
                now=now,
            )
            conn.commit()
        return result

    def cancel_run(
        self,
        run_id: str,
        *,
        stop_reason: RunStopReason | str = RunStopReason.cancelled,
    ) -> AgentRun:
        if not isinstance(stop_reason, RunStopReason):
            stop_reason = RunStopReason(stop_reason)
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_run_row_with_conn(conn, run_id)
            result = self._transition_run_with_conn(
                conn, row, AgentRunStatus.cancelled,
                stop_reason=stop_reason, now=now,
            )
            self._append_trajectory_with_conn(
                conn, result.investigation_id,
                AgentTrajectoryEventType.run_cancelled,
                run_id=run_id,
                payload={"stop_reason": stop_reason.value}, now=now,
            )
            conn.commit()
        return result

    def _require_run_row_with_conn(
        self, conn: sqlite3.Connection, run_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM agent_runs WHERE task_id = ? AND run_id = ?",
            [self.task_id, run_id],
        ).fetchone()
        if row is None:
            raise ValueError(f"run not found: {run_id!r}")
        return row

    def _transition_run_with_conn(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        to: AgentRunStatus,
        *,
        now: str,
        stop_reason: Optional[RunStopReason] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> AgentRun:
        """Apply one legal run transition inside the caller's transaction."""
        current = AgentRunStatus(row["status"])
        if current in _TERMINAL_RUN_STATUSES:
            raise AgentRuntimeConflictError(
                f"run is terminal ({current.value!r})"
            )
        if to not in RUN_TRANSITIONS[current]:
            raise AgentRuntimeConflictError(
                f"illegal run transition {current.value!r} -> {to.value!r}"
            )
        run_id = row["run_id"]
        set_clauses = ["status = ?"]
        params: list = [to.value]
        timestamp_column = {
            AgentRunStatus.running: "started_at",
            AgentRunStatus.completed: "completed_at",
            AgentRunStatus.failed: "failed_at",
            AgentRunStatus.cancelled: "cancelled_at",
        }.get(to)
        if timestamp_column is not None:
            set_clauses.append(f"{timestamp_column} = ?")
            params.append(now)
        if stop_reason is not None:
            set_clauses.append("stop_reason = ?")
            params.append(stop_reason.value)
        if error_code is not None:
            set_clauses.append("error_code = ?")
            params.append(error_code[:100])
        if error_message is not None:
            set_clauses.append("error_message = ?")
            params.append(error_message[:500])
        params.extend([self.task_id, run_id, current.value])
        cursor = conn.execute(
            f"UPDATE agent_runs SET {', '.join(set_clauses)} "
            "WHERE task_id = ? AND run_id = ? AND status = ?",
            params,
        )
        if cursor.rowcount != 1:
            raise AgentRuntimeConflictError(
                f"concurrent status change for run {run_id!r}"
            )
        updated = conn.execute(
            "SELECT * FROM agent_runs WHERE task_id = ? AND run_id = ?",
            [self.task_id, run_id],
        ).fetchone()
        return self._row_to_run(updated)

    # =====================================================================
    # delegation lifecycle
    # =====================================================================

    def admit_delegations(
        self, run_id: str, specs: Sequence[DelegationSpec]
    ) -> list[AgentDelegation]:
        """Delegation Admission (P1 §8): validate the run, INSERT queued
        delegations and append trace events in ONE transaction.  A future
        executor may only start work after this commits.

        Per-spec ``idempotency_key`` replay returns the already-admitted
        delegation instead of duplicating it.
        """
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run_row = conn.execute(
                "SELECT * FROM agent_runs WHERE task_id = ? AND run_id = ?",
                [self.task_id, run_id],
            ).fetchone()
            if run_row is None:
                raise ValueError(f"run not found: {run_id!r}")
            results = self._admit_delegation_specs_with_conn(
                conn, run_row, specs, now=now
            )
            conn.commit()
        return results

    def _admit_delegation_specs_with_conn(
        self,
        conn: sqlite3.Connection,
        run_row: sqlite3.Row,
        specs: Sequence[DelegationSpec],
        *,
        now: str,
    ) -> list[AgentDelegation]:
        """Conn-level admission body (P2 semantics), reused by
        ``admit_delegations`` and the P4B atomic supervisor-plan commit so
        the decision audit and the queued intents share ONE transaction."""
        run_id = run_row["run_id"]
        run_status = AgentRunStatus(run_row["status"])
        if run_status not in (AgentRunStatus.queued, AgentRunStatus.running):
            raise AgentRuntimeConflictError(
                f"delegations require an active run (current: {run_status.value!r})"
            )
        investigation_id = run_row["investigation_id"]
        results: list[AgentDelegation] = []
        for spec in specs:
            if spec.idempotency_key is not None:
                existing = conn.execute(
                    "SELECT * FROM agent_delegations "
                    "WHERE task_id = ? AND idempotency_key = ?",
                    [self.task_id, spec.idempotency_key],
                ).fetchone()
                if existing is not None:
                    # Replay of a committed admission must match the original
                    # content; a same-key different-request collision fails.
                    if existing["question_ref"] != spec.question_ref:
                        raise AgentRuntimeConflictError(
                            "idempotency key is bound to a different "
                            "delegation request"
                        )
                    results.append(self._row_to_delegation(existing))
                    continue
            delegation_id = _new_delegation_id()
            try:
                conn.execute(
                    "INSERT INTO agent_delegations "
                    "(delegation_id, task_id, investigation_id, run_id, status, "
                    " question_ref, based_on_state_revision, context_hash, "
                    " idempotency_key, created_at) "
                    "VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
                    [
                        delegation_id, self.task_id, investigation_id, run_id,
                        spec.question_ref, spec.based_on_state_revision,
                        spec.context_hash, spec.idempotency_key, now,
                    ],
                )
            except sqlite3.IntegrityError as exc:
                raise AgentRuntimeConflictError(
                    "delegation admission conflicts with an existing row"
                ) from exc
            self._append_trajectory_with_conn(
                conn, investigation_id,
                AgentTrajectoryEventType.delegation_admitted,
                run_id=run_id, delegation_id=delegation_id,
                payload={"question_ref": spec.question_ref}, now=now,
            )
            row = conn.execute(
                "SELECT * FROM agent_delegations "
                "WHERE task_id = ? AND delegation_id = ?",
                [self.task_id, delegation_id],
            ).fetchone()
            results.append(self._row_to_delegation(row))
        return results

    def commit_supervisor_plan(
        self,
        run_id: str,
        *,
        decision_payload: Mapping[str, Any],
        decision_hash: str,
        model_name: Optional[str] = None,
        model_config_hash: Optional[str] = None,
        prompt_version: Optional[str] = None,
        usage: Optional[Mapping[str, Any]] = None,
        specs: Sequence[DelegationSpec] = (),
    ) -> tuple[TrajectoryEvent, list[AgentDelegation]]:
        """Atomic PLAN admission (P4B §7): the structured decision audit and
        the queued delegation(s) land in ONE transaction. The executor may
        only see the delegations after this commits. Replay-safe: a decision
        hash already on the trace is not duplicated, and per-spec
        idempotency keys keep delegation admission replay-identical."""
        import json as _json

        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run_row = conn.execute(
                "SELECT * FROM agent_runs WHERE task_id = ? AND run_id = ?",
                [self.task_id, run_id],
            ).fetchone()
            if run_row is None:
                raise ValueError(f"run not found: {run_id!r}")
            investigation_id = run_row["investigation_id"]
            replayed = conn.execute(
                "SELECT * FROM agent_trajectory_events "
                "WHERE task_id = ? AND event_type = ? "
                "AND json_extract(payload_json, '$.decision_hash') = ? "
                "ORDER BY seq LIMIT 1",
                [
                    self.task_id,
                    AgentTrajectoryEventType.supervisor_plan_decided.value,
                    decision_hash,
                ],
            ).fetchone()
            audit_payload = {
                "decision_hash": decision_hash,
                "decision": dict(decision_payload),
                "model_name": model_name,
                "model_config_hash": model_config_hash,
                "prompt_version": prompt_version,
                "usage": dict(usage) if usage is not None else None,
            }
            if replayed is None:
                event = self._append_trajectory_with_conn(
                    conn, investigation_id,
                    AgentTrajectoryEventType.supervisor_plan_decided,
                    run_id=run_id, payload=audit_payload, now=now,
                )
            else:
                event = self._row_to_trajectory(replayed)
            delegations = self._admit_delegation_specs_with_conn(
                conn, run_row, specs, now=now
            )
            conn.commit()
        return event, delegations

    def get_delegation(self, delegation_id: str) -> Optional[AgentDelegation]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_delegations "
                "WHERE task_id = ? AND delegation_id = ?",
                [self.task_id, delegation_id],
            ).fetchone()
        return self._row_to_delegation(row) if row is not None else None

    def list_delegations(self, run_id: str) -> list[AgentDelegation]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_delegations "
                "WHERE task_id = ? AND run_id = ? "
                "ORDER BY created_at, delegation_id",
                [self.task_id, run_id],
            ).fetchall()
        return [self._row_to_delegation(r) for r in rows]

    def start_delegation(self, delegation_id: str) -> AgentDelegation:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_delegation_row_with_conn(conn, delegation_id)
            result = self._transition_delegation_with_conn(
                conn, row, DelegationStatus.running, now=now,
            )
            self._append_trajectory_with_conn(
                conn, result.investigation_id,
                AgentTrajectoryEventType.delegation_started,
                run_id=result.run_id, delegation_id=delegation_id, now=now,
            )
            conn.commit()
        return result

    def transition_delegation_terminal(
        self,
        delegation_id: str,
        to: DelegationStatus | str,
        *,
        failure_code: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> AgentDelegation:
        """Move a queued/running delegation to a terminal state.

        ``stale`` is terminal: a superseded result is kept for audit but never
        integrated.  ``failed`` requires a ``failure_code``.
        """
        if not isinstance(to, DelegationStatus):
            to = DelegationStatus(to)
        if to not in _DELEGATION_TRAJECTORY_EVENT:
            raise ValueError(
                f"transition_delegation_terminal requires a terminal status, "
                f"got {to.value!r}"
            )
        if to is DelegationStatus.failed and not failure_code:
            raise ValueError("failed delegation requires failure_code")
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_delegation_row_with_conn(conn, delegation_id)
            result = self._transition_delegation_with_conn(
                conn, row, to, now=now,
                failure_code=failure_code, failure_message=failure_message,
            )
            self._append_trajectory_with_conn(
                conn, result.investigation_id,
                _DELEGATION_TRAJECTORY_EVENT[to],
                run_id=result.run_id, delegation_id=delegation_id,
                payload={"failure_code": failure_code} if failure_code else None,
                now=now,
            )
            conn.commit()
        return result

    def request_delegation_cancel(self, delegation_id: str) -> AgentDelegation:
        """Cooperative cancellation: record ``cancel_requested_at`` on a
        non-terminal delegation (idempotent)."""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_delegation_row_with_conn(conn, delegation_id)
            if row["cancel_requested_at"] is not None:
                conn.commit()
                return self._row_to_delegation(row)
            if row["status"] in ("completed", "failed", "cancelled", "stale"):
                raise AgentRuntimeConflictError(
                    f"delegation is terminal ({row['status']!r})"
                )
            conn.execute(
                "UPDATE agent_delegations SET cancel_requested_at = ? "
                "WHERE task_id = ? AND delegation_id = ?",
                [now, self.task_id, delegation_id],
            )
            updated = conn.execute(
                "SELECT * FROM agent_delegations "
                "WHERE task_id = ? AND delegation_id = ?",
                [self.task_id, delegation_id],
            ).fetchone()
            result = self._row_to_delegation(updated)
            conn.commit()
        return result

    def mark_delegation_integrated(
        self, delegation_id: str, *, integrated_revision: int
    ) -> AgentDelegation:
        """Record integration bookkeeping on a completed delegation (once)."""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_delegation_row_with_conn(conn, delegation_id)
            if row["status"] != DelegationStatus.completed.value:
                raise AgentRuntimeConflictError(
                    "only a completed delegation can be integrated"
                )
            if row["integrated_at"] is not None:
                raise AgentRuntimeConflictError("delegation is already integrated")
            revision = conn.execute(
                "SELECT 1 FROM agent_working_state_revisions "
                "WHERE task_id = ? AND investigation_id = ? AND revision = ?",
                [self.task_id, row["investigation_id"], integrated_revision],
            ).fetchone()
            if revision is None:
                raise ValueError(
                    f"working state revision does not exist: {integrated_revision!r}"
                )
            cursor = conn.execute(
                "UPDATE agent_delegations "
                "SET integrated_at = ?, integrated_revision = ? "
                "WHERE task_id = ? AND delegation_id = ? "
                "AND status = 'completed' AND integrated_at IS NULL",
                [now, integrated_revision, self.task_id, delegation_id],
            )
            if cursor.rowcount != 1:
                raise AgentRuntimeConflictError(
                    "concurrent integration for delegation"
                )
            updated = conn.execute(
                "SELECT * FROM agent_delegations "
                "WHERE task_id = ? AND delegation_id = ?",
                [self.task_id, delegation_id],
            ).fetchone()
            result = self._row_to_delegation(updated)
            conn.commit()
        return result

    def _require_delegation_row_with_conn(
        self, conn: sqlite3.Connection, delegation_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM agent_delegations WHERE task_id = ? AND delegation_id = ?",
            [self.task_id, delegation_id],
        ).fetchone()
        if row is None:
            raise ValueError(f"delegation not found: {delegation_id!r}")
        return row

    def _transition_delegation_with_conn(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        to: DelegationStatus,
        *,
        now: str,
        failure_code: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> AgentDelegation:
        current = DelegationStatus(row["status"])
        if current in _TERMINAL_DELEGATION_STATUSES:
            raise AgentRuntimeConflictError(
                f"delegation is terminal ({current.value!r})"
            )
        if to not in DELEGATION_TRANSITIONS[current]:
            raise AgentRuntimeConflictError(
                f"illegal delegation transition {current.value!r} -> {to.value!r}"
            )
        delegation_id = row["delegation_id"]
        set_clauses = ["status = ?"]
        params: list = [to.value]
        timestamp_column = {
            DelegationStatus.running: "started_at",
            DelegationStatus.completed: "completed_at",
            DelegationStatus.failed: "failed_at",
            DelegationStatus.cancelled: "cancelled_at",
            DelegationStatus.stale: "stale_at",
        }.get(to)
        if timestamp_column is not None:
            set_clauses.append(f"{timestamp_column} = ?")
            params.append(now)
        if failure_code is not None:
            set_clauses.append("failure_code = ?")
            params.append(failure_code[:100])
        if failure_message is not None:
            set_clauses.append("failure_message = ?")
            params.append(failure_message[:500])
        params.extend([self.task_id, delegation_id, current.value])
        cursor = conn.execute(
            f"UPDATE agent_delegations SET {', '.join(set_clauses)} "
            "WHERE task_id = ? AND delegation_id = ? AND status = ?",
            params,
        )
        if cursor.rowcount != 1:
            raise AgentRuntimeConflictError(
                f"concurrent status change for delegation {delegation_id!r}"
            )
        updated = conn.execute(
            "SELECT * FROM agent_delegations WHERE task_id = ? AND delegation_id = ?",
            [self.task_id, delegation_id],
        ).fetchone()
        return self._row_to_delegation(updated)

    # =====================================================================
    # working state revisions
    # =====================================================================

    def _insert_revision_with_conn(
        self,
        conn: sqlite3.Connection,
        investigation_id: str,
        *,
        state_json: str,
        state_hash: str,
        previous_state_hash: Optional[str],
        now: str,
        operation_key: Optional[str] = None,
    ) -> WorkingStateRevision:
        """Caller-owned transaction insert; DB triggers enforce strict
        sequencing and hash chaining."""
        revision_row = conn.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 AS next_revision "
            "FROM agent_working_state_revisions "
            "WHERE task_id = ? AND investigation_id = ?",
            [self.task_id, investigation_id],
        ).fetchone()
        revision = revision_row["next_revision"]
        try:
            conn.execute(
                "INSERT INTO agent_working_state_revisions "
                "(task_id, investigation_id, revision, state_json, state_hash, "
                " previous_state_hash, operation_key, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    self.task_id, investigation_id, revision, state_json,
                    state_hash, previous_state_hash, operation_key, now,
                ],
            )
        except sqlite3.IntegrityError as exc:
            raise WorkingStateRevisionConflictError(
                "working state revision insert conflicts with existing rows"
            ) from exc
        row = conn.execute(
            "SELECT * FROM agent_working_state_revisions "
            "WHERE task_id = ? AND investigation_id = ? AND revision = ?",
            [self.task_id, investigation_id, revision],
        ).fetchone()
        return self._row_to_revision(row)

    def get_latest_working_state(
        self, investigation_id: str
    ) -> Optional[WorkingStateRevision]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_working_state_revisions "
                "WHERE task_id = ? AND investigation_id = ? "
                "ORDER BY revision DESC LIMIT 1",
                [self.task_id, investigation_id],
            ).fetchone()
        return self._row_to_revision(row) if row is not None else None

    def get_working_state_revision(
        self, investigation_id: str, revision: int
    ) -> Optional[WorkingStateRevision]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_working_state_revisions "
                "WHERE task_id = ? AND investigation_id = ? AND revision = ?",
                [self.task_id, investigation_id, revision],
            ).fetchone()
        return self._row_to_revision(row) if row is not None else None

    def find_revision_by_operation_key(
        self, investigation_id: str, operation_key: str
    ) -> Optional[WorkingStateRevision]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_working_state_revisions "
                "WHERE task_id = ? AND investigation_id = ? AND operation_key = ?",
                [self.task_id, investigation_id, operation_key],
            ).fetchone()
        return self._row_to_revision(row) if row is not None else None

    def commit_working_state(
        self,
        investigation_id: str,
        state: Mapping[str, Any],
        *,
        expected_revision: int,
        operation_key: Optional[str] = None,
    ) -> WorkingStateRevision:
        """Optimistic-concurrency Working State commit (fail closed).

        The commit is rejected unless ``expected_revision`` equals the current
        latest revision; the new revision is exactly ``expected_revision + 1``
        and its ``previous_state_hash`` is bound to the previous row by DB
        trigger.  Retrying a committed ``operation_key`` returns the original
        revision when the state hash matches, and raises otherwise.
        """
        state_json = canonical_state_json(state)
        new_hash = state_hash_of(state)
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_investigation_with_conn(conn, investigation_id)
            if operation_key is not None:
                replay = conn.execute(
                    "SELECT * FROM agent_working_state_revisions "
                    "WHERE task_id = ? AND investigation_id = ? AND operation_key = ?",
                    [self.task_id, investigation_id, operation_key],
                ).fetchone()
                if replay is not None:
                    if replay["state_hash"] != new_hash:
                        raise WorkingStateRevisionConflictError(
                            "operation key is bound to different state content"
                        )
                    conn.commit()
                    return self._row_to_revision(replay)
            current = conn.execute(
                "SELECT COALESCE(MAX(revision), 0) AS revision "
                "FROM agent_working_state_revisions "
                "WHERE task_id = ? AND investigation_id = ?",
                [self.task_id, investigation_id],
            ).fetchone()["revision"]
            if current != expected_revision:
                raise WorkingStateRevisionConflictError(
                    f"stale revision guard: expected {expected_revision}, "
                    f"current is {current}"
                )
            previous = conn.execute(
                "SELECT state_hash FROM agent_working_state_revisions "
                "WHERE task_id = ? AND investigation_id = ? AND revision = ?",
                [self.task_id, investigation_id, current],
            ).fetchone() if current > 0 else None
            revision = self._insert_revision_with_conn(
                conn,
                investigation_id,
                state_json=state_json,
                state_hash=new_hash,
                previous_state_hash=previous["state_hash"] if previous else None,
                now=now,
                operation_key=operation_key,
            )
            self._append_trajectory_with_conn(
                conn, investigation_id,
                AgentTrajectoryEventType.working_state_committed,
                payload={
                    "revision": revision.revision,
                    "state_hash": revision.state_hash,
                    "operation_key": operation_key,
                },
                now=now,
            )
            conn.commit()
        return revision

    # =====================================================================
    # tool observation storage boundary
    # =====================================================================

    def append_tool_observation(
        self,
        investigation_id: str,
        *,
        tool_id: str,
        summary: str,
        result: Mapping[str, Any],
        evidence_refs: Sequence[str] = (),
        run_id: Optional[str] = None,
        delegation_id: Optional[str] = None,
        truncated: bool = False,
    ) -> ToolObservation:
        """Persist one immutable Tool Observation row (storage boundary only;
        P1 defines no Tool Registry). For the registry path use
        :meth:`record_tool_observation` — a successful tool action must write
        the observation and its trajectory event atomically."""
        if not tool_id:
            raise ValueError("tool observation requires tool_id")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            observation = self._insert_observation_with_conn(
                conn, investigation_id,
                tool_id=tool_id, summary=summary, result=result,
                evidence_refs=evidence_refs, run_id=run_id,
                delegation_id=delegation_id, truncated=truncated,
            )
            conn.commit()
        return observation

    def _insert_observation_with_conn(
        self,
        conn: sqlite3.Connection,
        investigation_id: str,
        *,
        tool_id: str,
        summary: str,
        result: Mapping[str, Any],
        evidence_refs: Sequence[str] = (),
        run_id: Optional[str] = None,
        delegation_id: Optional[str] = None,
        truncated: bool = False,
    ) -> ToolObservation:
        observation_id = _new_observation_id()
        now = _now_iso()
        self._require_investigation_with_conn(conn, investigation_id)
        if run_id is not None:
            self._require_run_with_conn(conn, run_id, investigation_id)
        if delegation_id is not None:
            self._require_delegation_with_conn(
                conn, delegation_id, investigation_id
            )
        conn.execute(
            "INSERT INTO agent_tool_observations "
            "(observation_id, task_id, investigation_id, run_id, delegation_id, "
            " tool_id, summary, result_json, evidence_refs_json, result_count, "
            " truncated, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                observation_id, self.task_id, investigation_id, run_id,
                delegation_id, tool_id, summary,
                canonical_state_json(dict(result)),
                canonical_state_json(list(evidence_refs)),
                len(evidence_refs), 1 if truncated else 0, now,
            ],
        )
        row = conn.execute(
            "SELECT * FROM agent_tool_observations "
            "WHERE task_id = ? AND observation_id = ?",
            [self.task_id, observation_id],
        ).fetchone()
        return self._row_to_observation(row)

    def record_tool_observation(
        self,
        investigation_id: str,
        *,
        tool_id: str,
        summary: str,
        result: Mapping[str, Any],
        evidence_refs: Sequence[str] = (),
        run_id: Optional[str] = None,
        delegation_id: Optional[str] = None,
        truncated: bool = False,
        trajectory_payload: Optional[Mapping[str, Any]] = None,
    ) -> tuple[ToolObservation, TrajectoryEvent]:
        """Atomic tool-action audit pair (P3 F2.3).

        One ``BEGIN IMMEDIATE`` transaction inserts the immutable
        ToolObservation AND the ``tool_observation_recorded`` trajectory
        event. Either both exist afterwards or neither does — a failed
        trajectory insert rolls the observation back, so the registry can
        never report success with only half the audit record.
        """
        if not tool_id:
            raise ValueError("tool observation requires tool_id")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            observation = self._insert_observation_with_conn(
                conn, investigation_id,
                tool_id=tool_id, summary=summary, result=result,
                evidence_refs=evidence_refs, run_id=run_id,
                delegation_id=delegation_id, truncated=truncated,
            )
            payload = dict(trajectory_payload or {})
            payload.setdefault("observation_id", observation.observation_id)
            event = self._append_trajectory_with_conn(
                conn, investigation_id,
                AgentTrajectoryEventType.tool_observation_recorded,
                run_id=run_id, delegation_id=delegation_id, payload=payload,
            )
            conn.commit()
        return observation, event

    def list_tool_observations(
        self, investigation_id: str, *, run_id: Optional[str] = None
    ) -> list[ToolObservation]:
        sql = (
            "SELECT * FROM agent_tool_observations "
            "WHERE task_id = ? AND investigation_id = ?"
        )
        params: list = [self.task_id, investigation_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        sql += " ORDER BY created_at, observation_id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_observation(r) for r in rows]

    def _insert_delegation_result_with_conn(
        self,
        conn: sqlite3.Connection,
        delegation_id: str,
        *,
        result_version: str,
        result: Mapping[str, Any],
        result_hash: str,
        context_hash: Optional[str] = None,
        tool_registry_hash: Optional[str] = None,
        model_name: Optional[str] = None,
        model_config_hash: Optional[str] = None,
        usage: Optional[Mapping[str, Any]] = None,
        validation_status: str = "valid",
    ) -> DelegationResult:
        row = self._require_delegation_row_with_conn(conn, delegation_id)
        now = _now_iso()
        conn.execute(
            "INSERT INTO agent_delegation_results "
            "(task_id, investigation_id, run_id, delegation_id, result_version, "
            " result_json, result_hash, context_hash, tool_registry_hash, "
            " model_name, model_config_hash, usage_json, validation_status, "
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                self.task_id, row["investigation_id"], row["run_id"],
                delegation_id, result_version,
                canonical_state_json(dict(result)), result_hash,
                context_hash, tool_registry_hash, model_name,
                model_config_hash,
                canonical_state_json(dict(usage)) if usage is not None else None,
                validation_status, now,
            ],
        )
        stored = conn.execute(
            "SELECT * FROM agent_delegation_results "
            "WHERE task_id = ? AND delegation_id = ?",
            [self.task_id, delegation_id],
        ).fetchone()
        return self._row_to_delegation_result(stored)

    def _row_to_delegation_result(self, row: sqlite3.Row) -> DelegationResult:
        import json as _json

        usage = None
        if row["usage_json"]:
            usage = _json.loads(row["usage_json"])
        return DelegationResult(
            result_id=int(row["result_id"]),
            task_id=row["task_id"],
            investigation_id=row["investigation_id"],
            run_id=row["run_id"],
            delegation_id=row["delegation_id"],
            result_version=row["result_version"],
            result=_json.loads(row["result_json"]),
            result_hash=row["result_hash"],
            context_hash=row["context_hash"],
            tool_registry_hash=row["tool_registry_hash"],
            model_name=row["model_name"],
            model_config_hash=row["model_config_hash"],
            usage=usage,
            validation_status=row["validation_status"],
            created_at=row["created_at"],
        )

    def get_delegation_result(
        self, delegation_id: str
    ) -> Optional[DelegationResult]:
        with self._connect() as conn:
            stored = conn.execute(
                "SELECT * FROM agent_delegation_results "
                "WHERE task_id = ? AND delegation_id = ?",
                [self.task_id, delegation_id],
            ).fetchone()
        return self._row_to_delegation_result(stored) if stored else None

    def record_delegation_result(
        self,
        delegation_id: str,
        *,
        result_version: str,
        result: Mapping[str, Any],
        result_hash: str,
        context_hash: Optional[str] = None,
        tool_registry_hash: Optional[str] = None,
        model_name: Optional[str] = None,
        model_config_hash: Optional[str] = None,
        usage: Optional[Mapping[str, Any]] = None,
        validation_status: str = "valid",
    ) -> DelegationResult:
        """Persist one immutable result row (invalid-result audit path).

        For the successful path use :meth:`complete_delegation_with_result`,
        which makes the result row and the delegation's ``completed``
        transition one atomic transaction.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            stored = self._insert_delegation_result_with_conn(
                conn, delegation_id,
                result_version=result_version, result=result,
                result_hash=result_hash, context_hash=context_hash,
                tool_registry_hash=tool_registry_hash,
                model_name=model_name, model_config_hash=model_config_hash,
                usage=usage, validation_status=validation_status,
            )
            conn.commit()
        return stored

    def complete_delegation_with_result(
        self,
        delegation_id: str,
        *,
        result_version: str,
        result: Mapping[str, Any],
        result_hash: str,
        context_hash: Optional[str] = None,
        tool_registry_hash: Optional[str] = None,
        model_name: Optional[str] = None,
        model_config_hash: Optional[str] = None,
        usage: Optional[Mapping[str, Any]] = None,
        trajectory_payload: Optional[Mapping[str, Any]] = None,
    ) -> tuple[DelegationResult, AgentDelegation]:
        """Atomic terminal success (P4A): the result row and the delegation's
        ``completed`` transition land in one transaction — a completed
        delegation always has exactly one valid result row, and a failed
        insert never terminalizes the delegation.

        ``trajectory_payload`` extends the completion Action Trace with the
        execution provenance chain (execution input hash, frozen profile /
        skill bindings, registry hash) — durable audit without a schema
        change; the payload never carries result data or evidence bodies.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            stored = self._insert_delegation_result_with_conn(
                conn, delegation_id,
                result_version=result_version, result=result,
                result_hash=result_hash, context_hash=context_hash,
                tool_registry_hash=tool_registry_hash,
                model_name=model_name, model_config_hash=model_config_hash,
                usage=usage, validation_status="valid",
            )
            row = self._require_delegation_row_with_conn(conn, delegation_id)
            now = _now_iso()
            delegation = self._transition_delegation_with_conn(
                conn, row, DelegationStatus.completed, now=now,
            )
            payload = dict(trajectory_payload or {})
            payload.setdefault("result_hash", result_hash)
            self._append_trajectory_with_conn(
                conn, delegation.investigation_id,
                _DELEGATION_TRAJECTORY_EVENT[DelegationStatus.completed],
                run_id=delegation.run_id, delegation_id=delegation_id,
                payload=payload, now=now,
            )
            conn.commit()
        return stored, delegation

    # =====================================================================
    # atomic finalization commit (P2 §37)
    # =====================================================================

    def record_finalization(
        self,
        investigation_id: str,
        *,
        state_revision: int,
        state_hash: str,
        completion_mode: str,
        question_dispositions: dict,
        coverage_dispositions: dict,
        unresolved_contradictions: list,
        limitations: list,
        remaining_nonblocking_questions: list,
        pending_analyst_review_refs: list,
        final_verification_status: str,
        finalization_policy_version: str,
        input_hash: str,
        run_id: Optional[str] = None,
        verifier_result_ref: Optional[str] = None,
    ) -> FinalizationRecord:
        """Atomic Finalization Commit (single BEGIN IMMEDIATE transaction).

        Revalidates the mechanical preconditions (active investigation,
        current state revision + hash, active-run binding), inserts the
        immutable FinalizationRecord, completes the run
        (``stop_reason=finalized``) and the investigation, and appends the
        ``finalization_completed`` trace event.  Any failure rolls the whole
        finalization back — an investigation can never be left ``completed``
        without its record.
        """
        if completion_mode not in ("complete", "complete_with_limitations"):
            raise ValueError(f"invalid completion_mode: {completion_mode!r}")
        if final_verification_status not in ("passed", "unavailable"):
            raise ValueError(
                f"invalid final_verification_status: {final_verification_status!r}"
            )
        now = _now_iso()
        finalization_id = f"fz_{uuid.uuid4().hex}"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            investigation = self._require_investigation_with_conn(
                conn, investigation_id
            )
            if investigation["status"] != AgentInvestigationStatus.active.value:
                raise AgentRuntimeConflictError(
                    "finalization requires an active investigation "
                    f"(current: {investigation['status']!r})"
                )
            revision_row = conn.execute(
                "SELECT revision, state_hash FROM agent_working_state_revisions "
                "WHERE task_id = ? AND investigation_id = ? "
                "ORDER BY revision DESC LIMIT 1",
                [self.task_id, investigation_id],
            ).fetchone()
            if revision_row is None or revision_row["revision"] != state_revision:
                raise WorkingStateRevisionConflictError(
                    f"stale finalization: expected revision {state_revision}, "
                    f"current is {revision_row['revision'] if revision_row else None}"
                )
            if revision_row["state_hash"] != state_hash:
                raise WorkingStateRevisionConflictError(
                    "finalization state_hash does not match the committed revision"
                )
            if run_id is not None:
                run_row = conn.execute(
                    "SELECT * FROM agent_runs WHERE task_id = ? AND run_id = ?",
                    [self.task_id, run_id],
                ).fetchone()
                if run_row is None or run_row["investigation_id"] != investigation_id:
                    raise ValueError(f"run not found: {run_id!r}")
                if run_row["status"] != AgentRunStatus.running.value:
                    # Finalization never fabricates run_started semantics: a
                    # queued run only holds an admission, and terminal runs
                    # cannot finalize.
                    raise AgentRuntimeConflictError(
                        f"finalization requires a running run "
                        f"(current: {run_row['status']!r})"
                    )
                self._transition_run_with_conn(
                    conn, run_row, AgentRunStatus.completed,
                    stop_reason=RunStopReason.finalized, now=now,
                )
            else:
                stranded = conn.execute(
                    "SELECT 1 FROM agent_runs "
                    "WHERE task_id = ? AND investigation_id = ? "
                    "AND status IN ('queued','running')",
                    [self.task_id, investigation_id],
                ).fetchone()
                if stranded is not None:
                    raise AgentRuntimeConflictError(
                        "investigation still has an active run; pass run_id or "
                        "settle it first"
                    )
            conn.execute(
                "INSERT INTO agent_finalizations "
                "(finalization_id, task_id, investigation_id, run_id, "
                " state_revision, state_hash, completion_mode, "
                " question_dispositions_json, coverage_dispositions_json, "
                " unresolved_contradictions_json, limitations_json, "
                " remaining_nonblocking_questions_json, "
                " pending_analyst_review_refs_json, final_verification_status, "
                " verifier_result_ref, finalization_policy_version, input_hash, "
                " completed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    finalization_id, self.task_id, investigation_id, run_id,
                    state_revision, state_hash, completion_mode,
                    canonical_state_json(dict(question_dispositions)),
                    canonical_state_json(dict(coverage_dispositions)),
                    canonical_state_json(list(unresolved_contradictions)),
                    canonical_state_json(list(limitations)),
                    canonical_state_json(list(remaining_nonblocking_questions)),
                    canonical_state_json(list(pending_analyst_review_refs)),
                    final_verification_status, verifier_result_ref,
                    finalization_policy_version, input_hash, now,
                ],
            )
            conn.execute(
                "UPDATE agent_investigations "
                "SET status = 'completed', completed_at = ?, updated_at = ? "
                "WHERE task_id = ? AND investigation_id = ?",
                [now, now, self.task_id, investigation_id],
            )
            self._append_trajectory_with_conn(
                conn, investigation_id,
                AgentTrajectoryEventType.finalization_completed,
                run_id=run_id,
                payload={
                    "finalization_id": finalization_id,
                    "completion_mode": completion_mode,
                    "state_revision": state_revision,
                },
                now=now,
            )
            row = conn.execute(
                "SELECT * FROM agent_finalizations "
                "WHERE task_id = ? AND finalization_id = ?",
                [self.task_id, finalization_id],
            ).fetchone()
            record = self._row_to_finalization(row)
            conn.commit()
        return record

    def get_finalization(
        self, investigation_id: str
    ) -> Optional[FinalizationRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_finalizations "
                "WHERE task_id = ? AND investigation_id = ?",
                [self.task_id, investigation_id],
            ).fetchone()
        return self._row_to_finalization(row) if row is not None else None

    @staticmethod
    def _row_to_finalization(row: sqlite3.Row) -> FinalizationRecord:
        def _load_json(value: str, fallback):
            try:
                return json.loads(value)
            except (TypeError, ValueError):
                return fallback

        return FinalizationRecord(
            finalization_id=row["finalization_id"],
            task_id=row["task_id"],
            investigation_id=row["investigation_id"],
            run_id=row["run_id"],
            state_revision=row["state_revision"],
            state_hash=row["state_hash"],
            completion_mode=row["completion_mode"],
            question_dispositions=_load_json(row["question_dispositions_json"], {}),
            coverage_dispositions=_load_json(row["coverage_dispositions_json"], {}),
            unresolved_contradictions=_load_json(
                row["unresolved_contradictions_json"], []
            ),
            limitations=_load_json(row["limitations_json"], []),
            remaining_nonblocking_questions=_load_json(
                row["remaining_nonblocking_questions_json"], []
            ),
            pending_analyst_review_refs=_load_json(
                row["pending_analyst_review_refs_json"], []
            ),
            final_verification_status=row["final_verification_status"],
            verifier_result_ref=row["verifier_result_ref"],
            finalization_policy_version=row["finalization_policy_version"],
            input_hash=row["input_hash"],
            completed_at=row["completed_at"],
        )

    # =====================================================================
    # restart recovery
    # =====================================================================

    def recover_interrupted_agent_runtime(self) -> dict[str, int]:
        """Deterministic restart recovery (P1 §10).

        - queued/running runs -> failed(stop_reason=runtime_restart)
        - queued/running delegations -> failed(failure_code=runtime_restart)
        - active investigations -> paused(pause_reason=runtime_restart)
        - working state keeps its last committed revision (no rollback, no
          synthetic revision)

        Idempotent: a second invocation recovers nothing and returns zeros.
        """
        now = _now_iso()
        runs_failed = 0
        delegations_failed = 0
        investigations_paused = 0
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run_rows = conn.execute(
                "SELECT * FROM agent_runs "
                "WHERE task_id = ? AND status IN ('queued','running') "
                "ORDER BY created_at, run_id",
                [self.task_id],
            ).fetchall()
            for row in run_rows:
                self._transition_run_with_conn(
                    conn, row, AgentRunStatus.failed,
                    stop_reason=RunStopReason.runtime_restart,
                    error_code="runtime_restart",
                    error_message="agent run interrupted by service restart",
                    now=now,
                )
                self._append_trajectory_with_conn(
                    conn, row["investigation_id"],
                    AgentTrajectoryEventType.run_failed,
                    run_id=row["run_id"],
                    payload={"stop_reason": RunStopReason.runtime_restart.value},
                    now=now,
                )
                runs_failed += 1
            delegation_rows = conn.execute(
                "SELECT * FROM agent_delegations "
                "WHERE task_id = ? AND status IN ('queued','running') "
                "ORDER BY created_at, delegation_id",
                [self.task_id],
            ).fetchall()
            for row in delegation_rows:
                self._transition_delegation_with_conn(
                    conn, row, DelegationStatus.failed,
                    failure_code="runtime_restart",
                    failure_message="delegation interrupted by service restart",
                    now=now,
                )
                self._append_trajectory_with_conn(
                    conn, row["investigation_id"],
                    AgentTrajectoryEventType.delegation_failed,
                    run_id=row["run_id"], delegation_id=row["delegation_id"],
                    payload={"failure_code": "runtime_restart"}, now=now,
                )
                delegations_failed += 1
            investigation_rows = conn.execute(
                "SELECT * FROM agent_investigations "
                "WHERE task_id = ? AND status = 'active' "
                "ORDER BY created_at, investigation_id",
                [self.task_id],
            ).fetchall()
            for row in investigation_rows:
                investigation_id = row["investigation_id"]
                conn.execute(
                    "UPDATE agent_investigations "
                    "SET status = 'paused', pause_reason = ?, updated_at = ? "
                    "WHERE task_id = ? AND investigation_id = ?",
                    [
                        InvestigationPauseReason.runtime_restart.value, now,
                        self.task_id, investigation_id,
                    ],
                )
                self._append_trajectory_with_conn(
                    conn, investigation_id,
                    AgentTrajectoryEventType.investigation_paused,
                    payload={
                        "pause_reason": InvestigationPauseReason.runtime_restart.value
                    },
                    now=now,
                )
                investigations_paused += 1
            # One runtime_recovered marker per investigation the sweep touched.
            touched = {
                r["investigation_id"] for r in run_rows
            } | {
                r["investigation_id"] for r in delegation_rows
            } | {
                r["investigation_id"] for r in investigation_rows
            }
            for investigation_id in sorted(touched):
                self._append_trajectory_with_conn(
                    conn, investigation_id,
                    AgentTrajectoryEventType.runtime_recovered,
                    payload={
                        "runs_failed": runs_failed,
                        "delegations_failed": delegations_failed,
                        "investigations_paused": investigations_paused,
                    },
                    now=now,
                )
            conn.commit()
        if runs_failed or delegations_failed or investigations_paused:
            logger.info(
                "agent runtime recovery for task %s: %s",
                self.task_id,
                {
                    "runs_failed": runs_failed,
                    "delegations_failed": delegations_failed,
                    "investigations_paused": investigations_paused,
                },
            )
        return {
            "runs_failed": runs_failed,
            "delegations_failed": delegations_failed,
            "investigations_paused": investigations_paused,
        }
