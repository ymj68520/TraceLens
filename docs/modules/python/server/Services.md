# server 业务服务层（python_service/server/services/：auth_service、command_queue、task_orchestrator、result_aggregator）

> **一句话**：分布式 C/S 协议的四个领域服务——JWT 签发/校验（HS256，user/client 双 token）、命令队列（领取/TTL 过期/优先级）、任务编排（任务↔命令联动 + 审计历史）、结果回收（工件与 llm_analysis 按引用落库）——路由层（`server/api/`）只是它们的薄壳。

## 1. 为什么有这个模块

分布式形态的交互是一个**轮询协议**：服务端把命令排进队列，agent 客户端每 10s 来领、本地执行 forensic_analyzer、再把状态/工件报回来。这产生了四个路由层不该操心的领域问题：**信任**（两类主体——平台用户与取证机——如何拿到互不可冒充的 token）、**分发**（谁先领到命令、过期了怎么办）、**一致性**（任务状态机与命令状态机如何联动且留审计）、**回收**（远端工件如何在不传镜像字节的前提下登记）。每个服务对应一个问题。四个文件共享两个约定：**aware-UTC 时间**（`datetime.now(timezone.utc)`，naive `utcnow()` 与 DB 存的 aware 时间比较会 TypeError，且 Python 3.12 起废弃——auth_service.py:66-70、command_queue.py:11-17 的模块注释都记录了这一修复）与 **owns_session 模式**（每个公共方法接受可选 `db`，不传就自开自关一个 SessionLocal，`try/finally` 保证归还连接池——command_queue.py:172-177 是范式，后台调用方不会耗尽池）。

## 2. 在系统中的位置

- **谁调用它们**：`server/api/` 六个路由模块（auth.py 调 auth_service；commands.py 调 command_queue；tasks.py/results.py 调 task_orchestrator/result_aggregator）；`middleware/auth.py` 的 `get_current_user` / `get_current_client` 委托 auth_service 验签回查。
- **它们调用谁**：只碰 PostgreSQL（经 `server/db/session.py` 的 SessionLocal/engine）与 `server/models/` ORM；command_queue 与 task_orchestrator 之间是**调用时惰性导入**的同伴关系（command_queue.py:330-332），避免模块级互相依赖。
- **下游消费者**：C++ tracelens_agent 的 poller（轮询领取）、command_executor（执行 analyze_disk/extract_file/health_check）、status_reporter（回报状态，间接触发任务状态机）、result_uploader/index_uploader（上传工件索引）。

## 3. 核心概念与设计

**（a）auth_service：双 token、单密钥、严格类型。** 算法固定走 `settings.JWT_ALGORITHM`（默认 HS256 对称密钥 `JWT_SECRET_KEY`）——曾有过按 ENVIRONMENT 自动切 RS256 的实现，因没有密钥对而弄坏签发，已删除；换 RS256 必须显式配置（auth_service.py:12-18）。密钥/时效只从 config 读取，禁止再 `os.getenv` 造成第二真相源（auth_service.py:29-35）。两种 token 的差别全部体现在 payload：

```python
payload = {
    "user_id": str(user_id), "org_id": str(org_id),
    "role": role, "permissions": permissions,
    "iat": now.timestamp(), "exp": expires.timestamp(),  # 1 小时
    "type": "user",
}
```

client token 则是 `client_id`/`capabilities`、30 天时效、`type: "client"`（auth_service.py:86-116）。`type` 字段是中间件互斥校验的依据（client token 打 user 端点 → 401）。`verify_token` 对过期/无效统一返回 None（auth_service.py:129-135，不区分错误类别以免泄露探测面）；`get_user_from_token` / `get_client_from_token` 验签后再按 id 回查 ORM——token 有效但主体已删的边界被兜住。口令是 passlib bcrypt（auth_service.py:38-48）。

**（b）command_queue：领取有优先级，过期有 TTL。** `get_pending_commands`（command_queue.py:93-142）是协议核心——过滤"本客户端 + pending + 未过 TTL"，按优先级排序后**原子转 assigned**：

```python
priority_order = case(                       # critical > high > normal > low
    (CommandQueue.priority == "critical", 1), # 未知优先级排最后(else_=5)
    (CommandQueue.priority == "high", 2),
    (CommandQueue.priority == "normal", 3),
    (CommandQueue.priority == "low", 4), else_=5,
)
# order_by(priority_order, created_at.asc()) → 逐条 status="assigned", assigned_at=now → commit
```

