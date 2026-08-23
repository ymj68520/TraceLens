# C++ 测试目录（CppTestCatalog）

本文盘点 `tests/CMakeLists.txt` 中注册的**全部 61 个 ctest 目标**，按域分组给出：测什么（归纳自 `tests/UnitTest/` 下对应源文件的测试套件与用例名）、怎么单独跑（`ctest -R <名称>`）、依赖（需要外部工具/系统库/网络时标注）。所有测试名、目标名、源文件名逐一取自源码；`tests/CMakeLists.txt:N` 形式的锚点指向目标定义行。

## 总览

- 根 `CMakeLists.txt:571` `enable_testing()`，`CMakeLists.txt:572` `add_subdirectory(tests)`。
- `tests/CMakeLists.txt` 共 **61 条 `add_test`**；整仓 `ctest -N` 显示 **62 个测试**——第 62 个 `http_agent_unit` 来自根 `CMakeLists.txt:593` 的 `add_subdirectory(src/http_agent)`，不在 `tests/CMakeLists.txt` 内（见文末"问题"第 1 条）。
- 其中 2 条为条件注册：`WeChatDecryptorGTests`（`tests/CMakeLists.txt:1119`）与 `SqlCipherDatabaseGTests`（`:1160`）仅在 configure 期找到 SQLCipher 时存在。
- 61 个目标中 58 个是 GTest 可执行文件，1 个是独立 main 的集成程序（`DLLAnalyzerIntegrationTests`），1 个是 Python E2E 驱动（`MiuiCliEndToEndTests`），另有 1 个双注册注意点（`MarkitdownProxyTests`/`CommandLineParserTests` 同段定义）。
- GTest/GMock 经 `find_package(GTest QUIET)`/`find_package(GMock QUIET)`（`:5-6`）引入；libcurl 经 PkgConfig 必需（`:8`）。

### 运行方式

```bash
cd build && cmake .. && cmake --build . -j$(nproc)
ctest -N                                   # 列出全部 62 个测试
ctest -R MiuiBackupHeaderTests             # 单独跑一个目标
ctest -R "ParserTests"                     # 正则批量（日志/包管理器等解析器族）
ctest -R DLLAnalyzerGTests --output-on-failure
./build/test_dll_analyzer_gtest --gtest_filter='PEHeaderParserTest.*'   # 直接执行 + GTest 过滤
make test / make test-cpp                  # Makefile 入口（等价 ctest --output-on-failure）
```

要点：

- `ctest -R` 匹配的是 **ctest 名称**（如 `MiuiBackupHeaderTests`），不是可执行目标名（`test_miui_backup_gtest`）；直接执行 build 树里的二进制可用 `--gtest_filter`。
- 绝大多数测试自建临时目录 / `:memory:` 或临时 SQLite 文件，**离线**可跑；例外在"依赖"列标注（SQLCipher CLI、真实样本、外部 LLM 等）。
- `install()` 规则只覆盖部分目标（`tests/CMakeLists.txt:681-705` 的 24 个 + `:1133/:1136/:1161/:1197`），未安装目标仅在 build 树可用。

## 域一：Linux 取价分析器（LinuxFilesAnalyzer，17 个目标）

