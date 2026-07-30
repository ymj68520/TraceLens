# Cross-Platform Forensic Report Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the durable, versioned report snapshot core, background generation lifecycle, HTTP API, stable record protocol, pagination shards, and online search index used by every later report feature.

**Architecture:** The Python service owns report creation. A metadata repository assigns monotonically increasing versions, a scope resolver freezes task/case inputs, adapters stream normalized records into a staging directory, and a snapshot writer atomically publishes immutable manifests and page shards. FastAPI exposes version history, generation progress, manifests, category pages, and snapshot-local search without changing the legacy case-report APIs.

**Tech Stack:** Python 3, FastAPI, Pydantic 2, SQLite, asyncio, pathlib, hashlib, pytest, pytest-asyncio, httpx

## Global Constraints

- Reports contain both structured artifacts and the existing five-chapter AI analysis.
- Support both single-task (`task`) and multi-image case (`case`) scopes through one protocol.
- Deliver online browsing and offline HTML ZIP packages; PDF and DOCX are out of scope.
- Include every parsed artifact, not only evidence marked relevant to the case.
- Highlight deleted, recovered, high-risk, relevant, and analysis-referenced records.
- Published report versions are immutable; regeneration always creates a new monotonically increasing version.
- Sensitive values remain unmasked and are stored verbatim in snapshots.
- Offline packages include approved thumbnails and small previews only; large/original evidence remains a path-and-hash reference.
- Platforms and categories are emitted from actual non-empty data; never create empty Android, Windows, or Linux sections.
- One evidence item may contain multiple platforms.
- A non-critical adapter/category failure produces a ready report with warnings; manifest, shard-index, or publication failure fails the whole version.
- Existing `/api/llm/case-report/{task_id}` and `/api/llm/case-report-by-case/{case_id}` APIs remain available during migration.
- Online and offline renderers consume the same manifest, page, record, attachment, search-result, and analysis-reference shapes.
- Snapshot readers never execute arbitrary SQL supplied by HTTP clients.
- Source forensic databases are opened read-only and are never migrated or mutated by report generation.
- Report package paths are controlled relative paths; evidence names never become output paths without sanitization.
- The unrelated existing modification at `.superpowers/sdd/2026-07-29-miui-backup-forensics-phase1/final-remediation-round-report.md` must not be staged or committed.

## Shared Interface Contract

This plan establishes the names consumed by all later plans.

```python
# python_service/httpserver/services/forensic_report/models.py
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

class AdapterContext(BaseModel):
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
    def iter_records(self, context: AdapterContext, category: CategorySpec) -> Iterator[ReportRecord]: ...
```

The HTTP resource contract is:

```text
POST /api/reports
GET  /api/reports?scope_type=task|case&scope_id=<id>
GET  /api/reports/{report_id}/status
GET  /api/reports/{report_id}/manifest
GET  /api/reports/{report_id}/categories/{category_id}/pages/{page}
GET  /api/reports/{report_id}/search?q=<query>&offset=0&limit=50
```

---

### Task 1: Define the report protocol and stable identifiers

**Files:**
- Create: `python_service/httpserver/services/forensic_report/__init__.py`
- Create: `python_service/httpserver/services/forensic_report/models.py`
- Create: `python_service/httpserver/services/forensic_report/ids.py`
- Test: `python_service/tests/unit/forensic_report/test_models.py`
- Test: `python_service/tests/unit/forensic_report/test_ids.py`

**Interfaces:**
- Consumes: Pydantic 2 `BaseModel`, `Field`, Python `Enum`, `hashlib.sha256`.
- Produces: `ScopeType`, `ReportStatus`, `DataState`, `Severity`, `SourceFingerprint`, `EvidenceSource`, `ReportAttachment`, `AnalysisReference`, `ReportRecord`, `CategorySpec`, `ProbeResult`, `AdapterContext`, `AdapterWarning`, `ReportVersion`, `ReportManifest`, `PageShard`, `SearchHit`, `stable_record_id(...)`, and `safe_segment(...)`.

- [ ] **Step 1: Write failing model and identifier tests**

```python
# python_service/tests/unit/forensic_report/test_ids.py
from httpserver.services.forensic_report.ids import safe_segment, stable_record_id


def test_stable_record_id_ignores_pagination_order():
    first = stable_record_id(
        evidence_id="task-1",
        platform="android",
        category="sms",
        source_table="sms_messages",
        source_record_id="42",
    )
    second = stable_record_id("task-1", "android", "sms", "sms_messages", "42")
    assert first == second
    assert first.startswith("rec_")
    assert len(first) == 68


def test_safe_segment_rejects_path_traversal_and_is_deterministic():
    assert safe_segment("微信/聊天 ../ records") == safe_segment("微信/聊天 ../ records")
    assert "/" not in safe_segment("微信/聊天 ../ records")
    assert ".." not in safe_segment("微信/聊天 ../ records")
```

```python
# python_service/tests/unit/forensic_report/test_models.py
from pydantic import ValidationError
import pytest

from httpserver.services.forensic_report.models import (
    DataState,
    ReportRecord,
    Severity,
)


def test_report_record_preserves_sensitive_values_verbatim():
    record = ReportRecord(
        record_id="rec_" + "a" * 64,
        category="wifi",
        title="Home WiFi",
        source_table="wifi_networks",
        source_record_id="7",
        data_state=DataState.EXISTING,
        severity=Severity.HIGH,
        fields={"pre_shared_key": "CorrectHorseBatteryStaple"},
    )
    assert record.fields["pre_shared_key"] == "CorrectHorseBatteryStaple"


def test_record_rejects_non_prefixed_identifier():
    with pytest.raises(ValidationError):
        ReportRecord(
            record_id="7",
            category="wifi",
            title="Home WiFi",
            source_table="wifi_networks",
            source_record_id="7",
        )
```

- [ ] **Step 2: Run the tests and confirm the modules do not exist**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_models.py tests/unit/forensic_report/test_ids.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'httpserver.services.forensic_report'`.

- [ ] **Step 3: Implement the protocol models**

```python
# python_service/httpserver/services/forensic_report/models.py
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
```

```python
# python_service/httpserver/services/forensic_report/ids.py
import hashlib
import json
import re
import unicodedata


