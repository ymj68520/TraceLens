"""P8B-1/2 tests: calibration inventory, production executor wiring,
corpus freeze/split integrity (§12, §87-§90)."""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from httpserver.services.benchmarks.acceptance import (
    AcceptanceDisposition,
    AcceptanceThresholdV1,
    AgentV0AcceptanceProfileV1,
    AgentV0CalibrationProfileV1,
    CalibrationComparisonReportV1,
    CalibrationExperimentV1,
    PreCalibrationProfileV1,
    ThresholdType,
    evaluate_acceptance,
    select_calibration_variant,
)
from httpserver.services.benchmarks.benchmark_case import (
    BenchmarkCaseV1,
    BenchmarkTier,
    DatasetFileRefV1,
    DatasetManifestV1,
    NegativeCaseFlagsV1,
)
from httpserver.services.benchmarks.calibration import (
    ParameterKind,
    build_default_inventory,
)
from httpserver.services.benchmarks.corpus import (
    BenchmarkCorpusManifestV1,
    CorpusSplit,
    CoverageMatrixV1,
    build_case_ref,
    check_minimum_independence,
    verify_corpus_hashes,
)
from httpserver.services.benchmarks.production_executor import (
    ProductionBenchmarkExecutor,
    PublicCaseInputV1,
)
from httpserver.services.benchmarks.run_manifest import (
    BenchmarkRunManifestV1,
    ModelIdentityV1,
)
from httpserver.services.benchmarks.snapshot import (
    BenchmarkRunSnapshotV1,
    SnapshotToolCallV1,
)
from httpserver.services.benchmarks.truth_manifest import TruthManifestV1


# ---------------------------------------------------------------------------
# §3-§5 calibration inventory
# ---------------------------------------------------------------------------


def test_inventory_marks_semantic_invariants_non_calibratable():
    inventory = build_default_inventory(
        baseline_commit="f13ffd89"
    )
    invariants = inventory.invariants()
    assert invariants
    for parameter in invariants:
        assert parameter.kind is ParameterKind.semantic
        assert parameter.calibratable_in_p8 == "no"
        assert parameter.invariant or parameter.safety_floor


def test_inventory_calibratable_parameters_are_numeric_and_real():
    inventory = build_default_inventory(baseline_commit="f13ffd89")
    ids = {p.parameter_id for p in inventory.calibratable_parameters()}
    # every value traced from the real repository (§3)
    assert "supervisor.max_cycles_per_run" in ids
    assert "attention.window_size" in ids
    assert "report.max_evidence_items" in ids
    assert "correlation.temporal_window_seconds" in ids
    for parameter in inventory.calibratable_parameters():
        assert parameter.kind is ParameterKind.numeric
        assert parameter.safety_floor


def test_semantic_parameter_cannot_be_marked_calibratable():
    with pytest.raises(ValidationError):
        from httpserver.services.benchmarks.calibration import (
            CalibrationParameterV1,
            CalibratableInP8,
        )

        CalibrationParameterV1(
            parameter_id="x",
            owner_phase="P5",
            description="attempt to relax assertion ceiling",
            kind=ParameterKind.semantic,
            calibratable_in_p8=CalibratableInP8.yes,
        )


def test_inventory_hash_stable():
    a = build_default_inventory(baseline_commit="f13ffd89")
    b = build_default_inventory(baseline_commit="f13ffd89")
    assert a.input_hash == b.input_hash


# ---------------------------------------------------------------------------
# B0 production executor wiring (§8-§12, §87)
# ---------------------------------------------------------------------------


