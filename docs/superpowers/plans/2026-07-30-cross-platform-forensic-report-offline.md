# Cross-Platform Forensic Report Offline Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe preview assets, integrity manifests, a self-contained offline HTML ZIP, offline search and pagination through the shared report workspace, bundle generation/download APIs, and end-to-end acceptance fixtures.

**Architecture:** Preview admission is a separate bounded service that copies only approved image thumbnails and small UTF-8 text excerpts into controlled report-relative paths. Integrity generation hashes every published resource and is finalized before a report becomes ready. The web app gains an offline entry that instantiates `StaticReportDataSource` against relative JSON/search shards; the backend packages the same frontend bundle and immutable snapshot resources into a ZIP. Offline export is a durable secondary job attached to a ready report version and never mutates snapshot evidence content.

**Tech Stack:** Python 3, Pillow, pathlib, hashlib, zipfile, FastAPI, pytest, React 18, Vite 5, Vitest, jsdom, Node build tooling

## Global Constraints

- Reports contain both structured artifacts and the existing five-chapter AI analysis.
- Support both task and case scopes through the same online/offline protocol.
- Offline delivery is a ZIP that opens from `index.html` without TraceLens services or network access.
- PDF and DOCX are out of scope.
- Include approved thumbnails and small text previews only; never copy large/original evidence by default.
- Original evidence path, size, MIME, and hashes remain visible whether or not a preview exists.
- Sensitive values remain unmasked in report data and approved text previews.
- Preview generation has explicit file-size, output-size, pixel, and count limits.
- Every output path is controlled and relative; reject `..`, absolute paths, symlink escapes, and names derived directly from evidence paths.
- HTML/text output is escaped or rendered by controlled React components; evidence text is never injected with `dangerouslySetInnerHTML`.
- `integrity.json` covers manifest, page shards, offline search shards, preview files, and bundled frontend assets with SHA-256.
- Report integrity means the package has not changed; it does not assert independent judicial validity of original evidence.
- Online and offline pages display the same sections, statistics, records, warnings, references, previews, and version metadata.
- A preview failure is a warning; manifest, required page, offline index, or integrity failure fails the relevant publication/export job.
- The unrelated existing modification at `.superpowers/sdd/2026-07-29-miui-backup-forensics-phase1/final-remediation-round-report.md` must not be staged or committed.

## Consumed Interfaces

Plans 1–4 must be complete. This plan consumes the immutable snapshot directory, `ReportAttachment`, `ReportRepository`, `ForensicReportService`, `ReportDataSource`, report workspace components, and structured analysis references.

This plan extends `ReportVersion` with:

```python
offline_status: str | None = None  # queued | generating | ready | failed
offline_progress: int = 0
offline_error: str | None = None
offline_bundle_path: str | None = None
```

The added HTTP resources are:

```text
GET  /api/reports/{report_id}/previews/{attachment_id}
POST /api/reports/{report_id}/offline
GET  /api/reports/{report_id}/offline/status
GET  /api/reports/{report_id}/offline
POST /api/reports/{report_id}/integrity/verify
```

---

### Task 1: Add bounded preview policy and secure evidence-path resolution

**Files:**
- Create: `python_service/httpserver/services/forensic_report/previews.py`
- Modify: `python_service/httpserver/config.py` near report settings
- Modify: `python_service/httpserver/services/forensic_report/models.py`
- Test: `python_service/tests/unit/forensic_report/test_previews.py`

**Interfaces:**
- Consumes: evidence root candidates from task metadata, `ReportAttachment`, Pillow.
- Produces: `PreviewPolicy`, `PreviewBuilder.build(...) -> ReportAttachment`, `PreviewRegistry`, and controlled attachment IDs/relative paths.

- [ ] **Step 1: Write failing preview security tests**

```python
# python_service/tests/unit/forensic_report/test_previews.py
from pathlib import Path

from PIL import Image

from httpserver.services.forensic_report.previews import PreviewBuilder, PreviewPolicy


def test_image_preview_is_thumbnail_not_original(tmp_path: Path):
    source_root = tmp_path / "evidence"
    source_root.mkdir()
    image_path = source_root / "photo.png"
    Image.new("RGB", (2000, 1000), "red").save(image_path)
    builder = PreviewBuilder(
        output_root=tmp_path / "report",
        policy=PreviewPolicy(max_source_bytes=10_000_000, max_preview_bytes=300_000,
                             max_pixels=4_000_000, max_previews=10,
                             max_text_bytes=16_384, thumbnail_size=(320, 320)),
    )
    attachment = builder.build(
        evidence_id="e1", evidence_path=str(image_path),
        allowed_roots=[source_root], file_name="photo.png",
    )
    preview = tmp_path / "report" / attachment.preview_path
    assert attachment.preview_type == "image"
    assert attachment.original_included is False
    assert preview.stat().st_size < image_path.stat().st_size
    with Image.open(preview) as rendered:
        assert rendered.width <= 320 and rendered.height <= 320


def test_preview_rejects_traversal_absolute_escape_and_symlink(tmp_path: Path):
    root = tmp_path / "evidence"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)
    builder = PreviewBuilder(tmp_path / "report", PreviewPolicy())
    for path in (root / ".." / "secret.txt", outside, root / "link.txt"):
        result = builder.build("e1", str(path), [root], "secret.txt")
        assert result.preview_path is None
        assert result.unavailable_reason
```

- [ ] **Step 2: Run tests and verify preview module is missing**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_previews.py -v
```

Expected: import failure.

- [ ] **Step 3: Add exact report preview settings**

```python
report_preview_max_source_bytes: int = Field(
    default=10 * 1024 * 1024, alias="REPORT_PREVIEW_MAX_SOURCE_BYTES"
)
report_preview_max_output_bytes: int = Field(
    default=512 * 1024, alias="REPORT_PREVIEW_MAX_OUTPUT_BYTES"
)
report_preview_max_pixels: int = Field(
    default=25_000_000, alias="REPORT_PREVIEW_MAX_PIXELS"
)
report_preview_max_count: int = Field(
    default=500, alias="REPORT_PREVIEW_MAX_COUNT"
)
report_preview_max_text_bytes: int = Field(
    default=64 * 1024, alias="REPORT_PREVIEW_MAX_TEXT_BYTES"
)
report_preview_thumbnail_width: int = Field(
    default=640, alias="REPORT_PREVIEW_THUMBNAIL_WIDTH"
)
report_preview_thumbnail_height: int = Field(
    default=640, alias="REPORT_PREVIEW_THUMBNAIL_HEIGHT"
)
```

- [ ] **Step 4: Implement secure path validation and preview admission**

```python
# previews.py
from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .models import ReportAttachment


