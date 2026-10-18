"""Task/Source context tool (P3 §20)."""

from typing import Any

from pydantic import BaseModel, ConfigDict

from ..errors import ToolErrorCode, ToolExecutionError
from ..registry import ToolExecutionOutcome
from .base import ToolCatalogConfig
from .services import ForensicToolServices


class GetTaskContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceScopeDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_scope_id: str  # scenario key, e.g. "windows"
    database_kinds: tuple[str, ...] = ()  # logical db kinds, never paths


class GetTaskContextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: str | None = None
    image_name: str | None = None
    platforms: tuple[str, ...] = ()
    android_source: str | None = None
    filter_profile: str | None = None
    source_scopes: tuple[SourceScopeDigest, ...] = ()
    case_description_present: bool = False
    limitations: tuple[str, ...] = ()


def _scenario_list(task: dict[str, Any]) -> tuple[str, ...]:
    raw = task.get("scenarios") or ()
    return tuple(sorted({str(item) for item in raw}))


def _shared_db_kinds(task: dict[str, Any]) -> set[str]:
    kinds = set()
    if task.get("output_files_db"):
        kinds.add("files")
    if task.get("output_events_db"):
        kinds.add("events")
    if task.get("output_raw_db"):
        kinds.add("raw")
    return kinds


def _scenario_db_map(task: dict[str, Any]) -> dict[str, str]:
    value = task.get("scenario_databases")
    return dict(value) if isinstance(value, dict) else {}


def build_task_context_tool(
    services: ForensicToolServices, config: ToolCatalogConfig
):
    async def adapter(invocation) -> ToolExecutionOutcome:
        task_id = invocation.context.task_id
        task = await services.cpp_backend.get_task(task_id)
        if task is None:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_NOT_FOUND,
                "task context unavailable for this run",
            )
        scenarios = _scenario_list(task)
        scenario_dbs = _scenario_db_map(task)
        shared = sorted(_shared_db_kinds(task))
        scopes = []
        for scenario in scenarios:
            kinds = list(shared)
            if scenario in scenario_dbs:
                kinds.append(scenario)
            scopes.append(
                SourceScopeDigest(
                    source_scope_id=scenario,
                    database_kinds=tuple(sorted(kinds)),
                )
            )
        limitations = []
        if not scenarios:
            limitations.append(
                "task metadata exposes no platform scenario; source "
                "capabilities are reported per registered scenario only"
            )
        output = GetTaskContextOutput(
            task_id=task_id,
            status=task.get("status"),
            image_name=task.get("image_name"),
            platforms=scenarios,
            android_source=task.get("android_source"),
            filter_profile=task.get("filter_profile"),
            source_scopes=tuple(scopes),
            case_description_present=bool(task.get("case_description")),
            limitations=tuple(limitations),
        )
        return ToolExecutionOutcome(
            summary=(
                f"task {output.task_id} with platforms "
                f"{','.join(output.platforms) or 'none'}"
            ),
            result=output,
        )

    from ..definitions import (
        EvidenceBehavior,
        ForensicToolDefinition,
        ToolAccess,
        ToolCategory,
        ToolCostClass,
        ToolPaginationKind,
        ToolScopeKind,
    )

    definition = ForensicToolDefinition(
        tool_id="get_task_context",
        version="1",
        title="Get task and source context",
        description=(
            "Returns the forensic task digest: task identity, detected platform "
            "scenarios, available source scopes and their logical database "
            "kinds. Read-only."
        ),
        input_model=GetTaskContextInput,
        output_model=GetTaskContextOutput,
        category=ToolCategory.TASK_CONTEXT,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.TASK,
        evidence_behavior=EvidenceBehavior.NON_EVIDENCE,
        cost_class=ToolCostClass.CHEAP,
        pagination_kind=ToolPaginationKind.NONE,
    )
    return definition, adapter
