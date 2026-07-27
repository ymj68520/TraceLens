# Deterministic File Filter Design

**Date:** 2026-07-27
**Status:** Approved
**Scope:** Replace LLM-based file selection in the case-analysis pipeline with a deterministic classification filter

## Problem Statement

The case-analysis pipeline (`CaseAnalysisService.run_full_analysis`) selects which files to analyze in **Step 1** by asking an LLM to pick "important" files based on a free-text `case_description` (`python_service/httpserver/services/case_analysis/file_filter.py`, `filter_files_by_case`). The LLM streams the file list in TOON batches, judges each batch against the case description, and returns a subjective subset.

This is non-deterministic: the same disk image and the same case description produce a different selected-file set on every run. For project acceptance (验收) this is unacceptable — there is no reproducible, auditable criterion for *why* a file was or was not selected, and the analyzed evidence set varies between runs.

The project already contains a **deterministic** classification filter that is not wired into this step: the C++ `forensics::FileFilter` (`src/core/FileFilter/FileFilter.h`), driven by JSON profiles in `config/filter_profiles/*.json`. It applies include/exclude rules (extensions, path globs, filename globs, min/max size, deleted/allocated, combine mode) to produce a filtered database. It runs at task-creation time when `task.filter_profile` is set (`src/network/HTTPServer/TaskManagerAnalysis.cpp:148-175`), producing `filtered.db` from `raw.db`; the downstream `FileClassifier` then builds `files.db` from the filtered database. But `task.filter_profile` is optional and defaults to empty (no filtering), so the deterministic filter is not guaranteed to run.

## Goals

1. The set of files selected for analysis is **deterministic and reproducible**: same image + same profile ⇒ same file set, every run.
2. File **selection** no longer depends on an LLM. The LLM is still used to **describe** selected files (Step 3, unchanged).
3. Reuse the existing C++ `FileFilter` + `config/filter_profiles/*.json` as the classification filter — do not reimplement filtering rules in Python.
4. A filter profile is always in effect, defaulting to `general_forensics` when none is specified.
5. The number of selected files is configurable with a default of *unlimited* ("select all files meeting the requirements").
6. Single-image and multi-image analysis paths both become deterministic.
7. Existing LLM-filter code and its tests are preserved behind a configuration flag for fallback/comparison, not deleted.

## Non-Goals

- Modifying the contents of `config/filter_profiles/*.json` or adding new profiles.
- Auto-mapping case type → profile (case-level profile selection is manual; default `general_forensics`).
- Re-filtering already-analyzed tasks at case-analysis time (the profile is a task-creation-time setting; re-running the C++ pipeline is out of scope).
- Removing the LLM-filter code path.
- Changing the extraction step (`extract_filtered_files`), the LLM description step (`FileAnalyzer.analyze_files`), knowledge-graph ingestion, or report generation.
- Threading a `filter_profile` parameter through the case-analysis HTTP routes (profile selection happens at task creation).

## Design Decisions

### Decision 1: Reuse the C++ FileFilter; Python consumes the already-filtered `files.db`

**Chosen over:**
- *Port the profile rules to Python* — duplicates simple-but-existing logic; the C++ filter already runs upstream and already produces `files.db`.
- *Hybrid C++ coarse + Python fine filter* — most flexible but most complex; two rule sets to coordinate.

The C++ `FileFilter` is the classification filter. By guaranteeing `task.filter_profile` is always set (Decision 2), `files.db` is always a deterministic, profile-filtered product. Python Step 1 then simply reads **all** file paths from `files.db` — no rule engine, no LLM. This is the smallest change that delivers determinism at the exact point the problem occurs.

### Decision 2: Default `task.filter_profile` to `general_forensics`

When a task is created without an explicit `filter_profile`, default to `general_forensics`. That profile excludes only `/proc`, `/sys`, `/dev`, `/run` noise and includes everything else — a safe, near-complete default that guarantees the C++ filter always runs without aggressively excluding evidence. The default is applied at the single source of truth, `TaskManager::create_task`, so all entry points (single-task route, batch route, and the CLI `AnalysisOrchestrator`) inherit it.

### Decision 3: Keep the LLM filter behind a `file_filter_mode` flag (default `deterministic`)

A new `file_filter_mode` setting (`deterministic` | `llm`, default `deterministic`) dispatches Step 1. The default gives the determinism required for acceptance; `llm` preserves the prior behavior for A/B comparison and fallback. All existing LLM-filter code (`file_filter.py` streaming/legacy paths, `multi_image_filter.py` LLM branch, `llm_response_parser.py`, `file_matcher.py`, `filter_validator.py`, `concurrent_filter.py`) and its tests stay intact and are only reached when the mode is `llm`.

