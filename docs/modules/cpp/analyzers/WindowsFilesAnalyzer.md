# WindowsFilesAnalyzer（src/analyzers/WindowsFilesAnalyzer/）

> **一句话**：从 Windows 镜像的 raw.db 里按路径模式找出注册表、事件日志、Prefetch、LNK/JumpList、回收站、MFT、Amcache、SRUM、浏览器等系统工件，逐个提取出来解析成结构化记录，写入 windows.db（CLI 模式并入 `_files.db`）。

## 1. 为什么有这个模块

Windows 是"工件密度"最高的取证对象。一个入侵痕迹往往不落在用户文件里，而落在系统自己维护的几十种专有格式中：注册表 hive 记录了设备、账号、服务和网络痕迹；EVTX 事件日志记录登录、进程创建、服务安装；Prefetch 记录程序执行；Amcache 记录程序安装；SRUM 记录资源与网络用量；浏览器的 SQLite 记录上网行为。这些格式彼此毫无共性（二进制 hive、压缩 XML 的 evtx、自定义结构的 .pf、ESE 数据库……），人工逐个分析几乎不可行。这个模块的存在意义就是把"Windows 系统知道但不说的事"批量翻译出来。

它的方法论可以概括为**"模式匹配找文件 → 按 inode 提取 → 专有格式解析 → 落表"**。与 AndroidAnalyzer 的固定路径清单不同，Windows 的证据位置因用户名、Windows 版本而变化，所以这里全部用 SQL LIKE 模式在 raw.db 的 files 表里找（例如 `%/Users/%/NTUSER.DAT`），找到后通过 FileExtractor 按 inode + 分区号回到镜像把文件真正拷出来，再用对应解析器处理。这个"查询-提取-解析"三段式是理解所有子分析器的钥匙。

值得注意的诚实边界：并非所有表都会被填满。schema 里预留了 `shimcache_entries`、`user_assist_entries`、`rdp_connections`、`wifi_profiles`、`shell_bag_entries` 等表和对应解析函数，但当前流水线**没有调用**这些解析器（详见第 6 节的"死代码"清单）。读文档的人需要知道哪些证据"真在流水线里"，哪些只是"架子搭好了"。

## 2. 在流水线中的位置

两个入口：

- **HTTP 模式**：SceneDetector 检测到 WINDOWS 场景后，`TaskManagerAnalysis.cpp:470-485` 构造 `WindowsFilesAnalyzer(imagePath, dbManager)` 并 `analyzeWindowsData()`，输出 `data/tasks/<id>/<镜像名>_windows.db`（约 32 张表，含 DLLAnalyzer 用的 7 张 `dll_*` 表——建表 SQL 是共享的，见第 6 节）。
- **CLI 模式**：`--windows-analyze`，输出并入 `<镜像名>_files.db`（`AnalysisOrchestrator.cpp:295-310`），可用 `--no-ai` 跳过 AI 阶段。

输入：镜像路径 + 指向（过滤后）raw.db 的 `DatabaseManager`。工作目录约定：提取出来的中间文件放在输出库旁边的 `<镜像名>_extracted_files/`（`WindowsFilesAnalyzerCore.cpp:37-50`），按 `registry/`、`eventlogs/`、`prefetch/`、`mft/` 等子目录组织，方便人工复核。

主流程 `analyzeWindowsData()`（`WindowsFilesAnalyzerCore.cpp:63-109`）依次跑：注册表 → 事件日志 → Prefetch → LNK → JumpList → 回收站 → MFT → 用户配置 → 浏览器 → 计划任务/Amcache/SRUM → LLM 分析。

## 3. 证据来源与覆盖范围

所有取数都发生在 `analyzeWindowsData()` 调用的子方法里，每个子方法一个 `queryFilesByPattern` 模式。按证据类型分组：

