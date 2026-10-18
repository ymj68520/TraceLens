"""SemanticVerifierAgent contracts, validator and runtime (P5B §4-§19).

One SemanticVerifierAgent, four modes (§4) — claim_sufficiency,
correlation_sufficiency, question_closure, finalization_review. It is a
quality-control Agent: read + reason + structured output. It NEVER writes
Working State, never accepts/rejects anything, never mutates Evidence or
Graph, never publishes reports and never creates Analyst Reviews (§5).
Tools default to none: the frozen EvidenceSupportBundle is the input (§6).

Hard vocabulary boundary (§8/§16): the semantic-support statuses are
exactly sufficient / partially_sufficient / insufficient / contradicted /
indeterminate. Runtime/provider failures are NOT indeterminate — they are
explicitly audited failures (§19). There is no numeric confidence anywhere.

Evidence boundary (§10): every evidence ref in a verifier output must be in
the bundle's evidence allowlist. A guessed-but-real Evidence id that the
bundle never exposed makes the output invalid; the verifier can never
expand Evidence visibility.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, model_validator

from .agent_runtime import (
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
    canonical_state_json,
)
from .agent_specialist_result import AssertionClass

SEMANTIC_VERIFICATION_CONTEXT_VERSION = "semantic-verification-context:v1"
SEMANTIC_VERIFICATION_RESULT_VERSION = "semantic-verification-result:v1"
SEMANTIC_VERIFIER_PROMPT_VERSION = "semantic-verifier:v1"


class SemanticVerificationMode(str, Enum):
    claim_sufficiency = "claim_sufficiency"
    correlation_sufficiency = "correlation_sufficiency"
    question_closure = "question_closure"
    finalization_review = "finalization_review"


class SemanticVerificationStatus(str, Enum):
    """§8 frozen semantic-support vocabulary. Nothing else may exist."""

    SUFFICIENT = "sufficient"
    PARTIALLY_SUFFICIENT = "partially_sufficient"
    INSUFFICIENT = "insufficient"
    CONTRADICTED = "contradicted"
    INDETERMINATE = "indeterminate"


class VerifierFailureCode(str, Enum):
    """§19 explicit runtime failure vocabulary — never a semantic status."""

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    AUTH_FAILED = "auth_failed"
    BILLING_UNAVAILABLE = "billing_unavailable"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    OUTPUT_INVALID = "output_invalid"
    INPUT_STALE = "input_stale"
    INTERNAL_FAILURE = "internal_failure"
    RUNTIME_RESTART = "runtime_restart"


def _canonical_text(value: str) -> str:
    import re

    return re.sub(r"\s+", " ", value).strip()


class SemanticVerificationContextV1(BaseModel):
    """§7 frozen verifier input. The verifier reads ONLY this — it never
    re-reads a moving Working State to change claim semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_version: str = SEMANTIC_VERIFICATION_CONTEXT_VERSION

    task_id: str
    investigation_id: str
    mode: SemanticVerificationMode

    proposal_id: str
    proposal_hash: str

    grounding_id: str
    grounding_status: str

    support_bundle_id: str
    support_bundle_hash: str

    # §10 allowlist: the bundle's exposed evidence refs, the ONLY refs the
    # verifier may cite back.
    evidence_allowlist: tuple[str, ...] = ()

    effective_assertion_class: AssertionClass
    claim_text: str

    relationship_refs: tuple[str, ...] = ()
    temporal_scope: Optional[dict] = None
    question_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    policy_context_digest: str = ""

    verification_id: str = ""
    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive_ids(cls, data):
        if not isinstance(data, dict):
            return data
        payload = {
            "context_version": SEMANTIC_VERIFICATION_CONTEXT_VERSION,
            "task_id": data.get("task_id"),
            "investigation_id": data.get("investigation_id"),
            "mode": str(data.get("mode")),
            "proposal_id": data.get("proposal_id"),
            "proposal_hash": data.get("proposal_hash"),
            "grounding_id": data.get("grounding_id"),
            "grounding_status": data.get("grounding_status"),
            "support_bundle_id": data.get("support_bundle_id"),
            "support_bundle_hash": data.get("support_bundle_hash"),
            "evidence_allowlist": sorted(
                {str(ref) for ref in (data.get("evidence_allowlist") or ())
                 if ref}
            ),
            "effective_assertion_class": str(
                data.get("effective_assertion_class")
            ),
            "claim_text": _canonical_text(str(data.get("claim_text") or "")),
            "relationship_refs": sorted(
                {str(ref) for ref in (data.get("relationship_refs") or ())
                 if ref}
            ),
            "temporal_scope": data.get("temporal_scope"),
            "question_refs": sorted(
                {str(ref) for ref in (data.get("question_refs") or ()) if ref}
            ),
            "limitations": sorted(
                {str(item) for item in (data.get("limitations") or ())
                 if item}
            ),
            "policy_context_digest": data.get("policy_context_digest") or "",
        }
        input_hash = hashlib.sha256(
            canonical_state_json(payload).encode("utf-8")
        ).hexdigest()
        data["claim_text"] = payload["claim_text"]
        data["evidence_allowlist"] = tuple(payload["evidence_allowlist"])
        data["relationship_refs"] = tuple(payload["relationship_refs"])
        data["question_refs"] = tuple(payload["question_refs"])
        data["limitations"] = tuple(payload["limitations"])
        data["policy_context_digest"] = payload["policy_context_digest"]
        data["input_hash"] = input_hash
        data["verification_id"] = "sver:" + hashlib.sha256(
            canonical_state_json({**payload, "input_hash": input_hash})
            .encode("utf-8")
        ).hexdigest()[:24]
        return data

    def to_row(self) -> dict:
        return {
            "verification_id": self.verification_id,
            "mode": self.mode.value,
            "proposal_id": self.proposal_id,
            "proposal_hash": self.proposal_hash,
            "grounding_id": self.grounding_id,
            "support_bundle_id": self.support_bundle_id,
            "support_bundle_hash": self.support_bundle_hash,
            "effective_assertion_class": self.effective_assertion_class.value,
            "claim_text": self.claim_text,
            "input_hash": self.input_hash,
        }


