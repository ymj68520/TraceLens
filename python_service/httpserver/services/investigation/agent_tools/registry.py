"""ForensicToolRegistry — permission/scope authority for Agent tools (P3).

Execution pipeline (frozen P3 contract order):

    resolve -> permission -> agent type -> allowed ids -> input validation
    -> budget check -> duplicate guard -> domain adapter
    -> output normalization -> Evidence-ref validation
    -> observation persistence -> compact result

The registry is the only execution path for model-visible tools. Even though
the PydanticAI bridge hides non-allowed tools from the model, the registry
re-checks everything on every call — tool visibility is never the security
boundary.

P3 registration rule: only ``access=read`` tools may be registered. The full
read/propose/mutate contract exists, but propose/mutate executors belong to
their real phases and cannot enter an Agent-visible registry early.
"""

import inspect
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from ..agent_runtime import canonical_state_json
from .context import ForensicToolContext
from .definitions import (
    ForensicToolDefinition,
    ToolAccess,
    tool_definition_to_payload,
    validate_model_visible_schema,
)
from .errors import ToolErrorCode, ToolExecutionError
from .observations import (
    NoopObservationSink,
    build_observation_record,
    fingerprint_input,
)

REGISTRY_VERSION = "forensic-tool-registry:v1"

# Compact result cap: observations keep the full normalized payload, the
# model-facing result trims oversized data payloads to keep context bounded.
_COMPACT_DATA_CHARS = 4000

AdapterFunc = Callable[
    ["ToolInvocation"], Awaitable["ToolExecutionOutcome"]
]
EvidenceRefValidator = Callable[[str, ForensicToolContext], None]


