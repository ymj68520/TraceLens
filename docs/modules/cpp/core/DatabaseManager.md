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

## 4. 工作流程走读

以 CLI 分析的 raw.db 生成阶段为例：

1. ImageAnalyzer 构造 `DatabaseManager(rawDbPath)` 后调 `initialize()`（`DatabaseManager.cpp:19-51`）：打开连接 → 应用 PRAGMA → `createTables()` 建表建索引 → `checkAndMigrate()` 补列 → 写一条 `DB_INIT` 审计（`:49`）。
2. 扫描循环中每发现一个文件/分区，调用 `insertFileRecord`（`:150-187`）/`insertPartitionInfo`（`:189-214`）。两者都是标准的 prepare-bind-step-finalize 五步，全部参数绑定、无字符串拼接（路径来自镜像内容，参数化是安全底线）。
3. 消费方（FileExtractor 等）或以对象身份调 `getFileCount()`（`:216-227`），或用 `getDb()`（`DatabaseManager.h:73`）拿裸 `sqlite3*` 自行 prepare 查询——这是刻意保留的逃生口，让查询逻辑不必都塞进本类。
4. 析构关闭连接（`:13-17`）。

## 5. 与其他模块的协作

- **ImageAnalyzer → DatabaseManager**：唯一的大批量写入方；raw.db 是后续所有阶段的输入。
- **FileExtractor ↔ DatabaseManager**：FileExtractor 通过组合持有它（`FileExtractor.h:107`），同时把 `FileRecord` 结构当作查询结果的载体共用。
- **FileClassifier / EventExtractor**：不使用 DatabaseManager 类本身，而是沿用其 PRAGMA 基线与 SQL-as-headers 模式各自开库（详见各自文档）。`SQL/file_classifier_sql.h` 的 ALTER 数组反而是被 DatabaseManager 的迁移代码消费的（`DatabaseManager.cpp:72-74`）——跨模块共享 SQL 的实例。
- **ConfigManager**：三个 DB PRAGMA 的来源（`ConfigManager.cpp:146-148`）。
- **AuditLog**：开库成功/失败各记一条（`DatabaseManager.cpp:23, 49`）。
- 出错时行为：initialize 失败返回 false 并打 stderr，不抛异常；insert 失败同样只返回 false——上游决定"跳过该文件还是中止任务"。

## 6. 注意事项与已知问题

- **`insertEventRecord` 是死声明**：头文件 `DatabaseManager.h:49` 声明了它，`.cpp` 中无任何定义——事件写入实际由 EventExtractor 完成。链接期若有人调用会报 undefined reference，属于应删除的遗留。
- **无事务包裹的批量插入**：`insertFileRecord` 每条自动提交一次。WAL 下尚可接受，但数十万文件的镜像落库明显慢于 EventExtractor/FileClassifier 的事务批写（它们在各自代码里显式 `BEGIN/COMMIT`）。大镜像优化时可在此处加事务开关。
- **迁移不删列、不改类型**，只做加法；schema 演进要克制在这套"探测 + ALTER"能表达的范围内，更复杂的变更需写独立迁移脚本（仓库根 `migrations/` 目录是 Python 侧的位置）。
- `getDb()` 暴露裸句柄意味着调用方可能绕过本类的所有防护——用于只读查询可接受，用它写入则失去统一入口。
- 24 张分类表（在 FileClassifier.md 详述）不在本模块，但很多人误以为 DatabaseManager 管理所有表——它只拥有 raw.db 的两张。

## 7. 如何验证与扩展

- 直接验证：跑一次 CLI 分析（`./forensic_analyzer <image>`），对产物 `<base>_raw.db` 执行 `sqlite3 <db> '.schema'` 与 `PRAGMA table_info(files)`，对照 `DatabaseManager.cpp:80-105` 与 `SQL/file_classifier_sql.h` 的定义。
- 相关测试：raw.db 结构由 `tests/UnitTest/test_image_analyzer_gtest.cpp` 间接覆盖；子模块各有专属测试（见 EventExtractor.md / FileClassifier.md 第 7 节）。
- 扩展新列的标准流程：(1) 在 `SQL/` 对应头文件加"新库列"（改 CREATE TABLE）与"旧库迁移"（加进 ALTER 数组）；(2) 在 `checkAndMigrate()` 的探测条件里把新列名纳入判断（当前探测 llm_summary 一个代表列）；(3) 更新 `insertFileRecord` 的绑定。忘了第 (2) 步的后果是旧库升级不完整——这正是模板强调迁移的原因。

**最后更新**: 2026-08-23（解释式重写）