class SemanticVerificationResultV1(BaseModel):
    """§8/§9 immutable verifier output (version-frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result_version: str = SEMANTIC_VERIFICATION_RESULT_VERSION

    verification_id: str
    mode: SemanticVerificationMode

    task_id: str
    investigation_id: str

    proposal_id: str
    proposal_hash: str

    support_bundle_id: str
    support_bundle_hash: str

    status: SemanticVerificationStatus

    supported_parts: tuple[str, ...] = ()
    unsupported_parts: tuple[str, ...] = ()
    contradicting_evidence_refs: tuple[str, ...] = ()
    alternative_explanations: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()

    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    recommended_assertion_class: AssertionClass

    model: Optional[str] = None
    prompt_version: str = SEMANTIC_VERIFIER_PROMPT_VERSION
    model_config_hash: Optional[str] = None

    input_hash: str = ""

    def to_row(self) -> dict:
        return {
            "verification_id": self.verification_id,
            "mode": self.mode.value,
            "proposal_id": self.proposal_id,
            "proposal_hash": self.proposal_hash,
            "grounding_id": None,
            "support_bundle_id": self.support_bundle_id,
            "support_bundle_hash": self.support_bundle_hash,
            "status": self.status.value,
            "result": self.model_dump(mode="json"),
            "recommended_assertion_class":
                self.recommended_assertion_class.value,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "model_config_hash": self.model_config_hash,
            "input_hash": self.input_hash,
        }


class VerificationViolationCode(str, Enum):
    """§17 deterministic output-validator violation codes."""

    VERIFICATION_VERSION_UNSUPPORTED = "VERIFICATION_VERSION_UNSUPPORTED"
    VERIFICATION_IDENTITY_MISMATCH = "VERIFICATION_IDENTITY_MISMATCH"
    VERIFICATION_PROPOSAL_MISMATCH = "VERIFICATION_PROPOSAL_MISMATCH"
    VERIFICATION_BUNDLE_MISMATCH = "VERIFICATION_BUNDLE_MISMATCH"
    VERIFICATION_MODE_MISMATCH = "VERIFICATION_MODE_MISMATCH"
    VERIFICATION_CONTRADICTED_WITHOUT_REFS = (
        "VERIFICATION_CONTRADICTED_WITHOUT_REFS"
    )
    VERIFICATION_PARTIAL_WITHOUT_UNSUPPORTED = (
        "VERIFICATION_PARTIAL_WITHOUT_UNSUPPORTED"
    )
    VERIFICATION_EVIDENCE_REF_OUTSIDE_BUNDLE = (
        "VERIFICATION_EVIDENCE_REF_OUTSIDE_BUNDLE"
    )
    VERIFICATION_REVIEW_MUTATION_FORBIDDEN = (
        "VERIFICATION_REVIEW_MUTATION_FORBIDDEN"
    )
    VERIFICATION_TEXT_FIELD_INVALID = "VERIFICATION_TEXT_FIELD_INVALID"


class SemanticVerifierOutputValidator:
    """§17 structural accept/reject gate. Any violation = fail closed."""

    def validate(
        self,
        result: SemanticVerificationResultV1,
        *,
        context: SemanticVerificationContextV1,
    ) -> tuple[VerificationViolationCode, ...]:
        violations: list[VerificationViolationCode] = []
        if result.result_version != SEMANTIC_VERIFICATION_RESULT_VERSION:
            violations.append(
                VerificationViolationCode.VERIFICATION_VERSION_UNSUPPORTED
            )
        if (
            result.task_id != context.task_id
            or result.investigation_id != context.investigation_id
            or result.verification_id != context.verification_id
        ):
            violations.append(
                VerificationViolationCode.VERIFICATION_IDENTITY_MISMATCH
            )
        if (
            result.proposal_id != context.proposal_id
            or result.proposal_hash != context.proposal_hash
        ):
            violations.append(
                VerificationViolationCode.VERIFICATION_PROPOSAL_MISMATCH
            )
        if (
            result.support_bundle_id != context.support_bundle_id
            or result.support_bundle_hash != context.support_bundle_hash
        ):
            violations.append(
                VerificationViolationCode.VERIFICATION_BUNDLE_MISMATCH
            )
        if result.mode != context.mode:
            violations.append(
                VerificationViolationCode.VERIFICATION_MODE_MISMATCH
            )
        if (
            result.status is SemanticVerificationStatus.CONTRADICTED
            and not result.contradicting_evidence_refs
        ):
            violations.append(
                VerificationViolationCode.VERIFICATION_CONTRADICTED_WITHOUT_REFS
            )
        if (
            result.status
            is SemanticVerificationStatus.PARTIALLY_SUFFICIENT
            and not result.unsupported_parts
        ):
            violations.append(
                VerificationViolationCode.
                VERIFICATION_PARTIAL_WITHOUT_UNSUPPORTED
            )
        allowlist = set(context.evidence_allowlist)
        for ref in result.contradicting_evidence_refs:
            if ref not in allowlist:
                violations.append(
                    VerificationViolationCode.
                    VERIFICATION_EVIDENCE_REF_OUTSIDE_BUNDLE
                )
        # §17: no accepted/rejected or review mutation can even be
        # expressed — the frozen model has no such fields; a Graph or
        # report reference has no place in any text field either.
        blob = " ".join(
            (*result.supported_parts, *result.unsupported_parts,
             *result.alternative_explanations, *result.missing_evidence)
        ).lower()
        for token in ("accepted", "rejected", "review_pending"):
            if f"status={token}" in blob or f"decision:{token}" in blob:
                violations.append(
                    VerificationViolationCode.
                    VERIFICATION_REVIEW_MUTATION_FORBIDDEN
                )
                break
        return tuple(violations)


class VerifierFailure(BaseModel):
    """§19 explicit runtime failure — audited, never a semantic status."""

    model_config = ConfigDict(frozen=True)

    failure_code: VerifierFailureCode
    detail: str = ""
    model: Optional[str] = None
    input_hash: str = ""


# §11: the eight mandatory semantic-QC checks, verbatim in the instructions.
_MODE_INSTRUCTIONS = {
    SemanticVerificationMode.claim_sufficiency: (
        "You are a forensic semantic quality-control verifier. Given the "
        "frozen EvidenceSupportBundle for one claim proposal, explicitly "
        "assess: (1) which parts of the claim the evidence directly "
        "supports; (2) which parts are unsupported; (3) whether any "
        "evidence in the bundle contradicts the claim; (4) whether a "
        "reasonable alternative explanation exists; (5) which missing "
        "evidence would strengthen the assertion; (6) whether a temporal "
        "relation is being mistaken for a causal one; (7) whether entity "
        "identity is being over-merged; (8) whether observation is being "
        "confused with inference. Decide one support status: sufficient, "
        "partially_sufficient, insufficient, contradicted, or "
        "indeterminate. This is semantic QC, not report writing."
    ),
    SemanticVerificationMode.correlation_sufficiency: (
        "You are a forensic semantic quality-control verifier. Given the "
        "frozen bundle for one correlation-derived claim, assess whether "
        "the exposed evidence suffices for the asserted relation "
        "(same-entity, cross-device behavior, sequence, or causal "
        "hypothesis). Explicitly check the eight QC points: supported "
        "parts, unsupported parts, contradictions, alternative "
        "explanations, missing evidence, temporal-vs-causal confusion, "
        "identity over-merge, observation-vs-inference confusion."
    ),
    SemanticVerificationMode.question_closure: (
        "You are a forensic semantic quality-control verifier. Given the "
        "frozen context for one question, output only closure_support / "
        "closure_not_supported style QC findings: whether the recorded "
        "evidence digests support closing the question, issues found, and "
        "missing evidence. You never transition the question yourself."
    ),
    SemanticVerificationMode.finalization_review: (
        "You are a forensic semantic quality-control verifier performing "
        "the final semantic review. Given the frozen final-context "
        "digests, report pass or issues_found with explicit issues and "
        "affected refs. You never complete the investigation."
    ),
}


class SemanticVerifierAgent:
    """One agent class, four modes (§4). Tools = none (§6): the frozen
    bundle/context is the whole input. Lazy pydantic_ai import."""

    VERSION = SEMANTIC_VERIFIER_PROMPT_VERSION

    def __init__(
        self,
        *,
        mode: SemanticVerificationMode,
        model: Optional[Any] = None,
        model_name: Optional[str] = None,
        model_config_hash: Optional[str] = None,
        retries: int = 1,
    ):
        self.mode = mode
        self._model = model
        self._model_name = model_name
        self._model_config_hash = model_config_hash
        self._retries = retries

    @property
    def instructions(self) -> str:
        return _MODE_INSTRUCTIONS[self.mode]

    def _build_agent(self):
        # pydantic_ai 2.x: first positional arg is the model; instructions
        # are keyword-only. Tests pass an offline TestModel as self._model.
        if self._model is not None:
            from pydantic_ai import Agent

            return Agent(
                self._model,
                instructions=self.instructions,
                output_type=SemanticVerificationResultV1,
                retries=self._retries,
            )
        from pydantic_ai import Agent

        return Agent(
            self.instructions,
            output_type=SemanticVerificationResultV1,
            retries=self._retries,
        )

    async def run(
        self,
        context: SemanticVerificationContextV1,
    ) -> SemanticVerificationResultV1 | VerifierFailure:
        """Frozen context in, validated result out — or an explicit
        failure. Never raises a provider error past this boundary (§48)."""
        from .agent_specialist_executor import map_provider_exception

        try:
            agent = self._build_agent()
            run_result = await agent.run(
                _render_context(context),
                output_type=SemanticVerificationResultV1,
            )
            result: SemanticVerificationResultV1 = run_result.output
        except Exception as exc:  # provider / model / output failures
            failure_code = _map_verifier_exception(exc)
            return VerifierFailure(
                failure_code=failure_code,
                detail=f"{type(exc).__name__}: {exc}"[:500],
                model=self._model_name,
                input_hash=context.input_hash,
            )
        # Validate the RAW model output against the frozen context first:
        # a model asserting a different identity/proposal/bundle fails
        # closed (audited) instead of being silently repaired. Only then
        # are runtime facts (never model-controlled) bound deterministically.
        candidate = result.model_copy(update={
            "input_hash": context.input_hash,
            "model": self._model_name,
            "model_config_hash": self._model_config_hash,
            "prompt_version": self.VERSION,
        })
        violations = SemanticVerifierOutputValidator().validate(
            candidate, context=context
        )
        if violations:
            return VerifierFailure(
                failure_code=VerifierFailureCode.OUTPUT_INVALID,
                detail=",".join(code.value for code in violations),
                model=self._model_name,
                input_hash=context.input_hash,
            )
        return candidate.model_copy(update={
            "verification_id": context.verification_id,
            "mode": context.mode,
            "task_id": context.task_id,
            "investigation_id": context.investigation_id,
            "proposal_id": context.proposal_id,
            "proposal_hash": context.proposal_hash,
            "support_bundle_id": context.support_bundle_id,
            "support_bundle_hash": context.support_bundle_hash,
        })


def _render_context(context: SemanticVerificationContextV1) -> str:
    """Deterministic flat rendering of the frozen context for the model."""
    lines = [
        f"mode: {context.mode.value}",
        f"claim_text: {context.claim_text}",
        f"effective_assertion_class: {context.effective_assertion_class.value}",
        f"grounding_status: {context.grounding_status}",
        "evidence_allowlist: " + (
            ", ".join(context.evidence_allowlist) or "(none)"
        ),
    ]
    if context.relationship_refs:
        lines.append(
            "relationship_refs: " + ", ".join(context.relationship_refs)
        )
    if context.question_refs:
        lines.append("question_refs: " + ", ".join(context.question_refs))
    for limitation in context.limitations:
        lines.append(f"limitation: {limitation}")
    return "\n".join(lines)


def _map_verifier_exception(exc: Exception) -> VerifierFailureCode:
    """Reuse the P4A provider-failure normalization (§47); fall back to
    the verifier-specific structural codes."""
    from .agent_specialist_executor import (
        DelegationFailureCode,
        map_provider_exception,
    )

    try:
        mapped = map_provider_exception(exc)
    except Exception:
        return VerifierFailureCode.INTERNAL_FAILURE
    translation = {
        DelegationFailureCode.AGENT_BILLING_UNAVAILABLE:
            VerifierFailureCode.BILLING_UNAVAILABLE,
        DelegationFailureCode.AGENT_AUTH_FAILED:
            VerifierFailureCode.AUTH_FAILED,
        DelegationFailureCode.AGENT_RATE_LIMITED:
            VerifierFailureCode.RATE_LIMITED,
        DelegationFailureCode.AGENT_PROVIDER_UNAVAILABLE:
            VerifierFailureCode.PROVIDER_UNAVAILABLE,
        DelegationFailureCode.AGENT_TIMEOUT:
            VerifierFailureCode.TIMEOUT,
        DelegationFailureCode.AGENT_OUTPUT_INVALID:
            VerifierFailureCode.OUTPUT_INVALID,
        DelegationFailureCode.AGENT_INTERNAL_FAILURE:
            VerifierFailureCode.INTERNAL_FAILURE,
    }
    return translation.get(
        mapped, VerifierFailureCode.INTERNAL_FAILURE
    )


def build_claim_verification_context(
    *,
    task_id: str,
    investigation_id: str,
    proposal,
    grounding,
    support_bundle_row: Optional[Mapping[str, Any]] = None,
) -> SemanticVerificationContextV1:
    """Freeze the §7 context from durable P5A artifacts (claim mode).

    ``proposal`` is a ``ProposedClaimV1``; ``grounding`` is a
    ``GroundingResultV1`` or its repository row dict; the bundle row comes
    from ``list_support_bundles`` when one was persisted."""
    from .agent_claims import ProposedClaimV1
    from .agent_grounding import GroundingResultV1, GroundingStatus

    if isinstance(proposal, ProposedClaimV1):
        proposal_hash = proposal.input_hash
        claim_text = proposal.text
        question_refs = proposal.source_question_ids
        relationship_refs = proposal.relationship_refs
        temporal_scope = proposal.temporal_scope
    else:  # pragma: no cover - callers pass the frozen model
        raise TypeError("proposal must be ProposedClaimV1")
    if isinstance(grounding, GroundingResultV1):
        grounding_id = grounding.grounding_id
        grounding_status = grounding.status.value
        effective_class = grounding.effective_assertion_class
    else:
        grounding_id = grounding["grounding_id"]
        grounding_status = grounding["status"]
        effective_class = AssertionClass(grounding["effective_assertion_class"])
    bundle_id = (support_bundle_row or {}).get(
        "bundle_id", "bundle:absent"
    )
    bundle_hash = (support_bundle_row or {}).get("input_hash", "absent")
    allowlist = tuple(
        (support_bundle_row or {}).get("evidence_refs_allowlist", ())
        or ()
    )
    if not allowlist:
        # no persisted bundle: fall back to the grounding's valid refs —
        # exactly what a digest-only bundle would expose
        if isinstance(grounding, GroundingResultV1):
            allowlist = grounding.valid_evidence_refs
        else:
            allowlist = tuple(grounding.get("valid_evidence_refs", ()))
    return SemanticVerificationContextV1(
        task_id=task_id,
        investigation_id=investigation_id,
        mode=SemanticVerificationMode.claim_sufficiency,
        proposal_id=proposal.proposal_id,
        proposal_hash=proposal_hash,
        grounding_id=grounding_id,
        grounding_status=grounding_status,
        support_bundle_id=bundle_id,
        support_bundle_hash=bundle_hash,
        evidence_allowlist=allowlist,
        effective_assertion_class=effective_class,
        claim_text=claim_text,
        relationship_refs=relationship_refs,
        temporal_scope=temporal_scope,
        question_refs=question_refs,
        limitations=(),
    )


async def process_claim_verification(
    runtime: AgentRuntimeRepository,
    *,
    task_id: str,
    investigation_id: str,
    proposal,
    grounding,
    bundle_row: Optional[Mapping[str, Any]] = None,
    relation_family: Optional[str] = None,
    semantic_type: Optional["AssertionSemanticType"] = None,
    verifier: Optional[SemanticVerifierAgent] = None,
    policy: Optional["AssertionPolicy"] = None,
    run_id: Optional[str] = None,
) -> dict:
    """§77 explicit verification pipeline entry - NEVER called by the P4
    cycle. The policy decides whether the verifier runs (§54/§55); the
    verifier executes only when provided and required/optional; results or
    explicit failures persist; the disposition (+ optional review_pending
    Finding) commits atomically."""
    from .agent_assertion_policy import (
        AssertionPolicy,
        ClaimDecision,
        VerificationAvailability,
        VerificationRequirement,
    )
    from .agent_runtime import VerificationObligationStatus
    from .agent_findings import finding_from_disposition

    policy = policy or AssertionPolicy()
    resolved_type = policy.classify(
        relation_family=relation_family, explicit_type=semantic_type
    )
    requirement = policy.preflight(resolved_type)
    rule = policy.registry.rule_for(resolved_type)

    # F1 §3/§4/§5: a semantic_required preflight must produce a durable,
    # replay-idempotent Verification Obligation (never just a Python
    # return value). The obligation row - not process memory - is what
    # Attention and Finalization read (via the deterministic projection).
    import hashlib as _hashlib

    question_refs = tuple(
        proposal.source_question_ids
        if hasattr(proposal, "source_question_ids") else ()
    )
    obligation_payload = {
        "task_id": task_id,
        "investigation_id": investigation_id,
        "proposal_id": proposal.proposal_id,
        "proposal_hash": proposal.input_hash,
        "grounding_id": getattr(grounding, "grounding_id", None)
        or grounding.get("grounding_id"),
        "semantic_type": resolved_type.value,
        "assertion_policy_version": policy.VERSION,
        "rule_id": rule.rule_id,
        "verification_mode": rule.verification_mode.value,
        "question_refs": list(question_refs),
    }
    obligation_id = "vob:" + _hashlib.sha256(
        canonical_state_json(obligation_payload).encode("utf-8")
    ).hexdigest()[:24]
    obligation_known = (
        runtime.get_verification_obligation(
            investigation_id, obligation_id
        )
        is not None
    )
    if requirement is VerificationRequirement.REQUIRED and not obligation_known:
        # F1 §5 creation boundary: exactly once per mandatory verification
        runtime.record_verification_obligation(
            investigation_id,
            obligation_row={
                **obligation_payload,
                "obligation_id": obligation_id,
                "input_hash": canonical_state_json(obligation_payload),
                "status": "pending",
            },
        )
        obligation_known = True
    if requirement is VerificationRequirement.REQUIRED:
        existing = runtime.get_verification_obligation(
            investigation_id, obligation_id
        )
        if existing["status"] == "pending":
            runtime.advance_verification_obligation(
                investigation_id, obligation_id,
                to_status=VerificationObligationStatus.running,
            )

    verification = None
    availability = VerificationAvailability.UNAVAILABLE
    if requirement is not VerificationRequirement.NOT_REQUIRED:
        if verifier is None:
            # policy demanded verification but no verifier runtime was
            # provided: explicit unavailable (§48), never fabricated.
            # Obligation resolution happens in the unified tail below.
            availability = VerificationAvailability.UNAVAILABLE
        else:
            context = build_claim_verification_context(
                task_id=task_id,
                investigation_id=investigation_id,
                proposal=proposal,
                grounding=grounding,
                support_bundle_row=bundle_row,
            )
            outcome = await verifier.run(context)
            if isinstance(outcome, VerifierFailure):
                runtime.record_semantic_verification_failure(
                    investigation_id,
                    failure_row={
                        "failure_id": "sverfail:" + context.verification_id,
                        "mode": context.mode.value,
                        "proposal_id": context.proposal_id,
                        "failure_code": outcome.failure_code.value,
                        "detail": outcome.detail,
                        "model": outcome.model,
                        "input_hash": context.input_hash,
                    },
                )
                if obligation_known:
                    # F1 §8: pending -> failed/unavailable; provider-type
                    # failures are unavailable, structural ones failed
                    obligation_status = (
                        VerificationObligationStatus.UNAVAILABLE
                        if outcome.failure_code in (
                            VerifierFailureCode.PROVIDER_UNAVAILABLE,
                            VerifierFailureCode.AUTH_FAILED,
                            VerifierFailureCode.BILLING_UNAVAILABLE,
                            VerifierFailureCode.RATE_LIMITED,
                            VerifierFailureCode.TIMEOUT,
                        )
                        else VerificationObligationStatus.FAILED
                    )
                    runtime.advance_verification_obligation(
                        investigation_id, obligation_id,
                        to_status=obligation_status,
                        verification_id=context.verification_id,
                        failure_code=outcome.failure_code.value,
                    )
            else:
                verification = outcome
                availability = VerificationAvailability.AVAILABLE
                if obligation_known:
                    runtime.advance_verification_obligation(
                        investigation_id, obligation_id,
                        to_status=VerificationObligationStatus.satisfied,
                        verification_id=context.verification_id,
                    )
                trajectory_event = (
                    AgentTrajectoryEventType.correlation_semantic_verified
                    if resolved_type is not None
                    and context.mode is SemanticVerificationMode.correlation_sufficiency
                    else AgentTrajectoryEventType.claim_semantic_verified
                )
                runtime.record_semantic_verification(
                    investigation_id,
                    verification_row=verification.to_row(),
                    grounding_id=context.grounding_id,
                    trajectory_event=trajectory_event,
                    run_id=run_id,
                )
    elif verification is None:
        availability = VerificationAvailability.UNAVAILABLE

    disposition = policy.finalize(
        proposal, grounding,
        semantic_type=resolved_type,
        verification=verification,
        verification_availability=availability,
    )

    finding_row = None
    finding = None
    if disposition.decision in (
        ClaimDecision.ELIGIBLE_REVIEW_PENDING,
        ClaimDecision.DOWNGRADE_TO_HYPOTHESIS,
    ):
        grounding_id = (
            grounding.grounding_id
            if hasattr(grounding, "grounding_id")
            else grounding["grounding_id"]
        )
        finding = finding_from_disposition(
            disposition, proposal=proposal, grounding_id=grounding_id,
            semantic_verification_id=(
                verification.verification_id if verification else None
            ),
            effective_assertion_class=disposition.effective_assertion_class,
        )
        finding_row = finding.to_row()

    # F1 §8 resolution: every unfinished obligation of THIS proposal is
    # resolved deterministically by the disposition - blocked leaves the
    # blockers blocking; a safe (non-blocked) policy resolution terminates
    # them as explicitly safely_downgraded (never deleted).
    open_obligations = [
        row for row in runtime.list_verification_obligations(
            investigation_id
        )
        if row["proposal_id"] == proposal.proposal_id
        and row["status"] in ("pending", "running", "unavailable", "failed")
    ]
    if disposition.decision is ClaimDecision.BLOCKED_VERIFICATION_REQUIRED:
        for row in open_obligations:
            if row["status"] in ("pending", "running"):
                runtime.advance_verification_obligation(
                    investigation_id, row["obligation_id"],
                    to_status=VerificationObligationStatus.unavailable,
                    failure_code="semantic_verification_blocked",
                )
    elif availability is VerificationAvailability.UNAVAILABLE:
        for row in open_obligations:
            runtime.advance_verification_obligation(
                investigation_id, row["obligation_id"],
                to_status=VerificationObligationStatus.safely_downgraded,
                disposition_id=disposition.disposition_id,
            )

    outcome = runtime.commit_claim_disposition(
        investigation_id,
        disposition_row=disposition.to_row(),
        finding_row=finding_row,
        run_id=run_id,
    )
    return {
        "semantic_type": resolved_type.value
        if hasattr(resolved_type, "value") else str(resolved_type),
        "verification_requirement": requirement.value,
        "verification_available": availability
        is VerificationAvailability.AVAILABLE,
        "disposition": disposition,
        "finding": finding,
        "commit": outcome,
    }


# ---------------------------------------------------------------------------
# §50/§52: question_closure + finalization_review frozen contexts/outputs.
# The verifier never transitions a Question and never completes an
# Investigation - it only emits QC review input (§49/§52).
# ---------------------------------------------------------------------------

QUESTION_CLOSURE_REVIEW_VERSION = "question-closure-review:v1"
FINAL_SEMANTIC_REVIEW_VERSION = "final-semantic-review:v1"


class QuestionClosureContextV1(BaseModel):
    """Frozen question-closure QC input: recorded digests only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_version: str = SEMANTIC_VERIFICATION_CONTEXT_VERSION
    task_id: str
    investigation_id: str
    question_refs: tuple[str, ...] = ()
    question_text: str = ""
    evidence_allowlist: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    verification_id: str = ""
    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        payload = {
            "context_version": SEMANTIC_VERIFICATION_CONTEXT_VERSION,
            "task_id": data.get("task_id"),
            "investigation_id": data.get("investigation_id"),
            "question_refs": sorted(
                {str(ref) for ref in (data.get("question_refs") or ())
                 if ref}
            ),
            "question_text": _canonical_text(
                str(data.get("question_text") or "")
            ),
            "evidence_allowlist": sorted(
                {str(ref) for ref in (data.get("evidence_allowlist") or ())
                 if ref}
            ),
        }
        input_hash = hashlib.sha256(
            canonical_state_json(payload).encode("utf-8")
        ).hexdigest()
        data["question_text"] = payload["question_text"]
        data["evidence_allowlist"] = tuple(payload["evidence_allowlist"])
        data["question_refs"] = tuple(payload["question_refs"])
        data["input_hash"] = input_hash
        data["verification_id"] = "sver:" + hashlib.sha256(
            canonical_state_json({**payload, "input_hash": input_hash})
            .encode("utf-8")
        ).hexdigest()[:24]
        return data


