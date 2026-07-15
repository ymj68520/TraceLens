# CLI Text Dump Total-Size Limit — Design Spec

- **Date:** 2026-07-15
- **Status:** Approved (design)
- **Scope:** CLI `--dump-text` output only

## 1. Goal

Add an opt-in CLI parameter that limits the combined logical size of the files produced for `--dump-text` field-testing exports:

```bash
--dump-text-max-size <SIZE>
```

The feature is primarily intended for on-site environments where AI is unavailable and export storage is constrained. It is not coupled to `--no-ai`: users may apply the limit whenever they use text dumping.

The limit must preserve complete files. It is therefore a **per-file soft limit**, not a byte-exact hard cap: once processing of a file begins, its original extraction and Markdown conversion may finish even if they take the total over the configured limit. No later file starts after the limit is reached.

## 2. Confirmed Decisions

| Decision | Choice |
|---|---|
| Limited outputs | Only `<base>_extracted_files/` and `<base>_extracted_text/` |
| Unaffected outputs | Core databases, reports, and all other analysis artifacts |
| Limit behavior | Preserve completed files, stop gracefully, warn, and keep the main command successful |
| Limit precision | Per-file soft limit; the final file may exceed the configured value |
| Processing model | Extract one complete source file, convert it, account for both outputs, then consider the next file |
| CLI value syntax | Positive integer followed by one case-insensitive binary unit: `K`, `M`, `G`, or `T` |
| Unit values | `K=1024`, `M=1024²`, `G=1024³`, `T=1024⁴` bytes |
| Default | No limit unless the new parameter is explicitly supplied |
| Implication | `--dump-text-max-size` automatically enables `--dump-text` |
| Existing files | Existing regular files in both output trees count toward the limit |
| File order | Image paths in binary lexicographic order, with partition number and inode as stable tie-breakers |
| AI coupling | None; the option neither requires nor implies `--no-ai` |
| Resumption | Reuse valid existing outputs and continue when rerun with remaining capacity |

## 3. CLI Contract

### 3.1 Syntax and examples

```bash
./build/forensic_analyzer disk.E01 \
  --db-dir ./output \
  --linux-analyze \
  --no-ai \
  --dump-text-max-size 500M
```

Explicit `--dump-text` remains valid but is redundant when the limit is present:

```bash
./build/forensic_analyzer disk.E01 --dump-text --dump-text-max-size 2G
```

### 3.2 Valid values

The grammar is:

```text
SIZE := POSITIVE_DECIMAL_INTEGER UNIT
UNIT := K | M | G | T | k | m | g | t
```

Examples:

- `1K` = 1,024 bytes
- `500M` = 524,288,000 bytes
- `2g` = 2,147,483,648 bytes
- `1T` = 1,099,511,627,776 bytes

### 3.3 Invalid values

The parser rejects the following before analysis starts:

- zero: `0M`
- negative values: `-1G`
- decimals: `1.5G`
- missing unit: `500`
- extra unit characters: `10MB`, `2GiB`
- unknown units: `4P`
- missing option value
- values whose byte conversion would overflow `uint64_t`

A parse failure prints an actionable error, prints the expected syntax, returns a nonzero exit status, and creates no analysis outputs.

### 3.4 Compatibility

`--dump-text` without `--dump-text-max-size` retains the existing unlimited extraction and batch-conversion behavior. The new parameter only changes execution when explicitly supplied.

The CLI representation is an optional byte limit, for example:

```cpp
std::optional<uint64_t> dump_text_max_bytes;
```

The parser also exposes a parse error so `main()` can reject invalid input before dispatching any execution mode. This change does not alter the handling of unrelated options.

## 4. Limit Boundary and Accounting

### 4.1 Included files

The current logical usage is the sum of `file_size()` for regular files recursively present under:

```text
<db-prefix>/<base>_extracted_files/
<db-prefix>/<base>_extracted_text/
```

Both newly created and pre-existing valid output files count.

### 4.2 Excluded data

The limit does not include:

- `<base>_raw.db`
- `<base>_events.db`
- `<base>_files.db`
- filtered, platform, DLL, memory, or other databases
- `<base>_report.md`
- directory metadata or filesystem allocation overhead
- files outside the two text-dump output roots
- temporary files created as part of an in-progress atomic write

### 4.3 Filesystem rules

Accounting walks each output tree without following directory symlinks. Symlinks are not counted as target content. A filesystem error that prevents reliable accounting stops the text-dump phase with a warning; it does not invalidate the completed forensic databases.

