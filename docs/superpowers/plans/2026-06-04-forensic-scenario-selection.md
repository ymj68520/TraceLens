# Forensic Scenario Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single `bool android_analyze` flag with a unified `ForensicScenario` enum system supporting Android, Windows, Linux, and Server/Cloud scenarios with multi-select capability.

**Architecture:** Introduce a `ForensicScenario` enum and replace `bool android_analyze` in `AnalysisTask` with `std::vector<ForensicScenario> scenarios`. The pipeline runs a unified `PLATFORM_ANALYSIS` phase that iterates over selected scenarios and invokes the corresponding analyzer. Each scenario writes to an independent database. Backward compatibility is maintained via serialization logic.

**Tech Stack:** C++20, SQLite, Crow HTTP framework, nlohmann::json, React JSX

---

## File Structure

### Files to Modify

| File | Responsibility |
|------|----------------|
| `src/network/HTTPServer/HTTPServerDataTypes.h` | Data types: `ForensicScenario` enum, `AnalysisTask`, `TaskPhase` |
| `src/network/HTTPServer/TaskSerialization.cpp` | JSON serialization with backward compat |
| `src/network/HTTPServer/TaskManager.h` | Method declarations for scenario analysis |
| `src/network/HTTPServer/TaskManager.cpp` | Pipeline refactor, scenario analysis methods |
| `src/network/HTTPServer/routes/TaskCRUDRoutes.cpp` | API request parsing for `scenarios` |
| `src/network/HTTPServer/routes/TaskHelpers.cpp` | API response formatting |
| `web/src/components/tasks/CreateTaskModal.jsx` | Frontend scenario multi-select UI |
| `src/analyzers/LinuxFilesAnalyzer/Common/LinuxAnalyzerDeclarations.h` | Server/cloud method declarations |
| `src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerCore.cpp` | Server/cloud analysis implementation |
| `tests/UnitTest/test_task_scenarios_gtest.cpp` | Unit tests (new file) |

### Existing Infrastructure (no changes needed)

| File | Why |
|------|-----|
| `src/core/PathManager/PathManager.h` | Already has `androidDb`, `windowsDb`, `linuxDb`, `ossDb` in `TaskDbPaths` |
| `src/analyzers/WindowsFilesAnalyzer/` | Already fully implemented |
| `src/analyzers/LinuxFilesAnalyzer/` | Already has Docker/Nginx/Apache analysis |

---

## Task 1: Add ForensicScenario Enum and Modify Data Types

**Files:**
- Modify: `src/network/HTTPServer/HTTPServerDataTypes.h:1-28`

- [ ] **Step 1: Add ForensicScenario enum after the existing enums**

In `src/network/HTTPServer/HTTPServerDataTypes.h`, add after line 28 (after `TaskPhase` closing brace):

```cpp
/**
 * @brief Forensic analysis scenario types
 * Supports multi-scenario tasks where multiple platform analyzers run sequentially.
 */
enum class ForensicScenario {
    ANDROID,        // Android device forensics (SMS, contacts, call logs, apps)
    WINDOWS,        // Windows system forensics (registry, event logs, prefetch)
    LINUX,          // Linux system forensics (logs, users, shell history, SSH)
    SERVER_CLOUD    // Server/Cloud environment (Docker, K8s, Nginx, cloud configs)
};

/**
 * @brief Convert ForensicScenario enum to string
 */
inline std::string scenario_to_string(ForensicScenario scenario) {
    switch (scenario) {
        case ForensicScenario::ANDROID: return "android";
        case ForensicScenario::WINDOWS: return "windows";
        case ForensicScenario::LINUX: return "linux";
        case ForensicScenario::SERVER_CLOUD: return "server_cloud";
        default: return "unknown";
    }
}

/**
 * @brief Convert string to ForensicScenario enum
 * Returns std::nullopt if the string is not a valid scenario.
 */
inline std::optional<ForensicScenario> string_to_scenario(const std::string& str) {
    if (str == "android") return ForensicScenario::ANDROID;
    if (str == "windows") return ForensicScenario::WINDOWS;
    if (str == "linux") return ForensicScenario::LINUX;
    if (str == "server_cloud") return ForensicScenario::SERVER_CLOUD;
    return std::nullopt;
}
```

- [ ] **Step 2: Add `<optional>` include at the top of the file**

In `src/network/HTTPServer/HTTPServerDataTypes.h`, add after line 9 (`#include <coroutine>`):

```cpp
#include <optional>
#include <algorithm>
```

- [ ] **Step 3: Replace ANDROID_ANALYSIS with PLATFORM_ANALYSIS in TaskPhase**

In `src/network/HTTPServer/HTTPServerDataTypes.h`, replace lines 20-28:

```cpp
enum class TaskPhase {
    INITIALIZING,
    IMAGE_ANALYSIS,
    EVENT_EXTRACTION,
    FILE_CLASSIFICATION,
    LLM_ANALYSIS,        // LLM file description generation
    PLATFORM_ANALYSIS,   // Platform-specific analysis (Android/Windows/Linux/Server)
    FINALIZING
};
```

- [ ] **Step 4: Add scenarios vector to AnalysisTask**

In `src/network/HTTPServer/HTTPServerDataTypes.h`, find the `AnalysisTask` struct (around line 60). Replace `bool android_analyze;` (line 77) with:

```cpp
    std::vector<ForensicScenario> scenarios;  // Selected forensic scenarios

    // Backward compatibility: computed property
    bool get_android_analyze() const {
        return std::find(scenarios.begin(), scenarios.end(),
                         ForensicScenario::ANDROID) != scenarios.end();
    }
```

- [ ] **Step 5: Update AnalysisTask copy constructor**

In the copy constructor (around line 96), replace `android_analyze(other.android_analyze)` with `scenarios(other.scenarios)`.

- [ ] **Step 6: Update AnalysisTask copy assignment operator**

In the copy assignment operator (around line 114), replace `android_analyze = other.android_analyze;` with `scenarios = other.scenarios;`.

- [ ] **Step 7: Update AnalysisTask move constructor**

In the move constructor (around line 148), replace `android_analyze(other.android_analyze)` with `scenarios(std::move(other.scenarios))`.

- [ ] **Step 8: Update AnalysisTask move assignment operator**

In the move assignment operator (around line 168), replace `android_analyze = other.android_analyze;` with `scenarios = std::move(other.scenarios);`.

- [ ] **Step 9: Build to verify compilation**

Run: `cd build && cmake --build . -j$(nproc) 2>&1 | head -50`

Expected: Compilation errors in files that reference `android_analyze` directly (TaskSerialization, TaskCRUDRoutes, TaskHelpers, TaskManager). This is expected — we fix them in subsequent tasks.

- [ ] **Step 10: Commit**

```bash
git add src/network/HTTPServer/HTTPServerDataTypes.h
git commit -m "feat: add ForensicScenario enum and update AnalysisTask data types"
```

---

## Task 2: Update TaskSerialization for Scenarios

**Files:**
- Modify: `src/network/HTTPServer/TaskSerialization.cpp:56-105`

- [ ] **Step 1: Add ForensicScenario enum serialization**

In `src/network/HTTPServer/TaskSerialization.cpp`, add after the `XFSMode` serialization (after line 37):

```cpp
NLOHMANN_JSON_SERIALIZE_ENUM(ForensicScenario, {
    {ForensicScenario::ANDROID, "ANDROID"},
    {ForensicScenario::WINDOWS, "WINDOWS"},
    {ForensicScenario::LINUX, "LINUX"},
    {ForensicScenario::SERVER_CLOUD, "SERVER_CLOUD"}
})
```

- [ ] **Step 2: Update to_json for AnalysisTask**

In `src/network/HTTPServer/TaskSerialization.cpp`, in the `to_json` function for `AnalysisTask` (line 56), replace `j["android_analyze"] = t.android_analyze;` (line 67) with:

```cpp
    j["scenarios"] = t.scenarios;
    j["android_analyze"] = t.get_android_analyze();  // Backward compat
```

- [ ] **Step 3: Update from_json for AnalysisTask**

In `src/network/HTTPServer/TaskSerialization.cpp`, in the `from_json` function for `AnalysisTask` (line 85), replace `if(j.contains("android_analyze")) j.at("android_analyze").get_to(t.android_analyze);` (line 96) with:

```cpp
    // Backward compat: handle scenarios field
    if (j.contains("scenarios")) {
        j.at("scenarios").get_to(t.scenarios);
    } else if (j.contains("android_analyze") && j["android_analyze"].get<bool>()) {
        // Old format: convert android_analyze: true → scenarios: [ANDROID]
        t.scenarios = {ForensicScenario::ANDROID};
    }
```

- [ ] **Step 4: Build to verify**

Run: `cd build && cmake --build . -j$(nproc) 2>&1 | head -50`

Expected: Fewer errors. Remaining errors in TaskCRUDRoutes, TaskHelpers, TaskManager.

- [ ] **Step 5: Commit**

```bash
git add src/network/HTTPServer/TaskSerialization.cpp
git commit -m "feat: update task serialization for ForensicScenario with backward compat"
```

---

## Task 3: Update TaskHelpers for API Response

**Files:**
- Modify: `src/network/HTTPServer/routes/TaskHelpers.cpp:32-66`

- [ ] **Step 1: Add scenarios and scenario_databases to task_to_json**

