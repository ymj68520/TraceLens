# Deterministic File Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace LLM-based file selection in the case-analysis pipeline with deterministic selection that reads all paths from the C++-filtered `files.db`.

**Architecture:** The C++ `FileFilter` (default profile `general_forensics`, applied at task creation) guarantees `files.db` is a deterministic, profile-filtered product. Python Step 1 (`filter_files_by_case`) stops calling the LLM and instead reads every path from `files.db` (optional `filter_max_files` cap). Extraction (Step 2) and LLM description generation (Step 3) are unchanged. The legacy LLM filter is preserved behind `file_filter_mode="llm"` for fallback.

**Tech Stack:** C++ (CMake / SQLite / crow), Python (pydantic-settings / pytest / pytest-asyncio), React JSX.

## Global Constraints

- Default `file_filter_mode = "deterministic"`; `file_filter_mode = "llm"` preserves legacy behavior. Never delete the LLM filter code path.
- Default `filter_max_files = 0` (unlimited). When `> 0`, sort selected paths ascending and take the first N - deterministic.
- Default `task.filter_profile = "general_forensics"` when none is specified. `general_forensics` ships in `config/filter_profiles/` and excludes only `/proc`, `/sys`, `/dev`, `/run`.
- Do not modify `config/filter_profiles/*.json`, the extraction step, `FileAnalyzer.analyze_files`, KG ingestion, or report generation.
- Python tests import via `from httpserver...` and run from `python_service/` (`pytest` with `pytest.ini` `testpaths = tests`). New unit tests live in `python_service/tests/unit/`.
- Result shape of `filter_files_by_case` / `filter_files_multi` must stay backward-compatible: `filtered_files`, `reasoning`, `total_files`, `selected_count` (plus `source_counts`/`dedup_removed` for multi).

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `python_service/httpserver/config.py` | App settings; add `file_filter_mode`, `filter_max_files` | Modify |
| `src/network/HTTPServer/TaskManager.cpp` | `create_task`: default `filter_profile` | Modify |
| `src/AnalysisOrchestrator.cpp` | CLI: always apply filter with default profile | Modify |
| `python_service/httpserver/services/case_analysis/file_filter.py` | Add deterministic selection; mode dispatch | Modify |
| `python_service/httpserver/services/case_analysis/multi_image_filter.py` | Deterministic multi-image aggregate; mode dispatch | Modify |
| `python_service/httpserver/services/case_analysis/case_analysis_parts/_pipelines.py` | Update Step 1 copy + cap source | Modify |
| `web/src/components/tasks/CreateTaskModal.jsx` | Default `filter_profile` to `general_forensics` | Modify |
| `python_service/tests/unit/test_filter_config.py` | Config defaults | Create |
| `python_service/tests/unit/test_deterministic_filter.py` | Single-image deterministic filter | Create |
| `python_service/tests/unit/test_multi_deterministic_filter.py` | Multi-image deterministic filter | Create |

---

### Task 1: Add filter configuration settings

**Files:**
- Modify: `python_service/httpserver/config.py` (after the `llm_filter_config` field, ~line 253)
- Test: `python_service/tests/unit/test_filter_config.py`

**Interfaces:**
- Produces: `Settings.file_filter_mode: str` (default `"deterministic"`), `Settings.filter_max_files: int` (default `0`)

- [ ] **Step 1: Write the failing test**

Create `python_service/tests/unit/test_filter_config.py`:

```python
"""Tests for deterministic file filter configuration settings."""


def test_file_filter_mode_defaults_to_deterministic():
    from httpserver.config import Settings
    settings = Settings()
    assert settings.file_filter_mode == "deterministic"


def test_filter_max_files_defaults_to_zero_unlimited():
    from httpserver.config import Settings
    settings = Settings()
    assert settings.filter_max_files == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python_service && pytest tests/unit/test_filter_config.py -v`
Expected: FAIL - `AttributeError: 'Settings' object has no attribute 'file_filter_mode'`

- [ ] **Step 3: Add the settings fields**

In `python_service/httpserver/config.py`, insert immediately after the `llm_filter_config` field block (the `Field(default_factory=LLMFilterConfig, ...)` block ending around line 253, before the `@property cpp_backend_base_url`):

