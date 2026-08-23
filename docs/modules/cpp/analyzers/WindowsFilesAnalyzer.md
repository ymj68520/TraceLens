# WindowsFilesAnalyzer（src/analyzers/WindowsFilesAnalyzer/）

> **一句话**：从 Windows 镜像的 raw.db 里按路径模式找出注册表、事件日志、Prefetch、LNK/JumpList、回收站、MFT、Amcache、SRUM、浏览器等系统工件，逐个提取出来解析成结构化记录，写入 windows.db（CLI 模式并入 `_files.db`）。

## 1. 为什么有这个模块

Windows 是"工件密度"最高的取证对象。一个入侵痕迹往往不落在用户文件里，而落在系统自己维护的几十种专有格式中：注册表 hive 记录了设备、账号、服务和网络痕迹；EVTX 事件日志记录登录、进程创建、服务安装；Prefetch 记录程序执行；Amcache 记录程序安装；SRUM 记录资源与网络用量；浏览器的 SQLite 记录上网行为。这些格式彼此毫无共性（二进制 hive、压缩 XML 的 evtx、自定义结构的 .pf、ESE 数据库……），人工逐个分析几乎不可行。这个模块的存在意义就是把"Windows 系统知道但不说的事"批量翻译出来。

它的方法论可以概括为**"模式匹配找文件 → 按 inode 提取 → 专有格式解析 → 落表"**。与 AndroidAnalyzer 的固定路径清单不同，Windows 的证据位置因用户名、Windows 版本而变化，所以这里全部用 SQL LIKE 模式在 raw.db 的 files 表里找（例如 `%/Users/%/NTUSER.DAT`），找到后通过 FileExtractor 按 inode + 分区号回到镜像把文件真正拷出来，再用对应解析器处理。这个"查询-提取-解析"三段式是理解所有子分析器的钥匙。

值得注意的诚实边界：并非所有表都会被填满。schema 里预留了 `shimcache_entries`、`user_assist_entries`、`rdp_connections`、`wifi_profiles`、`shell_bag_entries` 等表和对应解析函数，但当前流水线**没有调用**这些解析器（详见第 6 节的"死代码"清单）。读文档的人需要知道哪些证据"真在流水线里"，哪些只是"架子搭好了"。

## 2. 核心数据结构与接口

**工件载体结构**（`Common/WindowsDataTypes.h:13-110+`），三个代表：

```cpp
struct RegistryValue {
    std::string hivePath;           // Full path to the hive file
    std::string hiveType;           // SAM, SYSTEM, SOFTWARE, SECURITY, NTUSER
    std::string keyPath;            // Registry key path
    std::string valueName;          // Value name
    std::string valueType;          // REG_SZ, REG_DWORD, REG_BINARY, etc.
    std::string valueData;          // Value data (as string)
    int64_t lastModified;           // Last modification timestamp
    std::string forensicImportance; // HIGH, MEDIUM, LOW
};
struct EventLogEntry {
    int64_t recordId;               // Record ID
    std::string logSource;          // Security, System, Application, etc.
    int eventId;                    // Event ID
    std::string level;              // Information, Warning, Error, Critical
    // ...
};
```

`forensicImportance` 是注册表全量遍历的降噪手段——hive 里有几十万条值，靠 `determineForensicImportance(keyPath, valueName)` 预分级（HIGH/MEDIUM/LOW），调查者与 LLM 都可以优先看 HIGH。`hiveType` 把"这个值来自哪个 hive"随行携带，五类 hive 的证据在 registry_values 表里混存也能按来源筛。

**核心接口清单**（`Common/WindowsAnalyzerDeclarations.h:24-108`）：