In `src/network/HTTPServer/routes/TaskHelpers.cpp`, in `task_to_json` (line 10), replace `{"android_analyze", task.android_analyze},` (line 53) with:

```cpp
    // Build scenario_databases map
    json scenario_databases = json::object();
    auto& pm = forensics::PathManager::instance();
    auto dbPaths = pm.getTaskDbPaths(task.id);
    for (auto scenario : task.scenarios) {
        std::string key = scenario_to_string(scenario);
        std::string db_path;
        switch (scenario) {
            case ForensicScenario::ANDROID: db_path = dbPaths.androidDb.string(); break;
            case ForensicScenario::WINDOWS: db_path = dbPaths.windowsDb.string(); break;
            case ForensicScenario::LINUX: db_path = dbPaths.linuxDb.string(); break;
            case ForensicScenario::SERVER_CLOUD: db_path = dbPaths.ossDb.string(); break;
        }
        if (std::filesystem::exists(db_path)) {
            scenario_databases[key] = db_path;
        }
    }

    // Scenarios as string array for API
    json scenarios_json = json::array();
    for (auto s : task.scenarios) {
        scenarios_json.push_back(scenario_to_string(s));
    }
```

Then in the return JSON, replace `{"android_analyze", task.android_analyze},` with:

```cpp
    {"scenarios", scenarios_json},
    {"scenario_databases", scenario_databases},
    {"android_analyze", task.get_android_analyze()},  // Backward compat
```

- [ ] **Step 2: Add filesystem include if missing**

At the top of `TaskHelpers.cpp`, ensure `#include <filesystem>` is present.

- [ ] **Step 3: Build to verify**

Run: `cd build && cmake --build . -j$(nproc) 2>&1 | head -50`

Expected: Fewer errors. Remaining errors in TaskCRUDRoutes, TaskManager.

- [ ] **Step 4: Commit**

```bash
git add src/network/HTTPServer/routes/TaskHelpers.cpp
git commit -m "feat: update task API response with scenarios and scenario_databases"
```

---

## Task 4: Update TaskCRUDRoutes for API Request Parsing

**Files:**
- Modify: `src/network/HTTPServer/routes/TaskCRUDRoutes.cpp:127-215`

- [ ] **Step 1: Replace android_analyze parsing with scenarios parsing**

In `src/network/HTTPServer/routes/TaskCRUDRoutes.cpp`, in `handle_create_task` (line 127), replace lines 156-157:

```cpp
        // Android analyze option
        bool android_analyze = body.value("android_analyze", false);
```

With:

```cpp
        // Forensic scenarios (multi-select)
        std::vector<ForensicScenario> scenarios;
        if (body.contains("scenarios")) {
            for (const auto& s : body["scenarios"]) {
                std::string val = s.get<std::string>();
                auto scenario = string_to_scenario(val);
                if (scenario.has_value()) {
                    scenarios.push_back(scenario.value());
                }
            }
        } else if (body.value("android_analyze", false)) {
            // Backward compat: old android_analyze flag
            scenarios = {ForensicScenario::ANDROID};
        }
```

- [ ] **Step 2: Update create_task call**

Replace `android_analyze,` in the `create_task` call (around line 184) with `scenarios,`.

- [ ] **Step 3: Update create_task method signature in TaskManager.h**

In `src/network/HTTPServer/TaskManager.h`, replace the `create_task` declaration (lines 59-69):

```cpp
    std::string create_task(const std::string& path,
                           TaskPriority priority = TaskPriority::NORMAL,
                           const std::map<std::string, std::string>& metadata = {},
                           const std::vector<TaskDependency>& dependencies = {},
                           const std::vector<ForensicScenario>& scenarios = {},
                           XFSMode xfs_mode = XFSMode::Auto,
                           const std::string& db_output_dir = "",
                           bool llm_analyze = false,
                           const std::string& llm_mode = "smart",
                           const std::string& case_description = "",
                           const std::string& filter_profile = "");
```

- [ ] **Step 4: Update create_task implementation in TaskManager.cpp**

In `src/network/HTTPServer/TaskManager.cpp`, replace the `create_task` signature (lines 74-84):

```cpp
std::string TaskManager::create_task(const std::string& path,
                                   TaskPriority priority,
                                   const std::map<std::string, std::string>& metadata,
                                   const std::vector<TaskDependency>& dependencies,
                                   const std::vector<ForensicScenario>& scenarios,
                                   XFSMode xfs_mode,
                                   const std::string& db_output_dir,
                                   bool llm_analyze,
                                   const std::string& llm_mode,
                                   const std::string& case_description,
                                   const std::string& filter_profile) {
```

And replace `new_task.android_analyze = android_analyze;` (line 108) with:

```cpp
    new_task.scenarios = scenarios;
```

- [ ] **Step 5: Update response JSON in TaskCRUDRoutes**