class QuestionClosureReviewV1(BaseModel):
    """§52: QC output only - closure_supported is a RECOMMENDATION; the
    real Question transition happens solely through Supervisor
    Integration -> StateTransitionPolicy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result_version: str = QUESTION_CLOSURE_REVIEW_VERSION
    verification_id: str
    mode: SemanticVerificationMode
    task_id: str
    investigation_id: str
    question_refs: tuple[str, ...] = ()
    closure_supported: bool
    issues: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    model: Optional[str] = None
    prompt_version: str = SEMANTIC_VERIFIER_PROMPT_VERSION
    input_hash: str = ""


class FinalSemanticReviewContextV1(BaseModel):
    """§50 frozen final-review input: state + finding DIGESTS, never the
    whole case evidence set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_version: str = SEMANTIC_VERIFICATION_CONTEXT_VERSION
    task_id: str
    investigation_id: str

    final_state_digest: str
    final_state_revision: int = 0

    required_question_digests: tuple[str, ...] = ()
    coverage_digests: tuple[str, ...] = ()
    contradiction_digests: tuple[str, ...] = ()
    finding_digests: tuple[str, ...] = ()
    mandatory_verification_statuses: tuple[str, ...] = ()

    limitations: tuple[str, ...] = ()
    evidence_provenance_digests: tuple[str, ...] = ()

    verification_id: str = ""
    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        payload = {
            "context_version": SEMANTIC_VERIFICATION_CONTEXT_VERSION,
            "task_id": data.get("task_id"),
            "investigation_id": data.get("investigation_id"),
            "final_state_digest": data.get("final_state_digest"),
            "final_state_revision": data.get("final_state_revision"),
            "required_question_digests": sorted(
                {str(item) for item in
                 (data.get("required_question_digests") or ()) if item}
            ),
            "coverage_digests": sorted(
                {str(item) for item in
                 (data.get("coverage_digests") or ()) if item}
            ),
            "contradiction_digests": sorted(
                {str(item) for item in
                 (data.get("contradiction_digests") or ()) if item}
            ),
            "finding_digests": sorted(
                {str(item) for item in
                 (data.get("finding_digests") or ()) if item}
            ),
            "mandatory_verification_statuses": sorted(
                {str(item) for item in
                 (data.get("mandatory_verification_statuses") or ())
                 if item}
            ),
            "limitations": sorted(
                {str(item) for item in (data.get("limitations") or ())
                 if item}
            ),
            "evidence_provenance_digests": sorted(
                {str(item) for item in
                 (data.get("evidence_provenance_digests") or ()) if item}
            ),
        }
        input_hash = hashlib.sha256(
            canonical_state_json(payload).encode("utf-8")
        ).hexdigest()
        for key, value in payload.items():
            if key.endswith("digests") or key.endswith("statuses"):
                data[key] = tuple(value)
            elif key == "limitations":
                data[key] = tuple(value)
        data["input_hash"] = input_hash
        data["verification_id"] = "sver:" + hashlib.sha256(
            canonical_state_json({**payload, "input_hash": input_hash})
            .encode("utf-8")
        ).hexdigest()[:24]
        return data


