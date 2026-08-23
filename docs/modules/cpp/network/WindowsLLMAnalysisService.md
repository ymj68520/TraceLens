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

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
