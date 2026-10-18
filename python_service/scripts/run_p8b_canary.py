"""P8B §58 canary driver — ONE real T1 case through the production path.

Wires the ProductionBenchmarkExecutor to the REAL ServiceManager
components (production orchestrator + supervisor + specialist executor +
read-only tool registry over the live C++ backend) and executes the
canary case ``t1-fraud-script-usb`` against the fresh benchmark task.

Truth isolation (§9): the TruthManifest is loaded ONLY after the run,
solely for deterministic evaluation. The executor's call graph receives
only PublicCaseInputV1.

Usage (from python_service/):
    .venv/bin/python scripts/run_p8b_canary.py            # full canary
    .venv/bin/python scripts/run_p8b_canary.py --evaluate # re-evaluate only
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

CANARY_TASK_ID = "dd09c083-94f3-4dfa-a79d-8844804bd73b"
CASE_DIR = PYTHON_SERVICE_ROOT / "benchmarks" / "cases" / "t1-fraud-script-usb"
OUTPUT_DIR = PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "canary"

# preloaded task record (trusted DB path source), populated in _async_main
_TASK_SNAPSHOT: dict = {}


def _seed_state(task_id: str, investigation_id: str, case_input):
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        QuestionPriority,
        QuestionSource,
        WorkingQuestion,
    )

    questions = tuple(
        WorkingQuestion(
            question_id=f"q-{index}",
            text=text,
            source=QuestionSource.charter,
            priority=QuestionPriority.high,
        )
        for index, text in enumerate(case_input.seed_questions, start=1)
    )
    return AgentWorkingStateV1(
        task_id=task_id,
        investigation_id=investigation_id,
        objective=case_input.goal,
        questions=questions,
    )


def _finalization_request_factory(state):
    """Build a REAL FinalizationRequest from durable state (§8).

    The FinalizationGate decides; an unavailable final review is recorded
    honestly (best_effort mode), never fabricated as passed.
    """
    from httpserver.services.investigation.agent_finalization import (
        FinalReviewMode,
        FinalizationRequest,
        FinalSemanticReview,
        FinalSemanticReviewStatus,
    )
    from httpserver.services.investigation.repository import (
        InvestigationRepository,
    )
    from httpserver.services.investigation.paths import (
        investigation_db_path_for_task,
    )
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )

    investigation_id = state.investigation_id
    # revision must come from the DURABLE store, read synchronously inside
    # the executor's worker thread via the preloaded task snapshot.
    db_path = investigation_db_path_for_task(_TASK_SNAPSHOT[CANARY_TASK_ID])
    runtime = AgentRuntimeRepository(
        InvestigationRepository.open_existing(db_path, CANARY_TASK_ID)
    )
    latest = runtime.get_latest_working_state(investigation_id)
    revision = latest.revision if latest is not None else 1
    return FinalizationRequest(
        investigation_id=investigation_id,
        expected_state_revision=revision,
        review_mode=FinalReviewMode.best_effort,
        final_semantic_review=FinalSemanticReview(
            status=FinalSemanticReviewStatus.unavailable,
            result_ref="benchmark:final-review-not-executed",
        ),
        requested_by="p8b-canary",
    )


async def _async_main(evaluate_only: bool) -> int:
    from httpserver.services import get_service_manager
    from httpserver.services.benchmarks.production_executor import (
        ProductionBenchmarkExecutor,
        PublicCaseInputV1,
    )
    from httpserver.services.benchmarks.run_manifest import (
        BenchmarkConfigurationV1,
        BenchmarkRunManifestV1,
        ModelIdentityV1,
        collect_environment_digest,
    )
    from httpserver.services.benchmarks.snapshot import (
        build_snapshot_from_runtime,
    )
    from httpserver.services.benchmarks.runner import current_git_identity
    from httpserver.config import Settings

    settings = Settings(_env_file="/home/ymj68520/projects/TraceLens/.env")

    case_payload = json.loads(
        (CASE_DIR / "case.json").read_text(encoding="utf-8")
    )
    case_input = PublicCaseInputV1(
        case_id=case_payload["case_id"],
        goal=case_payload["goal"],
        case_context=case_payload.get("case_context", ""),
        seed_questions=(
            "Does this device contain evidence of a scripted, "
            "persona-based fraud operation (话术/包装 materials), and "
            "exactly what can and cannot be concluded from the evidence?",
        ),
        source_scope_ids=("windows",),
    )

    git_commit, git_branch = current_git_identity(PYTHON_SERVICE_ROOT.parent)
    model = ModelIdentityV1(
        provider="hcnsec-cloud",
        model_id=settings.llm_text_model,
        generation_params={
            "temperature": settings.llm_text_temperature,
            "max_tokens": settings.llm_text_max_tokens,
            "thinking_mode": settings.llm_thinking_mode,
            "reasoning_effort": "none",
        },
        context_window_tokens=settings.llm_context_length,
        request_date="2026-09-27",
    )
    configuration = BenchmarkConfigurationV1(
        configuration_id="bconf-canary-baseline",
        label="canary-baseline",
        model_provider=model.provider,
        model_id=model.model_id,
        generation_params={"repeat": 1, "timeout_seconds": 900},
        agent_supervisor_enabled=True,
        specialist_enabled=True,
        timeout_seconds=900,
    )

    manager = get_service_manager()
    await manager.initialize()
    if not (
        manager._cpp_backend_ready
        and manager._specialist_delegation_executor_ready
    ):
        raise RuntimeError("production services not ready for the canary run")

    specialist = manager.specialist_delegation_executor
    supervisor_model = None  # supervisor builds its own model from settings

    from httpserver.services.investigation.agent_orchestrator import (
        AgentOrchestrator,
        DelegationExecutionSummary,
    )
    from httpserver.services.investigation.agent_supervisor import (
        InvestigationSupervisor,
    )
    from httpserver.services.investigation.agent_context import (
        ContextAssembler,
    )
    from httpserver.services.investigation.agent_capabilities import (
        ArtifactFamilyRegistry,
    )
    from httpserver.services.investigation.agent_profiles import (
        default_profiles,
    )
    from httpserver.services.investigation.agent_skills import SkillRegistry
    from httpserver.services.investigation.agent_specialist_executor import (
        build_execution_envelope,
    )
    from httpserver.services.investigation.agent_specialist_result import (
        SpecialistResultV1,
    )
    from httpserver.services.investigation.agent_model_adapter import (
        build_chat_model,
        resolve_adapter_config,
    )
    from httpserver.services.investigation.agent_specialist_executor import (
        model_config_digest_from_adapter_config,
    )
    from httpserver.services.investigation.agent_tools.adapters import (
        build_read_only_registry,
    )
    from httpserver.services.investigation.agent_tools.observations import (
        AgentObservationSink,
    )
    from httpserver.services.investigation.paths import (
        investigation_db_path_for_task,
    )
    from httpserver.services.investigation.repository import (
        InvestigationRepository,
    )
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )

    _task_cache: dict = {}

    def open_runtime(task_id: str) -> AgentRuntimeRepository:
        # bench-<run_id> aliases resolve to the real canary task record for
        # path resolution; the store is opened under the REAL task id
        task = _task_cache.get(task_id) or _task_cache.get(CANARY_TASK_ID)
        if task is None:
            raise RuntimeError(f"task not preloaded: {task_id}")
        db_path = investigation_db_path_for_task(task)
        return AgentRuntimeRepository(
            InvestigationRepository.open_existing(db_path, task_id)
        )

    async def get_task(task_id):
        if task_id not in _task_cache:
            _task_cache[task_id] = await manager._cpp_backend.get_task(
                task_id
            )
        return _task_cache[task_id]

    supervisor = InvestigationSupervisor(settings=settings)
    model_config_digest = model_config_digest_from_adapter_config(
        resolve_adapter_config(settings)
    )

    class _AliasedReadService:
        """Bench-id → real-task-id translation for the read-side facades
        (investigation_read_service / investigation_service).  These
        services re-derive stores from the task id; the synthetic
        bench-<run_id> identity must be aliased before they see it."""

        def __init__(self, inner):
            self._inner = inner

        def _alias(self, task_id):
            return (
                CANARY_TASK_ID
                if task_id and task_id.startswith("bench-")
                else task_id
            )

        async def list_evidence(self, task_id):
            return await self._inner.list_evidence(self._alias(task_id))

        async def list_analysis_claims(self, task_id, analysis_id):
            return await self._inner.list_analysis_claims(
                self._alias(task_id), analysis_id
            )

        async def resolve_evidence(self, task_id, evidence_key):
            return await self._inner.resolve_evidence(
                self._alias(task_id), evidence_key
            )

        async def effective_event_claims(self, task_id, event_id):
            return await self._inner.effective_event_claims(
                self._alias(task_id), event_id
            )

        def __getattr__(self, name):
            return getattr(self._inner, name)

    class _AliasedSecondaryExecutor:
        """secondary_analysis_executor derives the store from the task id
        AND keys the reader by the same id; the alias translates the
        bench-<run_id> id to the real task for both."""

        def __init__(self, inner):
            self._inner = inner

        def _alias(self, task_id):
            return (
                CANARY_TASK_ID
                if task_id and task_id.startswith("bench-")
                else task_id
            )

        async def list_analyses(self, task_id, evidence_key):
            return await self._inner.list_analyses(
                self._alias(task_id), evidence_key
            )

        async def list_all_analyses(self, task_id):
            return await self._inner.list_all_analyses(self._alias(task_id))

        def __getattr__(self, name):
            return getattr(self._inner, name)

    class _LazyToolServices:
        """Tool-facing service bundle.  ``cpp_backend`` is the path-only
        alias backend so every tool sees the REAL benchmark task record
        under the run's bench-<run_id> task identity; the read-side
        facades are aliased the same way; everything else resolves to the
        live ServiceManager on first access."""

        def __init__(self, mgr, backend):
            self._mgr = mgr
            self._backend = backend
            self._read = _AliasedReadService(mgr.investigation_read_service)
            # the workbench InvestigationService owns resolve_evidence /
            # effective_event_claims; the alias re-points task ids before
            # the service re-derives DB paths from the task record
            self._svc = _AliasedReadService(mgr.investigation_seed_service)
            self._sec = _AliasedSecondaryExecutor(
                mgr.secondary_analysis_executor
            )

        def __getattr__(self, name):
            if name == "cpp_backend":
                return self._backend
            if name == "investigation_read_service":
                return self._read
            if name == "investigation_service":
                return self._svc
            if name == "secondary_analysis_executor":
                return self._sec
            return getattr(self._mgr, name)

    class _PathOnlyBackend:
        """Resolves the bench-<run_id> task id to the REAL benchmark task
        record for EVERY task-scoped backend call (get_task,
        get_task_files_paginated, get_task_events, ...).  The canary task
        was created EMPTY for this run, so fresh-store semantics are
        preserved; only the task-id → record resolution is re-pointed so
        the C++ backend's 404 on the synthetic id cannot silently empty
        tool results."""

        def __init__(self, inner):
            self._inner = inner

        def _alias(self, task_id):
            return (
                CANARY_TASK_ID
                if task_id and task_id.startswith("bench-")
                else task_id
            )

        async def get_task(self, task_id, **kwargs):
            return await self._inner.get_task(self._alias(task_id), **kwargs)

        async def get_task_files_paginated(self, task_id, *a, **kw):
            return await self._inner.get_task_files_paginated(
                self._alias(task_id), *a, **kw
            )

        async def get_task_events(self, task_id, *a, **kw):
            return await self._inner.get_task_events(
                self._alias(task_id), *a, **kw
            )

        async def get_task_files(self, task_id, *a, **kw):
            return await self._inner.get_task_files(
                self._alias(task_id), *a, **kw
            )

        async def get_task_databases(self, task_id, *a, **kw):
            return await self._inner.get_task_databases(
                self._alias(task_id), *a, **kw
            )

        def __getattr__(self, name):
            return getattr(self._inner, name)


    alias_backend = _PathOnlyBackend(manager._cpp_backend)
    tool_services = _LazyToolServices(manager, alias_backend)

    async def dispatcher(planning_context, decision, admitted):
        """Real specialist dispatch through the REAL executor + registry."""
        if not admitted:
            return []
        task = await get_task(CANARY_TASK_ID)
        # the store was created under the executor's bench-<run_id> task id;
        # open through the SAME id the delegations carry
        runtime = open_runtime(admitted[0].task_id)
        registry = build_read_only_registry(
            tool_services,
            observation_sink=AgentObservationSink(runtime),
        )
        assembler = ContextAssembler(
            skill_registry=SkillRegistry.with_defaults(),
            family_registry=ArtifactFamilyRegistry.with_defaults(),
            profiles=default_profiles(),
            tool_schema_hash=registry.schema_hash(),
        )
        # question texts from the durable working state (authoritative)
        latest = runtime.get_latest_working_state(
            admitted[0].investigation_id
        )
        state_rows = (latest.state or {}).get("questions", ())
        question_text = {
            q.get("question_id"): q.get("text", "")
            for q in state_rows
        }
        envelopes = []
        for delegation, action in zip(admitted, decision.delegate_actions()):
            pack = assembler.build(
                task=task,
                run_identity={
                    "task_id": delegation.task_id,
                    "investigation_id": delegation.investigation_id,
                    "run_id": delegation.run_id,
                },
                question=question_text.get(action.question_id, ""),
                question_id=action.question_id,
                source_scope_id=action.source_scope_id or "windows",
                delegation_id=delegation.delegation_id,
                table_lister=lambda _p: frozenset(),
            )
            envelopes.append(
                build_execution_envelope(
                    pack,
                    registry,
                    question_text=question_text.get(action.question_id, ""),
                    model_config_digest=model_config_digest,
                )
            )
        # the specialist executor resolves the trusted store through
        # backend.get_task(envelope.task_id); alias the bench-<run_id> id
        # to the real benchmark task record (created EMPTY for this run,
        # so fresh-store semantics are preserved) by dispatching through a
        # production SpecialistDelegationExecutor bound to the path-only
        # backend.  Everything else (registry, settings, policy, store
        # writes) is the REAL production executor.
        from httpserver.services.investigation.agent_specialist_executor import (
            SpecialistDelegationExecutor,
        )

        specialist = SpecialistDelegationExecutor(
            cpp_backend=alias_backend,
            settings=manager.settings,
            tool_services=tool_services,
            registry_builder=lambda runtime, observation_sink=None: (
                build_read_only_registry(
                    tool_services,
                    observation_sink=observation_sink
                    or AgentObservationSink(runtime),
                )
            ),
            investigation_db_path_for_task=None,  # trusted default from .paths
        )
        outcomes = await specialist.execute_batch(envelopes)
        summaries = []
        for outcome, envelope in zip(outcomes, envelopes):
            result = None
            stored = runtime.get_delegation_result(outcome.delegation_id)
            if stored is not None:
                result = SpecialistResultV1.model_validate(stored.result)
            summaries.append(
                DelegationExecutionSummary(
                    delegation_id=outcome.delegation_id,
                    question_id=envelope.question_id,
                    source_scope_id=envelope.source_scope_ids[0]
                    if envelope.source_scope_ids
                    else None,
                    status=outcome.status.value,
                    result=result,
                    result_hash=outcome.result_hash,
                    context_hash=envelope.context_hash,
                    failure_code=outcome.failure_code,
                    failure_summary=outcome.failure_message,
                )
            )
        return summaries

    orchestrator = AgentOrchestrator(
        alias_backend,
        supervisor=supervisor,
        delegation_dispatcher=dispatcher,
    )
    await orchestrator.initialize()
    # preload the canary task so runtime_factory/dispatch can resolve the
    # trusted DB path synchronously
    task_record = await get_task(CANARY_TASK_ID)
    _TASK_SNAPSHOT[CANARY_TASK_ID] = task_record

    def orchestrator_factory(task_id: str):
        return orchestrator

    def runtime_factory(task_id: str):
        return open_runtime(task_id)

    async def run_manifest_executor(run_manifest, task_id):
        executor = ProductionBenchmarkExecutor(
            orchestrator_factory=orchestrator_factory,
            runtime_factory=runtime_factory,
            investigation_seed=_seed_state,
        )
        snapshot = await executor.execute(
            case_input=case_input,
            run_manifest=run_manifest,
            finalization_request_factory=_finalization_request_factory,
            timeout_seconds=900,
        )
        return {"snapshot": json.loads(snapshot.model_dump_json())}

    def runner_executor(run_manifest):
        # the BenchmarkRunner seam is synchronous; bridge to the async
        # production path on a worker-thread event loop (we are already
        # inside asyncio.run, so a nested loop is not allowed).  The
        # executor derives a bench-<run_id> task id; the REAL fresh task
        # store for this canary is the pre-created benchmark task, so we
        # re-point the derived id at the real task record for path
        # resolution only (fresh-store semantics preserved: the task was
        # created empty for this run).
        import concurrent.futures

        task_id = f"bench-{run_manifest.benchmark_run_id}"
        _TASK_SNAPSHOT[task_id] = _TASK_SNAPSHOT[CANARY_TASK_ID]

        def _execute():
            return asyncio.run(run_manifest_executor(run_manifest, task_id))

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_execute).result()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if evaluate_only:
        snapshot_payload = json.loads(
            (OUTPUT_DIR / "snapshot.json").read_text(encoding="utf-8")
        )
        manifest_payload = json.loads(
            (OUTPUT_DIR / "run_manifest.json").read_text(encoding="utf-8")
        )
        from httpserver.services.benchmarks.snapshot import (
            BenchmarkRunSnapshotV1,
        )
        from httpserver.services.benchmarks.run_manifest import (
            BenchmarkRunManifestV1 as _M,
        )
        from httpserver.services.benchmarks.truth_manifest import (
            TruthManifestV1,
        )
        from httpserver.services.benchmarks.runner import evaluate_only as ev

        truth = TruthManifestV1(
            **json.loads(
                (CASE_DIR / "truth_manifest.json").read_text(encoding="utf-8")
            )
        )
        from httpserver.services.benchmarks.truth_manifest import (
            ReachabilityManifestV1,
        )

        reach = ReachabilityManifestV1(
            **json.loads(
                (CASE_DIR / "reachability.json").read_text(encoding="utf-8")
            )
        )
        result = ev(
            run_manifest=_M(**manifest_payload),
            truth_manifest=truth,
            reachability=reach,
            snapshot=BenchmarkRunSnapshotV1(**snapshot_payload),
        )
        (OUTPUT_DIR / "result.json").write_text(
            result.model_dump_json(), encoding="utf-8"
        )
        print("EVALUATED result_hash=", result.result_hash)
        _print_summary(result.model_dump())
        return 0

    # -- full canary run ------------------------------------------------
    from httpserver.services.benchmarks.runner import BenchmarkRunner
    from httpserver.services.benchmarks.truth_manifest import (
        ReachabilityManifestV1,
        TruthManifestV1,
    )

    runner = BenchmarkRunner(
        executor=runner_executor,
        git_commit=git_commit,
        git_branch=git_branch,
    )
    truth = TruthManifestV1(
        **json.loads(
            (CASE_DIR / "truth_manifest.json").read_text(encoding="utf-8")
        )
    )
    reach = ReachabilityManifestV1(
        **json.loads(
            (CASE_DIR / "reachability.json").read_text(encoding="utf-8")
        )
    )
    outcome = runner.run(
        case=_load_case(),
        truth_manifest=truth,
        reachability=reach,
        configuration=configuration,
        model=model,
        repeat_index=0,
        environment=collect_environment_digest(),
    )
    return _handle_outcome(outcome)


def _load_case():
    from httpserver.services.benchmarks.benchmark_case import BenchmarkCaseV1

    return BenchmarkCaseV1(
        **json.loads(
            (CASE_DIR / "case.json").read_text(encoding="utf-8")
        )
    )


def _handle_outcome(outcome) -> int:
    manifest = outcome["run_manifest"]
    (OUTPUT_DIR / "run_manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )
    print("run:", manifest.benchmark_run_id, "status:", outcome["status"])
    if outcome["status"] == "completed":
        result = outcome["result"]
        (OUTPUT_DIR / "result.json").write_text(
            result.model_dump_json(), encoding="utf-8"
        )
        snapshot = json.loads((OUTPUT_DIR / "snapshot.json").read_text()) \
            if (OUTPUT_DIR / "snapshot.json").exists() else None
        print("result_hash:", result.result_hash)
        _print_summary(result.model_dump())
        return 0
    failure = outcome["failure"]
    (OUTPUT_DIR / "failure.json").write_text(
        failure.model_dump_json(), encoding="utf-8"
    )
    print("FAILED:", failure.failure_reason)
    return 1


def _print_summary(result: dict) -> None:
    print("== structural hard gates ==")
    for gate in result.get("hard_gate_results", ()):
        print(
            f"  {gate.get('gate_id')}: "
            f"{'PASS' if gate.get('passed') else 'VIOLATION'} "
            f"{list(gate.get('violations', ()))}"
        )
    print("== availability ==")
    for key, value in (result.get("availability_summary") or {}).items():
        print(f"  {key}: {value}")
    print("== cost ==")
    cost = result.get("cost_metrics", {})
    print("  wall_ms_total:", cost.get("wall_ms_total"))
    for entry in cost.get("usage_entries", ()):
        print(f"  usage: {entry}")
    print("== snapshot run ids ==")
    print("  limitations:", result.get("limitations"))


if __name__ == "__main__":
    evaluate_only_flag = "--evaluate" in sys.argv
    raise SystemExit(asyncio.run(_async_main(evaluate_only_flag)))
