"""Trusted per-run tool execution context (P3).

The context is created by TraceLens runtime code only. Its identity fields
(task/investigation/run/source scope) must never appear in any model-visible
tool input schema; the model fills real query parameters, the context carries
everything the registry needs to authorize and scope an execution.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

TOOL_CONTEXT_VERSION = "forensic-tool-context:v1"


class AgentTimeScope(BaseModel):
    """Optional investigation time window (unix seconds)."""

    model_config = ConfigDict(frozen=True)

    start_unix: Optional[int] = None
    end_unix: Optional[int] = None

    @model_validator(mode="after")
    def _check_order(self):
        if (
            self.start_unix is not None
            and self.end_unix is not None
            and self.start_unix > self.end_unix
        ):
            raise ValueError("time scope start must not be after end")
        return self


class ToolBudgetPolicy(BaseModel):
    """Configurable tool-budget knobs.

    Provisional defaults; the numbers are calibration inputs for the P8
    benchmark, not architecture constants — inject an explicit policy where a
    deployment needs different limits.
    """

    model_config = ConfigDict(frozen=True)

    max_duplicate_calls: int = Field(default=2, ge=1)
    max_observations_per_run: int = Field(default=200, ge=1)


class ForensicToolContext(BaseModel):
    """Trusted execution context handed to ForensicToolRegistry.execute."""

    model_config = ConfigDict(frozen=True)

    context_version: str = TOOL_CONTEXT_VERSION
    task_id: str
    investigation_id: str
    run_id: str
    delegation_id: Optional[str] = None
    question_id: Optional[str] = None

    source_scope_ids: tuple[str, ...] = ()
    time_scope: Optional[AgentTimeScope] = None

    allowed_tool_ids: frozenset[str]

    budget: ToolBudgetPolicy = ToolBudgetPolicy()

    # Filled by P3-4 ContextAssembler with the ContextPack input_hash; None
    # until a context pack exists. Participates in duplicate-call fingerprints.
    context_hash: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _check_ids(cls, data):
        if isinstance(data, dict):
            for field in ("task_id", "investigation_id", "run_id"):
                if not (data.get(field) or "").strip():
                    raise ValueError(f"tool context requires {field}")
        return data
