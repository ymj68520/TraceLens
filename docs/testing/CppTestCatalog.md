# C++ 测试目录（CppTestCatalog）

本文盘点 `tests/CMakeLists.txt` 中注册的**全部 92 条 ctest 目标**，按域分组给出：测什么（归纳自 `tests/UnitTest/` 与 `tests/integration/` 下对应源文件的测试套件与用例名）、怎么单独跑（`ctest -R <名称>`）、依赖（需要外部工具/系统库/网络时标注）。所有测试名、目标名、源文件名逐一取自源码；`tests/CMakeLists.txt:N` 形式的锚点指向目标定义行。用例数列为源码 `^TEST` 宏实测计数。feature/model-routing 分支新增的目标在表中以 **新增** 标注。

## 总览

- 根 `CMakeLists.txt:724` `enable_testing()`，`CMakeLists.txt:725` `add_subdirectory(tests)`。
- `tests/CMakeLists.txt` 共 **92 条 `add_test`**；整仓 `ctest -N` 显示 **93 个测试**——第 93 个 `http_agent_unit` 来自根 `CMakeLists.txt:746`（条件 `OpenSSL_FOUND AND SQLite3_FOUND`）引入的 `src/http_agent` 子树（`src/http_agent/CMakeLists.txt:83`），不在 `tests/CMakeLists.txt` 内（见文末"问题"第 1 条）。
- 条件注册共 8 条：
  - **SQLCipher**（2 条）：`WeChatDecryptorGTests`（`tests/CMakeLists.txt:1301`）与 `SqlCipherDatabaseGTests`（`:1342`）仅在 configure 期找到 SQLCipher 时存在；
  - **UNIX**（6 条）：`AndroidArchiveCliEndToEndTests`（`:1385`）、`AndroidArchiveHttpEndToEndTests`（`:1389`）、`AndroidFilesystemImageCliEndToEndTests`（`:1396`）、`AndroidFilesystemImageHttpEndToEndTests`（`:1401`）、`AndroidContainerHttpEndToEndTests`（`:1407`）、`AliyunImageHttpEndToEndTests`（`:1637`）——包裹在 `if(UNIX)` 内，且这 6 条固定使用 `python_service/.venv/bin/python`。
- 92 条目标中 74 条来自 71 个 GTest 单测二进制（其中 `AndroidLlmConcurrency` 一个二进制经 `--gtest_filter` 拆成 Knob/Parallel/Serial/Batch 四条）、1 条来自独立 main 的集成程序（`DLLAnalyzerIntegrationTests`）、17 条是 Python 驱动的端到端（无独立 C++ 二进制）。`tests/CMakeLists.txt` 共 **74 个 `add_executable`**：71 个 GTest 单测二进制（对应 `tests/UnitTest/` 71 个 `test_*.cpp`）、1 个集成程序、2 个**无 add_test** 的独立 main（`llm_files_test`、`test_mysql_daemon`）。
- GTest/GMock 经 `find_package(GTest QUIET)`/`find_package(GMock QUIET)`（`:5-6`）引入；libcurl 经 PkgConfig 必需（`:8`）；libarchive 为手机备份/归档族新引入的链接依赖（`HarmonyBackupTests`/`AndroidArchiveGTests` 等，`find_library(LIBARCHIVE)`）。

### 运行方式

```bash
cd build && cmake .. && cmake --build . -j$(nproc)
ctest -N                                   # 列出全部 93 个测试
ctest -R MiuiBackupHeaderTests             # 单独跑一个目标
ctest -R "ParserTests"                     # 正则批量（日志/包管理器等解析器族）
ctest -R "AndroidLlmConcurrency"           # 并发四场景（Knob/Parallel/Serial/Batch）
ctest -R DLLAnalyzerGTests --output-on-failure
./build/test_dll_analyzer_gtest --gtest_filter='PEHeaderParserTest.*'   # 直接执行 + GTest 过滤
make test / make test-cpp                  # Makefile 入口（等价 ctest --output-on-failure）
```

要点：

- `ctest -R` 匹配的是 **ctest 名称**（如 `MiuiBackupHeaderTests`），不是可执行目标名（`test_miui_backup_gtest`）；直接执行 build 树里的二进制可用 `--gtest_filter`。
- 绝大多数测试自建临时目录 / `:memory:` 或临时 SQLite 文件，**离线**可跑；例外在"依赖"列标注（SQLCipher CLI、真实样本、外部工具链、LLM stub 等）。
- `install()` 规则现在共 **5 处语句、27 个目标**：`tests/CMakeLists.txt:849-874` 的 `install(TARGETS ...)` 块覆盖 23 个测试可执行文件（`test_linux_analyzer_gtest`、`test_file_classifier`、`test_audit_log_gtest`、`test_file_carving`、`test_windows_parsers_gtest`、`test_android_analyzer_gtest`、`test_fulltext_search_gtest`、`test_image_analyzer_gtest`、`test_compressed_log_parser`、`test_journal_parser`、`test_timestamp_normalizer`、`test_auditd_aggregator`、`test_log_tampering_detector`、`test_persistence_detector`、`test_middleware_log_parser`、`test_container_runtime_log_parser`、`test_package_manager_log_parser`、`test_account_ssh_analyzer`、`test_database_log_parser`、`test_email_vpn_log_parser`、`test_firewall_security_log_parser`、`test_linux_enhanced_parsers_gtest`、`test_scene_classifier_gtest`），另有 4 处单目标语句——`test_wechat_parser_gtest`（`:1315`）、条件注册的 `test_wechat_decryptor_gtest`（`:1318`）与 `test_sqlcipher_database_gtest`（`:1343`）、`test_android_logical_source_gtest`（`:1450`）；这 27 个之外的目标仅在 build 树可用。

## 域一：Linux 取价分析器（LinuxFilesAnalyzer，17 个目标）

这一族覆盖 `src/analyzers/LinuxFilesAnalyzer/` 的解析器与分析器，是 C++ 单测的主体，也最能体现"解析器 + 分析器 + 时间归一"三层结构。

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `LinuxAnalyzerGTests`（`:104`） | `test_linux_analyzer_gtest` | `UnitTest/test_linux_analyzer_gtest.cpp`（1141 行） | 107 | 基础三解析器与集成 | 离线 |
| `CompressedLogParserTests`（`:290`） | `test_compressed_log_parser` | `UnitTest/test_compressed_log_parser.cpp` | 26 | 压缩日志透明解压 | 链接 zlib/lzma/bzip2/zstd |
| `JournalParserTests`（`:308`） | `test_journal_parser` | `UnitTest/test_journal_parser.cpp` | 30 | systemd journal | 离线 |
| `TimestampNormalizerTests`（`:326`） | `test_timestamp_normalizer` | `UnitTest/test_timestamp_normalizer.cpp` | 59 | 时间戳归一化 | 离线 |
| `AuditdAggregatorTests`（`:345`） | `test_auditd_aggregator` | `UnitTest/test_auditd_aggregator.cpp` | 25 | auditd 聚合 | 离线 |
| `LogTamperingDetectorTests`（`:371`） | `test_log_tampering_detector` | `UnitTest/test_log_tampering_detector.cpp` | 25 | 日志防篡改 | 离线 |
| `PersistenceDetectorTests`（`:391`） | `test_persistence_detector` | `UnitTest/test_persistence_detector.cpp` | 36 | 持久化后门检测 | 离线 |
| `MiddlewareLogParserTests`（`:411`） | `test_middleware_log_parser` | `UnitTest/test_middleware_log_parser.cpp` | 22 | 中间件日志（Phase 7） | 离线 |
| `ContainerRuntimeLogParserTests`（`:429`） | `test_container_runtime_log_parser` | `UnitTest/test_container_runtime_log_parser.cpp` | 36 | 容器运行时日志（Phase 8） | 离线 |
| `PackageManagerLogParserTests`（`:449`） | `test_package_manager_log_parser` | `UnitTest/test_package_manager_log_parser.cpp` | 40 | 包管理器日志（Phase 9） | 离线 |
| `AccountSSHAnalyzerTests`（`:469`） | `test_account_ssh_analyzer` | `UnitTest/test_account_ssh_analyzer.cpp` | 32 | 账户/SSH（Phase 10） | 离线 |
| `DatabaseLogParserTests`（`:487`） | `test_database_log_parser` | `UnitTest/test_database_log_parser.cpp` | 20 | 数据库日志 | 离线 |
| `EmailVPNLogParserTests`（`:507`） | `test_email_vpn_log_parser` | `UnitTest/test_email_vpn_log_parser.cpp` | 28 | 邮件/VPN 日志 | 离线 |
| `FirewallSecurityLogParserTests`（`:527`） | `test_firewall_security_log_parser` | `UnitTest/test_firewall_security_log_parser.cpp` | 40 | 防火墙/安全产品日志 | 离线 |
| `EnhancedParsersGTests`（`:550`） | `test_linux_enhanced_parsers_gtest` | `UnitTest/test_linux_enhanced_parsers_gtest.cpp` | 63 | USB/云/扩展历史/绕过（Phase 12-15） | 离线 |
| `WebServerParsersGTests`（`:571`） | `test_webserver_parsers_gtest` | `UnitTest/test_webserver_parsers_gtest.cpp` | 12 | Apache/Nginx | 离线 |
| `LinuxSecurityParsersGTests`（`:595`） | `test_linux_security_parsers_gtest` | `UnitTest/test_linux_security_parsers_gtest.cpp` | 28 | Setuid/能力/SELinux/AppArmor | 离线 |

