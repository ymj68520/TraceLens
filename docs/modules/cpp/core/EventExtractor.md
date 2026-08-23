# EventExtractor（src/core/DatabaseManager/EventExtractor/）

> **一句话**：时间线工厂——读取 raw.db 里每个文件的四个时间戳，展开成 CREATED/MODIFIED/ACCESSED/CHANGED/DELETED 五类事件写入 events.db，再把平台分析器产出的工件（Windows 事件日志、Linux syslog、Android log 等）合并进同一条时间线，最后为每个事件标注来源/类别/优先级/严重度。

## 1. 为什么有这个模块

取证的核心产出之一是**时间线**：调查者要回答"攻击者什么时候建了文件、什么时候执行、什么时候删除"。文件系统本身只给了每个 inode 四个时间戳——这不是"事件"，只是状态快照。把 `crtime` 解释为"创建事件"、把未分配空间里的 inode 解释为"删除事件"，这层语义转换必须有专门代码来做，而且要处理大量取证细节：crtime 缺失（旧文件系统）怎么办、atime 等于 mtime 时还算独立的"访问事件"吗、删除时间没有专门字段时用哪个时间近似。

同时，时间线不能只有文件系统事件。Windows 的预取文件、回收站，Linux 的 wtmp/cron/audit，Android 的 logcat——这些平台工件由各自的 Analyzer 解析进独立的表（windows.db/linux.db/android.db 或 files.db 的工件表），事件形状各异。EventExtractor 的第二职责是把这些异构记录**翻译成统一的 events 行**，让前端时间线视图和 LLM 分析面对的是一张表而不是七张。

"标准化"（standardize）步骤则解决第三个问题：事件来自五个来源，`WIN_LOG_error`、`LINUX_SYSLOG`、`FILE_DELETED` 的命名各自为政。入库后统一补上 normalized_type（规范化类型名）、source（来源枚举）、category（十类业务类别）、priority/severity（四档），下游的聚类、过滤、LLM 提示生成才能按键分组。

## 2. 在系统中的位置

EventExtractor 是流水线 EVENT_EXTRACTION 阶段的执行者，两个生产调用点：

- HTTP 任务流水线：`src/network/HTTPServer/TaskManagerAnalysis.cpp:303`（`std::make_unique<EventExtractor>(effectiveRawDb, eventDbPath)`，随后 `extractEvents()` 与按需 `import*Artifacts`）；
- CLI 模式：`src/AnalysisOrchestrator.cpp:331-339`，同样三步。

输入是上游 IMAGE_ANALYSIS/FILE_CLASSIFICATION 的产物 raw.db（files 表），以及可选的 files.db / 平台库（import 阶段 ATTACH 进来读）。输出是 `data/tasks/<task_id>/events.db`（HTTP 模式）或 `<镜像名>_events.db`（CLI 模式）——库文件名由调用方给定，目录归属见 PathManager.md。

```
raw.db(files) ──extractFileSystemEvents──┐
files.db 的 *_artifacts 表 ──import*──┤──> events.db
windows/linux/android.db ──ATTACH import──┘      (events + 5 张类型表 + system_events
                                                  + event_correlations + 视图)
```

它还包装了 EventCorrelationEngine（通过 `analyzeEventCorrelations()`，见第 6 节的"未被调用"说明）。

## 3. 核心概念与设计

**"一主表 + 五分表 + 视图"的库结构**。主表 `events`（`SQL/event_extractor_sql.h:14-35`）是所有事件的汇聚点，除时间/类型/路径外还带 priority/severity/event_source/event_category/normalized_type/source_id 六个标注列和七个 `llm_*` 列（供 LLM_ANALYSIS 阶段的 EventClusterAnalyzer 回写摘要，`src/network/HTTPServer/EventClusterAnalyzer.cpp`）。五张类型表（creation/modification/access/change/deletion_events，同文件 :37 起）与主表数据重复，是按操作类型的快速通道；视图层（timeline/statistics/hourly_activity 等，`EventExtractorCore.cpp:99-105` 创建）提供常用聚合。**查询应优先走视图，写入只走 insertEvent**。

**时间戳 → 事件的翻译规则**在 `extractFileSystemEvents()`（`Detail/FileSystemEventExtractor.cpp:62-245`），规则本身就是取证判断：