### Decision 4: Configurable cap, default unlimited

A new `filter_max_files` setting (default `0` = unlimited) bounds the selected set in deterministic mode. When `> 0`, files are sorted by path (deterministic ordering) and the first N are taken. The request-level `max_filter_files` parameter from the HTTP routes was an LLM-era cap and is ignored in deterministic mode (logged once), so the default behavior is genuinely "select all."

---

## Architecture

### Current (LLM selection)

```
run_full_analysis:
  Step1  filter_files_by_case()  ->  LLM picks subset by case_description  ->  filtered_files
  Step2  extract_filtered_files()
  Step3  FileAnalyzer.analyze_files()  ->  LLM generates description per file
  Step4  KG ingest
  Step5  report
```

### Proposed (deterministic selection)

```
Task creation:
  ImageAnalyzer -> raw.db
  FileFilter(profile = task.filter_profile ?? general_forensics) -> filtered.db   [deterministic]
  FileClassifier(filtered.db) -> files.db                                         [deterministic product]

run_full_analysis:
  Step1  [CHANGED] read ALL paths from files.db -> optional filter_max_files cap -> filtered_files
  Step2  [unchanged] extract_filtered_files()
  Step3  [unchanged] FileAnalyzer.analyze_files()  ->  LLM generates description per file
  Step4  [unchanged] KG ingest
  Step5  [unchanged] report
```

The LLM's role moves from *selecting* files to *describing* them. Selection becomes a deterministic function of (image, profile).

## Components

### A. C++ — default `filter_profile`

- **`src/network/HTTPServer/TaskManager.cpp`** (`create_task`): after `new_task.filter_profile = filter_profile;`, add `if (new_task.filter_profile.empty()) new_task.filter_profile = "general_forensics";`. This covers the single-task route, the batch route, and any other caller of `create_task`.
- **`src/AnalysisOrchestrator.cpp`** (CLI, ~line 201): when `args.filter_profile` is empty, use `general_forensics` so the CLI always applies the deterministic filter, matching the server.
- Effect: `TaskManagerAnalysis.cpp:148` (`if (!task.filter_profile.empty())`) always enters the filter branch, so `files.db` is always the deterministic, profile-filtered product.

### B. Python — configuration

- **`python_service/httpserver/config.py`** (`Settings`):
  - `file_filter_mode: str = Field(default="deterministic", alias="FILE_FILTER_MODE")` — `"deterministic"` (default) | `"llm"`.
  - `filter_max_files: int = Field(default=0, alias="FILTER_MAX_FILES")` — `0` = unlimited; `>0` = deterministic cap.

### C. Python — single-image deterministic filter

- **`python_service/httpserver/services/case_analysis/file_filter.py`** (`FileFilter`):
  - Add `async def _filter_files_deterministic(self, files_db_path, max_files, task_id) -> Dict[str, Any]`. Reuses the existing `_get_file_list_from_db(db_path)` to read every row of the `files` table, extracts the `path` list, sorts ascending by path (deterministic), applies `cap = self.settings.filter_max_files` (cap > 0 ⇒ first N; the `max_files` argument is ignored and logged once), persists via the existing `_persist_filtered_files`, and returns the **same result shape** as the LLM path: `{filtered_files, reasoning, total_files, selected_count, model_used: "deterministic_cpp_filter", streaming_used: False}`.
  - Rewire `filter_files_by_case(...)`: dispatch on `self.settings.file_filter_mode` — `"deterministic"` ⇒ call the new method and return; otherwise the existing LLM streaming/legacy path (unchanged).
  - `llm_service` / `cpp_backend` injection unchanged (the LLM path still needs them; the deterministic path needs only `settings`).

### D. Python — multi-image deterministic filter

- **`python_service/httpserver/services/case_analysis/multi_image_filter.py`** (`MultiImageFilter`):
  - Rewire `filter_files_multi(...)`: dispatch on `self.settings.file_filter_mode`.
  - Deterministic branch: reuse `_get_file_list_from_db` per database, reuse the existing `_cross_image_dedup` (key = filename, size), sort by path, apply `filter_max_files`, reuse `_distribute_and_persist` to persist per-database lists. Return shape unchanged (`filtered_files`, `reasoning`, `selected_count`, `source_counts`, `dedup_removed`, `total_files`); `reasoning` notes determinism.
  - LLM branch (`_run_streaming_filter`, etc.) unchanged.

