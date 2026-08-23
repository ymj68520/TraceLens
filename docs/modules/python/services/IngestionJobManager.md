# IngestionJobManager（python_service/httpserver/services/ingestion_job_manager.py + ingestion_job_models.py + ingestion_job_parts/）

> **一句话**：图谱摄取的后台作业队列——单个 `asyncio` worker 消费 `ingestion_queue`，作业状态 PENDING/RUNNING/COMPLETED/FAILED/CANCELLED 持久化到 Redis（`REDIS_URL`，不可用回退内存 dict），五种模式 FULL/FILES_ONLY/EVENTS_ONLY/SINGLE_FILE/ANALYZED_ONLY 分别把文件实体、事件、MENTIONED_IN 边与 path-A episode 写进 Neo4j。

## 1. 为什么有这个模块

Graphiti 摄取是长任务（一个任务几万文件 + LLM 抽取），不能挂在 HTTP 请求里。系统需要：**持久化的作业状态**（前端轮询、进程重启后状态不丢）、**可选的基础设施**（Redis/Neo4j 缺席时服务仍要起来并优雅降级）、以及**两条摄取路径的合流**——path-B（`FileEntityIngestor` 直接建 `:File` 节点）与 path-A（`GraphitiService.ingest_task_episodes` 走 add_episode 让 LLM 建实体关系图，前端可视化的正是后者）。IngestionJobManager 把这三件事集中在一个 mixin 组合的服务里，路由层不必关心存储与降级。

## 2. 在系统中的位置

- **谁调用它**：routes/graphiti_endpoints（手动 Ingest 按钮优先走本管理器，失败才回落 GraphitiService 的旧式内存作业，_ingest.py:60-77）；ServiceManager 启动序列在其 initialize 上给 12s 可选服务预算（service_manager.py:213-223）。
- **它调用谁**：Redis（`redis.asyncio`，作业哈希 + 队列 + 事件暂存）；graphiti_integration 的 `FileEntityIngestor` / `EntityRelationBuilder` / `ForensicsDatabase` / `EventsDatabase`（path-B 直写 Neo4j）；`GraphitiService.ingest_task_episodes`（path-A，经 service_manager 反查）；CppBackendService（任务数据库路径的权威来源）。
- **结构**：`ingestion_job_manager.py` 只是组装壳 + 兼容 re-export；实现在 `ingestion_job_parts/_manager.py`（生命周期/持久化/队列与状态 API）与 `_worker.py`（后台 worker 与各模式处理）；数据类在 `ingestion_job_models.py`。

## 3. 核心概念与设计

**（a）作业模型（ingestion_job_models.py）。** `IngestionMode`：FULL/FILES_ONLY/EVENTS_ONLY/SINGLE_FILE/ANALYZED_ONLY（:13-19，最后一项"只摄取 AI 已分析文件"）；`JobStatus`：PENDING/RUNNING/COMPLETED/FAILED/CANCELLED（:22-28）；`IngestionJob` dataclass 带 progress/current_phase/started_at/completed_at/error/result（:31-48）。状态迁移由 `_update_job_status` 集中落时间戳（_manager.py:296-301）。

**（b）Redis 持久化 + 内存回退。** `initialize`（_manager.py:62-155）先 `aioredis.from_url(settings.redis_url)`（默认 `redis://localhost:6379`，config.py:187），带 5s 连接/30s 命令超时与 30s 健康检查（:70-82 注释解释了为何不用 BRPOP：阻塞读会撞 socket 超时）；ping 失败即 `_use_redis=False` 落内存 dict，**永远不抛**。存储形态：每作业一个 `job:{id}` HSET（None 剥离、dict/list 序列化为 JSON，:210-247），队列是 `ingestion_queue` LIST（LPUSH 进/RPOP 出），EVENTS_ONLY 的载荷暂存 `job_events:{id}`（TTL 3600s，:406-412）。读回时恢复枚举与 result dict（:249-269）。`list_jobs` 在 Redis 模式用 `scan_iter(match="job:*")`（:491-505）。

**（c）降级的 Neo4j 组件装载。** `initialize` 第二步把 `python_service/`（本文件 `parents[3]`）插入 sys.path 后导入 graphiti_integration 组件——注释记录了历史上 `parents[3]` 误算成 `httpserver/` 导致启动脚本忘了 PYTHONPATH 时静默 ImportNotFound 的教训（:93-107）。任何失败都只降级（`_file_ingestor is None`），worker 照常启动（:151-153）；各模式处理函数开头检查组件并把作业标 COMPLETED 附 `"Neo4j not available"` 说明（如 _worker.py:112-117）。

**（d）Worker 循环（_worker.py:29-74）。** Redis 模式：非阻塞 RPOP 循环，单周期上限 100 条保持响应性，队列空 sleep(1)；内存模式：每秒扫一次 PENDING，**一次只处理一条**。`_process_job`（:76-107）是状态机骨架：标 RUNNING → 按 mode 分发 → COMPLETED(progress=100)；任何异常标 FAILED 并存 error。

