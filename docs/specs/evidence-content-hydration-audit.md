# Evidence Content Hydration — Repository Audit

Status: AUDIT COMPLETE (zero production changes made by this document).
Scope: production evidence content availability gap identified by
Acceptance Generation 3 B6 (B6_INVALID, reason
`EVIDENCE_CONTENT_SURFACE_TRANSIENT`). This audit answers §4 Q1–Q15 and
establishes the root cause, the reusable capabilities, and the minimum
production change before any code is written.

---

## 1. Current content read path (Q1, Q6, Q10)

### 1.1 Agent tool path (`get_evidence`)

`httpserver/services/investigation/agent_tools/adapters/evidence.py`
(`build_get_evidence_tool`):

```text
get_evidence(task_id, evidence_key, hydration_level)
  → InvestigationService.resolve_evidence(task_id, evidence_key)   # identity
  → level "digest": metadata only (no content)
  → level "preview": resolved["content"] (cluster: composed from events.db;
        file: always None)
        else EvidenceResolver.bounded_content(resolved)            # file bytes
```

The resolver used here is the workbench resolver
`httpserver/services/investigation_evidence.py` (`EvidenceResolver`):

- `_resolve_file` loads the exact `files.db` row (with a
  `REPLACE(path,'\','/')` fallback) and computes
  `content_path`:
  1. the forensic path itself **if it exists on the host** — for
     image-backed evidence this is an image-internal path (e.g.
     `/etc/passwd`) and never exists, by design;
  2. else `task_info["extraction_directory"] + relative` and
     `extraction_directory + basename` — i.e. **leftover artifacts in the
     task's `extracted_files/` directory**;
  3. else `None`.
- `bounded_content(resolved)`:
  - `content_path is None` → returns `""` (no fallback of any kind);
  - else `content_reader(content_path)` when injected
    (`InvestigationService._extract_file_text`: document extractor →
    markdown, hard-capped at `MAX_CONTENT_CHARS = 8000`), or a direct
    `open(path, encoding="utf-8", errors="ignore")` read capped at 8000.

### 1.2 `content_preview` semantics (Q10)

The preview is generated **at read time** from whatever bytes the
`content_path` file holds; nothing is persisted by the parser. Encoding
policy today is UTF-8 with `errors="ignore"` (lossy, silent). Cap is 8000
characters (`MAX_CONTENT_CHARS`, `investigation_evidence.py:22`).

### 1.3 Other consumers of the same resolution path

- Investigation evidence analysis job
  (`investigation_service.py:1010-1022`): reads
  `resolved["content_path"]` directly; when missing logs
  "extracted evidence content unavailable … (continuing with metadata
  and snapshot)" and feeds the LLM the literal placeholder
  （证据内容不可用…）.
- Report dataset builder and report evidence binding consume the same
  resolver (metadata/summary level).
- Files page content consumers (Q6) already have on-demand
  reacquisition wrappers: `routes/office.py::_materialize_from_image`
  (single-file C++ materialize call) and
  `services/llm/auto_extractor.py::ensure_extracted_for_analysis`
  (single-file extraction job, blocking wait, then read from
  `extracted_files`). The **Agent read path has no equivalent**.

### 1.4 Identity-only resolver (separate class)

`httpserver/services/evidence/resolver.py` (`EvidenceResolver(cpp_backend)`)
resolves evidence identity only (task-scoped, fail-closed, zero-write) and
never reads bytes. It backs A1-S snapshot acquisition
(`investigation/acquisition.py::_acquire_file` — metadata-only by frozen
contract), specialist execution-digest verification, report evidence
binding, and the workbench identity checks.

---

## 2. Temporary-resource lifecycle (Q2, Q3, Q8)

### 2.1 Who creates `extracted_files/`

`data/tasks/<task_id>/extracted_files` (`PathManager::getTaskExtractDir`,
published to task info as `extraction_directory`,
`routes/TaskHelpers.cpp:96`, `TaskSerialization.cpp:102`) is created **only
on demand**:

