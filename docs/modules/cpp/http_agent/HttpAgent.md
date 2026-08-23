# HttpAgent / tracelens_agent（src/http_agent/ 独立子项目）

> **一句话**：部署在被取证机器上的轮询代理——用 30 天客户端 JWT 反复轮询 C/S 服务端（:8091）的 `/api/commands/poll` 领命令，本地 fork `forensic_analyzer` 跑 `analyze_disk`（强制 `--no-ai`），把产出的 `*.db` 工件与本地镜像清单上传回去，用 SQLite `in_flight_commands` 表保证崩溃后孤儿命令可恢复。

## 1. 为什么有这个模块

TraceLens 的 C/S 形态里，取证数据不允许离开客户机（隐私与带宽双重原因），但调度要在服务端。于是控制面反转：**客户端长轮询**领任务、本地执行、只回传元数据与派生库。src/http_agent 就是这个客户端，构建为独立 CMake 目标 `tracelens_agent`——刻意不进根构建：它只需要 cpp-httplib/OpenSSL/SQLite3，不带 hivex/evtx/xapian 等重型取证依赖（CMakeLists.txt:1-10 注释；接入根 add_subdirectory 被列为 forward work，因为根配置硬性要求全部取证库）。

## 2. 在系统中的位置

```
服务端（python_service/server，端口 8091，config.py:34-39）
  注册令牌 → 签发 client JWT（auth_service）
GET  /api/commands/poll                  ← 认领命令（服务端先标记 claimed）
POST /api/commands/{id}/status           ← in_progress / completed / failed
POST /api/tasks/{task_id}/results        ← 上传 ResultArtifact（写 analysis_results）
POST /api/clients/{cid}/index-images     ← 上传本地镜像清单
      ▲ HTTP(S) + Bearer JWT（TLS 1.3 下限）
      │
tracelens_agent（本模块，客户机常驻）
  Poller → HttpAgentService 主循环 → AnalyzeDiskExecutor(fork forensic_analyzer --no-ai)
                                     → ResultUploader / StatusReporter / IndexUploader
  SqliteCommandStore(tracelens_state.db): in_flight_commands 去重/恢复/outbox
```

与单体版的关系：单体 `forensic_analyzer`（HTTP 服务模式）服务于"分析师把镜像拷进来"的集中式流程；agent 服务于"机器在现场、只回传结论"的分布式流程。两者共用同一个 analyzer 二进制。

**端点 ↔ 客户端组件 ↔ 服务端落点对应表**（服务端路由见 `python_service/server/api/commands.py`，其头注释还列出用户侧的 `POST /api/commands`、`GET /api/commands/{id}`、`GET /api/commands/client/{cid}`、`POST /api/commands/expire`——给人用，agent 不调）：

| 端点 | 客户端组件 | 服务端动作/落表 |
|---|---|---|
| `GET /api/commands/poll` | Poller（poller.cpp:9） | `CommandQueueService.get_commands_for_client`：盖 `last_poll` 戳并把命令**标记 claimed/assigned**（写 command_queue 状态） |
| `POST /api/commands/{id}/status` | StatusReporter（status_reporter.cpp:9-15） | 校验 TaskStatusUpdate schema（缺 command_id 直接 422）；终态幂等转换，映射到 task 生命周期（Task 15b） |
| `POST /api/tasks/{task_id}/results` | ResultUploader（result_uploader.cpp:19-20） | `ResultUploadRequest {artifacts: [...]}` → 写 **analysis_results** 表 |
| `POST /api/clients/{cid}/index-images` | IndexUploader（index_uploader.cpp:34-35） | `images: List[DiskImageCreate]` → 写 **disk_images** 表 |

## 3. 核心概念与设计

### 3.1 数据模型（src/http_agent/models/）

命令与状态模型是全部线协议的核心（`models/command.h:13-44`）：

```cpp
// models/command.h:13-44（节选）
struct Command {
    std::string id;            // server UUID (path-authoritative for /status)
    std::string command_type;  // analyze_disk | health_check | extract_file | ...
    nlohmann::json parameters; // analyze_disk 带 image_path/analysis_type + task_id 软链接
    std::string priority = "normal";  // low|normal|high|critical

    bool has_task_id(std::string& out) const {
        // The task_id soft link stamped by create_analysis_task (Task 12).
        if (parameters.is_object() && parameters.contains("task_id")) {
            const auto& v = parameters["task_id"];
            if (v.is_string()) { out = v.get<std::string>(); return true; }
        }
        return false;
    }
};
// from_json：对必填字段（id/command_type）严格——j.at(...) 缺失即抛异常，
// poller 据此跳过该条；对可选字段（parameters/priority）宽松取默认。
```