class FinalSemanticReviewOutputV1(BaseModel):
    """§51: pass / issues_found only. Never 'investigation completed'."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result_version: str = FINAL_SEMANTIC_REVIEW_VERSION
    verification_id: str
    mode: SemanticVerificationMode
    task_id: str
    investigation_id: str
    status: str  # 'pass' | 'issues_found'
    issues: tuple[str, ...] = ()
    affected_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    model: Optional[str] = None
    prompt_version: str = SEMANTIC_VERIFIER_PROMPT_VERSION
    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _check(cls, data):
        if isinstance(data, dict) and data.get("status") not in (
            "pass", "issues_found"
        ):
            raise ValueError(
                "final semantic review status must be pass/issues_found"
            )
        return data


class FinalSemanticReviewValidator:
    """§51 gate: issues_found requires issues; runtime callers never
    fabricate a pass row when the verifier is unavailable (§68)."""

    def validate(
        self,
        output: FinalSemanticReviewOutputV1,
        *,
        context: FinalSemanticReviewContextV1,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if output.result_version != FINAL_SEMANTIC_REVIEW_VERSION:
            violations.append("FINAL_REVIEW_VERSION_UNSUPPORTED")
        if (
            output.verification_id != context.verification_id
            or output.task_id != context.task_id
            or output.investigation_id != context.investigation_id
        ):
            violations.append("FINAL_REVIEW_IDENTITY_MISMATCH")
        if output.status == "issues_found" and not output.issues:
            violations.append("FINAL_REVIEW_ISSUES_REQUIRED")
        if output.input_hash != context.input_hash:
            violations.append("FINAL_REVIEW_INPUT_HASH_MISMATCH")
        return tuple(violations)


def build_final_review_context(payload: Mapping) -> FinalSemanticReviewContextV1:
    """Adapter seam (F2 §15): project the orchestrator's pure-data payload
    onto the frozen FinalSemanticReviewContextV1. Unknown payload keys are
    ignored; required identity keys must be present (fail closed)."""
    return FinalSemanticReviewContextV1(
        task_id=payload["task_id"],
        investigation_id=payload["investigation_id"],
        final_state_digest=str(
            payload.get("final_state_digest")
            or payload.get("expected_state_hash")
            or ""
        ),
        final_state_revision=int(
            payload.get("final_state_revision")
            or payload.get("expected_state_revision")
            or 0
        ),
        required_question_digests=tuple(
            payload.get("required_question_digests") or ()
        ),
        coverage_digests=tuple(payload.get("coverage_digests") or ()),
        contradiction_digests=tuple(
            payload.get("contradiction_digests") or ()
        ),
        finding_digests=tuple(payload.get("finding_digests") or ()),
        mandatory_verification_statuses=tuple(
            payload.get("mandatory_verification_statuses") or ()
        ),
        limitations=tuple(payload.get("limitations") or ()),
        evidence_provenance_digests=tuple(
            payload.get("evidence_provenance_digests") or ()
        ),
    )


__all__ = [
    "SEMANTIC_VERIFICATION_CONTEXT_VERSION",
    "SEMANTIC_VERIFICATION_RESULT_VERSION",
    "SEMANTIC_VERIFIER_PROMPT_VERSION",
    "AssertionClass",
    "SemanticVerificationContextV1",
    "SemanticVerificationMode",
    "SemanticVerificationResultV1",
    "SemanticVerificationStatus",
    "SemanticVerifierAgent",
    "SemanticVerifierOutputValidator",
    "VerifierFailure",
    "VerifierFailureCode",
    "VerificationViolationCode",
    "build_claim_verification_context",
    "FinalSemanticReviewContextV1",
    "FinalSemanticReviewOutputV1",
    "FinalSemanticReviewValidator",
    "FINAL_SEMANTIC_REVIEW_VERSION",
    "QuestionClosureContextV1",
    "QuestionClosureReviewV1",
    "QUESTION_CLOSURE_REVIEW_VERSION",
    "build_final_review_context",
]