| 工件类别 | raw.db 查询模式 | 解析库 / 落表 |
|---------|----------------|--------------|
| 注册表 | `%/System32/config/SYSTEM`、`.../SAM`、`.../SOFTWARE`、`%/Users/%/NTUSER.DAT` | hivex；registry_values + usb_devices / user_accounts / windows_services |
| 事件日志 | `%/System32/winevt/Logs/%.evtx`（小于 4KB 的跳过） | libevtx；event_logs |
| 程序执行 | `%/Windows/Prefetch/%.pf`、`%/Users/%/%.lnk`、`%/.../AutomaticDestinations/%.automaticDestinations-ms` + CustomDestinations、`%/Windows/AppCompat/Programs/Amcache.hve` | 自研二进制解析器；prefetch_files / lnk_files / jump_list_entries / amcache_entries |
| 文件系统 | `$MFT`、`%/$Recycle.Bin/%/$I%` | libfsntfs / 自研；mft_entries（默认前 10 万条）/ recycle_bin |
| 系统状态 | `%/Windows/System32/sru/SRUDB.dat`、`%/Windows/System32/Tasks/%` | libesedb / XML；srum_entries / scheduled_tasks |
| 浏览器 | Chrome/Edge `%/AppData/Local/<厂商>/User Data/%/History|Cookies|Bookmarks`、Firefox `%/AppData/Roaming/Mozilla/Firefox/Profiles/%/places.sqlite|cookies.sqlite`（见 `WindowsBrowserAnalyzer.cpp:31-111`） | SQLite/JSON 直接读；browser_history / browser_cookies / browser_bookmarks / browser_downloads / browser_logins |

注册表是"一鱼多吃"的典型：`analyzeRegistryHives()`（`WindowsRegistryParser.cpp:28-96`）对 SYSTEM/SAM/SOFTWARE/NTUSER 四类 hive 先做一次通用递归遍历（`parseRegistryHive`，键值全量落 registry_values，键的时间戳来自 `hivex_node_timestamp`），然后对 SYSTEM 追加 USB 设备与服务两个专项解析，对 SAM 追加用户账号解析。

## 4. 解析机制走读

**链路一：EVTX 事件日志（含损坏恢复）。** `analyzeEventLogs()`（`WindowsEventLogParser.cpp:198-254`）先校验魔数 `ElfFile\0`，再交给 libevtx。关键设计是**双段读取**：先 `libevtx_file_get_number_of_records` 读正常记录，再 `libevtx_file_get_number_of_recovered_records` 读"已损坏/被清除但仍可恢复"的记录（第 303-309、331-354 行）——攻击者清日志后残存的事件就是从这里捞回来的，恢复数会单独计数并写审计日志。每条记录经 `extractEventLogEntry` 抽出 recordId/时间/来源/级别/消息（FILETIME→Unix 时间换算见 `WindowsFilesAnalyzerCore.cpp:366-376`），成批 `insertEventLogEntries` 落表。内存上限 10 万条预留。

**链路二：SAM hive → 用户账号。** `parseUserAccountsFromSAM`（`WindowsRegistryArtifacts.cpp:24-90`）展示了典型的 hive 专项解析：`navigateToPath` 走到 `SAM\Domains\Account\Users\Names`，枚举子节点名即用户名；RID 藏在节点默认值的类型字段里（hivex 的怪异但真实的存储方式，第 53-57 行），据此拼出 `Users/%08X` 路径找到对应用户节点，再读 F 值（最后登录时间等）和 V 值（全名、注释）；`rid == 500` 判定内置管理员（第 85 行）。产物写 user_accounts 表。

**链路三：Prefetch → 程序执行痕迹。** `analyzePrefetchFiles()`（`WindowsArtifactsParsers_ExecutionTraces.cpp:26-44`）提取每个 `.pf` 后交给 `PrefetchParser`：按 MAM 版本号（Win10 的 30 / Win8 的 26 / Win7 的 23）解析引用文件与引用目录列表（版本差异处理见 `WindowsPrefetchParser.cpp:35-43`），产出可执行文件名、路径、运行次数、最后运行时间、prefetch 哈希。有个兜底细节值得知道：解析失败时从文件名反推（`NOTEPAD.EXE-ABC12312.pf` 的命名约定），保证至少留一条记录而不是空手而归（第 55-67 行）。

**链路四：$MFT → 全盘文件级时间线。** `analyzeNTFSMetadata()`（`WindowsArtifactsParsers_SystemAnalysis.cpp:26-...`）提取 `$MFT` 后用 libfsntfs 的 MFT metadata file API 逐条枚举，默认只处理前 10 万条防止内存爆掉（第 84-85 行），事务批量插入 mft_entries。相比 raw.db（来自目录项遍历），MFT 直接读 inode 记录，能覆盖更多已删除/无目录项的文件记录。

## 5. 与 LLM 的协作

