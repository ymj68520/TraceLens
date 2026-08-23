# DatabaseAnalyzer（src/analyzers/DatabaseAnalyzer/）

> **一句话**：数据库取证专用分析器——离线解析 SQLite 数据库文件和 MySQL/PostgreSQL 数据目录，提取表结构、记录、用户、工件，甚至恢复已删除记录，结果写入独立结果库的五张 `db_*` 表。
>
> **状态提示**：模块已编译进主程序（CMakeLists 挂入 LIB_SOURCES），但目前**没有任何生产调用方**——CLI 没有 `--analyze-dbs` 参数，HTTP 流水线不跑它，仅单元测试在用。详见第 2 节。

## 1. 为什么有这个模块

数据库是应用系统的"记忆"，也是取证时信息密度最高的证据之一：诈骗案的转账记录、入侵案的后门账号、业务系统的操作流水都在里面。但数据库证据有个特殊困难——**取证镜像里拿到的是"死"的数据文件**（SQLite 文件、MySQL 的数据目录、PostgreSQL 的 base 目录），不是正在运行的服务。要读它们，要么找到能离线解析其存储格式的工具，要么想办法把数据库引擎"复活"起来。这个模块两条路都走了，并且按数据库类型做了完全不同的取舍。

设计上是教科书式的**策略模式**（头文件注释原话）：`IDBParser` 定义统一接口（open/getTables/getRecords/getUsers/extractArtifacts/recoverDeletedRecords），`DBParserFactory` 按检测到的类型实例化 `SQLiteAnalyzer`/`MySQLAnalyzer`/`PostgreSQLAnalyzer`，`DatabaseAnalyzer` 主类只做编排和落库。加一种新数据库（比如 Redis 的 RDB）只需要注册一个新的解析器，编排层零改动。

第三条腿是**删除记录恢复**——数据库取证和文件取证一样，"被删的数据"往往比现存数据更有故事。SQLite 侧读 freelist 页，InnoDB 侧解析页目录找残留记录，PostgreSQL 侧找死元组（dead tuples）。这些能力深度不一（见第 4 节的诚实评估），但接口上是一致的。

## 2. 核心数据结构与接口

**策略接口 `IDBParser`**（`Parsers/IDBParser.h:35-223`）的关键虚方法：

```cpp
class IDBParser {
public:
    virtual bool open(const std::string& path) = 0;          // 打开文件/数据目录
    virtual bool connect(const DBConnectionConfig& config) { // 预留：直连（默认拒绝）
        lastError_ = "Direct connection not supported for this database type";
        return false;
    }
    virtual std::vector<DBTableInfo> getTables() = 0;        // 全量表结构
    virtual std::vector<DBRecordInfo> getRecords(            // 记录提取（limit/offset）
        const std::string& tableName, int limit = -1, int offset = 0) = 0;
    virtual std::vector<DBArtifact> extractArtifacts(        // 取证工件（freelist/WAL…）
        const DBAnalysisOptions& options = DBAnalysisOptions()) = 0;
    virtual std::vector<DBRecordInfo> recoverDeletedRecords( // 删除恢复（默认不支持）
        int maxRecords = 10000) { return {}; }
    virtual std::vector<DBUserInfo> getUsers() { return {}; }// 用户（默认不支持）
    virtual DBAnalysisSummary getAnalysisSummary() = 0;
    // ...
};
```

值得注意的三个默认实现：`connect`、`recoverDeletedRecords`、`getUsers` 都有"返回失败/空"的默认体——新解析器最少只需实现 open/getTables/getRecords 等纯虚函数，取证增强能力按需追加。

**记录与工件的载体**（`Common/DBDataTypes.h:299-334`）：

```cpp
struct DBRecordInfo {
    std::string tableName;               // 所属表名
    int64_t rowId = 0;                   // 行ID（如果有）
    std::map<std::string, std::string> values;  // 列名->值（全部字符串化）
    bool isDeleted = false;              // 是否为删除的记录
    int64_t pageNumber = 0;              // 页号（用于恢复分析）
    int64_t cellOffset = 0;              // 单元格偏移
};
struct DBArtifact {
    ArtifactType type = ArtifactType::UNKNOWN;
    std::string source;                  // 来源（表名、日志文件等）
    std::string description;
    std::map<std::string, std::string> data;
    int64_t pageNumber = 0;
    int64_t offset = 0;
    int64_t timestamp = 0;
    std::string rawData;                 // 原始数据（十六进制或Base64）
};
```

