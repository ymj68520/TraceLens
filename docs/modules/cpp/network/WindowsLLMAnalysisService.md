# WindowsLLMAnalysisService（src/network/HTTPServer/WindowsLLMAnalysisService{,_ArtifactAnalyzers,_Database}.cpp）

> **一句话**：LinuxLLMAnalysisService 的 Windows 镜像版——在 PLATFORM_ANALYSIS 阶段遍历 _windows.db 的 14 类 Windows 工件表（注册表、事件日志、预取、LNK、跳转列表、浏览器四件套、服务、计划任务、Amcache、SRUM），逐条生成 LLM 注解写回 llm_* 列。

## 1. 为什么有这个模块

Windows 取证的核心证据几乎都是结构化工件：注册表值、事件日志条目、Prefetch、LNK/JumpList、Amcache/SRUM……它们由 WindowsFilesAnalyzer 提取进 `_windows.db` 的专属表，但"原始行 → 调查员可读的解读"这一步仍缺。本模块补上它：与 Linux 版同一骨架，只换工件类型与 prompt（骨架说明请读 LinuxLLMAnalysisService.md，本文只讲 Windows 特有之处）。

同族：LinuxLLMAnalysisService、AndroidLLMAnalysisService（后者无独立文档，调用点 AndroidAnalyzerCore.cpp:302）。

## 2. 在系统中的位置

```
TaskManager::start_analysis PLATFORM_ANALYSIS 阶段 (TaskManagerAnalysis.cpp:470-485)
    └─ scenario=WINDOWS ──▶ WindowsFilesAnalyzer::analyzeWindowsData()
                                └─ 末尾调用 (WindowsFilesAnalyzerCore.cpp:167)
                                      WindowsLLMAnalysisService::analyzeWindowsArtifacts(_windows.db)
```

与 Linux 版一致：TaskManager 不直接调用，平台分析器提取完工件后立即接续注解；同样**不受任务级 llm_analyze 开关控制**（头文件同样标注 MANDATORY，WindowsLLMAnalysisService.h:23-25）。

## 3. 核心数据结构

### 3.1 ArtifactType 与 AnalysisOptions（WindowsLLMAnalysisService.h:31-62）

```cpp
// src/network/HTTPServer/WindowsLLMAnalysisService.h:31-47、52-62（节选）
enum class ArtifactType {
    REGISTRY, EVENT_LOG, PREFETCH, LNK, JUMP_LIST,
    BROWSER_HISTORY, BROWSER_DOWNLOAD, BROWSER_BOOKMARK, BROWSER_LOGIN,
    MFT_ENTRY, WINDOWS_SERVICE, SCHEDULED_TASK, AMCACHE, SRUM,
    ALL
};

struct AnalysisOptions {
    size_t maxArtifacts = 1000;         // Maximum artifacts per type to analyze
    bool includeRegistry = true;        // Analyze registry values
    bool includeEventLogs = true;       // Analyze event logs
    bool includePrefetch = true;        // Analyze prefetch files
    bool includeLnk = true;             // Analyze LNK files
    bool includeJumpLists = true;       // Analyze jump lists
    bool includeBrowser = true;         // Analyze browser artifacts
    bool includeSystem = true;          // Analyze services/tasks/Amcache/SRUM
    bool includeMFT = false;            // Analyze MFT entries (can be very large)
};
```

与 Linux 版的关键差异全在这个 struct：**类型枚举没有增强类型**（14 个实类型 + ALL，一一对应真实表，不像 Linux 有 16 个半接入的增强项）；**includeMFT 默认 false**——MFT 条目动辄十万行，默认排除是刻意的成本控制（h:61 注释 "can be very large"）。ArtifactRecord/AnalysisResult/ProgressCallback（void 回调、无取消）与 Linux 版逐字相同。

### 3.2 工件类型分组

AnalysisOptions 的开关不是一一对应类型，而是语义分组：