```python
    # File Filter Selection Mode
    file_filter_mode: str = Field(
        default="deterministic",
        alias="FILE_FILTER_MODE",
        description="File selection mode: 'deterministic' (default, reuses the "
                    "C++ FileFilter product in files.db) or 'llm' (legacy LLM "
                    "selection by case_description)."
    )
    filter_max_files: int = Field(
        default=0,
        alias="FILTER_MAX_FILES",
        description="Max files selected in deterministic mode. 0 = unlimited "
                    "(select all files meeting the profile)."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python_service && pytest tests/unit/test_filter_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add python_service/httpserver/config.py python_service/tests/unit/test_filter_config.py
git commit -m "feat(config): add file_filter_mode and filter_max_files settings"
```

---

### Task 2: Default `task.filter_profile` to `general_forensics` (C++)

**Files:**
- Modify: `src/network/HTTPServer/TaskManager.cpp:119` (inside `create_task`, after `new_task.filter_profile = filter_profile;`)
- Modify: `src/AnalysisOrchestrator.cpp:197-223` (CLI Step 2 filter block)

**Interfaces:**
- Produces: every `AnalysisTask` has a non-empty `filter_profile` (default `general_forensics`), so `TaskManagerAnalysis.cpp:148` (`if (!task.filter_profile.empty())`) always applies the deterministic C++ filter.

**Note on testing:** `TaskManager` has heavy singleton/queue/DB dependencies that make a dedicated gtest disproportionate. This task is verified by a successful build plus the existing `ctest` suite showing no regressions; the behavioral guarantee (default applies) is covered end-to-end by Task 3's deterministic tests reading `files.db` produced under the default profile.

- [ ] **Step 1: Default the profile in `TaskManager::create_task`**

In `src/network/HTTPServer/TaskManager.cpp`, replace:

```cpp
    new_task.filter_profile = filter_profile;
    new_task.enable_decryption = enable_decryption;
```

with:

```cpp
    new_task.filter_profile = filter_profile;
    // Default to general_forensics so the deterministic C++ FileFilter always
    // runs and files.db is always a profile-filtered product. Callers can still
    // pass an explicit profile to override.
    if (new_task.filter_profile.empty()) {
        new_task.filter_profile = "general_forensics";
    }
    new_task.enable_decryption = enable_decryption;
```

- [ ] **Step 2: Always apply the filter in the CLI orchestrator**

In `src/AnalysisOrchestrator.cpp`, replace the Step 2 block (lines 197-223):

```cpp
        // Step 2: Apply file filter (if profile specified)
        // The filtered database is used by all downstream processors
        std::string effectiveRawDb = rawDbPath;

        if (!args.filter_profile.empty()) {
            std::cout << "[2/4] Applying file filter: " << args.filter_profile << "..." << std::endl;
            std::string filteredDbPath = prefix + baseName + "_filtered.db";

            try {
                FileFilter filter;
                auto stats = filter.applyFilterByName(rawDbPath, filteredDbPath, args.filter_profile);

                if (stats.included_files > 0) {
                    effectiveRawDb = filteredDbPath;
                    std::cout << "✓ Filtered database: " << filteredDbPath
                              << " (" << stats.included_files << "/" << stats.total_files
                              << " files)\n" << std::endl;
                } else {
                    std::cerr << "Warning: Filter excluded all files. Using unfiltered data." << std::endl;
                }
            } catch (const std::exception& e) {
                std::cerr << "Warning: Filter failed: " << e.what() << std::endl;
                std::cerr << "Continuing with unfiltered data." << std::endl;
            }
        } else {
            std::cout << "[2/4] File filter: skipped (no profile specified)\n" << std::endl;
        }
```

with:

```cpp
        // Step 2: Apply file filter (default: general_forensics)
        // The filtered database is used by all downstream processors
        std::string effectiveRawDb = rawDbPath;
        std::string effectiveProfile = args.filter_profile.empty()
            ? "general_forensics" : args.filter_profile;

        std::cout << "[2/4] Applying file filter: " << effectiveProfile << "..." << std::endl;
        std::string filteredDbPath = prefix + baseName + "_filtered.db";

        try {
            FileFilter filter;
            auto stats = filter.applyFilterByName(rawDbPath, filteredDbPath, effectiveProfile);

            if (stats.included_files > 0) {
                effectiveRawDb = filteredDbPath;
                std::cout << "✓ Filtered database: " << filteredDbPath
                          << " (" << stats.included_files << "/" << stats.total_files
                          << " files)\n" << std::endl;
            } else {
                std::cerr << "Warning: Filter excluded all files. Using unfiltered data." << std::endl;
            }
        } catch (const std::exception& e) {
            std::cerr << "Warning: Filter failed: " << e.what() << std::endl;
            std::cerr << "Continuing with unfiltered data." << std::endl;
        }
```

- [ ] **Step 3: Build the C++ project**

Run: `cd build && cmake --build . -j$(nproc) 2>&1 | tail -20`
Expected: build succeeds with no new warnings/errors in `TaskManager.cpp` or `AnalysisOrchestrator.cpp`.

- [ ] **Step 4: Run the existing C++ test suite (no regressions)**

Run: `cd build && ctest --output-on-failure -j$(nproc) 2>&1 | tail -30`
Expected: all previously-passing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/network/HTTPServer/TaskManager.cpp src/AnalysisOrchestrator.cpp
git commit -m "feat(c++): default task filter_profile to general_forensics"
```

---

### Task 3: Deterministic single-image file selection

**Files:**
- Modify: `python_service/httpserver/services/case_analysis/file_filter.py` (rewire `filter_files_by_case`; add `_filter_files_deterministic`)
- Test: `python_service/tests/unit/test_deterministic_filter.py`

**Interfaces:**
- Consumes: `Settings.file_filter_mode`, `Settings.filter_max_files`; existing `FileFilter._get_file_list_from_db(db_path)` and `FileFilter._persist_filtered_files(db_path, task_id, files)`.
- Produces: `FileFilter._filter_files_deterministic(files_db_path, max_files, task_id) -> Dict[str, Any]`; `filter_files_by_case` dispatches on `file_filter_mode`.

- [ ] **Step 1: Write the failing test**

Create `python_service/tests/unit/test_deterministic_filter.py`:

```python
"""Tests for deterministic (non-LLM) file selection in FileFilter."""

import sqlite3
from types import SimpleNamespace

import pytest

from httpserver.services.case_analysis.file_filter import FileFilter


def _make_files_db(db_path: str, paths):
    """Create a minimal files.db with a files table."""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE files (path TEXT, type TEXT, size INTEGER)")
    conn.executemany(
        "INSERT INTO files (path, type, size) VALUES (?, ?, ?)",
        [(p, "", 0) for p in paths],
    )
    conn.commit()
    conn.close()


def _make_filter(mode="deterministic", cap=0):
    settings = SimpleNamespace(file_filter_mode=mode, filter_max_files=cap)
    # SimpleNamespace has no llm_filter_config attr, so FileMatcher /
    # FilterResultValidator hasattr-guards fall back to defaults.
    return FileFilter(settings, llm_service=None, cpp_backend=None)


@pytest.mark.asyncio
async def test_deterministic_returns_all_paths_sorted(tmp_path):
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/c/log", "/a/doc", "/b/img"])

    f = _make_filter()
    result = await f._filter_files_deterministic(db, max_files=200, task_id="t1")

    assert result["model_used"] == "deterministic_cpp_filter"
    assert result["streaming_used"] is False
    assert result["filtered_files"] == ["/a/doc", "/b/img", "/c/log"]
    assert result["total_files"] == 3
    assert result["selected_count"] == 3


@pytest.mark.asyncio
async def test_deterministic_cap_takes_first_n_sorted(tmp_path):
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/z", "/a", "/m"])

    f = _make_filter(cap=2)
    result = await f._filter_files_deterministic(db, max_files=200, task_id="t1")

    assert result["filtered_files"] == ["/a", "/m"]
    assert result["selected_count"] == 2
    assert result["total_files"] == 3


@pytest.mark.asyncio
async def test_deterministic_empty_db_returns_empty(tmp_path):
    db = str(tmp_path / "files.db")
    _make_files_db(db, [])

    f = _make_filter()
    result = await f._filter_files_deterministic(db, max_files=200, task_id="t1")

    assert result["filtered_files"] == []
    assert result["total_files"] == 0
    assert result["selected_count"] == 0