@dataclass(frozen=True)
class PreviewPolicy:
    max_source_bytes: int = 10 * 1024 * 1024
    max_preview_bytes: int = 512 * 1024
    max_pixels: int = 25_000_000
    max_previews: int = 500
    max_text_bytes: int = 64 * 1024
    thumbnail_size: tuple[int, int] = (640, 640)


class PreviewBuilder:
    IMAGE_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif"}
    TEXT_MIME = {"text/plain", "text/csv", "application/json", "application/xml", "text/xml"}

    def __init__(self, output_root: Path, policy: PreviewPolicy):
        self.output_root = Path(output_root)
        self.policy = policy
        self.count = 0

    def build(self, evidence_id, evidence_path, allowed_roots, file_name) -> ReportAttachment:
        attachment_id = "att_" + hashlib.sha256(
            f"{evidence_id}\0{evidence_path}".encode("utf-8")
        ).hexdigest()
        base = ReportAttachment(
            attachment_id=attachment_id,
            file_name=file_name,
            evidence_path=evidence_path,
        )
        try:
            source = self._validate_source(Path(evidence_path), allowed_roots)
        except ValueError as exc:
            return base.model_copy(update={"unavailable_reason": str(exc)})
        stat = source.stat()
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        hashes = {"sha256": self._hash_file(source)}
        base = base.model_copy(update={"size": stat.st_size, "mime": mime, "hashes": hashes})
        if self.count >= self.policy.max_previews:
            return base.model_copy(update={"unavailable_reason": "preview count limit reached"})
        if stat.st_size > self.policy.max_source_bytes:
            return base.model_copy(update={"unavailable_reason": "source exceeds preview size limit"})
        try:
            if mime in self.IMAGE_MIME:
                updated = self._image_preview(base, source)
            elif mime in self.TEXT_MIME:
                updated = self._text_preview(base, source)
            else:
                return base.model_copy(update={"unavailable_reason": "preview type not allowed"})
        except (OSError, UnicodeError, UnidentifiedImageError, ValueError) as exc:
            return base.model_copy(update={"unavailable_reason": f"preview failed: {exc}"})
        self.count += 1
        return updated

    def _validate_source(self, source: Path, allowed_roots) -> Path:
        if source.is_symlink():
            raise ValueError("symlink evidence preview is not allowed")
        resolved = source.resolve(strict=True)
        roots = [Path(root).resolve(strict=True) for root in allowed_roots]
        if not any(resolved == root or root in resolved.parents for root in roots):
            raise ValueError("evidence path is outside approved roots")
        if not resolved.is_file():
            raise ValueError("evidence preview source is not a regular file")
        return resolved

    def _relative_path(self, attachment_id: str, suffix: str) -> Path:
        return Path("previews") / attachment_id[4:6] / f"{attachment_id}{suffix}"

    def _image_preview(self, attachment: ReportAttachment, source: Path) -> ReportAttachment:
        with Image.open(source) as probe:
            probe.verify()
        with Image.open(source) as image:
            width, height = image.size
            if width * height > self.policy.max_pixels:
                raise ValueError("image exceeds preview pixel limit")
            image.thumbnail(self.policy.thumbnail_size)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            relative = self._relative_path(attachment.attachment_id, ".webp")
            destination = self.output_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            image.save(destination, format="WEBP", quality=82, method=4)
        if destination.stat().st_size > self.policy.max_preview_bytes:
            destination.unlink(missing_ok=True)
            raise ValueError("generated image preview exceeds output limit")
        return attachment.model_copy(update={
            "preview_type": "image",
            "preview_path": relative.as_posix(),
            "original_included": False,
        })

    def _text_preview(self, attachment: ReportAttachment, source: Path) -> ReportAttachment:
        with source.open("rb") as handle:
            raw = handle.read(self.policy.max_text_bytes + 1)
        if b"\x00" in raw:
            raise ValueError("binary text preview is not allowed")
        truncated = len(raw) > self.policy.max_text_bytes
        text = raw[:self.policy.max_text_bytes].decode("utf-8", errors="strict")
        if truncated:
            text += "\n\n[preview truncated]"
        relative = self._relative_path(attachment.attachment_id, ".txt")
        destination = self.output_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        if destination.stat().st_size > self.policy.max_preview_bytes:
            destination.unlink(missing_ok=True)
            raise ValueError("generated text preview exceeds output limit")
        return attachment.model_copy(update={
            "preview_type": "text",
            "preview_path": relative.as_posix(),
            "original_included": False,
        })

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
```

- [ ] **Step 5: Add registry lookup by attachment ID**

```python
class PreviewRegistry:
    def __init__(self):
        self._paths: dict[str, str] = {}

    def add(self, attachment: ReportAttachment) -> None:
        if attachment.preview_path:
            self._paths[attachment.attachment_id] = attachment.preview_path

    def get(self, attachment_id: str) -> str | None:
        return self._paths.get(attachment_id)
```

Store `manifest.preview_index` as `{attachment_id: relative_path}`. Add this field to `ReportManifest` with a default empty dict.

- [ ] **Step 6: Run preview tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_previews.py -v
```

Expected: pass, including path and symlink rejection.

- [ ] **Step 7: Commit preview policy**

```bash
git add python_service/httpserver/services/forensic_report/previews.py python_service/httpserver/services/forensic_report/models.py python_service/httpserver/config.py python_service/tests/unit/forensic_report/test_previews.py
git commit -m "feat(report): secure attachment previews"
```

---

### Task 2: Integrate preview construction into snapshot publication

**Files:**
- Modify: `python_service/httpserver/services/forensic_report/source_resolver.py`
- Modify: `python_service/httpserver/services/forensic_report/models.py`
- Modify: `python_service/httpserver/services/forensic_report/snapshot_writer.py`
- Modify: `python_service/httpserver/services/forensic_report/adapters/sqlite_base.py`
- Test: `python_service/tests/integration/forensic_report/test_preview_snapshot.py`

