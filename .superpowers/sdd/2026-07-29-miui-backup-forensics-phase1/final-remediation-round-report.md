# Final Remediation Round Report

## Scope

Implemented the requested narrow final remediation round without modifying CMake files, `src/integration/AndroidAdbExtractor/`, or supplied evidence.

## Changes

1. **Duplicate MIUI `.bak` names**
   - `MiuiBackupExtractor` records which manifest package entries were accepted for unique `.bak` ownership.
   - The later duplicate remains represented as a `parse_error` package failure.
   - MIUI installed-app persistence writes only accepted manifest packages.
   - Entry enumeration skips rejected duplicate package entries, preventing the accepted archive's members from being attributed to the rejected package.
   - Added a production persistence regression that verifies the first package has the only installed-app row, the rejected package retains a failure inventory row, and no accepted archive member is attributed to the rejected package.

2. **Canonical raw-key Base64**
   - `decodeRawKeyBase64` now validates the unused low two bits of the final data sextet for the exact 44-character, one-padding raw-key form.
   - The integration regression exercises `42 * 'A' + 'B='` with a corrupt SQLite header and asserts the production encrypted-inventory status is `parse_error`, not an encrypted classification.

3. **SQLite filesystem paths containing URI-reserved characters**
   - `isPlaintextSqlite` now opens a filesystem path directly with `SQLITE_OPEN_READONLY`; it retains its existing SQLite header and read-only schema validation.
   - The MIUI inventory helper uses the same direct read-only filesystem-path form.
   - Added an integration regression that stages a valid note SQLite database while `TMPDIR` includes `#`, `?`, and `%`, then verifies the production note parser records the recovered note.

## Verification

- `g++ -std=c++17 -fsyntax-only ... AndroidLogicalParsers.cpp MiuiBackupExtractor.cpp MiuiArtifactParsers.cpp` — passed.
- `python3 -m py_compile tests/integration/test_miui_cli_e2e.py` — passed.
- Regression fixture check confirmed the noncanonical raw-key input is 44 characters, with final data sextet `1` and nonzero unused low bits.
- SQLite filesystem-path fixture successfully created and read a database named `staging#?%.db`.
- `git diff --check` — passed.

## Test Environment Constraint

The dedicated analyzer build could not be configured because the required local static Aliyun OSS SDK library is absent at `libs/aliyun-oss-cpp-sdk/build/lib/libalibabacloud-oss-cpp-sdk.a`. The pre-existing `web/tests/test_android_analyzer_gtest` executable is not the analyzer CLI expected by the integration regression; it failed before the MIUI database assertion with `MIUI artifact database was not created`. The source-level syntax checks and regression-script compilation above are therefore the available focused verification in this worktree.