| 方法 | 语义 | 调用方 | 失败行为 |
|------|------|--------|---------|
| `bool initialize()` | 初始化输出库与提取目录 | HTTP `TaskManagerAnalysis.cpp:470-485` / CLI `AnalysisOrchestrator.cpp:295-310` | false 即中止 |
| `void analyzeWindowsData()` | 主流程：注册表→事件日志→Prefetch→LNK→JumpList→回收站→MFT→用户配置→浏览器→计划任务/Amcache/SRUM→LLM | 两个入口的第二步 | 各子方法独立容错 |
| `void setOutputDatabasePath(path)` / `setSkipAI(bool)` | 输出库与 `--no-ai` | 入口设置 | — |
| `void analyzeWithLLM()` | 15 类工件的 LLM 增强 | 主流程尾部 | 双闸门跳过（见第 5 节） |
| `std::vector<FileRecord> queryFilesByPattern(pattern)` | 在 raw.db 按 LIKE 找未删除文件 | 所有 analyzeXxx 的第一步 | 空结果（证据不存在） |
| `bool extractFileToPath(inode, outputPath, partitionNum=-1)` | 回镜像按 inode 提取 | 每个 analyzeXxx 的第二步 | false 记日志 |
| `parseShimcacheFromRegistry/parseUserAssistFromRegistry/parseRDPConnectionsFromRegistry/parseWiFiProfilesFromRegistry` | **有完整实现、无调用方**（死代码，见第 6 节） | 无 | — |

## 3. 在流水线中的位置

两个入口：

- **HTTP 模式**：SceneDetector 检测到 WINDOWS 场景后，`TaskManagerAnalysis.cpp:470-485` 构造 `WindowsFilesAnalyzer(imagePath, dbManager)` 并 `analyzeWindowsData()`，输出 `data/tasks/<id>/<镜像名>_windows.db`（约 32 张表，含 DLLAnalyzer 用的 7 张 `dll_*` 表——建表 SQL 是共享的，见第 6 节）。
- **CLI 模式**：`--windows-analyze`，输出并入 `<镜像名>_files.db`（`AnalysisOrchestrator.cpp:295-310`），可用 `--no-ai` 跳过 AI 阶段。

输入：镜像路径 + 指向（过滤后）raw.db 的 `DatabaseManager`。工作目录约定：提取出来的中间文件放在输出库旁边的 `<镜像名>_extracted_files/`（`WindowsFilesAnalyzerCore.cpp:37-50`），按 `registry/`、`eventlogs/`、`prefetch/`、`mft/` 等子目录组织，方便人工复核。

主流程 `analyzeWindowsData()`（`WindowsFilesAnalyzerCore.cpp:63-109`）依次跑：注册表 → 事件日志 → Prefetch → LNK → JumpList → 回收站 → MFT → 用户配置 → 浏览器 → 计划任务/Amcache/SRUM → LLM 分析。

## 4. 证据来源与覆盖范围

所有取数都发生在 `analyzeWindowsData()` 调用的子方法里，每个子方法一个 `queryFilesByPattern` 模式。按证据类型分组：

| 工件类别 | raw.db 查询模式 | 解析库 / 落表 |
|---------|----------------|--------------|
| 注册表 | `%/System32/config/SYSTEM`、`.../SAM`、`.../SOFTWARE`、`%/Users/%/NTUSER.DAT` | hivex；registry_values + usb_devices / user_accounts / windows_services |
| 事件日志 | `%/System32/winevt/Logs/%.evtx`（小于 4KB 的跳过） | libevtx；event_logs |
| 程序执行 | `%/Windows/Prefetch/%.pf`、`%/Users/%/%.lnk`、`%/.../AutomaticDestinations/%.automaticDestinations-ms` + CustomDestinations、`%/Windows/AppCompat/Programs/Amcache.hve` | 自研二进制解析器；prefetch_files / lnk_files / jump_list_entries / amcache_entries |
| 文件系统 | `$MFT`、`%/$Recycle.Bin/%/$I%` | libfsntfs / 自研；mft_entries（默认前 10 万条）/ recycle_bin |
| 系统状态 | `%/Windows/System32/sru/SRUDB.dat`、`%/Windows/System32/Tasks/%` | libesedb / XML；srum_entries / scheduled_tasks |
| 浏览器 | Chrome/Edge `%/AppData/Local/<厂商>/User Data/%/History|Cookies|Bookmarks`、Firefox `%/AppData/Roaming/Mozilla/Firefox/Profiles/%/places.sqlite|cookies.sqlite`（见 `WindowsBrowserAnalyzer.cpp:31-111`） | SQLite/JSON 直接读；browser_history / browser_cookies / browser_bookmarks / browser_downloads / browser_logins |