Temporary files owned by this feature use a reserved, recognizable name pattern. Stale files with that pattern are removed before accounting. Unrelated regular files in the output trees are counted because they consume space inside the user-selected output boundary.

### 4.4 Soft-limit rule

Before starting a new image file:

```text
if current_usage >= configured_limit:
    stop with size_limit_reached
else:
    process the complete file unit
```

No second limit check interrupts a file that has already started. After extraction and conversion complete or fail, usage is updated from actual on-disk sizes.

Example: with 490 MiB used and a 500 MiB limit, a file that produces a 30 MiB original and a 5 MiB Markdown file is retained in full. Usage becomes 525 MiB, and no subsequent file starts.

The documented maximum overshoot is the combined logical size of the final processing unit's original file and generated Markdown. This is intentional and is reported as a soft-limit overrun, not an error.

## 5. Architecture

### 5.1 Components

#### `CommandLineParser`

- Parse and validate `--dump-text-max-size`.
- Perform checked binary-unit conversion to `uint64_t`.
- Set `dump_text = true` when the option is valid.
- Record parse errors for rejection by `main()` before mode dispatch.
- Document the new option and soft-limit semantics in CLI help.

#### `TextDumpExporter`

A new focused C++ component owns text-dump policy and orchestration:

- choose the unlimited legacy path or limited per-file path;
- create and validate output roots;
- remove owned stale temporary files;
- calculate initial usage;
- enumerate files deterministically;
- coordinate extraction and conversion one file at a time;
- update usage from actual file sizes;
- stop on the configured limit or service-level failure;
- return a structured summary.

`AnalysisOrchestrator` only constructs the paths and dependencies, invokes the exporter, and renders the returned summary.

#### `FileExtractor`

Expose a narrow API required by the limited exporter:

- enumerate allocated, non-deleted regular-file records in deterministic order;
- safely map an image record to its output-relative path using the established extraction layout;
- extract one record atomically to a requested destination;
- report whether the result was newly written, reused, or failed.

Budget policy remains outside `FileExtractor`.

The deterministic database order is equivalent to:

```sql
ORDER BY path COLLATE BINARY ASC,
         COALESCE(partition_num, 0) ASC,
         inode ASC
```

The established output-path mapping remains compatible with current `extractAll()` behavior. If records map to the same output path, the stable order makes replacement behavior deterministic; accounting always uses the final files actually present on disk rather than summing database metadata.

#### `MarkitdownProxy`

Add a single-file conversion operation whose result distinguishes:

- converted successfully;
- reused existing Markdown;
- skipped by content/type rules;
- per-file conversion failure;
- Python service/transport failure.

The response includes the actual final output size when a Markdown file exists. Markdown content does not cross the C++/Python HTTP boundary.

#### Python MarkItDown route

Extract the existing `_convert_one` behavior into a reusable internal conversion function. Both the current batch endpoint and a new single-file endpoint call this function, preserving one implementation of extractor selection, text fallback, binary detection, and atomic output writing.

### 5.2 Execution modes

#### Unlimited mode

When no size limit is supplied, preserve the current workflow and performance characteristics:

```text
FileExtractor::extractAll()
    -> MarkitdownProxy::batchConvertToMarkdown()
```

#### Limited mode

When a size limit is supplied:

```text
account existing outputs
    -> enumerate records deterministically
        -> pre-file limit check
            -> atomically extract/reuse original
                -> atomically convert/reuse Markdown
                    -> account actual final sizes
                        -> repeat or stop
```

This isolates the new behavior and avoids turning every existing unlimited export into one HTTP request per file.

## 6. Detailed Data Flow

### 6.1 Startup

1. Resolve the original extraction and Markdown output roots.
2. Create missing roots.
3. Validate that both roots are directories and that output paths remain confined to them.
4. Remove stale temporary files created by this feature.
5. Recursively total existing regular-file sizes without following symlinks.
6. If existing usage is already at or above the limit, return a successful, truncated result without processing a new file.
7. Query allocated, non-deleted regular-file records in deterministic order.

### 6.2 One processing unit

For each record:

1. Check whether current usage is already at or above the limit. If so, stop.
2. Derive and validate the original output path.
3. If a regular original file exists with the expected size, reuse it. Otherwise extract to a same-directory temporary file and atomically replace the final path.
4. Derive the corresponding Markdown path by mirroring the original relative path and appending `.md`.
5. If a valid regular Markdown file already exists for an unchanged original, reuse it. Otherwise request conversion through Python. Python writes to a temporary file in the target directory and atomically replaces the final Markdown path.
6. Obtain actual final sizes for both paths and update total usage by the delta from their pre-operation sizes. A replacement is not double-counted.
7. Record per-file outcomes and continue.