各目标的 GTest 套件名（供 `--gtest_filter` 使用）：

- `LinuxAnalyzerGTests`：`LinuxLogParserTest`、`LinuxUserParserTest`、`LinuxHistoryParserTest`、`QueryBuilderTest`、`LinuxDataTypesTest`、`NewDataTypesTest`、`NewErrorCodesTest`、`ExtendedErrorFieldsTest`、`LinuxAnalyzerErrorTest`、`LinuxAnalyzerIntegrationTest`、`ResultTest`。
- `CompressedLogParserTests` / `JournalParserTests` / `TimestampNormalizerTests` / `AuditdAggregatorTests` / `PersistenceDetectorTests` 等：单一 `XxxTest` 套件承载全部用例（如 `TimestampNormalizerTest` 59 例覆盖各种字符串格式与边界）。
- `EnhancedParsersGTests`：`USBMountParserTest`、`CloudParserTest`、`ExtendedHistoryParserTest`、`SecurityBypassAnalyzerTest`、`TimestampNormalizerTest`、`EnhancedParsersIntegrationTest`。
- `WebServerParsersGTests`：`ApacheParserTest`、`NginxParserTest`。
- `LinuxSecurityParsersGTests`：`SetuidAnalyzerTest`、`CapabilityAnalyzerTest`、`SELinuxAnalyzerTest`、`AppArmorParserTest`、`SecurityParsersIntegrationTest`。
- `MiddlewareLogParserTests` / `ContainerRuntimeLogParserTests` / `PackageManagerLogParserTests` / `AccountSSHAnalyzerTests` / `DatabaseLogParserTests` / `EmailVPNLogParserTests` / `FirewallSecurityLogParserTests`：各自单一套件 `MiddlewareLogParserTest`（22）、`ContainerRuntimeLogParserTest`（36）、`PackageManagerLogParserTest`（40）、`AccountSSHAnalyzerTest`（32）、`DatabaseLogParserTest`（20）、`EmailVPNLogParserTest`（28）、`FirewallSecurityLogParserTest`（40）。
- `LogTamperingDetectorTests`：`LogTamperingDetectorTest`（25）。

## 域二：手机备份取证（MIUI / iOS / vivo / 鸿蒙 / 美亚 / 统一取数包，8 个目标）

feature/model-routing 分支把"手机离线备份 → 统一取数包 → 分析库"扩成多品牌矩阵，本域全部为**新增**目标。共同契约：提取器产出统一 `MobileEvidencePackage`（`.mep.db`），分析阶段仅凭包即可重建工件入库 `AndroidAnalysisDatabase`。

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `MiuiBackupHeaderTests`（`:127`） | `test_miui_backup_gtest` | `UnitTest/test_miui_backup_gtest.cpp`（1734 行） | 66 | MIUI 备份头/清单/提取/工件 | 离线；链接 duckx/OpenSSL/zlib |
| `MiuiProtoBakTests`（`:139`） **新增** | `test_miui_proto_bak_gtest` | `UnitTest/test_miui_proto_bak_gtest.cpp`（256 行） | 14 | miui_bak/_tmp_bak protobuf 记录（联系人/通话/短信/便签） | 离线 |
| `HarmonyBackupTests`（`:57`） **新增** | `test_harmony_backup_gtest` | `UnitTest/test_harmony_backup_gtest.cpp`（141 行） | 9 | 鸿蒙备份提取（`.info.json` 清单 + BASIC 分卷归档）→ 工件 → 落库 | **链接 libarchive** + OpenSSL |
| `IosBackupTests`（`:70`） **新增** | `test_ios_backup_gtest` | `UnitTest/test_ios_backup_gtest.cpp`（509 行） | 16 | iOS 逻辑备份（iTunes/Finder）：Manifest.plist/db + 哈希分片文件提取、工件解析、时间戳 | 离线（fixture 现场合成） |
| `VivoBackupTests`（`:83`） **新增** | `test_vivo_backup_gtest` | `UnitTest/test_vivo_backup_gtest.cpp`（291 行） | 13 | vivo(iQOO) 备份反混淆/提取/工件解析 | 离线（fixture 为 Python 桥产出的规范化 index JSON，不依赖 LevelDB） |
| `MobileEvidencePackageTests`（`:164`） **新增** | `test_mobile_evidence_package_gtest` | `UnitTest/test_mobile_evidence_package_gtest.cpp`（395 行） | 6 | 统一取数包 `.mep.db`：MIUI 备份→包→分析库往返、重复写幂等、拒绝非本格式 SQLite | duckx + zlib |
| `MobileEvidenceAdapterTests`（`:183`） **新增** | `test_mobile_evidence_adapters_gtest` | `UnitTest/test_mobile_evidence_adapters_gtest.cpp`（269 行） | 4 | 鸿蒙/雷电适配器的取数-分析分离契约（NOT_PRESENT 覆盖声明不丢） | libarchive |
| `MeiyaContainerTests`（`:205`） **新增** | `test_meiya_container_gtest` | `UnitTest/test_meiya_container_gtest.cpp`（367 行） | 7 | 美亚 Pico（MobileMaster FL-901）容器 XOR 掩码**自推导**与统一包适配 | zlib + OpenSSL |

细节：

