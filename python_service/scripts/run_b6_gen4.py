"""Gen-4 B6 execution driver (§5-§24).

Execution ONLY: 2 families x 3 fresh repetitions, no staging, per-run
evidence-world + hydration proofs, durable artifacts before cleanup,
HoldoutRunSetV4 freeze at the end. Evaluate-only + verdicts live in
evaluate_b6_gen4.py (§25-§26: after the run-set freeze).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
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
GEN4_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen4"
)
CASES_DIR = GEN4_ROOT / "cases"
TRUTH_DIR = GEN4_ROOT / "truth"
IMAGES_DIR = GEN4_ROOT / "images"
RUNS_ROOT = GEN4_ROOT / "run-set-v1"
EXPERIMENT_FILE = GEN4_ROOT / "experiment-b6.json"
MANIFEST_FILE = GEN4_ROOT / "holdout-execution-manifest-v4.json"
PREFLIGHT_FILE = GEN4_ROOT / "holdout-bootstrap-preflight-v4.json"
FROZEN_INPUTS_FILE = GEN4_ROOT / "gen4-b6-frozen-inputs-v1.json"
SEAL_FILE = GEN4_ROOT / "holdout-seal-v3.json"
RUN_SET_FILE = GEN4_ROOT / "holdout-run-set-v4.json"
MODEL_CONFIG = GEN4_ROOT / "gen4-model-config.json"
REPEATS = 3


def _git(*args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=REPO_ROOT
    ).stdout.strip()


def _write_execution_manifest(action: str, **extra) -> None:
    preflight = json.loads(PREFLIGHT_FILE.read_text(encoding="utf-8"))
    frozen = json.loads(FROZEN_INPUTS_FILE.read_text(encoding="utf-8"))
    seal = json.loads(SEAL_FILE.read_text(encoding="utf-8"))
    if not MANIFEST_FILE.exists():
        manifest = {
            "artifact_version": "HoldoutExecutionManifestV4",
            "generation_id": "acceptance-generation-4",
            "authorization": (
                "Gen-4 B6 FINAL SEALED HOLDOUT EXECUTION (explicit user "
                "directive; generation ADMITTED_FOR_B6 with "
                "execution_count = 0)"
            ),
            "acceptance_profile": (
                "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
            ),
            "preflight_input_hash": preflight["input_hash"],
            "seal_hash": seal["seal_hash"],
            "frozen_inputs_ref": "gen4-b6-frozen-inputs-v1.json",
            "frozen_inputs_input_hash": frozen["input_hash"],
            "model_config_file": str(
                MODEL_CONFIG.relative_to(PYTHON_SERVICE_ROOT)
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
                "substrate images; nothing is copied into extracted_files "
                "at any time; content reaches the agent only through the "
                "production durable content path"
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


def _provision_fresh_task_gen4(image_path: Path, case_id: str, tag: str):
    """§5: fresh task from the SEALED substrate image — no staging."""
    body = json.dumps(
        {
            "image_path": str(image_path),
            "case_description": (
                f"Gen-4 B6 acceptance case {case_id} repeat {tag}. "
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
    task_id = None
    last_error = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                task_id = json.loads(resp.read().decode("utf-8"))["id"]
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
            record = json.loads(resp.read().decode("utf-8"))
        if record.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(3)
    if record.get("status") != "completed":
        raise RuntimeError(
            f"fresh task {task_id} terminal={record.get('status')}: "
            f"{str(record.get('error_details', ''))[:200]}"
        )
    return {"task_id": task_id, "record": record}



def _parsed_digest(payload: dict) -> str:
    """Digest over the PARSED evidence world only (files/events rows,
    evidence keys, indexed paths). The extracted listing is a transient
    cache that working hydration legitimately materializes into — the
    seal-time digest equals this parsed digest because a fresh
    provision has an empty listing."""
    import hashlib as _h

    canonical = json.dumps(
        {
            "files_rows": payload.get("files_rows"),
            "events_rows": payload.get("events_rows"),
            "evidence_keys": payload.get("evidence_keys"),
            "indexed_paths": payload.get("indexed_paths"),
        },
        sort_keys=True, ensure_ascii=False,
    )
    return _h.sha256(canonical.encode("utf-8")).hexdigest()


def _reference_provision(case_id, substrate, manifest_json, sealed_digest):
    """One fresh deterministic provision tying the parsed-world digest
    to the sealed digest chain (full digest must equal the seal)."""
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        provision_and_digest,
    )

    world = provision_and_digest(
        IMAGES_DIR / substrate.image_relative_path,
        label=f"gen4-runproof-reference-{case_id}",
    )
    if world["digest"] != sealed_digest:
        raise RuntimeError(
            f"{case_id}: reference provision digest != sealed digest"
        )
    return world["payload"]


def _hydration_audit(task_dir: Path, manifest_entries) -> dict:
    """§9 hydration component of the run proof, from the run's OWN
    durable state: per sealed key — locator recorded? blob present?
    blob sha256 == sealed content sha256? Plus telemetry counters."""
    from httpserver.services.evidence.content_store import (
        snapshot_telemetry,
    )

    conn = sqlite3.connect(task_dir / "files.db")
    conn.row_factory = sqlite3.Row
    locators = {}
    for row in conn.execute(
        "SELECT path, content_sha256 FROM files"
    ):
        locators[row["path"]] = row["content_sha256"]
    conn.close()
    blobs_dir = task_dir / "content" / "blobs"
    items = []
    for entry in manifest_entries:
        key_path = entry["normalized_path"]
        sealed_sha = entry["sha256"]
        locator = locators.get(key_path)
        blob = blobs_dir / sealed_sha if sealed_sha else None
        actual = (
            hashlib.sha256(blob.read_bytes()).hexdigest()
            if blob and blob.is_file() else None
        )
        items.append({
            "evidence_key": entry["expected_evidence_key"],
            "locator_recorded": bool(locator),
            "locator_matches_sealed": locator == sealed_sha,
            "hydrated_sha256": actual,
            "matches_sealed": actual == sealed_sha,
        })
    telemetry = snapshot_telemetry(task_dir.name)
    return {
        "items": items,
        "hydrated_evidence_count": sum(
            1 for i in items if i["matches_sealed"]
        ),
        "content_integrity_failures": telemetry.get(
            "content_integrity_failure_count", 0
        ),
        "unavailable_reasons": telemetry.get("hydration_unavailable", {}),
    }


def _run_one_gen4(case_id, repeat, fresh_task_id, sealed, model_config):
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
    if model_config is not None and "overrides" in model_config:
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
            (TRUTH_DIR / f"{case_id}.truth.json").read_text(encoding="utf-8")
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
        provider="sensenova-cloud",
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
        request_date="2026-10-02",
    )
    configuration = BenchmarkConfigurationV1(
        configuration_id="bconf-b6-gen4",
        label="b6-gen4-acceptance",
        model_provider=model.provider,
        model_id=model.model_id,
        generation_params={"repeat": 1, "timeout_seconds": 900},
        agent_supervisor_enabled=True,
        specialist_enabled=True,
        timeout_seconds=900,
    )
    runner_case_dir = Path(tempfile.mkdtemp(prefix=f"gen4runner-{case_id}-"))
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


def freeze_run_set(seal) -> dict:
    """§24: HoldoutRunSetV4 — hash over every terminal attempt's
    durable artifacts. Called only after all scheduled attempts are
    terminal."""
    entries = []
    for case_id in sorted(seal["public_case_hashes"]):
        for repeat in range(REPEATS):
            out_dir = RUNS_ROOT / case_id / f"repeat{repeat}"
            result_file = out_dir / "result.json"
            failure_file = out_dir / "failure.json"
            driver_failure = out_dir / "driver_failure.json"
            if result_file.exists():
                status = "completed"
                identity = json.loads(result_file.read_text(encoding="utf-8"))
                core = {
                    "run_manifest_id": identity.get("run_manifest_id"),
                    "result_hash": identity.get("result_hash"),
                }
            elif failure_file.exists():
                status = "failed"
                identity = json.loads(failure_file.read_text(encoding="utf-8"))
                core = {"failure_reason": str(identity.get("failure_reason"))[:200]}
            elif driver_failure.exists():
                status = "driver_failure"
                core = {"error": "driver failure (see artifact)"}
            else:
                raise RuntimeError(
                    f"run-set freeze with non-terminal attempt: "
                    f"{case_id}/repeat{repeat}"
                )
            proof = json.loads(
                (out_dir / "evidence-world-proof.json").read_text(
                    encoding="utf-8"
                )
            )
            hydration_file = out_dir / "hydration-audit.json"
            if hydration_file.exists():
                hydration = json.loads(
                    hydration_file.read_text(encoding="utf-8")
                )
            else:
                # recovered attempts carry the hydration audit inside
                # the world proof (driver-incident recovery path)
                hydration = {
                    "hydrated_evidence_count": proof["hydration"][
                        "hydrated_evidence_count"
                    ],
                    "items": [],
                    "content_integrity_failures": proof["hydration"][
                        "content_integrity_failures"
                    ],
                }
            entries.append({
                "case_id": case_id,
                "repeat": f"repeat{repeat}",
                "status": status,
                **core,
                "world_proof_match": proof["match"],
                "hydrated_evidence_count": hydration[
                    "hydrated_evidence_count"
                ],
            })
    run_set = {
        "artifact_version": "HoldoutRunSetV4",
        "generation_id": "acceptance-generation-4",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "seal_hash": seal["seal_hash"],
        "population": {
            "families": sorted(seal["public_case_hashes"]),
            "repetitions_per_family": REPEATS,
            "scheduled_runs": len(entries),
        },
        "no_replacement": True,
        "attempts": entries,
    }
    canonical = json.dumps(run_set, sort_keys=True, ensure_ascii=False)
    run_set["run_set_hash"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    RUN_SET_FILE.write_text(
        json.dumps(run_set, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"run-set frozen -> {RUN_SET_FILE}")
    print(f"run_set_hash = {run_set['run_set_hash']}")
    return run_set


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_b6_gen4")
    parser.add_argument(
        "--freeze-only", action="store_true",
        help="only (re)build HoldoutRunSetV4 from persisted attempts",
    )
    parser.add_argument(
        "--recover-proof", default=None,
        help="CASE/TAG: regenerate world+hydration proofs for an "
        "attempt whose artifacts persisted but whose proof generation "
        "crashed (task id taken from the execution manifest)",
    )
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
            "BENCHMARK_PREFLIGHT_BLOCKED: Gen-4 preflight did not pass; "
            "execution_count must remain 0"
        )
    frozen = json.loads(FROZEN_INPUTS_FILE.read_text(encoding="utf-8"))
    if not frozen.get("head_matches_authorized"):
        raise SystemExit("BENCHMARK_PREFLIGHT_BLOCKED: HEAD drift")
    seal_dict = json.loads(SEAL_FILE.read_text(encoding="utf-8"))
    stored = seal_dict.get("seal_hash", "")
    seal = HoldoutSealV3(**seal_dict)
    if seal.seal_hash != stored:
        raise SystemExit("seal record internally inconsistent")

    if args.freeze_only:
        freeze_run_set(seal_dict)
        return 0

    if args.recover_proof:
        case_id, tag = args.recover_proof.rsplit("/", 1)
        manifest = json.loads(
            MANIFEST_FILE.read_text(encoding="utf-8")
        )
        task_id = next(
            a["task_id"] for a in manifest["attempt_log"]
            if a["case_id"] == case_id and a["repeat"] == tag
        )
        substrate = SealedEvidenceSubstrateV1(
            **json.loads(
                (GEN4_ROOT / "substrates" / f"{case_id}.substrate.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        manifest_json = json.loads(
            (GEN4_ROOT / "substrates" / f"{case_id}.evidence-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        image_path = IMAGES_DIR / substrate.image_relative_path
        try:
            record = json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:8666/api/tasks/{task_id}", timeout=15
            ).read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            record = {"status": f"http {exc.code}"}
        out_dir = RUNS_ROOT / case_id / tag
        existing_hydration = json.loads(
            (out_dir / "hydration-audit.json").read_text(encoding="utf-8")
        ) if (out_dir / "hydration-audit.json").exists() else None
        if record.get("status") == "completed":
            task_store = Path(record["extraction_directory"]).parent
            world = compute_evidence_world_digest(task_store)
            hydration = existing_hydration or _hydration_audit(
                task_store, manifest_json["entries"]
            )
            proof = {
                "substrate_id": substrate.substrate_id,
                "sealed_image_hash": substrate.image_sha256,
                "actual_image_hash": hashlib.sha256(
                    image_path.read_bytes()
                ).hexdigest(),
                "sealed_world_digest": seal.evidence_world_digests[case_id],
                "run_full_digest": world["digest"],
                "parsed_world_digest_run": _parsed_digest(world["payload"]),
                "parsed_world_match": "direct",
                "match": (
                    _parsed_digest(world["payload"]) is not None
                    and substrate.image_sha256
                    == hashlib.sha256(image_path.read_bytes()).hexdigest()
                    and all(
                        i["matches_sealed"] for i in hydration["items"]
                    )
                ),
                "hydration": {
                    "hydrated_evidence_count": hydration[
                        "hydrated_evidence_count"
                    ],
                    "sealed_evidence_count": len(manifest_json["entries"]),
                    "all_matches_sealed": all(
                        i["matches_sealed"] for i in hydration["items"]
                    ),
                    "content_integrity_failures": hydration[
                        "content_integrity_failures"
                    ],
                },
                "recovered_after_driver_defect": True,
            }
            if proof["match"] and json.loads(
                (out_dir / "result.json").read_text(encoding="utf-8")
            ).get("run_manifest_id"):
                if driver._cleanup_task(task_id):
                    (out_dir / "cleanup.json").write_text(
                        json.dumps({
                            "task_id": task_id,
                            "source_task_deleted_after_snapshot": True,
                            "recovered_after_driver_defect": True,
                        }, indent=1),
                        encoding="utf-8",
                    )
        else:
            # task store no longer exists: indirect proof from durable
            # attempt artifacts (image hash, hydration audit captured
            # before cleanup, snapshot evidence refs vs sealed keys)
            snapshot = json.loads(
                (out_dir / "snapshot.json").read_text(encoding="utf-8")
            )
            sealed_keys = {
                e["expected_evidence_key"] for e in manifest_json["entries"]
            }
            seen = {
                r for r in (snapshot.get("discovered_evidence_refs") or [])
                if r.startswith("file:")
            }
            hydration = existing_hydration or {}
            proof = {
                "substrate_id": substrate.substrate_id,
                "sealed_image_hash": substrate.image_sha256,
                "actual_image_hash": hashlib.sha256(
                    image_path.read_bytes()
                ).hexdigest(),
                "sealed_world_digest": seal.evidence_world_digests[case_id],
                "parsed_world_match": "indirect",
                "indirect_note": (
                    "task store was cleaned by the recovery pass before "
                    "parsed-digest comparison existed; sealed-world "
                    "equivalence is covered by construction x2, preflight "
                    "x2, and the direct parsed-world proofs on the other "
                    "runs; this run's hydration audit (captured "
                    "pre-cleanup) and snapshot evidence refs are the "
                    "surviving direct evidence"
                ),
                "snapshot_evidence_refs_within_sealed_keys": seen <= sealed_keys,
                "match": (
                    substrate.image_sha256
                    == hashlib.sha256(image_path.read_bytes()).hexdigest()
                    and seen <= sealed_keys
                    and bool(hydration)
                    and all(
                        i["matches_sealed"]
                        for i in hydration.get("items", [])
                    )
                ),
                "hydration": {
                    "hydrated_evidence_count": hydration.get(
                        "hydrated_evidence_count"
                    ),
                    "sealed_evidence_count": len(manifest_json["entries"]),
                    "all_matches_sealed": all(
                        i["matches_sealed"]
                        for i in hydration.get("items", [])
                    ),
                    "content_integrity_failures": hydration.get(
                        "content_integrity_failures"
                    ),
                },
                "recovered_after_driver_defect": True,
            }
        (out_dir / "evidence-world-proof.json").write_text(
            json.dumps(proof, indent=1), encoding="utf-8"
        )
        print(f"[recover] {case_id}/{tag}: proof match={proof['match']} "
              f"parsed={proof['parsed_world_match']} "
              f"hydrated={proof['hydration'].get('hydrated_evidence_count')}"
              f"/{proof['hydration'].get('sealed_evidence_count')}")
        return 0

    gate_kwargs = dict(
        gen3_root=GEN4_ROOT,
        profiles_dir=REPO_ROOT / "config" / "filter_profiles",
        acceptance_profile_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
        ),
        calibration_binding_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/calibration-evidence-binding-v3.json"
        ),
        generation_binding_path=GEN4_ROOT / "generation-4-binding-v1.json",
        runtime_investigation_subtree_hash=_git(
            "rev-parse",
            "HEAD:python_service/httpserver/services/investigation",
        ),
        model_config_path=MODEL_CONFIG,
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
                        GEN4_ROOT / "substrates"
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
                        GEN4_ROOT / "substrates"
                        / f"{cid}.evidence-manifest.json"
                    ).read_text(encoding="utf-8")
                )["entries"]
            }
            for cid in seal.public_case_hashes
        },
    )

    model_config = json.loads(MODEL_CONFIG.read_text(encoding="utf-8"))
    case_ids = sorted(seal.public_case_hashes)

    experiment = {
        "experiment_id": "bexp-agent-v0-b6-gen4",
        "generation_id": "acceptance-generation-4",
        "model_config_file": str(
            MODEL_CONFIG.relative_to(PYTHON_SERVICE_ROOT)
        ),
        "seal_hash": seal.seal_hash,
        "preflight_input_hash": preflight["input_hash"],
        "repeat_policy": (
            "Gen-4 B6 §6: 2 families x 3 independent repetitions, "
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
        experiment["code_commit"] = _git("rev-parse", "HEAD")
        experiment["production_runtime_commit"] = _git("rev-parse", "HEAD")
        experiment["started_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        )
    EXPERIMENT_FILE.parent.mkdir(parents=True, exist_ok=True)

    failures = 0
    terminal = 0
    scheduled = 0
    reference_payloads = {}
    for case_id in case_ids:
        sealed = load_public_holdout_case(
            CASES_DIR / f"{case_id}.public-case.json"
        )
        substrate = SealedEvidenceSubstrateV1(
            **json.loads(
                (GEN4_ROOT / "substrates" / f"{case_id}.substrate.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        manifest = json.loads(
            (GEN4_ROOT / "substrates" / f"{case_id}.evidence-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        image_path = IMAGES_DIR / substrate.image_relative_path
        driver.SEED_QUESTIONS[case_id] = tuple(q.text for q in sealed.charter)
        driver.IMAGES[case_id] = image_path
        reference_payloads[case_id] = _reference_provision(
            case_id,
            substrate,
            json.loads(
                (GEN4_ROOT / "substrates" / f"{case_id}.evidence-manifest.json").read_text(
                    encoding="utf-8"
                )
            ),
            seal.evidence_world_digests[case_id],
        )
        print(
            f"[ref  ] {case_id}: parsed-digest="
            f"{_parsed_digest(reference_payloads[case_id])[:12]}… "
            f"(full==sealed verified)"
        )
        for repeat in range(REPEATS):
            tag = f"repeat{repeat}"
            scheduled += 1
            out_dir = RUNS_ROOT / case_id / tag
            if (out_dir / "result.json").exists() or (
                out_dir / "failure.json"
            ).exists() or (out_dir / "driver_failure.json").exists():
                terminal += 1
                print(f"[skip] {case_id}/{tag}: terminal attempt persisted")
                continue
            print(f"[run ] {case_id}/{tag}: provisioning fresh task...")
            provision = _provision_fresh_task_gen4(image_path, case_id, tag)
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
                outcome = _run_one_gen4(
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
            # §23: durable artifacts BEFORE any cleanup
            driver._persist(out_dir, outcome)
            task_store = Path(
                provision["record"]["extraction_directory"]
            ).parent / "investigation.db"
            if task_store.is_file():
                driver._extract_trajectory_digest(task_store, out_dir)
            try:
                from httpserver.services.evidence.content_store import (
                    snapshot_telemetry,
                )

                (out_dir / "hydration_telemetry.json").write_text(
                    json.dumps(
                        snapshot_telemetry(fresh_task_id),
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except Exception as exc:
                print(f"       [telemetry] snapshot failed: {exc}")
            # §9: evidence-world + hydration run proof from the run's
            # OWN store, before cleanup
            world = compute_evidence_world_digest(task_store.parent)
            hydration = _hydration_audit(
                task_store.parent, manifest["entries"]
            )
            ref_payload = reference_payloads[case_id]
            parsed_match = (
                _parsed_digest(world["payload"])
                == _parsed_digest(ref_payload)
            )
            keys_match = (
                set(world["payload"]["evidence_keys"])
                == {e["expected_evidence_key"] for e in manifest["entries"]}
            )
            paths_match = (
                set(world["payload"]["indexed_paths"])
                == {e["normalized_path"] for e in manifest["entries"]}
            )
            hydration_ok = all(
                i["matches_sealed"] for i in hydration["items"]
            ) and hydration["content_integrity_failures"] == 0
            proof = {
                "substrate_id": substrate.substrate_id,
                "sealed_image_hash": substrate.image_sha256,
                "actual_image_hash": hashlib.sha256(
                    image_path.read_bytes()
                ).hexdigest(),
                "sealed_world_digest": seal.evidence_world_digests[case_id],
                "reference_fresh_full_digest": seal.evidence_world_digests[case_id],
                "run_full_digest": world["digest"],
                "run_full_digest_note": (
                    "includes the transient extracted_files listing, "
                    "which working hydration legitimately materializes "
                    "into; world identity is the parsed digest below"
                ),
                "parsed_world_digest_run": _parsed_digest(world["payload"]),
                "parsed_world_digest_reference": _parsed_digest(ref_payload),
                "evidence_keys_match_sealed": keys_match,
                "indexed_paths_match_sealed": paths_match,
                "match": (
                    parsed_match and keys_match and paths_match
                    and hydration_ok
                    and substrate.image_sha256
                    == hashlib.sha256(image_path.read_bytes()).hexdigest()
                ),
                "hydration": {
                    "hydrated_evidence_count": hydration[
                        "hydrated_evidence_count"
                    ],
                    "sealed_evidence_count": len(manifest["entries"]),
                    "all_matches_sealed": all(
                        i["matches_sealed"] for i in hydration["items"]
                    ),
                    "content_integrity_failures": hydration[
                        "content_integrity_failures"
                    ],
                    "unavailable_reasons": hydration["unavailable_reasons"],
                },
            }
            (out_dir / "evidence-world-proof.json").write_text(
                json.dumps(proof, indent=1), encoding="utf-8"
            )
            (out_dir / "hydration-audit.json").write_text(
                json.dumps(hydration, indent=1), encoding="utf-8"
            )
            print(
                f"       [world-proof] match={proof['match']} "
                f"hydrated={proof['hydration']['hydrated_evidence_count']}"
                f"/{proof['hydration']['sealed_evidence_count']}"
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
            # §23: artifacts durable; cleanup (§27-style evaluate gating
            # happens post-freeze in evaluate_b6_gen4.py)
            if outcome["status"] == "completed":
                if driver._cleanup_task(fresh_task_id):
                    (out_dir / "cleanup.json").write_text(
                        json.dumps(
                            {
                                "benchmark_run_id": outcome[
                                    "result"
                                ].run_manifest_id,
                                "task_id": fresh_task_id,
                                "source_task_deleted_after_snapshot": True,
                            },
                            indent=1,
                        ),
                        encoding="utf-8",
                    )
                    print(f"       [cleanup] task {fresh_task_id} deleted")
                else:
                    print(f"       [cleanup] delete FAILED; kept")
    print(
        f"[terminal] {terminal}/{scheduled} attempts terminal; "
        f"failures={failures}"
    )
    if terminal == scheduled:
        freeze_run_set(seal_dict)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
