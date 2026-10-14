"""RCA-2A.2d — one-shot AgentRun settlement regression (CF-1 fix).

Helper-level deterministic tests on the REAL P1 SQLite repository (no
service, no model).  The CLI-level scenarios (T1-T7) run through the
real run_p8b_baseline CLI with FunctionModel injection; their evidence
lives in benchmarks/audits/rca2a2d-cf1-settlement/.  This file pins the
settlement adapter contract itself: exact scope, idempotency,
no-regression concurrency behavior, cause preservation, missing-store
handling, recovery non-interference, and fail-loud persistence.

Lifecycle vocabulary is frozen: only existing AgentRunStatus values and
existing RunStopReason values are used; the investigation is never
completed or mutated by settlement.
"""

from __future__ import annotations

import json

import pytest

from httpserver.services.benchmarks.one_shot_settlement import (
    settle_one_shot_execution,
)
from httpserver.services.investigation.agent_runtime import (
    AgentRunStatus,
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
    RunStopReason,
)
from httpserver.services.investigation.agent_working_state import (
    QuestionPriority,
    QuestionSource,
    AgentWorkingStateV1,
    WorkingQuestion,
    working_state_to_json,
)
from httpserver.services.investigation.repository import (
    InvestigationRepository,
)

pytestmark = pytest.mark.migration_matrix

TASK = "task-A"


def _build_store(tmp_path):
    db = tmp_path / "investigation.db"
    repo = InvestigationRepository(db, TASK)
    runtime = AgentRuntimeRepository(repo)
    investigation_id = "inv-test"
    runtime.create_investigation(
        working_state_to_json(
            AgentWorkingStateV1(
                task_id=TASK,
                investigation_id=investigation_id,
                objective="o",
                questions=(
                    WorkingQuestion(
                        question_id="q-1",
                        text="t",
                        source=QuestionSource.charter,
                        priority=QuestionPriority.required,
                    ),
                ),
            )
        ),
        investigation_id=investigation_id,
    )
    return db, runtime, investigation_id


def _admit_run(runtime, investigation_id, *, mark_running=True):
    run = runtime.start_run(investigation_id)
    if mark_running:
        runtime.mark_run_running(run.run_id)
    return run


def _record_plan_failure(runtime, investigation_id, code="agent_timeout"):
    runtime.append_trajectory(
        investigation_id,
        AgentTrajectoryEventType.transition_decision_rejected,
        payload={"supervisor_failure": code, "stage": "plan",
                 "message": f"{code}: contained"},
    )


def _runs(runtime, investigation_id):
    return {
        r.run_id: (r.status.value, r.stop_reason.value if r.stop_reason else None)
        for r in runtime.list_runs(investigation_id)
    }


# ---------------------------------------------------------------------------
# cause mapping + basic settlement
# ---------------------------------------------------------------------------


def test_settle_running_run_with_plan_failure_preserves_original_code(tmp_path):
    db, runtime, investigation_id = _build_store(tmp_path)
    run = _admit_run(runtime, investigation_id)
    _record_plan_failure(runtime, investigation_id, "agent_output_invalid")

    report = settle_one_shot_execution(
        db_path=db, task_id=TASK, investigation_id=investigation_id
    )
    assert report["action"] == "settled"
    entry = report["runs"][0]
    assert (entry["before"], entry["after"]) == ("running", "failed")
    status, stop_reason = _runs(runtime, investigation_id)[run.run_id]
    assert status == "failed"
    # the trajectory-recorded cause is carried verbatim into the row
    assert stop_reason == "internal_failure"
    row = runtime.get_run(run.run_id)
    assert row.error_code == "agent_output_invalid"
    assert "contained supervisor failure" in row.error_message
    # the investigation was never finalized by settlement
    assert report["investigation_finalized"] is False
    assert runtime.get_finalization(investigation_id) is None


def test_settle_running_run_without_finalization_uses_budget_exhausted(tmp_path):
    db, runtime, investigation_id = _build_store(tmp_path)
    _admit_run(runtime, investigation_id)  # no failure events at all

    report = settle_one_shot_execution(
        db_path=db, task_id=TASK, investigation_id=investigation_id
    )
    run_row = list(_runs(runtime, investigation_id).values())[0]
    assert run_row == ("failed", "budget_exhausted")
    assert report["runs"][0]["transition"] == "failed"


def test_settle_with_finalization_denial_records_denied_code(tmp_path):
    db, runtime, investigation_id = _build_store(tmp_path)
    _admit_run(runtime, investigation_id)
    runtime.append_trajectory(
        investigation_id,
        AgentTrajectoryEventType.finalization_denied,
        payload={"violation_codes": ["COVERAGE_NOT_TERMINAL"]},
    )
    settle_one_shot_execution(
        db_path=db, task_id=TASK, investigation_id=investigation_id
    )
    run_row = list(_runs(runtime, investigation_id).values())[0]
    assert run_row == ("failed", "budget_exhausted")
    row = runtime.get_run(
        list(_runs(runtime, investigation_id))[0] if False else
        runtime.list_runs(investigation_id)[0].run_id
    )
    assert row.error_code == "finalization_denied"


