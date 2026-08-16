from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..investigation.models import (
    AnalysisGroundingStatus,
    ClaimGroundingStatus,
    ClaimType,
    ReportEvidenceStatus,
    SnapshotPayload,
)


class ScopeType(str, Enum):
    TASK = "task"
    CASE = "case"


class ReportStatus(str, Enum):
    QUEUED = "queued"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class DataState(str, Enum):
    EXISTING = "existing"
    DELETED = "deleted"
    RECOVERED = "recovered"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SourceFingerprint(BaseModel):
    path: str
    exists: bool
    size: int | None = None
    mtime_ns: int | None = None
    sha256: str | None = None


class EvidenceSource(BaseModel):
    evidence_id: str
    task_id: str
    name: str
    image_path: str | None = None
    db_paths: dict[str, str] = Field(default_factory=dict)
    source_fingerprints: dict[str, SourceFingerprint] = Field(default_factory=dict)


class ReportAttachment(BaseModel):
    attachment_id: str
    file_name: str
    evidence_path: str
    size: int | None = None
    mime: str | None = None
    hashes: dict[str, str] = Field(default_factory=dict)
    preview_type: str = "none"
    preview_path: str | None = None
    original_included: bool = False
    unavailable_reason: str | None = None


class AnalysisReference(BaseModel):
    chapter: str
    token: str


class ReportRecord(BaseModel):
    record_id: str
    category: str
    title: str
    timestamp: int | None = None
    source_path: str | None = None
    source_table: str
    source_record_id: str
    data_state: DataState = DataState.UNKNOWN
    severity: Severity = Severity.INFO
    is_relevant: bool = False
    hashes: dict[str, str] = Field(default_factory=dict)
    fields: dict[str, Any] = Field(default_factory=dict)
    attachments: list[ReportAttachment] = Field(default_factory=list)
    analysis_references: list[AnalysisReference] = Field(default_factory=list)

    @field_validator("record_id")
    @classmethod
    def validate_record_id(cls, value: str) -> str:
        digest = value[4:]
        if (
            not value.startswith("rec_")
            or len(digest) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in digest)
        ):
            raise ValueError("record_id must be rec_ followed by a SHA-256 hex digest")
        return value


class CategorySpec(BaseModel):
    category_id: str
    platform: str
    title: str
    renderer: str = "table"
    source_table: str
    page_size: int = Field(default=100, ge=1, le=1000)
    searchable_fields: list[str] = Field(default_factory=list)


class ProbeResult(BaseModel):
    available: bool
    reason: str | None = None


class AdapterWarning(BaseModel):
    adapter: str
    evidence_id: str
    category_id: str | None = None
    code: str
    message: str


class AdapterContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    scope_type: ScopeType
    scope_id: str
    evidence_id: str
    task_id: str
    evidence_name: str
    db_paths: dict[str, str]
    source_fingerprints: dict[str, SourceFingerprint]
    relevant_paths: set[str] = Field(default_factory=set)


class ReportAdapter(Protocol):
    name: str
    platform: str

    def probe(self, context: AdapterContext) -> ProbeResult: ...
    def categories(self, context: AdapterContext) -> Sequence[CategorySpec]: ...
    def iter_records(
        self, context: AdapterContext, category: CategorySpec
    ) -> Iterator[ReportRecord]: ...


class CategoryIndex(BaseModel):
    category_id: str
    evidence_id: str
    platform: str
    title: str
    renderer: str
    total: int
    deleted: int = 0
    recovered: int = 0
    high_risk: int = 0
    relevant: int = 0
    referenced: int = 0
    page_size: int
    pages: int
    page_paths: list[str]


class PageShard(BaseModel):
    schema_version: str = "1.0"
    category_id: str
    page: int
    page_size: int
    total: int
    records: list[ReportRecord]
    sha256: str


class ReportManifest(BaseModel):
    schema_version: str = "1.0"
    report_id: str
    version: int
    scope_type: ScopeType
    scope_id: str
    status: ReportStatus
    title: str
    generated_at: str
    generated_by: str
    generator_version: str
    platforms: list[str]
    task_ids: list[str]
    evidence: list[EvidenceSource]
    directory: list[dict[str, Any]]
    categories: list[CategoryIndex]
    source_fingerprints: dict[str, SourceFingerprint]
    warnings: list[AdapterWarning]
    integrity: dict[str, Any] = Field(default_factory=dict)


