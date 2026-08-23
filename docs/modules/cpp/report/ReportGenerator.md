# ReportGenerator（src/report/ReportGenerator.{h,cpp}）

> **一句话**：无 AI 依赖的 Markdown 取证报告生成器——直接读任务的 `_files.db`（linux_* 工件表）与 `_events.db`（时间线），拼出一份带摘要、账户、shell 历史、cron、网络、日志亮点、安全发现与时间线的静态报告（`--report` / `--report-path`）。

## 1. 为什么有这个模块

分析流水线的终点是一堆 SQLite 库——对调查员不友好。LLM 能写"聪明的报告"，但它慢、贵、且输出不可复现。本模块走另一条路：**结构化数据 → 确定性 Markdown**，同样的库永远生成同样的报告，适合作为交付物底稿、复核材料或归档快照。头文件自我定位准确："Does NOT require AI/LLM — reads only the structured analysis tables"（ReportGenerator.h:4-5）。

## 2. 在系统中的位置

```
CLI: forensic_analyzer <镜像> … --report [--report-path <p>]
  └─ CommandLineParser.cpp:230-233（--report 置位；--report-path 附带置位）
       └─ AnalysisOrchestrator.cpp:380-391（Step 6，磁盘流水线尾部）
            ReportGenerator(fileDbPath, eventDbPath).writeMarkdown(imagePath, reportPath)
                 ├─ 只读 _files.db（linux_users / linux_shell_history / linux_cron_jobs /
                 │   linux_network_connections / linux_log_entries / linux_anomalies /
                 │   linux_tampering_findings）
                 └─ 只读 _events.db（events 表）
            → <base>_report.md（或 --report-path 指定路径）
```

装配点的真实代码（`AnalysisOrchestrator.cpp:380-391` 节选）：

```cpp
if (args.generate_report) {
    std::string reportPath = args.report_path.empty()
        ? prefix + baseName + "_report.md"        // 默认：<镜像同目录>/<stem>_report.md
        : args.report_path;
    ReportGenerator gen(fileDbPath, eventDbPath);  // 分类后的 _files.db / _events.db
    if (gen.writeMarkdown(args.image_path, reportPath)) {
        std::cout << "✓ Report: " << reportPath << std::endl;
    } else {
        std::cerr << "Warning: Failed to generate report" << std::endl;   // 只告警，不中断
    }
}
```

它是**纯 CLI 附件**：HTTP 任务流水线（TaskManagerAnalysis.cpp）不生成报告，REST 面上也没有对应端点——网页端的"报告"走的是 Python 侧 intelligence report 服务，与本模块无关。报告生成失败只打 Warning，退出码不受影响。

## 3. 核心概念与设计

### 3.1 类结构：九个章节写手 + 两个守卫函数

整个类只有两个路径成员（构造时传入），章节函数全部私有（`ReportGenerator.h:29-45`）：

```cpp
// --- Chapter writers (each opens its own sqlite3 connection) ---
void writeHeader(std::ofstream& out, const std::string& imagePath);
void writeSummary(std::ofstream& out);                // per-table row counts
void writeUsers(std::ofstream& out);                  // linux_users
void writeShellHistory(std::ofstream& out);           // linux_shell_history
void writeCronJobs(std::ofstream& out);               // linux_cron_jobs
void writeNetworkConnections(std::ofstream& out);     // linux_network_connections
void writeLogHighlights(std::ofstream& out);          // linux_log_entries (non-INFO)
void writeSecurityFindings(std::ofstream& out);       // linux_anomalies + tampering
void writeTimeline(std::ofstream& out);               // events table (top entries)

// --- Helpers ---
int tableRowCount(sqlite3* db, const std::string& table);
bool tableExists(sqlite3* db, const std::string& table);
```

两个守卫是"半成品库健壮性"的基础（`ReportGenerator.cpp:26-51`）：

```cpp
bool ReportGenerator::tableExists(sqlite3* db, const std::string& table) {
    // SELECT name FROM sqlite_master WHERE type='table' AND name=?
    // → 参数化 bind → step==SQLITE_ROW 即存在（无注入面）
}
int ReportGenerator::tableRowCount(sqlite3* db, const std::string& table) {
    if (!tableExists(db, table)) return -1;  // table missing（-1 是"缺表"哨兵值）
    std::string sql = "SELECT COUNT(*) FROM \"" + table + "\"";   // 表名拼接（见第 6 节）
    // → prepare → step 取 int → count
}
```