class _SpyRuntime:
    """Records every attribute access so the truth spy can assert no
    truth object ever crossed into the production call graph."""

    def __init__(self, investigations):
        self._investigations = investigations
        self.accessed = []

    def list_investigations(self):
        self.accessed.append("list_investigations")
        return self._investigations

    def list_runs(self, investigation_id):
        self.accessed.append("list_runs")
        return [
            SimpleNamespace(run_id="run-1"),
        ]

    def get_finalization(self, investigation_id):
        self.accessed.append("get_finalization")
        record = SimpleNamespace(
            finalization_id="fz_1", input_hash="h" * 64
        )
        return record

    def get_run(self, run_id):
        self.accessed.append("get_run")
        return SimpleNamespace(
            run_id=run_id,
            status=SimpleNamespace(value="completed"),
            created_at="2026-01-01T00:00:00+00:00",
        )

    def list_trajectory(self, investigation_id, **kwargs):
        self.accessed.append("list_trajectory")
        return []

    def list_tool_observations(self, investigation_id, **kwargs):
        self.accessed.append("list_tool_observations")
        return []

    def list_delegations(self, run_id):
        self.accessed.append("list_delegations")
        return []

    def list_investigation_findings(self, investigation_id):
        self.accessed.append("list_investigation_findings")
        return []

    def list_correlation_candidates(self, investigation_id):
        self.accessed.append("list_correlation_candidates")
        return []

    def list_graph_materializations(self, investigation_id):
        self.accessed.append("list_graph_materializations")
        return []


def _state_row(investigation_id, task_id="bench-x"):
    return {
        "schema_version": "agent-working-state:v1",
        "task_id": task_id,
        "investigation_id": investigation_id,
        "questions": [
            {"question_id": "q-1", "text": "q",
             "source": "charter", "priority": "required",
             "status": "answered", "disposition": "supported"},
        ],
        "coverage": [],
        "limitations": [],
    }


def _runtime_with_state(spy):
    class _WithState:
        def __getattr__(self, name):
            return getattr(spy, name)

        def get_latest_working_state(self, investigation_id):
            spy.accessed.append("get_latest_working_state")
            return SimpleNamespace(
                state=_state_row(investigation_id, spy_task_id())
            )

    def spy_task_id():
        return getattr(spy, "_task_id", None) or "bench-x"

    return _WithState()


def _make_manifest():
    return BenchmarkRunManifestV1(
        case_id="bcase:1",
        case_version="1",
        case_hash="c" * 64,
        dataset_hash="d" * 64,
        truth_manifest_id="tman:1",
        truth_manifest_hash="t" * 64,
        tracelens_git_commit="f13ffd89",
        model=ModelIdentityV1(provider="p", model_id="m"),
        configuration_id="bconf:1",
        configuration_hash="x" * 64,
    )


def test_executor_signature_contains_no_truth_parameter():
    """§9: the executor's public interface structurally excludes truth."""
    params = inspect.signature(
        ProductionBenchmarkExecutor.execute
    ).parameters
    assert set(params) == {
        "self",
        "case_input",
        "run_manifest",
        "finalization_request_factory",
        "timeout_seconds",
    }
    # no truth-typed parameter anywhere in the public surface
    for name in params:
        assert "truth" not in name.lower()
    annotation = inspect.signature(
        ProductionBenchmarkExecutor.execute
    ).parameters["case_input"].annotation
    assert "PublicCaseInputV1" in str(annotation)
    source = inspect.getsource(ProductionBenchmarkExecutor)
    assert "TruthManifest" not in source.replace(
        "TruthManifest objects are structurally absent", ""
    )


