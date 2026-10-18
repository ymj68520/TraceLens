"""P3 freeze follow-up F2: atomic observation+trajectory audit pair.

Invariants under test:
    successful tool action -> observation + trajectory both exist
    observation insert failure -> trajectory rolled back (and vice versa)
    invalid Evidence ref -> neither record persisted
    duplicate replay -> exactly one of each
    restart -> visibility still reconstructs from observations only
    Observation != Evidence; Trajectory != Evidence
"""

import sqlite3

import pytest
from pydantic import BaseModel, ConfigDict

from httpserver.services.investigation import agent_runtime as agent_runtime_module
from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
)
from httpserver.services.investigation.agent_tools.context import (
    ForensicToolContext,
    ToolBudgetPolicy,
)
from httpserver.services.investigation.agent_tools.definitions import (
    EvidenceBehavior,
    ForensicToolDefinition,
    ToolAccess,
    ToolCategory,
    ToolCostClass,
    ToolPaginationKind,
    ToolScopeKind,
)
from httpserver.services.investigation.agent_tools.errors import ToolExecutionError
from httpserver.services.investigation.agent_tools.observations import (
    AgentObservationSink,
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

    note: str = "done"


def _definition() -> ForensicToolDefinition:
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
        return ToolExecutionOutcome(
            summary="found file:C/decoy.doc",
            result=RefsOutput(),
            evidence_refs=refs,
        )

    registry.register(_definition(), adapter)
    return registry


def _trajectory_events(repo, investigation_id):
    return [
        t
        for t in repo.list_trajectory(investigation_id)
        if t.event_type == AgentTrajectoryEventType.tool_observation_recorded
    ]


@pytest.fixture()
def env(tmp_path):
    db_path = tmp_path / "investigation.db"
    store = InvestigationRepository(db_path, "task-A")
    repo = AgentRuntimeRepository(store)
    investigation, _ = repo.create_investigation({"objective": "audit"})
    run = repo.start_run(investigation.investigation_id)
    repo.mark_run_running(run.run_id)
    context = ForensicToolContext(
        task_id="task-A",
        investigation_id=investigation.investigation_id,
        run_id=run.run_id,
        allowed_tool_ids=frozenset({"reveal_refs"}),
    )
    return repo, context, db_path


async def test_successful_call_persists_exactly_one_pair(env):
    repo, context, _db = env
    registry = make_registry(repo)
    await registry.execute(context, "reveal_refs", {"refs": ("file:C/x.doc",)})
    observations = repo.list_tool_observations(context.investigation_id)
    events = _trajectory_events(repo, context.investigation_id)
    assert len(observations) == 1
    assert len(events) == 1
    assert events[0].payload["observation_id"] == observations[0].observation_id
    assert events[0].payload["input_fingerprint"]
    assert events[0].payload["evidence_ref_count"] == 1
    assert events[0].run_id == context.run_id


async def test_observation_insert_failure_rolls_back_trajectory(env, monkeypatch):
    repo, context, _db = env
    # pre-insert an observation that the (forced) next insert will collide with
    fixed_id = "obs_forced_collision"
    with sqlite3.connect(context and env[2]) as raw:
        raw.execute(
            "INSERT INTO agent_tool_observations "
            "(observation_id, task_id, investigation_id, run_id, delegation_id, "
            " tool_id, summary, result_json, evidence_refs_json, result_count, "
            " truncated, created_at) VALUES "
            "(?, ?, ?, ?, NULL, 'seed', 'seed', '{}', '[]', 0, 0, 'now')",
            (fixed_id, "task-A", context.investigation_id, context.run_id),
        )
        raw.commit()
    monkeypatch.setattr(
        agent_runtime_module, "_new_observation_id", lambda: fixed_id
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.record_tool_observation(
            context.investigation_id,
            tool_id="reveal_refs",
            summary="s",
            result={"schema_version": "tool-observation:v1"},
            evidence_refs=("file:C/x.doc",),
            run_id=context.run_id,
            trajectory_payload={"observation_id": fixed_id},
        )
    # atomic: neither half of the pair survived the failed insert
    assert len(repo.list_tool_observations(context.investigation_id)) == 1  # seed only
    assert _trajectory_events(repo, context.investigation_id) == []


async def test_trajectory_insert_failure_rolls_back_observation(env, monkeypatch):
    repo, context, _db = env

    def _explode(*args, **kwargs):
        raise RuntimeError("trajectory write failed")

    monkeypatch.setattr(
        AgentRuntimeRepository, "_append_trajectory_with_conn", _explode
    )
    with pytest.raises(RuntimeError):
        repo.record_tool_observation(
            context.investigation_id,
            tool_id="reveal_refs",
            summary="s",
            result={"schema_version": "tool-observation:v1"},
            evidence_refs=("file:C/x.doc",),
            run_id=context.run_id,
        )
    assert repo.list_tool_observations(context.investigation_id) == []
    assert _trajectory_events(repo, context.investigation_id) == []


async def test_invalid_evidence_ref_persists_neither_record(env):
    repo, context, _db = env
    registry = make_registry(repo)
    with pytest.raises(ToolExecutionError):
        await registry.execute(
            context, "reveal_refs", {"refs": ("garbage-ref",), "invalid": True}
        )
    assert repo.list_tool_observations(context.investigation_id) == []
    assert _trajectory_events(repo, context.investigation_id) == []


async def test_duplicate_replay_persists_no_second_pair(env):
    repo, context, _db = env
    registry = make_registry(repo)
    context = ForensicToolContext(
        task_id=context.task_id,
        investigation_id=context.investigation_id,
        run_id=context.run_id,
        allowed_tool_ids=context.allowed_tool_ids,
        budget=ToolBudgetPolicy(max_duplicate_calls=1),
    )
    await registry.execute(context, "reveal_refs", {"refs": ("file:C/x.doc",)})
    with pytest.raises(ToolExecutionError):
        await registry.execute(context, "reveal_refs", {"refs": ("file:C/x.doc",)})
    assert len(repo.list_tool_observations(context.investigation_id)) == 1
    assert len(_trajectory_events(repo, context.investigation_id)) == 1


async def test_restart_visibility_uses_observations_not_trajectory(env):
    repo, context, db_path = env
    registry = make_registry(repo)
    await registry.execute(context, "reveal_refs", {"refs": ("file:C/x.doc",)})

    reopened = AgentRuntimeRepository(InvestigationRepository(db_path, "task-A"))
    observations = reopened.list_tool_observations(context.investigation_id)
    visible = reconstruct_allowed_evidence_ids(INITIAL_REFS, observations)
    assert visible == frozenset({"file:C/start.doc", "file:C/x.doc"})

    # trajectory presence cannot alter visibility: the reconstruction input
    # is the observation list only — trajectory rows are not a source
    trajectory_count = len(_trajectory_events(reopened, context.investigation_id))
    assert trajectory_count == 1
    visible_again = reconstruct_allowed_evidence_ids(INITIAL_REFS, observations)
    assert visible_again == visible


def test_trajectory_is_action_trace_not_evidence(env):
    """Observation != Evidence; Trajectory != Evidence."""
    repo, context, _db = env
    repo.record_tool_observation(
        context.investigation_id,
        tool_id="reveal_refs",
        summary="s",
        result={"schema_version": "tool-observation:v1"},
        evidence_refs=("file:C/x.doc",),
        run_id=context.run_id,
        trajectory_payload={
            "tool_id": "reveal_refs",
            "evidence_ref_count": 1,
        },
    )
    event = _trajectory_events(repo, context.investigation_id)[0]
    # counts only — the trajectory never carries the refs themselves
    assert event.payload["evidence_ref_count"] == 1
    assert "evidence_refs" not in event.payload
    assert "file:C/x.doc" not in str(event.payload)