`task_id` 是嵌在 parameters 里的**软链接**：上传结果要用它拼 `/api/tasks/{task_id}/results`，没有它的命令执行后不上传。`from_json` 的严格/宽松分界正是 poller "单条坏命令跳过" 的实现基础。状态侧（`models/task_status.h`）：`CommandStatus` 枚举有五个值，但**客户端只会发送 in_progress / completed / failed**（`command_status_string` 给出 wire 字符串）；`StatusUpdate` 序列化为 `{status, progress?, message?}`，`command_id` 由 StatusReporter 补进 body（path id 负责路由，body 字段负责 schema 校验）。凭据（`models/credential.h:13-16`）：`struct ClientCredential { std::string token; std::string host; }`——token 是 agent 持有的**唯一**秘密（30 天 JWT，注册时一次性签发）。工件（`result_artifact.h:23-30`）：`ResultArtifact{result_type, file_path, file_size?, storage_location, result_metadata}` 是**纯元数据**——没有内容字段，镜像字节永不离开客户机；`file_path` 指向分析产出的 .db，绝不是原始镜像（头注释 SECURITY INVARIANT 原话）。

### 3.2 组件一览（全部在 tracelens 命名空间下）

| 组件 | 职责 |
|---|---|
| http_client | cpp-httplib 封装；加 Bearer 头、超时 10/300/60s、**禁止跟随重定向**（防 token 随 3xx 泄漏，http_client.cpp:29-38）；无 OpenSSL 直接 `#error`（:14-16） |
| jwt_client | 30 天 JWT 装载；**token 文件必须 0600**（group/other 任何位都硬错，jwt_client.cpp:68-74）；client_id 从 payload 解出（不做签名校验，服务端会再验，jwt_client.h:18-21） |
| client_config | key=value 配置文件或 TRACELENS_* 环境变量；validate 强制 https（localhost 豁免）、token/analyzer 必填、poll 5-30s |
| poller | GET poll → 解析 commands 数组；**单条坏命令跳过不弃批**（poller.cpp:37-42） |
| command_executor | 命令 → analyzer argv；非 analyze_disk 一律"确认并成功"（见 §6） |
| process_runner | fork/execvp + 管道捕获（>8MiB 输出的防死锁有测试钉住；argv 直传 execvp、无 shell，注入免疫） |
| command_store | SQLite `in_flight_commands(command_id PK, command_type, parameters JSON, priority, started_epoch)`（command_store.cpp:71-82）；INSERT OR REPLACE 落盘即 fsync |
| http_agent_service | 主循环与崩溃恢复（§4） |
| image_indexer / index_uploader | 扫描 image_dirs 报告本机镜像（DD/E01/目录三种格式识别，image_indexer.cpp:52-70）；md5 刻意不上传 |
| result_uploader / status_reporter | 结果与状态回传；status body 必须带 command_id（服务端 schema 校验，422 陷阱，status_reporter.cpp:10-16） |

http_client 的安全配置值得整段看（`http_client.cpp:27-43`）：

```cpp
// http_client.cpp:27-43（节选）
Impl(const std::string& base_url, const std::string& bearer) : cli(base_url) {
    cli.set_connection_timeout(10);  // seconds
    cli.set_read_timeout(300);       // generous: result uploads (Task 17) are large
    cli.set_write_timeout(60);
    // Do NOT auto-follow redirects: cpp-httplib re-sends default headers
    // (including Authorization: Bearer ...) across a redirect and does not
    // strip the token on a cross-host hop. The token is the agent's only
    // secret; the poll/status/result endpoints return 2xx, never 3xx, so a
    // redirect would be anomalous and should surface as an error, not leak
    // the credential.
    cli.set_follow_location(false);
    cli.set_default_headers({{"Authorization", "Bearer " + bearer},
                             {"Accept", "application/json"}});
}
```

三个超时三个量级（10s 连接 / 300s 读 / 60s 写）反映流量形态：命令 JSON 很小，结果上传可能很大；禁重定向把"异常 3xx"显式化为错误而非静默泄 token。

### 3.3 主循环的五段式命令处理

