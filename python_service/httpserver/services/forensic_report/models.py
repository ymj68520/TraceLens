from __future__ import annotations

import json
import hashlib
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

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


class EnvelopeSnapshotV3(EnvelopeSnapshotV1):
    """Versioned Android extension; V1/V2 refuse the new evidence type."""

    evidence_type: Literal["file", "cluster", "android_artifact"]


class EnvelopeEvidenceItemV3(EnvelopeEvidenceItemV1):
    snapshot: EnvelopeSnapshotV3


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
        _validate_envelope_determinism(
            task_id=self.task_id,
            main_evidence=self.main_evidence,
            appendix_evidence=self.appendix_evidence,
            allowed_report_evidence_ids=self.allowed_report_evidence_ids,
        )
        return self


CASE_DESCRIPTION_MAX_CHARS = 8000


class ReportGenerationEnvelopeV2(BaseModel):
    """V2: adds the frozen case description to the generation input.

    The case background is part of the hash-verified persisted input (not
    the system prompt) so "what background did the model see" stays exactly
    auditable per generation. Admission truncates deterministically at
    ``CASE_DESCRIPTION_MAX_CHARS``; the narrative contract that consumes it
    lives in the prompt version, not here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[2] = 2
    prompt_version: str
    task_id: str
    case_description: str = Field(max_length=CASE_DESCRIPTION_MAX_CHARS)
    main_evidence: tuple[EnvelopeEvidenceItemV1, ...] = ()
    appendix_evidence: tuple[EnvelopeEvidenceItemV1, ...] = ()
    allowed_report_evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_determinism(self):
        _validate_envelope_determinism(
            task_id=self.task_id,
            main_evidence=self.main_evidence,
            appendix_evidence=self.appendix_evidence,
            allowed_report_evidence_ids=self.allowed_report_evidence_ids,
        )
        return self


class ReportGenerationEnvelopeV3(ReportGenerationEnvelopeV2):
    schema_version: Literal[3] = 3
    main_evidence: tuple[EnvelopeEvidenceItemV3, ...] = ()
    appendix_evidence: tuple[EnvelopeEvidenceItemV3, ...] = ()


class ReportGenerationEnvelopeV4(ReportGenerationEnvelopeV3):
    """Classification is part of the existing report job, with a frozen policy."""

    schema_version: Literal[4] = 4
    classification_policy: Literal["evidence-dimensions:v1"] = "evidence-dimensions:v1"


class NeutralMaterial(BaseModel):
    """Content frozen for this report; never a historical AI summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    material_id: str = Field(pattern=r"^m[0-9]+$")
    evidence_key: str
    kind: Literal["text", "parsed_text", "android_record", "audio_transcript",
                  "image", "machine_visual", "unavailable"]
    text: str = Field(default="", max_length=4000)
    media_base64: str = Field(default="", max_length=3_000_000)
    source_sha256: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    original_characters: int = Field(default=0, ge=0)
    status: Literal["ready", "partial", "unavailable"]
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _content_integrity(self):
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.content_sha256:
            raise ValueError("neutral material text hash mismatch")
        if self.kind == "image" and self.status != "unavailable":
            import base64
            try:
                raw = base64.b64decode(self.media_base64, validate=True)
            except ValueError as exc:
                raise ValueError("invalid frozen image") from exc
            if not raw or hashlib.sha256(raw).hexdigest() != self.source_sha256:
                raise ValueError("frozen image hash mismatch")
        elif self.media_base64:
            raise ValueError("only frozen images carry media")
        return self


class MaterialQuote(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    material_id: str
    quote: str = Field(min_length=1, max_length=300)


class MaterialSpan(MaterialQuote):
    character_start: int = Field(ge=0)
    character_end: int = Field(gt=0)
    ambiguous: bool = False


class DirectionSuggestion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1500)
    finding_kind: Literal["observation", "hypothesis"]
    supporting_refs: tuple[MaterialQuote, ...] = Field(default=(), max_length=6)
    counter_refs: tuple[MaterialQuote, ...] = Field(default=(), max_length=6)
    missing_information: tuple[str, ...] = Field(default=(), max_length=8)
    alternative_explanations: tuple[str, ...] = Field(default=(), max_length=6)
    baseline_direction_ids: tuple[str, ...] = Field(default=(), max_length=8)
    case_context_quote: str = Field(default="", max_length=500)

    @field_validator("supporting_refs", "counter_refs", "missing_information",
                     "alternative_explanations", "baseline_direction_ids", mode="before")
    @classmethod
    def _accept_scalar_as_single_item(cls, v):
        # Models intermittently emit a bare string/object for these array
        # fields; one item is one item, so normalize before strict validation.
        if v is None:
            return ()
        if isinstance(v, (list, tuple)):
            return v
        return [v]


class DirectionBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    directions: tuple[DirectionSuggestion, ...] = Field(max_length=8)


class InvestigationDirection(DirectionSuggestion):
    direction_id: str
    supporting_refs: tuple[MaterialSpan, ...] = ()
    counter_refs: tuple[MaterialSpan, ...] = ()
    origin: Literal["material", "reinterpreted", "new_candidate", "case_only"]


class ComparisonSuggestion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    baseline_direction_id: str
    status: Literal["supported", "revised", "weakened", "contradicted", "insufficient", "case_only"]
    reason: str = Field(min_length=1, max_length=1200)
    supporting_refs: tuple[MaterialQuote, ...] = Field(default=(), max_length=6)
    counter_refs: tuple[MaterialQuote, ...] = Field(default=(), max_length=6)
    missing_information: tuple[str, ...] = Field(default=(), max_length=8)
    case_context_quote: str = Field(default="", max_length=500)

    @field_validator("supporting_refs", "counter_refs", "missing_information", mode="before")
    @classmethod
    def _accept_scalar_as_single_item(cls, v):
        if v is None:
            return ()
        if isinstance(v, (list, tuple)):
            return v
        return [v]


class DirectionComparison(ComparisonSuggestion):
    supporting_refs: tuple[MaterialSpan, ...] = ()
    counter_refs: tuple[MaterialSpan, ...] = ()


class BaselineContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    report_id: str
    report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_scope_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    materials: tuple[NeutralMaterial, ...]
    directions: tuple[InvestigationDirection, ...]
    priorities: dict[str, Literal["P1", "P2", "P3", "unassessed"]] = Field(default_factory=dict)
    text_models: tuple[str, ...] = ()


def material_scope_hash(materials) -> str:
    value = [m.model_dump(mode="json") for m in materials]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


class ReportGenerationEnvelopeV5(ReportGenerationEnvelopeV4):
    schema_version: Literal[5] = 5
    analysis_mode: Literal["evidence_only", "case_guided"]
    neutral_materials: tuple[NeutralMaterial, ...]
    evidence_scope_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    baseline: BaselineContext | None = None

    @model_validator(mode="after")
    def _stage_boundary(self):
        keys = [m.evidence_key for m in self.neutral_materials]
        ids = [m.material_id for m in self.neutral_materials]
        if keys != list(self.allowed_report_evidence_ids) or len(ids) != len(set(ids)):
            raise ValueError("neutral material coverage mismatch")
        if material_scope_hash(self.neutral_materials) != self.evidence_scope_hash:
            raise ValueError("evidence scope hash mismatch")
        for item in (*self.main_evidence, *self.appendix_evidence):
            payload = item.snapshot.payload
            if item.bound_analysis is not None or any(getattr(payload, k, None) is not None for k in (
                "initial_summary", "initial_description", "initial_keywords", "initial_model",
                "initial_analyzed_at", "scene_type", "scene_priority", "scene_relevant",
            )):
                raise ValueError("case-derived analysis is forbidden in neutral sources")
        if self.analysis_mode == "evidence_only":
            if self.case_description or self.baseline is not None or self.prompt_version != "final-report:evidence-only:v1":
                raise ValueError("first-stage input must be independent of case context")
        else:
            if not self.case_description.strip() or self.baseline is None or self.prompt_version != "final-report:case-guided:v1":
                raise ValueError("second-stage input requires case context and baseline")
            if self.baseline.evidence_scope_hash != self.evidence_scope_hash:
                raise ValueError("second-stage evidence scope changed")
            if [(m.material_id, m.evidence_key, m.source_sha256) for m in self.baseline.materials] != [
                (m.material_id, m.evidence_key, m.source_sha256) for m in self.neutral_materials
            ]:
                raise ValueError("baseline material identity changed")
        return self


def _validate_envelope_determinism(
    *,
    task_id: str,
    main_evidence: tuple[EnvelopeEvidenceItemV1, ...],
    appendix_evidence: tuple[EnvelopeEvidenceItemV1, ...],
    allowed_report_evidence_ids: tuple[str, ...],
) -> None:
    items = (*main_evidence, *appendix_evidence)
    for name, keys in (
        ("main_evidence", [i.evidence_key for i in main_evidence]),
        ("appendix_evidence", [i.evidence_key for i in appendix_evidence]),
    ):
        if keys != sorted(keys):
            raise ValueError(f"{name} must be sorted by evidence_key")
        if len(set(keys)) != len(keys):
            raise ValueError(f"{name} contains a duplicate evidence_key")
    if list(allowed_report_evidence_ids) != sorted(set(allowed_report_evidence_ids)):
        raise ValueError("allowed_report_evidence_ids must be sorted and unique")
    if set(allowed_report_evidence_ids) != {i.evidence_key for i in items}:
        raise ValueError(
            "allowed_report_evidence_ids must equal the main+appendix keys"
        )
    for item in items:
        if item.snapshot.task_id != task_id:
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


