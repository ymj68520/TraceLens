# DatabaseManager（src/core/DatabaseManager/）

> **一句话**：取证数据落盘的最底层组件——负责打开一个 SQLite 库、按需建出 files/partitions 表、提供文件记录的插入与计数接口，同时是 "SQL-as-headers"（建表语句全部集中在 `SQL/` 目录头文件）模式的发源地。

## 1. 为什么有这个模块

流水线的第一步是把磁盘镜像"数字化"：ImageAnalyzer 遍历镜像里的每个 inode，产生几万到几十万条文件元数据记录。这些记录必须有地方放。直接在 ImageAnalyzer 里裸写 `sqlite3_exec` 看似最快，但很快会遇到三件每个写库模块都会撞上的事：打开连接要设 busy_timeout/journal mode 等性能 PRAGMA；建表语句会随需求演进（后来加的 partition_num、llm_* 列都是这么来的），散在各处后旧库无法平滑升级；以及多模块写同一个库时的锁行为需要统一基线。

DatabaseManager 把"拥有一个 SQLite 库"这件事封装成 RAII 对象：构造传路径、`initialize()` 打开并建表、析构关闭。它自己只管理 raw.db 形态的库（files + partitions 两张表），但它的子目录里住着三个更大的组件（EventExtractor、FileClassifier、FileExtractor，各有独立文档）和 `SQL/` 头文件族——后三者复用同一套连接管理与建表哲学，各自的表结构也在 `SQL/` 中定义。

一个必须理解的历史包袱：**迁移靠"探测 + ALTER"而非版本号**。`CREATE TABLE IF NOT EXISTS` 不会给旧表补新列，于是 `checkAndMigrate()`（`DatabaseManager.cpp:53-76`）用 `PRAGMA table_info(files)` 探测 `llm_summary` 列是否存在，缺了就逐条执行 ALTER 数组（语句来自 `SQL/file_classifier_sql.h:75-82`）。这套模式在 FileClassifier 的 partition_num 迁移里也重复出现（`FileClassifier.cpp:94-97, 151-156`）。

## 2. 在系统中的位置

DatabaseManager 被两类角色使用：

- **raw.db 的生产者与消费者**：ImageAnalyzer 扫描镜像后通过 `insertFileRecord`/`insertPartitionInfo` 灌数据（`src/analyzers/ImageAnalyzer/ImageAnalyzer.cpp`）；FileExtractor 持有一个 DatabaseManager 来按 inode/路径查询记录（`src/core/DatabaseManager/FileExtractor/FileExtractor.h:107`）；CLI 分析流水线里平台分析器（Android/Windows/Linux/OSSAnalyzer）以它作为输入库句柄传入（如 `AnalysisOrchestrator.cpp:278-314`）。
- **PRAGMA 基线的提供者**：`initialize()` 中应用的三个数据库性能设置（`DatabaseManager.cpp:28-36`）来自 ConfigManager（`DB_BUSY_TIMEOUT_MS`/`DB_JOURNAL_MODE`/`DB_SYNCHRONOUS_OFF`），EventExtractor 与 FileClassifier 虽然自开连接，也在各自 `openDatabases()` 中复制了同样的 WAL + NORMAL 组合（`EventExtractorCore.cpp:59-66`、`FileClassifier.cpp:70-79`）——三处代码注释互相印证了这是全系统约定。

在任务目录里，它对应 `data/tasks/<task_id>/raw.db`（路径来自 PathManager，见 PathManager.md 第 3 节）。

```
ImageAnalyzer ──insertFileRecord/insertPartitionInfo──> DatabaseManager(raw.db)
                                                          │ files / partitions 两表
FileExtractor、平台分析器 <──查询(getDb()/getFileCount)──┘
```

## 3. 核心概念与设计

**双表数据模型**。`files` 表（`DatabaseManager.cpp:80-105`）每行一个文件系统对象：inode、路径、大小、四个时间戳（atime/mtime/ctime/crtime）、类型（REG/DIR 等 TSKit 命名）、md5、删除/分配标志、权限 uid/gid、`partition_num`，外加五个 `llm_*` 列（建表时就带上，保证新库直接支持 LLM 回写）。`partitions` 表（`:125-134`）记录分区号、起始偏移、长度、文件系统类型。配套索引覆盖 inode/path/type/is_deleted/partition_num 五个常用过滤维度（`:141-145`）。

对应的内存结构 `FileRecord`（`DatabaseManagerDataTypes.h:13-40`）在文件末尾有两点值得注意：`partitionNum` 的注释明确说了存在原因是"多文件系统镜像中 inode 会碰撞，需要分区号消歧"——这是贯穿 FileExtractor 的核心约束；`sceneType/scenePriority/sceneRelevant` 三个字段是为 FileClassifier 的场景分类预留的，DatabaseManager 自己的 INSERT 并不写它们（`:150-156` 的列清单里没有）。

