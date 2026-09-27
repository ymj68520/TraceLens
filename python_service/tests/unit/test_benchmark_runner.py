"""Benchmark runner / ablation / CLI / truth-leak tests (P8A §89, §97-§99)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from httpserver.services.benchmarks.availability import (
    resolve_reachability_record,
)
from httpserver.services.benchmarks.benchmark_case import (
    BenchmarkCaseV1,
    BenchmarkTier,
    DatasetFileRefV1,
    DatasetManifestV1,
)
from httpserver.services.benchmarks.runner import (
    AblationContractV1,
    AblationStage,
    BenchmarkRunner,
    ablation_configuration,
    evaluate_only,
)
from httpserver.services.benchmarks.run_manifest import (
    BenchmarkConfigurationV1,
    BenchmarkRunManifestV1,
    ModelIdentityV1,
)
from httpserver.services.benchmarks.snapshot import (
    BenchmarkRunSnapshotV1,
    SnapshotToolCallV1,
)
from httpserver.services.benchmarks.truth_manifest import (
    ReachabilityManifestV1,
    TruthManifestV1,
)

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "benchmark_agent_v0.py"
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _manifest() -> TruthManifestV1:
    def ev(eid):
        return {
            "truth_evidence_id": eid,
            "evidence_identity_description": eid,
            "criticality": "critical",
            "parser_expectation": "reachable",
        }

    return TruthManifestV1(
        case_id="case-smoke",
        case_version="1",
        critical_evidence=(ev("E1"), ev("E2")),
        expected_questions=(),
        confirmed_claims=(),
        acceptable_inferences=(),
        unsupported_or_prohibited_overclaims=(),
        expected_relations=(),
        expected_coverage=(),
    )


def _reachability(truth, discovered):
    records = []
    for item in truth.all_evidence_items():
        key = "key-" + item.truth_evidence_id
        found = key in discovered
        records.append(
            resolve_reachability_record(
                truth_evidence_id=item.truth_evidence_id,
                resolved_evidence_keys=(key,) if found else (),
                parser_reachable=True,
                agent_discoverable=found,
            )
        )
    return ReachabilityManifestV1(case_id=truth.case_id, records=records)


def _snapshot(discovered):
    return BenchmarkRunSnapshotV1(
        run_id="brun:x",
        task_id="task-1",
        investigation_id="inv-1",
        terminal_status="completed",
        discovered_evidence_refs=tuple(discovered),
        wall_ms_total=5_000,
    )


def _case(tmp_path, truth):
    dataset_file = tmp_path / "dataset" / "a.db"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_bytes(b"abcd")
    import hashlib

    return BenchmarkCaseV1(
        case_version="1",
        title="smoke",
        dataset=DatasetManifestV1(
            dataset_id="ds",
            files=(
                DatasetFileRefV1(
                    logical_id="a",
                    relative_path="a.db",
                    size_bytes=4,
                    sha256=hashlib.sha256(b"abcd").hexdigest(),
                ),
            ),
        ),
        truth_manifest_id=truth.manifest_id,
        truth_manifest_hash=truth.input_hash,
        goal="smoke goal",
        case_context="smoke",
        tier=BenchmarkTier.T1,
    )


# ---------------------------------------------------------------------------
# §24 ablation contract
# ---------------------------------------------------------------------------


def test_ablation_stages_cumulative_and_honest():
    a0 = ablation_configuration(AblationStage.A0_NON_AGENT_BASELINE)
    assert a0.agent_supervisor_enabled is False
    assert a0.model_provider == "none"
    a6 = ablation_configuration(AblationStage.A6_FULL_ARCHITECTURE)
    assert a6.semantic_verifier_enabled is True
    assert a6.graph_mode == "full"
    assert a6.report_enabled is True
    a5 = ablation_configuration(AblationStage.A5_SELECTIVE_GRAPH)
    assert a5.graph_mode == "selective"
    assert a5.report_enabled is False
    # each stage is a distinct frozen configuration with its own hash
    hashes = {
        ablation_configuration(stage).input_hash
        for stage in AblationStage
    }
    assert len(hashes) == len(list(AblationStage))


def test_ablation_contract_requires_graph_support_statement():
    contract = AblationContractV1(
        stages=(AblationStage.A0_NON_AGENT_BASELINE,)
    )
    assert (
        contract.graph_no_graph
        == "unsupported_historical_comparison"
    )


# ---------------------------------------------------------------------------
# §26/§57/§65 runner
# ---------------------------------------------------------------------------


def test_runner_full_pipeline_and_manifest_frozen_before_run():
    truth = _manifest()
    discovered = ("key-E1",)
    reachability = _reachability(truth, discovered)
    configuration = BenchmarkConfigurationV1(label="smoke")
    observed_order = []

    def executor(run_manifest):
        # the manifest was frozen (status running) BEFORE the executor ran
        observed_order.append(run_manifest.terminal_status)
        return {
            "snapshot": _snapshot(discovered).model_dump(mode="json")
        }

    runner = BenchmarkRunner(executor=executor, git_commit="936d3fbd")
    outcome = runner.run(
        case=_case(Path(__import__("tempfile").mkdtemp()), truth),
        truth_manifest=truth,
        reachability=reachability,
        configuration=configuration,
        model=ModelIdentityV1(provider="p", model_id="m"),
    )
    assert observed_order == ["running"]
    assert outcome["status"] == "completed"
    manifest = outcome["run_manifest"]
    assert manifest.terminal_status == "completed"
    assert manifest.completed_at
    result = outcome["result"]
    assert result.run_manifest_id == manifest.benchmark_run_id
    # availability is part of the result (§50)
    assert result.availability_summary["critical_ground_truth"] == 2


def test_failed_run_preserves_manifest_and_diagnostics():
    truth = _manifest()
    reachability = _reachability(truth, ())
    configuration = BenchmarkConfigurationV1(label="boom")

    def executor(run_manifest):
        raise RuntimeError("provider unavailable")

    runner = BenchmarkRunner(executor=executor)
    outcome = runner.run(
        case=_case(Path(__import__("tempfile").mkdtemp()), truth),
        truth_manifest=truth,
        reachability=reachability,
        configuration=configuration,
        model=ModelIdentityV1(provider="p", model_id="m"),
    )
    assert outcome["status"] == "failed"
    failure = outcome["failure"]
    assert failure.failure_layer == "RUNTIME"
    assert "provider unavailable" in failure.failure_reason
    # the frozen manifest is preserved (§65)
    assert failure.run_manifest["terminal_status"] == "failed"


# ---------------------------------------------------------------------------
# §84 evaluate-only reproducibility
# ---------------------------------------------------------------------------


def test_evaluate_only_reproduces_same_result_hash():
    truth = _manifest()
    reachability = _reachability(truth, ("key-E1", "key-E2"))
    manifest = BenchmarkRunManifestV1(
        case_id=truth.case_id,
        case_version="1",
        case_hash="c" * 64,
        dataset_hash="d" * 64,
        truth_manifest_id=truth.manifest_id,
        truth_manifest_hash=truth.input_hash,
        tracelens_git_commit="936d3fbd",
        model=ModelIdentityV1(provider="p", model_id="m"),
        configuration_id="bconf:1",
        configuration_hash="x" * 64,
    )
    snapshot = _snapshot(("key-E1", "key-E2"))
    result_a = evaluate_only(
        run_manifest=manifest,
        truth_manifest=truth,
        reachability=reachability,
        snapshot=snapshot,
    )
    result_b = evaluate_only(
        run_manifest=manifest,
        truth_manifest=truth,
        reachability=reachability,
        snapshot=snapshot,
    )
    assert result_a.result_hash == result_b.result_hash


# ---------------------------------------------------------------------------
# §85/§98 CLI
# ---------------------------------------------------------------------------


def _write_case_dir(tmp_path, truth):
    case = _case(tmp_path, truth)
    (tmp_path / "case.json").write_text(
        case.model_dump_json(), encoding="utf-8"
    )
    (tmp_path / "truth_manifest.json").write_text(
        truth.model_dump_json(), encoding="utf-8"
    )
    (tmp_path / "dataset").mkdir(exist_ok=True)
    (tmp_path / "dataset" / "a.db").write_bytes(b"abcd")
    return case


def test_cli_dry_run_no_llm_ok_and_fail(tmp_path):
    truth = _manifest()
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    _write_case_dir(case_dir, truth)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--case", str(case_dir), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "no model executed" in proc.stdout
    # corrupt the dataset -> dry-run fails without any model call
    (case_dir / "dataset" / "a.db").write_bytes(b"WRONG")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--case", str(case_dir), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1
    assert "mismatch" in proc.stdout  # size check fires before hash check


def test_cli_evaluate_only_reproducible(tmp_path):
    truth = _manifest()
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    _write_case_dir(case_dir, truth)
    reachability = _reachability(truth, ("key-E1", "key-E2"))
    (case_dir / "reachability.json").write_text(
        reachability.model_dump_json(), encoding="utf-8"
    )
    manifest = BenchmarkRunManifestV1(
        case_id=truth.case_id,
        case_version="1",
        case_hash="c" * 64,
        dataset_hash="d" * 64,
        truth_manifest_id=truth.manifest_id,
        truth_manifest_hash=truth.input_hash,
        tracelens_git_commit="936d3fbd",
        model=ModelIdentityV1(provider="p", model_id="m"),
        configuration_id="bconf:1",
        configuration_hash="x" * 64,
    )
    snapshot = _snapshot(("key-E1", "key-E2"))
    (case_dir / "run.manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )
    (case_dir / "run.snapshot.json").write_text(
        snapshot.model_dump_json(), encoding="utf-8"
    )
    out = tmp_path / "out"
    argv = [
        sys.executable,
        str(SCRIPT),
        "--case", str(case_dir),
        "--evaluate-only",
        "--snapshot", str(case_dir / "run.snapshot.json"),
        "--run-manifest", str(case_dir / "run.manifest.json"),
        "--output", str(out),
    ]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result_files = list(out.glob("*.result.json"))
    assert len(result_files) == 1
    result = json.loads(result_files[0].read_text(encoding="utf-8"))
    # second evaluate with an expected hash: reproducibility gate (§84)
    argv.append("--expect-result-hash")
    argv.append(result["result_hash"])
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# §55/§89 truth leakage
# ---------------------------------------------------------------------------


def test_tool_registry_cannot_access_truth_manifest():
    """§89: the production ToolRegistry has no truth path — its module
    source contains no reference to the benchmark oracle."""
    import inspect

    from httpserver.services.investigation.agent_tools import (
        registry as tool_registry,
    )

    source = inspect.getsource(tool_registry)
    assert "TruthManifest" not in source
    assert "truth_manifest" not in source
    assert "benchmarks" not in source


def test_report_context_pack_contains_no_benchmark_oracle():
    """§89: the frozen pack projection is pack-content only; no truth
    fields exist in the Writer input model."""
    from httpserver.services.report_runtime.report_chapter_writer import (
        build_writer_prompts,
    )
    from httpserver.services.report_runtime.report_chapter_generation import (
        build_starter_narrative_policy,
        ChapterGenerationInputV1,
    )
    from httpserver.services.report_runtime.report_context_pack import (
        FrozenReportContextPackV1,
        ReportEvidenceItemV1,
    )
    from httpserver.services.report_runtime.report_chapter import ChapterSpecV1
    from httpserver.services.report_runtime.report_retrieval import (
        ReportRetrievalPlanV1,
    )

    spec = ChapterSpecV1(
        chapter_id="c1",
        outline_id="o",
        outline_revision=1,
        outline_hash="h",
        title="T",
        generation_mode="deterministic",
        ordering=1,
    )
    plan = ReportRetrievalPlanV1(
        task_id="t",
        investigation_id="i",
        finalization_id="f",
        outline_id="o",
        outline_revision=1,
        chapter_id="c1",
        chapter_spec_hash=spec.input_hash,
        anchor_refs=("file:C/a.doc",),
    )
    pack = FrozenReportContextPackV1(
        task_id="t",
        investigation_id="i",
        finalization_id="f",
        finalization_record_hash="fh",
        outline_id="o",
        outline_revision=1,
        chapter_id="c1",
        chapter_spec_hash=spec.input_hash,
        retrieval_plan_id=plan.retrieval_plan_id,
        retrieval_plan_hash=plan.input_hash,
        generation_mode="deterministic",
        anchor_evidence=(
            ReportEvidenceItemV1(
                evidence_ref="file:C/a.doc",
                role="anchor",
                evidence_digest="d",
            ),
        ),
        hydration_policy_version="report-hydration-policy:v1",
        retrieval_policy_version="report-retrieval-policy:v1",
        dedup_policy_version="report-dedup-policy:v1",
        budget_policy_version="report-retrieval-budget:v1",
    )
    generation_input = ChapterGenerationInputV1(
        task_id="t",
        investigation_id="i",
        finalization_id="f",
        finalization_record_hash="fh",
        outline_id="o",
        outline_revision=1,
        chapter_id="c1",
        chapter_spec_hash=spec.input_hash,
        context_pack_id=pack.context_pack_id,
        context_pack_hash=pack.input_hash,
        retrieval_plan_id=plan.retrieval_plan_id,
        generation_mode="deterministic",
        narrative_policy=build_starter_narrative_policy(),
        prompt_version="chapter-writer:starter:v1",
    )
    system_prompt, user_prompt = build_writer_prompts(
        generation_input, pack
    )
    for oracle_marker in (
        "truth_evidence_id",
        "unsupported_or_prohibited_overclaims",
        "expected_questions",
        "truth_manifest",
        "acceptable_evidence_sets",
    ):
        assert oracle_marker not in system_prompt
        assert oracle_marker not in user_prompt


# ---------------------------------------------------------------------------
# §99 minimal E2E
# ---------------------------------------------------------------------------


def test_minimal_e2e_case_to_result():
    truth = _manifest()
    discovered = ("key-E1", "key-E2")
    reachability = _reachability(truth, discovered)
    configuration = BenchmarkConfigurationV1(label="e2e")
    import tempfile

    runner = BenchmarkRunner(
        executor=lambda manifest: {
            "snapshot": _snapshot(discovered).model_dump(mode="json")
        },
        git_commit="936d3fbd",
    )
    outcome = runner.run(
        case=_case(Path(tempfile.mkdtemp()), truth),
        truth_manifest=truth,
        reachability=reachability,
        configuration=configuration,
        model=ModelIdentityV1(provider="p", model_id="m"),
    )
    assert outcome["status"] == "completed"
    result = outcome["result"]
    assert result.availability_summary["critical_ground_truth"] == 2
    assert all(
        gate["passed"] for gate in result.hard_gate_results
    )
    assert result.cost_metrics["wall_ms_total"] == 5_000
    # determinism (§97): re-evaluating the SAME persisted manifest+snapshot
    # reproduces the exact result hash — independent runs may differ in
    # wall time, which is legitimately part of the cost metrics
    re_evaluated = evaluate_only(
        run_manifest=outcome["run_manifest"],
        truth_manifest=truth,
        reachability=reachability,
        snapshot=outcome["snapshot"],
    )
    assert re_evaluated.result_hash == result.result_hash