def parse_generation_envelope(raw: str) -> "ReportGenerationEnvelopeV1 | ReportGenerationEnvelopeV2 | ReportGenerationEnvelopeV3 | ReportGenerationEnvelopeV4 | ReportGenerationEnvelopeV5":
    """Parse a persisted generation envelope, dispatching on schema_version.

    A stored row's bytes are version-tagged; strict pydantic validation for
    the matching model, ValueError for anything else (unknown/missing
    version, shape drift) -- the executor turns that into
    ``input_integrity_error`` exactly like a ValidationError today.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("envelope is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("envelope must be a JSON object")
    version = payload.get("schema_version")
    model = {
        1: ReportGenerationEnvelopeV1,
        2: ReportGenerationEnvelopeV2,
        3: ReportGenerationEnvelopeV3,
        4: ReportGenerationEnvelopeV4,
        5: ReportGenerationEnvelopeV5,
    }.get(version)
    if model is None:
        raise ValueError(f"unsupported envelope schema_version: {version!r}")
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("envelope failed schema validation") from exc


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


class StructuredOutlineSection(BaseModel):
    """One planned section of the v2 outline.

    ``group_ids`` names the deterministic evidence groups this section must
    cover (membership semantics enforced by the executor against the real
    grouping, not here -- the model only ever sees group ids and names).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    heading: str = Field(min_length=1, max_length=500)
    brief: str = Field(min_length=1, max_length=2000)
    group_ids: tuple[str, ...] = ()


class StructuredOutlineResponse(BaseModel):
    """Strict structured LLM output for the v2 outline stage.

    Lower bound is 3 so small evidence sets (a handful of files) still map
    to a legal outline; the prompt asks the model to scale the count to the
    evidence at hand instead of padding filler chapters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    sections: tuple[StructuredOutlineSection, ...] = Field(min_length=3, max_length=15)


class StructuredSectionResponse(BaseModel):
    """Strict structured LLM output for one v2 section.

    ``analysis_id``/``claim_id`` stay structurally possible (same citation
    identity as the assembled report). V2 rejects non-null derived IDs; V3
    may emit an ID only when the frozen item has that exact accepted binding.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    heading: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=100_000)
    citations: tuple[StructuredReportCitation, ...] = ()


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


EvidenceTopic = Literal[
    "funds", "identity_accounts", "communications", "location", "network", "tools",
]
MaterialType = Literal[
    "document", "chat_record", "transaction_record", "image", "log",
    "android_artifact", "other", "unknown",
]


class ClassificationQuestion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=500)
    origin: Literal["case", "material", "generic"] = "case"


class EvidenceQuestionRelation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: str = Field(min_length=1, max_length=32)
    relation: Literal["supports", "inconsistent", "background", "unknown"]
    reason: str = Field(min_length=1, max_length=300)


class EvidenceClassificationSuggestion(BaseModel):
    """Only semantic suggestions can be emitted by the model; never review state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_key: str = Field(min_length=1, max_length=4096)
    material_type: MaterialType
    topics: tuple[EvidenceTopic, ...] = Field(max_length=6)
    relations: tuple[EvidenceQuestionRelation, ...] = Field(max_length=4)
    key_issue: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=300)
    basis_quote: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _unique_dimensions(self):
        if len(set(self.topics)) != len(self.topics):
            raise ValueError("duplicate classification topic")
        ids = [r.question_id for r in self.relations]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate classification question")
        return self


class EvidenceClassificationBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    classifications: tuple[EvidenceClassificationSuggestion, ...] = Field(max_length=6)


class ReportEvidenceClassification(BaseModel):
    """Frozen display annotation; it never changes adoption or analysis review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_key: str
    material_type: MaterialType = "unknown"
    topics: tuple[EvidenceTopic, ...] = ()
    relations: tuple[EvidenceQuestionRelation, ...] = ()
    priority: Literal["P1", "P2", "P3", "unassessed"] = "unassessed"
    material_states: tuple[Literal[
        "deleted", "recovered", "insufficient_content", "incomplete_provenance",
    ], ...] = ()
    review_status: Literal["machine_suggested", "pending", "confirmed", "adjusted"] = "pending"
    assessment_status: Literal["classified", "insufficient", "failed"] = "insufficient"
    reason: str
    basis_type: Literal["initial_analysis", "android_record", "metadata", "neutral_material", "machine_visual"]
    basis_quote: str = ""
    basis_truncated: bool = False
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    model: str | None = None


