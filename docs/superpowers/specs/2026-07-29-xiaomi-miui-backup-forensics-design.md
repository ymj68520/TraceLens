# Xiaomi (MIUI) Backup Forensics Design

**Date:** 2026-07-29
**Status:** Approved
**Scope:** Add offline forensic analysis of Xiaomi/MIUI phone backups (`.bak` + `descript.xml`) to TraceLens, as a new Android data source, while preserving the existing live-device ADB module untouched.

## Problem Statement

The client (甲方) now requires forensic analysis performed from a **Xiaomi phone backup** instead of a live ADB-attached device. A real backup was exported to `/home/ymj68520/projects/Forensics/AndroidBackup`: it contains one `.bak` file per app plus a `descript.xml` manifest, totalling ~4 GB.

Investigation of the actual files (see *Format Background*) revealed the decisive fact: **a MIUI `.bak` file is a small MIUI text header followed verbatim by a standard Android Backup stream** (`ANDROID BACKUP` + a tar of `apps/<pkg>/db|f|sp/...`). That tar is exactly the `/data/data/<pkg>/` tree shape that the existing `AndroidAnalyzer` already parses through its `dir` and `zip` source modes.

Therefore the feature is, at its core, **a new `IFileExtractor` backend** that feeds the offline MIUI backup into the existing forensic pipeline. The live-device module `AndroidAdbExtractor` (`src/integration/AndroidAdbExtractor/`) operates on a connected device and is fully decoupled; it is left unchanged.

The client also requires (a) AES-256 decryption of password-protected backups this iteration, (b) both CLI and Web entry points, and (c) extraction of MIUI-specific artifacts beyond what the generic Android analyzers already produce.

## Goals

1. **New offline source.** Analyze a MIUI backup folder (`descript.xml` + `*.bak`) end-to-end through the existing `AndroidAnalyzer`, producing the standard `_android.db` artifacts (SMS, contacts, call logs, notes, device identifiers, encrypted-DB inventory, etc.).
2. **Preserve the ADB module.** `AndroidAdbExtractor` is not modified; the new path is purely additive.
3. **On-demand streaming.** Read individual files out of the `.bak` tar streams on demand, without extracting ~4 GB to disk — mirroring the existing `ZipArchiveExtractor` design.
4. **Transparent path mapping.** Map the backup's `apps/<pkg>/db|f|sp/...` layout to the `data/data/<pkg>/databases|files|shared_prefs/...` paths the analyzers query, so the **nine existing `extractFileByPath` call sites change by zero lines**.
5. **AES-256 decryption (this iteration).** Decrypt `AES-256-encrypted` backups given a password, implementing the AOSP `adb backup` v5 scheme; never silently fail or emit wrong data on an unrecognized scheme.
6. **MIUI-specific artifacts (all apps).** Capture every MIUI app's data: a universal DB **inventory** guarantees nothing is silently lost, plus **targeted parsers** for high-value apps, plus a low-friction **registry** so new app parsers are added with minimal code.
7. **Dual entry points.** `--android-source miui-backup` on the CLI and a "Xiaomi backup" source type in the Web task-creation flow, with an optional backup-password field.
8. **Forensic integrity.** Preserve the existing hash verification and `AuditLog` audit trail for the new source.

## Non-Goals

- Modifying `AndroidAdbExtractor`, `ADBClient`, or any live-device code path.
- Building a new tar/zip/crypto stack where an existing dependency suffices (reuse libzip/zlib/OpenSSL already in the build via SQLCipher/WeChatDecryptor).
- Reverse-engineering app-specific SQLCipher KDFs beyond what `SqlCipherDatabase` already supports (record-and-defer for locked app DBs, as today).
- Producing a MIUI-specific *report renderer*; outputs land in the same `_android.db` consumed by the existing report/UI layers.
- Network/cloud acquisition of backups; the input is always a local backup folder (or a single `.bak`).

## Format Background (verified against the real backup)

