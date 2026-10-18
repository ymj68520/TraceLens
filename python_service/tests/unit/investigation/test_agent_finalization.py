"""P2-2 tests: schema v9 (agent_finalizations), FinalizationGate, and the
atomic Finalization Commit.

Covers P2 §50 (v9 schema/migration), §54 (gate hard-blocker matrix) and §55
(failure injection: a half-finished finalization can never persist).
"""

import sqlite3

import pytest

from httpserver.services.investigation.repository import SUPPORTED_SCHEMA_VERSION

from httpserver.services.evidence import EvidenceStoreError
from httpserver.services.investigation import (
    AgentInvestigationStatus,
    AgentRunStatus,
    AgentRuntimeConflictError,
    AgentRuntimeRepository,
    DelegationSpec,
    DelegationStatus,
    InvestigationRepository,
    RunStopReason,
    SUPPORTED_SCHEMA_VERSION,
    WorkingStateRevisionConflictError,
)
from httpserver.services.investigation.agent_finalization import (
    CapabilityFailure,
    CapabilityFailureCategory,
    CompletionMode,
    CRITICAL_CONTRADICTION_OPEN,
    FinalizationGate,
    FinalizationOutcome,
    FinalizationRequest,
    FinalReviewMode,
    FinalSemanticReview,
    FinalSemanticReviewStatus,
    INVESTIGATION_NOT_ACTIVE,
    MANDATORY_VERIFICATION_BLOCKING,
    RuntimeFinalizationView,
    UNAPPLIED_DIRECTIVE_PRESENT,
    ACTIVE_DELEGATION_PRESENT,
    UNINTEGRATED_COMPLETED_DELEGATION,
    REVIEW_ISSUES_FOUND,
    REVIEW_UNAVAILABLE,
    SEMANTIC_REQUIRED_NOT_DEGRADED,
    INTEGRITY_CRITICAL_FAILURE,
    STATE_REVISION_STALE,
    coverage_disposition_snapshot,
    finalization_input_hash,
    question_disposition_snapshot,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    Contradiction,
    ContradictionSeverity,
    ContradictionStatus,
    CoverageDimension,
    CoverageStatus,
    DirectiveDigest,
    PendingVerification,
    QuestionDisposition,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    VerificationStatus,
    WorkingQuestion,
)


# ---------- fixtures / helpers ----------

@pytest.fixture()
def runtime(tmp_path):
    repo = InvestigationRepository(tmp_path / "investigation.db", "A")
    return AgentRuntimeRepository(repo)


GATE = FinalizationGate()


def _active_run(runtime):
    investigation, revision = runtime.create_investigation({"objective": "demo"})
    run = runtime.start_run(investigation.investigation_id)
    runtime.mark_run_running(run.run_id)
    return investigation, revision, run


def _question(qid="Q1", priority=QuestionPriority.required, **overrides):
    kwargs = dict(
        question_id=qid, text=f"text {qid}",
        source=QuestionSource.charter, priority=priority,
    )
    kwargs.update(overrides)
    return WorkingQuestion(**kwargs)


def _state(**overrides) -> AgentWorkingStateV1:
    kwargs = dict(task_id="A", investigation_id="inv_x")
    kwargs.update(overrides)
    return AgentWorkingStateV1(**kwargs)


def _request(state, review_status=FinalSemanticReviewStatus.passed, **overrides):
    kwargs = dict(
        investigation_id=state.investigation_id,
        expected_state_revision=state.progress_state.completed_cycles + 1,
        review_mode=FinalReviewMode.required,
        final_semantic_review=FinalSemanticReview(status=review_status),
    )
    kwargs.update(overrides)
    return FinalizationRequest(**kwargs)