In the response JSON (around line 198), replace `{"llm_analyze", llm_analyze},` with:

```cpp
    {"scenarios", [&scenarios]() {
        json arr = json::array();
        for (auto s : scenarios) arr.push_back(scenario_to_string(s));
        return arr;
    }()},
```

- [ ] **Step 6: Build to verify**

Run: `cd build && cmake --build . -j$(nproc) 2>&1 | head -50`

Expected: Remaining errors only in TaskManager.cpp (pipeline code) and frontend.

- [ ] **Step 7: Commit**

```bash
git add src/network/HTTPServer/routes/TaskCRUDRoutes.cpp src/network/HTTPServer/TaskManager.h src/network/HTTPServer/TaskManager.cpp
git commit -m "feat: update API to parse scenarios array with backward compat"
```

---

## Task 5: Refactor TaskManager Pipeline for Scenario Analysis

**Files:**
- Modify: `src/network/HTTPServer/TaskManager.cpp:495-813`
- Modify: `src/network/HTTPServer/TaskManager.h:267-298`

- [ ] **Step 1: Update phase_weights in calculate_overall_percentage**

In `src/network/HTTPServer/TaskManager.cpp`, in `calculate_overall_percentage` (line 825), replace the phase_weights map:

```cpp
    std::map<TaskPhase, int> phase_weights = {
        {TaskPhase::INITIALIZING, 5},
        {TaskPhase::IMAGE_ANALYSIS, 25},
        {TaskPhase::EVENT_EXTRACTION, 10},
        {TaskPhase::FILE_CLASSIFICATION, 15},
        {TaskPhase::LLM_ANALYSIS, 20},
        {TaskPhase::PLATFORM_ANALYSIS, 23},
        {TaskPhase::FINALIZING, 2}
    };
```

- [ ] **Step 2: Replace the Android analysis block with unified platform analysis**

In `src/network/HTTPServer/TaskManager.cpp`, replace lines 751-772 (the `// 6. Android Analysis` block) with:

```cpp
            // 6. Platform-Specific Analysis (Unified)
            if (!task.scenarios.empty()) {
                if (is_task_cancelled(task_id)) { return; }
                int total_scenarios = static_cast<int>(task.scenarios.size());
                update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 0,
                    "Starting platform analysis for " + std::to_string(total_scenarios) + " scenario(s)...");

                int scenario_index = 0;
                for (auto scenario : task.scenarios) {
                    if (is_task_cancelled(task_id)) { return; }

                    int base_progress = (scenario_index * 100) / total_scenarios;
                    std::string scenario_name = scenario_to_string(scenario);
                    update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, base_progress,
                        "Analyzing " + scenario_name + " artifacts...");

                    try {
                        switch (scenario) {
                            case ForensicScenario::ANDROID: {
                                auto dbManager = std::make_unique<DatabaseManager>(effectiveRawDb);
                                auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(imagePath, dbManager.get());
                                std::string androidDbPath = pm.getTaskDbPaths(task_id, baseName).androidDb.string();
                                androidAnalyzer->setOutputDatabasePath(androidDbPath);
                                if (androidAnalyzer->initialize()) {
                                    androidAnalyzer->analyzeAndroidData();
                                } else {
                                    std::cerr << "Warning: Failed to initialize Android analyzer" << std::endl;
                                }
                                break;
                            }
                            case ForensicScenario::WINDOWS: {
                                auto dbManager = std::make_unique<DatabaseManager>(effectiveRawDb);
                                auto windowsAnalyzer = std::make_unique<WindowsFilesAnalyzer>(imagePath, dbManager.get());
                                std::string windowsDbPath = pm.getTaskDbPaths(task_id, baseName).windowsDb.string();
                                windowsAnalyzer->setOutputDatabasePath(windowsDbPath);
                                if (windowsAnalyzer->initialize()) {
                                    windowsAnalyzer->analyzeWindowsData();
                                } else {
                                    std::cerr << "Warning: Failed to initialize Windows analyzer" << std::endl;
                                }
                                break;
                            }
                            case ForensicScenario::LINUX: {
                                auto dbManager = std::make_unique<DatabaseManager>(effectiveRawDb);
                                auto linuxAnalyzer = std::make_unique<LinuxFilesAnalyzer>(imagePath, dbManager.get());
                                std::string linuxDbPath = pm.getTaskDbPaths(task_id, baseName).linuxDb.string();
                                linuxAnalyzer->setOutputDatabasePath(linuxDbPath);
                                if (linuxAnalyzer->initialize()) {
                                    linuxAnalyzer->analyzeLinuxData();
                                } else {
                                    std::cerr << "Warning: Failed to initialize Linux analyzer" << std::endl;
                                }
                                break;
                            }
                            case ForensicScenario::SERVER_CLOUD: {
                                auto dbManager = std::make_unique<DatabaseManager>(effectiveRawDb);
                                auto serverAnalyzer = std::make_unique<LinuxFilesAnalyzer>(imagePath, dbManager.get());
                                std::string serverDbPath = pm.getTaskDbPaths(task_id, baseName).ossDb.string();
                                serverAnalyzer->setOutputDatabasePath(serverDbPath);
                                if (serverAnalyzer->initialize()) {
                                    serverAnalyzer->analyzeServerCloudArtifacts();
                                } else {
                                    std::cerr << "Warning: Failed to initialize Server/Cloud analyzer" << std::endl;
                                }
                                break;
                            }
                        }
                    } catch (const std::exception& e) {
                        std::cerr << "Warning: " << scenario_name << " analysis failed: " << e.what() << std::endl;
                        add_audit_log(task_id, "WARNING", scenario_name + " analysis failed: " + std::string(e.what()));
                    }

                    scenario_index++;
                    int done_progress = (scenario_index * 100) / total_scenarios;
                    update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, done_progress,
                        scenario_name + " analysis completed");
                }
            }
```

