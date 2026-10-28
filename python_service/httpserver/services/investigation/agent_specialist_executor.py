"""Specialist delegation execution (P4A).

Real PydanticAI SourceSpecialist execution over the P3 substrate:

    DelegationExecutionEnvelope (frozen at dispatch)
        -> SourceSpecialistAgentFactory (ContextPack -> Agent[deps, SpecialistResultProposalV1])
        -> offline-tested real run
        -> SpecialistResultValidator (visible-evidence + contract checks)
        -> finalize_specialist_result (deterministic trusted-field enrichment, A1-T)
        -> atomic result row + delegation ``completed`` transition

Hard P4A boundary: the Specialist investigates and returns proposals; it
never mutates Working State, never creates canonical Claims/Events, never
integrates. Supervisor / Integration mode stay in P4B.
"""

import asyncio
import time
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .agent_context import SpecialistContextPack
from .agent_failure_taxonomy import classify_failure
from .agent_failure_taxonomy import (
    PROVIDER_CONNECTION_ERROR as _TAX_CONNECTION_ERROR,
)
from .agent_failure_taxonomy import (
    PROVIDER_REQUEST_TIMEOUT as _TAX_REQUEST_TIMEOUT,
)
from . import agent_failure_taxonomy as taxonomy
from .agent_runtime import AgentRuntimeRepository, canonical_state_json, state_hash_of
from .agent_skills import FrozenSkillBinding
from .agent_specialist_result import (
    SPECIALIST_RESULT_VERSION,
    SpecialistResultProposalV1,
    SpecialistResultValidator,
    execution_digest_hash,
    finalize_specialist_result,
)
from .agent_tools.context import ForensicToolContext, ToolBudgetPolicy

if True:  # typing-only import; keeps pydantic_ai off the module import path
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:  # pragma: no cover
        from .agent_tools.pydantic_bridge import ForensicToolRegistryProtocol

ENVELOPE_VERSION = "delegation-execution-envelope:v1"


# ---------------------------------------------------------------------------
# failure mapping (P4A §13)
# ---------------------------------------------------------------------------


class DelegationFailureCode(str, Enum):
    AGENT_PROVIDER_UNAVAILABLE = "agent_provider_unavailable"
    AGENT_AUTH_FAILED = "agent_auth_failed"
    AGENT_RATE_LIMITED = "agent_rate_limited"
    AGENT_BILLING_UNAVAILABLE = "agent_billing_unavailable"
    AGENT_TIMEOUT = "agent_timeout"
    AGENT_OUTPUT_INVALID = "agent_output_invalid"
    AGENT_TOOL_FAILURE = "agent_tool_failure"
    AGENT_INTERNAL_FAILURE = "agent_internal_failure"
    # RCA-1.1: the supervisor INTEGRATE stage failed and was contained as a
    # first-class cycle outcome; the underlying cause rides beside the code
    SUPERVISOR_INTEGRATION_FAILED = "supervisor_integration_failed"
    # binding mismatch before execution (P4A §36); precise stale
    # classification is P4B MergeGuard work
    INPUT_CONTRACT_CHANGED = "input_contract_changed"
    # A1-S §9/§12: a promoted evidence ref could not be canonically
    # resolved into an immutable snapshot candidate before completion —
    # the delegation fails closed, never completes partially
    EVIDENCE_RESOLUTION_FAILED = "evidence_resolution_failed"


_RETRYABLE_PROVIDER_CODES = frozenset(
    {
        DelegationFailureCode.AGENT_TIMEOUT,
        DelegationFailureCode.AGENT_RATE_LIMITED,
        DelegationFailureCode.AGENT_PROVIDER_UNAVAILABLE,
    }
)


def map_provider_exception(exc: Exception) -> DelegationFailureCode:
    """Map a PydanticAI/provider failure to its stable delegation code.

    RCA-1.2 (audit F-4): openai transport errors are recognized by TYPE
    first. ``openai.APITimeoutError`` subclasses neither the builtin
    ``TimeoutError`` nor carries a ``status_code``, so the pre-RCA-1 order
    classified every transport timeout as AGENT_INTERNAL_FAILURE
    (non-retryable); it is AGENT_TIMEOUT exactly like the builtin family.
    """
    classification = classify_failure(exc)
    if classification.code == taxonomy.PROVIDER_REQUEST_TIMEOUT:
        return DelegationFailureCode.AGENT_TIMEOUT
    if classification.code == taxonomy.PROVIDER_CONNECTION_ERROR:
        return DelegationFailureCode.AGENT_PROVIDER_UNAVAILABLE
    # pydantic-ai wraps provider HTTP errors in ModelHTTPError
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return _map_status_code(int(status_code))
    # raw OpenAI SDK errors (status lives on the response)
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is not None:
        return _map_status_code(int(status))
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return DelegationFailureCode.AGENT_TIMEOUT
    if exc.__class__.__name__ in (
        "UnexpectedModelBehavior",
        "ValidationError",
        "UserError",
    ):
        return DelegationFailureCode.AGENT_OUTPUT_INVALID
    if exc.__class__.__name__ == "ToolExecutionError":
        return DelegationFailureCode.AGENT_TOOL_FAILURE
    return DelegationFailureCode.AGENT_INTERNAL_FAILURE