class ReportClassifications(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: Literal["evidence-dimensions:v1"] = "evidence-dimensions:v1"
    questions: tuple[ClassificationQuestion, ...] = ()
    items: tuple[ReportEvidenceClassification, ...]

    @model_validator(mode="after")
    def _validate_references(self):
        keys = [item.evidence_key for item in self.items]
        questions = [q.question_id for q in self.questions]
        if len(set(keys)) != len(keys) or len(set(questions)) != len(questions):
            raise ValueError("duplicate classification identity")
        for item in self.items:
            if any(r.question_id not in questions for r in item.relations):
                raise ValueError("classification references unknown question")
        return self


class StageAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    analysis_mode: Literal["evidence_only", "case_guided"]
    evidence_scope_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    case_description: str = Field(default="", max_length=8000)
    case_context_hash: str | None = None
    baseline_report_id: str | None = None
    baseline_report_hash: str | None = None
    materials: tuple[NeutralMaterial, ...]
    directions: tuple[InvestigationDirection, ...]
    comparisons: tuple[DirectionComparison, ...] = ()
    baseline_directions: tuple[InvestigationDirection, ...] = ()
    baseline_priorities: dict[str, str] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    text_models: tuple[str, ...] = ()
    baseline_text_models: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _stage_integrity(self):
        materials = {m.material_id: m for m in self.materials}
        if len(materials) != len(self.materials) or len({m.evidence_key for m in self.materials}) != len(self.materials):
            raise ValueError("duplicate stage material")
        if any(m.media_base64 for m in self.materials):
            raise ValueError("published stage must not expose frozen media bytes")
        if self.analysis_mode == "evidence_only":
            if self.case_description or self.case_context_hash or self.baseline_report_id or self.baseline_report_hash or self.baseline_directions or self.comparisons:
                raise ValueError("autonomous report cannot inherit case context or a baseline")
        elif (not self.case_description.strip() or not self.baseline_report_id or not self.baseline_report_hash
              or self.case_context_hash != hashlib.sha256(self.case_description.encode("utf-8")).hexdigest()):
            raise ValueError("case-guided report lineage or context hash mismatch")
        baseline_ids = {d.direction_id for d in self.baseline_directions}
        if len(baseline_ids) != len(self.baseline_directions):
            raise ValueError("duplicate baseline direction")
        compared = [c.baseline_direction_id for c in self.comparisons]
        if len(compared) != len(set(compared)) or set(compared) != baseline_ids:
            raise ValueError("comparison must retain every baseline direction exactly once")
        if len({d.direction_id for d in self.directions}) != len(self.directions):
            raise ValueError("duplicate investigation direction")
        for record in (*self.directions, *self.baseline_directions, *self.comparisons):
            for ref in (*record.supporting_refs, *record.counter_refs):
                source = materials.get(ref.material_id)
                if source is None or source.status == "unavailable" or source.text[ref.character_start:ref.character_end] != ref.quote:
                    raise ValueError("stage quote no longer matches frozen material")
        for direction in self.directions:
            if not set(direction.baseline_direction_ids) <= baseline_ids:
                raise ValueError("direction refers outside baseline")
            if self.analysis_mode == "evidence_only" and (direction.case_context_quote or direction.origin != "material"):
                raise ValueError("case context cannot enter autonomous directions")
        if not set(self.baseline_priorities) <= {m.evidence_key for m in self.materials}:
            raise ValueError("baseline priority is outside material scope")
        return self


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
    evidence_classifications: ReportClassifications | None = None
    stage_analysis: StageAnalysis | None = None

    @model_validator(mode="after")
    def _classification_contract(self):
        if self.prompt_version in ("final-report:evidence-only:v1", "final-report:case-guided:v1"):
            if self.schema_version != "1.2" or self.stage_analysis is None or self.evidence_classifications is None:
                raise ValueError("stage report requires frozen analysis and classifications")
            expected = "evidence_only" if self.prompt_version == "final-report:evidence-only:v1" else "case_guided"
            if self.stage_analysis.analysis_mode != expected:
                raise ValueError("stage report mode mismatch")
        elif self.stage_analysis is not None:
            raise ValueError("legacy reports cannot acquire a stage implicitly")
        elif self.prompt_version == "final-report:v4":
            if self.schema_version != "1.1" or self.evidence_classifications is None:
                raise ValueError("classified report requires its frozen classification contract")
        elif self.evidence_classifications is not None:
            raise ValueError("legacy reports cannot acquire classifications implicitly")
        return self


class ReportGenerationStatus(BaseModel):
    """Generation row plus the published manifest (completed reads only)."""

    model_config = ConfigDict(frozen=True)

    generation: ReportGenerationInput
    report: dict[str, Any] | None = None
