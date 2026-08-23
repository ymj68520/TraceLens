# LinuxFilesAnalyzer（src/analyzers/LinuxFilesAnalyzer/）

> **一句话**：Linux/服务器取证的总装车间——把 syslog/journald/auditd、账号与登录、shell 历史、持久化配置、容器与 Web 服务器、安全基线等几十类证据解析进 linux.db 的 70 多张表，再在其上跑关联、时间线、异常检测和 MITRE ATT&CK 规则引擎，产出"攻击链"级别的结论。

## 1. 为什么有这个模块

Linux 取证的证据形态是"文本为主、散布极广"。一台被入侵的服务器，入侵痕迹可能藏在 `/var/log/auth.log` 的一次 SSH 登录、`~/.bash_history` 的一条命令、`/etc/cron.d` 的一个新任务、Docker 容器日志的一次异常 exec、auditd 记录的一次文件读取——每一处单看都不起眼，串起来才是完整的入侵故事。这个模块存在的第一理由就是**穷尽地收集**：它分 21 个 Phase（代码里就这么编号的）覆盖了从系统日志到 XDG 桌面痕迹的几十类工件。

第二个理由是**从"记录"到"结论"的提升**。单纯把日志入库只是搬运；真正值钱的是把异构证据放在一起推理。模块在解析层之上建了一组分析引擎：`LogCorrelationEngine` 跨日志源关联事件、`TimelineReconstructor` 重建统一时间线并找"无法解释的空档"、`AnomalyDetector` 按内置规则标异常、`LogTamperingDetector` 专查反取证（日志清空、轮转断号、时间倒流）、`RuleEngine` 用 Sigma 风格规则匹配并映射 MITRE ATT&CK 技术编号、组装攻击链。这些引擎都读 linux.db（而不是读原始文件），体现了"先物证入库、再推理"的架构分层。

第三个理由是**对抗反取证**。攻击者删日志、压缩归档、篡改时间是常态。所以 Phase 1 特意先做压缩/轮转日志预处理（`.gz/.xz/.bz2/.zst` 解压入库），保证"历史日志"参与分析；日志防篡改检测（Phase 5.5）则专门识别轮转序列缺号（如 auth.log.2 消失）这类删除痕迹。

## 2. 在流水线中的位置

两个入口：

- **HTTP 模式**：LINUX 或 SERVER_CLOUD 场景。前者写 `data/tasks/<id>/<镜像名>_linux.db`（`TaskManagerAnalysis.cpp:486-501`）；后者复用同一个类，只是入口换成 `analyzeServerCloudArtifacts()`、输出写 `<镜像名>_oss.db`——它的实现就是一句 `analyzeLinuxData()`（`LinuxFilesAnalyzerCore.cpp:218-231`），即"服务器/云场景 = 完整 Linux 分析换了个输出库名"。
- **CLI 模式**：`--linux-analyze`，工件并入 `<镜像名>_files.db`（`AnalysisOrchestrator.cpp:312-327`）。

输入：镜像路径 + raw.db（`DatabaseManager`）。中间产物（解压的日志、提出的配置）落在输出库旁的 `<镜像名>_extracted_files/`（`LinuxFilesAnalyzerCore.cpp:55-68`）。输出：linux.db，73 张表左右（表清单在 `src/core/DatabaseManager/SQL/linux_analysis_sql_tables.h`），另有 `llm_*` 列由 `linux_analysis_sql_llm.h` 的语句维护。

主流程 `analyzeLinuxData()`（`LinuxFilesAnalyzerCore.cpp:81-216`）是理解模块的地图：21 个 Phase 的 `analyzeXxx()` 各自独立 try 级容错（前几个显式 try/catch，其余靠外层），最后依次跑五个分析引擎，再跑 LLM。

## 3. 证据来源与覆盖范围

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

持久化检测单独说明：`PersistenceType` 枚举列出 14 种机制（`LinuxDataTypes.h:592-607`），`PersistenceDetector` 对每种都有独立检测方法（`PersistenceDetector.h:29-39`），带可疑模式判定（`isSuspiciousCommand/isSuspiciousSudoersRule/isSuspiciousUdevRule`）与三级风险评估。

## 4. 解析机制走读

**链路一：压缩轮转日志（Phase 1，必须最先跑）。** `analyzeCompressedLogs()` 用 `CompressedLogParser` 处理 `auth.log.2.gz` 这类文件。文件名先被拆成"基础名 + 轮转号 + 压缩扩展"（两种轮转风格 `base.N` 和 `base-日期` 都认，`CompressedLogParser.cpp:45-58`），按魔数识别压缩格式（zstd 魔数 `28 b5 2f fd` 见第 118 行），解压到临时文件后复用普通日志解析器入库。为什么必须最先跑？因为后续的日志防篡改检测要靠"完整轮转序列"判断缺号——历史日志不先入库，序列就是残缺的（`LinuxFilesAnalyzerCore.cpp:86-88` 的注释强调了这个顺序）。

**链路二：journal 解析（Phase 2.5）。** `JournalParser` 是自研的 journald 二进制格式解析器：直接读 journal 文件的 header、entry array、data object 与 field hash table（`JournalParser.h:63-74` 的结构定义），把字段-值对还原成结构化事件，落 linux_journal_entries，并单独产出"启动会话"（boot session）划分。选择自研而不是调 `journalctl`，是因为取证环境里通常不能（也不该）在镜像上执行二进制——这也是整个项目"用户态解析优先"哲学的体现。