这一族覆盖 `src/analyzers/LinuxFilesAnalyzer/` 的解析器与分析器，是 C++ 单测的主体，也最能体现"解析器 + 分析器 + 时间归一"三层结构。

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `LinuxAnalyzerGTests`（`:64`） | `test_linux_analyzer_gtest` | `UnitTest/test_linux_analyzer_gtest.cpp`（1141 行） | 107 | 基础三解析器与集成 | 离线 |
| `CompressedLogParserTests`（`:125`） | `test_compressed_log_parser` | `UnitTest/test_compressed_log_parser.cpp` | 26 | 压缩日志透明解压 | 链接 zlib/lzma/bzip2/zstd |
| `JournalParserTests`（`:143`） | `test_journal_parser` | `UnitTest/test_journal_parser.cpp` | 30 | systemd journal | 离线 |
| `TimestampNormalizerTests`（`:161`） | `test_timestamp_normalizer` | `UnitTest/test_timestamp_normalizer.cpp` | 59 | 时间戳归一化 | 离线 |
| `AuditdAggregatorTests`（`:180`） | `test_auditd_aggregator` | `UnitTest/test_auditd_aggregator.cpp` | 25 | auditd 聚合 | 离线 |
| `LogTamperingDetectorTests`（`:206`） | `test_log_tampering_detector` | `UnitTest/test_log_tampering_detector.cpp` | 25 | 日志防篡改 | 离线 |
| `PersistenceDetectorTests`（`:226`） | `test_persistence_detector` | `UnitTest/test_persistence_detector.cpp` | 36 | 持久化后门检测 | 离线 |
| `MiddlewareLogParserTests`（`:246`） | `test_middleware_log_parser` | `UnitTest/test_middleware_log_parser.cpp` | 22 | 中间件日志（Phase 7） | 离线 |
| `ContainerRuntimeLogParserTests`（`:264`） | `test_container_runtime_log_parser` | `UnitTest/test_container_runtime_log_parser.cpp` | 36 | 容器运行时日志（Phase 8） | 离线 |
| `PackageManagerLogParserTests`（`:284`） | `test_package_manager_log_parser` | `UnitTest/test_package_manager_log_parser.cpp` | 40 | 包管理器日志（Phase 9） | 离线 |
| `AccountSSHAnalyzerTests`（`:304`） | `test_account_ssh_analyzer` | `UnitTest/test_account_ssh_analyzer.cpp` | 32 | 账户/SSH（Phase 10） | 离线 |
| `DatabaseLogParserTests`（`:322`） | `test_database_log_parser` | `UnitTest/test_database_log_parser.cpp` | 20 | 数据库日志 | 离线 |
| `EmailVPNLogParserTests`（`:342`） | `test_email_vpn_log_parser` | `UnitTest/test_email_vpn_log_parser.cpp` | 28 | 邮件/VPN 日志 | 离线 |
| `FirewallSecurityLogParserTests`（`:362`） | `test_firewall_security_log_parser` | `UnitTest/test_firewall_security_log_parser.cpp` | 40 | 防火墙/安全产品日志 | 离线 |
| `EnhancedParsersGTests`（`:385`） | `test_linux_enhanced_parsers_gtest` | `UnitTest/test_linux_enhanced_parsers_gtest.cpp` | 63 | USB/云/扩展历史/绕过（Phase 12-15） | 离线 |
| `WebServerParsersGTests`（`:406`） | `test_webserver_parsers_gtest` | `UnitTest/test_webserver_parsers_gtest.cpp` | 12 | Apache/Nginx | 离线 |
| `LinuxSecurityParsersGTests`（`:430`） | `test_linux_security_parsers_gtest` | `UnitTest/test_linux_security_parsers_gtest.cpp` | 28 | Setuid/能力/SELinux/AppArmor | 离线 |

各目标的 GTest 套件名（供 `--gtest_filter` 使用）：

- `LinuxAnalyzerGTests`：`LinuxLogParserTest`、`LinuxUserParserTest`、`LinuxHistoryParserTest`、`QueryBuilderTest`、`LinuxDataTypesTest`、`NewDataTypesTest`、`NewErrorCodesTest`、`ExtendedErrorFieldsTest`、`LinuxAnalyzerErrorTest`、`LinuxAnalyzerIntegrationTest`、`ResultTest`。
- `CompressedLogParserTests` / `JournalParserTests` / `TimestampNormalizerTests` / `AuditdAggregatorTests` / `PersistenceDetectorTests` 等：单一 `XxxTest` 套件承载全部用例（如 `TimestampNormalizerTest` 59 例覆盖各种字符串格式与边界）。
- `EnhancedParsersGTests`：`USBMountParserTest`、`CloudParserTest`、`ExtendedHistoryParserTest`、`SecurityBypassAnalyzerTest`、`TimestampNormalizerTest`、`EnhancedParsersIntegrationTest`。
- `WebServerParsersGTests`：`ApacheParserTest`、`NginxParserTest`。
- `LinuxSecurityParsersGTests`：`SetuidAnalyzerTest`、`CapabilityAnalyzerTest`、`SELinuxAnalyzerTest`、`AppArmorParserTest`、`SecurityParsersIntegrationTest`。
- `MiddlewareLogParserTests` / `ContainerRuntimeLogParserTests` / `PackageManagerLogParserTests` / `AccountSSHAnalyzerTests` / `DatabaseLogParserTests` / `EmailVPNLogParserTests` / `FirewallSecurityLogParserTests`：各自单一套件 `MiddlewareLogParserTest`（22）、`ContainerRuntimeLogParserTest`（36）、`PackageManagerLogParserTest`（40）、`AccountSSHAnalyzerTest`（32）、`DatabaseLogParserTest`（20）、`EmailVPNLogParserTest`（28）、`FirewallSecurityLogParserTest`（40）。
- `LogTamperingDetectorTests`：`LogTamperingDetectorTest`（25）。

## 域二：MIUI / Android（6 个 ctest 目标 + 2 个脚本）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `MiuiBackupHeaderTests`（`:87`） | `test_miui_backup_gtest` | `UnitTest/test_miui_backup_gtest.cpp`（1538 行） | 59 | MIUI 备份头/清单/提取/工件 | 离线；链接 duckx/OpenSSL/zlib |
| `AndroidLlmGTests`（`:103`） | `test_android_llm_gtest` | `UnitTest/test_android_llm_gtest.cpp` | 5 | Android LLM 分析持久化 | 离线 |
| `AndroidAnalyzerGTests`（`:567`） | `test_android_analyzer_gtest` | `UnitTest/test_android_analyzer_gtest.cpp` | 26 | Android 数据结构（纯头文件） | 离线 |
| `AndroidMediaQueriesGTests`（`:582`） | `test_android_media_queries_gtest` | `UnitTest/test_android_media_queries_gtest.cpp` | 1 | 媒体查询回归 | 离线 |
| `AndroidLogicalSourceGTests`（`:1191`） | `test_android_logical_source_gtest` | `UnitTest/test_android_logical_source_gtest.cpp` | 12 | 逻辑提取源后端 | libzip 可选（`:1178` 定义 `HAVE_LIBZIP`） |
| `MiuiCliEndToEndTests`（`:1192`） | （Python 驱动） | `integration/test_miui_cli_e2e.py` | 端到端 | CLI 级 MIUI 备份提取 | 需已构建 `forensic_analyzer`；python3 |

