"""ProposedClaim foundation (P5A §23-§30, §45-§46).

A ``ProposedClaimV1`` is a versioned, immutable, non-canonical claim
proposal.  It never touches canonical Claim/Finding state — canonical
acceptance is P5B+ and stays behind the P2 StateTransitionPolicy.

Sources (§24): SpecialistResultV1.claim_candidates and deterministic
CorrelationCandidates that safely map to claim text.  Working-State prose,
Analyst Notes, Supervisor summaries and ToolObservation summaries are NEVER
claim sources.

The ProposalNormalizer is deterministic-first (§27): it canonicalizes
whitespace and set-like refs, detects compound claims, and splits ONLY on
unambiguous independent-statement separators where no clause needs a
semantic rewrite.  Everything else is kept compound with a warning — the
normalizer never rewrites meaning, never upgrades an assertion class and
never invents Evidence (§28).

Frozen requirement (§30): ``FACT`` with no evidence is deterministically
downgraded to ``HYPOTHESIS`` with a warning, never preserved as FACT.
"""

from __future__ import annotations

import hashlib
import re
from typing import Mapping, Optional

from pydantic import BaseModel, ConfigDict, model_validator

from .agent_correlation import CorrelationCandidateV1
from .agent_runtime import canonical_state_json
from .agent_specialist_result import AssertionClass, SpecialistResultV1

PROPOSED_CLAIM_VERSION = "proposed-claim:v1"
PROPOSAL_NORMALIZER_VERSION = "proposal-normalizer:v1"