`tableExists` 用参数化查询查 sqlite_master；`tableRowCount` 返回 -1 表示"表不存在"，调用方据此决定章节去留。

### 3.2 章节写手（chapter writer）模式与生成调度

`writeMarkdown`（ReportGenerator.cpp:95-118）只是一串章节函数调用：

```cpp
bool ReportGenerator::writeMarkdown(const std::string& imagePath, const std::string& outputPath) {
    std::ofstream out(outputPath);
    if (!out.is_open()) {
        std::cerr << "Error: Cannot create report file: " << outputPath << std::endl;
        return false;                     // 唯一的 false 出口
    }

    writeHeader(out, imagePath);
    writeSummary(out);
    // Linux artifact sections
    writeUsers(out);
    writeShellHistory(out);
    writeCronJobs(out);
    writeNetworkConnections(out);
    writeLogHighlights(out);
    writeSecurityFindings(out);
    writeTimeline(out);

    out << "\n*This report was generated from structured analysis data and does not "
        << "require AI/LLM processing.*\n";
    return true;
}
```

固定顺序 = 固定章节号：header → summary → users → shell history → cron jobs → network connections → log highlights → security findings → timeline，最后附一段"无 AI 生成"的脚注。每个章节**自己开自己的 sqlite3 连接、自己 tableExists 守卫**——缺表的章节静默跳过而不是报错。这让报告对"半成品库"（比如某平台分析器没跑）天然健壮，代价是"报告里没有某章"不区分"没数据"和"没表"。

### 3.3 摘要章是跨平台的，细节章只有 Linux

`writeSummary`（:137-195）用 sqlite_master GLOB 按前缀枚举所有工件表并数行数。核心是这段 lambda（`:149-176` 节选）：

```cpp
auto appendRowsForPrefix = [&](const std::string& prefix,
                               const std::string& categoryPrefix) {
    bool any = false;
    const char* sql =
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND name GLOB ? ORDER BY name";             // 参数化的 GLOB 模式
    // ... bind (prefix + "*")，逐表 tableRowCount ...
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        const char* table = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        int count = tableRowCount(db, table);
        if (count >= 0) {
            any = true;
            std::string label = categoryPrefix;
            label += table + prefix.size();          // 去前缀作展示名："linux_users" → "Linux users"
            out << "| " << mdEscape(label) << " | " << count << " |\n";
        }
    }
    if (!any) {
        out << "| " << mdEscape(categoryPrefix + "artifacts") << " | — |\n";   // 空类别占位
    }
};

appendRowsForPrefix("linux_", "Linux ");
appendRowsForPrefix("windows_", "Windows ");
appendRowsForPrefix("android_", "Android ");
```

所以摘要表**任何场景都有内容**——它不假设表存在，而是发现什么数什么；某平台无表时输出"—"占位。但细节章节只实现了 Linux（头注释 "Currently covers Linux artifacts (linux_* tables). Windows and Android sections can be added later"，ReportGenerator.h:6-7）：Windows/Android 镜像得到的报告 = 头 + 摘要 + 时间线，中间章节全省略。这是当前最大的能力边界。

### 3.4 Markdown 安全转义与时间格式

`mdEscape`（:74-83）转义 `|`、把换行压成空格——防止工件内容（shell 命令、日志消息）击穿表格结构：

```cpp
static std::string mdEscape(const std::string& s) {
    std::string out;
    out.reserve(s.size());
    for (char c : s) {
        if (c == '|') out += "\\|";
        else if (c == '\n' || c == '\r') out += ' ';
        else out += c;
    }
    return out;
}
```

所有用户数据入表前都过它（shell 命令、路径、日志消息、异常描述无一例外）；时间戳格式化 `YYYY-MM-DD HH:MM:SS` 用 `localtime_r`（:54-62）——注意是**本地时区**，跨时区比对时留意。`ts <= 0` 输出 "N/A"（`:55`）。

## 4. 工作流程走读

**入口装配**（AnalysisOrchestrator.cpp:380-391）：默认输出 `prefix + baseName + "_report.md"`；构造时传入的是 `fileDbPath/eventDbPath`——即分类后的 `_files.db` 与 `_events.db`（不是 raw.db，也不是 filtered.db）。

**日志亮点**（:401-455）体现"降噪"取舍：

```cpp
// ReportGenerator.cpp:414-418
"SELECT timestamp, hostname, process, pid, message, level, log_file "
"FROM linux_log_entries "
"WHERE level IS NOT NULL AND UPPER(level) NOT IN ('INFO', 'DEBUG', '') "
"ORDER BY unix_timestamp LIMIT 200"
```