`create_command`（command_queue.py:41-91）对 `critical` 命令**无视调用方给的 ttl_hours**，强制 1 小时短窗（`CRITICAL_COMMAND_TTL_HOURS`，其余默认 24h）；显式置 `status="pending"` 而不依赖列默认，保证返回对象在 flush 前就完整。`expire_commands`（command_queue.py:206-246）是 TTL 清扫器：pending/assigned 且 TTL 已过的批量转 `expired`。`update_command_status`（command_queue.py:144-204）的语义是：`completed`/`failed` 盖 `completed_at`，`failed` 额外 `retry_count += 1`；`in_progress` 只翻状态；`result_message` 仅在新值提供时覆写，进度上报不会冲掉既有错误信息。`get_commands_for_client`（command_queue.py:248-288）组装一次 poll：先刷新在场状态（`last_seen=now`；`last_poll` 在 60s 内则 online，否则 offline——`last_poll` 由 poll 路由在调它之前盖章，api/commands.py:100-113），再领取命令。

**（c）propagate_command_status：命令→任务的桥。** 命令状态上报后，此方法（command_queue.py:290-385）把变化传导给发起任务：task 解析**以 002 迁移的 `task_id` FK 列为准**，仅对迁移前的旧行回退 `parameters->>'task_id'` 软链接（command_queue.py:339）；`health_check`/`extract_file` 这类无主命令直接返回。传导按 `command.client_id` 限定任务查找范围——防的是有人往 ad-hoc 命令的 parameters 里塞伪造 task_id 去推动别家任务（纵深防御，任务级隔离仍在 API 层）。整个传导是 best-effort：命令状态（客户端可见的主操作）已提交，任务缺失/过期/越界抛的 ValueError 只记 warning 不上抛（command_queue.py:374-384）。

**（d）task_orchestrator：一次创建、两份落库、全程审计。** `create_analysis_task`（task_orchestrator.py:45-157）是一个事务叙事：校验 client/disk_image 存在 → 建任务（status=created，`task_metadata` 快照镜像路径与格式）→ 记 `task_history`（"created"）→ 建 `analyze_disk` 命令——**同时写 FK 列 `task_id` 和 JSONB 软链接 `parameters["task_id"]`**（后者按迁移说明保留一个发布周期兼容在途客户端，task_orchestrator.py:121-124）→ 任务转 `queued`。此后状态机靠两个方法推进，都有**终态幂等护栏**（completed/failed/cancelled 的任务无视后续上报——迟到/重复的客户端报告不能重盖 `completed_at`、不能复活用户取消的任务，task_orchestrator.py:324-325）：`update_task_progress`（:182-277）首份执行报告把任务从 created/queued 转 running 并盖 `started_at`；`complete_task`（:279-349）按成败落终态。`cancel_task`（:351-409）取消任务时用 FK 列精准失败**本任务**尚未开跑的命令（pending/assigned），不会误伤同客户端并发任务的命令。`_record_history`（:443-463）刻意不 commit——审计行随它描述的状态变更同一个事务落库。一个必须记住的 ORM 坑：

```python
# JSONB 不能原地改：无 MutableDict 的 Column(JSONB) 不会把 in-place 变更显式化
metadata = dict(task.task_metadata or {})
messages = list(metadata.get("messages", []))
messages.append({"timestamp": ..., "message": message})
metadata["messages"] = messages
task.task_metadata = metadata   # 整体重赋值才会被识别为 dirty
```

（task_orchestrator.py:256-270；原地 `task.task_metadata["messages"].append(...)` 提交时会静默丢失。）

**（e）result_aggregator：按引用回收，不传字节。** 工件契约（result_aggregator.py:65-74、136-144）明确：`file_path`/`storage_location` 是客户端给的**不透明句柄**，服务端不假设本地模式的固定文件名（raw.db/events.db/files.db 是 :8666 C++ 进程内约定，不适用分布式路径）；原始镜像字节永不过线，只登记引用与元数据，`result_metadata` 原样落库（其中的 `base_name` 是客户端命名的工件基名，形如 `<baseName>_<kind>.db`）。`store_results`（:126-197）批量版先**全量校验** result_type（仅 database/file/metadata，与 DB CHECK 一致）再单事务写入——坏条目在任何写之前失败。`_get_task_or_raise`（:312-330）执行存在性 + 所有权检查：client 只能往**自己任务**里塞结果，兄弟客户端注入被挡。`store_llm_analysis`（:203-262）存 agent 本地 LLM 分析的回收记录（`input_text_hash` 是去重键，`cost` 是 Numeric(10,4)）。两个模型的时间戳都交给 `server_default=func.now()`，服务层不设时间（result_aggregator.py:26-30）。

## 4. 工作流程走读：一个任务的完整生命周期