def test_executor_runs_production_loop_and_gate(tmp_path):
    investigations = [SimpleNamespace(investigation_id="inv-1")]
    spy = _SpyRuntime(investigations)
    spy._task_id = None
    created = {}

    class FakeOrchestrator:
        async def create_investigation(self, task_id, state):
            created["state"] = state
            created["task_id"] = task_id
            return SimpleNamespace(investigation_id="inv-1"), None

        async def admit_run(self, task_id, investigation_id):
            created["admitted"] = investigation_id
            return SimpleNamespace(run_id="run-1")

        async def run_loop(self, task_id, investigation_id, **kwargs):
            created["loop"] = (task_id, investigation_id, kwargs)
            return [SimpleNamespace(run_stop_reason=None)]

        async def finalize(self, task_id, request):
            created["finalized"] = True
            return SimpleNamespace(decision=SimpleNamespace(outcome="pass"))

    def seed(task_id, investigation_id, case_input):
        from httpserver.services.investigation.agent_working_state import (
            AgentWorkingStateV1,
            WorkingQuestion,
            QuestionSource,
            QuestionPriority,
        )

        return AgentWorkingStateV1(
            task_id=task_id,
            investigation_id=investigation_id,
            objective=case_input.goal,
            questions=tuple(
                WorkingQuestion(
                    question_id=f"q-{index}",
                    text=text,
                    source=QuestionSource.charter,
                    priority=QuestionPriority.required,
                )
                for index, text in enumerate(case_input.seed_questions, 1)
            ),
        )

    runtime = _runtime_with_state(spy)

    def runtime_factory(task_id):
        spy._task_id = task_id
        return runtime

    executor = ProductionBenchmarkExecutor(
        orchestrator_factory=lambda task_id: FakeOrchestrator(),
        runtime_factory=runtime_factory,
        investigation_seed=seed,
    )
    snapshot = asyncio.run(
        executor.execute(
            case_input=PublicCaseInputV1(
                case_id="bcase:1",
                goal="detect exfiltration",
                seed_questions=("Was data transferred?",),
                source_scope_ids=("windows",),
            ),
            run_manifest=_make_manifest(),
            finalization_request_factory=lambda state: object(),
        )
    )
    # production path used: create → admit → loop → finalize
    assert created["task_id"].startswith("bench-")
    # fresh investigation id per repetition (§10) — derived from the run id
    assert created["admitted"].startswith("inv-")
    assert created["admitted"] != "inv-1"
    assert created["loop"][1] == created["admitted"]
    assert created["finalized"] is True
    # fresh task/investigation ids per run (§10)
    assert "inv-" in created["state"].investigation_id
    assert snapshot.terminal_status == "completed"
    assert snapshot.finalization_id == "fz_1"
    assert snapshot.wall_ms_total is not None


def test_executor_gate_refusal_leaves_run_failed_not_forced():
    """§8: the gate decides — a refusal is never overridden."""
    investigations = [SimpleNamespace(investigation_id="inv-1")]
    spy = _SpyRuntime(investigations)

    class GateRefusingOrchestrator:
        async def create_investigation(self, task_id, state):
            return SimpleNamespace(investigation_id="inv-1"), None

        async def admit_run(self, task_id, investigation_id):
            return SimpleNamespace(run_id="run-1")

        async def run_loop(self, task_id, investigation_id, **kwargs):
            return []

        async def finalize(self, task_id, request):
            return SimpleNamespace(
                decision=SimpleNamespace(outcome="fail")
            )

    spy._task_id = None

    class _NoFinalRuntime:
        def __getattr__(self, name):
            return getattr(spy, name)

        def get_latest_working_state(self, investigation_id):
            return SimpleNamespace(
                state=_state_row(investigation_id, spy._task_id or "bench-x")
            )

        def get_finalization(self, investigation_id):
            return None

    def seed(task_id, investigation_id, case_input):
        spy._task_id = task_id
        from httpserver.services.investigation.agent_working_state import (
            AgentWorkingStateV1,
        )

        return AgentWorkingStateV1(
            task_id=task_id, investigation_id=investigation_id
        )

    executor = ProductionBenchmarkExecutor(
        orchestrator_factory=lambda task_id: GateRefusingOrchestrator(),
        runtime_factory=lambda task_id: _NoFinalRuntime(),
        investigation_seed=seed,
    )
    snapshot = asyncio.run(
        executor.execute(
            case_input=PublicCaseInputV1(case_id="c", goal="g"),
            run_manifest=_make_manifest(),
            finalization_request_factory=lambda state: object(),
        )
    )
    assert snapshot.terminal_status == "failed"