"查询-提取"两步的真实实现（全部子分析器共用这一个函数）：

```cpp
// Core/WindowsFilesAnalyzerCore.cpp:191-235（节选）
std::vector<FileRecord> WindowsFilesAnalyzer::queryFilesByPattern(const std::string& pathPattern) {
    std::vector<FileRecord> results;
    sqlite3* db = dbManager_->getDb();
    if (!db) return results;

    // Use parameterized query to prevent SQL injection
    const char* query = "SELECT inode, name, path, size, mtime, atime, crtime, type, is_deleted, md5, "
                        "COALESCE(partition_num, 0) "
                        "FROM files WHERE path LIKE ? AND is_deleted=0";
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing query: " << sqlite3_errmsg(db) << std::endl;
        return results;
    }
    sqlite3_bind_text(stmt, 1, pathPattern.c_str(), -1, SQLITE_TRANSIENT);
    // ... 逐行读成 FileRecord（inode/path/type/is_deleted/md5/partitionNum）
```

三个要点：LIKE 模式参数化绑定（模式串来自代码常量但仍走 bind，防注入是习惯也是防御）；**`is_deleted=0` 过滤**——已删除的工件文件不会被分析（见第 6 节的补救）；`COALESCE(partition_num, 0)` 兜住旧库无此列的情形。找到后 `extractFileToPath(inode, getExtractPath(...), partitionNum)` 把字节拷到提取目录，再交给对应解析器。

### 4.1 产出表结构说明（windows.db 关键表）

| 表 | 关键列（取自真实 schema） | 取证含义 |
|----|--------------------------|---------|
| `registry_values`（`windows_analysis_sql_tables.h:12-27`） | `hive_path/hive_type/key_path/value_name/value_type/value_data/last_modified/forensic_importance` | 全量注册表值的平铺：`forensic_importance` 预筛 HIGH/MEDIUM/LOW；`last_modified` 是键级时间戳（键被改过的证据） |
| `event_logs`（:30-47） | `record_id/log_source/event_id/level/timestamp/source/message/computer_name/user_sid/channel` | EVTX 事件：event_id（4624 登录/4688 进程创建…）+ user_sid 关联到人；computer_name 确认来源机器 |
| `prefetch_files`（:50-66） | `executable_name/executable_path/prefetch_hash/run_count/last_run_time/referenced_files/referenced_directories` | 程序执行证据：run_count 量化"跑了多少次"，referenced_files 是 DLL 依赖面（DLLAnalyzer 反查的原料） |
| `user_accounts`（:110-124） | `rid/username/full_name/last_login/password_last_set/account_flags/is_admin` | SAM 提取的账号：`rid==500` 即内置管理员；后门账号常是 hidden flag |
| `usb_devices`（:127-138） | `vendor_id/product_id/serial_number/first_connected/last_connected/last_drive_letter` | USB 使用史：序列号唯一标识设备，first/last 连接时间框定接触窗口 |
| `mft_entries`（:267-290） | `entry_number/file_path/parent_entry/creation_time/fn_creation_time/is_deleted/has_ads/permissions` | MFT 级时间线：`fn_*` 列是 $FILE_NAME 属性里的时间（与 $STANDARD_INFORMATION 双时间戳交叉可测时间篡改）；`has_ads` 标记备用数据流 |
| `recycle_bin`（:141-149） | `original_path/file_name/deletion_time/original_size/user_sid` | 回收站 $I 文件：**删除时间**是别的工件都没有的事件类型 |

## 5. 解析机制走读

**链路一：注册表 hive 的递归遍历（`parseRegistryHive`，`WindowsRegistryParser.cpp:98-165`）。** `analyzeRegistryHives()`（`WindowsRegistryParser.cpp:28-96`）对 SYSTEM/SAM/SOFTWARE/NTUSER 四类 hive 都先跑这一个通用遍历：

