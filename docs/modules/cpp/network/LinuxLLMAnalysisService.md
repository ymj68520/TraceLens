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

## 3. 核心数据结构

### 3.1 类型与选项（LinuxLLMAnalysisService.h:31-104）

```cpp
// src/network/HTTPServer/LinuxLLMAnalysisService.h:31-46（节选）
enum class ArtifactType {
    // Original types
    LOG_ENTRY, USER_ACCOUNT, LOGIN_RECORD, SHELL_HISTORY, CRON_JOB,
    SSH_KEY, SSH_KNOWN_HOST, PACKAGE, NETWORK_CONNECTION, SYSTEMD_SERVICE,
    KERNEL_MODULE, FIREWALL_RULE, AUDIT_LOG, BROWSER_PROFILE,
    // New types from enhanced Linux analysis
    JOURNAL_ENTRY, BOOT_SESSION, AGGREGATED_AUDIT_EVENT, TAMPERING_INDICATOR,
    PERSISTENCE_ENTRY, ERROR_LOG, MIDDLEWARE_LOG, CONTAINER_LOG,
    PACKAGE_OPERATION, ACCOUNT_ANOMALY, DATABASE_LOG, EMAIL_LOG, VPN_LOG,
    FIREWALL_LOG, SECURITY_PRODUCT_LOG,
    ALL
};

// h:89-93
struct ArtifactRecord {
    int64_t id;
    std::string type;
    std::string data;  // JSON-formatted artifact data
};
```

- **ArtifactType 前 14 个**是默认执行的原始类型；后面 16 个"增强类型"有表映射与 SELECT 但不在默认开关列表（§8 半接入状态）。
- **ArtifactRecord.data 是整行工件的 JSON 串**——这是"记录即 JSON"泛化技巧的载体（§4.2），prompt 直接 dump 它。
- AnalysisResult（h:98-104）：success/summary/description/keywords/modelUsed 五字段；success=false 时该条作废、不回写（无重试）。
- AnalysisOptions（h:69-84）：14 个 include 开关默认全开 + `maxArtifacts=1000`（每类上限）。

## 4. 核心概念与设计

### 4.1 表驱动：ArtifactType ↔ 表名 ↔ SELECT ↔ prompt

四件套把"新增一种工件"变成填表。前两件是两个纯映射函数（_Database.cpp）：

```cpp
// src/network/HTTPServer/LinuxLLMAnalysisService_Database.cpp:104-119（原始 14 类节选）
std::string LinuxLLMAnalysisService::getTableNameForType(ArtifactType type) {
    switch (type) {
        case ArtifactType::LOG_ENTRY: return "linux_log_entries";
        case ArtifactType::USER_ACCOUNT: return "linux_users";
        case ArtifactType::LOGIN_RECORD: return "linux_login_records";
        case ArtifactType::SHELL_HISTORY: return "linux_shell_history";
        case ArtifactType::CRON_JOB: return "linux_cron_jobs";
        case ArtifactType::SSH_KEY: return "linux_ssh_keys";
        case ArtifactType::SSH_KNOWN_HOST: return "linux_ssh_known_hosts";
        case ArtifactType::PACKAGE: return "linux_packages";
        case ArtifactType::NETWORK_CONNECTION: return "linux_network_connections";
        case ArtifactType::SYSTEMD_SERVICE: return "linux_systemd_services";
        case ArtifactType::KERNEL_MODULE: return "linux_kernel_modules";
        case ArtifactType::FIREWALL_RULE: return "linux_firewall_rules";
        case ArtifactType::AUDIT_LOG: return "linux_audit_logs";
        case ArtifactType::BROWSER_PROFILE: return "linux_browser_profiles";
        // 增强类型另映射到 linux_journal_entries / linux_boot_sessions /
        // linux_audit_events / linux_tampering_findings / ... 共 30 张表（:120-134）
        default: return "";
    }
}
```

第三件是 PENDING SELECT 常量（`getSelectSQLForType`，Database.cpp:139-171 返回 `LinuxAnalysisSQL::*_PENDING_ANALYSIS`），定义在 linux_analysis_sql_llm.h：

```cpp
// src/core/DatabaseManager/SQL/linux_analysis_sql_llm.h:126-136
inline constexpr const char* SELECT_LOG_ENTRIES_PENDING_ANALYSIS =
    "SELECT id, log_file, timestamp, hostname, process, message FROM linux_log_entries WHERE llm_analyzed_at IS NULL ORDER BY unix_timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_USERS_PENDING_ANALYSIS =
    "SELECT id, username, uid, shell, home_directory, is_system_account FROM linux_users WHERE llm_analyzed_at IS NULL ORDER BY uid LIMIT ?;";

inline constexpr const char* SELECT_LOGIN_RECORDS_PENDING_ANALYSIS =
    "SELECT id, username, terminal, remote_host, login_time, login_type, is_success FROM linux_login_records WHERE llm_analyzed_at IS NULL ORDER BY login_time DESC LIMIT ?;";
```

