# AuditLog（src/core/AuditLog/）

> **一句话**：进程级单例的审计日志器，把"谁在什么时候对哪个任务做了什么"以 SQLite（WAL）持久化，用写缓冲 + 后台刷盘线程 + 按任务 LRU 读缓存换取吞吐，并自带轮转、保留清理和 JSON/CSV 导出。

## 1. 为什么有这个模块

取证系统的产出会被用于指控与辩护，因此**操作本身也要留痕**：任务何时创建、分析走到哪个阶段、哪个模块失败、解密动作何时发生——这些"关于分析的分析"是可追责性的基础。普通日志（Logger）给开发者看，会被轮转清掉、格式随意；审计需要的是结构化（task_id/action/details/user_id/毫秒时间戳）、可查询（按任务/时间段/动作类型）、可导出（给报告或合规审查）的持久记录。

吞吐是第二个设计约束。流水线里几乎每个阶段转换、每个 analyzer 的关键节点都写审计（全仓库 25+ 处调用，如 `DatabaseManager.cpp:23,49`、`EventExtractorCore.cpp:20`、`FileClassifier.cpp:37`），长任务下写入量可观。如果每条都同步 fsync，审计本身会拖慢分析。模块为此准备了三层机制：预编译 INSERT、批量事务插入、可选的异步刷盘线程——但默认配置选择了**数据安全优先**（`AuditLogDataTypes.h:48-57`：`batch_size=1`、`async_write=false`，注释写明"Disable async write by default for data safety"）。

第三个问题是**进程被杀时的兜底**。Ctrl-C 杀掉服务时，缓冲里的审计不能丢。模块安装了自己的 SIGINT/SIGTERM/SIGHUP 处理器：信号处理器只置一个 `sig_atomic_t` 标志（异步信号安全），由刷盘线程在下次唤醒时执行 flush、恢复默认处理器并重新 raise 信号（`AuditLog.cpp:9-45, 284-320`）——优雅退出与内核默认终止语义的折中。

## 2. 在系统中的位置

- **初始化**：`main.cpp:69-74` 用 `.env` 组装 `AuditLogConfig`（`AUDIT_LOG_DB` 默认相对路径 `forensics_audit.db`、`AUDIT_LOG_CACHE_SIZE` 默认 100、`AUDIT_LOG_WAL` 默认开），首次 `AuditLog::instance(auditConfig)` 触发单例构造（`AuditLog.cpp:48-53`，配置仅第一次生效）。
- **写入方**（约 25 处）：DatabaseManager（库初始化成败）、EventExtractor/FileClassifier/FileExtractor（阶段起止）、FileFilter、ImageAnalyzer 解密动作（`DecryptionModule.cpp:345,443,557,622`）、LinuxFilesAnalyzer 各 parser、SetuidAnalyzer 等。动作风格为 `"SYSTEM"|"ERROR"|"WARNING"|"SUCCESS"` + 大写动作名。
- **读取方**：HTTP 层的审计查询接口——`TaskManager::get_audit_logs`（`TaskManager.cpp:522-524`）直接转发 `getTaskLogs(id, limit, offset)`，对应任务的 `GET /api/tasks/<id>/logs` 类路由。
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

### 3.1 核心数据结构：AuditLogEntry（AuditLogDataTypes.h:15-43）

```cpp
struct AuditLogEntry {
    int64_t id = 0;                                          // Database primary key (auto-increment)
    std::string task_id;                                     // Associated task ID
    std::chrono::system_clock::time_point timestamp;         // Timestamp (human-readable)
    std::string action;                                      // Action type (e.g., "CREATED", "STATUS_CHANGE")
    std::string details;                                     // Detailed information
    std::string user_id;                                     // User identifier (optional)

    int64_t timestampToUnixMs() const { /* duration_cast<milliseconds> ... */ }
    static AuditLogEntry fromUnixMs(int64_t id, const std::string& task_id,
                                    int64_t timestamp_ms, const std::string& action,
                                    const std::string& details, const std::string& user_id);
};
```