**SQL-as-headers**：`SQL/` 目录把所有建表/CRUD SQL 放进头文件，形如：

```cpp
namespace FileClassifierSQL {
inline constexpr const char* CREATE_MAIN_FILES_TABLE = R"(
    CREATE TABLE IF NOT EXISTS files (...);)";
}
```

（示例节选自 `SQL/file_classifier_sql.h:8-38`。）`inline constexpr` 保证多头文件包含零开销，命名空间（`FileClassifierSQL`、`EventExtractorSQL`、`AndroidAnalysisSQL`、`WindowsAnalysisSQL`……）让不同子系统的语句互不冲突。这个设计解决了"SQL 字符串散在 .cpp 里、无法审计全库 schema"的问题——**想看某个库有哪些表，直接读对应头文件即可**。规模较大的子系统进一步拆分并用聚合头再导出：`windows_analysis_sql.h` include tables/crud/llm 三个子头后用 `using` 逐条 re-export（`SQL/windows_analysis_sql.h:18-27` 起）；`memory_analysis_sql.h` 是纯聚合器（该文件全文 11 行）。

**PRAGMA 基线**（`DatabaseManager.cpp:28-39`）：busy_timeout 5000ms（默认，可配）避免并发写时立刻 SQLITE_BUSY；journal_mode=WAL 让读写不互斥；`foreign_keys=ON` 纯声明（当前两张表无外键，但为未来 schema 兜底）；`DB_SYNCHRONOUS_OFF` 默认关闭，开启则牺牲掉电安全换速度。

**迁移的边界**：`checkAndMigrate()` 只补 llm_* 五列（`:53-76`）；partition_num 的迁移放在 `createTables()` 里，用"ALTER 失败即已存在"的错误吞掉法（`:111-122` 有注释解释为何 prepare 出错可以忽略）。

### 3.1 核心数据结构：FileRecord（DatabaseManagerDataTypes.h:13-40）

```cpp
struct FileRecord {
	int id = 0;
	int64_t inode;
	std::string name;
	std::string path;
	int64_t size;
	std::string extension;
	std::string category;
	int64_t atime;
	int64_t mtime;
	int64_t ctime;
	int64_t crtime;
	std::string type;
	std::string md5;
	int isDeleted;
	int isAllocated;
	std::string permissions;
	int uid;
	int gid;
	// Partition number this file belongs to (0 = no partition table / single FS).
	// Disambiguates inode collisions across multiple filesystems in one image.
	int partitionNum = 0;

	// Scene-aware classification fields
	std::string sceneType;
	int scenePriority = 0;
	int sceneRelevant = 0;
};
```

逐组解释：`id` 是查询回读时才有意义的自增主键，插入路径恒 0；`inode`+`partitionNum` 构成**文件的自然键**——注释点明多文件系统镜像中 inode 会碰撞，靠分区号消歧，FileExtractor 的提取查询都以这对组合为条件。四个时间戳是取证的核心证据：`atime/mtime/ctime` 是 POSIX 三件套，`crtime`（创建时间）只有 ext4 等新文件系统提供，缺失时为 0。`type` 存 TSKit 命名（REG/DIR/LNK…），`md5` 由 ImageAnalyzer 可选计算（空串表示未算）。`isDeleted`/`isAllocated` 区分"已删但内容仍在"与"已分配"，前者正是取证最感兴趣的。`extension`/`category`/`sceneType`/`scenePriority`/`sceneRelevant` 五个字段 DatabaseManager 的 INSERT 一概不写（`:150-156` 列清单可证）——它们是 FileClassifier 的回写字段，结构上共用、写入上分离，同一结构被流水线前后两段当载体复用。`EventRecord`（同文件 :47-53）则只服务于那个死声明（见第 6 节）。

### 3.2 核心接口清单

| 签名（DatabaseManager.h） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `explicit DatabaseManager(const std::string& dbPath)` | 记录路径，不开连接 | ImageAnalyzer/FileExtractor/平台分析器 | 无 |
| `bool initialize()` | 打开连接+PRAGMA+建表+迁移+审计 | 构造后的第一件事 | 打开/建表失败返回 false，写 DB_INIT_FAILED 审计 |
| `bool insertFileRecord(const FileRecord&)` | 单条文件记录入库（16 列参数化绑定） | ImageAnalyzer 扫描循环 | prepare/step 失败返回 false 打 stderr |
| `bool insertPartitionInfo(partNum, start, length, desc, fsType)` | 分区元数据入库 | ImageAnalyzer 分区枚举 | 同上 |
| `int getFileCount()` | files 表行数 | 进度/统计 | 失败返回 -1（调用方需判负） |
| `sqlite3* getDb() const` | 裸连接逃生口 | FileExtractor、平台分析器自写查询 | db_ 未初始化时返回 nullptr |
| `const std::string& getDbPath() const` | 库路径回读 | 日志/诊断 | 无 |
| `bool insertEventRecord(const EventRecord&)` | **死声明**：头文件 :49 声明、无定义 | 无调用方 | 链接错误（详见第 6 节） |

