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
                  quota_digest: bool = False):
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
                          quota_digest=(kind == "terminal_quota_digest"))
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


@pytest.mark.xfail(
    strict=True,
    reason="BENCHMARK_DISPOSITION_DEFECT (audit-confirmed): the disposition "
           "decision tree has no RUNTIME_FAILURE_UNATTRIBUTED/timeout branch "
           "and no terminalization gate, so a 6/8-failed timeout-dominant "
           "series falls through to READY_FOR_8X3. Fix pending authorization.",
)
def test_timeout_dominant_series_must_not_be_ready_for_8x3(tmp_path):
    """The observed step-5-preview shape: 2 terminal (1 answered, 1 open)
    + 6 request timeouts. The only acceptable dispositions are
    NOT_QUALIFIED_SCREENING or PROVIDER_TIMEOUT-class blockers."""
    qual = _series(tmp_path, [
        ("terminal", {}), ("terminal_open", {})] +
        [("failed_timeout", {})] * 6)
    report = _run_disposition(qual)
    assert report["disposition"] != "READY_FOR_8X3"
    assert report["disposition"] == "NOT_QUALIFIED_SCREENING"


def test_timeout_series_currently_falls_through_to_ready_false_positive(
        tmp_path):
    """Documents the CURRENT behaviour as a pinned defect reference: the
    same series the required-behaviour test rejects is returned as
    READY_FOR_8X3 today. If this test starts failing because the required
    behaviour landed, remove it together with the xfail above."""
    qual = _series(tmp_path, [
        ("terminal", {}), ("terminal_open", {})] +
        [("failed_timeout", {})] * 6)
    report = _run_disposition(qual)
    assert report["disposition"] == "READY_FOR_8X3"
    assert report["failed_runs"]  # the losses are at least visible
    assert report["question_terminalization"]["terminalized"] == 1
    assert report["question_terminalization"]["total"] == 8


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