def _clean_state(**overrides) -> AgentWorkingStateV1:
    """A finalizable state: the required question answered with a clean
    disposition, required coverage covered.  Overrides replace defaults."""
    kwargs = dict(
        task_id="A",
        investigation_id="inv_x",
        questions=(_question(
            status=QuestionStatus.answered,
            disposition=QuestionDisposition.not_supported,
            basis_refs=("file:/a.txt",),
        ),),
        coverage=(CoverageDimension(
            dimension_id="usb", required=True,
            status=CoverageStatus.covered,
            basis_refs=("file:/a.txt",),
        ),),
    )
    kwargs.update(overrides)
    return AgentWorkingStateV1(**kwargs)


def _view(**overrides) -> RuntimeFinalizationView:
    kwargs = dict(investigation_status="active")
    kwargs.update(overrides)
    return RuntimeFinalizationView(**kwargs)


def _commit(runtime, investigation, revision, run=None, decision=None, state=None):
    return runtime.record_finalization(
        investigation.investigation_id,
        run_id=run.run_id if run else None,
        state_revision=revision.revision,
        state_hash=revision.state_hash,
        completion_mode=(decision.completion_mode.value if decision else "complete"),
        question_dispositions=question_disposition_snapshot(state or _clean_state()),
        coverage_dispositions=coverage_disposition_snapshot(state or _clean_state()),
        unresolved_contradictions=[],
        limitations=list(decision.limitations) if decision else [],
        remaining_nonblocking_questions=[],
        pending_analyst_review_refs=[],
        final_verification_status="passed",
        finalization_policy_version=GATE.policy_version,
        input_hash=finalization_input_hash(
            state or _clean_state(), _request(state or _clean_state()),
            _view(), decision,
        ) if decision else "hash",
    )


# ---------- schema v9 (P2 §50) ----------

def test_fresh_db_initializes_v9_with_finalizations(tmp_path):
    db = tmp_path / "investigation.db"
    InvestigationRepository(db, "A")
    assert SUPPORTED_SCHEMA_VERSION == 16
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SUPPORTED_SCHEMA_VERSION
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_finalizations'"
    ).fetchone() is not None
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def test_v8_to_v9_migration_rebuilds_enums_and_preserves_rows(tmp_path):
    db = tmp_path / "investigation.db"
    repo = InvestigationRepository(db, "A")
    agent = AgentRuntimeRepository(repo)
    investigation, _ = agent.create_investigation({"objective": "keep"})
    agent.append_trajectory(
        investigation.investigation_id, "investigation_created", payload={}
    )
    conn = sqlite3.connect(db)
    trajectory_count = conn.execute(
        "SELECT COUNT(*) FROM agent_trajectory_events"
    ).fetchone()[0]
    max_seq = conn.execute("SELECT MAX(seq) FROM agent_trajectory_events").fetchone()[0]
    # simulate a true v8 store: no finalizations table, old CHECK enums
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("DROP TABLE agent_finalizations")
    conn.execute("PRAGMA user_version = 8")
    conn.commit()
    conn.close()

    reopened = InvestigationRepository(db, "A")
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SUPPORTED_SCHEMA_VERSION
    assert conn.execute(
        "SELECT COUNT(*) FROM agent_trajectory_events"
    ).fetchone()[0] == trajectory_count
    assert conn.execute(
        "SELECT COUNT(*) FROM agent_investigations"
    ).fetchone()[0] == 1
    conn.close()
    # extended trajectory enum accepted; autoincrement seq survived rebuild
    agent2 = AgentRuntimeRepository(reopened)
    event = agent2.append_trajectory(
        investigation.investigation_id, "finalization_requested", payload={}
    )
    assert event.seq > max_seq
    # extended pause reason accepted
    inv2, _ = agent2.create_investigation({"objective": "x"})
    run2 = agent2.start_run(inv2.investigation_id)
    paused = agent2.pause_investigation(
        inv2.investigation_id, reason="finalization_review_unavailable"
    )
    assert paused.pause_reason.value == "finalization_review_unavailable"


