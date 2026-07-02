# Memory Forensics Module — Design Spec

- **Date**: 2026-06-22
- **Status**: Approved (design)
- **Owner**: ymj68520
- **Target image**: `TestImgs/decrypted_images/决赛服务器/内存镜像/mem.lime` (4 GB Linux LiME dump, magic `EMiL`)

## 1. Goal

Add a **MemoryAnalyzer** module to the Digital Forensics Image Analysis Tool that performs memory forensics on RAM images via **Volatility3** (run as a subprocess from C++), parses its JSON output, and stores results in a dedicated SQLite database exposed through the existing HTTP API and web UI.

This is a **non-filesystem analyzer** (like the Android logical path): it does **not** go through the TSK / `_raw.db` / `FileClassifier` pipeline. A raw RAM dump is not a disk image, so the analyzer takes its own dispatch path that writes directly to a `_<baseName>_memory.db`.

## 2. Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Analysis engine | **Volatility3** invoked as a subprocess; parse JSON output with `nlohmann::json` |
| Feature scope (phase 1) | **Server full suite** — process list, network connections, sockets, bash history, boot time, cmdline |
| Vol3 deployment | Reuse the `python_service/.venv` virtualenv; add `volatility3` to `python_service/httpserver/requirements.txt` |
| DB model | Standalone `_<baseName>_memory.db` (not the `_files.db` artifacts-table path) |
| Scene type | Phase 1 does **not** add a `SceneType::MEMORY` value — memory surfaces via dedicated `/api/forensics/memory/*` endpoints |

## 3. Scope

### In scope (phase 1)
- LiME-format Linux memory images (the available test image).
- Volatility3 `linux.*` plugins: `linux.pslist`, `linux.bash`, `linux.netstat`, `linux.sockstat`, `linux.boottime`, `linux.cmdline`.
- CLI: `--memory-analyze` flag.
- New `_memory.db` schema with horizontal record tables.
- HTTP endpoints under `/api/forensics/memory/*`.
- A web page at `/memory`.
- Validation against the five server-memory challenge questions:
  - Q100 uptime (boottime → image acquisition time)
  - Q101 SSH session count (netstat, filter `:22`)
  - Q102 dangerous `rm` deletion command time (bash history)
  - Q103 ZFS snapshot name (bash history, `zfs snapshot`)
  - Q104 ZFS dataset unlock password (bash history, `zfs load-key`/`zfs mount`, if captured)

### Out of scope (phase 1)
- Windows memory support (no Windows RAM image available to validate).
- Memory malware / kernel rootkit scanning.
- Mobile / robot memory (non-standard formats).
- Custom Volatility3 plugins (phase 1 uses only built-in `linux.*` plugins).
- Auto-detection of image type (user passes `--memory-analyze` explicitly).

## 4. Architecture

```
mem.lime (LiME)
  → C++ MemoryAnalyzer::analyzeMemoryData()
    → Volatility3Runner (subprocess)
      → .venv/bin/vol -r json -p <plugin> -f <mem_path>   (one call per plugin)
    → JSON output → nlohmann::json
    → MemoryAnalysisDatabase (SQLite, mirrors LinuxAnalysisDatabase)
      → _memory.db: processes, network_connections, sockets,
                    bash_history, boot_info, cmdline, analysis_meta
  → HTTP:  /api/forensics/memory/*   (new MemoryForensicsRoutes)
  → Web:   /memory page
```

### Why a standalone `_memory.db`
Memory records (processes, connections, command history) are **horizontal record tables**, not file rows. They do not fit the `FileClassifier` artifact model (one row = one file). A standalone DB matches the existing `_android.db` / `_linux.db` convention and keeps schema intent clear.

## 5. Module layout (mirrors `LinuxFilesAnalyzer`)

