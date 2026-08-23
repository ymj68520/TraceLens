# IngestionJobManager（python_service/httpserver/services/ingestion_job_manager.py + ingestion_job_models.py + ingestion_job_parts/）

> **一句话**：图谱摄取的后台作业队列——单个 `asyncio` worker 消费 `ingestion_queue`，作业状态 PENDING/RUNNING/COMPLETED/FAILED/CANCELLED 持久化到 Redis（`REDIS_URL`，不可用回退内存 dict），五种模式 FULL/FILES_ONLY/EVENTS_ONLY/SINGLE_FILE/ANALYZED_ONLY 分别把文件实体、事件、MENTIONED_IN 边与 path-A episode 写进 Neo4j。

## 1. 为什么有这个模块

Graphiti 摄取是长任务（一个任务几万文件 + LLM 抽取），不能挂在 HTTP 请求里。系统需要：**持久化的作业状态**（前端轮询、进程重启后状态不丢）、**可选的基础设施**（Redis/Neo4j 缺席时服务仍要起来并优雅降级）、以及**两条摄取路径的合流**——path-B（`FileEntityIngestor` 直接建 `:File` 节点）与 path-A（`GraphitiService.ingest_task_episodes` 走 add_episode 让 LLM 建实体关系图，前端可视化的正是后者）。IngestionJobManager 把这三件事集中在一个 mixin 组合的服务里，路由层不必关心存储与降级。

## 2. 在系统中的位置

- **谁调用它**：routes/graphiti_endpoints（手动 Ingest 按钮优先走本管理器，失败才回落 GraphitiService 的旧式内存作业，_ingest.py:60-77：`hasattr(service_manager, 'ingestion_job_manager')` 判定后 `queue_ingestion(task_id, mode)`，否则 `graphiti_service.start_ingestion`）；ServiceManager 启动序列在其 initialize 上给 12s 可选服务预算（service_manager.py:213-223）。
- **它调用谁**：Redis（`redis.asyncio`，作业哈希 + 队列 + 事件暂存）；graphiti_integration 的 `FileEntityIngestor` / `EntityRelationBuilder` / `ForensicsDatabase` / `EventsDatabase`（path-B 直写 Neo4j）；`GraphitiService.ingest_task_episodes`（path-A，经 service_manager 反查）；CppBackendService（任务数据库路径的权威来源）。
- **结构**：`ingestion_job_manager.py` 只是组装壳 + 兼容 re-export；实现在 `ingestion_job_parts/_manager.py`（生命周期/持久化/队列与状态 API）与 `_worker.py`（后台 worker 与各模式处理）；数据类在 `ingestion_job_models.py`。

## 3. 核心数据结构

```python
# ingestion_job_models.py:13-48
class IngestionMode(str, Enum):
    """Ingestion operation modes."""
    FULL = "full"
    FILES_ONLY = "files_only"
    EVENTS_ONLY = "events_only"
    SINGLE_FILE = "single_file"
    ANALYZED_ONLY = "analyzed_only"  # Only AI-analyzed files


class JobStatus(str, Enum):
    """Job status states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class IngestionJob:
    """Represents an ingestion job."""
    job_id: str
    task_id: str
    mode: IngestionMode
    status: JobStatus = JobStatus.PENDING
    progress: int = 0  # 0-100
    current_phase: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None

    # Additional metadata
    file_id: Optional[int] = None  # For SINGLE_FILE mode
    events_count: int = 0  # For EVENTS_ONLY mode
```

- 两枚举都继承 `str, Enum`：Redis/JSON 里以 value 往返，读回时 `IngestionMode(data["mode"])` 复原；
- `current_phase` 是机器可读的阶段名（reading_databases/creating_file_entities/attaching_events/ingesting_episodes...），前端据此渲染步骤；`progress` 与 phase 由 worker 双轨更新；
- `created_at` 用 `datetime.utcnow()`（naive ISO 串，仅作记录不参与比较）；
- `file_id`/`events_count` 是模式专属载荷；注意 `queue_event_sync` 在内存模式还会动态挂 `_events` 属性（见第 6 节）。

## 4. 核心接口清单