- `MiuiBackupHeaderTests` 套件：`AndroidBackupHeaderTest`、`TarIndexTest`、`MiuiManifestTest`、`MiuiBackupExtractorTest`、`MiuiArtifactTest`、`QqntArtifactTest`、`WechatArtifactTest`、`MiuiDbTest`、`MiuiPathMapTest`、`InvalidCompressionField`。编译进 AndroidBackupHeader/TarIndex/MiuiBackupManifest/MiuiBackupExtractor/MiuiArtifactParsers/QqntArtifactParsers/WechatArtifactParsers/AndroidAnalysisDatabase 八个实现（`:107-117`）。
- `MiuiProtoBakTests` 套件：`MiuiBakClassifyTest`、`MiuiContactsBakTest`、`MiuiCallLogBakTest`、`MiuiSmsBakTest`、`MiuiNotesBakTest`——源文件头注明 fixture 为 MIUI 12（cepheus, V12.5.6.0）真机离线备份捕获的真实 protobuf 载荷；只编译 `MiuiBakProtoParsers.cpp`。
- `HarmonyBackupTests` 套件 `HarmonyRealBackup`：SetUp 用 `mkdtemp` 合成 `files/BASIC/com.huawei.hmos.calendardata` 的 `manage.jsonx`/`part.0.tarx`/`wal_blobx` 分卷结构，走 libarchive 解包断言工件入库。
- `IosBackupTests` 套件：`IosBackupExtractorTest`、`IosArtifactParsersTest`、`IosTimestampTest`——头注释强调 fixture 现场合成（真实 Manifest 结构 + 哈希分片），"不依赖案件证据"。
- `VivoBackupTests` 套件：`VivoDeobfuscatorTest`、`VivoBackupExtractorTest`、`VivoArtifactParsersTest`——C++ 侧直接消费 Python 桥产出的 index JSON 契约，测试二进制不需要 LevelDB。
- `MobileEvidencePackageTests` 套件：`MobileEvidencePackageTest`、`MobileEvidenceMiuiTest`；`MobileEvidenceAdapterTests` 套件：`MobileEvidencePackageTest`、`MobileEvidenceHarmonyTest`；`MeiyaContainerTests` 套件：`MeiyaCryptoTest`、`MeiyaAdapterTest`（头注释：合成容器 = 合法 SQLite + 任意掩码 XOR，不携带厂商密钥）。
- `MiuiBackupHeaderTests` 相对上一版从 59 例扩到 66 例（工件解析与路径映射补例）。

MIUI 相关但**不在 ctest**：

- `tests/test_miui_backup_e2e.sh`（23 行）：对真实备份目录跑 CLI 端到端；参数 1 默认 `/home/ymj68520/projects/Forensics/AndroidBackup`，输出 `/tmp/tracelens-miui-backup-e2e.*`。
- `tests/test_miui_backup_e2e_safety.sh`（63 行）：对上面脚本本身做安全性回归（在受控临时环境里验证其不会越界写）。

## 域三：Android 数据面（LLM / 结构 / 逻辑源 / 归档，6 个二进制 = 9 条 ctest）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `AndroidLlmGTests`（`:221`） | `test_android_llm_gtest` | `UnitTest/test_android_llm_gtest.cpp`（295 行） | 7 | Android LLM 分析持久化 | 离线 |
| `AndroidLlmConcurrency.Knob`（`:251`） **新增** | `test_android_llm_concurrency_gtest` | `UnitTest/test_android_llm_concurrency_gtest.cpp`（349 行） | 1 | `ANDROID_ARTIFACT_LLM_CONCURRENCY` 旋钮（默认 32，钳 1..64） | 起 OpenAI 兼容 stub；dotenv 读进程环境 |
| `AndroidLlmConcurrency.Parallel`（`:254`） **新增** | 同上 | 同上 | 1 | 并行 worker 真实重叠（峰值在途 ≥2）且每记录恰好一次 llm_* 回写 | 同上 |
| `AndroidLlmConcurrency.Serial`（`:257`） **新增** | 同上 | 同上 | 1 | 串行模式逐个分析全部记录 | 同上 |
| `AndroidLlmConcurrency.Batch`（`:260`） **新增** | 同上 | 同上 | 1 | 批分块并行执行 | 同上 |
| `AndroidAnalyzerGTests`（`:734`） | `test_android_analyzer_gtest` | `UnitTest/test_android_analyzer_gtest.cpp` | 26 | Android 数据结构（纯头文件） | 离线 |
| `AndroidMediaQueriesGTests`（`:749`） | `test_android_media_queries_gtest` | `UnitTest/test_android_media_queries_gtest.cpp` | 1 | 媒体查询回归 | 离线 |
| `AndroidLogicalSourceGTests`（`:1373`） | `test_android_logical_source_gtest` | `UnitTest/test_android_logical_source_gtest.cpp` | 15 | 逻辑提取源后端 | libzip 可选（`:1361` 定义 `HAVE_LIBZIP`） |
| `AndroidArchiveGTests`（`:1383`） **新增** | `test_android_archive_gtest` | `UnitTest/test_android_archive_gtest.cpp`（369 行） | 11 | AndroidPathMapper 路径映射 + 归档（ZIP/TAR/7z/AB）提取 | **链接 libarchive** + zlib + OpenSSL |

细节：

- `AndroidLlmGTests` 套件：`AndroidLlmAnalysisPersistenceTest`、`AndroidLlmMigrationTest`、`AndroidLlmProgressTest`、`AndroidLlmSqlCoverageTest` + **新增** `AndroidLlmLanguageTest`、`AndroidSourceCoverageTest`——只测 `AndroidAnalysisDatabase` 持久层，不调 LLM。
- `AndroidLlmConcurrency` 是**一个二进制拆四条 ctest**：源文件头注释解释了原因——dotenv 支持的配置读进程环境且"已见过的键不覆盖"，四个场景必须各自独立进程才有干净环境。它编入真实 `AndroidLLMAnalysisService`（三个实现文件）+ LLMClient/ModelRouter/ConfigManager（`:226-249`），对临时 `android.db` 驱动真实 worker pool，LLM 流量全部指向测试内起 stub 服务器。
- `AndroidAnalyzerGTests` 是纯头文件目标（`:728-736` 未编任何实现），12 个套件：`AppDataTest`、`BuildPropAnalysisResultTest`、`BuildPropEntryTest`、`ChatMessageTest`、`ChromeHistoryItemTest`、`DeviceInfoTest`、`ForensicAnalysisTest`、`InstalledPackageInfoTest`、`SecurityConfigTest`、`SystemConfigTest`、`UsageStatRecordTest`、`WifiNetworkTest`。
- `AndroidMediaQueriesGTests` 单用例 `DoesNotClassifyFrameworkArtifactsAsMedia`：SetUp 用 sqlite3 在临时目录建 `framework_files` 表（`framework.jar` 行），验证 `AndroidQueries` 不把系统工件算进媒体结果。
- `AndroidLogicalSourceGTests` 套件：`LogicalDirExtractorTest`、`ZipArchiveExtractorTest`——目录与 zip 两种逻辑源，绕过 TSK。
- `AndroidArchiveGTests` 套件：`AndroidPathMapperTest`、`AndroidUserdataPathMapping`——覆盖 `/data/data`、`/sdcard` 等路径到归档内条目的映射与逐条提取。
- 另注意 `:1625-1628` 的 `foreach(harmony_consumer ...)`：`test_file_extractor_text_dump`、`test_scene_classifier_gtest`、`test_text_dump_adapters` 三个既有目标被追加编译 `HarmonyBackupExtractor.cpp`（libarchive + OpenSSL），即逻辑源/导出族也回归鸿蒙提取路径。

## 域四：任务预算与断点续跑（2 个目标）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `AnalysisBudgetTests`（`:1276`） **新增** | `test_analysis_budget` | `UnitTest/test_analysis_budget_gtest.cpp`（248 行） | 20 | 任务级 `llm_max_files` 解析规则：0 继承全局、任务值直用、smart 模式钳到候选池上限 | 纯头文件目标，秒级 |
| `StageLedgerTests`（`:1651`） **新增** | `test_stage_ledger_gtest` | `UnitTest/test_stage_ledger_gtest.cpp`（211 行） | 20 | 可续跑任务的阶段台账（TaskStageLedger.h）：值语法往返 + "完成指纹 == 当前输入指纹才允许跳过" | 离线；链接 OpenSSL |

