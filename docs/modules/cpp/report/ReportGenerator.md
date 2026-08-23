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

它是**纯 CLI 附件**：HTTP 任务流水线（TaskManagerAnalysis.cpp）不生成报告，REST 面上也没有对应端点——网页端的"报告"走的是 Python 侧 intelligence report 服务，与本模块无关。

## 3. 核心概念与设计

### 3.1 章节写手（chapter writer）模式

`writeMarkdown`（ReportGenerator.cpp:95-118）只是一串章节函数调用：header → summary → users → shell history → cron jobs → network connections → log highlights → security findings → timeline（h:32-41 声明）。每个章节**自己开自己的 sqlite 连接、自己 tableExists 守卫**——缺表的章节静默跳过而不是报错。这让报告对"半成品库"（比如某平台分析器没跑）天然健壮，代价是"报告里没有某章"不区分"没数据"和"没表"。

### 3.2 摘要章是跨平台的，细节章只有 Linux

`writeSummary`（:137-195）用 sqlite_master GLOB 按 `linux_ / windows_ / android_` 三个前缀枚举所有工件表并数行数（:149-180），外加 events 总数——所以摘要表**任何场景都有内容**。但细节章节只实现了 Linux（头注释 "Currently covers Linux artifacts (linux_* tables). Windows and Android sections can be added later"，ReportGenerator.h:6-7）：Windows/Android 镜像得到的报告 = 头 + 摘要 + 时间线，中间章节全省略。这是当前最大的能力边界。

### 3.3 Markdown 安全转义

`mdEscape`（:74-83）转义 `|`、把换行压成空格——防止工件内容（shell 命令、日志消息）击穿表格结构。所有用户数据入表前都过它；时间戳格式化 `YYYY-MM-DD HH:MM:SS` 用 `localtime_r`（:54-62）——注意是**本地时区**，跨时区比对时留意。

## 4. 工作流程走读

**入口装配**（AnalysisOrchestrator.cpp:380-391）：默认输出 `prefix + baseName + "_report.md"`；构造时传入的是 `fileDbPath/eventDbPath`——即分类后的 `_files.db` 与 `_events.db`（不是 raw.db，也不是 filtered.db）。

**日志亮点**（:401-455）体现"降噪"取舍：

```cpp
"FROM linux_log_entries "
"WHERE level IS NOT NULL AND UPPER(level) NOT IN ('INFO', 'DEBUG', '') "
"ORDER BY unix_timestamp LIMIT 200"
```

（ReportGenerator.cpp:414-418。全量日志只报总数，正表只收 WARN/ERROR/CRITICAL，消息截断到 120 字符 :441。）

**安全发现**（:457-548）合并两个来源：`linux_anomalies`（severity 4=CRITICAL…1=LOW，:484-490）与 `linux_tampering_findings`（日志篡改指标，:506-540）；两个表都没有时输出 "No security tables found"（:542-544）。

**时间线**（:550-595）：events 表按 timestamp 排序取前 100，路径超 50 字符截尾显示（:581）——是"样例"而非完整时间线，完整数据仍要去查库或前端时间线页。

**返回值**：只有"输出文件打不开"返回 false（:97-100）；打开成功后即便中途写坏也返回 true（ofstream 不检查）。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| AnalysisOrchestrator | 唯一调用方（CLI Step 6） |
| LinuxFilesAnalyzer（间接） | linux_* 表的生产者，表结构变了章节 SQL 要跟着改 |
| EventExtractor / EventCorrelationEngine（间接） | events 表的生产者 |
| CommandLineParser | `--report` / `--report-path` 入口 |

不依赖 ConfigManager / LLMClient / TaskManager——构造函数只有两个路径字符串，单测友好。

## 6. 注意事项与已知问题

- **Windows/Android 细节章节缺失**（§3.2）：对这两类镜像本模块价值有限，扩展点见 §7。
- **章节静默跳过**：缺表 = 章节消失，无提示；复核报告完整性时要结合摘要章的表计数判断。
- **时间线只有前 100 条**、日志亮点 200 条、消息 120 字符——报告是"概览"定位，别当完整证据副本用。
- **本地时区渲染**：`localtime_r` 使同一库在不同机器上生成不同时间字符串，对比报告差异时注意。
- **写失败不报错**：磁盘写满时 writeMarkdown 仍可能返回 true（只查 open）；重要报告落盘后建议 `wc -l` 抽查。
- **表名拼接**：`tableRowCount` 用 `"\"" + table + "\""` 拼接（:41），表名来自代码内常量与 sqlite_master 枚举，无注入面；若未来接受用户输入需改参数化。

## 7. 如何验证与扩展

- **验证**：跑一个 linux 场景任务后 `forensic_analyzer <镜像> --linux-analyze --report --db-dir /tmp/r`，`grep '^## ' /tmp/r/<base>_report.md` 应列出 8 个章节；对同一库重跑应产出逐字节一致的报告（无 AI、无随机性）。
- **扩展 Windows/Android 章节**：模式完全固定——加一个 `writeXxx(std::ofstream&)`，内部 open `_files.db` → tableExists 守卫 → SELECT → mdEscape 入表，然后在 writeMarkdown 的调用串（ReportGenerator.cpp:105-112）挂上。字段参考 WindowsAnalysisSQL / AndroidAnalysisSQL 的建表常量。

**最后更新**: 2026-08-23（新建，解释式）
