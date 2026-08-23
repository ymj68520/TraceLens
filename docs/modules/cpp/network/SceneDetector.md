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

## 9. 消费侧端点契约：scene-stats / scene-artifacts（二轮补全）

探测结果回填 `task.scenarios` 后，场景相关数据有两个查询出口——SceneQueryRoutes 注册的 `/api/tasks/{id}/scene-stats` 与 `/api/tasks/{id}/scene-artifacts`（SceneQueryRoutes.cpp:10-24）。它们不是 SceneDetector 的一部分，但共享"场景"数据模型，是探测结论在 REST 层的最终呈现。

### 9.1 GET /api/tasks/{id}/scene-stats（SceneQueryRoutes.cpp:26-134）

无查询参数。响应字段（:121-124）：

| 键 | 来源 | 说明 |
|---|---|---|
| `task_id` | 路径参数回显 | |
| `scene_stats[]` | files 表按 scene_type 分组（:52-61） | 每项 `{scene_type, total_files, relevant_files, total_size, llm_analyzed_files}`；只含 scene_type 非 NULL 的行 |
| `artifact_stats[]` | android/windows/linux_artifacts 三表 UNION ALL（:87-104） | 每项 `{scene_type, artifact_count, analyzed_count}`；**无 server_cloud**——oss.db 不在此查询里；三表任一不存在时整体为空数组（prepare 失败静默跳过，:117 注释） |

两个边界：文件库打不开返回 500 `{"error": "Failed to open database: ..."}`（:42-47）；artifact SQL 的 UNION 只列三表，SERVER_CLOUD 场景的任务在此端点看不到工件统计。

### 9.2 GET /api/tasks/{id}/scene-artifacts?scene_type=&limit=&offset=（SceneQueryRoutes.cpp:136-298）

| 参数 | 默认 | 校验 |
|---|---|---|
| `scene_type` | 无（必填） | **白名单三选一：android/windows/linux**（:161-166）——server_cloud 不被接受，传了返回 400 "Invalid scene_type"；白名单同时是 SQL 注入防线（表名拼接前已验证，:180-181 注释） |
| `limit` | 100 | `std::stoi` 直转，**非数字会抛异常落进 500**（:150，无 try 包裹 stoi 本身） |
| `offset` | 0 | 同上 |

响应：`{task_id, scene_type, artifacts[], total, limit, offset}`。artifacts 每项 13 字段（:233-263）：`id, file_id, artifact_type, artifact_data, extracted_at, llm_summary, llm_description, llm_keywords, llm_analyzed_at, llm_model_used, file_name, file_path, file_size`——后三字段来自 LEFT JOIN files（:212），file_id 悬空时为空串。表不存在时**不报错**，返回空 artifacts + total=0（:194-206），这让"场景没跑对应分析器"与"跑过但零工件"在响应上不可区分，前端只能靠空数组渲染。

### 9.3 两个端点与 detectScenes 的数据链

detectScenes 只写 task.scenarios（内存+tasks.json），**不写任何库**；scene-stats 读的 `files.scene_type` 列由 FileClassifier 按路径分类写入（FileClassifier.cpp:263-270），`*_artifacts` 表由各平台分析器写入——即两个端点反映的是"下游分析器的产出"，与探测命中数没有直接等式关系（探测命中 1000 个 android 路径 ≠ android_artifacts 有 1000 行）。排障"探测说有、统计说无"时按这条链查：scenarios（探测）→ FileClassifier/平台分析器（写入）→ 端点（读出）。

## 10. 场景枚举双轨映射表

本模块是两套场景枚举的转换点，完整对照（SceneDetector.cpp:134-144 的 switch + FileClassifier.h:46-52 + HTTPServerDataTypes.h）：

| ForensicScenario（任务/请求层） | SceneType（分类/评分层） | 场景串（REST/JSON 层，scenario_to_string） | 写入库的 scene_type 值 |
|---|---|---|---|
| ANDROID | SceneType::ANDROID | "android" | "android" |
| WINDOWS | SceneType::WINDOWS | "windows" | "windows" |
| LINUX | SceneType::LINUX | "linux" | "linux" |
| SERVER_CLOUD | SceneType::SERVER_CLOUD | "server_cloud" | "server_cloud" |
| —（无对应） | SceneType::NONE | —（不出现在 detected） | NULL（files 行无场景） |

NONE 只存在于 SceneType 一侧——探测无命中时 dominant 保持 NONE、scenarios 保持空，"无场景"在任务层用空列表表达、在文件层用 NULL 表达，两层语义对齐靠这份映射维持。

## 11. 性能量化与关联矩阵补充

- **18 次 COUNT 的成本结构**：每次 countMatches 是独立 prepare/step/finalize（SceneDetector.cpp:65-82），18 条模式 = 18 次语句编译 + 18 次扫描。前导 `%` 模式无法用 B-tree 索引，files 表 N 行时最坏 18N 行扫描；10M 文件级的 raw.db 在机械盘上可到分钟级——这段同步跑在流水线关键路径（FILE_CLASSIFICATION 2%），是"进度条卡在 2%"的可疑点之一。缓解手段（当前未做）：合并为一条 `CASE WHEN` 聚合 SQL（一次扫描 18 个模式）、或对 `substr(path, -30)` 之类的模式尾部建表达式索引。
- **开库模式**：`SQLITE_OPEN_READONLY`（:94）无 busy_timeout 设置——若分析线程正在写 raw.db 且未开 WAL，探测的读会立刻 SQLITE_BUSY，表现为所有计数 0（countMatches 返回 0）但 `ok=true` 的**假阴性**。实际上 raw.db 在 IMAGE_ANALYSIS 结束后已无写者，此风险仅在流程被改动时需要警惕。

