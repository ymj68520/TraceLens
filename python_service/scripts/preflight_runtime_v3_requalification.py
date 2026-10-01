"""RuntimeBaselineV3 requalification preflight (zero model calls).

Records the §2 evidence: git/runtime identity, artifact hashes, frozen
contract versions, service health. Writes preflight.json under the
requalification results root.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import urllib.request
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PYTHON_SERVICE_ROOT.parent
RESULTS_ROOT = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "requalification" / "runtime-v3"
)
FROZEN_RUNTIME_HEAD = "d213145dc29b05fc8b7bbe83ab3070e572cbca71"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> int:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    head = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    status = git("status", "--porcelain")
    # runtime subtree identity: any change to production code changes these
    subtree_hashes = {
        str(p): git("rev-parse", f"HEAD:{p}")
        for p in (
            "python_service/httpserver",
            "python_service/scripts/run_p8b_baseline.py",
            "python_service/scripts/canary_content_hydration.py",
            "src",
            "config",
        )
    }
    runtime_is_frozen_head = head == FROZEN_RUNTIME_HEAD
    # if HEAD moved, enumerate the exact runtime delta; only enumerated
    # measurement-infrastructure files may differ (never src/ or config/).
    allowed_delta_files = {
        # additive observability + driver content-mode flag (requalification
        # instrumentation; no semantics change — enforced by unit suite)
        "python_service/httpserver/services/evidence/content_store.py",
        "python_service/scripts/run_p8b_baseline.py",
    }
    runtime_delta = []
    if not runtime_is_frozen_head:
        changed = git(
            "diff", "--name-only", FROZEN_RUNTIME_HEAD, "HEAD", "--",
            "python_service/httpserver", "python_service/scripts", "src", "config",
        ).splitlines()
        runtime_delta = [line for line in changed if line.strip()]
    delta_allowed = runtime_is_frozen_head or (
        set(runtime_delta) <= allowed_delta_files
        and not git(
            "diff", "--name-only", FROZEN_RUNTIME_HEAD, "HEAD", "--", "src", "config"
        ).strip()
    )

    artifacts = {
        "runtime_baseline_v3": sha256_file(
            PYTHON_SERVICE_ROOT / "benchmarks/profiles/agent-v0-runtime-baseline-v3.json"
        ),
        "content_hydration_contract_doc": sha256_file(
            REPO_ROOT / "docs/specs/evidence-content-hydration-contract.md"
        ),
        "content_store_module": sha256_file(
            PYTHON_SERVICE_ROOT
            / "httpserver/services/evidence/content_store.py"
        ),
        "tool_registry": sha256_file(
            PYTHON_SERVICE_ROOT
            / "httpserver/services/investigation/agent_tools/registry.py"
        ),
        "tool_definitions": sha256_file(
            PYTHON_SERVICE_ROOT
            / "httpserver/services/investigation/agent_tools/definitions.py"
        ),
        "investigation_prompts": sha256_file(
            PYTHON_SERVICE_ROOT / "httpserver/services/investigation/prompts.py"
        ),
        "agent_supervisor": sha256_file(
            PYTHON_SERVICE_ROOT
            / "httpserver/services/investigation/agent_supervisor.py"
        ),
        "agent_specialist_executor": sha256_file(
            PYTHON_SERVICE_ROOT
            / "httpserver/services/investigation/agent_specialist_executor.py"
        ),
        "agent_specialist_result": sha256_file(
            PYTHON_SERVICE_ROOT
            / "httpserver/services/investigation/agent_specialist_result.py"
        ),
        "acquisition_snapshot": sha256_file(
            PYTHON_SERVICE_ROOT / "httpserver/services/investigation/acquisition.py"
        ),
        "agent_finalization": sha256_file(
            PYTHON_SERVICE_ROOT
            / "httpserver/services/investigation/agent_finalization.py"
        ),
        "agent_transitions": sha256_file(
            PYTHON_SERVICE_ROOT
            / "httpserver/services/investigation/agent_transitions.py"
        ),
        "benchmark_runner": sha256_file(
            PYTHON_SERVICE_ROOT
            / "httpserver/services/benchmarks/runner.py"
        ),
        "b2_driver": sha256_file(
            PYTHON_SERVICE_ROOT / "scripts/run_p8b_baseline.py"
        ),
    }
    health = {}
    for name, url in (
        ("cpp_8666", "http://127.0.0.1:8666/api/health"),
        ("python_8090", "http://127.0.0.1:8090/health"),
    ):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                health[name] = "healthy" if resp.status == 200 else f"http {resp.status}"
        except Exception as exc:
            health[name] = f"unreachable: {type(exc).__name__}"

    record = {
        "record": "runtime-v3-requalification-preflight:v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "git": {
            "branch": branch,
            "head": head,
            "frozen_runtime_head": FROZEN_RUNTIME_HEAD,
            "runtime_is_frozen_head": runtime_is_frozen_head,
            "runtime_delta_vs_frozen_head": runtime_delta or "HEAD==frozen",
            "runtime_delta_allowed": delta_allowed,
            "subtree_hashes": subtree_hashes,
            "worktree_dirty_paths": [
                line for line in status.splitlines() if line.strip()
            ],
        },
        "runtime_epoch": "AgentV0RuntimeBaselineV3 (historical: V2, PreCalibration V1/V4/V6-era)",
        "contracts": {
            "supervisor": "v2 (frozen, A1 R2 disposition)",
            "specialist_proposal": "SpecialistResultProposalV1 + deterministic finalizer (A1-T, 546d0d2c)",
            "typed_handle": "decision schema v3 (A1-H, f7b02af6)",
            "snapshot": "S4 evidence snapshot admission (A1-S, f711851c) — metadata-only",
            "finalization_gate": "UNINTEGRATED_COMPLETED_DELEGATION / COVERAGE_NOT_TERMINAL / REQUIRED_QUESTION_OPEN (unchanged)",
            "content_hydration": "evidence-content-hydration:v1 (FROZEN d213145d)",
        },
        "artifact_sha256": artifacts,
        "service_health": health,
    }
    ok = delta_allowed and all(v == "healthy" for v in health.values())
    record["preflight_status"] = "PASS" if ok else "FAILED"
    out = RESULTS_ROOT / "preflight.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    print(json.dumps({k: record[k] for k in (
        "preflight_status", "git", "runtime_epoch", "service_health"
    )}, indent=2))
    print(f"artifact hashes -> {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