**Interfaces:**
- Consumes: attachment evidence paths emitted by platform adapters and approved roots on each `EvidenceSource`.
- Produces: final `ReportAttachment` metadata, preview files under `previews/`, preview index, and warnings.

- [ ] **Step 1: Add approved roots to evidence/context models**

Add:

```python
# EvidenceSource and AdapterContext
approved_roots: list[str] = Field(default_factory=list)
```

In `SourceResolver._resolve_evidence`, derive roots only from authoritative task metadata and database parents:

```python
roots = []
image_path = task.get("image_path")
if image_path and Path(image_path).exists():
    roots.append(str(Path(image_path).resolve().parent))
for path in db_paths.values():
    if Path(path).exists():
        roots.append(str(Path(path).resolve().parent))
approved_roots = list(dict.fromkeys(roots))
```

Do not use filesystem root `/` or arbitrary request input.

- [ ] **Step 2: Write a failing integration test**

Create a fixture with:

- an Android message whose `media_url` points to an approved image;
- a media path outside approved roots;
- a 20 MB source exceeding policy;
- one small UTF-8 text attachment.

After snapshot publication assert:

- approved image/text previews exist under controlled `previews/att_*` paths;
- outside/large files retain path/hash metadata but no preview;
- original bytes are not copied;
- manifest warnings mention rejected preview reasons;
- preview index contains only successful previews.

- [ ] **Step 3: Normalize attachment candidates in adapters**

Add a helper to `SqliteReportAdapter`:

```python
def attachment_from_path(self, context, path, file_name=None):
    if not path:
        return None
    value = str(path)
    return ReportAttachment(
        attachment_id="att_" + hashlib.sha256(
            f"{context.evidence_id}\0{value}".encode("utf-8")
        ).hexdigest(),
        file_name=file_name or PurePosixPath(value).name or "attachment",
        evidence_path=value,
    )
```

Android media/avatar categories use this helper. Common file records should not make every file an attachment; only categories explicitly marked previewable create candidates.

- [ ] **Step 4: Build previews during the JSONL-to-page pass**

Instantiate one `PreviewBuilder` per report with configured limits. For every attachment candidate:

```python
resolved = preview_builder.build(
    evidence_id=context.evidence_id,
    evidence_path=attachment.evidence_path,
    allowed_roots=context.approved_roots,
    file_name=attachment.file_name,
)
```

Replace the candidate with the resolved metadata, register successful previews, and append `AdapterWarning(code="preview_unavailable")` for failures. A preview warning never discards its record.

- [ ] **Step 5: Run preview snapshot tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_previews.py tests/integration/forensic_report/test_preview_snapshot.py -v
```

Expected: pass.

- [ ] **Step 6: Commit snapshot previews**

```bash
git add python_service/httpserver/services/forensic_report/source_resolver.py python_service/httpserver/services/forensic_report/models.py python_service/httpserver/services/forensic_report/snapshot_writer.py python_service/httpserver/services/forensic_report/adapters/sqlite_base.py python_service/tests/integration/forensic_report/test_preview_snapshot.py
git commit -m "feat(report): publish bounded preview assets"
```

---

### Task 3: Generate and verify snapshot integrity

**Files:**
- Create: `python_service/httpserver/services/forensic_report/integrity.py`
- Modify: `python_service/httpserver/services/forensic_report/snapshot_writer.py`
- Modify: `python_service/httpserver/services/forensic_report/service.py`
- Test: `python_service/tests/unit/forensic_report/test_integrity.py`
- Test: `python_service/tests/integration/forensic_report/test_integrity_snapshot.py`

**Interfaces:**
- Consumes: a complete staging snapshot directory.
- Produces: `build_integrity(root, excluded={"integrity.json"}) -> dict`, `verify_integrity(root, integrity) -> IntegrityResult`, `integrity.json`, and `ForensicReportService.verify_integrity(report_id)`.

- [ ] **Step 1: Write failing integrity tests**

```python
# python_service/tests/unit/forensic_report/test_integrity.py
from pathlib import Path

from httpserver.services.forensic_report.integrity import build_integrity, verify_integrity


def test_integrity_detects_modified_missing_and_unexpected_files(tmp_path: Path):
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / "1.json").write_text("[]", encoding="utf-8")
    integrity = build_integrity(tmp_path)
    assert verify_integrity(tmp_path, integrity).valid is True
    (data / "1.json").write_text("[1]", encoding="utf-8")
    changed = verify_integrity(tmp_path, integrity)
    assert changed.valid is False
    assert changed.modified == ["data/1.json"]
```

- [ ] **Step 2: Run test and verify missing integrity module**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_integrity.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement canonical full-tree hashing**

```python
# integrity.py
from pydantic import BaseModel, Field


class IntegrityResult(BaseModel):
    valid: bool
    modified: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    unexpected: list[str] = Field(default_factory=list)


def iter_files(root: Path, excluded: set[str]):
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink not allowed in report: {path}")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            if relative not in excluded:
                yield relative, path


def build_integrity(root: Path, excluded={"integrity.json"}) -> dict:
    files = {}
    for relative, path in iter_files(root, set(excluded)):
        files[relative] = {"sha256": hash_file(path), "size": path.stat().st_size}
    return {"algorithm": "sha256", "files": files}
```

`verify_integrity` compares expected and actual path sets and hashes. It must not follow symlinks.

- [ ] **Step 4: Finalize integrity before manifest publication**

Publication order inside staging becomes:

1. final page/search/preview assets;
2. manifest with `integrity.status="pending"`;
3. build `integrity.json` excluding itself;
4. update manifest integrity summary to `{status: "verified", file_count, algorithm}`;
5. rebuild `integrity.json` because manifest changed;
6. verify once;
7. only then `os.replace(staging, final_dir)`.

The final integrity file hashes the final manifest. If verification fails, throw and leave the version failed.

- [ ] **Step 5: Add service verification**

```python
def verify_integrity(self, report_id: str):
    root = self._ready_dir(report_id)
    integrity = json.loads((root / "integrity.json").read_text("utf-8"))
    return verify_integrity(root, integrity)
