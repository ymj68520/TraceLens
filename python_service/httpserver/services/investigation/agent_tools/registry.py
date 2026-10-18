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
        """Frozen execution pipeline (P3 freeze follow-up F1 order):

            1 resolve -> 2 permission (read/allowed/agent-types)
            -> 3 scope validation -> 4 input schema validation
            -> 5 budget/duplicate policy -> 6 domain adapter
            -> 7 output normalization -> 8 Evidence-ref validation
            -> 9+10 ToolObservation persistence + Trajectory append
               (one atomic repository transaction)
            -> 11 compact model-facing result

        Each step is a private method so the order is directly testable;
        a rejected step consumes no downstream state (no budget, no
        duplicate fingerprint, no adapter call, no persistence).
        """
        definition = self._step_resolve(tool_id)                      # 1
        self._step_check_permission(definition, context, tool_id)     # 2
        self._step_check_scope(args, context)                         # 3
        validated = self._step_validate_input(definition, args)       # 4
        run_key = self._run_key(context)
        self._step_check_budget(run_key, context)                     # 5a
        fingerprint = self._step_check_duplicate(                     # 5b
            definition, validated, run_key, context
        )
        outcome = await self._step_run_adapter(definition, context, validated)  # 6
        outcome = self._step_normalize_output(definition, outcome)    # 7
        evidence_refs = self._step_validate_evidence_refs(outcome, context)     # 8
        record = build_observation_record(                            # 9+10
            definition, outcome, input_fingerprint=fingerprint, context=context,
        )
        self._step_persist(definition, record, evidence_refs, context, run_key)
        return self._step_compact_result(definition, outcome, record)  # 11

    # -- pipeline steps (order = frozen contract) -----------------------

    def _run_key(self, context: ForensicToolContext) -> tuple[str, str, str]:
        return (context.task_id, context.investigation_id, context.run_id)

    def _step_resolve(self, tool_id: str) -> ForensicToolDefinition:  # 1
        return self.resolve_definition(tool_id)

    def _step_check_permission(                                      # 2
        self, definition: ForensicToolDefinition, context, tool_id: str
    ) -> None:
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
        if definition.allowed_agent_types:
            if context.agent_type not in definition.allowed_agent_types:
                raise ToolExecutionError(
                    ToolErrorCode.TOOL_AGENT_NOT_ALLOWED,
                    f"tool {tool_id!r} is not available to agent type "
                    f"{context.agent_type!r}",
                )

    def _step_check_scope(self, args: Mapping[str, Any], context) -> None:  # 3
        """Scope authorization BEFORE full domain input acceptance.

        Minimal deterministic pre-check on the raw mapping: extract only the
        declared scope discriminator field and validate it against the run's
        source-scope grant. Type/format errors are left to schema validation.
        """
        if not isinstance(args, Mapping):
            return
        raw_scope = args.get("source_scope_id")
        if not isinstance(raw_scope, str):
            return
        if context.source_scope_ids and raw_scope not in context.source_scope_ids:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_SCOPE_DENIED,
                "requested source scope is outside this run's grant",
            )

    def _step_validate_input(                                        # 4
        self, definition: ForensicToolDefinition, args: Mapping[str, Any]
    ):
        try:
            return definition.input_model.model_validate(dict(args))
        except ValidationError as exc:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_INPUT_INVALID,
                "tool arguments failed validation",
                details={"errors": exc.errors(include_url=False)[:5]},
            ) from None

    def _step_check_budget(self, run_key, context) -> None:          # 5a
        if (
            self._run_observation_counts.get(run_key, 0)
            >= context.budget.max_observations_per_run
        ):
            raise ToolExecutionError(
                ToolErrorCode.TOOL_BUDGET_EXCEEDED,
                "run reached its tool observation budget",
            )

    def _step_check_duplicate(                                       # 5b
        self, definition, validated, run_key, context
    ) -> str:
        fingerprint = fingerprint_input(
            definition, dict(validated.model_dump()), context=context
        )
        fingerprints = self._run_fingerprints.setdefault(run_key, {})
        duplicate_limit = (
            self._duplicate_call_policy(context)
            if self._duplicate_call_policy is not None
            else context.budget.max_duplicate_calls
        )
        if fingerprints.get(fingerprint, 0) >= duplicate_limit:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_DUPLICATE_CALL,
                f"tool {definition.tool_id!r} was already called with "
                "identical arguments",
            )
        fingerprints[fingerprint] = fingerprints.get(fingerprint, 0) + 1
        return fingerprint

    async def _step_run_adapter(self, definition, context, validated):   # 6
        invocation = ToolInvocation(
            context=context, definition=definition, args=validated
        )
        try:
            return await self._adapters[definition.tool_id](invocation)
        except ToolExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalized for the model
            raise ToolExecutionError(
                ToolErrorCode.TOOL_ADAPTER_FAILED,
                f"tool {definition.tool_id!r} failed inside its domain adapter",
                details={"exception_type": type(exc).__name__},
            ) from None

    def _step_normalize_output(self, definition, outcome):           # 7
        if not isinstance(outcome, ToolExecutionOutcome):
            raise ToolExecutionError(
                ToolErrorCode.TOOL_RESULT_INVALID,
                f"tool {definition.tool_id!r} returned a non-normalized result",
            )
        if not isinstance(outcome.result, definition.output_model):
            raise ToolExecutionError(
                ToolErrorCode.TOOL_RESULT_INVALID,
                f"tool {definition.tool_id!r} result does not match its "
                "output contract",
            )
        return outcome

    def _step_validate_evidence_refs(self, outcome, context):        # 8
        """Fail closed: nothing is persisted when any ref is invalid."""
        evidence_refs = tuple(outcome.evidence_refs)
        for ref in evidence_refs:
            self._validate_evidence_ref(ref, context)
        return evidence_refs

    def _step_persist(                                               # 9+10
        self, definition, record, evidence_refs, context, run_key
    ) -> None:
        """ToolObservation + trajectory append (one atomic transaction)."""
        self._sink.record(definition, record, evidence_refs, context=context)
        self._run_observation_counts[run_key] = (
            self._run_observation_counts.get(run_key, 0) + 1
        )

    def _step_compact_result(self, definition, outcome, record):     # 11
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