1. 分析师经 web 前端 `POST /api/tasks` → API 层注入 `current_user.org_id` → `TaskOrchestrator.create_analysis_task`：任务 created → analyze_disk 命令 pending（FK + 软链接双写）→ 任务 queued，全程记 history。
2. agent 的 poller 带 client JWT 到 `GET /api/commands/poll`：路由盖章 `last_poll` → `get_commands_for_client` 刷新在线状态并按优先级领取命令（→assigned）。
3. agent 本地跑 forensic_analyzer，期间 `POST /api/commands/{id}/status`（in_progress+progress）→ `update_command_status` 翻状态 → `propagate_command_status` → `update_task_progress`（任务→running，progress 盖章，message 进 metadata.messages）。
4. 结束时上报 completed/failed → `complete_task` 落终态、记 history；工件经 result_uploader `POST /api/tasks/{id}/results` → `store_results` 按引用批量登记；LLM 分析回收进 `store_llm_analysis`。
5. 兜底：客户端一直不来领/领了不回——`expire_commands` 把 TTL 过期的命令转 expired（由 expire 端点触发）；任务侧若无终态则停在 queued/running，等待人工 cancel（同时失败其未开跑命令）。

## 5. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| `middleware/auth.py` | 验签/回查全委托 auth_service；中间件只做类型互斥与 401 语义 |
| `server/api/commands.py` | poll 端点盖章 last_poll 后调 get_commands_for_client；状态端点先 update_command_status 再 propagate_command_status（api/commands.py:149-160） |
| `server/api/tasks.py` / `results.py` | orchestrator 与 aggregator 的薄封装；org 隔离在此层（服务层信任传入的 org_id，docstring task_orchestrator.py:21-26） |
| `migrations/postgresql/002` | task_id FK 是 propagate/cancel 的权威链接；软链接仅过渡兼容 |
| tracelens_agent | 命令的真正执行者；capabilities/轮询节奏（5-30s，默认 10s）与 config.py:71-73 呼应 |
| 本地栈（httpserver） | 无协作——服务层不感知 :8090；同 venv 纯属部署共享 |

## 6. 注意事项与已知问题

- **retry_count 只计数不重试**：`failed` 时自增（command_queue.py:195），但没有任何代码消费它做自动重新入队——"重试"目前是运维语义不是机制。
- **expire_commands 没有定时器**：只有 `/api/commands/expire` 端点触发（需 user token）；没有后台 sweeper，长期无人调用的部署里过期命令会一直保持 pending/assigned 状态占着队列查询。
- **软链接双写有截止日**：propagate 的 JSONB 回退路径（command_queue.py:339）只为迁移前旧行保留；过渡期结束后应删除，届时 create 的双写（task_orchestrator.py:125-134）一并清理。
- **并发领取非严格原子**：`get_pending_commands` 是"查询→逐条改状态→commit"，两个同客户端并发 poll 在 READ COMMITTED 下理论上可同时查到同一批 pending（agent 是单 poller，实际风险低；严格化需 `SELECT ... FOR UPDATE SKIP LOCKED`）。
- **org 隔离不在服务层**：orchestrator/aggregator 信任传入 org_id/user_id（docstring 明示）；新增调用方必须自己带 scope，别绕过 API 层直接调服务。
- client 的在线判定窗口硬编码 60s（command_queue.py:275），与 MIN_POLL_INTERVAL=5/MAX_POLL_INTERVAL=30 的合法轮询区间匹配，但改轮询上限超过 60s 会让守法客户端被判 offline。

## 7. 如何验证与扩展

- auth：`tests/test_auth_service.py`（签发/校验/回查）、`test_auth_api.py`（登录/refresh/me 端到端）、`test_auth_algorithm.py`（HS256 一致性）。
- 命令队列：`tests/test_command_queue.py`（领取/状态/TTL/优先级）、`test_commands_api.py`（HTTP 契约）、`test_command_task_fk.py`（FK 级联、cancel 经 FK 失败命令、propagate 用列不用 JSONB——需 `TEST_DATABASE_URL` 真 PostgreSQL）。
- 编排/回收：`tests/test_task_orchestrator.py`、`test_result_aggregator.py`、`test_tasks_api.py`、`test_results_api.py`。
- 手工链路：登录拿 token → 注册客户端（拿 client JWT）→ `POST /api/tasks` → 用 client token `GET /api/commands/poll` → `POST /api/commands/{id}/status` → `POST /api/tasks/{id}/results` → `GET /api/tasks/{id}/results`。
- 新增命令类型：schemas.py 的 CommandCreate 正则、database.py 的 command_queue_command_type_check、C++ command_executor 的分发三处要同步加，漏一处就会被 CHECK/校验挡下。

相关阅读：[Main.md](./Main.md)（应用装配/DB/中间件）、`docs/architecture/DatabaseSchema.md` 第 9 节（这四件套读写的 10 张表）、`src/http_agent/`（协议另一端）。

**最后更新**: 2026-08-23（新建，解释式）