def stable_record_id(
    evidence_id: str,
    platform: str,
    category: str,
    source_table: str,
    source_record_id: str,
) -> str:
    canonical = json.dumps(
        [evidence_id, platform, category, source_table, str(source_record_id)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "rec_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def safe_segment(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", normalized).strip("-_")[:48]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{slug or 'item'}-{digest}"
```

Export all public models and helpers from `forensic_report/__init__.py`.

- [ ] **Step 4: Run the protocol tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_models.py tests/unit/forensic_report/test_ids.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the protocol**

```bash
git add python_service/httpserver/services/forensic_report python_service/tests/unit/forensic_report/test_models.py python_service/tests/unit/forensic_report/test_ids.py
git commit -m "feat(report): define snapshot protocol"
```

---

### Task 2: Add the report metadata repository and immutable version allocation

**Files:**
- Create: `python_service/httpserver/services/forensic_report/repository.py`
- Test: `python_service/tests/unit/forensic_report/test_repository.py`

**Interfaces:**
- Consumes: `ScopeType`, `ReportStatus`, `ReportVersion`, `AdapterWarning` from Task 1.
- Produces: `ReportRepository(db_path: Path)`, `create_version(...) -> ReportVersion`, `get(report_id) -> ReportVersion | None`, `list_versions(scope_type, scope_id) -> list[ReportVersion]`, `list_unfinished() -> list[ReportVersion]`, `mark_generating(...)`, `update_progress(...)`, `mark_ready(...)`, and `mark_failed(...)`.

- [ ] **Step 1: Write failing repository tests**

```python
# python_service/tests/unit/forensic_report/test_repository.py
from pathlib import Path

import pytest

from httpserver.services.forensic_report.models import ReportStatus, ScopeType
from httpserver.services.forensic_report.repository import ReportRepository


def test_versions_increase_per_scope_and_not_globally(tmp_path: Path):
    repo = ReportRepository(tmp_path / "reports.db")
    one = repo.create_version(ScopeType.TASK, "task-a", "A", ["task-a"])
    two = repo.create_version(ScopeType.TASK, "task-a", "A", ["task-a"])
    other = repo.create_version(ScopeType.TASK, "task-b", "B", ["task-b"])
    assert (one.version, two.version, other.version) == (1, 2, 1)


def test_published_version_cannot_return_to_generating(tmp_path: Path):
    repo = ReportRepository(tmp_path / "reports.db")
    version = repo.create_version(ScopeType.TASK, "task-a", "A", ["task-a"])
    repo.mark_generating(version.report_id, "resolve-scope")
    repo.mark_ready(version.report_id, "task/task-a/report/manifest.json", [])
    with pytest.raises(ValueError, match="immutable"):
        repo.mark_generating(version.report_id, "retry")
    assert repo.get(version.report_id).status is ReportStatus.READY
```

- [ ] **Step 2: Run the tests and verify the missing repository failure**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_repository.py -v
```

Expected: collection fails because `forensic_report.repository` does not exist.

- [ ] **Step 3: Implement SQLite-backed metadata storage**

Use `BEGIN IMMEDIATE` while calculating the next version so two workers cannot allocate the same version.

```python
# python_service/httpserver/services/forensic_report/repository.py
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import AdapterWarning, ReportStatus, ReportVersion, ScopeType


class ReportRepository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS report_versions (
                    report_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    task_ids_json TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    generated_at TEXT,
                    manifest_path TEXT,
                    offline_bundle_path TEXT,
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(scope_type, scope_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_report_scope
                    ON report_versions(scope_type, scope_id, version DESC);
            """)

    def create_version(
        self,
        scope_type: ScopeType,
        scope_id: str,
        title: str,
        task_ids: list[str],
    ) -> ReportVersion:
        report_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_version "
                "FROM report_versions WHERE scope_type = ? AND scope_id = ?",
                (scope_type.value, scope_id),
            ).fetchone()
            version = int(row["next_version"])
            conn.execute(
                """INSERT INTO report_versions
                   (report_id, version, scope_type, scope_id, status, title,
                    task_ids_json, stage, progress, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?)""",
                (
                    report_id,
                    version,
                    scope_type.value,
                    scope_id,
                    ReportStatus.QUEUED.value,
                    title,
                    json.dumps(task_ids),
                    created_at,
                ),
            )
            conn.commit()
        return self.get(report_id)

    def _assert_mutable(self, conn: sqlite3.Connection, report_id: str) -> None:
        row = conn.execute(
            "SELECT status FROM report_versions WHERE report_id = ?", (report_id,)
        ).fetchone()
        if row is None:
            raise KeyError(report_id)
        if row["status"] in (ReportStatus.READY.value, ReportStatus.FAILED.value):
            raise ValueError("published report version is immutable")

    def mark_generating(self, report_id: str, stage: str) -> None:
        with self._connect() as conn:
            self._assert_mutable(conn, report_id)
            conn.execute(
                "UPDATE report_versions SET status = ?, stage = ?, progress = 1 "
                "WHERE report_id = ?",
                (ReportStatus.GENERATING.value, stage, report_id),
            )

    def update_progress(self, report_id: str, stage: str, progress: int) -> None:
        with self._connect() as conn:
            self._assert_mutable(conn, report_id)
            conn.execute(
                "UPDATE report_versions SET stage = ?, progress = ? WHERE report_id = ?",
                (stage, max(0, min(progress, 99)), report_id),
            )

    def mark_ready(
        self, report_id: str, manifest_path: str, warnings: list[AdapterWarning]
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            self._assert_mutable(conn, report_id)
            conn.execute(
                """UPDATE report_versions
                   SET status = ?, stage = 'ready', progress = 100,
                       generated_at = ?, manifest_path = ?, warnings_json = ?
                   WHERE report_id = ?""",
                (
                    ReportStatus.READY.value,
                    now,
                    manifest_path,
                    json.dumps([w.model_dump(mode="json") for w in warnings]),
                    report_id,
                ),
            )

    def mark_failed(self, report_id: str, stage: str, error: str) -> None:
        with self._connect() as conn:
            self._assert_mutable(conn, report_id)
            conn.execute(
                "UPDATE report_versions SET status = ?, stage = ?, error = ? "
                "WHERE report_id = ?",
                (ReportStatus.FAILED.value, stage, error, report_id),
            )

    def get(self, report_id: str) -> ReportVersion | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM report_versions WHERE report_id = ?", (report_id,)
            ).fetchone()
        return self._to_model(row) if row else None

    def list_versions(
        self, scope_type: ScopeType, scope_id: str
    ) -> list[ReportVersion]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM report_versions WHERE scope_type = ? AND scope_id = ? "
                "ORDER BY version DESC",
                (scope_type.value, scope_id),
            ).fetchall()
        return [self._to_model(row) for row in rows]

    def list_unfinished(self) -> list[ReportVersion]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM report_versions WHERE status IN (?, ?) "
                "ORDER BY created_at",
                (ReportStatus.QUEUED.value, ReportStatus.GENERATING.value),
            ).fetchall()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: sqlite3.Row) -> ReportVersion:
        return ReportVersion(
            report_id=row["report_id"],
            version=row["version"],
            scope_type=row["scope_type"],
            scope_id=row["scope_id"],
            status=row["status"],
            title=row["title"],
            task_ids=json.loads(row["task_ids_json"]),
            stage=row["stage"],
            progress=row["progress"],
            generated_at=row["generated_at"],
            manifest_path=row["manifest_path"],
            offline_bundle_path=row["offline_bundle_path"],
            warnings=[AdapterWarning.model_validate(v) for v in json.loads(row["warnings_json"])],
            error=row["error"],
        )
```

- [ ] **Step 4: Run repository tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_repository.py -v
```

Expected: all tests pass, including the immutable-state assertion.

- [ ] **Step 5: Commit repository storage**

```bash
git add python_service/httpserver/services/forensic_report/repository.py python_service/tests/unit/forensic_report/test_repository.py
git commit -m "feat(report): persist immutable report versions"
```

---

### Task 3: Stream adapters into atomic page shards and a snapshot-local search index

**Files:**
- Create: `python_service/httpserver/services/forensic_report/search_index.py`
- Create: `python_service/httpserver/services/forensic_report/snapshot_writer.py`
- Test: `python_service/tests/unit/forensic_report/test_snapshot_writer.py`
- Test: `python_service/tests/unit/forensic_report/test_search_index.py`

**Interfaces:**
- Consumes: Task 1 models and `safe_segment(...)`.
- Produces: `SnapshotWriter(report_root: Path, generator_version: str)`, `write(...) -> Path`, `SnapshotSearchIndex(path)`, `add_document(...)`, and `search(query, offset, limit) -> tuple[int, list[SearchHit]]`.

- [ ] **Step 1: Write failing snapshot and search tests**

```python
# python_service/tests/unit/forensic_report/test_snapshot_writer.py
import json
from pathlib import Path

from httpserver.services.forensic_report.models import (
    AdapterContext,
    CategorySpec,
    DataState,
    EvidenceSource,
    ProbeResult,
    ReportRecord,
    ReportVersion,
    ScopeType,
)
from httpserver.services.forensic_report.snapshot_writer import SnapshotWriter


class FakeAdapter:
    name = "fake"
    platform = "android"

    def probe(self, context):
        return ProbeResult(available=True)

    def categories(self, context):
        return [CategorySpec(
            category_id="android.sms",
            platform="android",
            title="短信",
            renderer="chat",
            source_table="sms_messages",
            page_size=2,
            searchable_fields=["body", "address"],
        )]

    def iter_records(self, context, category):
        for row_id in range(1, 4):
            yield ReportRecord(
                record_id="rec_" + f"{row_id:064x}",
                category=category.category_id,
                title=f"message {row_id}",
                source_table="sms_messages",
                source_record_id=str(row_id),
                data_state=DataState.DELETED if row_id == 2 else DataState.EXISTING,
                fields={"body": f"验证码 {row_id}", "address": "13800138000"},
            )


def test_writer_publishes_pages_only_after_manifest_is_complete(tmp_path: Path):
    version = ReportVersion(
        report_id="r1", version=1, scope_type=ScopeType.TASK,
        scope_id="task-1", status="generating", title="Task report",
        task_ids=["task-1"],
    )
    evidence = EvidenceSource(evidence_id="task-1", task_id="task-1", name="phone")
    context = AdapterContext(
        scope_type=ScopeType.TASK, scope_id="task-1", evidence_id="task-1",
        task_id="task-1", evidence_name="phone", db_paths={}, source_fingerprints={},
    )
    final_dir = SnapshotWriter(tmp_path, "test").write(
        version=version,
        title="Task report",
        case_description="",
        evidence=[evidence],
        contexts=[context],
        adapters=[FakeAdapter()],
        analysis={},
    )
    manifest = json.loads((final_dir / "manifest.json").read_text("utf-8"))
    category = manifest["categories"][0]
    assert category["total"] == 3
    assert category["deleted"] == 1
    assert category["pages"] == 2
    assert not (tmp_path / ".staging" / "r1").exists()
    assert all((final_dir / path).exists() for path in category["page_paths"])
```

```python
# python_service/tests/unit/forensic_report/test_search_index.py
from pathlib import Path

from httpserver.services.forensic_report.search_index import SnapshotSearchIndex


def test_search_matches_chinese_phone_path_and_hash(tmp_path: Path):
    index = SnapshotSearchIndex(tmp_path / "search.sqlite3")
    index.add_document(
        kind="record", title="短信验证码", search_text="验证码 13800138000 /data/mmssms.db abcdef1234",
        record_id="rec_" + "a" * 64, evidence_id="e1", platform="android",
        category_id="android.sms", page=1,
    )
    for query in ("验证码", "13800138000", "/data/mmssms.db", "abcdef1234"):
        total, hits = index.search(query, 0, 10)
        assert total == 1
        assert hits[0].record_id == "rec_" + "a" * 64
```

- [ ] **Step 2: Run tests and confirm missing writer/index modules**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_snapshot_writer.py tests/unit/forensic_report/test_search_index.py -v
```

Expected: collection fails for both missing modules.

- [ ] **Step 3: Implement the search index**

Use a report-local SQLite database and `instr(casefolded_text, casefolded_query)` rather than a tokenizer-dependent FTS configuration, so Chinese, paths, phone numbers, and hashes have deterministic substring behavior.

```python
# python_service/httpserver/services/forensic_report/search_index.py
import sqlite3
from pathlib import Path

from .models import SearchHit


class SnapshotSearchIndex:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS search_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    record_id TEXT,
                    evidence_id TEXT,
                    platform TEXT,
                    category_id TEXT,
                    page INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_search_record ON search_documents(record_id);
                CREATE INDEX IF NOT EXISTS idx_search_category ON search_documents(category_id, page);
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add_document(self, **document) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO search_documents
                   (kind, title, search_text, record_id, evidence_id, platform,
                    category_id, page) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    document["kind"], document["title"], document["search_text"].casefold(),
                    document.get("record_id"), document.get("evidence_id"),
                    document.get("platform"), document.get("category_id"),
                    document.get("page"),
                ),
            )

    def search(self, query: str, offset: int, limit: int) -> tuple[int, list[SearchHit]]:
        needle = query.strip().casefold()
        if not needle:
            return 0, []
        where = "instr(search_text, ?) > 0"
        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM search_documents WHERE {where}", (needle,)
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM search_documents WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
                (needle, limit, offset),
            ).fetchall()
        hits = [SearchHit(
            record_id=row["record_id"], kind=row["kind"], title=row["title"],
            snippet=row["search_text"][:240], matched_field="search_text",
            evidence_id=row["evidence_id"], platform=row["platform"],
            category_id=row["category_id"], page=row["page"],
        ) for row in rows]
        return total, hits
```

- [ ] **Step 4: Implement atomic snapshot publication and streaming pagination**

The writer must serialize each record exactly once, flush a page at `CategorySpec.page_size`, calculate page statistics while streaming, write `manifest.json` last inside staging, then rename staging to the final immutable directory.

```python
# python_service/httpserver/services/forensic_report/snapshot_writer.py
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .ids import safe_segment
from .models import (
    AdapterContext, AdapterWarning, CategoryIndex, EvidenceSource,
    ReportAdapter, ReportManifest, ReportStatus, ReportVersion, Severity,
)
from .search_index import SnapshotSearchIndex


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class SnapshotWriter:
    def __init__(self, report_root: Path, generator_version: str):
        self.report_root = Path(report_root)
        self.generator_version = generator_version

    def write(
        self,
        *,
        version: ReportVersion,
        title: str,
        case_description: str,
        evidence: list[EvidenceSource],
        contexts: list[AdapterContext],
        adapters: Iterable[ReportAdapter],
        analysis: dict,
    ) -> Path:
        staging = self.report_root / ".staging" / version.report_id
        final_dir = self.report_root / version.scope_type.value / safe_segment(version.scope_id) / version.report_id
        if final_dir.exists():
            raise FileExistsError(f"immutable report already exists: {final_dir}")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        search = SnapshotSearchIndex(staging / "search.sqlite3")
        warnings: list[AdapterWarning] = []
        indexes: list[CategoryIndex] = []
        platforms: set[str] = set()

        for context in contexts:
            for adapter in adapters:
                try:
                    probe = adapter.probe(context)
                except Exception as exc:
                    warnings.append(AdapterWarning(
                        adapter=adapter.name, evidence_id=context.evidence_id,
                        code="probe_failed", message=str(exc),
                    ))
                    continue
                if not probe.available:
                    continue
                for category in adapter.categories(context):
                    try:
                        index = self._write_category(staging, search, context, adapter, category)
                    except Exception as exc:
                        warnings.append(AdapterWarning(
                            adapter=adapter.name, evidence_id=context.evidence_id,
                            category_id=category.category_id, code="category_failed", message=str(exc),
                        ))
                        continue
                    if index.total > 0:
                        indexes.append(index)
                        platforms.add(category.platform)

        directory = self._build_directory(evidence, indexes)
        generated_at = datetime.now(timezone.utc).isoformat()
        manifest = ReportManifest(
            report_id=version.report_id,
            version=version.version,
            scope_type=version.scope_type,
            scope_id=version.scope_id,
            status=ReportStatus.READY,
            title=title,
            case_description=case_description,
            generated_at=generated_at,
            generated_by="TraceLens",
            generator_version=self.generator_version,
            platforms=sorted(platforms),
            task_ids=version.task_ids,
            evidence=evidence,
            directory=directory,
            categories=indexes,
            analysis=analysis,
            source_fingerprints={
                f"{item.evidence_id}:{name}": fingerprint
                for item in evidence for name, fingerprint in item.source_fingerprints.items()
            },
            warnings=warnings,
        )
        (staging / "manifest.json").write_bytes(_canonical_json(manifest.model_dump(mode="json")))
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final_dir)
        return final_dir

    def _write_category(self, staging, search, context, adapter, category):
        category_dir = staging / "data" / safe_segment(context.evidence_id) / category.platform / safe_segment(category.category_id)
        category_dir.mkdir(parents=True, exist_ok=True)
        page_records = []
        page_paths = []
        totals = {"total": 0, "deleted": 0, "recovered": 0, "high_risk": 0, "relevant": 0, "referenced": 0}

        def flush_page(page_number: int) -> None:
            payload = {
                "schema_version": "1.0", "category_id": category.category_id,
                "page": page_number, "page_size": category.page_size,
                "total": totals["total"],
                "records": [r.model_dump(mode="json") for r in page_records],
            }
            payload["sha256"] = hashlib.sha256(_canonical_json(payload)).hexdigest()
            relative = category_dir.relative_to(staging) / f"{page_number}.json"
            (staging / relative).write_bytes(_canonical_json(payload))
            page_paths.append(relative.as_posix())

        for record in adapter.iter_records(context, category):
            totals["total"] += 1
            totals["deleted"] += record.data_state.value == "deleted"
            totals["recovered"] += record.data_state.value == "recovered"
            totals["high_risk"] += record.severity in (Severity.HIGH, Severity.CRITICAL)
            totals["relevant"] += record.is_relevant
            totals["referenced"] += bool(record.analysis_references)
            page_number = math.ceil(totals["total"] / category.page_size)
            search_text = " ".join([
                record.title, record.source_path or "", *record.hashes.values(),
                *[str(record.fields.get(name, "")) for name in category.searchable_fields],
            ])
            search.add_document(
                kind="record", title=record.title, search_text=search_text,
                record_id=record.record_id, evidence_id=context.evidence_id,
                platform=category.platform, category_id=category.category_id,
                page=page_number,
            )
            page_records.append(record)
            if len(page_records) == category.page_size:
                flush_page(page_number)
                page_records.clear()
        if page_records:
            flush_page(math.ceil(totals["total"] / category.page_size))
        return CategoryIndex(
            category_id=category.category_id, evidence_id=context.evidence_id,
            platform=category.platform, title=category.title, renderer=category.renderer,
            page_size=category.page_size, pages=len(page_paths), page_paths=page_paths,
            **totals,
        )

    @staticmethod
    def _build_directory(evidence, indexes):
        result = []
        for item in evidence:
            item_indexes = [index for index in indexes if index.evidence_id == item.evidence_id]
            platforms = []
            for platform in sorted({index.platform for index in item_indexes}):
                categories = [index.model_dump(mode="json") for index in item_indexes if index.platform == platform]
                platforms.append({"id": platform, "title": platform.title(), "children": categories})
            result.append({"id": item.evidence_id, "title": item.name, "children": platforms})
        return result
```

The implementation may extract `_write_category` helpers into private functions, but its public signatures and output fields must remain exactly as specified.

- [ ] **Step 5: Run snapshot and search tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_snapshot_writer.py tests/unit/forensic_report/test_search_index.py -v
```

Expected: all tests pass; the fixture produces two page shards and one manifest.

- [ ] **Step 6: Commit the snapshot writer**

```bash
git add python_service/httpserver/services/forensic_report/search_index.py python_service/httpserver/services/forensic_report/snapshot_writer.py python_service/tests/unit/forensic_report/test_snapshot_writer.py python_service/tests/unit/forensic_report/test_search_index.py
git commit -m "feat(report): publish paged report snapshots"
```

---

### Task 4: Freeze task scope, database paths, source fingerprints, and existing analysis

**Files:**
- Create: `python_service/httpserver/services/forensic_report/source_resolver.py`
- Create: `python_service/httpserver/services/forensic_report/analysis_adapter.py`
- Test: `python_service/tests/unit/forensic_report/test_source_resolver.py`
- Test: `python_service/tests/unit/forensic_report/test_analysis_adapter.py`

**Interfaces:**
- Consumes: `CppBackendService.get_task(task_id)`, `CppBackendService.get_task_databases(task_id)`, legacy `get_case_report_from_db(...)`, and Task 1 models.
- Produces: `SourceResolver.resolve_task(task_id) -> ResolvedScope`, `fingerprint_file(path) -> SourceFingerprint`, `AnalysisChaptersAdapter.load_task(files_db_path, task_id) -> dict`, and `ResolvedScope` with `title`, `case_description`, `evidence`, `contexts`, and `analysis`.

- [ ] **Step 1: Write failing resolver tests with a fake C++ backend**

```python
# python_service/tests/unit/forensic_report/test_source_resolver.py
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from httpserver.services.forensic_report.models import ScopeType
from httpserver.services.forensic_report.source_resolver import SourceResolver


@pytest.mark.asyncio
async def test_task_resolution_uses_backend_paths_and_freezes_fingerprints(tmp_path: Path):
    files_db = tmp_path / "files.db"
    android_db = tmp_path / "android.db"
    files_db.write_bytes(b"files")
    android_db.write_bytes(b"android")
    backend = AsyncMock()
    backend.get_task.return_value = {
        "id": "task-1", "image_path": "/evidence/phone.E01",
        "case_description": "fraud", "output_files_db": str(files_db),
    }
    backend.get_task_databases.return_value = [
        {"type": "files", "path": str(files_db)},
        {"type": "android", "path": str(android_db)},
    ]
    resolved = await SourceResolver(backend).resolve_task("task-1")
    assert resolved.scope_type is ScopeType.TASK
    assert resolved.evidence[0].db_paths["android"] == str(android_db)
    assert resolved.evidence[0].source_fingerprints["android"].size == 7
    assert resolved.contexts[0].evidence_id == "task-1"
```

```python
# python_service/tests/unit/forensic_report/test_analysis_adapter.py
import sqlite3
from pathlib import Path

from httpserver.services.forensic_report.analysis_adapter import AnalysisChaptersAdapter


def test_load_task_keeps_existing_markdown_and_reference_tokens(tmp_path: Path):
    db = tmp_path / "files.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE case_analysis (
            task_id TEXT PRIMARY KEY, case_description TEXT, filtered_files TEXT,
            case_report TEXT, created_at INTEGER, updated_at INTEGER)""")
        conn.execute(
            "INSERT INTO case_analysis VALUES (?, ?, ?, ?, ?, ?)",
            ("task-1", "fraud", '["/data/a.db"]',
             "# 案件概述\n[[file:/data/a.db]]\n[[event:CREATE@1700000000/data]]", 1, 2),
        )
    analysis = AnalysisChaptersAdapter().load_task(str(db), "task-1")
    assert analysis["markdown"].startswith("# 案件概述")
    assert analysis["generated_at"] == "2"
    assert analysis["filtered_files"] == ["/data/a.db"]
```

- [ ] **Step 2: Run tests and verify missing resolver/adapter failures**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_source_resolver.py tests/unit/forensic_report/test_analysis_adapter.py -v
```

Expected: collection fails because the two modules are absent.

- [ ] **Step 3: Implement read-only fingerprints and task resolution**

```python
# python_service/httpserver/services/forensic_report/source_resolver.py
from __future__ import annotations

import hashlib
from pathlib import Path
from pydantic import BaseModel

from .analysis_adapter import AnalysisChaptersAdapter
from .models import AdapterContext, EvidenceSource, ScopeType, SourceFingerprint


class ResolvedScope(BaseModel):
    scope_type: ScopeType
    scope_id: str
    title: str
    case_description: str
    task_ids: list[str]
    evidence: list[EvidenceSource]
    contexts: list[AdapterContext]
    analysis: dict


def fingerprint_file(path: str) -> SourceFingerprint:
    candidate = Path(path)
    if not candidate.is_file():
        return SourceFingerprint(path=str(candidate), exists=False)
    stat = candidate.stat()
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return SourceFingerprint(
        path=str(candidate), exists=True, size=stat.st_size,
        mtime_ns=stat.st_mtime_ns, sha256=digest.hexdigest(),
    )


class SourceResolver:
    def __init__(self, cpp_backend, analysis_adapter=None):
        self.cpp_backend = cpp_backend
        self.analysis_adapter = analysis_adapter or AnalysisChaptersAdapter()

    async def resolve_task(self, task_id: str) -> ResolvedScope:
        task = await self.cpp_backend.get_task(task_id)
        if not task:
            raise LookupError(f"task not found: {task_id}")
        database_rows = await self.cpp_backend.get_task_databases(task_id)
        db_paths = {
            str(row.get("type") or row.get("database_type") or "").lower(): row["path"]
            for row in database_rows if row.get("path")
        }
        if task.get("output_files_db"):
            db_paths.setdefault("files", task["output_files_db"])
        fingerprints = {name: fingerprint_file(path) for name, path in db_paths.items()}
        evidence_name = Path(task.get("image_path") or task_id).name
        evidence = EvidenceSource(
            evidence_id=task_id, task_id=task_id, name=evidence_name,
            image_path=task.get("image_path"), db_paths=db_paths,
            source_fingerprints=fingerprints,
        )
        analysis = self.analysis_adapter.load_task(db_paths.get("files", ""), task_id)
        relevant_paths = set(analysis.get("filtered_files", []))
        context = AdapterContext(
            scope_type=ScopeType.TASK, scope_id=task_id, evidence_id=task_id,
            task_id=task_id, evidence_name=evidence_name, db_paths=db_paths,
            source_fingerprints=fingerprints, relevant_paths=relevant_paths,
        )
        return ResolvedScope(
            scope_type=ScopeType.TASK, scope_id=task_id,
            title=f"{evidence_name} 取证报告",
            case_description=task.get("case_description", ""), task_ids=[task_id],
            evidence=[evidence], contexts=[context], analysis=analysis,
        )
```

- [ ] **Step 4: Implement the legacy analysis snapshot reader**

```python
# python_service/httpserver/services/forensic_report/analysis_adapter.py
from ..case_analysis.db_utils import get_case_report_from_db


class AnalysisChaptersAdapter:
    def load_task(self, files_db_path: str, task_id: str) -> dict:
        row = get_case_report_from_db(files_db_path, task_id) if files_db_path else None
        if not row:
            return {"markdown": "", "generated_at": None, "filtered_files": []}
        return {
            "markdown": row.get("case_report") or "",
            "generated_at": str(row.get("updated_at") or ""),
            "filtered_files": row.get("filtered_files") or [],
        }
```

Do not parse references yet; Plan 4 adds structured forward and reverse links while preserving this shape.

- [ ] **Step 5: Run resolver and analysis tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_source_resolver.py tests/unit/forensic_report/test_analysis_adapter.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit source freezing**

```bash
git add python_service/httpserver/services/forensic_report/source_resolver.py python_service/httpserver/services/forensic_report/analysis_adapter.py python_service/tests/unit/forensic_report/test_source_resolver.py python_service/tests/unit/forensic_report/test_analysis_adapter.py
git commit -m "feat(report): freeze task report sources"
```

---

### Task 5: Orchestrate durable background generation

**Files:**
- Create: `python_service/httpserver/services/forensic_report/service.py`
- Modify: `python_service/httpserver/services/service_manager.py:34-47,80-109,112-132,158-167`
- Modify: `python_service/httpserver/config.py:193-200`
- Test: `python_service/tests/unit/forensic_report/test_service.py`

**Interfaces:**
- Consumes: `ReportRepository`, `SourceResolver`, `SnapshotWriter`, and a list of `ReportAdapter` implementations.
- Produces: `ForensicReportService.start(scope_type, scope_id) -> ReportVersion`, `resume_unfinished()`, `get_status(report_id)`, `list_versions(...)`, `get_manifest_path(...)`, `get_page_path(...)`, `search(...)`, `initialize()`, and `shutdown()`; `ServiceManager.forensic_report_service`.

- [ ] **Step 1: Write a failing orchestration test**

```python
# python_service/tests/unit/forensic_report/test_service.py
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from httpserver.services.forensic_report.models import ReportStatus, ScopeType
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.forensic_report.service import ForensicReportService
from httpserver.services.forensic_report.snapshot_writer import SnapshotWriter
from httpserver.services.forensic_report.source_resolver import ResolvedScope


@pytest.mark.asyncio
async def test_generation_reaches_ready_and_is_recoverable_from_repository(tmp_path: Path):
    resolver = AsyncMock()
    resolver.resolve_task.return_value = ResolvedScope(
        scope_type=ScopeType.TASK, scope_id="task-1", title="Task report",
        case_description="", task_ids=["task-1"], evidence=[], contexts=[], analysis={},
    )
    repo = ReportRepository(tmp_path / "reports.db")
    service = ForensicReportService(
        repository=repo, resolver=resolver,
        writer=SnapshotWriter(tmp_path / "snapshots", "test"), adapters=[],
    )
    await service.initialize()
    version = await service.start(ScopeType.TASK, "task-1")
    for _ in range(50):
        status = service.get_status(version.report_id)
        if status.status in (ReportStatus.READY, ReportStatus.FAILED):
            break
        await asyncio.sleep(0.01)
    assert status.status is ReportStatus.READY
    assert repo.get(version.report_id).manifest_path.endswith("manifest.json")
    await service.shutdown()
```

- [ ] **Step 2: Run the service test and verify it fails**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_service.py -v
```

Expected: collection fails because `forensic_report.service` is missing.

- [ ] **Step 3: Implement the service and task lifecycle**

```python
# python_service/httpserver/services/forensic_report/service.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .models import AdapterWarning, ReportStatus, ScopeType


class ForensicReportService:
    def __init__(self, repository, resolver, writer, adapters):
        self.repository = repository
        self.resolver = resolver
        self.writer = writer
        self.adapters = list(adapters)
        self._tasks: dict[str, asyncio.Task] = {}

    async def initialize(self) -> None:
        await self.resume_unfinished()

    async def shutdown(self) -> None:
        pending = list(self._tasks.values())
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()

    async def resume_unfinished(self) -> None:
        # Queued/generating rows have durable metadata but no trustworthy completed
        # snapshot. Mark them failed; a retry creates a new immutable version.
        for version in self.repository.list_unfinished():
            self.repository.mark_failed(
                version.report_id,
                "service_restart",
                "generation interrupted by service restart; create a new version",
            )

    async def start(self, scope_type: ScopeType, scope_id: str):
        resolved = await self._resolve(scope_type, scope_id)
        version = self.repository.create_version(
            scope_type, scope_id, resolved.title, resolved.task_ids
        )
        task = asyncio.create_task(self._generate(version.report_id, resolved))
        self._tasks[version.report_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(version.report_id, None))
        return version

    async def _resolve(self, scope_type: ScopeType, scope_id: str):
        if scope_type is ScopeType.TASK:
            return await self.resolver.resolve_task(scope_id)
        return await self.resolver.resolve_case(scope_id)

    async def _generate(self, report_id: str, resolved) -> None:
        stage = "snapshot"
        try:
            self.repository.mark_generating(report_id, "snapshot")
            version = self.repository.get(report_id)
            final_dir = await asyncio.to_thread(
                self.writer.write,
                version=version,
                title=resolved.title,
                case_description=resolved.case_description,
                evidence=resolved.evidence,
                contexts=resolved.contexts,
                adapters=self.adapters,
                analysis=resolved.analysis,
            )
            manifest_path = final_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text("utf-8"))
            self.repository.mark_ready(
                report_id,
                str(manifest_path.relative_to(self.writer.report_root)),
                [
                    AdapterWarning.model_validate(item)
                    for item in manifest.get("warnings", [])
                ],
            )
        except Exception as exc:
            self.repository.mark_failed(report_id, stage, str(exc))

    def get_status(self, report_id: str):
        return self.repository.get(report_id)

    def list_versions(self, scope_type: ScopeType, scope_id: str):
        return self.repository.list_versions(scope_type, scope_id)

    def _ready_dir(self, report_id: str) -> Path:
        version = self.repository.get(report_id)
        if version is None:
            raise KeyError(report_id)
        if version.status is not ReportStatus.READY:
            raise RuntimeError(f"report is not ready: {version.status.value}")
        return self.writer.report_root / Path(version.manifest_path).parent

    def get_manifest_path(self, report_id: str) -> Path:
        return self._ready_dir(report_id) / "manifest.json"

    def get_page_path(self, report_id: str, category_id: str, page: int) -> Path:
        manifest = json.loads(self.get_manifest_path(report_id).read_text("utf-8"))
        category = next((c for c in manifest["categories"] if c["category_id"] == category_id), None)
        if category is None or page < 1 or page > len(category["page_paths"]):
            raise KeyError(f"unknown category page: {category_id}/{page}")
        return self._ready_dir(report_id) / category["page_paths"][page - 1]

    def search(self, report_id: str, query: str, offset: int, limit: int):
        from .search_index import SnapshotSearchIndex
        return SnapshotSearchIndex(self._ready_dir(report_id) / "search.sqlite3").search(
            query, offset, limit
        )
```

Replace the placeholder body in `resume_unfinished` before committing by adding `ReportRepository.list_unfinished()` and this concrete implementation:

```python
async def resume_unfinished(self) -> None:
    for version in self.repository.list_unfinished():
        self.repository.mark_failed(
            version.report_id,
            "service_restart",
            "generation interrupted by service restart; create a new version",
        )
```

`list_unfinished()` must select rows whose status is `queued` or `generating`. This explicit recovery rule avoids silently claiming an incomplete staging directory is valid.

- [ ] **Step 4: Add report settings and ServiceManager lifecycle**

Add these settings to `Settings`:

```python
report_output_dir: str = Field(
    default="build/data/reports", alias="FORENSIC_REPORT_DIR"
)
report_generator_version: str = Field(
    default="1.0.0", alias="FORENSIC_REPORT_GENERATOR_VERSION"
)
```

Add `self._forensic_report_service = None`, initialize it after `CppBackendService`, shut it down before the C++ backend, and expose:

```python
@property
def forensic_report_service(self):
    if self._forensic_report_service is None:
        from pathlib import Path
        from .forensic_report.repository import ReportRepository
        from .forensic_report.service import ForensicReportService
        from .forensic_report.snapshot_writer import SnapshotWriter
        from .forensic_report.source_resolver import SourceResolver

        root = Path(self.settings.report_output_dir)
        if not root.is_absolute():
            from ..config import get_project_root
            root = get_project_root() / root
        self._forensic_report_service = ForensicReportService(
            repository=ReportRepository(root / "reports.db"),
            resolver=SourceResolver(self.cpp_backend),
            writer=SnapshotWriter(root / "snapshots", self.settings.report_generator_version),
            adapters=[],
        )
    return self._forensic_report_service
```

During `initialize()`, call `await self.forensic_report_service.initialize()`. Plan 3 replaces the empty adapter list with the production registry.

- [ ] **Step 5: Run service and ServiceManager tests**

Add assertions to `test_service.py` for interrupted jobs, then run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_service.py -v
```

Expected: all tests pass; queued/generating rows become failed after initialization.

- [ ] **Step 6: Commit orchestration**

```bash
git add python_service/httpserver/services/forensic_report/service.py python_service/httpserver/services/forensic_report/repository.py python_service/httpserver/services/service_manager.py python_service/httpserver/config.py python_service/tests/unit/forensic_report/test_service.py
git commit -m "feat(report): orchestrate durable snapshot jobs"
```

---

### Task 6: Expose the report HTTP API and preserve legacy routes

**Files:**
- Create: `python_service/httpserver/routes/forensic_reports.py`
- Modify: `python_service/httpserver/routes/__init__.py:1-4`
- Modify: `python_service/httpserver/main.py:193-212`
- Modify: `web/vite.config.js:18-41`
- Test: `python_service/tests/unit/forensic_report/test_routes.py`

**Interfaces:**
- Consumes: `ServiceManager.forensic_report_service` and Task 1 models.
- Produces: all HTTP endpoints in the Shared Interface Contract with consistent 404, 409, and 422 behavior.

- [ ] **Step 1: Write failing route tests**

```python
# python_service/tests/unit/forensic_report/test_routes.py
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import forensic_reports


def make_client(service):
    app = FastAPI()
    app.include_router(forensic_reports.router, prefix="/api/reports")
    app.dependency_overrides[forensic_reports.get_report_service] = lambda: service
    return TestClient(app)


def test_create_and_list_report_versions():
    service = Mock()
    service.start = AsyncMock(return_value={
        "report_id": "r1", "version": 1, "scope_type": "task", "scope_id": "t1",
        "status": "queued", "title": "T", "task_ids": ["t1"],
        "stage": "queued", "progress": 0, "warnings": [],
    })
    service.list_versions.return_value = []
    client = make_client(service)
    response = client.post("/api/reports", json={"scope_type": "task", "scope_id": "t1"})
    assert response.status_code == 202
    assert response.json()["report_id"] == "r1"
    assert client.get("/api/reports?scope_type=task&scope_id=t1").status_code == 200


def test_manifest_returns_conflict_until_ready():
    service = Mock()
    service.get_manifest_path.side_effect = RuntimeError("report is not ready: generating")
    client = make_client(service)
    response = client.get("/api/reports/r1/manifest")
    assert response.status_code == 409
```

- [ ] **Step 2: Run route tests and verify missing route import**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_routes.py -v
```

Expected: import fails because `httpserver.routes.forensic_reports` is missing.

- [ ] **Step 3: Implement request models and routes**

```python
# python_service/httpserver/routes/forensic_reports.py
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..services import get_service_manager
from ..services.forensic_report.models import ReportVersion, ScopeType

router = APIRouter()


class CreateReportRequest(BaseModel):
    scope_type: ScopeType
    scope_id: str = Field(min_length=1)


class SearchResponse(BaseModel):
    total: int
    offset: int
    limit: int
    hits: list[dict]


def get_report_service():
    return get_service_manager().forensic_report_service


@router.post("", response_model=ReportVersion, status_code=202)
async def create_report(request: CreateReportRequest, service=Depends(get_report_service)):
    try:
        return await service.start(request.scope_type, request.scope_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=list[ReportVersion])
def list_reports(
    scope_type: ScopeType = Query(...), scope_id: str = Query(..., min_length=1),
    service=Depends(get_report_service),
):
    return service.list_versions(scope_type, scope_id)


@router.get("/{report_id}/status", response_model=ReportVersion)
def report_status(report_id: str, service=Depends(get_report_service)):
    version = service.get_status(report_id)
    if version is None:
        raise HTTPException(status_code=404, detail="report not found")
    return version


def _file_response(loader, *args):
    try:
        path: Path = loader(*args)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not path.is_file():
        raise HTTPException(status_code=500, detail="published report resource is missing")
    return FileResponse(path, media_type="application/json")


@router.get("/{report_id}/manifest")
def manifest(report_id: str, service=Depends(get_report_service)):
    return _file_response(service.get_manifest_path, report_id)


@router.get("/{report_id}/categories/{category_id}/pages/{page}")
def category_page(report_id: str, category_id: str, page: int, service=Depends(get_report_service)):
    if page < 1:
        raise HTTPException(status_code=422, detail="page must be >= 1")
    return _file_response(service.get_page_path, report_id, category_id, page)


@router.get("/{report_id}/search", response_model=SearchResponse)
def search(
    report_id: str, q: str = Query(min_length=1), offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200), service=Depends(get_report_service),
):
    try:
        total, hits = service.search(report_id, q, offset, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SearchResponse(
        total=total, offset=offset, limit=limit,
        hits=[hit.model_dump(mode="json") for hit in hits],
    )
```

- [ ] **Step 4: Register the router and Vite proxy**

In `routes/__init__.py`, import and export `forensic_reports`. In `_register_routes` add:

```python
app.include_router(
    forensic_reports.router,
    prefix="/api/reports",
    tags=["Forensic Reports"],
)
```

Place the Vite-specific proxy before the broad `/api` entry:

```javascript
'/api/reports': {
  target: 'http://localhost:8090',
  changeOrigin: true,
},
```

Do not alter or remove the existing `case_analysis` registration.

- [ ] **Step 5: Run route and legacy route tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_routes.py tests/unit/test_dll_route.py -v
```

Expected: all selected tests pass.

- [ ] **Step 6: Run the complete foundation test slice**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report -v
```

Expected: all forensic-report tests pass with no writes to source forensic databases.

- [ ] **Step 7: Commit API registration**

```bash
git add python_service/httpserver/routes/forensic_reports.py python_service/httpserver/routes/__init__.py python_service/httpserver/main.py web/vite.config.js python_service/tests/unit/forensic_report/test_routes.py
git commit -m "feat(report): expose versioned report API"
```

---

## Plan 1 Completion Gate

Before starting Plan 2, verify all of the following:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report -v
cd /home/ymj68520/projects/Forensics/TraceLens
git status --short
```

Expected:

- Report protocol tests pass.
- Version numbers are scope-local and monotonic.
- Ready/failed versions reject mutation.
- A snapshot publishes only after manifest and shards exist.
- Search matches Chinese text, paths, phone numbers, and hashes.
- A task scope freezes actual database paths and fingerprints.
- Background status survives HTTP refresh through `reports.db`.
- Legacy case-report routes remain registered.
- Git status does not show the MIUI remediation document staged.

Next plan: `docs/superpowers/plans/2026-07-30-cross-platform-forensic-report-frontend.md`.