每条命令严格按序：**record_started（先落盘）→ 报 in_progress → execute → 上传工件 → 报终态 → clear**。顺序本身就是容错设计：崩溃发生在任何一点，重启后 `recover()` 都能从 in_flight_commands 里找到孤儿。核心段（`http_agent_service.cpp:129-166` 节选）：

```cpp
// http_agent_service.cpp:129-166（节选）
// Persist the in-flight marker BEFORE doing anything else, so a crash
// at any later point (even before the in_progress report lands) is
// recoverable. Best-effort: a store failure is logged, not fatal.
if (!store_.record_started(cmd, se))
    logger_.warn("could not persist in-flight record for " + cmd.id + ": " + se);

// Announce we have started. Best-effort: a failed in_progress report
// is logged but does not stop us executing locally.
StatusUpdate u;
u.status = CommandStatus::InProgress;
if (!reporter_.report(cmd.id, u, e))
    logger_.warn("could not report in_progress for " + cmd.id + ": " + e);

auto result = executor_.execute(cmd);

// An upload failure makes the task's results undeliverable -> report FAILED so
// it is retriable and the operator is alerted (the local artifacts
// remain on disk for manual recovery).
if (result.success && !result.task_id.empty() && !result.artifacts.empty()) {
    if (!uploader_.upload(result.task_id, result.artifacts, ue)) {
        result.success = false;                      // ← 上传失败改判 FAILED
        result.message = "analysis completed but result upload failed: " + ue;
    }
}
// ... 报终态（Completed/Failed）→ store_.clear(cmd.id) ...
```

每一段都是 best-effort 分级：store 失败→告警继续；in_progress 上报失败→告警但照常本地执行（本地结果的价值高于状态汇报）；只有上传失败会**改判终态**——结果不可交付就该报警并让服务端可重试。

### 3.4 崩溃恢复：报 FAILED 而不重跑

`recover`（http_agent_service.cpp:37-79）核心段：

```cpp
// http_agent_service.cpp:44-73（节选）
auto orphans = store_.recover_orphans(err);
if (!err.empty()) {
    logger_.warn("recover: could not read local in-flight store: " + err);
    return;  // unreadable store: don't guess; let normal polling proceed
}
for (const auto& cmd : orphans) {
    StatusUpdate u;
    u.status = CommandStatus::Failed;
    u.message = "agent restarted; command interrupted — local status uncertain";
    std::string e;
    if (!reporter_.report(cmd.id, u, e)) {
        // Do NOT clear: the failure signal never reached the server. Leaving
        // the row lets the next restart retry the report (D3 — never lose a
        // failure signal by deleting before it is communicated).
        continue;
    }
    std::string ce;
    if (!store_.clear(cmd.id, ce)) {
        // Report landed but the local clear failed: the row will be
        // re-reported next restart (harmless — terminal guard). Log only.
    }
}
```

孤儿命令一律向服务端报 FAILED（"agent restarted; command interrupted"）后清行，**不重新执行**——崩溃留下的磁盘状态完整性未知，重跑不可靠（`:40-43` 注释）。若 FAILED 上报失败则**不清行**（D3：never lose a failure signal），留给下次重启重试；终态转换在服务端幂等，重复上报无害。存储读不出来时**直接放弃恢复**继续轮询——宁可漏报也不基于猜测行动。

### 3.5 command_store：in_flight 表的去重与持久化

表结构与写入（`command_store.cpp:71-78, 102-123` 节选）：

```cpp
const char* kSchema =
    "CREATE TABLE IF NOT EXISTS in_flight_commands ("
    "  command_id   TEXT PRIMARY KEY,"
    "  command_type TEXT NOT NULL,"
    "  parameters   TEXT NOT NULL,"       // JSON blob
    "  priority     TEXT NOT NULL DEFAULT 'normal',"
    "  started_epoch INTEGER NOT NULL"    // UTC seconds, diagnostics only
    ")";

const char* kSql =
    "INSERT OR REPLACE INTO in_flight_commands "
    "(command_id, command_type, parameters, priority, started_epoch) "
    "VALUES (?1, ?2, ?3, ?4, ?5)";
// (INSERT OR REPLACE is atomic + autocommitted -> fsynced at commit with the
//  default synchronous=FULL, so this row survives a crash.)
```

`INSERT OR REPLACE` + PRIMARY KEY 就是**去重机制**：服务端重启后重发同一 command_id，本地只是覆盖旧行，不会误报双孤儿；synchronous=FULL 下提交即 fsync，record_started 扛得住 SIGKILL/断电。`recover_orphans`（`:145-191`）读回时把行重组成 wire 形状再过一遍 `from_json`——解析协议只有一份，未来 Command 加字段自动生效；坏行留在表里（仍是孤儿）只是跳过，不中止恢复。

