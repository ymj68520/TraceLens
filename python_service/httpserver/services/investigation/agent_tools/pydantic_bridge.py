"""PydanticAI bridge: ForensicToolRegistry -> PydanticAI toolset (P3).

The toolset is a thin wrapper: every model-visible tool executes through
``ForensicToolRegistry.execute(context, tool_id, args)``. Permission/scope
authority always stays with the TraceLens registry — "the model did not see
the tool" is never the only safety boundary, because the registry re-checks
permission, scope, budget and duplicate guards on every execution even if a
tool was somehow surfaced to the model.

The bridge is stateless: it owns no investigation state, no persistence and no
tool catalog of its own.
"""

from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from pydantic import TypeAdapter
from pydantic_core import SchemaValidator

from pydantic_ai import InlineDefsJsonSchemaTransformer
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.toolsets.abstract import AbstractToolset, ToolsetTool

from .context import ForensicToolContext
from .definitions import ForensicToolDefinition, ToolAccess


@runtime_checkable
class ForensicToolRegistryProtocol(Protocol):
    """Minimal registry surface the bridge relies on (implemented in P3-2)."""

    def iter_definitions(self) -> Iterable[ForensicToolDefinition]: ...

    def resolve_definition(self, tool_id: str) -> ForensicToolDefinition: ...

    async def execute(
        self,
        context: ForensicToolContext,
        tool_id: str,
        args: Mapping[str, Any],
    ) -> Any: ...


def _parameters_json_schema(definition: ForensicToolDefinition) -> dict[str, Any]:
    """Model-visible parameter schema with $defs inlined."""
    schema = definition.input_json_schema()
    transformed = InlineDefsJsonSchemaTransformer(schema).walk()
    return dict(transformed)


class ForensicToolset(AbstractToolset):
    """One run's model-visible toolset, projected from the trusted registry."""

    def __init__(
        self,
        registry: ForensicToolRegistryProtocol,
        context: ForensicToolContext,
    ) -> None:
        self._registry = registry
        self._context = context

    @property
    def id(self) -> str | None:
        return "forensic-toolset"

    @property
    def context(self) -> ForensicToolContext:
        return self._context

    @property
    def registry(self) -> ForensicToolRegistryProtocol:
        return self._registry

    def visible_definitions(self) -> list[ForensicToolDefinition]:
        """Deterministic projection applied before any model interaction.

        A tool is visible when it is registered with read access AND its
        tool_id is in the run's allowed_tool_ids. Sort by tool_id so the
        model-facing order is stable.
        """
        visible = [
            definition
            for definition in self._registry.iter_definitions()
            if definition.access == ToolAccess.READ
            and definition.tool_id in self._context.allowed_tool_ids
        ]
        visible.sort(key=lambda definition: definition.tool_id)
        return visible

    async def get_tools(self, ctx: RunContext) -> dict[str, ToolsetTool]:
        tools: dict[str, ToolsetTool] = {}
        for definition in self.visible_definitions():
            tool_def = ToolDefinition(
                name=definition.tool_id,
                description=definition.description,
                parameters_json_schema=_parameters_json_schema(definition),
            )
            tools[definition.tool_id] = ToolsetTool(
                toolset=self,
                tool_def=tool_def,
                max_retries=ctx.max_retries,
                args_validator=SchemaValidator(
                    TypeAdapter(definition.input_model).core_schema
                ),
                args_validator_func=None,
            )
        return tools

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext,
        tool: ToolsetTool,
    ) -> Any:
        # pydantic-ai hands over already-schema-validated args (an instance of
        # the tool's input model); normalize back to a plain mapping. The
        # registry remains the authority: it re-validates input, permission,
        # scope, budget and duplicate guards before the domain adapter runs.
        if hasattr(tool_args, "model_dump"):
            tool_args = tool_args.model_dump()
        return await self._registry.execute(self._context, name, tool_args)


def build_pydantic_toolset(
    registry: ForensicToolRegistryProtocol,
    context: ForensicToolContext,
) -> ForensicToolset:
    """Build the run-scoped PydanticAI toolset for one trusted context."""
    return ForensicToolset(registry, context)


__all__ = [
    "ForensicToolRegistryProtocol",
    "ForensicToolset",
    "build_pydantic_toolset",
]
