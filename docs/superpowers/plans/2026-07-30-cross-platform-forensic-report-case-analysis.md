# Cross-Platform Forensic Report Case Aggregation and Analysis References Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the report system from single-task snapshots to multi-image case snapshots, cross-evidence search and timeline content, structured five-chapter references, reverse record links, and report entry points from the existing intelligence workspace.

**Architecture:** `SourceResolver.resolve_case()` retrieves the authoritative case from the C++ backend, resolves each associated task independently, preserves task/evidence order, and loads the case-level five-chapter report. A case aggregation adapter emits derived cross-evidence timeline and important-evidence categories without duplicating platform records. A strict reference resolver parses existing `[[file:...]]` and `[[event:...]]` tokens, resolves only exact snapshot targets, annotates records before page publication, and records unresolved references explicitly.

**Tech Stack:** Python 3, FastAPI, Pydantic 2, SQLite read-only access, pytest, React 18, React Router 6, Vitest, React Testing Library

## Global Constraints

- Reports contain both structured artifacts and the existing five-chapter AI analysis.
- Support both single-task (`task`) and multi-image case (`case`) scopes through one protocol.
- Case snapshots are grouped as `evidence item -> platform -> category` and search spans every included evidence item.
- Case snapshots include a cross-evidence timeline and case-level important evidence.
- The five-chapter report uses the existing task-level `case_analysis` row for task scope and the case-level database for case scope.
- Existing `[[file:完整路径]]` and `[[event:事件类型@时间窗口/目录]]` tokens remain valid.
- Reference resolution is exact and deterministic; missing targets are shown as unresolved and are never guessed fuzzily.
- Every resolved record displays the chapters that reference it.
- Include every parsed artifact; relevance and chapter references are metadata, not filters.
- Published report versions are immutable; source analysis changes require a new report version.
- A missing task or database within a case creates a warning for that evidence when at least one valid evidence item remains; a case with no resolvable task fails.
- Existing legacy analysis APIs and evidence-reanalysis behavior remain available.
- The unrelated existing modification at `.superpowers/sdd/2026-07-29-miui-backup-forensics-phase1/final-remediation-round-report.md` must not be staged or committed.

## Consumed Interfaces

Plans 1–3 must be complete. This plan consumes `ResolvedScope`, `SnapshotWriter`, the default platform adapters, `ReportRecord.analysis_references`, and the report workspace renderer registry.

This plan adds the following snapshot analysis shape:

```json
{
  "markdown": "## 案件概述...",
  "generated_at": "...",
  "chapters": [
    {"title": "案件概述", "markdown": "...", "references": ["ref_..."]}
  ],
  "references": [
    {
      "reference_id": "ref_...",
      "chapter": "证据分析",
      "token": "[[file:/data/a.db]]",
      "kind": "file",
      "status": "resolved",
      "target": {
        "record_id": "rec_...",
        "evidence_id": "task-1",
        "platform": "common",
        "category_id": "common.files",
        "page": 1
      }
    }
  ]
}
```

---

### Task 1: Add authoritative case retrieval to the C++ backend client

**Files:**
- Modify: `python_service/httpserver/services/cpp_backend.py:130-170`
- Test: `python_service/tests/unit/forensic_report/test_cpp_backend_case.py`

**Interfaces:**
- Consumes: C++ routes `GET /api/cases/{case_id}` and `GET /api/tasks/list`.
- Produces: `CppBackendService.get_case(case_id: str) -> dict[str, Any] | None`.

- [ ] **Step 1: Write a failing client test**

```python
# python_service/tests/unit/forensic_report/test_cpp_backend_case.py
from unittest.mock import AsyncMock

import pytest

from httpserver.config import Settings
from httpserver.services.cpp_backend import CppBackendService


@pytest.mark.asyncio
async def test_get_case_returns_case_and_maps_404_to_none():
    service = CppBackendService(Settings())
    service._request = AsyncMock(side_effect=[
        {"id": "case-1", "name": "Fraud", "task_ids": ["t1", "t2"]},
        {"success": False, "status": 404, "error": "not found"},
    ])
    assert (await service.get_case("case-1"))["task_ids"] == ["t1", "t2"]
    assert await service.get_case("missing") is None
```