- `id`：仅查询路径有意义——写入路径构造 entry 时恒为 0，由 SQLite `AUTOINCREMENT` 赋值；`executeQuery` 读回时填充（`AuditLog_Queries.cpp:46`）。JSON 导出会带出它，可用来检测丢行（id 应连续递增）。
- `timestamp`：进程内用 `system_clock::time_point`（纳秒精度），落库与查询边界统一换算成毫秒 int64。**注意是墙钟**：系统时间被回调时审计序可能与 id 序不一致，排查时以 id 序为准更可靠。
- `action`：非归一化字符串，词表靠调用方自觉（DB_INIT、EVENT_EXTRACTION_START……），`getLogsByAction` 的等值匹配因此对拼写大小写敏感。
- `details`/`user_id`：纯文本，无结构约定；`user_id` 全仓库实际调用几乎都留默认空串——多用户区分能力存在但未启用。

### 3.2 配置结构：AuditLogConfig（AuditLogDataTypes.h:48-57）

```cpp
struct AuditLogConfig {
    std::string db_path = "forensics_audit.db";              // Database file path
    size_t cache_size = 100;                                 // Number of entries in read cache
    size_t batch_size = 1;                                   // Batch write threshold (1 = immediate write for safety)
    int flush_interval_seconds = 3;                          // Auto-flush interval (for async mode only)
    bool async_write = false;                                // Disable async write by default for data safety
    size_t max_db_size_mb = 100;                             // Max database size before rotation
    int retention_days = 30;                                 // Log retention period
    bool enable_wal = true;                                  // Enable SQLite WAL mode
};
```

逐字段含义与 .env 接线（只有前三个能从外部配置，其余是代码默认值）：

| 字段 | 默认值 | 语义 / 约束 | .env 键 |
|---|---|---|---|
| `db_path` | `forensics_audit.db`（相对 CWD） | 库文件路径；`initDatabase` 会自动建父目录（`AuditLog.cpp:89-92`） | `AUDIT_LOG_DB` |
| `cache_size` | 100 | 读缓存**条目数**上限（非任务数）；`getTaskLogs(limit=0)` 一次大任务结果就可能顶满并逐出其他任务 | `AUDIT_LOG_CACHE_SIZE` |
| `batch_size` | 1 | 写缓冲落库阈值；1 = 每条立即 flush（同步语义）。调大可摊薄事务开销但引入崩溃丢失窗口 | 未接线 |
| `flush_interval_seconds` | 3 | 仅 `async_write=true` 时生效，后台线程的 `wait_for` 周期，即最大丢失窗口 | 未接线 |
| `async_write` | false | 开启后台刷盘线程；默认关闭换取崩溃零丢失 | 未接线 |
| `max_db_size_mb` | 100 | `rotate()` 的触发阈值；**当前无调用方**，仅手工触发 | 未接线 |
| `retention_days` | 30 | `cleanup()` 的保留期；同样无自动调用方 | 未接线 |
| `enable_wal` | true | WAL 模式（写不阻塞读）；`synchronous=NORMAL` 无条件设置（`:112`） | `AUDIT_LOG_WAL` |

### 3.3 关键成员变量（AuditLog.h:213-236）

写侧三件套：`write_buffer_`/`write_mutex_`/`drop_warning_emitted_`（`:217-221`）；读侧三件套：`read_cache_`/`current_cache_size_`/`cache_mutex_`（`:225-227`）；DB 侧：`db_` 与预编译 `insert_stmt_`（`:214, 236`）；异步侧：`flush_thread_`/`stop_flush_thread_`（atomic）/`flush_cv_`（`:230-233`）。两个值得注意的点：`insert_stmt_` 全线程共享且 flush 解锁窗口允许并发使用（见第 6 节并发边界）；信号标志 `g_signal_received` 是文件级静态（`AuditLog.cpp:11`），不属于任何实例。

### 3.4 核心接口清单