三个共性：① 首列必是 id（回写主键，`getArtifactsFromDatabase` 硬编码取 column 0）；② **WHERE llm_analyzed_at IS NULL 天然排除已分析行**——重跑任务时增量续作而不是重复花钱；③ ORDER BY 各表按证据新鲜度排序（时间倒序/uid 正序），LIMIT 保证 1000/类上限内的截断偏向最近数据。第四件是每类型一个 prompt 函数（见 §6.2）。

### 4.2 记录即 JSON 的泛化技巧

`getArtifactsFromDatabase`（Database.cpp:60-102）不为每张表写行结构体：

```cpp
// src/network/HTTPServer/LinuxLLMAnalysisService_Database.cpp:66-97（节选）
std::string query = selectSQL;
size_t pos = query.find("?");
if (pos != std::string::npos) {
    query.replace(pos, 1, std::to_string(limit));
}
// ...
while (sqlite3_step(stmt) == SQLITE_ROW) {
    ArtifactRecord record;
    record.id = sqlite3_column_int64(stmt, 0);
    record.type = tableName;

    // Build JSON representation of the artifact
    json artifactJson;
    int columnCount = sqlite3_column_count(stmt);
    for (int i = 1; i < columnCount; i++) {
        const char* colName = sqlite3_column_name(stmt, i);
        const char* colValue = reinterpret_cast<const char*>(sqlite3_column_text(stmt, i));
        if (colValue) {
            artifactJson[colName] = colValue;
        }
    }
    record.data = artifactJson.dump();
    artifacts.push_back(record);
}
```

LIMIT 不是 bind 参数而是**字符串替换第一个 `?`**（SELECT 常量里只有 LIMIT 一个占位符，约定成立但不被编译器保证）；列循环从 1 开始跳过 id，把其余列按"列名→文本值"动态拼成 JSON。同一套循环因此能处理 30 种异构表——代价是丧失编译期字段检查，且所有值都经 `sqlite3_column_text` 文本化（数值列进 JSON 也变字符串，如 uid=0 会是 "0"）。

### 4.3 文件拆分：按变更频率分层

- `LinuxLLMAnalysisService.cpp`：核心循环（analyzeLinuxArtifacts / analyzeArtifactType）；
- `_ArtifactAnalyzers.cpp` / `_SystemAnalyzers.cpp`：纯 prompt 构造，改动最频繁；
- `_Database.cpp`：SQL 与映射表。

改 prompt 不会碰核心逻辑，审阅 diff 也更容易。

### 4.4 "MANDATORY" 的真实含义

头文件注释 "This is a MANDATORY analysis step, not optional"（LinuxLLMAnalysisService.h:23-25）指：**只要跑了 Linux 场景分析，工件 LLM 注解就会跟着跑**，不受任务级 `llm_analyze` 开关控制。与文件级 LLMAnalysisService（受 llm_analyze 门控）不同。这是个容易误解的差异。

## 5. 核心接口清单

| 方法（真实签名） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `bool initialize()` | 惰性取文本模型建 ModelRouter | 所有方法首行 | 异常打印返回 false → 返回 0 |
| `int analyzeLinuxArtifacts(linuxDbPath, options, cb)` | 按 14 个 include 开关顺序调度每类 | LinuxFilesAnalyzerCore.cpp:294（唯一） | LLM 不可用逐条失败，静默返回 0，任务不受影响 |
| `int analyzeArtifactType(linuxDbPath, type, maxArtifacts, cb)` | 单类型全流程（开库→取行→逐条分析→回写） | analyzeLinuxArtifacts / 可直接调用增强类型 | 单条异常仅打印并继续（:237-239） |
| `storeArtifactAnalysis(db, tableName, id, ...)`（private，_Database.cpp:16-58） | 通用 UPDATE 回写 | analyzeArtifactType | prepare 失败返回 false；不看 changes 行数 |
| `getArtifactsFromDatabase(db, tableName, selectSQL, limit)`（private） | §4.2 取行拼 JSON | analyzeArtifactType | 开库/prepare 失败返回空 vector |

## 6. 工作流程走读

### 6.1 类型路由与回写（analyzeArtifactType 核心，cpp:149-244）

```cpp
// src/network/HTTPServer/LinuxLLMAnalysisService.cpp:160-168、173-186、230-239（节选）
std::string tableName = getTableNameForType(artifactType);
std::string selectSQL = getSelectSQLForType(artifactType);

auto artifacts = getArtifactsFromDatabase(db, tableName, selectSQL, maxArtifacts);
if (artifacts.empty()) { /* ... */ return 0; }

for (size_t i = 0; i < artifacts.size(); ++i) {
    const auto& artifact = artifacts[i];
    // ...
    try {
        AnalysisResult result;
        switch (artifactType) {
            case ArtifactType::LOG_ENTRY:   result = analyzeLogArtifact(artifact); break;
            case ArtifactType::USER_ACCOUNT: result = analyzeUserArtifact(artifact); break;
            // ...
            default: continue;
        }
        if (result.success) {
            if (storeArtifactAnalysis(db, tableName, artifact.id,
                                     result.summary, result.description,
                                     result.keywords, result.modelUsed)) {
                analyzed++;
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "Failed to analyze artifact " << artifact.id << ": " << e.what() << std::endl;
    }
}
```