- [ ] **Step 2: Run the test and verify the method is absent**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_cpp_backend_case.py -v
```

Expected: `AttributeError: 'CppBackendService' object has no attribute 'get_case'`.

- [ ] **Step 3: Implement exact case retrieval**

```python
# add to CppBackendService
async def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
    result = await self._request("GET", f"/api/cases/{case_id}")
    if result.get("status") == 404:
        return None
    if result.get("success") is False and result.get("error"):
        raise RuntimeError(f"failed to load case {case_id}: {result['error']}")
    return result
```

Do not duplicate the direct `httpx` proxy implementation from `multi_analysis.py`; the report resolver must use the shared backend client.

- [ ] **Step 4: Run the client test**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_cpp_backend_case.py -v
```

Expected: pass.

- [ ] **Step 5: Commit case retrieval**

```bash
git add python_service/httpserver/services/cpp_backend.py python_service/tests/unit/forensic_report/test_cpp_backend_case.py
git commit -m "feat(report): resolve case metadata through backend"
```

---

### Task 2: Resolve multi-image case sources and case-level analysis

**Files:**
- Modify: `python_service/httpserver/services/forensic_report/source_resolver.py`
- Modify: `python_service/httpserver/services/forensic_report/analysis_adapter.py`
- Test: `python_service/tests/unit/forensic_report/test_case_source_resolver.py`
- Test: `python_service/tests/unit/forensic_report/test_case_analysis_adapter.py`

**Interfaces:**
- Consumes: `CppBackendService.get_case`, `resolve_task`, and `get_case_db_path(case_id)`.
- Produces: `SourceResolver.resolve_case(case_id) -> ResolvedScope` and `AnalysisChaptersAdapter.load_case(case_id) -> dict`.

- [ ] **Step 1: Write failing case source tests**

```python
# python_service/tests/unit/forensic_report/test_case_source_resolver.py
from unittest.mock import AsyncMock

import pytest

from httpserver.services.forensic_report.models import ScopeType
from httpserver.services.forensic_report.source_resolver import SourceResolver


@pytest.mark.asyncio
async def test_case_resolution_preserves_case_task_order_and_warns_for_missing_task():
    backend = AsyncMock()
    backend.get_case.return_value = {
        "id": "case-1", "name": "Fraud", "description": "cross image",
        "task_ids": ["task-b", "missing", "task-a"],
    }
    backend.get_task.side_effect = lambda task_id: None if task_id == "missing" else {
        "id": task_id, "image_path": f"/evidence/{task_id}.E01", "output_files_db": "",
    }
    backend.get_task_databases.return_value = []
    resolver = SourceResolver(backend)
    resolved = await resolver.resolve_case("case-1")
    assert resolved.scope_type is ScopeType.CASE
    assert resolved.task_ids == ["task-b", "task-a"]
    assert [item.task_id for item in resolved.evidence] == ["task-b", "task-a"]
    assert resolved.warnings[0].code == "task_missing"
```

Update `ResolvedScope` with:

```python
warnings: list[AdapterWarning] = Field(default_factory=list)
```

```python
# python_service/tests/unit/forensic_report/test_case_analysis_adapter.py
# Create build/data/cases/case-1/case-1.db with case_analysis row keyed by case-1.
# Instantiate AnalysisChaptersAdapter(case_db_resolver=lambda _: db_path).
# Assert load_case("case-1") returns markdown, generated_at, and filtered files.
```

- [ ] **Step 2: Run tests and confirm missing methods/field**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_case_source_resolver.py tests/unit/forensic_report/test_case_analysis_adapter.py -v
```

Expected: failures for `resolve_case`, `load_case`, and `ResolvedScope.warnings`.

- [ ] **Step 3: Refactor task resolution into a reusable evidence resolver**

Add a private method with this exact contract:

```python
async def _resolve_evidence(
    self,
    task_id: str,
    *,
    scope_type: ScopeType,
    scope_id: str,
) -> tuple[EvidenceSource, AdapterContext]:
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
    analysis = self.analysis_adapter.load_task(db_paths.get("files", ""), task_id)
    evidence = EvidenceSource(
        evidence_id=task_id,
        task_id=task_id,
        name=evidence_name,
        image_path=task.get("image_path"),
        db_paths=db_paths,
        source_fingerprints=fingerprints,
    )
    context = AdapterContext(
        scope_type=scope_type,
        scope_id=scope_id,
        evidence_id=task_id,
        task_id=task_id,
        evidence_name=evidence_name,
        db_paths=db_paths,
        source_fingerprints=fingerprints,
        relevant_paths=set(analysis.get("filtered_files", [])),
    )
    return evidence, context