设计取舍：记录用"列名→字符串"的 map 而不是强类型，因为三种数据库的列类型系统互不相通，字符串化是最大公约数；`pageNumber/cellOffset` 两个字段专为删除恢复保留——恢复出的记录没有 rowId 时，页号+偏移是它在物理文件里的"地址"，也是复核时定位原始字节的依据。

**工厂注册表**（`Parsers/DBParserFactory.cpp:21-40`）是静态 lambda 表：

```cpp
std::map<DatabaseType, ParserCreator>& DBParserFactory::getRegistry() {
    static std::map<DatabaseType, ParserCreator> registry;
    static bool initialized = false;
    if (!initialized) {
        registry[DatabaseType::SQLITE] = []() { return std::make_unique<SQLiteAnalyzer>(); };
        registry[DatabaseType::MYSQL]  = []() { return std::make_unique<MySQLAnalyzer>(); };
        registry[DatabaseType::POSTGRESQL] = []() { return std::make_unique<PostgreSQLAnalyzer>(); };
        initialized = true;
    }
    return registry;
}
```

函数级 static 保证线程安全初始化（C++11 magic static），`registerParser(type, creator)` 允许外部在运行时追加/覆盖条目——加 Redis/MongoDB 时这是唯一要动的工厂代码。

### 2.1 核心接口清单

`DatabaseAnalyzer`（`DatabaseAnalyzer.h:44-170`）的公开 API：

| 方法 | 语义 | 调用方 | 失败行为 |
|------|------|--------|---------|
| `bool initialize(outputDbPath)` | 建结果库（五张 db_* 表） | 仅测试（模块未接线） | false + lastError |
| `int64_t analyze(path)` / `analyze(path, type)` | 单库分析：检测类型→建解析器→open→doAnalyze，返回会话 ID | 同上 | 每步失败 return -1 + setError；类型未知直接拒绝 |
| `std::vector<std::pair<path,type>> scanDirectory(dir, recursive)` | 递归找库（文件查魔数、目录查特征） | `analyzeDirectory` 的第一步 | 目录异常捕获进 lastError，返回已发现部分 |
| `int analyzeDirectory(dir, recursive)` | 批量分析，返回成功数 | 同上 | 单库失败继续下一库 |
| `getAllSessions/getTables/getRecords/getArtifacts/getUsers(sessionId)` | 查询接口（读结果库） | 预留 | 未初始化返回空容器 |
| `static detectType(path)` / `getSupportedTypes()` | 类型探测/已注册类型列表 | 便捷转发到工厂 | — |

## 3. 在流水线中的位置

**当前没有流水线位置。** 逐一核实过的现状：

- `CommandLineParser` 的全部参数里没有 `--analyze-dbs`（`src/CommandLineParser.cpp` 通读可证）；
- `AnalysisOrchestrator` 不 include 也不构造 `DatabaseAnalyzer`；
- HTTP TaskManager 的各阶段同样不涉及；
- 唯一的调用方是测试：`tests/UnitTest/test_database_analyzer_gtest.cpp`、`tests/test_mysql_daemon.cpp`。

所以它是"已建成、未接入"的模块——代码质量完整（类型检测、进度回调、会话管理都有），二进制里也带着，但用户目前无法从任何入口触发它。预期的使用方式（也是它的 API 设计意图）是：`initialize(<结果库路径>)` → `analyze(<库文件或数据目录>)`（自动检测类型）或 `analyzeDirectory(<目录>, recursive)` 批量扫。输出是结果库中的五张表（见 3.1）。

注意与 LinuxFilesAnalyzer 的 `analyzeDatabaseLogs()` 区分：那是解析 MySQL/PostgreSQL 的**日志文件**（慢查询日志、错误日志），写 linux.db；本模块解析的是**数据文件本体**。两者互补，无调用关系。

### 3.1 产出表结构说明（结果库五张表）

建表语句在 `Database/DBAnalysisDatabase.cpp:48-127`：