### 3.6 配置面（client_config.h:13-41 + client_config.cpp:91-115）

| 配置键（文件） | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| `server_base_url` | `TRACELENS_SERVER_URL` | 必填 | 必须 https://（localhost/127.0.0.1/::1 豁免 http，client_config.cpp:49-65） |
| `poll_interval_seconds` | `TRACELENS_POLL_INTERVAL` | 10 | validate 限 5-30 |
| `reindex_interval_seconds` | `TRACELENS_REINDEX_INTERVAL` | 1800 | 0 = 关闭周期重索引 |
| `token_path` | `TRACELENS_TOKEN_PATH` | 必填 | JWT 文件，须 0600 |
| `hostname` | `TRACELENS_HOSTNAME` | 空 | 上报用 |
| `analyzer_path` | `TRACELENS_ANALYZER_PATH` | 必填 | forensic_analyzer 二进制 |
| `work_base_dir` | `TRACELENS_WORK_DIR` | `<cwd>/tracelens_work`（main 兜底） | 每命令子目录的父目录 |
| `state_db_path` | `TRACELENS_STATE_DB` | `<work_dir>/tracelens_state.db`（main 兜底） | in-flight 存储 |
| `image_dirs` | `TRACELENS_IMAGE_DIRS` | 空 | 冒号分隔列表；空则跳过镜像索引 |

## 4. 工作流程走读

**main**（http_agent_main.cpp:38-136）：`--config <path>` / `--once`（单轮即退，:44；测试与 cron 场景用）；配置装载 → validate（不过直接退出码 2）→ JwtClient（权限不对抛异常）→ 组件装配。两处易错点有代码注释钉住：传给 HttpLibClient 的是**裸 token** 而非 `bearer_value()`，否则头变成 `Bearer Bearer …` 全线 401（:81-85）；启动时做一次**尽力而为**的镜像索引上报（失败只告警不致命，:105-121）。SIGINT/SIGTERM 走 async-signal-safe 的原子置位（:124-125），主循环 200ms 粒度切片睡眠保证快速退出（http_agent_service.cpp:191-196）。

**循环体**（http_agent_service.cpp:81-199）：先 recover；若 `reindex_interval_seconds > 0`（默认 1800，0 关闭）按周期重扫镜像清单，失败不更新时间戳以便下轮重试（:89-111）；poll 领批（传输错误记日志继续循环，单次失败不打倒 agent；poller 对部分解析失败返回"已解析的命令 + err"，服务循环据此区分信息性错误与真实失败，:115-121）；逐条执行五段式（见 3.3）。

**执行** `AnalyzeDiskExecutor::execute`（command_executor.cpp:141-207），argv 构造（`build_analyzer_argv`，command_executor.cpp:69-88）：

```cpp
std::vector<std::string>& a = out.argv;
a.push_back(analyzer_path);
a.push_back(out.image_path);          // 位置参数
a.push_back("--db-dir"); a.push_back(db_dir);
a.push_back("--no-ai");               // INVARIANT: client never runs the LLM.
a.push_back("--overwrite");           // fresh dir, but always regenerate cleanly.

const std::string atype = to_lower(param_string(cmd.parameters, "analysis_type"));
if (atype == "windows")      a.push_back("--windows-analyze");
else if (atype == "linux")   a.push_back("--linux-analyze");
else if (atype == "android") a.push_back("--android-analyze");
// "full"/"quick"/unknown: defer to the analyzer default (no platform flag).
// options.file_carving -> --carve. options.llm_text_extraction is
// INTENTIONALLY ignored (the client never runs the LLM; --no-ai above).
if (param_bool(cmd.parameters, "options", "file_carving")) {
    a.push_back("--carve");
}
```

`--no-ai` 是硬编码不变量——即使服务端命令里带了 `llm_text_extraction: true` 也被刻意忽略。工作目录按命令隔离：`work_base_dir/<cmd.id>`，跑完收集其中 `<镜像stem>*.db`（collect_db_artifacts，:92-120；`.db` 后缀天然排除 -wal/-shm 边车，结果按路径排序保证测试确定性）。**原始镜像路径永不离开客户机**：本地缺失时错误消息只带 stem（:163-167），完成消息只有 "analyzed; N artifact(s)"（:205）。