**（e）FULL 模式的五步（:109-220）。** 读库（`_resolve_task_database` :776-795 **优先 C++ 任务记录的 output_*_db**，找不到才走 `_find_database` 的文件系统启发式 :797-856）→ `batch_ensure_files` 建文件实体（进度回调做了百分比去抖，避免几十万次 HSET，:138-150）→ `attach_events_batch` 挂事件 → `_create_mentioned_in_edges` → `merge_duplicate_files` → path-A episode 摄取。`_create_mentioned_in_edges`（:635-735）的 docstring 记录了一个被修复的老 bug：旧实现试图从 episode 名恢复文件路径再哈希，但 episode 名是本地化的（"文件分析: /path"）且事件簇 episode 根本没有路径，导致 `mentioned_in_edges_created` 恒为 0；现在从 File 记录按 basename 建映射，另有 `_link_entities_to_files_by_name`（:737-774）用一条参数化 UNWIND MERGE 把"实体名 == 文件名"的强取证信号连上。

**（f）ANALYZED_ONLY 与 path-A。** `_process_analyzed_only`（:307-435）只取 `iter_files_batched(analyzed_only=True)` 的文件走同套流程。`_ingest_episodes_path_a`（:437-601）从 `_files.db` 读 file_descriptions 并 **JOIN files 表带上 category/md5/name/size**（注释：默认 JSON prompt 会丢掉这些高价值抽取信号，:486-489），text_factory 兜底 GBK 文件名（:476-485）；事件簇分析按 `(event_type, minute)` 去重读出；全部喂给 `GraphitiService.ingest_task_episodes`，进度映射到 92-95% 区间。此路径**失败非致命**——path-B 的 :File 节点仍然有效。

## 4. 工作流程走读：一次手动摄取

`POST /api/graphiti/ingest`（路由优先选 job manager）→ `queue_ingestion(task_id, mode)`（_manager.py:307-341）：生成 `job_{uuid16}` → 保存 HSET → `LPUSH ingestion_queue` → 返回 job_id → worker RPOP → `_process_job` 标 RUNNING("starting") → FULL 五步逐步更新 phase/progress → COMPLETED → 前端轮询 `get_job_status`（:425-451）读 HSET 直至终态。`cancel_job`（:453-472）只允许取消非终态作业，把状态改 CANCELLED——正在执行中的作业不会被中断，worker 完成后仍会尝试写入状态（见第 6 节）。

## 5. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| GraphitiService | path-A 的最终执行者（ingest_task_episodes）；其 `_jobs.py` 旧式内存作业是本管理器的回退 |
| graphiti_integration | FileEntityIngestor/EntityRelationBuilder/数据库读取器（path-B） |
| CppBackendService | 任务库路径的信任源（D2b） |
| ServiceManager | 12s 可选初始化预算；shutdown 会 cancel worker 并关闭组件连接 |
| routes/graphiti_endpoints | 队列入口与状态/取消/列表端点 |

## 6. 注意事项与已知问题

- **cancel 不是抢占**：`cancel_job` 只改状态；已 RUNNING 的作业会继续执行完，且 `_process_job` 结束时会把状态覆盖成 COMPLETED——CANCELLED 只对尚未被 worker 取到的作业可靠。
- Redis 模式下重启后 PENDING 作业仍在队列里会被继续消费；内存模式下重启即丢。
- `_find_database` 的启发式（build/data、data、tasks/<id> 等）只是 legacy 布局兜底，新代码应依赖 C++ 任务记录。
- 进度回调用 `asyncio.create_task` fire-and-forget 更新状态（:145-150、:244-249），顺序不保证——progress 可能瞬时回跳一次，轮询端要做单调显示处理。
- `_process_single_file` 用 `get_files(limit=1, offset=file_id-1)` 定位文件（:619-620），假定 files.id 连续且从 1 开始；对删除过行的库可能取错文件。
- `queue_event_sync` 在内存模式把 events 挂到 `self._jobs[job_id]._events`（:412），而 `IngestionJob` dataclass 未声明该字段——依赖 Python 动态属性，重构成 slots 会炸。

## 7. 如何验证（python_service/tests/unit/）

- `test_ingestion_analyzed_only.py`（ANALYZED_ONLY 模式：跳过未分析、事件过滤、结果统计）、`test_graphiti_integration_fixes.py`（episode 契约）、`test_d4b_graphiti_cleanup.py`（任务图删除边界）、`test_startup_reliability.py`（ServiceManager 初始化预算/回滚）。
- 手工链路：`POST /api/graphiti/ingest {"task_id","mode":"analyzed_only"}` → `GET /api/graphiti/jobs/{job_id}`（Redis 模式 `redis-cli HGETALL job:{id}` 可直接看）→ 终态后 `GET /api/graphiti/graph?task_id=` 应看到实体而非只有 File 节点。

**最后更新**: 2026-08-23（新建，解释式）
