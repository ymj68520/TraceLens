"""P3-4 tests: SpecialistContextPack + ContextAssembler (work order §59)
plus the completed PydanticAI bridge (context pack -> run-ready agent)."""

from types import SimpleNamespace
from typing import Optional

import pytest
from pydantic import BaseModel, ConfigDict

from httpserver.services.investigation.agent_capabilities import (
    ArtifactFamilyRegistry,
)
from httpserver.services.investigation.agent_context import (
    OUTPUT_CONTRACT_REF,
    ContextAssembler,
    ContextCaseNote,
    EvidenceDigestItem,
    SpecialistContextPack,
)
from httpserver.services.investigation.agent_deps import ForensicAgentDeps
from httpserver.services.investigation.agent_profiles import default_profiles
from httpserver.services.investigation.agent_skills import SkillRegistry
from httpserver.services.investigation.agent_tools.adapters.base import (
    ToolCatalogConfig,
)
from httpserver.services.investigation.agent_tools.pydantic_bridge import (
    ModelRequiredError,
    build_pydantic_toolset,
    build_specialist_agent,
)

pytest.importorskip("pydantic_ai")

TASK = {
    "id": "task-A",
    "scenarios": ["windows"],
    "scenario_databases": {"windows": "/fake/windows.db"},
    "output_files_db": "/fake/files.db",
    "output_events_db": "/fake/events.db",
}
RUN = {"task_id": "task-A", "investigation_id": "inv-A", "run_id": "run-A"}


def _tables_of(names):
    return lambda _p: frozenset(names)


def _assembler() -> ContextAssembler:
    from httpserver.services.investigation.agent_tools.adapters import (
        build_read_only_registry,
    )

    registry = build_read_only_registry(services=_NullServices())
    return ContextAssembler(
        skill_registry=SkillRegistry.with_defaults(),
        family_registry=ArtifactFamilyRegistry.with_defaults(),
        profiles=default_profiles(),
        tool_schema_hash=registry.schema_hash(),
    )


class _NullServices:
    """Assembler never touches services; registry build needs the bundle."""

    def __getattr__(self, name):
        raise AssertionError("services must not be touched during assembly")


def _build_pack(assembler: ContextAssembler, **overrides) -> SpecialistContextPack:
    fields = dict(
        task=TASK,
        run_identity=RUN,
        question="unusual logons on the workstation?",
        source_scope_id="windows",
        coverage_dimension_ids=("authentication",),
        constraints=("report in Chinese",),
        case_context=(
            ContextCaseNote(kind="case_context", text="fraud case background"),
        ),
        finding_refs=("finding-1",),
        evidence_digests=(
            EvidenceDigestItem(
                evidence_key="file:C/evtx.sys.log",
                kind="file",
                title="event log export",
                summary_digest="abc",
            ),
        ),
        working_state_revision=3,
        working_state_hash="cafe1234",
        table_lister=_tables_of({"registry_values", "event_log_entries", "user_accounts", "usb_devices"}),
    )
    fields.update(overrides)
    return assembler.build(**fields)


# ---------------------------------------------------------------------------
# determinism + hash coverage (P3-E18)
# ---------------------------------------------------------------------------


def test_same_input_same_context_hash():
    assembler = _assembler()
    pack = _build_pack(assembler)
    pack_again = _build_pack(assembler)
    assert pack.input_hash() == pack_again.input_hash()
    assert pack.model_dump() == pack_again.model_dump()


def test_hash_covers_state_question_profile_skills_manifest_tools():
    assembler = _assembler()
    baseline = _build_pack(assembler)

    changed_state = _build_pack(assembler, working_state_revision=4)
    assert changed_state.input_hash() != baseline.input_hash()

    changed_question = _build_pack(assembler, question="usb device history?")
    assert changed_question.input_hash() != baseline.input_hash()

    changed_scope = _build_pack(assembler, source_scope_id="android")
    assert changed_scope.input_hash() != baseline.input_hash()

    changed_evidence = _build_pack(
        assembler,
        evidence_digests=(
            EvidenceDigestItem(evidence_key="file:C/other.doc", kind="file"),
        ),
    )
    assert changed_evidence.input_hash() != baseline.input_hash()


def test_hash_is_order_insensitive_for_sets():
    assembler = _assembler()
    pack_a = _build_pack(
        assembler,
        evidence_digests=(
            EvidenceDigestItem(evidence_key="file:C/a.doc", kind="file"),
            EvidenceDigestItem(evidence_key="file:C/b.doc", kind="file"),
        ),
    )
    pack_b = _build_pack(
        assembler,
        evidence_digests=(
            EvidenceDigestItem(evidence_key="file:C/b.doc", kind="file"),
            EvidenceDigestItem(evidence_key="file:C/a.doc", kind="file"),
        ),
    )
    assert pack_a.input_hash() == pack_b.input_hash()