def test_settle_cancelled_execution_keeps_cancel_semantics(tmp_path):
    db, runtime, investigation_id = _build_store(tmp_path)
    _admit_run(runtime, investigation_id)

    report = settle_one_shot_execution(
        db_path=db, task_id=TASK, investigation_id=investigation_id,
        execution_cancelled=True,
    )
    run_row = list(_runs(runtime, investigation_id).values())[0]
    assert run_row == ("cancelled", "cancelled")
    assert report["execution_cancelled"] is True


def test_settle_queued_run_is_legal(tmp_path):
    db, runtime, investigation_id = _build_store(tmp_path)
    _admit_run(runtime, investigation_id, mark_running=False)

    settle_one_shot_execution(
        db_path=db, task_id=TASK, investigation_id=investigation_id
    )
    assert list(_runs(runtime, investigation_id).values())[0][0] == "failed"


# ---------------------------------------------------------------------------
# idempotency / recovery / isolation
# ---------------------------------------------------------------------------


def test_second_settlement_is_noop_without_new_events(tmp_path):
    db, runtime, investigation_id = _build_store(tmp_path)
    _admit_run(runtime, investigation_id)
    _record_plan_failure(runtime, investigation_id)

    first = settle_one_shot_execution(
        db_path=db, task_id=TASK, investigation_id=investigation_id
    )
    events_after_first = len(runtime.list_trajectory(investigation_id))
    second = settle_one_shot_execution(
        db_path=db, task_id=TASK, investigation_id=investigation_id
    )
    assert first["action"] == "settled"
    assert second["action"] == "settled"
    assert second["runs"][0]["transition"] == "already_terminal"
    assert second["settlement_events_appended"] == 0
    assert len(runtime.list_trajectory(investigation_id)) == events_after_first


def test_recovery_after_settlement_changes_nothing(tmp_path):
    db, runtime, investigation_id = _build_store(tmp_path)
    _admit_run(runtime, investigation_id)
    settle_one_shot_execution(
        db_path=db, task_id=TASK, investigation_id=investigation_id
    )
    before = _runs(runtime, investigation_id)
    summary = runtime.recover_interrupted_agent_runtime()
    # no runs to recover and no re-settlement: the settled terminal state
    # is untouched (recovery may still pause the still-active
    # investigation — that is recovery's own unchanged semantics)
    assert summary["runs_failed"] == 0
    assert summary["delegations_failed"] == 0
    assert _runs(runtime, investigation_id) == before


def test_settlement_is_isolated_to_target_investigation(tmp_path):
    db, runtime, investigation_id = _build_store(tmp_path)
    target = _admit_run(runtime, investigation_id)
    _record_plan_failure(runtime, investigation_id)

    # a second investigation + run in the SAME store must stay untouched
    other_id = "inv-other"
    runtime.create_investigation(
        working_state_to_json(
            AgentWorkingStateV1(
                task_id=TASK, investigation_id=other_id, objective="o",
                questions=(),
            )
        ),
        investigation_id=other_id,
    )
    other = _admit_run(runtime, other_id)
    other_events = len(runtime.list_trajectory(other_id))

    settle_one_shot_execution(
        db_path=db, task_id=TASK, investigation_id=investigation_id
    )
    assert _runs(runtime, investigation_id)[target.run_id][0] == "failed"
    assert _runs(runtime, other_id)[other.run_id][0] == "running"
    assert len(runtime.list_trajectory(other_id)) == other_events


# ---------------------------------------------------------------------------
# missing store / missing investigation / fail-loud persistence
# ---------------------------------------------------------------------------


def test_missing_store_is_reported_and_never_recreated(tmp_path):
    db = tmp_path / "investigation.db"
    report = settle_one_shot_execution(
        db_path=db, task_id=TASK, investigation_id="inv-x"
    )
    assert report["action"] == "store_missing"
    assert not db.exists()


def test_missing_investigation_is_reported(tmp_path):
    db, runtime, _ = _build_store(tmp_path)
    report = settle_one_shot_execution(
        db_path=db, task_id=TASK, investigation_id="inv-absent"
    )
    assert report["action"] == "no_investigation"


def test_unpersistable_settlement_raises_never_fakes_success(
    tmp_path, monkeypatch
):
    db, runtime, investigation_id = _build_store(tmp_path)
    _admit_run(runtime, investigation_id)

    def broken_fail_run(self, *args, **kwargs):
        return None  # silently does nothing — a persistence lie

    monkeypatch.setattr(AgentRuntimeRepository, "fail_run", broken_fail_run)
    with pytest.raises(RuntimeError, match="did not persist"):
        settle_one_shot_execution(
            db_path=db, task_id=TASK, investigation_id=investigation_id
        )
    # the durable row is still non-terminal (safely recoverable later)
    assert (
        _runs(runtime, investigation_id)[
            runtime.list_runs(investigation_id)[0].run_id
        ][0]
        == "running"
    )


# ---------------------------------------------------------------------------
# T11 — independent accounting facts
# ---------------------------------------------------------------------------


def test_accounting_facts_are_independent(tmp_path):
    db, runtime, investigation_id = _build_store(tmp_path)
    _admit_run(runtime, investigation_id)
    report = settle_one_shot_execution(
        db_path=db, task_id=TASK, investigation_id=investigation_id
    )
    # AgentRun terminal AND investigation NOT finalized are independent
    # facts in one report — CLI-exited is the caller's own fact.
    assert report["investigation_finalized"] is False
    assert all(r["after"] in ("failed", "cancelled", "completed")
               for r in report["runs"])
    # the report must be JSON-serializable for settlement.json
    json.dumps(report)