## 4. 工作流程走读

以 CLI 分析的 raw.db 生成阶段为例：

1. ImageAnalyzer 构造 `DatabaseManager(rawDbPath)` 后调 `initialize()`（`DatabaseManager.cpp:19-51`）：打开连接 → 应用 PRAGMA → `createTables()` 建表建索引 → `checkAndMigrate()` 补列 → 写一条 `DB_INIT` 审计（`:49`）。
2. 扫描循环中每发现一个文件/分区，调用 `insertFileRecord`（`:150-187`）/`insertPartitionInfo`（`:189-214`）。两者都是标准的 prepare-bind-step-finalize 五步，全部参数绑定、无字符串拼接（路径来自镜像内容，参数化是安全底线）。
3. 消费方（FileExtractor 等）或以对象身份调 `getFileCount()`（`:216-227`），或用 `getDb()`（`DatabaseManager.h:73`）拿裸 `sqlite3*` 自行 prepare 查询——这是刻意保留的逃生口，让查询逻辑不必都塞进本类。
4. 析构关闭连接（`:13-17`）。

### 4.1 代码走读：initialize 的 PRAGMA 应用序（DatabaseManager.cpp:19-51）

```cpp
bool DatabaseManager::initialize() {
	int rc = sqlite3_open(dbPath_.c_str(), &db_);
	if (rc != SQLITE_OK) {
		std::cerr << "Cannot open database: " << sqlite3_errmsg(db_) << std::endl;
		AuditLog::instance().log("SYSTEM", "DB_INIT_FAILED", "Failed to open database: " + dbPath_);
		return false;
	}

	// Apply performance settings from ConfigManager
	auto& config = forensics::ConfigManager::instance();
	sqlite3_busy_timeout(db_, config.getDBBusyTimeoutMs());

	std::string journalMode = config.getDBJournalMode();
	executeSQL("PRAGMA journal_mode = " + journalMode + ";");

	if (config.getDBSyncOff()) {
		executeSQL("PRAGMA synchronous = OFF;");
	}

	// Enable foreign keys
	executeSQL("PRAGMA foreign_keys = ON;");

	// Create tables
	if (!createTables()) {
		return false;
	}

    // Migration: Check and add LLM columns if they don't exist
    checkAndMigrate();

	AuditLog::instance().log("SYSTEM", "DB_INIT", "Database initialized: " + dbPath_);
	return true;
}
```

逐块解释：PRAGMA 的顺序有讲究——busy_timeout 必须在任何写入前设好，否则第一次并发碰撞就直接吃 SQLITE_BUSY；`journal_mode` 是这条链里唯一**字符串拼接**进 SQL 的值（来自 .env 的 `DB_JOURNAL_MODE`），信任边界是运维自己的配置文件，但严格说这里是个注入面（值只能是 WAL/TRUNCATE 等合法模式，写歪了 executeSQL 会报错并返回 false，此处未检查返回值——journal 设置失败被静默吞掉，库仍以默认 journal 模式运行）。`foreign_keys=ON` 每连接生效（不是库属性），所以每个新开的连接都要重申——这解释了为什么 EventExtractor/FileClassifier 开库时也要带自己的 PRAGMA 段。收尾的 `DB_INIT` 审计是"初始化成功"的唯一权威记录，与开头的 `DB_INIT_FAILED` 构成一对互斥事件。

### 4.2 代码走读：checkAndMigrate 的探测-补列（DatabaseManager.cpp:53-76）

```cpp
void DatabaseManager::checkAndMigrate() {
    // Check if llm_summary column exists in files table
    sqlite3_stmt* stmt;
    const char* checkSql = "PRAGMA table_info(files);";
    bool hasLlmSummary = false;

    if (sqlite3_prepare_v2(db_, checkSql, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* colName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            if (colName && std::string(colName) == "llm_summary") {
                hasLlmSummary = true;
                break;
            }
        }
        sqlite3_finalize(stmt);
    }

    if (!hasLlmSummary) {
        std::cout << "[DB Migration] Adding LLM columns to files table in " << dbPath_ << std::endl;
        for (int i = 0; i < FileClassifierSQL::ALTER_FILES_ADD_LLM_COLUMNS_COUNT; ++i) {
            executeSQL(FileClassifierSQL::ALTER_FILES_ADD_LLM_COLUMNS[i]);
        }
    }
}
```

