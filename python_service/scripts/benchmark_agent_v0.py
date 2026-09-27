"""Benchmark CLI (P8A §83-§86).

    python -m scripts.benchmark_agent_v0 --case <dir> --config <id>
        --repeat N --output <dir> [--dry-run] [--evaluate-only]

- ``--dry-run``: dataset/hash/manifest/config validation, NO model call;
- ``--evaluate-only``: recompute metrics from a persisted snapshot, NO
  Agent execution; same inputs reproduce the same result hash (§84);
- a configuration change is always a NEW run (§57).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from httpserver.services.benchmarks.benchmark_case import (  # noqa: E402
    BenchmarkCaseV1,
    verify_dataset_files,
)
from httpserver.services.benchmarks.runner import (  # noqa: E402
    BenchmarkRunner,
    evaluate_only,
    current_git_identity,
)
from httpserver.services.benchmarks.run_manifest import (  # noqa: E402
    BenchmarkConfigurationV1,
    BenchmarkRunManifestV1,
    collect_environment_digest,
)
from httpserver.services.benchmarks.snapshot import (  # noqa: E402
    BenchmarkRunSnapshotV1,
)
from httpserver.services.benchmarks.truth_manifest import (  # noqa: E402
    ReachabilityManifestV1,
    TruthManifestV1,
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_case(case_dir: Path) -> tuple[BenchmarkCaseV1, TruthManifestV1]:
    case = BenchmarkCaseV1(**_load_json(case_dir / "case.json"))
    truth = TruthManifestV1(
        **_load_json(case_dir / "truth_manifest.json")
    )
    return case, truth


def _load_reachability(case_dir: Path) -> ReachabilityManifestV1:
    path = case_dir / "reachability.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"reachability manifest missing: {path} (run case preparation)"
        )
    return ReachabilityManifestV1(**_load_json(path))


def cmd_dry_run(args) -> int:
    case_dir = Path(args.case)
    case, truth = _load_case(case_dir)
    violations = verify_dataset_files(case.dataset, case_dir / "dataset")
    if truth.manifest_id != case.truth_manifest_id:
        violations.append("truth manifest id mismatch")
    if truth.input_hash != case.truth_manifest_hash:
        violations.append("truth manifest hash mismatch")
    if args.config:
        BenchmarkConfigurationV1(**_load_json(Path(args.config)))
    for violation in violations:
        print(f"VIOLATION: {violation}")
    print("DRY-RUN:", "FAIL" if violations else "OK (no model executed)")
    return 1 if violations else 0


def cmd_evaluate_only(args) -> int:
    case_dir = Path(args.case)
    case, truth = _load_case(case_dir)
    reachability = _load_reachability(case_dir)
    snapshot_payload = _load_json(Path(args.snapshot))
    manifest_payload = _load_json(Path(args.run_manifest))
    manifest = BenchmarkRunManifestV1(**manifest_payload)
    snapshot = BenchmarkRunSnapshotV1(**snapshot_payload)
    result = evaluate_only(
        run_manifest=manifest,
        truth_manifest=truth,
        reachability=reachability,
        snapshot=snapshot,
    )
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{result.run_manifest_id}.result.json"
    out_path.write_text(result.model_dump_json(), encoding="utf-8")
    print(f"EVALUATED result_hash={result.result_hash} -> {out_path}")
    if args.expect_result_hash and (
        args.expect_result_hash != result.result_hash
    ):
        print(
            f"REPRODUCIBILITY FAIL: expected "
            f"{args.expect_result_hash}, got {result.result_hash}"
        )
        return 1
    return 0


def cmd_run(args) -> int:
    case_dir = Path(args.case)
    case, truth = _load_case(case_dir)
    reachability = _load_reachability(case_dir)
    config_payload = _load_json(Path(args.config))
    configuration = BenchmarkConfigurationV1(**config_payload)
    from httpserver.services.benchmarks.run_manifest import ModelIdentityV1

    model = ModelIdentityV1(
        provider=configuration.model_provider,
        model_id=configuration.model_id,
    )
    commit, branch = current_git_identity(PYTHON_SERVICE_ROOT.parent)
    commit = args.git_commit or commit

    def executor(run_manifest):
        # P8A smoke path: the production executor seam is injected by the
        # caller; the CLI itself never fakes Agent semantics (§27).  A
        # persisted snapshot from a prior production run may be supplied.
        if not args.snapshot:
            raise RuntimeError(
                "P8A CLI requires --snapshot (a persisted run snapshot); "
                "live Agent execution lands in P8B"
            )
        return {"snapshot": _load_json(Path(args.snapshot))}

    runner = BenchmarkRunner(
        executor=executor, git_commit=commit, git_branch=branch
    )
    completed = 0
    for repeat_index in range(max(1, args.repeat)):
        outcome = runner.run(
            case=case,
            truth_manifest=truth,
            reachability=reachability,
            configuration=configuration,
            model=model,
            repeat_index=repeat_index,
            environment=collect_environment_digest(),
        )
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = outcome["run_manifest"]
        (output_dir / f"{manifest.benchmark_run_id}.manifest.json").write_text(
            manifest.model_dump_json(), encoding="utf-8"
        )
        if outcome["status"] == "completed":
            result = outcome["result"]
            (output_dir / f"{manifest.benchmark_run_id}.result.json").write_text(
                result.model_dump_json(), encoding="utf-8"
            )
            completed += 1
            print(
                f"RUN {manifest.benchmark_run_id} completed "
                f"result_hash={result.result_hash}"
            )
        else:
            failure = outcome["failure"]
            (output_dir / f"{manifest.benchmark_run_id}.failure.json").write_text(
                failure.model_dump_json(), encoding="utf-8"
            )
            print(
                f"RUN {manifest.benchmark_run_id} FAILED: "
                f"{failure.failure_reason}"
            )
    return 0 if completed == max(1, args.repeat) else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="benchmark_agent_v0",
        description="Agent v0 benchmark harness (P8A measurement only)",
    )
    parser.add_argument("--case", required=True, help="benchmark case dir")
    parser.add_argument("--config", help="benchmark configuration JSON")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", default="benchmark_results")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate only, no LLM"
    )
    parser.add_argument(
        "--evaluate-only",
        action="store_true",
        help="recompute metrics from a persisted snapshot",
    )
    parser.add_argument("--snapshot", help="persisted run snapshot JSON")
    parser.add_argument("--run-manifest", help="persisted run manifest JSON")
    parser.add_argument(
        "--expect-result-hash",
        help="evaluate-only reproducibility check (§84)",
    )
    parser.add_argument("--git-commit", help="override recorded commit")
    args = parser.parse_args(argv)

    if args.dry_run:
        return cmd_dry_run(args)
    if args.evaluate_only:
        if not (args.snapshot and args.run_manifest):
            parser.error(
                "--evaluate-only requires --snapshot and --run-manifest"
            )
        return cmd_evaluate_only(args)
    if not args.config:
        parser.error("--run requires --config")
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