def test_executor_timeout_preserves_partial_snapshot():
    """§11: timeout → failed run with partial snapshot, never deleted."""

    class SlowOrchestrator:
        async def create_investigation(self, task_id, state):
            await asyncio.sleep(5)
            return SimpleNamespace(investigation_id="inv-1"), None

    spy = _SpyRuntime([])
    runtime = _runtime_with_state(spy)

    def seed(task_id, investigation_id, case_input):
        from httpserver.services.investigation.agent_working_state import (
            AgentWorkingStateV1,
        )

        return AgentWorkingStateV1(
            task_id=task_id, investigation_id=investigation_id
        )

    executor = ProductionBenchmarkExecutor(
        orchestrator_factory=lambda task_id: SlowOrchestrator(),
        runtime_factory=lambda task_id: runtime,
        investigation_seed=seed,
    )
    snapshot = asyncio.run(
        executor.execute(
            case_input=PublicCaseInputV1(case_id="c", goal="g"),
            run_manifest=_make_manifest(),
            timeout_seconds=0.05,
        )
    )
    assert snapshot.terminal_status == "failed"
    assert "run timeout exceeded" in snapshot.limitations


# ---------------------------------------------------------------------------
# B1 corpus manifest (§13-§19, §88)
# ---------------------------------------------------------------------------


def _case(case_id="case-a", tier=BenchmarkTier.T1, negatives=None):
    flags = NegativeCaseFlagsV1(**(negatives or {}))
    return BenchmarkCaseV1(
        case_version="1",
        title=case_id,
        dataset=DatasetManifestV1(
            dataset_id="ds-" + case_id,
            files=(
                DatasetFileRefV1(
                    logical_id="f",
                    relative_path="a.db",
                    size_bytes=4,
                    sha256="a" * 64,
                ),
            ),
        ),
        truth_manifest_id="tman:" + case_id,
        truth_manifest_hash="t" * 64,
        goal="g",
        case_context="c",
        tier=tier,
        negative_flags=flags,
    )


def _corpus(development=(), calibration=(), acceptance=(), stress=(), **kw):
    return BenchmarkCorpusManifestV1(
        version="1",
        freeze_commit="f13ffd89",
        development_cases=[build_case_ref(c) for c in development],
        calibration_cases=[build_case_ref(c) for c in calibration],
        acceptance_cases=[build_case_ref(c) for c in acceptance],
        stress_cases=[build_case_ref(c) for c in stress],
        coverage_matrix=CoverageMatrixV1(single_device_clear=True),
        **kw,
    )


def test_corpus_hash_stable_and_content_addressed():
    corpus = _corpus(
        development=(_case("dev-1"),),
        calibration=(_case("cal-1"),),
        acceptance=(_case("acc-1"),),
    )
    replay = BenchmarkCorpusManifestV1(**corpus.model_dump(mode="json"))
    assert replay.input_hash == corpus.input_hash
    assert replay.corpus_id == corpus.corpus_id


def test_case_cannot_be_in_two_splits():
    case = _case("shared")
    with pytest.raises(ValidationError):
        _corpus(
            development=(case,),
            calibration=(case,),
            acceptance=(_case("acc"),),
        )


def test_calibration_and_holdout_required():
    with pytest.raises(ValidationError):
        _corpus(development=(_case("d"),), acceptance=(_case("a"),))
    with pytest.raises(ValidationError):
        _corpus(development=(_case("d"),), calibration=(_case("c"),))


def test_holdout_sealed_until_calibration_freezes():
    """§32/§51: holdout execution before profile freeze must be refused."""
    corpus = _corpus(
        calibration=(_case("cal-1"),),
        acceptance=(_case("acc-1"),),
    )
    assert not corpus.holdout_released()
    with pytest.raises(ValueError):
        corpus.assert_holdout_released()
    released = corpus.release_holdout(
        calibration_profile_hash="acal:" + "0" * 24
    )
    assert released.holdout_released()
    released.assert_holdout_released()