- `includeBrowser` 一次触发 **4** 个子类型（history/downloads/bookmarks/logins）；
- `includeSystem` 覆盖 services/scheduled_tasks/Amcache/SRUM 四个；
- 其余开关与类型一一对应（registry/event_logs/prefetch/lnk/jump_list）。

### 3.3 表映射（_Database.cpp:104-122）

```cpp
// src/network/HTTPServer/WindowsLLMAnalysisService_Database.cpp:104-122
std::string WindowsLLMAnalysisService::getTableNameForType(ArtifactType type) {
    switch (type) {
        case ArtifactType::REGISTRY: return "registry_values";
        case ArtifactType::EVENT_LOG: return "event_logs";
        case ArtifactType::PREFETCH: return "prefetch_files";
        case ArtifactType::LNK: return "lnk_files";
        case ArtifactType::JUMP_LIST: return "jump_list_entries";
        case ArtifactType::BROWSER_HISTORY: return "browser_history";
        case ArtifactType::BROWSER_DOWNLOAD: return "browser_downloads";
        case ArtifactType::BROWSER_BOOKMARK: return "browser_bookmarks";
        case ArtifactType::BROWSER_LOGIN: return "browser_logins";
        case ArtifactType::MFT_ENTRY: return "mft_entries";
        case ArtifactType::WINDOWS_SERVICE: return "windows_services";
        case ArtifactType::SCHEDULED_TASK: return "scheduled_tasks";
        case ArtifactType::AMCACHE: return "amcache_entries";
        case ArtifactType::SRUM: return "srum_entries";
        default: return "";
    }
}
```

注意表名**不带 windows_ 前缀**（`registry_values` 而非 `windows_registry_values`）——它们住在独立的 `_windows.db` 里，靠库隔离而非表名前缀。SELECT 语句来自 `windows_analysis_sql.h` 的 PENDING_ANALYSIS 系列（`getSelectSQLForType`，_Database.cpp:124-142），同样 `WHERE llm_analyzed_at IS NULL` 只取未分析行、天然增量。

## 4. 核心接口清单

| 方法（真实签名） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `bool initialize()` | 惰性建文本模型 ModelRouter（:18-41，与 Linux 版同构） | 所有方法首行 | 异常返回 false → 0 |
| `int analyzeWindowsArtifacts(windowsDbPath, options, cb)` | 按 9 个 include 分组调度（MFT 需显式开） | WindowsFilesAnalyzerCore.cpp:167（唯一） | LLM 不可用逐条失败、静默返回 0 |
| `int analyzeArtifactType(windowsDbPath, type, maxArtifacts, cb)` | 单类型全流程（:139-244，与 Linux 版逐行同构） | 上者 / 可直接调用 | 单条异常打印继续 |
| `storeArtifactAnalysis / getArtifactsFromDatabase / getTableNameForType / getSelectSQLForType`（private，_Database.cpp） | 与 Linux 版同构（通用 UPDATE + 记录即 JSON + 两映射） | 内部 | 同 Linux 版 |

## 5. 工作流程走读

`analyzeWindowsArtifacts`（WindowsLLMAnalysisService.cpp:43-146）：initialize（文本模型 ModelRouter，:18-41）→ 按 include 分组循环调 `analyzeArtifactType`（:63-143）→ 每类型开库、取未分析行（上限默认 1000/类）、逐条"进度回调 → 类型路由到 prompt 函数 → chat → 解析 → 成功才 UPDATE"（:149-244 段，与 Linux 版逐行同构）。

分组展开的代码面貌（浏览器组）：