细节：

- `MiuiBackupHeaderTests` 套件：`AndroidBackupHeaderTest`、`TarIndexTest`、`MiuiManifestTest`、`MiuiBackupExtractorTest`、`MiuiArtifactTest`、`QqntArtifactTest`、`WechatArtifactTest`、`MiuiDbTest`、`MiuiPathMapTest`、`InvalidCompressionField`。编译进 AndroidBackupHeader/TarIndex/MiuiBackupManifest/MiuiBackupExtractor/MiuiArtifactParsers/QqntArtifactParsers/WechatArtifactParsers/AndroidAnalysisDatabase 八个实现（`:70-77`）。
- `AndroidLlmGTests` 套件：`AndroidLlmAnalysisPersistenceTest`、`AndroidLlmMigrationTest`、`AndroidLlmProgressTest`、`AndroidLlmSqlCoverageTest`——只测 `AndroidAnalysisDatabase` 持久层，不调 LLM。
- `AndroidAnalyzerGTests` 是纯头文件目标（`:561-563` 未编任何实现），12 个套件：`AppDataTest`、`BuildPropAnalysisResultTest`、`BuildPropEntryTest`、`ChatMessageTest`、`ChromeHistoryItemTest`、`DeviceInfoTest`、`ForensicAnalysisTest`、`InstalledPackageInfoTest`、`SecurityConfigTest`、`SystemConfigTest`、`UsageStatRecordTest`、`WifiNetworkTest`。
- `AndroidMediaQueriesGTests` 单用例 `DoesNotClassifyFrameworkArtifactsAsMedia`：SetUp 用 sqlite3 在临时目录建 `framework_files` 表（`framework.jar` 行），验证 `AndroidQueries` 不把系统工件算进媒体结果。
- `AndroidLogicalSourceGTests` 套件：`LogicalDirExtractorTest`、`ZipArchiveExtractorTest`——目录与 zip 两种逻辑源，绕过 TSK。
- `MiuiCliEndToEndTests`：ctest 命令为 `python3 ${CMAKE_CURRENT_SOURCE_DIR}/integration/test_miui_cli_e2e.py --analyzer $<TARGET_FILE:forensic_analyzer>`（Generator 表达式解析出 forensic_analyzer 路径），脚本在临时目录合成 USTAR `.bak`（可选 zlib 压缩）+ `descript.xml` 后调 CLI 断言提取结果。

MIUI 相关但**不在 ctest**：

- `tests/test_miui_backup_e2e.sh`（23 行）：对真实备份目录跑 CLI 端到端；参数 1 默认 `/home/ymj68520/projects/Forensics/AndroidBackup`，输出 `/tmp/tracelens-miui-backup-e2e.*`。
- `tests/test_miui_backup_e2e_safety.sh`（63 行）：对上面脚本本身做安全性回归（在受控临时环境里验证其不会越界写）。

## 域三：WeChat / SQLCipher（3 个目标，2 个条件）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `WeChatDecryptorGTests`（`:1119`） | `test_wechat_decryptor_gtest` | `UnitTest/test_wechat_decryptor_gtest.cpp` | 13 | `WeChatDecryptor` 解密与 `SqlCipherDatabase` 协作 | **configure 条件** `if(SQLCIPHER_FOUND)`（`:1097`）；缺失时目标整体跳过（`:1121` 打印 Skipping 消息） |
| `WeChatParserGTests`（`:1130`） | `test_wechat_parser_gtest` | `UnitTest/test_wechat_parser_gtest.cpp` | 19 | EnMicroMsg 解析（raw sqlite3，注释明确"no SQLCipher needed"） | 离线 |
| `SqlCipherDatabaseGTests`（`:1160`） | `test_sqlcipher_database_gtest` | `UnitTest/test_sqlcipher_database_gtest.cpp` | 4 | 通用 SQLCipher 打开器（Phase 2 加密 app-DB 清点） | 同上条件；**运行期需 `sqlcipher` CLI**——`test_sqlcipher_database_gtest.cpp:25` 以 `command -v sqlcipher` 探测，缺失时用例自跳过 |