**链路三：日志防篡改检测（Phase 5.5）。** `LogTamperingDetector` 定义了多种篡改类型：日志清空、轮转缺号（TIME_WINDOW_GAP、ROTATION_GAP 类）、时间倒流（time reversal）、journal 缺段、可疑的重复时间戳（`LogTamperingDetector.h:31-35` 的枚举）。每个检测方法扫描已入库的日志条目（输入是 linux.db，不是原始文件），产出带时间区间的 `TamperingFinding` 落 linux_tampering_findings。这是"解析层产物喂分析层"的典型例子。

**链路四：规则引擎与攻击链（最后的分析层）。** `analyzeWithRuleEngine()`（`LinuxFilesAnalyzerEnhanced.cpp:186-207`）构造 `RuleEngine(outputDbPath_)`：`evaluateAllRules()` 跑 Sigma 风格规则与 IOC 匹配，每个命中带 MITRE ATT&CK 技术编号（T1078/T1059/T1053…映射表在 `RuleEngine.cpp:38` 起）与置信度；`buildAttackChains(matches)` 把按战术（Initial Access→Execution→Persistence→…）排序的命中串成链。结果分别落 linux_rule_matches 和 linux_attack_chains。前面的 `correlateEvents/reconstructTimeline/detectAnomalies`（`LinuxFilesAnalyzerEnhanced.cpp:111-184`）同理都是"查库-推理-落表"的独立引擎。

## 5. 与 LLM 的协作

`analyzeWithLLM()` 是主流程最后一步（`LinuxFilesAnalyzerCore.cpp:233-...`），跳过条件与 Windows/Android 一致：`--no-ai` 或无 `LLM_BASE_URL`。`LinuxLLMAnalysisService`（`src/network/HTTPServer/LinuxLLMAnalysisService.h`）是三个平台服务里覆盖类型最多的：25+ 种 ArtifactType，从原始 LOG_ENTRY 到 TAMPERING_INDICATOR、MIDDLEWARE_LOG、ACCOUNT_ANOMALY——也就是说它不只总结"原始记录"，还会对分析引擎产出的异常/篡改发现做二次解读。写回模式同前：5 个 `llm_*` 列原地 UPDATE。另有 `LinuxLLMAnalysisService_SystemAnalyzers.cpp` 存放按工件类型定制的分析器实现。

## 6. 与其他模块的协作 / 注意事项

- **命名陷阱（必读）**：`LinuxFilesAnalyzer/Analysis/LogCorrelationEngine` 与 `src/core/EventCorrelationEngine/` 是**两个无关模块**。前者只服务 Linux 日志（产出 linux_correlated_events）；后者是流水线级的事件关联（events.db 侧）。搜代码时别混。
- **外部依赖**：zlib/xz/bzip2/zstd（压缩日志，`CompressedLogParser.cpp` 直接链库而非 popen 外部命令）；TSK/FileExtractor；其余解析全部自研（auditd、journal、wtmp 都是二进制手工解析，可单测）。
- **SERVER_CLOUD 场景的输出库**叫 `oss.db` 但内容是 Linux 工件（PathManager 的 ossDb 路径，`TaskManagerAnalysis.cpp:509`）；真正的 OSS（阿里云对象存储）分析在独立的 OSSAnalyzer 模块，两者无关，只是历史命名撞车。
- **容错设计**：主流程对每个 Phase 单独 catch，一个解析器崩溃不会拖垮整个分析（错误进审计日志）；这也是为什么有些表在某些镜像上会是空的——通常是"证据不存在"而非"解析失败"，排查时先查 `linux_analysis_progress` 表。
- **auditd 聚合**：原始 auditd 一行一条（一个 syscall 拆多行），`AuditdAggregator::aggregate` 把它们按事件序号聚合成完整事件再入库（`AuditdAggregator.h:95-99`），否则没法按"一次文件操作"来分析。

## 7. 如何验证与扩展

- 测试相当齐全：`test_linux_analyzer_gtest.cpp`（主流程）、`test_linux_enhanced_parsers_gtest.cpp`、`test_linux_security_parsers_gtest.cpp`、`test_compressed_log_parser.cpp`、`test_journal_parser.cpp`、`test_auditd_aggregator.cpp`、`test_log_tampering_detector.cpp`、`test_persistence_detector.cpp`、`test_timestamp_normalizer.cpp`、`test_container_runtime_log_parser.cpp`、`test_firewall_security_log_parser.cpp`、`test_package_manager_log_parser.cpp`、`test_email_vpn_log_parser.cpp`、`test_middleware_log_parser.cpp`、`test_database_log_parser.cpp`。每个测试基本对应一个 Parsers/ 子模块。
- 加新证据类型：解析器放 `Parsers/`（输入用 `queryFilesByPattern` 定位 + `getExtractPath`/`extractFileToPath` 提取，复杂格式参考 `JournalParser` 的二进制解析或 `TimestampNormalizer` 的时间规整），落表加到 `linux_analysis_sql_tables.h`，然后在 `analyzeLinuxData()` 挂一个新 Phase；若要参与关联/规则分析，还需在 `LogCorrelationEngine`/`RuleEngine` 里加对应查询。
- 加新检测规则：`RuleEngine.cpp` 的规则表内联在源码里，追加一条（含 ATT&CK 编号、severity、匹配谓词）即可被 `evaluateAllRules` 和攻击链组装自动使用。

**最后更新**: 2026-08-23（解释式重写）
