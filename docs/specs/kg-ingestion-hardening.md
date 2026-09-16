# SPEC: KG 读路径与摄取并发加固（KG Ingestion Hardening）

- 状态：已评审锁定，实施中（Phase A–C，2026-09-16）
- 来源：2026-09-15 GUI 黑盒实测发现"KG 页首载 46 秒、UI 无进度提示"；2026-09-16 复现实验修正了归因
- 分支：直接在 Dev 上实施（与 feature/file-analysis-redesign 有少量同文件重叠，合并时按本 SPEC 为准）

## 0. 复现实验结论（归因修正）

当晚假设"graphiti 摄取并发争用拖慢读路径"**不成立**。2026-09-16 在活服务上实测：

| 场景 | /status | /graph | /tasks |
|---|---|---|---|
| 空闲 | 8–22ms | 8–20ms | 5–112ms |
| 后台真实 add_episode 摄取 + LM Studio 双路 chat 打满 | 15–32ms | 7–23ms | 5–12ms |

即：**Neo4j 写并发与 LM Studio 饱和都不会拖慢 KG 读端点**。46 秒量级的首载冻结只能来自
uvicorn 单事件循环上的同步阻塞段。已定位的阻塞点：

1. `_worker.py::_ingest_episodes_path_a` 在事件循环上同步 `sqlite3.connect(timeout=10)` +
   整表 `fetchall()`（files+events 两库）。当晚 C++ 对同批库高并发写（日志有
   `database is locked`），每次读可能 busy-wait 最长 10s——唯一能解释 46s 的机制。
2. 摄取本身极慢且不可见：单 episode `add_episode` 实测 **309s**（4–7 个串行 LLM 调用，
   本地单模型排队），管线 KG 阶段内联 `await`（`_pipelines.py` 两处）会挂住管线数小时，
   前端无任何进度。
3. 读路径无超时（`/graph`、`/tasks`）、每请求新建 Neo4j driver、计数查询按 MENTIONS
   展开逐行探测、`list_task_graphs` 每次全表扫描——平时毫秒级，但没有任何护栏。
4. 三条摄取流（管线内联 KG、job worker、reanalyze 的 fire-and-forget `create_task`）
   可对同一 group 并发 `add_episode`——graphiti 设计假设组内串行，并发会去重竞态
   （重复实体）+ 放大 LM Studio 排队。

## 1. 决策

- **A1**：worker 的整表 SQLite 读移出事件循环（`asyncio.to_thread`），这两个连接的
  busy_timeout 10s→2s（快速失败优于冻结）。其余小型同步 SQLite 写（如
  `persist_to_files_db`，WAL + 毫秒级）本期不动，记为已知余留。
- **A2**：读路径统一收敛：GraphitiService 持有**共享 Neo4j driver 单例**；所有读查询
  套 `asyncio.wait_for(neo4j_query_timeout)`；计数改索引直查
  （`Entity {group_id}` / `RELATES_TO {group_id}`，索引已存在）。
  *语义注记*：/status 计数从"按 MENTIONS 从该组 episode 可达"变为"该组直接标注的
  节点/边"，数值可能略大（含跨组共享实体），是更准确的"该组图规模"。
- **A3**：`list_task_graphs` 结果缓存 5s。
- **B1**：按 group_id **单飞锁**（keyed `asyncio.Lock`，宿主 GraphitiService），包裹所有
  `add_episode` 批量摄取区段（管线内联路径、worker Path-A、reanalyze 路径）。
- **B2**：管线 KG 阶段不再内联 `await`：改为经 `IngestionJobManager` 投递 **kg_sync job**
  （新增 mode），job 内复用现有 `ingest_to_knowledge_graph` + `batch_ingest` 原生的
  `progress_callback`；job manager 不可用时回退现行为。管线返回
  `knowledge_graph: {queued: true, job_id}`（已核实 C++/前端均不消费该字段，安全）。
  摄取数据仍取自管线在手的新鲜结果（描述 + 真实簇分析），不经 DB 回读。
- **B3**：KG 页显示摄取进度：挂载/换任务时查 `GET /jobs?task_id=`，有活动 job 则横幅
  显示进度与阶段，2s 轮询；完成/失败后刷新 status 与图数据。

## 2. 禁改红线

- http_agent `--no-ai` 不变量（client never runs the LLM）不受影响（本 SPEC 不触 C++）。
- `add_episode` 的串行语义保持组内一次一个（batch_ingest 内部循环不改并发度）。
- 事件簇 SPEC（78d1109）与文件分析 SPEC 的 append-only 约定不受影响；本 SPEC 不改任何
  分析记录表。
- job 体系公开 API（queue_ingestion / GET /jobs…）签名不变，只做增量。

## 3. 阶段

- **Phase A（P0）**：A1 → worker to_thread + busy_timeout 2s。验收：单测证明读取经
  to_thread、行解析正确；focused 回归绿。
- **Phase B（P1）**：A2 + A3 → driver 单例、全读路径超时、索引直查计数、列表缓存。
  验收：单测（driver 复用、缓存、计数查询形状）；活服务 /status /graph /tasks 计数与
  旧实现同量级。
- **Phase C（P2）**：B1 + B2 + B3 → 单飞锁、管线投递 kg_sync job、KG 页进度横幅。
  验收：单测（锁串行化、job 状态机、管线 queued 返回）；web lint/build 绿。

## 4. 实施记录

- **Phase A**（已提交）：`_worker.py` 新增模块级 `_read_episode_source_rows`（busy_timeout=2），
  `_ingest_episodes_path_a` 经 `asyncio.to_thread` 调用；测试
  `tests/unit/test_worker_episode_rows_offloop.py`（6 用例）。
- **Phase B**（已提交）：`GraphitiService` 增加共享 driver（`_get_shared_driver`）与
  `_run_read_query`（全读路径 `asyncio.wait_for` 超时）；`_query_neo4j_counts` 改索引直查；
  `list_task_graphs` 5s 缓存（delete 失效）；`shutdown` 关闭共享 driver；测试
  `tests/unit/test_graphiti_read_path_hardening.py`（8 用例）。
- **Phase C**（已提交）：单飞锁 `lock_for_group`（4 个 add_episode 入口全部包裹：
  `_ingest.py` 三处 batch、`file_analyzer.ingest_to_knowledge_graph` 直调处）；新增
  `IngestionMode.KG_SYNC` + `IngestionJobManager.queue_kg_sync_job`（自运行 job，
  RUNNING 起步避免被 worker 扫描误接）；管线两处 KG 步骤改
  `dispatch_kg_ingestion`（job manager 缺席时回退内联）；KG 页轮询 `/jobs` 显示
  摄取进度横幅，job 结束自动刷新计数与图；测试
  `tests/unit/test_kg_ingestion_dispatch.py`（8 用例）；web lint 无新增（8 项均为
  Dev 存量基线）、vite build 通过。
- 合计 92 用例（新增 22 + graphiti 回归 70）全绿。

### 已知余留

- 小型同步 SQLite 写（`persist_to_files_db` 等，WAL 毫秒级）仍在事件循环上（A1 明确不动）。
- 单 episode 约 5 分钟的摄取量级由模型速度决定，本 SPEC 只保证其可见与可控
  （进度横幅、单飞、管线不阻塞）。若需根治，另行评估给 graphiti 抽取单独配小模型。
- 事件库簇源仍读 events.llm_description 旧缓存列（事件簇 SPEC 的
  event_cluster_analyses 真源接入由文件分析 SPEC P1 在其分支上完成，合并后即覆盖）。