class ReportVersion(BaseModel):
    report_id: str
    version: int
    scope_type: ScopeType
    scope_id: str
    status: ReportStatus
    title: str
    task_ids: list[str]
    stage: str = "queued"
    progress: int = Field(default=0, ge=0, le=100)
    generated_at: str | None = None
    manifest_path: str | None = None
    offline_bundle_path: str | None = None
    warnings: list[AdapterWarning] = Field(default_factory=list)
    error: str | None = None
    # R2d explicit type marker: None = deterministic forensic snapshot
    # (every pre-existing row), 'llm_generation' = R2c narrative version.
    report_kind: str | None = None


class SearchHit(BaseModel):
    record_id: str | None = None
    kind: str
    title: str
    snippet: str
    matched_field: str
    evidence_id: str | None = None
    platform: str | None = None
    category_id: str | None = None
    page: int | None = None


# ---------------------------------------------------------------------------
# Frozen Report Generation Input (Phase R2b)
# ---------------------------------------------------------------------------


class EnvelopeSnapshotV1(BaseModel):
    """Exact immutable Evidence Snapshot projection inside the envelope.

    Only canonical persisted snapshot fields: no surrogate ids, no source
    store paths, no runtime metadata. ``payload`` is the frozen capture-time
    projection itself (C4), never a re-read of files.db.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    evidence_key: str
    evidence_type: Literal["file", "cluster"]
    captured_at: int
    payload: SnapshotPayload


class EnvelopeClaimV1(BaseModel):
    """One persisted Claim of the bound analysis, with exact historical refs.

    ``evidence_refs`` keeps the claim's full persisted provenance (it may
    reference evidence outside the report set); those keys are claim
    provenance only and never become citation candidates by themselves.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str
    claim_index: int
    claim_type: ClaimType
    claim_text: str
    grounding_status: ClaimGroundingStatus
    warnings: dict[str, Any] | None = None
    evidence_refs: tuple[str, ...] = ()
    created_at: str


class EnvelopeBoundAnalysisReviewV1(BaseModel):
    """Review metadata of the frozen accepted binding (audit fields only)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decided_by: str | None = None
    decided_at: str | None = None
    decision_reason: str | None = None


class EnvelopeBoundAnalysisV1(BaseModel):
    """The exact accepted Secondary Analysis bound to one Report Evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    analysis_id: str
    version: int
    description: str | None = None
    summary: str | None = None
    model: str | None = None
    grounding_status: AnalysisGroundingStatus | None = None
    review: EnvelopeBoundAnalysisReviewV1
    claims: tuple[EnvelopeClaimV1, ...] = ()


class EnvelopeEvidenceItemV1(BaseModel):
    """One main/appendix Report Evidence with its frozen provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_key: str
    report_status: ReportEvidenceStatus
    snapshot: EnvelopeSnapshotV1
    bound_analysis: EnvelopeBoundAnalysisV1 | None = None

    @model_validator(mode="after")
    def _validate_identity(self):
        allowed = (ReportEvidenceStatus.main, ReportEvidenceStatus.appendix)
        if self.report_status not in allowed:
            raise ValueError("envelope report_status must be main or appendix")
        if self.snapshot.evidence_key != self.evidence_key:
            raise ValueError("envelope snapshot identity mismatch")
        return self


class ReportGenerationEnvelopeV1(BaseModel):
    """Frozen LLM-generation input assembled from R1 Report Evidence (R2b).

    Deterministic by construction and by validator: main/appendix sorted by
    evidence_key, claims sorted by claim_id, claim refs sorted, and
    ``allowed_report_evidence_ids`` exactly the sorted-unique main+appendix
    keys (server-derived; clients can never supply it). Never contains
    excluded rows, UI hints (``newer_accepted_available``), latest/current
    selections, or runtime metadata — ``requested_by`` and audit info live
    on the generation row, not in the LLM input.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    prompt_version: str
    task_id: str
    main_evidence: tuple[EnvelopeEvidenceItemV1, ...] = ()
    appendix_evidence: tuple[EnvelopeEvidenceItemV1, ...] = ()
    allowed_report_evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_determinism(self):
        items = (*self.main_evidence, *self.appendix_evidence)
        for name, keys in (
            ("main_evidence", [i.evidence_key for i in self.main_evidence]),
            ("appendix_evidence", [i.evidence_key for i in self.appendix_evidence]),
        ):
            if keys != sorted(keys):
                raise ValueError(f"{name} must be sorted by evidence_key")
            if len(set(keys)) != len(keys):
                raise ValueError(f"{name} contains a duplicate evidence_key")
        if list(self.allowed_report_evidence_ids) != sorted(set(self.allowed_report_evidence_ids)):
            raise ValueError("allowed_report_evidence_ids must be sorted and unique")
        if set(self.allowed_report_evidence_ids) != {i.evidence_key for i in items}:
            raise ValueError(
                "allowed_report_evidence_ids must equal the main+appendix keys"
            )
        for item in items:
            if item.snapshot.task_id != self.task_id:
                raise ValueError("envelope snapshot task mismatch")
            bound = item.bound_analysis
            if bound is None:
                continue
            claim_ids = [claim.claim_id for claim in bound.claims]
            if claim_ids != sorted(claim_ids):
                raise ValueError("claims must be sorted by claim_id")
            for claim in bound.claims:
                if list(claim.evidence_refs) != sorted(claim.evidence_refs):
                    raise ValueError("claim evidence_refs must be sorted")
        return self