- crtime>0 → CREATED（`:121-141`）；
- mtime>0 且 **mtime != crtime** → MODIFIED（`:144-164`）——创建即最后修改的文件不再生成冗余"修改"事件；
- atime>0 且不等于 mtime/crtime → ACCESSED（`:167-187`）；
- ctime>0 且不等于 mtime/crtime → CHANGED（`:190-211`，inode 元数据变更）；
- is_deleted → DELETED，时间取四时间戳的最大值（`:214-235`）——删除时刻没有专门记录，这是保守近似。

只处理 `type='REG'`（`:63-67`），目录与符号链接不产生事件。

**import 的两种实现**按输入形态选择：(1) 平台独立库（windows.db 等）用 SQLite `ATTACH DATABASE` + `INSERT INTO events SELECT ... FROM win_db.<表>` 纯 SQL 搬运（`Detail/SystemEventExtractor.cpp:9-100`，Windows 一次导入事件日志/浏览器/服务/计划任务/预取/USB/回收站/Amcache 约 11 类，`:15-92`；Linux 9 类，`:102-185`；Android 目前仅 system_logs 一类，`:187-205`）；(2) 统一 files.db 场景库的 `*_artifacts` 工件表用 C++ 逐行读出再 insertEvent（`importSceneArtifacts` 分发，`EventExtractorCore.cpp:280-293`）。前者快（SQL 引擎内完成），后者能在行进途中构造事件对象。

**标准化流水线**（`EventExtractorCore.cpp:111-244` 的事务版 + `:247-269` 的单事件版）：identifySource（事件类型字符串前缀匹配到十种来源，`Detail/EventCorrelationExtractor.cpp:206-267`）→ classifyEvent（十类业务类别，`:126-157`）→ assessPriority/assessSeverity（规则：DELETED=HIGH、含 SECURITY=CRITICAL、/tmp 等可疑路径升档等，`:160-203`）→ normalizeEventType（`CREATED`→`FILE_CREATED`、`WIN_LOG_*`→`WINDOWS_EVENT` 等映射表，`:270-313`）→ getSourceId（`FS_<inode>` 等来源内唯一 ID，`:316-331`）。全部在一个事务里 UPDATE 回主表（`:115, 238`），几十万事件也只有一次 fsync。

### 3.1 核心数据结构：TimelineEvent 与四个标注枚举（EventExtractor.h:12-71）

```cpp
enum class EventPriority { LOW, MEDIUM, HIGH, CRITICAL };
enum class EventSeverity { INFO, WARNING, ERROR, CRITICAL };

enum class EventSource {
    FILE_SYSTEM, WINDOWS_EVENT_LOG, LINUX_SYSLOG, ANDROID_LOG,
    WEB_BROWSER, SYSTEM, NETWORK, SECURITY, APPLICATION, UNKNOWN
};

enum class EventCategory {
    FILE_OPERATION,        // 文件操作（创建、修改、访问、删除）
    SYSTEM_ACTIVITY,       // 系统活动（启动、关闭、服务）
    USER_ACTIVITY,         // 用户活动（登录、注销、权限变更）
    NETWORK_ACTIVITY,      // 网络活动（连接、断开、流量）
    SECURITY_EVENT,        // 安全事件（认证失败、权限提升）
    APPLICATION_EVENT,     // 应用程序事件（启动、错误、崩溃）
    DATABASE_ACTIVITY,     // 数据库活动（查询、更新、备份）
    HARDWARE_EVENT,        // 硬件事件（设备连接、故障）
    EXTERNAL_SOURCE,       // 外部来源事件
    UNKNOWN_CATEGORY
};

struct TimelineEvent {
	int64_t timestamp;
	std::string eventType;  // CREATED, MODIFIED, ACCESSED, CHANGED, DELETED
	std::string filePath;
	int64_t inode;
	std::string description;
	int64_t fileSize;
	std::string fileType;
	std::string systemContext;
	EventPriority priority;     // 事件优先级
	EventSeverity severity;     // 事件严重程度
	EventSource source;         // 事件来源
	EventCategory category;     // 事件类别
	std::string normalizedType; // 标准化事件类型
	std::string sourceId;       // 事件来源ID
};
```