## 域四：DLL 分析器（3 个目标）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `DLLAnalyzerGTests`（`:911`） | `test_dll_analyzer_gtest` | `UnitTest/test_dll_analyzer_gtest.cpp`（3176 行） | 180 | PE/ELF 解析、异常/依赖分析、DB schema | 离线（自合成字节流） |
| `DLLAnalyzerIntegrationTests`（`:959`） | `test_dll_analyzer_integration` | `integration_dll_analyzer.cpp`（独立 main） | 23 | 真实样本解析全链 | `TEST_SAMPLES_DIR=tests/samples`（`:956-957`）：ELF 3 个 + PE 1 个 |
| `DLLAnalyzerLLMTests`（`:1006`） | `test_dll_analyzer_llm` | `UnitTest/test_dll_analyzer_llm.cpp` | 5 | `DLLAnalyzerLLMService` 选项与内容截断 | 离线（不发真实请求） |

细节：

- `DLLAnalyzerGTests` 的 17 个套件：`PEHeaderParserTest`、`PEImportExportParserTest`、`PEAnalyzerTest`、`PEConstantsTest`、`DependencyAnalyzerTest`、`DependencyNodeTest`、`AnomalyDetectorTest`、`EntropyCalculatorTest`、`DLLAnalysisDatabaseTest`、`DLLSQLSchemaTest`、`DLLAnalyzerTest`、`DataTypesIntegrationTest`、`MachineTypeEnumTest`、`RiskLevelEnumTest`、`StructureAssignmentTest`、`StructureInstantiationTest`、`SubsystemTypeEnumTest`、`NamespaceTest`。同时编入 WindowsFilesAnalyzer 的 DB 操作（Prefetch/Registry/EventLog，`:884-888`）做取证关联。
- `DLLAnalyzerIntegrationTests` 用 `IntegrationTestRunner` 手写断言框架（非 GTest），对 `samples/elf/{libc.so.6, ld-linux.so.2, libarmadillo.so.12}` 与 `samples/pe/test_minimal.exe` 逐个解析；2026-05-14 的历史结果记录在 `tests/INTEGRATION_TEST_REPORT.md`（23/23 通过）。
- `DLLAnalyzerLLMTests` 套件 `DLLAnalyzerLLMServiceTest`：默认/自定义 `DLLAnalysisOptions`、maxContentLength 截断等纯逻辑。

## 域五：OSS / Database / Memory（6 个目标）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `OSSAnalyzerGTests`（`:833`） | `test_oss_analyzer_gtest` | `UnitTest/test_oss_analyzer_gtest.cpp` | 11 | `OSSAnalysisDatabase` 与 Queries（注释"no SDK dependency"） | 离线 |
| `DatabaseAnalyzerGTests`（`:867`） | `test_database_analyzer_gtest` | `UnitTest/test_database_analyzer_gtest.cpp`（563 行） | 44 | DB 解析器族与取证查询 | 链接 `mysqlclient`/`pq`（`:864-865`）；用例自建 fixture，离线 |
| `MemoryDatabaseGTests`（`:1250`） | `test_memory_database_gtest` | `UnitTest/test_memory_database_gtest.cpp` | 1 | `MemoryAnalysisDatabase` 封装 | 离线 |
| `MemoryVolatilityRunnerGTests`（`:1267`） | `test_memory_volatility_runner_gtest` | `UnitTest/test_memory_volatility_runner_gtest.cpp` | 2 | `Volatility3Runner` 子进程封装探测 | **不需要**真实 vol：找不到返回空即通过 |
| `MemoryParsersGTests`（`:1289`） | `test_memory_parsers_gtest` | `UnitTest/test_memory_parsers_gtest.cpp` | 5 | 四个内存 JSON 解析器 | 离线 |

细节：

- `DatabaseAnalyzerGTests` 单套件 `DatabaseAnalyzerTest` 44 例；编译进 SQLiteAnalyzer(+Forensics)/MySQLAnalyzer/MySQLDaemon/PostgreSQLAnalyzer(+PostgreSQLDaemon)/MySQLBinlogParser/InnoDBParser/PostgreSQLHeapParser/DBParserFactory/DBAnalysisDatabase(+Queries)（`:839-851`）；include 路径硬编码 `/usr/include/postgresql/16/server` 与 `/usr/include/mysql`（`:860-862`），换发行版/版本需调整。
- `MemoryParsersGTests` 套件 `MemoryParsersTest`：ProcessParser/NetworkParser/BashHistoryParser/BootTimeParser；源文件注释强调 fixture"mirror the ACTUAL Volatility3 2.x JSON renderer output"。

