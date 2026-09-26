"""Publication adapter for validated agent-aware reports (P7B §51-§57).

Adapter B (per §52 investigation): the R2 executor is coupled to its own
LLM invocation, so P7B reuses the *publication primitives* —
``GenerationReportWriter.publish`` (atomic os.replace),
``complete_generation_publication`` (version allocation + completion in
one transaction), ``read_narrative_version_strict`` (Viewer) — and adds a
thin prevalidated adapter.  NO second LLM call, NO semantic rewrite
(§53): the published sections are the validated assertions rendered
deterministically.

The manifest carries P7 provenance via ``GenerationReportManifestV3``
(§54): a strict-schema additive extension (old v1/v2 readers keep working
through their own models; the strict narrative reader accepts the new
``schema_version``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .report_chapter_draft import ChapterDraftV1

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import sha256_hex
from .report_ledger import ChapterDigestV1, ReportAssertionLedgerV1, run_deterministic_consistency
from ..forensic_report.models import CitationManifestEntry, StructuredReportSection

MANIFEST_V3_SCHEMA_VERSION = "3.0"
REPORT_KIND_AGENT_AWARE = "agent_aware_generation"


class ManifestProvenanceV3(BaseModel):
    """P7 runtime provenance bound into the published manifest (§54)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_runtime: str = "agent-aware:v1"

    finalization_id: str
    finalization_record_hash: str

    outline_id: str
    outline_revision: int

    chapter_ids: tuple[str, ...] = ()
    chapter_spec_hashes: tuple[str, ...] = ()
    context_pack_ids: tuple[str, ...] = ()
    context_pack_hashes: tuple[str, ...] = ()
    chapter_generation_ids: tuple[str, ...] = ()
    chapter_output_hashes: tuple[str, ...] = ()
    chapter_digest_ids: tuple[str, ...] = ()
    chapter_digest_hashes: tuple[str, ...] = ()

    assertion_ledger_id: str
    assertion_ledger_hash: str
    consistency_review_ids: tuple[str, ...] = ()
    consistency_review_hashes: tuple[str, ...] = ()


class AgentAwareCitationV3(BaseModel):
    """§55: P7 citations carry REAL evidence identity only — analysis_id/
    claim_id stay null; semantic authorization lives in the ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    citation_id: str
    evidence_key: str
    analysis_id: None = None
    claim_id: None = None


class GenerationReportManifestV3(BaseModel):
    """V3 manifest for agent-aware reports (§54)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MANIFEST_V3_SCHEMA_VERSION
    report_kind: str = REPORT_KIND_AGENT_AWARE
    report_id: str
    scope_type: str = "task"
    scope_id: str
    task_id: str
    generation_id: str
    title: str
    prompt_version: str
    input_hash: str
    model: str
    generated_at: str

    sections: tuple[StructuredReportSection, ...] = ()
    citations: tuple[CitationManifestEntry, ...] = ()

    provenance: ManifestProvenanceV3

    @model_validator(mode="after")
    def _validate_citations(self):
        keys = [c.citation_id for c in self.citations]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate citation_id in manifest")
        for citation in self.citations:
            if citation.analysis_id is not None or (
                citation.claim_id is not None
            ):
                raise ValueError(
                    "agent-aware citations carry evidence identity only"
                )
        return self


def render_sections_from_drafts(
    drafts: list[ChapterDraftV1],
    *,
    chapter_titles: dict[str, str],
) -> list[StructuredReportSection]:
    """§13/§53: deterministic rendering of validated assertions into
    strict R2 sections; citation IDs are global across all chapters."""
    sections: list[StructuredReportSection] = []
    citation_counter = 0
    citation_ids_by_ref: dict[str, str] = {}
    for draft in drafts:
        lines: list[str] = []
        section_citation_ids: list[str] = []
        for statement in draft.statements:
            marker = {
                "FACT": "【事实】",
                "INFERENCE": "【推断】",
                "HYPOTHESIS": "【假设】",
                "LIMITATION": "【局限】",
            }[statement.assertion_class]
            citations = ""
            if statement.citation_refs:
                rendered: list[str] = []
                for ref in statement.citation_refs:
                    citation_id = citation_ids_by_ref.get(ref)
                    if citation_id is None:
                        citation_counter += 1
                        citation_id = f"c{citation_counter:03d}"
                        citation_ids_by_ref[ref] = citation_id
                    rendered.append(citation_id)
                    if citation_id not in section_citation_ids:
                        section_citation_ids.append(citation_id)
                citations = "（证据：" + "、".join(rendered) + "）"
            lines.append(f"- {marker}{statement.text}{citations}")
        for limitation in draft.chapter_limitations:
            lines.append(f"- 【局限】{limitation}")
        sections.append(
            StructuredReportSection(
                heading=chapter_titles.get(draft.chapter_id, draft.chapter_id),
                content="\n".join(lines),
                citation_ids=tuple(section_citation_ids),
            )
        )
    return sections


def build_citations_from_drafts(
    drafts: list[ChapterDraftV1],
) -> tuple[CitationManifestEntry, ...]:
    """Deterministic citation manifest from validated assertions only."""
    citations: list[CitationManifestEntry] = []
    counter = 0
    seen: set[str] = set()
    for draft in drafts:
        for statement in draft.statements:
            for ref in statement.citation_refs:
                if ref in seen:
                    continue
                seen.add(ref)
                counter += 1
                citations.append(
                    CitationManifestEntry(
                        citation_id=f"c{counter:03d}",
                        evidence_key=ref,
                    )
                )
    return tuple(citations)