| 签名（AuditLog.h） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `static AuditLog& instance(const AuditLogConfig& = {})` | 取单例；首次调用安装信号/atexit 处理器 | main.cpp:75；各 analyzer 内 `AuditLog::instance().log(...)` | 不会失败；构造失败只打 stderr，单例仍返回 |
| `void log(task_id, action, details, user_id="")` | 追加一条审计（同步默认立即落库） | 25+ 处 analyzer/parser | 静默重排队或丢弃，无返回值 |
| `void flush()` | 强制清空写缓冲 | atexit 处理器、rotate/export 前置 | 失败走重排队/丢弃分支 |
| `vector<AuditLogEntry> getTaskLogs(task_id, limit=0, offset=0)` | 按任务查（先读缓存） | TaskManager::get_audit_logs（HTTP 路由） | db_ 为 null 返回空 vector |
| `vector<AuditLogEntry> getLogsByTimeRange(start, end, ...)` | 按毫秒时间段查（走 idx_timestamp） | 暂无生产调用方 | 同上 |
| `vector<AuditLogEntry> getLogsByAction(action, ...)` | 按动作等值查（走 idx_action） | 暂无生产调用方 | 同上 |
| `int64_t getLogCount(task_id="")` | 计数（空=全库） | getStatistics 内部 | 失败返回 0（与"真 0 条"不可区分） |
| `nlohmann::json getStatistics()` | 总数/按动作分组/库大小/缓存/待写数 | 暂无生产调用方 | db_ 为 null 返回空 json |
| `void cleanup(retention_days=-1)` | 删除超期日志 + VACUUM + 清缓存 | 暂无自动调用方 | prepare 失败打 stderr 返回 |
| `void rotate()` | 超过 max_db_size_mb 时改名备份并重建 | 暂无自动调用方 | 未超阈值直接 return |
| `void exportToFile(output_path, format="json")` | 导出 JSON/CSV | 暂无生产调用方（合规导出预留） | 未知 format 静默不写文件但仍打成功提示 |

## 4. 工作流程走读

一次典型写入（EventExtractor 阶段开始）：

1. `AuditLog::instance().log("SYSTEM", "EVENT_EXTRACTION_START", "Starting...")`（`EventExtractorCore.cpp:20`）→ 构造 entry、取当前时间点（`AuditLog.cpp:164-174`）。
2. `addToWriteBuffer` 加写锁入队；默认配置（`async_write=false`）立即触发 `flushWriteBuffer`（`:177-186`）。
3. swap 出缓冲 → 解锁 → `insertBatch`：`BEGIN TRANSACTION` → 逐条 `sqlite3_reset/clear_bindings/bind/step` 预编译语句 → `COMMIT`（`:236-276`）。WAL + `synchronous=NORMAL`（`:102-112`）保证这一步只写 WAL 不 fsync 主库。两个初始化细节值得知道：WAL/索引失败只警告不终止（`:106-108, 145-147`，代价是并发退化为默认 journal、查询退化全表扫），而 prepare INSERT 失败则整体初始化失败（`:155-158`）；表结构里 `created_at`（SQL 默认值生成的落库毫秒）与 `timestamp`（业务毫秒）分离，排查异步延迟可用 `created_at - timestamp` 量化。
4. 失败（如库被锁超时）时条目回到缓冲，等下次触发重试；DB 句柄为 null 则走丢弃分支（`:204-219`）。

查询路径（按任务）：`getTaskLogs` 先查缓存（`AuditLog_Queries.cpp:70-81`），未命中执行 `ORDER BY timestamp DESC` 查询（`:84-88`），完整结果入缓存并按需淘汰（`:91-102`）。

维护路径：`cleanup(days)`（`:219-256`）按保留期 DELETE + `VACUUM` 回收空间并清空缓存；`rotate()`（`:259-298`）在库超过 `max_db_size_mb`（默认 100）时改名备份（后缀 `.YYYYmmdd_HHMMSS.backup`）并重建空库；`exportToFile` 支持 JSON（借 nlohmann 的 adl_serializer，`AuditLogDataTypes.h:60-76`）与 CSV（`:301-332`）。

### 4.1 代码走读：flushWriteBuffer 的"解锁落库"与一次性丢弃（AuditLog.cpp:189-221）

```cpp
void AuditLog::flushWriteBuffer() {
    // Note: Caller must hold write_mutex_
    if (write_buffer_.empty()) {
        return;
    }

    // Move buffer to local variable for processing
    std::vector<AuditLogEntry> entries_to_insert;
    entries_to_insert.swap(write_buffer_);

    // Release lock during database operation
    write_mutex_.unlock();
    bool success = insertBatch(entries_to_insert);
    write_mutex_.lock();

    if (!success) {
        // Only re-queue when the database is actually available (a transient
        // error worth retrying). If it is not initialized (db_/insert_stmt_
        // null), re-queuing would loop forever — the buffer grows unbounded and
        // spams stderr, which stalls shutdown. Drop the batch and warn once.
        if (db_ && insert_stmt_) {
            std::cerr << "Failed to flush write buffer, re-queuing entries" << std::endl;
            write_buffer_.insert(write_buffer_.begin(),
                                entries_to_insert.begin(), entries_to_insert.end());
        } else if (!drop_warning_emitted_) {
            std::cerr << "AuditLog not initialized; dropping "
                      << entries_to_insert.size() << " buffered entr"
                      << (entries_to_insert.size() == 1 ? "y" : "ies")
                      << " (further drops suppressed)" << std::endl;
            drop_warning_emitted_ = true;
        }
    }
}
```