## 域六：场景（Scene）与任务序列化（6 个目标 + 2 个脚本）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `FileClassifierTests`（`:474`） | `test_file_classifier` | `UnitTest/test_file_classifier.cpp` | 41 | 分类器 + FileCategory + SceneRules | 离线 |
| `SceneClassifierGTests`（`:510`） | `test_scene_classifier_gtest` | `UnitTest/test_scene_classifier_gtest.cpp` | 19 | 场景感知分类（重链接 LLM 链） | 离线（逻辑层） |
| `SceneDetectorGTests`（`:523`） | `test_scene_detector_gtest` | `UnitTest/test_scene_detector_gtest.cpp` | 8 | 平台自动判定（raw DB 路径） | 离线 |
| `SceneDatabaseGTests`（`:1220`） | `test_scene_database_gtest` | `UnitTest/test_scene_database_gtest.cpp` | 18 | 场景特化 SQL schema | 离线 |
| `ScenePerformanceGTests`（`:1228`） | `test_scene_performance_gtest` | `UnitTest/test_scene_performance_gtest.cpp` | 11 | 场景化 LLM 优化特征 | 离线 |
| `TaskScenarioTests`（`:1094`） | `test_task_scenarios` | `UnitTest/test_task_scenarios_gtest.cpp` | 19 | `ForensicScenario` 序列化与兼容 | 离线 |

细节：

- `FileClassifierTests` 套件：`FileClassifierTest`、`FileCategoryTest`、`SceneClassifierTest`；编译进 FileClassifier 四实现 + EncryptionUtils + ConfigManager/PathManager/Logger（`:460-468`）。
- `SceneClassifierGTests` 是链接面最重的单测之一（`:480-503` 编入 LLMAnalysisService/LLMScratch/ModelRouter/FileAnalyzer/LLMClient/FileContentExtractor/FileTextProcessor/MarkitdownProxy/ThreadPool/PDFAnalyzer/OfficeAnalyzer）。
- `TaskScenarioTests` 套件：`AnalysisTaskTest`、`ForensicScenarioTest`、`SceneConfigTest`，验证 nlohmann::json 往返与向后兼容。

配套集成脚本（非 ctest）：

- `tests/test_scene_api.sh`（109 行）：启动 `build/forensic_analyzer --http-server 18080`，对不存在任务探测 `/api/tasks/<id>/scene-stats`、`/scene-artifacts?scene_type=android`、无参、非法 scene_type 四种调用的状态码契约，随后清理进程。
- `tests/test_scene_integration.sh`（114 行）：重建工程 → 准备 Android 镜像（见问题 3）→ `forensic_analyzer --android-analyze --db-dir` → 校验 `_raw/_files/_events.db` 三件套、`files` 表 `scene_type='android'` 行数、`scene_priority` 列存在、"不产生独立 `_android.db`"、事件计数。

## 域七：核心模块 / 网络 / 导出 / 容错（21 个目标）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `ConfigManagerTests`（`:764`） | `test_config_manager` | `UnitTest/test_config_manager.cpp` | 4 | .env/dotenv 配置加载（每用例独立临时目录） | 离线 |
| `ThreadPoolTests`（`:779`） | `test_thread_pool` | `UnitTest/test_thread_pool.cpp` | 8 | 线程池 | 离线 |
| `LoggerTests`（`:789`） | `test_logger` | `UnitTest/test_logger.cpp` | 7 | 日志器 | 离线 |
| `ErrorHandlingTests`（`:799`） | `test_error_handling` | `UnitTest/test_error_handling.cpp` | 16 | `Result<T>`/`ErrorCode` 框架 | 离线 |
| `AuditLogGTests`（`:533`） | `test_audit_log_gtest` | `UnitTest/test_audit_log_gtest.cpp` | 25 | 审计日志 | 离线 |
| `EventCorrelationEngineTests`（`:1048`） | `test_event_correlation_engine` | `UnitTest/test_event_correlation_engine.cpp` | 6 | 事件关联引擎核心 | 离线 |
| `EventTimelineTests`（`:1080`） | `test_event_timeline` | `UnitTest/test_event_timeline_gtest.cpp` | 12 | 时间线导入 | 离线 |
| `FileCarvingTests`（`:542`） | `test_file_carving` | `UnitTest/test_file_carving.cpp` | 27 | 文件雕刻 | 链接 tsk |
| `FileExtractorTextDumpTests`（`:454`） | `test_file_extractor_text_dump` | `UnitTest/test_file_extractor_text_dump.cpp` | 18 | FileExtractor 文本转储 | 离线 |
| `WindowsParsersGTests`（`:558`） | `test_windows_parsers_gtest` | `UnitTest/test_windows_parsers_gtest.cpp` | 20 | LNK/Prefetch 结构（纯头文件） | 离线 |
| `ImageAnalyzerGTests`（`:605`） | `test_image_analyzer_gtest` | `UnitTest/test_image_analyzer_gtest.cpp` | 22 | XFS 结构（纯头文件） | 离线 |
| `FullTextSearchGTests`（`:597`） | `test_fulltext_search_gtest` | `UnitTest/test_fulltext_search_gtest.cpp` | 31 | Xapian 全文检索 | 构建期需 Xapian（`:595`） |
| `PDFAnalyzerTests`（`:661`） | `test_pdf_analyzer` | `UnitTest/test_pdf_analyzer.cpp` | 4 | PDF 解析 | Poppler |
| `OfficeAnalyzerTests`（`:674`） | `test_office_analyzer` | `UnitTest/test_office_analyzer.cpp` | 8 | 临时 DOCX 解析 | duckx + libcurl |
| `LLMIntegrationGTests`（`:648`） | `test_llm_integration` | `UnitTest/test_llm_integration.cpp` | 25 | LLM 客户端/路由/分析器配置 | 离线（仅构造校验，不打真端点） |
| `TOONExporterTests`（`:812`） | `test_toon_exporter` | `UnitTest/test_toon_exporter.cpp` | 7 | TOON 导出 | 离线 |
| `MarkitdownProxyTests`（`:1312`） | `test_markitdown_proxy` | `UnitTest/test_markitdown_proxy.cpp` | 4 | MarkItDown 代理响应映射 | 离线（注入 mock POST） |
| `CommandLineParserTests`（`:1313`） | `test_command_line_parser` | `UnitTest/test_command_line_parser.cpp` | 12 | CLI 旗标 | 离线 |
| `TextDumpExporterTests`（`:1328`） | `test_text_dump_exporter` | `UnitTest/test_text_dump_exporter.cpp` | 11 | 转储导出纯策略 | 离线 |
| `TextDumpAdapterTests`（`:1359`） | `test_text_dump_adapters` | `UnitTest/test_text_dump_adapters.cpp` | 5 | 生产适配器桥接 | 离线 |
| `LLMScratchTests`（`:1367`） | `test_llm_scratch_gtest` | `UnitTest/test_llm_scratch_gtest.cpp` | 3 | D4b 任务级 LLM scratch 生命周期 | 离线 |

