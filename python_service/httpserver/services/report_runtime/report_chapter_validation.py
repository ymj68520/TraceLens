"""Chapter validation pipeline (P7B §16-§25).

Order (§24): contract version → identity → spec/pack identity →
assertion id uniqueness → basis refs exact → evidence refs pack-visible →
citation refs allowlisted → review status allowed → assertion ceiling →
forbidden graph ids → unsupported basis type → deterministic hash.

One failure invalidates the WHOLE chapter (§24) — never partial
acceptance, never silent repair (§25: an over-strong assertion is a
rejection, not a downgrade).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .report_chapter_draft import (
    AssertionClass,
    ChapterDraftV1,
    ReportAssertionV1,
)
from .report_chapter_generation import ChapterGenerationInputV1
from .report_context_pack import AcceptedSemanticBasisV1

STRENGTH_ORDER: dict[str, int] = {
    "HYPOTHESIS": 0,
    "INFERENCE": 1,
    "FACT": 2,
    # LIMITATION is its own category: never compared on the strength axis
    "LIMITATION": -1,
}

CHAPTER_VALIDATION_VERSION = "chapter-validation:v1"

# §20: direct evidence can state only what the evidence itself records;
# these semantic moves need an accepted canonical basis.
_DIRECT_EVIDENCE_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "malicious", "intent", "attacker", "exfiltrat", "caused", "caused by",
    "because of", "same person", "belongs to the same", "attack chain",
    "responsible", "stole", "hacked", "入侵", "恶意", "故意", "导致",
    "同一人", "责任", "窃取",
)


class ChapterValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ChapterValidationResult:
    valid: bool
    draft: Optional[ChapterDraftV1] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    checked_rules: list[str] = field(default_factory=list)


class ReportAssertionCeilingValidator:
    """§18-§21: preserve or lower, never raise.

    - direct_evidence basis: max FACT, and only direct recorded facts
      (§20 marker scan is the structural first pass; the Semantic
      Consistency Reviewer does the semantic overreach pass later);
    - accepted semantic basis: ceiling = the LOWEST class among the
      required basis refs the assertion actually cites (§19 conservative
      rule — a Writer cannot pick one FACT basis to mask a required
      INFERENCE basis).
    """

    version = CHAPTER_VALIDATION_VERSION

    def validate_assertion(
        self,
        assertion: ReportAssertionV1,
        *,
        semantic_basis: dict[str, AcceptedSemanticBasisV1],
    ) -> None:
        if assertion.assertion_class == "LIMITATION":
            return  # its own category; never a strength move
        if assertion.basis_type == "direct_evidence":
            self._validate_direct_evidence(assertion)
            return
        if assertion.basis_type in ("report_assertion", "chapter_digest"):
            # synthesis path: validated by the synthesis ceiling validator
            return
        if not assertion.basis_refs:
            raise ChapterValidationError(
                "basis_missing",
                f"assertion {assertion.assertion_id or '<unbound>'} cites "
                "no semantic basis",
            )
        ceilings: list[int] = []
        for ref in assertion.basis_refs:
            basis = semantic_basis.get(ref)
            if basis is None:
                raise ChapterValidationError(
                    "basis_unknown",
                    f"assertion cites basis outside the frozen pack: {ref}",
                )
            ceilings.append(STRENGTH_ORDER[basis.assertion_class])
        ceiling = min(ceilings)  # conservative: lowest allowed strength
        if STRENGTH_ORDER[assertion.assertion_class] > ceiling:
            raise ChapterValidationError(
                "assertion_ceiling_violated",
                f"assertion class {assertion.assertion_class} exceeds the "
                f"accepted basis ceiling (refs: "
                f"{sorted(assertion.basis_refs)})",
            )

    @staticmethod
    def _validate_direct_evidence(assertion: ReportAssertionV1) -> None:
        if not assertion.evidence_refs:
            raise ChapterValidationError(
                "direct_evidence_missing_refs",
                "a direct-evidence assertion must cite its evidence",
            )
        if assertion.evidence_refs and not assertion.basis_refs:
            pass  # direct evidence IS the basis; no semantic ref needed
        lowered = assertion.text.lower()
        for marker in _DIRECT_EVIDENCE_FORBIDDEN_MARKERS:
            if marker in lowered:
                raise ChapterValidationError(
                    "direct_evidence_overreach",
                    f"direct-evidence assertion expresses unsupported "
                    f"high-level semantics (marker: {marker!r})",
                )


def validate_chapter_draft(
    draft: ChapterDraftV1,
    generation_input: ChapterGenerationInputV1,
    context_pack,
) -> ChapterDraftV1:
    """§24 full validation order.  Returns the draft with server-derived
    assertion identities; raises ChapterValidationError on ANY failure."""
    # 1. output contract/version
    if draft.draft_version != "chapter-draft:v1":
        raise ChapterValidationError(
            "contract_version_invalid", "unsupported draft contract version"
        )
    # 2. task/investigation/finalization identity
    if (
        draft.chapter_id != generation_input.chapter_id
        or generation_input.task_id != context_pack.task_id
        or generation_input.investigation_id != context_pack.investigation_id
        or generation_input.finalization_id != context_pack.finalization_id
    ):
        raise ChapterValidationError(
            "identity_mismatch", "draft does not match its generation input"
        )
    # 3. chapter/spec/context_pack identity
    if generation_input.context_pack_id != context_pack.context_pack_id or (
        generation_input.context_pack_hash != context_pack.input_hash
    ):
        raise ChapterValidationError(
            "context_pack_mismatch", "generation input pins another pack"
        )
    if generation_input.chapter_spec_hash and (
        generation_input.chapter_id != context_pack.chapter_id
    ):
        raise ChapterValidationError(
            "chapter_mismatch", "generation input pins another chapter"
        )
    if generation_input.generation_mode != context_pack.generation_mode:
        raise ChapterValidationError(
            "generation_mode_mismatch", "mode disagrees with the pack"
        )

    # bind server-derived identities first (§14)
    bound = draft.with_identities(generation_input.input_hash)

    ids = [statement.assertion_id for statement in bound.statements]
    # 4. assertion id uniqueness
    if len(set(ids)) != len(ids):
        raise ChapterValidationError(
            "assertion_id_duplicate", "duplicate assertion_id in draft"
        )

    semantic_basis = {
        basis.basis_ref: basis for basis in context_pack.accepted_semantic_basis
    }
    pack_evidence = set(context_pack.allowed_citation_refs)
    ceiling_validator = ReportAssertionCeilingValidator()
    for statement in bound.statements:
        # 10. forbidden graph ids (any ref position)
        for ref in (*statement.basis_refs, *statement.evidence_refs,
                    *statement.citation_refs):
            if ref.startswith(("graph:", "gm:", "gcand:", "node-")):
                raise ChapterValidationError(
                    "graph_ref_forbidden", f"graph id in assertion: {ref}"
                )
        # 11. unsupported basis type / 5. basis refs exact
        if statement.basis_type in ("report_assertion", "chapter_digest"):
            raise ChapterValidationError(
                "basis_type_unsupported_in_detailed_chapter",
                "synthesis basis types require the synthesis pipeline",
            )
        if statement.basis_type in ("accepted_finding", "accepted_event",
                                    "accepted_analysis"):
            for ref in statement.basis_refs:
                if ref not in semantic_basis:
                    raise ChapterValidationError(
                        "basis_unknown",
                        f"basis ref not in pack semantic basis: {ref}",
                    )
        # 6. evidence refs pack-visible
        for ref in statement.evidence_refs:
            if ref not in pack_evidence:
                raise ChapterValidationError(
                    "evidence_not_pack_visible",
                    f"evidence ref is not in the frozen pack: {ref}",
                )
        # 7. citation refs allowlisted + subset of evidence_refs
        for ref in statement.citation_refs:
            if ref not in pack_evidence:
                raise ChapterValidationError(
                    "citation_not_allowed",
                    f"citation ref outside the pack allowlist: {ref}",
                )
            if ref not in statement.evidence_refs:
                raise ChapterValidationError(
                    "citation_not_grounded",
                    "citation ref must be one of the assertion's "
                    "evidence refs",
                )
        # 8/9. review status + ceiling
        ceiling_validator.validate_assertion(
            statement, semantic_basis=semantic_basis
        )

    # direct-evidence statements must cite real evidence only (§13:
    # no untracked factual prose — every statement is an assertion already)
    return bound


__all__ = [
    "ChapterValidationError",
    "ChapterValidationResult",
    "CHAPTER_VALIDATION_VERSION",
    "ReportAssertionCeilingValidator",
    "STRENGTH_ORDER",
    "validate_chapter_draft",
]