def test_migration_chain_from_v5_reaches_v9(tmp_path):
    db = tmp_path / "investigation.db"
    InvestigationRepository(db, "A")
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    conn.close()
    InvestigationRepository(db, "A")
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SUPPORTED_SCHEMA_VERSION
    conn.close()


def test_unsupported_future_version_fails_closed(tmp_path):
    db = tmp_path / "investigation.db"
    db.write_bytes(b"")
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()
    with pytest.raises(EvidenceStoreError):
        InvestigationRepository(db, "A")


def test_finalization_record_is_immutable_and_single(runtime):
    investigation, revision, run = _active_run(runtime)
    _commit(runtime, investigation, revision, run=run)

    conn = sqlite3.connect(runtime._repo.db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE agent_finalizations SET completion_mode = 'complete' "
                "WHERE task_id = ?",
                ["A"],
            )
        conn.rollback()
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM agent_finalizations WHERE task_id = ?", ["A"])
        conn.rollback()
    finally:
        conn.close()
    with pytest.raises(AgentRuntimeConflictError):
        _commit(runtime, investigation, revision)


# ---------- FinalizationGate (P2 §54) ----------

def test_stale_revision_is_stale_not_denied():
    state = _clean_state()
    request = _request(state, expected_state_revision=99)
    decision = GATE.evaluate_stale(5, request)
    assert decision is not None
    assert decision.outcome is FinalizationOutcome.stale
    assert STATE_REVISION_STALE in decision.violation_codes
    assert GATE.evaluate_stale(5, _request(state, expected_state_revision=5)) is None


def test_active_and_unintegrated_delegations_deny():
    state = _clean_state()
    active = GATE.evaluate(
        "A", state, _request(state),
        _view(active_delegation_ids=("del_1",)),
    )
    assert active.outcome is FinalizationOutcome.deny
    assert ACTIVE_DELEGATION_PRESENT in active.violation_codes
    unintegrated = GATE.evaluate(
        "A", state, _request(state),
        _view(completed_unintegrated_delegation_ids=("del_2",)),
    )
    assert UNINTEGRATED_COMPLETED_DELEGATION in unintegrated.violation_codes


def test_unapplied_directive_denies():
    state = _clean_state(directive_refs=(
        DirectiveDigest(directive_ref="dir_1", applied=False),
    ))
    decision = GATE.evaluate("A", state, _request(state), _view())
    assert UNAPPLIED_DIRECTIVE_PRESENT in decision.violation_codes


def test_required_question_terminal_matrix():
    base = dict(coverage=(CoverageDimension(
        dimension_id="usb", required=True,
        status=CoverageStatus.covered, basis_refs=("file:/a",),
    ),))
    for status, expected_code in (
        (QuestionStatus.open, "REQUIRED_QUESTION_OPEN"),
        (QuestionStatus.in_progress, "REQUIRED_QUESTION_IN_PROGRESS"),
        (QuestionStatus.deferred, "REQUIRED_QUESTION_DEFERRED"),
    ):
        state = _clean_state(
            **base, questions=(_question(status=status),)
        )
        decision = GATE.evaluate("A", state, _request(state), _view())
        assert decision.outcome is FinalizationOutcome.deny
        assert expected_code in decision.violation_codes

    answered = _clean_state(
        **base, questions=(_question(
            status=QuestionStatus.answered,
            disposition=QuestionDisposition.supported,
            basis_refs=("file:/a.txt",),
        ),)
    )
    ok = GATE.evaluate("A", answered, _request(answered), _view())
    assert ok.outcome is FinalizationOutcome.pass_
    # not_supported is a clean full result, never an automatic limitation
    assert ok.completion_mode is CompletionMode.complete

    missing_disposition = _clean_state(
        **base, questions=(_question(status=QuestionStatus.answered),)
    )
    decision = GATE.evaluate("A", missing_disposition, _request(missing_disposition), _view())
    assert "QUESTION_DISPOSITION_REQUIRED" in decision.violation_codes

    unresolved = _clean_state(
        **base, questions=(_question(
            status=QuestionStatus.unresolved,
            basis_refs=("file:/a.txt",),
            limitations=("logs gone",),
            investigated_summary="searched",
        ),)
    )
    limited = GATE.evaluate("A", unresolved, _request(unresolved), _view())
    assert limited.outcome is FinalizationOutcome.pass_
    assert limited.completion_mode is CompletionMode.complete_with_limitations

    blocked = _clean_state(
        **base, questions=(_question(
            status=QuestionStatus.blocked, blocker="archive offline",
        ),)
    )
    blocked_decision = GATE.evaluate("A", blocked, _request(blocked), _view())
    assert blocked_decision.outcome is FinalizationOutcome.pass_
    assert blocked_decision.completion_mode is CompletionMode.complete_with_limitations