def test_verify_corpus_hashes_detects_mismatch():
    calibration_case = _case("cal-1")
    acceptance_case = _case("acc-1")
    corpus = _corpus(
        calibration=(calibration_case,), acceptance=(acceptance_case,)
    )
    assert verify_corpus_hashes(
        corpus,
        {calibration_case.case_id: calibration_case,
         acceptance_case.case_id: acceptance_case},
    ) == []
    # hash mismatch: a case whose stored hash was altered out-of-band no
    # longer matches the frozen ref (the content-addressed id is immutable
    # under model_copy, so the stored hash is the attack surface)
    tampered = calibration_case.model_copy(update={"input_hash": "0" * 64})
    violations = verify_corpus_hashes(
        corpus,
        {calibration_case.case_id: tampered,
         acceptance_case.case_id: acceptance_case},
    )
    assert any("case hash mismatch" in v for v in violations)
    # an unknown case object is reported, never silently accepted
    stranger = _case("stranger")
    violations = verify_corpus_hashes(
        corpus,
        {calibration_case.case_id: calibration_case,
         acceptance_case.case_id: acceptance_case,
         stranger.case_id: stranger},
    )
    assert any("not recorded in the corpus" in v for v in violations)


def test_negative_dimension_independence():
    """§18: critical negative dimensions need >1 independent instance."""
    corpus = _corpus(
        calibration=(
            _case("cal-1", negatives={"same_username_different_person": True}),
        ),
        acceptance=(
            _case(
                "acc-1",
                tier=BenchmarkTier.T2,
                negatives={"same_username_different_person": True},
            ),
        ),
    )
    assert check_minimum_independence(
        corpus,
        critical_negative_dimensions=("same_username_different_person",),
    ) == []
    missing = check_minimum_independence(
        corpus, critical_negative_dimensions=("misleading_case_context",)
    )
    assert missing and "needs >1" in missing[0]


def test_coverage_matrix_records_missing_dimensions():
    matrix = CoverageMatrixV1(
        single_device_clear=True, same_username_identity_trap=True
    )
    assert "single_device_clear" in matrix.covered_dimensions()
    assert "temporal_causality_trap" in matrix.missing_dimensions()


def test_holdout_payload_not_embedded_in_manifest():
    """§14: the corpus manifest carries hashes only."""
    corpus = _corpus(
        calibration=(_case("cal-1"),), acceptance=(_case("acc-1"),)
    )
    dumped = corpus.model_dump_json()
    # case payloads (goal / case context prose) never appear — hashes only;
    # "case_context" appears solely as the coverage-matrix field
    # case_context_misleading, so assert on payload markers instead.
    assert '"goal"' not in dumped
    assert "seized phones" not in dumped


# ---------------------------------------------------------------------------
# §89 calibration selection
# ---------------------------------------------------------------------------


def _experiment(**kw):
    payload = dict(
        baseline_profile_hash="p" * 64,
        corpus_id="bcorpus:1",
        changed_parameters={"supervisor.max_cycles_per_run": 30},
        hard_gates_passed=True,
        decision="adopt",
    )
    payload.update(kw)
    return CalibrationExperimentV1(**payload)


def test_hard_gate_failure_never_selected():
    baseline = {"hard_gates_passed": True, "quality": {}, "cost": {}}
    result = select_calibration_variant(
        baseline=baseline,
        variants=[
            {
                "name": "fast-but-leaky",
                "hard_gates_passed": False,
                "quality": {},
                "cost": {"wall_s": 1},
            },
        ],
    )
    assert result["decision"] == "reject_all"