细节：

- `AnalysisBudgetTests` 套件：`AnalysisBudgetTest`、`SelectionReliabilityTest`、`SummaryListingTest`——同一数字约束 LLM 分析、知识图谱摄取与报告证据种子三条消费路径。
- `StageLedgerTests` 套件 `StageLedger`：与 `CliResumeEndToEndTests`/`TaskResumeHttpEndToEndTests`（域十）互补——单测钉住规则，E2E 钉住全链行为。

## 域五：WeChat / SQLCipher（3 个目标，2 个条件）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `WeChatDecryptorGTests`（`:1301`） | `test_wechat_decryptor_gtest` | `UnitTest/test_wechat_decryptor_gtest.cpp` | 14 | `WeChatDecryptor` 解密与 `SqlCipherDatabase` 协作 | **configure 条件** `if(SQLCIPHER_FOUND)`（`:1279`）；缺失时目标整体跳过（`:1303` 打印 Skipping 消息） |
| `WeChatParserGTests`（`:1312`） | `test_wechat_parser_gtest` | `UnitTest/test_wechat_parser_gtest.cpp` | 19 | EnMicroMsg 解析（raw sqlite3，注释明确"no SQLCipher needed"） | 离线 |
| `SqlCipherDatabaseGTests`（`:1342`） | `test_sqlcipher_database_gtest` | `UnitTest/test_sqlcipher_database_gtest.cpp` | 4 | 通用 SQLCipher 打开器（Phase 2 加密 app-DB 清点） | 同上条件；**运行期需 `sqlcipher` CLI**——缺失时用例自跳过 |

## 域六：DLL 分析器（3 个目标）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `DLLAnalyzerGTests`（`:1080`） | `test_dll_analyzer_gtest` | `UnitTest/test_dll_analyzer_gtest.cpp`（3176 行） | 180 | PE/ELF 解析、异常/依赖分析、DB schema | 离线（自合成字节流） |
| `DLLAnalyzerIntegrationTests`（`:1128`） | `test_dll_analyzer_integration` | `integration_dll_analyzer.cpp`（独立 main） | 23 | 真实样本解析全链 | `TEST_SAMPLES_DIR=tests/samples`（`:1125-1126`）：ELF 3 个 + PE 1 个 |
| `DLLAnalyzerLLMTests`（`:1176`） | `test_dll_analyzer_llm` | `UnitTest/test_dll_analyzer_llm.cpp` | 5 | `DLLAnalyzerLLMService` 选项与内容截断 | 离线（不发真实请求） |

细节：

- `DLLAnalyzerGTests` 的 17 个套件：`PEHeaderParserTest`、`PEImportExportParserTest`、`PEAnalyzerTest`、`PEConstantsTest`、`DependencyAnalyzerTest`、`DependencyNodeTest`、`AnomalyDetectorTest`、`EntropyCalculatorTest`、`DLLAnalysisDatabaseTest`、`DLLSQLSchemaTest`、`DLLAnalyzerTest`、`DataTypesIntegrationTest`、`MachineTypeEnumTest`、`RiskLevelEnumTest`、`StructureAssignmentTest`、`StructureInstantiationTest`、`SubsystemTypeEnumTest`、`NamespaceTest`。同时编入 WindowsFilesAnalyzer 的 DB 操作（Prefetch/Registry/EventLog）做取证关联。
- `DLLAnalyzerIntegrationTests` 用 `IntegrationTestRunner` 手写断言框架（非 GTest），对 `samples/elf/{libc.so.6, ld-linux.so.2, libarmadillo.so.12}` 与 `samples/pe/test_minimal.exe` 逐个解析；2026-05-14 的历史结果记录在 `tests/INTEGRATION_TEST_REPORT.md`（23/23 通过）。
- `DLLAnalyzerLLMTests` 套件 `DLLAnalyzerLLMServiceTest`：默认/自定义 `DLLAnalysisOptions`、maxContentLength 截断等纯逻辑。

## 域七：OSS / Database / Memory（5 个目标）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `OSSAnalyzerGTests`（`:1002`） | `test_oss_analyzer_gtest` | `UnitTest/test_oss_analyzer_gtest.cpp` | 11 | `OSSAnalysisDatabase` 与 Queries（注释"no SDK dependency"） | 离线 |
| `DatabaseAnalyzerGTests`（`:1036`） | `test_database_analyzer_gtest` | `UnitTest/test_database_analyzer_gtest.cpp`（563 行） | 44 | DB 解析器族与取证查询 | 链接 `mysqlclient`/`pq`；用例自建 fixture，离线 |
| `MemoryDatabaseGTests`（`:1503`） | `test_memory_database_gtest` | `UnitTest/test_memory_database_gtest.cpp` | 1 | `MemoryAnalysisDatabase` 封装 | 离线 |
| `MemoryVolatilityRunnerGTests`（`:1520`） | `test_memory_volatility_runner_gtest` | `UnitTest/test_memory_volatility_runner_gtest.cpp` | 2 | `Volatility3Runner` 子进程封装探测 | **不需要**真实 vol：找不到返回空即通过 |
| `MemoryParsersGTests`（`:1542`） | `test_memory_parsers_gtest` | `UnitTest/test_memory_parsers_gtest.cpp` | 5 | 四个内存 JSON 解析器 | 离线 |

细节：

- `DatabaseAnalyzerGTests` 单套件 `DatabaseAnalyzerTest` 44 例；编译进 SQLiteAnalyzer(+Forensics)/MySQLAnalyzer/MySQLDaemon/PostgreSQLAnalyzer(+PostgreSQLDaemon)/MySQLBinlogParser/InnoDBParser/PostgreSQLHeapParser/DBParserFactory/DBAnalysisDatabase(+Queries)；include 路径仍硬编码 `/usr/include/postgresql`、`/usr/include/postgresql/16/server` 与 `/usr/include/mysql`（`:1029-1031`，另 `:1193`），换发行版/版本需调整。
- `MemoryParsersGTests` 套件 `MemoryParsersTest`：ProcessParser/NetworkParser/BashHistoryParser/BootTimeParser；源文件注释强调 fixture"mirror the ACTUAL Volatility3 2.x JSON renderer output"。

## 域八：场景（Scene）与任务序列化（6 个目标 + 2 个脚本）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `FileClassifierTests`（`:639`） | `test_file_classifier` | `UnitTest/test_file_classifier.cpp` | 41 | 分类器 + FileCategory + SceneRules | 离线 |
| `SceneClassifierGTests`（`:677`） | `test_scene_classifier_gtest` | `UnitTest/test_scene_classifier_gtest.cpp` | 40 | 场景感知分类（重链接 LLM 链） | 离线（逻辑层） |
| `SceneDetectorGTests`（`:690`） | `test_scene_detector_gtest` | `UnitTest/test_scene_detector_gtest.cpp` | 8 | 平台自动判定（raw DB 路径） | 离线 |
| `SceneDatabaseGTests`（`:1473`） | `test_scene_database_gtest` | `UnitTest/test_scene_database_gtest.cpp` | 18 | 场景特化 SQL schema | 离线 |
| `ScenePerformanceGTests`（`:1481`） | `test_scene_performance_gtest` | `UnitTest/test_scene_performance_gtest.cpp` | 11 | 场景化 LLM 优化特征 | 离线 |
| `TaskScenarioTests`（`:1264`） | `test_task_scenarios` | `UnitTest/test_task_scenarios_gtest.cpp` | 22 | `ForensicScenario` 序列化与兼容 | 离线 |

细节：

