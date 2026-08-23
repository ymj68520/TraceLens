# SceneDetector（src/network/HTTPServer/SceneDetector.{h,cpp}）

> **一句话**：平台场景自动探测器——对**未过滤**的 raw.db 跑一组 `path LIKE` 计数查询（Android/Windows/Linux/Server-Cloud 各自的特征路径标记），返回 `SceneDetection{ok, detected, counts, dominant}`，供任务在用户没选场景时回填 `task.scenarios`。

## 1. 为什么有这个模块

提交任务要求用户勾选"取证场景"（android/windows/linux/server_cloud）——但用户经常不知道镜像是什么系统，选错了整条平台分析就跑偏。本模块把这一步自动化：镜像内容自己说话。头文件的设计陈述很完整：让 UI 可以去掉强制多选；检测只读、不改库、不依赖任何过滤画像（SceneDetector.h:8-25）。

## 2. 在系统中的位置

```
TaskManager::start_analysis（HTTP 流水线）
  IMAGE_ANALYSIS 完成后、FileFilter 之前
  └─ if (task.scenarios.empty())                       ← 只在用户未选择时探测
       SceneDetector::detectScenes(rawDbPath)          (TaskManagerAnalysis.cpp:227-259)
         ├─ 命中 ─▶ 回填 task.scenarios + 写 SCENE_DETECTED 审计日志（含各平台命中数）
         ├─ 未命中 ─▶ 审计日志 "No platform markers found; running generic analysis"
         └─ 失败(ok=false) ─▶ 静默跳过，下游按无场景处理
  之后 FileFilter 按 task.filter_profile 产 filtered.db（SceneDetector 必须在此之前）
```

**唯一调用方**是 TaskManagerAnalysis.cpp:236——CLI 流水线（AnalysisOrchestrator）不跑场景探测（CLI 用户用 `--android-analyze` 等显式声明）。这是一条 HTTP-only 的自动化。

## 3. 核心数据结构与接口

### 3.1 SceneDetection：结果结构的逐字段解释（SceneDetector.h:31-49）

```cpp
// SceneDetector.h:31-49
struct SceneDetection {
    /// Number of matching files per scenario (only keys with count > 0 are
    /// guaranteed meaningful, but every enum value is always present).
    std::map<ForensicScenario, int> counts;

    /// Scenarios whose marker count > 0, ordered by count descending. Ties are
    /// broken by a fixed priority order (android > windows > linux >
    /// server_cloud) for deterministic results.
    std::vector<ForensicScenario> detected;

    /// The single scene with the highest marker count (SceneType::NONE if
    /// nothing matched). Drives FileClassifier / LLMAnalysisService scene-aware
    /// scoring, which only consumes one scene at a time.
    SceneType dominant = SceneType::NONE;

    /// false if the raw DB could not be opened or queried; callers should treat
    /// a failed detection as "no scenarios" and leave downstream behavior as-is.
    bool ok = false;
};
```

| 字段 | 谁写 | 谁读 | 语义 |
|---|---|---|---|
| `counts` | detectScenes 逐标记累加（所有枚举键先初始化为 0） | 调用侧审计明细 | 每场景命中文件数；**键集恒等于枚举全集**，调用方遍历 map 不会遇到缺键 |
| `detected` | 排序后写入 | 回填 task.scenarios | count>0 的场景，按计数降序；同数时按 ANDROID>WINDOWS>LINUX>SERVER_CLOUD 固定序——保证同镜像重复探测结果一致 |
| `dominant` | 排头场景 switch 转换 | FileClassifier/LLMAnalysisService（经 task.scenarios 传导后间接消费） | 单场景评分只看一个值；无命中保持 NONE |
| `ok` | 开库/查询结果 | 调用侧分支 | false 时调用方按"无场景"处理（h:46-48），**不会让任务失败** |

注意 `dominant` 的类型是 `SceneType`（FileClassifier.h 的枚举）而其余字段用 `ForensicScenario`（HTTPServerDataTypes.h）——两套场景枚举在本模块完成转换（:134-144）。