| 方法（真实签名） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `async initialize()` | Redis 连接 + Neo4j 组件装载 + 起 worker | ServiceManager（12s 预算） | 任何失败只降级，永不抛 |
| `async queue_ingestion(task_id, mode=IngestionMode.FULL) -> str` | 建 PENDING 作业并 LPUSH 队列 | 摄取路由 | Redis 失败前已回退内存 |
| `async queue_file_update(file_id, task_id) -> str` | SINGLE_FILE 入队 | 文件级更新入口 | 同上 |
| `async queue_event_sync(task_id, events: list[dict]) -> str` | EVENTS_ONLY 入队 + 载荷暂存（TTL 3600s） | 事件同步入口 | 同上 |
| `async get_job_status(job_id) -> Optional[dict]` | 读回作业（HGETALL/内存） | 前端轮询 | 不存在返回 None→404 |
| `async cancel_job(job_id) -> bool` | 非终态作业改 CANCELLED | 取消按钮 | 终态作业拒绝 |
| `async list_jobs() / redis_health_check() -> dict` | 扫描 job:* / Redis 健康 | 管理端点 | 不抛 |
| `async shutdown()` | 停 worker、关组件与 Redis | ServiceManager 关停 | 容忍各步异常 |
| `_process_job` / `_process_full_ingestion` / `_process_analyzed_only` / `_ingest_episodes_path_a`（worker 内部） | 状态机分发与五模式执行 | worker 自身 | 异常→FAILED+error |

## 5. 核心概念与设计

**（a）Redis 持久化 + 内存回退。** `initialize`（_manager.py:62-155）先 `aioredis.from_url(settings.redis_url)`（默认 `redis://localhost:6379`，config.py:187），带 5s 连接/30s 命令超时与 30s 健康检查；ping 失败即 `_use_redis=False` 落内存 dict，**永远不抛**。存储形态——每作业一个 `job:{id}` HSET（None 剥离、dict/list 序列化为 JSON），队列是 `ingestion_queue` LIST（LPUSH 进/RPOP 出）。序列化代码：

```python
# ingestion_job_parts/_manager.py:228-245（节选）
# Redis HSET mapping does not accept None values — strip them
job_dict = {k: v for k, v in job_dict.items() if v is not None}

# Redis can only store scalar types (str, bytes, int, float).
# Convert dicts/lists to JSON strings so nested values serialize cleanly.
import json
_serializable = {}
for k, v in job_dict.items():
    if isinstance(v, (dict, list)):
        _serializable[k] = json.dumps(v, ensure_ascii=False, default=str)
    else:
        _serializable[k] = v

if self._use_redis:
    await self._redis.hset(
        f"job:{job.job_id}",
        mapping=_serializable
    )
else:
    self._jobs[job.job_id] = job
```

两层转换的原因写在注释里：HSET 的 mapping 不接受 None；Redis 只存标量，嵌套 result 必须先 JSON 化。读回时恢复枚举与 result dict（:249-269：`IngestionMode(data["mode"])` / `json.loads(data["result"])`，坏 JSON 静默置 None）。EVENTS_ONLY 的载荷暂存 `job_events:{id}`（TTL 3600s，:406-412）。`list_jobs` 在 Redis 模式用 `scan_iter(match="job:*")`（:491-505）。入队侧：

```python
# ingestion_job_parts/_manager.py:330-338（节选）
await self._save_job(job)

# Signal worker by adding to queue
if self._use_redis:
    await self._redis.lpush("ingestion_queue", json.dumps({
        "job_id": job_id,
        "task_id": task_id,
        "mode": mode.value,
    }))
```

作业本体先落 HSET、再 LPUSH 小信封——worker 只从信封拿 job_id 回读全量，队列元素保持极小。

**（b）降级的 Neo4j 组件装载。** `initialize` 第二步把 `python_service/`（本文件 `parents[3]`）插入 sys.path 后导入 graphiti_integration 组件——注释记录了历史上 `parents[3]` 误算成 `httpserver/` 导致启动脚本忘了 PYTHONPATH 时静默 ImportNotFound 的教训（:93-107）。任何失败都只降级（`_file_ingestor is None`），worker 照常启动（:151-153）；各模式处理函数开头检查组件并把作业标 COMPLETED 附 `"Neo4j not available"` 说明（如 _worker.py:112-117）。