- `FileClassifierTests` 套件：`FileClassifierTest`、`FileCategoryTest`、`SceneClassifierTest`；编译进 FileClassifier 四实现 + EncryptionUtils + ConfigManager/PathManager/Logger。
- `SceneClassifierGTests` 是链接面最重的单测之一（编入 LLMAnalysisService/LLMScratch/ModelRouter/FileAnalyzer/LLMClient/FileContentExtractor/FileTextProcessor/MarkitdownProxy/ThreadPool/PDFAnalyzer/OfficeAnalyzer），本分支又追加编入 `HarmonyBackupExtractor.cpp`（`:1625-1628`）；用例数从 19 扩到 40。
- `TaskScenarioTests` 套件：`AnalysisTaskTest`、`ForensicScenarioTest`、`SceneConfigTest`，验证 nlohmann::json 往返与向后兼容；本分支扩到 22 例（预算/断点字段）。

配套集成脚本（非 ctest）：

- `tests/test_scene_api.sh`（109 行）：启动 `build/forensic_analyzer --http-server 18080`，对不存在任务探测 `/api/tasks/<id>/scene-stats`、`/scene-artifacts?scene_type=android`、无参、非法 scene_type 四种调用的状态码契约，随后清理进程。
- `tests/test_scene_integration.sh`（114 行）：重建工程 → 准备 Android 镜像（见问题 3）→ `forensic_analyzer --android-analyze --db-dir` → 校验 `_raw/_files/_events.db` 三件套、`files` 表 `scene_type='android'` 行数、`scene_priority` 列存在、"不产生独立 `_android.db`"、事件计数。

## 域九：核心模块 / 网络 / 导出 / 报告 / 容错（22 个目标）

| ctest 名称 | 目标 | 源文件 | 用例 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| `ConfigManagerTests`（`:933`） | `test_config_manager` | `UnitTest/test_config_manager.cpp` | 6 | .env/dotenv 配置加载（每用例独立临时目录） | 离线 |
| `ThreadPoolTests`（`:948`） | `test_thread_pool` | `UnitTest/test_thread_pool.cpp` | 8 | 线程池 | 离线 |
| `LoggerTests`（`:958`） | `test_logger` | `UnitTest/test_logger.cpp` | 7 | 日志器 | 离线 |
| `ErrorHandlingTests`（`:968`） | `test_error_handling` | `UnitTest/test_error_handling.cpp` | 16 | `Result<T>`/`ErrorCode` 框架 | 离线 |
| `AuditLogGTests`（`:700`） | `test_audit_log_gtest` | `UnitTest/test_audit_log_gtest.cpp` | 25 | 审计日志 | 离线 |
| `EventCorrelationEngineTests`（`:1218`） | `test_event_correlation_engine` | `UnitTest/test_event_correlation_engine.cpp` | 6 | 事件关联引擎核心 | 离线 |
| `EventTimelineTests`（`:1250`） | `test_event_timeline` | `UnitTest/test_event_timeline_gtest.cpp` | 16 | 时间线导入 | 离线 |
| `FileCarvingTests`（`:709`） | `test_file_carving` | `UnitTest/test_file_carving.cpp` | 27 | 文件雕刻 | 链接 tsk |
| `FileExtractorTextDumpTests`（`:619`） | `test_file_extractor_text_dump` | `UnitTest/test_file_extractor_text_dump.cpp` | 18 | FileExtractor 文本转储 | 离线；链接 tsk + libarchive（鸿蒙追加） |
| `WindowsParsersGTests`（`:725`） | `test_windows_parsers_gtest` | `UnitTest/test_windows_parsers_gtest.cpp` | 20 | LNK/Prefetch 结构（纯头文件） | 离线 |
| `ImageAnalyzerGTests`（`:772`） | `test_image_analyzer_gtest` | `UnitTest/test_image_analyzer_gtest.cpp` | 22 | XFS 结构（纯头文件） | 离线 |
| `FullTextSearchGTests`（`:764`） | `test_fulltext_search_gtest` | `UnitTest/test_fulltext_search_gtest.cpp` | 31 | Xapian 全文检索 | 构建期需 Xapian |
| `PDFAnalyzerTests`（`:829`） | `test_pdf_analyzer` | `UnitTest/test_pdf_analyzer.cpp` | 4 | PDF 解析 | Poppler |
| `OfficeAnalyzerTests`（`:842`） | `test_office_analyzer` | `UnitTest/test_office_analyzer.cpp` | 8 | 临时 DOCX 解析 | duckx + libcurl |
| `LLMIntegrationGTests`（`:816`） | `test_llm_integration` | `UnitTest/test_llm_integration.cpp` | 25 | LLM 客户端/路由/分析器配置 | 离线（仅构造校验，不打真端点） |
| `TOONExporterTests`（`:981`） | `test_toon_exporter` | `UnitTest/test_toon_exporter.cpp` | 7 | TOON 导出 | 离线 |
| `MarkitdownProxyTests`（`:1567`） | `test_markitdown_proxy` | `UnitTest/test_markitdown_proxy.cpp` | 4 | MarkItDown 代理响应映射 | 离线（注入 mock POST） |
| `CommandLineParserTests`（`:1568`） | `test_command_line_parser` | `UnitTest/test_command_line_parser.cpp` | 12 | CLI 旗标 | 离线 |
| `TextDumpExporterTests`（`:1583`） | `test_text_dump_exporter` | `UnitTest/test_text_dump_exporter.cpp` | 11 | 转储导出纯策略 | 离线 |
| `TextDumpAdapterTests`（`:1614`） | `test_text_dump_adapters` | `UnitTest/test_text_dump_adapters.cpp` | 5 | 生产适配器桥接 | 离线；链接 tsk + libarchive（鸿蒙追加） |
| `LLMScratchTests`（`:1622`） | `test_llm_scratch_gtest` | `UnitTest/test_llm_scratch_gtest.cpp` | 3 | D4b 任务级 LLM scratch 生命周期 | 离线 |
| `ChineseReportTests`（`:268`） **新增** | `test_report_chinese_gtest` | `UnitTest/test_report_chinese_gtest.cpp`（35 行） | 1 | ReportGenerator 中文模板本地化（章节标题中文化，证据原文不翻译） | 离线 |

要点：