```

`resolve_task()` delegates to it. This avoids calling `resolve_task()` from case resolution and then rebuilding context scope fields.

- [ ] **Step 4: Implement case-level analysis loading**

```python
# analysis_adapter.py
from ..case_analysis.db_utils import get_case_report_from_db
from ..case_analysis.db_utils import get_case_db_path


class AnalysisChaptersAdapter:
    def __init__(self, case_db_resolver=get_case_db_path):
        self.case_db_resolver = case_db_resolver

    # keep load_task unchanged

    def load_case(self, case_id: str) -> dict:
        case_db = self.case_db_resolver(case_id)
        row = get_case_report_from_db(case_db, case_id)
        if not row:
            return {"markdown": "", "generated_at": None, "filtered_files": []}
        return {
            "markdown": row.get("case_report") or "",
            "generated_at": str(row.get("updated_at") or ""),
            "filtered_files": row.get("filtered_files") or [],
        }
```

The relative imports above resolve to `httpserver.services.case_analysis.db_utils`; do not create a second case path helper.

- [ ] **Step 5: Implement `resolve_case`**

```python
async def resolve_case(self, case_id: str) -> ResolvedScope:
    case = await self.cpp_backend.get_case(case_id)
    if not case:
        raise LookupError(f"case not found: {case_id}")
    evidence = []
    contexts = []
    warnings = []
    for task_id in case.get("task_ids", []):
        try:
            item, context = await self._resolve_evidence(
                task_id, scope_type=ScopeType.CASE, scope_id=case_id,
            )
        except LookupError:
            warnings.append(AdapterWarning(
                adapter="source_resolver", evidence_id=task_id,
                code="task_missing", message=f"task not found: {task_id}",
            ))
            continue
        evidence.append(item)
        contexts.append(context)
    if not contexts:
        raise LookupError(f"case has no resolvable tasks: {case_id}")
    return ResolvedScope(
        scope_type=ScopeType.CASE,
        scope_id=case_id,
        title=f"{case.get('name') or case_id} 取证报告",
        case_description=case.get("description", ""),
        task_ids=[item.task_id for item in evidence],
        evidence=evidence,
        contexts=contexts,
        analysis=self.analysis_adapter.load_case(case_id),
        warnings=warnings,
    )
```

- [ ] **Step 6: Run case resolution tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_case_source_resolver.py tests/unit/forensic_report/test_case_analysis_adapter.py -v
```

Expected: pass.

- [ ] **Step 7: Commit case scope resolution**

```bash
git add python_service/httpserver/services/forensic_report/source_resolver.py python_service/httpserver/services/forensic_report/analysis_adapter.py python_service/tests/unit/forensic_report/test_case_source_resolver.py python_service/tests/unit/forensic_report/test_case_analysis_adapter.py
git commit -m "feat(report): freeze multi-image case sources"
```

---

### Task 3: Emit cross-evidence timeline and important-evidence categories

**Files:**
- Create: `python_service/httpserver/services/forensic_report/case_aggregation.py`
- Modify: `python_service/httpserver/services/forensic_report/snapshot_writer.py`
- Test: `python_service/tests/unit/forensic_report/test_case_aggregation.py`
- Test: `python_service/tests/integration/forensic_report/test_case_snapshot.py`

**Interfaces:**
- Consumes: normalized records from all adapter categories before page serialization.
- Produces: derived categories `case.timeline` and `case.important_evidence` for case scope only.

- [ ] **Step 1: Write failing aggregation tests**