def _map_status_code(status_code: int) -> DelegationFailureCode:
    if status_code == 402:
        # a billing failure is never an evidence conclusion
        return DelegationFailureCode.AGENT_BILLING_UNAVAILABLE
    if status_code in (401, 403):
        return DelegationFailureCode.AGENT_AUTH_FAILED
    if status_code == 429:
        return DelegationFailureCode.AGENT_RATE_LIMITED
    if status_code in (400, 404, 422):
        # invalid model / unsupported request shapes
        return DelegationFailureCode.AGENT_OUTPUT_INVALID
    if status_code >= 500:
        return DelegationFailureCode.AGENT_PROVIDER_UNAVAILABLE
    return DelegationFailureCode.AGENT_INTERNAL_FAILURE


def safe_failure_message(exc: Exception, code: DelegationFailureCode) -> str:
    """Auditable one-liner without provider payloads or internals."""
    detail = None
    if code is DelegationFailureCode.AGENT_BILLING_UNAVAILABLE:
        detail = "provider returned billing/402"
    elif code is DelegationFailureCode.AGENT_AUTH_FAILED:
        detail = "provider rejected credentials"
    elif code is DelegationFailureCode.AGENT_RATE_LIMITED:
        detail = "provider rate limited the request"
    elif code is DelegationFailureCode.AGENT_TIMEOUT:
        detail = "provider call timed out"
    elif code is DelegationFailureCode.AGENT_PROVIDER_UNAVAILABLE:
        detail = "provider unavailable"
    elif code is DelegationFailureCode.AGENT_OUTPUT_INVALID:
        detail = "agent output did not satisfy the specialist result contract"
    elif code is DelegationFailureCode.SUPERVISOR_INTEGRATION_FAILED:
        detail = "supervisor INTEGRATE stage failed (contained, fail-closed)"
    return f"{code.value}: {detail or type(exc).__name__}"


# ---------------------------------------------------------------------------
# execution envelope (P4A §14-15, §42)
# ---------------------------------------------------------------------------


# single versioned binding contract (P4A freeze follow-up F1); the executor
# never defines a second one
SkillBinding = FrozenSkillBinding