- `AuditLogGTests` 套件：`AuditLogConfigTest`、`AuditLogEntryTest`、`AuditLogJsonTest`、`AuditLogTest`、`AuditLogTimeTest`。
- `EventCorrelationEngineTests` 源文件注释强调用**真实临时文件**而非 `:memory:`（每个 `:memory:` 连接有独立库），这是事件链共享存储语义的关键 fixture 决策。
- `EventTimelineTests` 套件 `EventTimelineTest`；注释记录 raw.db `files` 表列名为 `size` 的契约；本分支扩到 16 例（手机事件接入）。
- `FileCarvingTests` 套件：`CarvedFileInfoTest`、`CarvingSignatureTest`、`CarvingStatisticsTest`、`FileCarverTest`、`FileCarverValidationTest`、`MagicBytesTest`。
- `FileExtractorTextDumpTests` 套件：`FileExtractorTextDumpAtomic`、`FileExtractorTextDumpPath`、`FileExtractorTextDumpQuery`、`SQLiteFixture`（链接 gtest_main + TSK + cpp_dotenv）。
- `WindowsParsersGTests` 套件：`LnkHeaderTest`、`LnkLinkFlagsTest`、`LnkFileAttributesTest`、`LnkShowCommandTest`、`PrefetchFileHeaderTest`、`PrefetchFileInfoTest`、`PrefetchVersionTest`、`PrefetchConstantsTest`、`FileExtensionTest`。
- `ImageAnalyzerGTests` 套件：`XFSSuperblockTest`、`XFSDinodeCoreTest`、`XFSDirEntryTest`、`XFSExtentTest`、`XFSFileInfoTest`、`XFSModeTest`、`NativeFileInfoTest`、`FilesystemConstantsTest`。
- `FullTextSearchGTests` 套件：`XapianIndexerTest`、`XapianSearcherTest`、`FullTextSearchIntegrationTest`、`SearchResultTest`、`FileMetadataTest`、`ContentCacheEntryTest`。
- `LLMIntegrationGTests` 套件：`LLMClientTest`、`ModelRouterTest`、`FileAnalyzerTest`、`LLMDataTypesTest`；同时编入 `libs/cpp-mcp` 五个源。
- `MarkitdownProxyTests` 套件 `MarkitdownProxyConvertOne`：以 `make_mock_poster` 注入伪 httplib POST（校验请求体 `input_root/input_file/output_root/workspace_root` 与响应映射），完全不依赖 markitdown 服务。
- `CommandLineParserTests` 套件：`CommandLineParserAndroidSource`、`CommandLineParserSizeLimit`、`InvalidSize`（对应 `--android-source` 与 `--text-dump` 大小上限）。
- `TextDumpExporterTests` 与 `TextDumpAdapterTests` 的分工：前者只链接 `src/export/TextDumpExporter.cpp`（策略纯度），后者链接 FileExtractor/MarkitdownProxy/DatabaseManager 等重依赖验证生产桥接（`:1585-1587` 注释）。
- `ErrorHandlingTests` 套件：`ErrorCodeTest`、`ResultTest`、`ResultUsageTest`、`ResultVoidTest`。
- `LLMScratchTests`（D4b）与 `python_service` 侧的 `test_d4b_*` 呼应，构成跨语言的任务级资源清理验收。
- `ChineseReportTests` 单用例 `ChineseReport.LocalizesTemplateAndCountsWithoutTranslatingEvidence`：临时目录建 `files.db`（植入英文证据原文），断言模板章节数中文化且证据文本原样保留。

## 域十：Python 驱动的 ctest 端到端（17 条 ctest）

这些 ctest 条目没有独立 C++ 二进制，直接以 `forensic_analyzer`（Generator 表达式 `$<TARGET_FILE:forensic_analyzer>`）+ Python 驱动脚本运行；脚本位于 `tests/integration/`。按主题分组；**TIMEOUT** 为 ctest 属性实测值。

### Android 归档 / 容器 / 文件系统镜像（5 条，全部 `if(UNIX)` + venv python）

| ctest 名称 | 脚本 | 超时 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- |
| `AndroidArchiveCliEndToEndTests`（`:1385`） **新增** | `test_android_container_cli_e2e.py`（242 行） | 180s | 合成 Android 目录 → dir/ZIP/TAR/7z/AB 五种容器 → 真实 AndroidAnalyzer 行；7z fixture 经 ctypes 走 libarchive writer C API | `forensic_analyzer`；venv python |
| `AndroidArchiveHttpEndToEndTests`（`:1389`） **新增** | `test_android_archive_http_e2e.py`（89 行） | 180s | 同上五种容器的真实 HTTP 任务准入与提取（`PYTHONPATH=python_service`） | 同上 |
| `AndroidFilesystemImageCliEndToEndTests`（`:1396`） **新增** | `test_android_filesystem_image_e2e.py`（157 行） | 1200s | 合成 userdata EXT4/F2FS/RAW/E01 → 真实工件；**需 mke2fs、mkfs.f2fs、sload.f2fs、sgdisk、ewfacquire** | 外部工具链齐全 |
| `AndroidFilesystemImageHttpEndToEndTests`（`:1401`） **新增** | `test_android_filesystem_http_e2e.py`（166 行） | 1800s | 隔离镜像预检（校验和）→ HTTP 任务 → android.db + 覆盖度 | 同上 |
| `AndroidContainerHttpEndToEndTests`（`:1407`） **新增** | `test_android_container_http_e2e.py`（266 行） | 1800s | 合成 AOSP sparse/super 镜像 → 校验过的 HTTP 任务生产链 | 同上 |

### MIUI / 手机分析阶段 / 统一通讯图（3 条，无 UNIX 包裹）

| ctest 名称 | 脚本 | 超时 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- |
| `MiuiCliEndToEndTests`（`:1414`） | `test_miui_cli_e2e.py`（322 行） | 默认 | 临时目录合成 USTAR `.bak`（可选 zlib 压缩）+ `descript.xml` 后调 CLI 断言提取结果 | `forensic_analyzer`；python3 |
| `MobileAnalysisEndToEndTests`（`:1421`） **新增** | `test_mobile_analysis_e2e.py`（364 行） | 900s | 完整手机分析阶段：MIUI 备份 → `--mobile-extract` 出 `.mep.db` → `--mobile-package` 仅凭包重建 `android.db` → 统一通讯图 → 案件时间线 → 报告章节 | venv python（PYTHONPATH） |
| `CommGraphEndToEndTests`（`:1429`） **新增** | `test_comm_graph_e2e.py`（263 行） | 600s | 一案件双源（手机采集 + 微信导入）：电话号码等强身份键合并人员身份，统一层聚合关系图 | venv python（PYTHONPATH） |

### 鸿蒙 / 阿里云（3 条）

| ctest 名称 | 脚本 | 超时 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- |
| `HarmonyBackupCliEndToEndTests`（`:1630`） **新增** | `test_harmony_backup_cli.py`（123 行） | 默认 | 鸿蒙备份 CLI 离线端到端；`--source/--output` 可外接解密证据（不提交任何真实证据） | `forensic_analyzer` |
| `HarmonyBackupHttpEndToEndTests`（`:1633`） **新增** | `test_harmony_backup_http.py`（128 行） | 默认 | 走真实 `/api/tasks` 链，intelligence tail 用本地 stub（零模型调用） | 同上 |
| `AliyunImageHttpEndToEndTests`（`:1637`，`if(UNIX)`） **新增** | `test_aliyun_image_http.py`（231 行） | 240s | 云导出包 → 真实任务 → files/events/提取 + 原始报告门控；只有模型/图谱响应是 test double | venv python（PYTHONPATH） |

### 雷电快取（ThunderForensic，3 条）

| ctest 名称 | 脚本 | 超时 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- |
| `ThunderForensicCliEndToEndTests`（`:1435`） **新增** | `test_thunderforensic_backup_cli.py`（805 行） | 1800s | 合成 OPPO/OnePlus/vivo 三种雷电快取提取形态：非八进制 gid 首成员（libarchive 拒收）、GNU 长名、PhoneData JSON、`<package>.tar`/`.ab` 数据树、vivo root | `forensic_analyzer`；python3 |
| `ThunderForensicHttpEndToEndTests`（`:1439`） **新增** | `test_thunderforensic_backup_http.py`（158 行） | 1800s | 真实服务器（intelligence tail stub）：tar 与项目文件夹两形态归一为 `thunder-backup` 源，vendor 无关移动表携带工件 | 同上 |
| `ThunderForensicRealSampleAcceptanceTests`（`:1443`） **新增** | `test_thunderforensic_real_samples.py`（442 行） | 3600s | **真实样本**验收：对开发期三个项目文件夹（20261025OPPO/OnePlus/VIVO）跑分析；样本缺失时**干净跳过**；`--samples-root` 或 `TRACELENS_THUNDERFORENSIC_SAMPLES` 指定根 | 外部真实样本（可选） |

### 断点续跑 / 任务预算（3 条）