`analyzeWindowsData()` 的最后一步是 `analyzeWithLLM()`（`WindowsFilesAnalyzerCore.cpp:111-177`），代码注释里写着 "MANDATORY"，但实际有两道自动跳过闸门：`--no-ai` 或未配置 `LLM_BASE_URL`（本地 LLM 无需 key，门禁看 URL，第 119-134 行）。干活的是 `WindowsLLMAnalysisService`（`src/network/HTTPServer/WindowsLLMAnalysisService.h`），覆盖 15 种工件类型（registry、event_log、prefetch、lnk、jump_list、五类 browser、mft、service、task、amcache、srum）。模式与其他平台一致：建库时给工件表补 5 个 `llm_*` 列（UPDATE 语句集中在 `src/core/DatabaseManager/SQL/windows_analysis_sql_llm.h`），分析时取 pending 行 → JSON prompt → `ModelRouter::chat()` → 原地回写。默认上限 10000 条/类型；MFT 默认排除（量太大，`options.includeMFT = false`，第 160 行）。

## 6. 与其他模块的协作 / 注意事项

- **第三方库**：hivex（注册表）、libevtx（事件日志）、libesedb（SRUM 的 ESE 库）、libfsntfs（MFT）；Prefetch/LNK/JumpList/回收站 `$I` 文件是自研二进制解析器（`WindowsLnkParser.cpp` 573 行、`WindowsPrefetchParser.cpp` 482 行，公有解析接口可单测）。
- **与 DLLAnalyzer 的关系**：windows.db 建表时一并创建了 7 张 `dll_*` 表（共享 SQL 文件 `windows_analysis_sql_tables.h`），DLLAnalyzer 把它当只读关联库查询（`AnalysisOrchestrator.cpp:351-367`）。
- **未接线的工件（重要）**：`parseShimcacheFromRegistry`（`WindowsRegistryArtifacts.cpp:339`）、`parseUserAssistFromRegistry`（第 433 行）、`parseRDPConnectionsFromRegistry`、`parseWiFiProfilesFromRegistry` 均有完整实现与落表方法，但**没有任何调用方**；`shell_bag_entries` 表有建表和 INSERT 语句但连解析器都没有。这些表在真实分析里会是空的，二次开发时可考虑把调用补上（Shimcache 接 SYSTEM hive、UserAssist/RDP 接 NTUSER.DAT 即可激活）。
- **路径规范化**：镜像里的 Windows 路径是 `\` 分隔且可能带盘符，`normalizeWindowsPath`（`WindowsFilesAnalyzerCore.cpp:317-350`）统一成 `/` 开头的 Unix 风格，与 TSK walker 的路径规范对齐；`readUTF16LEString` 只保 ASCII（非 ASCII 替换为 `?`，第 386-404 行注释解释了取舍），中文路径/内容可能丢字。
- **查询只取未删除文件**（`queryFilesByPattern` 的 SQL 带 `is_deleted=0`，`WindowsFilesAnalyzerCore.cpp:199-201`）——已删除的工件文件不会被分析，但 EVTX 内部的"恢复记录"和 MFT 层面弥补了一部分。

## 7. 如何验证与扩展

- 测试：`tests/UnitTest/test_windows_parsers_gtest.cpp`（解析器单元级，覆盖 Prefetch/LNK/注册表等）、`test_scene_database_gtest.cpp`（windows.db schema）。手工验证可用任意 Windows 测试镜像跑 `--windows-analyze`，检查 `_extracted_files/` 里提出了哪些中间文件、各表行数是否符合预期。
- 加新工件：四步——(1) 在某个 `analyzeXxx` 或新方法里 `queryFilesByPattern("<模式>")`；(2) `extractFileToPath(inode, getExtractPath(...), partitionNum)` 提出；(3) 写解析器（复杂格式优先找 libyal 系列库：libregf/libmsiecf/libolecf…）；(4) 在 `windows_analysis_sql_tables.h` 加表、`WindowsDBOperations_*.cpp` 加插入方法。参考 `analyzeAmcache()`（`WindowsArtifactsParsers_SystemAnalysis.cpp:369-411`）是最标准的样板。
- 要 LLM 也分析新表：给表补 5 个 `llm_*` 列的迁移 + 在 `windows_analysis_sql_llm.h` 加 UPDATE、在 `WindowsLLMAnalysisService` 注册 ArtifactType。

**最后更新**: 2026-08-23（解释式重写）
