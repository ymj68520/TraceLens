"""Benchmark runner + ablation configurations (P8A §24-§28, §65-§69).

The runner freezes the BenchmarkRunManifest BEFORE execution (§57),
executes the requested configuration through PRODUCTION service APIs
only (§27 — no policy monkeypatching, no direct Finding/WorkingState
writes, no Finalization bypass), collects the immutable snapshot, and
evaluates deterministically.  Ablation stages express the frozen
architecture levels (§24); unsupported historical comparisons are marked,
never faked (§24/§25).
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..report_runtime.canonical import sha256_hex
from .benchmark_case import BenchmarkCaseV1, verify_dataset_files
from .metrics import BenchmarkResultV1
from .run_manifest import (
    BenchmarkConfigurationV1,
    BenchmarkRunManifestV1,
    EnvironmentDigestV1,
    ModelIdentityV1,
)
from .truth_manifest import ReachabilityManifestV1, TruthManifestV1

RUNNER_VERSION = "benchmark-runner:v1"


class RunStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class AblationStage(str, Enum):
    """§24 frozen ablation stages.  ``full_graph`` is expressed but may be
    marked unsupported rather than faked."""

    A0_NON_AGENT_BASELINE = "A0_non_agent_baseline"
    A1_SUPERVISOR_TOOLS = "A1_supervisor_tools"
    A2_PLAYBOOK_SPECIALIST = "A2_playbook_specialist"
    A3_CORRELATION = "A3_correlation"
    A4_SEMANTIC_VERIFIER = "A4_semantic_verifier"
    A5_SELECTIVE_GRAPH = "A5_selective_graph"
    A6_FULL_ARCHITECTURE = "A6_full_architecture"


_GRAPH_MODE_BY_STAGE = {
    AblationStage.A0_NON_AGENT_BASELINE: "none",
    AblationStage.A1_SUPERVISOR_TOOLS: "none",
    AblationStage.A2_PLAYBOOK_SPECIALIST: "none",
    AblationStage.A3_CORRELATION: "none",
    AblationStage.A4_SEMANTIC_VERIFIER: "none",
    AblationStage.A5_SELECTIVE_GRAPH: "selective",
    AblationStage.A6_FULL_ARCHITECTURE: "full",
}


def ablation_configuration(
    stage: AblationStage,
    *,
    model_provider: str = "",
    model_id: str = "",
    label_suffix: str = "",
) -> BenchmarkConfigurationV1:
    """§24: one configuration per frozen stage.  Stages are cumulative —
    A4 keeps everything A3 enabled."""
    supervisor = stage is not AblationStage.A0_NON_AGENT_BASELINE
    index = list(AblationStage).index(stage)
    return BenchmarkConfigurationV1(
        label=stage.value + label_suffix,
        model_provider=model_provider if supervisor else "none",
        model_id=model_id if supervisor else "deterministic-baseline",
        agent_supervisor_enabled=supervisor,
        playbook_enabled=index >= 2,
        specialist_enabled=index >= 2,
        correlation_enabled=index >= 3,
        semantic_verifier_enabled=index >= 4,
        graph_mode=_GRAPH_MODE_BY_STAGE[stage],
        report_enabled=stage is AblationStage.A6_FULL_ARCHITECTURE,
    )


class GraphComparisonSupport(str, Enum):
    """§24: honest expression of the Graph comparison axis."""

    supported = "supported"
    unsupported_historical_comparison = (
        "unsupported_historical_comparison"
    )


class AblationContractV1(BaseModel):
    """§24 ablation axes for one benchmark execution, including the
    explicit Graph-comparison support statement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: str = "ablation-contract:v1"
    stages: tuple[AblationStage, ...] = ()
    graph_no_graph: GraphComparisonSupport = (
        GraphComparisonSupport.unsupported_historical_comparison
    )
    graph_note: str = ""

    @model_validator(mode="after")
    def _validate(self):
        if not self.stages:
            raise ValueError("ablation contract requires at least one stage")
        return self


