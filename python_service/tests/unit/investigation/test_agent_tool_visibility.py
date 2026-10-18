"""P3-2 observation / evidence-visibility tests (work order §55).

Visibility is reconstructable from durable records only: the initial
ContextPack refs (simulated here as the run's starting set) plus successful
ToolObservation rows. No process memory participates.
"""

import pytest
from pydantic import BaseModel, ConfigDict

from httpserver.services.investigation.agent_runtime import AgentRuntimeRepository
from httpserver.services.investigation.agent_tools.definitions import (
    EvidenceBehavior,
    ForensicToolDefinition,
    ToolAccess,
    ToolCategory,
    ToolCostClass,
    ToolPaginationKind,
    ToolScopeKind,
)
from httpserver.services.investigation.agent_tools.context import ForensicToolContext
from httpserver.services.investigation.agent_tools.errors import (
    ToolErrorCode,
    ToolExecutionError,
)
from httpserver.services.investigation.agent_tools.observations import (
    AgentObservationSink,
    build_observation_record,
)
from httpserver.services.investigation.agent_tools.registry import (
    ForensicToolRegistry,
    ToolExecutionOutcome,
)
from httpserver.services.investigation.agent_tools.visibility import (
    reconstruct_allowed_evidence_ids,
)
from httpserver.services.investigation.repository import InvestigationRepository

pytestmark = pytest.mark.migration_matrix

INITIAL_REFS = ("file:C/start.doc",)


class RefsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refs: tuple[str, ...] = ()
    fail: bool = False
    invalid: bool = False


class RefsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_text: str = "done"


def _reveal_definition() -> ForensicToolDefinition:
    return ForensicToolDefinition(
        tool_id="reveal_refs",
        version="1",
        title="Reveal",
        description="test adapter",
        input_model=RefsInput,
        output_model=RefsOutput,
        category=ToolCategory.EVIDENCE,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.EVIDENCE,
        evidence_behavior=EvidenceBehavior.EVIDENCE_PRODUCING,
        cost_class=ToolCostClass.CHEAP,
        pagination_kind=ToolPaginationKind.NONE,
    )


def make_registry(repo) -> ForensicToolRegistry:
    registry = ForensicToolRegistry(observation_sink=AgentObservationSink(repo))

    async def adapter(invocation) -> ToolExecutionOutcome:
        args: RefsInput = invocation.args
        if args.fail:
            raise RuntimeError("boom")
        refs = ("garbage-ref",) if args.invalid else args.refs
        # summary/data may contain ref-looking strings that are NOT evidence
        return ToolExecutionOutcome(
            summary="found file:C/decoy.doc",
            result=RefsOutput(summary_text="look at file:C/decoy.doc"),
            evidence_refs=refs,
        )

    registry.register(_reveal_definition(), adapter)
    return registry


@pytest.fixture()
def env(tmp_path):
    db_path = tmp_path / "investigation.db"
    store = InvestigationRepository(db_path, "task-A")
    repo = AgentRuntimeRepository(store)
    investigation, _ = repo.create_investigation({"objective": "vis"})
    run = repo.start_run(investigation.investigation_id)
    repo.mark_run_running(run.run_id)
    context = ForensicToolContext(
        task_id="task-A",
        investigation_id=investigation.investigation_id,
        run_id=run.run_id,
        allowed_tool_ids=frozenset({"reveal_refs"}),
    )
    return repo, context, db_path


async def test_initial_context_refs_visible(env):
    visible = reconstruct_allowed_evidence_ids(INITIAL_REFS, [])
    assert visible == frozenset(INITIAL_REFS)


async def test_observation_refs_become_reconstructably_visible(env):
    repo, context, _db_path = env
    registry = make_registry(repo)
    await registry.execute(
        context, "reveal_refs", {"refs": ("file:C/x.doc", "file:C/y.doc")}
    )
    visible = reconstruct_allowed_evidence_ids(
        INITIAL_REFS,
        repo.list_tool_observations(context.investigation_id),
        delegation_id=context.delegation_id,
        run_id=context.run_id,
    )
    assert visible == frozenset(
        {"file:C/start.doc", "file:C/x.doc", "file:C/y.doc"}
    )


async def test_summary_text_never_enters_visibility(env):
    """Observation != Evidence: only evidence_refs count, not data/summary."""
    repo, context, _db_path = env
    registry = make_registry(repo)
    await registry.execute(context, "reveal_refs", {"refs": ()})
    visible = reconstruct_allowed_evidence_ids(
        INITIAL_REFS, repo.list_tool_observations(context.investigation_id)
    )
    assert "file:C/decoy.doc" not in visible


async def test_failed_tool_result_adds_no_visibility(env):
    repo, context, _db_path = env
    registry = make_registry(repo)
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(
            context, "reveal_refs", {"refs": ("file:C/z.doc",), "fail": True}
        )
    assert excinfo.value.code == ToolErrorCode.TOOL_ADAPTER_FAILED
    visible = reconstruct_allowed_evidence_ids(
        INITIAL_REFS, repo.list_tool_observations(context.investigation_id)
    )
    assert "file:C/z.doc" not in visible


async def test_invalid_ref_never_enters_visibility(env):
    repo, context, _db_path = env
    registry = make_registry(repo)
    with pytest.raises(ToolExecutionError):
        await registry.execute(
            context, "reveal_refs", {"refs": ("garbage-ref",), "invalid": True}
        )
    visible = reconstruct_allowed_evidence_ids(
        INITIAL_REFS, repo.list_tool_observations(context.investigation_id)
    )
    assert "garbage-ref" not in visible


async def test_visibility_reconstructable_after_restart(env):
    repo, context, db_path = env
    registry = make_registry(repo)
    await registry.execute(context, "reveal_refs", {"refs": ("file:C/x.doc",)})

    # simulate a restart: fresh repository objects over the same store
    reopened = AgentRuntimeRepository(InvestigationRepository(db_path, "task-A"))
    visible = reconstruct_allowed_evidence_ids(
        INITIAL_REFS,
        reopened.list_tool_observations(context.investigation_id),
        run_id=context.run_id,
    )
    assert "file:C/x.doc" in visible
    assert "file:C/start.doc" in visible


def test_other_delegation_observations_do_not_leak(env):
    repo, context, _db_path = env
    record = build_observation_record(
        _reveal_definition(),
        ToolExecutionOutcome(
            summary="s",
            result=RefsOutput(),
            evidence_refs=("file:C/other_delegation.doc",),
        ),
        input_fingerprint="fp",
        context=context,
    )
    repo.append_tool_observation(
        context.investigation_id,
        tool_id="reveal_refs",
        summary=record.summary,
        result=record.model_dump(),
        evidence_refs=("file:C/other_delegation.doc",),
        run_id=context.run_id,
        delegation_id=None,  # observation of a different (anonymous) delegation
    )
    visible = reconstruct_allowed_evidence_ids(
        INITIAL_REFS,
        repo.list_tool_observations(context.investigation_id),
        delegation_id="delegation-1",
    )
    assert "file:C/other_delegation.doc" not in visible
