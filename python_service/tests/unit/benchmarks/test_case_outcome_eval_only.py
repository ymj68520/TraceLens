"""P8B B3.5 §19: evaluate-only independence from source task stores.

The evaluate-only path must produce the SAME result hash using ONLY the
persisted snapshot + truth manifest + metric registry — never the source
task's investigation.db/files.db.  This pins the §18/§19 contract that
post-snapshot benchmark-task cleanup cannot change evaluation outcomes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[3]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from httpserver.services.benchmarks.runner import evaluate_only
from httpserver.services.benchmarks.run_manifest import BenchmarkRunManifestV1
from httpserver.services.benchmarks.snapshot import BenchmarkRunSnapshotV1
from httpserver.services.benchmarks.truth_manifest import (
    ReachabilityManifestV1,
    TruthManifestV1,
)


def _minimal_manifest() -> BenchmarkRunManifestV1:
    from httpserver.services.benchmarks.run_manifest import ModelIdentityV1

    return BenchmarkRunManifestV1(
        case_id="case-x",
        case_version="1",
        case_hash="0" * 64,
        dataset_hash="1" * 64,
        truth_manifest_id="tman:x",
        truth_manifest_hash="2" * 64,
        model=ModelIdentityV1(provider="test", model_id="test-model"),
        tracelens_git_commit="0" * 40,
        configuration_id="bconf:test",
        configuration_hash="3" * 64,
        benchmark_run_id="brun:test-eval-only",
    )


def _minimal_truth() -> TruthManifestV1:
    return TruthManifestV1(
        manifest_id="tman:x",
        case_id="case-x",
        case_version="1",
        critical_evidence=[
            {
                "truth_evidence_id": "TE-1",
                "evidence_identity_description": "the ledger file",
                "expected_evidence_key": "file:/ledger.txt",
                "criticality": "critical",
                "parser_expectation": "reachable",
            }
        ],
    )


def _minimal_reachability() -> ReachabilityManifestV1:
    return ReachabilityManifestV1(
        case_id="case-x",
        records=[
            {
                "truth_evidence_id": "TE-1",
                "resolved_evidence_keys": ["file:/ledger.txt"],
                "parser_reachable": True,
                "agent_discoverable": True,
                "status": "resolved",
            }
        ],
    )


def _minimal_snapshot() -> BenchmarkRunSnapshotV1:
    return BenchmarkRunSnapshotV1(
        run_id="run_x",
        task_id="bench-test",
        investigation_id="inv-test",
        terminal_status="failed",
        discovered_evidence_refs=("file:/ledger.txt",),
    )


def test_evaluate_only_independent_of_source_task_store(tmp_path):
    """Evaluate twice: once 'with' the task store present, once after the
    store directory is deleted entirely.  Same inputs -> same result hash
    (B3.5 §19); the evaluator never touches the task store."""
    # a fake task store that WOULD break the evaluator if it were consulted
    task_store = tmp_path / "tasks" / "bench-test" / "investigation.db"
    task_store.parent.mkdir(parents=True)
    task_store.write_bytes(b"not even sqlite")

    manifest = _minimal_manifest()
    snapshot = _minimal_snapshot()
    truth = _minimal_truth()
    reach = _minimal_reachability()

    first = evaluate_only(
        run_manifest=manifest,
        truth_manifest=truth,
        reachability=reach,
        snapshot=snapshot,
    )

    # simulate post-snapshot cleanup: the source task store is GONE
    import shutil

    shutil.rmtree(task_store.parent.parent)

    second = evaluate_only(
        run_manifest=manifest,
        truth_manifest=truth,
        reachability=reach,
        snapshot=snapshot,
    )

    assert first.result_hash == second.result_hash
    assert first.result_hash  # non-trivial hash


def test_evaluate_only_reproduces_persisted_baseline_hashes():
    """B3.5 §7: same snapshot + same metric version -> same result hash for
    every persisted B2 baseline run (recompute determinism)."""
    baseline_root = (
        PYTHON_SERVICE_ROOT
        / "benchmarks"
        / "results"
        / "agent-v0"
        / "baseline"
    )
    if not baseline_root.is_dir():
        pytest.skip("baseline artifacts not present")
    checked = 0
    for case_dir in sorted(baseline_root.iterdir()):
        if not case_dir.is_dir():
            continue
        truth = TruthManifestV1(
            **json.loads(
                (PYTHON_SERVICE_ROOT / "benchmarks/cases" / case_dir.name / "truth_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        reach = ReachabilityManifestV1(
            **json.loads(
                (PYTHON_SERVICE_ROOT / "benchmarks/cases" / case_dir.name / "reachability.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        for run_dir in sorted(case_dir.iterdir()):
            result_file = run_dir / "result.json"
            manifest_file = run_dir / "run_manifest.json"
            snap_file = run_dir / "snapshot.json"
            if not (result_file.is_file() and manifest_file.is_file() and snap_file.is_file()):
                continue
            expected = json.loads(result_file.read_text(encoding="utf-8"))[
                "result_hash"
            ]
            manifest = BenchmarkRunManifestV1(
                **json.loads(manifest_file.read_text(encoding="utf-8"))
            )
            snapshot = BenchmarkRunSnapshotV1(
                **json.loads(snap_file.read_text(encoding="utf-8"))
            )
            recomputed = evaluate_only(
                run_manifest=manifest,
                truth_manifest=truth,
                reachability=reach,
                snapshot=snapshot,
            )
            assert recomputed.result_hash == expected, (
                f"{case_dir.name}/{run_dir.name} hash drift"
            )
            checked += 1
    assert checked > 0
