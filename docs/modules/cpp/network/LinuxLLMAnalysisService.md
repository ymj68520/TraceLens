# LinuxLLMAnalysisService（src/network/HTTPServer/LinuxLLMAnalysisService{,_ArtifactAnalyzers,_SystemAnalyzers,_Database}.cpp）

> **一句话**：Linux 工件级 LLM 批量分析器——遍历 _linux.db 里 14 类系统工件表（日志、账户、登录、shell 历史、cron、SSH、包、网络、systemd……），逐条生成摘要/描述/关键词并写回各表的 llm_* 列，在 PLATFORM_ANALYSIS 阶段由 LinuxFilesAnalyzer 收尾调用。

## 1. 为什么有这个模块

文件级描述（LLMAnalysisService）覆盖的是"普通文件"；而 Linux 取证的证据主力是**结构化工件**：/etc/passwd 解析出的账户行、auth.log 的登录记录、crontab、SSH known_hosts……这些已经躺在 _linux.db 的专属表里，逐条人工解读费时费力。本模块把"每行工件 → 三段式 AI 注解（summary/description/keywords）"做成流水线，让 `/linux` 结果页与调查报告直接呈现语义化的工件解读。

同族兄弟：**WindowsLLMAnalysisService**（注册表/预取文件等）与 **AndroidLLMAnalysisService**（短信/通话/应用数据，无独立文档，机制完全同构，调用点 AndroidAnalyzerCore.cpp:302）。

## 2. 在系统中的位置

```
TaskManager::start_analysis PLATFORM_ANALYSIS 阶段 (TaskManagerAnalysis.cpp:486-500)
    └─ scenario=LINUX ──▶ LinuxFilesAnalyzer::analyzeLinuxData()
                              └─ 末尾必然调用 (LinuxFilesAnalyzerCore.cpp:294)
                                    LinuxLLMAnalysisService::analyzeLinuxArtifacts(_linux.db)
                                          ├─读─▶ linux_* 各表（仅未分析行）
                                          ├─析─▶ llm::ModelRouter（文本模型）
                                          └─写─▶ 各表 llm_* 列
前端 /linux 相关视图 ← SQLiteHelper/路由读取 llm_* 列
```

注意调用链的方向：**TaskManager 不直接调它**，而是经平台分析器间接进入——这保证了"先提取工件、后 AI 注解"的顺序天然成立。

## 3. 核心概念与设计

### 3.1 表驱动：ArtifactType ↔ 表名 ↔ SELECT ↔ prompt

四件套把"新增一种工件"变成填表：

- `getTableNameForType`（Database.cpp:104-137）：ArtifactType → `linux_log_entries`、`linux_users`、`linux_login_records`、`linux_shell_history`、`linux_cron_jobs`、`linux_ssh_keys`、`linux_ssh_known_hosts`、`linux_packages`、`linux_network_connections`、`linux_systemd_services`、`linux_kernel_modules`、`linux_firewall_rules`、`linux_audit_logs`、`linux_browser_profiles`……（含增强类型的 30 张表映射）；
- `getSelectSQLForType`（Database.cpp:139-171）：每种类型对应 `LinuxAnalysisSQL::*_PENDING_ANALYSIS` 常量——WHERE 条件天然排除已分析行（llm_analyzed_at 为空），**重跑任务时增量续作而不是重复花钱**；
- 每类型一个 prompt 函数（ArtifactAnalyzers.cpp = 日志/用户/登录/shell/cron/SSH；SystemAnalyzers.cpp = 包/网络/systemd/内核/防火墙/审计/浏览器），prompt 结构统一：角色设定 + 工件 JSON + 要求返回 `{summary, description, keywords}`；
- `storeArtifactAnalysis`（Database.cpp:16-58）：通用的 `UPDATE <表> SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?`。

### 3.2 记录即 JSON 的泛化技巧

`getArtifactsFromDatabase`（Database.cpp:60-102）不为每张表写行结构体：它按列名把任意行 **动态拼成 JSON 对象**（列名→值），prompt 直接 dump 这个 JSON。于是同一套循环能处理 30 种异构表——代价是丧失编译期字段检查。

