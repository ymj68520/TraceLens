"""Deterministic claim grounding (P5A §31-§43, §65).

The frozen boundary this module implements:

    Grounding != Semantic Verification
    grounded != proven

Grounding answers ONLY: is every evidence ref well-formed, real, part of
this task, actually exposed to the agent that produced the proposal, and of
an allowed Evidence type?  It never answers whether the Evidence is
SUFFICIENT — that is the P5B SemanticVerifierAgent's job, and the support
statuses (sufficient / partially_sufficient / insufficient / contradicted /
indeterminate) do not exist in P5A.

The validator is deterministic and calls no model.  There are no confidence
scores, proof probabilities or pseudo-precision numbers anywhere.

Visibility authority (§33): ``allowed_evidence_ids`` is rebuilt from durable
provenance — the delegation's frozen ContextPack initial refs (durable since
v13 via agent_delegation_evidence_scopes) plus successful ToolObservation
refs.  "Evidence exists" never implies "the agent saw it".
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Awaitable, Callable, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict

from .agent_claims import ProposedClaimV1, ProposalNormalizer
from .agent_runtime import AgentRuntimeRepository, canonical_state_json
from .agent_specialist_result import AssertionClass
from ..evidence.exceptions import InvalidEvidenceKeyError
from ..evidence.keys import parse_evidence_key

GROUNDING_RESULT_VERSION = "grounding-result:v1"
GROUNDING_VALIDATOR_VERSION = "deterministic-grounding-validator:v1"
GROUNDING_POLICY_VERSION = 1

# §38 EvidenceRefPolicy: exactly the key types the repo's frozen evidence
# grammar supports today (evidence/keys.py). Never pre-register future types.
ALLOWED_EVIDENCE_TYPES = frozenset({"file", "cluster"})


class GroundingStatus(str, Enum):
    """§31/§36 deterministic baseline. grounded ≠ semantic sufficiency."""

    GROUNDED = "grounded"
    PARTIALLY_GROUNDED = "partially_grounded"
    UNGROUNDED = "ungrounded"
    INVALID = "invalid"


class EvidenceRefPolicy:
    """§38: which parsed evidence types may back a claim proposal."""

    allowed_types: frozenset

    def __init__(self, allowed_types: Optional[frozenset] = None):
        self.allowed_types = frozenset(
            allowed_types or ALLOWED_EVIDENCE_TYPES
        )

    def policy_hash(self) -> str:
        return hashlib.sha256(
            canonical_state_json(
                {"allowed_types": sorted(self.allowed_types)}
            ).encode("utf-8")
        ).hexdigest()


class GroundingResultV1(BaseModel):
    """Immutable grounding verdict for one proposal (version-frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    grounding_version: str = GROUNDING_RESULT_VERSION

    grounding_id: str
    task_id: str
    investigation_id: str
    proposal_id: str
    grounding_policy_version: int = GROUNDING_POLICY_VERSION

    input_assertion_class: AssertionClass
    effective_assertion_class: AssertionClass

    status: GroundingStatus

    valid_evidence_refs: tuple[str, ...] = ()
    invalid_evidence_refs: tuple[str, ...] = ()
    invisible_evidence_refs: tuple[str, ...] = ()
    disallowed_ref_types: tuple[str, ...] = ()

    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    validator_version: str = GROUNDING_VALIDATOR_VERSION
    input_hash: str

    def to_row(self) -> dict:
        return {
            "grounding_id": self.grounding_id,
            "proposal_id": self.proposal_id,
            "grounding_policy_version": self.grounding_policy_version,
            "input_assertion_class": self.input_assertion_class.value,
            "effective_assertion_class": self.effective_assertion_class.value,
            "status": self.status.value,
            "valid_evidence_refs": tuple(self.valid_evidence_refs),
            "invalid_evidence_refs": tuple(self.invalid_evidence_refs),
            "invisible_evidence_refs": tuple(self.invisible_evidence_refs),
            "disallowed_ref_types": tuple(self.disallowed_ref_types),
            "warnings": tuple(self.warnings),
            "limitations": tuple(self.limitations),
            "validator_version": self.validator_version,
            "input_hash": self.input_hash,
        }

    @classmethod
    def from_row(cls, row: Mapping) -> "GroundingResultV1":
        return cls(
            task_id=row["task_id"],
            investigation_id=row["investigation_id"],
            grounding_id=row["grounding_id"],
            proposal_id=row["proposal_id"],
            grounding_policy_version=row["grounding_policy_version"],
            input_assertion_class=AssertionClass(
                row["input_assertion_class"]
            ),
            effective_assertion_class=AssertionClass(
                row["effective_assertion_class"]
            ),
            status=GroundingStatus(row["status"]),
            valid_evidence_refs=tuple(row["valid_evidence_refs"]),
            invalid_evidence_refs=tuple(row["invalid_evidence_refs"]),
            invisible_evidence_refs=tuple(row["invisible_evidence_refs"]),
            disallowed_ref_types=tuple(row["disallowed_ref_types"]),
            warnings=tuple(row["warnings"]),
            limitations=tuple(row["limitations"]),
            validator_version=row["validator_version"],
            input_hash=row["input_hash"],
        )


EvidenceResolverFunc = Callable[[str, str], Awaitable[Optional[Mapping]]]


def _deterministic_id(prefix: str, payload: dict) -> str:
    digest = hashlib.sha256(
        canonical_state_json(payload).encode("utf-8")
    ).hexdigest()
    return f"{prefix}:{digest[:24]}"


class DeterministicGroundingValidator:
    """§32 ten-step deterministic gate. Not an agent; no model calls."""

    VERSION = GROUNDING_VALIDATOR_VERSION

    def __init__(self, *, policy: Optional[EvidenceRefPolicy] = None):
        self._policy = policy or EvidenceRefPolicy()

    async def validate(
        self,
        proposal: ProposedClaimV1,
        *,
        task_id: str,
        investigation_id: str,
        allowed_evidence_ids: frozenset,
        evidence_resolver: EvidenceResolverFunc,
        grounding_policy_version: int = GROUNDING_POLICY_VERSION,
    ) -> GroundingResultV1:
        # 1. contract
        warnings: list[str] = []
        limitations: list[str] = []
        contract_ok = (
            proposal.proposal_id
            and proposal.text.strip()
            and isinstance(proposal.assertion_class, AssertionClass)
        )
        # 3. task boundary (provenance/integrity, fail closed per §37)
        task_mismatch = (
            proposal.task_id != task_id
            or proposal.investigation_id != investigation_id
        )

        valid: list[str] = []
        invalid: list[str] = []
        invisible: list[str] = []
        disallowed: list[str] = []
        integrity_violation = task_mismatch

        if not contract_ok:
            integrity_violation = True
        for ref in proposal.evidence_refs:
            # 2. syntax (also covers §34/§56 masquerading: ToolObservation
            # ids, Graph node ids, LLM text and analysis refs all fail the
            # frozen evidence grammar and land here -> invalid)
            try:
                parsed = parse_evidence_key(ref)
            except InvalidEvidenceKeyError:
                invalid.append(ref)
                integrity_violation = True
                continue
            # 7. allowed source type per EvidenceRefPolicy
            if parsed.evidence_type not in self._policy.allowed_types:
                disallowed.append(ref)
                integrity_violation = True
                continue
            # 4. resolution inside this task
            try:
                resolved = await evidence_resolver(task_id, ref)
            except Exception:
                resolved = None
            if resolved is None:
                invalid.append(ref)  # well-formed but not real
                continue
            # 5. visibility from durable provenance. A ref that resolves but
            # was never exposed to the producing agent is NOT a valid
            # grounding ref (§56: well-formed same-task invisible ->
            # ungrounded, never silently grounded). Supports FQER scoped and canonical matching.
            is_visible = (
                ref in allowed_evidence_ids
                or parsed.canonical_key in allowed_evidence_ids
                or (parsed.source_scope_id and parsed.canonical_key.split(":", 1)[1] in allowed_evidence_ids)
            )
            if not is_visible:
                invisible.append(ref)
                continue
            valid.append(ref)

        valid = sorted(set(valid))
        invalid = sorted(set(invalid))
        invisible = sorted(set(invisible))
        disallowed = sorted(set(disallowed))

        # 9. FACT evidence requirement (defensive duplicate of §30; the
        # normalizer already downgrades empty-refs FACTs upstream)
        effective_class = proposal.assertion_class
        if (
            effective_class is AssertionClass.FACT
            and not valid
        ):
            effective_class = AssertionClass.HYPOTHESIS
            warnings.append("GROUNDING_FACT_DOWNGRADED_NO_VALID_EVIDENCE")

        # 10. status computation (§36/§37)
        if integrity_violation:
            status = GroundingStatus.INVALID
        elif not valid:
            status = GroundingStatus.UNGROUNDED
        elif invalid or invisible or disallowed:
            status = GroundingStatus.PARTIALLY_GROUNDED
        else:
            status = GroundingStatus.GROUNDED
        if status is GroundingStatus.PARTIALLY_GROUNDED:
            limitations.append(
                "grounding is partial: some refs did not validate"
            )
        limitations.append(
            "grounded means refs are legal, real, task-scoped and were "
            "exposed to the producing agent - NOT that they prove the claim"
        )

        input_payload = {
            "proposal_input_hash": proposal.input_hash,
            "proposal_id": proposal.proposal_id,
            "allowed_evidence_ids": sorted(allowed_evidence_ids),
            "validator_version": self.VERSION,
            "grounding_policy_version": grounding_policy_version,
        }
        input_hash = hashlib.sha256(
            canonical_state_json(input_payload).encode("utf-8")
        ).hexdigest()
        grounding_id = _deterministic_id(
            "grnd",
            {
                "proposal_id": proposal.proposal_id,
                "validator_version": self.VERSION,
                "grounding_policy_version": grounding_policy_version,
                "input_hash": input_hash,
            },
        )
        return GroundingResultV1(
            grounding_id=grounding_id,
            task_id=task_id,
            investigation_id=investigation_id,
            proposal_id=proposal.proposal_id,
            grounding_policy_version=grounding_policy_version,
            input_assertion_class=proposal.assertion_class,
            effective_assertion_class=effective_class,
            status=status,
            valid_evidence_refs=tuple(valid),
            invalid_evidence_refs=tuple(invalid),
            invisible_evidence_refs=tuple(invisible),
            disallowed_ref_types=tuple(disallowed),
            warnings=tuple(warnings),
            limitations=tuple(limitations),
            validator_version=self.VERSION,
            input_hash=input_hash,
        )


class GroundingPipelineReport(BaseModel):
    """Deterministic outcome of one explicit pipeline run."""

    model_config = ConfigDict(frozen=True)

    proposals_recorded: int = 0
    proposals_replayed: int = 0
    grounding_by_status: dict = {}
    bundles_recorded: int = 0
    limitations: tuple[str, ...] = ()


async def process_specialist_proposals(
    runtime: AgentRuntimeRepository,
    *,
    task_id: str,
    investigation_id: str,
    results: Sequence,
    evidence_resolver: EvidenceResolverFunc,
    visibility_provider: Optional[Callable[[object], frozenset]] = None,
    normalizer: Optional[ProposalNormalizer] = None,
    validator: Optional[DeterministicGroundingValidator] = None,
    bundle_builder=None,
    extra_proposals: Sequence[ProposedClaimV1] = (),
    extra_proposal_provenance: Optional[Sequence[frozenset]] = None,
    run_id: Optional[str] = None,
) -> GroundingPipelineReport:
    """§65 explicit P5A pipeline entry — never called by the P4 loop.

    Persists claim proposals + grounding results (+ optional support
    bundles). P5A persistence never touches Working State; the P4B
    Supervisor sees proposal refs later through normal integration.

    ``visibility_provider(result)`` may supply a delegation's
    ``allowed_evidence_ids``; by default it is rebuilt from durable
    provenance (agent_delegation_evidence_scopes + successful
    ToolObservations).  ``extra_proposals`` accepts deterministic
    correlation-derived claims; each carries its own explicit provenance
    set (``extra_proposal_provenance``, §33 union rule)."""
    normalizer = normalizer or ProposalNormalizer()
    validator = validator or DeterministicGroundingValidator()
    from .agent_claims import build_proposals_from_specialist_result
    from .agent_tools.visibility import reconstruct_allowed_evidence_ids

    grounding_by_status = {
        status.value: 0 for status in GroundingStatus
    }
    limitations: list[str] = []

    proposals: list[ProposedClaimV1] = []
    provenance: list[frozenset] = []

    for result in results:
        built = build_proposals_from_specialist_result(
            result, task_id=task_id, investigation_id=investigation_id,
            normalizer=normalizer,
        )
        limitations.extend(built.limitations)
        allowed = None
        if visibility_provider is not None:
            allowed = frozenset(visibility_provider(result))
        else:
            scope = runtime.get_delegation_evidence_scope(result.delegation_id)
            initial_refs = scope.initial_evidence_refs if scope else ()
            observations = [
                observation
                for observation in runtime.list_tool_observations(
                    investigation_id
                )
                if observation.delegation_id == result.delegation_id
            ]
            allowed = reconstruct_allowed_evidence_ids(
                initial_refs, observations,
                delegation_id=result.delegation_id,
            )
        for proposal in built.proposals:
            proposals.append(proposal)
            provenance.append(allowed)

    for index, proposal in enumerate(extra_proposals):
        proposals.append(proposal)
        if extra_proposal_provenance is not None and index < len(
            extra_proposal_provenance
        ):
            provenance.append(
                frozenset(extra_proposal_provenance[index])
            )
        else:
            # fail closed: an extra proposal without an explicit provenance
            # set is grounded against exactly its own evidence refs
            provenance.append(frozenset(proposal.evidence_refs))

    if not proposals:
        return GroundingPipelineReport(
            grounding_by_status=grounding_by_status,
            limitations=tuple(limitations),
        )

    outcome = runtime.record_claim_proposals(
        investigation_id,
        [proposal.to_row() for proposal in proposals],
        run_id=run_id,
        append_trajectory=True,
    )
    proposals_recorded = outcome["inserted_count"]
    proposals_replayed = outcome["duplicate_count"]
    bundles_recorded = 0

    for proposal, allowed in zip(proposals, provenance):
        grounding = await validator.validate(
            proposal,
            task_id=task_id,
            investigation_id=investigation_id,
            allowed_evidence_ids=frozenset(allowed),
            evidence_resolver=evidence_resolver,
        )
        runtime.record_grounded_proposal(
            investigation_id,
            proposal_row=proposal.to_row(),
            grounding_row=grounding.to_row(),
            run_id=run_id,
        )
        grounding_by_status[grounding.status.value] += 1

        if bundle_builder is not None:
            bundle = await bundle_builder.build(
                grounding, proposal,
                task_id=task_id, investigation_id=investigation_id,
                evidence_resolver=evidence_resolver,
            )
            runtime.record_support_bundles(
                investigation_id, [bundle.to_row()], run_id=run_id
            )
            bundles_recorded += 1

    return GroundingPipelineReport(
        proposals_recorded=proposals_recorded,
        proposals_replayed=proposals_replayed,
        grounding_by_status=grounding_by_status,
        bundles_recorded=bundles_recorded,
        limitations=tuple(limitations),
    )


__all__ = [
    "ALLOWED_EVIDENCE_TYPES",
    "GROUNDING_POLICY_VERSION",
    "GROUNDING_RESULT_VERSION",
    "GROUNDING_VALIDATOR_VERSION",
    "DeterministicGroundingValidator",
    "EvidenceRefPolicy",
    "GroundingPipelineReport",
    "GroundingResultV1",
    "GroundingStatus",
    "process_specialist_proposals",
]
