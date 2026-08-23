# LinuxFilesAnalyzer（src/analyzers/LinuxFilesAnalyzer/）

> **一句话**：Linux/服务器取证的总装车间——把 syslog/journald/auditd、账号与登录、shell 历史、持久化配置、容器与 Web 服务器、安全基线等几十类证据解析进 linux.db 的 70 多张表，再在其上跑关联、时间线、异常检测和 MITRE ATT&CK 规则引擎，产出"攻击链"级别的结论。

## 1. 为什么有这个模块

Linux 取证的证据形态是"文本为主、散布极广"。一台被入侵的服务器，入侵痕迹可能藏在 `/var/log/auth.log` 的一次 SSH 登录、`~/.bash_history` 的一条命令、`/etc/cron.d` 的一个新任务、Docker 容器日志的一次异常 exec、auditd 记录的一次文件读取——每一处单看都不起眼，串起来才是完整的入侵故事。这个模块存在的第一理由就是**穷尽地收集**：它分 21 个 Phase（代码里就这么编号的）覆盖了从系统日志到 XDG 桌面痕迹的几十类工件。

第二个理由是**从"记录"到"结论"的提升**。单纯把日志入库只是搬运；真正值钱的是把异构证据放在一起推理。模块在解析层之上建了一组分析引擎：`LogCorrelationEngine` 跨日志源关联事件、`TimelineReconstructor` 重建统一时间线并找"无法解释的空档"、`AnomalyDetector` 按内置规则标异常、`LogTamperingDetector` 专查反取证（日志清空、轮转断号、时间倒流）、`RuleEngine` 用 Sigma 风格规则匹配并映射 MITRE ATT&CK 技术编号、组装攻击链。这些引擎都读 linux.db（而不是读原始文件），体现了"先物证入库、再推理"的架构分层。

第三个理由是**对抗反取证**。攻击者删日志、压缩归档、篡改时间是常态。所以 Phase 1 特意先做压缩/轮转日志预处理（`.gz/.xz/.bz2/.zst` 解压入库），保证"历史日志"参与分析；日志防篡改检测（Phase 5.5）则专门识别轮转序列缺号（如 auth.log.2 消失）这类删除痕迹。

## 2. 核心数据结构与接口

**主类骨架**（`Common/LinuxAnalyzerDeclarations.h:23-260`）：21 个 Phase 的 `analyzeXxx()` 全部是公有方法（方便逐个单测），外加四个分析引擎入口。关键公有接口：

| 方法 | 语义 | 调用方 | 失败行为 |
|------|------|--------|---------|
| `bool initialize()` | 准备输出库与提取目录 | 两个入口构造后调用 | false 即中止 |
| `void setOutputDatabasePath(path)` / `setExtractDirectory(dir)` / `setSkipAI(bool)` | 输出库路径 / 中间文件目录 / `--no-ai` | HTTP（任务路径）与 CLI | — |
| `void analyzeLinuxData()` | 主流程：21 Phase + 五引擎 + LLM | LINUX 场景（`TaskManagerAnalysis.cpp:486-501`）与 CLI `--linux-analyze` | 每 Phase 独立 try/catch |
| `void analyzeServerCloudArtifacts()` | 服务器/云入口——实现就是一句 `analyzeLinuxData()`（`LinuxFilesAnalyzerCore.cpp:218-231`） | SERVER_CLOUD 场景 | 同上 |
| `void analyzeWithLLM()` | 25+ 类工件的 LLM 增强 | 主流程尾部 | 跳过条件同其他平台 |
| `void analyzeWithRuleEngine()` / `correlateEvents()` / `reconstructTimeline()` / `detectAnomalies()` | 四个推理引擎 | 主流程 Phase 16 之后依次调用 | 引擎失败不回滚已落表 |

**auditd 聚合事件**（`Parsers/AuditdAggregator.h:23-93`）——模块里字段最丰富的结构：

