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

## 4. 工作流程走读

以一次 HTTP 任务的 EVENT_EXTRACTION 阶段为例：

1. `extractEvents()` 入口（`EventExtractorCore.cpp:19-44`）：审计记录 → 打开两个库（`:46-67`，对 eventDb 应用 WAL + NORMAL + busy_timeout，注释明确写了"否则每次 commit 都 fsync 卡在 jbd2"）→ `createEventTables()`（`:69-108`，所有 DDL 来自 `SQL/event_extractor_sql.h`）。
2. `extractFileSystemEvents()` 扫 raw.db files 表，单个大事务内逐文件生成 0-5 个事件：先 `insertEvent` 写主表（`FileSystemEventExtractor.cpp:247-276`，14 个绑定参数），再手写 INSERT 进对应类型分表（如 :125-137）——同一数据写两处是本模块最"重"的写放大点。
3. `standardizeEvents()` 扫描 `normalized_type IS NULL` 的行（`EventExtractorCore.cpp:118-122`，天然幂等：重复运行只补未标注行），事务内逐行算标注并 UPDATE。
4. 调用方接着按需 import：`TaskManagerAnalysis.cpp` 在平台分析完成后调 `importWindowsArtifacts(fileDbPath)` 等——注意 HTTP 流水线传的是 **files.db**（统一场景库），所以实际走的是"检查 windows.db 风格表是否存在"的路径；ATTACH 失败会被 sqlite3_exec 静默吞掉，最终 `standardizeEvents()` 再跑一遍补标注。
5. 完成后审计 `EVENT_EXTRACTION_COMPLETE`（`:41`）。

## 5. 与其他模块的协作

- **ImageAnalyzer/DatabaseManager**（上游）：files 表是唯一的事件原料；四时间戳语义继承自 TSK 的定义。
- **TaskManagerAnalysis / AnalysisOrchestrator**（调度方）：决定何时执行、传入哪两个库路径；EVENT_EXTRACTION 阶段占总进度权重 10%。
- **平台 Analyzer**（Android/Windows/Linux，间接上游）：它们写出的 windows.db 事件日志表、files.db 的 artifacts 表，字段名被 import SQL 硬编码引用（如 `win_db.prefetch_info`，`SystemEventExtractor.cpp:63-68`）——平台侧改表名必须同步这里的 SQL。
- **EventCorrelationEngine**：`analyzeEventCorrelations()`（`Detail/EventCorrelationExtractor.cpp:31-80`）构建引擎实例跑关联/链/因果并导出 JSON+dot。三者的区别与现状见 EventCorrelationEngine.md。
- **EventClusterAnalyzer / LLM 阶段**（下游）：消费 events 表按时间窗聚类并回写 `llm_summary` 等列（`TaskManagerAnalysis.cpp:398`）。
- 出错时行为：任一步失败返回 false，任务阶段标记失败；import 的单条 SQL 失败被吞（`sqlite3_exec` 返回值未检查），表现为"该类工件缺失"而非任务失败——排障时看 stderr 与审计。

## 6. 注意事项与已知问题

- **主表 + 分表双写没有一致性保护**：两个 INSERT 各自独立，中断后主表与分表计数可能不一致。以主表为准。
- **`analyzeEventCorrelations()` 与 `extractSystemEvents()` 无生产调用方**（全仓库检索仅测试）：HTTP/CLI 流水线都不触发关联分析；`extractSystemEvents` 里那段"扫 raw.db 里名字含 event/log 的表"的通用提取（`SystemEventExtractor.cpp:245-300`）属于实验代码，其 `SELECT *` 按列序取值的方式也很脆弱。
- import 阶段 SQL 失败静默：平台库表结构不匹配时不会报错，只会在结果里少一批事件。调试时用 `sqlite3` 手动跑同款 ATTACH+SELECT。
- 标准化对每行重新 prepare UPDATE 语句（`EventExtractorCore.cpp:176`），几十万事件时可优化为语句复用；当前吞吐瓶颈实际在双写而非此处。
- 事件时间戳均为 Unix 秒（raw.db 继承而来），与 AuditLog 的毫秒不同，做跨库对齐时注意单位。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_event_timeline_gtest.cpp` 覆盖时间线生成。
- 手工验证：`sqlite3 <events.db> "SELECT event_type, COUNT(*) FROM events GROUP BY 1"` 对比五类数量与文件数的关系；`SELECT * FROM timeline LIMIT 20`（视图）看标注列是否齐全。
- 扩展新事件来源：优先走 import 路线——(1) 让对应 Analyzer 把工件写进平台库或 files.db artifacts 表；(2) 在 `SystemEventExtractor.cpp` 的对应 import 函数里加一段 INSERT..SELECT，字段映射参考现有段落；(3) 在 `identifySource`/`normalizeEventType`（`EventCorrelationExtractor.cpp`）加新类型分支。文件系统侧的新事件类型则改 `FileSystemEventExtractor.cpp` 的翻译规则，并同步 `SQL/event_extractor_sql.h` 的分表。

**最后更新**: 2026-08-23（解释式重写）