```cpp
// src/network/HTTPServer/WindowsLLMAnalysisService.cpp:93-109
if (options.includeBrowser) {
    int count = analyzeArtifactType(windowsDbPath, ArtifactType::BROWSER_HISTORY,
                                     options.maxArtifacts, progressCallback);
    totalAnalyzed += count;

    count = analyzeArtifactType(windowsDbPath, ArtifactType::BROWSER_DOWNLOAD,
                                options.maxArtifacts, progressCallback);
    totalAnalyzed += count;

    count = analyzeArtifactType(windowsDbPath, ArtifactType::BROWSER_BOOKMARK,
                                options.maxArtifacts, progressCallback);
    totalAnalyzed += count;

    count = analyzeArtifactType(windowsDbPath, ArtifactType::BROWSER_LOGIN,
                                options.maxArtifacts, progressCallback);
    totalAnalyzed += count;
}
```

一次开关带来四次全流程，浏览器痕迹重的镜像里这四张表往往是证据密度最高的，属于合理的预算倾斜。includeSystem 组（:111-127）同构展开为 services/scheduled_tasks/amcache/srum 四连调。

prompt 函数示例（注册表，_ArtifactAnalyzers.cpp:21-36）：

```cpp
// src/network/HTTPServer/WindowsLLMAnalysisService_ArtifactAnalyzers.cpp:21-36（节选）
std::string prompt = R"(You are a digital forensics expert analyzing Windows registry artifacts.

Analyze this registry entry and provide:
1. Summary: Brief one-line description of what this registry value does
2. Description: Detailed explanation of its forensic significance
3. Keywords: 3-5 relevant keywords for search and categorization

Registry Entry:
)" + data.dump() + R"(

Respond in JSON format:
{
  "summary": "brief description",
  "description": "detailed forensic analysis",
  "keywords": ["keyword1", "keyword2", "keyword3"]
})";
```

与 Linux 版同款四段式骨架（角色 + 三项要求 + 工件 JSON + 输出模板），仅角色句与工件标签不同；解析同样是 `json::parse(response.content)` 裸解析，模型多吐一个字即整条作废。

### 与 Linux 版共用的三个设计决定

1. **记录即 JSON**：任意表行动态拼 JSON 进 prompt（_Database.cpp 的 getArtifactsFromDatabase 与 Linux 版同构）；
2. **通用回写**：一套 `UPDATE <表> SET llm_*` 走天下（_Database.cpp:16-58）；
3. **文件三层拆分**：核心循环 / prompt（_ArtifactAnalyzers）/ SQL 映射（_Database）。

## 6. 与其他模块的协作

- **WindowsFilesAnalyzer**：唯一调用方（提取→注解一条龙）。
- **WindowsAnalysisSQL**：PENDING_ANALYSIS 查询定义处。
- **TaskManager**：间接上游（PLATFORM_ANALYSIS 进度）。
- **前端 Windows 相关视图 / 报告**：消费 llm_* 列。
- **Linux/Android 同族**：同骨架的平台变体。

## 7. 注意事项与已知问题

- **不受 llm_analyze 门控**：无 LLM 后端时跑 Windows 场景仍会逐条尝试调用（超时兜底但拖慢阶段），与 Linux 版一致。
- **MFT 默认关闭**：需要时间线佐证 MFT 行为时记得显式开 includeMFT，并接受耗时与费用。
- **逐条同步、无重试**：模型输出不合 JSON 即丢弃该条（与 Linux 版相同，裸解析无容错截取）。
- **注册表量级风险**：registry_values 若提取了几十万行，1000/类的截断意味着覆盖不全——截断顺序由 SELECT 的 ORDER BY 决定，先到先得。
- **无取消通道**：void 进度回调，任务取消不能中断逐条循环（与 Linux 版同款限制）。

## 8. 如何验证与扩展

- **验证**：跑含 windows 场景的任务后查 `_windows.db`：`SELECT path, llm_summary FROM prefetch_files WHERE llm_analyzed_at > 0 LIMIT 10`；确认 browser_history/browser_downloads 等四表都有注解（分组开关生效）；重跑同库确认 PENDING 增量。
- **扩展新工件类型**：与 Linux 版步骤一致——WindowsFilesAnalyzer 建表填充 → windows_analysis_sql.h 加 PENDING 查询 → _Database.cpp 两映射函数加 case → _ArtifactAnalyzers.cpp 加 prompt 函数并在 analyzeArtifactType 的 switch 注册（如需默认执行再加分组和循环调用）。