```

- [ ] **Step 6: Run unit/integration integrity tests**

The integration test publishes a report, verifies success, modifies one page shard, and verifies modification detection.

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_integrity.py tests/integration/forensic_report/test_integrity_snapshot.py -v
```

Expected: pass.

- [ ] **Step 7: Commit integrity support**

```bash
git add python_service/httpserver/services/forensic_report/integrity.py python_service/httpserver/services/forensic_report/snapshot_writer.py python_service/httpserver/services/forensic_report/service.py python_service/tests/unit/forensic_report/test_integrity.py python_service/tests/integration/forensic_report/test_integrity_snapshot.py
git commit -m "feat(report): verify snapshot integrity"
```

---

### Task 4: Produce browser-loadable offline search shards

**Files:**
- Create: `python_service/httpserver/services/forensic_report/offline_search.py`
- Modify: `python_service/httpserver/services/forensic_report/snapshot_writer.py`
- Modify: `python_service/httpserver/services/forensic_report/models.py`
- Test: `python_service/tests/unit/forensic_report/test_offline_search.py`

**Interfaces:**
- Consumes: the same documents sent to `SnapshotSearchIndex`.
- Produces: categorized JSON search shards, `manifest.search_index`, and deterministic browser substring matching.

- [ ] **Step 1: Write a failing shard test**

```python
# python_service/tests/unit/forensic_report/test_offline_search.py
from pathlib import Path

from httpserver.services.forensic_report.offline_search import OfflineSearchShardWriter


def test_writer_splits_shards_by_evidence_platform_category_and_size(tmp_path: Path):
    writer = OfflineSearchShardWriter(tmp_path, max_documents=2)
    for index in range(3):
        writer.add_document(
            kind='record', title=f'验证码 {index}', search_text=f'验证码 1380013800{index}',
            record_id=f'rec_{index}', evidence_id='e1', platform='android',
            category_id='android.sms', page=1,
        )
    metadata = writer.finalize()
    assert len(metadata['shards']) == 2
    assert all((tmp_path / item['path']).is_file() for item in metadata['shards'])
```

- [ ] **Step 2: Run test and verify missing module**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_offline_search.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement deterministic JSON shards**

Each document contains only:

```json
{
  "kind": "record",
  "title": "...",
  "search_text": "casefolded text",
  "record_id": "rec_...",
  "evidence_id": "...",
  "platform": "android",
  "category_id": "android.sms",
  "page": 1
}
```

Shard key is `evidence_id/platform/category_id`; chapter documents use `analysis/chapters`. Paths are generated through `safe_segment`, never raw labels. Metadata includes `path`, `document_count`, `evidence_id`, `platform`, and `category_id`.

- [ ] **Step 4: Feed both online and offline indexes from one method**

Create a small `SearchDocumentSink` inside `SnapshotWriter`:

```python
def add_document(self, **document):
    self.online.add_document(**document)
    self.offline.add_document(**document)
```

Replace direct online index calls. Add the `OfflineSearchShardWriter.finalize()` result to `manifest.search_index`.

- [ ] **Step 5: Run offline search tests and existing search tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_offline_search.py tests/unit/forensic_report/test_search_index.py -v
```

Expected: pass and both indexes contain equivalent fixture hits.

- [ ] **Step 6: Commit offline search shards**

```bash
git add python_service/httpserver/services/forensic_report/offline_search.py python_service/httpserver/services/forensic_report/snapshot_writer.py python_service/httpserver/services/forensic_report/models.py python_service/tests/unit/forensic_report/test_offline_search.py
git commit -m "feat(report): emit offline search shards"
```

---

### Task 5: Add a static data source and offline application entry

**Files:**
- Create: `web/src/services/staticReportDataSource.js`
- Create: `web/src/offline/OfflineReportApp.jsx`
- Create: `web/src/offline/main.jsx`
- Create: `web/offline.html`
- Modify: `web/vite.config.js`
- Modify: `web/src/services/reportDataSource.js`
- Test: `web/src/services/staticReportDataSource.test.js`
- Test: `web/src/offline/OfflineReportApp.test.jsx`

**Interfaces:**
- Consumes: relative `report/manifest.json`, page paths, search shard metadata, and preview paths.
- Produces: `StaticReportDataSource` with the same read methods as `ReportDataSource` and a Vite `offline.html` entry.

- [ ] **Step 1: Write failing static data-source tests**

```javascript
// web/src/services/staticReportDataSource.test.js
import { vi } from 'vitest';
import { StaticReportDataSource } from './staticReportDataSource';

test('loads manifest/pages relatively and searches only relevant shards', async () => {
  const fetcher = vi.fn(async (url) => ({
    ok: true,
    json: async () => ({
      'report/manifest.json': {
        report_id: 'r1', version: 1,
        categories: [{ category_id: 'android.sms', page_paths: ['data/sms/1.json'] }],
        search_index: { shards: [{ path: 'search/sms-1.json', category_id: 'android.sms' }] },
      },
      'report/data/sms/1.json': { page: 1, records: [{ record_id: 'rec1' }] },
      'report/search/sms-1.json': [{ title: '验证码', search_text: '验证码 123', record_id: 'rec1', category_id: 'android.sms', page: 1 }],
    }[url]),
  }));
  const source = new StaticReportDataSource({ baseUrl: 'report/', fetcher });
  const manifest = await source.getManifest('r1');
  expect((await source.getCategoryPage('r1', 'android.sms', 1)).records).toHaveLength(1);
  expect((await source.search('r1', '验证码')).total).toBe(1);
  expect(fetcher).toHaveBeenCalledWith('report/search/sms-1.json');
});
```

- [ ] **Step 2: Run tests and verify missing module**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/services/staticReportDataSource.test.js
```

Expected: import failure.

- [ ] **Step 3: Implement static relative-path reads**