```
src/analyzers/MemoryAnalyzer/
├── MemoryAnalyzer.h                    # aggregator header (mirrors LinuxFilesAnalyzer.h)
├── Core/
│   ├── MemoryAnalyzerDeclarations.h    # class declaration
│   └── MemoryAnalyzerCore.cpp          # initialize() + analyzeMemoryData() orchestration
├── Volatility/
│   ├── Volatility3Runner.h / .cpp      # subprocess invocation, JSON capture, timeout/error handling
│   └── VolatilityPlugins.h             # plugin-name constants (linux.pslist, etc.)
├── Parsers/
│   ├── ProcessParser.h / .cpp          # linux.pslist  → processes
│   ├── NetworkParser.h / .cpp          # linux.netstat + linux.sockstat → network_connections, sockets
│   ├── BashHistoryParser.h / .cpp      # linux.bash → bash_history
│   └── BootTimeParser.h / .cpp         # linux.boottime → boot_info (uptime)
└── Database/
    ├── MemoryAnalysisDatabase.h / .cpp # mirrors LinuxAnalysisDatabase
    └── Detail/                         # split implementation includes
```

### SQL schema (new headers under `src/core/DatabaseManager/SQL/`)
- `memory_analysis_sql_tables.h` — `CREATE_ALL_TABLES` constexpr string.
- `memory_analysis_sql_crud.h` — INSERT / SELECT statements.
- `memory_analysis_sql.h` — aggregator header.

### Core tables

| Table | Source plugin | Challenge coverage |
|---|---|---|
| `processes` | `linux.pslist` | process analysis |
| `network_connections` | `linux.netstat` | SSH session count (Q101) |
| `sockets` | `linux.sockstat` | network support |
| `bash_history` | `linux.bash` | dangerous deletion time (Q102), ZFS snapshot name (Q103), unlock password (Q104) |
| `boot_info` | `linux.boottime` | uptime (Q100) |
| `cmdline` | `linux.cmdline` | process arguments |
| `analysis_meta` | — | vol3 version + per-plugin run log + stderr capture |

## 6. Key technical decisions

### 6.1 Volatility3Runner (subprocess wrapper)
- **Locate venv**: prefer `python_service/.venv/bin/vol`; fall back to system `vol` on `PATH`.
- **Invocation**: `vol -r json -p <plugin> -f <mem_path>`, one call per plugin (isolates failures, enables per-plugin progress).
- **Output format**: `-r json` produces stable JSON; parse with `nlohmann::json` (already a project dependency).
- **Timeout**: per-plugin timeout (large dumps make `pslist` slow); a plugin timeout or failure must not abort the remaining plugins.
- **Error capture**: stderr stored into `analysis_meta` for diagnostics.

### 6.2 CLI / Orchestrator wiring
- `src/CommandLineParser.h`: add `bool memory_analyze = false;` (mirrors `linux_analyze` at `.h:33`).
- `src/CommandLineParser.cpp`: parse `--memory-analyze` (mirrors `--linux-analyze` at `.cpp:97-98`); add usage text near `.cpp:39`.
- **Dispatch**: the memory path must bypass TSK, so `runMemoryAnalysis` is called as an **early guard inside `AnalysisOrchestrator::runAnalysis`** — exactly how `runAnalysis` already routes the android-logical path via an early `if (args.android_source == "dir"|"zip") return runAndroidLogicalAnalysis(args);` at `AnalysisOrchestrator.cpp:46-47`. Add an analogous early guard: `if (args.memory_analyze) return runMemoryAnalysis(args);` placed near the top of `runAnalysis` (before the TSK image-open block). No new top-level branch in `main.cpp` is required.
- `src/AnalysisOrchestrator.{h,cpp}`: add `static int runMemoryAnalysis(const CommandLineArgs&);` modeled on `runAndroidLogicalAnalysis` (`AnalysisOrchestrator.cpp:231-276`) — no TSK, builds `_<baseName>_memory.db` directly. Add `#include "MemoryAnalyzer/MemoryAnalyzer.h"`.

### 6.3 HTTP routes
New `src/network/HTTPServer/routes/MemoryForensicsRoutes.{h,cpp}` mirroring `AndroidForensicsRoutes`:
- registers its own `CROW_ROUTE`s in its constructor;
- declared as a member of `ForensicsRoutes` (`ForensicsRoutes.h:79-88`) and constructed in the `ForensicsRoutes` constructor (`ForensicsRoutes.cpp:31-44`).

Endpoints:
- `GET /api/forensics/memory/summary?task_id=`
- `GET /api/forensics/memory/processes?task_id=&search=`
- `GET /api/forensics/memory/network?task_id=`
- `GET /api/forensics/memory/bash-history?task_id=&keyword=`  (highlight `rm` / `zfs`)
- `GET /api/forensics/memory/boot-info?task_id=`

