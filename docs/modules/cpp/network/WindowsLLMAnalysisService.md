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

## 3. 核心概念与设计

### 3.1 工件类型分组

AnalysisOptions 的开关不是一一对应类型，而是语义分组（WindowsLLMAnalysisService.h:52-62）：

- `includeBrowser` 一次触发 **4** 个子类型（history/downloads/bookmarks/logins），核心循环里连调四次 analyzeArtifactType（WindowsLLMAnalysisService.cpp:93-109）；
- `includeSystem` 覆盖 services/scheduled_tasks/Amcache/SRUM（:111-127）；
- **`includeMFT` 默认 false**——MFT 条目动辄十万行，默认排除是刻意的成本控制（h:61 注释 "can be very large"）。

### 3.2 表映射

`getTableNameForType`（WindowsLLMAnalysisService_Database.cpp:104-122）：REGISTRY→`registry_values`、EVENT_LOG→`event_logs`、PREFETCH→`prefetch_files`、LNK→`lnk_files`、JUMP_LIST→`jump_list_entries`、BROWSER_*→`browser_history/browser_downloads/browser_bookmarks/browser_logins`、MFT_ENTRY→`mft_entries`、WINDOWS_SERVICE→`windows_services`、SCHEDULED_TASK→`scheduled_tasks`、AMCACHE→`amcache_entries`、SRUM→`srum_entries`。SELECT 语句来自 `windows_analysis_sql.h` 的 PENDING_ANALYSIS 系列（同样只取未分析行，天然增量）。

### 3.3 与 Linux 版共用的三个设计决定

1. **记录即 JSON**：任意表行动态拼 JSON 进 prompt（Database.cpp 的 getArtifactsFromDatabase 与 Linux 版同构）；
2. **通用回写**：一套 `UPDATE <表> SET llm_*` 走天下（Database.cpp:16-58）；
3. **文件三层拆分**：核心循环 / prompt（_ArtifactAnalyzers）/ SQL 映射（_Database）。

## 4. 工作流程走读

`analyzeWindowsArtifacts`（WindowsLLMAnalysisService.cpp:43-146）：initialize（文本模型 ModelRouter，:18-41）→ 按 include 分组循环调 `analyzeArtifactType`（:63-143）→ 每类型开库、取未分析行（上限默认 1000/类）、逐条"进度回调 → 类型路由到 prompt 函数 → chat → 解析 → 成功才 UPDATE"（:149-244 段，与 Linux 版逐行同构）。

浏览器组值得一看：一次开关带来四次全流程（cpp:93-109），浏览器痕迹重的镜像里这四张表往往是证据密度最高的，属于合理的预算倾斜。

## 5. 与其他模块的协作

- **WindowsFilesAnalyzer**：唯一调用方（提取→注解一条龙）。
- **WindowsAnalysisSQL**：PENDING_ANALYSIS 查询定义处。
- **TaskManager**：间接上游（PLATFORM_ANALYSIS 进度）。
- **前端 Windows 相关视图 / 报告**：消费 llm_* 列。
- **Linux/Android 同族**：同骨架的平台变体。

## 6. 注意事项与已知问题

- **不受 llm_analyze 门控**：无 LLM 后端时跑 Windows 场景仍会逐条尝试调用（超时兜底但拖慢阶段），与 Linux 版一致。
- **MFT 默认关闭**：需要时间线佐证 MFT 行为时记得显式开 includeMFT，并接受耗时与费用。
- **逐条同步、无重试**：模型输出不合 JSON 即丢弃该条（与 Linux 版相同）。
- **注册表量级风险**：registry_values 若提取了几十万行，1000/类的截断意味着覆盖不全——截断顺序由 SELECT 决定，先到先得。

## 7. 如何验证与扩展

- **验证**：跑含 windows 场景的任务后查 `_windows.db`：`SELECT path, llm_summary FROM prefetch_files WHERE llm_analyzed_at > 0 LIMIT 10`；确认 browser_history/browser_downloads 等四表都有注解（分组开关生效）。
- **扩展新工件类型**：与 Linux 版步骤一致——WindowsFilesAnalyzer 建表填充 → windows_analysis_sql.h 加 PENDING 查询 → _Database.cpp 两映射函数加 case → _ArtifactAnalyzers.cpp 加 prompt 函数并在 analyzeArtifactType 的 switch 注册（如需默认执行再加分组和循环调用）。

**最后更新**: 2026-08-23（解释式重写）