逐块解释：`PRAGMA table_info` 每行返回一列的元信息，第 2 列（下标 1）是列名——遍历比对 `llm_summary` 这个**代表列**：五个 llm_* 列是同批加的，探测一个即可推断整批存在与否，这是"探测一个、补一列组"的省事假设；若历史上出现过只加了一半的库（比如某次迁移中途失败），这个假设会漏补缺的列——无版本号方案的固有脆弱点。ALTER 语句本体在 `SQL/file_classifier_sql.h` 的数组里、配 COUNT 常量，DatabaseManager 只负责执行——**schema 知识与迁移逻辑分离**，加新列时只动 SQL 头文件和这里的探测条件。注意 ALTER 在新库上也会执行失败（列已存在），executeSQL 打一条 stderr 后返回 false 被忽略——所以新库初始化时 stderr 里出现 "duplicate column name" 是预期噪音。

### 4.3 代码走读：partition_num 迁移的"吞错法"（DatabaseManager.cpp:111-122）

```cpp
	// Migration: older databases created before partition_num existed won't have
	// the column (CREATE TABLE IF NOT EXISTS does not alter existing tables).
	// Add it with a default of 0 so single-partition images keep working.
	// sqlite3_prepare_v2 returns an error if the column already exists; ignore it.
	{
		sqlite3_stmt* migStmt = nullptr;
		if (sqlite3_prepare_v2(db_, "ALTER TABLE files ADD COLUMN partition_num INTEGER DEFAULT 0;",
		                       -1, &migStmt, nullptr) == SQLITE_OK) {
			sqlite3_step(migStmt);
		}
		if (migStmt) sqlite3_finalize(migStmt);
	}
```

逐块解释：与 checkAndMigrate 的"先探测再执行"不同，这里用**无条件执行 + 吞掉失败**：prepare 阶段就会因"duplicate column name"报错，`!= SQLITE_OK` 直接跳过 step——错误即"已迁移"的信号，一次往返省掉了 PRAGMA 探测。四行注释把 WHY 写全（IF NOT EXISTS 不改旧表、DEFAULT 0 保单分区兼容、prepare 失败可忽略），是仓库存量代码里注释质量较高的段落。代价是**真正的失败也被吞**：磁盘满、权限错导致的 prepare 失败与"列已存在"不可区分，迁移静默缺失要到下游查询报 no such column 才暴露——两种迁移风格（探测式/吞错式）各自的安全边界，新加列时建议用探测式。

### 4.4 代码走读：insertFileRecord 的全参数绑定（DatabaseManager.cpp:150-186）

```cpp
bool DatabaseManager::insertFileRecord(const FileRecord& record) {
	const char* sql = R"(
        INSERT INTO files (inode, name, path, size, atime, mtime, ctime, crtime,
                          type, md5, is_deleted, is_allocated, permissions, uid, gid,
                          partition_num)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    )";

	sqlite3_stmt* stmt;
	int rc = sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr);

	if (rc != SQLITE_OK) {
		std::cerr << "Failed to prepare statement: " << sqlite3_errmsg(db_) << std::endl;
		return false;
	}

	sqlite3_bind_int64(stmt, 1, record.inode);
	sqlite3_bind_text(stmt, 2, record.name.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 3, record.path.c_str(), -1, SQLITE_TRANSIENT);
	// ... 4-15 号绑定：size/四个时间戳/type/md5/isDeleted/isAllocated/permissions/uid/gid
	sqlite3_bind_int(stmt, 16, record.partitionNum);

	rc = sqlite3_step(stmt);
	sqlite3_finalize(stmt);

	return rc == SQLITE_DONE;
}
```

逐块解释：16 个占位符与列清单一一对应，路径/文件名来自**镜像内容**（可能是恶意构造的文件名），参数化绑定保证任何引号/控制字符都只是数据——取证工具处理不可信输入，这里是不可妥协的底线。数值列用 `bind_int64`（inode/size/时间戳都可能超 32 位），标志位用 `bind_int`。每次调用 prepare + finalize 一条语句，**没有复用预编译语句**（对比 AuditLog 的 insert_stmt_ 常驻）：每条记录多付一次 SQL 解析，换来无状态的单线程安全；配合"每条自动提交"（无事务包裹），数十万文件的镜像落库明显慢于 EventExtractor/FileClassifier 的事务批写（见第 6 节）。返回值语义精确：只有 `SQLITE_DONE` 才算成功，SQLITE_BUSY/约束冲突等一律 false，由上游决定跳过还是中止。

### 4.5 代码走读：insertPartitionInfo 与 getFileCount（DatabaseManager.cpp:189-227）

