"""ProductionBenchmarkExecutor — live benchmark execution wiring (P8B B0,
§8-§12, §87).

The adapter drives the REAL production investigation pipeline through its
public orchestration APIs only:

    fresh task/investigation admission
    → AgentOrchestrator.run_loop (PLAN→EXECUTE→INTEGRATE→EVALUATE)
    → FinalizationGate via orchestrator.finalize
    → durable BenchmarkRunSnapshot from the runtime repositories

Hard prohibitions (§8): no direct Finding inserts, no Working State
mutation, no FinalizationGate bypass, no forced report success.  The
executor's public interface carries NO truth (§9): it accepts only the
public case input (goal/questions/coverage) plus the configuration —
TruthManifest objects are structurally absent from this call graph and a
runtime spy test proves it.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field

from .run_manifest import BenchmarkRunManifestV1
from .snapshot import BenchmarkRunSnapshotV1

EXECUTOR_VERSION = "production-benchmark-executor:v1"


class PublicCaseInputV1(BaseModel):
    """§9: the ONLY case surface the production executor may see.  Built
    from the BenchmarkCase + its public goal/questions — never from the
    TruthManifest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    goal: str
    case_context: str = ""
    seed_questions: tuple[str, ...] = ()
    seed_coverage_dimensions: tuple[str, ...] = ()
    source_scope_ids: tuple[str, ...] = ()


class ExecutorError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ProductionBenchmarkExecutor:
    """§8 adapter.  ``orchestrator_factory`` builds a production
    AgentOrchestrator bound to a FRESH task store; ``runtime_factory``
    opens the AgentRuntimeRepository for that task; ``investigation_seed``
    builds the initial typed Working State from the public case input.
    All three are production components — the adapter never implements a
    second semantic path."""

    version = EXECUTOR_VERSION

    def __init__(
        self,
        *,
        orchestrator_factory: Callable[[str], Any],
        runtime_factory: Callable[[str], Any],
        investigation_seed: Callable[[str, str, PublicCaseInputV1], Any],
        clock: Callable[[], float] = time.monotonic,
    ):
        self._orchestrator_factory = orchestrator_factory
        self._runtime_factory = runtime_factory
        self._investigation_seed = investigation_seed
        self._clock = clock

    async def execute(
        self,
        *,
        case_input: PublicCaseInputV1,
        run_manifest: BenchmarkRunManifestV1,
        finalization_request_factory: Optional[Callable[..., Any]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> BenchmarkRunSnapshotV1:
        """Run one fresh benchmark repetition through production services.

        The run_manifest supplies ONLY configuration identity (budgets via
        the orchestrator factory); truth never appears in this signature.
        Timeout covers the WHOLE run (§11): on expiry the partial
        snapshot is returned with terminal_status failed.
        """
        task_id = f"bench-{run_manifest.benchmark_run_id}"
        started = self._clock()
        budget = timeout_seconds or run_manifest.model.generation_params.get(
            "timeout_seconds"
        )
        try:
            return await asyncio.wait_for(
                self._execute_inner(
                    case_input=case_input,
                    run_manifest=run_manifest,
                    task_id=task_id,
                    started=started,
                    finalization_request_factory=(
                        finalization_request_factory
                    ),
                ),
                timeout=budget,
            )
        except asyncio.TimeoutError:
            runtime = self._runtime_factory(task_id)
            investigations = runtime.list_investigations()
            partial = self._snapshot(
                runtime,
                task_id=task_id,
                investigation_id=(
                    investigations[-1].investigation_id
                    if investigations
                    else ""
                ),
                run_id=self._last_run_id(runtime, investigations),
                terminal_status="failed",
                started=started,
            )
            return partial.model_copy(
                update={
                    "limitations": tuple(
                        partial.limitations + ("run timeout exceeded",)
                    )
                }
            )

    # -- internals ---------------------------------------------------------

    async def _execute_inner(
        self,
        *,
        case_input: PublicCaseInputV1,
        run_manifest: BenchmarkRunManifestV1,
        task_id: str,
        started: float,
        finalization_request_factory: Optional[Callable[..., Any]],
    ) -> BenchmarkRunSnapshotV1:
        orchestrator = self._orchestrator_factory(task_id)
        seed_state = self._investigation_seed(
            task_id, f"inv-{run_manifest.benchmark_run_id}", case_input
        )
        _investigation, _rev = await orchestrator.create_investigation(
            task_id, seed_state
        )
        await orchestrator.admit_run(task_id, seed_state.investigation_id)
        outcomes = await orchestrator.run_loop(
            task_id,
            seed_state.investigation_id,
            source_scope_ids=case_input.source_scope_ids,
        )

        runtime = self._runtime_factory(task_id)
        run_id = self._last_run_id(
            runtime, runtime.list_investigations()
        )

        # Finalization through the production gate ONLY (§8): if the caller
        # supplies a request factory it must build a REAL FinalizationRequest
        # from the durable state; the gate decides, never the benchmark.
        finalization = None
        if finalization_request_factory is not None:
            from httpserver.services.investigation.agent_working_state import (
                working_state_from_json,
            )

            latest = runtime.get_latest_working_state(
                seed_state.investigation_id
            )
            state = working_state_from_json(
                task_id, seed_state.investigation_id, latest.state
            )
            request = finalization_request_factory(state)
            commit = await orchestrator.finalize(task_id, request)
            finalization = runtime.get_finalization(
                seed_state.investigation_id
            )
            if finalization is None and commit.decision.outcome is not None:
                pass  # gate refused; snapshot records the not-finalized state

        terminal = "completed" if finalization is not None else "failed"
        return self._snapshot(
            runtime,
            task_id=task_id,
            investigation_id=seed_state.investigation_id,
            run_id=run_id,
            terminal_status=terminal,
            started=started,
        )

    @staticmethod
    def _last_run_id(runtime, investigations):
        if not investigations:
            return ""
        runs = runtime.list_runs(investigations[-1].investigation_id)
        return runs[-1].run_id if runs else ""

    def _snapshot(
        self,
        runtime,
        *,
        task_id: str,
        investigation_id: str,
        run_id: str,
        terminal_status: str,
        started: float,
    ) -> BenchmarkRunSnapshotV1:
        from .snapshot import build_snapshot_from_runtime

        snapshot = build_snapshot_from_runtime(
            runtime,
            task_id=task_id,
            investigation_id=investigation_id,
            run_id=run_id or "unknown",
        )
        snapshot = snapshot.model_copy(
            update={
                "terminal_status": terminal_status,
                "wall_ms_total": int((self._clock() - started) * 1000),
            }
        )
        return snapshot


__all__ = [
    "EXECUTOR_VERSION",
    "ExecutorError",
    "ProductionBenchmarkExecutor",
    "PublicCaseInputV1",
]
