"""query_platform_artifacts tool (P3 §21).

Implemented only because a safe typed facade exists: the platform readers
(graphiti_integration.database_reader) expose fixed per-artifact methods with
bounded pagination and typed record construction. The model supplies an
artifact_family id (from the registered catalog), an optional source scope
and a server-side text filter — never a table name, SQL, column expression
or database path.

Rows returned are parser outputs, NOT canonical Evidence: they carry no
evidence_refs and never enter Evidence visibility.
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from ...agent_capabilities import (
    ArtifactFamilyRegistry,
    FamilyAvailability,
    list_sqlite_tables,
)
from ..errors import ToolErrorCode, ToolExecutionError
from ..registry import ToolExecutionOutcome
from .base import ToolCatalogConfig, bounded_page_size
from .services import ForensicToolServices

_READER_CLASSES = {}


def _reader_classes() -> dict:
    global _READER_CLASSES
    if not _READER_CLASSES:
        from ....graphiti_integration.database_reader.android_reader import (
            AndroidDatabase,
        )
        from ....graphiti_integration.database_reader.linux_reader import (
            LinuxDatabase,
        )
        from ....graphiti_integration.database_reader.windows_reader import (
            WindowsDatabase,
        )

        _READER_CLASSES = {
            "windows": WindowsDatabase,
            "linux": LinuxDatabase,
            "android": AndroidDatabase,
        }
    return _READER_CLASSES


def _row_to_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        return row.model_dump()
    if hasattr(row, "_asdict"):
        return dict(row._asdict())
    import dataclasses

    if dataclasses.is_dataclass(row):
        return dataclasses.asdict(row)
    return dict(row)


class QueryPlatformArtifactsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_family: str
    # validated against the run's source scope grant by the registry
    source_scope_id: Optional[str] = None
    text_contains: Optional[str] = None
    page_size: Optional[int] = None
    page_token: Optional[int] = None  # row offset


class PlatformArtifactPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_family: str
    source_scope_id: str
    items: tuple[dict[str, Any], ...] = ()
    result_count: int = 0
    truncated: bool = False
    continuation: str | None = None
    limitations: tuple[str, ...] = ()


def build_query_platform_artifacts_tool(
    services: ForensicToolServices,
    config: ToolCatalogConfig,
    *,
    family_registry: ArtifactFamilyRegistry | None = None,
):
    registry = family_registry or ArtifactFamilyRegistry.with_defaults()

    async def adapter(invocation) -> ToolExecutionOutcome:
        import asyncio

        args: QueryPlatformArtifactsInput = invocation.args
        context = invocation.context
        family = registry.resolve(args.artifact_family)
        if family is None:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_INPUT_INVALID,
                "unknown artifact family (see get_task_context capabilities)",
            )
        source_scope = args.source_scope_id or family.platform
        if source_scope != family.platform:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_INPUT_INVALID,
                "source scope does not match the artifact family platform",
            )

        task = await services.cpp_backend.get_task(context.task_id)
        if task is None:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_NOT_FOUND,
                "task context unavailable for this run",
            )
        scenarios = {str(s) for s in (task.get("scenarios") or ())}
        if family.platform not in scenarios:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_SCOPE_DENIED,
                "artifact family platform is not part of this task",
            )
        db_path = (task.get("scenario_databases") or {}).get(family.platform)
        if not db_path:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_SCOPE_DENIED,
                "platform database is not attached to this task",
            )
        tables = await asyncio.to_thread(list_sqlite_tables, db_path)
        present = [t for t in family.required_tables if t in tables]
        if not present:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_INPUT_INVALID,
                "artifact family has no parsed rows for this source",
                details={"availability": FamilyAvailability.UNAVAILABLE.value},
            )

        reader_cls = _reader_classes().get(family.platform)
        if reader_cls is None or not family.reader_method:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_ADAPTER_FAILED,
                "no typed reader facade bound to this artifact family",
            )

        def _read_page() -> list[dict[str, Any]]:
            reader = reader_cls(db_path)
            method = getattr(reader, family.reader_method)
            rows = method(
                limit=bounded_page_size(args.page_size, config),
                offset=int(args.page_token or 0),
                **family.reader_kwargs,
            )
            return [_row_to_dict(row) for row in rows]

        items = await asyncio.to_thread(_read_page)
        if args.text_contains:
            needle = args.text_contains.casefold()
            items = [
                item
                for item in items
                if needle in str(item).casefold()
            ]
        page_size = bounded_page_size(args.page_size, config)
        offset = int(args.page_token or 0)
        continuation = str(offset + page_size) if len(items) >= page_size else None
        return ToolExecutionOutcome(
            summary=(
                f"{len(items)} {family.title} rows (page at offset {offset})"
            ),
            result=PlatformArtifactPage(
                artifact_family=family.family_id,
                source_scope_id=source_scope,
                items=tuple(items),
                result_count=len(items),
                truncated=continuation is not None,
                continuation=continuation,
                limitations=(
                    "parser output rows are not canonical Evidence",
                    *family.limitations,
                ),
            ),
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
        tool_id="query_platform_artifacts",
        version="1",
        title="Query platform artifact families",
        description=(
            "Reads a registered platform artifact family (typed, bounded "
            "pages) for one source scope. Accepts only a family id from the "
            "capability catalog, an optional source scope and a server-side "
            "text filter. Never accepts table names, SQL or database paths."
        ),
        input_model=QueryPlatformArtifactsInput,
        output_model=PlatformArtifactPage,
        category=ToolCategory.PLATFORM_ARTIFACTS,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.PLATFORM_ARTIFACT,
        evidence_behavior=EvidenceBehavior.NON_EVIDENCE,
        cost_class=ToolCostClass.STANDARD,
        pagination_kind=ToolPaginationKind.PAGE_TOKEN,
    )
    return definition, adapter
