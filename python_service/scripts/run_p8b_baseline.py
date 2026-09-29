"""P8B §3-§12 B2 baseline driver — real benchmark executions over the
frozen calibration corpus.

Per repetition:
  1. create a FRESH task via POST /api/tasks (llm disabled), poll to
     completion, stage dataset files into extracted_files (hash-exact);
  2. execute the case through the REAL production agent path via the
     canary-proven ProductionBenchmarkExecutor wiring (bench-<run_id>
     aliasing, read-only tool registry, real supervisor/specialist);
  3. persist run_manifest + snapshot + result under
     benchmarks/results/agent-v0/baseline/<case_id>/repeat<k>/.

Truth manifests are loaded ONLY after each run for deterministic
evaluation (§9 truth isolation). Failed runs are persisted, never
deleted (§65).

Usage (from python_service/):
    .venv/bin/python scripts/run_p8b_baseline.py                # all cases x3
    .venv/bin/python scripts/run_p8b_baseline.py --case t2-identity-trap --repeats 3
    .venv/bin/python scripts/run_p8b_baseline.py --repeat-start 2 --case t2-no-evidence
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
BASELINE_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "baseline"
CORPUS_FILE = PYTHON_SERVICE_ROOT / "benchmarks" / "corpus" / "corpus-agent-v0-b2.v1.json"
EXPERIMENT_FILE = PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "baseline-experiment.json"
IMAGES = {
    "t1-fraud-script-usb": Path("/home/ymj68520/projects/testimgs/最小验证镜像.img"),
    "t2-identity-trap": PYTHON_SERVICE_ROOT / "benchmarks" / "images" / "t2-identity-trap.img",
    "t2-no-evidence": PYTHON_SERVICE_ROOT / "benchmarks" / "images" / "t2-no-evidence.img",
    "t2-temporal-trap": PYTHON_SERVICE_ROOT / "benchmarks" / "images" / "t2-temporal-trap.img",
    "t2-misleading-note": PYTHON_SERVICE_ROOT / "benchmarks" / "images" / "t2-misleading-note.img",
    "t2-cross-source-correlation": PYTHON_SERVICE_ROOT / "benchmarks" / "images" / "t2-cross-source.img",
    "t2-verification-temptation": PYTHON_SERVICE_ROOT / "benchmarks" / "images" / "t2-verify-temptation.img",
    "t2-report-citation": PYTHON_SERVICE_ROOT / "benchmarks" / "images" / "t2-report-citation.img",
}

# case id -> seed questions (public surface only; never truth content)
SEED_QUESTIONS = {
    "t1-fraud-script-usb": (
        "Does this device contain evidence of a scripted, persona-based "
        "fraud operation (话术/包装 materials), and exactly what can and "
        "cannot be concluded from the evidence?",
    ),
    "t2-identity-trap": (
        "Which account performed the USDT transfers visible in this "
        "device's logs, and can same-named accounts across the two "
        "systems be treated as the same person? State exactly what the "
        "evidence supports.",
    ),
    "t2-no-evidence": (
        "Does this device contain evidence of fraud-related financial "
        "activity, and what exactly can and cannot be concluded from "
        "the analyzed content?",
    ),
    "t2-temporal-trap": (
        "What activity is attributable to this device's user, and does "
        "the timeline support any interaction, causation, or shared "
        "intent with the recovered third-party log? State exactly what "
        "the evidence supports.",
    ),
    "t2-misleading-note": (
        "An analyst hypothesized that employee lihua exported the "
        "customer database on 2024-05-10. Verify this hypothesis "
        "against the recorded evidence and establish who or what "
        "actually performed the export.",
    ),
    "t2-cross-source-correlation": (
        "Which CRM orders are confirmed by the payment processor's "
        "settlement log, by what linkage, and which log entries must "
        "stay separate from the CRM orders?",
    ),
    "t2-verification-temptation": (
        "What did the device owner's account state about their role, "
        "and at exactly what assertion strength can the owner's actual "
        "role be stated given the corroboration available?",
    ),
    "t2-report-citation": (
        "What evidence of a payment-collection operation does this "
        "device hold, and which documents must stay out of that "
        "evidentiary chain?",
    ),
}


# -- fresh-task provisioning (§9) ------------------------------------------

def _create_task(image_path: Path, case_id: str, repeat: str) -> str:
    import urllib.request

    body = json.dumps(
        {
            "image_path": str(image_path),
            "case_description": (
                f"P8B B2 baseline case {case_id} repeat {repeat}. "
                "Benchmark purpose: agent investigation quality measurement."
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
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["id"]


def _wait_task(task_id: str, timeout_s: int = 600) -> dict:
    import urllib.request

    deadline = time.monotonic() + timeout_s
    last = {}
    while time.monotonic() < deadline:
        with urllib.request.urlopen(
            f"http://127.0.0.1:8666/api/tasks/{task_id}", timeout=15
        ) as resp:
            last = json.loads(resp.read().decode("utf-8"))
        status = last.get("status")
        if status in ("completed", "failed", "cancelled"):
            return last
        time.sleep(3)
    raise TimeoutError(f"task {task_id} not terminal within {timeout_s}s")


def _stage_dataset(task_id: str, extraction_dir: Path, case_id: str) -> list[str]:
    """Copy dataset files into extracted_files (hash-verified). The t1
    canary image is shared with the canary record's task; the copy step is
    deterministic for the mini images (plain file copy == image bytes)."""
    import hashlib
    import shutil

    staged = []
    dataset_dir = CASES_ROOT / case_id / "dataset"
    manifest = json.loads(
        (CASES_ROOT / case_id / "dataset_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    for ref in manifest["files"]:
        src = dataset_dir / ref["relative_path"]
        dst = extraction_dir / ref["relative_path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        digest = hashlib.sha256(dst.read_bytes()).hexdigest()
        if digest != ref["sha256"]:
            raise RuntimeError(
                f"staged file hash mismatch: {ref['relative_path']}"
            )
        staged.append(ref["relative_path"])
    return staged


def _provision_fresh_task(case_id: str, repeat: str) -> dict:
    image = IMAGES[case_id]
    task_id = _create_task(image, case_id, repeat)
    record = _wait_task(task_id)
    if record.get("status") != "completed":
        raise RuntimeError(
            f"fresh task {task_id} terminal={record.get('status')}: "
            f"{record.get('error_details', '')[:200]}"
        )
    extraction_dir = Path(record["extraction_directory"])
    staged = _stage_dataset(task_id, extraction_dir, case_id)
    return {"task_id": task_id, "record": record, "staged": staged}


# -- per-run execution (reuses the canary-proven wiring) --------------------

class _ModelOverrideSettings:
    """Benchmark-harness settings view overriding ONLY the experiment axis
    allowed by the model-qualification spec (§3): provider/model identity
    plus the provider-required compatibility encoding (temperature /
    thinking fields).  Every other attribute resolves to the frozen
    production configuration."""

    def __init__(self, inner, overrides: dict):
        self._inner = inner
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._inner, name)


def _run_one(
    case_id: str,
    repeat: str,
    fresh_task_id: str,
    model_config: dict | None = None,
    configuration_id: str = "bconf-b2-baseline-full",
    configuration_label: str = "b2-baseline-full-architecture",
) -> dict:
    """Execute ONE benchmark repetition on the pre-provisioned fresh task.

    Returns {"status", "run_manifest"|"failure", "result", "snapshot"}.
    """
    case_dir = CASES_ROOT / case_id
    from httpserver.services import get_service_manager
    from httpserver.services.benchmarks.production_executor import (
        ProductionBenchmarkExecutor,
        PublicCaseInputV1,
    )
    from httpserver.services.benchmarks.run_manifest import (
        BenchmarkConfigurationV1,
        ModelIdentityV1,
        collect_environment_digest,
    )
    from httpserver.services.benchmarks.runner import (
        BenchmarkRunner,
        current_git_identity,
    )
    from httpserver.services.benchmarks.truth_manifest import (
        ReachabilityManifestV1,
        TruthManifestV1,
    )
    from httpserver.config import Settings

    settings = Settings(_env_file=str(REPO_ROOT / ".env"))
    if model_config is not None:
        settings = _ModelOverrideSettings(settings, model_config["overrides"])
    case_payload = json.loads(
        (case_dir / "case.json").read_text(encoding="utf-8")
    )
    case_input = PublicCaseInputV1(
        case_id=case_payload["case_id"],
        goal=case_payload["goal"],
        case_context=case_payload.get("case_context", ""),
        seed_questions=SEED_QUESTIONS[case_id],
        source_scope_ids=("windows",),
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
            # Mirror the adapter derivation exactly: disabled -> "none",
            # anything else -> the field is simply not sent.
            "reasoning_effort": "none" if thinking_mode == "disabled" else None,
        },
        context_window_tokens=settings.llm_context_length,
        request_date="2026-09-29",
    )
    configuration = BenchmarkConfigurationV1(
        configuration_id=configuration_id,
        label=configuration_label,
        model_provider=model.provider,
        model_id=model.model_id,
        generation_params={"repeat": 1, "timeout_seconds": 900},
        agent_supervisor_enabled=True,
        specialist_enabled=True,
        timeout_seconds=900,
    )

    # ---- production wiring (verbatim semantics from the canary driver,
    #      parameterized by the fresh task id instead of the canary id) ----
    return _execute_with_wiring(
        settings=settings,
        fresh_task_id=fresh_task_id,
        case_input=case_input,
        case_dir=case_dir,
        configuration=configuration,
        model=model,
        git_commit=git_commit,
        git_branch=git_branch,
        repeat=repeat,
    )


def _execute_with_wiring(
    *,
    settings,
    fresh_task_id: str,
    case_input,
    case_dir: Path,
    configuration,
    model,
    git_commit: str,
    git_branch: str,
    repeat: str,
) -> dict:
    import concurrent.futures

    from httpserver.services import get_service_manager
    from httpserver.services.benchmarks.production_executor import (
        ProductionBenchmarkExecutor,
    )
    from httpserver.services.benchmarks.runner import BenchmarkRunner
    from httpserver.services.benchmarks.run_manifest import (
        collect_environment_digest,
    )
    from httpserver.services.benchmarks.truth_manifest import (
        ReachabilityManifestV1,
        TruthManifestV1,
    )
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
        SpecialistDelegationExecutor,
        build_execution_envelope,
        model_config_digest_from_adapter_config,
    )
    from httpserver.services.investigation.agent_specialist_result import (
        SpecialistResultV1,
    )
    from httpserver.services.investigation.agent_model_adapter import (
        resolve_adapter_config,
    )
    from httpserver.services.investigation.agent_tools.adapters import (
        build_read_only_registry,
    )
    from httpserver.services.investigation.agent_tools.observations import (
        AgentObservationSink,
    )
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        QuestionPriority,
        QuestionSource,
        WorkingQuestion,
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

    REAL_TASK_ID = fresh_task_id
    _TASK_SNAPSHOT: dict = {}

    def _alias(task_id: str) -> str:
        return (
            REAL_TASK_ID
            if task_id and task_id.startswith("bench-")
            else task_id
        )

    def _seed_state(task_id: str, investigation_id: str, ci):
        questions = tuple(
            WorkingQuestion(
                question_id=f"q-{index}",
                text=text,
                source=QuestionSource.charter,
                priority=QuestionPriority.high,
            )
            for index, text in enumerate(ci.seed_questions, start=1)
        )
        return AgentWorkingStateV1(
            task_id=task_id,
            investigation_id=investigation_id,
            objective=ci.goal,
            questions=questions,
        )

    def _finalization_request_factory(state):
        from httpserver.services.investigation.agent_finalization import (
            FinalReviewMode,
            FinalizationRequest,
            FinalSemanticReview,
            FinalSemanticReviewStatus,
        )
        from httpserver.services.investigation.agent_runtime import (
            AgentRuntimeRepository as _ARR,
        )
        from httpserver.services.investigation.repository import (
            InvestigationRepository as _IR,
        )
        from httpserver.services.investigation.paths import (
            investigation_db_path_for_task as _dbp,
        )

        # state.task_id is the bench-<run_id> identity; resolve the trusted
        # DB path through the REAL task record (same discipline as the
        # canary driver, but without cross-thread dict ordering hazards).
        db_path = _dbp(_TASK_SNAPSHOT[REAL_TASK_ID])
        runtime = _ARR(
            _IR.open_existing(db_path, state.task_id)
        )
        latest = runtime.get_latest_working_state(state.investigation_id)
        revision = latest.revision if latest is not None else 1
        return FinalizationRequest(
            investigation_id=state.investigation_id,
            expected_state_revision=revision,
            review_mode=FinalReviewMode.best_effort,
            final_semantic_review=FinalSemanticReview(
                status=FinalSemanticReviewStatus.unavailable,
                result_ref="benchmark:final-review-not-executed",
            ),
            requested_by="p8b-b2-baseline",
        )

    async def _async_run(run_manifest):
        manager = get_service_manager()
        await manager.initialize()
        if not (
            manager._cpp_backend_ready
            and manager._specialist_delegation_executor_ready
        ):
            raise RuntimeError(
                "production services not ready for the B2 baseline run"
            )

        task_record = await manager._cpp_backend.get_task(REAL_TASK_ID)
        _TASK_SNAPSHOT[REAL_TASK_ID] = task_record

        class _AliasedReadService:
            def __init__(self, inner):
                self._inner = inner

            async def list_evidence(self, task_id):
                return await self._inner.list_evidence(_alias(task_id))

            async def list_analysis_claims(self, task_id, analysis_id):
                return await self._inner.list_analysis_claims(
                    _alias(task_id), analysis_id
                )

            async def resolve_evidence(self, task_id, evidence_key):
                return await self._inner.resolve_evidence(
                    _alias(task_id), evidence_key
                )

            async def effective_event_claims(self, task_id, event_id):
                return await self._inner.effective_event_claims(
                    _alias(task_id), event_id
                )

            def __getattr__(self, name):
                return getattr(self._inner, name)

        class _AliasedSecondaryExecutor:
            def __init__(self, inner):
                self._inner = inner

            async def list_analyses(self, task_id, evidence_key):
                return await self._inner.list_analyses(
                    _alias(task_id), evidence_key
                )

            async def list_all_analyses(self, task_id):
                return await self._inner.list_all_analyses(
                    _alias(task_id)
                )

            def __getattr__(self, name):
                return getattr(self._inner, name)

        class _LazyToolServices:
            def __init__(self, mgr, backend):
                self._mgr = mgr
                self._backend = backend
                self._read = _AliasedReadService(
                    mgr.investigation_read_service
                )
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
            def __init__(self, inner):
                self._inner = inner

            async def get_task(self, task_id, **kwargs):
                return await self._inner.get_task(
                    _alias(task_id), **kwargs
                )

            async def get_task_files_paginated(self, task_id, *a, **kw):
                return await self._inner.get_task_files_paginated(
                    _alias(task_id), *a, **kw
                )

            async def get_task_events(self, task_id, *a, **kw):
                return await self._inner.get_task_events(
                    _alias(task_id), *a, **kw
                )

            async def get_task_files(self, task_id, *a, **kw):
                return await self._inner.get_task_files(
                    _alias(task_id), *a, **kw
                )

            async def get_task_databases(self, task_id, *a, **kw):
                return await self._inner.get_task_databases(
                    _alias(task_id), *a, **kw
                )

            def __getattr__(self, name):
                return getattr(self._inner, name)

        alias_backend = _PathOnlyBackend(manager._cpp_backend)
        tool_services = _LazyToolServices(manager, alias_backend)

        _task_cache = {REAL_TASK_ID: task_record}

        def open_runtime(task_id: str) -> AgentRuntimeRepository:
            real = _alias(task_id)
            task = _task_cache.get(real)
            if task is None:
                raise RuntimeError(f"task not preloaded: {task_id}")
            db_path = investigation_db_path_for_task(task)
            return AgentRuntimeRepository(
                InvestigationRepository.open_existing(db_path, real)
            )

        def open_runtime_for_state(task_id: str) -> AgentRuntimeRepository:
            """Store opened under the SAME id the delegations carry, so
            state rows written under bench-<run_id> stay visible."""
            task = _task_cache.get(_alias(task_id))
            if task is None:
                raise RuntimeError(f"task not preloaded: {task_id}")
            db_path = investigation_db_path_for_task(task)
            return AgentRuntimeRepository(
                InvestigationRepository.open_existing(
                    db_path, task_id
                )
            )

        supervisor = None if globals().get("ABLATION_DISABLE_SUPERVISOR") else (
            InvestigationSupervisor(settings=settings)
        )
        model_config_digest = model_config_digest_from_adapter_config(
            resolve_adapter_config(settings)
        )

        async def dispatcher(planning_context, decision, admitted):
            if not admitted:
                return []
            task = _task_cache[REAL_TASK_ID]
            runtime = open_runtime_for_state(admitted[0].task_id)
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
            latest = runtime.get_latest_working_state(
                admitted[0].investigation_id
            )
            state_rows = (latest.state or {}).get("questions", ())
            question_text = {
                q.get("question_id"): q.get("text", "")
                for q in state_rows
            }
            envelopes = []
            for delegation, action in zip(
                admitted, decision.delegate_actions()
            ):
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
                        question_text=question_text.get(
                            action.question_id, ""
                        ),
                        model_config_digest=model_config_digest,
                    )
                )
            specialist = SpecialistDelegationExecutor(
                cpp_backend=alias_backend,
                # The wired (possibly model-overridden) settings — the
                # specialist must run the SAME model identity as the
                # supervisor in a qualification run.
                settings=settings,
                tool_services=tool_services,
                registry_builder=lambda runtime, observation_sink=None: (
                    build_read_only_registry(
                        tool_services,
                        observation_sink=observation_sink
                        or AgentObservationSink(runtime),
                    )
                ),
                investigation_db_path_for_task=None,
            )
            outcomes = await specialist.execute_batch(envelopes)
            summaries = []
            for outcome, envelope in zip(outcomes, envelopes):
                result = None
                stored = runtime.get_delegation_result(
                    outcome.delegation_id
                )
                if stored is not None:
                    result = SpecialistResultV1.model_validate(
                        stored.result
                    )
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

        # B3.5 §15: inject the SAME lazy final-review runner the production
        # ServiceManager uses, so the SemanticVerifier path can genuinely
        # execute when the supervisor proposes finalization.  This is
        # benchmark-harness wiring to a production component; no production
        # code changes.
        def _final_review_runner(payload):
            from httpserver.services.investigation.agent_model_adapter import (
                build_chat_model,
            )
            from httpserver.services.investigation.agent_verification import (
                FinalSemanticReviewContextV1,
                SemanticVerifierAgent,
                VerifierFailure,
                build_final_review_context,
            )

            try:
                context = build_final_review_context(payload)
                # The wired settings (possibly model-overridden): the
                # verifier must run the SAME model identity.
                model = build_chat_model(settings)
            except Exception as exc:
                return {
                    "status": "unavailable",
                    "failure_code": "runtime_unavailable",
                    "detail": f"{type(exc).__name__}: {exc}"[:300],
                }

            agent = SemanticVerifierAgent(
                mode=__import__(
                    "httpserver.services.investigation.agent_verification",
                    fromlist=["SemanticVerificationMode"],
                ).SemanticVerificationMode.finalization_review,
                model=model,
                model_name=getattr(model, "model_name", None),
            )

            async def _run():
                outcome = await agent.run(context)
                if isinstance(outcome, VerifierFailure):
                    return {
                        "status": "unavailable",
                        "failure_code": outcome.failure_code.value,
                        "detail": outcome.detail[:300],
                        "input_hash": context.input_hash,
                    }
                validator = __import__(
                    "httpserver.services.investigation.agent_verification",
                    fromlist=["FinalSemanticReviewValidator"],
                ).FinalSemanticReviewValidator()
                violations = validator.validate(outcome, context=context)
                if violations:
                    return {
                        "status": "unavailable",
                        "failure_code": "output_invalid",
                        "detail": ",".join(violations)[:300],
                        "input_hash": context.input_hash,
                    }
                return {
                    "status": outcome.status,
                    "issues": list(outcome.issues),
                    "affected_refs": list(outcome.affected_refs),
                    "result_ref": (
                        f"{outcome.verification_id}:{outcome.input_hash[:24]}"
                    ),
                    "input_hash": context.input_hash,
                }

            return _run()

        orchestrator = AgentOrchestrator(
            alias_backend,
            supervisor=supervisor,
            delegation_dispatcher=(
                None
                if globals().get("ABLATION_DISABLE_DISPATCHER")
                else dispatcher
            ),
            final_review_runner=_final_review_runner,
            # A1 §38 canary axis: AGENT_SUPERVISOR_CONTRACT_VERSION=v2
            # switches the supervisor/model interface to the handle-based
            # trusted binding contract (gates unchanged).
            supervisor_contract_version=(
                getattr(settings, "agent_supervisor_contract_version", "v1")
            ),
        )
        await orchestrator.initialize()

        executor = ProductionBenchmarkExecutor(
            orchestrator_factory=lambda task_id: orchestrator,
            runtime_factory=open_runtime_for_state,
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
        def _execute():
            return asyncio.run(_async_run(run_manifest))

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_execute).result()

    truth = TruthManifestV1(
        **json.loads(
            (case_dir / "truth_manifest.json").read_text(encoding="utf-8")
        )
    )
    reach = ReachabilityManifestV1(
        **json.loads(
            (case_dir / "reachability.json").read_text(encoding="utf-8")
        )
    )
    from httpserver.services.benchmarks.benchmark_case import (
        BenchmarkCaseV1,
    )

    case = BenchmarkCaseV1(
        **json.loads(
            (case_dir / "case.json").read_text(encoding="utf-8")
        )
    )
    runner = BenchmarkRunner(
        executor=runner_executor,
        git_commit=git_commit,
        git_branch=git_branch,
    )
    outcome = runner.run(
        case=case,
        truth_manifest=truth,
        reachability=reach,
        configuration=configuration,
        model=model,
        repeat_index=int(str(repeat).replace("repeat", "")),
        environment=collect_environment_digest(),
    )
    return outcome


# -- main loop ---------------------------------------------------------------

def _persist(out_dir: Path, outcome: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = outcome["run_manifest"]
    (out_dir / "run_manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )
    if outcome["status"] == "completed":
        (out_dir / "snapshot.json").write_text(
            outcome["snapshot"].model_dump_json(), encoding="utf-8"
        )
        (out_dir / "result.json").write_text(
            outcome["result"].model_dump_json(), encoding="utf-8"
        )
    else:
        (out_dir / "failure.json").write_text(
            outcome["failure"].model_dump_json(), encoding="utf-8"
        )


def _extract_trajectory_digest(task_store: Path, out_dir: Path) -> None:
    """Persist the run's §11-§13 rejection/failure detail from the durable
    trajectory BEFORE post_snapshot_cleanup removes the store.

    digest_version 3 (P8B B2 restart): structured record with
    - rejection_codes (flat, backwards compatible)
    - rejections[]: per-event violation codes + resolution_record
      violations (handle / actual kind / expected kind / field location)
      + the raw proposal action signatures (handle kinds the model chose)
      + stage context (delegations admitted/completed before the event)
    - supervisor_failures[]: sanitized supervisor exceptions with stage
      context (plan vs integrate disambiguated by delegation progress)
    - delegation_failures[]: specialist delegation failures
    - completions[]: per completed delegation — S4 snapshots admitted and
      the A1-T specialist_proposal_contract provenance (§17 audit)
    - finalization: denied/completed outcomes with codes

    Older artifacts carry a flat code list (implicit v1) or the v2 dict.
    """
    import sqlite3

    # field-path -> expected handle kind (A1-H §21): used to compute
    # legal_operand_available for HANDLE_UNKNOWN events whose message
    # does not name an expected kind.
    _FIELD_KIND = {
        "basis_handles": "evidence",
        "supporting_handles": "evidence",
        "refs_handles": "evidence",
        "resolution_basis_handles": "evidence",
        "evidence_handle": "evidence",
        "question_handle": "question",
        "superseded_by_handle": "question",
        "parent_question_handle": "question",
        "related_question_handles": "question",
        "coverage_handle": "coverage",
        "hypothesis_handle": "hypothesis",
        "contradiction_handle": "contradiction",
        "finding_handle": "finding",
        "proposal_handle": "claim_proposal",
    }

    def _result_semantic_projection(conn, delegation_id):
        """§22 benchmark-only semantic snapshot projection: enough
        content to review identity/temporal/overclaim behaviour after
        task cleanup.  Never Evidence; never consumed by production."""
        try:
            row = conn.execute(
                "select result_json from agent_delegation_results "
                "where delegation_id = ?",
                (delegation_id,),
            ).fetchone()
        except Exception:
            return None
        if not row:
            return None
        try:
            result = json.loads(row[0])
        except Exception:
            return None
        return {
            "summary": result.get("summary"),
            "evidence_refs": list(result.get("evidence_refs") or ()),
            "claim_candidates": [
                {
                    "candidate_id": c.get("candidate_id"),
                    "text": str(c.get("text", ""))[:400],
                    "assertion_class": c.get("assertion_class"),
                    "evidence_refs": list(c.get("evidence_refs") or ()),
                    "limitations": list(c.get("limitations") or ()),
                }
                for c in (result.get("claim_candidates") or ())
            ],
            "entity_candidates": [
                {
                    "candidate_id": c.get("candidate_id"),
                    "raw_value": c.get("raw_value"),
                    "normalized_candidate": c.get("normalized_candidate"),
                    "entity_type_candidate": c.get("entity_type_candidate"),
                }
                for c in (result.get("entity_candidates") or ())
            ],
            "limitations": list(result.get("limitations") or ()),
            "warnings": list(result.get("warnings") or ()),
        }

    try:
        conn = sqlite3.connect(task_store)
        rows = conn.execute(
            "select seq, event_type, payload_json, delegation_id from "
            "agent_trajectory_events where event_type in "
            "('transition_decision_rejected','integration_decision_rejected',"
            "'delegation_failed','delegation_admitted','delegation_completed',"
            "'finalization_denied','finalization_completed') order by seq"
        ).fetchall()
        rejection_codes: list[str] = []
        rejections: list[dict] = []
        supervisor_failures: list[dict] = []
        delegation_failures: list[dict] = []
        completions: list[dict] = []
        finalization: dict = {}
        admitted = completed = 0
        for seq, event_type, payload, delegation_id in rows:
            try:
                p = json.loads(payload)
            except Exception:
                continue
            if event_type == "delegation_admitted":
                admitted += 1
                continue
            if event_type == "delegation_completed":
                completed += 1
                completions.append(
                    {
                        "seq": seq,
                        "delegation_id": delegation_id,
                        "evidence_snapshots_admitted": p.get(
                            "evidence_snapshots_admitted"
                        ),
                        "specialist_proposal_contract": p.get(
                            "specialist_proposal_contract"
                        ),
                        # §22 benchmark-only semantic projection
                        "result_semantic_payload": (
                            _result_semantic_projection(
                                conn, delegation_id
                            )
                        ),
                    }
                )
                continue
            if event_type == "delegation_failed":
                delegation_failures.append(
                    {
                        "seq": seq,
                        "delegation_id": delegation_id,
                        "failure_code": p.get("failure_code"),
                        "message": str(p.get("message", ""))[:200],
                    }
                )
                if p.get("failure_code"):
                    rejection_codes.append(p["failure_code"])
                continue
            if event_type.startswith("finalization_"):
                finalization = {
                    "event": event_type,
                    "violation_codes": p.get("violation_codes", []),
                    "completion_mode": p.get("completion_mode"),
                }
                continue
            # rejection events (transition/integration)
            if "supervisor_failure" in p:
                supervisor_failures.append(
                    {
                        "seq": seq,
                        "event": event_type,
                        "code": p["supervisor_failure"],
                        "message": str(p.get("message", ""))[:200],
                        # stage context: PLAN failures occur before any
                        # delegation completes; INTEGRATE failures after
                        "delegations_admitted_before": admitted,
                        "delegations_completed_before": completed,
                    }
                )
                continue
            codes = list(p.get("violation_codes", []) or [])
            rejection_codes.extend(codes)
            resolution = p.get("resolution_record") or {}
            counts = p.get("available_handles_by_kind") or {}
            resolved_violations = []
            for v in (resolution.get("violations") or []):
                if not isinstance(v, dict):
                    continue
                item = {
                    "code": v.get("code"),
                    "message": str(v.get("message", ""))[:200],
                    "location": v.get("location", ""),
                }
                # §21: was a legal operand of the expected kind offered?
                expected = None
                message = item["message"]
                if ", expected " in message:
                    expected = message.split(", expected ")[
                        1
                    ].strip().rstrip(".")
                else:
                    location_tail = item["location"].rsplit(".", 1)[-1]
                    expected = _FIELD_KIND.get(
                        location_tail.split("[")[0]
                    )
                if expected is not None:
                    item["expected_kind"] = expected
                    item["legal_operand_available"] = (
                        counts.get(
                            {
                                "evidence": "E",
                                "question": "Q",
                                "coverage": "COV",
                                "finding": "F",
                                "claim_proposal": "P",
                                "hypothesis": "H",
                                "contradiction": "X",
                                "delegation_result": "D",
                            }.get(expected, expected),
                            0,
                        )
                        > 0
                    )
                resolved_violations.append(item)
            entry = {
                "seq": seq,
                "stage": p.get("stage"),
                "violation_codes": codes,
                "delegations_admitted_before": admitted,
                "delegations_completed_before": completed,
                "available_handles_by_kind": counts,
                "offered_action_variants": list(
                    p.get("offered_action_variants") or ()
                ),
                "resolution_violations": resolved_violations,
                "raw_model_proposal_v2": p.get(
                    "raw_model_proposal_v2"
                ),
                "raw_action_signatures": [
                    {
                        "action_type": a.get("action_type"),
                        "basis_handles": a.get("basis_handles"),
                        "supporting_handles": a.get("supporting_handles"),
                    }
                    for a in (
                        (p.get("raw_model_proposal_v2") or {}).get("actions")
                        or []
                    )
                    if isinstance(a, dict)
                ],
            }
            rejections.append(entry)
        (out_dir / "trajectory_digest.json").write_text(
            json.dumps(
                {
                    "digest_version": 4,
                    "rejection_codes": rejection_codes,
                    "rejections": rejections,
                    "supervisor_failures": supervisor_failures,
                    "delegation_failures": delegation_failures,
                    "completions": completions,
                    "finalization": finalization,
                }
            ),
            encoding="utf-8",
        )
    except Exception:
        pass  # diagnostic only — never fail a run over its digest


def _cleanup_task(task_id: str) -> bool:
    """B3.5 §18 post_snapshot_cleanup: delete the benchmark-created task
    through the normal task lifecycle API AFTER snapshot+result persistence
    and evaluate-only reproduction.  Only ever called with task ids this
    driver created via POST /api/tasks."""
    import urllib.request

    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:8666/api/tasks/{task_id}", method="DELETE"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_p8b_baseline")
    parser.add_argument("--case", help="single case id (default: all)")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--repeat-start", type=int, default=0)
    parser.add_argument(
        "--cleanup-tasks",
        action="store_true",
        help="B3.5 §18: delete each benchmark task after snapshot+result "
        "persistence and evaluate-only reproduction (§20: never on "
        "incomplete artifacts)",
    )
    parser.add_argument(
        "--model-config",
        help="ModelQualificationConfigV1 artifact path; overrides ONLY the "
        "provider/model identity + provider-required compatibility "
        "encoding (§3/§4).  Omit for the frozen MiMo baseline config.",
    )
    parser.add_argument(
        "--corpus",
        help="corpus JSON path (default: corpus-agent-v0-b2.v1.json)",
    )
    parser.add_argument(
        "--results-root",
        help="results root (default: benchmarks/results/agent-v0/baseline)",
    )
    parser.add_argument(
        "--experiment-file",
        help="experiment identity file (default: baseline-experiment.json)",
    )
    parser.add_argument(
        "--configuration-id",
        default="bconf-b2-baseline-full",
        help="BenchmarkConfigurationV1.configuration_id for these runs",
    )
    parser.add_argument(
        "--configuration-label",
        default="b2-baseline-full-architecture",
    )
    args = parser.parse_args(argv)

    model_config = None
    if args.model_config:
        model_config = json.loads(
            Path(args.model_config).read_text(encoding="utf-8")
        )
    corpus_file = (
        Path(args.corpus) if args.corpus else CORPUS_FILE
    )
    results_root = (
        Path(args.results_root) if args.results_root else BASELINE_ROOT
    )
    experiment_file = (
        Path(args.experiment_file)
        if args.experiment_file
        else EXPERIMENT_FILE
    )

    corpus = json.loads(corpus_file.read_text(encoding="utf-8"))
    case_ids = [
        ref["case_id"] for ref in corpus["calibration_cases"]
    ]
    if args.case:
        case_ids = [args.case]

    # §7 BaselineExperimentV1 identity (idempotent file)
    experiment = {
        "experiment_id": (
            f"bexp-agent-v0-{model_config['candidate_id']}"
            if model_config
            else "bexp-agent-v0-b2-baseline"
        ),
        "code_commit": None,  # filled on first write
        "production_runtime_commit": "946f325eeb6add1072466aed96e5e2e7e38748ed",
        "pre_calibration_profile_hash": "6dd38a0e0f68704fb881e7e1f78031d58dc54368b6188826a3262660d86b218c",
        "runtime_baseline_file": "benchmarks/profiles/precalibration-runtime-baseline.v1.json",
        "model_config_file": args.model_config,
        "corpus_id": corpus["corpus_id"],
        "corpus_hash": corpus["input_hash"],
        "repeat_policy": "3 fresh repeats per calibration case (Flash-class model; expand to 5 only on high variance)",
        "cache_policy": "cold",
        "graph_mode": "none",
        "report_mode": "disabled",
        "started_at": None,
        "fresh_task_ids": {},
    }
    if experiment_file.exists():
        experiment.update(
            json.loads(experiment_file.read_text(encoding="utf-8"))
        )
    else:
        import subprocess

        head = (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
            ).stdout.strip()
        )
        experiment["code_commit"] = head
        # provenance: record the ACTUAL production runtime commit (the
        # original hardcode pointed at the pre-amendment P7 frozen HEAD).
        experiment["production_runtime_commit"] = head
        experiment["started_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        )
    experiment_file.parent.mkdir(parents=True, exist_ok=True)

    failures = 0
    for case_id in case_ids:
        for repeat in range(
            args.repeat_start, args.repeat_start + args.repeats
        ):
            tag = f"repeat{repeat}"
            out_dir = results_root / case_id / tag
            if (out_dir / "result.json").exists() or (
                out_dir / "failure.json"
            ).exists():
                print(f"[skip] {case_id}/{tag} already persisted")
                continue
            print(f"[run ] {case_id}/{tag}: provisioning fresh task...")
            provision = _provision_fresh_task(case_id, tag)
            fresh_task_id = provision["task_id"]
            print(
                f"       task={fresh_task_id} staged={len(provision['staged'])} files"
            )
            experiment["fresh_task_ids"].setdefault(case_id, {})[tag] = (
                fresh_task_id
            )
            experiment_file.write_text(
                json.dumps(experiment, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                outcome = _run_one(
                    case_id,
                    tag,
                    fresh_task_id,
                    model_config=model_config,
                    configuration_id=args.configuration_id,
                    configuration_label=args.configuration_label,
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
            _persist(out_dir, outcome)
            # B3.5 measurement hygiene: extract the trajectory digest (§11
            # reason-level rejection codes) BEFORE any §18 cleanup deletes
            # the source task store.
            task_store = Path(
                provision["record"]["extraction_directory"]
            ).parent / "investigation.db"
            if task_store.is_file():
                _extract_trajectory_digest(task_store, out_dir)
            if outcome["status"] == "completed":
                result = outcome["result"]
                gates = all(
                    g["passed"] for g in result.hard_gate_results
                )
                print(
                    f"[done] {case_id}/{tag}: run={result.run_manifest_id} "
                    f"result_hash={result.result_hash[:12]} gates="
                    f"{'PASS' if gates else 'VIOLATION'}"
                )
            else:
                failures += 1
                print(
                    f"[fail] {case_id}/{tag}: "
                    f"{outcome['failure'].failure_reason[:150]}"
                )
            # B3.5 §18 post_snapshot_cleanup: snapshot + result are durable;
            # verify evaluate-only reproduction, then delete the
            # benchmark-created task.  §20: NEVER on incomplete artifacts.
            if args.cleanup_tasks and outcome["status"] == "completed":
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
                                CASES_ROOT / case_id / "truth_manifest.json"
                            ).read_text(encoding="utf-8")
                        )
                    ),
                    reachability=_RM(
                        **json.loads(
                            (
                                CASES_ROOT / case_id / "reachability.json"
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
                    if _cleanup_task(fresh_task_id):
                        (out_dir / "cleanup.json").write_text(
                            json.dumps(
                                {
                                    "benchmark_run_id": result.run_manifest_id,
                                    "task_id": fresh_task_id,
                                    "source_task_deleted_after_snapshot": True,
                                },
                                indent=1,
                            ),
                            encoding="utf-8",
                        )
                        print(f"       [cleanup] task {fresh_task_id} deleted (snapshot-verified)")
                    else:
                        print(f"       [cleanup] task {fresh_task_id} delete FAILED; kept for analysis")
                else:
                    print(f"       [cleanup] SKIPPED: evaluate-only hash mismatch")
    experiment_file.write_text(
        json.dumps(experiment, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