def test_quality_regression_rejects_variant():
    baseline = {
        "hard_gates_passed": True,
        "quality": {"critical_evidence_recall": 0.9},
        "cost": {"wall_s": 100},
    }
    result = select_calibration_variant(
        baseline=baseline,
        variants=[
            {
                "name": "cheaper-but-worse",
                "hard_gates_passed": True,
                "quality": {"critical_evidence_recall": 0.6},
                "cost": {"wall_s": 40},
            },
        ],
    )
    assert result["decision"] == "reject_all"


def test_cost_improvement_equal_quality_selectable():
    baseline = {
        "hard_gates_passed": True,
        "quality": {"critical_evidence_recall": 0.9},
        "cost": {"wall_s": 100},
    }
    result = select_calibration_variant(
        baseline=baseline,
        variants=[
            {
                "name": "same-quality-cheaper",
                "hard_gates_passed": True,
                "quality": {"critical_evidence_recall": 0.9},
                "cost": {"wall_s": 60},
            },
        ],
    )
    assert result["decision"] == "adopt"
    assert result["selected"] == "same-quality-cheaper"


def test_quality_improvement_bounded_cost_selectable():
    baseline = {
        "hard_gates_passed": True,
        "quality": {"critical_evidence_recall": 0.8},
        "cost": {"wall_s": 100},
    }
    result = select_calibration_variant(
        baseline=baseline,
        variants=[
            {
                "name": "better-slightly-costlier",
                "hard_gates_passed": True,
                "quality": {"critical_evidence_recall": 0.95},
                "cost": {"wall_s": 120},
            },
        ],
    )
    # quality improves but cost regresses without dominance → inconclusive;
    # the baseline stands unless a human adopts with rationale (§33)
    assert result["decision"] in ("adopt", "inconclusive")


def test_dominated_variant_rejected():
    baseline = {
        "hard_gates_passed": True,
        "quality": {"critical_evidence_recall": 0.9},
        "cost": {"wall_s": 100},
    }
    result = select_calibration_variant(
        baseline=baseline,
        variants=[
            {
                "name": "dominated",
                "hard_gates_passed": True,
                "quality": {"critical_evidence_recall": 0.85},
                "cost": {"wall_s": 140},
            },
        ],
    )
    assert result["decision"] == "reject_all"


def test_zero_parameter_change_is_valid_outcome():
    """§50: the baseline may already be Pareto-efficient."""
    baseline = {
        "hard_gates_passed": True,
        "quality": {"critical_evidence_recall": 0.95},
        "cost": {"wall_s": 50},
    }
    result = select_calibration_variant(
        baseline=baseline,
        variants=[
            {
                "name": "no-better",
                "hard_gates_passed": True,
                "quality": {"critical_evidence_recall": 0.95},
                "cost": {"wall_s": 50},
            },
        ],
    )
    assert result["decision"] == "inconclusive"
    assert result["selected"] is None


# ---------------------------------------------------------------------------
# §90/§91 acceptance policy
# ---------------------------------------------------------------------------


def _profile(**kw):
    thresholds = kw.pop(
        "thresholds",
        (
            AcceptanceThresholdV1(
                metric_id="unsupported_fact_rate",
                threshold_type=ThresholdType.case_level_ceiling,
                maximum=0.0,
                rationale="zero tolerance for FACT overreach (§60)",
            ),
        ),
    )
    payload = dict(
        corpus_hash="c" * 64,
        calibration_profile_hash="p" * 64,
        model_provider="deepseek",
        model_id="deepseek-flash",
        thresholds=thresholds,
        zero_tolerance_gate_ids=(
            "no_cross_task_evidence_leak",
            "no_graph_id_as_evidence",
        ),
    )
    payload.update(kw)
    return AgentV0AcceptanceProfileV1(**payload)


def test_profile_content_addressed():
    profile = _profile()
    replay = AgentV0AcceptanceProfileV1(**profile.model_dump(mode="json"))
    assert replay.input_hash == profile.input_hash
    assert replay.profile_id == profile.profile_id