**（c）Worker 循环（_worker.py:29-74）。** Redis 模式：非阻塞 RPOP 循环，单周期上限 100 条保持响应性，队列空 sleep(1)：

```python
# ingestion_job_parts/_worker.py:35-53（节选）
if self._use_redis:
    # Drain the queue with a non-blocking RPOP loop, then idle.
    # We intentionally avoid BRPOP(timeout=...): when the queue is
    # empty the server-side block holds the socket open for up to
    # `timeout` seconds, and any socket read timeout smaller than
    # that (or a transient read delay) trips redis-py's
    # "Timeout reading from localhost:6379" and disconnects the
    # connection. RPOP returns immediately, so socket read
    # latency is bounded by the actual command, not the block.
    processed_any = False
    for _ in range(100):  # hard cap per cycle to stay responsive
        item = await self._redis.rpop("ingestion_queue")
        if item is None:
            break
        processed_any = True
        queue_data = json.loads(item)
        await self._process_job(queue_data)
    if not processed_any:
        await asyncio.sleep(1)  # queue idle
```

BRPOP 被弃用的原因写足在注释：阻塞读与 socket_timeout 相互踩踏会周期性断连。内存模式：每秒扫一次 PENDING，**一次只处理一条**。`_process_job`（:76-107）是状态机骨架：标 RUNNING → 按 mode 分发 → COMPLETED(progress=100)；任何异常标 FAILED 并存 error。

**（d）FULL 模式的五步（:109-220）。** 读库（`_resolve_task_database` :776-795 **优先 C++ 任务记录的 output_*_db**，找不到才走 `_find_database` 的文件系统启发式 :797-856）→ `batch_ensure_files` 建文件实体（进度回调做了百分比去抖，避免几十万次 HSET，:138-150）→ `attach_events_batch` 挂事件 → `_create_mentioned_in_edges` → `merge_duplicate_files` → path-A episode 摄取。`_create_mentioned_in_edges`（:635-735）的 docstring 记录了一个被修复的老 bug：旧实现试图从 episode 名恢复文件路径再哈希，但 episode 名是本地化的（"文件分析: /path"）且事件簇 episode 根本没有路径，导致 `mentioned_in_edges_created` 恒为 0；现在从 File 记录按 basename 建映射，另有 `_link_entities_to_files_by_name`（:737-774）用一条参数化 UNWIND MERGE 把"实体名 == 文件名"的强取证信号连上。

**（e）ANALYZED_ONLY 与 path-A 的 JOIN files 高价值信号。** `_process_analyzed_only`（:307-435）只取 `iter_files_batched(analyzed_only=True)` 的文件走同套流程。`_ingest_episodes_path_a`（:437-601）从 `_files.db` 读 file_descriptions 并 **JOIN files 表带上 category/md5/name/size**，text_factory 兜底 GBK 文件名（:476-485）：

```python
# ingestion_job_parts/_worker.py:486-505（节选）
# Ensure schema has the description columns (added lazily by analysis pipeline)
# We JOIN against the files table to also surface category/md5/name/size
# which are high-value extraction signals (hashes and category names
# are exactly what the default JSON prompt throws away).
where = (
    "WHERE fd.description IS NOT NULL AND fd.description != ''"
    if analyzed_only else ""
)
try:
    cur = conn.execute(
        f"""
        SELECT fd.file_path, fd.description, fd.summary,
               fd.keywords, fd.is_relevant,
               f.category, f.md5, f.name, f.size, f.extension,
               f.type AS file_type
        FROM file_descriptions fd
        LEFT JOIN files f ON f.path = fd.file_path
        {where}
        """
    )
```

JOIN 的动机在注释：默认 JSON prompt 会丢哈希/类别这类字段值，带进 episode body 才能被取证抽取指令捞回。行转成带 `success: True` 的 desc dict 后，连同 `(event_type, minute)` 去重的事件簇，全部喂给 `GraphitiService.ingest_task_episodes`（:583-588），进度映射到 92-95% 区间（`_ep_progress` 用正则从消息里解析 "X/Y"）。此路径**失败非致命**——path-B 的 :File 节点仍然有效（外层 try/except 只写 stats["error"]，:598-600）。

