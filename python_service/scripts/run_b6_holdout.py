#!/usr/bin/env python3
"""B6 §7-§8 formal holdout acceptance series driver.

Population (frozen AcceptanceProfileV2 / B6 authorization):
    2 holdout case families x 3 independent repetitions = 6 scheduled runs
    (t3-holdout-refund-fraud, t3-holdout-vpn-causal), case-major order.

Every scheduled attempt runs on a FRESH task / Investigation / AgentRun /
Working State.  NO best-of: a terminal attempt (result.json OR
failure.json) is never replaced, retried, or discarded; resume after a
crash only continues an attempt that left no terminal artifact.

Each attempt: fresh task provisioning -> REAL production agent wiring
(verbatim reuse of the frozen B2 driver path) -> durable artifacts
BEFORE lifecycle cleanup -> evaluate-only reproduction check -> task
cleanup.  The public charter (b6-holdout-charter-v1.json) supplies the
B6-entry goal/seed questions/association; the driver never guesses them.

Usage (from python_service/):
    .venv/bin/python scripts/run_b6_holdout.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))
SCRIPTS_DIR = SCRIPT_PATH.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
CHARTER_FILE = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "profiles"
    / "b6-holdout-charter-v1.json"
)
PREFLIGHT_FILE = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "b6-holdout" / "holdout-bootstrap-preflight-v1.json"
)
FROZEN_IDENTITY_FILE = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "b6-holdout" / "frozen-identities-v1.json"
)
RUNS_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "b6-holdout" / "run-set-v1"
)
EXPERIMENT_FILE = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "b6-holdout" / "experiment.json"
)
DEFAULT_MODEL_CONFIG = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "b2-restart" / "sensenova-6.8-flash-lite.model-config.json"
)
HOLDOUT_IMAGES = {
    "t3-holdout-refund-fraud": (
        PYTHON_SERVICE_ROOT / "benchmarks" / "images"
        / "t3-holdout-refund.img"
    ),
    "t3-holdout-vpn-causal": (
        PYTHON_SERVICE_ROOT / "benchmarks" / "images"
        / "t3-holdout-vpn-causal.img"
    ),
}
REPEATS = 3


def _write_execution_manifest(charter: dict, model_config_path: str) -> None:
    """B6 §6 start boundary + §35 HoldoutExecutionManifestV1."""
    import run_p8b_baseline as driver

    manifest_path = RUNS_ROOT.parent / "holdout-execution-manifest-v1.json"
    started = False
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        started = manifest.get("b6_started", False)
    if not manifest:
        frozen = json.loads(
            FROZEN_IDENTITY_FILE.read_text(encoding="utf-8")
        )
        manifest = {
            "artifact_version": "HoldoutExecutionManifestV1",
            "authorization": "B6 AUTHORIZED (explicit user directive)",
            "acceptance_profile": (
                "benchmarks/profiles/agent-v0-acceptance-profile-v2.json "
                "(FROZEN / ADMITTED_FOR_B6)"
            ),
            "frozen_identities_ref": (
                "benchmarks/results/agent-v0/b6-holdout/"
                "frozen-identities-v1.json"
            ),
            "frozen_identities_input_hash": frozen.get("input_hash"),
            "charter_input_hash": charter["input_hash"],
            "preflight_input_hash": json.loads(
                PREFLIGHT_FILE.read_text(encoding="utf-8")
            )["input_hash"],
            "population": {
                "families": charter["holdout_population"]["families"],
                "repetitions_per_family": REPEATS,
                "scheduled_runs": len(
                    charter["holdout_population"]["families"]
                )
                * REPEATS,
                "fresh_task_per_attempt": True,
            },
            "model_config_file": model_config_path,
            "no_best_of_policy": (
                "no retry-until-success, no replacement of a terminal "
                "attempt, no discard of 429/structured-output/semantic "
                "failures; existing frozen provider-internal retry only"
            ),
            "runtime_freeze": (
                "from the first holdout model request: model, provider, "
                "generation params, timeouts, retry policy, prompts, "
                "tool registry, supervisor/specialist/handle contracts, "
                "evidence lifecycle, budgets, bootstrap, case "
                "contracts, TruthManifests, evaluator, AcceptanceProfile "
                "and thresholds are all frozen"
            ),
            "b6_started": False,
            "b6_started_at": None,
            "attempt_log": [],
        }
    if not started:
        manifest["b6_started"] = True
        manifest["b6_started_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        )
        print(f"[B6] STARTED at {manifest['b6_started_at']} "
              f"(first holdout model request about to be issued)")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _append_attempt_log(case_id: str, tag: str, task_id: str) -> None:
    manifest_path = RUNS_ROOT.parent / "holdout-execution-manifest-v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["attempt_log"].append(
        {
            "case_id": case_id,
            "repeat": tag,
            "task_id": task_id,
            "provisioned_at": time.strftime(
                "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
            ),
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_b6_holdout")
    parser.add_argument(
        "--model-config",
        default=str(DEFAULT_MODEL_CONFIG),
        help="frozen ModelQualificationConfigV1 (default: the B2-final "
        "sensenova-6.8-flash-lite configuration — same frozen model "
        "identity as the calibration evidence)",
    )
    parser.add_argument(
        "--cleanup-tasks",
        action="store_true",
        default=True,
        help="§25: delete each task after snapshot+digest persistence "
        "and evaluate-only reproduction (default on)",
    )
    args = parser.parse_args(argv)

    import run_p8b_baseline as driver

    charter = json.loads(CHARTER_FILE.read_text(encoding="utf-8"))
    # Inject the holdout public charter into the frozen driver surfaces.
    # The driver itself is untouched; everything holdout-specific lives
    # here and in the charter artifact.
    for case_id, entry in charter["cases"].items():
        driver.SEED_QUESTIONS[case_id] = tuple(entry["seed_questions"])
        driver.IMAGES[case_id] = HOLDOUT_IMAGES[case_id]

    model_config = json.loads(
        Path(args.model_config).read_text(encoding="utf-8")
    )
    preflight = json.loads(PREFLIGHT_FILE.read_text(encoding="utf-8"))
    if not preflight.get("all_passed"):
        raise SystemExit(
            "B6_NOT_STARTED: holdout preflight did not pass"
        )

    case_ids = list(charter["holdout_population"]["families"])

    experiment = {
        "experiment_id": "bexp-agent-v0-b6-holdout",
        "code_commit": None,
        "production_runtime_commit": None,
        "model_config_file": str(
            Path(args.model_config).relative_to(PYTHON_SERVICE_ROOT)
        ),
        "candidate_id": model_config.get("candidate_id"),
        "charter_artifact": str(
            CHARTER_FILE.relative_to(PYTHON_SERVICE_ROOT)
        ),
        "charter_input_hash": charter["input_hash"],
        "corpus_id": "corpus-agent-v0-calibration (acceptance_cases "
        "holdout subset, corpus v2)",
        "repeat_policy": (
            "B6 §7: 2 holdout families x 3 independent repetitions, "
            "case-major; every attempt fresh task/investigation/run/state"
        ),
        "cache_policy": "cold",
        "graph_mode": "none",
        "report_mode": "disabled",
        "started_at": None,
        "fresh_task_ids": {},
    }
    if EXPERIMENT_FILE.exists():
        experiment.update(
            json.loads(EXPERIMENT_FILE.read_text(encoding="utf-8"))
        )
    else:
        import subprocess

        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        ).stdout.strip()
        experiment["code_commit"] = head
        experiment["production_runtime_commit"] = head
        experiment["started_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        )
    EXPERIMENT_FILE.parent.mkdir(parents=True, exist_ok=True)

    failures = 0
    scheduled = 0
    terminal = 0
    for case_id in case_ids:
        for repeat in range(REPEATS):
            tag = f"repeat{repeat}"
            scheduled += 1
            out_dir = RUNS_ROOT / case_id / tag
            if (out_dir / "result.json").exists() or (
                out_dir / "failure.json"
            ).exists():
                terminal += 1
                print(f"[skip] {case_id}/{tag}: terminal attempt already "
                      f"persisted (B6 §8: never replaced)")
                continue
            print(f"[run ] {case_id}/{tag}: provisioning fresh task...")
            provision = driver._provision_fresh_task(case_id, tag)
            fresh_task_id = provision["task_id"]
            print(
                f"       task={fresh_task_id} "
                f"staged={len(provision['staged'])} files"
            )
            _write_execution_manifest(charter, args.model_config)
            _append_attempt_log(case_id, tag, fresh_task_id)
            experiment["fresh_task_ids"].setdefault(case_id, {})[tag] = (
                fresh_task_id
            )
            EXPERIMENT_FILE.write_text(
                json.dumps(experiment, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                outcome = driver._run_one(
                    case_id,
                    tag,
                    fresh_task_id,
                    model_config=model_config,
                    configuration_id="bconf-b6-holdout",
                    configuration_label="b6-holdout-acceptance",
                )
            except Exception as exc:
                import traceback

                failures += 1
                print(f"[FAIL] {case_id}/{tag}: {exc}")
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "driver_failure.json").write_text(
                    json.dumps(
                        {
                            "error": str(exc)[:1000],
                            "traceback": traceback.format_exc()[-4000:],
                            "task_id": fresh_task_id,
                        }
                    ),
                    encoding="utf-8",
                )
                continue
            # §25: durable artifacts BEFORE any cleanup
            driver._persist(out_dir, outcome)
            task_store = Path(
                provision["record"]["extraction_directory"]
            ).parent / "investigation.db"
            if task_store.is_file():
                driver._extract_trajectory_digest(task_store, out_dir)
            terminal += 1
            if outcome["status"] == "completed":
                result = outcome["result"]
                gates = all(
                    g["passed"] for g in result.hard_gate_results
                )
                print(
                    f"[done] {case_id}/{tag}: "
                    f"run={result.run_manifest_id} "
                    f"result_hash={result.result_hash[:12]} gates="
                    f"{'PASS' if gates else 'VIOLATION'}"
                )
            else:
                failures += 1
                print(
                    f"[fail] {case_id}/{tag}: "
                    f"{outcome['failure'].failure_reason[:150]}"
                )
            # §26: evaluate-only reproduction, then §25 cleanup
            if args.cleanup_tasks and outcome["status"] == "completed":
                from httpserver.services.benchmarks.runner import (
                    evaluate_only,
                )
                from httpserver.services.benchmarks.run_manifest import (
                    BenchmarkRunManifestV1,
                )
                from httpserver.services.benchmarks.snapshot import (
                    BenchmarkRunSnapshotV1,
                )
                from httpserver.services.benchmarks.truth_manifest import (
                    ReachabilityManifestV1 as _RM,
                    TruthManifestV1 as _TM,
                )

                recomputed = evaluate_only(
                    run_manifest=BenchmarkRunManifestV1(
                        **json.loads(
                            (out_dir / "run_manifest.json").read_text(
                                encoding="utf-8"
                            )
                        )
                    ),
                    truth_manifest=_TM(
                        **json.loads(
                            (
                                driver.CASES_ROOT / case_id
                                / "truth_manifest.json"
                            ).read_text(encoding="utf-8")
                        )
                    ),
                    reachability=_RM(
                        **json.loads(
                            (
                                driver.CASES_ROOT / case_id
                                / "reachability.json"
                            ).read_text(encoding="utf-8")
                        )
                    ),
                    snapshot=BenchmarkRunSnapshotV1(
                        **json.loads(
                            (out_dir / "snapshot.json").read_text(
                                encoding="utf-8"
                            )
                        )
                    ),
                )
                persisted_hash = json.loads(
                    (out_dir / "result.json").read_text(encoding="utf-8")
                )["result_hash"]
                if recomputed.result_hash == persisted_hash:
                    if driver._cleanup_task(fresh_task_id):
                        (out_dir / "cleanup.json").write_text(
                            json.dumps(
                                {
                                    "benchmark_run_id": (
                                        result.run_manifest_id
                                    ),
                                    "task_id": fresh_task_id,
                                    "source_task_deleted_after_snapshot": (
                                        True
                                    ),
                                },
                                indent=1,
                            ),
                            encoding="utf-8",
                        )
                        print(
                            f"       [cleanup] task {fresh_task_id} "
                            f"deleted (evaluate-only hash verified)"
                        )
                    else:
                        print(
                            f"       [cleanup] task {fresh_task_id} "
                            f"delete FAILED; kept for analysis"
                        )
                else:
                    print(
                        f"       [cleanup] SKIPPED: evaluate-only hash "
                        f"MISMATCH (B6 §11 signal)"
                    )
    EXPERIMENT_FILE.write_text(
        json.dumps(experiment, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"\nB6 series loop exit: scheduled={scheduled} terminal={terminal} "
        f"failures={failures}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
