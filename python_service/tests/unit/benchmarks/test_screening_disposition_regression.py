"""CrossModelFailureRootCauseAuditV1 §8/§12 — screening disposition contract
regression tests (deterministic, zero model calls).

Pins the 8x1 screening disposition contract on synthetic series fixtures:

- a timeout-dominant series (the observed step-5-preview shape) must NEVER
  be disposed READY_FOR_8X3 — currently it IS (the automated decision tree
  has no RUNTIME_FAILURE_UNATTRIBUTED / terminalization branch), so the
  required-behaviour test is xfail(strict) until the authorized fix lands;
- the branches that do exist (schema-dominant, quota-dominant, identity
  mismatch, fully clean) are anchored so a fix cannot regress them;
- failed-run accounting: scheduled vs terminal vs evaluate-only coverage
  must stay visible in the report (§9 evaluate-only completeness).
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

from disposition_openrouter_8x1 import main as disposition_main  # noqa: E402

REQUESTED_MODEL = "synthetic-model-a"
REAL_CASES = [
    "t2-identity-trap",
    "t2-verification-temptation",
    "t2-temporal-trap",
    "t2-no-evidence",
    "t2-misleading-note",
    "t2-report-citation",
    "t2-cross-source-correlation",
    "t1-fraud-script-usb",
]

SNAPSHOT_VERSION = "benchmark-run-snapshot:v1"


def _terminal_run(run_dir: Path, case_id: str, *, charter_status: str = "answered",
                  quota_digest: bool = False,
                  integration_failure: dict | None = None):
    snapshot = {
        "snapshot_version": SNAPSHOT_VERSION,
        "run_id": f"brun:{case_id}",
        "task_id": f"task-{case_id}",
        "investigation_id": "inv-audit",
        "terminal_status": "completed",
        "questions": (
            {"question_id": "q-1", "status": charter_status,
             "disposition": "supported" if charter_status == "answered" else None},
        ),
        "coverage": (),
        "created_at": "2026-10-13T00:00:00+00:00",
    }
    (run_dir / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    result = {
        "run_manifest_id": f"brun:{case_id}",
        "run_manifest_hash": "h",
        "truth_manifest_id": "tman",
        "truth_manifest_hash": "h",
        "snapshot_hash": "h",
        "availability_summary": {},
        "hard_gate_results": [],
        "cost_metrics": {"wall_ms_total": 1, "usage_entries": []},
        "reliability_metadata": {},
    }
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    digest: dict = {"rejections": [], "supervisor_failures": [],
                    "delegation_failures": [], "completions": []}
    if quota_digest:
        digest["delegation_failures"] = [
            {"failure_code": "agent_rate_limited"}]
    if integration_failure is not None:
        digest["supervisor_failures"] = [integration_failure]
    (run_dir / "trajectory_digest.json").write_text(
        json.dumps(digest), encoding="utf-8")


def _failed_run(run_dir: Path, reason: str, *, quota_digest: bool = False):
    (run_dir / "failure.json").write_text(
        json.dumps({"failure_layer": "RUNTIME", "failure_reason": reason}),
        encoding="utf-8")
    digest: dict = {"rejections": [], "supervisor_failures": [],
                    "delegation_failures": [], "completions": []}
    if quota_digest:
        digest["delegation_failures"] = [
            {"failure_code": "agent_rate_limited"}]
    (run_dir / "trajectory_digest.json").write_text(
        json.dumps(digest), encoding="utf-8")


def _make_series(root: Path, spec: list[tuple[str, dict]]) -> Path:
    """spec: list of (kind, kwargs); kind in {terminal_open, terminal,
    failed_timeout, failed_schema, failed_other, failed_quota_digest}."""
    for i, (kind, kwargs) in enumerate(spec):
        case = REAL_CASES[i % len(REAL_CASES)]
        repeat = f"repeat{i // len(REAL_CASES)}"
        run_dir = root / case / repeat
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "identity_telemetry.json").write_text(
            json.dumps([{"requested_model": REQUESTED_MODEL,
                         "returned_model": kwargs.get(
                             "returned_model", REQUESTED_MODEL)}]),
            encoding="utf-8")
        if kind.startswith("terminal"):
            charter = "open" if kind == "terminal_open" else "answered"
            _terminal_run(run_dir, case, charter_status=charter,
                          quota_digest=(kind == "terminal_quota_digest"),
                          integration_failure=(
                              {"code": "supervisor_integration_failed",
                               "stage": "integrate",
                               "underlying_code": "provider_request_timeout"}
                              if kind == "terminal_integrate_failed" else None))
        elif kind == "failed_timeout":
            _failed_run(run_dir, "Request timed out.")
        elif kind == "failed_schema":
            _failed_run(run_dir, "Exceeded maximum output retries (1)")
        elif kind == "failed_quota_digest":
            _failed_run(run_dir, "worker exhausted", quota_digest=True)
        else:
            _failed_run(run_dir, kwargs.get("reason", "boom"))
    (root.parent / "candidate-config.json").write_text(
        json.dumps({"config_hash": "audit0"}), encoding="utf-8")
    return root


def _run_disposition(qual_root: Path) -> dict:
    import sys as _sys

    argv = _sys.argv
    _sys.argv = [
        "disposition_openrouter_8x1",
        "--results-root", str(qual_root),
        "--candidate-config", str(qual_root.parent / "candidate-config.json"),
        "--requested-model", REQUESTED_MODEL,
        "--candidate-id", "synthetic@audit",
        "--artifact-version", "AuditSyntheticSeriesV1",
    ]
    try:
        assert disposition_main() == 0
    finally:
        _sys.argv = argv
    return json.loads(
        (qual_root / "screening-report.json").read_text(encoding="utf-8"))


def _series(tmp_path, spec):
    root = tmp_path / "candidate" / "qual-8x1"
    root.mkdir(parents=True)
    return _make_series(root, spec)


def test_timeout_dominant_series_must_not_be_ready_for_8x3(tmp_path):
    """The observed step-5-preview shape: 2 terminal (1 answered, 1 open)
    + 6 request timeouts. RCA-1.5 fix: classified PROVIDER_REQUEST_TIMEOUT
    failures block READY with their class-specific reason — the fallback
    branch can no longer produce READY_FOR_8X3. (Was xfail-pinned as
    BENCHMARK_DISPOSITION_DEFECT; converted to a PASS regression by RCA-1.)"""
    qual = _series(tmp_path, [
        ("terminal", {}), ("terminal_open", {})] +
        [("failed_timeout", {})] * 6)
    report = _run_disposition(qual)
    assert report["disposition"] == "NOT_QUALIFIED_SCREENING"
    assert "PROVIDER_REQUEST_TIMEOUT" in report["reason"]
    assert report["run_level_failure_classes"] == {
        "provider_request_timeout": 6}
    # explicit accounting: snapshot reproduction is 2/8, never presented
    # as full-measurement verification
    acc = report["accounting"]
    assert acc["scheduled_count"] == 8
    assert acc["run_terminal_count"] == 2
    assert acc["run_failed_count"] == 6
    assert acc["snapshot_reproduced_count"] == 2
    assert acc["failure_classified_count"] == 6
    assert acc["unclassified_failure_count"] == 0


def test_unclassified_run_failure_forces_review_required(tmp_path):
    """RCA-1.0 exhaustiveness: a run failure that matches no classification
    rule routes to REVIEW_REQUIRED — the fallback branch can never turn an
    unclassifiable failure into a pass-ish disposition."""
    qual = _series(tmp_path, [
        ("terminal", {}), ("terminal", {}), ("terminal", {})] +
        [("failed_other", {"reason": "RuntimeError: cosmic ray"})] * 5)
    report = _run_disposition(qual)
    assert report["disposition"] == "REVIEW_REQUIRED"
    acc = report["accounting"]
    assert acc["unclassified_failure_count"] == 5
    assert acc["failure_classified_count"] == 0


def test_integration_failed_terminal_run_counts_as_run_level_failure(tmp_path):
    """RCA-1.1 interplay: a contained INTEGRATE failure produces a terminal
    snapshot (no failure.json) whose digest carries the supervisor
    integration failure — the disposition must count it as a run-level
    failure, never as a clean terminal run."""
    qual = _series(tmp_path, [
        ("terminal", {}), ("terminal", {}), ("terminal", {}),
        ("terminal_integrate_failed", {}),
        ("terminal_integrate_failed", {}),
    ] + [("failed_timeout", {})] * 3)
    report = _run_disposition(qual)
    assert report["disposition"] == "NOT_QUALIFIED_SCREENING"
    assert report["accounting"]["run_integration_failed_count"] == 2
    # 3 failed-run timeouts + 2 contained INTEGRATE timeouts = same class
    assert report["run_level_failure_classes"].get(
        "provider_request_timeout") == 5


def test_schema_dominant_series_not_qualified(tmp_path):
    qual = _series(tmp_path, [
        ("terminal", {}), ("terminal", {}), ("terminal", {})] +
        [("failed_schema", {})] * 5)
    report = _run_disposition(qual)
    assert report["disposition"] == "NOT_QUALIFIED_SCREENING"
    assert "systemic structured-output failure" in report["reason"]
    assert report["specialist_schema_reliability"]["run_axis_rate"] == 0.625


def test_quota_dominant_series_provider_blocked(tmp_path):
    """§10: provider failures counted from TERMINAL runs' delegation
    digests (failed runs stop at failure.json) must dominate the
    disposition — a quota-starved series is never a semantic verdict."""
    qual = _series(tmp_path, [
        ("terminal", {}), ("terminal", {}), ("terminal", {})] +
        [("terminal_quota_digest", {})] * 5)
    report = _run_disposition(qual)
    assert report["disposition"] == "PROVIDER_CAPACITY_BLOCKED"
    assert report["provider_failures"]["provider_quota_rate_limited"] == 5


def test_identity_mismatch_blocks_series(tmp_path):
    qual = _series(tmp_path, [
        ("terminal", {"returned_model": "OTHER-MODEL"}), ("terminal", {})] +
        [("failed_timeout", {})] * 6)
    report = _run_disposition(qual)
    assert report["disposition"] == "PROVIDER_ROUTING_IDENTITY_MISMATCH"


def test_failed_run_accounting_stays_visible(tmp_path):
    """§9/§12: scheduled=8, terminal=2, failed=6 and the evaluate-only
    reproduction covers ONLY the snapshot-bearing runs — the report must
    never let 2/2 reproduction read as an 8/8 qualification."""
    qual = _series(tmp_path, [
        ("terminal", {}), ("terminal", {})] +
        [("failed_timeout", {})] * 6)
    report = _run_disposition(qual)
    assert report["scheduled_runs"] == 8
    assert report["terminal_runs"] == 2
    assert len(report["failed_runs"]) == 6
    assert report["evaluate_only_reproduction"] is True
    assert report["question_terminalization"]["total"] == 8