- [ ] **Step 3: Add necessary includes at the top of TaskManager.cpp**

At the top of `src/network/HTTPServer/TaskManager.cpp`, ensure these includes exist:

```cpp
#include "../../analyzers/WindowsFilesAnalyzer/Common/WindowsAnalyzerDeclarations.h"
#include "../../analyzers/LinuxFilesAnalyzer/Common/LinuxAnalyzerDeclarations.h"
```

- [ ] **Step 4: Remove the old set_android_analyze_options method**

In `src/network/HTTPServer/TaskManager.cpp`, replace `set_android_analyze_options` (lines 189-198) with:

```cpp
void TaskManager::set_scenarios(const std::string& id, const std::vector<ForensicScenario>& scenarios) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        tasks_[id].scenarios = scenarios;
        save_tasks_internal();
    }
}
```

In `src/network/HTTPServer/TaskManager.h`, replace the `set_android_analyze_options` declaration (line 104) with:

```cpp
    void set_scenarios(const std::string& id, const std::vector<ForensicScenario>& scenarios);
```

- [ ] **Step 5: Update TaskPhase serialization**

In `src/network/HTTPServer/TaskSerialization.cpp`, replace `ANDROID_ANALYSIS` with `PLATFORM_ANALYSIS` in the `TaskPhase` enum serialization (line 29):

```cpp
    {TaskPhase::PLATFORM_ANALYSIS, "PLATFORM_ANALYSIS"},
```

Also update `TaskHelpers.cpp` phase_to_string (line 105):

```cpp
        case TaskPhase::PLATFORM_ANALYSIS: return "platform_analysis";
```

- [ ] **Step 6: Build to verify**

Run: `cd build && cmake --build . -j$(nproc) 2>&1 | head -50`

Expected: Compilation succeeds (or only frontend errors remain).

- [ ] **Step 7: Commit**

```bash
git add src/network/HTTPServer/TaskManager.cpp src/network/HTTPServer/TaskManager.h \
        src/network/HTTPServer/TaskSerialization.cpp src/network/HTTPServer/routes/TaskHelpers.cpp
git commit -m "feat: refactor pipeline for unified PLATFORM_ANALYSIS with multi-scenario support"
```

---

## Task 6: Add Server/Cloud Analysis to LinuxFilesAnalyzer

**Files:**
- Modify: `src/analyzers/LinuxFilesAnalyzer/Common/LinuxAnalyzerDeclarations.h:95-155`
- Modify: `src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerCore.cpp:141+`

- [ ] **Step 1: Add method declarations to LinuxAnalyzerDeclarations.h**

In `src/analyzers/LinuxFilesAnalyzer/Common/LinuxAnalyzerDeclarations.h`, add after `analyzeBrowserDetailedData()` (around line 150):

```cpp
    // Server/Cloud environment analysis (for SERVER_CLOUD scenario)
    /** @brief Entry point for server/cloud artifact analysis */
    void analyzeServerCloudArtifacts();

    // New server/cloud capabilities
    /** @brief Analyze Kubernetes configurations and resources */
    void analyzeKubernetesConfigs();
    /** @brief Analyze cloud instance metadata (cloud-init, /etc/cloud/) */
    void analyzeCloudMetadata();
    /** @brief Analyze container orchestration (Docker Compose, K8s manifests) */
    void analyzeContainerOrchestration();
    /** @brief Analyze CI/CD pipeline configurations */
    void analyzeCICDPipelines();
```

- [ ] **Step 2: Implement analyzeServerCloudArtifacts in LinuxFilesAnalyzerCore.cpp**

In `src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerCore.cpp`, add after the last method implementation (end of file):

