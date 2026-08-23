# DatabaseAnalyzer（src/analyzers/DatabaseAnalyzer/）

> **一句话**：数据库取证专用分析器——离线解析 SQLite 数据库文件和 MySQL/PostgreSQL 数据目录，提取表结构、记录、用户、工件，甚至恢复已删除记录，结果写入独立结果库的五张 `db_*` 表。
>
> **状态提示**：模块已编译进主程序（CMakeLists 挂入 LIB_SOURCES），但目前**没有任何生产调用方**——CLI 没有 `--analyze-dbs` 参数，HTTP 流水线不跑它，仅单元测试在用。详见第 2 节。

## 1. 为什么有这个模块

数据库是应用系统的"记忆"，也是取证时信息密度最高的证据之一：诈骗案的转账记录、入侵案的后门账号、业务系统的操作流水都在里面。但数据库证据有个特殊困难——**取证镜像里拿到的是"死"的数据文件**（SQLite 文件、MySQL 的数据目录、PostgreSQL 的 base 目录），不是正在运行的服务。要读它们，要么找到能离线解析其存储格式的工具，要么想办法把数据库引擎"复活"起来。这个模块两条路都走了，并且按数据库类型做了完全不同的取舍。

设计上是教科书式的**策略模式**（头文件注释原话）：`IDBParser` 定义统一接口（open/getTables/getRecords/getUsers/extractArtifacts/recoverDeletedRecords），`DBParserFactory` 按检测到的类型实例化 `SQLiteAnalyzer`/`MySQLAnalyzer`/`PostgreSQLAnalyzer`，`DatabaseAnalyzer` 主类只做编排和落库。加一种新数据库（比如 Redis 的 RDB）只需要注册一个新的解析器，编排层零改动。

第三条腿是**删除记录恢复**——数据库取证和文件取证一样，"被删的数据"往往比现存数据更有故事。SQLite 侧读 freelist 页，InnoDB 侧解析页目录找残留记录，PostgreSQL 侧找死元组（dead tuples）。这些能力深度不一（见第 4 节的诚实评估），但接口上是一致的。

## 2. 在流水线中的位置

**当前没有流水线位置。** 逐一核实过的现状：

- `CommandLineParser` 的全部参数里没有 `--analyze-dbs`（`src/CommandLineParser.cpp` 通读可证）；
- `AnalysisOrchestrator` 不 include 也不构造 `DatabaseAnalyzer`；
- HTTP TaskManager 的各阶段同样不涉及；
- 唯一的调用方是测试：`tests/UnitTest/test_database_analyzer_gtest.cpp`、`tests/test_mysql_daemon.cpp`。

所以它是"已建成、未接入"的模块——代码质量完整（类型检测、进度回调、会话管理都有），二进制里也带着，但用户目前无法从任何入口触发它。预期的使用方式（也是它的 API 设计意图）是：`initialize(<结果库路径>)` → `analyze(<库文件或数据目录>)`（自动检测类型）或 `analyzeDirectory(<目录>, recursive)` 批量扫。输出是结果库中的五张表：db_sessions（每次分析一个会话，含版本/文件大小/统计）、db_tables、db_records、db_artifacts、db_users（建表见 `Database/DBAnalysisDatabase.cpp:48-114`）。

注意与 LinuxFilesAnalyzer 的 `analyzeDatabaseLogs()` 区分：那是解析 MySQL/PostgreSQL 的**日志文件**（慢查询日志、错误日志），写 linux.db；本模块解析的是**数据文件本体**。两者互补，无调用关系。

## 3. 证据来源与覆盖范围

类型检测在 `DBParserFactory::detectType`（`Parsers/DBParserFactory.cpp:55-...`），识别三种证据形态：

| 类型 | 识别特征 | 解析路径 |
|------|---------|---------|
| SQLite | 文件头 16 字节魔数 `SQLite format 3\0`（`isSQLiteFile`，第 123-129 行） | 直接读写文件（sqlite3 API + 自研 forensics） |
| MySQL | 目录下有 `mysql/` 系统库子目录或 `ibdata1`（第 133-145 行） | 目录扫描 `.frm/.myi/.myd/.ibd` + 可选拉起 mysqld + binlog/InnoDB 解析 |
| PostgreSQL | 目录下有 `PG_VERSION`（最可靠）或 `postgresql.conf`/`base/`（第 165-186 行） | 可选拉起 postgres + 离线 heap 文件解析 |

MySQL 数据目录里能提取的工件面（`MySQLAnalyzer.cpp`）：数据库名清单、表清单（5.x 靠 `.frm` 文件名）、用户信息（`mysql/user.frm` 存在性 + InnoDB 系统表空间解析）、binlog 事件（详见第 4 节）。PostgreSQL 侧额外会读 `postmaster.pid`（判断上次是否非正常关闭，`PostgreSQLAnalyzer.cpp:383-390`）这类"数据库自己知道的异常"。

## 4. 解析机制走读

