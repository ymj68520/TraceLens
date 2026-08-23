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

## 3. 核心概念与设计

### 3.1 组件一览（全部在 tracelens 命名空间下）

| 组件 | 职责 |
|---|---|
| http_client | cpp-httplib 封装；加 Bearer 头、超时 10/300/60s、**禁止跟随重定向**（防 token 随 3xx 泄漏，http_client.cpp:29-38）；无 OpenSSL 直接 `#error`（:14-16） |
| jwt_client | 30 天 JWT 装载；**token 文件必须 0600**（group/other 任何位都硬错，jwt_client.cpp:68-74）；client_id 从 payload 解出（不做签名校验，服务端会再验，jwt_client.h:18-21） |
| client_config | key=value 配置文件或 TRACELENS_* 环境变量；validate 强制 https（localhost 豁免）、token/analyzer 必填、poll 5-30s |
| poller | GET poll → 解析 commands 数组；**单条坏命令跳过不弃批**（poller.cpp:37-42） |
| command_executor | 命令 → analyzer argv；非 analyze_disk 一律"确认并成功"（见 §6） |
| process_runner | fork/exec + 管道捕获（>8MiB 输出的防死锁有测试钉住） |
| command_store | SQLite `in_flight_commands(command_id PK, command_type, parameters JSON, priority, started_epoch)`（command_store.cpp:71-82）；INSERT OR REPLACE 落盘即 fsync |
| http_agent_service | 主循环与崩溃恢复（§4） |
| image_indexer / index_uploader | 扫描 image_dirs 报告本机镜像（DD/E01/目录三种格式识别，image_indexer.cpp:52-70）；md5 刻意不上传 |
| result_uploader / status_reporter | 结果与状态回传；status body 必须带 command_id（服务端 schema 校验，422 陷阱，status_reporter.cpp:10-16） |

### 3.2 主循环的五段式命令处理

每条命令严格按序：**record_started（先落盘）→ 报 in_progress → execute → 上传工件 → 报终态 → clear**。顺序本身就是容错设计：崩溃发生在任何一点，重启后 `recover()` 都能从 in_flight_commands 里找到孤儿。

### 3.3 崩溃恢复：报 FAILED 而不重跑

`recover`（http_agent_service.cpp:37-79）：孤儿命令一律向服务端报 FAILED（"agent restarted; command interrupted"）后清行，**不重新执行**——崩溃留下的磁盘状态完整性未知，重跑不可靠（:40-43 注释）。若 FAILED 上报失败则**不清行**，留给下次重启重试（"never lose a failure signal"，:57-64）；终态转换在服务端幂等，重复上报无害。

## 4. 工作流程走读

**main**（http_agent_main.cpp:38-136）：`--config <path>` / `--once`（单轮即退，:44；测试与 cron 场景用）；配置装载 → validate（不过直接退出码 2）→ JwtClient（权限不对抛异常）→ 组件装配。两处易错点有代码注释钉住：传给 HttpLibClient 的是**裸 token** 而非 `bearer_value()`，否则头变成 `Bearer Bearer …` 全线 401（:81-85）；启动时做一次**尽力而为**的镜像索引上报（失败只告警不致命，:105-121）。SIGINT/SIGTERM 走 async-signal-safe 的原子置位（:124-125），主循环 200ms 粒度切片睡眠保证快速退出（http_agent_service.cpp:191-196）。

**循环体**（http_agent_service.cpp:81-199）：先 recover；若 `reindex_interval_seconds > 0`（默认 1800，0 关闭）按周期重扫镜像清单，失败不更新时间戳以便下轮重试（:89-111）；poll 领批（传输错误记日志继续循环，单次失败不打倒 agent）；逐条执行五段式；上传失败会把整条命令改判 FAILED（结果不可交付就该报警并让服务端可重试，:156-166）。

**执行** `AnalyzeDiskExecutor::execute`（command_executor.cpp:141-207）：

```cpp
a.push_back(analyzer_path);
a.push_back(out.image_path);          // 位置参数
a.push_back("--db-dir"); a.push_back(db_dir);
a.push_back("--no-ai");               // INVARIANT: 客户端永不跑 LLM
a.push_back("--overwrite");
```

（command_executor.cpp:69-76。）工作目录按命令隔离：`work_base_dir/<cmd.id>`，跑完收集其中 `<镜像stem>*.db`（collect_db_artifacts，:92-120；`.db` 后缀天然排除 -wal/-shm 边车）。**原始镜像路径永不离开客户机**：本地缺失时错误消息只带 stem（:163-167），完成消息只有 "analyzed; N artifact(s)"（:205）。

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

## 7. 如何验证与扩展

- **验证**：`cmake -S src/http_agent -B build/http_agent && cmake --build build/http_agent && ctest --test-dir build/http_agent --output-on-failure`；真机冒烟：起本地 8091 服务端注册客户端 → `tracelens_agent --config agent.conf --once` → 查服务端命令状态与 analysis_results；杀进程再启，确认孤儿命令被报 FAILED（recover 生效）。
- **扩展新命令类型**：① models/command.h 的注释补类型名；② command_executor.cpp 加一个 Executor 或在 execute 里分支（argv 构造参考 build_analyzer_argv 的 fail-fast 模式）；③ 收集工件参考 collect_db_artifacts（stem 前缀 + 后缀白名单）；④ 测试补 FakeProcessRunner 用例（tests/test_http_agent.cpp 已有完整范式）。

**最后更新**: 2026-08-23（新建，解释式）
