# Task 8 Report: MIUI Offline Backup Production Integration

## Status

Implemented and review-hardened production support for `--android-source miui-backup`, including strict CLI value validation, password-safe failure handling, analyzer/orchestrator wiring, MIUI database writer invocation, production/test source registration, and automated subprocess coverage.

## Files changed

### Initial Task 8 integration

- `CMakeLists.txt`
  - Added the five existing MIUI implementation units to production `LIB_SOURCES` immediately after `ZipArchiveExtractor.cpp`.
- `src/analyzers/AndroidAnalyzer/AndroidAnalyzerDeclarations.h`
  - Added `AndroidSourceMode::MiuiBackup`.
  - Added `setBackupPassword()` and private password storage.
- `src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp`
  - Added MIUI extractor dispatch.
  - Applies the backup password before `MiuiBackupExtractor::initialize()`.
  - Initializes `AndroidAnalysisDatabase` before `writeMiuiManifest()` and `writeAppDbInventory()`.
- `src/AnalysisOrchestrator.cpp`
  - Routes `miui-backup` through the no-TSK logical path.
  - Selects `MiuiBackup` mode and forwards the backup password.
- `src/CommandLineParser.h`
  - Added `backup_password` and documented `miui-backup`.
- `src/CommandLineParser.cpp`
  - Parses `--backup-password` and advertises the new source mode.
- `tests/UnitTest/test_command_line_parser.cpp`
  - Added valid MIUI/password and legacy-source parser coverage.

### Review fixes

- `src/CommandLineParser.cpp`
  - Requires value-bearing string/path options to receive a non-option token.
  - Whitelists `--android-source` to exactly `tsk`, `dir`, `zip`, or `miui-backup`.
  - Returns `parse_error` immediately for a missing/flag value or unknown source before later argv tokens can become positional evidence paths.
  - Does not include supplied password values in errors.
- `src/main.cpp`
  - Keeps parse failure output generic to the actual `parse_error`; removed the unrelated dump-size-only hint for all parser failures.
- `tests/CMakeLists.txt`
  - Added only `MiuiArtifactParsers.cpp` to the known `test_miui_backup_gtest` source list, repairing its unresolved writer symbols.
  - Registered the focused MIUI CLI subprocess test.
- `tests/UnitTest/test_command_line_parser.cpp`
  - Added regression tests for a flag used as the source value, an unknown source value, and a flag used as the backup-password value.
- `tests/integration/test_miui_cli_e2e.py`
  - Creates a minimal MIUI backup fixture and invokes the production binary.
  - Verifies MIUI routing bypasses TSK, artifact rows are persisted, and the password is absent from stdout/stderr.
  - Verifies malformed option shifting and unknown source values fail with status 2 before analysis and do not expose the trailing secret.

No file under `src/integration/AndroidAdbExtractor/` was changed.

## TDD / regression evidence

The validation tests were written before the review fix. All three failed against the previous parser:

- `RejectsFlagAsSourceValueBeforeConsumingSecret`: parser had no error, stored `--backup-password` as the source, and replaced `image_path` with `topsecret`.
- `RejectsUnknownSource`: parser silently accepted `vendor-backup`.
- `RejectsFlagAsBackupPasswordValue`: parser silently stored `--no-ai` as the password.

After the parser validation change, all parser tests pass.

## Exact verification and results

Build configuration used for C++/test verification:

```bash
cmake -S . -B build -DBUILD_WEB_FRONTEND=OFF
```

The optional frontend was disabled because this worktree does not have local npm/vite dependencies installed; this does not alter C++ analyzer behavior.

### Full C++ build

```bash
cmake --build build -j2
```

Result: PASS. All configured C++ targets built successfully, including `forensic_analyzer`, `test_miui_backup_gtest`, parser tests, and the remaining test executables.

### Task 8 relevant targets and tests

```bash
cmake --build build --target \
  forensic_analyzer \
  test_command_line_parser \
  test_android_logical_source_gtest \
  test_miui_backup_gtest -j2

ctest --test-dir build \
  -R '^(CommandLineParserTests|AndroidLogicalSourceGTests|MiuiBackupHeaderTests|MiuiCliEndToEndTests)$' \
  --output-on-failure
```

Result:

- `MiuiBackupHeaderTests`: PASS, 31 internal GTests.
- `AndroidLogicalSourceGTests`: PASS.
- `MiuiCliEndToEndTests`: PASS.
- `CommandLineParserTests`: PASS, 17 internal GTests.
- CTest total: 4/4 passed, 0 failed.

### Automated MIUI subprocess coverage

`MiuiCliEndToEndTests` invokes the actual `forensic_analyzer` binary with a generated offline MIUI backup. Assertions include:

- Exit status 0 for valid `miui-backup` analysis.
- Output does not contain the password sentinel.
- Output does not contain `Using The Sleuth Kit`, proving logical/no-TSK routing.
- `backup_files.db` exists.
- `miui_backup_manifest` contains `task8-device`, `V12`.
- `installed_apps` contains `com.foo`.
- `app_db_inventory` contains `com.foo`, `apps/com.foo/db/x.db`, `parse_error` for intentionally non-SQLite fixture bytes.
- `--android-source --backup-password <secret>` returns status 2, reports `Missing value for --android-source`, does not reach analysis, and does not print the secret.
- `--android-source vendor-backup` returns status 2 with `Invalid --android-source`.

### Complete CTest suite

```bash
ctest --test-dir build --output-on-failure
```

Result: 57/58 passed. The sole failure is unrelated, pre-existing `TaskScenarioTests` / `AnalysisTaskTest.ScenariosFieldSerialization`, which throws:

```text
[json.exception.type_error.302] type must be string, but is number
```

All Task 8, MIUI, Android logical-source, parser, and subprocess tests pass in that full run.

### Formatting / scope checks

```bash
git diff --check
```

Result: PASS.

The diff contains no path under `src/integration/AndroidAdbExtractor/`.

## CLI validation and secret handling

- Every string/path option represented in `optionRequiresNonOptionValue()` fails if missing or followed by another option token.
- Negative numeric `--dll-threshold` values retain their prior parsing behavior and are not classified as missing string values.
- Android source mode accepts only `tsk`, `dir`, `zip`, and `miui-backup`.
- Parser errors return before analysis routing, preventing a trailing secret from becoming `image_path` and being printed by `runAnalysis()`.
- Neither valid nor malformed MIUI CLI paths print the backup password.
- The password remains present in process argv by design of the required CLI interface; a stdin alternative would be a future security enhancement.

## Legacy behavior validation

- TSK remains the default `AndroidSourceMode` and existing `FileExtractor`/`DatabaseManager` branch.
- `dir` still selects `LogicalDirExtractor`.
- `zip` still selects `ZipArchiveExtractor`.
- Parser tests explicitly accept all three legacy source strings without synthesizing a backup password.
- `AndroidLogicalSourceGTests` passes.
- `src/integration/AndroidAdbExtractor/` remains unchanged.

## Error propagation and database ordering

- CLI parse errors return status 2 before `AnalysisOrchestrator::runAnalysis()`.
- Extractor initialization failure returns `false` and causes the logical orchestrator path to return 1.
- Android database initialization must succeed before either MIUI writer is called.
- `writeMiuiManifest()` runs before `writeAppDbInventory()` as required.
- The backup password is assigned before MIUI extractor initialization.

## Self-review

- Confirmed the original high-severity option-shifting sequence can no longer move a secret into positional input.
- Confirmed unknown source values cannot fall through to TSK or logical analysis.
- Confirmed the MIUI test target now links its writer implementation through one isolated source-list addition.
- Converted the essential manual CLI checks into repeatable CTest subprocess coverage.
- Kept production CMake registration narrow and made only the explicitly authorized MIUI test-target/link/e2e registration changes in `tests/CMakeLists.txt`.
- Preserved analyzer initialization and writer ordering.

## Concerns

1. Phase 1 stores the backup password but encrypted payloads remain `encrypted_locked`; AES processing is deferred to a later phase.
2. The repository-wide `TaskScenarioTests` failure is outside Task 8 and remains unresolved; all relevant Task 8 tests pass.
3. The CLI password is not logged but is visible through normal process-argv inspection while the process runs.

## Commits

- `c8e501a` — initial Task 8 implementation and parser tests.
- `61a905e` — initial Task 8 report.
- Review-fix commit — recorded after this updated report and fixes are committed.