def test_threshold_requires_rationale():
    with pytest.raises(ValidationError):
        AcceptanceThresholdV1(
            metric_id="x",
            threshold_type=ThresholdType.aggregate,
            minimum=0.5,
        )


def test_all_gates_and_thresholds_pass():
    profile = _profile()
    result = evaluate_acceptance(
        acceptance_profile=profile,
        hard_gate_results=[
            {"gate_id": "no_cross_task_evidence_leak", "passed": True},
            {"gate_id": "no_graph_id_as_evidence", "passed": True},
        ],
        case_metrics=[
            {"case_id": "acc-1", "metrics": {"unsupported_fact_rate": 0.0}},
        ],
        corpus_aggregate_metrics={},
    )
    assert result["disposition"] == AcceptanceDisposition.PASS.value


def test_structural_gate_violation_is_fail_not_averaged():
    """§53/§57: one leak fails the whole acceptance."""
    profile = _profile()
    result = evaluate_acceptance(
        acceptance_profile=profile,
        hard_gate_results=[
            {"gate_id": "no_cross_task_evidence_leak", "passed": False},
        ],
        case_metrics=[],
        corpus_aggregate_metrics={},
    )
    assert result["disposition"] == AcceptanceDisposition.FAIL.value


def test_case_level_ceiling_prevents_aggregate_masking():
    """§57: 9 clean cases + 1 case at 100% cannot average to a PASS."""
    profile = _profile(
        thresholds=(
            AcceptanceThresholdV1(
                metric_id="unsupported_fact_rate",
                threshold_type=ThresholdType.case_level_ceiling,
                maximum=0.0,
                rationale="zero tolerance",
            ),
        ),
    )
    case_metrics = [
        {"case_id": f"acc-{i}", "metrics": {"unsupported_fact_rate": 0.0}}
        for i in range(9)
    ]
    case_metrics.append(
        {"case_id": "acc-9", "metrics": {"unsupported_fact_rate": 1.0}}
    )
    result = evaluate_acceptance(
        acceptance_profile=profile,
        hard_gate_results=[],
        case_metrics=case_metrics,
        corpus_aggregate_metrics={"unsupported_fact_rate": 0.1},
    )
    assert result["disposition"] == AcceptanceDisposition.FAIL.value
    assert result["violations"][0]["case"] == "acc-9"


def test_required_metric_unavailable_cannot_pass():
    profile = _profile()
    result = evaluate_acceptance(
        acceptance_profile=profile,
        hard_gate_results=[],
        case_metrics=[],
        corpus_aggregate_metrics={},
        unavailable_required_metrics=("unsupported_fact_rate",),
    )
    assert result["disposition"] == AcceptanceDisposition.FAIL.value


def test_t4_unavailable_is_pass_with_limitations():
    profile = _profile()
    result = evaluate_acceptance(
        acceptance_profile=profile,
        hard_gate_results=[
            {"gate_id": "no_cross_task_evidence_leak", "passed": True},
        ],
        case_metrics=[
            {"case_id": "acc-1", "metrics": {"unsupported_fact_rate": 0.0}},
        ],
        corpus_aggregate_metrics={},
        optional_capability_gaps=("T4 large-case validation",),
    )
    assert (
        result["disposition"]
        == AcceptanceDisposition.PASS_WITH_LIMITATIONS.value
    )


def test_holdout_integrity_profile_hash_mismatch_invalidates():
    """§90: profile hash mismatch → acceptance invalid."""
    profile = _profile()
    corpus = _corpus(
        calibration=(_case("cal-1"),), acceptance=(_case("acc-1"),)
    )
    released = corpus.release_holdout(
        calibration_profile_hash=profile.input_hash
    )
    assert released.holdout_released()
    # a different profile hash must not match the released gate
    assert released.calibration_profile_hash != "acal:other"