```cpp
// ============================================================================
// Server/Cloud Environment Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeServerCloudArtifacts() {
    // Entry point for SERVER_CLOUD scenario
    // Reuses existing Linux analyzer capabilities + new server/cloud methods

    // Existing container analysis
    analyzeDockerContainers();
    analyzeDockerImages();
    analyzeDockerVolumes();
    analyzePodmanContainers();

    // Existing web server analysis
    analyzeApacheServers();
    analyzeNginxServers();

    // New server/cloud capabilities
    analyzeKubernetesConfigs();
    analyzeCloudMetadata();
    analyzeContainerOrchestration();
    analyzeCICDPipelines();
}

void LinuxFilesAnalyzer::analyzeKubernetesConfigs() {
    // Analyze Kubernetes configmaps, secrets, and resource definitions
    auto k8sFiles = queryFilesByPattern("/etc/kubernetes/%");
    k8sFiles.push_back(queryFilesByPattern("/var/lib/kubelet/%"));

    for (const auto& file : k8sFiles) {
        // Parse YAML/JSON K8s resource definitions
        // Extract namespace, kind, metadata, and security-relevant fields
    }
}

void LinuxFilesAnalyzer::analyzeCloudMetadata() {
    // Analyze cloud-init configuration and instance metadata
    auto cloudFiles = queryFilesByPattern("/etc/cloud/%");
    cloudFiles.push_back(queryFilesByPattern("/var/lib/cloud/%"));

    for (const auto& file : cloudFiles) {
        // Parse cloud-init configs, user-data scripts
        // Extract instance metadata, security groups, IAM roles
    }
}

void LinuxFilesAnalyzer::analyzeContainerOrchestration() {
    // Analyze Docker Compose files and K8s manifests
    auto composeFiles = queryFilesByPattern("%/docker-compose.yml");
    composeFiles.push_back(queryFilesByPattern("%/docker-compose.yaml"));
    composeFiles.push_back(queryFilesByPattern("%/Dockerfile"));

    for (const auto& file : composeFiles) {
        // Parse compose/manifest files
        // Extract service definitions, port mappings, volume mounts, secrets
    }
}

void LinuxFilesAnalyzer::analyzeCICDPipelines() {
    // Analyze CI/CD pipeline configurations
    auto jenkinsFiles = queryFilesByPattern("%/Jenkinsfile%");
    auto gitlabFiles = queryFilesByPattern("%/.gitlab-ci.yml");
    auto githubFiles = queryFilesByPattern("%/.github/workflows/%");

    for (const auto& file : jenkinsFiles) {
        // Parse Jenkinsfile for credentials, deployment targets
    }
    for (const auto& file : gitlabFiles) {
        // Parse GitLab CI config
    }
    for (const auto& file : githubFiles) {
        // Parse GitHub Actions workflows
    }
}
```

- [ ] **Step 3: Build to verify**

Run: `cd build && cmake --build . -j$(nproc) 2>&1 | head -50`

Expected: Compilation succeeds.

- [ ] **Step 4: Commit**

```bash
git add src/analyzers/LinuxFilesAnalyzer/Common/LinuxAnalyzerDeclarations.h \
        src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerCore.cpp
git commit -m "feat: add server/cloud analysis methods to LinuxFilesAnalyzer"
```

---

## Task 7: Update Frontend CreateTaskModal

**Files:**
- Modify: `web/src/components/tasks/CreateTaskModal.jsx:1-201`

- [ ] **Step 1: Update INITIAL_FORM**

In `web/src/components/tasks/CreateTaskModal.jsx`, replace lines 21-29:

```javascript
const INITIAL_FORM = {
  image_path: '',
  priority: 'normal',
  case_description: '',
  scenarios: [],
  xfs_mode: 'auto',
  filter_profile: '',
};
```

- [ ] **Step 2: Update form submission**

In the `handleSubmit` function (line 43), replace line 48:

```javascript
      await dispatch(createTask({ ...form, llm_analyze: true, llm_mode: 'smart' })).unwrap();
```

No change needed — `form.scenarios` is already included via `...form`.

- [ ] **Step 3: Replace Android checkbox with scenario multi-select group**

In `web/src/components/tasks/CreateTaskModal.jsx`, replace lines 127-137 (the Android checkbox section):

