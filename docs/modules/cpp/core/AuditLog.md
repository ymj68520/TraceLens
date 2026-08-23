# AuditLog（src/core/AuditLog/）

> **一句话**：进程级单例的审计日志器，把"谁在什么时候对哪个任务做了什么"以 SQLite（WAL）持久化，用写缓冲 + 后台刷盘线程 + 按任务 LRU 读缓存换取吞吐，并自带轮转、保留清理和 JSON/CSV 导出。

## 1. 为什么有这个模块

取证系统的产出会被用于指控与辩护，因此**操作本身也要留痕**：任务何时创建、分析走到哪个阶段、哪个模块失败、解密动作何时发生——这些"关于分析的分析"是可追责性的基础。普通日志（Logger）给开发者看，会被轮转清掉、格式随意；审计需要的是结构化（task_id/action/details/user_id/毫秒时间戳）、可查询（按任务/时间段/动作类型）、可导出（给报告或合规审查）的持久记录。

吞吐是第二个设计约束。流水线里几乎每个阶段转换、每个 analyzer 的关键节点都写审计（全仓库 25+ 处调用，如 `DatabaseManager.cpp:23,49`、`EventExtractorCore.cpp:20`、`FileClassifier.cpp:37`），长任务下写入量可观。如果每条都同步 fsync，审计本身会拖慢分析。模块为此准备了三层机制：预编译 INSERT、批量事务插入、可选的异步刷盘线程——但默认配置选择了**数据安全优先**（`AuditLogDataTypes.h:48-57`：`batch_size=1`、`async_write=false`，注释写明"Disable async write by default for data safety"）。

第三个问题是**进程被杀时的兜底**。Ctrl-C 杀掉服务时，缓冲里的审计不能丢。模块安装了自己的 SIGINT/SIGTERM/SIGHUP 处理器：信号处理器只置一个 `sig_atomic_t` 标志（异步信号安全），由刷盘线程在下次唤醒时执行 flush、恢复默认处理器并重新 raise 信号（`AuditLog.cpp:9-45, 284-320`）——优雅退出与内核默认终止语义的折中。

## 2. 在系统中的位置

- **初始化**：`main.cpp:69-74` 用 `.env` 组装 `AuditLogConfig`（`AUDIT_LOG_DB` 默认相对路径 `forensics_audit.db`、`AUDIT_LOG_CACHE_SIZE` 默认 100、`AUDIT_LOG_WAL` 默认开），首次 `AuditLog::instance(auditConfig)` 触发单例构造（`AuditLog.cpp:48-53`，配置仅第一次生效）。
- **写入方**（约 25 处）：DatabaseManager（库初始化成败）、EventExtractor/FileClassifier/FileExtractor（阶段起止）、FileFilter、ImageAnalyzer 解密动作（`DecryptionModule.cpp:345,443,557,622`）、LinuxFilesAnalyzer 各 parser、SetuidAnalyzer 等。动作风格为 `"SYSTEM"|"ERROR"|"WARNING"|"SUCCESS"` + 大写动作名。
- **读取方**：HTTP 层的审计查询/统计/导出接口。
- 存储：单表 `audit_logs`（task_id/timestamp/action/details/user_id，`AuditLog.cpp:115-125`），三个索引覆盖三种查询维度（`:136-140`）。

```
analyzer/parser ──log(task,action,details)──> 写缓冲(写锁) ──批量事务──> audit_logs(SQLite WAL)
                                                  ▲ 后台线程每 flush_interval 秒刷一次(可选)
前端/路由 <──getTaskLogs/ByTimeRange/ByAction──  LRU 读缓存(task_id → entries)
```

## 3. 核心概念与设计

**写路径三级流水**。`log()` 构造 entry 后进 `addToWriteBuffer`（`AuditLog.cpp:164-186`）：同步模式（默认）或缓冲满（`batch_size`）时立即 `flushWriteBuffer`。`flushWriteBuffer`（`:189-221`）有一个值得学习的锁手法——调用者持有 `write_mutex_`，它把缓冲 swap 到局部变量后**手动解锁、执行 DB 操作、再加锁**（`:199-202`），让并发写 log() 不必等待磁盘；失败时条目重新插回队首。落库由 `insertBatch` 完成（`:230-277`）：单事务内循环绑定预编译语句、失败整体回滚。

**"数据库未初始化就丢弃并只警告一次"** 是刻意的行为（`:204-219`）：db 打开失败时如果无限重排队，缓冲会无界增长并在关机时卡死 flush，因此选择丢弃批次、`drop_warning_emitted_` 标志保证 stderr 只吵一次。审计"尽力而为"优先于进程可用性。

**读缓存以任务为粒度**：`unordered_map<task_id, list<entry>>`（`AuditLog.h:225`），只缓存"完整结果"（`getTaskLogs` 仅在 `limit==0` 时写入缓存，`AuditLog_Queries.cpp:91-102`），否则分页请求会毒化缓存。淘汰按"整任务逐出"（`:97-101`），粒度粗但实现简单——`current_cache_size_` 按条目数对齐 `config_.cache_size`（默认 100 条）。

**时间戳统一毫秒**（`AuditLogDataTypes.h:24-42` 的 toUnixMs/fromUnixMs），与 events.db 的秒级时间戳不同源，跨库对齐时须换算。

**信号安全模板**：处理器只做 `g_signal_received = signum`（`AuditLog.cpp:14-16`），所有非异步安全的操作（加锁、SQL）都在刷盘线程的常规上下文里做（`:291-307`）。`atexit` 处理器兜底正常退出路径的 flush（`:41-45`）。

