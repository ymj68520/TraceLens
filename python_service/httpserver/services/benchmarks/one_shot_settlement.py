"""One-shot AgentRun lifecycle settlement (RCA-2A.2d, CF-1 minimal fix).

A one-shot benchmark CLI owns exactly one investigation and its run(s).
When the execution returns — or raises — the durable AgentRun row must
not persist a non-terminal state that only an out-of-band service
restart would ever terminalize (CF-1, RCA-2A.2c audit).

This adapter composes EXISTING repository primitives only:

- reads the run's persisted status (the concurrency check — any
  concurrent transition is re-validated inside the repository's
  ``BEGIN IMMEDIATE`` transaction against the frozen ``RUN_TRANSITIONS``
  table, so a lost race can never regress a terminal state);
- terminalizes via ``fail_run`` / ``cancel_run`` — the same targeted,
  run_id-scoped transitions the containment paths use.  No new AgentRun
  status, no new stop reason, no trajectory fabrications.

It is deliberately NOT ``recover_interrupted_agent_runtime``: recovery
is a task-wide crash-recovery sweep (fails other runs, fails pending
delegations, pauses investigations, appends runtime_recovered markers).
One-shot settlement only settles the runs of the investigation this
execution created; recovery remains the owner of abnormal-interrupt
cleanup.  The two are never conflated:

    Recovery:            abnormal interruption of historical runs
    One-Shot Settlement: the definitely-ended execution of THIS invocation

Cause mapping (existing vocabulary only, original causes preserved):

- cancelled execution            -> cancelled / stop_reason=cancelled
- contained supervisor failure   -> failed / stop_reason=internal_failure,
                                    error_code = the trajectory-recorded
                                    supervisor failure code (verbatim)
- finalization denied            -> failed / stop_reason=budget_exhausted,
                                    error_code=finalization_denied
- ended without finalization     -> failed / stop_reason=budget_exhausted,
                                    error_code=one_shot_exit_without_finalization

The investigation itself is NEVER completed, finalized, or mutated:
settlement touches only the AgentRun row, and a failed settlement
propagates — a settlement that cannot persist never reports success.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..investigation.agent_runtime import (
    AgentRunStatus,
    AgentRuntimeConflictError,
    AgentRuntimeRepository,
    RunStopReason,
)
from ..investigation.repository import InvestigationRepository

_NON_TERMINAL = (AgentRunStatus.queued, AgentRunStatus.running)

_NO_FINALIZATION_CODE = "one_shot_exit_without_finalization"


def _derive_cause(
    runtime: AgentRuntimeRepository, investigation_id: str
) -> tuple[str, str, str]:
    """(stop_reason, error_code, error_message) from the durable
    trajectory — the original failure codes are carried verbatim."""
    stop_reason = RunStopReason.budget_exhausted
    error_code = _NO_FINALIZATION_CODE
    error_message = (
        "one-shot execution ended without investigation finalization"
    )
    supervisor_failure = None
    finalization_denial = None
    for event in runtime.list_trajectory(investigation_id):
        payload = event.payload or {}
        if event.event_type.value == "transition_decision_rejected" and (
            payload.get("supervisor_failure")
        ):
            supervisor_failure = (
                payload.get("supervisor_failure"),
                payload.get("stage") or "plan",
                payload.get("message"),
            )
        elif event.event_type.value == "finalization_denied":
            finalization_denial = list(payload.get("violation_codes") or ())
    if supervisor_failure is not None:
        code, stage, message = supervisor_failure
        return (
            RunStopReason.internal_failure.value,
            str(code),
            (
                f"one-shot execution ended before finalization; contained "
                f"supervisor failure at stage {stage!r}: {message or code}"
            ),
        )
    if finalization_denial is not None:
        return (
            RunStopReason.budget_exhausted.value,
            "finalization_denied",
            (
                "one-shot execution ended; the finalization gate denied "
                f"completion with violation codes {finalization_denial}"
            ),
        )
    return stop_reason.value, error_code, error_message


def settle_one_shot_execution(
    *,
    db_path: str | Path,
    task_id: str,
    investigation_id: str,
    execution_cancelled: bool = False,
) -> dict:
    """Settle every non-terminal AgentRun of ONE investigation.

    Scope is exact: only runs under ``investigation_id`` in the store at
    ``db_path`` are considered.  Idempotent: already-terminal runs are
    reported and left untouched (a second invocation performs no state
    transition and appends no events).  A missing store is never
    recreated.  Any persistence failure raises — the caller must never
    observe a success report for a settlement that did not persist.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        # never recreate a deleted store (T7): report and return
        return {
            "action": "store_missing",
            "task_id": task_id,
            "investigation_id": investigation_id,
            "runs": [],
            "investigation_finalized": False,
        }
    try:
        repo = InvestigationRepository.open_existing(db_path, task_id)
    except Exception:
        # vanished between the check and the open — same contract
        return {
            "action": "store_missing",
            "task_id": task_id,
            "investigation_id": investigation_id,
            "runs": [],
            "investigation_finalized": False,
        }
    runtime = AgentRuntimeRepository(repo)
    if runtime.get_investigation(investigation_id) is None:
        return {
            "action": "no_investigation",
            "task_id": task_id,
            "investigation_id": investigation_id,
            "runs": [],
            "investigation_finalized": False,
        }

    events_before = len(runtime.list_trajectory(investigation_id))
    stop_reason = error_code = error_message = None
    if not execution_cancelled:
        stop_reason, error_code, error_message = _derive_cause(
            runtime, investigation_id
        )

    run_reports: list[dict] = []
    for run in runtime.list_runs(investigation_id):
        before = run.status.value
        if run.status not in _NON_TERMINAL:
            run_reports.append({
                "run_id": run.run_id,
                "before": before,
                "after": before,
                "transition": "already_terminal",
                "stop_reason": (
                    run.stop_reason.value if run.stop_reason else None
                ),
                "error_code": run.error_code,
            })
            continue
        try:
            if execution_cancelled:
                settled = runtime.cancel_run(
                    run.run_id, stop_reason=RunStopReason.cancelled
                )
            else:
                settled = runtime.fail_run(
                    run.run_id,
                    stop_reason=RunStopReason(stop_reason),
                    error_code=error_code,
                    error_message=error_message,
                )
        except AgentRuntimeConflictError:
            # a concurrent transition won the race; never regress it —
            # re-read and report the persisted outcome
            settled = runtime.get_run(run.run_id)
            transition = "lost_race_no_regression"
        else:
            transition = (
                "cancelled" if execution_cancelled else "failed"
            )
        if settled is None or settled.status in _NON_TERMINAL:
            # a transition that silently failed to persist is a
            # persistence lie — fail loud, never report success
            raise RuntimeError(
                "one-shot settlement did not persist: run "
                f"{run.run_id} transition returned "
                f"{getattr(settled, 'status', None)!r}"
            )
        run_reports.append({
            "run_id": run.run_id,
            "before": before,
            "after": settled.status.value,
            "transition": transition,
            "stop_reason": (
                settled.stop_reason.value if settled.stop_reason else None
            ),
            "error_code": settled.error_code,
        })

    # durable verification: nothing of this investigation may remain
    # non-terminal; a settlement that cannot verify persistence raises
    remaining = [
        run.status.value
        for run in runtime.list_runs(investigation_id)
        if run.status in _NON_TERMINAL
    ]
    if remaining:
        raise RuntimeError(
            "one-shot settlement did not persist: "
            f"non-terminal runs remain under {investigation_id!r}: "
            f"{remaining}"
        )

    return {
        "action": "settled",
        "task_id": task_id,
        "investigation_id": investigation_id,
        "execution_cancelled": execution_cancelled,
        "runs": run_reports,
        "investigation_finalized": (
            runtime.get_finalization(investigation_id) is not None
        ),
        "settlement_events_appended": (
            len(runtime.list_trajectory(investigation_id)) - events_before
        ),
    }


__all__ = ["settle_one_shot_execution"]
