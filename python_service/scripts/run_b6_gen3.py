#!/usr/bin/env python3
"""Acceptance Generation 3 — B6 formal sealed holdout execution driver.

Population (frozen AcceptanceProfileV2 / B6 authorization):
    2 Gen-3 families x 3 independent repetitions = 6 scheduled runs,
    case-major order, every attempt on a fresh task / Investigation /
    AgentRun / Working State.  NO best-of; terminal attempts are never
    replaced.

§5 NO LATE INJECTION: every task is provisioned DIRECTLY from the
sealed per-case substrate image — the indexed evidence world is exactly
what the image extraction yields.  No file is copied into
extracted_files at any time.

§26 EVIDENCE-WORLD RUN PROOF: before cleanup, each run's own parsed
stores are digested and bound into the run record
(substrate_id, image hash, actual digest, sealed digest, match).

Entry: the passing HoldoutBootstrapPreflightV3 must exist; the seal is
re-verified and enforce_execution_gate_v3 runs again before the first
provisioning.  The first model request sets B6_STARTED (§6).

Usage (from python_service/):
    .venv/bin/python scripts/run_b6_gen3.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))
SCRIPTS_DIR = SCRIPT_PATH.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
GEN3_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen3"
)
CASES_DIR = GEN3_ROOT / "cases"
TRUTH_DIR = GEN3_ROOT / "truth"
IMAGES_DIR = GEN3_ROOT / "images"
RUNS_ROOT = GEN3_ROOT / "run-set-v1"
EXPERIMENT_FILE = GEN3_ROOT / "experiment-b6.json"
MANIFEST_FILE = GEN3_ROOT / "holdout-execution-manifest-v3.json"
PREFLIGHT_FILE = GEN3_ROOT / "holdout-bootstrap-preflight-v3.json"
SEAL_FILE = GEN3_ROOT / "holdout-seal-v3.json"
DEFAULT_MODEL_CONFIG = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "b2-restart" / "sensenova-6.8-flash-lite.model-config.json"
)
REPEATS = 3


def _write_execution_manifest(action: str, **extra) -> None:
    preflight = json.loads(PREFLIGHT_FILE.read_text(encoding="utf-8"))
    seal = json.loads(SEAL_FILE.read_text(encoding="utf-8"))
    if not MANIFEST_FILE.exists():
        manifest = {
            "artifact_version": "HoldoutExecutionManifestV3",
            "generation_id": "acceptance-generation-3",
            "authorization": (
                "Gen-3 B6 FINAL SEALED HOLDOUT EXECUTION (explicit user "
                "directive, after the §1 d05f402d superseding record)"
            ),
            "acceptance_profile": (
                "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
            ),
            "preflight_input_hash": preflight["input_hash"],
            "seal_hash": seal["seal_hash"],
            "frozen_inputs_ref": "gen3-b6-frozen-inputs-v1.json",
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
                "attempt; frozen provider-internal retry only"
            ),
            "no_late_injection": (
                "tasks are provisioned directly from the sealed per-case "
                "substrate images; nothing is copied into "
                "extracted_files at any time"
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


def _provision_fresh_task_gen3(image_path: Path, case_id: str, tag: str):
    """§5: fresh task from the SEALED substrate image — no staging."""
    import json as _json

    body = _json.dumps(
        {
            "image_path": str(image_path),
            "case_description": (
                f"Gen-3 B6 acceptance case {case_id} repeat {tag}. "
                f"Benchmark purpose: agent investigation quality "
                f"measurement."
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
    last_error = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                task_id = _json.loads(resp.read().decode("utf-8"))["id"]
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in (400, 500, 502, 503) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    if task_id is None:
        raise RuntimeError(f"task creation failed: {last_error}")
    deadline = time.monotonic() + 600
    record = {}
    while time.monotonic() < deadline:
        with urllib.request.urlopen(
            f"http://127.0.0.1:8666/api/tasks/{task_id}", timeout=15
        ) as resp:
            record = _json.loads(resp.read().decode("utf-8"))
        if record.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(3)
    if record.get("status") != "completed":
        raise RuntimeError(
            f"fresh task {task_id} terminal={record.get('status')}: "
            f"{str(record.get('error_details', ''))[:200]}"
        )
    return {"task_id": task_id, "record": record}


def _run_one_gen3(case_id, repeat, fresh_task_id, sealed, model_config):
    from httpserver.config import Settings
    from httpserver.services.benchmarks.holdout_contract import (
        build_holdout_working_state,
    )
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        derive_runner_case_for_gen3,
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
    case = derive_runner_case_for_gen3(
        sealed, truth, reach, CASES_DIR / case_id / "dataset"
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
        configuration_id="bconf-b6-gen3",
        label="b6-gen3-acceptance",
        model_provider=model.provider,
        model_id=model.model_id,
        generation_params={"repeat": 1, "timeout_seconds": 900},
        agent_supervisor_enabled=True,
        specialist_enabled=True,
        timeout_seconds=900,
    )
    runner_case_dir = Path(
        tempfile.mkdtemp(prefix=f"gen3runner-{case_id}-")
    )
    (runner_case_dir / "truth_manifest.json").write_text(
        json.dumps(json.loads(truth.model_dump_json()), indent=1),
        encoding="utf-8",
    )
    (runner_case_dir / "reachability.json").write_text(
        json.dumps(json.loads(reach.model_dump_json()), indent=1),
        encoding="utf-8",
    )
    (runner_case_dir / "case.json").write_text(
        case.model_dump_json(), encoding="utf-8"
    )
    try:
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
    parser = argparse.ArgumentParser(prog="run_b6_gen3")
    parser.add_argument("--model-config", default=str(DEFAULT_MODEL_CONFIG))
    args = parser.parse_args(argv)

    import run_p8b_baseline as driver
    from httpserver.services.benchmarks.holdout_contract import (
        load_public_holdout_case,
    )
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        HoldoutSealV3,
        SealedEvidenceSubstrateV1,
        compute_evidence_world_digest,
        derive_runner_case_for_gen3,
        enforce_execution_gate_v3,
    )

    preflight = json.loads(PREFLIGHT_FILE.read_text(encoding="utf-8"))
    if not preflight.get("all_passed"):
        raise SystemExit(
            "BENCHMARK_PREFLIGHT_BLOCKED: Gen-3 preflight did not pass; "
            "execution_count must remain 0"
        )
    seal_dict = json.loads(SEAL_FILE.read_text(encoding="utf-8"))
    stored = seal_dict.get("seal_hash", "")
    seal = HoldoutSealV3(**seal_dict)
    if seal.seal_hash != stored:
        raise SystemExit("seal record internally inconsistent")

    gate_kwargs = dict(
        gen3_root=GEN3_ROOT,
        profiles_dir=REPO_ROOT / "config" / "filter_profiles",
        acceptance_profile_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
        ),
        calibration_binding_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/calibration-evidence-binding-v2.json"
        ),
        generation_binding_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/acceptance-profile-generation-binding-v3.json"
        ),
        runtime_investigation_subtree_hash=_git(
            "rev-parse",
            "HEAD:python_service/httpserver/services/investigation",
        ),
        model_config_path=DEFAULT_MODEL_CONFIG,
    )
    enforce_execution_gate_v3(
        seal,
        **gate_kwargs,
        evidence_world_digests=dict(seal.evidence_world_digests),
        evidence_world_keys={
            cid: {
                e["expected_evidence_key"]
                for e in json.loads(
                    (
                        GEN3_ROOT / "substrates"
                        / f"{cid}.evidence-manifest.json"
                    ).read_text(encoding="utf-8")
                )["entries"]
            }
            for cid in seal.public_case_hashes
        },
        evidence_world_files={
            cid: {
                e["normalized_path"].lstrip("/")
                for e in json.loads(
                    (
                        GEN3_ROOT / "substrates"
                        / f"{cid}.evidence-manifest.json"
                    ).read_text(encoding="utf-8")
                )["entries"]
            }
            for cid in seal.public_case_hashes
        },
    )

    model_config = json.loads(
        Path(args.model_config).read_text(encoding="utf-8")
    )
    case_ids = sorted(seal.public_case_hashes)

    experiment = {
        "experiment_id": "bexp-agent-v0-b6-gen3",
        "generation_id": "acceptance-generation-3",
        "model_config_file": str(
            Path(args.model_config).relative_to(PYTHON_SERVICE_ROOT)
        ),
        "candidate_id": model_config.get("candidate_id"),
        "seal_hash": seal.seal_hash,
        "preflight_input_hash": preflight["input_hash"],
        "repeat_policy": (
            "Gen-3 B6 §7: 2 families x 3 independent repetitions, "
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
            capture_output=True, text=True, cwd=REPO_ROOT,
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
        substrate = SealedEvidenceSubstrateV1(
            **json.loads(
                (
                    GEN3_ROOT / "substrates" / f"{case_id}.substrate.json"
                ).read_text(encoding="utf-8")
            )
        )
        image_path = IMAGES_DIR / substrate.image_relative_path
        driver.SEED_QUESTIONS[case_id] = tuple(
            q.text for q in sealed.charter
        )
        driver.IMAGES[case_id] = image_path
        for repeat in range(REPEATS):
            tag = f"repeat{repeat}"
            scheduled += 1
            out_dir = RUNS_ROOT / case_id / tag
            if (out_dir / "result.json").exists() or (
                out_dir / "failure.json"
            ).exists():
                terminal += 1
                print(f"[skip] {case_id}/{tag}: terminal attempt persisted")
                continue
            print(f"[run ] {case_id}/{tag}: provisioning fresh task...")
            provision = _provision_fresh_task_gen3(
                image_path, case_id, tag
            )
            fresh_task_id = provision["task_id"]
            print(f"       task={fresh_task_id} (sealed image, no staging)")
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
                    "substrate_id": substrate.substrate_id,
                    "provisioned_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
                    ),
                },
            )
            _write_execution_manifest("start")
            try:
                outcome = _run_one_gen3(
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
            # §26: evidence-world run proof from the run's OWN store
            world = compute_evidence_world_digest(task_store.parent)
            proof = {
                "substrate_id": substrate.substrate_id,
                "image_sha256": substrate.image_sha256,
                "actual_parsed_evidence_world_digest": world["digest"],
                "expected_sealed_evidence_world_digest": (
                    seal.evidence_world_digests[case_id]
                ),
                "match": (
                    world["digest"]
                    == seal.evidence_world_digests[case_id]
                ),
            }
            (out_dir / "evidence-world-proof.json").write_text(
                json.dumps(proof, indent=1), encoding="utf-8"
            )
            print(
                f"       [world-proof] match={proof['match']} "
                f"digest={world['digest'][:12]}…"
            )
            terminal += 1
            if outcome["status"] == "completed":
                result = outcome["result"]
                gates = all(g["passed"] for g in result.hard_gate_results)
                print(
                    f"[done] {case_id}/{tag}: run={result.run_manifest_id} "
                    f"gates={'PASS' if gates else 'VIOLATION'}"
                )
            else:
                failures += 1
                print(
                    f"[fail] {case_id}/{tag}: "
                    f"{outcome['failure'].failure_reason[:150]}"
                )
            # §27: evaluate-only reproduction, then cleanup
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
                                TRUTH_DIR
                                / f"{case_id}.reachability.json"
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
                            f"delete FAILED; kept"
                        )
                else:
                    print(
                        f"       [cleanup] SKIPPED: evaluate-only hash "
                        f"MISMATCH (§11 signal)"
                    )
    EXPERIMENT_FILE.write_text(
        json.dumps(experiment, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"\nGen-3 B6 loop exit: scheduled={scheduled} terminal={terminal} "
        f"failures={failures}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