def test_required_coverage_matrix():
    base_question = _question(
        status=QuestionStatus.answered,
        disposition=QuestionDisposition.not_supported,
        basis_refs=("file:/a",),
    )
    for status, denied in (
        (CoverageStatus.not_started, True),
        (CoverageStatus.in_progress, True),
    ):
        state = _clean_state(
            questions=(base_question,),
            coverage=(CoverageDimension(
                dimension_id="usb", required=True, status=status,
            ),),
        )
        decision = GATE.evaluate("A", state, _request(state), _view())
        assert (decision.outcome is FinalizationOutcome.deny) is denied
        if denied:
            assert "COVERAGE_NOT_TERMINAL" in decision.violation_codes

    partial = _clean_state(
        questions=(base_question,),
        coverage=(CoverageDimension(
            dimension_id="usb", required=True, status=CoverageStatus.partial,
            basis_refs=("file:/a",), limitation="read-only image",
        ),),
    )
    decision = GATE.evaluate("A", partial, _request(partial), _view())
    assert decision.outcome is FinalizationOutcome.pass_
    assert decision.completion_mode is CompletionMode.complete_with_limitations

    not_applicable = _clean_state(
        questions=(base_question,),
        coverage=(CoverageDimension(
            dimension_id="usb", required=True,
            status=CoverageStatus.not_applicable,
            basis_refs=("no usb devices present",),
        ),),
    )
    decision = GATE.evaluate("A", not_applicable, _request(not_applicable), _view())
    assert decision.outcome is FinalizationOutcome.pass_
    assert decision.completion_mode is CompletionMode.complete


def test_critical_contradiction_finalization():
    open_critical = _clean_state(contradictions=(Contradiction(
        contradiction_id="C1", severity=ContradictionSeverity.critical,
        status=ContradictionStatus.open, refs=("file:/a",),
    ),))
    decision = GATE.evaluate("A", open_critical, _request(open_critical), _view())
    assert decision.outcome is FinalizationOutcome.deny
    assert CRITICAL_CONTRADICTION_OPEN in decision.violation_codes

    unresolved = _clean_state(contradictions=(Contradiction(
        contradiction_id="C1", severity=ContradictionSeverity.critical,
        status=ContradictionStatus.unresolved, refs=("file:/a",),
        resolution_basis_refs=("file:/a",),
        attempted_resolution="checked", impact="ambiguous", limitation="rotated",
    ),))
    decision = GATE.evaluate("A", unresolved, _request(unresolved), _view())
    assert decision.outcome is FinalizationOutcome.pass_
    assert decision.completion_mode is CompletionMode.complete_with_limitations


def test_mandatory_verification_blocks():
    state = _clean_state(pending_verifications=(PendingVerification(
        verification_id="V1", target_ref="Q1", required=True, blocking=True,
        status=VerificationStatus.pending,
    ),))
    decision = GATE.evaluate("A", state, _request(state), _view())
    assert MANDATORY_VERIFICATION_BLOCKING in decision.violation_codes


