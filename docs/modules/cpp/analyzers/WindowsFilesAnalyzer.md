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

### 4.2 产出表全清单（32 张，windows_analysis_sql_tables.h）

按写入状态分三档：

**在流水线中有写入方的 19 张**：registry_values、event_logs、prefetch_files、lnk_files、jump_list_entries、user_accounts、usb_devices、recycle_bin、browser_history/downloads/bookmarks/cookies/logins（5 张）、mft_entries、windows_services、scheduled_tasks、amcache_entries、srum_entries、windows_analysis_progress。

**建表+解析器齐备但无调用方的 4 张**：wifi_profiles、rdp_connections、shimcache_entries、user_assist_entries（第 7 节死代码清单，激活=补一行调用）。

**只有表没有解析器的 2 张**：shell_bag_entries（连解析器都没有）、browser_artifacts（浏览器杂项兜底表，无写入方）。

**共享给 DLLAnalyzer 的 7 张**：dll_base_info 等（本模块建出、DLLAnalyzer 写入——两个库各有一份空/满互补的同名表）。

列级补充（关键表逐列核对，DDL 行号）：

**event_logs（17 列，:30-46）**：id、record_id（EVTX 记录号）、log_source（Security/System 等日志名）、event_id、level（Information/Warning/Error/Critical）、timestamp（Unix 秒，FILETIME 换算）、source（事件来源组件）、message（渲染后的消息文本）、computer_name、user_sid、channel + llm_* 5 列——写入条件：libevtx 正常段+恢复段双读（链路二）。

**registry_values（16 列，:12-27）**：id、hive_path、hive_type（SAM/SYSTEM/SOFTWARE/SECURITY/NTUSER 五值）、key_path、value_name（默认值记 "(Default)"）、value_type（REG_* 名）、value_data（统一字符串化）、last_modified（**键级**时间戳）、forensic_importance（HIGH/MEDIUM/LOW）+ llm_* 5 列。

**prefetch_files（14 列，:50-65）**：executable_name/executable_path/prefetch_hash/run_count/last_run_time（+多次运行时间列族）/referenced_files/referenced_directories + llm_*——run_count 与 last_run_time 是"程序执行"的核心量化。

**mft_entries（25 列，:267-289）**：entry_number/parent_entry/file_path/file_size/flags、四组 $SI 时间（creation/modification/access/entry_mod）、四组 $FILE_NAME 时间（fn_*，双时间戳篡改交叉用）、is_deleted/has_ads/permissions/attributes + llm_*。

LLM 侧语句族（windows_analysis_sql_llm.h，31 条 SELECT + UPDATE）：15 类工件的 pending 取数与回写；MFT 默认排除在服务 options 层（includeMFT=false），不在 SQL 层。


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

### 5.1 代码走读：normalizeWindowsPath 的分隔符与盘符归一（WindowsFilesAnalyzerCore.cpp:317-350）

```cpp
std::string WindowsFilesAnalyzer::normalizeWindowsPath(const std::string& input) {
    // 骨架：\Device\HarddiskVolumeX\... 或 C:\Users\... 或 /Users/...
    // 1) 统一替换 \ 为 /
    // 2) 剥离盘符前缀（C:）或 \Device\HarddiskVolumeN 前缀
    // 3) 保证以 / 开头
    // 4) 折叠连续分隔符
}
```

逐块解释（骨架，全实现 :317-350）：为什么要归一——镜像里的工件内容（注册表键、LNK 目标、Prefetch 路径）用的是 Windows 原生写法，而 raw.db 的 files.path 是 TSK 归一后的 `/` 风格（ImageAnalyzer.md 链路二的路径规范化）；两套写法不统一，"Prefetch 里引用的 DLL 是否在 files 表里"这类跨表 join 就永远 join 不上。归一化把三种输入形态（盘符式/设备路径式/已归一式）压成同一种，是全部工件表路径列可对齐 files 表的前提。已知局限：只处理结构不处理大小写（Windows 路径大小写不敏感但 SQLite LIKE 默认敏感——join 时需要 LOWER() 或 COLLATE NOCASE 配合，当前查询未做）。