The implementation must not trust the raw database `size` value for final accounting; actual output file sizes are authoritative.

### 6.3 Resume behavior

On rerun:

- matching original and Markdown files are reused;
- a matching original without Markdown is converted;
- Markdown without the original is retained while the original is restored;
- a mismatched original is atomically replaced and its Markdown regenerated;
- existing sizes count before any new work starts;
- increasing the limit allows traversal to continue without regenerating valid earlier outputs.

A small provenance sidecar is not introduced in this scope. Reuse is based on the existing extractor's compatibility rule for originals (regular file and expected size) and the presence of the corresponding regular Markdown output. This deliberately avoids adding a new output format or manifest.

## 7. Python Single-File Contract

The endpoint accepts roots rather than an arbitrary caller-computed output file:

```http
POST /api/markitdown/convert-one
Content-Type: application/json

{
  "input_root": "/abs/output/disk_extracted_files",
  "input_file": "/abs/output/disk_extracted_files/etc/auth.log",
  "output_root": "/abs/output/disk_extracted_text"
}
```

The server resolves and validates that `input_file` is a regular file confined beneath `input_root`. It derives the relative path itself and writes:

```text
<output_root>/etc/auth.log.md
```

A successful HTTP response reports one of:

```text
converted | skipped | failed
```

and includes the derived output path and its byte size when an output exists. Per-file extractor/conversion failures return HTTP 200 with `status=failed`, because they are isolated data outcomes and traversal may continue. Invalid paths or malformed requests return 4xx. Endpoint infrastructure failures return 5xx, while an unreachable service has no HTTP response; C++ treats either 5xx or transport failure as a service-level stop condition rather than retrying every remaining file.

Conversion rules remain identical to the current batch behavior:

1. use the specialized extractor returned by `ExtractorLocator` when available;
2. otherwise read likely-text files directly;
3. try strict UTF-8, then Latin-1 with replacement;
4. skip likely-binary files, empty output, and unsupported content;
5. isolate extractor exceptions to the current file.

The batch endpoint is refactored to call the same internal function, so its public response and concurrency limit remain unchanged.

## 8. Atomicity and Path Safety

- Normalize image-relative paths before joining them to an output root.
- Reject absolute/path-traversal records that would escape the output root.
- Do not follow output-directory symlinks while scanning or selecting destinations.
- Create temporary files in the same directory as their final file so rename is atomic on the target filesystem.
- Flush and close a temporary file before renaming it.
- Remove temporary files after extraction/conversion failure.
- Preserve an existing valid final file until its replacement is complete.
- A failed write must not leave a newly truncated final file.

The budget describes retained logical output, not transient workspace usage. Atomic temporary files can temporarily require additional disk space and are excluded from the logical total shown to the user.

## 9. Error Handling

| Condition | Text-dump behavior | Main command result |
|---|---|---|
| Invalid size syntax or overflow | Reject before analysis | Nonzero |
| Existing usage already reaches limit | Process no new files; report truncated | Success |
| Limit reached after a complete file | Preserve it; stop before next file | Success |
| One original extraction fails | Count failure; continue with next record | Success |
| One conversion is skipped | Preserve original; count skipped; continue | Success |
| One extractor/conversion fails | Preserve original; count failure; continue | Success |
| Python service unavailable before dump | Do not start dump; warn | Success |
| Python transport/service lost mid-run | Preserve completed outputs; stop further dump work; warn | Success |
| Output-root/accounting infrastructure error | Stop dump; warn | Success |
| Main forensic analysis fails | Existing analysis behavior | Nonzero |

Transport failure must be distinguishable from an ordinary per-file conversion failure. This prevents repeated connection timeouts for every remaining file after the Python service has disappeared.

## 10. Result and CLI Summary

`TextDumpExporter` returns structured fields sufficient to report:

- candidate file count;
- processed file count;
- originals newly extracted, reused, and failed;
- Markdown files converted, reused, skipped, and failed;
- initial and final logical byte usage;
- configured limit, if any;
- whether the export was truncated;
- stop reason (`completed`, `size_limit_reached`, `service_unavailable`, or `output_error`);
- a diagnostic message for service or output errors.

Example:

```text
✓ Text dump: 128/1042 files processed
  Extracted: 120 new, 8 reused, 0 failed
  Markdown: 105 converted, 8 reused, 10 skipped, 5 failed
  Size: 525.0 MiB / 500.0 MiB soft limit
  Stopped: size limit reached; completed files were preserved
```

Warnings must explicitly state that the core forensic databases remain valid.

## 11. Code Changes

