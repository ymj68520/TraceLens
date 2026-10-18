"""EvidenceSupportBundle builder (P5A §39-§41, §58).

The bundle is the frozen input artifact for the P5B SemanticVerifierAgent:
bounded, provenance-preserving hydration of the Evidence a grounded claim
references.  The builder performs NO semantic judgement — ``sufficient``,
``partially_sufficient``, ``insufficient``, ``contradicted`` and
``indeterminate`` support statuses do not exist here (P5B only), and no
confidence / probability numbers are ever emitted.

Hydration is digest-first and bounded by policy (§41): items carry resolved
Evidence metadata (digest fields), never whole files and never raw event
payloads; a bounded excerpt is included only when the resolver itself
supplies one, and it is truncated to ``max_excerpt_chars``.  All bounds are
provisional runtime defaults, P8-calibratable.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Mapping, Optional

from pydantic import BaseModel, ConfigDict

from .agent_claims import ProposedClaimV1
from .agent_grounding import GroundingResultV1, GroundingStatus

EVIDENCE_SUPPORT_BUNDLE_VERSION = "evidence-support-bundle:v1"

DEFAULT_MAX_ITEMS = 32
DEFAULT_MAX_EXCERPT_CHARS = 512


class HydrationPolicy(BaseModel):
    """§41: digest-first by default; bounds are P8-calibratable."""

    model_config = ConfigDict(frozen=True)

    name: str = "digest_first_bounded"
    max_items: int = DEFAULT_MAX_ITEMS
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS

    def policy_hash(self) -> str:
        from .agent_runtime import state_hash_of

        return state_hash_of(self.model_dump())


class EvidenceSupportItem(BaseModel):
    """One bounded Evidence item: digest + optional bounded excerpt."""

    model_config = ConfigDict(frozen=True)

    evidence_ref: str
    digest: dict  # resolved metadata: hashes, size, times, path, counts
    excerpt: Optional[str] = None  # bounded; resolver-supplied only
    provenance: dict = {}  # source db binding / resolution facts


class EvidenceSupportBundleV1(BaseModel):
    """Frozen P5B input: what evidence supports one proposal (§39)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_version: str = EVIDENCE_SUPPORT_BUNDLE_VERSION

    bundle_id: str
    task_id: str
    investigation_id: str

    proposal_id: str
    grounding_id: str
    grounding_status: GroundingStatus
    effective_assertion_class: object  # AssertionClass (avoids import cycle)

    claim_text: str

    evidence_items: tuple[EvidenceSupportItem, ...] = ()

    relationship_refs: tuple[str, ...] = ()
    temporal_scope: Optional[dict] = None

    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    source_question_ids: tuple[str, ...] = ()

    hydration_policy: str
    input_hash: str

    def to_row(self) -> dict:
        from .agent_runtime import canonical_state_json

        assertion = self.effective_assertion_class
        assertion_value = getattr(assertion, "value", assertion)
        return {
            "bundle_id": self.bundle_id,
            "proposal_id": self.proposal_id,
            "grounding_id": self.grounding_id,
            "grounding_status": self.grounding_status.value,
            "effective_assertion_class": assertion_value,
            "claim_text": self.claim_text,
            "evidence_items": [
                {
                    "evidence_ref": item.evidence_ref,
                    "digest": dict(item.digest),
                    "excerpt": item.excerpt,
                    "provenance": dict(item.provenance),
                }
                for item in self.evidence_items
            ],
            "relationship_refs": tuple(self.relationship_refs),
            "temporal_scope": self.temporal_scope,
            "limitations": tuple(self.limitations),
            "warnings": tuple(self.warnings),
            "source_question_ids": tuple(self.source_question_ids),
            "hydration_policy": self.hydration_policy,
            "input_hash": self.input_hash,
        }


class SupportBundleBuilder:
    """Bounded, deterministic bundle construction over a grounding result."""

    def __init__(self, *, policy: Optional[HydrationPolicy] = None):
        self._policy = policy or HydrationPolicy()

    @property
    def policy(self) -> HydrationPolicy:
        return self._policy

    async def build(
        self,
        grounding: GroundingResultV1,
        proposal: ProposedClaimV1,
        *,
        task_id: str,
        investigation_id: str,
        evidence_resolver: Callable[[str, str], Awaitable[Optional[Mapping]]],
    ) -> EvidenceSupportBundleV1:
        """§58: only refs the grounding validated are included; items carry
        digest provenance; same inputs -> same bundle id."""
        items: list[EvidenceSupportItem] = []
        for ref in grounding.valid_evidence_refs:
            if len(items) >= self._policy.max_items:
                break
            metadata = None
            try:
                metadata = await evidence_resolver(task_id, ref)
            except Exception:
                metadata = None
            digest: dict = {}
            provenance: dict = {"resolved": metadata is not None}
            excerpt: Optional[str] = None
            if metadata:
                for field in (
                    "evidence_key", "normalized_path", "source_hash",
                    "md5", "source_size", "source_mtime", "cluster_start",
                    "cluster_end", "event_count", "representative_timestamp",
                    "source_db",
                ):
                    if metadata.get(field) is not None:
                        digest[field] = metadata[field]
                raw_excerpt = metadata.get("excerpt")
                if raw_excerpt:
                    excerpt = str(raw_excerpt)[
                        : self._policy.max_excerpt_chars
                    ]
            items.append(
                EvidenceSupportItem(
                    evidence_ref=ref,
                    digest=digest,
                    excerpt=excerpt,
                    provenance=provenance,
                )
            )

        from .agent_runtime import state_hash_of

        input_payload = {
            "bundle_version": EVIDENCE_SUPPORT_BUNDLE_VERSION,
            "grounding_id": grounding.grounding_id,
            "proposal_input_hash": proposal.input_hash,
            "hydration_policy": self._policy.model_dump(),
            "items": [
                {
                    "evidence_ref": item.evidence_ref,
                    "digest": item.digest,
                    "excerpt": item.excerpt,
                }
                for item in items
            ],
        }
        input_hash = state_hash_of(input_payload)
        from .agent_runtime import canonical_state_json
        import hashlib

        bundle_id = "bundle:" + hashlib.sha256(
            canonical_state_json(input_payload).encode("utf-8")
        ).hexdigest()[:24]
        return EvidenceSupportBundleV1(
            bundle_id=bundle_id,
            task_id=task_id,
            investigation_id=investigation_id,
            proposal_id=proposal.proposal_id,
            grounding_id=grounding.grounding_id,
            grounding_status=grounding.status,
            effective_assertion_class=grounding.effective_assertion_class,
            claim_text=proposal.text,
            evidence_items=tuple(items),
            relationship_refs=tuple(proposal.relationship_refs),
            temporal_scope=proposal.temporal_scope,
            limitations=tuple(grounding.limitations),
            warnings=tuple(grounding.warnings),
            source_question_ids=tuple(proposal.source_question_ids),
            hydration_policy=self._policy.name,
            input_hash=input_hash,
        )


__all__ = [
    "DEFAULT_MAX_EXCERPT_CHARS",
    "DEFAULT_MAX_ITEMS",
    "EVIDENCE_SUPPORT_BUNDLE_VERSION",
    "EvidenceSupportBundleV1",
    "EvidenceSupportItem",
    "HydrationPolicy",
    "SupportBundleBuilder",
]