def test_capability_failure_policy():
    state = _clean_state()
    integrity = GATE.evaluate(
        "A", state, _request(state, capability_failures=(
            CapabilityFailure(
                category=CapabilityFailureCategory.integrity_critical,
                capability="store_hash",
            ),
        )),
        _view(),
    )
    assert INTEGRITY_CRITICAL_FAILURE in integrity.violation_codes

    not_degraded = GATE.evaluate(
        "A", state, _request(state, capability_failures=(
            CapabilityFailure(
                category=CapabilityFailureCategory.semantic_required,
                capability="semantic_verification",
            ),
        )),
        _view(),
    )
    assert SEMANTIC_REQUIRED_NOT_DEGRADED in not_degraded.violation_codes

    degraded = GATE.evaluate(
        "A", state, _request(state, capability_failures=(
            CapabilityFailure(
                category=CapabilityFailureCategory.semantic_required,
                capability="semantic_verification", degraded=True,
            ),
        )),
        _view(),
    )
    assert degraded.outcome is FinalizationOutcome.pass_
    assert degraded.completion_mode is CompletionMode.complete_with_limitations

    optional = GATE.evaluate(
        "A", state, _request(state, capability_failures=(
            CapabilityFailure(
                category=CapabilityFailureCategory.optional_enhancement,
                capability="graph_materialization",
            ),
        )),
        _view(),
    )
    assert optional.outcome is FinalizationOutcome.pass_
    assert optional.completion_mode is CompletionMode.complete


def test_final_semantic_review_policy():
    state = _clean_state()
    issues = GATE.evaluate(
        "A", state,
        _request(state, review_status=FinalSemanticReviewStatus.issues_found),
        _view(),
    )
    assert REVIEW_ISSUES_FOUND in issues.violation_codes

    best_effort = GATE.evaluate(
        "A", state,
        _request(
            state,
            review_status=FinalSemanticReviewStatus.unavailable,
            review_mode=FinalReviewMode.best_effort,
        ),
        _view(),
    )
    assert best_effort.outcome is FinalizationOutcome.pass_
    assert best_effort.completion_mode is CompletionMode.complete_with_limitations

    required_unavailable = GATE.evaluate(
        "A", state,
        _request(
            state,
            review_status=FinalSemanticReviewStatus.unavailable,
            review_mode=FinalReviewMode.required,
        ),
        _view(),
    )
    assert required_unavailable.outcome is FinalizationOutcome.deny
    assert REVIEW_UNAVAILABLE in required_unavailable.violation_codes


def test_completed_investigation_cannot_finalize_again():
    state = _clean_state()
    decision = GATE.evaluate(
        "A", state, _request(state), _view(investigation_status="completed")
    )
    assert INVESTIGATION_NOT_ACTIVE in decision.violation_codes


# ---------- atomic Finalization Commit (P2 §55) ----------

def test_successful_commit_is_atomic_and_complete(runtime):
    investigation, revision, run = _active_run(runtime)
    record = _commit(runtime, investigation, revision, run=run)
    assert runtime.get_investigation(
        investigation.investigation_id
    ).status is AgentInvestigationStatus.completed
    assert runtime.get_run(run.run_id).status is AgentRunStatus.completed
    assert runtime.get_run(run.run_id).stop_reason is RunStopReason.finalized
    assert runtime.get_finalization(investigation.investigation_id) == record
    trajectory = [
        e.event_type.value
        for e in runtime.list_trajectory(investigation.investigation_id)
    ]
    assert trajectory[-1] == "finalization_completed"