逐块解释：这段的核心是**约定式锁转移**——注释声明"调用者必须持锁"（`addToWriteBuffer` 的 lock_guard 与 `flush()` 均满足），swap 后手动 unlock/lock 打开一个磁盘 I/O 窗口：期间其他线程可继续 log() 入队（进新的 `write_buffer_`），不会在写锁上排队等 sqlite。代价是失败重排队用的是 `insert(begin(), ...)`——新条目已经排在前面，重试批次**插到队首**，保序正确。丢弃分支的条件判断把"暂时性失败"（库忙，值得重试）与"永久性失败"（句柄为 null，重试必死循环）分开，后者直接丢批 + 单次警告；英文注释把"缓冲无界增长、刷屏 stderr、卡死关机"三个后果写得很清楚，这是审计不阻断主流程的最后一道闸门。

### 4.2 代码走读：insertBatch 单事务批量绑定（AuditLog.cpp:235-276）

```cpp
    // Begin transaction
    char* errMsg = nullptr;
    int rc = sqlite3_exec(db_, "BEGIN TRANSACTION;", nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        // ... 打印错误并 return false（:238-242）
    }

    bool success = true;
    for (const auto& entry : entries) {
        sqlite3_reset(insert_stmt_);
        sqlite3_clear_bindings(insert_stmt_);

        // Bind parameters
        sqlite3_bind_text(insert_stmt_, 1, entry.task_id.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_int64(insert_stmt_, 2, entry.timestampToUnixMs());
        sqlite3_bind_text(insert_stmt_, 3, entry.action.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(insert_stmt_, 4, entry.details.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(insert_stmt_, 5, entry.user_id.c_str(), -1, SQLITE_TRANSIENT);

        rc = sqlite3_step(insert_stmt_);
        if (rc != SQLITE_DONE) {
            // ... 打印 sqlite3_errmsg、success = false、break（:257-261）
        }
    }

    // Commit or rollback
    if (success) {
        rc = sqlite3_exec(db_, "COMMIT;", nullptr, nullptr, &errMsg);
        // ...
    } else {
        sqlite3_exec(db_, "ROLLBACK;", nullptr, nullptr, nullptr);
    }
```

逐块解释：整个批次是一个事务——要么全部可见、要么全部回滚，避免了"半批落库"这种最难排查的审计状态。预编译语句被复用（prepare 只在 initDatabase 做一次，`AuditLog.cpp:149-158`），循环里 reset/clear_bindings 是 SQLite 复用的标准三步；`SQLITE_TRANSIENT` 让 SQLite 拷贝字符串（绑定后 entry 生命周期不与语句绑定），牺牲一次堆拷贝换安全。任何一条 step 失败即 break + ROLLBACK，**整批回到缓冲重试**——若失败源于某条内容（如 details 含非法编码），整批会反复失败形成毒丸，这是批量重试的固有弱点（默认 batch_size=1 时影响最小）。COMMIT 失败（如磁盘满）同样置 false 走重排队。

### 4.3 代码走读：flushThreadFunc 的信号安全关停（AuditLog.cpp:284-320）

```cpp
void AuditLog::flushThreadFunc() {
    while (!stop_flush_thread_) {
        std::unique_lock<std::mutex> lock(flush_mtx_);
        flush_cv_.wait_for(lock, std::chrono::seconds(config_.flush_interval_seconds),
                          [this]() { return stop_flush_thread_.load() || g_signal_received != 0; });

        // Check for signal - perform graceful shutdown
        if (g_signal_received != 0) {
            int sig = g_signal_received;
            g_signal_received = 0;  // Reset for potential re-use

            // Flush all pending writes
            {
                std::lock_guard<std::mutex> write_lock(write_mutex_);
                flushWriteBuffer();
            }

            // Stop this thread
            stop_flush_thread_ = true;

            // Restore default handler and re-raise signal
            std::signal(sig, SIG_DFL);
            std::raise(sig);
            break;
        }
        // ... 周期性 flushWriteBuffer 见 :310-318
    }
}
```