switch 的 default 直接 continue——这就是"增强类型只能直接调 analyzeArtifactType、经 analyzeLinuxArtifacts 根本不会跑到"的代码根源（循环外层只按 14 个开关传原始类型；SSH_KEY 与 SSH_KNOWN_HOST 两个 case 共用 analyzeSSHArtifact）。进度回调是 void 签名（h:113-115），**没有取消能力**——与 LLMAnalysisService 的 bool 回调不同，用户取消任务不能中断这里的逐条循环。回写成功才计数，异常吞掉继续。注意每类型**自开 sqlite 连接**（:153-158），跑完即关。

### 6.2 prompt 长什么样（_ArtifactAnalyzers.cpp:13-56）

```cpp
// src/network/HTTPServer/LinuxLLMAnalysisService_ArtifactAnalyzers.cpp:19-50（节选）
auto data = json::parse(artifact.data);

std::string prompt = R"(You are a digital forensics expert analyzing Linux system log entries.

Analyze this log entry and provide:
1. Summary: Brief one-line description of the event
2. Description: Detailed explanation of its forensic significance and potential security implications
3. Keywords: 3-5 relevant keywords for categorization

Log Entry:
)" + data.dump() + R"(

Respond in JSON format:
{
  "summary": "brief description",
  "description": "detailed forensic analysis",
  "keywords": ["keyword1", "keyword2", "keyword3"]
})";

auto response = router_->chat(prompt);
if (response.success) {
    auto jsonResponse = json::parse(response.content);
    result.summary = jsonResponse.value("summary", "");
    // ...
    result.modelUsed = router_->getLastUsedModel();
    result.success = true;
}
```

prompt 结构四段式：角色设定 + 三项要求 + **工件 JSON 原文**（data.dump()，§4.2 的动态 JSON 直接进 prompt）+ 输出 JSON 模板。解析侧 `json::parse(response.content)` 是**裸解析**——模型在 JSON 外多吐一个字都会抛异常 → catch → result.success 保持 false → 该条作废。这与 EventClusterAnalyzer/LLMAnalysisService 的 find('[')/rfind(']') 容错截取不同，是同族服务里更严格的解析策略。所有 prompt 函数共用这个骨架，只有角色句与工件标签不同。

汇总流程：`analyzeLinuxArtifacts`（cpp:43-147）initialize → 按 14 开关依次调 analyzeArtifactType 累加 → 返回总数（调用方用于日志与进度）。失败模式：LLM 不可用时每条 chat 都失败，函数静默返回 0——任务不会因此失败，工件表保持未分析状态等待下次增量。

## 7. 与其他模块的协作

- **LinuxFilesAnalyzer**：唯一调用方（提取完工件后立即注解）。
- **TaskManager**：间接上游，负责 PLATFORM_ANALYSIS 进度条。
- **LinuxAnalysisSQL（DatabaseManager/SQL）**：PENDING_ANALYSIS 系列 SELECT 的定义处，表结构变更要同步。
- **Windows/Android 同族服务**：相同骨架的平台变体。
- **前端 /linux 页**：经路由读 llm_* 列渲染 AI 注解。

## 8. 注意事项与已知问题

- **不受 llm_analyze 门控**：见 §4.4；没有 LLM 后端时跑 Linux 场景会为每条工件做失败调用（有超时兜底但拖慢平台阶段）。
- **增强类型默认不跑**：ArtifactType 里 JOURNAL_ENTRY、TAMPERING_INDICATOR、VPN_LOG 等 16 种"增强类型"有表映射与 SELECT（Database.cpp:120-134），但 analyzeLinuxArtifacts 的开关列表只覆盖原始 14 类（cpp:63-143），switch 的 default 也直接跳过（§6.1）——增强类型只能通过直接调 `analyzeArtifactType` 使用，属于半接入状态。
- **逐条同步调用**：一条工件一次 LLM 往返，10 万行日志（截到 1000/类）耗时可观；无并发/批量。
- **模型输出解析强依赖 JSON**：模型不守格式时该条作废（无重试，§6.2 裸解析）。
- **keywords 逗号拼接**：与 EventClusterAnalyzer 同样的老问题。

## 9. 如何验证与扩展

- **验证**：跑一个含 linux 场景的任务后查 `_linux.db`：`SELECT user, llm_summary FROM linux_users WHERE llm_analyzed_at > 0 LIMIT 10`；再跑一次同任务库（或调用 analyzeArtifactType）确认 PENDING 查询不再返回已分析行（增量生效）。
- **扩展新工件类型**：① LinuxFilesAnalyzer 建表并填充；② LinuxAnalysisSQL 加 `SELECT_X_PENDING_ANALYSIS`；③ Database.cpp 两个映射函数加 case；④ ArtifactAnalyzers/SystemAnalyzers 加 prompt 函数并在 analyzeArtifactType 的 switch（cpp:185-228）注册；若要默认执行，再加 include 开关与循环调用。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