**链路一：统一分析流水（`doAnalyze`，`Core/DatabaseAnalyzerCore.cpp:72-178`）。** 每次分析开一个会话（`beginSession` 记录路径/类型/版本），然后五步：`getTables` 全量表结构入库；按 `options_` 的开关与 include/exclude 表名单、每表 `maxRecordsPerTable` 上限提取记录；`extractArtifacts` 拿数据库特有的取证工件（freelist、加密标志等）；`getUsers` 提用户；`extractDeletedRecords` 跑删除恢复并统一打 `isDeleted=true` 标记。异常被捕获进 `summary.lastError` 而不是中断——库读了一半坏掉时已提取的部分仍然保留，会话总是正常收尾（`endSession`）。

**链路二：MySQL 的"两条腿"——离线元数据 + 复活引擎。** `MySQLAnalyzer::open()` 先离线扫数据目录（`scanDataDirectory`，第 117 行起），表结构靠解析 `.frm` 文件（`parseFrmFile` 自知是"基本解析"，第 215-221 行），同时尝试 `MySQLDaemon`：fork 一个 `mysqld --skip-grant-tables --skip-networking --socket=<临时socket> --datadir=<数据目录>`（`MySQLDaemon.cpp:39-40`），起来后就能用 MySQL C API 真正查询记录。daemon 起不来不阻塞 open——退化为"只有元数据"的模式（`MySQLAnalyzer.cpp:65-72` 的注释写明了这个降级）。配套的 `MySQLBinlogParser` 离线解析 binlog：FormatDescription/Query/TableMap/Rows/Rotate 五类事件（`MySQLBinlogParser.h:133-141`），能重建"谁在什么时间改了什么数据"；`InnoDBParser` 则手工解析 ibdata/.ibd 的 FIL 页头、页目录与记录（`InnoDBParser.h:19-45` 的偏移常量），用于引擎不可用时的兜底。

**链路三：SQLite 取证与删除恢复的诚实现状。** `SQLiteAnalyzer` 用 sqlite3 API 做常规表/记录提取，`SQLiteAnalyzer_Forensics.cpp` 做取证增强：读 freelist 页数作为工件（第 141-148 行），`recoverDeletedRecords`（第 181 行起）标注了 `TODO: 实现完整的freelist解析和记录恢复`——当前只统计 freelist 规模，并没有真正从 freelist 页里挖出记录内容。PostgreSQL 的 `PostgreSQLHeapParser` 是更完整的离线解析器：按 8KB 块读页头（PD_LSN/PD_LOWER 等偏移，`PostgreSQLHeapParser.h:25-35`）逐元组提取，能识别死元组。

## 5. 与 LLM 的协作

无。模块自身不接 LLM；预期的接入点是分析完之后把 db_records 里的敏感内容交给平台 LLM 服务，但目前连调用方都没有，谈不上 LLM 管道。

## 6. 与其他模块的协作 / 注意事项

- **无调用方（重要）**：见第 2 节。想启用它需要在 CommandLineParser 加参数、在 AnalysisOrchestrator 加一个 `runDatabaseAnalysis`，或挂进 HTTP 任务阶段——API 已就绪。
- **外部依赖**：MySQL C API（`mysql/mysql.h`，随 MySQLDaemon）、libpq（PostgreSQLDaemon）；引擎二进制 mysqld/postgres 在运行时 PATH 探测（`which mysqld`，`MySQLDaemon.cpp:24`），缺失则降级。
- **取证完整性警告**：`MySQLDaemon` 直接对**原始数据目录**拉起 mysqld（`--datadir` 指向传入路径，无拷贝/快照步骤），InnoDB 引擎启动时会写 redo 日志、更新文件——这会**修改证据**。PostgreSQLDaemon 同理。若要用于真实取证流程，务必先对数据目录做副本再喂给分析器，或改造 daemon 加 copy-on-open。这是模块接入流水线前必须解决的问题。
- **`connect(DBConnectionConfig)` 是预留接口**，未实现（`MySQLAnalyzer.cpp:76-83` 明确报错提示用 open()）。
- **与 DatabaseManager（core/）无关**：那是本项目的 SQLite 结果库管理类；这里的 `DBAnalysisDatabase` 是模块自己的结果库封装，名字相近但完全独立。

## 7. 如何验证与扩展

- 测试：`tests/UnitTest/test_database_analyzer_gtest.cpp`（类型枚举、工厂注册、选项默认值）、`tests/test_mysql_daemon.cpp`（daemon 生命周期）。端到端验证：手工构造一个 SQLite 文件 + `initialize("out.db"); analyze("test.db")`，检查 db_sessions/db_tables/db_records 的会话闭环。
- 加新数据库类型：实现 `IDBParser` 的全部虚函数，在 `DBParserFactory::getRegistry()` 注册 lambda，`DatabaseType` 枚举加值，`detectType` 加识别特征（`DBParserFactory.cpp:27-41` 的注册表是唯一需要动的工厂代码）。
- 接入流水线的最小改法：给 `CommandLineArgs` 加 `analyze_dbs` 标志与目标路径参数，`main.cpp` 路由到新的 `AnalysisOrchestrator::runDatabaseAnalysis`（照抄 `runDLLAnalysis` 的骨架即可，`AnalysisOrchestrator.cpp:710-752`）。

**最后更新**: 2026-08-23（解释式重写）