逐块解释：这是"信号处理器只置标志、善后在线程里做"的标准范式落地。`wait_for` 的谓词同时监视停止标志与信号标志，因此最坏等待一个 flush 周期（默认 3 秒）就能响应 Ctrl-C。善后序列是关键：先抢 `write_mutex_` 清空缓冲（保证 SIGKILL 之前的最后一批落库），再 `signal(sig, SIG_DFL)` + `raise(sig)` **以默认语义重新自杀**——进程的退出码、`$?`、shell 的信号报告都与未安装处理器时一致，外层 supervisor（systemd/docker）看到的仍是"被信号杀死"而非"exit 0"。注意此路径只在 `async_write=true` 时存在：**默认同步配置下信号处理器置完标志后没有任何线程消费它**，进程直接按默认语义终止（缓冲为空所以无损），安装处理器只是给异步模式预留。

## 5. 与其他模块的协作

- **main.cpp**：唯一初始化点；想改审计行为（异步、批量、轮转阈值）只能改 `.env` 三个键或代码默认值，运行期不可调。影响本模块的 .env 变量：`AUDIT_LOG_DB`（默认 `forensics_audit.db`）、`AUDIT_LOG_CACHE_SIZE`（默认 100）、`AUDIT_LOG_WAL`（默认 true）——`batch_size`/`async_write`/`flush_interval_seconds`/`max_db_size_mb`/`retention_days` 五项**均未接 .env**，只能改 `AuditLogDataTypes.h` 默认值。
- **DatabaseManager/EventExtractor/FileClassifier/FileExtractor/FileFilter**：阶段级审计写入方，动作名构成事实上的审计词表（DB_INIT、EVENT_EXTRACTION_START、CLASSIFICATION_COMPLETE、EXTRACTOR_INIT、FILE_FILTER……）。
- **TaskManager（HTTP 形态）**：`add_audit_log` 是带闸门的包装——任务不存在于 `tasks_` 映射时直接不写（`TaskManager.cpp:511-516`），防孤儿审计；`get_audit_logs` 原样转发 `getTaskLogs`。`getStatistics`/`exportToFile`/`cleanup`/`rotate` 在 HTTP 层与 CLI 层**都没有调用方**，属于建好未接线的运维接口。
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
- **并发边界**：预编译 `insert_stmt_` 被所有线程共享且 `flushWriteBuffer` 解锁窗口允许并发 flush——两个线程同时对同一 stmt 做 reset/bind/step 属数据竞争，实践中同步模式（每条立即 flush 且整段持锁路径很短）降低了触发概率，但把 `batch_size` 调大或开异步后风险上升；彻底修复应给 `insertBatch` 单独加语句锁或每线程一个 stmt。`rotate()` 关闭并重建 `db_` 期间未与其他读写互斥，只能在单线程维护脚本里调用。
- `getStatistics` 读 `current_cache_size_` 不加 `cache_mutex_`（`AuditLog_Queries.cpp:208`），统计值是近似值。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_audit_log_gtest.cpp`（`tests/CMakeLists.txt:526-533`，测试名 `AuditLogGTests`）；模块目录内另有 `src/core/AuditLog/test_audit_log.cpp`。
- 手工验证：跑一次分析任务后 `sqlite3 forensics_audit.db "SELECT action, COUNT(*) FROM audit_logs GROUP BY 1 ORDER BY 2 DESC"`，应看到 DB_INIT、EVENT_EXTRACTION_* 等动作；`kill -INT` 服务进程后再查，最后一批（同步模式下无丢失）应已落库。再验证毫秒时间戳：`SELECT timestamp, created_at, created_at-timestamp AS lag_ms FROM audit_logs ORDER BY id DESC LIMIT 5`，同步模式 lag 应接近 0。
- 扩展点：(1) 接线 PathManager 审计路径（改 `main.cpp:70` 默认值）；(2) 缓存失效——写入路径成功后对同 task_id 的缓存项打脏标记；(3) 定期维护——在 HTTP 服务里加定时器调 `rotate()+cleanup()`；(4) CSV 转义——把 `exportToFile` 的拼接换成逐字段 escape（可参考 TOONExporter::escapeValue 的思路，`TOONExporter.cpp:21-65`）；(5) 若要开异步/批量，先给 `insertBatch` 补语句级互斥（见第 6 节并发边界）。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