class DelegationExecutionEnvelope(BaseModel):
    """Everything one PydanticAI run may read, frozen before dispatch.

    The run reads ONLY this envelope: ContextPack, profile, skills, toolset,
    question snapshot and scopes never follow live Working State changes.
    Staleness of the frozen input is judged after completion by the P4B
    MergeGuard, not by hot-swapping context mid-run.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    envelope_version: str = ENVELOPE_VERSION

    task_id: str
    investigation_id: str
    run_id: str
    delegation_id: str

    question_id: Optional[str] = None
    question_text: str = ""

    based_on_state_revision: Optional[int] = None
    based_on_state_hash: Optional[str] = None

    source_scope_ids: tuple[str, ...] = ()
    time_scope: Optional[Any] = None

    profile_id: str
    profile_version: str

    skill_bindings: tuple[SkillBinding, ...] = ()

    tool_registry_hash: str

    context_pack: SpecialistContextPack
    context_hash: str

    allowed_tool_ids: frozenset[str]

    budget: ToolBudgetPolicy = ToolBudgetPolicy()

    model_config_digest: str

    output_contract_ref: str = SPECIALIST_RESULT_VERSION

    created_at: Optional[str] = None

    @field_validator("output_contract_ref")
    @classmethod
    def _check_contract(cls, value: str) -> str:
        if value != SPECIALIST_RESULT_VERSION:
            raise ValueError(
                "envelope must bind the frozen specialist result contract "
                f"{SPECIALIST_RESULT_VERSION!r}, got {value!r}"
            )
        return value

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_skill_bindings(cls, data):
        """Deterministic binding order (canonical sort by skill_id)."""
        if isinstance(data, dict) and data.get("skill_bindings"):
            def _sort_key(binding):
                if isinstance(binding, dict):
                    return binding.get("skill_id") or ""
                return getattr(binding, "skill_id", "") or ""

            data["skill_bindings"] = sorted(
                data["skill_bindings"], key=_sort_key
            )
        return data

    @model_validator(mode="after")
    def _check_skill_bindings(self):
        ids = [binding.skill_id for binding in self.skill_bindings]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate skill_id in frozen skill bindings")
        for binding in self.skill_bindings:
            if not binding.version.strip():
                raise ValueError(
                    "frozen skill bindings require a non-empty version"
                )
        return self

    def execution_input_hash(self) -> str:
        """Deterministic hash over the full frozen execution input (§42)."""
        payload = {
            "envelope_version": self.envelope_version,
            "task_id": self.task_id,
            "investigation_id": self.investigation_id,
            "run_id": self.run_id,
            "delegation_id": self.delegation_id,
            "question_id": self.question_id,
            "question_text": self.question_text,
            "based_on_state_revision": self.based_on_state_revision,
            "based_on_state_hash": self.based_on_state_hash,
            "source_scope_ids": sorted(self.source_scope_ids),
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "skill_bindings": sorted(
                (b.skill_id, b.version) for b in self.skill_bindings
            ),
            "tool_registry_hash": self.tool_registry_hash,
            "context_hash": self.context_hash,
            "allowed_tool_ids": sorted(self.allowed_tool_ids),
            "budget": self.budget.model_dump(),
            "model_config_digest": self.model_config_digest,
            "output_contract_ref": self.output_contract_ref,
        }
        return state_hash_of(canonical_state_json(payload))


def model_config_digest_from_adapter_config(config) -> str:
    """Hash the normalized adapter config (never the API key)."""
    return state_hash_of(canonical_state_json(config.model_dump()))


def build_execution_envelope(
    pack: SpecialistContextPack,
    registry,  # ForensicToolRegistryProtocol
    *,
    question_text: str = "",
    based_on_state_revision: Optional[int] = None,
    based_on_state_hash: Optional[str] = None,
    skill_bindings: Optional[Sequence[SkillBinding]] = None,
    model_config_digest: str,
    budget: Optional[ToolBudgetPolicy] = None,
    created_at: Optional[str] = None,
) -> DelegationExecutionEnvelope:
    """Freeze one delegation's execution input from a ContextPack.

    Skill bindings are derived from the pack's frozen bindings by default;
    an explicit list must match the pack exactly (fail closed at freeze
    time — never execute against a different skill surface than hashed).
    """
    frozen_bindings = tuple(
        sorted(pack.skill_bindings, key=lambda b: b.skill_id)
    )
    if skill_bindings is not None:
        explicit = tuple(
            sorted(
                (
                    FrozenSkillBinding(
                        skill_id=b.skill_id, version=b.version
                    )
                    for b in skill_bindings
                ),
                key=lambda b: b.skill_id,
            )
        )
        if explicit != frozen_bindings:
            raise ValueError(
                "explicit skill bindings do not match the ContextPack's "
                "frozen skill bindings"
            )
    else:
        explicit = frozen_bindings
    context = pack.tool_context()
    envelope = DelegationExecutionEnvelope(
        task_id=context.task_id,
        investigation_id=context.investigation_id,
        run_id=context.run_id,
        delegation_id=context.delegation_id or "",
        question_id=pack.question_id,
        question_text=question_text or pack.question,
        based_on_state_revision=based_on_state_revision,
        based_on_state_hash=based_on_state_hash,
        source_scope_ids=tuple(
            dict.fromkeys((context.source_scope_ids)),
        ),
        time_scope=context.time_scope,
        profile_id=pack.profile.profile_id,
        profile_version=pack.profile.version,
        skill_bindings=explicit,
        tool_registry_hash=registry.schema_hash(),
        context_pack=pack,
        context_hash=pack.input_hash(),
        allowed_tool_ids=context.allowed_tool_ids,
        budget=budget or context.budget,
        model_config_digest=model_config_digest,
        created_at=created_at,
    )
    return envelope


def verify_envelope_bindings(
    envelope: DelegationExecutionEnvelope,
    pack: SpecialistContextPack,
    registry,  # ForensicToolRegistryProtocol
) -> Optional[str]:
    """Pre-execution binding check (P4A §34-37).

    Returns None when every frozen binding matches the live objects, or a
    short reason string for ``failed(input_contract_changed)``.
    """
    if pack.input_hash() != envelope.context_hash:
        return "context pack hash changed"
    if (
        pack.profile.profile_id != envelope.profile_id
        or pack.profile.version != envelope.profile_version
    ):
        return "profile binding changed"
    # exact id + version binding match (P4A freeze follow-up F1): missing
    # skill, extra skill, and same-id-version-change all fail closed here —
    # BEFORE any agent call, never via a post-hoc stale verdict
    frozen_bindings = tuple(
        sorted(pack.skill_bindings, key=lambda b: b.skill_id)
    )
    envelope_binding_pairs = tuple(
        sorted(
            (binding.skill_id, binding.version)
            for binding in envelope.skill_bindings
        )
    )
    pack_binding_pairs = tuple(
        (binding.skill_id, binding.version) for binding in frozen_bindings
    )
    if pack_binding_pairs != envelope_binding_pairs:
        # covers missing skills, extra skills, version drift and
        # empty-vs-frozen disagreements alike
        return "skill version binding changed"
    if registry.schema_hash() != envelope.tool_registry_hash:
        return "tool registry hash changed"
    # §34 three-way source scope agreement
    context = pack.tool_context()
    if (
        envelope.source_scope_ids
        and context.source_scope_ids != envelope.source_scope_ids
    ):
        return "source scope disagreement between pack and envelope"
    return None


# ---------------------------------------------------------------------------
# agent run policy (configurable, P8-calibrated — nothing frozen here)
# ---------------------------------------------------------------------------


class AgentRunPolicy(BaseModel):
    """Provisional runtime defaults; every number is config, P8 calibrates."""

    model_config = ConfigDict(frozen=True)

    max_output_retries: int = Field(default=2, ge=0)
    max_provider_retries: int = Field(default=1, ge=0)
    max_parallel_delegations: int = Field(default=2, ge=1)
    max_model_requests: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None


# ---------------------------------------------------------------------------
# dispatch outcome
# ---------------------------------------------------------------------------


class DispatchStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class DispatchOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    delegation_id: str
    status: DispatchStatus
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    result_hash: Optional[str] = None
    validation_codes: tuple[str, ...] = ()
    skipped_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# executor
# ---------------------------------------------------------------------------


class SpecialistDelegationExecutor:
    """Executes admitted delegations as real PydanticAI specialist runs.

    Responsibilities end at a persisted terminal result: no Working State
    mutation, no integration, no question closure — those are P4B.
    """

    def __init__(
        self,
        *,
        cpp_backend: Any,
        settings: Any,
        tool_services: Any,
        registry_builder,
        policy: Optional[AgentRunPolicy] = None,
        investigation_db_path_for_task=None,
        observation_sink_factory=None,
        failure_diagnostics_sink=None,
    ):
        self._cpp_backend = cpp_backend
        self._settings = settings
        self._tool_services = tool_services
        self._registry_builder = registry_builder  # (repo) -> ForensicToolRegistry
        self._policy = policy or AgentRunPolicy()
        if investigation_db_path_for_task is None:
            from .paths import investigation_db_path_for_task as trusted_path

            investigation_db_path_for_task = trusted_path
        self._db_path_for = investigation_db_path_for_task
        self._observation_sink_factory = observation_sink_factory
        # RCA-1.3: optional structured failure diagnostics (default OFF)
        self._failure_diagnostics_sink = failure_diagnostics_sink
        self._model = None

    def _emit_failure_diagnostics(
        self, exc: Exception, *, attempt: int, latency_ms: float | None = None
    ) -> None:
        if self._failure_diagnostics_sink is None:
            return
        try:
            from .agent_failure_diagnostics import (
                build_failure_entry,
                schema_hash_of,
            )
            from .agent_failure_taxonomy import classify_failure

            self._failure_diagnostics_sink.record_failure(
                build_failure_entry(
                    stage="SPECIALIST",
                    exc=exc,
                    classification=classify_failure(exc),
                    output_schema_hash=schema_hash_of(
                        SpecialistResultProposalV1),
                    retry_attempts=attempt,
                    request_latency_ms=latency_ms,
                )
            )
        except Exception:  # noqa: BLE001 — diagnostics are never fatal
            pass

    # -- lifecycle ------------------------------------------------------

    async def initialize(self) -> None:
        """Lifecycle setup only — never auto-consumes queued delegations."""

    async def shutdown(self) -> None:
        self._model = None

    # -- model ----------------------------------------------------------

    def _get_model(self):
        if self._model is None:
            # deferred: pulls pydantic_ai at first dispatch, never during
            # service initialization
            from .agent_model_adapter import build_chat_model

            self._model = build_chat_model(self._settings)
        return self._model

    # -- dispatch -------------------------------------------------------

    async def dispatch_delegation(
        self, envelope: DelegationExecutionEnvelope
    ) -> DispatchOutcome:
        delegation_id = envelope.delegation_id
        task = await self._cpp_backend.get_task(envelope.task_id)
        if task is None:
            # vanished store: no terminal write anywhere
            return DispatchOutcome(
                delegation_id=delegation_id,
                status=DispatchStatus.SKIPPED,
                skipped_reason="task_unavailable",
            )
        try:
            db_path = self._db_path_for(task)
        except Exception:
            return DispatchOutcome(
                delegation_id=delegation_id,
                status=DispatchStatus.SKIPPED,
                skipped_reason="no_trusted_store_path",
            )
        from .repository import InvestigationRepository

        if not db_path.exists():
            return DispatchOutcome(
                delegation_id=delegation_id,
                status=DispatchStatus.SKIPPED,
                skipped_reason="store_missing",
            )
        repo = AgentRuntimeRepository(
            InvestigationRepository.open_existing(db_path, envelope.task_id)
        )
        runtime = repo
        delegation = runtime.get_delegation(delegation_id)
        if delegation is None:
            return DispatchOutcome(
                delegation_id=delegation_id,
                status=DispatchStatus.SKIPPED,
                skipped_reason="delegation_not_found",
            )
        if delegation.status.value in ("completed", "failed", "cancelled", "stale"):
            return DispatchOutcome(
                delegation_id=delegation_id,
                status=DispatchStatus.SKIPPED,
                skipped_reason=f"already_terminal_{delegation.status.value}",
            )

        # cancellation checkpoint 1: before start
        if delegation.cancel_requested_at:
            runtime.transition_delegation_terminal(
                delegation_id, "cancelled"
            )
            return DispatchOutcome(
                delegation_id=delegation_id, status=DispatchStatus.CANCELLED
            )

        # build the run-scoped registry and verify frozen bindings (§36)
        registry = self._build_registry(runtime)
        pack = envelope.context_pack
        binding_problem = verify_envelope_bindings(envelope, pack, registry)
        if binding_problem is not None:
            runtime.transition_delegation_terminal(
                delegation_id,
                "failed",
                failure_code=DelegationFailureCode.INPUT_CONTRACT_CHANGED.value,
                failure_message=binding_problem,
            )
            return DispatchOutcome(
                delegation_id=delegation_id,
                status=DispatchStatus.FAILED,
                failure_code=DelegationFailureCode.INPUT_CONTRACT_CHANGED.value,
                failure_message=binding_problem,
            )

        runtime.start_delegation(delegation_id)

        # cancellation checkpoint 2: before the agent run
        delegation = runtime.get_delegation(delegation_id)
        if delegation.cancel_requested_at:
            runtime.transition_delegation_terminal(delegation_id, "cancelled")
            return DispatchOutcome(
                delegation_id=delegation_id, status=DispatchStatus.CANCELLED
            )

        return await self._execute_envelope(
            envelope, pack, registry, runtime, delegation_id
        )

    # -- agent execution ------------------------------------------------

    async def _execute_envelope(
        self,
        envelope: DelegationExecutionEnvelope,
        pack: SpecialistContextPack,
        registry,
        runtime: AgentRuntimeRepository,
        delegation_id: str,
    ) -> DispatchOutcome:
        from pydantic_ai.exceptions import UnexpectedModelBehavior
        from pydantic_ai.usage import UsageLimits

        from .agent_deps import ForensicAgentDeps

        context = pack.tool_context()
        deps = ForensicAgentDeps(
            task_id=context.task_id,
            investigation_id=context.investigation_id,
            run_id=context.run_id,
            delegation_id=context.delegation_id,
            question_id=context.question_id,
            source_scope_ids=context.source_scope_ids,
            time_scope=context.time_scope,
            allowed_tool_ids=frozenset(
                tool_id
                for tool_id in context.allowed_tool_ids
                if tool_id in envelope.allowed_tool_ids
            ),
            tool_registry=registry,
            tool_context=context,
        )
        agent = self._build_agent(pack, registry)

        usage_limits = None
        limits: dict[str, int] = {}
        if self._policy.max_model_requests:
            limits["request_limit"] = self._policy.max_model_requests
        if self._policy.max_input_tokens:
            limits["input_tokens_limit"] = self._policy.max_input_tokens
        if self._policy.max_output_tokens:
            limits["output_tokens_limit"] = self._policy.max_output_tokens
        if limits:
            usage_limits = UsageLimits(**limits)

        prompt = self._compose_prompt(pack)
        attempts = self._policy.max_provider_retries + 1
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            agent_started = time.monotonic()
            try:
                agent_result = await agent.run(
                    prompt, deps=deps, usage_limits=usage_limits
                )
                break
            except Exception as exc:  # noqa: BLE001 - provider/tool/output all mapped
                code = map_provider_exception(exc)
                last_exc = exc
                self._emit_failure_diagnostics(
                    exc,
                    attempt=attempt + 1,
                    latency_ms=(time.monotonic() - agent_started) * 1000.0,
                )
                if (
                    code in _RETRYABLE_PROVIDER_CODES
                    and attempt + 1 < attempts
                ):
                    continue
                failure_message = safe_failure_message(exc, code)
                runtime.transition_delegation_terminal(
                    delegation_id,
                    "failed",
                    failure_code=code.value,
                    failure_message=failure_message,
                )
                return DispatchOutcome(
                    delegation_id=delegation_id,
                    status=DispatchStatus.FAILED,
                    failure_code=code.value,
                    failure_message=failure_message,
                )

        # cancellation checkpoint 3: cancel wins over a late result (§28)
        delegation = runtime.get_delegation(delegation_id)
        if delegation.cancel_requested_at:
            runtime.transition_delegation_terminal(delegation_id, "cancelled")
            return DispatchOutcome(
                delegation_id=delegation_id, status=DispatchStatus.CANCELLED
            )

        raw_result = agent_result.output
        if not isinstance(raw_result, SpecialistResultProposalV1):
            failure_code = DelegationFailureCode.AGENT_OUTPUT_INVALID
            failure_message = safe_failure_message(
                last_exc or UnexpectedModelBehavior("output"),
                failure_code,
            )
            runtime.transition_delegation_terminal(
                delegation_id,
                "failed",
                failure_code=failure_code.value,
                failure_message=failure_message,
            )
            return DispatchOutcome(
                delegation_id=delegation_id,
                status=DispatchStatus.FAILED,
                failure_code=failure_code.value,
                failure_message=failure_message,
            )

        # A1-T: the model proposes semantics only; runtime facts are
        # server-owned.  §9 order: proposal schema validation happened at
        # pydantic parse time (extra=forbid, trusted fields structurally
        # absent) -> semantic/evidence validation on the canonical draft
        # -> deterministic enrichment -> canonical validation.
        proposal: SpecialistResultProposalV1 = raw_result

        # Sanitize follow-up scopes: specialists may suggest cross-source scopes (e.g. linux/android/windows)
        # for supervisor follow-up, but the validator enforces pack scope boundaries. Clamp to granted scopes
        # so LLM cross-scope suggestions don't fail the entire specialist result.
        granted_scopes = {
            pack.source_scope_id,
            *pack.source_scope_ids,
        }
        if any(
            any(scope not in granted_scopes for scope in q.suggested_source_scope_ids)
            for q in proposal.follow_up_questions
        ):
            sanitized_follow_ups = []
            for q in proposal.follow_up_questions:
                valid_scopes = tuple(s for s in q.suggested_source_scope_ids if s in granted_scopes)
                if valid_scopes != q.suggested_source_scope_ids:
                    q = q.model_copy(update={"suggested_source_scope_ids": valid_scopes})
                sanitized_follow_ups.append(q)
            proposal = proposal.model_copy(update={"follow_up_questions": tuple(sanitized_follow_ups)})

        observations = runtime.list_tool_observations(
            envelope.investigation_id, run_id=envelope.run_id
        )
        from .agent_tools.visibility import reconstruct_allowed_evidence_ids
        allowed_refs = reconstruct_allowed_evidence_ids(
            (item.evidence_key for item in pack.evidence_digests),
            observations,
            delegation_id=pack.delegation_id,
            run_id=pack.run_id,
        )
        if any(any(ref not in allowed_refs for ref in o.evidence_refs) for o in proposal.coverage_observations):
            proposal = proposal.model_copy(update={
                "coverage_observations": tuple(
                    o.model_copy(update={"evidence_refs": tuple(x for x in o.evidence_refs if x in allowed_refs)})
                    for o in proposal.coverage_observations
                ),
            })
        validator = SpecialistResultValidator()
        draft = proposal.to_canonical_draft()
        validation = validator.validate(pack, draft, observations)

        raw_usage = agent_result.usage
        # pydantic-ai exposes usage as a property on this version; tolerate
        # both shapes so the executor tracks the installed runtime
        usage = raw_usage() if callable(raw_usage) else raw_usage
        usage_payload = self._usage_payload(usage)

        if not validation.valid:
            # audit the invalid proposal, fail the delegation.  The audit
            # row keeps the model's semantic payload with the digest unset;
            # no trusted enrichment of a rejected proposal.
            runtime.record_delegation_result(
                delegation_id,
                result_version=draft.result_version,
                result=draft.model_dump(),
                result_hash=draft.result_hash(),
                context_hash=envelope.context_hash,
                tool_registry_hash=envelope.tool_registry_hash,
                model_name=self._model_name(agent_result),
                model_config_hash=envelope.model_config_digest,
                usage=usage_payload,
                validation_status="invalid",
            )
            runtime.transition_delegation_terminal(
                delegation_id,
                "failed",
                failure_code=DelegationFailureCode.AGENT_OUTPUT_INVALID.value,
                failure_message="result validation failed: "
                + ",".join(validation.codes),
            )
            return DispatchOutcome(
                delegation_id=delegation_id,
                status=DispatchStatus.FAILED,
                failure_code=DelegationFailureCode.AGENT_OUTPUT_INVALID.value,
                failure_message="result validation failed",
                validation_codes=validation.codes,
            )

        # deterministic server enrichment (§5): trusted facts from durable
        # records only; the model's execution digest (if any was somehow
        # produced) never existed — the proposal schema cannot carry it.
        result = finalize_specialist_result(
            proposal,
            delegation_id=envelope.delegation_id,
            model_name=self._model_name(agent_result),
            usage_payload=usage_payload,
            run_observations=observations,
        )
        # canonical validation on the enriched result (§9): identical
        # semantics (the validator is digest-blind) and it pins that the
        # canonical construction itself introduced no drift.
        canonical_validation = validator.validate(pack, result, observations)
        if not canonical_validation.valid:
            runtime.record_delegation_result(
                delegation_id,
                result_version=result.result_version,
                result=result.model_dump(),
                result_hash=result.result_hash(),
                context_hash=envelope.context_hash,
                tool_registry_hash=envelope.tool_registry_hash,
                model_name=result.execution_digest.model_name,
                model_config_hash=envelope.model_config_digest,
                usage=usage_payload,
                validation_status="invalid",
            )
            runtime.transition_delegation_terminal(
                delegation_id,
                "failed",
                failure_code=DelegationFailureCode.AGENT_OUTPUT_INVALID.value,
                failure_message="canonical validation failed: "
                + ",".join(canonical_validation.codes),
            )
            return DispatchOutcome(
                delegation_id=delegation_id,
                status=DispatchStatus.FAILED,
                failure_code=DelegationFailureCode.AGENT_OUTPUT_INVALID.value,
                failure_message="canonical validation failed",
                validation_codes=canonical_validation.codes,
            )
        execution_digest = result.execution_digest

        # A1-S Phase A (§5): resolve every PROMOTED evidence ref
        # (result.evidence_refs — never raw ToolObservation refs, §6/§11)
        # canonically and build immutable snapshot candidates entirely
        # outside any write transaction.  Any resolution failure fails the
        # delegation closed (§9/§12): no completed result, no snapshots.
        snapshot_candidates, resolution_error = (
            await self._resolve_result_evidence(pack.task_id, result)
        )
        if resolution_error is not None:
            runtime.record_delegation_result(
                delegation_id,
                result_version=result.result_version,
                result=result.model_dump(),
                result_hash=result.result_hash(),
                context_hash=envelope.context_hash,
                tool_registry_hash=envelope.tool_registry_hash,
                model_name=execution_digest.model_name,
                model_config_hash=envelope.model_config_digest,
                usage=usage_payload,
                validation_status="invalid",
            )
            runtime.transition_delegation_terminal(
                delegation_id,
                "failed",
                failure_code=(
                    DelegationFailureCode.EVIDENCE_RESOLUTION_FAILED.value
                ),
                failure_message="evidence resolution failed: "
                + resolution_error,
            )
            return DispatchOutcome(
                delegation_id=delegation_id,
                status=DispatchStatus.FAILED,
                failure_code=(
                    DelegationFailureCode.EVIDENCE_RESOLUTION_FAILED.value
                ),
                failure_message="evidence resolution failed",
            )

        # A1-S Phase B (§4): snapshots + result + completed transition in
        # ONE investigation transaction — crash cannot split them.
        stored, _delegation = runtime.complete_delegation_with_result(
            delegation_id,
            result_version=result.result_version,
            result=result.model_dump(),
            result_hash=result.result_hash(),
            context_hash=envelope.context_hash,
            tool_registry_hash=envelope.tool_registry_hash,
            model_name=execution_digest.model_name,
            model_config_hash=envelope.model_config_digest,
            usage=usage_payload,
            evidence_snapshots=tuple(snapshot_candidates),
            trajectory_payload={
                "execution_input_hash": envelope.execution_input_hash(),
                "context_hash": envelope.context_hash,
                "profile_id": envelope.profile_id,
                "profile_version": envelope.profile_version,
                "skill_bindings": [
                    [binding.skill_id, binding.version]
                    for binding in envelope.skill_bindings
                ],
                "tool_registry_hash": envelope.tool_registry_hash,
                "model_config_hash": envelope.model_config_digest,
                # A1-T §10 auditability: what the model proposed, what the
                # server added, what was persisted.
                "specialist_proposal_contract": {
                    "proposal_version": proposal.proposal_version,
                    "proposal_hash": proposal.proposal_hash(),
                    "trusted_enrichment_digest": execution_digest_hash(
                        execution_digest
                    ),
                },
            },
        )
        return DispatchOutcome(
            delegation_id=delegation_id,
            status=DispatchStatus.COMPLETED,
            result_hash=stored.result_hash,
        )

    # -- A1-S evidence admission (Phase A) -------------------------------

    async def _resolve_result_evidence(self, task_id: str, result):
        """Resolve every promoted evidence ref canonically and build the
        immutable snapshot candidates for the completion transaction.

        Source payloads come ONLY from resolve_evidence + the source stores
        (spec §12) — model/tool summaries never enter a snapshot.  Returns
        (candidates, None) or ([], failure_message) fail-closed.
        """
        import asyncio as _asyncio

        from ..evidence.resolver import EvidenceResolver
        from .acquisition import build_snapshot_candidate

        resolver = EvidenceResolver(self._cpp_backend)
        candidates: dict[str, object] = {}
        for ref in result.iter_evidence_refs():
            if not ref or ref in candidates:
                continue
            try:
                resolved = await resolver.resolve_evidence(task_id, ref)
                candidate = await _asyncio.to_thread(
                    build_snapshot_candidate, resolved
                )
            except Exception as exc:  # noqa: BLE001 — fail closed (§9)
                return [], f"{ref!r}: {type(exc).__name__}: {exc}"[:280]
            # canonical key wins over any raw variant the model echoed
            candidates[resolved.evidence_key] = candidate
        return list(candidates.values()), None

    # -- helpers --------------------------------------------------------

    def _build_registry(self, runtime: AgentRuntimeRepository):
        if self._observation_sink_factory is not None:
            return self._registry_builder(
                runtime, observation_sink=self._observation_sink_factory(runtime)
            )
        return self._registry_builder(runtime)

    def _build_agent(self, pack: SpecialistContextPack, registry):
        from .agent_tools.pydantic_bridge import build_specialist_agent

        # A1-T: the model-facing output contract is the trusted-field-free
        # proposal; the canonical SpecialistResultV1 is constructed
        # server-side by finalize_specialist_result after validation.
        return build_specialist_agent(
            pack,
            registry,
            model=self._get_model(),
            output_type=SpecialistResultProposalV1,
            retries=self._policy.max_output_retries,
        )

    def _compose_prompt(self, pack: SpecialistContextPack) -> str:
        """Thin run prompt; the heavy context lives in the agent
        instructions (compiled from the frozen ContextPack layers)."""
        question = pack.question
        scope = pack.source_scope_id
        return (
            f"Investigate the delegated question on source scope "
            f"{scope!r} using only the allowed read-only tools, then return "
            f"the structured specialist result.\n\nQuestion: {question}"
        )

    @staticmethod
    def _model_name(agent_result) -> Optional[str]:
        for candidate in (
            getattr(agent_result, "_model_name", None),
            getattr(getattr(agent_result, "response", None), "model_name", None),
        ):
            if candidate:
                return str(candidate)
        return None

    @staticmethod
    def _usage_payload(usage) -> Optional[dict[str, Any]]:
        if usage is None:
            return None
        payload = {
            "requests": getattr(usage, "requests", None),
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }
        return {k: v for k, v in payload.items() if v is not None} or None

    # -- batch execution (P4A §24-26) -----------------------------------

    async def execute_batch(
        self,
        envelopes: Iterable[DelegationExecutionEnvelope],
        *,
        mode: str = "parallel_all",
        max_parallel: Optional[int] = None,
    ) -> list[DispatchOutcome]:
        """Bounded parallel execution of read-only specialist work.

        ``parallel_all`` runs every envelope concurrently under a
        semaphore (``max_parallel`` or policy default); ``sequential`` runs
        one at a time. A worker failure never cancels unrelated workers.
        """
        envelope_list = list(envelopes)
        if mode == "sequential":
            return [await self._guard(envelope) for envelope in envelope_list]
        semaphore = asyncio.Semaphore(
            max_parallel or self._policy.max_parallel_delegations
        )

        async def worker(envelope: DelegationExecutionEnvelope) -> DispatchOutcome:
            async with semaphore:
                return await self._guard(envelope)

        return list(
            await asyncio.gather(
                *(worker(envelope) for envelope in envelope_list)
            )
        )

    async def _guard(self, envelope) -> DispatchOutcome:
        try:
            return await self.dispatch_delegation(envelope)
        except Exception as exc:  # noqa: BLE001 - one worker never kills others
            return DispatchOutcome(
                delegation_id=envelope.delegation_id,
                status=DispatchStatus.FAILED,
                failure_code=DelegationFailureCode.AGENT_INTERNAL_FAILURE.value,
                failure_message=type(exc).__name__,
            )


__all__ = [
    "AgentRunPolicy",
    "DelegationExecutionEnvelope",
    "DelegationFailureCode",
    "DispatchOutcome",
    "DispatchStatus",
    "ENVELOPE_VERSION",
    "SkillBinding",
    "SpecialistDelegationExecutor",
    "build_execution_envelope",
    "map_provider_exception",
    "model_config_digest_from_adapter_config",
    "safe_failure_message",
    "verify_envelope_bindings",
]