逐组解释：`EventPriority`（行动紧急度）与 `EventSeverity`（结果严重度）是**两个正交刻度**——一条 INFO 级的 FILE_DELETED 也有 HIGH 优先级（删除是强取证信号），不要混用。`EventSource` 十值回答"谁记录的"（识别靠 identifySource 的类型前缀匹配，如 WIN_ 前缀 → WINDOWS_EVENT_LOG）；`EventCategory` 十值回答"业务上算哪类活动"，是前端筛选与 LLM 聚类的主键。`TimelineEvent` 是插入前的内存形态：前 8 个字段是事实（来自 raw.db 列或平台表），后 6 个是标注（标准化流水线填充）——**落库时枚举全部经 *ToString 转文本**（`FileSystemEventExtractor.cpp:265-270` 的绑定可见），events 表里没有整数枚举。`SystemEvent`（h:73-85）与 `EventCorrelation`（h:87-93）分别服务 system_events 表与关联分析，后者含 confidence（0-1）字段。

### 3.2 核心接口清单

| 签名（EventExtractor.h） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `EventExtractor(sourceDbPath, eventDbPath)` | 记录双库路径，不开连接 | TaskManagerAnalysis.cpp:303、AnalysisOrchestrator.cpp:331 | 无 |
| `bool extractEvents()` | 主流程：开库→建表→FS 事件→标准化 | 两个编排方 | 任一步失败返回 false |
| `bool importWindowsArtifacts(windowsDbPath)` | ATTACH 平台库 + 11 段 INSERT..SELECT | TMA 平台段后 / Orchestrator | 单段 SQL 失败静默，恒返回 true |
| `bool importLinuxArtifacts(linuxDbPath)` / `bool importAndroidArtifacts(androidDbPath)` | 同上（9 类 / 1 类） | 同上 | 同上 |
| `bool importSceneArtifacts(fileDbPath, sceneType)` | 统一 files.db 工件表 → C++ 逐行 import | HTTP 流水线（传 files.db） | 分发到对应 FromFilesDb 实现 |
| `bool standardizeEvents()` | 补齐 normalized_type IS NULL 行的六项标注 | extractEvents/import 内部自动调用 | 失败返回 false（主流程视为致命） |
| `bool analyzeEventCorrelations()` | 构建关联/链/因果并导出 | **无生产调用方**（仅测试） | 见 EventCorrelationEngine.md |
| `bool extractSystemEvents()` / `bool insertSystemEvent(event)` | system_events 表的通用提取/写入 | **无生产调用方**（实验代码） | — |

## 4. 工作流程走读

以一次 HTTP 任务的 EVENT_EXTRACTION 阶段为例：

1. `extractEvents()` 入口（`EventExtractorCore.cpp:19-44`）：审计记录 → 打开两个库（`:46-67`，对 eventDb 应用 WAL + NORMAL + busy_timeout，注释明确写了"否则每次 commit 都 fsync 卡在 jbd2"）→ `createEventTables()`（`:69-108`，所有 DDL 来自 `SQL/event_extractor_sql.h`）。
2. `extractFileSystemEvents()` 扫 raw.db files 表，单个大事务内逐文件生成 0-5 个事件：先 `insertEvent` 写主表（`FileSystemEventExtractor.cpp:247-276`，14 个绑定参数），再手写 INSERT 进对应类型分表（如 :125-137）——同一数据写两处是本模块最"重"的写放大点。
3. `standardizeEvents()` 扫描 `normalized_type IS NULL` 的行（`EventExtractorCore.cpp:118-122`，天然幂等：重复运行只补未标注行），事务内逐行算标注并 UPDATE。
4. 调用方接着按需 import：`TaskManagerAnalysis.cpp` 在平台分析完成后调 `importWindowsArtifacts(fileDbPath)` 等——注意 HTTP 流水线传的是 **files.db**（统一场景库），所以实际走的是"检查 windows.db 风格表是否存在"的路径；ATTACH 失败会被 sqlite3_exec 静默吞掉，最终 `standardizeEvents()` 再跑一遍补标注。
5. 完成后审计 `EVENT_EXTRACTION_COMPLETE`（`:41`）。

### 4.1 代码走读：events 主表的列设计（SQL/event_extractor_sql.h:14-37）