```cpp
bool DatabaseManager::insertPartitionInfo(int partitionNum, int64_t startOffset,
                                          int64_t length, const std::string& description,
                                          const std::string& fsType) {
    const char* sql = "INSERT INTO partitions (partition_num, start_offset, length, description, fs_type) "
                      "VALUES (?, ?, ?, ?, ?);";
    // prepare -> 5 个绑定（int64/int64/int64/text/text）-> step -> finalize
    ...
}

int DatabaseManager::getFileCount() {
    const char* sql = "SELECT COUNT(*) FROM files;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare count statement: " << sqlite3_errmsg(db_) << std::endl;
        return -1;
    }
    int count = -1;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        count = sqlite3_column_int(stmt, 0);
    }
    sqlite3_finalize(stmt);
    return count;
}
```

逐块解释：分区记录每个镜像只有几条（MBR≤4 主分区 + 逻辑分区），没有性能压力，与 insertFileRecord 同款"每条一 prepare"写法无碍。注意 `start_offset/length` 是 int64 绑定——2 TiB 以上镜像的字节偏移超 32 位，这里是必须的。`getFileCount` 的返回值语义是**三态坍缩成 int**：prepare 失败 -1、step 非 ROW -1、成功才是 ≥0——调用方必须判负，把 -1 当 0 用会把"库坏了"伪装成"空镜像"。COUNT(*) 在有 idx_files_* 索引下仍是全表扫级别（SQLite 会选最小索引扫描），几十万行毫秒级，只用于初始化后的统计输出而非循环内轮询。

### 4.6 代码走读：executeSQL 的公共出口与"吞错"边界（DatabaseManager.cpp:229-237）

```cpp
bool DatabaseManager::executeSQL(const std::string& sql) {
    char* errMsg = nullptr;
    if (sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, &errMsg) != SQLITE_OK) {
        std::cerr << "SQL error: " << (errMsg ? errMsg : "unknown") << std::endl;
        sqlite3_free(errMsg);
        return false;
    }
    return true;
}
```

逐块解释：类内所有 DDL（建表/建索引/ALTER/PRAGMA）都从这个 4 行函数走。`sqlite3_exec` 是"prepare+step+finalize"的批量包装，errMsg 由 SQLite malloc 分配、**必须 sqlite3_free**（此处正确）。打日志后返回 false——但注意调用方的三种态度：createTables 里建表失败会中止 initialize（致命）；建索引/ALTER/PRAGMA 的返回值被丢弃（非致命，第 6 节已列）。同一个出口、三档容错，全部由调用点决定——读代码时"executeSQL 失败到底要不要紧"必须看调用处是否检查返回值。`errMsg` 的空判（`errMsg ? errMsg : "unknown"`）防极少数不填 errMsg 的错误码，细节扎实。

## 5. 与其他模块的协作

- **ImageAnalyzer → DatabaseManager**：唯一的大批量写入方；raw.db 是后续所有阶段的输入。
- **FileExtractor ↔ DatabaseManager**：FileExtractor 通过组合持有它（`FileExtractor.h:107`），同时把 `FileRecord` 结构当作查询结果的载体共用。
- **FileClassifier / EventExtractor**：不使用 DatabaseManager 类本身，而是沿用其 PRAGMA 基线与 SQL-as-headers 模式各自开库（详见各自文档）。`SQL/file_classifier_sql.h` 的 ALTER 数组反而是被 DatabaseManager 的迁移代码消费的（`DatabaseManager.cpp:72-74`）——跨模块共享 SQL 的实例。
- **ConfigManager**：三个 DB PRAGMA 的来源（`ConfigManager.cpp:146-148`）。相关 .env：`DB_BUSY_TIMEOUT_MS`（默认 5000ms）、`DB_JOURNAL_MODE`（默认 "WAL"）、`DB_SYNCHRONOUS_OFF`（默认 false）。
- **AuditLog**：开库成功/失败各记一条（`DatabaseManager.cpp:23, 49`）。
- 出错时行为：initialize 失败返回 false 并打 stderr，不抛异常；insert 失败同样只返回 false——上游决定"跳过该文件还是中止任务"。
- 表契约：只拥有 raw.db 的 `files`（22 列，含 5 个 llm_*）与 `partitions`（6 列）两表、5 个 `idx_files_*` 索引；24 张分类分表在 FileClassifier，事件表在 EventExtractor——本模块不是"所有表的总管"。

## 6. 注意事项与已知问题