要点：

- `AuditLogGTests` 套件：`AuditLogConfigTest`、`AuditLogEntryTest`、`AuditLogJsonTest`、`AuditLogTest`、`AuditLogTimeTest`。
- `EventCorrelationEngineTests` 源文件注释强调用**真实临时文件**而非 `:memory:`（每个 `:memory:` 连接有独立库），这是事件链共享存储语义的关键 fixture 决策。
- `EventTimelineTests` 套件 `EventTimelineTest`；注释记录 raw.db `files` 表列名为 `size` 的契约。
- `FileCarvingTests` 套件：`CarvedFileInfoTest`、`CarvingSignatureTest`、`CarvingStatisticsTest`、`FileCarverTest`、`FileCarverValidationTest`、`MagicBytesTest`。
- `FileExtractorTextDumpTests` 套件：`FileExtractorTextDumpAtomic`、`FileExtractorTextDumpPath`、`FileExtractorTextDumpQuery`、`SQLiteFixture`（链接 gtest_main + TSK + cpp_dotenv，`:445-453`）。
- `WindowsParsersGTests` 套件：`LnkHeaderTest`、`LnkLinkFlagsTest`、`LnkFileAttributesTest`、`LnkShowCommandTest`、`PrefetchFileHeaderTest`、`PrefetchFileInfoTest`、`PrefetchVersionTest`、`PrefetchConstantsTest`、`FileExtensionTest`。
- `ImageAnalyzerGTests` 套件：`XFSSuperblockTest`、`XFSDinodeCoreTest`、`XFSDirEntryTest`、`XFSExtentTest`、`XFSFileInfoTest`、`XFSModeTest`、`NativeFileInfoTest`、`FilesystemConstantsTest`。
- `FullTextSearchGTests` 套件：`XapianIndexerTest`、`XapianSearcherTest`、`FullTextSearchIntegrationTest`、`SearchResultTest`、`FileMetadataTest`、`ContentCacheEntryTest`。
- `LLMIntegrationGTests` 套件：`LLMClientTest`、`ModelRouterTest`、`FileAnalyzerTest`、`LLMDataTypesTest`；同时编入 `libs/cpp-mcp` 五个源（`:623-627`）。
- `MarkitdownProxyTests` 套件 `MarkitdownProxyConvertOne`：以 `make_mock_poster` 注入伪 httplib POST（校验请求体 `input_root/input_file/output_root/workspace_root` 与响应映射），完全不依赖 markitdown 服务。
- `CommandLineParserTests` 套件：`CommandLineParserAndroidSource`、`CommandLineParserSizeLimit`、`InvalidSize`（对应 `--android-source` 与 `--text-dump` 大小上限）。
- `TextDumpExporterTests` 与 `TextDumpAdapterTests` 的分工：前者只链接 `src/export/TextDumpExporter.cpp`（策略纯度），后者链接 FileExtractor/MarkitdownProxy/DatabaseManager 等重依赖验证生产桥接（`tests/CMakeLists.txt:1330-1332` 注释）。
- `ErrorHandlingTests` 套件：`ErrorCodeTest`、`ResultTest`、`ResultUsageTest`、`ResultVoidTest`。
- `LLMScratchTests`（D4b）与 `python_service` 侧的 `test_d4b_*` 呼应，构成跨语言的任务级资源清理验收。