### `.bak` file layout
A `.bak` is a sequence of newline-terminated text header lines followed by a byte payload. For every sampled file the structure was identical:

```
MIUI BACKUP                       <- MIUI magic
2                                 <- MIUI backup format version
com.tencent.mm 微信               <- "<packageName> <displayName>" (UTF-8; name may contain spaces/CJK)
-1                                <- (MIUI field)
0                                 <- (MIUI field)
ANDROID BACKUP                    <- Android Backup magic (start of standard stream)
5                                 <- Android Backup format version (1..5)
0                                 <- compression: 0 = none, 1 = zlib-deflate
none                              <- encryption: "none" | "AES-256-encrypted"
<payload>                         <- tar (comp=0) | zlib(tar) (comp=1) | AES(...) of [comp](tar) (encrypted)
```

The MIUI header length varies per file (packageName/displayName differ), so the parser locates `ANDROID BACKUP` by scanning, then reads exactly the next 3 lines (version, compression, encryption), then treats the remainder as the (possibly compressed/encrypted) tar.

### Tar payload structure (Android Backup convention)
```
apps/<pkg>/_manifest              <- app manifest (versionCode/versionName/signatures/permissions)
apps/<pkg>/db/<file>              <- /data/data/<pkg>/databases/
apps/<pkg>/f/<file>               <- /data/data/<pkg>/files/
apps/<pkg>/sp/<file>              <- /data/data/<pkg>/shared_prefs/
apps/<pkg>/r/<file>               <- restore scripts (when present)
apps/<pkg>/miui_meta/...          <- MIUI-specific per-app metadata
apps/<pkg>/miui_bak/...           <- MIUI-specific per-app metadata
```
Verified: `电子邮件(com.android.email).bak` carries 17 databases (`Contact.db`, `EmailProviderBackup.db`, ...), 8 files, 6 shared_prefs. On a fresh/empty phone many apps are near-empty (e.g. deskclock has only `_manifest` + miui dirs); the parser handles both.

### `descript.xml` manifest
```xml
<MIUI-backup>
  <device>cepheus</device>            <!-- hardware codename -->
  <miuiVersion>V12.5.6.0.RFACNXM</miuiVersion>
  <date>1785299538978</date>           <!-- epoch milliseconds -->
  <size>4122640883</size>
  <packages>
    <package>
      <packageName>com.android.mms</packageName>
      <bakFile>短信设置(com.android.mms).bak</bakFile>
      <bakType>1</bakType>             <!-- observed: 1 = app-data backup -->
      <pkgSize>...</pkgSize><sdSize>...</sdSize>
      <state>1</state><error>0</error>
      ... (sizes/progress fields) ...
    </package>
    ...
  </packages>
</MIUI-backup>
```
`bakFile` filenames contain CJK + parentheses; paths must be handled as UTF-8 (the ADB module already solved cross-platform encoding; the same discipline applies).

## Design Decisions

### Decision 1: A new `IFileExtractor` backend, not a pre-extraction step
**Chosen over:**
- *Extract all `.bak` to a `data/` dir, then reuse `--android-source dir`* — simplest and reuses tested code, but materializes ~4 GB to disk and breaks the "read on demand" consistency of the other backends. Rejected for disk/time cost.
- *A new analyzer stage that parses backups directly* — would duplicate the entire `AndroidAnalyzer` parsing surface. The backup tar is structurally identical to an ADB logical extraction, so it belongs behind `IFileExtractor`, not as a parallel analyzer.

The backend sits beside `LogicalDirExtractor` and `ZipArchiveExtractor` in `src/analyzers/AndroidAnalyzer/`, implements the same `extractFileByPath(imageRelPath, outPath)` contract, and is selected by the existing `sourceMode_` switch. This keeps all parsing logic single-sourced.