```cpp
struct AggregatedAuditEvent {
    // Core identifiers
    int64_t timestamp = 0;               // Epoch seconds from msg=audit()
    int serialNumber = 0;                // Serial from msg=audit()
    std::string eventId;                 // Unique ID: "timestamp:serial"
    // SYSCALL fields
    int syscall = -1;                    // Syscall number
    std::string syscallName;             // Syscall name (if resolvable)
    int success = -1;                    // 1=success, 0=fail
    int pid = -1, ppid = -1;
    int uid = -1, gid = -1, euid = -1, egid = -1, auid = -1;  // auid=登录 UID
    std::string exe, comm, terminal, key;
    // EXECVE fields
    std::vector<std::string> argv;       // Command arguments
    // PATH fields (list of paths accessed)
    struct PathEntry {
        std::string name;                // File path
        std::string inode;               // Inode number
        int nametype = 0;                // 0=normal, 1=PARENT, 2=CREATE, etc.
    };
    std::vector<PathEntry> paths;
    // ...
    std::vector<std::string> rawLines;   // All raw log lines for this event
    std::string eventType;   // "process_execution", "file_access", "auth", "privilege_change"
    int severity = 0;        // 0=info .. 4=critical
};
```

为什么需要它：auditd 的一次 syscall 会输出 SYSCALL/EXECVE/CWD/PATH 多行，共享同一个 `msg=audit(时间戳:序号)` 前缀；不聚合就没法按"一次文件操作"来分析。`eventId = "timestamp:serial"` 是聚合键；`auid`（audit UID，登录时的真实用户）是追踪"sudo 提权后到底是谁"的关键字段；`rawLines` 保留原始行，结论可疑时可以回查原文。

**持久化机制枚举**（`Common/LinuxDataTypes.h:592-607`）：

```cpp
enum class PersistenceType {
    RC_LOCAL,           // /etc/rc.local
    INIT_D_SCRIPT,      // /etc/init.d/*
    SHELL_PROFILE,      // /etc/profile, ~/.bashrc, ~/.profile, /etc/bash.bashrc
    AUTHORIZED_KEYS,    // ~/.ssh/authorized_keys
    LD_SO_PRELOAD,      // /etc/ld.so.preload
    SUDOERS,            // /etc/sudoers, /etc/sudoers.d/*
    UDEV_RULE,          // /etc/udev/rules.d/*.rules
    POLKIT_RULE,        // /etc/polkit-1/rules.d/*.rules
    XINETD_SERVICE,     // /etc/xinetd.d/*
    SYSTEMD_TIMER,      // *.timer units
    AT_JOB,             // /var/spool/at/*
    CRON_JOB,           // Already parsed, but included for completeness
    SYSTEMD_SERVICE,    // Already parsed, but included for completeness
    UNKNOWN_PERSISTENCE
};
```

14 种机制对应 `PersistenceDetector` 的 14 个检测方法（`PersistenceDetector.h:29-39`），注释特意说明 cron/systemd 是"为完整性重复枚举"（已在别的 Phase 解析过）。

## 3. 在流水线中的位置

两个入口：

- **HTTP 模式**：LINUX 或 SERVER_CLOUD 场景。前者写 `data/tasks/<id>/<镜像名>_linux.db`（`TaskManagerAnalysis.cpp:486-501`）；后者复用同一个类，只是入口换成 `analyzeServerCloudArtifacts()`、输出写 `<镜像名>_oss.db`——它的实现就是一句 `analyzeLinuxData()`（`LinuxFilesAnalyzerCore.cpp:218-231`），即"服务器/云场景 = 完整 Linux 分析换了个输出库名"。
- **CLI 模式**：`--linux-analyze`，工件并入 `<镜像名>_files.db`（`AnalysisOrchestrator.cpp:312-327`）。

输入：镜像路径 + raw.db（`DatabaseManager`）。中间产物（解压的日志、提出的配置）落在输出库旁的 `<镜像名>_extracted_files/`（`LinuxFilesAnalyzerCore.cpp:55-68`）。输出：linux.db，73 张表左右（表清单在 `src/core/DatabaseManager/SQL/linux_analysis_sql_tables.h`），另有 `llm_*` 列由 `linux_analysis_sql_llm.h` 的语句维护。