## 外部依赖一览

构建期（缺失则对应目标无法编译/链接）：

| 依赖 | 影响的目标 |
| --- | --- |
| GTest + GMock | 全部 GTest 目标（`find_package(... QUIET)`，缺失时静默） |
| libcurl（PkgConfig） | `tests/CMakeLists.txt:8` 必检；LLM/Office/Markitdown 族链接 |
| Xapian | `FullTextSearchGTests` |
| Poppler（POPPLER_LIBRARIES） | `PDFAnalyzerTests`、`OfficeAnalyzerTests`、`LLMIntegrationGTests`、`SceneClassifierGTests`、`DLLAnalyzerLLMTests` |
| duckx + pugixml | MIUI/Android 工件族、Office、DLL LLM |
| zlib / lzma / bzip2 / zstd | `CompressedLogParserTests`、`LogTamperingDetectorTests` |
| mysqlclient + pq（含服务器头） | `DatabaseAnalyzerGTests` |
| SQLCipher（find_package） | `WeChatDecryptorGTests`、`SqlCipherDatabaseGTests`（条件注册） |
| Sleuth Kit（tsk） | `FileCarvingTests`、`FileExtractorTextDumpTests`、`TextDumpAdapterTests` |
| OpenSSL | MIUI、WeChat 解密、DLL 族 |
| cpp_dotenv / nlohmann_json / libzip（可选） | Config/Audit/场景/text-dump 族；libzip 仅增强 `AndroidLogicalSourceGTests` |

运行期（ctest 会跑但行为依赖环境）：

| 依赖 | 影响的目标 | 行为 |
| --- | --- | --- |
| `sqlcipher` CLI | `SqlCipherDatabaseGTests` | 缺失时用例内部自跳过（探测见源文件 :25） |
| `forensic_analyzer` 二进制 | `MiuiCliEndToEndTests` | 未构建则 ctest 直接失败 |
| `tests/samples/` 样本 | `DLLAnalyzerIntegrationTests` | 样本被删则运行期断言失败 |
| LLM 服务 + 仓库 `.env` | `llm_files_test`（非 ctest） | 手工联调，无自动门禁 |
| `/var/lib/mysql` | `test_mysql_daemon`（非 ctest） | 缺失时返回 0 跳过 |

## 分域快速运行示例

```bash
ctest -R "LinuxAnalyzerGTests|EnhancedParsersGTests|WebServerParsersGTests|LinuxSecurityParsersGTests"   # Linux 域
ctest -R "Miui|Android"                                                                                   # MIUI/Android 域
ctest -R "WeChat|SqlCipher"                                                                               # WeChat/SQLCipher 域
ctest -R "DLL"                                                                                            # DLL 三件套
ctest -R "Scene|TaskScenario"                                                                             # 场景域
ctest -R "Memory"                                                                                         # 内存域
./build/test_linux_analyzer_gtest --gtest_filter='LinuxLogParserTest.*'                                   # 单套件
./build/test_dll_analyzer_gtest --gtest_filter='-DLLSQLSchemaTest.*'                                      # 反向过滤
```

规模参考（用例数最多/源文件最大的目标）：`test_dll_analyzer_gtest` 180 例 / 3176 行、`test_linux_analyzer_gtest` 107 例 / 1141 行、`test_linux_enhanced_parsers_gtest` 63 例、`test_miui_backup_gtest` 59 例 / 1538 行、`test_timestamp_normalizer` 59 例。

## 61 目标速查索引（按 ctest 名称字母序）

`AccountSSHAnalyzerTests`、`AndroidAnalyzerGTests`、`AndroidLlmGTests`、`AndroidLogicalSourceGTests`、`AndroidMediaQueriesGTests`、`AuditdAggregatorTests`、`AuditLogGTests`、`CompressedLogParserTests`、`ConfigManagerTests`、`ContainerRuntimeLogParserTests`、`CommandLineParserTests`、`DatabaseAnalyzerGTests`、`DatabaseLogParserTests`、`DLLAnalyzerGTests`、`DLLAnalyzerIntegrationTests`、`DLLAnalyzerLLMTests`、`EmailVPNLogParserTests`、`EnhancedParsersGTests`、`ErrorHandlingTests`、`EventCorrelationEngineTests`、`EventTimelineTests`、`FileCarvingTests`、`FileClassifierTests`、`FileExtractorTextDumpTests`、`FirewallSecurityLogParserTests`、`FullTextSearchGTests`、`ImageAnalyzerGTests`、`LinuxAnalyzerGTests`、`LinuxSecurityParsersGTests`、`LLMIntegrationGTests`、`LLMScratchTests`、`LoggerTests`、`LogTamperingDetectorTests`、`MarkitdownProxyTests`、`MemoryDatabaseGTests`、`MemoryParsersGTests`、`MemoryVolatilityRunnerGTests`、`MiddlewareLogParserTests`、`MiuiBackupHeaderTests`、`MiuiCliEndToEndTests`、`OfficeAnalyzerTests`、`OSSAnalyzerGTests`、`PackageManagerLogParserTests`、`PDFAnalyzerTests`、`PersistenceDetectorTests`、`SceneClassifierGTests`、`SceneDatabaseGTests`、`SceneDetectorGTests`、`ScenePerformanceGTests`、`SqlCipherDatabaseGTests`*、`TaskScenarioTests`、`TextDumpAdapterTests`、`TextDumpExporterTests`、`ThreadPoolTests`、`TimestampNormalizerTests`、`TOONExporterTests`、`WebServerParsersGTests`、`WeChatDecryptorGTests`*、`WeChatParserGTests`、`WindowsParsersGTests`（* 号为 SQLCipher 条件目标；`MiuiCliEndToEndTests` 为 Python 驱动；合计 61）。