### 3.2 接口清单

| 接口 | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `detectScenes(rawDbPath)`（SceneDetector.h:60） | 自由函数（非类成员）；READONLY 开库 → 18 条标记计数 → 排序出结果 | TaskManagerAnalysis.cpp:236（唯一） | 开库失败返回 `ok=false` 的空结果；单条查询失败计 0（safe default） |

模块对外就这一个函数加一个结构体——刻意保持无状态、无类，任何调用者拿到结果后自行决定怎么用。

## 4. 核心概念与设计

### 4.1 标记表：SQL LIKE 模式 ↔ 场景

18 条标记（SceneDetector.cpp:35-61），按场景分组：Android 4 条、Windows 5 条、Linux 4 条、Server-Cloud 5 条：

```cpp
// SceneDetector.cpp:21-33、35-61（节选）
struct Marker {
    ForensicScenario scenario;
    const char* like;  // SQL LIKE pattern
};

// Fixed tie-break priority when two scenarios match equal counts. Lower index =
// higher priority. Keeps results deterministic.
const ForensicScenario PRIORITY_ORDER[] = {
    ForensicScenario::ANDROID,
    ForensicScenario::WINDOWS,
    ForensicScenario::LINUX,
    ForensicScenario::SERVER_CLOUD,
};

const std::vector<Marker> MARKERS = {
    // --- Android: app data, system state, telephony providers ---
    {ForensicScenario::ANDROID, "%/data/data/com.android.%"},
    {ForensicScenario::ANDROID, "%/data/system/%"},
    {ForensicScenario::ANDROID, "%/data/media/%"},
    {ForensicScenario::ANDROID, "%/data/misc/%"},

    // --- Windows: registry hives, prefetch, system dirs ---
    {ForensicScenario::WINDOWS, "%/Windows/System32/config/%"},
    {ForensicScenario::WINDOWS, "%/Windows/Prefetch/%"},
    {ForensicScenario::WINDOWS, "%/Windows/System32/Tasks/%"},
    {ForensicScenario::WINDOWS, "%\\Windows\\System32\\config\\%"},
    {ForensicScenario::WINDOWS, "%\\Windows\\Prefetch\\%"},

    // --- Linux: logs, account files ---
    {ForensicScenario::LINUX, "/var/log/%"},
    {ForensicScenario::LINUX, "%/etc/passwd"},
    {ForensicScenario::LINUX, "%/etc/shadow"},
    {ForensicScenario::LINUX, "%/.bash_history"},

    // --- Server / Cloud: service configs, container/cloud runtimes ---
    {ForensicScenario::SERVER_CLOUD, "%/etc/nginx/%"},
    {ForensicScenario::SERVER_CLOUD, "%/etc/apache2/%"},
    {ForensicScenario::SERVER_CLOUD, "%/etc/httpd/%"},
    {ForensicScenario::SERVER_CLOUD, "%/var/lib/docker/%"},
    {ForensicScenario::SERVER_CLOUD, "%/etc/kubernetes/%"},
};
```