### 6.4 Web page
New `web/src/pages/Memory.jsx` (mirrors `Android.jsx`):
- process list (search / sort),
- network connection table,
- bash history (keyword highlighting for `rm -rf` / `zfs snapshot` / `zfs load-key`),
- system info card (boot time, uptime, image acquisition time),
- wiring: import + route in `routes.jsx`, nav entry in `Layout.jsx:31`, append `'/memory'` to `taskContextPages` at `Layout.jsx:47`, add i18n key `nav.memory` under `web/src/locales/`.

### 6.5 Dependency install
- Append `volatility3>=2.7.0` to `python_service/httpserver/requirements.txt` (with a comment noting its purpose). `setup.sh` already runs `pip install -r requirements.txt` (lines 195-211), so no change required there.
- Add a soft check in `setup.sh`: if `.venv/bin/vol` is missing after install, emit a warning (non-fatal — must not block C++ compilation).

### 6.6 CMakeLists.txt
- Add MemoryAnalyzer subdirectories to `target_include_directories` (block at ~line 169-183).
- Add every `MemoryAnalyzer/**/*.cpp` to `LIB_SOURCES` (near line 391, where Linux sources end).
- Add `MemoryForensicsRoutes.cpp` to `LIB_SOURCES` (near line 291 where route files are listed).
- No new external C++ libraries — uses existing `nlohmann_json`, `sqlite3`, and POSIX subprocess.

## 7. Validation

End-to-end test against `mem.lime` must produce answers for:

| Q | Expected source |
|---|---|
| 100 uptime | `boot_info` (boottime vs image acquisition time) |
| 101 SSH sessions | `network_connections` filtered by `:22` |
| 102 deletion command time | `bash_history` filtered by `rm` |
| 103 ZFS snapshot name | `bash_history` filtered by `zfs snapshot` |
| 104 ZFS unlock password | `bash_history` filtered by `zfs load-key` / `zfs mount` (if captured) |

Acceptance: `_memory.db` is produced without errors, every table is populated, and the five questions above are answerable from the DB / web UI.

## 8. Risks

| Risk | Mitigation |
|---|---|
| vol3 cannot identify the Linux kernel / needs symbols | Document the symbol-path requirement; capture vol3 stderr in `analysis_meta` so failures are diagnosable. Fall back to `linux.pslist`-only if profile autototal fails. |
| Large dump (4 GB) makes some plugins slow | Per-plugin timeout; run plugins sequentially with progress logging. |
| venv not present at runtime | `Volatility3Runner` falls back to system `vol`; emits a clear error if neither is found. |
| vol3 JSON schema varies across versions | Pin `volatility3>=2.7.0,<3.0`; parsers defensive against missing keys. |

## 9. Replication checklist (files to touch)

| Layer | File(s) | Pattern source |
|---|---|---|
| CLI flag | `src/CommandLineParser.{h,cpp}` | `linux_analyze` |
| Orchestrator dispatch | `src/AnalysisOrchestrator.{h,cpp}` + `#include` (early guard inside `runAnalysis`, mirrors `runAndroidLogicalAnalysis`) | `AnalysisOrchestrator.cpp:46-47, 231-276` |
| Analyzer class | new `src/analyzers/MemoryAnalyzer/` tree | `LinuxFilesAnalyzer/` |
| DB wrapper | new `MemoryAnalyzer/Database/` | `LinuxAnalysisDatabase.{h,cpp}` + `Detail/` split |
| SQL schema | new headers in `src/core/DatabaseManager/SQL/` | `linux_analysis_sql*.h` |
| CMake | `CMakeLists.txt` | include dirs + `LIB_SOURCES` |
| HTTP routes | new `MemoryForensicsRoutes.{h,cpp}`, member of `ForensicsRoutes` | `AndroidForensicsRoutes` |
| Web page | new `web/src/pages/Memory.jsx` + `routes.jsx` + `Layout.jsx` | `Android.jsx` |
| Python dep | `python_service/httpserver/requirements.txt`, soft check in `setup.sh` | existing requirements flow |
