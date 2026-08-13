"""Grounding validation for Secondary Analysis Claims (Phase C5a).

Pure functions — no DB access, no LLM. The Repository calls these inside the
persist_claims transaction so callers can never bypass the Trust Boundary.

Key invariants (G1-G14, see plan):
  G2  allowed_evidence_ids derived ONLY from the frozen envelope
  G5  invalid refs stripped + recorded in warnings (never persisted)
  G7  FACT without valid refs → downgraded to HYPOTHESIS
  G8  grounded = refs valid (NOT semantically sufficient)
  G11 Repository re-derives allowed inside the write transaction
"""

from __future__ import annotations

from typing import Sequence, Union

from .models import (
    AnalysisGroundingStatus,
    AnalysisInputEnvelopeV1,
    AnalysisInputEnvelopeV2,
    ClaimCandidate,
    ClaimGroundingStatus,
    ClaimType,
    ValidatedClaim,
)


def derive_allowed_evidence_ids(
    envelope: Union[AnalysisInputEnvelopeV1, AnalysisInputEnvelopeV2],
) -> frozenset[str]:
    """Derive the set of canonical evidence_keys this analysis version is
    allowed to reference in Claims (G2-G4).

    Primary evidence (G3) and only the related evidence frozen in the envelope
    (G4) are included. No Associations, no re-resolve, no client-supplied IDs.
    """
    ids: set[str] = {envelope.evidence_snapshot["evidence_key"]}
    if isinstance(envelope, AnalysisInputEnvelopeV2):
        ids.update(entry.evidence_key for entry in envelope.related_evidence)
    else:
        ids.update(envelope.related_evidence)
    return frozenset(ids)


class GroundingValidator:
    """Validates untrusted ClaimCandidates against an allowed evidence set.

    Usage::

        allowed = derive_allowed_evidence_ids(envelope)
        validated = GroundingValidator(allowed).validate(candidates)

    The validator uses **exact canonical-ID matching** — it does NOT
    canonicalize or interpret LLM-supplied ref strings. ``file:\\\\case`` and
    ``file:/case`` are treated as distinct IDs.
    """

    def __init__(self, allowed_evidence_ids: frozenset[str]):
        self._allowed = allowed_evidence_ids

    def validate(self, candidates: Sequence[ClaimCandidate]) -> list[ValidatedClaim]:
        return [self._validate_one(c) for c in candidates]

    def _validate_one(self, candidate: ClaimCandidate) -> ValidatedClaim:
        # De-duplicate refs preserving first-occurrence order (stable output).
        unique_refs = tuple(dict.fromkeys(candidate.evidence_refs))

        valid_refs = tuple(r for r in unique_refs if r in self._allowed)
        invalid_refs = tuple(r for r in unique_refs if r not in self._allowed)

        warnings: dict = {}
        if invalid_refs:
            warnings["invalid_evidence_refs"] = list(invalid_refs)

        claim_type = candidate.claim_type

        # G7: FACT without any valid evidence ref → downgrade to HYPOTHESIS.
        if claim_type == ClaimType.FACT and not valid_refs:
            claim_type = ClaimType.HYPOTHESIS
            if not candidate.evidence_refs:
                warnings["fact_without_evidence_refs"] = True
            else:
                warnings["fact_all_refs_invalid"] = True

        # Grounding (G8: grounded = refs are valid, not semantically proven).
        if not valid_refs:
            grounding = ClaimGroundingStatus.UNGROUNDED
        elif invalid_refs:
            grounding = ClaimGroundingStatus.PARTIALLY_GROUNDED
        else:
            grounding = ClaimGroundingStatus.GROUNDED

        return ValidatedClaim(
            claim_type=claim_type,
            claim_text=candidate.claim_text,
            grounding_status=grounding,
            evidence_refs=valid_refs,
            warnings=warnings,
        )


def compute_analysis_grounding(
    claims: Sequence[ValidatedClaim],
) -> AnalysisGroundingStatus:
    """Aggregate per-claim grounding statuses into an analysis-level status.

    - 0 claims or all claims grounded → ``valid``
    - all claims ungrounded → ``invalid``
    - otherwise → ``partially_grounded``
    """
    if not claims:
        return AnalysisGroundingStatus.VALID
    statuses = [c.grounding_status for c in claims]
    if all(s == ClaimGroundingStatus.GROUNDED for s in statuses):
        return AnalysisGroundingStatus.VALID
    if all(s == ClaimGroundingStatus.UNGROUNDED for s in statuses):
        return AnalysisGroundingStatus.INVALID
    return AnalysisGroundingStatus.PARTIALLY_GROUNDED