## 9. 14 表的 SELECT 列契约（二轮补全）

windows_analysis_sql_llm.h:60-100 的 PENDING 查询决定**进 prompt 的 JSON 字段**（id 之外的列全部动态拼进 artifactJson，_Database.cpp:87-96）。完整清单：

| ArtifactType | 表 | 进 prompt 的列（id 之后） | 源码 |
|---|---|---|---|
| REGISTRY | registry_values | hive_path, key_path, value_name, value_data | :60-61 |
| EVENT_LOG | event_logs | record_id, event_id, level, source, message | :63-64 |
| PREFETCH | prefetch_files | file_path, executable_name, executable_path, run_count | :66-67 |
| LNK | lnk_files | lnk_path, target_path, working_directory, arguments | :69-70 |
| JUMP_LIST | jump_list_entries | app_id, entry_path, entry_name, access_count | :72-73 |
| BROWSER_HISTORY | browser_history | browser_name, url, title, visit_count | :75-76 |
| BROWSER_DOWNLOAD | browser_downloads | browser_name, url, file_name, file_size | :78-79 |
| BROWSER_BOOKMARK | browser_bookmarks | browser_name, url, title, folder_path | :81-82 |
| BROWSER_LOGIN | browser_logins | browser_name, url, username | :84-85 |
| MFT_ENTRY | mft_entries | file_path, file_name, is_directory, is_deleted | :87-88 |
| WINDOWS_SERVICE | windows_services | service_name, display_name, image_path, start_type | :90-91 |
| SCHEDULED_TASK | scheduled_tasks | task_name, task_path, action_type, action_path | :93-94 |
| AMCACHE | amcache_entries | file_path, file_name, company_name, product_name | :96-97 |
| SRUM | srum_entries | app_name, user_name, timestamp, bytes_received | :99-100 |

所有查询统一形态：`WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?`——**按 id 升序取未分析行**，截断即"最早的 N 条先分析"（§7 已记覆盖不全问题，这里补上截断顺序的确切答案）。数值列（run_count/file_size 等）经 `sqlite3_column_text` 统一转文本进 JSON——prompt 里没有类型区分，模型看到的全是字符串。

**列名即 JSON 键**：`artifactJson[colName] = colValue`（_Database.cpp:93）用的是 prepare 出来的列名，prompt 里的工件 JSON 键与库列名严格一致——改列名会直接改变模型看到的字段名。

## 10. 新发现的三处死代码（二轮核验）

1. **14 条 `UPDATE_*_LLM_ANALYSIS` 常量从未被使用**（windows_analysis_sql_llm.h:14-54）。实际回写走 storeArtifactAnalysis 内的**字符串拼接通用 UPDATE**（_Database.cpp:35-37：`"UPDATE " + tableName + " SET llm_summary=?... WHERE id=?"`）——语义与常量等价（同样的五列六参），但常量版本是历史遗留。grep 全仓无引用。
2. **`windows_analysis_progress` 进度表 SQL 三连（INSERT/UPDATE/COMPLETE）零调用方**（:126-134）。进度跟踪本可落库（表名都设计好了），实际只有内存里的 totalAnalyzed 计数。
3. **`getUpdateSQLForType` 声明无定义**（WindowsLLMAnalysisService.h:164 声明，无任何 cpp 定义也无调用）——头文件死声明，链接期不炸只因无人调用。

同族对照：DLL 专属的 `UPDATE_DLL_LLM_ANALYSIS`/`SELECT_DLL_PENDING_ANALYSIS`（:106-120，threat_score 过滤）属于 DLL 分析路径（dll_base_info 表），不经本模块的 14 类型路由——它们由 DLLAnalyzer 系消费。