1. `/api/forensics/extract` jobs — `FileExtractionRoutes::run_extraction_job`
   → `FileExtractor::extractAll/extractByExtension/extractByName/
   extractDeleted` (writes under the task extract root; user `output_dir`
   is traversal-checked and contained under the root,
   `FileExtractionRoutes.cpp:139-166`);
2. `/api/forensics/files/materialize` — single-file synchronous extraction,
   `extractFileByPath`, membership-gated by the raw DB ("only resolves
   paths that are known file records in the raw database",
   `FileExtractionRoutes.cpp:278-301`);
3. the Python auto-extractor (`ensure_extracted_for_analysis`, used by the
   interactive analyze routes) and the case-analysis extraction flow
   (`case_analysis_parts/_windows.py`), both driving (1).

### 2.2 Who does NOT create it

The standard parse pipeline never materializes bytes:

```text
TaskManagerAnalysis::runAnalysis
  → extractToDatabase      (image walk → raw.db)          # metadata only
  → EventExtractor         (raw.db → events.db)           # metadata only
  → FileClassifier         (raw.db → files.db rows)       # metadata only
  → LLMAnalysisService     (image → file → description)   # bytes → OS temp
```

LLM file analysis extracts each file to `llm_scratch::dirForTask(task_id)`
= `$TMPDIR/forensics_llm_extract/<task_id>` (`LLMScratch.cpp:11-14`), which
is **destroyed when the LLM analysis phase ends**
(`LLMAnalysisService::~LLMAnalysisService` → `llm_scratch::cleanupTask`,
`LLMAnalysisService.cpp:22-26`). This — not `extracted_files` — is the
transient extraction surface.

### 2.3 Who deletes `extracted_files/`

**Nobody deletes it mid-life.** Deletion happens only with the whole task
directory: explicit task delete (`TaskManager.cpp:394`), the RAII cleanup
handler when a task was deleted while analysis was running
(`TaskManagerAnalysis.cpp:160-172`), and the orphan-directory sweep at
startup (`TaskPersistence::cleanup_orphan_directories`, task dirs not in the
tasks map). The original design intent (Q8) is therefore "extraction output
is a disposable cache of an operation the user explicitly requested", not
"a temporary store the system reclaims".

### 2.4 Empirical state (this repo, 2026-10-01)

Of 54 task directories under `build/data/tasks/`: 18 have
`extracted_files/` (1 empty; sizes range 3 → 77 783 files), 36 have none.
Content readability of Evidence is currently **accidental**: it depends on
whether some interactive flow happened to run an extraction job for that
task. The earlier working hypothesis "the backend deletes extracted_files
shortly after indexing" is **corrected** by this audit: benchmark/
API-provisioned tasks never had extraction artifacts in the first place,
and interactive LLM analysis bytes went to OS-temp scratch which is cleaned
by design.

---

## 3. Root cause

The Parsed Evidence layer persists identity + metadata (`files.db`) and
derived text (`llm_summary/llm_description`), but **file bytes are not part
of the parse output**. The content read path treats leftover extraction
artifacts as the content backing and has **no reacquisition fallback**:

```text
file:<path> (image-backed)
  → forensic path on host: never exists
  → extracted_files leftover: exists only by accident of history
  → otherwise: content = null / "" (ambiguous)
```

Consequences: Gen-1 holdout tasks happened to carry extraction artifacts
(demo-driven extraction jobs) so content was readable; Gen-3 tasks had
none, so every `get_evidence` preview was null. Same production code,
different accidental state — a production evidence-content availability
gap (not a benchmark defect, not an agent failure).

---

## 4. Existing reusable capability (Q4, Q5, Q15)

### 4.1 `files.db` schema (Q4)

`CREATE_MAIN_FILES_TABLE` (`src/core/DatabaseManager/SQL/file_classifier_sql.h`):
`id, inode, name, path, size, extension, category, type, mtime, ctime,
is_deleted, md5, partition_num, llm_summary, llm_description, llm_keywords,
llm_analyzed_at, llm_model_used, scene_type, scene_priority, scene_relevant`.

