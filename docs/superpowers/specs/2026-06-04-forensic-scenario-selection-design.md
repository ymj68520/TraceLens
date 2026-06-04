# Forensic Scenario Selection Design

**Date:** 2026-06-04
**Status:** Approved
**Scope:** Unified forensic scenario selection system for multi-platform analysis

## Problem Statement

The current system only supports Android deep analysis via a single `bool android_analyze` flag. The `WindowsFilesAnalyzer` and `LinuxFilesAnalyzer` classes are fully implemented but never called from the HTTP server pipeline. There is no way for users to select Windows or Linux analysis scenarios, and no support for multi-scenario tasks.

## Goals

1. Support four forensic scenarios: Android, Windows, Linux, Server/Cloud
2. Users select one or more scenarios via frontend checkboxes when creating tasks
3. Backend automatically runs the corresponding analyzers for selected scenarios
4. Each scenario produces an independent database file
5. Backward compatibility with existing `android_analyze` field

## Non-Goals

- Auto-detection of image type (manual selection only)
- macOS forensics (not requested)
- Runtime plugin system for scenarios

## Design Decisions

### Approach: ForensicScenario Enum + Scenario Vector

**Chosen over:**
- Multiple boolean flags (doesn't scale)
- Strategy pattern with interface (over-engineering for 4 scenarios)

### Execution Model: Serial

Scenario analyzers run sequentially after the core pipeline completes. This avoids resource contention and simplifies error handling.

### Database Model: Per-Scenario Independent Databases

Each scenario generates its own database file (`_android.db`, `_windows.db`, `_linux.db`, `_server.db`), consistent with the existing pattern.

---

## Data Model

### ForensicScenario Enum

```cpp
// HTTPServerDataTypes.h
enum class ForensicScenario {
    ANDROID,        // Android device forensics
    WINDOWS,        // Windows system forensics
    LINUX,          // Linux system forensics
    SERVER_CLOUD    // Server/Cloud environment forensics (extends Linux analyzer)
};
```

### AnalysisTask Changes

```cpp
struct AnalysisTask {
    // ... existing fields ...

    // NEW: Replaces bool android_analyze
    std::vector<ForensicScenario> scenarios;

    // Backward compatibility: computed property
    bool get_android_analyze() const {
        return std::find(scenarios.begin(), scenarios.end(),
                         ForensicScenario::ANDROID) != scenarios.end();
    }
};
```

### TaskPhase Changes

```cpp
enum class TaskPhase {
    INITIALIZING,
    IMAGE_ANALYSIS,
    EVENT_EXTRACTION,
    FILE_CLASSIFICATION,
    LLM_ANALYSIS,
    PLATFORM_ANALYSIS,  // Unified phase (replaces ANDROID_ANALYSIS)
    FINALIZING
};
```

`PLATFORM_ANALYSIS` replaces `ANDROID_ANALYSIS` since multiple platform analyzers now exist.

---

## Pipeline Integration

### Execution Flow

```
Image Analysis → Event Extraction → File Classification → LLM Analysis
                                                                    ↓
                                                    ┌───────────────────────┐
                                                    │  PLATFORM_ANALYSIS    │
                                                    │                       │
                                                    │  1. Android (if selected)
                                                    │     → _android.db     │
                                                    │                       │
                                                    │  2. Windows (if selected)
                                                    │     → _windows.db     │
                                                    │                       │
                                                    │  3. Linux (if selected)
                                                    │     → _linux.db       │
                                                    │                       │
                                                    │  4. Server (if selected)
                                                    │     → _server.db      │
                                                    └───────────────────────┘
                                                                    ↓
                                                        Graphiti Ingestion
```

### Core Pipeline (Steps 1-5, unchanged)

Steps 1-5 run once regardless of scenario selection. All scenarios share the same `_raw.db`, `_events.db`, and `_files.db`.

### Platform Analysis (Step 6, new)

```cpp
// In TaskManager::start_analysis()
if (!task.scenarios.empty()) {
    update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 0,
        "Starting platform analysis for " + std::to_string(task.scenarios.size()) + " scenario(s)...");

    int scenario_index = 0;
    for (auto scenario : task.scenarios) {
        if (is_task_cancelled(task_id)) return;

        int base_progress = (scenario_index * 100) / task.scenarios.size();
        std::string scenario_name = scenario_to_string(scenario);
        update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, base_progress,
            "Analyzing " + scenario_name + " artifacts...");

        switch (scenario) {
            case ForensicScenario::ANDROID:
                run_android_analysis(task_id, imagePath, effectiveRawDb, baseName, pm);
                break;
            case ForensicScenario::WINDOWS:
                run_windows_analysis(task_id, imagePath, effectiveRawDb, baseName, pm);
                break;
            case ForensicScenario::LINUX:
                run_linux_analysis(task_id, imagePath, effectiveRawDb, baseName, pm);
                break;
            case ForensicScenario::SERVER_CLOUD:
                run_server_cloud_analysis(task_id, imagePath, effectiveRawDb, baseName, pm);
                break;
        }

        scenario_index++;
        int done_progress = (scenario_index * 100) / task.scenarios.size();
        update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, done_progress,
            scenario_name + " analysis completed");
    }
}
```

### Per-Scenario Analysis Methods

Each scenario is a private method in TaskManager:

```cpp
void run_android_analysis(const std::string& task_id,
    const std::string& imagePath, const std::string& rawDb,
    const std::string& baseName, PathManager& pm);

void run_windows_analysis(const std::string& task_id,
    const std::string& imagePath, const std::string& rawDb,
    const std::string& baseName, PathManager& pm);

void run_linux_analysis(const std::string& task_id,
    const std::string& imagePath, const std::string& rawDb,
    const std::string& baseName, PathManager& pm);

void run_server_cloud_analysis(const std::string& task_id,
    const std::string& imagePath, const std::string& rawDb,
    const std::string& baseName, PathManager& pm);
```

### Database Paths

| Scenario | Database Path |
|----------|---------------|
| Android | `{task_dir}/{baseName}_android.db` |
| Windows | `{task_dir}/{baseName}_windows.db` |
| Linux | `{task_dir}/{baseName}_linux.db` |
| Server/Cloud | `{task_dir}/{baseName}_server.db` |

### Progress Weight Adjustment

```cpp
std::map<TaskPhase, int> phase_weights = {
    {TaskPhase::INITIALIZING, 5},
    {TaskPhase::IMAGE_ANALYSIS, 25},
    {TaskPhase::EVENT_EXTRACTION, 10},
    {TaskPhase::FILE_CLASSIFICATION, 15},
    {TaskPhase::LLM_ANALYSIS, 20},
    {TaskPhase::PLATFORM_ANALYSIS, 23},  // Unified phase, increased weight
    {TaskPhase::FINALIZING, 2}
};
```

---

## API Changes

### Create Task Request (`POST /api/tasks`)

```json
{
  "image_path": "/path/to/image.dd",
  "priority": "normal",
  "case_description": "Case description",
  "scenarios": ["android", "windows"],
  "filter_profile": "telecom_fraud",
  "xfs_mode": "auto",
  "llm_analyze": true,
  "llm_mode": "smart"
}
```

### Backward Compatibility

If `scenarios` is absent but `android_analyze: true` exists, convert to `scenarios: ["android"]`.

```cpp
// In TaskCRUDRoutes::handle_create_task
std::vector<ForensicScenario> scenarios;
if (body.contains("scenarios")) {
    for (const auto& s : body["scenarios"]) {
        std::string val = s.get<std::string>();
        if (val == "android") scenarios.push_back(ForensicScenario::ANDROID);
        else if (val == "windows") scenarios.push_back(ForensicScenario::WINDOWS);
        else if (val == "linux") scenarios.push_back(ForensicScenario::LINUX);
        else if (val == "server_cloud") scenarios.push_back(ForensicScenario::SERVER_CLOUD);
    }
} else if (body.value("android_analyze", false)) {
    scenarios = {ForensicScenario::ANDROID};
}
```

### Task Response

```json
{
  "id": "task-uuid",
  "scenarios": ["android", "windows"],
  "scenario_databases": {
    "android": "/path/to/_android.db",
    "windows": "/path/to/_windows.db"
  },
  "android_analyze": true,
  "platform_analysis_phase": "completed",
  ...
}
```

---

## Frontend Changes

### CreateTaskModal.jsx

Replace the single Android checkbox with a multi-select scenario group:

```jsx
const INITIAL_FORM = {
  image_path: '',
  priority: 'normal',
  case_description: '',
  scenarios: [],        // Replaces android_analyze: false
  xfs_mode: 'auto',
  filter_profile: '',
};

// Scenario selection UI
<Field label="取证场景 *" hint="选择需要分析的平台场景（可多选）">
  <div className="space-y-2">
    {[
      { value: 'android', label: '📱 Android', desc: 'SMS、联系人、通话记录、应用数据' },
      { value: 'windows', label: '🪟 Windows', desc: '注册表、事件日志、Prefetch、浏览器历史' },
      { value: 'linux', label: '🐧 Linux', desc: '系统日志、用户账户、Shell 历史、SSH' },
      { value: 'server_cloud', label: '☁️ 服务器/云', desc: 'Docker、Nginx/Apache、K8s、云配置' },
    ].map(s => (
      <label key={s.value} className="flex items-start gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={form.scenarios.includes(s.value)}
          disabled={isCreating}
          onChange={(e) => {
            set('scenarios', e.target.checked
              ? [...form.scenarios, s.value]
              : form.scenarios.filter(v => v !== s.value));
          }}
          className="mt-1 rounded border-slate-300 text-primary-600"
        />
        <div>
          <span className="text-sm text-slate-700 dark:text-slate-300">{s.label}</span>
          <p className="text-xs text-slate-400">{s.desc}</p>
        </div>
      </label>
    ))}
  </div>
</Field>
```

---

## Server/Cloud Scenario Implementation

Extends `LinuxFilesAnalyzer` with server/cloud-specific analysis methods.

### New Methods in LinuxFilesAnalyzer

```cpp
// Entry point for server/cloud analysis
void analyzeServerCloudArtifacts();

// New capabilities:
void analyzeKubernetesConfigs();      // K8s configmaps, secrets, pod specs
void analyzeCloudMetadata();          // /etc/cloud/, cloud-init configs
void analyzeContainerOrchestration(); // Docker Compose, K8s manifests
void analyzeServiceMesh();            // Istio, Envoy configs
void analyzeCICDPipelines();          // Jenkins, GitLab CI configs
```

### Existing Capabilities (reused)

- `analyzeDockerContainers()`
- `analyzeDockerImages()`
- `analyzeDockerVolumes()`
- `analyzePodmanContainers()`
- `analyzeApacheServers()`
- `analyzeNginxServers()`

### Routing Logic

When `ForensicScenario::SERVER_CLOUD` is selected, the pipeline calls `LinuxFilesAnalyzer::analyzeServerCloudArtifacts()` instead of `analyzeLinuxData()`.

---

## Serialization / Backward Compatibility

### TaskSerialization.cpp

```cpp
void to_json(nlohmann::json& j, const AnalysisTask& t) {
    // ... existing fields ...
    j["scenarios"] = t.scenarios;
    j["android_analyze"] = t.get_android_analyze();  // Computed for backward compat
}

void from_json(const nlohmann::json& j, AnalysisTask& t) {
    // ... existing fields ...

    if (j.contains("scenarios")) {
        j.at("scenarios").get_to(t.scenarios);
    } else if (j.contains("android_analyze") && j["android_analyze"].get<bool>()) {
        t.scenarios = {ForensicScenario::ANDROID};
    }
}
```

---

## Files to Modify

| File | Change Type | Description |
|------|-------------|-------------|
| `src/network/HTTPServer/HTTPServerDataTypes.h` | Modify | Add `ForensicScenario` enum, modify `AnalysisTask`, update `TaskPhase` |
| `src/network/HTTPServer/TaskSerialization.cpp` | Modify | Serialize/deserialize `scenarios`, backward compat |
| `src/network/HTTPServer/TaskManager.cpp` | Modify | Pipeline refactor, add scenario analysis methods |
| `src/network/HTTPServer/TaskManager.h` | Modify | New method declarations |
| `src/network/HTTPServer/routes/TaskCRUDRoutes.cpp` | Modify | Parse `scenarios` from request |
| `src/network/HTTPServer/routes/TaskHelpers.cpp` | Modify | Output `scenarios` in task JSON |
| `web/src/components/tasks/CreateTaskModal.jsx` | Modify | Scenario multi-select UI |
| `src/analyzers/LinuxFilesAnalyzer/.../LinuxAnalyzerDeclarations.h` | Modify | Add server/cloud method declarations |
| `src/analyzers/LinuxFilesAnalyzer/.../LinuxFilesAnalyzerCore.cpp` | Modify | Implement server/cloud analysis |

---

## Testing Strategy

### Unit Tests

- `test_task_scenarios_gtest.cpp`:
  - `ForensicScenario` enum serialization/deserialization
  - Backward compat: `android_analyze: true` → `scenarios: [ANDROID]`
  - Multi-scenario task creation and retrieval
  - `scenario_to_string()` and `string_to_scenario()` helpers

### Integration Tests

- Modify `test_e01_http.sh`:
  - Create task with multiple scenarios
  - Verify per-scenario database generation
  - Verify progress reporting includes `PLATFORM_ANALYSIS` phase

### Frontend Tests

- Verify scenario checkbox group renders correctly
- Verify multi-selection works
- Verify form submission sends `scenarios` array

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Old tasks JSON without `scenarios` field | Medium | Backward compat in `from_json` |
| Windows/Linux analyzers fail on non-applicable images | Low | Analyzers already handle missing files gracefully |
| Server/Cloud analysis overlaps with Linux analysis | Medium | Clear separation: `analyzeLinuxData()` vs `analyzeServerCloudArtifacts()` |
| Frontend sends invalid scenario values | Low | Backend validates and ignores unknown values |