| Component | Planned change |
|---|---|
| `src/CommandLineParser.h` | Add optional byte limit and parse-error representation |
| `src/CommandLineParser.cpp` | Add checked size parser, option handling, implication, and help text |
| `src/main.cpp` | Reject parse errors before execution-mode dispatch |
| `src/core/DatabaseManager/FileExtractor/FileExtractor.h` | Add deterministic record enumeration and atomic single-record extraction API |
| `src/core/DatabaseManager/FileExtractor/FileExtractor*.cpp` | Implement ordered query, outcome reporting, and atomic extraction support |
| `src/export/TextDumpExporter.h/.cpp` | Add unlimited/limited orchestration, accounting, safety, and result model |
| `src/integration/LLMIntegration/MarkitdownProxy.h/.cpp` | Add typed single-file conversion request/result |
| `python_service/httpserver/routes/markitdown.py` | Share one conversion primitive and add `/convert-one` |
| `src/AnalysisOrchestrator.cpp` | Replace embedded dump logic with `TextDumpExporter` invocation |
| `CMakeLists.txt` and test CMake files | Compile exporter and register C++ tests |
| Python tests | Cover shared conversion and endpoint behavior |
| `scripts/ONSITE_TEST_GUIDE.md` | Document constrained on-site export usage and soft-limit semantics |

No core database schema changes and no HTTP task-analysis changes are included.

## 12. Testing Strategy

### 12.1 C++ size parser tests

Verify:

- exact conversion for `1K`, `500M`, `2G`, and `1T`;
- lowercase units;
- automatic `dump_text` enablement;
- absent option leaves unlimited behavior unchanged;
- rejection of zero, negatives, decimals, missing/extra/unknown units, missing values, and `uint64_t` overflow;
- invalid input is rejected before output creation.

### 12.2 Accounting tests

Using temporary directory fixtures, verify:

- both output roots are included;
- nested regular files are counted;
- empty/missing roots account as zero after creation;
- symlink targets are not followed or counted as regular output;
- owned stale temporary files are cleaned and excluded;
- unrelated regular files count;
- unreadable/invalid roots produce a typed output error.

### 12.3 Limited exporter tests

Use injected/fake extraction and conversion collaborators to verify:

- deterministic path/partition/inode order;
- no records start when initial usage already reaches the limit;
- the active file may take final usage over the limit;
- no later record starts after that overrun;
- outputs are never intentionally truncated;
- original extraction failure is isolated;
- conversion skip/failure preserves the original and traversal continues;
- service/transport failure stops traversal;
- existing originals and Markdown are reused without double-counting;
- replacement accounting uses old-to-new size deltas;
- a larger limit resumes from existing outputs;
- path escape and symlink destination attempts are rejected;
- summary counts and stop reasons are exact.

### 12.4 Python tests

Verify the shared conversion primitive and route for:

- specialized extractor success;
- raw UTF-8 fallback;
- Latin-1 fallback;
- likely-binary skip;
- empty-output skip;
- extractor exception isolation;
- temporary-file cleanup after failure;
- input confinement beneath `input_root`;
- derived output confinement beneath `output_root`;
- correct output path and byte size;
- unchanged batch counts, error isolation, and concurrency behavior after refactoring.

### 12.5 End-to-end acceptance

Run a small image with a deliberately small limit:

```bash
./build/forensic_analyzer test_image.img \
  --db-dir ./build/limited-output \
  --no-ai \
  --dump-text-max-size 1M
```

Acceptance criteria:

1. The size option automatically enables text dumping.
2. The normal raw, events, and files databases are generated successfully.
3. Both text-dump output trees contain complete valid files when convertible input exists.
4. Selection order is reproducible for the same image and pre-existing output state.
5. The final processing unit may exceed 1 MiB; no subsequent file starts.
6. CLI output reports configured limit, actual logical usage, counts, and stop reason.
7. Limit exhaustion does not make the command fail.
8. Rerunning with a larger limit reuses valid outputs and continues.
9. Plain `--dump-text` without the new option follows the existing unlimited batch path.
10. Invalid size syntax returns nonzero before the analyzer creates databases or dump directories.

## 13. Out of Scope

- Limiting core database size.
- Limiting `--report` output.
- Limiting stdout/stderr volume.
- Deleting original files after Markdown conversion.
- Partial-file or partial-Markdown truncation.
- Compression, quota reservation, or physical allocated-block accounting.
- Prioritizing by forensic relevance or file size; ordering is deterministic path order.
- Applying the option to HTTP-created analysis tasks or the web UI.
- Introducing an export manifest or changing database schemas.
