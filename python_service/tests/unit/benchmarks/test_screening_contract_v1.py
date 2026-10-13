"""ScreeningContractV1 (RCA-1.8 §1/§2) — machine-verifiable contract tests.

The contract JSON is the normative source; these tests assert the
disposition script's behaviour matches it series by series, and that the
coded ceilings equal the contract's recorded values (including the
CONTRACT_UNRESOLVED run-axis provenance flag).

Zero model calls; synthetic series only.
"""

import json
import sys
from pathlib import Path

import pytest

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = PYTHON_SERVICE_ROOT / "scripts"
for p in (str(PYTHON_SERVICE_ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tests.unit.benchmarks.test_screening_disposition_regression import (  # noqa: E402
    REAL_CASES,
    SNAPSHOT_VERSION,
    _failed_run,
    _make_series,
    _run_disposition,
    _series,
    _terminal_run,
)

CONTRACT = json.loads(
    (PYTHON_SERVICE_ROOT
     / "benchmarks" / "audits" / "cross-model-root-cause-audit-v1"
     / "screening-contract-v1.json"
     ).read_text(encoding="utf-8"))

VOCABULARY = set(CONTRACT["disposition_vocabulary"])


def test_contract_gates_match_coded_constants():
    """The coded ceilings must equal the contract's recorded values."""
    import disposition_openrouter_8x1 as disp

    gates = {g["id"]: g for g in CONTRACT["gates"]}
    assert disp.RUN_AXIS_COLLAPSE_CEILING == gates["G6"]["ceiling"]
    assert disp.DELEGATION_AXIS_COLLAPSE_CEILING == gates["G5"]["ceiling"]
    # provenance honesty: the run-axis ceiling stays flagged, never
    # presented as historically frozen
    assert gates["G6"]["status"] == "CONTRACT_UNRESOLVED"
    assert gates["G5"]["status"] == "FROZEN"


def _expect_within_vocabulary(report):
    assert report["disposition"] in VOCABULARY
    return report["disposition"]


# ---------------------------------------------------------------------------
# §2 series matrix — each row: (name, spec builder, expected disposition)
# ---------------------------------------------------------------------------


def test_s1_all_terminal_clean_is_ready(tmp_path):
    """S1: 8/8 terminal, all gates pass, terminalization 100%."""
    qual = _series(tmp_path, [("terminal", {})] * 8)
    report = _run_disposition(qual)
    assert _expect_within_vocabulary(report) == "READY_FOR_8X3"
    assert report["question_terminalization"]["terminalized"] == 8


def test_s2_seven_terminal_one_timeout_not_ready(tmp_path):
    """S2: 7 terminal + 1 classified timeout — G8 blocks READY."""
    qual = _series(tmp_path, [("terminal", {})] * 7 + [("failed_timeout", {})])
    report = _run_disposition(qual)
    assert _expect_within_vocabulary(report) == "NOT_QUALIFIED_SCREENING"
    assert report["run_level_failure_classes"] == {
        "provider_request_timeout": 1}


def test_s3_two_terminal_six_timeouts_not_ready(tmp_path):
    """S3: the observed step-5-preview shape stays blocked."""
    qual = _series(tmp_path, [
        ("terminal", {}), ("terminal_open", {})] +
        [("failed_timeout", {})] * 6)
    report = _run_disposition(qual)
    assert _expect_within_vocabulary(report) == "NOT_QUALIFIED_SCREENING"
    assert "PROVIDER_REQUEST_TIMEOUT" in report["reason"]


def test_s4_all_terminal_partial_terminalization_still_ready(tmp_path):
    """S4 / CC-2 resolution (R4/M1): 8/8 terminal, gates clean,
    terminalization NOT 100% — READY remains reachable; the metric is
    reported independently."""
    spec = [("terminal", {})] * 4 + [("terminal_open", {})] * 4
    qual = _series(tmp_path, spec)
    report = _run_disposition(qual)
    assert _expect_within_vocabulary(report) == "READY_FOR_8X3"
    assert report["question_terminalization"]["terminalized"] == 4
    assert report["question_terminalization"]["total"] == 8
    assert report["accounting"]["run_failed_count"] == 0


def test_s5_schema_over_run_axis_ceiling_not_qualified(tmp_path):
    """S5 / G6: 5/8 output-retry failures = 62.5% > run-axis 0.5 ceiling
    (CONTRACT_UNRESOLVED provenance — value operative, not 'historically
    frozen')."""
    qual = _series(tmp_path, [
        ("terminal", {})] * 3 + [("failed_schema", {})] * 5)
    report = _run_disposition(qual)
    assert _expect_within_vocabulary(report) == "NOT_QUALIFIED_SCREENING"
    assert "systemic structured-output failure" in report["reason"]
    assert report["specialist_schema_reliability"]["run_axis_rate"] == 0.625
    assert report["specialist_schema_reliability"]["run_axis_ceiling"] == 0.5


def test_s6_structural_violation_not_qualified(tmp_path):
    """S6 / G1: a structural hard-gate violation on a terminal snapshot is
    zero-tolerance NOT_QUALIFIED_SCREENING (graph id surfaced as evidence
    ref trips no_graph_id_as_evidence)."""
    qual = _series(tmp_path, [("terminal", {})] * 8)
    # poison one terminal run's snapshot with a graph-id evidence ref
    run_dir = next(qual.glob("t*/repeat0"))
    snapshot = json.loads((run_dir / "snapshot.json").read_text())
    snapshot["discovered_evidence_refs"] = ["graph:fake-episode-1"]
    (run_dir / "snapshot.json").write_text(json.dumps(snapshot))
    report = _run_disposition(qual)
    assert _expect_within_vocabulary(report) == "NOT_QUALIFIED_SCREENING"
    assert "structural hard gate violation" in report["reason"]


def test_s7_unclassified_failure_review_required(tmp_path):
    """S7 / G9: unclassified runtime failures can never enter READY."""
    qual = _series(tmp_path, [
        ("terminal", {})] * 3 + [("failed_other", {"reason": "boom"})] * 5)
    report = _run_disposition(qual)
    assert _expect_within_vocabulary(report) == "REVIEW_REQUIRED"


def test_s8_failed_runs_accounted_without_result_json(tmp_path):
    """S8 / R2: failed runs carry failure.json and NO result.json; they are
    counted in run_failed_count and never in snapshot reproduction."""
    qual = _series(tmp_path, [
        ("terminal", {})] * 4 + [("failed_timeout", {})] * 4)
    for run_dir in qual.glob("t*/repeat0"):
        if (run_dir / "failure.json").is_file():
            assert not (run_dir / "result.json").is_file()
            assert (run_dir / "failure.json").is_file()
    report = _run_disposition(qual)
    acc = report["accounting"]
    assert acc["scheduled_count"] == 8
    assert acc["run_terminal_count"] == 4
    assert acc["run_failed_count"] == 4
    assert acc["snapshot_reproduced_count"] == 4
    assert acc["failure_classified_count"] == 4
    assert _expect_within_vocabulary(report) == "NOT_QUALIFIED_SCREENING"