class FailedRunRecordV1(BaseModel):
    """§65: a failed run is NEVER deleted; diagnostics are preserved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_manifest: dict
    failure_layer: str
    failure_reason: str
    partial_telemetry: dict = Field(default_factory=dict)
    failed_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if isinstance(data, dict) and not data.get("failed_at"):
            data["failed_at"] = datetime.now(timezone.utc).isoformat()
        return data


class BenchmarkRunner:
    """§26 runner pipeline.  ``executor`` is the injection seam for the
    production investigation path (real service orchestration in P8B; a
    deterministic fixture path for the P8A smoke).  The runner itself
    never changes production semantic rules (§27)."""

    version = RUNNER_VERSION

    def __init__(
        self,
        *,
        executor: Callable[[BenchmarkRunManifestV1], dict],
        git_commit: str = "",
        git_branch: str = "",
        runtime_version: str = RUNNER_VERSION,
    ):
        self._executor = executor
        self._git_commit = git_commit
        self._git_branch = git_branch
        self._runtime_version = runtime_version

    # -- §85 dry-run -------------------------------------------------------

    def dry_run(
        self,
        *,
        case: BenchmarkCaseV1,
        truth_manifest: TruthManifestV1,
        configuration: BenchmarkConfigurationV1,
        dataset_base_dir,
        reachability: Optional[ReachabilityManifestV1] = None,
    ) -> list[str]:
        """§85: validate without any model execution.  Returns violations
        (empty = OK)."""
        violations: list[str] = []
        violations.extend(verify_dataset_files(case.dataset, dataset_base_dir))
        if truth_manifest.case_id != case.case_id:
            violations.append(
                f"truth manifest case mismatch: "
                f"{truth_manifest.case_id!r} != {case.case_id!r}"
            )
        if truth_manifest.manifest_id != case.truth_manifest_id:
            violations.append("truth manifest id does not match the case ref")
        if truth_manifest.input_hash != case.truth_manifest_hash:
            violations.append("truth manifest hash does not match the case ref")
        if reachability is not None:
            known = {
                item.truth_evidence_id
                for item in truth_manifest.all_evidence_items()
            }
            for record in reachability.records:
                if record.truth_evidence_id not in known:
                    violations.append(
                        f"reachability record for unknown truth evidence: "
                        f"{record.truth_evidence_id}"
                    )
        return violations

    # -- §26/§57 main pipeline ----------------------------------------------

    def run(
        self,
        *,
        case: BenchmarkCaseV1,
        truth_manifest: TruthManifestV1,
        reachability: ReachabilityManifestV1,
        configuration: BenchmarkConfigurationV1,
        model: ModelIdentityV1,
        repeat_index: int = 0,
        environment: Optional[EnvironmentDigestV1] = None,
    ) -> dict:
        """Freeze the run manifest, execute, evaluate.  Returns
        {"status", "result"|"failure"} — a failed run still carries its
        manifest and diagnostics (§65)."""
        run_manifest = BenchmarkRunManifestV1(
            case_id=case.case_id,
            case_version=case.case_version,
            case_hash=case.input_hash,
            dataset_hash=case.dataset.dataset_hash,
            truth_manifest_id=truth_manifest.manifest_id,
            truth_manifest_hash=truth_manifest.input_hash,
            tracelens_git_commit=self._git_commit,
            tracelens_branch=self._git_branch,
            model=model,
            runtime_version=self._runtime_version,
            environment=environment or EnvironmentDigestV1(),
            configuration_id=configuration.configuration_id,
            configuration_hash=configuration.input_hash,
            cache_state=configuration.cache_state,
            started_at=datetime.now(timezone.utc).isoformat(),
            terminal_status="running",
        )
        try:
            outcome = self._executor(run_manifest)
            snapshot_payload = outcome["snapshot"]
            from .snapshot import BenchmarkRunSnapshotV1

            snapshot = BenchmarkRunSnapshotV1(**snapshot_payload)
            from .metrics import structural_hard_gates

            gates = [
                {
                    "gate_id": gate.gate_id,
                    "passed": gate.passed,
                    "violations": list(gate.violations),
                }
                for gate in structural_hard_gates(snapshot)
            ]
            completed_manifest = BenchmarkRunManifestV1(
                **{
                    **run_manifest.model_dump(mode="json"),
                    "terminal_status": "completed",
                    "completed_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }
            )
            from .availability import compute_availability_summary

            availability = compute_availability_summary(
                truth_manifest, reachability
            )
            result = BenchmarkResultV1(
                run_manifest_id=completed_manifest.benchmark_run_id,
                run_manifest_hash=completed_manifest.input_hash,
                truth_manifest_id=truth_manifest.manifest_id,
                truth_manifest_hash=truth_manifest.input_hash,
                snapshot_hash=snapshot.snapshot_hash,
                availability_summary=availability.__dict__,
                hard_gate_results=tuple(gates),
                cost_metrics={
                    "wall_ms_total": snapshot.wall_ms_total,
                    "usage_entries": [
                        entry.model_dump(mode="json")
                        for entry in snapshot.usage_entries
                    ],
                },
                reliability_metadata={
                    "cache_state": configuration.cache_state.value,
                    "configuration_id": configuration.configuration_id,
                },
            )
            return {
                "status": "completed",
                "run_manifest": completed_manifest,
                "snapshot": snapshot,
                "result": result,
            }
        except Exception as exc:
            failed_manifest = BenchmarkRunManifestV1(
                **{
                    **run_manifest.model_dump(mode="json"),
                    "terminal_status": "failed",
                    "completed_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }
            )
            from .metrics import FailureLayer

            return {
                "status": "failed",
                "run_manifest": failed_manifest,
                "failure": FailedRunRecordV1(
                    run_manifest=failed_manifest.model_dump(mode="json"),
                    failure_layer=FailureLayer.RUNTIME.value,
                    failure_reason=str(exc)[:500],
                ),
            }


def evaluate_only(
    *,
    run_manifest: BenchmarkRunManifestV1,
    truth_manifest: TruthManifestV1,
    reachability: ReachabilityManifestV1,
    snapshot,
) -> BenchmarkResultV1:
    """§84: recompute metrics from an already-persisted snapshot without
    executing the Agent.  Deterministic: same inputs → same result hash."""
    from .availability import compute_availability_summary
    from .metrics import structural_hard_gates
    from .snapshot import BenchmarkRunSnapshotV1

    if isinstance(snapshot, dict):
        snapshot = BenchmarkRunSnapshotV1(**snapshot)
    gates = [
        {
            "gate_id": gate.gate_id,
            "passed": gate.passed,
            "violations": list(gate.violations),
        }
        for gate in structural_hard_gates(snapshot)
    ]
    availability = compute_availability_summary(truth_manifest, reachability)
    return BenchmarkResultV1(
        run_manifest_id=run_manifest.benchmark_run_id,
        run_manifest_hash=run_manifest.input_hash,
        truth_manifest_id=truth_manifest.manifest_id,
        truth_manifest_hash=truth_manifest.input_hash,
        snapshot_hash=snapshot.snapshot_hash,
        availability_summary=availability.__dict__,
        hard_gate_results=tuple(gates),
        cost_metrics={
            "wall_ms_total": snapshot.wall_ms_total,
            "usage_entries": [
                entry.model_dump(mode="json")
                for entry in snapshot.usage_entries
            ],
        },
        reliability_metadata={
            "cache_state": run_manifest.cache_state.value,
            "configuration_id": run_manifest.configuration_id,
        },
    )


def current_git_identity(repo_dir=None) -> tuple[str, str]:
    """Best-effort git commit/branch for the run manifest (§21)."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=repo_dir,
            timeout=10,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
            cwd=repo_dir,
            timeout=10,
        ).stdout.strip()
        return commit, branch
    except Exception:
        return "", ""


__all__ = [
    "AblationContractV1",
    "AblationStage",
    "BenchmarkRunner",
    "FailedRunRecordV1",
    "RUNNER_VERSION",
    "RunStatus",
    "ablation_configuration",
    "current_git_identity",
    "evaluate_only",
]