### E. Python — pipeline wiring and copy

- **`python_service/httpserver/services/case_analysis/case_analysis_parts/_pipelines.py`**:
  - `run_full_analysis`: Step 1 progress text and log lines change from "使用 LLM 自动筛选" to "使用确定性分类筛选（复用 C++ profile）". The `max_filter_files` parameter is kept for API compatibility but is no longer the cap source in deterministic mode (logged). Pipeline structure and the `FileAnalyzer.analyze_files` call are unchanged.
  - `run_multi_image_analysis`: matching copy changes.

### F. Web — default profile (optional, non-blocking)

- **`web/src/components/tasks/CreateTaskModal.jsx`**: `filter_profile` initial value `''` → `'general_forensics'`, dropdown defaults to it. The C++ default already guarantees correctness if the frontend omits the field, so this is purely UX consistency.

### G. Tests

- New `python_service/httpserver/tests/unit/test_deterministic_filter.py`: in-memory `files.db` with `files` rows ⇒ assert all paths returned, correct shape, `model_used="deterministic_cpp_filter"`; `filter_max_files=2` ⇒ first 2 by path order; `file_filter_mode="llm"` ⇒ dispatch to LLM path (mocked).
- New `python_service/httpserver/tests/unit/test_multi_deterministic_filter.py`: multi-database aggregate + cross-image dedup + cap.
- C++: assert `filter_profile` defaults to `general_forensics` on task creation (extend an existing task-creation test or add a minimal one).
- Existing LLM-filter tests (`test_file_filter_integration.py`, `test_concurrent_filter.py`, `test_filter_validator.py`, `test_file_matcher.py`, `test_llm_response_parser.py`) remain green — the LLM path is preserved and the default mode does not perturb their direct calls.

## Data Flow

```
Task create  ──►  ImageAnalyzer ──► raw.db
                 FileFilter(profile = filter_profile ?? "general_forensics") ──► filtered.db   [deterministic]
                 FileClassifier(filtered.db) ──► files.db                                    [deterministic product]

Case analysis (run_full_analysis):
  Step1 [CHANGED]  DeterministicFileFilter: read all paths in files.db
                   → sort by path → cap via settings.filter_max_files (0 = no cap)
                   → filtered_files (persisted to case_analysis.filtered_files)
  Step2 [unchanged] extract_filtered_files(task_id, filtered_files) → extraction_dir
  Step3 [unchanged] FileAnalyzer.analyze_files(files_db_path, filtered_files, …)
                   → per-file LLM description → file_descriptions table
  Step4 [unchanged] KG ingest
  Step5 [unchanged] report
```

## Error Handling and Edge Cases

- **`files.db` missing or empty**: `_filter_files_deterministic` returns `{filtered_files: [], total_files: 0, selected_count: 0, …}`. The pipeline already skips extraction/description when `filtered_files` is empty — behavior unchanged.
- **`filter_max_files = 0`** (default): no cap; all `files.db` paths selected. **`> 0`**: sort by path ascending, take first N — deterministic and order-stable.
- **`file_filter_mode = "llm"`**: falls back to the original LLM streaming/legacy path with its own `max_files` semantics. Used for comparison/fallback only; not the default.
- **Pre-existing tasks** (created before this change, with empty `filter_profile`): their `files.db` was not C++-profile-filtered. The deterministic Step 1 still reads all their paths (reproducible, but not profile-filtered). To apply a profile to such a task, re-analyze it with an explicit profile.
- **Profile not found**: existing C++ `applyFilterByName` behavior — it throws and `TaskManagerAnalysis.cpp` catches, falling back to unfiltered. The default `general_forensics` ships in-repo, so this is a misconfiguration guard, not a normal path.

## Testing Strategy

- **Unit (Python)**: deterministic single-image filter — full selection, shape, `model_used`, cap ordering, mode dispatch. Multi-image — aggregate, dedup, cap.
- **Unit (C++)**: task creation defaults `filter_profile` to `general_forensics`.
- **Regression**: existing LLM-filter tests stay green (path preserved; default mode does not invoke them).
- **Acceptance criterion**: with `file_filter_mode="deterministic"` (default) and a fixed profile, re-running case analysis on the same image yields the identical `filtered_files` set.

## Migration Notes

- No schema migration. New settings have safe defaults (`deterministic`, `0`).
- Old tasks are not automatically re-filtered; re-analyze to apply the default profile.
- The change is backward-compatible at the API level: no route signatures change, the `max_filter_files` request parameter is accepted but becomes a no-op in deterministic mode.