def test_record_insert_failure_rolls_everything_back(runtime):
    """A pre-existing record row forces a UNIQUE violation on the INSERT; the
    whole finalization transaction must roll back."""
    import uuid as _uuid

    investigation, revision, run = _active_run(runtime)
    # raw pre-insert of a colliding record (same investigation) bypassing the
    # API — simulates a crash between INSERT and COMMIT retried after commit
    conn = sqlite3.connect(runtime._repo.db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO agent_finalizations "
        "(finalization_id, task_id, investigation_id, run_id, state_revision, "
        " state_hash, completion_mode, question_dispositions_json, "
        " coverage_dispositions_json, unresolved_contradictions_json, "
        " limitations_json, remaining_nonblocking_questions_json, "
        " pending_analyst_review_refs_json, final_verification_status, "
        " finalization_policy_version, input_hash, completed_at) "
        "VALUES (?, 'A', ?, NULL, 1, 'h', 'complete', '{}', '{}', '[]', '[]', "
        "'[]', '[]', 'passed', 'finalization-policy:v1', 'h', '2026-01-01')",
        [f"fz_{_uuid.uuid4().hex}", investigation.investigation_id],
    )
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.IntegrityError):
        runtime.record_finalization(
            investigation.investigation_id,
            run_id=run.run_id,
            state_revision=revision.revision,
            state_hash=revision.state_hash,
            completion_mode="complete",
            question_dispositions={}, coverage_dispositions={},
            unresolved_contradictions=[], limitations=[],
            remaining_nonblocking_questions=[], pending_analyst_review_refs=[],
            final_verification_status="passed",
            finalization_policy_version=GATE.policy_version,
            input_hash="h",
        )
    # the colliding INSERT rolled back every other write of that transaction
    assert runtime.get_investigation(
        investigation.investigation_id
    ).status is AgentInvestigationStatus.active
    assert runtime.get_run(run.run_id).status is AgentRunStatus.running


def test_trajectory_failure_rolls_back_finalization(runtime, monkeypatch):
    investigation, revision, run = _active_run(runtime)
    original = AgentRuntimeRepository._append_trajectory_with_conn

    def broken(*args, **kwargs):
        raise RuntimeError("injected trajectory failure")

    monkeypatch.setattr(
        AgentRuntimeRepository, "_append_trajectory_with_conn", broken
    )
    with pytest.raises(RuntimeError):
        _commit(runtime, investigation, revision, run=run)
    monkeypatch.setattr(
        AgentRuntimeRepository, "_append_trajectory_with_conn", original
    )
    # nothing persisted: investigation still active, run still running,
    # no record row
    assert runtime.get_investigation(
        investigation.investigation_id
    ).status is AgentInvestigationStatus.active
    assert runtime.get_run(run.run_id).status is AgentRunStatus.running
    assert runtime.get_finalization(investigation.investigation_id) is None
    # and the finalization can be retried successfully afterwards
    record = _commit(runtime, investigation, revision, run=run)
    assert record.finalization_id.startswith("fz_")


def test_stale_state_revision_rejected_fail_closed(runtime):
    investigation, revision, run = _active_run(runtime)
    with pytest.raises(WorkingStateRevisionConflictError):
        runtime.record_finalization(
            investigation.investigation_id,
            run_id=run.run_id,
            state_revision=revision.revision + 5,
            state_hash=revision.state_hash,
            completion_mode="complete",
            question_dispositions={}, coverage_dispositions={},
            unresolved_contradictions=[], limitations=[],
            remaining_nonblocking_questions=[], pending_analyst_review_refs=[],
            final_verification_status="passed",
            finalization_policy_version=GATE.policy_version,
            input_hash="h",
        )
    assert runtime.get_investigation(
        investigation.investigation_id
    ).status is AgentInvestigationStatus.active


def test_legacy_v3_guard_still_skips_repository_owned_v9(tmp_path):
    """The legacy InvestigationPersistence must never touch a v9 store."""
    from httpserver.services.investigation_persistence import (
        InvestigationPersistence,
        UnsupportedSchemaVersion,
    )

    db = tmp_path / "investigation.db"
    InvestigationRepository(db, "A")
    # constructing the legacy layer on a repository-owned v9 store is a no-op
    persistence = InvestigationPersistence(db)
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SUPPORTED_SCHEMA_VERSION
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert "analyst_notes" not in tables  # legacy DDL did not run