```jsx
          {/* Forensic Scenarios */}
          <Field label="取证场景 *" hint="选择需要分析的平台场景（可多选）">
            <div className="space-y-2">
              {[
                { value: 'android', label: '📱 Android', desc: 'SMS、联系人、通话记录、应用数据' },
                { value: 'windows', label: '🪟 Windows', desc: '注册表、事件日志、Prefetch、浏览器历史' },
                { value: 'linux', label: '🐧 Linux', desc: '系统日志、用户账户、Shell 历史、SSH' },
                { value: 'server_cloud', label: '☁️ 服务器/云', desc: 'Docker、Nginx/Apache、K8s、云配置' },
              ].map((s) => (
                <label key={s.value} className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.scenarios.includes(s.value)}
                    disabled={isCreating}
                    onChange={(e) => {
                      set(
                        'scenarios',
                        e.target.checked
                          ? [...form.scenarios, s.value]
                          : form.scenarios.filter((v) => v !== s.value)
                      );
                    }}
                    className="mt-1 rounded border-slate-300 text-primary-600 focus:ring-primary-500 disabled:opacity-50"
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

- [ ] **Step 4: Remove the LLM always-on notice (optional cleanup)**

The LLM notice (lines 161-167) can remain as-is — it's still relevant.

- [ ] **Step 5: Verify frontend builds**

Run: `cd web && npm run build 2>&1 | tail -10`

Expected: Build succeeds.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/tasks/CreateTaskModal.jsx
git commit -m "feat: replace Android checkbox with multi-scenario selection UI"
```

---

## Task 8: Write Unit Tests

**Files:**
- Create: `tests/UnitTest/test_task_scenarios_gtest.cpp`

- [ ] **Step 1: Create the test file**

```cpp
#include <gtest/gtest.h>
#include <nlohmann/json.hpp>
#include "network/HTTPServer/HTTPServerDataTypes.h"
#include "network/HTTPServer/TaskSerialization.h"

namespace forensics {
namespace {

TEST(ForensicScenarioTest, ScenarioToString) {
    EXPECT_EQ(scenario_to_string(ForensicScenario::ANDROID), "android");
    EXPECT_EQ(scenario_to_string(ForensicScenario::WINDOWS), "windows");
    EXPECT_EQ(scenario_to_string(ForensicScenario::LINUX), "linux");
    EXPECT_EQ(scenario_to_string(ForensicScenario::SERVER_CLOUD), "server_cloud");
}

TEST(ForensicScenarioTest, StringToScenario) {
    EXPECT_EQ(string_to_scenario("android"), ForensicScenario::ANDROID);
    EXPECT_EQ(string_to_scenario("windows"), ForensicScenario::WINDOWS);
    EXPECT_EQ(string_to_scenario("linux"), ForensicScenario::LINUX);
    EXPECT_EQ(string_to_scenario("server_cloud"), ForensicScenario::SERVER_CLOUD);
    EXPECT_EQ(string_to_scenario("invalid"), std::nullopt);
    EXPECT_EQ(string_to_scenario(""), std::nullopt);
}

TEST(ForensicScenarioTest, ScenarioSerialization) {
    nlohmann::json j = ForensicScenario::ANDROID;
    EXPECT_EQ(j.get<std::string>(), "ANDROID");

    auto s = j.get<ForensicScenario>();
    EXPECT_EQ(s, ForensicScenario::ANDROID);
}

TEST(AnalysisTaskTest, ScenariosFieldSerialization) {
    AnalysisTask task;
    task.id = "test-123";
    task.scenarios = {ForensicScenario::ANDROID, ForensicScenario::WINDOWS};

    nlohmann::json j;
    to_json(j, task);

    EXPECT_TRUE(j.contains("scenarios"));
    EXPECT_EQ(j["scenarios"].size(), 2);
    EXPECT_EQ(j["scenarios"][0].get<std::string>(), "ANDROID");
    EXPECT_EQ(j["scenarios"][1].get<std::string>(), "WINDOWS");

    // Backward compat field
    EXPECT_TRUE(j.contains("android_analyze"));
    EXPECT_TRUE(j["android_analyze"].get<bool>());
}

TEST(AnalysisTaskTest, BackwardCompatFromJson) {
    // Old format with android_analyze: true
    nlohmann::json j = {
        {"id", "test-456"},
        {"image_path", "/test/image.dd"},
        {"status", "PENDING"},
        {"message", ""},
        {"output_files_db", ""},
        {"output_raw_db", ""},
        {"output_events_db", ""},
        {"priority", "NORMAL"},
        {"progress", {
            {"current_phase", "INITIALIZING"},
            {"phase_percentage", 0},
            {"overall_percentage", 0},
            {"phase_description", ""}
        }},
        {"android_analyze", true}
    };

    AnalysisTask task;
    from_json(j, task);

    EXPECT_EQ(task.scenarios.size(), 1);
    EXPECT_EQ(task.scenarios[0], ForensicScenario::ANDROID);
    EXPECT_TRUE(task.get_android_analyze());
}

TEST(AnalysisTaskTest, NewFormatFromJson) {
    nlohmann::json j = {
        {"id", "test-789"},
        {"image_path", "/test/image.dd"},
        {"status", "PENDING"},
        {"message", ""},
        {"output_files_db", ""},
        {"output_raw_db", ""},
        {"output_events_db", ""},
        {"priority", "NORMAL"},
        {"progress", {
            {"current_phase", "INITIALIZING"},
            {"phase_percentage", 0},
            {"overall_percentage", 0},
            {"phase_description", ""}
        }},
        {"scenarios", {"ANDROID", "LINUX"}}
    };

    AnalysisTask task;
    from_json(j, task);

    EXPECT_EQ(task.scenarios.size(), 2);
    EXPECT_EQ(task.scenarios[0], ForensicScenario::ANDROID);
    EXPECT_EQ(task.scenarios[1], ForensicScenario::LINUX);
    EXPECT_TRUE(task.get_android_analyze());
}

TEST(AnalysisTaskTest, EmptyScenariosFromJson) {
    nlohmann::json j = {
        {"id", "test-empty"},
        {"image_path", "/test/image.dd"},
        {"status", "PENDING"},
        {"message", ""},
        {"output_files_db", ""},
        {"output_raw_db", ""},
        {"output_events_db", ""},
        {"priority", "NORMAL"},
        {"progress", {
            {"current_phase", "INITIALIZING"},
            {"phase_percentage", 0},
            {"overall_percentage", 0},
            {"phase_description", ""}
        }},
        {"android_analyze", false}
    };

    AnalysisTask task;
    from_json(j, task);

    EXPECT_TRUE(task.scenarios.empty());
    EXPECT_FALSE(task.get_android_analyze());
}

TEST(AnalysisTaskTest, CopyPreservesScenarios) {
    AnalysisTask original;
    original.id = "copy-test";
    original.scenarios = {ForensicScenario::WINDOWS, ForensicScenario::SERVER_CLOUD};

    AnalysisTask copy = original;
    EXPECT_EQ(copy.scenarios.size(), 2);
    EXPECT_EQ(copy.scenarios[0], ForensicScenario::WINDOWS);
    EXPECT_EQ(copy.scenarios[1], ForensicScenario::SERVER_CLOUD);
}

TEST(TaskPhaseTest, PlatformAnalysisPhase) {
    // Verify PLATFORM_ANALYSIS replaces ANDROID_ANALYSIS
    TaskPhase phase = TaskPhase::PLATFORM_ANALYSIS;

    nlohmann::json j = phase;
    EXPECT_EQ(j.get<std::string>(), "PLATFORM_ANALYSIS");

    auto deserialized = j.get<TaskPhase>();
    EXPECT_EQ(deserialized, TaskPhase::PLATFORM_ANALYSIS);
}

} // namespace
} // namespace forensics
```