## 11. prompt 路由的真实收敛：14 类型 → 8 个 prompt 函数

analyzeArtifactType 的 switch（WindowsLLMAnalysisService.cpp:175-208）把 14 类型收敛到 8 个分析函数：

| prompt 函数 | 覆盖的类型 | 共享后果 |
|---|---|---|
| analyzeRegistryArtifact | REGISTRY | — |
| analyzeEventLogArtifact | EVENT_LOG | — |
| analyzePrefetchArtifact | PREFETCH | — |
| analyzeLnkArtifact | LNK | — |
| analyzeJumpListArtifact | JUMP_LIST | — |
| analyzeBrowserArtifact | BROWSER_HISTORY/DOWNLOAD/BOOKMARK/LOGIN（4 类） | 四类共用"浏览器痕迹"prompt，角色句不区分是历史还是登录——浏览器登录凭证（username）与访问记录拿到相同的分析视角 |
| analyzeSystemArtifact | WINDOWS_SERVICE/SCHEDULED_TASK/AMCACHE/SRUM（4 类） | 四类共用"系统工件"prompt |
| analyzeMftArtifact | MFT_ENTRY | — |

default 分支 `continue`（:206-207）——ALL 与未知类型静默跳过；ALL 枚举值实际不可经 analyzeArtifactType 使用（没有遍历逻辑）。

## 12. 与 LLMAnalysisService 的回写语义差异

两处值得注意的对比（此前未记录）：

- **storeArtifactAnalysis 的返回值被消费**（WindowsLLMAnalysisService.cpp:210-216）：UPDATE 失败不计入 analyzed——与 LLMAnalysisService 文件级循环" analyzed++ 不看写库结果"相反，本模块的计数语义是"成功落库数"。
- **UPDATE 以 id 为键**（_Database.cpp:37）而非 path——行级主键，没有 LLMAnalysisService 的"唯一路径守卫"问题，也没有跨表双写（不维护 file_descriptions 对应物）。平台工件的注解不进调查中心证据列表，只在 `_windows.db` 的 llm_* 列里。

## 13. 配置影响表（全集）

| 配置 | 默认 | 消费链 | 说明 |
|---|---|---|---|
| `LLM_TEXT_*` 五项 | 见 Environment.md | initialize() → ModelRouter 文本模型 | 每条工件的模型调用 |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | 120 / 3 | LLMClient | 无 LLM 后端时每条工件超时等待，14 表 × 1000 条上限的最坏情况极慢（§7 已记） |
| （无 maxArtifacts 的 env） | 1000 硬编码 | AnalysisOptions 默认值（h:53） | 调用方 WindowsFilesAnalyzerCore.cpp:167 不传 options，改预算只能改代码 |
| （无 include* 的 env） | 见 §3.1 | 同上 | includeMFT=true 也只能改代码 |
| `THREAD_POOL_SIZE` | 4 | 不影响本模块 | 逐条串行，无内部并发 |

## 14. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 | 说明 |
|---|---|---|---|
| 被调 | WindowsFilesAnalyzerCore.cpp:167 | 唯一调用点 | 提取→注解一条龙；不传 options（全默认） |
| 依赖 | llm::ModelRouter | initialize() | 文本模型 |
| 读写 | `_windows.db` 14 张工件表 | SELECT pending / UPDATE llm_* by id | 列契约见 §9 |
| SQL 来源 | windows_analysis_sql_llm.h（SELECT）+ 字符串拼接（UPDATE） | :60-100 / _Database.cpp:35 | UPDATE 常量族是死代码（§10） |
| 同族 | Linux/AndroidLLMAnalysisService | 同骨架 | prompt 收敛度不同（本模块 8 函数） |
| 间接上游 | TaskManager PLATFORM_ANALYSIS | 进度 80-95% 区间 | void 回调无取消 |
| 读出方 | 前端 Windows 视图/报告 | llm_* 列 | DLL 表除外（另一路径） |

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