There is **no** content/blob/content_path/extracted_path/text/preview
column. There **are** provenance locators: `md5` + `size` (image-walk
content hash/length), `inode`, `partition_num`. All C++ writers
(`FileClassifier` INSERT, `LLMAnalysisService` REPLACE) use explicit column
lists, so additive columns are safe. Python already extends this table
additively (`llm_*` columns written by `persist_to_files_db`; the
`partition_num` additive migration precedent on both sides).

### 4.2 Raw-source reacquisition (Q5) — EXISTS

`FileExtractor(image_path, raw_db)` (C++, TSK-based):

- `extractFileByPath(path, out)` — resolves only paths that are known file
  records in raw.db (membership gate, fail closed), opens the image
  partition by computed TSK offsets, writes exact bytes;
- exposed synchronously via `POST /api/forensics/files/materialize`
  (single file) and as job-based `POST /api/forensics/extract`;
- Python clients already exist: `cpp_backend.extract_files` /
  `get_extraction_status`, `ensure_extracted_for_analysis` (blocking
  wrapper), `office._materialize_from_image` (single-file HTTP).

Locator stability (Q5): requires the task's `image_path` + `output_raw_db`
(both published on task info, `TaskHelpers.cpp:63-96`). Deleted-file rows
are extractable via `extractDeleted` in job mode; the single-file
materialize path resolves records by path in raw.db — deleted-file
reacquisition may fail and must fail closed (recorded limitation).

### 4.3 Reuse / Modified / Added (Q15)

```text
Reused  (unchanged):
  - FileExtractor + /api/forensics/files/materialize + /api/forensics/extract (C++ reacquisition primitive)
  - files.db as the canonical Parsed Evidence repository (manifest owner, §17)
  - task-dir lifecycle (delete removes task dir incl. content artifacts, §30)
  - MAX_CONTENT_CHARS bounded preview; document extractor for rich formats

Modified (read-path wiring only):
  - investigation_evidence.EvidenceResolver: optional durable content provider
  - InvestigationService content read path (analysis job) → same provider
  - agent get_evidence output: explicit content availability fields

Added:
  - services/evidence/content_store.py — derived immutable task content store
    (hash-addressed blobs + verified adoption + lazy deterministic reacquisition)
  - additive files.db locator columns (content_sha256/content_size/content_stored_at)
  - explicit reason-code enum for unavailable content
```

No second store exists today (Q4), so a minimal derived content backing is
warranted (§6 rule 3), but it must reuse the C++ reacquisition primitive
(§6 rule 2) and files.db as manifest (§6 rule 1/§17).

---

## 5. Ownership boundary (Q7), task lifecycle (Q11), restart (Q12), legacy (Q13), provenance (Q14)

- **Q7 ownership**: durable content backing is owned by the Python
  evidence/read layer (`services/evidence`), where every content consumer
  (Agent tool, investigation analysis, report dataset) already resolves
  Evidence. The C++ side keeps exactly one responsibility: the
  reacquisition primitive. No C++ changes are required or permitted in
  this phase's minimum change.
- **Q11 task deletion**: the content store lives inside the task directory
  (`data/tasks/<id>/content/`), so the existing atomic task-dir
  `remove_all` cleans identity, DBs, and content together; no new
  lifecycle owner and no cross-task orphans.
- **Q31 deletion race**: reacquisition is attempted only after a live
  `get_task` and only writes into that task's directory; if the task is
  deleted concurrently, the C++ materialize/extract call fails (task gone)
  and the store write is abandoned — the store is never recreated for a
  deleted task.
- **Q12 restart**: the read path is stateless (no in-memory content cache);
  blobs + locator columns are task-owned durable state on disk. After a
  full service restart, hydration needs nothing else.
- **Q13 legacy tasks**: rows without a locator are served by (a) verified
  adoption of existing `extracted_files` leftovers, then (b) lazy
  deterministic reacquisition from the image (works while image + raw.db
  exist — i.e. for essentially all legacy tasks that still open in the
  product), and fail with an explicit `CONTENT_NOT_PERSISTED_LEGACY` /
  `CONTENT_SOURCE_MISSING` otherwise. Content is never synthesized from
  names, metadata, or LLM descriptions.
