"""Normalized Tool Observations and the persistence sink (P3).

A ToolObservation is a normalized, immutable record of one successful tool
execution. It is NOT Evidence: `summary`/`data` are model-facing projections,
only `evidence_refs` carry canonical Evidence identity.

P3 storage decision: the P1 `agent_tool_observations` table (INSERT-only,
canonical JSON payload) is sufficient and is the durable tool action-trace.
The frozen trajectory CHECK enum has no tool event type, and P3 does not bump
the investigation.db schema — so no trajectory row is emitted for tool calls.
"""

from typing import Any, Mapping, Optional, Protocol

from pydantic import BaseModel, ConfigDict

from ..agent_runtime import (
    AgentRuntimeRepository,
    ToolObservation,
    canonical_state_json,
    state_hash_of,
)
from .definitions import ForensicToolDefinition


class ToolObservationRecord(BaseModel):
    """Normalized observation payload persisted verbatim (canonical JSON)."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "tool-observation:v1"

    tool_id: str
    tool_version: str
    schema_hash: str

    summary: str
    data: Mapping[str, Any]

    # canonical P3: entity pipeline arrives in P5, so observations keep [] here
    entity_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    result_count: int = 0
    truncated: bool = False
    continuation: Optional[str] = None
    pagination: Optional[Mapping[str, Any]] = None

    input_fingerprint: str
    context_hash: Optional[str] = None


class ObservationSink(Protocol):
    """Persistence boundary for observations (implemented over the P1 repo)."""

    def record(
        self,
        definition: ForensicToolDefinition,
        record: ToolObservationRecord,
        evidence_refs: tuple[str, ...],
        *,
        context,
    ) -> ToolObservation: ...


class AgentObservationSink:
    """Persists observations through P1 ``append_tool_observation``.

    Both the observation row and the run/delegation linkage live in the same
    INSERT — a failed append leaves no partial record (single statement).
    """

    def __init__(self, repository: AgentRuntimeRepository):
        self._repository = repository

    def record(
        self,
        definition: ForensicToolDefinition,
        record: ToolObservationRecord,
        evidence_refs: tuple[str, ...],
        *,
        context,
    ) -> ToolObservation:
        return self._repository.append_tool_observation(
            context.investigation_id,
            tool_id=record.tool_id,
            summary=record.summary,
            result=record.model_dump(),
            evidence_refs=evidence_refs,
            run_id=context.run_id,
            delegation_id=context.delegation_id,
            truncated=record.truncated,
        )


def build_observation_record(
    definition: ForensicToolDefinition,
    outcome,
    *,
    input_fingerprint: str,
    context,
) -> ToolObservationRecord:
    """Normalize an adapter outcome into the immutable observation payload."""
    return ToolObservationRecord(
        tool_id=definition.tool_id,
        tool_version=definition.version,
        schema_hash=definition.schema_hash(),
        summary=outcome.summary,
        data=outcome.result_payload(),
        entity_refs=tuple(outcome.entity_refs),
        warnings=tuple(outcome.warnings),
        limitations=tuple(outcome.limitations),
        result_count=outcome.result_count,
        truncated=outcome.truncated,
        continuation=outcome.continuation,
        pagination=dict(outcome.pagination) if outcome.pagination else None,
        input_fingerprint=input_fingerprint,
        context_hash=context.context_hash,
    )


def fingerprint_input(
    definition: ForensicToolDefinition,
    args: Mapping[str, Any],
    *,
    context,
) -> str:
    """Deterministic duplicate-detection fingerprint (P3 §43).

    Covers tool identity, canonical arguments, source scope and the context
    hash; run ownership comes from the sink linkage, not the fingerprint.
    """
    payload = {
        "tool_id": definition.tool_id,
        "tool_version": definition.version,
        "args": dict(args),
        "source_scope_ids": list(context.source_scope_ids),
        "context_hash": context.context_hash,
    }
    return state_hash_of(canonical_state_json(payload))


class NoopObservationSink:
    """Sink for pure-read contexts with no investigation runtime attached.

    Still records nothing: P3 never lets tool executions bypass durability
    silently in production — this sink is for offline registry tests and
    adapter unit tests only.
    """

    def __init__(self) -> None:
        self.records: list[tuple[ForensicToolDefinition, ToolObservationRecord, tuple[str, ...]]] = []

    def record(
        self,
        definition: ForensicToolDefinition,
        record: ToolObservationRecord,
        evidence_refs: tuple[str, ...],
        *,
        context,
    ) -> None:
        self.records.append((definition, record, evidence_refs))
        return None


__all__ = [
    "AgentObservationSink",
    "NoopObservationSink",
    "ObservationSink",
    "ToolObservationRecord",
    "build_observation_record",
    "fingerprint_input",
]