**上传契约**：`ResultUploader::upload`（result_uploader.cpp:5-28）要求 task_id 非空（空则拒绝：命令没有任务软链接），body 是 `{"artifacts": [...]}`；`StatusReporter::report`（status_reporter.cpp:5-23）在 body 里**强制补 `command_id`**——漏了就是 422。

**失败与重试语义矩阵**：

| 环节 | 失败行为 | 重试机制 |
|---|---|---|
| poll 传输失败/非 2xx | 记日志，本轮空批 | 下一轮 poll 间隔后自然重试（无退避，间隔固定） |
| poll 单条 JSON 坏 | 跳过该条，其余照常 | 无（该命令对 agent 不可见，靠服务端 TTL 24h/1h-critical 过期） |
| record_started 失败 | 告警，**照常执行** | 无（该命令崩溃后不可恢复——已知的可靠性缺口） |
| in_progress 上报失败 | 告警，照常执行 | 无（终态上报才是关键路径） |
| analyzer 非零退出/无法启动 | 命令判 FAILED，message 带 stderr 尾部 500 字符 | 服务端可重派 |
| 结果上传失败 | **整条命令改判 FAILED**，本地工件保留 | 服务端可重派；本地可手工恢复 |
| 终态上报失败 | 记 error 日志；in-flight 行保留 | **只在下次重启时**由 recover 补报（无后台重试线程） |
| 镜像索引上报失败 | 告警；时间戳不更新 | 下一周期重试 |

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| python_service/server（C/S 服务端，:8091） | 命令源与结果汇（命令类型 analyze_disk/health_check/extract_file 等，结果写 analysis_results）；协议细节在服务端 `server/api/commands.py` |
| forensic_analyzer（单体二进制） | 被 fork 的分析器本体；参数面就是它的 CLI |
| libs/cpp-mcp/common（vendored httplib/json） | HTTP 与 JSON 依赖；TLS1.3 下限靠 `CPPHTTPLIB_ENFORCE_TLS1_3_MIN`（仅本目标 PRIVATE 生效，CMakeLists.txt:38-42） |
| tests/test_http_agent.cpp | 47 个 GTest 用例（CMake 目标 tracelens_agent_test，60s 超时），含回环 httplib::Server 的真传输测试 |

## 6. 注意事项与已知问题

- **extract_file 在客户端是"确认但不执行"**：execute 对一切非 analyze_disk 命令返回 success + "ignored non-analyze command"（command_executor.cpp:145-150）。服务端可以下发 extract_file/health_check，但当前客户端不实现其语义——服务端会看到 completed。扩展时的第一优先级。
- **30 天 JWT 无刷新机制**：过期路径是重新注册换新 token（jwt_client.h:4-8 注释）；部署脚本要监控到期。
- **不接入根构建**：单独 `cmake -S src/http_agent -B build/http_agent` 构建；根 CMake 不会顺带编它（CMakeLists.txt:12-16）。
- **poll 领取即负责**：poll 端点在服务端侧已把命令标记给该客户端，agent 崩溃只能靠 recover 报 FAILED 补救——没有"处理超时服务端回收重派"的客户端侧机制（服务端侧策略见其文档）。
- **命令存储单连接、同步写**：record_started 在执行前多一次 fsync，高频命令下是可感知的延迟；当前设计取向是可靠优先。
- **in_flight_commands 兼作 outbox**：终态上报失败时行保留（服务恢复后由下次重启补报），但**没有**后台重试线程——补报只发生在重启时刻。
- **http_client 全局互斥**：Impl 内 `mtx` 让 get/post 串行——agent 本就是单线程循环，这是防御性的（未来并发化时要么放开要么按端点分客户端）。

## 7. 如何验证与扩展

- **验证**：`cmake -S src/http_agent -B build/http_agent && cmake --build build/http_agent && ctest --test-dir build/http_agent --output-on-failure`；真机冒烟：起本地 8091 服务端注册客户端 → `tracelens_agent --config agent.conf --once` → 查服务端命令状态与 analysis_results；杀进程再启，确认孤儿命令被报 FAILED（recover 生效）。
- **扩展新命令类型**：① models/command.h 的注释补类型名；② command_executor.cpp 加一个 Executor 或在 execute 里分支（argv 构造参考 build_analyzer_argv 的 fail-fast 模式）；③ 收集工件参考 collect_db_artifacts（stem 前缀 + 后缀白名单）；④ 测试补 FakeProcessRunner 用例（tests/test_http_agent.cpp 已有完整范式）。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