class ProposedClaimV1(BaseModel):
    """One durable claim proposal (version-frozen, idempotent by id)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_version: str = PROPOSED_CLAIM_VERSION

    task_id: str
    investigation_id: str
    proposal_id: str

    text: str
    assertion_class: AssertionClass

    evidence_refs: tuple[str, ...] = ()
    source_question_ids: tuple[str, ...] = ()
    source_delegation_id: Optional[str] = None
    source_result_hash: Optional[str] = None
    source_candidate_id: Optional[str] = None
    relationship_refs: tuple[str, ...] = ()

    temporal_scope: Optional[dict] = None
    limitations: tuple[str, ...] = ()
    normalization_warnings: tuple[str, ...] = ()

    normalizer_version: str = PROPOSAL_NORMALIZER_VERSION
    input_hash: str

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_and_derive(cls, data):
        """Single derivation authority: canonical form, proposal_id and
        input_hash are always recomputed from the semantic fields."""
        if not isinstance(data, dict):
            return data
        text = _canonicalize_text(str(data.get("text") or ""))
        evidence_refs = tuple(sorted({str(ref) for ref in
                                      (data.get("evidence_refs") or ())
                                      if ref}))
        question_ids = tuple(sorted({str(ref) for ref in
                                     (data.get("source_question_ids") or ())
                                     if ref}))
        relationship_refs = tuple(sorted(
            {str(ref) for ref in (data.get("relationship_refs") or ()) if ref}
        ))
        limitations = tuple(sorted(
            {str(item) for item in (data.get("limitations") or ()) if item}
        ))
        warnings = tuple(
            str(item) for item in (data.get("normalization_warnings") or ())
        )
        payload = {
            "task_id": data.get("task_id"),
            "investigation_id": data.get("investigation_id"),
            "source_delegation_id": data.get("source_delegation_id"),
            "source_result_hash": data.get("source_result_hash"),
            "source_candidate_id": data.get("source_candidate_id"),
            "text": text,
            "assertion_class": str(data.get("assertion_class")),
            "evidence_refs": list(evidence_refs),
            "source_question_ids": list(question_ids),
            "relationship_refs": list(relationship_refs),
            "temporal_scope": data.get("temporal_scope"),
            "normalizer_version": data.get("normalizer_version")
            or PROPOSAL_NORMALIZER_VERSION,
        }
        input_hash = hashlib.sha256(
            canonical_state_json(payload).encode("utf-8")
        ).hexdigest()
        data["text"] = text
        data["evidence_refs"] = evidence_refs
        data["source_question_ids"] = question_ids
        data["relationship_refs"] = relationship_refs
        data["limitations"] = limitations
        data["normalization_warnings"] = warnings
        data["normalizer_version"] = payload["normalizer_version"]
        data["input_hash"] = input_hash
        id_payload = dict(payload, input_hash=input_hash)
        data["proposal_id"] = "prop:" + hashlib.sha256(
            canonical_state_json(id_payload).encode("utf-8")
        ).hexdigest()[:24]
        return data

    def to_row(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "source_question_ids": tuple(self.source_question_ids),
            "source_delegation_id": self.source_delegation_id,
            "source_result_hash": self.source_result_hash,
            "source_candidate_id": self.source_candidate_id,
            "text": self.text,
            "assertion_class": self.assertion_class.value,
            "evidence_refs": tuple(self.evidence_refs),
            "relationship_refs": tuple(self.relationship_refs),
            "temporal_scope": self.temporal_scope,
            "limitations": tuple(self.limitations),
            "normalization_warnings": tuple(self.normalization_warnings),
            "normalizer_version": self.normalizer_version,
            "input_hash": self.input_hash,
        }

    @classmethod
    def from_row(cls, row: Mapping) -> "ProposedClaimV1":
        return cls(
            task_id=row["task_id"],
            investigation_id=row["investigation_id"],
            proposal_id=row["proposal_id"],
            text=row["text"],
            assertion_class=AssertionClass(row["assertion_class"]),
            evidence_refs=tuple(row["evidence_refs"]),
            source_question_ids=tuple(row["source_question_ids"]),
            source_delegation_id=row["source_delegation_id"],
            source_result_hash=row["source_result_hash"],
            source_candidate_id=row["source_candidate_id"],
            relationship_refs=tuple(row["relationship_refs"]),
            temporal_scope=row.get("temporal_scope"),
            limitations=tuple(row["limitations"]),
            normalization_warnings=tuple(row["normalization_warnings"]),
            normalizer_version=row["normalizer_version"],
            input_hash=row["input_hash"],
        )


def _canonicalize_text(text: str) -> str:
    """Whitespace canonicalization only — never a semantic rewrite."""
    return re.sub(r"\s+", " ", text).strip()


class ProposalBuildReport(BaseModel):
    """Deterministic proposal-building outcome over one source."""

    model_config = ConfigDict(frozen=True)

    proposals: tuple[ProposedClaimV1, ...] = ()
    limitations: tuple[str, ...] = ()

    def sorted(self) -> "ProposalBuildReport":
        return ProposalBuildReport(
            proposals=tuple(
                sorted(self.proposals, key=lambda item: item.proposal_id)
            ),
            limitations=tuple(sorted(self.limitations)),
        )


class ProposalNormalizer:
    """Deterministic claim proposal normalization (§27-§30)."""

    VERSION = PROPOSAL_NORMALIZER_VERSION

    # Unambiguous independent-statement separators: splitting here never
    # requires a semantic rewrite (each clause is already self-contained).
    _SAFE_SPLIT_RE = re.compile(r"\s*(?:;|；|。|\|\||\n+)\s*")
    _MIN_CLAUSE_LENGTH = 3
    # Conjunction-style compounds may bind actor/action semantics across
    # clauses; splitting them IS a semantic rewrite, so they are retained.
    _UNSAFE_MARKERS = (
        " and then ",
        " and subsequently ",
        " and ",
        "，然后",
        "，随后",
        "并且",
        "然后",
        "随后",
    )

    def normalize_claim_candidate(
        self,
        candidate,
        *,
        task_id: str,
        investigation_id: str,
        delegation_id: Optional[str],
        result_hash: Optional[str],
    ) -> tuple[tuple[ProposedClaimV1, ...], tuple[str, ...]]:
        """Return (proposals, warnings). Never invents Evidence, never
        upgrades the assertion class."""
        warnings: list[str] = []
        text = _canonicalize_text(candidate.text)
        assertion = candidate.assertion_class
        evidence_refs = tuple(candidate.evidence_refs)
        limitations = list(candidate.limitations)

        if assertion is AssertionClass.FACT and not evidence_refs:
            # §30 frozen requirement — deterministic fail-safe downgrade.
            assertion = AssertionClass.HYPOTHESIS
            warnings.append("FACT_DOWNGRADED_NO_EVIDENCE")

        lowered = f" {text.lower()} "
        compound_unsafe = any(
            marker in lowered for marker in self._UNSAFE_MARKERS
        )
        clauses = [
            clause.strip()
            for clause in self._SAFE_SPLIT_RE.split(text)
            if len(clause.strip()) >= self._MIN_CLAUSE_LENGTH
        ]
        if compound_unsafe:
            # §27: a conjunction compound cannot be split without a semantic
            # rewrite — keep it compound, with a warning, unchanged.
            warnings.append("COMPOUND_CLAIM_RETAINED_UNSAFE_SPLIT")
            proposals = (self._build(
                task_id=task_id,
                investigation_id=investigation_id,
                delegation_id=delegation_id,
                result_hash=result_hash,
                candidate_id=candidate.candidate_id,
                text=text,
                assertion=assertion,
                evidence_refs=evidence_refs,
                limitations=limitations,
                warnings=warnings,
            ),)
            return proposals, tuple(warnings)

        if len(clauses) >= 2:
            # explicit independent statements: safe to keep as separate
            # proposals; evidence is NOT re-attributed per clause
            warnings.append("COMPOUND_SPLIT_EVIDENCE_NOT_REATTRIBUTED")
            built = []
            for clause in clauses:
                built.append(self._build(
                    task_id=task_id,
                    investigation_id=investigation_id,
                    delegation_id=delegation_id,
                    result_hash=result_hash,
                    candidate_id=candidate.candidate_id,
                    text=clause,
                    assertion=assertion,
                    evidence_refs=evidence_refs,
                    limitations=limitations
                    + ["compound split: evidence refs inherited in full"],
                    warnings=warnings,
                ))
            return tuple(built), tuple(warnings)

        proposals = (self._build(
            task_id=task_id,
            investigation_id=investigation_id,
            delegation_id=delegation_id,
            result_hash=result_hash,
            candidate_id=candidate.candidate_id,
            text=text,
            assertion=assertion,
            evidence_refs=evidence_refs,
            limitations=limitations,
            warnings=warnings,
        ),)
        return proposals, tuple(warnings)

    @staticmethod
    def _build(
        *,
        task_id: str,
        investigation_id: str,
        delegation_id: Optional[str],
        result_hash: Optional[str],
        candidate_id: str,
        text: str,
        assertion: AssertionClass,
        evidence_refs: tuple[str, ...],
        limitations: list[str],
        warnings: tuple[str, ...],
    ) -> ProposedClaimV1:
        return ProposedClaimV1(
            task_id=task_id,
            investigation_id=investigation_id,
            proposal_id="",  # derived
            text=text,
            assertion_class=assertion,
            evidence_refs=evidence_refs,
            source_delegation_id=delegation_id,
            source_result_hash=result_hash,
            source_candidate_id=candidate_id,
            limitations=limitations,
            normalization_warnings=warnings,
            input_hash="",  # derived
        )


def build_proposals_from_specialist_result(
    result: SpecialistResultV1,
    *,
    task_id: str,
    investigation_id: str,
    normalizer: Optional[ProposalNormalizer] = None,
) -> ProposalBuildReport:
    """§24: claim_candidates are the specialist source of proposals."""
    normalizer = normalizer or ProposalNormalizer()
    proposals: list[ProposedClaimV1] = []
    limitations: list[str] = []
    for candidate in result.claim_candidates:
        if not _canonicalize_text(candidate.text):
            limitations.append(
                f"claim candidate {candidate.candidate_id!r} has empty text"
            )
            continue
        built, _warnings = normalizer.normalize_claim_candidate(
            candidate,
            task_id=task_id,
            investigation_id=investigation_id,
            delegation_id=result.delegation_id,
            result_hash=result.result_hash(),
        )
        proposals.extend(built)
    return ProposalBuildReport(
        proposals=tuple(proposals), limitations=tuple(limitations)
    ).sorted()


_CORRELATION_TEXT = {
    "same_content_hash": (
        "The evidence items {refs} reference content with the same "
        "{algorithm} digest."
    ),
    "normalized_identifier_match": (
        "The evidence items {refs} reference the same normalized "
        "{entity_type} value {value!r}."
    ),
    "composite_account_match": (
        "The same realm-qualified account {value!r} is recorded across the "
        "evidence items {refs}."
    ),
    "url_domain_structure": (
        "The URL recorded in {subject_evidence} resolves under the domain "
        "recorded in {object_evidence}."
    ),
    "structured_co_occurrence": (
        "The evidence item {refs0} records both the {subject_type} "
        "{subject_value!r} and the {object_type} {object_value!r}."
    ),
    "temporal_overlap": (
        "The evidence items {refs} fall within the same bounded temporal "
        "window ({window_seconds}s)."
    ),
}


def claim_from_correlation_candidate(
    candidate: CorrelationCandidateV1,
    *,
    task_id: str,
    investigation_id: str,
    occurrences: Mapping[str, "object"],
) -> Optional[ProposedClaimV1]:
    """§46 safe mapping: a correlation candidate becomes at most the claim
    its derivation literally supports — never the stronger story.

    Returns None when the referenced occurrences are not supplied (fail
    closed); the caller decides how to surface the gap."""
    subject = occurrences.get(candidate.subject_ref)
    object_ = occurrences.get(candidate.object_ref)
    if subject is None or object_ is None:
        return None
    template = _CORRELATION_TEXT.get(candidate.relation_family)
    if template is None:
        return None
    refs = tuple(sorted(set(candidate.evidence_refs)))
    fmt = {
        "refs": " and ".join(f"{ref!r}" for ref in refs)
        or "unknown evidence",
        "refs0": refs[0] if refs else "unknown evidence",
        "algorithm": subject.namespace.split(":", 1)[-1],
        "entity_type": (subject.entity_type or "").replace("_", " "),
        "value": subject.normalized_value,
        "subject_type": subject.entity_type,
        "subject_value": subject.normalized_value,
        "object_type": object_.entity_type,
        "object_value": object_.normalized_value,
        "subject_evidence": subject.evidence_ref,
        "object_evidence": object_.evidence_ref,
        "window_seconds": (
            candidate.temporal_relation.window_seconds
            if candidate.temporal_relation else 0
        ),
    }
    text = _canonicalize_text(template.format(**fmt))
    assertion = {
        "structured_co_occurrence": AssertionClass.FACT,
        "temporal_overlap": AssertionClass.HYPOTHESIS,
    }.get(candidate.relation_family, AssertionClass.INFERENCE)
    temporal_scope = None
    if candidate.temporal_relation is not None:
        temporal_scope = candidate.temporal_relation.model_dump()
    return ProposedClaimV1(
        task_id=task_id,
        investigation_id=investigation_id,
        proposal_id="",  # derived
        text=text,
        assertion_class=assertion,
        evidence_refs=refs,
        source_candidate_id=candidate.correlation_id,
        relationship_refs=(candidate.correlation_id,),
        temporal_scope=temporal_scope,
        limitations=tuple(candidate.limitations),
        normalization_warnings=(),
        input_hash="",  # derived
    )


__all__ = [
    "PROPOSED_CLAIM_VERSION",
    "PROPOSAL_NORMALIZER_VERSION",
    "ProposalBuildReport",
    "ProposalNormalizer",
    "ProposedClaimV1",
    "build_proposals_from_specialist_result",
    "claim_from_correlation_candidate",
]