```python
# python_service/tests/unit/forensic_report/test_case_aggregation.py
from httpserver.services.forensic_report.case_aggregation import CaseAggregationCollector
from httpserver.services.forensic_report.models import ReportRecord, Severity


def record(record_id, evidence_id, timestamp=None, severity='info', relevant=False):
    return ReportRecord(
        record_id=record_id, category='source', title=record_id,
        timestamp=timestamp, source_table='rows', source_record_id=record_id,
        severity=severity, is_relevant=relevant,
        fields={'_evidence_id': evidence_id},
    )


def test_collector_orders_timeline_and_deduplicates_important_records():
    collector = CaseAggregationCollector()
    collector.observe(record('rec_' + '1' * 64, 'e2', timestamp=20, severity=Severity.HIGH))
    collector.observe(record('rec_' + '2' * 64, 'e1', timestamp=10, relevant=True))
    collector.observe(record('rec_' + '2' * 64, 'e1', timestamp=10, relevant=True))
    assert [item.record_id for item in collector.timeline_records()] == [
        'rec_' + '2' * 64, 'rec_' + '1' * 64,
    ]
    assert len(collector.important_records()) == 2
```

- [ ] **Step 2: Run the test and verify the collector is missing**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_case_aggregation.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement a bounded collector**

```python
# case_aggregation.py
class CaseAggregationCollector:
    def __init__(self):
        self._timeline = {}
        self._important = {}

    def observe(self, record: ReportRecord, evidence_id: str | None = None) -> None:
        evidence = evidence_id or str(record.fields.get("_evidence_id", ""))
        projected = record.model_copy(deep=True)
        projected.fields = {**projected.fields, "evidence_id": evidence}
        if projected.timestamp is not None:
            self._timeline[projected.record_id] = projected
        if (
            projected.is_relevant
            or projected.severity in (Severity.HIGH, Severity.CRITICAL)
            or projected.data_state in (DataState.DELETED, DataState.RECOVERED)
            or projected.analysis_references
        ):
            self._important[projected.record_id] = projected

    def timeline_records(self) -> list[ReportRecord]:
        return sorted(
            self._timeline.values(),
            key=lambda item: (item.timestamp, item.record_id),
        )

    def important_records(self) -> list[ReportRecord]:
        rank = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2,
                Severity.LOW: 3, Severity.INFO: 4}
        return sorted(
            self._important.values(),
            key=lambda item: (rank[item.severity], -(item.timestamp or 0), item.record_id),
        )
```

The collector stores one normalized projection per record. It must not include full duplicated attachment binary data; attachments remain metadata-only at this stage.

- [ ] **Step 4: Add snapshot writer aggregation hooks**

Refactor `SnapshotWriter._write_category` to accept an optional callback while retaining its existing parameters:

```python
def _write_category(
    self,
    staging: Path,
    search: SnapshotSearchIndex,
    context: AdapterContext,
    adapter: ReportAdapter,
    category: CategorySpec,
    on_record=None,
) -> CategoryIndex:
    # Keep the page-writing body from Plan 1. Immediately after a record is
    # returned by adapter.iter_records(...) and before statistics/page flush:
    if on_record is not None:
        on_record(record, context.evidence_id)
```

For `ScopeType.CASE`, instantiate the collector before iterating adapters. After all source categories are written, write two derived categories using a small `StaticRecordsAdapter` internal helper:

```python
CategorySpec(
    category_id="case.timeline", platform="case", title="跨检材综合时间线",
    renderer="timeline", source_table="snapshot_records", page_size=100,
    searchable_fields=["title", "evidence_id", "source_path"],
)
CategorySpec(
    category_id="case.important_evidence", platform="case", title="案件重点证据",
    renderer="table", source_table="snapshot_records", page_size=100,
    searchable_fields=["title", "evidence_id", "source_path"],
)
```

Do not create these categories when their record lists are empty.

- [ ] **Step 5: Preserve source warnings in the manifest**

Add `initial_warnings: list[AdapterWarning] = []` to `SnapshotWriter.write(...)`, initialize its local warnings with that list, and pass `resolved.warnings` from `ForensicReportService._generate(...)`.

- [ ] **Step 6: Write and run a case snapshot integration test**

The fixture contains two tasks from different platforms with timestamps and risk/relevance flags. Assert:

- directory evidence order matches case `task_ids` order;
- both evidence groups retain their own platform categories;
- `case.timeline` contains records from both evidence items in timestamp order;
- `case.important_evidence` deduplicates records;
- source resolver warnings are in `manifest.warnings`.

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_case_aggregation.py tests/integration/forensic_report/test_case_snapshot.py -v
```

Expected: pass.

- [ ] **Step 7: Commit case aggregation**

```bash
git add python_service/httpserver/services/forensic_report/case_aggregation.py python_service/httpserver/services/forensic_report/snapshot_writer.py python_service/httpserver/services/forensic_report/service.py python_service/tests/unit/forensic_report/test_case_aggregation.py python_service/tests/integration/forensic_report/test_case_snapshot.py
git commit -m "feat(report): aggregate case timeline and evidence"
```

---

### Task 4: Parse five-chapter Markdown and resolve exact snapshot references

**Files:**
- Create: `python_service/httpserver/services/forensic_report/references.py`
- Modify: `python_service/httpserver/services/forensic_report/models.py`
- Modify: `python_service/httpserver/services/forensic_report/snapshot_writer.py`
- Modify: `python_service/httpserver/services/forensic_report/search_index.py`
- Test: `python_service/tests/unit/forensic_report/test_references.py`
- Test: `python_service/tests/integration/forensic_report/test_reference_snapshot.py`

**Interfaces:**
- Consumes: five-chapter Markdown, normalized records, category page numbers.
- Produces: `parse_chapters(markdown)`, `parse_reference_tokens(markdown)`, `ReferenceResolver`, structured analysis references in manifest, and reverse `ReportRecord.analysis_references`.

- [ ] **Step 1: Add exact reference models**

Add to `models.py`:

```python
class ReferenceStatus(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"

class ReferenceTarget(BaseModel):
    record_id: str | None = None
    evidence_id: str | None = None
    platform: str | None = None
    category_id: str | None = None
    page: int | None = None
    section_id: str | None = None

class StructuredAnalysisReference(BaseModel):
    reference_id: str
    chapter: str
    token: str
    kind: str
    status: ReferenceStatus
    target: ReferenceTarget | None = None
    reason: str | None = None
```

Keep the existing lightweight `AnalysisReference(chapter, token)` on records.

- [ ] **Step 2: Write failing parser/resolver tests**

```python
# python_service/tests/unit/forensic_report/test_references.py
from httpserver.services.forensic_report.references import (
    ReferenceResolver, parse_chapters, parse_reference_tokens,
)


def test_parser_preserves_five_chapters_and_reference_tokens():
    markdown = """## 案件概述
[[file:/data/a.db]]

## 时间线梳理
[[event:CREATE@1700000000/data]]"""
    chapters = parse_chapters(markdown)
    tokens = parse_reference_tokens(markdown)
    assert [chapter.title for chapter in chapters] == ['案件概述', '时间线梳理']
    assert [token.kind for token in tokens] == ['file', 'event']


def test_file_resolution_requires_exact_normalized_path():
    resolver = ReferenceResolver()
    resolver.observe_record(
        evidence_id='e1', platform='common', category_id='common.files', page=1,
        record_id='rec_' + 'a' * 64, source_path='/data/a.db',
        event_type=None, timestamp=None,
    )
    resolved = resolver.resolve_token('证据分析', '[[file:/data/a.db]]')
    missing = resolver.resolve_token('证据分析', '[[file:/data/A.db]]')
    assert resolved.status == 'resolved'
    assert missing.status == 'unresolved'
    assert missing.reason == 'exact snapshot target not found'
```

- [ ] **Step 3: Run tests and verify missing module/models**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_references.py -v
```

Expected: collection fails.

- [ ] **Step 4: Implement strict parsing**

Use these exact regular expressions:

```python
CHAPTER_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
TOKEN_RE = re.compile(
    r"\[\[file:(?P<file>[^\]]+)\]\]|"
    r"\[\[event:(?P<event_type>[A-Za-z_]+)@(?P<window>\d+)/(?P<directory>[^\]]*)\]\]"
)
```

`parse_chapters` splits on `##` headings and retains chapter Markdown. If no headings exist, return one chapter titled `智能研判` rather than dropping the text.

Stable reference IDs use SHA-256 over `[chapter, token, occurrence_index]` and prefix `ref_`.

- [ ] **Step 5: Implement exact file and event resolution**

`ReferenceResolver.observe_record(...)` builds:

- exact source path index: normalized slash separators only; preserve case;
- event index by exact uppercase event type plus exact integer time window and directory.

For event tokens, calculate each event record's window with the same expression used by existing report generation:

```python
window = int(timestamp) // 60
parent_dir = str(PurePosixPath(source_path).parent).lstrip("/")
```

The token window is already numeric and must match exactly. If several records match an exact token, resolve to section `case.timeline` for case scope or `timeline.events` for task scope, and include the first matching page; do not choose one record arbitrarily.

- [ ] **Step 6: Resolve references before final page serialization**

Because reverse links must be present inside page shards, perform reference resolution in two deterministic passes:

1. First adapter pass writes normalized records to temporary JSONL category streams while building the reference index and aggregation collector.
2. Resolve analysis tokens after all records are indexed.
3. Second pass reads JSONL streams, adds lightweight `AnalysisReference` values to matching records, and writes final page shards/search documents.
4. Delete temporary streams before manifest publication.

Create focused private methods rather than loading all records in RAM:

```python
def _snapshot_to_streams(
    self,
    staging: Path,
    contexts: list[AdapterContext],
    adapters: list[ReportAdapter],
    resolver: ReferenceResolver,
    collector: CaseAggregationCollector | None,
) -> list[CategoryStream]:
    """Write one JSONL stream per non-empty category and index each record."""


def _resolve_analysis(
    self,
    markdown: str,
    resolver: ReferenceResolver,
    scope_type: ScopeType,
) -> dict:
    """Return manifest analysis chapters/references and resolver reverse-link map."""


def _streams_to_pages(
    self,
    staging: Path,
    streams: list[CategoryStream],
    reverse_links: dict[str, list[AnalysisReference]],
    search: SnapshotSearchIndex,
) -> list[CategoryIndex]:
    """Read streams sequentially, attach reverse links, and emit final page shards."""
```

Add this internal model near the writer:

```python
class CategoryStream(BaseModel):
    context: AdapterContext
    category: CategorySpec
    path: str
    total: int
```

The staging directory may contain `streams/*.jsonl` during generation, but final published reports must not.

- [ ] **Step 7: Add chapter text and reference tokens to search**

For each chapter, call `SnapshotSearchIndex.add_document` with `kind="chapter"`, title, full chapter text, and `category_id=None`. Search hits can therefore navigate either to a record or to the analysis section.

- [ ] **Step 8: Run reference unit and integration tests**

The integration fixture must assert:

- exact file token resolves to the file record and page;
- case file references resolve to the correct evidence item when the same basename exists elsewhere;
- exact event token resolves to timeline section;
- missing/case-different path remains unresolved;
- target record's `analysis_references` contains chapter/token;
- no `streams` directory remains after publication.

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_references.py tests/integration/forensic_report/test_reference_snapshot.py -v
```

Expected: pass.

- [ ] **Step 9: Commit structured references**

```bash
git add python_service/httpserver/services/forensic_report/references.py python_service/httpserver/services/forensic_report/models.py python_service/httpserver/services/forensic_report/snapshot_writer.py python_service/httpserver/services/forensic_report/search_index.py python_service/tests/unit/forensic_report/test_references.py python_service/tests/integration/forensic_report/test_reference_snapshot.py
git commit -m "feat(report): resolve analysis references"
```

---

### Task 5: Render five chapters with snapshot-aware reference navigation

**Files:**
- Create: `web/src/components/reports/AnalysisChapters.jsx`
- Create: `web/src/components/reports/ReportReference.jsx`
- Modify: `web/src/components/case-intelligence/markdownRenderer.jsx`
- Modify: `web/src/components/reports/ReportWorkspace.jsx`
- Modify: `web/src/components/reports/renderers/RecordBadges.jsx`
- Test: `web/src/components/reports/AnalysisChapters.test.jsx`
- Test: `web/src/components/case-intelligence/markdownRenderer.test.jsx`

**Interfaces:**
- Consumes: `manifest.analysis.chapters`, structured references, `onNavigateTarget(target)`, and legacy Markdown.
- Produces: reusable `renderCaseMarkdown(text, ctx)` with optional `resolveReference(token)`, report-specific resolved/unresolved badges, and reverse chapter links on records.

- [ ] **Step 1: Write failing reference UI tests**

```jsx
// web/src/components/reports/AnalysisChapters.test.jsx
import userEvent from '@testing-library/user-event';
import { screen } from '@testing-library/react';
import { vi } from 'vitest';
import { renderWithRouter } from '../../test/renderWithRouter';
import AnalysisChapters from './AnalysisChapters';


test('resolved references navigate and unresolved references explain failure', async () => {
  const onNavigateTarget = vi.fn();
  const analysis = {
    chapters: [{
      title: '证据分析',
      markdown: '数据库 [[file:/data/a.db]]，缺失 [[file:/data/missing.db]]',
    }],
    references: [
      { reference_id: 'ref1', chapter: '证据分析', token: '[[file:/data/a.db]]', status: 'resolved', target: { category_id: 'common.files', page: 1, record_id: 'rec1' } },
      { reference_id: 'ref2', chapter: '证据分析', token: '[[file:/data/missing.db]]', status: 'unresolved', reason: 'exact snapshot target not found' },
    ],
  };
  renderWithRouter(<AnalysisChapters analysis={analysis} onNavigateTarget={onNavigateTarget} />);
  await userEvent.click(screen.getByRole('button', { name: /a.db/ }));
  expect(onNavigateTarget).toHaveBeenCalledWith(analysis.references[0].target);
  expect(screen.getByText(/当前版本未找到目标/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests and confirm component/renderer behavior is missing**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/components/reports/AnalysisChapters.test.jsx src/components/case-intelligence/markdownRenderer.test.jsx
```

Expected: missing `AnalysisChapters` and no resolver hook in Markdown renderer.

- [ ] **Step 3: Extend the Markdown renderer without breaking CaseIntelligence**

Add optional context functions:

```javascript
// ctx additions
resolveReference?: (token) => structuredReference | null
onReferenceClick?: (reference) => void
```

At the start of `renderRef`:

```jsx
const structured = ctx.resolveReference?.(token);
if (structured) {
  const label = token.startsWith('[[file:')
    ? `📄 ${token.slice(7, -2).split('/').pop()}`
    : `⏱ ${token.slice(8, -2)}`;
  if (structured.status === 'resolved') {
    return (
      <button
        key={`${keyPrefix}-structured`}
        type="button"
        onClick={() => ctx.onReferenceClick?.(structured)}
        title={token}
        className="inline-flex items-center rounded-md border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 font-mono text-[13px] font-bold text-emerald-700 hover:bg-emerald-100 dark:border-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
      >
        {label}
      </button>
    );
  }
  return (
    <span
      key={`${keyPrefix}-unresolved`}
      title={structured.reason}
      className="inline-flex items-center rounded-md border border-amber-300 bg-amber-50 px-1.5 py-0.5 font-mono text-[13px] font-bold text-amber-700 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
    >
      ⚠ 当前版本未找到目标：{token}
    </span>
  );
}
```

If `resolveReference` is absent, preserve the existing file/event behavior exactly so `CaseIntelligence` does not regress.

- [ ] **Step 4: Implement `AnalysisChapters` and workspace navigation**

Build a map keyed by `${chapter}\0${token}`. `onNavigateTarget` must:

```javascript
if (target.category_id && target.page) {
  selectCategory(target.category_id, target.page);
  pendingScrollRecordIdRef.current = target.record_id || null;
} else if (target.section_id) {
  document.getElementById(target.section_id)?.scrollIntoView({ behavior: 'smooth' });
}
```

Render `AnalysisChapters` after structured evidence and important evidence, with `id="analysis-chapters"`.

- [ ] **Step 5: Add clickable reverse links to records**

`RecordBadges` receives `analysisReferences` and `onChapterClick`. Render one button per distinct chapter:

```jsx
<button onClick={() => onChapterClick(chapter)}>
  被 {chapter} 引用
</button>
```

The callback scrolls to `analysis-chapters` and focuses that chapter heading.

- [ ] **Step 6: Run UI tests and full frontend report suite**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/components/reports src/components/case-intelligence/markdownRenderer.test.jsx
npm run build
```

Expected: pass; old CaseIntelligence reference behavior remains covered.

- [ ] **Step 7: Commit analysis rendering**

```bash
git add web/src/components/reports/AnalysisChapters.jsx web/src/components/reports/AnalysisChapters.test.jsx web/src/components/reports/ReportReference.jsx web/src/components/case-intelligence/markdownRenderer.jsx web/src/components/case-intelligence/markdownRenderer.test.jsx web/src/components/reports/ReportWorkspace.jsx web/src/components/reports/renderers/RecordBadges.jsx
git commit -m "feat(web): navigate report analysis references"
```

---

### Task 6: Move full report ownership out of CaseIntelligence while retaining analysis controls

**Files:**
- Modify: `web/src/pages/CaseIntelligence.jsx:58-62,171-188` and report rendering/action section
- Modify: `web/src/pages/Cases.jsx:330-339`
- Test: `web/src/pages/CaseIntelligence.test.jsx`
- Test: `web/src/pages/Cases.test.jsx`

**Interfaces:**
- Consumes: new task/case report routes.
- Produces: `CaseIntelligence` links `查看最新报告版本` and `生成新版本` while retaining evidence selection, relevance toggles, re-analysis, and legacy five-chapter generation.

- [ ] **Step 1: Write failing migration tests**

```jsx
// CaseIntelligence.test.jsx
// Mock task/case stores and legacy analysis services.
// Assert the page still shows evidence controls and re-analysis controls.
// Assert it contains a link to /reports/task/task-1 or /reports/case/case-1.
// Assert it no longer renders the entire report Markdown card inline.

// Cases.test.jsx
// For a completed case, assert the report button targets /reports/case/case-1.
```

- [ ] **Step 2: Run tests and verify current inline report behavior fails expectations**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/pages/CaseIntelligence.test.jsx src/pages/Cases.test.jsx
```

Expected: failures because the report is still rendered inline and/or link labels differ.

- [ ] **Step 3: Replace inline report browsing with focused entry cards**

Keep `report` loading only to determine whether a legacy five-chapter analysis exists. Replace the full `renderCaseMarkdown(report.report, ...)` section with:

```jsx
<Card>
  <h2>结构化取证报告</h2>
  <p>报告版本包含全部结构化痕迹、跨平台目录、搜索、分页和五章研判。</p>
  <div className="flex gap-2">
    <Button onClick={() => navigate(
      caseId ? `/reports/case/${caseId}` : `/reports/task/${activeContextId}`
    )}>查看最新报告版本</Button>
    <Button variant="outline" onClick={() => navigate(
      `${caseId ? `/reports/case/${caseId}` : `/reports/task/${activeContextId}`}?generate=1`
    )}>生成新版本</Button>
  </div>
</Card>
```

The report page reads `generate=1`, creates a version once, then removes the query parameter with `navigate(..., { replace: true })` to prevent duplicate generation on refresh.

Do not remove existing `startCaseAnalysis`, `reanalyzeFiles`, relevance toggles, cluster drawers, or evidence selection.

- [ ] **Step 4: Run migration tests and build**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/pages/CaseIntelligence.test.jsx src/pages/Cases.test.jsx
npm run build
```

Expected: pass.

- [ ] **Step 5: Commit intelligence migration**

```bash
git add web/src/pages/CaseIntelligence.jsx web/src/pages/CaseIntelligence.test.jsx web/src/pages/Cases.jsx web/src/pages/Cases.test.jsx web/src/pages/ForensicReportPage.jsx
git commit -m "refactor(web): move report browsing to workspace"
```

---

## Plan 4 Completion Gate

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report tests/integration/forensic_report/test_case_snapshot.py tests/integration/forensic_report/test_reference_snapshot.py -v
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/components/reports src/components/case-intelligence src/pages/CaseIntelligence.test.jsx src/pages/Cases.test.jsx
npm run build
cd /home/ymj68520/projects/Forensics/TraceLens
git status --short
```

Expected:

- Case task order and evidence grouping are stable.
- Missing case tasks become warnings when usable evidence remains.
- Case timeline and important evidence span all evidence items.
- Search covers all evidence through the shared snapshot index.
- File/event tokens resolve only to exact snapshot targets.
- Unresolved targets remain explicit.
- Referenced records show reverse chapter links.
- CaseIntelligence retains analysis/re-analysis controls but no longer owns full report browsing.
- Legacy case-report APIs still pass existing tests.
- Git status does not show the unrelated MIUI document staged.

Next plan: `docs/superpowers/plans/2026-07-30-cross-platform-forensic-report-offline.md`.