| 表 | 关键列 | 取证含义 |
|----|--------|---------|
| `db_sessions`（:48-62） | `source_path/database_type/version/file_size/table_count/total_records/deleted_records/user_count/artifact_count/started_at/completed_at/last_error` | 每次分析一个会话：证物的身份（路径/类型/版本）+ 全部统计 + 结束时间与最后错误——`last_error` 非空即"分析中途出过异常但已保留部分结果"的信号 |
| `db_tables`（:65-79） | `name/schema_name/row_count/size_bytes/create_statement/engine/collation/columns_json/indexes_json` | 表清单；列与索引用 JSON 折叠存储（`columns_json`），既省表数又保结构 |
| `db_records`（:82-94） | `table_name/row_id/values_json/is_deleted/page_number/cell_offset` | 通用记录容器；`(session_id, table_name)` 有复合索引；`is_deleted=1` 的行来自恢复通道，页号/偏移可回溯物理位置 |
| `db_artifacts`（:97-111） | `type/source/description/data_json/page_number/offset/timestamp/raw_data` | 取证工件：freelist 规模、WAL 残留、恢复出的删除记录副本；`(session_id, type)` 索引支持按工件类型筛选 |
| `db_users`（:114-127） | `username/host/auth_method/password_hash/privileges_json/is_locked/created_at/last_login` | 数据库账号：后门账号最典型的指纹是 `host='%'` + 高权限 + 近期 `created_at` |

所有子表都对 `session_id` 建 `ON DELETE CASCADE` 外键——删会话即级联清空其全部产物，多会话并存互不污染。

## 4. 证据来源与覆盖范围

类型检测在 `DBParserFactory::detectType`（`Parsers/DBParserFactory.cpp:42-67`），识别三种证据形态：

| 类型 | 识别特征 | 解析路径 |
|------|---------|---------|
| SQLite | 文件头 16 字节魔数 `SQLite format 3\0`（`isSQLiteFile`，第 123-129 行） | 直接读写文件（sqlite3 API + 自研 forensics） |
| MySQL | 目录下有 `mysql/` 系统库子目录或 `ibdata1`（第 131-161 行，另认 `.frm/.myi/.myd`） | 目录扫描 `.frm/.myi/.myd/.ibd` + 可选拉起 mysqld + binlog/InnoDB 解析 |
| PostgreSQL | 目录下有 `PG_VERSION`（最可靠）或 `postgresql.conf`/`base/`（第 163-192 行） | 可选拉起 postgres + 离线 heap 文件解析 |

MySQL 数据目录里能提取的工件面（`MySQLAnalyzer.cpp`）：数据库名清单、表清单（5.x 靠 `.frm` 文件名）、用户信息（`mysql/user.frm` 存在性 + InnoDB 系统表空间解析）、binlog 事件（详见第 4 节）。PostgreSQL 侧额外会读 `postmaster.pid`（判断上次是否非正常关闭，`PostgreSQLAnalyzer.cpp:383-390`）这类"数据库自己知道的异常"。

## 5. 解析机制走读

**链路一：统一分析流水（`doAnalyze`，`Core/DatabaseAnalyzerCore.cpp:76-173`）。** 每次分析开一个会话（`beginSession` 记录路径/类型/版本），然后五步：`getTables` 全量表结构入库；按 `options_` 的开关与 include/exclude 表名单、每表 `maxRecordsPerTable` 上限提取记录；`extractArtifacts` 拿数据库特有的取证工件（freelist、加密标志等）；`getUsers` 提用户；`extractDeletedRecords` 跑删除恢复并统一打 `isDeleted=true` 标记。表过滤的真实代码：

```cpp
// Core/DatabaseAnalyzerCore.cpp:101-133（节选）
for (size_t i = 0; i < tables.size(); i++) {
    const auto& table = tables[i];
    // 检查排除列表
    bool excluded = false;
    for (const auto& exclude : options_.excludeTables) {
        if (table.name == exclude) { excluded = true; break; }
    }
    if (excluded) continue;
    // 检查包含列表
    if (!options_.includeTables.empty()) {
        bool included = false;
        for (const auto& include : options_.includeTables) {
            if (table.name == include) { included = true; break; }
        }
        if (!included) continue;
    }
    int limit = options_.maxRecordsPerTable;
    auto records = parser->getRecords(table.name, limit);
    resultDb_->insertRecords(sessionId, records);
    summary.totalRecords += records.size();
    reportProgress("Extracting records", i + 1, tables.size());
}
```

做什么/为什么：排除名单适合"库里有几百张无关业务表、只要涉案几张"的场景，包含名单是白名单模式（给了就只取这几张），两者叠加时排除优先。每表提完就插库并汇报进度——大库分析中途 kill 掉，已完成的表已经持久化。错误路径在整段外层：五步全部包在一个 try/catch 里（第 90-166 行），异常被捕获进 `summary.lastError` 而不是中断——库读了一半坏掉时已提取的部分仍然保留，会话总是正常收尾（`endSession`）。