### 3.3 文件拆分：按变更频率分层

- `LinuxLLMAnalysisService.cpp`：核心循环（analyzeLinuxArtifacts / analyzeArtifactType）；
- `_ArtifactAnalyzers.cpp` / `_SystemAnalyzers.cpp`：纯 prompt 构造，改动最频繁；
- `_Database.cpp`：SQL 与映射表。

改 prompt 不会碰核心逻辑，审阅 diff 也更容易。

### 3.4 "MANDATORY" 的真实含义

头文件注释 "This is a MANDATORY analysis step, not optional"（LinuxLLMAnalysisService.h:23-25）指：**只要跑了 Linux 场景分析，工件 LLM 注解就会跟着跑**，不受任务级 `llm_analyze` 开关控制。与文件级 LLMAnalysisService（受 llm_analyze 门控）不同。这是个容易误解的差异。

## 4. 工作流程走读

`analyzeLinuxArtifacts`（LinuxLLMAnalysisService.cpp:43-147）：

1. initialize：从 ConfigManager 取文本模型建 ModelRouter（:18-41）；
2. 按 AnalysisOptions 的 14 个 include 开关（默认全开，maxArtifacts 默认每类 1000）依次调 `analyzeArtifactType`（:63-143）；
3. `analyzeArtifactType`（:149-244）：开库 → 取未分析行（上限 maxArtifacts）→ 逐条：进度回调 → 按 type 路由到 prompt 函数 → `router_->chat` → 解析 JSON → 成功才 UPDATE 回写；单条异常仅打印并继续（:237-239）；
4. 汇总返回总分析数（调用方用于日志与进度）。

失败模式：LLM 不可用时每条 chat 都失败，函数静默返回 0——任务不会因此失败，工件表保持未分析状态等待下次增量。

## 5. 与其他模块的协作

- **LinuxFilesAnalyzer**：唯一调用方（提取完工件后立即注解）。
- **TaskManager**：间接上游，负责 PLATFORM_ANALYSIS 进度条。
- **LinuxAnalysisSQL（DatabaseManager/SQL）**：PENDING_ANALYSIS 系列 SELECT 的定义处，表结构变更要同步。
- **Windows/Android 同族服务**：相同骨架的平台变体。
- **前端 /linux 页**：经路由读 llm_* 列渲染 AI 注解。

## 6. 注意事项与已知问题

- **不受 llm_analyze 门控**：见 §3.4；没有 LLM 后端时跑 Linux 场景会为每条工件做失败调用（有超时兜底但拖慢平台阶段）。
- **增强类型默认不跑**：ArtifactType 里 JOURNAL_ENTRY、TAMPERING_INDICATOR、VPN_LOG 等 16 种"增强类型"有表映射与 SELECT（Database.cpp:120-134），但 analyzeLinuxArtifacts 的开关列表只覆盖原始 14 类（cpp:63-143）——增强类型只能通过直接调 `analyzeArtifactType` 使用，属于半接入状态。
- **逐条同步调用**：一条工件一次 LLM 往返，10 万行日志（截到 1000/类）耗时可观；无并发/批量。
- **模型输出解析强依赖 JSON**：模型不守格式时该条作废（无重试）。
- **keywords 逗号拼接**：与 EventClusterAnalyzer 同样的老问题。

## 7. 如何验证与扩展

- **验证**：跑一个含 linux 场景的任务后查 `_linux.db`：`SELECT user, llm_summary FROM linux_users WHERE llm_analyzed_at > 0 LIMIT 10`；再跑一次同任务库（或调用 analyzeArtifactType）确认 PENDING 查询不再返回已分析行（增量生效）。
- **扩展新工件类型**：① LinuxFilesAnalyzer 建表并填充；② LinuxAnalysisSQL 加 `SELECT_X_PENDING_ANALYSIS`；③ Database.cpp 两个映射函数加 case；④ ArtifactAnalyzers/SystemAnalyzers 加 prompt 函数并在 analyzeArtifactType 的 switch（cpp:185-228）注册；若要默认执行，再加 include 开关与循环调用。

**最后更新**: 2026-08-23（解释式重写）