全量日志只报总数（`:410` 的 `tableRowCount` 印在导语里），正表只收 WARN/ERROR/CRITICAL，`UPPER(level)` 容忍大小写混写；消息截断到 120 字符 `:441`（`if (msg.size() > 120) msg = msg.substr(0, 117) + "..."`）。

**安全发现**（:457-548）合并两个来源：`linux_anomalies`（severity 4=CRITICAL…1=LOW）与 `linux_tampering_findings`（日志篡改指标，`:506-540`）。异常章的严重度映射（`:483-490`）：

```cpp
std::string sevLabel;
switch (severity) {
    case 4: sevLabel = "🔴 CRITICAL"; break;
    case 3: sevLabel = "🟠 HIGH"; break;
    case 2: sevLabel = "🟡 MEDIUM"; break;
    case 1: sevLabel = "🔵 LOW"; break;
    default: sevLabel = "ℹ️ INFO"; break;
}
```

注意两个来源的严重度标尺**不同**：anomalies 用 switch 精确匹配 1-4，tampering 用 `>= 3 / >= 2 / >= 1` 的区间判断（`:524-527`），同一数字在两节的标签可能不同。两个表都没有时输出 "No security tables found"（:542-544）。

**时间线**（:550-595）：events 表按 timestamp 排序取前 100（`"SELECT ... FROM events ORDER BY timestamp LIMIT 100"`，:561-563）；路径超 50 字符截尾显示（:581：`path = "..." + path.substr(path.size() - 47)`）——是"样例"而非完整时间线，完整数据仍要去查库或前端时间线页。

**返回值**：只有"输出文件打不开"返回 false（:97-100）；打开成功后即便中途写坏也返回 true（ofstream 不检查）。

**错误处理一览**：

| 故障点 | 行为 |
|---|---|
| 输出文件打不开 | `writeMarkdown` 返回 false；orchestrator 打 Warning，**不影响退出码与后续 Step 7** |
| `_files.db` 打不开 | 摘要章输出 "Cannot open files.db"，其余细节章各自尝试打开（失败即静默跳过） |
| 某工件表缺失 | 对应章节整体消失（tableExists 守卫），无提示 |
| 查询 prepare 失败 | 该章节静默跳过（各 writer 内 `!= SQLITE_OK → close + return`） |
| 时间戳非正数 | 显示 "N/A" |

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| AnalysisOrchestrator | 唯一调用方（CLI Step 6） |
| LinuxFilesAnalyzer（间接） | linux_* 表的生产者，表结构变了章节 SQL 要跟着改 |
| EventExtractor / EventCorrelationEngine（间接） | events 表的生产者 |
| CommandLineParser | `--report` / `--report-path` 入口 |

不依赖 ConfigManager / LLMClient / TaskManager——构造函数只有两个路径字符串，单测友好。

## 6. 注意事项与已知问题

- **Windows/Android 细节章节缺失**（§3.3）：对这两类镜像本模块价值有限，扩展点见 §7。
- **章节静默跳过**：缺表 = 章节消失，无提示；复核报告完整性时要结合摘要章的表计数判断。
- **时间线只有前 100 条**、日志亮点 200 条、消息 120 字符——报告是"概览"定位，别当完整证据副本用。
- **本地时区渲染**：`localtime_r` 使同一库在不同机器上生成不同时间字符串，对比报告差异时注意。
- **写失败不报错**：磁盘写满时 writeMarkdown 仍可能返回 true（只查 open）；重要报告落盘后建议 `wc -l` 抽查。
- **表名拼接**：`tableRowCount` 用 `"\"" + table + "\""` 拼接（:41），表名来自代码内常量与 sqlite_master 枚举，无注入面；若未来接受用户输入需改参数化。
- **两个严重度标尺不一致**：anomalies 的 1-4 精确匹配与 tampering 的区间判断（§4）在数字语义上不统一，合并分析时留意。

## 7. 如何验证与扩展

- **验证**：跑一个 linux 场景任务后 `forensic_analyzer <镜像> --linux-analyze --report --db-dir /tmp/r`，`grep '^## ' /tmp/r/<base>_report.md` 应列出 8 个章节；对同一库重跑应产出逐字节一致的报告（无 AI、无随机性——严格说除"Generated At"一行外逐字节一致）。
- **扩展 Windows/Android 章节**：模式完全固定——加一个 `writeXxx(std::ofstream&)`，内部 open `_files.db` → tableExists 守卫 → SELECT → mdEscape 入表，然后在 writeMarkdown 的调用串（ReportGenerator.cpp:105-112）挂上。字段参考 WindowsAnalysisSQL / AndroidAnalysisSQL 的建表常量。