模式设计有三条规则：前导 `%` 吸收分区根/盘符前缀（"/data/data/..." 和 "C:/Users/..." 都能命中）；**Windows 另配反斜杠变体**——hive 里存的路径常是 `C:\Windows\...` 形态，LIKE 对 `\` 与 `/` 不做归一化，只能双份标记覆盖；Linux 的 `/var/log/%` 无前导通配（Linux 路径没有盘符前缀，锚定根更精确、也避免误命中用户目录下的同名路径）。标记选择的注释标准是"**镜像各平台分析器真正会去处理的工件位置**"（:12-15）——命中即强信号"对应分析器有活干"。

### 4.2 计数查询：只读、只数、不判断内容

```cpp
// SceneDetector.cpp:63-82
// Run `SELECT COUNT(*) FROM files WHERE path LIKE ? AND is_deleted=0`.
// Returns 0 on any error (treated as "no match" — safe default).
int countMatches(sqlite3* db, const std::string& likePattern) {
    const char* sql =
        "SELECT COUNT(*) FROM files WHERE path LIKE ? AND is_deleted=0;";
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        if (stmt) sqlite3_finalize(stmt);
        return 0;
    }
    sqlite3_bind_text(stmt, 1, likePattern.c_str(),
                      static_cast<int>(likePattern.size()), SQLITE_TRANSIENT);

    int count = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        count = sqlite3_column_int(stmt, 0);
    }
    sqlite3_finalize(stmt);
    return count;
}
```

一条 SQL 一个标记：模式走 `?` 绑定（LIKE 模式含 `%` 但不含用户输入，绑定主要防模式里的特殊字符被二次解释）；`is_deleted=0` 把已删除文件排除在信号外——活着的系统目录比雕复出来的残骸更能代表镜像的平台；prepare/step 任何异常一律计 0（"safe default"）——探测是尽力而为的增强，任何一步失败都不该升级成任务错误。**没有任何启发式内容解析**（不读文件内容、不看签名）——纯路径形态学，快但也就只认"文件在不在"。

### 4.3 主流程：计数、排序与 tie-break

`detectScenes`（SceneDetector.cpp:86-148）三步：counts 清零 + READONLY 开库（:88-98）；逐标记累加计数（:101-103）；构造 detected、取 dominant、返回（:110-147）。排序段是本模块最精巧的部分：

```cpp
// SceneDetector.cpp:110-131（节选）
std::vector<ForensicScenario> present;
for (auto s : PRIORITY_ORDER) {
    if (result.counts[s] > 0) present.push_back(s);
}
std::stable_sort(present.begin(), present.end(),
                 [&result](ForensicScenario a, ForensicScenario b) {
                     if (result.counts[a] != result.counts[b]) {
                         return result.counts[a] > result.counts[b];
                     }
                     // Tie: respect PRIORITY_ORDER (a comes first if its
                     // index is smaller).
                     auto idxOf = [](ForensicScenario s) {
                         for (size_t i = 0;
                              i < sizeof(PRIORITY_ORDER) / sizeof(PRIORITY_ORDER[0]);
                              ++i) {
                             if (PRIORITY_ORDER[i] == s) return i;
                         }
                         return SIZE_MAX;
                     };
                     return idxOf(a) < idxOf(b);
                 });
