"""Executable entry point for RCA-2A.10f Bounded Gateway Compatibility Diagnosis (longcat-2.5)."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from benchmarks.isolated_integration.gateway_diagnostic_runner import (
    AUTHORIZED_BASELINE_RCA2A10F,
    AUTHORIZED_MODEL_RCA2A10F,
    EXPERIMENT_ID_RCA2A10F,
    GatewayDiagnosticOrchestrator,
)


async def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    audit_dir = repo_root / "python_service/benchmarks/audits/rca2a10f-bounded-gateway-diagnosis"
    scratch_dir = repo_root / "python_service/benchmarks/scratch/rca2a10f_diagnostic"

    print("=================================================================")
    print("TraceLens Agent v0 — RCA-2A.10f Bounded Gateway Diagnosis (longcat-2.5)")
    print(f"Audit Directory: {audit_dir}")
    print(f"Scratch Directory: {scratch_dir}")
    print("=================================================================")

    orch = GatewayDiagnosticOrchestrator(
        repo_root=repo_root,
        audit_dir=audit_dir,
        scratch_dir=scratch_dir,
        experiment_id=EXPERIMENT_ID_RCA2A10F,
        authorized_baseline=AUTHORIZED_BASELINE_RCA2A10F,
        authorized_model=AUTHORIZED_MODEL_RCA2A10F,
        expected_returned_model="longcat-2.5",
    )

    try:
        deliverables = await orch.run_diagnosis()
        d3_st = deliverables["d3_execution"]["result"]["status"]
        d4_st = deliverables["d4_execution"]["result"]["status"]
        disp = deliverables["final_decision"]["final_disposition"]
        print("-----------------------------------------------------------------")
        print(f"D3 Status: {d3_st}")
        print(f"D4 Status: {d4_st}")
        print(f"Final Disposition: {disp}")
        print("Diagnosis completed. Hard STOP.")
        print("=================================================================")
        return 0
    except Exception as exc:
        print(f"ERROR: Diagnostic failed with exception: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