## 8. 章节契约全表（SQL/列/上限，二轮补全）

九个章节的完整查询契约——每章自开连接、tableExists 守卫、mdEscape 全字段：

| 章节 | 源表 | SELECT 列 | 排序/过滤 | 上限 | 源码 |
|---|---|---|---|---|---|
| Header | — | — | — | — | :120-135 |
| Summary | sqlite_master GLOB 前缀枚举 | 表名 + COUNT(*) | 按 name | 无（每表一行） | :137-195 |
| User Accounts | linux_users | username, uid, gid, shell, home_directory, is_locked, is_system_account | ORDER BY uid | 无 | :197-242 |
| Shell History | linux_shell_history | 先 DISTINCT username，再逐用户 command, line_number | ORDER BY line_number | 无（**全量**，代码块不截断） | :244-303 |
| Cron Jobs | linux_cron_jobs | （建表列全取） | — | — | :305+ |
| Network Connections | linux_network_connections | — | — | — | :340+ |
| Log Highlights | linux_log_entries | timestamp, hostname, process, pid, message, level, log_file | `level NOT IN ('INFO','DEBUG','')`（UPPER 容忍大小写）、ORDER BY unix_timestamp | 200 行；message 120 字符截断 | :401-455 |
| Security Findings | linux_anomalies + linux_tampering_findings | 各自全列 | severity 降序 | — | :457-548 |
| Timeline | events | events 全列 | ORDER BY timestamp | 100 行；路径 50 字符截尾 | :550-595 |

**表格形态细节**：users 表的 Locked 列渲染成 "🔒 Yes"/"No"（:231-232）；shell history 用 ``` 代码块而非表格（命令含空格/引号时表格易碎），行号 >0 时前缀行号；摘要表空类别输出"—"占位（§3.3）。

## 9. 新走读分支：shell history 的两段式查询（二轮）

writeShellHistory（:244-303）是唯一做"分组嵌套输出"的章节：

```cpp
// ReportGenerator.cpp:253-265（第一段：枚举用户）
"SELECT DISTINCT username FROM linux_shell_history ORDER BY username"
// :275-277（第二段：逐用户取命令）
"SELECT command, line_number FROM linux_shell_history WHERE username=? ORDER BY line_number"
```

每用户一个 `### 用户名 (N commands)` 小节 + 独立代码块。三个边界：用户集为空时整章缩为一行 "*No shell history found.*"（:267-271）；某用户命令为空（不可能出现，DISTINCT 已过滤）continue；**line_number ≤ 0 的行不印行号**（:293-296，非 bash 格式的历史可能无行号）。与 SQL 注入面：username 走 `?` 绑定（:279）——分组键也是用户可控数据，参数化纪律在此同样生效。

## 10. 配置影响表（CLI 全集）

| 配置 | 形态 | 默认 | 说明 |
|---|---|---|---|
| `--report` | CLI flag | 关 | CommandLineParser.cpp:230-233 |
| `--report-path` | CLI 值 | `<镜像目录>/<stem>_report.md` | 附带置位 --report；相对路径按进程 CWD 解析 |
| （无 env） | — | — | 模块不读 ConfigManager——构造仅两个路径串 |
| 间接：`--linux-analyze` 等 | CLI flag | — | 决定 linux_* 表有没有数据（无则章节消失） |
| 间接：时区 | 系统 TZ | 本地时区 | §3.4 的 localtime_r——同一库不同机器产出不同时间串；CI 比对报告时要固定 TZ env |

## 11. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 |
|---|---|---|
| 被调 | AnalysisOrchestrator.cpp:380-391（Step 6） | 唯一调用方 |
| 读 | `_files.db` 的 7 张 linux_* 表 + sqlite_master | 只读 |
| 读 | `_events.db` events 表 | 只读 |
| 间接上游 | LinuxFilesAnalyzer（表生产者） | 结构变更联动 |
| 间接上游 | EventExtractor/EventCorrelationEngine | events 生产者 |
| 入口 | CommandLineParser 两 flag | CLI-only |
| 无关 | HTTPServer/TaskManager/Swagger/LLM 全家 | 零关联——网页报告走 Python intelligence report |
| 无关 | ConfigManager | 不读任何 env |

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
