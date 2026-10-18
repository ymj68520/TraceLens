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

Freeze follow-up (§3-§9): publication reloads a ``TrustedPublicationInput``
from the durable report-runtime store and fails closed on any identity/
hash/review mismatch — caller-supplied payloads never reach the manifest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .report_chapter_draft import ChapterDraftV1

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import sha256_hex
from .report_ledger import (
    ChapterDigestV1,
    ReportAssertionLedgerV1,
    run_deterministic_consistency,
)
from .report_chapter_draft import ChapterDraftV1
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


class PublicationTrustError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class TrustedPublicationInput(BaseModel):
    """§3 (P7B freeze follow-up): publication-side reload of the exact
    durable artifacts.

    Every field is re-read from the durable store by
    :func:`build_trusted_publication_input` and hash-verified; the caller
    may only supply IDs / expected hashes.  The published manifest and the
    deterministic consistency re-run are built from THIS snapshot, never
    from caller-built objects.  The reload also carries the exact durable
    admission so callers (and tests) can cross-check task identity
    without re-reading the store.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    admission: Any  # durable ReportRuntimeAdmissionV1 row (re-loaded)

    admission_id: str
    finalization_id: str
    finalization_record_hash: str

    outline_id: str
    outline_revision: int

    drafts: list[ChapterDraftV1]
    chapter_spec_hashes: tuple[str, ...]
    context_pack_ids: tuple[str, ...]
    context_pack_hashes: tuple[str, ...]

    ledger: ReportAssertionLedgerV1
    digests: list[ChapterDigestV1]

    review_ids: tuple[str, ...]
    review_hashes: tuple[str, ...]


def build_trusted_publication_input(
    repository: Any,
    *,
    admission_id: str,
    expected_generation_ids: tuple[str, ...],
    ledger_id: str,
    review_ids: tuple[str, ...],
) -> TrustedPublicationInput:
    """Rebuild the publication snapshot from durable rows (fail closed).

    Loads the exact admission, the exact completed chapter generations for
    the admission's outline revision, their validated outputs / digests,
    the exact persisted ledger and the exact persisted consistency
    reviews, and cross-checks every identity/hash binding.  Any mismatch,
    missing row, or non-pass review raises :class:`PublicationTrustError`
    and leaves no Viewer-visible version.
    """
    import json as _json

    def _reject(code: str, message: str) -> None:
        raise PublicationTrustError(code, message)

    admission = repository.get_report_runtime_admission(admission_id)
    if admission is None:
        _reject(
            "admission_missing",
            f"report runtime admission not persisted: {admission_id}",
        )
    completed = repository.list_completed_chapter_generations(
        task_id=admission.task_id,
        investigation_id=admission.investigation_id,
        finalization_id=admission.finalization_id,
    )
    if not completed:
        _reject(
            "chapter_set_empty",
            "no completed chapter generations for this admission",
        )
    by_id = {row["generation_id"]: row for row in completed}
    missing = [gid for gid in expected_generation_ids if gid not in by_id]
    if missing:
        _reject(
            "chapter_generation_missing",
            f"expected chapter generations are not completed: {sorted(missing)}",
        )
    if expected_generation_ids:
        generation_set = set(expected_generation_ids)
        if set(by_id) - generation_set:
            _reject(
                "chapter_set_mismatch",
                "completed chapter set contains unexpected generations",
            )
    else:
        _reject(
            "chapter_set_empty",
            "expected chapter generation set is empty",
        )

    ordered = [by_id[gid] for gid in expected_generation_ids]
    chapter_ids = [row["chapter_id"] for row in ordered]
    if len(set(chapter_ids)) != len(chapter_ids):
        _reject(
            "chapter_identity_duplicate",
            "two completed generations claim the same chapter_id",
        )

    finalization_id = admission.finalization_id
    outline_id = ordered[0]["outline_id"]
    outline_revision = ordered[0]["outline_revision"]
    for row in ordered:
        if row["task_id"] != admission.task_id or (
            row["investigation_id"] != admission.investigation_id
            or row["finalization_id"] != finalization_id
        ):
            _reject(
                "finalization_binding_mismatch",
                f"chapter {row['generation_id']} belongs to another "
                "task/finalization",
            )
        if row["outline_id"] != outline_id or (
            row["outline_revision"] != outline_revision
        ):
            _reject(
                "outline_binding_mismatch",
                f"chapter {row['generation_id']} belongs to another outline",
            )

    drafts: list[ChapterDraftV1] = []
    digests: list[ChapterDigestV1] = []
    for row in ordered:
        pack = repository.get_context_pack(row["context_pack_id"])
        if pack is None:
            _reject(
                "context_pack_missing",
                f"context pack not persisted: {row['context_pack_id']}",
            )
        if pack.input_hash != row["context_pack_hash"]:
            _reject(
                "context_pack_hash_mismatch",
                f"persisted pack hash differs for {row['context_pack_id']}",
            )
        if pack.finalization_id != finalization_id or (
            pack.outline_id != outline_id
            or pack.outline_revision != outline_revision
        ):
            _reject(
                "finalization_binding_mismatch",
                f"pack {pack.context_pack_id} belongs to another "
                "finalization/outline",
            )
        if pack.chapter_spec_hash != row["chapter_spec_hash"]:
            _reject(
                "chapter_spec_hash_mismatch",
                f"pack spec hash differs for chapter {row['chapter_id']}",
            )
        try:
            payload = _json.loads(row["output_json"])
            # output_json embeds draft_hash alongside the model payload
            # (complete_chapter_generation contract); strip it before
            # strict re-validation.
            draft = ChapterDraftV1.model_validate(
                {k: v for k, v in payload.items() if k != "draft_hash"}
            )
        except Exception as exc:
            _reject(
                "chapter_output_invalid",
                f"completed output for {row['generation_id']} does not "
                f"re-validate: {exc}",
            )
        if sha256_hex(draft.model_dump(mode="json")) != row["output_hash"]:
            _reject(
                "chapter_output_hash_mismatch",
                f"validated output hash differs for "
                f"{row['generation_id']}",
            )
        digest = ChapterDigestV1.model_validate_json(row["digest_json"])
        if digest.generation_id != row["generation_id"] or (
            digest.chapter_id != row["chapter_id"]
        ):
            _reject(
                "digest_identity_mismatch",
                f"persisted digest identity differs for "
                f"{row['generation_id']}",
            )
        if digest.draft_hash != row["output_hash"] or (
            digest.context_pack_hash != pack.input_hash
        ):
            _reject(
                "digest_hash_mismatch",
                f"persisted digest binds other output/pack for "
                f"{row['generation_id']}",
            )
        drafts.append(draft)
        digests.append(digest)

    ledger = repository.get_assertion_ledger(ledger_id)
    if ledger is None:
        _reject(
            "ledger_missing",
            f"assertion ledger not persisted: {ledger_id}",
        )
    if ledger.finalization_id != finalization_id:
        _reject(
            "ledger_finalization_mismatch",
            "ledger belongs to another finalization",
        )
    if ledger.outline_id != outline_id or (
        ledger.outline_revision != outline_revision
    ):
        _reject(
            "ledger_outline_mismatch",
            "ledger belongs to another outline revision",
        )
    persisted_generation_ids = {
        row["generation_id"] for row in ordered
    }
    if set(ledger.chapter_generation_ids) != persisted_generation_ids:
        _reject(
            "ledger_chapter_set_mismatch",
            "ledger does not aggregate exactly the persisted chapter set",
        )
    draft_hashes = {draft.draft_hash() for draft in drafts}
    if not set(ledger.chapter_draft_hashes) <= draft_hashes:
        _reject(
            "ledger_draft_hash_mismatch",
            "ledger draft hashes do not match the persisted outputs",
        )

    if not review_ids:
        _reject("review_missing", "publication requires a consistency review")
    for review_id in review_ids:
        review = repository.get_consistency_review(review_id)
        if review is None:
            _reject(
                "review_missing",
                f"consistency review not persisted: {review_id}",
            )
        if review.status != "pass":
            _reject(
                "review_not_pass",
                f"consistency review {review_id} is "
                f"{review.status!r}, not pass",
            )
        if review.ledger_id != ledger_id or (
            review.ledger_hash != ledger.input_hash
        ):
            _reject(
                "review_ledger_mismatch",
                f"review {review_id} was produced for another ledger",
            )
        if review.task_id != admission.task_id or (
            review.investigation_id != admission.investigation_id
        ):
            _reject(
                "review_runtime_mismatch",
                f"review {review_id} belongs to another runtime",
            )
    persisted_review_hashes = tuple(
        repository.get_consistency_review(review_id).input_hash
        for review_id in review_ids
    )

    return TrustedPublicationInput(
        admission=admission,
        admission_id=admission.admission_id,
        finalization_id=finalization_id,
        finalization_record_hash=admission.finalization_record_hash,
        outline_id=outline_id,
        outline_revision=outline_revision,
        drafts=drafts,
        chapter_spec_hashes=tuple(row["chapter_spec_hash"] for row in ordered),
        context_pack_ids=tuple(row["context_pack_id"] for row in ordered),
        context_pack_hashes=tuple(row["context_pack_hash"] for row in ordered),
        ledger=ledger,
        digests=digests,
        review_ids=tuple(review_ids),
        review_hashes=persisted_review_hashes,
    )


class PrevalidatedReportPublicationAdapter:
    """§52 option B: publish VALIDATED chapter drafts through the R2
    publication primitives without a second LLM.

    Freeze follow-up (§3-§9): ``publish`` no longer trusts caller-built
    artifacts.  It reloads the exact durable publication snapshot through
    :func:`build_trusted_publication_input` (admission, completed chapter
    generations, validated outputs/digests, ledger, persisted passing
    reviews), re-runs deterministic consistency against THAT snapshot,
    and renders the manifest from the reloaded drafts only.  The caller
    supplies IDs / expected hashes; every payload comes from the store.
    """

    version = "prevalidated-publication-adapter:v1"

    def __init__(self, *, runtime_repository: Any, r2_repository: Any, writer: Any):
        # runtime_repository: ReportRuntimeRepository — the trusted-input
        # reload source (durable P7 plane);
        # r2_repository: R2 ReportRepository — version allocation/READY row;
        # writer: R2 GenerationReportWriter — atomic snapshot publish.
        self._runtime_repository = runtime_repository
        self._r2_repository = r2_repository
        self._writer = writer

    def publish(
        self,
        *,
        task_id: str,
        title: str,
        admission_id: str,
        expected_generation_ids: tuple[str, ...],
        ledger_id: str,
        review_ids: tuple[str, ...],
        chapter_titles: dict[str, str],
        evidence_digests: dict[str, str] | None = None,
        model: str,
        prompt_version: str,
    ) -> tuple[str, str]:
        """Publish and return (report_id, manifest_path_relative).

        The R2 publication contract is preserved: atomic file publish
        first, then version allocation + READY row in one repository
        transaction; any failure leaves no Viewer-visible version (§57).
        """
        from .report_chapter_generation import (
            CHAPTER_OUTPUT_CONTRACT_VERSION,
        )
        from .report_ledger import run_deterministic_consistency

        trusted = build_trusted_publication_input(
            self._runtime_repository,
            admission_id=admission_id,
            expected_generation_ids=tuple(expected_generation_ids),
            ledger_id=ledger_id,
            review_ids=tuple(review_ids),
        )
        if trusted.admission.task_id != task_id:
            raise PublicationTrustError(
                "task_mismatch",
                "publication task does not match the durable admission",
            )
        drafts = trusted.drafts
        digests = trusted.digests
        ledger = trusted.ledger
        review_hashes = trusted.review_hashes
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
            raise PublicationTrustError(
                "deterministic_consistency_failed",
                "deterministic consistency failed before publication: "
                + ", ".join(sorted({i["code"] for i in consistency_issues})),
            )
        sections = render_sections_from_drafts(
            drafts, chapter_titles=chapter_titles
        )
        citations = build_citations_from_drafts(drafts)
        output_hashes = tuple(draft.draft_hash() for draft in drafts)
        provenance = ManifestProvenanceV3(
            finalization_id=trusted.finalization_id,
            finalization_record_hash=trusted.finalization_record_hash,
            outline_id=trusted.outline_id,
            outline_revision=trusted.outline_revision,
            chapter_ids=tuple(draft.chapter_id for draft in drafts),
            chapter_spec_hashes=trusted.chapter_spec_hashes,
            context_pack_ids=trusted.context_pack_ids,
            context_pack_hashes=trusted.context_pack_hashes,
            chapter_generation_ids=ledger.chapter_generation_ids,
            chapter_output_hashes=output_hashes,
            chapter_digest_ids=tuple(d.digest_id for d in digests),
            chapter_digest_hashes=tuple(d.digest_hash for d in digests),
            assertion_ledger_id=ledger.ledger_id,
            assertion_ledger_hash=ledger.input_hash,
            consistency_review_ids=trusted.review_ids,
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
        self._r2_repository.complete_prevalidated_publication(
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
    "PublicationTrustError",
    "REPORT_KIND_AGENT_AWARE",
    "TrustedPublicationInput",
    "build_citations_from_drafts",
    "build_trusted_publication_input",
    "render_sections_from_drafts",
]
