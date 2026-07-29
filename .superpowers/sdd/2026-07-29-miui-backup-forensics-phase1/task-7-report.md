# Task 7 Report — MIUI Artifact Manifest and Database Inventory

## Status

Implemented Task 7 without production wiring and without changes under `src/integration/AndroidAdbExtractor/` or any CMake file.

## Files

### Created

- `src/analyzers/AndroidAnalyzer/MiuiArtifactParsers.h`
  - Declares `writeMiuiManifest` and `writeAppDbInventory`.
- `src/analyzers/AndroidAnalyzer/MiuiArtifactParsers.cpp`
  - Writes the MIUI backup manifest and installed-app rows through the existing parameter-bound database API.
  - Enumerates application database artifacts, extracts bounded private temporary copies, opens SQLite evidence read-only, and records table names, bounded row counts, columns, and statuses.
  - Processes SQLite WAL/SHM/rollback-journal sidecars as a bundle with their primary DB, rather than misclassifying sidecars as independent DBs.
  - Records `parse_error` or `encrypted_locked` instead of silently omitting failures.

### Modified

- `src/analyzers/AndroidAnalyzer/MiuiBackupExtractor.h`
  - Added required `EntryVisitor`, `enumerateEntries`, and `extractTarMember` APIs.
  - Added `entrySize` for bounded extraction preflight.
  - Added read-only package failure access so encrypted or malformed package streams can be persisted by Task 7.
- `src/analyzers/AndroidAnalyzer/MiuiBackupExtractor.cpp`
  - Implements deterministic entry enumeration and raw tar-member extraction.
  - Tracks encrypted/malformed/indexing failures.
  - Creates output parents/files with owner-only permissions before extraction.
- `tests/UnitTest/test_miui_backup_gtest.cpp`
  - Added manifest and invalid-DB inventory coverage.
  - Added real SQLite table/row/column inventory coverage.
  - Added WAL-sidecar regression proving uncheckpointed rows are included.
  - Added encrypted-package failure persistence coverage.
  - Added oversized sparse DB-member rejection coverage.
  - Added private output permission assertion on POSIX.

## Security and Forensic Behavior

- No shell-outs are used for evidence metadata or SQLite schema/row inspection.
- Evidence backup files remain read-only and unchanged.
- SQLite evidence copies are opened with `SQLITE_OPEN_READONLY` and URI `mode=ro`.
- Candidate DB extraction is preflight-bounded to 512 MiB per member and 768 MiB per DB bundle.
- Row inventory walks at most 10,001 rows per table and has an SQLite VM instruction budget; it never asks SQLite to count an unlimited table.
- Table count, SQLite value length, SQL length, and column count are bounded.
- Temporary directories are owner-only; extracted DB and sidecar files are owner read/write only.
- WAL, SHM, and rollback-journal sidecars are extracted adjacent to the primary DB before SQLite opens it, preserving live SQLite state in the inventory.
- Sidecars are not emitted as independent inventory failures.
- Malformed, over-limit, extraction-failed, and encrypted sources produce explicit failure rows.
- Enumeration order is deterministic by manifest package order and sorted member path.
- Database writes use the existing `AndroidAnalysisDatabase::insert*` methods, which bind parameters.

## Tests and Results

### TDD red verification

Before production implementation, compiling the new tests failed as expected because `MiuiArtifactParsers.h` did not exist.

### Final verification

Command used a manual target-equivalent compile because the provided worktree has no configured local build directory and the user explicitly prohibited reading/modifying CMake files:

```text
c++ -std=gnu++20 -DUSE_ZLIB ... \
  tests/UnitTest/test_miui_backup_gtest.cpp \
  AndroidBackupHeader.cpp TarIndex.cpp MiuiBackupManifest.cpp \
  MiuiBackupExtractor.cpp MiuiArtifactParsers.cpp AndroidAnalysisDatabase.cpp \
  -lgtest -lsqlite3 -lz -pthread
/tmp/tracelens-task7-miui-tests --gtest_color=no
```

Result: **28 tests passed, 0 failed**.

Additional checks:

- `git diff --check`: passed.
- `-Wall -Wextra -Wpedantic` compile: passed without diagnostics.
- Independent post-remediation review: **No blocking findings**.

## Self-Review

- Interfaces match the Task 7 brief.
- No Task 8 analyzer/orchestrator/CLI wiring was added.
- No ADB integration files were touched.
- No CMake file was read or modified in the worktree.
- No evidence metadata is gathered through a shell command.
- Temporary forensic artifacts are bounded, private, and cleaned with RAII.
- SQLite dynamic identifiers are quoted through `sqlite3_mprintf("%w", ...)`; metadata lookups and all output DB values use binding through existing APIs.
- Read failures are represented explicitly rather than being reported as successfully decrypted.

## Concerns / Deferred Scope

- The row count is exact only up to the Task 7 safety cap of 10,000 rows per table. Tables exceeding the cap receive a `parse_error` failure row rather than an unbounded count. This is intentional to satisfy the no-unbounded-evidence-read requirement using the existing schema, which has no dedicated `capped` status or count flag.
- Task 8 still owns build-source registration and production invocation of these writers.

## Independent Review Follow-up

A coordinator review identified four remaining hardening gaps. They were addressed as follows:

- Every manifest-declared package path rejection now appends a `parse_error` `PackageFailure`, including empty/absolute/traversal paths, missing or unreadable files, symlinks, and paths that resolve outside the backup folder.
- `initialize()` now reports readiness after a valid manifest and backup folder are established, even when every package is encrypted or malformed. This guarantees Task 7 writers can persist the collected package failures.
- POSIX inventory directories now use `mkdtemp`, which atomically creates an owner-only directory. POSIX evidence file slots use `mkstemp` and atomic rename, avoiding predictable truncating opens and symlink following. The Windows fallback retains exclusive existence checks and explicit owner-only permissions.
- Serialized column metadata is capped at 4 KiB. Exceeding the cap deterministically creates a `parse_error` inventory row instead of an unbounded string.

Focused regression coverage now includes encrypted-only initialization, missing/absolute/traversal/symlink package failures, oversized column metadata, and protection against a pre-existing temporary-path symlink. Existing row-bound, WAL bundle, oversize member, and failure-recording tests remain green.

## Latest Review-Fix Test Result

Focused command filter: `MiuiBackupExtractorTest.*:MiuiArtifactTest.*`

Result: **15 tests passed, 0 failed**.

## Commits

- `4a435c5 feat(android): add MIUI artifact inventory pass`
- `c0a5d6e fix(android): harden MIUI inventory failures`
