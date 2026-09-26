"""Synthesis: SynthesisContextPackV1 + Executive Summary / Conclusion
(P7B §38-§43).

Synthesis NEVER re-reads the case: its frozen input is digests + ledger +
question dispositions + major limitations only (§39).  Basis refs cite
validated report assertions / chapter digests; citations stay real
Evidence from the ledger's citation universe (§40).  The synthesis
ceiling (§41): an assertion is at most as strong as the LOWEST required
basis class — a summary can never strengthen its chapters.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

from .canonical import sha256_hex
from .report_chapter_draft import AssertionClass, BasisType
from .report_ledger import (
    ChapterDigestV1,
    ReportAssertionLedgerV1,
    STRENGTH,
)

SYNTHESIS_CONTEXT_VERSION = "synthesis-context:v1"
SYNTHESIS_CONTEXT_ID_PREFIX = "rsyn:"

SYNTHESIS_POLICY_VERSION = "report-synthesis-policy:starter:v1"


class SynthesisContextPackV1(BaseModel):
    """Frozen synthesis input (§39)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_version: str = SYNTHESIS_CONTEXT_VERSION

    context_id: str
    task_id: str
    investigation_id: str
    finalization_id: str

    outline_id: str
    outline_revision: int

    chapter_digests: tuple[ChapterDigestV1, ...] = ()
    ledger_id: str
    ledger_hash: str

    allowed_ledger_assertion_refs: tuple[str, ...] = ()
    allowed_citation_refs: tuple[str, ...] = ()

    required_question_dispositions: dict[str, str] = {}
    major_limitations: tuple[str, ...] = ()

    synthesis_policy_version: str = SYNTHESIS_POLICY_VERSION

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("context_version", SYNTHESIS_CONTEXT_VERSION)
        data["chapter_digests"] = sorted(
            (
                ChapterDigestV1.model_validate(item)
                for item in data.get("chapter_digests", ())
            ),
            key=lambda item: item.chapter_id,
        )
        data["allowed_ledger_assertion_refs"] = tuple(
            sorted(set(data.get("allowed_ledger_assertion_refs", ())))
        )
        data["allowed_citation_refs"] = tuple(
            sorted(set(data.get("allowed_citation_refs", ())))
        )
        data["major_limitations"] = tuple(
            sorted(set(data.get("major_limitations", ())))
        )
        data["required_question_dispositions"] = dict(
            sorted(data.get("required_question_dispositions", {}).items())
        )
        if not data.get("created_at"):
            from datetime import datetime, timezone

            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("context_id", "created_at", "input_hash")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        data["context_id"] = SYNTHESIS_CONTEXT_ID_PREFIX + digest[:24]
        return data


def build_synthesis_context_pack(
    ledger: ReportAssertionLedgerV1,
    digests: list[ChapterDigestV1],
    *,
    question_dispositions: dict[str, str],
) -> SynthesisContextPackV1:
    """§39: allowed citations derive from ledger Evidence refs ONLY."""
    citation_universe: set[str] = set()
    for assertion in ledger.assertions:
        citation_universe.update(assertion.citation_refs)
    return SynthesisContextPackV1(
        task_id=ledger.task_id,
        investigation_id=ledger.investigation_id,
        finalization_id=ledger.finalization_id,
        outline_id=ledger.outline_id,
        outline_revision=ledger.outline_revision,
        chapter_digests=tuple(digests),
        ledger_id=ledger.ledger_id,
        ledger_hash=ledger.input_hash,
        allowed_ledger_assertion_refs=tuple(
            assertion.assertion_id for assertion in ledger.assertions
        ),
        allowed_citation_refs=tuple(sorted(citation_universe)),
        required_question_dispositions=dict(question_dispositions),
        major_limitations=ledger.major_limitations,
    )


class SynthesisCeilingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_synthesis_assertion(
    assertion: ReportAssertionV1,
    *,
    ledger: ReportAssertionLedgerV1,
    synthesis_context: SynthesisContextPackV1,
    ledger_classes: dict[str, str],
) -> None:
    """§40-§42 structural gates for one synthesis assertion.

    - basis_refs must be validated ledger assertions (or digest refs);
    - citation_refs ⊆ evidence_refs ⊆ ledger citation universe;
    - ceiling = LOWEST required basis class (§41);
    - no new unsupported high-level conclusion (structural pass: the
      semantic reviewer performs the semantic overreach pass).
    """
    if assertion.assertion_class == "LIMITATION":
        return
    if not assertion.basis_refs:
        raise SynthesisCeilingError(
            "basis_missing", "synthesis assertion cites no basis"
        )
    for ref in assertion.basis_refs:
        if ref not in set(synthesis_context.allowed_ledger_assertion_refs):
            raise SynthesisCeilingError(
                "basis_unknown",
                f"synthesis basis is not a validated ledger assertion: {ref}",
            )
    for ref in assertion.evidence_refs:
        if ref not in set(synthesis_context.allowed_citation_refs):
            raise SynthesisCeilingError(
                "evidence_not_in_ledger",
                f"synthesis evidence ref is outside the ledger universe: {ref}",
            )
    for ref in assertion.citation_refs:
        if ref not in set(assertion.evidence_refs):
            raise SynthesisCeilingError(
                "citation_not_grounded",
                "synthesis citation must be one of its evidence refs",
            )
    if assertion.assertion_class in STRENGTH:
        classes = [
            ledger_classes.get(ref)
            for ref in assertion.basis_refs
            if ledger_classes.get(ref) in STRENGTH
        ]
        if classes:
            ceiling = min(STRENGTH[cls] for cls in classes)
            if STRENGTH[assertion.assertion_class] > ceiling:
                raise SynthesisCeilingError(
                    "synthesis_ceiling_violated",
                    f"summary class {assertion.assertion_class} exceeds the "
                    f"lowest required basis class "
                    f"({min(classes, key=lambda c: STRENGTH[c])})",
                )


class ReportConsistencyPolicy(BaseModel):
    """§45 starter policy: versioned, never silently ignore issues."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: str = "report-consistency-policy:starter:v1"
    semantic_review_required_for_evidence_narrative: bool = True
    semantic_review_required_for_synthesis: bool = True
    deterministic_only_sufficient: bool = True
    reviewer_unavailable_behavior: Literal[
        "block_publication", "record_and_continue"
    ] = "block_publication"


__all__ = [
    "build_synthesis_context_pack",
    "ReportConsistencyPolicy",
    "SYNTHESIS_CONTEXT_VERSION",
    "SynthesisCeilingError",
    "SynthesisContextPackV1",
    "SYNTHESIS_POLICY_VERSION",
    "validate_synthesis_assertion",
]