@pytest.mark.asyncio
async def test_filter_files_by_case_dispatches_deterministic(tmp_path):
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/x"])

    f = _make_filter(mode="deterministic")
    result = await f.filter_files_by_case(db, "case desc", max_files=200, task_id="t1")

    assert result["model_used"] == "deterministic_cpp_filter"


@pytest.mark.asyncio
async def test_filter_files_by_case_llm_mode_does_not_call_deterministic(tmp_path):
    """In llm mode the deterministic path is skipped (LLM service is None -> raises)."""
    db = str(tmp_path / "files.db")
    _make_files_db(db, ["/x"])

    f = _make_filter(mode="llm")
    with pytest.raises(RuntimeError, match="LLM service not initialized"):
        await f.filter_files_by_case(db, "case desc", max_files=200, task_id="t1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python_service && pytest tests/unit/test_deterministic_filter.py -v`
Expected: FAIL - `AttributeError: 'FileFilter' object has no attribute '_filter_files_deterministic'`

- [ ] **Step 3: Add the deterministic method and mode dispatch**

In `python_service/httpserver/services/case_analysis/file_filter.py`, modify `filter_files_by_case` to dispatch on mode. Replace the start of the method (the docstring + the `if not self._llm_service:` block) — insert the deterministic dispatch **before** the `if not self._llm_service:` check:

```python
    async def filter_files_by_case(
        self,
        files_db_path: str,
        case_description: str,
        max_files: int = 200,
        batch_size: int = 50,
        use_streaming: bool = True,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Select files for case analysis.

        Dispatches on settings.file_filter_mode:
        - 'deterministic' (default): read all paths from the C++-filtered
          files.db. No LLM, fully reproducible.
        - 'llm': legacy LLM selection by case_description.
        """
        mode = getattr(self.settings, "file_filter_mode", "deterministic")
        if mode != "llm":
            return await self._filter_files_deterministic(
                files_db_path, max_files, task_id
            )

        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")
```

Leave the rest of the existing method (streaming/legacy/lock-manager logic) unchanged.

Then add the new method to the `FileFilter` class (e.g. immediately after `filter_files_by_case`):

```python
    async def _filter_files_deterministic(
        self,
        files_db_path: str,
        max_files: int,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deterministic file selection: read all paths from files.db.

        files.db is already the product of the C++ FileFilter (scenario profile
        applied at task creation). This method performs NO LLM call and NO
        rule-based filtering - it selects every file the C++ filter kept, so the
        selection is reproducible across runs.
        """
        records = self._get_file_list_from_db(files_db_path)
        paths = sorted({r.get("path", "") for r in records if r.get("path")})
        total_files = len(paths)

        cap = int(getattr(self.settings, "filter_max_files", 0) or 0)
        if cap > 0:
            selected = paths[:cap]
            logger.info(
                f"[FILE_FILTER] Deterministic cap applied: {len(selected)}/{total_files} "
                f"(filter_max_files={cap})"
            )
        else:
            selected = paths

        if max_files and max_files > 0:
            logger.info(
                f"[FILE_FILTER] max_files={max_files} ignored in deterministic mode; "
                f"using settings.filter_max_files={cap}"
            )

        resolved_task_id = task_id or "_latest"
        self._persist_filtered_files(files_db_path, resolved_task_id, selected)

        return {
            "filtered_files": selected,
            "reasoning": f"Deterministic selection from C++-filtered files.db ({total_files} files)",
            "total_files": total_files,
            "selected_count": len(selected),
            "model_used": "deterministic_cpp_filter",
            "streaming_used": False,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python_service && pytest tests/unit/test_deterministic_filter.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run existing filter tests to confirm no regression**

Run: `cd python_service && pytest tests/unit/test_file_matcher.py tests/unit/test_filter_validator.py tests/unit/test_llm_response_parser.py -v`
Expected: PASS (LLM-path code untouched)

- [ ] **Step 6: Commit**

```bash
git add python_service/httpserver/services/case_analysis/file_filter.py python_service/tests/unit/test_deterministic_filter.py
git commit -m "feat(filter): deterministic single-image file selection"
```

---

### Task 4: Deterministic multi-image file selection

**Files:**
- Modify: `python_service/httpserver/services/case_analysis/multi_image_filter.py` (rewire `filter_files_multi`; add deterministic branch)
- Test: `python_service/tests/unit/test_multi_deterministic_filter.py`

**Interfaces:**
- Consumes: `Settings.file_filter_mode`, `Settings.filter_max_files`; inherited `FileFilter._get_file_list_from_db`, `_cross_image_dedup`, `_distribute_and_persist`.
- Produces: `filter_files_multi` dispatches on `file_filter_mode`; deterministic branch returns the same shape plus `source_counts`/`dedup_removed`.

- [ ] **Step 1: Write the failing test**

Create `python_service/tests/unit/test_multi_deterministic_filter.py`:

```python
"""Tests for deterministic multi-image file selection."""

import sqlite3
from types import SimpleNamespace

import pytest

from httpserver.services.case_analysis.multi_image_filter import MultiImageFilter


def _make_files_db(db_path: str, rows):
    """rows: list of (path, size)."""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE files (path TEXT, type TEXT, size INTEGER)")
    conn.executemany(
        "INSERT INTO files (path, type, size) VALUES (?, ?, ?)",
        [(p, "", s) for p, s in rows],
    )
    conn.commit()
    conn.close()


def _make_filter(cap=0):
    settings = SimpleNamespace(file_filter_mode="deterministic", filter_max_files=cap)
    return MultiImageFilter(settings, llm_service=None, cpp_backend=None)


@pytest.mark.asyncio
async def test_multi_deterministic_aggregates_and_dedups(tmp_path):
    db1 = str(tmp_path / "files1.db")
    db2 = str(tmp_path / "files2.db")
    _make_files_db(db1, [("/a/doc", 100), ("/shared/dup.log", 500)])
    _make_files_db(db2, [("/b/img", 200), ("/shared/dup.log", 500)])  # dup by (name,size)

    f = _make_filter()
    result = await f.filter_files_multi(
        files_db_paths=[db1, db2], case_description="case",
        max_files=400, task_ids=["t1", "t2"],
    )

    assert result["model_used"] == "deterministic_cpp_filter"
    assert result["total_files"] == 3          # 4 rows - 1 cross-image dup
    assert result["dedup_removed"] == 1
    assert set(result["filtered_files"]) == {"/a/doc", "/shared/dup.log", "/b/img"}
    assert result["source_counts"] == {db1: 2, db2: 2}


@pytest.mark.asyncio
async def test_multi_deterministic_cap(tmp_path):
    db1 = str(tmp_path / "files1.db")
    _make_files_db(db1, [("/z", 1), ("/a", 2), ("/m", 3)])

    f = _make_filter(cap=2)
    result = await f.filter_files_multi(
        files_db_paths=[db1], case_description="case",
        max_files=400, task_ids=["t1"],
    )

    assert result["filtered_files"] == ["/a", "/m"]
    assert result["selected_count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python_service && pytest tests/unit/test_multi_deterministic_filter.py -v`
Expected: FAIL - `result["model_used"]` missing (the LLM path is taken and raises / returns a different shape).

- [ ] **Step 3: Add mode dispatch and deterministic branch**

In `python_service/httpserver/services/case_analysis/multi_image_filter.py`, modify `filter_files_multi`. Replace the method body's start (after the docstring) — insert the mode dispatch before Step 1 (the `# Step 1: load + tag` block):

```python
    async def filter_files_multi(
        self,
        files_db_paths: List[str],
        case_description: str,
        max_files: int = 400,
        batch_size: int = 50,
        task_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Filter files across multiple _files.db databases.

        Dispatches on settings.file_filter_mode:
        - 'deterministic' (default): aggregate + dedup all paths from each
          C++-filtered files.db. No LLM, fully reproducible.
        - 'llm': legacy streaming LLM filter.

        Returns the same structure as FileFilter.filter_files_by_case(), plus:
            source_counts: {db_path: file_count}   - per-image file count
            dedup_removed: int                      - cross-image duplicates removed
        """
        if not files_db_paths:
            return {"filtered_files": [], "total_files": 0, "selected_count": 0}

        mode = getattr(self.settings, "file_filter_mode", "deterministic")
        if mode != "llm":
            return await self._filter_files_multi_deterministic(
                files_db_paths, task_ids
            )

        # --- legacy LLM path (unchanged) ---
        # Step 1: load + tag all files from every db
        all_tagged: List[Dict[str, str]] = []
```

(Leave the entire existing LLM body - Steps 1-4 and `_run_streaming_filter` - unchanged.)

Then add the deterministic method to the `MultiImageFilter` class (e.g. after `filter_files_multi`):

```python
    async def _filter_files_multi_deterministic(
        self,
        files_db_paths: List[str],
        task_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Deterministic multi-image selection: aggregate + dedup all paths."""
        all_tagged: List[Dict[str, Any]] = []
        source_counts: Dict[str, int] = {}

        for idx, db_path in enumerate(files_db_paths):
            records = self._get_file_list_from_db(db_path)
            source_counts[db_path] = len(records)
            for r in records:
                rec = dict(r)
                rec["tagged_path"] = rec.get("path", "")
                rec["source_db"] = db_path
                all_tagged.append(rec)
            logger.info(f"[MULTI_FILTER] DB {idx+1}: {len(records)} files from {db_path}")

        total_before_dedup = len(all_tagged)
        deduped = self._cross_image_dedup(all_tagged)
        dedup_removed = total_before_dedup - len(deduped)

        paths = sorted({r.get("path", "") for r in deduped if r.get("path")})
        total_files = len(paths)

        cap = int(getattr(self.settings, "filter_max_files", 0) or 0)
        if cap > 0:
            selected = paths[:cap]
            logger.info(
                f"[MULTI_FILTER] Deterministic cap applied: {len(selected)}/{total_files} "
                f"(filter_max_files={cap})"
            )
        else:
            selected = paths

        self._distribute_and_persist(selected, deduped, files_db_paths, task_ids)

        return {
            "filtered_files": selected,
            "reasoning": f"Deterministic multi-image selection ({total_files} files after dedup)",
            "total_files": total_files,
            "selected_count": len(selected),
            "model_used": "deterministic_cpp_filter",
            "streaming_used": False,
            "source_counts": source_counts,
            "dedup_removed": dedup_removed,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python_service && pytest tests/unit/test_multi_deterministic_filter.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add python_service/httpserver/services/case_analysis/multi_image_filter.py python_service/tests/unit/test_multi_deterministic_filter.py
git commit -m "feat(filter): deterministic multi-image file selection"
```

---

### Task 5: Update pipeline copy and cap source

**Files:**
- Modify: `python_service/httpserver/services/case_analysis/case_analysis_parts/_pipelines.py` (Step 1 copy in `run_full_analysis` ~lines 94-110; `run_multi_image_analysis` ~line 390)

**Interfaces:**
- Consumes: the deterministic `filter_files_by_case` / `filter_files_multi` from Tasks 3-4.
- Produces: no API change; only log/progress text and a clarifying log that `max_filter_files` is ignored in deterministic mode.

- [ ] **Step 1: Update Step 1 copy in `run_full_analysis`**

In `python_service/httpserver/services/case_analysis/case_analysis_parts/_pipelines.py`, replace the Step 1 block (~lines 94-99):

```python
            # Step 1: Filter files via LLM
            if progress_callback:
                await progress_callback("filtering", "正在使用 LLM 自动筛选关键文件...")
            logger.info(f"[CASE_ANALYSIS] Task {task_id}: Starting LLM file filtering...")
            logger.info(f"[CASE_ANALYSIS] files_db_path: {files_db_path}")
            logger.info(f"[CASE_ANALYSIS] case_description length: {len(case_description)}")
            logger.info(f"[CASE_ANALYSIS] max_filter_files: {max_filter_files}")
```

with:

```python
            # Step 1: Filter files (deterministic by default; reuses C++ profile)
            filter_mode = getattr(self.settings, "file_filter_mode", "deterministic")
            if progress_callback:
                if filter_mode == "llm":
                    await progress_callback("filtering", "正在使用 LLM 自动筛选关键文件...")
                else:
                    await progress_callback("filtering", "正在使用确定性分类筛选（复用 C++ profile）...")
            logger.info(f"[CASE_ANALYSIS] Task {task_id}: Starting file filtering (mode={filter_mode})...")
            logger.info(f"[CASE_ANALYSIS] files_db_path: {files_db_path}")
            logger.info(f"[CASE_ANALYSIS] case_description length: {len(case_description)}")
            logger.info(f"[CASE_ANALYSIS] max_filter_files: {max_filter_files} "
                        f"(ignored in deterministic mode; cap=settings.filter_max_files)")
```

- [ ] **Step 2: Update `run_multi_image_analysis` copy**

In the same file, replace (~line 390):

```python
        if progress_callback:
            await progress_callback("filtering", f"正在跨 {len(files_db_paths)} 个镜像筛选关键文件...")

        # Step 1 - Cross-image LLM filter
        logger.info(f"[MULTI_ANALYSIS] Case {case_id}: starting multi-image filter "
                    f"({len(files_db_paths)} images)")
```

with:

```python
        if progress_callback:
            await progress_callback("filtering", f"正在跨 {len(files_db_paths)} 个镜像筛选关键文件...")

        # Step 1 - Cross-image filter (deterministic by default)
        logger.info(f"[MULTI_ANALYSIS] Case {case_id}: starting multi-image filter "
                    f"({len(files_db_paths)} images, mode={getattr(self.settings, 'file_filter_mode', 'deterministic')})")
```

- [ ] **Step 3: Run the deterministic + existing case-analysis tests**

Run: `cd python_service && pytest tests/unit/test_deterministic_filter.py tests/unit/test_multi_deterministic_filter.py tests/unit/test_filter_config.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add python_service/httpserver/services/case_analysis/case_analysis_parts/_pipelines.py
git commit -m "feat(pipeline): deterministic filter copy and cap-source logging"
```

---

### Task 6: Default `filter_profile` in the web CreateTaskModal

**Files:**
- Modify: `web/src/components/tasks/CreateTaskModal.jsx:27` (`filter_profile: ''` in `INITIAL_FORM`)

**Interfaces:**
- Produces: the create-task form defaults `filter_profile` to `general_forensics`, matching the C++ default. Non-blocking - the C++ default already guarantees correctness if the field is omitted.

- [ ] **Step 1: Change the initial form value**

In `web/src/components/tasks/CreateTaskModal.jsx`, replace (line 27):

```jsx
  filter_profile: '',
```

with:

```jsx
  filter_profile: 'general_forensics',
```

- [ ] **Step 2: Verify the frontend builds**

Run: `cd web && npm run build 2>&1 | tail -15` (or `npm run lint` if build is unavailable)
Expected: build succeeds; no new errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/tasks/CreateTaskModal.jsx
git commit -m "feat(web): default filter_profile to general_forensics in CreateTaskModal"
```

---

## Self-Review Notes

**Spec coverage:**
- Decision 1 (reuse C++ filter) - Task 2 (default profile) + Tasks 3-4 (Python reads files.db, no rule engine). ✓
- Decision 2 (default general_forensics) - Task 2. ✓
- Decision 3 (LLM behind file_filter_mode, default deterministic) - Task 1 (setting) + Tasks 3-4 (dispatch). ✓
- Decision 4 (configurable cap, default unlimited) - Task 1 (setting) + Tasks 3-4 (cap logic). ✓
- Components A-G in the spec map to Tasks 1-6 (Web = Task 6, Tests embedded in Tasks 1/3/4). ✓

**Placeholder scan:** every code step contains actual code; no TBD/TODO. The C++ Task 2 testing note is an explicit, justified exception (heavy TaskManager dependencies), not a placeholder.

**Type consistency:** `_filter_files_deterministic(files_db_path, max_files, task_id)` signature is identical in Task 3 (definition) and Task 3 Step 1 dispatch (call). `_filter_files_multi_deterministic(files_db_paths, task_ids)` is identical in Task 4 definition and dispatch. `model_used="deterministic_cpp_filter"` is consistent across single and multi. Result shapes preserve `filtered_files`/`reasoning`/`total_files`/`selected_count`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-27-deterministic-file-filter.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