### Decision 2: Locate the Android Backup magic by scan, not fixed offset
The MIUI header is variable-length. The parser reads the first ~4 KiB, finds the `ANDROID BACKUP\n` marker, then consumes exactly three more lines (version / compression / encryption) before the payload begins. This is robust to MIUI header field changes and to the displayName containing arbitrary bytes.

### Decision 3: Path mapping as an isolated, queryable translation layer
The backend builds an index of tar entries keyed by the **mapped** image-relative path (`apps/<pkg>/db/X` is indexed under both `apps/<pkg>/db/X` *and* `data/data/<pkg>/databases/X`). `extractFileByPath` then resolves any of the path shapes the analyzers use (with/without leading slash, `data/data/...` vs `apps/...`). Mapping table:

| Analyzer query (TSK-style) | Tar entry |
|---|---|
| `data/data/<pkg>/databases/X` | `apps/<pkg>/db/X` |
| `data/data/<pkg>/files/X` | `apps/<pkg>/f/X` |
| `data/data/<pkg>/shared_prefs/X` | `apps/<pkg>/sp/X` |
| `data/data/<pkg>/_manifest` | `apps/<pkg>/_manifest` |

`miui_meta/` and `miui_bak/` are indexed under their native paths for the MIUI-artifact parsers (Decision 6) and are not exposed through the `data/data/` alias.

### Decision 4: A pluggable de-obfuscation pipeline before the tar index
Raw payload → optional **decrypt** → optional **inflate** → tar. Each `.bak`'s header determines which stages run. Decrypt is an interface (`IBackupDecryptor`) so the AOSP v5 scheme is one implementation and a future MIUI-specific scheme is another, swappable without touching the indexer.

### Decision 5: AES-256 via the AOSP `adb backup` v5 scheme, validated against a locally-generated fixture
When `encryption == "AES-256-encrypted"`, implement the documented AOSP full-backup v5 two-level scheme (algorithmic level — exact byte constants confirmed against AOSP `BackupManagerService`/`FullBackup` source during implementation):

1. Read header: password salt, cipher salt, IV, and the encrypted master-key block.
2. `userKey = PBKDF2-HMAC-SHA1(password, passwordSalt, 10000, 256-bit)`.
3. Decrypt the master-key block with `userKey` + IV (AES-256-CBC) → master key.
4. `cipherKey = PBKDF2-HMAC-SHA1(hex(masterKey), cipherSalt, 10000, 256-bit)`.
5. Decrypt the payload with `cipherKey` + IV → (optionally compressed) tar.

Crypto uses the OpenSSL already linked into the build (SQLCipher / `WeChatDecryptor` depend on it).

**Validation without a MIUI encrypted sample:** correctness is unit-tested against an AOSP-compatible encrypted fixture generated locally (e.g. `abe.jar pack plain.tar out.ab "<pw>"`), since the bytes produced by `adb backup`/`bu` are the reference. This proves the *cryptography* is correct independent of MIUI.

**Residual risk (explicit):** the provided backup is unencrypted, so we cannot confirm MIUI uses the *same* `AES-256-encrypted` marker/scheme. Mitigation: (a) the decryptor is an interface; (b) on an unrecognized marker or decryption integrity failure, the backend reports the app as `encrypted_locked` with the observed marker — it never fabricates data. A follow-up MIUI-encrypted sample, if later provided, plugs in as a second `IBackupDecryptor`.

### Decision 6: "Do all MIUI apps" via inventory + targeted parsers + registry
Hand-writing a schema parser per app is fragile (version-dependent) and infeasible for ~60 apps. Instead, three layers guarantee full coverage:

1. **Universal DB inventory (nothing lost).** For every app's every database file found in a backup, record `(package, db_path, table_name, row_count, columns_csv)` into an `app_db_inventory` table. This is schema-agnostic and guarantees investigators a complete map of recoverable data, even for apps with no dedicated parser.
2. **Targeted parsers (high value).** Structured parsers for apps whose schemas are worth decoding, each writing its own table. Priority set (confirmed present in this backup):
   - Backup manifest (`descript.xml` + per-app `_manifest`) → device snapshot + installed-app inventory.
   - `com.autonavi.minimap` (Amap) → location/search history.
   - `com.xiaomi.market` (app store) → download/install history.
   - `com.mi.health` (health) → activity/health records.
   - `com.miui.notes`, `com.android.soundrecorder`, `com.android.calendar`, `com.android.email` → notes/recordings/events/mail.
   - `com.android.settings` / WLAN → saved Wi-Fi SSIDs/credentials.
   - `com.xiaomi.smarthome` (Mi Home), `com.duokan.phone.remotecontroller` → IoT pairings / IR-remote usage.
   - Browsers (`com.android.browser`, `com.UCMobile`), shopping (`com.taobao.taobao`, ...), social (`com.sina.weibo`, `com.ss.android.ugc.aweme`) as schemas allow.
3. **Registry (low-friction extensibility).** A `MiuiAppParser` registry keyed by `packageName`; each parser is a small class that receives the `IFileExtractor` and the analysis DB and writes its table. Adding an app = register one class. Apps with no parser still appear in the inventory (layer 1).

Each targeted parser's exact SQL is **discovered empirically** from the real DB during implementation; if a schema differs from expectation the parser records what it found rather than crashing.

### Decision 7: Dual entry points, additive wiring
- `AndroidSourceMode` gains `MiuiBackup`; the dispatch switch constructs the new backend.
- CLI: `--android-source miui-backup` (value joins `tsk|dir|zip`) and a new `--backup-password <pw>`.
- Web: a "Xiaomi backup" source type in the task-creation modal with an optional password field; the backend forwards source mode + password into the pipeline.
- The `imagePath` for this source is the **backup folder** (the directory containing `descript.xml`); a single `.bak` is also accepted (one-app mode).

## Architecture

### New module: `MiuiBackupExtractor` (IFileExtractor backend)
Location: `src/analyzers/AndroidAnalyzer/MiuiBackupExtractor.{h,cpp}` (alongside the other two backends).

Internal components (split into focused files; each has one purpose, is testable in isolation, and hides its internals):

- `MiuiBackupManifest` — parses `descript.xml` → list of `(packageName, bakFile, bakType, sizes, device, miuiVersion, date)`.
- `AndroidBackupHeader` — scans one `.bak`, returns `(version, compression, encryption)` and the byte offset where the payload begins.
- `IBackupDecryptor` + `AospV5Decryptor` — Decision 4/5; `nullptr` for unencrypted backups.
- `TarIndex` — given a payload reader (with decrypt/inflate applied), builds `map<mappedPath, TarEntry{bakFile, dataOffset, size}>` by streaming 512-byte tar headers (no full materialization).
- `MiuiBackupExtractor` — orchestrates: open folder → manifest → per-`.bak` header + (decrypt/inflate) + index → serve `extractFileByPath` via `pread`-style seek/read.

### Data flow
```
backup folder ──► MiuiBackupManifest (descript.xml)
                 │
   per .bak ───► AndroidBackupHeader ──► [AospV5Decryptor?] ──► [inflate?] ──► TarIndex
                 │                                                              │
                 └──────────────► combined map: imageRelPath → TarEntry ◄──────┘
                                        │
            AndroidAnalyzer (9 call sites) ──► extractFileByPath() ──► seek+read bytes ──► _android.db
                                        │
            MIUI artifact parsers (inventory + targeted) ──► miui_* tables in _android.db
```

### MIUI artifact parsers
New sources: `src/analyzers/AndroidAnalyzer/MiuiArtifactParsers.{h,cpp}` (registry + targeted parsers), invoked from the analysis flow after the generic analyzers run, reading through the same `MiuiBackupExtractor` (so they share decryption/decompression transparently). Results land in the `AndroidAnalysisDatabase`.

## Data Model (new tables in `_android.db`)