## 6. 注意事项与已知问题

- **cancel 不是抢占**：`cancel_job` 只改状态；已 RUNNING 的作业会继续执行完，且 `_process_job` 结束时会把状态覆盖成 COMPLETED——CANCELLED 只对尚未被 worker 取到的作业可靠。
- Redis 模式下重启后 PENDING 作业仍在队列里会被继续消费；内存模式下重启即丢。
- `_find_database` 的启发式（build/data、data、tasks/<id> 等）只是 legacy 布局兜底，新代码应依赖 C++ 任务记录。
- 进度回调用 `asyncio.create_task` fire-and-forget 更新状态（:145-150、:244-249），顺序不保证——progress 可能瞬时回跳一次，轮询端要做单调显示处理。
- `_process_single_file` 用 `get_files(limit=1, offset=file_id-1)` 定位文件（:619-620），假定 files.id 连续且从 1 开始；对删除过行的库可能取错文件。
- `queue_event_sync` 在内存模式把 events 挂到 `self._jobs[job_id]._events`（:412），而 `IngestionJob` dataclass 未声明该字段——依赖 Python 动态属性，重构成 slots 会炸。
- Redis 队列语义：LPUSH+RPOP 是 FIFO；worker 崩溃在 RPOP 与处理之间会丢一条信封（作业本体仍在 job:{id}，但永远 PENDING）——重提交即可，属于已知取舍。

## 7. 如何验证（python_service/tests/unit/）

- `test_ingestion_analyzed_only.py`（ANALYZED_ONLY 模式：跳过未分析、事件过滤、结果统计）、`test_graphiti_integration_fixes.py`（episode 契约）、`test_d4b_graphiti_cleanup.py`（任务图删除边界）、`test_startup_reliability.py`（ServiceManager 初始化预算/回滚）。
- 手工链路：`POST /api/graphiti/ingest {"task_id","mode":"analyzed_only"}` → `GET /api/graphiti/jobs/{job_id}`（Redis 模式 `redis-cli HGETALL job:{id}` 可直接看）→ 终态后 `GET /api/graphiti/graph?task_id=` 应看到实体而非只有 File 节点。

## 8. 二轮深化 A：Redis 键空间契约（字段级）

| 键 | 类型 | 字段/语义 | TTL |
|---|---|---|---|
| `job:{job_id}` | HASH | 14 字段：job_id、task_id、mode（枚举 value）、status、progress(int)、current_phase、created_at、started_at、completed_at、error、result（JSON 串）、file_id、events_count | **无 TTL**——作业历史永驻，需运维清理 |
| `ingestion_queue` | LIST | 元素为小信封 JSON `{job_id, task_id, mode}`（LPUSH 进 / RPOP 出 = FIFO） | 无 |
| `job_events:{job_id}` | STRING(?) | EVENTS_ONLY 的完整 events 载荷（入队时暂存，worker 取走） | 3600s（:406-412） |

`_save_job`（_manager.py:210-247）的两层转换规则：**None 字段直接剥离**（HSET 不收 None——意味着 started_at/completed_at/error/result 未赋值时键不存在，HGETALL 读回后 dataclass 用默认值补）；dict/list 序列化为 JSON 字符串（`ensure_ascii=False, default=str`）。`_load_job`（:249-269）的反向规则：mode/status 字符串经 `IngestionMode(...)`/`JobStatus(...)` 复原成枚举；result 尝试 `json.loads`，**坏 JSON 静默置 None**（TypeError/JSONDecodeError 双捕获）——手改过 Redis 里的 result 后作业会"丢失结果"但不报错。`IngestionJob(**data)` 用 dict 直接构造：多一个未知字段会 TypeError，因此**禁止往 HSET 手工加字段**。

## 9. 二轮深化 B：五模式 × 图产物对照表