class ReportGenerationInput(BaseModel):
    """One persisted frozen generation admission row (read model).

    ``status`` starts ``admitted`` (R2b naming; it is the queued state) and
    moves ``admitted -> running -> completed | failed`` under the R2c
    executor; identity, scope, requester, prompt version, envelope bytes,
    and hash are frozen at the DB level after admission. ``report_id`` /
    ``produced_version`` link the published report version and are set only
    by the successful publication transaction.
    """

    model_config = ConfigDict(frozen=True)

    generation_id: str
    task_id: str
    scope_type: ScopeType
    scope_id: str
    status: str
    requested_by: str
    input_schema_version: int
    prompt_version: str
    input_envelope_json: str
    input_hash: str
    report_id: str | None = None
    produced_version: int | None = None
    model: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    failed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Structured report output & citation manifest (Phase R2c)
# ---------------------------------------------------------------------------


class StructuredReportCitation(BaseModel):
    """One machine-readable exact citation emitted by the LLM."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    citation_id: str = Field(min_length=1, max_length=256)
    evidence_key: str = Field(min_length=1, max_length=4096)
    analysis_id: str | None = Field(default=None, min_length=1, max_length=128)
    claim_id: str | None = Field(default=None, min_length=1, max_length=128)


class StructuredReportSection(BaseModel):
    """One narrative section with its exact citation references."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    heading: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=100_000)
    citation_ids: tuple[str, ...] = ()


class StructuredReportResponse(BaseModel):
    """Strict structured LLM output for report generation (R2c).

    Free-form Markdown is rejected: the report is born as this structure and
    any rendering happens deterministically server-side later.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    sections: tuple[StructuredReportSection, ...] = Field(min_length=1)
    citations: tuple[StructuredReportCitation, ...] = ()

    @model_validator(mode="after")
    def _validate_citation_references(self):
        ids = [citation.citation_id for citation in self.citations]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate citation_id in report output")
        known = set(ids)
        for section in self.sections:
            unknown = [cid for cid in section.citation_ids if cid not in known]
            if unknown:
                raise ValueError("section references an unknown citation_id")
        return self


class CitationManifestEntry(BaseModel):
    """One immutable manifest entry persisted with a published report.

    Exact persisted identity only (citation -> evidence -> optional frozen
    analysis/claim), plus the frozen provenance metadata copied from the
    admitted envelope so the Viewer never re-derives citation provenance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    citation_id: str
    evidence_key: str
    analysis_id: str | None = None
    claim_id: str | None = None
    evidence_captured_at: int | None = None
    analysis_version: int | None = None
    claim_type: ClaimType | None = None


class GenerationReportManifest(BaseModel):
    """The published artifact of one successful LLM generation (R2c).

    The narrative body, the citation manifest, and the generation linkage
    are ONE canonical JSON file, so a published report version can never
    expose a body without its manifest. The report ``version`` is
    intentionally absent: version identity is owned by the
    ``report_versions`` row allocated in the publication transaction.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    report_kind: Literal["llm_generation"] = "llm_generation"
    report_id: str
    scope_type: ScopeType
    scope_id: str
    task_id: str
    generation_id: str
    title: str
    prompt_version: str
    input_hash: str
    model: str
    generated_at: str
    sections: tuple[StructuredReportSection, ...]
    citations: tuple[CitationManifestEntry, ...]


class ReportGenerationStatus(BaseModel):
    """Generation row plus the published manifest (completed reads only)."""

    model_config = ConfigDict(frozen=True)

    generation: ReportGenerationInput
    report: dict[str, Any] | None = None
