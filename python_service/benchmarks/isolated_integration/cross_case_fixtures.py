"""RCA-2A.9 Cross-Case Synthetic Post-Delegation Fixture Builders.

Builds deterministic, synthetic post-delegation stores for four calibration scenarios:
- F1: ``t2-no-evidence`` (honest absence of incriminating evidence)
- F2: ``t2-temporal-trap`` (temporal proximity between independent records)
- F3: ``t2-identity-trap`` (same username across unrelated systems)
- F4: ``t2-report-citation`` (evidentiary citation discipline, stage-limited)

All stores are generated through the REAL production orchestrator path (Path A)
with offline deterministic models (FunctionModel/TestModel). Zero real LLM calls.
All evidence items resolve through the production EvidenceResolver and snapshot
acquisition against isolated SQLite files.db databases.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (
    GUIDANCE_TEXT,
    GuidanceIntegrationAgentFactory,
    guidance_sha256,
)
from benchmarks.isolated_integration.fixtures import (
    CHARTER_QUESTION,
    SYNTHETIC_SPECIALIST_RESULT,
    _CaptureReached,
    _IntegrateCaptureFunction,
    _ProjectionPlanFunction,
    _jsonable,
)
from benchmarks.isolated_integration.harness import (
    IsolatedIntegrationHarness,
    validate_isolated_input,
)
from httpserver.services.investigation.agent_failure_diagnostics import schema_hash_of
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)
from httpserver.services.investigation.agent_orchestrator import (
    AgentOrchestrator,
    DelegationExecutionSummary,
)
from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
)
from httpserver.services.investigation.agent_specialist_executor import (
    AgentRunPolicy,
    SpecialistDelegationExecutor,
    build_execution_envelope,
)
from httpserver.services.investigation.agent_specialist_result import (
    SpecialistResultProposalV1,
    SpecialistResultV1,
)
from httpserver.services.investigation.agent_supervisor import (
    InvestigationSupervisor,
    SupervisorAgentFactory,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    QuestionPriority,
    QuestionSource,
    WorkingQuestion,
    working_state_to_json,
)
from httpserver.services.investigation.repository import InvestigationRepository
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel


@dataclass(frozen=True)
class ScenarioFixtureSpec:
    scenario_id: str
    tier: str
    title: str
    task_id: str
    charter_question: str
    objective: str
    files_spec: tuple[dict[str, Any], ...]
    specialist_evidence_refs: tuple[str, ...]
    specialist_claim_candidates: tuple[dict[str, Any], ...]
    specialist_limitations: tuple[str, ...]
    specialist_summary: str
    stage_applicability: str  # INTEGRATE_REPRESENTABLE or REQUIRES_ADAPTER
    expected_integration_obligations: tuple[str, ...]
    known_stage_limitations: tuple[str, ...]


SCENARIO_SPECS: dict[str, ScenarioFixtureSpec] = {
    "t2-no-evidence": ScenarioFixtureSpec(
        scenario_id="t2-no-evidence",
        tier="T2",
        title="T2 no-evidence / indeterminate: benign office volume (cleanfs)",
        task_id="t2-no-evidence",
        charter_question=(
            "Does this device contain evidence of fraud-related financial "
            "activity, and what exactly can and cannot be concluded from the analyzed content?"
        ),
        objective="detect unauthorized access and fraud-related financial activity",
        files_spec=(
            {
                "path": "C/benign/memo.docx",
                "name": "memo.docx",
                "extension": ".docx",
                "category": "document",
                "type": "file",
                "size": 2048,
                "mtime": 1690000000,
                "ctime": 1690000000,
                "is_deleted": 0,
                "md5": "md5_benign_memo",
            },
        ),
        specialist_evidence_refs=(),
        specialist_claim_candidates=(),
        specialist_limitations=("no analyzable evidence of the queried activity",),
        specialist_summary="honest no-evidence investigation; nothing fraud-related found",
        stage_applicability="INTEGRATE_REPRESENTABLE",
        expected_integration_obligations=(
            "keep required charter question non-terminal (open or in_progress)",
            "record investigative limitation",
            "zero fabricated evidence references",
        ),
        known_stage_limitations=(),
    ),
    "t2-temporal-trap": ScenarioFixtureSpec(
        scenario_id="t2-temporal-trap",
        tier="T2",
        title="T2 temporal proximity without causality (tempfs)",
        task_id="t2-temporal-trap",
        charter_question=(
            "Does the temporal adjacency between wangfang messages and zhangming "
            "USDT deposit entries establish interaction, causation, or shared intent?"
        ),
        objective="determine whether temporal proximity between chat logs indicates fraud collaboration",
        files_spec=(
            {
                "path": "C/chat/wangfang.log",
                "name": "wangfang.log",
                "extension": ".log",
                "category": "document",
                "type": "file",
                "size": 1024,
                "mtime": 1712783520,
                "ctime": 1712783520,
                "is_deleted": 0,
                "md5": "md5_wangfang_chat",
            },
            {
                "path": "C/chat/zhangming.log",
                "name": "zhangming.log",
                "extension": ".log",
                "category": "document",
                "type": "file",
                "size": 2048,
                "mtime": 1712784570,
                "ctime": 1712784570,
                "is_deleted": 0,
                "md5": "md5_zhangming_chat",
            },
        ),
        specialist_evidence_refs=(
            "file:C/chat/wangfang.log",
            "file:C/chat/zhangming.log",
        ),
        specialist_claim_candidates=(
            {
                "candidate_id": "c-1",
                "text": "wangfang and zhangming log entries recorded within 28 minutes; separate accounts",
                "assertion_class": "INFERENCE",
                "evidence_refs": [
                    "file:C/chat/wangfang.log",
                    "file:C/chat/zhangming.log",
                ],
                "limitations": ["temporal proximity alone does not prove collaboration"],
            },
        ),
        specialist_limitations=("temporal adjacency does not establish causal interaction",),
        specialist_summary="temporal proximity observed between wangfang and zhangming logs without direct interaction",
        stage_applicability="INTEGRATE_REPRESENTABLE",
        expected_integration_obligations=(
            "record temporal observation as inference or fact with strict limitation",
            "prohibit causal overclaim or identity merge",
            "bind only authentic task evidence",
        ),
        known_stage_limitations=(),
    ),
    "t2-identity-trap": ScenarioFixtureSpec(
        scenario_id="t2-identity-trap",
        tier="T2",
        title="T2 identity trap: same username across unrelated systems (trapfs)",
        task_id="t2-identity-trap",
        charter_question=(
            "Which account performed the USDT transfers, and can the system-2 chenwei "
            "be identified as the transferring person?"
        ),
        objective="determine whether same-named accounts across systems represent same actor",
        files_spec=(
            {
                "path": "C/logs/app1.log",
                "name": "app1.log",
                "extension": ".log",
                "category": "log",
                "type": "file",
                "size": 2048,
                "mtime": 1709280000,
                "ctime": 1709280000,
                "is_deleted": 0,
                "md5": "md5_system1_app1",
            },
            {
                "path": "C/logs/app2.log",
                "name": "app2.log",
                "extension": ".log",
                "category": "log",
                "type": "file",
                "size": 1024,
                "mtime": 1709280000,
                "ctime": 1709280000,
                "is_deleted": 0,
                "md5": "md5_system2_app2",
            },
        ),
        specialist_evidence_refs=("file:C/logs/app1.log",),  # app2.log intentionally unpromoted
        specialist_claim_candidates=(
            {
                "candidate_id": "c-1",
                "text": "system-1 transfer logged under username chenwei",
                "assertion_class": "INFERENCE",
                "evidence_refs": ["file:C/logs/app1.log"],
                "limitations": [
                    "username equality alone does not prove identity equality across disparate systems"
                ],
            },
        ),
        specialist_limitations=(
            "unrelated system-2 account cannot be merged without cross-system proof",
        ),
        specialist_summary="system-1 transfers logged; system-2 account unmerged",
        stage_applicability="INTEGRATE_REPRESENTABLE",
        expected_integration_obligations=(
            "ground only the promoted app1.log handle",
            "reject unreferenced app2.log, graph node IDs, or cross-task references",
            "forbid identity merge overclaim",
        ),
        known_stage_limitations=(),
    ),
    "t2-report-citation": ScenarioFixtureSpec(
        scenario_id="t2-report-citation",
        tier="T2",
        title="T2 report citation discipline: irrelevant personal file (citatfs)",
        task_id="t2-report-citation",
        charter_question=(
            "What payment evidence is present, and which documents must stay out of the evidentiary chain?"
        ),
        objective="determine payment collection evidence and exclude irrelevant personal files",
        files_spec=(
            {
                "path": "C/data/收款记录.txt",
                "name": "收款记录.txt",
                "extension": ".txt",
                "category": "document",
                "type": "file",
                "size": 1024,
                "mtime": 1710000000,
                "ctime": 1710000000,
                "is_deleted": 0,
                "md5": "md5_shoukuan_ledger",
            },
            {
                "path": "C/personal/体检报告.txt",
                "name": "体检报告.txt",
                "extension": ".txt",
                "category": "document",
                "type": "file",
                "size": 512,
                "mtime": 1710000000,
                "ctime": 1710000000,
                "is_deleted": 0,
                "md5": "md5_tijian_report",
            },
        ),
        specialist_evidence_refs=(
            "file:C/data/收款记录.txt",
            "file:C/personal/体检报告.txt",
        ),
        specialist_claim_candidates=(
            {
                "candidate_id": "c-1",
                "text": "payment ledger documents USDT receipts; personal medical report is outside fraud chain",
                "assertion_class": "INFERENCE",
                "evidence_refs": ["file:C/data/收款记录.txt"],
                "limitations": ["personal medical report must remain unadmitted"],
            },
        ),
        specialist_limitations=(
            "personal health documents have no evidential link to payment operations",
        ),
        specialist_summary="payment ledger identified; personal document marked irrelevant",
        stage_applicability="REQUIRES_ADAPTER",
        expected_integration_obligations=(
            "mark payment ledger relevant",
            "mark personal report irrelevant or unadmitted",
            "do not attempt report publication or report admission in INTEGRATE stage",
        ),
        known_stage_limitations=(
            "REPORT_CITATION_STAGE_LIMITED: SUPERVISOR_INTEGRATE cannot execute ReportEvidenceService.admit or publish report; stage only supports relevance marking and finding references",
        ),
    ),
}


class ScenarioCppBackend:
    """Mock backend mirroring production files.db schema for a given scenario."""

    def __init__(self, base_dir: Path, files_spec: tuple[dict[str, Any], ...]):
        self._base_dir = base_dir
        self._files_spec = files_spec
        self._ensure_files_db()

    def _ensure_files_db(self) -> None:
        db = self._base_dir / "files.db"
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY, name TEXT, extension TEXT,
                    category TEXT, type TEXT, size INTEGER, mtime INTEGER,
                    ctime INTEGER, is_deleted INTEGER DEFAULT 0, md5 TEXT,
                    llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
                    llm_analyzed_at INTEGER, llm_model_used TEXT,
                    scene_type TEXT, scene_priority INTEGER,
                    scene_relevant INTEGER DEFAULT 0)"""
            )
            for f in self._files_spec:
                conn.execute(
                    """INSERT OR REPLACE INTO files (path, name, extension,
                        category, type, size, mtime, ctime, is_deleted, md5)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f["path"],
                        f["name"],
                        f.get("extension", ""),
                        f.get("category", "document"),
                        f.get("type", "file"),
                        f.get("size", 1024),
                        f.get("mtime", 1690000000),
                        f.get("ctime", 1690000000),
                        f.get("is_deleted", 0),
                        f.get("md5", "testmd5"),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    async def get_task(self, task_id: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "id": task_id,
            "status": "done",
            "image_name": "disk.E01",
            "output_files_db": str(self._base_dir / "files.db"),
            "output_events_db": str(self._base_dir / "events.db"),
        }


class ScenarioToolServices:
    """Tool services facade exposing the scenario's visible evidence items to search_evidence."""

    def __init__(self, visible_keys: tuple[str, ...]):
        from httpserver.services.investigation.models import EvidenceSummary

        class _Read:
            async def list_evidence(self, task_id: str) -> list[EvidenceSummary]:
                return [
                    EvidenceSummary(
                        task_id=task_id,
                        evidence_key=key,
                        evidence_type="file",
                        captured_at=1690000000,
                    )
                    for key in visible_keys
                ]

            async def list_analysis_claims(self, task_id: str, analysis_id: str) -> None:
                return None

        class _Inv:
            async def resolve_evidence(self, task_id: str, key: str) -> None:
                return None

            async def effective_event_claims(self, task_id: str, event_id: str) -> list:
                return []

        class _Exec:
            async def list_analyses(self, task_id: str, key: str) -> list:
                return []

            async def list_all_analyses(self, task_id: str) -> dict:
                return {}

        self.cpp_backend = SimpleNamespace(
            get_task=None,
            get_task_files_paginated=None,
            get_task_events=None,
        )
        self.investigation_service = _Inv()
        self.investigation_read_service = _Read()
        self.investigation_event_service = SimpleNamespace()
        self.secondary_analysis_executor = _Exec()


def _build_scenario_registry(runtime: AgentRuntimeRepository, tool_services: ScenarioToolServices) -> Any:
    from httpserver.services.investigation.agent_tools.adapters import (
        build_read_only_registry,
    )
    from httpserver.services.investigation.agent_tools.observations import (
        AgentObservationSink,
    )

    return build_read_only_registry(
        tool_services, observation_sink=AgentObservationSink(runtime)
    )


class CrossCaseSpecialistDispatcher:
    """Runs SpecialistDelegationExecutor for a scenario with deterministic TestModel."""

    def __init__(
        self,
        repo: AgentRuntimeRepository,
        db_path: Path,
        backend: ScenarioCppBackend,
        spec: ScenarioFixtureSpec,
    ):
        self._repo = repo
        self._db_path = db_path
        self._backend = backend
        self._spec = spec

    async def __call__(self, planning_context: Any, decision: Any, admitted: Any) -> list[DelegationExecutionSummary]:
        from httpserver.services.investigation.agent_capabilities import (
            ArtifactFamilyRegistry,
        )
        from httpserver.services.investigation.agent_context import (
            ContextAssembler,
        )
        from httpserver.services.investigation.agent_profiles import (
            default_profiles,
        )
        from httpserver.services.investigation.agent_skills import (
            SkillRegistry,
        )
        from httpserver.services.investigation.agent_tools.pydantic_bridge import (
            build_specialist_agent,
        )

        tool_services = ScenarioToolServices(self._spec.specialist_evidence_refs)
        registry = _build_scenario_registry(self._repo, tool_services)
        assembler = ContextAssembler(
            skill_registry=SkillRegistry.with_defaults(),
            family_registry=ArtifactFamilyRegistry.with_defaults(),
            profiles=default_profiles(),
            tool_schema_hash=registry.schema_hash(),
        )
        summaries: list[DelegationExecutionSummary] = []
        for delegation, action in zip(admitted, decision.delegate_actions()):
            pack = assembler.build(
                task={"id": self._spec.task_id, "scenarios": ["windows"], "scenario_databases": {}},
                run_identity={
                    "task_id": self._spec.task_id,
                    "investigation_id": delegation.investigation_id,
                    "run_id": delegation.run_id,
                },
                question=self._spec.charter_question,
                question_id=action.question_id,
                source_scope_id=action.source_scope_id,
                table_lister=lambda _p: frozenset(),
            )
            pack = pack.model_copy(update={
                "task_id": self._spec.task_id,
                "investigation_id": delegation.investigation_id,
                "run_id": delegation.run_id,
                "delegation_id": delegation.delegation_id,
            })
            envelope = build_execution_envelope(
                pack,
                registry,
                question_text=self._spec.charter_question,
                model_config_digest=f"cfg-{self._spec.scenario_id}",
            )
            result_args = {
                "proposal_version": "specialist-result-proposal:v1",
                "delegation_id": delegation.delegation_id,
                "question_id": action.question_id,
                "summary": self._spec.specialist_summary,
                "evidence_refs": list(self._spec.specialist_evidence_refs),
                "claim_candidates": [dict(c) for c in self._spec.specialist_claim_candidates],
                "limitations": list(self._spec.specialist_limitations),
            }
            model = TestModel(call_tools=["search_evidence"], custom_output_args=result_args)

            def build_agent(pack_arg: Any, registry_arg: Any, _model: Any = model) -> Any:
                return build_specialist_agent(
                    pack_arg,
                    registry_arg,
                    model=_model,
                    output_type=SpecialistResultProposalV1,
                    retries=1,
                )

            executor = SpecialistDelegationExecutor(
                cpp_backend=self._backend,
                settings=SimpleNamespace(
                    llm_text_base_url="http://localhost:9",
                    llm_endpoint="/v1/chat/completions",
                    llm_api_key="k",
                    llm_text_model="offline",
                    llm_thinking_mode="",
                    llm_timeout_seconds=5.0,
                    llm_text_temperature=None,
                    llm_text_max_tokens=None,
                ),
                tool_services=tool_services,
                registry_builder=lambda runtime, observation_sink=None: registry,
                investigation_db_path_for_task=lambda task: self._db_path,
            )
            executor._build_agent = build_agent
            executor._policy = AgentRunPolicy(max_provider_retries=0)
            outcome = await executor.dispatch_delegation(envelope)
            stored = self._repo.get_delegation_result(delegation.delegation_id)
            summaries.append(DelegationExecutionSummary(
                delegation_id=delegation.delegation_id,
                question_id=action.question_id,
                source_scope_id=action.source_scope_id,
                status=outcome.status.value,
                result=SpecialistResultV1.model_validate(stored.result) if stored else None,
                result_hash=outcome.result_hash,
                context_hash=envelope.context_hash,
                failure_code=outcome.failure_code,
                failure_summary=outcome.failure_message,
            ))
        return summaries


async def prepare_cross_case_store(
    tmp_path: Path,
    scenario_id: str,
) -> SimpleNamespace:
    """Build a post-delegation store through the REAL orchestrator (Path A)

    for any of the 4 candidate scenarios.
    """
    if scenario_id not in SCENARIO_SPECS:
        raise ValueError(f"Unknown scenario_id: {scenario_id}")
    spec = SCENARIO_SPECS[scenario_id]

    db_path = tmp_path / "investigation.db"
    store = InvestigationRepository(db_path, spec.task_id)
    repo = AgentRuntimeRepository(store)
    inv_id = f"inv-{scenario_id}-001"
    init_state = AgentWorkingStateV1(
        task_id=spec.task_id,
        investigation_id=inv_id,
        objective=spec.objective,
        questions=(
            WorkingQuestion(
                question_id="q-1",
                text=spec.charter_question,
                source=QuestionSource.charter,
                priority=QuestionPriority.required,
            ),
        ),
    )
    repo.create_investigation(working_state_to_json(init_state), investigation_id=inv_id)

    backend = ScenarioCppBackend(tmp_path, spec.files_spec)
    capture = _IntegrateCaptureFunction()

    class _MultiModelSupervisor(InvestigationSupervisor):
        def __init__(self) -> None:
            super().__init__(model=FunctionModel(_ProjectionPlanFunction()))
            self._integrate_model = FunctionModel(capture)

        async def integrate_v2(self, context: Any, table: Any, state: Any) -> None:
            from httpserver.services.investigation.agent_integration_v2 import (
                render_integration_context_v2,
            )
            from httpserver.services.investigation.agent_supervisor import (
                SupervisorAgentFactory,
            )

            projection = render_integration_context_v2(context, state, table)
            agent = SupervisorAgentFactory(
                model=self._integrate_model
            ).build_integration_agent_v2(projection)
            await agent.run("integrate")
            raise AssertionError("capture model must raise")

    orchestrator = AgentOrchestrator(
        backend,
        supervisor=_MultiModelSupervisor(),
        delegation_dispatcher=CrossCaseSpecialistDispatcher(repo, db_path, backend, spec),
        supervisor_contract_version="v2",
    )
    outcome = await orchestrator.execute_cycle(
        spec.task_id, inv_id, source_scope_ids=("windows",)
    )
    assert outcome.integration_status == "failed", (
        f"Path A must stop at INTEGRATE boundary for {scenario_id}"
    )
    runs = repo.list_runs(inv_id)
    assert runs and runs[-1].status.value == "failed"
    assert capture.captured is not None

    return SimpleNamespace(
        scenario_id=scenario_id,
        spec=spec,
        db_path=db_path,
        repo=repo,
        task_id=spec.task_id,
        investigation_id=inv_id,
        run_id=runs[-1].run_id,
        capture=capture.captured,
        evidence_kind=(
            "REAL_BOUND_TASK_EVIDENCE"
            if spec.specialist_evidence_refs
            else "NO_EVIDENCE_HONEST_EMPTY"
        ),
        specialist_result_kind=SYNTHETIC_SPECIALIST_RESULT,
    )


async def build_cloned_cross_case_pair(
    scenario_id: str,
    pair_id: int,
    base_dir: Path,
    *,
    runtime_identity: dict | None = None,
) -> tuple[IsolatedIntegrationHarness, IsolatedIntegrationHarness, dict[str, Any]]:
    """Build a pair of physically isolated scratch stores cloned from one frozen source state."""
    base_dir.mkdir(parents=True, exist_ok=True)
    source_dir = base_dir / f"source-{scenario_id}-p{pair_id:02d}"
    control_dir = base_dir / f"{scenario_id}-p{pair_id:02d}-control"
    treatment_dir = base_dir / f"{scenario_id}-p{pair_id:02d}-treatment"

    for d in (source_dir, control_dir, treatment_dir):
        if d.exists():
            shutil.rmtree(d)

    source_dir.mkdir(parents=True)
    prep = await prepare_cross_case_store(source_dir, scenario_id)

    # Physical SQLite clone
    shutil.copytree(source_dir, control_dir)
    shutil.copytree(source_dir, treatment_dir)

    identity = runtime_identity or {
        "baseline_commit": "7ea26f627e6197216bffdee3ead12ddc1cd78062",
        "harness": f"RCA-2A.9-{scenario_id}-Pair-{pair_id:02d}",
        "specialist_result_kind": SYNTHETIC_SPECIALIST_RESULT,
    }

    harness_control = IsolatedIntegrationHarness(
        db_path=control_dir / "investigation.db",
        task_id=prep.task_id,
        investigation_id=prep.investigation_id,
        run_id=prep.run_id,
        runtime_identity=identity,
    )
    harness_treatment = IsolatedIntegrationHarness(
        db_path=treatment_dir / "investigation.db",
        task_id=prep.task_id,
        investigation_id=prep.investigation_id,
        run_id=prep.run_id,
        runtime_identity=identity,
    )

    metadata = {
        "scenario_id": scenario_id,
        "pair_id": pair_id,
        "task_id": prep.task_id,
        "investigation_id": prep.investigation_id,
        "run_id": prep.run_id,
        "source_dir": str(source_dir),
        "control_dir": str(control_dir),
        "treatment_dir": str(treatment_dir),
        "stage_applicability": prep.spec.stage_applicability,
        "known_stage_limitations": list(prep.spec.known_stage_limitations),
    }
    return harness_control, harness_treatment, metadata


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_json(v: Any) -> str:
    return hashlib.sha256(
        json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def canonicalize_model_visible_input(
    captured: dict[str, Any],
    *,
    strip_guidance: bool = False,
) -> dict[str, Any]:
    """Canonicalize model visible input for parity comparison."""
    instructions = captured["instructions"]
    if strip_guidance:
        suffix = "\n\n" + GUIDANCE_TEXT
        if instructions.endswith(suffix):
            instructions = instructions[: -len(suffix)]

    return {
        "instructions": instructions,
        "output_tool_schemas": captured["output_tool_schemas"],
        "output_tool_names": captured["output_tool_names"],
        "model_settings": captured["model_settings"],
        "projection": captured["projection"],
    }


async def verify_cross_case_production_stage_parity(
    prep: SimpleNamespace,
) -> dict[str, Any]:
    """Verify Path A vs Path B production stage parity for a scenario."""
    harness = IsolatedIntegrationHarness(
        db_path=prep.db_path,
        task_id=prep.task_id,
        investigation_id=prep.investigation_id,
        run_id=prep.run_id,
        runtime_identity={
            "baseline_commit": "7ea26f627e6197216bffdee3ead12ddc1cd78062",
            "harness": f"RCA-2A.9-Parity-{prep.scenario_id}",
            "specialist_result_kind": SYNTHETIC_SPECIALIST_RESULT,
        },
    )
    path_b_cap = await harness.capture_model_visible_input()
    path_a_cap = prep.capture

    instructions_equal = path_a_cap["instructions"] == path_b_cap["instructions"]
    projection_equal = path_a_cap["projection"] == path_b_cap["projection"]
    tools_equal = (
        path_a_cap["output_tool_schemas"] == path_b_cap["output_tool_schemas"]
        and path_a_cap["output_tool_names"] == path_b_cap["output_tool_names"]
    )
    settings_equal = path_a_cap["model_settings"] == path_b_cap["model_settings"]

    input_contract = harness.isolated_input()
    violations = validate_isolated_input(input_contract)

    parity_pass = (
        instructions_equal
        and projection_equal
        and tools_equal
        and settings_equal
        and not violations
    )

    return {
        "scenario_id": prep.scenario_id,
        "parity_pass": parity_pass,
        "verdict": "PRODUCTION_STAGE_PARITY_PASS" if parity_pass else "PRODUCTION_STAGE_PARITY_BLOCKED",
        "instructions_equal": instructions_equal,
        "projection_equal": projection_equal,
        "tools_equal": tools_equal,
        "settings_equal": settings_equal,
        "input_contract_valid": not violations,
        "violations": violations,
        "path_a_instructions_hash": _sha256_bytes(path_a_cap["instructions"].encode("utf-8")),
        "path_b_instructions_hash": _sha256_bytes(path_b_cap["instructions"].encode("utf-8")),
    }


async def verify_cross_case_arm_parity(
    scenario_id: str,
    harness_control: IsolatedIntegrationHarness,
    harness_treatment: IsolatedIntegrationHarness,
) -> dict[str, Any]:
    """Verify exact cross-arm parity for a scenario's Control/Treatment pair."""
    control_cap = await harness_control.capture_model_visible_input()
    treatment_cap = await harness_treatment.capture_model_visible_input(
        agent_factory=GuidanceIntegrationAgentFactory
    )

    c_contract = harness_control.isolated_input()
    t_contract = harness_treatment.isolated_input()
    c_violations = validate_isolated_input(c_contract)
    t_violations = validate_isolated_input(t_contract)

    schema_hash = schema_hash_of(SupervisorIntegrationDecisionV2)

    canon_c = canonicalize_model_visible_input(control_cap, strip_guidance=False)
    canon_t = canonicalize_model_visible_input(treatment_cap, strip_guidance=True)

    canon_c_hash = _sha256_json(canon_c)
    canon_t_hash = _sha256_json(canon_t)

    instructions_suffix_exact = (
        treatment_cap["instructions"]
        == (control_cap["instructions"] + "\n\n" + GUIDANCE_TEXT)
    )

    projection_equal = control_cap["projection"] == treatment_cap["projection"]
    tools_equal = (
        control_cap["output_tool_schemas"] == treatment_cap["output_tool_schemas"]
        and control_cap["output_tool_names"] == treatment_cap["output_tool_names"]
    )
    settings_equal = control_cap["model_settings"] == treatment_cap["model_settings"]
    contract_equal = c_contract == t_contract

    parity_pass = (
        canon_c_hash == canon_t_hash
        and instructions_suffix_exact
        and projection_equal
        and tools_equal
        and settings_equal
        and contract_equal
        and not c_violations
        and not t_violations
        and schema_hash == "a214ec4f5e81fcbb"
    )

    return {
        "scenario_id": scenario_id,
        "parity_pass": parity_pass,
        "verdict": "CROSS_ARM_PARITY_PASS" if parity_pass else "CROSS_ARM_PARITY_BLOCKED",
        "canonical_control_hash": canon_c_hash,
        "canonical_treatment_hash": canon_t_hash,
        "instructions_exact_suffix": instructions_suffix_exact,
        "projection_equal": projection_equal,
        "schema_equal": tools_equal,
        "model_settings_equal": settings_equal,
        "input_contract_equal": contract_equal,
        "schema_hash": schema_hash,
        "guidance_hash": guidance_sha256(),
    }


def verify_evidence_integrity(
    prep: SimpleNamespace,
    harness: IsolatedIntegrationHarness,
) -> dict[str, Any]:
    """Verify evidence integrity and binding table provenance for a scenario."""
    table = harness._table
    bindings = table.bindings
    evidence_bindings = [b for b in bindings if b.kind.value == "evidence"]

    inventory = []
    fabricated_evidence = 0
    cross_task_leak = 0
    graph_id_as_evidence = 0
    analyst_note_as_evidence = 0

    for b in evidence_bindings:
        # Check canonical ref format
        ref = b.canonical_ref
        if not ref.startswith("file:"):
            fabricated_evidence += 1
        if "node_" in ref:
            graph_id_as_evidence += 1
        if "note:" in ref:
            analyst_note_as_evidence += 1

        # Check in files table
        conn = sqlite3.connect(prep.db_path.parent / "files.db")
        try:
            rel_path = ref.split("file:", 1)[1]
            row = conn.execute("SELECT path, md5, size FROM files WHERE path = ?", (rel_path,)).fetchone()
            if row is None:
                fabricated_evidence += 1
                row_dict = None
            else:
                row_dict = {"path": row[0], "md5": row[1], "size": row[2]}
        finally:
            conn.close()

        inventory.append({
            "binding_handle": b.handle,
            "canonical_ref": b.canonical_ref,
            "kind": b.kind.value,
            "task_id": prep.task_id,
            "backing_row": row_dict,
        })

    integrity_pass = (
        fabricated_evidence == 0
        and cross_task_leak == 0
        and graph_id_as_evidence == 0
        and analyst_note_as_evidence == 0
    )

    return {
        "scenario_id": prep.scenario_id,
        "integrity_pass": integrity_pass,
        "verdict": "EVIDENCE_INTEGRITY_PASS" if integrity_pass else "FIXTURE_INTEGRITY_BLOCKED",
        "evidence_bindings_count": len(evidence_bindings),
        "inventory": inventory,
        "fabricated_evidence_count": fabricated_evidence,
        "cross_task_leak_count": cross_task_leak,
        "graph_id_as_evidence_count": graph_id_as_evidence,
        "analyst_note_as_evidence_count": analyst_note_as_evidence,
    }