```cpp
// Parsers/WindowsRegistryParser.cpp:113-163（节选）
    // Recursive traversal function
    std::function<void(hive_node_h, const std::string&)> traverseNode;
    traverseNode = [&](hive_node_h node, const std::string& currentPath) {
        char* nodeNameStr = hivex_node_name(hive, node);
        std::string nodeName = nodeNameStr ? nodeNameStr : "";
        if (nodeNameStr) free(nodeNameStr);

        std::string path = currentPath.empty() ?
            nodeName :
            currentPath + "\\" + nodeName;

        // Get values
        hive_value_h* nodeValues = hivex_node_values(hive, node);
        if (nodeValues) {
            for (int i = 0; nodeValues[i] != 0; i++) {
                RegistryValue regVal;
                regVal.hivePath = hivePath;
                regVal.hiveType = hiveType;
                regVal.keyPath = path;

                char* valueNameStr = hivex_value_key(hive, nodeValues[i]);
                regVal.valueName = valueNameStr ? valueNameStr : "(Default)";
                // ...
                char* data = hivex_value_value(hive, nodeValues[i], &valueType, &dataLen);
                regVal.valueType = getValueTypeName(valueType);
                regVal.valueData = convertValueData(data, dataLen, valueType);
                // ...
                regVal.forensicImportance = determineForensicImportance(path, regVal.valueName);
                regVal.lastModified = hivex_node_timestamp(hive, node); // Node timestamp applies to the key
                values.push_back(regVal);
            }
            free(nodeValues);
        }
        // Recurse children
        hive_node_h* children = hivex_node_children(hive, node);
        if (children) {
            for (int i = 0; children[i] != 0; i++) {
                traverseNode(children[i], path);
            }
            free(children);
        }
    };
    traverseNode(root, "");
```

做什么：`std::function` 自引用 lambda 做 DFS——每个节点先把键路径拼出来（反斜杠连接），枚举节点下全部值转成 `RegistryValue`（类型名翻译 + 按 REG_SZ/REG_DWORD/REG_BINARY 分别转字符串），再递归子节点。两个取证细节：`hivex_node_timestamp` 拿的是**键**的时间戳而非值的（注释特意说明），Windows 注册表本来就不记值级时间；`determineForensicImportance` 在遍历中同步打分，Run 键/USBSTOR 之类会得到 HIGH。hivex 是 C API 返回 `char*`/句柄数组，代码里逐处 free——`HiveHandle` RAII 包装管文件句柄，节点与值的手工释放是这个 C 库的固有样板。遍历完的专项解析叠在上面：SYSTEM hive 追加 USB 设备（`parseUSBDevicesFromRegistry`，`WindowsRegistryArtifacts.cpp:91+`）与服务两个专项，SAM 追加用户账号解析。

**链路二：EVTX 双段读取——正常记录 + 恢复记录（`WindowsEventLogParser.cpp:290-361`）。**

```cpp
// Parsers/WindowsEventLogParser.cpp:299-320（节选）
    // Get number of records
    int numberOfRecords = 0;
    if (libevtx_file_get_number_of_records(evtxFile, &numberOfRecords, nullptr) != 1) {
        AuditLog::instance().log("WARNING", "EVTX_RECORD_COUNT_FAILED",
            "Could not get record count for: " + logPath);
        numberOfRecords = 0;
    }

    // Get number of recovered records
    int numberOfRecoveredRecords = 0;
    if (libevtx_file_get_number_of_recovered_records(evtxFile, &numberOfRecoveredRecords, nullptr) != 1) {
        numberOfRecoveredRecords = 0;
    }

    // Pre-allocate vector for efficiency
    int totalExpected = numberOfRecords + numberOfRecoveredRecords;
    if (totalExpected > 0) {
        entries.reserve(std::min(totalExpected, 100000)); // Cap at 100k to avoid excessive memory
    }
```