| ctest 名称 | 脚本 | 超时 | 测什么 | 依赖 |
| --- | --- | --- | --- | --- |
| `CliResumeEndToEndTests`（`:1656`） **新增** | `test_cli_resume_e2e.py`（228 行） | 1200s | 合成 EXT4 断点续跑：首跑全链写台账 → 重跑全跳过且库**字节级一致** → 只删 events 库重跑按需重建 → `--overwrite` | `forensic_analyzer` |
| `TaskResumeHttpEndToEndTests`（`:1660`） **新增** | `test_task_resume_http.py`（310 行） | 1800s | HTTP resume 生命周期（真实服务器）：完成 → 删 events → cancel 标 FAILED → `POST /resume` → 跳过完成阶段 → COMPLETED + 审计 | 同上 |
| `TaskBudgetHttpEndToEndTests`（`:1667`） **新增** | `test_task_budget_http.py`（242 行） | 900s | 任务级 `llm_max_files`：缺省继承全局、各合法形态回显并持久、非法值 400/`INVALID_LLM_MAX_FILES`、跨服务重启仍在 | 同上 |

### 注册但不在 ctest 清单的 integration 脚本（孤儿）

| 脚本 | 行数 | 测什么 | 现状 |
| --- | --- | --- | --- |
| `tests/integration/test_field_security_e2e.py` | 462 行 | 隔离 live C++/Python 现场认证冒烟：匿名 401、合法用户 200、角色 403、双向服务认证、`disabled` 模式降级 | **无 add_test**；`docs/android-field-security-6a.md` 将其列为手工步骤（问题 5） |
| `tests/integration/test_pipeline_report_gate_http.py` | 142 行 | C++ 任务完成必须等待摄取与报告终态（report gate） | **无 add_test 也无任何引用**（问题 5） |

## 外部依赖一览

构建期（缺失则对应目标无法编译/链接）：

| 依赖 | 影响的目标 |
| --- | --- |
| GTest + GMock | 全部 GTest 目标（`find_package(... QUIET)`，缺失时静默） |
| libcurl（PkgConfig） | `tests/CMakeLists.txt:8` 必检；LLM/Office/Markitdown 族链接 |
| **libarchive**（新增） | 手机备份族（Harmony/MobileEvidence/Meiya/AndroidArchive）+ 鸿蒙追加的三个既有目标 |
| Xapian | `FullTextSearchGTests` |
| Poppler（POPPLER_LIBRARIES） | `PDFAnalyzerTests`、`OfficeAnalyzerTests`、`LLMIntegrationGTests`、`SceneClassifierGTests`、`DLLAnalyzerLLMTests` |
| duckx + pugixml | MIUI/Android 工件族、Office、DLL LLM、统一取数包族 |
| zlib / lzma / bzip2 / zstd | `CompressedLogParserTests`、`LogTamperingDetectorTests`、MIUI/取数包族 |
| mysqlclient + pq（含服务器头） | `DatabaseAnalyzerGTests` |
| SQLCipher（find_package） | `WeChatDecryptorGTests`、`SqlCipherDatabaseGTests`（条件注册） |
| Sleuth Kit（tsk） | `FileCarvingTests`、`FileExtractorTextDumpTests`、`TextDumpAdapterTests` |
| OpenSSL | 手机备份族、WeChat 解密、DLL 族、StageLedger |
| cpp_dotenv / nlohmann_json / libzip（可选） | Config/Audit/场景/text-dump 族；libzip 仅增强 `AndroidLogicalSourceGTests` |

运行期（ctest 会跑但行为依赖环境）：

| 依赖 | 影响的目标 | 行为 |
| --- | --- | --- |
| `sqlcipher` CLI | `SqlCipherDatabaseGTests` | 缺失时用例内部自跳过 |
| `forensic_analyzer` 二进制 | 域十全部 17 条 E2E | 未构建则 ctest 直接失败 |
| `python_service/.venv/bin/python` | 6 条 UNIX 条目（硬编码 venv 路径）+ 多条 venv 条目 | venv 缺失则命令直接失败 |
| mke2fs / mkfs.f2fs / sload.f2fs / sgdisk / ewfacquire | `AndroidFilesystemImage*` 两条 | 工具缺失时脚本内报错 |
| `tests/samples/` 样本 | `DLLAnalyzerIntegrationTests` | 样本被删则运行期断言失败 |
| `TRACELENS_THUNDERFORENSIC_SAMPLES` 真实样本 | `ThunderForensicRealSampleAcceptanceTests` | 缺失时干净跳过（不算失败） |
| LLM 服务 + 仓库 `.env` | `llm_files_test`（非 ctest） | 手工联调，无自动门禁 |
| `/var/lib/mysql` | `test_mysql_daemon`（非 ctest） | 缺失时返回 0 跳过 |

## 分域快速运行示例

```bash
ctest -R "LinuxAnalyzerGTests|EnhancedParsersGTests|WebServerParsersGTests|LinuxSecurityParsersGTests"   # Linux 域
ctest -R "Backup|Miui|Meiya|MobileEvidence"                                                              # 手机备份域
ctest -R "Android"                                                                                        # Android 数据面 + E2E
ctest -R "ThunderForensic"                                                                                # 雷电三件套
ctest -R "Harmony|Aliyun"                                                                                # 鸿蒙/阿里云 E2E
ctest -R "Resume|StageLedger|AnalysisBudget|TaskBudget"                                                  # 预算/断点域
ctest -R "WeChat|SqlCipher"                                                                               # WeChat/SQLCipher 域
ctest -R "DLL"                                                                                            # DLL 三件套
ctest -R "Scene|TaskScenario"                                                                             # 场景域
ctest -R "Memory"                                                                                         # 内存域
./build/test_linux_analyzer_gtest --gtest_filter='LinuxLogParserTest.*'                                   # 单套件
./build/test_android_llm_concurrency_gtest --gtest_filter='AndroidArtifactConcurrencyKnob.*'              # 并发旋钮单场景
```

规模参考（用例数最多/源文件最大的目标）：`test_dll_analyzer_gtest` 180 例 / 3176 行、`test_linux_analyzer_gtest` 107 例 / 1141 行、`test_miui_backup_gtest` 66 例 / 1734 行、`test_linux_enhanced_parsers_gtest` 63 例、`test_timestamp_normalizer` 59 例、`test_thunderforensic_backup_cli.py` 805 行（最大 E2E 脚本）。

## 92 条 ctest 速查索引（按 ctest 名称字母序）