- `miui_backup_manifest` — one row per backup: `device, miui_version, backup_date(epoch_ms), total_size, package_count, source_folder`.
- `installed_apps` — one row per package: `package_name, display_name, version_code, version_name, data_size, sd_size, bak_type, manifest_summary` (from `descript.xml` + `_manifest`).
- `app_db_inventory` — one row per (app, db, table): `package_name, db_path, table_name, row_count, columns, open_status` (Decision 6 layer 1; `open_status` reuses `decrypted`/`encrypted_locked`).
- `miui_appstore_downloads`, `miui_amap_locations`, `miui_wifi_networks`, `miui_health_records`, `miui_notes` (if not already populated by the generic note parser), etc. — one table per targeted parser, columns per discovered schema.

## Integration (exact touch points)

| Concern | File | Change |
|---|---|---|
| Source enum | `src/analyzers/AndroidAnalyzer/AndroidAnalyzerDeclarations.h:29` | add `MiuiBackup` to `enum class AndroidSourceMode` |
| Backend dispatch | `src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp:24` | add `case MiuiBackup: fileExtractor_ = make_unique<MiuiBackupExtractor>(imagePath_);` |
| CLI flag | `src/CommandLineParser.cpp:162` (`src/CommandLineParser.h:33`) | accept `miui-backup`; add `--backup-password` |
| Enum mapping | wherever `args.android_source` → `AndroidSourceMode` | add `miui-backup` → `MiuiBackup` |
| Web source | task-creation modal + backend task model | add "Xiaomi backup" type + password field; forward mode+password |
| Build | AndroidAnalyzer CMake target | add new `.cpp` sources; crypto via existing OpenSSL linkage |

## Error Handling & Forensic Integrity

- Unknown/unsupported encryption marker, decryption integrity failure, or truncated tar → the offending app is recorded as `encrypted_locked` / `parse_error` in the inventory; processing of other apps continues. No silent skip, no fabricated bytes.
- Every `.bak` byte-offset seek and every extracted file is logged to `AuditLog`; extracted files retain SHA-256 via the existing hash path.
- The backup folder is opened **read-only**; no writes back to the evidence.

## Testing Strategy

- **Unit:** MIUI header scan (variable length, CJK displayName); Android Backup header parse (ver/comp/enc); path-mapping table (both directions + leading-slash tolerance); `TarIndex` seek/read correctness; **AES decryptor validated against a locally-generated AOSP fixture** (`abe.jar pack`).
- **Integration (real backup):** end-to-end run over `/home/ymj68520/projects/Forensics/AndroidBackup`; assert `EmailProviderBackup.db` records surface via the generic analyzer, `miui_backup_manifest` + `installed_apps` are populated, and `app_db_inventory` covers all apps with DBs.
- **Negative:** unencrypted-default path (no password) and unrecognized-encryption path (synthetic bad marker) both behave correctly.
- Determinism: same backup ⇒ identical `_android.db` artifact set across runs.

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| MIUI encrypted backups use a non-AOSP scheme | Medium | Pluggable `IBackupDecryptor`; detect-and-report on unknown marker; no MIUI sample available this iteration (client confirmed). |
| App DB schemas vary by app version | High | Inventory layer guarantees coverage; targeted parsers record-what-they-find and degrade gracefully. |
| Large `.bak` (e.g. WeChat 645 MB) memory/time | Medium | Streaming tar header parse + seek-on-demand reads; never load whole file. |
| CJK/parentheses in `bakFile` paths | Low | UTF-8 path handling (ADB module precedent). |
| tarstream is compressed (comp=1) — no random access | Medium | For compressed payloads, the indexer inflates to a temp stream once and indexes offsets within it (still no full per-file extraction to the evidence area); documented as the one case needing a temp file. |

## Resolved Questions

1. *Encrypted sample available?* — No (client). Proceed with AOSP v5 + pluggable + local-fixture validation + detect-and-report.
2. *MIUI artifact scope?* — All apps ("都做"). Implemented via inventory + targeted parsers + registry.