关键设计是**双段读取**：先 `libevtx_file_get_number_of_records` 读正常记录，再 `libevtx_file_get_number_of_recovered_records` 读"已损坏/被清除但仍可恢复"的记录（第 303-309、331-354 行）——攻击者清日志后残存的事件就是从第二段捞回来的，恢复数单独计数并写审计日志（`EVTX_PARSE_SUCCESS` 条目里带 recovered 数）。前置检查：魔数 `ElfFile\0` 校验（`analyzeEventLogs()`，`WindowsEventLogParser.cpp:198-254`），4KB 以下文件跳过。每条记录经 `extractEventLogEntry` 抽出 recordId/时间/来源/级别/消息（FILETIME→Unix 时间换算见 `WindowsFilesAnalyzerCore.cpp:366-376`），成批 `insertEventLogEntries` 落表。内存上限 10 万条预留（第 318 行的 reserve cap）。读取失败的记录级错误只告警 continue，一个坏记录不拖垮整个日志文件。

**链路三：SAM hive → 用户账号（`parseUserAccountsFromSAM`，`WindowsRegistryArtifacts.cpp:24-89`）。** 典型的 hive 专项解析：

```cpp
// Parsers/WindowsRegistryArtifacts.cpp:42-82（节选）
    hive_node_h* nameNodes = hivex_node_children(hive, namesNode);
    if (nameNodes) {
        for (int i = 0; nameNodes[i] != 0; i++) {
            WindowsUserInfo user;

            char* username = hivex_node_name(hive, nameNodes[i]);
            user.username = username ? username : "";
            // ...
            hive_value_h defaultValue = hivex_node_get_value(hive, nameNodes[i], "");
            if (defaultValue != 0) {
                hive_type type;
                size_t len;
                if (hivex_value_type(hive, defaultValue, &type, &len) == 0) {
                    user.rid = static_cast<int>(type);
                }
            }

            char ridPath[32];
            snprintf(ridPath, sizeof(ridPath), "%08X", user.rid);
            // ... 在 Users 下按 "%08X" 名字找到用户节点，读 F 值与 V 值
            user.isAdmin = (user.rid == 500);
            users.push_back(user);
        }
```