**链路二：MySQL 的"复活引擎"（`MySQLDaemon.cpp:27-76`）。** `MySQLAnalyzer::open()` 先离线扫数据目录（`scanDataDirectory`），表结构靠解析 `.frm` 文件（`parseFrmFile` 自知是"基本解析"），同时尝试 `MySQLDaemon`：fork 一个 mysqld 起来后用 MySQL C API 真正查询记录。daemon 起不来不阻塞 open——退化为"只有元数据"的模式。fork/exec 的真实代码：

```cpp
// Parsers/MySQLDaemon.cpp:33-71（节选）
pid_t pid = fork();
if (pid == -1) {
    lastError_ = "Failed to fork mysqld process.";
    return false;
} else if (pid == 0) {
    // Child process
    std::string cmd = "mysqld --skip-grant-tables --skip-networking --socket=" + socketPath_ +
                      " --datadir=" + dataDir_ + " --log-error=" + logPath_;
    execl("/bin/sh", "sh", "-c", cmd.c_str(), NULL);
    exit(1); // Exits if execl fails
} else {
    daemonPid_ = pid;
    // Wait for socket to appear (max 10 seconds)
    for (int i = 0; i < 100; i++) {
        if (fs::exists(socketPath_)) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    if (!fs::exists(socketPath_)) {
        lastError_ = "mysqld failed to start or socket not created in time.";
        stop(); return false;
    }
    conn_ = mysql_init(NULL);
    // ... mysql_real_connect(conn_, "localhost", "root", "", NULL, 0, socketPath_.c_str(), 0)
}
```

三个参数各有含义：`--skip-grant-tables` 免掉 mysql.user 里未知密码的认证（取证拿到的正是不知道密码的库）；`--skip-networking` 只开本地 socket，避免分析机端口暴露；`--datadir` 直接指向传入路径。启动判定不是看进程而是**轮询 socket 文件出现**（100 次 × 100ms = 10 秒上限）——mysqld 启动慢且不保证输出稳定，socket 是"可连接"的最可靠信号。错误路径：socket 超时、`mysql_init`/`mysql_real_connect` 失败都会 `stop()`（SIGTERM + waitpid + 删 socket 文件）后返回 false，调用方降级。配套的 `MySQLBinlogParser` 离线解析 binlog：FormatDescription/Query/TableMap/Rows/Rotate/Xid 六类事件（`MySQLBinlogParser.h:137-142` 的解析方法表，内部维护 `tableId -> TableMapInfo` 缓存把 Rows 事件关联到表名），能重建"谁在什么时间改了什么数据"；`InnoDBParser` 则手工解析 ibdata/.ibd 的 FIL 页头（`FIL_PAGE_TYPE` 偏移 24、`FIL_PAGE_SPACE_ID` 偏移 34 等常量表在 `InnoDBParser.h:26-52`），用于引擎不可用时的兜底。

**链路三：离线堆解析与删除恢复的诚实现状。** PostgreSQL 的 `PostgreSQLHeapParser` 是模块里最完整的离线二进制解析器，按 8KB 块读页头，偏移常量直接对着 PostgreSQL 源码的 `PageHeaderData`：

```cpp
// Parsers/PostgreSQLHeapParser.h:24-46（节选）
namespace PG {
    constexpr size_t DEFAULT_BLOCK_SIZE = 8192;   // 默认块大小 (BLCKSZ)
    constexpr size_t PAGE_HEADER_SIZE = 24;
    // PageHeaderData偏移
    constexpr size_t PD_LSN = 0;           // 8 bytes
    constexpr size_t PD_LOWER = 12;        // 2 bytes - 空闲空间开始
    constexpr size_t PD_UPPER = 14;        // 2 bytes - 空闲空间结束
    constexpr size_t PD_SPECIAL = 16;      // 2 bytes - 特殊区域偏移
    constexpr size_t PD_PRUNE_XID = 20;    // 4 bytes
    // ItemId 相关
    constexpr size_t ITEM_ID_SIZE = 4;
    constexpr uint16_t LP_UNUSED = 0;
    constexpr uint16_t LP_NORMAL = 1;
    constexpr uint16_t LP_REDIRECT = 2;
    constexpr uint16_t LP_DEAD = 3;        // 死元组：被删/被更新的旧版本
    // HeapTupleHeader偏移
    constexpr size_t T_XMIN = 0;           // 4 bytes  插入事务ID
    constexpr size_t T_XMAX = 4;           // 4 bytes  删除事务ID
    // ...
}
```