主流程 `analyzeLinuxData()`（`LinuxFilesAnalyzerCore.cpp:81-216`）是理解模块的地图：21 个 Phase 的 `analyzeXxx()` 各自独立 try 级容错（前几个显式 try/catch，其余靠外层），最后依次跑五个分析引擎，再跑 LLM。

## 4. 证据来源与覆盖范围

证据按 Phase 分组，全部通过 `queryFilesByPattern` 在 raw.db 里按路径模式定位（与 Windows 侧同构）：

| 证据组 | 代表性来源 | 落表（节选） |
|-------|-----------|-------------|
| 日志与压缩日志 | `/var/log/syslog|messages|auth.log|secure|kern.log` 及其 `.1/.gz/.xz` 轮转、systemd journal（`/var/log/journal/`）、auditd | linux_log_entries / linux_journal_entries / linux_audit_events |
| 账号与认证 | `/etc/passwd`、`/etc/shadow`、`/etc/group`、wtmp/btmp、`~/.ssh/authorized_keys`、known_hosts | linux_users / linux_login_records / linux_ssh_keys |
| 命令与扩展历史 | `~/.bash_history` 等 + Phase 13 的 `~/.python_history`、`~/.mysql_history`、`~/.gitconfig`、`~/.kube/config`、AWS/gcloud/az 凭证文件 | linux_shell_history / linux_extended_history |
| 持久化与配置 | cron、systemd 单元与 timer、`/etc/rc.local`、init.d、shell profile、`/etc/ld.so.preload`、sudoers、udev/polkit/xinetd 规则、at 任务 | linux_cron_jobs / linux_systemd_services / linux_persistence_entries |
| 容器与 Web | `var/lib/docker/containers/%/config.json`、docker 运行日志（`*-json.log`）、Podman、Apache/Nginx access log 与 vhost、modsecurity | linux_docker_* / linux_apache_* / linux_nginx_* / linux_modsecurity_logs |
| 安全基线与网络 | setuid 文件、capabilities、SELinux AVC、AppArmor、防火墙规则、DNS 配置、USB/挂载事件 | linux_setuid_files / linux_selinux_avc_denials / linux_firewall_rules |
| 行为痕迹 | 浏览器 profile（Chromium/Firefox）、XDG 最近文档/回收站、CUPS 打印、systemd-coredump、Snap/Flatpak 包 | linux_browser_* / linux_recent_documents / linux_trash_entries |

### 4.1 产出表结构说明（linux.db 关键表）

| 表 | 关键列（取自真实 schema） | 取证含义 |
|----|--------------------------|---------|
| `linux_log_entries`（`linux_analysis_sql_tables.h:12-28`） | `log_file/timestamp/unix_timestamp/hostname/process/pid/message/level/facility` | 通用日志容器，`unix_timestamp` 与 `log_file` 都有索引——时间窗查询和按文件追溯都走索引 |
| `linux_users`（:34-56） | `username/uid/shell/password_hash/last_password_change/is_locked/is_system_account` | `/etc/passwd`+`shadow` 合一：后门账号的典型画像 = 高 uid + 不锁 + 近期改密 |
| `linux_audit_events`（:281-324） | `event_id/syscall_name/argv/auid/exe/paths/event_type/severity/raw_lines` | 聚合后的 auditd 事件全字段；6 个索引覆盖 time/type/pid/auid/severity 的常见追问 |
| `linux_tampering_findings`（:333-350） | `tampering_type/severity/timestamp_start/timestamp_end/evidence/related_files` | 反取证发现：篡改类型 + 时间区间——"这段时间的日志去哪了"直接可查 |
| `linux_rule_matches`（:1547+） | `rule_id/rule_type/attck_technique/attack_stage/severity/confidence/matched_event_ids/raw_record` | Sigma/IOC 命中，带 ATT&CK 编号与置信度；`matched_event_ids` 关联回原始事件 |
| `linux_attack_chains`（:728+） | `chain_id/attack_type/events/timeline/summary/confidence` | 攻击链：events/timeline 是序列化的事件 ID 与时间线 |
| `linux_timeline_events` / `linux_timeline_gaps` | `timestamp/source_type/event_type/username/ip_address` / 空档区间 | 统一时间线与"无法解释的空档"（空档本身是证据） |