result.detected = std::move(present);
```

排序键是二元组（计数降序，优先级序升序）。用 `stable_sort` + "先按 PRIORITY_ORDER 收集再排"是双保险：即使 comparator 只比计数，stable_sort 也会保持同计数元素的初始相对顺序——而初始顺序恰是 PRIORITY_ORDER 的收集顺序。确定性是目的：同一镜像两次探测必须给出同一 detected 序列，否则重启恢复后的任务会跑出不同平台组合。dominant 取排头转 `SceneType`（:134-144 的 switch，四值全覆盖、无 default）。

## 5. 工作流程走读（调用侧回填）

```cpp
// TaskManagerAnalysis.cpp:232-259（场景探测回填块）
if (task.scenarios.empty()) {
    if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
    update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 2,
                    "Detecting platform scenarios from image...");
    SceneDetection detection = detectScenes(rawDbPath);
    if (detection.ok && !detection.detected.empty()) {
        {
            std::lock_guard<std::mutex> lock(mtx_);
            if (tasks_.count(task_id)) {
                tasks_[task_id].scenarios = detection.detected;
                task.scenarios = detection.detected;
            }
        }
        // Record the detection for traceability (which platforms,
        // and how many marker files each matched).
        std::string detail;
        for (size_t i = 0; i < detection.detected.size(); ++i) {
            if (i) detail += ", ";
            detail += scenario_to_string(detection.detected[i]);
            detail += "=" + std::to_string(detection.counts[detection.detected[i]]);
        }
        add_audit_log(task_id, "SCENE_DETECTED",
                      "Auto-detected scenarios: " + detail);
    } else if (detection.ok) {
        add_audit_log(task_id, "SCENE_DETECTED",
                      "No platform markers found; running generic analysis");
    }
}
```

四个细节：探测前有取消检查点（与流水线其他步骤一致的纪律）；回填**同时写两处**——锁内写 `tasks_[task_id]`（供序列化/重启存活）和本地 `task` 副本（本流水线后续步骤直接用，避免再过锁）；**回填的是完整 detected 列表，不只有 dominant**——多平台镜像会同时跑多个场景分析器；审计明细逐平台记 `android=123, linux=7` 这样的计数值，探测结论可追溯。`ok=false` 时什么都不写——静默跳过，下游按无场景处理。

**顺序约束**（:227-231 注释 + SceneDetector.h:53-55 文档）：必须传**未过滤**的 raw.db 且必须跑在 FileFilter 之前——过滤画像丢掉的"系统噪声"恰恰是这些标记路径；对 filtered.db 探测会系统性漏检。

## 6. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| TaskManagerAnalysis | 唯一调用方；探测结果回填 task.scenarios 决定后续平台分析器集合 |
| FileFilter | 顺序约束的对端：检测在前，过滤在后 |
| FileClassifier / LLMAnalysisService | 消费 dominant 场景做场景感知评分（经 task.scenarios 传导） |
| ForensicScenario / SceneType（HTTPServerDataTypes / FileClassifier.h） | 两套场景枚举在此转换（ForensicScenario 四值 ↔ SceneType，:134-144） |
| SQLiteHelper | 无共享代码——本模块自带最小 sqlite 封装（countMatches），不复用 execute_query；因为它是库无关的自由函数，被 TaskManagerAnalysis 而非路由层调用 |

## 7. 注意事项与已知问题

- **路径形态学的天花板**：只认路径不认内容。改名的安卓 data 目录、非标准前缀的 Linux 安装、Windows 盘符大小写/NTFS 交替数据流等都不在覆盖面内；`%/etc/passwd` 这类宽松模式也可能被嵌套目录里的同名文件误命中（计数>0 即算检出）。
- **CLI 路径无探测**：`forensic_analyzer` 单体 CLI 不调用本模块，场景只有显式 flag 一条路；两入口行为有差异。
- **multi-boot/混合镜像**：detected 可多值，下游会跑多组平台分析器（耗时叠加）；dominant 只取计数头名，tie 时按固定优先级而非语义权重。
- **SERVER_CLOUD 与 LINUX 的标记有重叠面**：`/var/lib/docker/%` 在 Linux 服务器镜像常与 `/var/log/%` 同时命中——两个场景都会被点亮，是否符合预期取决于调查定位。
- **性能**：18 条 `LIKE '%…%'` 前导通配查询无法走索引，files 表极大时是全表扫描 ×18；当前在 IMAGE_ANALYSIS 刚结束的关键路径上同步执行（进度条 FILE_CLASSIFICATION 2%）。优化方向是 LIKE 前缀部分建表达式索引，或改读 partitions/files 的目录行而非全表。
- **`%/etc/passwd` 命中用户自建文件**：取证镜像里证据盘任何深度都可能躺着一个 etc/passwd 拷贝，会把 LINUX 场景误点亮——计数明细在审计日志里可查，人工复核成本不高。

## 8. 如何验证与扩展

- **验证**：提交一个不含 scenarios 的任务，查审计日志 `SELECT * FROM audit_logs WHERE action='SCENE_DETECTED'`（任务库/系统审计）看命中明细；再对 filtered.db 手工调 detectScenes 对比计数缩水，直观理解"必须过滤前跑"。
- **扩展新场景/新标记**：在 MARKERS（SceneDetector.cpp:35-61）加 `{场景, LIKE 模式}` 一行即可，计数、排序、审计全部自动跟进；新增**场景枚举**则要动 ForensicScenario、PRIORITY_ORDER、dominant 的 switch（:134-144）以及下游分析器注册——成本主要在枚举联动，不在本模块。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