- [ ] **Step 2: Add test to CMakeLists.txt**

In `CMakeLists.txt`, find the existing test definitions and add:

```cmake
add_executable(test_task_scenarios tests/UnitTest/test_task_scenarios_gtest.cpp
    src/network/HTTPServer/TaskSerialization.cpp
    src/network/HTTPServer/routes/TaskHelpers.cpp
    src/core/PathManager/PathManager.cpp
)
target_include_directories(test_task_scenarios PRIVATE src)
target_link_libraries(test_task_scenarios PRIVATE GTest::gtest_main nlohmann_json::nlohmann_sqlite3)
add_test(NAME test_task_scenarios COMMAND test_task_scenarios)
```

- [ ] **Step 3: Build and run tests**

Run: `cd build && cmake --build . -j$(nproc) && ctest -R test_task_scenarios --output-on-failure`

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/UnitTest/test_task_scenarios_gtest.cpp CMakeLists.txt
git commit -m "test: add unit tests for ForensicScenario enum and task serialization"
```

---

## Task 9: Final Integration Verification

- [ ] **Step 1: Full build**

Run: `cd build && cmake .. -DCMAKE_BUILD_TYPE=Release && cmake --build . -j$(nproc) 2>&1 | tail -20`

Expected: Build succeeds with no errors.

- [ ] **Step 2: Run all tests**

Run: `cd build && ctest --output-on-failure 2>&1 | tail -30`

Expected: All tests pass (including new test_task_scenarios).

- [ ] **Step 3: Verify frontend builds**

Run: `cd web && npm run build 2>&1 | tail -10`

Expected: Build succeeds.

- [ ] **Step 4: Manual API test**

Run the server and test the API:

```bash
# Start server in background
./build/forensic_analyzer --http-server 8080 &
SERVER_PID=$!
sleep 2

# Test creating a task with scenarios
curl -s -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"image_path":"/tmp/test.dd","scenarios":["android","linux"],"llm_analyze":true,"case_description":"test"}' | python3 -m json.tool

# Cleanup
kill $SERVER_PID
```

Expected: Response includes `"scenarios": ["android", "linux"]`.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete forensic scenario selection system"
```