- **`insertEventRecord` 是死声明**：头文件 `DatabaseManager.h:49` 声明了它，`.cpp` 中无任何定义——事件写入实际由 EventExtractor 完成。链接期若有人调用会报 undefined reference，属于应删除的遗留。
- **无事务包裹的批量插入**：`insertFileRecord` 每条自动提交一次。WAL 下尚可接受，但数十万文件的镜像落库明显慢于 EventExtractor/FileClassifier 的事务批写（它们在各自代码里显式 `BEGIN/COMMIT`）。大镜像优化时可在此处加事务开关。
- **迁移不删列、不改类型**，只做加法；schema 演进要克制在这套"探测 + ALTER"能表达的范围内，更复杂的变更需写独立迁移脚本（仓库根 `migrations/` 目录是 Python 侧的位置）。
- `getDb()` 暴露裸句柄意味着调用方可能绕过本类的所有防护——用于只读查询可接受，用它写入则失去统一入口。
- 24 张分类表（在 FileClassifier.md 详述）不在本模块，但很多人误以为 DatabaseManager 管理所有表——它只拥有 raw.db 的两张。
- journal_mode PRAGMA 的返回值未检查（`DatabaseManager.cpp:32`），非法配置值会静默回退默认 journal 模式。
- initialize 之外的任何调用都没有 null 检查：未 initialize 就 insert 会在 `db_ == nullptr` 上崩溃（sqlite3_prepare_v2 传 null 句柄）——生命周期约定是"构造后立即 initialize，失败即弃用"。

## 7. 如何验证与扩展

- 直接验证：跑一次 CLI 分析（`./forensic_analyzer <image>`），对产物 `<base>_raw.db` 执行 `sqlite3 <db> '.schema'` 与 `PRAGMA table_info(files)`，对照 `DatabaseManager.cpp:80-105` 与 `SQL/file_classifier_sql.h` 的定义。
- 相关测试：raw.db 结构由 `tests/UnitTest/test_image_analyzer_gtest.cpp` 间接覆盖；子模块各有专属测试（见 EventExtractor.md / FileClassifier.md 第 7 节）。
- 扩展新列的标准流程：(1) 在 `SQL/` 对应头文件加"新库列"（改 CREATE TABLE）与"旧库迁移"（加进 ALTER 数组）；(2) 在 `checkAndMigrate()` 的探测条件里把新列名纳入判断（当前探测 llm_summary 一个代表列）；(3) 更新 `insertFileRecord` 的绑定。忘了第 (2) 步的后果是旧库升级不完整——这正是模板强调迁移的原因。

## 8. 产出表列级说明（raw.db）

本模块直接拥有的两张表，DDL 定义于 `DatabaseManager.cpp:80-105`（files）与 `:125-134`（partitions），索引 `:141-145`。

**files（22 列）**：

| 列名 | 类型 | 含义 | 写入条件 |
|---|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | 行 ID | 自动；插入不绑 |
| `inode` | INTEGER | inode 号（与 partition_num 组成自然键） | insertFileRecord bind 1 |
| `name` | TEXT | 文件名 | bind 2 |
| `path` | TEXT | 全路径 | bind 3 |
| `size` | INTEGER | 字节数 | bind 4 |
| `atime`/`mtime`/`ctime`/`crtime` | INTEGER | 访问/修改/元数据变更/创建时间（Unix 秒；crtime 缺失为 0） | bind 5-8 |
| `type` | TEXT | TSKit 类型（REG/DIR/LNK/UNDEF…） | bind 9 |
| `md5` | TEXT | 哈希（ImageAnalyzer 可选计算，未算为空串） | bind 10 |
| `is_deleted` | INTEGER | 已删除标志 | bind 11 |
| `is_allocated` | INTEGER | 已分配标志 | bind 12 |
| `permissions` | TEXT | 权限串 | bind 13 |
| `uid`/`gid` | INTEGER | 属主/组 | bind 14-15 |
| `llm_summary` | TEXT | LLM 摘要 | **死列**：见下文 |
| `llm_description` | TEXT | LLM 描述 | **死列** |
| `llm_keywords` | TEXT | LLM 关键词 | **死列** |
| `llm_analyzed_at` | INTEGER | LLM 分析时刻 | **死列** |
| `llm_model_used` | TEXT | LLM 模型名 | **死列** |
| `partition_num` | INTEGER DEFAULT 0 | 分区号（0=无分区表/单 FS） | bind 16 |

**llm_* 五列在 raw.db 中是死列**（本轮核实）：CREATE TABLE 与 checkAndMigrate 的 ALTER 都会建出它们，但 `insertFileRecord` 的 16 列清单（`:150-156`）不含任何 llm_*，且全仓库对 files 表 llm_* 的 UPDATE 全部打在 **files.db** 上（LLMAnalysisService.cpp:367 用 FileClassifierSQL::UPDATE_FILE_LLM_ANALYSIS 时注释明确 "Store directly to _files.db"，`LLMAnalysisService.cpp:166,220`；三个平台 LLMAnalysisService_Database.cpp:35-36 的 UPDATE 按 tableName 拼、目标是各工件表）。raw.db 的这五列因此恒为 NULL——它们是从 file_classifier_sql.h 的建表语句"带过来"的历史痕迹（两处 CREATE 同源演化）。TOONExporter 读取的 llm_*（TOONExporter.cpp:82-83）作用在调用方传入的库句柄上（实际是 files.db），不受影响。查询 raw.db 时 `WHERE llm_analyzed_at IS NOT NULL` 永远为空，不要据此判断 LLM 分析状态。