class PrevalidatedReportPublicationAdapter:
    """§52 option B: publish VALIDATED chapter drafts through the R2
    publication primitives without a second LLM."""

    version = "prevalidated-publication-adapter:v1"

    def __init__(self, *, repository: Any, writer: Any):
        # repository: R2 ReportRepository (version allocation/completion)
        # writer: R2 GenerationReportWriter (atomic snapshot publish)
        self._repository = repository
        self._writer = writer

    def publish(
        self,
        *,
        task_id: str,
        title: str,
        drafts: list[ChapterDraftV1],
        chapter_titles: dict[str, str],
        ledger: ReportAssertionLedgerV1,
        digests: list[ChapterDigestV1],
        review_ids: tuple[str, ...],
        review_hashes: tuple[str, ...],
        review_status: str = "pass",
        evidence_digests: dict[str, str] | None = None,
        chapter_spec_hashes: tuple[str, ...] = (),
        context_pack_ids: tuple[str, ...] = (),
        context_pack_hashes: tuple[str, ...] = (),
        model: str,
        prompt_version: str,
    ) -> tuple[str, str]:
        """Publish and return (report_id, manifest_path_relative).

        The R2 publication contract is preserved: atomic file publish
        first, then version allocation + generation completion inside the
        repository transaction; any failure leaves no Viewer-visible
        version (§57).
        """
        from .report_chapter_generation import (
            CHAPTER_OUTPUT_CONTRACT_VERSION,
        )

        if review_status != "pass":
            raise ValueError("report publication requires a passing consistency review")
        if not drafts or not digests or not review_ids or not review_hashes:
            raise ValueError("publication requires validated chapters, digests and review")
        if len(drafts) != len(digests):
            raise ValueError("draft/digest count mismatch")
        if tuple(draft.chapter_id for draft in drafts) != tuple(digest.chapter_id for digest in digests):
            raise ValueError("draft/digest chapter identity mismatch")
        evidence_digests = evidence_digests or {}
        consistency_issues = run_deterministic_consistency(
            ledger,
            digests=digests,
            evidence_digests=evidence_digests,
            finalization_id=ledger.finalization_id,
            outline_id=ledger.outline_id,
            outline_revision=ledger.outline_revision,
        )
        if consistency_issues:
            raise ValueError("deterministic consistency failed before publication")
        sections = render_sections_from_drafts(
            drafts, chapter_titles=chapter_titles
        )
        citations = build_citations_from_drafts(drafts)
        output_hashes = tuple(draft.draft_hash() for draft in drafts)
        provenance = ManifestProvenanceV3(
            finalization_id=ledger.finalization_id,
            finalization_record_hash=ledger.finalization_record_hash,
            outline_id=ledger.outline_id,
            outline_revision=ledger.outline_revision,
            chapter_ids=tuple(draft.chapter_id for draft in drafts),
            chapter_spec_hashes=chapter_spec_hashes,
            context_pack_ids=context_pack_ids,
            context_pack_hashes=context_pack_hashes,
            chapter_generation_ids=ledger.chapter_generation_ids,
            chapter_output_hashes=output_hashes,
            chapter_digest_ids=tuple(digest.digest_id for digest in digests),
            chapter_digest_hashes=tuple(
                digest.digest_hash for digest in digests
            ),
            assertion_ledger_id=ledger.ledger_id,
            assertion_ledger_hash=ledger.input_hash,
            consistency_review_ids=review_ids,
            consistency_review_hashes=review_hashes,
        )
        input_hash = sha256_hex(
            {
                "schema_version": MANIFEST_V3_SCHEMA_VERSION,
                "report_kind": REPORT_KIND_AGENT_AWARE,
                "task_id": task_id,
                "title": title,
                "prompt_version": prompt_version,
                "output_contract": CHAPTER_OUTPUT_CONTRACT_VERSION,
                "chapter_output_hashes": list(output_hashes),
                "ledger_id": ledger.ledger_id,
                "ledger_hash": ledger.input_hash,
                "review_hashes": list(review_hashes),
            }
        )
        report_id = _new_report_id()
        manifest = GenerationReportManifestV3(
            report_id=report_id,
            scope_id=task_id,
            task_id=task_id,
            generation_id=ledger.ledger_id,
            title=title,
            prompt_version=prompt_version,
            input_hash=input_hash,
            model=model or "agent_aware_pipeline",
            generated_at=_now_iso(),
            sections=tuple(sections),
            citations=citations,
            provenance=provenance,
        )
        # The R2 writer type-hints the v1 manifest but only serializes
        # via model_dump(mode="json"); the V3 manifest is duck-type
        # compatible (frozen pydantic model with the same surface).
        final_dir = self._writer.publish(
            task_id=task_id,
            report_id=report_id,
            manifest=manifest,  # type: ignore[arg-type]
        )
        relative_manifest = str(
            (final_dir / "manifest.json").relative_to(self._writer.report_root)
        )
        # Adapter B: the manifest is already atomically present; this
        # existing R2 repository primitive now allocates the immutable
        # report_versions row in its own transaction. No second LLM and no
        # semantic rewrite occur here.
        self._repository.complete_prevalidated_publication(
            task_id=task_id,
            report_id=report_id,
            title=title,
            manifest_path=relative_manifest,
            model=model or "agent_aware_pipeline",
            input_hash=input_hash,
        )
        return report_id, relative_manifest


def _new_report_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "AgentAwareCitationV3",
    "GenerationReportManifestV3",
    "ManifestProvenanceV3",
    "MANIFEST_V3_SCHEMA_VERSION",
    "PrevalidatedReportPublicationAdapter",
    "REPORT_KIND_AGENT_AWARE",
    "build_citations_from_drafts",
    "render_sections_from_drafts",
]