```javascript
// staticReportDataSource.js
import { ReportDataSource } from './reportDataSource';

export class StaticReportDataSource extends ReportDataSource {
  constructor({ baseUrl = 'report/', fetcher = fetch }) {
    super();
    this.baseUrl = baseUrl;
    this.fetcher = fetcher;
    this.manifest = null;
    this.shardCache = new Map();
  }

  async _json(relative) {
    const response = await this.fetcher(`${this.baseUrl}${relative}`);
    if (!response.ok) throw new Error(`offline resource unavailable: ${relative}`);
    return response.json();
  }

  async listVersions() {
    const manifest = await this.getManifest();
    return [{
      report_id: manifest.report_id, version: manifest.version, status: 'ready',
      scope_type: manifest.scope_type, scope_id: manifest.scope_id,
      title: manifest.title, task_ids: manifest.task_ids,
      stage: 'ready', progress: 100, generated_at: manifest.generated_at,
      warnings: manifest.warnings || [],
    }];
  }
  async createVersion() { throw new Error('offline report is read-only'); }
  async getStatus() { return (await this.listVersions())[0]; }
  async getManifest() {
    if (!this.manifest) this.manifest = await this._json('manifest.json');
    return this.manifest;
  }
  async getCategoryPage(_reportId, categoryId, page) {
    const manifest = await this.getManifest();
    const category = manifest.categories.find((item) => item.category_id === categoryId);
    if (!category || !category.page_paths[page - 1]) throw new Error('offline page not found');
    return this._json(category.page_paths[page - 1]);
  }
  async search(_reportId, query, { offset = 0, limit = 200 } = {}) {
    const manifest = await this.getManifest();
    const needle = query.trim().toLocaleLowerCase();
    const documents = [];
    for (const shard of manifest.search_index?.shards || []) {
      if (!this.shardCache.has(shard.path)) {
        this.shardCache.set(shard.path, await this._json(shard.path));
      }
      documents.push(...this.shardCache.get(shard.path));
    }
    const matches = documents.filter((doc) => doc.search_text.includes(needle));
    return { total: matches.length, offset, limit, hits: matches.slice(offset, offset + limit) };
  }
  getPreviewUrl(_reportId, attachment) {
    return attachment.preview_path ? `${this.baseUrl}${attachment.preview_path}` : null;
  }
  getOfflineBundleUrl() { return null; }
}
```

The test text says “only relevant shards”; the first implementation may load all shard metadata lazily on submit because all shards are potentially relevant to a full-report query. It must not load any shard before search. Add future optimization metadata without changing the interface.

- [ ] **Step 4: Build the offline entry from the shared workspace**

```jsx
// OfflineReportApp.jsx
import { useMemo } from 'react';
import ForensicReportPage from '../pages/ForensicReportPage';
import { StaticReportDataSource } from '../services/staticReportDataSource';

export default function OfflineReportApp() {
  const source = useMemo(() => new StaticReportDataSource({ baseUrl: 'report/' }), []);
  return <ForensicReportPage scopeType="task" dataSource={source} offline />;
}
```

Adjust `ForensicReportPage` so offline mode derives scope/report IDs from the manifest rather than route params and hides generation/export controls. Do not fork the workspace components.

- [ ] **Step 5: Configure Vite multi-entry output**

Add:

```javascript
build: {
  // existing options
  rollupOptions: {
    input: {
      app: fileURLToPath(new URL('./index.html', import.meta.url)),
      offline: fileURLToPath(new URL('./offline.html', import.meta.url)),
    },
    // existing output chunks
  },
},
```

Use relative base only for a dedicated offline build command. Add scripts:

```json
"build:offline": "vite build --mode offline --outDir dist-offline"
```

In config, return `base: mode === 'offline' ? './' : '/'` from a function-form `defineConfig(({ mode }) => ({ ... }))`.

- [ ] **Step 6: Test offline app and build**

`OfflineReportApp.test.jsx` injects a fake static source or mocked fetch and asserts the same report title/category renderer appears with no generate button.

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/services/staticReportDataSource.test.js src/offline/OfflineReportApp.test.jsx
npm run build:offline
```

Expected: pass and `web/dist-offline/offline.html` plus assets exist.

- [ ] **Step 7: Commit offline frontend**

```bash
git add web/src/services/staticReportDataSource.js web/src/services/staticReportDataSource.test.js web/src/services/reportDataSource.js web/src/offline/OfflineReportApp.jsx web/src/offline/OfflineReportApp.test.jsx web/src/offline/main.jsx web/offline.html web/vite.config.js web/package.json web/package-lock.json web/src/pages/ForensicReportPage.jsx web/src/components/reports/ReportToolbar.jsx
git commit -m "feat(web): run report workspace offline"
```

---

### Task 6: Build durable offline ZIP jobs

**Files:**
- Create: `python_service/httpserver/services/forensic_report/offline_bundle.py`
- Modify: `python_service/httpserver/services/forensic_report/repository.py`
- Modify: `python_service/httpserver/services/forensic_report/models.py`
- Modify: `python_service/httpserver/services/forensic_report/service.py`
- Modify: `python_service/httpserver/config.py`
- Test: `python_service/tests/unit/forensic_report/test_offline_bundle.py`
- Test: `python_service/tests/integration/forensic_report/test_offline_bundle.py`

**Interfaces:**
- Consumes: a ready and integrity-valid snapshot plus `web/dist-offline` assets.
- Produces: `OfflineBundleBuilder.build(report_id, snapshot_root) -> Path`, durable offline status, and ZIP structure.

- [ ] **Step 1: Write a failing bundle structure test**

```python
# python_service/tests/unit/forensic_report/test_offline_bundle.py
from pathlib import Path
from zipfile import ZipFile

from httpserver.services.forensic_report.offline_bundle import OfflineBundleBuilder


def test_bundle_contains_shared_app_snapshot_readme_and_no_absolute_paths(tmp_path: Path):
    assets = tmp_path / "dist-offline"
    assets.mkdir()
    (assets / "offline.html").write_text("<html></html>", encoding="utf-8")
    (assets / "assets").mkdir()
    (assets / "assets" / "app.js").write_text("console.log('offline')", encoding="utf-8")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text('{"report_id":"r1"}', encoding="utf-8")
    (snapshot / "integrity.json").write_text('{"files":{}}', encoding="utf-8")
    bundle = OfflineBundleBuilder(assets, tmp_path / "bundles").build("r1", snapshot)
    with ZipFile(bundle) as archive:
        names = archive.namelist()
        assert 'index.html' in names
        assert 'assets/app.js' in names
        assert 'report/manifest.json' in names
        assert 'report/integrity.json' in names
        assert 'README.txt' in names
        assert all(not name.startswith('/') and '..' not in Path(name).parts for name in names)
