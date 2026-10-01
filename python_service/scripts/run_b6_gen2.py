#!/usr/bin/env python3
"""Acceptance Generation 2 — B6 formal sealed holdout execution driver.

Population (frozen AcceptanceProfileV2 / B6 authorization):
    2 Gen-2 families x 3 independent repetitions = 6 scheduled runs,
    case-major order, every attempt on a fresh task / Investigation /
    AgentRun / Working State.  NO best-of: terminal attempts are never
    replaced or retried.

Every byte the Agent sees comes from the SEALED PublicHoldoutCaseV2
(goal, case_context, charter questions, coverage dimensions, source
scopes) and the staged sealed assets — the driver only loads, validates,
hash-checks, and projects (B6 never authors semantics, spec §3/§13).
The initial Working State is the FROZEN projection
(`holdout_contract.build_holdout_working_state`), so the declared
coverage→question links are used verbatim.  The runner-facing case.json
is the frozen `derive_benchmark_case_v1` projection materialized into a
per-attempt temp dir together with byte-exact copies of the sealed truth
and reachability files (hashes unchanged).

Entry gates: the passing HoldoutBootstrapPreflightV2 must exist and
`enforce_execution_gate` must pass again immediately before the first
provisioning; the first model request sets B6_STARTED (spec §2/§5/§6).

Usage (from python_service/):
    .venv/bin/python scripts/run_b6_gen2.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
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
GEN2_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen2"
)
CASES_DIR = GEN2_ROOT / "cases"
TRUTH_DIR = GEN2_ROOT / "truth"
RUNS_ROOT = GEN2_ROOT / "run-set-v1"
EXPERIMENT_FILE = GEN2_ROOT / "experiment.json"
MANIFEST_FILE = GEN2_ROOT / "holdout-execution-manifest-v2.json"
PREFLIGHT_FILE = GEN2_ROOT / "holdout-bootstrap-preflight-v2.json"
SEAL_FILE = GEN2_ROOT / "holdout-seal-v2.json"
DEFAULT_MODEL_CONFIG = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "b2-restart" / "sensenova-6.8-flash-lite.model-config.json"
)
REPEATS = 3


def _provision_fresh_task_gen2(sealed, substrate: Path, tag: str) -> dict:
    """Gen-2 provisioning: fresh task from the sealed substrate, then
    stage the SEALED public assets into extracted_files (hash-verified
    against PublicHoldoutCaseV2.public_assets).  Equivalent to the frozen
    driver's provisioning, but the staged set is exactly the sealed
    asset list — no dataset_manifest.json exists for Gen-2 cases."""
    import hashlib
    import shutil
    import urllib.request

    def _create_task() -> str:
        body = json.dumps(
            {
                "image_path": str(substrate),
                "case_description": (
                    f"Gen-2 B6 acceptance case {sealed.case_id} "
                    f"repeat {tag}. Benchmark purpose: agent "
                    f"investigation quality measurement."
                ),
                "llm_analyze": False,
                "llm_event_analyze": False,
                "priority": "high",
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:8666/api/tasks",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))["id"]

    def _wait_task(task_id: str, timeout_s: int = 600) -> dict:
        deadline = time.monotonic() + timeout_s
        last = {}
        while time.monotonic() < deadline:
            with urllib.request.urlopen(
                f"http://127.0.0.1:8666/api/tasks/{task_id}", timeout=15
            ) as resp:
                last = json.loads(resp.read().decode("utf-8"))
            if last.get("status") in ("completed", "failed", "cancelled"):
                return last
            time.sleep(3)
        raise TimeoutError(f"task {task_id} not terminal in {timeout_s}s")

    task_id = _create_task()
    record = _wait_task(task_id)
    if record.get("status") != "completed":
        raise RuntimeError(
            f"fresh task {task_id} terminal={record.get('status')}: "
            f"{str(record.get('error_details', ''))[:200]}"
        )
    extraction_dir = Path(record["extraction_directory"])
    staged = []
    for asset in sealed.public_assets:
        src = CASES_DIR / sealed.case_id / "dataset" / asset.relative_path
        dst = extraction_dir / asset.relative_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        digest = hashlib.sha256(dst.read_bytes()).hexdigest()
        if digest != asset.sha256:
            raise RuntimeError(
                f"staged sealed asset hash mismatch: "
                f"{asset.relative_path}"
            )
        staged.append(asset.relative_path)
    return {"task_id": task_id, "record": record, "staged": staged}


def _write_execution_manifest(action: str, **extra) -> None:
    """HoldoutExecutionManifestV2 (spec §6/§36): B6 start boundary +
    attempt log, hash-linked to preflight/seal."""
    preflight = json.loads(PREFLIGHT_FILE.read_text(encoding="utf-8"))
    seal = json.loads(SEAL_FILE.read_text(encoding="utf-8"))
    if not MANIFEST_FILE.exists():
        manifest = {
            "artifact_version": "HoldoutExecutionManifestV2",
            "generation_id": "acceptance-generation-2",
            "authorization": (
                "Generation-2 B6 FINAL SEALED HOLDOUT EXECUTION "
                "(explicit user directive)"
            ),
            "acceptance_profile": (
                "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
            ),
            "preflight_input_hash": preflight["input_hash"],
            "seal_hash": seal["seal_hash"],
            "model_config_file": str(
                Path(DEFAULT_MODEL_CONFIG).relative_to(PYTHON_SERVICE_ROOT)
            ),
            "population": {
                "families": sorted(seal["public_case_hashes"]),
                "repetitions_per_family": REPEATS,
                "scheduled_runs": len(seal["public_case_hashes"]) * REPEATS,
                "fresh_state_per_attempt": True,
            },
            "no_best_of_policy": (
                "no retry-until-success, no replacement of a terminal "
                "attempt, no discard of 429/structured-output/semantic "
                "failures; frozen provider-internal retry only"
            ),
            "agent_visible_input_source": (
                "SEALED PublicHoldoutCaseV2 only — the driver loads, "
                "validates, hash-checks and projects; it never authors"
            ),
            "b6_started": False,
            "b6_started_at": None,
            "attempt_log": [],
        }
    else:
        manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    if action == "start" and not manifest["b6_started"]:
        manifest["b6_started"] = True
        manifest["b6_started_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        )
        print(
            f"[B6] STARTED at {manifest['b6_started_at']} "
            f"(first holdout model request about to be issued)"
        )
    if action == "attempt":
        manifest["attempt_log"].append(extra["entry"])
    MANIFEST_FILE.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _materialize_runner_case_dir(sealed, truth, reach, case) -> Path:
    """Per-attempt runner-facing case dir: the frozen projection
    case.json + byte-exact sealed truth/reachability copies."""
    tmp = Path(tempfile.mkdtemp(prefix=f"gen2runner-{sealed.case_id}-"))
    (tmp / "truth_manifest.json").write_text(
        json.dumps(json.loads(truth.model_dump_json()), indent=1),
        encoding="utf-8",
    )
    (tmp / "reachability.json").write_text(
        json.dumps(json.loads(reach.model_dump_json()), indent=1),
        encoding="utf-8",
    )
    (tmp / "case.json").write_text(case.model_dump_json(), encoding="utf-8")
    return tmp


def _run_one_gen2(case_id, repeat, fresh_task_id, sealed, model_config):
    """ONE scheduled attempt on a pre-provisioned fresh task.

    Gen-2 variant of the frozen B2 driver's _run_one: the case input is
    built STRICTLY from the sealed PublicHoldoutCaseV2; the runner case
    is the pure derive_benchmark_case_v1 projection.  All execution
    wiring is verbatim reuse (`driver._execute_with_wiring`).
    """
    from httpserver.config import Settings
    from httpserver.services.benchmarks.holdout_contract import (
        build_holdout_working_state,
        derive_benchmark_case_v1,
    )
    from httpserver.services.benchmarks.production_executor import (
        PublicCaseInputV1,
    )
    from httpserver.services.benchmarks.run_manifest import (
        BenchmarkConfigurationV1,
        ModelIdentityV1,
    )
    from httpserver.services.benchmarks.runner import current_git_identity
    from httpserver.services.benchmarks.truth_manifest import (
        ReachabilityManifestV1,
        TruthManifestV1,
    )

    import run_p8b_baseline as driver

    settings = Settings(_env_file=str(REPO_ROOT / ".env"))
    if model_config is not None:
        settings = driver._ModelOverrideSettings(
            settings, model_config["overrides"]
        )

    case_input = PublicCaseInputV1(
        case_id=sealed.case_id,
        goal=sealed.goal,
        case_context=sealed.case_context,
        seed_questions=tuple(q.text for q in sealed.charter),
        seed_coverage_dimensions=tuple(sealed.required_coverage_dimensions),
        source_scope_ids=tuple(sealed.source_scope_ids),
    )

    truth = TruthManifestV1(
        **json.loads(
            (TRUTH_DIR / f"{case_id}.truth.json").read_text(
                encoding="utf-8"
            )
        )
    )
    reach = ReachabilityManifestV1(
        **json.loads(
            (TRUTH_DIR / f"{case_id}.reachability.json").read_text(
                encoding="utf-8"
            )
        )
    )
    dataset_manifest = {
        "dataset_version": "benchmark-dataset:v1",
        "dataset_id": f"ds-{case_id}",
        "files": [
            {
                "logical_id": asset.logical_id,
                "relative_path": asset.relative_path,
                "size_bytes": (
                    CASES_DIR
                    / case_id
                    / "dataset"
                    / asset.relative_path
                ).stat().st_size,
                "sha256": asset.sha256,
            }
            for asset in sealed.public_assets
        ],
        "created_at": "2026-10-01T00:00:00+00:00",
    }
    case = derive_benchmark_case_v1(
        sealed,
        dataset_manifest=dataset_manifest,
        truth_manifest_id=truth.manifest_id,
        truth_manifest_hash=truth.input_hash,
        platform_composition=("linux",),
        expected_parser_profile="linux",
        tier="T2",
        title=f"GEN2 SEALED {case_id}",
    )

    git_commit, git_branch = current_git_identity(REPO_ROOT)
    thinking_mode = settings.llm_thinking_mode
    model = ModelIdentityV1(
        provider=(
            model_config["provider"] if model_config else "hcnsec-cloud"
        ),
        model_id=settings.llm_text_model,
        generation_params={
            "temperature": settings.llm_text_temperature,
            "max_tokens": settings.llm_text_max_tokens,
            "thinking_mode": thinking_mode,
            "reasoning_effort": (
                "none" if thinking_mode == "disabled" else None
            ),
        },
        context_window_tokens=settings.llm_context_length,
        request_date="2026-10-01",
    )
    configuration = BenchmarkConfigurationV1(
        configuration_id="bconf-b6-gen2",
        label="b6-gen2-acceptance",
        model_provider=model.provider,
        model_id=model.model_id,
        generation_params={"repeat": 1, "timeout_seconds": 900},
        agent_supervisor_enabled=True,
        specialist_enabled=True,
        timeout_seconds=900,
    )

    runner_case_dir = _materialize_runner_case_dir(
        sealed, truth, reach, case
    )
    try:
        # §3: the ONLY initial Working State is the frozen projection of
        # the sealed contract (wiring resolves the module global at call
        # time, so this patch is the projection hook).
        driver.build_benchmark_seed_state = (
            lambda task_id, investigation_id, ci: build_holdout_working_state(
                sealed,
                task_id=task_id,
                investigation_id=investigation_id,
            )
        )
        return driver._execute_with_wiring(
            settings=settings,
            fresh_task_id=fresh_task_id,
            case_input=case_input,
            case_dir=runner_case_dir,
            configuration=configuration,
            model=model,
            git_commit=git_commit,
            git_branch=git_branch,
            repeat=repeat,
        )
    finally:
        shutil.rmtree(runner_case_dir, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_b6_gen2")
    parser.add_argument("--model-config", default=str(DEFAULT_MODEL_CONFIG))
    args = parser.parse_args(argv)

    import run_p8b_baseline as driver
    from httpserver.services.benchmarks.holdout_contract import (
        HoldoutSealV2,
        enforce_execution_gate,
        load_public_holdout_case,
    )

    preflight = json.loads(PREFLIGHT_FILE.read_text(encoding="utf-8"))
    if not preflight.get("all_passed"):
        raise SystemExit(
            "BENCHMARK_PREFLIGHT_BLOCKED: Gen-2 preflight did not pass; "
            "execution_count must remain 0"
        )
    seal_dict = json.loads(SEAL_FILE.read_text(encoding="utf-8"))
    stored = seal_dict.get("seal_hash", "")
    seal = HoldoutSealV2(**seal_dict)
    if seal.seal_hash != stored:
        raise SystemExit("seal record internally inconsistent")
    enforce_execution_gate(
        seal,
        cases_dir=CASES_DIR,
        truth_dir=TRUTH_DIR,
        acceptance_profile_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
        ),
        calibration_binding_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/calibration-evidence-binding-v2.json"
        ),
        provisioning_substrate_path=Path(
            seal.provisioning_substrate["path"]
        ),
    )

    model_config = json.loads(
        Path(args.model_config).read_text(encoding="utf-8")
    )
    case_ids = sorted(seal.public_case_hashes)
    substrate = Path(seal.provisioning_substrate["path"])

    experiment = {
        "experiment_id": "bexp-agent-v0-b6-gen2",
        "code_commit": None,
        "production_runtime_commit": None,
        "model_config_file": str(
            Path(args.model_config).relative_to(PYTHON_SERVICE_ROOT)
        ),
        "candidate_id": model_config.get("candidate_id"),
        "generation_id": "acceptance-generation-2",
        "seal_hash": seal.seal_hash,
        "preflight_input_hash": preflight["input_hash"],
        "repeat_policy": (
            "Gen-2 B6 §7: 2 families x 3 independent repetitions, "
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
    terminal = 0
    scheduled = 0
    for case_id in case_ids:
        sealed = load_public_holdout_case(
            CASES_DIR / f"{case_id}.public-case.json"
        )
        # §3: the ONLY seed-questions source is the sealed charter; the
        # ONLY initial Working State is the frozen projection.
        driver.SEED_QUESTIONS[case_id] = tuple(
            q.text for q in sealed.charter
        )
        driver.IMAGES[case_id] = substrate
        for repeat in range(REPEATS):
            tag = f"repeat{repeat}"
            scheduled += 1
            out_dir = RUNS_ROOT / case_id / tag
            if (out_dir / "result.json").exists() or (
                out_dir / "failure.json"
            ).exists():
                terminal += 1
                print(
                    f"[skip] {case_id}/{tag}: terminal attempt already "
                    f"persisted (§9: never replaced)"
                )
                continue
            print(f"[run ] {case_id}/{tag}: provisioning fresh task...")
            provision = _provision_fresh_task_gen2(sealed, substrate, tag)
            fresh_task_id = provision["task_id"]
            print(
                f"       task={fresh_task_id} "
                f"staged={len(provision['staged'])} files"
            )
            experiment["fresh_task_ids"].setdefault(case_id, {})[tag] = (
                fresh_task_id
            )
            EXPERIMENT_FILE.write_text(
                json.dumps(experiment, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            _write_execution_manifest(
                "attempt",
                entry={
                    "case_id": case_id,
                    "repeat": tag,
                    "task_id": fresh_task_id,
                    "provisioned_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
                    ),
                },
            )
            _write_execution_manifest("start")
            try:
                outcome = _run_one_gen2(
                    case_id, tag, fresh_task_id, sealed, model_config
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
            # §26: evaluate-only reproduction against the SEALED truth,
            # then §25 cleanup
            if outcome["status"] == "completed":
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
                                TRUTH_DIR / f"{case_id}.truth.json"
                            ).read_text(encoding="utf-8")
                        )
                    ),
                    reachability=_RM(
                        **json.loads(
                            (
                                TRUTH_DIR / f"{case_id}.reachability.json"
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
                        f"MISMATCH (§12 signal)"
                    )
    EXPERIMENT_FILE.write_text(
        json.dumps(experiment, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"\nGen-2 B6 loop exit: scheduled={scheduled} terminal={terminal} "
        f"failures={failures}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