```cpp
inline constexpr const char* CREATE_EVENTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        file_path TEXT,
        inode INTEGER,
        description TEXT,
        file_size INTEGER,
        file_type TEXT,
        system_context TEXT,
        priority TEXT,         -- 事件优先级: LOW, MEDIUM, HIGH, CRITICAL
        severity TEXT,         -- 事件严重程度: INFO, WARNING, ERROR, CRITICAL
        event_source TEXT,     -- 事件来源: FILE_SYSTEM, WINDOWS_EVENT_LOG, LINUX_SYSLOG, etc.
        event_category TEXT,   -- 事件类别: FILE_OPERATION, SYSTEM_ACTIVITY, etc.
        normalized_type TEXT,  -- 标准化事件类型
        source_id TEXT,        -- 事件来源ID
        llm_summary TEXT,      -- AI生成的事件簇摘要
        llm_description TEXT,  -- AI生成的详细描述
        llm_keywords TEXT,     -- AI提取的关键词（逗号分隔）
        llm_analyzed_at INTEGER, -- 分析时间戳
        llm_model_used TEXT,   -- 使用的AI模型
        llm_is_relevant INTEGER -- 事件簇是否有价值（0/1）
    );
)";
```

逐块解释：列布局分四段——事实段（timestamp/event_type/file_path/inode/description/file_size/file_type/system_context）来自原料库或平台表；标注段（priority 到 source_id 六列）由标准化流水线补；LLM 段（七个 llm_* 列）留给 EventClusterAnalyzer 回写，**建表即带**避免事后迁移；id 自增主键是事件入序（不等于时间序）。`timestamp INTEGER NOT NULL` 用 Unix 秒（继承 raw.db），`event_type` 是原始类型串（WIN_LOG_error 等大小写混杂），`normalized_type` 才是下游分组键——两个字段的分工是"保留原貌 + 提供规范"。注释直接把枚举取值写进 DDL，schema 文件因此自带值域文档。没有对 (timestamp, event_type) 的索引——视图层若做全表 ORDER BY，大库查询会慢，这是"写入优先"设计的代价。

### 4.2 代码走读：createBaseEvent 与创建事件翻译（FileSystemEventExtractor.cpp:100-141）

```cpp
		// Helper to create basic event
		auto createBaseEvent = [&](int64_t ts, const std::string& et, const std::string& desc) {
			TimelineEvent ev;
			ev.timestamp = ts;
			ev.eventType = et;
			ev.filePath = path;
			ev.inode = inode;
			ev.description = desc;
			ev.fileSize = size;
			ev.fileType = type;
			ev.systemContext = "";
			ev.priority = EventPriority::MEDIUM;
			ev.severity = EventSeverity::INFO;
			ev.source = EventSource::FILE_SYSTEM;
			ev.category = EventCategory::FILE_OPERATION;
			ev.normalizedType = normalizeEventType(et);
			ev.sourceId = getSourceId(ev);
			return ev;
		};

		// Create event for file creation (birth time)
		if (crtime > 0) {
			insertEvent(createBaseEvent(crtime, "CREATED", "File created"));

			// Insert into creation_events table
			std::string sql = R"(
                INSERT INTO creation_events (timestamp, file_path, inode, file_size, file_type)
                VALUES (?, ?, ?, ?, ?);
            )";
			// ... prepare/bind/step/finalize 见 :126-137
```

逐块解释：lambda 捕获按引用 `[&]` 复用外层 while 循环的局部变量（path/inode/size/type），五个时间戳规则只需各给一个 `(时间, 类型, 描述)` 三元组就能生成事件——**翻译规则与事件构造解耦**，加新规则（如按 atime 偏移推"最近访问窗口"）不必复制构造代码。默认标注（MEDIUM/INFO/FILE_SYSTEM/FILE_OPERATION）在源头就填好，standardizeEvents 之后多数行不会被改——事实上的"先给保守值、再统一校正"两层标注。`crtime > 0` 的判断把"文件系统不支持创建时间"（crtime=0）与"1970 纪元"区分开：0 是哨兵值不是时间。主表插入走 `insertEvent`（参数化、复用 INSERT_EVENT 常量），**分表插入却是现场拼的裸 SQL + 现场 prepare**——同文件里两种风格并存，分表侧的 5 列绑定不含标注列，这就是"分表是精简物化视图"的代码体现。

### 4.3 代码走读：importWindowsArtifacts 的 ATTACH+INSERT..SELECT（SystemEventExtractor.cpp:9-44）