`AccountSSHAnalyzerTests`、`AliyunImageHttpEndToEndTests`†、`AnalysisBudgetTests`、`AndroidAnalyzerGTests`、`AndroidArchiveCliEndToEndTests`†、`AndroidArchiveGTests`、`AndroidArchiveHttpEndToEndTests`†、`AndroidContainerHttpEndToEndTests`†、`AndroidFilesystemImageCliEndToEndTests`†、`AndroidFilesystemImageHttpEndToEndTests`†、`AndroidLogicalSourceGTests`、`AndroidLlmConcurrency.Batch`、`AndroidLlmConcurrency.Knob`、`AndroidLlmConcurrency.Parallel`、`AndroidLlmConcurrency.Serial`、`AndroidLlmGTests`、`AndroidMediaQueriesGTests`、`AuditdAggregatorTests`、`AuditLogGTests`、`ChineseReportTests`、`CliResumeEndToEndTests`、`CompressedLogParserTests`、`CommGraphEndToEndTests`、`ConfigManagerTests`、`ContainerRuntimeLogParserTests`、`CommandLineParserTests`、`DatabaseAnalyzerGTests`、`DatabaseLogParserTests`、`DLLAnalyzerGTests`、`DLLAnalyzerIntegrationTests`、`DLLAnalyzerLLMTests`、`EmailVPNLogParserTests`、`EnhancedParsersGTests`、`ErrorHandlingTests`、`EventCorrelationEngineTests`、`EventTimelineTests`、`FileCarvingTests`、`FileClassifierTests`、`FileExtractorTextDumpTests`、`FirewallSecurityLogParserTests`、`FullTextSearchGTests`、`HarmonyBackupCliEndToEndTests`、`HarmonyBackupHttpEndToEndTests`、`HarmonyBackupTests`、`ImageAnalyzerGTests`、`IosBackupTests`、`JournalParserTests`、`LinuxAnalyzerGTests`、`LinuxSecurityParsersGTests`、`LLMIntegrationGTests`、`LLMScratchTests`、`LoggerTests`、`LogTamperingDetectorTests`、`MarkitdownProxyTests`、`MeiyaContainerTests`、`MemoryDatabaseGTests`、`MemoryParsersGTests`、`MemoryVolatilityRunnerGTests`、`MiddlewareLogParserTests`、`MiuiBackupHeaderTests`、`MiuiCliEndToEndTests`、`MiuiProtoBakTests`、`MobileAnalysisEndToEndTests`、`MobileEvidenceAdapterTests`、`MobileEvidencePackageTests`、`OfficeAnalyzerTests`、`OSSAnalyzerGTests`、`PackageManagerLogParserTests`、`PDFAnalyzerTests`、`PersistenceDetectorTests`、`SceneClassifierGTests`、`SceneDatabaseGTests`、`SceneDetectorGTests`、`ScenePerformanceGTests`、`SqlCipherDatabaseGTests`*、`StageLedgerTests`、`TaskBudgetHttpEndToEndTests`、`TaskResumeHttpEndToEndTests`、`TaskScenarioTests`、`TextDumpAdapterTests`、`TextDumpExporterTests`、`ThunderForensicCliEndToEndTests`、`ThunderForensicHttpEndToEndTests`、`ThunderForensicRealSampleAcceptanceTests`、`ThreadPoolTests`、`TimestampNormalizerTests`、`TOONExporterTests`、`VivoBackupTests`、`WebServerParsersGTests`、`WeChatDecryptorGTests`*、`WeChatParserGTests`、`WindowsParsersGTests`（* 号为 SQLCipher 条件目标；† 号为 `if(UNIX)` 条件目标；合计 92）。

## 不在 ctest 中的独立 main 与顶层脚本

| 条目 | 位置 | 说明 | 依赖 |
| --- | --- | --- | --- |
| `llm_files_test` | `tests/llm_files_test.cpp`，目标定义 `tests/CMakeLists.txt:876` | 独立 main（非 GTest）：加载仓库 `.env`，对 `tests/test_data_13` 的 13 个文件跑文本+视觉多模型分析，验证 ModelRouter 路由 | **需可用 LLM 服务**（text/vision BaseURL）与 `.env`；人工联调工具 |
| `test_mysql_daemon` | `tests/test_mysql_daemon.cpp`，目标定义 `:1180` | 独立 main：尝试打开本机 `/var/lib/mysql`，打不开则返回 0 跳过 | 本机 MySQL 数据目录（可选） |
| `tests/smart_select_test.cpp` **新增** | 根 `CMakeLists.txt:687-689` 以 `if(EXISTS)` 注册为 `smart_select_test`（**EXCLUDE_FROM_ALL**） | Smart 选文件手工测试台：只跑 `LLMAnalysisService::selectImportantFiles`，用法 `smart_select_test <files_db> [budget]`；已注册但不进默认构建，build 树中若已构建可直接运行（问题 6） | 需显式构建该目标（`cmake --build . --target smart_select_test`） |
| `tests/raid_validation/`（10 个 .py：7 个 test_*.py） **新增** | `test_raw/test_infer/test_integration/test_readonly_md/test_sample_manifest/test_task_integration/test_task_raw_worker + http_task_e2e + fixtures + __init__` | RAID（MD v1）解析验证：合成 MD fixture（独立编码 oracle）、真实 EWF 解码、live 隔离 RAID→Task 回归 | 无 pytest 配置收录（问题 6） |
| `tests/test_wechat_analysis.sh` | 153 行 | WeChat 管线接线自检：C++ 单测、Python 路由注册、前端页面/服务/路由/导航 | 仓库文件布局 |
| `tests/integration/test_graphiti_e2e.sh` | 端到端 | Graphiti 摄取全流程（建任务→摄取→File 实体→重析→事件同步→MD5 去重→迁移） | **需双服务已启动**（8090/8080）与 `/tmp/test_image.dd` |
| `tests/integration/test_ingestion_pipeline.py` | pytest 文件 | Graphiti 摄取管线集成（httpx + mock_task_exists） | 手工 `PYTHONPATH=python_service` 运行；不被收录 |
| `tests/test_case_analysis_extraction.py` | 196 行 | AST 静态冒烟：case-analysis 提取与跨镜像接线 | python3 |
| `tests/test_streaming_filter.py` | 111 行 | 源码级检查流式筛选函数存在与调用关系（读源文本断言） | python3 |
| `tests/verify_llm_calls.py` / `tests/diagnose_llm_api.py` | 诊断脚本 | `generate_file_descriptions` 是否真调 LLM；`/api/llm/analyze` 端点诊断 | **需运行中的服务** |
| `tests/unit/test_entity_relation_builder.py`、`tests/unit/test_file_entity_ingestor.py` | 仓库根 `tests/unit/` | `graphiti_integration` 的 Python 单测 | 需 `PYTHONPATH=python_service` 手工运行 |

## 已发现的测试层面问题

1. **`http_agent_unit` 与 tests 目录数量不符**：`ctest -N` 共 93，本文件 92 条 `add_test`；多出的 `http_agent_unit` 定义在 `src/http_agent/` 子树（根 `CMakeLists.txt:746` 条件引入，`src/http_agent/CMakeLists.txt:83`），容易被"tests 目录文档"遗漏。
2. **独立 main 脱离 ctest**：`llm_files_test`（需外部 LLM）与 `test_mysql_daemon`（需本机 MySQL 目录）均无 `add_test`，`make test` 不执行，失败不可感知。
3. **`tests/test_scene_integration.sh:34` 仍引用不存在的 `tests/create_android_image.sh`**：脚本实际在 `scripts/`；且其期望镜像 `build/test_android.img` 与生成脚本产出 `tests/android_test_gen.img` 不一致（`scripts/run_android_test.sh:27` 的同类引用也未修），最终走双静默跳过（详见 TestFixtures.md 问题 1）。
4. **条件目标的"消失"是静默的**：未装 SQLCipher 时 `WeChatDecryptorGTests`/`SqlCipherDatabaseGTests` 直接不注册（`:1303` 仅 STATUS 消息）；非 Linux 平台另有 6 条 UNIX 条目消失。`ctest -N` 数量变化不会报警，容易误判覆盖率。
5. **两条 integration 脚本无 runner**：`test_field_security_e2e.py` 只在 `docs/android-field-security-6a.md` 中作为手工步骤出现；`test_pipeline_report_gate_http.py` 无任何注册与文档引用——"report gate"回归事实上无门禁。
6. **孤儿新增测试资产**：`tests/smart_select_test.cpp`（已注册但 EXCLUDE_FROM_ALL，不进默认构建、ctest 不收录，需显式 `cmake --build . --target smart_select_test` 才产出二进制）与 `tests/raid_validation/`（Python，无 pytest 配置收录）都前缀/命名像测试却不被 ctest/pytest 收录、不易发现。
7. **6 条 UNIX E2E 硬编码 `python_service/.venv/bin/python`**：与同文件其他条目用 `python3`/`${Python3_EXECUTABLE}` 的风格不一致，venv 不存在时这些 ctest 直接失败而非跳过。
8. **`ThunderForensicRealSampleAcceptanceTests` 的 3600s 超时**依赖外部真实样本目录；CI 环境无样本时跳过无害，但样本路径仅靠环境变量约定，无清单校验。

**最后更新**: 2026-11-10（feature/model-routing 分支全面改版：92+1 条 ctest 实测清点）