**关联矩阵补充**（对 §6 的展开）：

| 方向 | 对象 | 交互内容 |
|---|---|---|
| 被调 | TaskManagerAnalysis.cpp:236 | 唯一调用点；结果回填+审计 |
| 数据源 | `<image>_raw.db` 的 files 表 | 18 条 LIKE COUNT，只读 |
| 间接下游 | FileClassifier（scene_type/scene_priority/scene_relevant 列） | dominant 场景驱动场景感知评分 |
| 间接下游 | 各平台分析器（android/windows/linux/oss） | detected 列表决定哪些分析器运行 |
| 间接下游 | SceneQueryRoutes 两端点 | 场景数据的 REST 出口（§9） |
| 无关 | SQLiteHelper | 不复用（自带 countMatches）；不复用 RouteHelpers |

## 12. 18 标记的命中语义逐条注释（二轮补全）

每个 LIKE 模式对应的"镜像里有什么"与误命中面（模式语义来自 SceneDetector.cpp:35-61 的分组注释）：

| 标记 | 镜像特征 | 误命中面 |
|---|---|---|
| %/data/data/com.android.% | Android 应用私有数据（包名 com.android.* 系系统应用） | 无——com.android. 前缀很特定 |
| %/data/system/% | 系统状态（设置、锁屏、包管理） | 无 |
| %/data/media/% | 用户媒体（/sdcard 挂载点真身） | 无 |
| %/data/misc/% | 杂项系统数据（WiFi、VPN、keystore） | 无 |
| %/Windows/System32/config/% | 注册表 hive（SOFTWARE/SYSTEM/SAM） | 大小写变体 WinDows 不命中（LIKE 默认对 ASCII 大小写敏感） |
| %/Windows/Prefetch/% | 预取文件（程序执行痕迹） | 同上 |
| %/Windows/System32/Tasks/% | 计划任务文件 | 同上 |
| %\Windows\System32\config\%（反斜杠） | 同 43 行但覆盖 hive 内存反斜杠路径 | 仅 Windows 侧 |
| %\Windows\Prefetch\% | 同 44 行 | 同上 |
| /var/log/%（**无前导 %**） | Linux 日志（锚定根） | 用户目录下嵌 /var/log/ 副本不命中（锚定的收益） |
| %/etc/passwd | 账户文件 | 证据盘任意深度的 passwd 拷贝都点亮（§7 已记） |
| %/etc/shadow | 口令哈希 | 同上 |
| %/.bash_history | shell 历史 | 同上（任何用户的） |
| %/etc/nginx/% | Nginx 配置 | 无 |
| %/etc/apache2/% | Debian 系 Apache | 无 |
| %/etc/httpd/% | RHEL 系 Apache | 无 |
| %/var/lib/docker/% | Docker 运行时数据 | 与 LINUX 的 /var/log/% 常同时命中（§7） |
| %/etc/kubernetes/% | K8s 配置 | 无 |

**LIKE 大小写语义**：SQLite 的 LIKE 对 ASCII 默认大小写不敏感！——上表"大小写变体不命中"的直觉是**错的**：`%/Windows/%` 同样命中 `windows/system32`（SQLite 文档：LIKE is case-insensitive for ASCII）。修正前面的判断：Windows 五条标记无需大小写双份覆盖，反斜杠变体才是真正的第二份存在理由。这一条同时影响 §7 的"误命中面"评估——`windoWs/prefetch` 也能命中。

## 13. 与 FileClassifier 场景评分的衔接（数据链下半段）

dominant SceneType 传导到 FileClassifier 后的具体用途（FileClassifier.cpp:263-270 的三处消费）：

| 消费点 | 列 | 语义 |
|---|---|---|
| calculateScenePriority(path, name, category) | scene_priority | 场景内工件的优先分（ScenePriority::CRITICAL=100 等常量，FileClassifier.h:55+） |
| isSceneRelevant(path, name) | scene_relevant | 是否场景相关（scene-stats 端点的 relevant_files 计数来源） |
| getSceneTypeName(sceneType_) | scene_type | 小写场景串写进 files 表 |

即探测命中 → 场景列表 → dominant 单值 → FileClassifier 按它给每个文件打 scene_* 三列 → scene-stats 端点按 scene_type 分组统计——一条从"路径形态学"到"REST 统计"的完整数据链。中间任何一环断（scenarios 空、分类器没跑、表缺列）都表现为端点计数为 0。

## 14. 验证 runbook（可直接执行的命令序列）

```bash
# 1. 建一个无 scenarios 的任务（触发自动探测）
curl -s -X POST :8080/api/tasks -d '{"image_path":"/evidence/linux.dd"}' | jq .id
# 2. 等任务过 FILE_CLASSIFICATION 2% 后查审计
sqlite3 data/forensics_audit.db "SELECT action, details FROM audit_logs \
  WHERE action='SCENE_DETECTED' ORDER BY timestamp DESC LIMIT 3"
#    期望：Auto-detected scenarios: linux=N（N=四个 LINUX 标记命中数之和）
# 3. 任务完成后核对 files 表的场景列
sqlite3 data/tasks/<id>/*_files.db "SELECT scene_type, COUNT(*) FROM files \
  WHERE scene_type IS NOT NULL GROUP BY scene_type"
# 4. scene-stats 端点对照
curl -s ":8080/api/tasks/<id>/scene-stats" | jq .scene_stats
# 5. 单独验证某个标记的命中数（手工复算 countMatches）
sqlite3 data/tasks/<id>/*_raw.db "SELECT COUNT(*) FROM files \
  WHERE path LIKE '%/etc/passwd' AND is_deleted=0"
```

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
