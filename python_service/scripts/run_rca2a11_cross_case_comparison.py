"""Executable entry point for RCA-2A.11 DeepSeek-Flash Cross-Case Vocabulary Guidance Comparison."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from benchmarks.isolated_integration.rca2a11_cross_case_runner import (
    AUTHORIZED_BASE_URL,
    AUTHORIZED_BASELINE,
    AUTHORIZED_MODEL,
    EXPERIMENT_ID,
    RCA2A11CrossCaseOrchestrator,
)


async def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    audit_dir = repo_root / "python_service/benchmarks/audits/rca2a11-deepseek-flash-vocabulary-comparison"
    scratch_dir = repo_root / "python_service/benchmarks/scratch/rca2a11_scratch"

    print("=================================================================")
    print("TraceLens Agent v0 — RCA-2A.11 Cross-Case Comparison (deepseek-flash)")
    print(f"Audit Directory:   {audit_dir}")
    print(f"Scratch Directory: {scratch_dir}")
    print("=================================================================")

    orch = RCA2A11CrossCaseOrchestrator(
        repo_root=repo_root,
        audit_dir=audit_dir,
        scratch_dir=scratch_dir,
        experiment_id=EXPERIMENT_ID,
        authorized_baseline=AUTHORIZED_BASELINE,
        authorized_model=AUTHORIZED_MODEL,
        authorized_base_url=AUTHORIZED_BASE_URL,
    )

    try:
        deliverables = await orch.run_experiment()
        matrix = deliverables["seat_execution_matrix"]["matrix"]
        disposition = deliverables["final_decision"]["final_disposition"]
        rec = deliverables["final_decision"]["recommendation"]

        print("-----------------------------------------------------------------")
        print(f"Seats Executed:     {matrix.get('stage_invocations_executed', 0)} / 16")
        print(f"Stop Reason:        {matrix.get('stop_reason')}")
        print(f"Final Disposition:  {disposition}")
        print(f"Recommendation:     {rec}")
        print("Comparison completed. Hard STOP.")
        print("=================================================================")
        return 0
    except Exception as exc:
        print(f"ERROR: RCA-2A.11 failed with exception: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