取证视角读这组常量：`PD_LOWER/PD_UPPER` 划出页内空闲区（空闲区里的残留字节是恢复目标）；ItemId 的 `LP_DEAD/LP_UNUSED` 状态标记出死元组槽位——"被删但尚未 vacuum"的记录就从这里识别；`T_XMAX != 0` 的元组是被删除/更新过的版本，配合 `HEAP_XMAX_COMMITTED` 等 infomask（第 59-65 行）还能判断删除事务是否已提交。SQLite 侧对照：`SQLiteAnalyzer_Forensics.cpp` 的 `extractArtifacts`（第 136-174 行）读 freelist 页数作为工件（`"SQLite freelist contains N pages"`、`potential_deleted_data=true`），但 `recoverDeletedRecords`（第 176 行起）是诚实标注的半成品：

```cpp
// Parsers/SQLiteAnalyzer_Forensics.cpp:177-190（节选）
std::vector<DBRecordInfo> SQLiteAnalyzer::recoverDeletedRecords(int maxRecords) {
    // 基础实现：分析freelist页
    // 注意：完整的删除记录恢复需要对SQLite文件格式进行深入解析
    std::vector<DBRecordInfo> recovered;
    if (!db_ || maxRecords == 0) return recovered;
    (void)maxRecords;  // 未来实现使用
    // TODO: 实现完整的freelist解析和记录恢复
    // 这需要直接读取数据库文件并解析SQLite B-Tree结构
    return recovered;
}
```

即 SQLite 当前只统计 freelist 规模，**并没有真正从 freelist 页里挖出记录内容**——恢复能力三家深度不一，PostgreSQL > MySQL(InnoDB) > SQLite，接口一致但实现要看清。

## 6. 与 LLM 的协作

无。模块自身不接 LLM；预期的接入点是分析完之后把 db_records 里的敏感内容交给平台 LLM 服务，但目前连调用方都没有，谈不上 LLM 管道。

## 7. 与其他模块的协作 / 注意事项

- **无调用方（重要）**：见第 3 节。想启用它需要在 CommandLineParser 加参数、在 AnalysisOrchestrator 加一个 `runDatabaseAnalysis`，或挂进 HTTP 任务阶段——API 已就绪。
- **外部依赖**：MySQL C API（`mysql/mysql.h`，随 MySQLDaemon）、libpq（PostgreSQLDaemon）；引擎二进制 mysqld/postgres 在运行时 PATH 探测（`which mysqld`，`MySQLDaemon.cpp:24`），缺失则降级。
- **取证完整性警告**：`MySQLDaemon` 直接对**原始数据目录**拉起 mysqld（`--datadir` 指向传入路径，无拷贝/快照步骤，见上文代码），InnoDB 引擎启动时会写 redo 日志、更新文件——这会**修改证据**。PostgreSQLDaemon 同理。若要用于真实取证流程，务必先对数据目录做副本再喂给分析器，或改造 daemon 加 copy-on-open。这是模块接入流水线前必须解决的问题。
- **`connect(DBConnectionConfig)` 是预留接口**，未实现（`IDBParser.h:54-58` 的默认实现明确报错 "Direct connection not supported"，`MySQLAnalyzer.cpp:76-83` 的覆写也提示用 open()）。
- **与 DatabaseManager（core/）无关**：那是本项目的 SQLite 结果库管理类；这里的 `DBAnalysisDatabase` 是模块自己的结果库封装，名字相近但完全独立。

## 8. 如何验证与扩展

- 测试：`tests/UnitTest/test_database_analyzer_gtest.cpp`（类型枚举、工厂注册、选项默认值）、`tests/test_mysql_daemon.cpp`（daemon 生命周期）。端到端验证：手工构造一个 SQLite 文件 + `initialize("out.db"); analyze("test.db")`，检查 db_sessions/db_tables/db_records 的会话闭环。
- 加新数据库类型：实现 `IDBParser` 的全部纯虚函数（`connect/recoverDeletedRecords/getUsers` 有默认实现可不写），在 `DBParserFactory::getRegistry()` 注册 lambda，`DatabaseType` 枚举加值，`detectType` 加识别特征（`DBParserFactory.cpp:27-41` 的注册表是唯一需要动的工厂代码）。
- 接入流水线的最小改法：给 `CommandLineArgs` 加 `analyze_dbs` 标志与目标路径参数，`main.cpp` 路由到新的 `AnalysisOrchestrator::runDatabaseAnalysis`（照抄 `runDLLAnalysis` 的骨架即可，`AnalysisOrchestrator.cpp:710-752`）。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