- **Q14 provenance binding**: a stored blob is accepted only after
  `md5(bytes) == files.db.md5` (and `size(bytes) == files.db.size`);
  the locator then binds `(task_id, evidence_key → path row) → content_sha256
  → size → stored_at`. Reads re-verify `sha256(bytes) == content_sha256`
  and fail closed on mismatch (`CONTENT_INTEGRITY_MISMATCH`).

---

## 6. Content-type policy (Q9, Q19, Q20, Q21)

- Plain text: raw bytes → deterministic decode chain (UTF-8 strict →
  GB18030 → UTF-8 replacement) → bounded preview (8000 chars). The chain is
  fixed and auditable; no LLM/media detection.
- Binary / undecodable (NUL byte in the first 8 KiB, or declared binary
  category): metadata + explicit `content_available=false` +
  `CONTENT_UNSUPPORTED_TYPE`; never force-decoded.
- Document formats (Office/PDF): bytes are stored/reacquired; textual
  preview continues to use the existing document extractor (markdown,
  bounded) exactly as `InvestigationService._extract_file_text` does today.
- Large files: full raw bytes are the durable backing, but persistence is
  capped (default 64 MiB) to bound disk amplification; reads are always
  bounded previews. Above the cap: hash-verify against a temp materialize,
  serve bounded preview, do not retain (explicit reason code). Amplification
  and latency numbers are recorded by the canary (§55).

---

## 7. Recommended target model (§7 of the directive)

```text
Original Evidence (image)            [unchanged, §9]
        ↓ C++ parse (unchanged)      raw.db / files.db / events.db
Resolved File Evidence (identity)    (task_id, file:<normalized_path>)  [unchanged, §8]
        ↓ verified adoption / lazy deterministic reacquisition (C++ materialize)
Immutable Task Content Store         data/tasks/<id>/content/blobs/<sha256>
        ↓ locator manifest           files.db additive columns (content_sha256/…)
EvidenceResolver / InvestigationService          [read wiring]
        ↓
Agent Tool (get_evidence) / Investigation analysis / Files consumers
```

Boundaries preserved (§60): Evidence identity ≠ content backing ≠
EvidenceSnapshot (A1-S stays metadata-only) ≠ Initial AI Analysis (never a
content source) ≠ ToolObservation. The Agent read path stays read-only:
lazy materialization produces only a verified derived content cache (§25).

---

## 8. Migration impact (§54) and performance (§55)

- `files.db`: additive `ALTER TABLE ... ADD COLUMN` guarded by
  `pragma table_info` — idempotent per task DB, applied on first
  content-store write; all C++ statements use explicit column lists, so
  old and new binaries coexist; no data migration needed (locator absent =
  "not yet persisted").
- Disk amplification: one copy per distinct content-readable file actually
  hydrated (hash-deduped within the task), capped per file by the
  persistence limit; parse latency unchanged (no eager extraction in the
  parse pipeline); first hydration pays one C++ materialize round-trip,
  later reads are local.
- Integrity/auditability rank above performance (§55): every stored byte is
  hash-verified against the parser-produced `files.db` hashes at write and
  re-verified at read.

## 9. Minimum production change

1. `services/evidence/content_store.py` (new): reason-code enum, decode
   chain, blob store, verified adoption, lazy reacquisition, locator
   manifest (files.db additive columns), fail-closed reads.
2. Wire as an optional content provider into the workbench
   `EvidenceResolver` (used by `get_evidence`, investigation analysis) —
   content_path stays the fast path when it exists; store is consulted
   when it does not.
3. `get_evidence` output: explicit `content_available` +
   `content_unavailable_reason` (no more ambiguous null).
4. Tests (§32-§43) + production-style canaries on a new synthetic
   non-secret fixture (§44-§47). No benchmark artifacts are used.
5. New runtime baseline binding the content-hydration contract (§49);
   calibration requalification is NOT executed in this phase (§50).

No C++ changes. No benchmark changes. No agent contract changes beyond the
two additive `get_evidence` output fields. No changes to Evidence identity,
normalization, snapshots, or A1-T/A1-H contracts.