```cpp
bool EventExtractor::importWindowsArtifacts(const std::string& windowsDbPath) {
    AuditLog::instance().log("SYSTEM", "TIMELINE_MERGE", "Importing Windows artifacts from: " + windowsDbPath);
    std::string attachSql = "ATTACH DATABASE '" + windowsDbPath + "' AS win_db;";
    sqlite3_exec(eventDb_, attachSql.c_str(), nullptr, nullptr, nullptr);

    // Import event logs
    const char* importLogsSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT timestamp, 'WIN_LOG_' || COALESCE(level, 'UNK'), log_source, 0, 'ID:' || event_id || ' ' || message, 0, 'LOG', '', 'LOW', 'INFO', 'WINDOWS_EVENT_LOG', 'SYSTEM_ACTIVITY', '', ''
        FROM win_db.event_logs;
    )";
    sqlite3_exec(eventDb_, importLogsSql, nullptr, nullptr, nullptr);

    // Import browser history
    const char* importBrowserSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, event_source, event_category, normalized_type, source_id)
        SELECT visit_time, 'WEB_HISTORY', url, 0, 'Title: ' || title, 0, 'WEB', '', 'LOW', 'INFO', 'WEB_BROWSER', 'USER_ACTIVITY', '', ''
        FROM win_db.browser_history;
    )";
    sqlite3_exec(eventDb_, importBrowserSql, nullptr, nullptr, nullptr);
    // ... 其余 9 段（下载/登录/服务/计划任务/预取/USB/回收站/Amcache）同构，见 :30-90
```

逐块解释：`ATTACH DATABASE ... AS win_db` 把平台库挂进当前连接，之后 `win_db.<表>` 跨库可查——**数据不出 SQLite 引擎**，C++ 层零行搬运，这是两种 import 实现里快的那种。INSERT..SELECT 的 SELECT 列表同时做三件事：**选列**（visit_time→timestamp）、**造类型**（`'WIN_LOG_' || COALESCE(level,'UNK')` 拼出 WIN_LOG_error 这类前缀类型，NULL 级别兜底成 UNK）、**压描述**（`'ID:' || event_id || ' ' || message` 把多列折进一个 description）。标注列在 SELECT 里直接给常量初值（WEB_LOGIN 给 HIGH/WARNING/SECURITY_EVENT，回收站删除给 HIGH/WARNING——优先级规则在这里就预支了一层），`normalized_type`/`source_id` 留空串交给收尾的 `standardizeEvents()`。每段 exec 的返回值都不检查：表不存在（如 Linux 镜像跑 Windows import）报错被吞，结果是"该类事件缺席"而非任务失败——**这个静默是刻意选择**（跨平台健壮性）也是排障盲点（见第 6 节）。收尾 DETACH + standardize 的搭配保证标注完整。

### 4.4 代码走读：insertEvent 的 14 参数绑定（FileSystemEventExtractor.cpp:247-277）

```cpp
bool EventExtractor::insertEvent(const TimelineEvent& event) {
	using namespace EventExtractorSQL;

	sqlite3_stmt* stmt;
	int rc = sqlite3_prepare_v2(eventDb_, INSERT_EVENT, -1, &stmt, nullptr);

	if (rc != SQLITE_OK) {
		return false;
	}

	sqlite3_bind_int64(stmt, 1, event.timestamp);
	sqlite3_bind_text(stmt, 2, event.eventType.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 3, event.filePath.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_int64(stmt, 4, event.inode);
	sqlite3_bind_text(stmt, 5, event.description.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_int64(stmt, 6, event.fileSize);
	sqlite3_bind_text(stmt, 7, event.fileType.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 8, event.systemContext.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 9, priorityToString(event.priority).c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 10, severityToString(event.severity).c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 11, sourceToString(event.source).c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 12, categoryToString(event.category).c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 13, event.normalizedType.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 14, event.sourceId.c_str(), -1, SQLITE_TRANSIENT);

	rc = sqlite3_step(stmt);
	sqlite3_finalize(stmt);

	return rc == SQLITE_DONE;
}
```

逐块解释：这是**唯一的主表写入入口**——枚举在绑定边界统一转文本（四个 *ToString），保证库里永远是可读字符串；SQL 本体来自 `EventExtractorSQL::INSERT_EVENT` 常量（SQL-as-headers 纪律），拼写与 schema 单点同步。与 AuditLog 不同，这里没有常驻预编译语句，每次调用 prepare/finalize——在"单大事务包裹几十万次调用"的前提下（BEGIN 在 extractFileSystemEvents 开头），性能损失可接受但仍是优化点。注意 `priorityToString(...).c_str()` 这类**临时 string 的 c_str()**：临时对象存活到完整表达式结束（bind 调用完才析构），SQLITE_TRANSIENT 又让 SQLite 立即拷贝——两层保险下这是安全的，但若有人把这段改成先存 `const char*` 再 bind 就会悬垂。返回值精确区分 DONE 与其他（BUSY/约束失败返回 false），调用方（分表旁的主表写入）**没有检查这个返回值**——主表行可能静默缺失，对账以分表为准反向也成立（见第 6 节双写风险）。