| 模式 | :File 实体 | 事件挂载 | MENTIONED_IN 边 | 去重 | path-A episode |
|---|---|---|---|---|---|
| FULL | batch_ensure_files（全量） | attach_events_batch | ✓ | merge_duplicate_files | ✓（全部有描述的文件） |
| FILES_ONLY | ✓ | ✗ | ✓ | ✓ | ✗（worker :232-258，到 reading/processing 即止） |
| EVENTS_ONLY | ✗ | events 载荷直挂（来自 job_events 暂存） | ✗ | ✗ | ✗ |
| SINGLE_FILE | 单文件（file_id 定位） | ✗ | ✓ | ✗ | ✗ |
| ANALYZED_ONLY | 仅 analyzed 文件 | ✓ | ✓ | ✓ | ✓（仅 file_descriptions 非空者） |

对照含义：前端 `/graph` 看到的"实体+关系"来自 path-A（FULL/ANALYZED_ONLY 才有）；只跑 FILES_ONLY 会得到"纯 File 节点森林"。EVENTS_ONLY 是唯一不建 File 实体的模式（事件挂到已有 File 上，库中无 File 时事件无处可挂——作业会统计 attached=0）。

## 10. 二轮深化 C：进度区间全表（worker 实测写入值）

| 区间 | 模式 | 阶段 |
|---|---|---|
| 5-10 | FULL/ANALYZED_ONLY | reading_databases |
| 10-? | FULL | creating_file_entities（批次推进） |
| 80 | FULL | attaching_events |
| 85 | FULL | linking_entities |
| 90 | FULL | deduplicating_files |
| 92-95 | 有 path-A 的模式 | episode 摄取（`_ep_progress` 把阶段消息里的 "X/Y" 线性映射进区间，:556-566） |
| 100 | 全部 | 终态 COMPLETED |

FILES_ONLY/SINGLE_FILE 等短路径的阶段值更稀疏（10/processing 后直接 100）。前端若做进度条，注意 80→85→90 的跳跃只在 FULL 出现；progress 可能因 fire-and-forget 更新瞬时回跳（第 6 节已记录），显示层应取 max。

## 11. 二轮深化 D：新走读——Redis 模式下 worker 崩溃的队列窗口（已知取舍的边界）

```python
# _worker.py:35-53 的关键两步
item = await self._redis.rpop("ingestion_queue")   # ① 信封出队
...
await self._process_job(queue_data)                 # ② 处理（标 RUNNING）
```

逐块解释丢失窗口：①与②之间（或②内部标 RUNNING 前）进程崩溃——信封已从 LIST 移除、作业本体还停在 `job:{id}` 的 PENDING；重启后没有任何机制会重新入队（worker 只消费 LIST，不扫描孤儿 PENDING）。这与第 6 节"重提交即可"的记录一致，但值得补齐精确边界：**只要 `_process_job` 已把状态写成 RUNNING，重启后作业同样无人接手**——恢复扫描在本管理器里不存在（对比：SecondaryAnalysis/ReportGeneration 执行器都有 recover_stale_*，本管理器没有）。补齐方向（如需）：initialize 时 `scan_iter("job:*")` 找 PENDING/RUNNING 行重新 LPUSH——注意幂等（避免与仍在跑的进程双跑，需要借 Neo4j 侧幂等或分布式锁）。另一个事实：内存模式的 worker 不会丢作业（重启即整体丢失，无窗口概念）。

## 12. 二轮深化 E：配置影响表

| env | 字段 | 默认 | 消费点 |
|---|---|---|---|
| REDIS_URL | redis_url | redis://localhost:6379 | from_url（connect 5s / 命令 30s / 健康检查 30s） |
| NEO4J_URI/USER/PASSWORD | neo4j_* | 本地默认 | FileEntityIngestor 等组件构造 |
| NEO4J_CONNECT_TIMEOUT / NEO4J_QUERY_TIMEOUT | 5.0 | 组件驱动参数 | |
| GRAPHITI_BATCH_SIZE | graphiti_batch_size | 50 | path-A 的 episode 批 |
| GRAPHITI_MAX_RETRIES | 3 | 组件重试 | |
| （无专属 env） | worker 节奏 | 每周期 ≤100 条 / 空转 sleep(1)s | 硬编码 _worker.py:44、:52 |

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