class ToolInvocation(BaseModel):
    """Everything one adapter call receives (validated, trusted context)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    context: ForensicToolContext
    definition: ForensicToolDefinition
    args: BaseModel


class ToolExecutionOutcome(BaseModel):
    """Adapter result envelope (normalized before persistence)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    summary: str
    result: BaseModel

    evidence_refs: tuple[str, ...] = ()
    entity_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    truncated: bool = False
    continuation: Optional[str] = None
    pagination: Optional[Mapping[str, Any]] = None

    def result_payload(self) -> dict[str, Any]:
        return self.result.model_dump()

    @property
    def result_count(self) -> int:
        data = self.result_payload()
        for key in ("result_count", "total_count"):
            value = data.get(key)
            if isinstance(value, int):
                return value
        for key in ("items", "results", "files", "events", "evidence", "claims", "analyses"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
        return 0


class ForensicToolRegistry:
    """Single authority for registering and executing forensic tools."""

    def __init__(
        self,
        *,
        observation_sink=None,
        evidence_ref_validator: Optional[EvidenceRefValidator] = None,
        duplicate_call_policy: Optional[Callable[[ForensicToolContext], int]] = None,
    ):
        self._tools: dict[str, ForensicToolDefinition] = {}
        self._adapters: dict[str, AdapterFunc] = {}
        self._sink = observation_sink or NoopObservationSink()
        self._evidence_ref_validator = evidence_ref_validator
        self._duplicate_call_policy = duplicate_call_policy
        # per-run bookkeeping (budget + duplicate guards); keyed by run
        self._run_observation_counts: dict[tuple[str, str, str], int] = {}
        self._run_fingerprints: dict[tuple[str, str, str], dict[str, int]] = {}

    # -- registration ---------------------------------------------------

    def register(self, definition: ForensicToolDefinition, adapter: AdapterFunc) -> None:
        if definition.tool_id in self._tools:
            raise ValueError(f"tool already registered: {definition.tool_id!r}")
        if definition.access != ToolAccess.READ:
            # P3 frozen boundary: propose/mutate never enters the registry.
            raise ValueError(
                "P3 registry accepts read-only tools only; "
                f"{definition.tool_id!r} declares access={definition.access.value!r}"
            )
        validate_model_visible_schema(definition)
        if not inspect.iscoroutinefunction(adapter):
            raise TypeError(f"adapter for {definition.tool_id!r} must be async")
        self._tools[definition.tool_id] = definition
        self._adapters[definition.tool_id] = adapter

    def iter_definitions(self) -> Iterable[ForensicToolDefinition]:
        return [self._tools[tool_id] for tool_id in sorted(self._tools)]

    def resolve_definition(self, tool_id: str) -> ForensicToolDefinition:
        definition = self._tools.get(tool_id)
        if definition is None:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_NOT_FOUND,
                f"tool {tool_id!r} is not registered",
            )
        return definition

    def definition_payloads(self) -> list[dict[str, Any]]:
        return [tool_definition_to_payload(d) for d in self.iter_definitions()]

    @property
    def registry_version(self) -> str:
        return REGISTRY_VERSION

    def schema_hash(self) -> str:
        """Deterministic hash over the whole registered catalog."""
        payload = {
            "registry_version": REGISTRY_VERSION,
            "tools": sorted(
                (
                    {
                        "tool_id": d.tool_id,
                        "version": d.version,
                        "schema_hash": d.schema_hash(),
                    }
                    for d in self._tools.values()
                ),
                key=lambda entry: entry["tool_id"],
            ),
        }
        import hashlib

        return hashlib.sha256(canonical_state_json(payload).encode("utf-8")).hexdigest()

    def __len__(self) -> int:
        return len(self._tools)

    # -- execution ------------------------------------------------------

    async def execute(
        self,
        context: ForensicToolContext,
        tool_id: str,
        args: Mapping[str, Any],
    ) -> dict[str, Any]:
        definition = self._tools.get(tool_id)
        if definition is None:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_NOT_FOUND,
                f"tool {tool_id!r} is not registered",
            )

        # permission (registry re-check even if the bridge hid the tool)
        if definition.access != ToolAccess.READ:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_NOT_ALLOWED,
                f"tool {tool_id!r} is not read-access",
            )
        if tool_id not in context.allowed_tool_ids:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_NOT_ALLOWED,
                f"tool {tool_id!r} is not allowed for this run",
            )

        # agent type restriction
        if definition.allowed_agent_types:
            if context.agent_type not in definition.allowed_agent_types:
                raise ToolExecutionError(
                    ToolErrorCode.TOOL_AGENT_NOT_ALLOWED,
                    f"tool {tool_id!r} is not available to agent type "
                    f"{context.agent_type!r}",
                )

        # budget: observation cap per run
        run_key = (context.task_id, context.investigation_id, context.run_id)
        budget_cap = context.budget.max_observations_per_run
        if self._run_observation_counts.get(run_key, 0) >= budget_cap:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_BUDGET_EXCEEDED,
                "run reached its tool observation budget",
            )

        # input validation (before any adapter work)
        try:
            validated = definition.input_model.model_validate(dict(args))
        except ValidationError as exc:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_INPUT_INVALID,
                "tool arguments failed validation",
                details={"errors": exc.errors(include_url=False)[:5]},
            ) from None

        # scope enforcement: tools that accept a source_scope_id may only
        # target source scopes granted to this run (checked before the adapter)
        requested_scope = getattr(validated, "source_scope_id", None)
        if (
            requested_scope is not None
            and context.source_scope_ids
            and requested_scope not in context.source_scope_ids
        ):
            raise ToolExecutionError(
                ToolErrorCode.TOOL_SCOPE_DENIED,
                "requested source scope is outside this run's grant",
            )

        # duplicate guard (deterministic fingerprint, policy-controlled)
        fingerprint = fingerprint_input(definition, dict(validated.model_dump()), context=context)
        fingerprints = self._run_fingerprints.setdefault(run_key, {})
        duplicate_limit = (
            self._duplicate_call_policy(context)
            if self._duplicate_call_policy is not None
            else context.budget.max_duplicate_calls
        )
        if fingerprints.get(fingerprint, 0) >= duplicate_limit:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_DUPLICATE_CALL,
                f"tool {tool_id!r} was already called with identical arguments",
            )
        fingerprints[fingerprint] = fingerprints.get(fingerprint, 0) + 1

        # domain adapter
        invocation = ToolInvocation(
            context=context, definition=definition, args=validated
        )
        try:
            outcome = await self._adapters[tool_id](invocation)
        except ToolExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalized for the model
            raise ToolExecutionError(
                ToolErrorCode.TOOL_ADAPTER_FAILED,
                f"tool {tool_id!r} failed inside its domain adapter",
                details={"exception_type": type(exc).__name__},
            ) from None

        # output normalization
        if not isinstance(outcome, ToolExecutionOutcome):
            raise ToolExecutionError(
                ToolErrorCode.TOOL_RESULT_INVALID,
                f"tool {tool_id!r} returned a non-normalized result",
            )
        if not isinstance(outcome.result, definition.output_model):
            raise ToolExecutionError(
                ToolErrorCode.TOOL_RESULT_INVALID,
                f"tool {tool_id!r} result does not match its output contract",
            )

        # Evidence-ref validation (fail closed, nothing persisted on failure)
        evidence_refs = tuple(outcome.evidence_refs)
        for ref in evidence_refs:
            self._validate_evidence_ref(ref, context)

        # observation persistence (durable tool action-trace, P3 decision)
        record = build_observation_record(
            definition,
            outcome,
            input_fingerprint=fingerprint,
            context=context,
        )
        self._sink.record(definition, record, evidence_refs, context=context)
        self._run_observation_counts[run_key] = (
            self._run_observation_counts.get(run_key, 0) + 1
        )

        return self._compact_result(definition, outcome, record)

    # -- helpers --------------------------------------------------------

    def _validate_evidence_ref(self, ref: str, context: ForensicToolContext) -> None:
        from ...evidence.keys import InvalidEvidenceKeyError, parse_evidence_key

        if not isinstance(ref, str) or not ref.strip():
            raise ToolExecutionError(
                ToolErrorCode.EVIDENCE_REF_INVALID,
                "tool result contained an empty evidence reference",
            )
        try:
            parse_evidence_key(ref)
        except InvalidEvidenceKeyError:
            raise ToolExecutionError(
                ToolErrorCode.EVIDENCE_REF_INVALID,
                "tool result contained a malformed evidence reference",
            ) from None
        if self._evidence_ref_validator is not None:
            try:
                self._evidence_ref_validator(ref, context)
            except ToolExecutionError:
                raise
            except Exception:
                raise ToolExecutionError(
                    ToolErrorCode.EVIDENCE_REF_CROSS_TASK,
                    "tool result referenced evidence outside this task scope",
                ) from None

    def _compact_result(
        self,
        definition: ForensicToolDefinition,
        outcome: ToolExecutionOutcome,
        record,
    ) -> dict[str, Any]:
        data = outcome.result_payload()
        serialized = canonical_state_json(data)
        truncated_data = False
        if len(serialized) > _COMPACT_DATA_CHARS:
            data = {"omitted": True, "reason": "result too large for compact view"}
            truncated_data = True
        return {
            "tool_id": definition.tool_id,
            "tool_version": definition.version,
            "observation": "recorded",
            "summary": outcome.summary,
            "data": data,
            "data_truncated_for_context": truncated_data,
            "evidence_refs": list(outcome.evidence_refs),
            "result_count": record.result_count,
            "truncated": outcome.truncated,
            "continuation": outcome.continuation,
            "warnings": list(outcome.warnings),
            "limitations": list(outcome.limitations),
        }

    def reset_run_bookkeeping(
        self, task_id: str, investigation_id: str, run_id: str
    ) -> None:
        """Drop in-memory guards for one run (restart recovery helper)."""
        self._run_observation_counts.pop((task_id, investigation_id, run_id), None)
        self._run_fingerprints.pop((task_id, investigation_id, run_id), None)


__all__ = [
    "AdapterFunc",
    "ForensicToolRegistry",
    "REGISTRY_VERSION",
    "ToolExecutionOutcome",
    "ToolInvocation",
]