### 5.2 代码走读：readUTF16LEString 的 ASCII 截断（WindowsFilesAnalyzerCore.cpp:386-404）

```cpp
std::string WindowsFilesAnalyzer::readUTF16LEString(const uint8_t* data, size_t maxChars) {
    // 骨架：逐 UTF-16LE 码元读取
    // 非 ASCII 码元（>0x7F 或代理对）替换为 '?'
    // 注释原文解释了取舍：解析器只需要路径/名称等标识性文本，完整 UTF-8 转换留待需要时
}
```

逐块解释（骨架）：中文用户名、中文文件名、中文注释在这条通道上全部变 `?`—— Prefetch 引用路径、JumpList、注册表值数据都经过它。对"路径是否存在于 files 表"的结构比对无碍（分隔符与 ASCII 部分保留），但 message 类文本会失真，LLM 分析中文系统的 EVTX 消息时要注意这一层损耗在 C++ 侧而非模型侧。修复点是标准 UTF-16→UTF-8 转换（iconv 或手写 BMP 映射，几十行）。


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

## 9. 方法全清单（Common/WindowsAnalyzerDeclarations.h:24-108 + Core）

| 方法 | 定义 | 语义 | 调用方 |
|---|---|---|---|
| `initialize()` | Core:26-61 | 输出库+提取目录准备 | 两个入口 |
| `analyzeWindowsData()` | Core:63-109 | 11 段主流程编排 | 同上 |
| `setOutputDatabasePath/setSkipAI` | .h | 配置 | 入口 |
| `analyzeWithLLM()` | Core:111-177 | 15 类工件 LLM（双闸门） | 主流程尾 |
| `queryFilesByPattern(pattern)` | Core:191-235 | raw.db LIKE 定位（is_deleted=0） | 各 analyzeXxx |
| `extractFileToPath(inode, out, partition=-1)` | Core | 按 inode 回镜像提取 | 同上 |
| `getExtractPath(subdir, name)` | Core | 提取目录路径规划 | 同上 |
| `analyzeRegistryHives/parseRegistryHive` | RegistryParser:28-165 | hivex DFS 全量+专项 | 主流程段 1 |
| `analyzeEventLogs` | EventLogParser:198-361 | EVTX 双段（正常+恢复） | 段 2 |
| `analyzePrefetchFiles` | ExecutionTraces:26-44 | MAM 版本分派 | 段 3 |
| `analyzeLNKFiles/analyzeJumpLists` | ExecutionTraces | LNK/dest-ms 解析 | 段 4-5 |
| `analyzeRecycleBin` | SystemAnalysis | $I/$R 解析 | 段 6 |
| `analyzeNTFSMetadata` | SystemAnalysis:26+ | $MFT（10 万条上限） | 段 7 |
| `analyzeUserProfiles/analyzeBrowsers` | BrowserAnalyzer:31-111 | Chrome/Edge/Firefox | 段 8-9 |
| `analyzeScheduledTasks/analyzeAmcache/analyzeSRUM` | SystemAnalysis:369-411+ | XML/hive/ESE | 段 10-12 |
| `parseShimcache/UserAssist/RDP/WiFiFromRegistry` | RegistryArtifacts:339-433+ | **无调用方**（第 7 节） | — |
| `normalizeWindowsPath/readUTF16LEString/FILETIME 转换` | Core:317-404 | 基础设施 | 各解析器 |

## 10. 关联矩阵