**partitions（6 列）**：`id`（PK 自增）、`partition_num`（分区号）、`start_offset`（起始字节偏移，int64）、`length`（字节长）、`description`（分区名/描述）、`fs_type`（文件系统类型，如 NTFS/EXT4）。写入方仅 ImageAnalyzer 的分区枚举。

**索引 5 个**（`DatabaseManager.cpp:141-145`）：`idx_files_inode(inode)`、`idx_files_path(path)`、`idx_files_type(type)`、`idx_files_deleted(is_deleted)`、`idx_files_partition(partition_num)`。注意 **inode 索引不带 partition_num 复合**——FileExtractor 按 inode 查询时多分区镜像会命中多行，需要应用层再过滤分区号；没有 (inode, partition_num) 复合索引是已知可优化点。

## 9. 方法全清单（含私有）

公开方法已列 3.2 节；私有面与文件布局：

| 方法 | 定义位置 | 语义 | 调用方 |
|---|---|---|---|
| `~DatabaseManager()` | DatabaseManager.cpp:13-17 | close 连接 | RAII |
| `createTables()`（私有） | :78-148 | 建 files/partitions 两表 + partition_num 吞错迁移 + 5 索引 | initialize |
| `checkAndMigrate()`（私有） | :53-76 | 探测 llm_summary 补五列（语句来自 FileClassifierSQL） | initialize |
| `executeSQL(sql)`（私有） | :229-237 | sqlite3_exec 包装，stderr+返回 false | initialize/createTables/checkAndMigrate |
| `insertFileRecord` | :150-186 | 16 列参数化 INSERT | ImageAnalyzer |
| `insertPartitionInfo` | :189-214 | 5 列参数化 INSERT | ImageAnalyzer |
| `getFileCount` | :216-227 | COUNT(*)，失败 -1 | 统计/进度 |
| `getDb()/getDbPath()` | .h:73 一带 | 裸句柄/路径 | FileExtractor、平台分析器 |
| `insertEventRecord`（死声明） | .h:49 | 无定义 | 无（第 6 节） |

## 10. SQL/ 头文件族全清单（本模块视角）

`SQL/` 目录 16 个头文件是全系统 schema 的唯一权威。规模与组织方式（统计口径：文件内出现次数）：

| 头文件 | 命名空间 | CREATE TABLE | SELECT | 服务的库/组件 |
|---|---|---|---|---|
| file_classifier_sql.h | FileClassifierSQL | 5 | 89 | files.db 主表+24 分类分表（FileClassifier） |
| event_extractor_sql.h | EventExtractorSQL | 9 | 12 | events.db（EventExtractor） |
| android_analysis_sql.h | AndroidAnalysisSQL | 34 | 0 | files.db 的 Android 工件表（AndroidAnalyzer） |
| android_analysis_sql_llm.h | android_analysis_sql_llm | 0 | 30 | Android LLM 分析查询 |
| windows_analysis_sql_tables.h | windows_analysis_sql_tables | 33 | 0 | files.db 的 Windows 工件表 DDL |
| windows_analysis_sql_crud.h | windows_analysis_sql_crud | 0 | 64 | Windows 工件 CRUD |
| windows_analysis_sql_llm.h | windows_analysis_sql_llm | 0 | 31 | Windows LLM 分析查询 |
| windows_analysis_sql.h | WindowsAnalysisSQL | 0 | 33 | 聚合器：using re-export 上述三个子头（:16-35 起） |
| linux_analysis_sql_tables.h | linux_analysis_sql_tables | 74 | 0 | files.db 的 Linux 工件表 DDL |
| linux_analysis_sql.h | LinuxAnalysisSQL | 0 | 76 | Linux 工件查询 |
| linux_analysis_sql_crud.h | linux_analysis_sql_crud | 0 | 73 | Linux 工件 CRUD |
| linux_analysis_sql_llm.h | linux_analysis_sql_llm | 0 | 73 | Linux LLM 分析查询（**含引用不存在列的 7 条 SELECT**，见 LinuxFilesAnalyzer.md） |
| memory_analysis_sql_tables.h | MemoryAnalysisSQL | 7 | 0 | memory.db 表 DDL |
| memory_analysis_sql_crud.h | MemoryAnalysisSQL | 0 | 1 | memory CRUD |
| memory_analysis_sql.h | （无命名空间，纯 include 聚合，全文 11 行） | 0 | 0 | MemoryAnalyzer 的统一入口 |
| oss_sql.h | SQL::OSS | 3 | 32 | OSS 云工件 |