## 5. 解析机制走读

**链路一：压缩轮转日志（Phase 1，必须最先跑）。** `analyzeCompressedLogs()` 用 `CompressedLogParser` 处理 `auth.log.2.gz` 这类文件。文件名先被拆成"基础名 + 轮转号 + 压缩扩展"，压缩格式按魔数识别，解压到临时文件后复用普通日志解析器入库：

```cpp
// Parsers/CompressedLogParser.cpp:51-60  轮转命名模式
const std::vector<std::regex> CompressedLogParser::ROTATION_PATTERNS = {
    // Pattern: base.N or base.N.ext (e.g., auth.log.1, auth.log.2.gz)
    std::regex(R"(^(.+)\.(\d+)(\.(gz|xz|bz2|zst))?$)"),
    // Pattern: base-YYYYMMDD or base-YYYYMMDD.ext (e.g., messages-20240101)
    std::regex(R"(^(.+)-(\d{8})(\.(gz|xz|bz2|zst))?$)"),
    // Pattern: base.YYYYMMDD or base.YYYYMMDD.ext
    std::regex(R"(^(.+)\.(\d{8})(\.(gz|xz|bz2|zst))?$)"),
    // Pattern: base.1.ext (e.g., syslog.1.gz)
    std::regex(R"(^(.+)\.(\d+)\.(gz|xz|bz2|zst)$)")
};

// Parsers/CompressedLogParser.cpp:107-122  魔数识别（节选）
    // gzip magic: 1f 8b
    if (magic[0] == 0x1f && magic[1] == 0x8b) return CompressionType::GZIP;
    // ...
    // zstd magic: 28 b5 2f fd
    if (bytesRead >= 4 && magic[0] == 0x28 && magic[1] == 0xb5 &&
        magic[2] == 0x2f && magic[3] == 0xfd) {
        return CompressionType::ZSTD;
    }
```

四组正则覆盖两类轮转风格（logrotate 的 `base.N` 与日期后缀风格）。格式识别先看扩展名、无扩展名再读前 16 字节按魔数判（`identifyCompressionFromMagic`，第 92-125 行）；一个防呆细节：`.zip/.7z/.rar/.lz4` 这些"是压缩但本模块不支持"的扩展名返回 UNKNOWN 而不是 NONE（第 81-86 行注释）——否则会被当纯文本硬读出一堆乱码行。为什么必须最先跑？因为后续的日志防篡改检测要靠"完整轮转序列"判断缺号——历史日志不先入库，序列就是残缺的（`LinuxFilesAnalyzerCore.cpp:86-88` 的注释强调了这个顺序）。

**链路二：auditd 多行聚合（`AuditdAggregator::aggregate`，`AuditdAggregator.cpp:411-448`）。**

```cpp
// Parsers/AuditdAggregator.cpp:411-448（节选）
std::vector<AggregatedAuditEvent> AuditdAggregator::aggregate(const std::string& content) {
    std::vector<AggregatedAuditEvent> results;
    // Step 1: Parse all lines
    std::vector<ParsedLine> allLines;
    std::istringstream stream(content);
    std::string line;
    while (std::getline(stream, line)) {
        if (line.empty()) continue;
        auto parsed = parseLine(line);
        if (!parsed.type.empty()) {
            allLines.push_back(parsed);
        }
    }
    // Step 2: Group by (timestamp, serial)
    std::map<std::string, std::vector<ParsedLine>> groups;
    for (const auto& parsed : allLines) {
        std::string key = std::to_string(parsed.timestamp) + ":" + std::to_string(parsed.serialNumber);
        groups[key].push_back(parsed);
    }
    // Step 3: Merge each group into an aggregated event
    for (const auto& [key, lines] : groups) {
        auto event = mergeEvent(lines);
        if (!event.rawLines.empty()) {
            results.push_back(event);
        }
    }
    // Step 4: Sort by timestamp
    std::sort(results.begin(), results.end(),
        [](const AggregatedAuditEvent& a, const AggregatedAuditEvent& b) {
            return a.timestamp < b.timestamp;
        });
    return results;
}
```