## 不在 ctest 中的独立 main 与顶层脚本

| 条目 | 位置 | 说明 | 依赖 |
| --- | --- | --- | --- |
| `llm_files_test` | `tests/llm_files_test.cpp`，目标定义 `tests/CMakeLists.txt:709` | 独立 main（非 GTest）：加载仓库 `.env`，对 `tests/test_data_13` 的 13 个文件跑文本+视觉多模型分析，验证 ModelRouter 路由 | **需可用 LLM 服务**（text/vision BaseURL）与 `.env`；人工联调工具 |
| `test_mysql_daemon` | `tests/test_mysql_daemon.cpp`，目标定义 `:1010` | 独立 main：尝试打开本机 `/var/lib/mysql`，打不开则返回 0 跳过（源码注释"Skip test if environment doesn't have a testable mysql dir"） | 本机 MySQL 数据目录（可选） |
| `tests/test_wechat_analysis.sh` | 153 行 | WeChat 管线接线自检：C++ 单测、Python 路由注册、前端页面/服务/路由/导航 | 仓库文件布局 |
| `tests/integration/test_graphiti_e2e.sh` | 端到端 | Graphiti 摄取全流程（建任务→摄取→File 实体→重析→事件同步→MD5 去重→迁移） | **需双服务已启动**（8090/8080）与 `/tmp/test_image.dd` |
| `tests/integration/test_ingestion_pipeline.py` | pytest 文件 | Graphiti 摄取管线集成（httpx + mock_task_exists） | 手工 `PYTHONPATH=python_service` 运行；不被收录 |
| `tests/test_case_analysis_extraction.py` | 196 行 | AST 静态冒烟：case-analysis 提取与跨镜像接线 | python3 |
| `tests/test_streaming_filter.py` | 111 行 | 源码级检查流式筛选函数存在与调用关系（读源文本断言） | python3 |
| `tests/verify_llm_calls.py` / `tests/diagnose_llm_api.py` | 263/156 行 | 诊断：`generate_file_descriptions` 是否真调 LLM；`/api/llm/analyze` 端点诊断 | **需运行中的服务** |
| `tests/unit/test_entity_relation_builder.py`、`tests/unit/test_file_entity_ingestor.py` | 仓库根 `tests/unit/` | `graphiti_integration` 的 Python 单测 | 需 `PYTHONPATH=python_service` 手工运行 |

## 已发现的测试层面问题

1. **`http_agent_unit` 与 tests 目录数量不符**：`ctest -N` 共 62，本文件 61 条 `add_test`；多出的 `http_agent_unit` 定义在根 `CMakeLists.txt:579-595` 引入的 `src/http_agent/` 子树，容易被"tests 目录文档"遗漏。
2. **独立 main 脱离 ctest**：`llm_files_test`（需外部 LLM）与 `test_mysql_daemon`（需本机 MySQL 目录）均无 `add_test`，`make test` 不执行，失败不可感知。
3. **`tests/test_scene_integration.sh:42` 引用不存在的 `tests/create_android_image.sh`**：脚本实际在 `scripts/`；导致"创建镜像"分支永远走不到，且其期望的镜像路径 `build/test_android.img` 与生成脚本产出 `tests/android_test_gen.img` 不一致（详见 TestFixtures.md 问题 1）。
4. **条件目标的"消失"是静默的**：未装 SQLCipher 时 `WeChatDecryptorGTests`/`SqlCipherDatabaseGTests` 直接不注册（`:1121` 仅 STATUS 消息），`ctest -N` 数量变化不会报警，容易误判覆盖率。
5. **`DatabaseAnalyzerGTests` 硬编码系统头文件路径**（`/usr/include/postgresql/16/server`、`/usr/include/mysql`，`:860-862`），跨发行版构建易碎。
6. **顶层 Python 辅助脚本 `test_` 前缀无 runner**：`tests/integration/test_ingestion_pipeline.py`、`tests/unit/*.py`、`python_service/test_archive.py` 不被任何 pytest 配置收录（详见 PythonTestCatalog.md）。

**最后更新**: 2026-08-24（新建，测试目录）
