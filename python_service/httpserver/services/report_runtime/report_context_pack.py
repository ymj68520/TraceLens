"""FrozenReportContextPackV1 + deterministic citation allowlist (P7A
§39-§47) — the core P7A artifact.

Once frozen a pack is never updated (§45): any outline / spec / retrieval
/ evidence-set / hydration change produces a new ``context_pack_id``.  The
pack is the ONLY thing the future P7B Chapter Writer sees (§87): tools=0,
no DB, no Graph.  ``allowed_citation_refs`` is deterministic and contains
only real Evidence refs actually present in the pack (§40/§41) — a Writer
that cites case evidence the pack never exposed fails validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import sha256_hex
from .report_hydration import EvidenceRole, HydrationDepth

CONTEXT_PACK_VERSION = "report-context-pack:v1"
CONTEXT_PACK_ID_PREFIX = "rpack:"

ASSERTION_CLASSES = ("FACT", "INFERENCE", "HYPOTHESIS")


class ReportEvidenceItemV1(BaseModel):
    """One Evidence item inside a frozen pack (§32).

    Carries digests and bounded structured projections — never an entire
    binary or unbounded raw file.  ``direct_fact_only`` marks the §43/§44
    assertion ceiling: raw evidence supports only its directly recorded
    facts; actor attribution / intent / causality must come from an
    accepted semantic basis.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_ref: str
    role: EvidenceRole
    source_kind: str = "file"
    evidence_digest: str
    structured_fields: dict = Field(default_factory=dict)
    bounded_excerpt: Optional[str] = None
    hydration_depth: HydrationDepth = "digest"
    source_scope: str = ""
    temporal_ref: Optional[int] = None
    independence_key: str = ""
    retrieval_provenance: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    direct_fact_only: bool = True

    @model_validator(mode="after")
    def _validate_bounds(self):
        if self.bounded_excerpt is not None and len(self.bounded_excerpt) > 2000:
            raise ValueError("bounded_excerpt exceeds 2000 chars")
        return self


class AcceptedSemanticBasisV1(BaseModel):
    """One accepted canonical semantic object inside the pack (§42).

    The pack never restates or upgrades the assertion; P7B reads
    ``assertion_class`` as the Writer's maximum strength for this basis.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    basis_ref: str
    basis_type: str  # finding / event / analysis
    assertion_class: str
    text_digest: str
    evidence_refs: tuple[str, ...] = ()
    accepted_version: str = ""
    provenance_hash: str = ""

    @model_validator(mode="after")
    def _validate_ceiling(self):
        if self.assertion_class not in ASSERTION_CLASSES:
            raise ValueError(
                f"unknown assertion_class: {self.assertion_class}"
            )
        return self


class GraphNavigationProvenanceV1(BaseModel):
    """§26: graph navigation is retrieval provenance only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    graph_ref: str
    materialization_id: Optional[str] = None
    hydrated_evidence_refs: tuple[str, ...] = ()
    trust_class: str = "provenance_bound"