## 4. 工作流程走读

一次典型写入（EventExtractor 阶段开始）：

1. `AuditLog::instance().log("SYSTEM", "EVENT_EXTRACTION_START", "Starting...")`（`EventExtractorCore.cpp:20`）→ 构造 entry、取当前时间点（`AuditLog.cpp:164-174`）。
2. `addToWriteBuffer` 加写锁入队；默认配置（`async_write=false`）立即触发 `flushWriteBuffer`（`:177-186`）。
3. swap 出缓冲 → 解锁 → `insertBatch`：`BEGIN TRANSACTION` → 逐条 `sqlite3_reset/clear_bindings/bind/step` 预编译语句 → `COMMIT`（`:236-276`）。WAL + `synchronous=NORMAL`（`:102-112`）保证这一步只写 WAL 不 fsync 主库。
4. 失败（如库被锁超时）时条目回到缓冲，等下次触发重试；DB 句柄为 null 则走丢弃分支（`:204-219`）。

查询路径（按任务）：`getTaskLogs` 先查缓存（`AuditLog_Queries.cpp:70-81`），未命中执行 `ORDER BY timestamp DESC` 查询（`:84-88`），完整结果入缓存并按需淘汰（`:91-102`）。

维护路径：`cleanup(days)`（`:219-256`）按保留期 DELETE + `VACUUM` 回收空间并清空缓存；`rotate()`（`:259-298`）在库超过 `max_db_size_mb`（默认 100）时改名备份（后缀 `.YYYYmmdd_HHMMSS.backup`）并重建空库；`exportToFile` 支持 JSON（借 nlohmann 的 adl_serializer，`AuditLogDataTypes.h:60-76`）与 CSV（`:301-332`）。

## 5. 与其他模块的协作

- **main.cpp**：唯一初始化点；想改审计行为（异步、批量、轮转阈值）只能改 `.env` 三个键或代码默认值，运行期不可调。
- **DatabaseManager/EventExtractor/FileClassifier/FileExtractor/FileFilter**：阶段级审计写入方，动作名构成事实上的审计词表（DB_INIT、EVENT_EXTRACTION_START、CLASSIFICATION_COMPLETE、EXTRACTOR_INIT、FILE_FILTER……）。
- **ImageAnalyzer/DecryptionModule**：记录解密动作（LUKS/BitLocker/VeraCrypt，`DecryptionModule.cpp:345` 等）——取证上最敏感的操作必须留痕。
- **Logger**：分工见 Logger.md 第 5 节——Logger 控制台、AuditLog 证据。
- 出错时行为：初始化失败不抛异常（`AuditLog.cpp:59-61` 打 stderr），后续写入走丢弃分支；查询在 `db_` 为 null 时返回空集合（`AuditLog_Queries.cpp:19-21`）——审计永远不是阻断项。

## 6. 注意事项与已知问题

- **审计库落在 CWD 而非 data/audit/**：main.cpp 的默认值是相对路径 `forensics_audit.db`（`main.cpp:70`），PathManager 的 `getAuditDbPath()`（`data/audit/forensics_audit.db`）没有接线——这就是仓库根目录出现 `forensics_audit.db` 的原因。想收敛位置应在 `.env` 设 `AUDIT_LOG_DB` 为绝对路径，或按 PathManager.md 第 7 节接线。
- **读缓存不做失效**：任务有新日志写入后，缓存里仍是旧快照，直到淘汰或 cleanup。对"实时审计视图"需求，当前实现会返回陈旧数据。
- **CSV 导出未转义**：details 里若含引号/逗号会破坏格式（`AuditLog_Queries.cpp:317-328` 只有 details 一对裸引号）。导出合规材料请用 JSON。
- **轮转是手动触发**：没有任何调用方周期性调 `rotate()`/`cleanup()`，超阈值后库会继续增长，需要运维脚本或将来在 HTTP 层挂定时任务。
- 异步模式（`async_write=true`）牺牲最多 `flush_interval_seconds`（默认 3 秒）的审计记录，崩溃窗口内的条目会丢——默认关闭即为此。
- 单例构造线程不安全（C++11 magic static 保证并发首调安全，但 `instance(config)` 的 config 只在最早那次生效，晚到的配置被忽略）。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_audit_log_gtest.cpp`（`tests/CMakeLists.txt:526-533`，测试名 `AuditLogGTests`）；模块目录内另有 `src/core/AuditLog/test_audit_log.cpp`。
- 手工验证：跑一次分析任务后 `sqlite3 forensics_audit.db "SELECT action, COUNT(*) FROM audit_logs GROUP BY 1 ORDER BY 2 DESC"`，应看到 DB_INIT、EVENT_EXTRACTION_* 等动作；`kill -INT` 服务进程后再查，最后一批（同步模式下无丢失）应已落库。
- 扩展点：(1) 接线 PathManager 审计路径（改 `main.cpp:70` 默认值）；(2) 缓存失效——写入路径成功后对同 task_id 的缓存项打脏标记；(3) 定期维护——在 HTTP 服务里加定时器调 `rotate()+cleanup()`；(4) CSV 转义——把 `exportToFile` 的拼接换成逐字段 escape（可参考 TOONExporter::escapeValue 的思路，`TOONExporter.cpp:21-65`）。

**最后更新**: 2026-08-23（解释式重写）