最"怪但真实"的一步是 RID 的藏身处：`SAM\Domains\Account\Users\Names` 下每个用户子节点的**默认值（空名值）的类型字段**里存着 RID——hivex 的 `hivex_value_type` 本来是报告 REG_DWORD 之类的类型的地方，SAM 却把 RID 塞在这里。拿到 RID 后格式化成 `%08X` 去 `Users\` 下找同名节点，再读 F 值（最后登录时间等）和 V 值（全名、注释）；`rid == 500` 判定内置管理员（第 82 行）。产物写 user_accounts 表。错误路径：hive 打不开/路径走不到都返回空列表，不抛异常。

**链路四：Prefetch → 程序执行痕迹（`WindowsArtifactsParsers_ExecutionTraces.cpp:26-44`）。** `analyzePrefetchFiles()` 提取每个 `.pf` 后交给 `PrefetchParser`：按 MAM 版本号（Win10 的 30 / Win8 的 26 / Win7 的 23）解析引用文件与引用目录列表（版本差异处理见 `WindowsPrefetchParser.cpp:35-43`），产出可执行文件名、路径、运行次数、最后运行时间、prefetch 哈希。有个兜底细节值得知道：解析失败时从文件名反推（`NOTEPAD.EXE-ABC12312.pf` 的命名约定），保证至少留一条记录而不是空手而归（第 55-67 行）。

**链路五：$MFT → 全盘文件级时间线（`analyzeNTFSMetadata()`，`WindowsArtifactsParsers_SystemAnalysis.cpp:26-...`）。** 提取 `$MFT` 后用 libfsntfs 的 MFT metadata file API 逐条枚举，默认只处理前 10 万条防止内存爆掉（第 84-85 行），事务批量插入 mft_entries。相比 raw.db（来自目录项遍历），MFT 直接读 inode 记录，能覆盖更多已删除/无目录项的文件记录。

## 6. 与 LLM 的协作

`analyzeWindowsData()` 的最后一步是 `analyzeWithLLM()`（`WindowsFilesAnalyzerCore.cpp:111-177`），代码注释里写着 "MANDATORY"，但实际有两道自动跳过闸门：`--no-ai` 或未配置 `LLM_BASE_URL`（本地 LLM 无需 key，门禁看 URL，第 119-134 行）。干活的是 `WindowsLLMAnalysisService`（`src/network/HTTPServer/WindowsLLMAnalysisService.h`），覆盖 15 种工件类型（registry、event_log、prefetch、lnk、jump_list、五类 browser、mft、service、task、amcache、srum）。模式与其他平台一致：建库时给工件表补 5 个 `llm_*` 列（UPDATE 语句集中在 `src/core/DatabaseManager/SQL/windows_analysis_sql_llm.h`），分析时取 pending 行 → JSON prompt → `ModelRouter::chat()` → 原地回写。默认上限 10000 条/类型；MFT 默认排除（量太大，`options.includeMFT = false`，第 160 行）。

## 7. 与其他模块的协作 / 注意事项

- **第三方库**：hivex（注册表）、libevtx（事件日志）、libesedb（SRUM 的 ESE 库）、libfsntfs（MFT）；Prefetch/LNK/JumpList/回收站 `$I` 文件是自研二进制解析器（`WindowsLnkParser.cpp` 573 行、`WindowsPrefetchParser.cpp` 482 行，公有解析接口可单测）。
- **与 DLLAnalyzer 的关系**：windows.db 建表时一并创建了 7 张 `dll_*` 表（共享 SQL 文件 `windows_analysis_sql_tables.h`），DLLAnalyzer 把它当只读关联库查询（`AnalysisOrchestrator.cpp:351-367`）。
- **未接线的工件（重要）**：`parseShimcacheFromRegistry`（`WindowsRegistryArtifacts.cpp:339`）、`parseUserAssistFromRegistry`（第 433 行）、`parseRDPConnectionsFromRegistry`、`parseWiFiProfilesFromRegistry` 均有完整实现与落表方法，但**没有任何调用方**；`shell_bag_entries` 表有建表和 INSERT 语句但连解析器都没有。这些表在真实分析里会是空的，二次开发时可考虑把调用补上（Shimcache 接 SYSTEM hive、UserAssist/RDP 接 NTUSER.DAT 即可激活）。
- **路径规范化**：镜像里的 Windows 路径是 `\` 分隔且可能带盘符，`normalizeWindowsPath`（`WindowsFilesAnalyzerCore.cpp:317-350`）统一成 `/` 开头的 Unix 风格，与 TSK walker 的路径规范对齐；`readUTF16LEString` 只保 ASCII（非 ASCII 替换为 `?`，第 386-404 行注释解释了取舍），中文路径/内容可能丢字。
- **查询只取未删除文件**（`queryFilesByPattern` 的 SQL 带 `is_deleted=0`，`WindowsFilesAnalyzerCore.cpp:199-201`）——已删除的工件文件不会被分析，但 EVTX 内部的"恢复记录"和 MFT 层面弥补了一部分。

## 8. 如何验证与扩展

- 测试：`tests/UnitTest/test_windows_parsers_gtest.cpp`（解析器单元级，覆盖 Prefetch/LNK/注册表等）、`test_scene_database_gtest.cpp`（windows.db schema）。手工验证可用任意 Windows 测试镜像跑 `--windows-analyze`，检查 `_extracted_files/` 里提出了哪些中间文件、各表行数是否符合预期。
- 加新工件：四步——(1) 在某个 `analyzeXxx` 或新方法里 `queryFilesByPattern("<模式>")`；(2) `extractFileToPath(inode, getExtractPath(...), partitionNum)` 提出；(3) 写解析器（复杂格式优先找 libyal 系列库：libregf/libmsiecf/libolecf…）；(4) 在 `windows_analysis_sql_tables.h` 加表、`WindowsDBOperations_*.cpp` 加插入方法。参考 `analyzeAmcache()`（`WindowsArtifactsParsers_SystemAnalysis.cpp:369-411`）是最标准的样板。
- 要 LLM 也分析新表：给表补 5 个 `llm_*` 列的迁移 + 在 `windows_analysis_sql_llm.h` 加 UPDATE、在 `WindowsLLMAnalysisService` 注册 ArtifactType。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