class FrozenReportContextPackV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pack_version: str = CONTEXT_PACK_VERSION

    context_pack_id: str

    task_id: str
    investigation_id: str
    finalization_id: str
    finalization_record_hash: str

    outline_id: str
    outline_revision: int
    chapter_id: str
    chapter_spec_hash: str

    retrieval_plan_id: str
    retrieval_plan_hash: str

    generation_mode: str
    context_stage: str = "ready"

    anchor_evidence: tuple[ReportEvidenceItemV1, ...] = ()
    supporting_evidence: tuple[ReportEvidenceItemV1, ...] = ()
    retrieved_context_evidence: tuple[ReportEvidenceItemV1, ...] = ()

    accepted_semantic_basis: tuple[AcceptedSemanticBasisV1, ...] = ()
    graph_navigation_provenance: tuple[GraphNavigationProvenanceV1, ...] = ()

    required_question_dispositions: dict[str, str] = Field(
        default_factory=dict
    )
    coverage_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    allowed_citation_refs: tuple[str, ...] = ()

    hydration_policy_version: str
    retrieval_policy_version: str
    dedup_policy_version: str
    budget_policy_version: str

    created_at: str
    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("pack_version", CONTEXT_PACK_VERSION)
        data.setdefault("context_stage", "ready")
        data.setdefault("retrieved_context_evidence", ())
        data["supporting_evidence"] = data.get("supporting_evidence", ())
        data["anchor_evidence"] = data.get("anchor_evidence", ())
        for field in (
            "anchor_evidence",
            "supporting_evidence",
            "retrieved_context_evidence",
        ):
            items = sorted(
                (
                    ReportEvidenceItemV1.model_validate(item)
                    for item in data.get(field, ())
                ),
                key=lambda item: item.evidence_ref,
            )
            data[field] = items
        # §40/§41: the allowlist is ALWAYS server-derived from the pack
        # contents; any caller-supplied value is discarded, never merged.
        data["allowed_citation_refs"] = build_citation_allowlist(
            _EvidenceView(
                anchor_evidence=tuple(data["anchor_evidence"]),
                supporting_evidence=tuple(data["supporting_evidence"]),
                retrieved_context_evidence=tuple(
                    data["retrieved_context_evidence"]
                ),
            )
        )
        data["accepted_semantic_basis"] = sorted(
            (
                AcceptedSemanticBasisV1.model_validate(item)
                for item in data.setdefault("accepted_semantic_basis", ())
            ),
            key=lambda item: item.basis_ref,
        )
        data["graph_navigation_provenance"] = sorted(
            (
                GraphNavigationProvenanceV1.model_validate(item)
                for item in data.setdefault(
                    "graph_navigation_provenance", ()
                )
            ),
            key=lambda item: item.graph_ref,
        )
        data["coverage_refs"] = tuple(
            sorted(set(data.setdefault("coverage_refs", ())))
        )
        data["limitations"] = tuple(
            sorted(set(data.setdefault("limitations", ())))
        )
        data["required_question_dispositions"] = dict(
            sorted(data.setdefault("required_question_dispositions", {}).items())
        )
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("context_pack_id", "created_at", "input_hash")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        data["context_pack_id"] = CONTEXT_PACK_ID_PREFIX + digest[:24]
        return data


class CitationAllowlistError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _EvidenceView:
    """Structural view of the three evidence lists (pre-model derivation)."""

    def __init__(self, *, anchor_evidence, supporting_evidence,
                 retrieved_context_evidence):
        self.anchor_evidence = anchor_evidence
        self.supporting_evidence = supporting_evidence
        self.retrieved_context_evidence = retrieved_context_evidence


def build_citation_allowlist(
    pack: "FrozenReportContextPackV1 | _EvidenceView",
) -> tuple[str, ...]:
    """§40/§41: deterministic allowlist = every real Evidence ref that is
    actually present in the frozen pack and legal for citation.

    Graph ids, semantic ids (finding/event/analysis), and any ref not in
    the pack never enter.  A Writer citing case evidence the pack never
    exposed fails validation.
    """
    refs: set[str] = set()
    for field_name in (
        "anchor_evidence",
        "supporting_evidence",
        "retrieved_context_evidence",
    ):
        for item in getattr(pack, field_name):
            if item.evidence_ref.startswith(
                ("graph:", "gm:", "gcand:", "node-")
            ):
                raise CitationAllowlistError(
                    "graph_ref_in_pack",
                    f"graph id reached the pack as evidence: "
                    f"{item.evidence_ref}",
                )
            refs.add(item.evidence_ref)
    return tuple(sorted(refs))


def validate_citation_allowlist(
    pack: FrozenReportContextPackV1,
) -> None:
    """The persisted allowlist must exactly equal the derived one."""
    expected = build_citation_allowlist(pack)
    if tuple(pack.allowed_citation_refs) != expected:
        raise CitationAllowlistError(
            "allowlist_mismatch",
            "allowed_citation_refs does not match the pack contents",
        )


def semantic_basis_refs_of(
    pack: FrozenReportContextPackV1,
) -> tuple[str, ...]:
    """Semantic basis ids (never citations) for the P7B assertion ceiling."""
    return tuple(sorted(basis.basis_ref for basis in pack.accepted_semantic_basis))


__all__ = [
    "AcceptedSemanticBasisV1",
    "CONTEXT_PACK_VERSION",
    "CitationAllowlistError",
    "FrozenReportContextPackV1",
    "GraphNavigationProvenanceV1",
    "ReportEvidenceItemV1",
    "build_citation_allowlist",
    "semantic_basis_refs_of",
    "validate_citation_allowlist",
]