四步流水线：逐行解析出 `type/timestamp/serial` → 以 `"timestamp:serial"` 为键分组（auditd 内核保证同 serial 的事件行时间戳一致，这个复合键是官方聚合方式）→ 每组 `mergeEvent` 合成一个 `AggregatedAuditEvent`（SYSCALL 行给主字段、EXECVE 行拼 argv、PATH 行收集文件列表、`classifyEvent` 定 event_type、`assessSeverity` 定 0-4 严重度）→ 按时间排序保证入库顺序即时间顺序。边界处理：解析不出 type 的行丢弃（空行/损坏行），`rawLines` 为空的组不产出——不完整的事件宁可不要也不写半截。

**链路三：日志防篡改检测（Phase 5.5）。** `LogTamperingDetector` 定义了多种篡改类型：日志清空、轮转缺号（TIME_WINDOW_GAP、ROTATION_GAP 类）、时间倒流（time reversal）、journal 缺段、可疑的重复时间戳（`LogTamperingDetector.h:31-35` 的枚举）。每个检测方法扫描已入库的日志条目（输入是 linux.db，不是原始文件），产出带时间区间的 `TamperingFinding` 落 linux_tampering_findings。这是"解析层产物喂分析层"的典型例子：Phase 1 先把历史压缩日志补齐，这里才可能发现"轮转序列中间少了一号"——两段代码隔了五个 Phase 却是一对搭档。

**链路四：规则引擎与攻击链（最后的分析层）。** `analyzeWithRuleEngine()`（`LinuxFilesAnalyzerEnhanced.cpp:186-207`）构造 `RuleEngine(outputDbPath_)`：`evaluateAllRules()` 跑 Sigma 风格规则与 IOC 匹配，每个命中带 MITRE ATT&CK 技术编号与置信度；`buildAttackChains(matches)` 把按战术排序的命中串成链。技术→战术的映射表（`RuleEngine.cpp:37-59`）：

```cpp
// Analysis/RuleEngine.cpp:23-40（节选）
const std::vector<std::string> RuleEngine::ATTCK_STAGES = {
    "Initial Access", "Execution", "Persistence", "Privilege Escalation",
    "Defense Evasion", "Credential Access", "Discovery",
    "Lateral Movement", "Collection", "Exfiltration", "Command and Control"
};
const std::map<std::string, std::string> RuleEngine::TECHNIQUE_TO_TACTIC = {
    {"T1078", "Initial Access"},
    {"T1059", "Execution"},
    {"T1053", "Persistence"},
    {"T1543", "Persistence"},
    {"T1547", "Persistence"},
    {"T1055", "Privilege Escalation"},
    // ... 共 20 项技术编号映射
};
```

`ATTCK_STAGES` 的 11 个战术既是映射表的目标，也是攻击链排序的依据——`buildAttackChains` 按这个顺序把命中串成"Initial Access → Execution → Persistence → …"的链，链上的时间顺序若有倒挂（后面战术的事件反而更早）本身就是疑点。规则命中示例：暴力破解规则标 `T1110`（Credential Access）、可疑 cron 标 `T1053`、异常登录标 `T1078`、sudo 滥用标 `T1548`。结果分别落 linux_rule_matches 和 linux_attack_chains。前面的 `correlateEvents/reconstructTimeline/detectAnomalies`（`LinuxFilesAnalyzerEnhanced.cpp:111-184`）同理都是"查库-推理-落表"的独立引擎。

## 6. 与 LLM 的协作

