# Task 9 Report: MIUI Real-Backup End-to-End Smoke Test

## Status

Implemented and passed the real-backup MIUI smoke test. The script runs the production analyzer against the supplied offline evidence directory, writes the analyzer database only to a fresh `mktemp -d` directory, verifies MIUI metadata and generic application database inventory, checks `com.android.email`, then removes only that temporary output through an exit trap.

## Modified files

- `tests/test_miui_backup_e2e.sh`
  - New executable Bash smoke script.
  - Accepts an optional backup directory, defaulting to `/home/ymj68520/projects/Forensics/AndroidBackup`.
  - Runs `./build/forensic_analyzer "$BACKUP" --android-analyze --android-source miui-backup --db-dir "$OUT"`.
  - Asserts the expected output database exists, both `miui_backup_manifest` and `app_db_inventory` contain rows, and `app_db_inventory` includes `com.android.email`.
  - Uses `set -euo pipefail` and an exit trap that removes only its own temporary `OUT` directory.

- `.superpowers/sdd/2026-07-29-miui-backup-forensics-phase1/task-9-report.md`
  - This execution and review report.

No file under `src/integration/AndroidAdbExtractor/` was changed. No CMakeLists file was read or modified for this task.

## Commands and results

### Test-first evidence

Before the script was created, attempting to run its expected path failed because `tests/test_miui_backup_e2e.sh` did not exist. The new script is therefore an executable test of behavior that had no prior implementation.

### Production build

```bash
cmake -S . -B build -DBUILD_WEB_FRONTEND=OFF
cmake --build build --target forensic_analyzer -j2
```

Initial configuration failed because the worktree did not contain the ignored, locally-built Aliyun OSS static library required by the established project configuration. Root cause: `libs/aliyun-oss-cpp-sdk/build/` is ignored and therefore is not materialized in a fresh worktree.

The required existing third-party dependency was built locally without changing tracked source:

```bash
cmake -S libs/aliyun-oss-cpp-sdk -B libs/aliyun-oss-cpp-sdk/build \
  -DBUILD_SAMPLE=OFF -DBUILD_TESTS=OFF
cmake --build libs/aliyun-oss-cpp-sdk/build -j2
```

The production analyzer configuration/build then completed successfully.

### Smoke test

```bash
bash tests/test_miui_backup_e2e.sh
```

Result: PASS. Output ended with:

```text
MIUI backup E2E OK
```

The production run reported the MIUI logical/no-TSK route and created its artifact database at a temporary path outside the evidence directory. SQL assertions passed for non-empty `miui_backup_manifest`, non-empty `app_db_inventory`, and the expected `com.android.email` package inventory row.

### Static and scope checks

```bash
bash -n tests/test_miui_backup_e2e.sh
git diff --check
```

Result: PASS.

## Evidence non-mutation check

A deterministic file-list fingerprint, file count, and total byte size of `/home/ymj68520/projects/Forensics/AndroidBackup` were captured immediately before and after the real-backup analysis:

| Check | Before | After |
| --- | --- | --- |
| Sorted `size path` SHA-256 | `90b03db3bb2fe1d6c4711ae892dbaf1510236d7fd823df091eba1a70d3ae5a8e` | `90b03db3bb2fe1d6c4711ae892dbaf1510236d7fd823df091eba1a70d3ae5a8e` |
| Regular files | `55` | `55` |
| Directory size | `4122670095` bytes | `4122670095` bytes |

The identical values confirm the smoke run did not add, remove, rename, or resize evidence files. The analyzer output was created under `mktemp -d`, never underneath the supplied backup, and the script's exit trap removed that temporary output after assertions completed.

## Self-review

- The script follows the exact Task 9 CLI invocation and expected SQL evidence assertions.
- The optional positional backup argument preserves the required real-export default while allowing a separately located read-only copy when needed.
- Quoted variables support evidence paths containing spaces, Unicode, or parentheses.
- `trap cleanup EXIT` runs for both pass and failure paths and is limited to the script-created `OUT` path.
- The test executes the production `forensic_analyzer`, not a fixture-only or unit-test binary.
- Existing live ADB implementation remains untouched.

## Concerns

- The smoke test processes the full 4.1 GB evidence export, so it is intentionally an on-demand integration smoke test rather than a default fast unit test.
- The worktree required a local build of the ignored Aliyun OSS SDK static library before CMake could configure the production analyzer. This is an environment/setup prerequisite, not a source change.
- Analyzer startup emits a pre-existing parser diagnostic (`line 42:21 extraneous input '"*"'`) and reports absent legacy logical paths while continuing successfully; neither affects the Task 9 output database assertions.

## Commits

- Pending Task 9 commit at report-writing time.