命名空间大小写不统一（FileClassifierSQL 大驼峰 vs windows_analysis_sql_tables 全小写）是两批贡献风格的痕迹；oss_sql.h 的 `SQL::OSS` 又是第三种。聚合模式（tables/crud/llm 三分 + using re-export）只在 Windows/Linux/Memory 三家采用，Android 是单文件 34 表未拆分——**同一目录三种组织风格并存**，检索 schema 时先看文件名后缀（_tables=DDL、_crud=增删改、_llm=LLM 查询、无后缀=聚合或早期形态）。

## 11. 关联矩阵

| 对端 | 方向 | 交互点 | 数据形态 |
|---|---|---|---|
| ImageAnalyzer | 上游 | initialize/insertFileRecord/insertPartitionInfo/getFileCount | FileRecord 结构体 |
| FileExtractor | 下游 | 组合持有（FileExtractor.h:107）；getDb() 裸句柄 + FileRecord 载体 | sqlite3* / SELECT 结果 |
| Android/Windows/Linux/OSSAnalyzer | 下游 | 构造注入 dbMgr（AnalysisOrchestrator.cpp:278-318）；经 getDb() 读 raw 清单 | 裸句柄只读 |
| EventExtractor/FileClassifier | 平行 | 不用本类；复用 PRAGMA 基线（各自 openDatabases）+ 消费 FileClassifierSQL::ALTER 数组（DatabaseManager.cpp:72-74 反向依赖） | SQL 头文件共享 |
| ConfigManager | 上游 | DB_BUSY_TIMEOUT_MS/DB_JOURNAL_MODE/DB_SYNCHRONOUS_OFF（DatabaseManager.cpp:28-36） | int/string/bool |
| AuditLog | 下游 | DB_INIT / DB_INIT_FAILED（:23,49） | 审计条目 |
| TOONExporter | 平行 | 不经本类；直接 SELECT files（含 llm_*），实际指向 files.db | 独立开库 |
| queries/（HTTP 查询层） | 下游 | column_exists 探测 llm_* 后动态投影（AndroidQueries.cpp:435-439） | 兼容有无列的两种库 |

## 12. 配置影响表

| 参数 | 默认 | 影响 | 备注 |
|---|---|---|---|
| `DB_BUSY_TIMEOUT_MS` | 5000 | 并发写等待上限（DatabaseManager.cpp:28-29） | 不在 .env.example |
| `DB_JOURNAL_MODE` | WAL | journal 模式；字符串拼进 PRAGMA（:31-32） | 非法值静默回退默认 journal |
| `DB_SYNCHRONOUS_OFF` | false | 开启则 synchronous=OFF（:34-36） | 断电丢最近事务，取证慎开 |
| `THREAD_POOL_SIZE` | 4 | 不直接影响本类（单连接单线程写） | 影响 ImageAnalyzer 的并行度 |
| 其余键 | — | 本类不读其他配置 | |



## 13. 性能与并发细节

- **每条一事务的成本结构**：insertFileRecord 无事务包裹，WAL 模式下每条 INSERT = 一次 WAL 帧追加 + 一次提交（synchronous 默认 FULL 时还要 fsync WAL——注意本模块**没有设 synchronous=NORMAL**，与 AuditLog/EventExtractor 不同，同机默认下 raw.db 落库比 events.db 慢一个数量级的场景真实存在）。十万级文件镜像的优化路径：外层开 BEGIN/COMMIT（ImageAnalyzer 侧批 5000 条一提交）或在此类加事务开关。
- **prepare 不复用**：每条记录 prepare+finalize 一次，SQL 解析占单条成本的相当比例；对比 AuditLog 常驻 insert_stmt_。改动时注意语句是局部 const char*，改成员常驻即可，但需引入语句互斥（多线程写同连接本身就不允许，SQLite 单连接非线程安全——当前设计用"调用方串行调用"保证）。
- **锁与线程模型**：一个 DatabaseManager 实例 = 一条连接，不是线程安全对象；ImageAnalyzer 在扫描线程串行调用。跨实例并发（FileExtractor 读 raw.db 同时另一进程写）由 WAL + busy_timeout 兜底：读不阻塞、写等 5 秒。
- **内存特征**：无行缓存，全流式；FileRecord 是值语义结构体（约 200 字节 + 字符串），扫描循环中每文件一次构造销毁。
- **IO 大头**：建库期写 files 表与 5 个索引（每条 INSERT 维护 5 棵 B 树）；md5 计算的镜像读开销在 ImageAnalyzer 侧，与本类无关。
- **可调参数影响**：DB_SYNCHRONOUS_OFF=true 对本类的加速最直接（省每条提交的 fsync）；DB_BUSY_TIMEOUT_MS 只在跨进程并发时起作用；journal_mode=WAL 是读并发的前提，换 DELETE 模式会让 FileExtractor 的同时读直接吃 SHARED 锁竞争。

**最后更新**: 2026-08-24（二轮深化：补全表列说明与方法清单）
