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

## 10. 原始 14 类的 SELECT 列契约全表（二轮补全）

linux_analysis_sql_llm.h:126-166 逐条列出进 prompt 的列（id 之外的列全部动态拼进 JSON）与截断排序：

| 类型 | 表 | 进 prompt 的列 | ORDER BY（截断偏向） | 行号 |
|---|---|---|---|---|
| LOG_ENTRY | linux_log_entries | log_file, timestamp, hostname, process, message | unix_timestamp DESC（最新） | :126-127 |
| USER_ACCOUNT | linux_users | username, uid, shell, home_directory, is_system_account | uid ASC（root 优先） | :129-130 |
| LOGIN_RECORD | linux_login_records | username, terminal, remote_host, login_time, login_type, is_success | login_time DESC | :132-133 |
| SHELL_HISTORY | linux_shell_history | username, shell_type, command, timestamp | timestamp DESC | :135-136 |
| CRON_JOB | linux_cron_jobs | username, minute, hour, day_of_month, month, day_of_week, command | id ASC | :138-139 |
| SSH_KEY | linux_ssh_keys | username, key_type, key_path, comment | id ASC | :141-142 |
| SSH_KNOWN_HOST | linux_ssh_known_hosts | username, hostname, key_type | id ASC | :144-145 |
| PACKAGE | linux_packages | name, version, package_manager, description | name ASC | :147-148 |
| NETWORK_CONNECTION | linux_network_connections | protocol, local_address, local_port, remote_address, remote_port, state, process | id ASC | :150-151 |
| SYSTEMD_SERVICE | linux_systemd_services | service_name, description, active_state, sub_state, exec_start | service_name ASC | :153-154 |
| KERNEL_MODULE | linux_kernel_modules | module_name, size, used_count, used_by, state | module_name ASC | :156-157 |
| FIREWALL_RULE | linux_firewall_rules | chain, table_name, protocol, source, destination, action | id ASC | :159-160 |
| AUDIT_LOG | linux_audit_logs | timestamp, type, message, subject, object, action, result | timestamp DESC | :162-163 |
| BROWSER_PROFILE | linux_browser_profiles | browser_type, browser_name, profile_name, profile_path, username | id ASC | :165-166 |

## 11. 增强类型的真实可用性：三层断裂（新发现）

§8 说增强类型"半接入"；逐层核验后结论要收紧——它们**当前完全不可用**，断裂在三层：

1. **BOOT_SESSION 断在 SELECT 映射**：getTableNameForType 有 BOOT_SESSION→linux_boot_sessions（_Database.cpp:121），但 getSelectSQLForType **没有对应 case**（:145-176 无此项）——直接调 analyzeArtifactType(BOOT_SESSION) 拿到空 SQL，prepare 失败返回空 vector，静默返回 0。
2. **16 个增强类型全部断在 prompt 路由**：analyzeArtifactType 的 switch（LinuxLLMAnalysisService.cpp:186-223）只有原始 14 类的 case，default 直接 `continue`——即使表映射与 SELECT 都通，增强类型一条都不会分析。prompt 函数文件里也只有 13 个函数（_ArtifactAnalyzers.cpp 6 个 + _SystemAnalyzers.cpp 7 个，SSH 两类共用 analyzeSSHArtifact），没有任何增强类型的 prompt 实现。
3. **8 条 SELECT 常量连类型映射都没有**：CONTAINER_SECURITY_FINDINGS / SUSPICIOUS_PACKAGES / SSH_SECURITY_FINDINGS / DATABASE_SECURITY_FINDINGS / EMAIL_SECURITY_FINDINGS / VPN_SECURITY_FINDINGS / SECURITY_PRODUCT_FINDINGS / MODSECURITY_LOGS（linux_analysis_sql_llm.h:189-233）在 getSelectSQLForType 里无任何 case 引用——除 linux_analysis_sql.h 的 using 转发外全仓无消费方，纯死常量。

增强类型映射齐全的 15 个（表+SELECT 都有：JOURNAL_ENTRY、AGGREGATED_AUDIT_EVENT、TAMPERING_INDICATOR、PERSISTENCE_ENTRY、ERROR_LOG、MIDDLEWARE_LOG、CONTAINER_LOG、PACKAGE_OPERATION、ACCOUNT_ANOMALY、DATABASE_LOG、EMAIL_LOG、VPN_LOG、FIREWALL_LOG、SECURITY_PRODUCT_LOG）卡在第 2 层——复活它们需要写 prompt 函数 + switch 加 case + 开关三步，SQL 侧已就绪。

## 12. prompt 函数清单（13 个，覆盖 14 类型）

| 文件 | 函数 | 覆盖类型 |
|---|---|---|
| _ArtifactAnalyzers.cpp:14 | analyzeLogArtifact | LOG_ENTRY |
| :59 | analyzeUserArtifact | USER_ACCOUNT |
| :104 | analyzeLoginArtifact | LOGIN_RECORD |
| :149 | analyzeShellHistoryArtifact | SHELL_HISTORY |
| :194 | analyzeCronArtifact | CRON_JOB |
| :239 | analyzeSSHArtifact | SSH_KEY + SSH_KNOWN_HOST（共用） |
| _SystemAnalyzers.cpp:13 | analyzePackageArtifact | PACKAGE |
| :58 | analyzeNetworkArtifact | NETWORK_CONNECTION |
| :103 | analyzeSystemdArtifact | SYSTEMD_SERVICE |
| :148 | analyzeKernelModuleArtifact | KERNEL_MODULE |
| :193 | analyzeFirewallArtifact | FIREWALL_RULE |
| :238 | analyzeAuditLogArtifact | AUDIT_LOG |
| :283 | analyzeBrowserProfileArtifact | BROWSER_PROFILE |