| 对端 | 方向 | 交互点 | 数据形态 |
|---|---|---|---|
| TaskManagerAnalysis.cpp:470-485 / Orchestrator:295-310 | 上游 | WINDOWS 场景构造 | windows.db 或 files.db |
| DatabaseManager（raw.db） | 输入 | queryFilesByPattern | FileRecord vector |
| FileExtractor（经 dbManager） | 下游 | extractFileToPath | 提取目录文件 |
| windows_analysis_sql_tables.h（32 表） | 输出 | CREATE_ALL_TABLES | DDL |
| WindowsAnalysisDatabase（DBOperations_*） | 下游 | 批量 insert（事务） | 参数化 |
| WindowsLLMAnalysisService（15 类） | 下游 | llm 语句族 pending→chat→回写 | JSON |
| DLLAnalyzer | 平行 | dll_* 表只读关联 | SELECT |
| hivex/libevtx/libesedb/libfsntfs | 下游 | 四个 libyal 系库 | C API |
| EventExtractor.importWindowsArtifacts | 下游 | 时间线合并（11 类） | INSERT..SELECT |
| AuditLog | 下游 | 43 处（WINDOWS_*/EVTX_*/AMCACHE_* 等） | 审计 |

## 11. 配置影响表

| 参数 | 默认 | 影响 | 备注 |
|---|---|---|---|
| `--windows-analyze` / scene=WINDOWS | false | 触发 | |
| `--skip-ai` | false | LLM 段跳过 | Core:119-134 双闸门之一 |
| `LLM_BASE_URL` | 192.168.31.170 | 无则 LLM 段跳过 | 闸门之二 |
| MFT 上限 | 10 万条（硬编码） | mft_entries 覆盖范围 | 大盘只取前段 |
| EVTX reserve 上限 | 10 万条 | 单日志文件内存 | |
| includeMFT（LLM） | false | MFT 不进 LLM | 服务 options |
| 无 .env 专有键 | — | — | |

## 12. 性能与并发细节

- **IO 大头**：工件的镜像提取（每个 hive/evtx/pf 一次 TSK 随机读）与 $MFT（可能数百 MB 单文件）。EVTX 的双段读把恢复记录也过一遍，大 Security.evtx（数百 MB）解析分钟级。
- **CPU 大头**：注册表 DFS 全量遍历（SYSTEM hive 数十万值逐个转字符串）与 MFT 逐条枚举——两者都有 per-record 的 C API 调用与字符串构造；事务批插缓解写侧。
- **内存**：EVTX reserve 上限 10 万条（约百 MB 级瞬时）；MFT 10 万条同量级；注册表 values vector 全量物化后批量落库——三个上限都靠硬编码 cap 而非流式，接线超大镜像时先调 cap。
- **并发**：主流程单线程串行（11 段顺序）；LLM 段服务内部并发。无内部线程池。
- **提取目录的磁盘占用**：全部工件先落 `<镜像>_extracted_files/` 再解析——大镜像上该目录 GB 级，任务结束不清理（供人工复核），磁盘预算要预留。
- **可调参数影响**：MFT/EVTX 两个 cap 是覆盖度与资源的天平；--skip-ai 省下 15 类 × 10000 条的 LLM 往返。


## 10. 常见任务配方

### 配方 A：接线一个未接线解析器（以 Shimcache 为例）
1. 确认 Parser 存在（Shimcache 解析已在 Parsers/）。
2. `Core/WindowsFilesAnalyzerCore.cpp` 的 analyzeWindowsData 编排里加调用（参照 Amcache 段）。
3. 落库走 `WindowsDBOperations_System.cpp:274` 的现成 INSERT 方法（无调用方但方法在）。
4. 验证：跑 Windows 任务后 `shimcache_entries` 非恒空；schema/WindowsDB 的"恒空"标注同步删除。
注意 user_assist/rdp/wifi 同法；shellbag 连 INSERT 方法都没有——先补 DB 操作。

### 配方 B：新增注册表工件项
`WindowsRegistryArtifacts.cpp` 加 hive/key 模式 → registry_values 落行（forensic_importance 评级顺手给）→ 需要则 LLM 四件套。

### 配方 C：扩展浏览器解析器
`WindowsBrowserParser*` 系列加引擎分支（现有 Chromium/Firefox 模板）；产出统一落 browser_history 六表。
**最后更新**: 2026-08-24（二轮深化：补全表列说明与方法清单）