## 5. 与其他模块的协作

- **ImageAnalyzer/DatabaseManager**（上游）：files 表是唯一的事件原料；四时间戳语义继承自 TSK 的定义。
- **TaskManagerAnalysis / AnalysisOrchestrator**（调度方）：决定何时执行、传入哪两个库路径；EVENT_EXTRACTION 阶段占总进度权重 10%。
- **平台 Analyzer**（Android/Windows/Linux，间接上游）：它们写出的 windows.db 事件日志表、files.db 的 artifacts 表，字段名被 import SQL 硬编码引用（如 `win_db.prefetch_info`，`SystemEventExtractor.cpp:63-68`）——平台侧改表名必须同步这里的 SQL。
- **EventCorrelationEngine**：`analyzeEventCorrelations()`（`Detail/EventCorrelationExtractor.cpp:31-80`）构建引擎实例跑关联/链/因果并导出 JSON+dot。三者的区别与现状见 EventCorrelationEngine.md。
- **EventClusterAnalyzer / LLM 阶段**（下游）：消费 events 表按时间窗聚类并回写 `llm_summary` 等列（`TaskManagerAnalysis.cpp:398`）。
- 出错时行为：任一步失败返回 false，任务阶段标记失败；import 的单条 SQL 失败被吞（`sqlite3_exec` 返回值未检查），表现为"该类工件缺失"而非任务失败——排障时看 stderr 与审计。
- 表契约：events.db = events 主表（21 列含 7 个 llm_*）+ creation/modification/access/change/deletion_events 五分表（6 列精简）+ system_events + event_correlations + timeline/statistics/hourly_activity 等视图；audit 动作词表含 EVENT_EXTRACTION_START/COMPLETE、TIMELINE_MERGE。

## 6. 注意事项与已知问题

- **主表 + 分表双写没有一致性保护**：两个 INSERT 各自独立，中断后主表与分表计数可能不一致。以主表为准。
- **`analyzeEventCorrelations()` 与 `extractSystemEvents()` 无生产调用方**（全仓库检索仅测试）：HTTP/CLI 流水线都不触发关联分析；`extractSystemEvents` 里那段"扫 raw.db 里名字含 event/log 的表"的通用提取（`SystemEventExtractor.cpp:245-300`）属于实验代码，其 `SELECT *` 按列序取值的方式也很脆弱。
- import 阶段 SQL 失败静默：平台库表结构不匹配时不会报错，只会在结果里少一批事件。调试时用 `sqlite3` 手动跑同款 ATTACH+SELECT。
- 标准化对每行重新 prepare UPDATE 语句（`EventExtractorCore.cpp:176`），几十万事件时可优化为语句复用；当前吞吐瓶颈实际在双写而非此处。
- 事件时间戳均为 Unix 秒（raw.db 继承而来），与 AuditLog 的毫秒不同，做跨库对齐时注意单位。
- ATTACH 的库路径是**字符串拼接**进 SQL（`SystemEventExtractor.cpp:11`）：路径含单引号会破坏语句——当前路径来自 PathManager/调用方，风险可控但非零。
- 主表无 (timestamp, event_type) 索引：时间范围查询走全表排序，前端大时间线分页变慢时可补索引。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_event_timeline_gtest.cpp` 覆盖时间线生成。
- 手工验证：`sqlite3 <events.db> "SELECT event_type, COUNT(*) FROM events GROUP BY 1"` 对比五类数量与文件数的关系；`SELECT * FROM timeline LIMIT 20`（视图）看标注列是否齐全。
- 扩展新事件来源：优先走 import 路线——(1) 让对应 Analyzer 把工件写进平台库或 files.db artifacts 表；(2) 在 `SystemEventExtractor.cpp` 的对应 import 函数里加一段 INSERT..SELECT，字段映射参考现有段落；(3) 在 `identifySource`/`normalizeEventType`（`EventCorrelationExtractor.cpp`）加新类型分支。文件系统侧的新事件类型则改 `FileSystemEventExtractor.cpp` 的翻译规则，并同步 `SQL/event_extractor_sql.h` 的分表。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
