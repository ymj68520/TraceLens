from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
        if not value.startswith("rec_") or len(value) != 68:
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
    case_description: str = ""
    generated_at: str
    generated_by: str
    generator_version: str
    platforms: list[str]
    task_ids: list[str]
    evidence: list[EvidenceSource]
    directory: list[dict[str, Any]]
    categories: list[CategoryIndex]
    analysis: dict[str, Any] = Field(default_factory=dict)
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