`analyzeWithLLM()` 是主流程最后一步（`LinuxFilesAnalyzerCore.cpp:233-...`），跳过条件与 Windows/Android 一致：`--no-ai` 或无 `LLM_BASE_URL`。`LinuxLLMAnalysisService`（`src/network/HTTPServer/LinuxLLMAnalysisService.h`）是三个平台服务里覆盖类型最多的：25+ 种 ArtifactType，从原始 LOG_ENTRY 到 TAMPERING_INDICATOR、MIDDLEWARE_LOG、ACCOUNT_ANOMALY——也就是说它不只总结"原始记录"，还会对分析引擎产出的异常/篡改发现做二次解读。写回模式同前：5 个 `llm_*` 列原地 UPDATE。另有 `LinuxLLMAnalysisService_SystemAnalyzers.cpp` 存放按工件类型定制的分析器实现。

## 7. 与其他模块的协作 / 注意事项

- **命名陷阱（必读）**：`LinuxFilesAnalyzer/Analysis/LogCorrelationEngine` 与 `src/core/EventCorrelationEngine/` 是**两个无关模块**。前者只服务 Linux 日志（产出 linux_correlated_events）；后者是流水线级的事件关联（events.db 侧）。搜代码时别混。
- **外部依赖**：zlib/xz/bzip2/zstd（压缩日志，`CompressedLogParser.cpp` 直接链库而非 popen 外部命令）；TSK/FileExtractor；其余解析全部自研（auditd、journal、wtmp 都是二进制手工解析，可单测）。`JournalParser` 是自研的 journald 二进制格式解析器：直接读 journal 文件的 header、entry array、data object 与 field hash table（`JournalParser.h:63-74` 的结构定义）——不调 `journalctl` 是因为取证环境里通常不能（也不该）在镜像上执行二进制，这也是整个项目"用户态解析优先"哲学的体现。
- **SERVER_CLOUD 场景的输出库**叫 `oss.db` 但内容是 Linux 工件（PathManager 的 ossDb 路径，`TaskManagerAnalysis.cpp:509`）；真正的 OSS（阿里云对象存储）分析在独立的 OSSAnalyzer 模块，两者无关，只是历史命名撞车。
- **容错设计**：主流程对每个 Phase 单独 catch，一个解析器崩溃不会拖垮整个分析（错误进审计日志）；这也是为什么有些表在某些镜像上会是空的——通常是"证据不存在"而非"解析失败"，排查时先查 `linux_analysis_progress` 表。
- **auditd 聚合**：原始 auditd 一行一条（一个 syscall 拆多行），`AuditdAggregator::aggregate` 把它们按事件序号聚合成完整事件再入库（`AuditdAggregator.h:95-99`），否则没法按"一次文件操作"来分析。

## 8. 如何验证与扩展

- 测试相当齐全：`test_linux_analyzer_gtest.cpp`（主流程）、`test_linux_enhanced_parsers_gtest.cpp`、`test_linux_security_parsers_gtest.cpp`、`test_compressed_log_parser.cpp`、`test_journal_parser.cpp`、`test_auditd_aggregator.cpp`、`test_log_tampering_detector.cpp`、`test_persistence_detector.cpp`、`test_timestamp_normalizer.cpp`、`test_container_runtime_log_parser.cpp`、`test_firewall_security_log_parser.cpp`、`test_package_manager_log_parser.cpp`、`test_email_vpn_log_parser.cpp`、`test_middleware_log_parser.cpp`、`test_database_log_parser.cpp`。每个测试基本对应一个 Parsers/ 子模块。
- 加新证据类型：解析器放 `Parsers/`（输入用 `queryFilesByPattern` 定位 + `getExtractPath`/`extractFileToPath` 提取，复杂格式参考 `JournalParser` 的二进制解析或 `TimestampNormalizer` 的时间规整），落表加到 `linux_analysis_sql_tables.h`，然后在 `analyzeLinuxData()` 挂一个新 Phase；若要参与关联/规则分析，还需在 `LogCorrelationEngine`/`RuleEngine` 里加对应查询。
- 加新检测规则：`RuleEngine.cpp` 的规则表内联在源码里，追加一条（含 ATT&CK 编号、severity、匹配谓词）即可被 `evaluateAllRules` 和攻击链组装自动使用。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