与 Windows 版的"14→8 收敛"不同，Linux 版是"14→13"——除 SSH 两类共用外每类独立 prompt（角色句按工件类型定制，如"analyzing Linux system log entries"）。

## 13. 配置影响表（全集）

| 配置 | 默认 | 消费链 | 说明 |
|---|---|---|---|
| `LLM_TEXT_*` 五项 | 见 Environment.md | initialize() → ModelRouter | 每条工件的模型 |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | 120 / 3 | LLMClient | 无后端时 14 表逐条超时（§8） |
| （无 maxArtifacts env） | 1000 | AnalysisOptions（h:69-84） | 调用方 LinuxFilesAnalyzerCore.cpp:294 不传 options |
| （无 include* env） | 14 开关全开 | 同上 | 关类型只能改代码或 options |
| `THREAD_POOL_SIZE` | 4 | 不影响 | 逐条串行 |

## 14. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 | 说明 |
|---|---|---|---|
| 被调 | LinuxFilesAnalyzerCore.cpp:294 | 唯一调用点 | 默认 options |
| 依赖 | llm::ModelRouter | initialize() | 文本模型 |
| 读写 | `_linux.db` 29 张映射表 + 8 张无映射表 | SELECT pending（14 类）/ UPDATE by id | §10-11 |
| SQL 来源 | linux_analysis_sql_llm.h（SELECT）+ 字符串拼接 UPDATE（_Database.cpp 同 Windows 版结构） | :126-233 | 8 条 SELECT 是死常量（§11.3） |
| 同族 | Windows（14→8 收敛）/Android 版 | 同骨架 | Linux 版收敛度最低但 prompt 最定制 |
| 间接上游 | TaskManager PLATFORM_ANALYSIS | void 回调 | 无取消通道 |
| 读出方 | 前端 /linux 视图 | llm_* 列 | 增强类型表无注解可读（§11） |

## 15. 14 个 include 开关的展开表（analyzeLinuxArtifacts 调度序）

analyzeLinuxArtifacts（cpp:43-147）按固定顺序逐开关展开（顺序即执行序，也是 §10 表计数增长的顺序）：

| 开关 | 展开的类型（调用序） | 失败传播 |
|---|---|---|
| includeLogs | LOG_ENTRY | 单类型失败不阻断后续 |
| includeUsers | USER_ACCOUNT | |
| includeLogins | LOGIN_RECORD | |
| includeShellHistory | SHELL_HISTORY | |
| includeCron | CRON_JOB | |
| includeSSH | SSH_KEY → SSH_KNOWN_HOST（共用 prompt） | |
| includePackages | PACKAGE | |
| includeNetwork | NETWORK_CONNECTION | |
| includeSystemd | SYSTEMD_SERVICE | |
| includeKernel | KERNEL_MODULE | |
| includeFirewall | FIREWALL_RULE | |
| includeAudit | AUDIT_LOG | |
| includeBrowser | BROWSER_PROFILE | |

（开关名与调度序以 h:69-84 / cpp:63-139 的真实字段与 if 序为准；13 个类型由 13 个 prompt 函数承接，§12。）每类型的 maxArtifacts 独立计数——14 类全开时理论上限 14×1000 = 14000 次 LLM 调用，串行 × 120s 超时的最坏时长以天计（无 LLM 后端时的真实风险，§8 已记）。

## 16. 回写契约与计数语义（对照前文）

- **UPDATE by id**（_Database.cpp:16-58，与 Windows 版同构的字符串拼接）：`UPDATE <table> SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?`——行级主键，无 LLMAnalysisService 的唯一路径守卫问题，也无跨表双写（不维护 file_descriptions）；
- **analyzed++ 条件**：`result.success && storeArtifactAnalysis(...)` 双条件（cpp:210-216 一带）——模型成功且落库成功才计数，与文件级 LLMAnalysisService 的"不看写库结果"相反（Windows 版同 Linux 版）；
- **LLM 失败的默认处理**：result.success=false 时**只跳过该条**（无重试、无日志——三个平台版都静默，对比文件级 smart 模式有 Warning）。

## 17. 验证 runbook

```bash
# 1. 跑含 linux 场景 + LLM 正常的任务，查注解覆盖
sqlite3 data/tasks/<id>/*_files.db \
  "SELECT 'users', COUNT(*), SUM(llm_analyzed_at IS NOT NULL) FROM linux_users
   UNION ALL SELECT 'shell', COUNT(*), SUM(llm_analyzed_at IS NOT NULL) FROM linux_shell_history"
# 2. 增量验证：同库直接再触发（或重跑任务）——PENDING 查询只取 NULL 行
# 3. 增强类型不可用性验证（§11）：直接调用入口不存在——只能从代码层面确认 switch 无 case
grep -n "JOURNAL_ENTRY\|TAMPERING_INDICATOR" src/network/HTTPServer/LinuxLLMAnalysisService.cpp  # 无命中
# 4. 死常量确认
grep -rn "SELECT_MODSECURITY_LOGS_PENDING_ANALYSIS" src --include=*.cpp | grep -v sql  # 无命中
```

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