# ---------------------------------------------------------------------------
# pack content contracts (P3-E19, P3-E20)
# ---------------------------------------------------------------------------


def test_evidence_digests_only_no_full_evidence():
    assembler = _assembler()
    pack = _build_pack(assembler)
    for item in pack.evidence_digests:
        assert item.evidence_key
        assert not hasattr(item, "content")
    serialized = str(pack.model_dump())
    assert "PRECIOUS" not in serialized


def test_case_context_is_context_only_and_outside_visibility():
    assembler = _assembler()
    pack = _build_pack(assembler)
    assert pack.relevant_case_context
    assert all(note.context_only for note in pack.relevant_case_context)
    # visibility is not derived from case context anywhere in the pack:
    context = pack.tool_context()
    assert context.context_hash == pack.input_hash()
    serialized = pack.model_dump()
    case_notes = serialized["relevant_case_context"]
    assert all(note["context_only"] for note in case_notes)


def test_skills_resolved_against_profile_and_registry():
    assembler = _assembler()
    pack = _build_pack(assembler)
    assert pack.profile.profile_id == "windows.specialist"
    assert "windows.authentication" in (
        pack.resolved_skills.primary_skills + pack.resolved_skills.supporting_skills
    )
    assert set(pack.resolved_skills.resolved_tool_ids) <= set(pack.allowed_tool_ids)


def test_unavailable_platform_artifacts_tool_omitted():
    assembler = _assembler()
    # no parsed tables -> every family unavailable -> the platform-artifact
    # tool is omitted from the allowed surface
    empty = _build_pack(assembler, table_lister=_tables_of(set()))
    assert "query_platform_artifacts" not in empty.allowed_tool_ids
    available = _build_pack(
        assembler, table_lister=_tables_of({"registry_values"})
    )
    assert "query_platform_artifacts" in available.allowed_tool_ids


def test_graph_context_absent_and_no_chat_history():
    assembler = _assembler()
    pack = _build_pack(assembler)
    assert "graph" not in pack.model_dump()
    assert "chat" not in pack.model_dump()
    assert "messages" not in pack.model_dump()


def test_output_contract_ref_is_p4_placeholder():
    assembler = _assembler()
    pack = _build_pack(assembler)
    assert pack.output_contract_ref == OUTPUT_CONTRACT_REF


def test_unknown_scope_profile_fails_deterministically():
    assembler = _assembler()
    with pytest.raises(KeyError):
        _build_pack(assembler, source_scope_id="memory")


def test_working_state_anchors_carried():
    assembler = _assembler()
    pack = _build_pack(assembler)
    assert pack.working_state_revision == 3
    assert pack.working_state_hash == "cafe1234"
    assert pack.tool_schema_hash


# ---------------------------------------------------------------------------
# layered view + bridge completion (P3-E21 foundation, no EXECUTE wiring)
# ---------------------------------------------------------------------------


def test_layered_view_l0_to_l7():
    assembler = _assembler()
    pack = _build_pack(assembler)
    layers = dict(pack.layered_view())
    assert list(layers)[:1] == ["L0_system_invariants"]
    for expected in (
        "L0_system_invariants",
        "L1_investigation_contract",
        "L2_profile",
        "L3_skills",
        "L4_working_state_refs",
        "L5_evidence_digests",
        "L6_allowed_tools",
        "L7_output_contract",
    ):
        assert expected in layers


def test_build_specialist_agent_requires_explicit_model():
    assembler = _assembler()
    pack = _build_pack(assembler)
    with pytest.raises(ModelRequiredError):
        build_specialist_agent(pack, registry=_StubRegistry())


class _StubRegistry:
    def iter_definitions(self):
        return []

    def resolve_definition(self, tool_id):
        raise KeyError(tool_id)

    async def execute(self, context, tool_id, args):
        raise AssertionError("not executed in this test")


async def test_specialist_agent_constructs_and_runs_offline():
    from pydantic_ai.models.test import TestModel

    assembler = _assembler()
    pack = _build_pack(assembler)
    agent = build_specialist_agent(
        pack,
        _StubRegistry(),
        model=TestModel(call_tools=[], custom_output_text="ok"),
    )
    assert agent.deps_type is ForensicAgentDeps
    context = pack.tool_context()
    deps = ForensicAgentDeps(
        task_id=context.task_id,
        investigation_id=context.investigation_id,
        run_id=context.run_id,
        allowed_tool_ids=frozenset(
            tool_id
            for tool_id in context.allowed_tool_ids
            if tool_id in {"get_task_context"}
        ),
        tool_registry=_StubRegistry(),
        tool_context=context,
    )
    result = await agent.run("smoke", deps=deps)
    assert result.output == "ok"