```

- [ ] **Step 2: Run test and verify missing builder**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_offline_bundle.py -v
```

Expected: import failure.

- [ ] **Step 3: Add frontend asset directory configuration**

```python
report_offline_assets_dir: str = Field(
    default="web/dist-offline", alias="FORENSIC_REPORT_OFFLINE_ASSETS_DIR"
)
```

Resolve relative to project root exactly as report output paths are resolved.

- [ ] **Step 4: Implement safe ZIP creation**

```python
# offline_bundle.py
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile


class OfflineBundleBuilder:
    def __init__(self, assets_dir: Path, bundle_dir: Path):
        self.assets_dir = Path(assets_dir)
        self.bundle_dir = Path(bundle_dir)

    @staticmethod
    def _validate_arcname(value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe ZIP path: {value}")
        return path.as_posix()

    @staticmethod
    def _iter_regular_files(root: Path):
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"symlink not allowed in offline bundle: {path}")
            if path.is_file():
                yield path

    def build(self, report_id: str, snapshot_root: Path) -> Path:
        snapshot_root = Path(snapshot_root)
        offline_entry = self.assets_dir / "offline.html"
        for required in (
            offline_entry,
            snapshot_root / "manifest.json",
            snapshot_root / "integrity.json",
        ):
            if not required.is_file():
                raise FileNotFoundError(required)

        self.bundle_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.bundle_dir / f"{report_id}.tmp.zip"
        final = self.bundle_dir / f"{report_id}.zip"
        temporary.unlink(missing_ok=True)

        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            archive.write(offline_entry, self._validate_arcname("index.html"))
            for path in self._iter_regular_files(self.assets_dir):
                if path == offline_entry:
                    continue
                relative = path.relative_to(self.assets_dir).as_posix()
                archive.write(path, self._validate_arcname(relative))
            for path in self._iter_regular_files(snapshot_root):
                relative = path.relative_to(snapshot_root).as_posix()
                if relative == "search.sqlite3":
                    continue
                archive.write(path, self._validate_arcname(f"report/{relative}"))
            archive.writestr(
                self._validate_arcname("README.txt"),
                "TraceLens 离线取证报告\n\n"
                "打开 index.html 浏览报告。报告完整性仅表示本 ZIP 中的文件未被修改，"
                "不等同于对原始证据来源作独立司法鉴定。\n",
            )

        with ZipFile(temporary) as archive:
            corrupt = archive.testzip()
            if corrupt:
                temporary.unlink(missing_ok=True)
                raise ValueError(f"offline ZIP verification failed: {corrupt}")
        os.replace(temporary, final)
        return final
```

Use `ZIP_DEFLATED`; do not include `search.sqlite3` because browser code cannot query it. Include JSON search shards. The online snapshot may retain `search.sqlite3`, but bundle inclusion uses an allow/deny predicate excluding it.

- [ ] **Step 5: Persist offline job state**

Add columns through idempotent repository migration:

```sql
offline_status TEXT,
offline_progress INTEGER NOT NULL DEFAULT 0,
offline_error TEXT,
offline_bundle_path TEXT
```

Add methods:

```python
mark_offline_generating(report_id)
update_offline_progress(report_id, progress)
mark_offline_ready(report_id, bundle_path)
mark_offline_failed(report_id, error)
```

These methods may update offline delivery fields on a ready version because they do not alter the immutable snapshot itself. They must reject non-ready reports.

- [ ] **Step 6: Add service job methods**

```python
async def start_offline_bundle(self, report_id: str) -> ReportVersion:
    version = self.repository.get(report_id)
    if not version or version.status is not ReportStatus.READY:
        raise RuntimeError("offline export requires a ready report")
    integrity = self.verify_integrity(report_id)
    if not integrity.valid:
        raise RuntimeError("offline export requires valid snapshot integrity")
    self.repository.mark_offline_generating(report_id)
    task = asyncio.create_task(self._build_offline(report_id))
    self._tasks[f"offline:{report_id}"] = task
    return self.repository.get(report_id)
```

`_build_offline` calls the builder in `asyncio.to_thread`, updates progress, and records ready/failed state. On service restart, `offline_status in ('queued','generating')` becomes failed with an interruption message; users may request export again.

- [ ] **Step 7: Run bundle unit and integration tests**

The integration test builds the offline frontend fixture, publishes a snapshot, builds ZIP, extracts it, verifies all paths and hashes, and asserts no `search.sqlite3`, server URL, or absolute evidence resource link is present.

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm run build:offline
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_offline_bundle.py tests/integration/forensic_report/test_offline_bundle.py -v
```

Expected: pass.

- [ ] **Step 8: Commit offline bundle jobs**

```bash
git add python_service/httpserver/services/forensic_report/offline_bundle.py python_service/httpserver/services/forensic_report/repository.py python_service/httpserver/services/forensic_report/models.py python_service/httpserver/services/forensic_report/service.py python_service/httpserver/config.py python_service/tests/unit/forensic_report/test_offline_bundle.py python_service/tests/integration/forensic_report/test_offline_bundle.py
git commit -m "feat(report): build offline HTML bundles"
```

---

### Task 7: Expose previews, integrity, and offline export APIs

**Files:**
- Modify: `python_service/httpserver/routes/forensic_reports.py`
- Test: `python_service/tests/unit/forensic_report/test_delivery_routes.py`
- Modify: `web/src/services/reportDataSource.js`
- Modify: `web/src/services/reportService.js`
- Modify: `web/src/components/reports/ReportToolbar.jsx`
- Modify: `web/src/pages/ForensicReportPage.jsx`
- Test: `web/src/components/reports/ReportToolbar.test.jsx`

**Interfaces:**
- Consumes: preview index, integrity service, and offline job methods.
- Produces: delivery HTTP endpoints and functional toolbar actions.

- [ ] **Step 1: Write failing delivery route tests**

```python
# test_delivery_routes.py
# Use dependency override with a mocked report service.
# Assert:
# - unknown attachment => 404
# - known preview returns FileResponse
# - POST offline on generating report => 409
# - POST offline ready => 202
# - GET offline status returns ReportVersion
# - GET offline bundle returns application/zip
# - integrity verify returns modified/missing/unexpected arrays
```

- [ ] **Step 2: Implement secure preview lookup in service**

```python
def get_preview_path(self, report_id: str, attachment_id: str) -> Path:
    manifest = json.loads(self.get_manifest_path(report_id).read_text("utf-8"))
    relative = manifest.get("preview_index", {}).get(attachment_id)
    if not relative:
        raise KeyError(attachment_id)
    path = (self._ready_dir(report_id) / relative).resolve()
    root = self._ready_dir(report_id).resolve()
    if root not in path.parents or not path.is_file():
        raise KeyError(attachment_id)
    return path
