"""ForensicAgentDeps — PydanticAI run dependencies injected by TraceLens (P3).

The deps object is what PydanticAI tools see via ``RunContext.deps``. It
carries trusted identity (task/investigation/run), the allowed tool surface
and the trusted execution context for the tool registry. It must never carry
provider secrets, raw DB paths, sqlite connections, the ServiceManager or a
Graphiti client.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator

from .agent_tools.context import AgentTimeScope, ForensicToolContext
from .agent_tools.pydantic_bridge import ForensicToolRegistryProtocol

AGENT_DEPS_VERSION = "forensic-agent-deps:v1"


class ForensicAgentDeps(BaseModel):
    """Run dependencies for every TraceLens forensic agent run (P3)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    deps_version: str = AGENT_DEPS_VERSION

    task_id: str
    investigation_id: str
    run_id: str

    delegation_id: Optional[str] = None
    question_id: Optional[str] = None

    source_scope_ids: tuple[str, ...] = ()
    time_scope: Optional[AgentTimeScope] = None

    allowed_tool_ids: frozenset[str]

    tool_registry: "ForensicToolRegistryProtocol"
    tool_context: ForensicToolContext

    @model_validator(mode="after")
    def _check_context_consistency(self):
        ctx = self.tool_context
        for field in ("task_id", "investigation_id", "run_id"):
            if getattr(self, field) != getattr(ctx, field):
                raise ValueError(
                    f"deps {field} must match tool_context {field}"
                )
        if self.delegation_id != ctx.delegation_id:
            raise ValueError("deps delegation_id must match tool_context")
        if self.question_id != ctx.question_id:
            raise ValueError("deps question_id must match tool_context")
        if not self.allowed_tool_ids.issubset(ctx.allowed_tool_ids):
            raise ValueError(
                "deps allowed_tool_ids must be a subset of tool_context allowed_tool_ids"
            )
        return self


__all__ = ["ForensicAgentDeps"]