```

Never accept a preview relative path directly from the route.

- [ ] **Step 3: Implement route endpoints**

```python
from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse


@router.get("/{report_id}/previews/{attachment_id}")
def preview(
    report_id: str,
    attachment_id: str,
    service=Depends(get_report_service),
):
    try:
        path = service.get_preview_path(report_id, attachment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="preview not found") from exc
    return FileResponse(path)


@router.post("/{report_id}/offline", response_model=ReportVersion, status_code=202)
async def create_offline(
    report_id: str,
    service=Depends(get_report_service),
):
    try:
        return await service.start_offline_bundle(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{report_id}/offline/status", response_model=ReportVersion)
def offline_status(report_id: str, service=Depends(get_report_service)):
    version = service.get_status(report_id)
    if version is None:
        raise HTTPException(status_code=404, detail="report not found")
    return version


@router.get("/{report_id}/offline")
def download_offline(report_id: str, service=Depends(get_report_service)):
    try:
        path = service.get_offline_bundle_path(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not path.is_file():
        raise HTTPException(status_code=500, detail="published offline bundle is missing")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"tracelens-report-{report_id}.zip",
    )


@router.post("/{report_id}/integrity/verify")
def verify(report_id: str, service=Depends(get_report_service)):
    try:
        return service.verify_integrity(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
```

Add this service helper before registering the routes:

```python
def get_offline_bundle_path(self, report_id: str) -> Path:
    version = self.repository.get(report_id)
    if version is None:
        raise KeyError(report_id)
    if version.offline_status != "ready" or not version.offline_bundle_path:
        raise RuntimeError("offline bundle is not ready")
    return self.writer.report_root.parent / version.offline_bundle_path
```

Map not-ready/conflict to 409, not found to 404, and missing published resources to 500.

- [ ] **Step 4: Extend frontend data sources**

Add methods:

```javascript
createOfflineBundle(reportId) {
  return this.client.post(`/api/reports/${encodeURIComponent(reportId)}/offline`);
}
getOfflineStatus(reportId) {
  return this.client.get(`/api/reports/${encodeURIComponent(reportId)}/offline/status`);
}
verifyIntegrity(reportId) {
  return this.client.post(`/api/reports/${encodeURIComponent(reportId)}/integrity/verify`);
}
```

The static source implements `verifyIntegrity` in Task 8 and throws for bundle creation.

- [ ] **Step 5: Wire toolbar actions and polling**

`ReportToolbar` states:

- `构建离线 HTML` when no job exists;
- `正在构建 {offline_progress}%` while generating;
- `下载离线 HTML` when ready;
- `重新构建离线 HTML` plus error text when failed;
- `验证报告完整性` always available for a ready version.

Use an actual `<a href={dataSource.getOfflineBundleUrl(reportId)} download>` for download. Do not fetch the ZIP into browser memory.

- [ ] **Step 6: Run route and toolbar tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/test_delivery_routes.py -v
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/components/reports/ReportToolbar.test.jsx src/services/reportService.test.js
```

Expected: pass.

- [ ] **Step 7: Commit delivery APIs/UI**

```bash
git add python_service/httpserver/routes/forensic_reports.py python_service/tests/unit/forensic_report/test_delivery_routes.py web/src/services/reportDataSource.js web/src/services/reportService.js web/src/components/reports/ReportToolbar.jsx web/src/components/reports/ReportToolbar.test.jsx web/src/pages/ForensicReportPage.jsx
git commit -m "feat(report): deliver previews and offline bundles"
```

---

### Task 8: Verify integrity inside the offline browser

**Files:**
- Create: `web/src/offline/integrity.js`
- Create: `web/src/components/reports/IntegrityPanel.jsx`
- Modify: `web/src/services/staticReportDataSource.js`
- Modify: `web/src/components/reports/ReportToolbar.jsx`
- Modify: `web/src/components/reports/ReportWorkspace.jsx`
- Test: `web/src/offline/integrity.test.js`
- Test: `web/src/components/reports/IntegrityPanel.test.jsx`

**Interfaces:**
- Consumes: `report/integrity.json`, Web Crypto SHA-256, and relative report resources.
- Produces: critical-startup verification and user-triggered full verification.

- [ ] **Step 1: Write failing browser integrity tests**

```javascript
// integrity.test.js
// Mock fetch responses and crypto.subtle.digest.
// Assert verifyFiles verifies manifest and selected critical files first.
// Assert full verification reports one modified file and one missing file.
```

- [ ] **Step 2: Implement SHA-256 verification**

```javascript
export async function sha256Hex(arrayBuffer) {
  const digest = await crypto.subtle.digest('SHA-256', arrayBuffer);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

export async function verifyIntegrity({ baseUrl = 'report/', fetcher = fetch, full = false }) {
  const integrityResponse = await fetcher(`${baseUrl}integrity.json`);
  const integrity = await integrityResponse.json();
  const entries = Object.entries(integrity.files);
  const selected = full
    ? entries
    : entries.filter(([path]) => path === 'manifest.json' || path.startsWith('data/') && path.endsWith('/1.json'));
  // fetch as arrayBuffer, compare size/hash, return result
}
```

The startup check verifies manifest and the first shard of each category, not every potentially large file. `验证报告完整性` runs full verification.

- [ ] **Step 3: Implement online/static verification through one UI contract**

`StaticReportDataSource.verifyIntegrity(_reportId, { full = true } = {})` calls browser verifier. `HttpReportDataSource.verifyIntegrity` calls the API. `IntegrityPanel` renders:

- `完整性已验证`;
- `关键资源验证通过，尚未执行全包验证`;
- `完整性校验失败` plus modified/missing/unexpected lists;
- explanatory text that package integrity is not source-evidence provenance validation.

- [ ] **Step 4: Trigger critical verification on offline startup**

`OfflineReportApp` verifies critical files before declaring the report available. If verification fails, keep the report readable but display a persistent critical alert; do not silently hide data.

- [ ] **Step 5: Run offline integrity tests/build**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/offline/integrity.test.js src/components/reports/IntegrityPanel.test.jsx src/offline/OfflineReportApp.test.jsx
npm run build:offline
```

Expected: pass.

- [ ] **Step 6: Commit browser integrity verification**

```bash
git add web/src/offline/integrity.js web/src/offline/integrity.test.js web/src/components/reports/IntegrityPanel.jsx web/src/components/reports/IntegrityPanel.test.jsx web/src/services/staticReportDataSource.js web/src/components/reports/ReportToolbar.jsx web/src/components/reports/ReportWorkspace.jsx web/src/offline/OfflineReportApp.jsx web/src/offline/OfflineReportApp.test.jsx
git commit -m "feat(web): verify offline report integrity"
```

---

### Task 9: Add fixed acceptance fixtures and complete compatibility coverage

**Files:**
- Create: `python_service/tests/fixtures/forensic_report/build_fixtures.py`
- Create: `python_service/tests/integration/forensic_report/test_acceptance_matrix.py`
- Create: `web/src/test/fixtures/reportManifest.js`
- Create: `web/src/pages/ForensicReportPage.test.jsx`
- Modify: `web/src/pages/LegacyReportRedirect.test.jsx`
- Modify: `docs/superpowers/specs/2026-07-30-cross-platform-forensic-report-design.md` only if implementation exposes a genuine documented correction; otherwise do not edit the approved spec.

**Interfaces:**
- Consumes: all report generation, browsing, reference, preview, integrity, and offline components.
- Produces: four reproducible acceptance fixtures and an automated acceptance matrix.

- [ ] **Step 1: Implement fixture builder functions**

The builder creates isolated temporary datasets, not committed binary DB files:

```python
def build_android_fixture(root: Path) -> FixtureScope: ...
def build_windows_fixture(root: Path) -> FixtureScope: ...
def build_linux_fixture(root: Path) -> FixtureScope: ...
def build_mixed_case_fixture(root: Path) -> FixtureScope: ...
```

Each fixture includes:

- at least two paged records in one category;
- Chinese text, a path, a phone number, and a hash searchable value;
- one high-risk/relevant/deleted record;
- one five-chapter file reference and event reference;
- one resolvable and one unresolved reference;
- one approved preview and one rejected attachment;
- a legacy five-chapter report row.

- [ ] **Step 2: Write the backend acceptance matrix**

Parametrize Android, Windows, Linux, and mixed case. For each:

1. create version;
2. wait for ready;
3. verify only actual platforms/categories appear;
4. fetch every category page and count all records;
5. search Chinese/path/phone/hash samples;
6. assert highlighting metadata;
7. assert analysis references and reverse links;
8. verify snapshot integrity;
9. build offline ZIP;
10. extract and verify all required relative resources;
11. assert source DB hashes are unchanged.

- [ ] **Step 3: Add frontend online/static equivalence test**

Render `ForensicReportPage` once with `FixtureReportDataSource` and once with `StaticReportDataSource` backed by identical fixture JSON. Assert both display identical:

- title/version/platform badges;
- directory category counts;
- selected record values/badges;
- analysis chapters and unresolved reference status;
- preview metadata;
- warning summary.

Do not compare generated class names or full HTML snapshots; assert semantic roles/text.

- [ ] **Step 4: Complete compatibility redirect matrix**

Test:

```text
/case-report?task_id=t1 -> /reports/task/t1
/case-report?taskId=t1  -> /reports/task/t1
/case-report?case_id=c1 -> /reports/case/c1
/case-report             -> /tasks
```

Also assert backend legacy endpoints remain in `create_app().openapi()`:

```text
/api/llm/case-report/{task_id}
/api/llm/case-report-by-case/{case_id}
```

- [ ] **Step 5: Run the full report verification suite**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm run build:offline
npm test -- --run
npm run build
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report tests/integration/forensic_report -v
```

Expected: all tests pass.

- [ ] **Step 6: Run focused legacy regression tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/test_dll_route.py -v
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/pages/LegacyReportRedirect.test.jsx src/pages/CaseIntelligence.test.jsx src/pages/Cases.test.jsx src/components/tasks/TaskTable.test.jsx
```

Expected: pass.

- [ ] **Step 7: Commit acceptance fixtures**

```bash
git add python_service/tests/fixtures/forensic_report/build_fixtures.py python_service/tests/integration/forensic_report/test_acceptance_matrix.py web/src/test/fixtures/reportManifest.js web/src/pages/ForensicReportPage.test.jsx web/src/pages/LegacyReportRedirect.test.jsx
git commit -m "test(report): cover cross-platform acceptance matrix"
```

---

## Plan 5 Completion Gate

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm run build:offline
npm test -- --run
npm run build
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report tests/integration/forensic_report -v
cd /home/ymj68520/projects/Forensics/TraceLens
git status --short
git diff --cached --name-only
```

Expected:

- Preview traversal, symlink, size, pixel, and count protections pass.
- Only approved thumbnails/small text previews are copied.
- Original evidence paths/hashes remain available and originals are not copied by default.
- Snapshot integrity detects modified, missing, and unexpected resources.
- Offline search uses JSON shards and works for Chinese/path/phone/hash queries.
- Offline app uses shared report components and no server API.
- ZIP opens from `index.html`, uses relative paths, and contains no `search.sqlite3` or absolute executable resource links.
- Online and offline fixtures render equivalent report content.
- Four acceptance fixture scopes pass.
- Legacy routes/APIs remain available.
- `.superpowers/sdd/2026-07-29-miui-backup-forensics-phase1/final-remediation-round-report.md` is not staged.

This is the final implementation plan in the suite.
