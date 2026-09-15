# SPEC：事件簇分析重构（Event Cluster Analysis Redesign）

> **状态**：已评审锁定并实施完毕（2026-09-15，Phase B1/B2/C/D 全部落地）。锁定决策已由实现代码、[schema/EventsDB.md](../schema/EventsDB.md) 与 API 参考（[Python](../api_reference/Python_REST_API.md) / [C++](../api_reference/CPP_REST_API.md)）接管；本文档转为过程存档。
> **范围**：事件簇的聚簇、分析、存储、判定、检索、图谱摄入全链路。
> **性质**：与 `docs/hardening/` 同属过程规范文档，不随代码同步更新。
> **遗留**：仓库级全量测试（`make test` / `make test-python` 全量）按计划在全部阶段完成后统一执行；回填脚本 `backfill_cluster_analyses.py` 为对既有任务 events 库的一次性可选操作。
> **分支**：Dev 工作区。

---

## 0. 背景与问题清单

调研确认的现状（锚点均为当前代码位置）：

1. **聚簇时间三处定义不一致**：初次管线硬编码 60s（`python_service/httpserver/services/case_analysis/cluster_analyzer.py:122`）；时间线页面默认 60s、UI 阶梯 60s~6h（`web/src/pages/Timeline.jsx:91,656-664`）；后端钳制 [1, 86400]s（`src/network/HTTPServer/Queries/TimelineQueries.cpp:100-101`、`python_service/httpserver/services/investigation_evidence.py:24`）。
2. **聚簇 SQL 三处重复**：`TimelineQueries.cpp:132-138`、`investigation_evidence.py:113-116`、`cluster_analyzer.py:126-129`。历史上已因重复实现出过一次分组 bug（`TimelineQueries.cpp:126-131` 注释）。
3. **分析结果不是一等实体**：只以 per-event `llm_*` 列存在（每事件一份、后写覆盖先写），导致：无历史、无版本、"是否已分析"只能靠裸列猜测、Graphiti 无法引用。
4. **"是否已分析"有盲区**：时间线聚合查询中 `llm_summary` 等是 GROUP BY 裸列（`TimelineQueries.cpp:174-177`），SQLite 从组内任意一行取值；前端以 `!event.llm_summary` 判未分析（`Timeline.jsx:271`），换 bucket 后合并簇可能带旧摘要被跳过。
5. **超大簇截断**：管线 prompt 取前 10 条（`cluster_analyzer.py:235-238`），路由取前 50 条（`routes/llm_endpoints/_analysis.py:78-81`）。对证据分析而言采样不可接受。
6. **入口缺口**：单镜像分析入口已退役（`POST /api/llm/case-analysis` 410，`routes/case_analysis_endpoints/_case.py:80-93`；前端 `startCaseAnalysis` 为 throw stub，`web/src/services/caseAnalysisService.js:33`）；活入口仅案件级三端点（`routes/multi_analysis.py:220/322/360`）与时间线 auto-analyze。`events_db` 缺失时簇分析被静默跳过（`case_analysis_parts/_pipelines.py:162-167`）。
7. **C++ 遗留端点未清**：`/clusters/analyze` 410 占位；`/clusters/reanalyze`、`/clusters/batch` **仍是活的 C++ LLM 路径**（`src/network/HTTPServer/routes/EventClusterRoutes.cpp:94-216`），绕过 Python 侧全部护栏。
8. **Graphiti 摄入不一致**：初次管线分析后摄入；时间线单簇分析只落库不摄入。
9. **"已分析簇"页固定 60s + MAX() 聚合**（`EventClusterRoutes.cpp:243-261`，消费方 `web/src/pages/AnalysisCenter.jsx:126`），与实际分析 bucket 脱节。

## 1. 术语与坐标

| 术语 | 定义 |
|---|---|
| **聚簇坐标** | 五元组 `(bucket_epoch_offset, bucket_seconds, bucket_index, event_type, parent_directory)`，全局唯一确定一个簇分组 |
| **bucket_seconds** | 聚簇时间窗宽（秒） |
| **bucket_index** | `(timestamp − bucket_epoch_offset) / bucket_seconds`（整数除法，向零截断） |
| **bucket_epoch_offset** | 时间窗本地对齐偏移（秒），见 §4.2 |
| **分析记录（analysis）** | `event_cluster_analyses` 表一行，一次 LLM 分析的完整结果，**append-only** |
| **运行（run）** | `cluster_analysis_runs` 表一行，一次批量分析执行（管线或任务级入口），含预算与统计 |
| **最新版本** | 同一聚簇坐标下 `id` 最大的分析记录 |
| **stale** | 最新版本的成员指纹与当前成员集不一致（新事件落入了同一窗） |
| **成员** | 满足聚簇坐标的 events 表行 |
| **trigger_source** | 分析来源枚举：`pipeline` / `timeline_auto` / `timeline_manual` / `task_run` / `migrated` |

## 2. 锁定的设计决策

以下决策已在评审中拍板，实施阶段**不得擅改**；确需变更走 SPEC 修订。

| # | 决策 | 理由 |
|---|---|---|
| D1 | 新建 `event_cluster_analyses`（append-only）与 `cluster_analysis_runs` 表，分析结果成为一等实体 | 解开历史/版本/判定/检索/图谱引用五个问题 |
| D2 | per-event `llm_*` 列**保留，双写**：作为展示缓存与管线跳过标记；真相源为 analyses 表 | 前端展示零迁移；初次管线"只析 NULL"原设计保留（D9） |
| D3 | 初次分析聚簇时间**预算驱动自适应**：候选阶梯扫描 + 簇数预算 B；B 代码默认 200，部署配置文件设 1500 | LLM 成本单位是簇数；预算可控且全覆盖 |
| D4 | 协议层 bucket_seconds 上限放宽至 **2592000（30 天）**，Python 校验与 C++ clamp 同步；时间线 UI 阶梯保持 ≤21600 | 单一上限保证时间线可复现任意 run 的分组 |
| D5 | **时间窗本地对齐**本期必须完成：`bucket_epoch_offset` 在 events 库创建时由 C++ 计算写入，所有 bucket 表达式统一使用 | 用户要求，不遗留 |
| D6 | 超大簇**不采样**，全量 map-reduce：每成员必进入至少一个 chunk 的 LLM 输入 | 分析结论作为证据不得丢失事件 |
| D7 | "是否已分析" = 存在同坐标且成员指纹一致的分析记录；**stale 只标记 + 人工重析，不自动重析** | 避免新事件静默触发昂贵 LLM |
| D8 | 手动分析/重析不做任何已分析判断，总是追加新版本，`analysis_id_upstream` 形成版本链 | 侦查员显式行为优先 |
| D9 | 初次管线跳过判据保持 `llm_analyzed_at IS NULL` 原设计；失败簇不写标记，留给下次重跑 | 评审确认保留 |
| D10 | 时间线单簇分析**必须摄入 Graphiti**，与管线共用同一摄入函数；`ingested_at` 做幂等状态；摄入失败只告警不回滚 | 摄入是锦上添花，不得阻断落库 |
| D11 | C++ 三个簇分析端点（analyze/reanalyze/batch）及 `EventClusterAnalyzer` 注释退役；`GET /clusters/analyzed` 保留至 Phase D 换数据源 | 清理绕过护栏的遗留面 |
| D12 | 调查证据簇 key（`cluster:v1:{minute}:{type}`）**明确不动** | 已持久化证据引用的稳定性优先 |
| D13 | 聚簇 SQL 收敛：Python 以 `investigation_evidence.py` 为规范源；C++ 保留原生实现 + 双端金测试 | 无法跨语言共享代码，用一致性测试锁死 |

## 3. 数据模型规范

### 3.1 新表 DDL（权威版本，双端逐字一致）

SQLite 保留字注意：不用 `trigger` 作列名（用 `trigger_source`）。

```sql
CREATE TABLE IF NOT EXISTS event_cluster_analyses (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id              TEXT    NOT NULL,
    bucket_epoch_offset  INTEGER NOT NULL DEFAULT 0,
    bucket_seconds       INTEGER NOT NULL,
    bucket_index         INTEGER NOT NULL,
    event_type           TEXT    NOT NULL,
    parent_directory     TEXT    NOT NULL,
    member_count         INTEGER NOT NULL,
    member_min_id        INTEGER NOT NULL,
    member_max_id        INTEGER NOT NULL,
    members_hash         TEXT    NOT NULL,
    summary              TEXT    NOT NULL DEFAULT '',
    description          TEXT    NOT NULL DEFAULT '',
    keywords             TEXT    NOT NULL DEFAULT '',
    model                TEXT    NOT NULL DEFAULT '',
    trigger_source       TEXT    NOT NULL,
    analysis_id_upstream INTEGER,
    created_at           INTEGER NOT NULL,
    ingested_at          INTEGER
);
CREATE INDEX IF NOT EXISTS idx_eca_coord
    ON event_cluster_analyses(task_id, bucket_epoch_offset, bucket_seconds,
                              bucket_index, event_type, parent_directory);
CREATE INDEX IF NOT EXISTS idx_eca_task_time
    ON event_cluster_analyses(task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS cluster_analysis_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id             TEXT    NOT NULL,
    trigger_source      TEXT    NOT NULL,
    bucket_seconds      INTEGER,
    bucket_epoch_offset INTEGER NOT NULL DEFAULT 0,
    budget              INTEGER,
    status              TEXT    NOT NULL DEFAULT 'running',
    cluster_total       INTEGER,
    cluster_failed      INTEGER,
    map_calls           INTEGER,
    reduce_calls        INTEGER,
    model               TEXT,
    started_at          INTEGER NOT NULL,
    finished_at         INTEGER,
    detail              TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_car_task ON cluster_analysis_runs(task_id, started_at DESC);

CREATE TABLE IF NOT EXISTS analysis_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

### 3.2 字段语义与不变量

- **append-only**：`event_cluster_analyses` 只允许 INSERT；唯一允许的 UPDATE 是把 `ingested_at` 从 NULL 改为时间戳（Graphiti 摄入状态机）。任何其他 UPDATE/DELETE 都是 bug。
- **成员指纹三件套**：`member_count / member_min_id / member_max_id`（SQL 可算，供 C++ JOIN 判 stale）；`members_hash = sha256(",".join(str(i) for i in sorted(member_ids)))` 的 hex（Python 侧强校验，`read_timeline_group_members` 取回成员后计算）。
- **最新版本**：同坐标 `MAX(id)`。版本链经 `analysis_id_upstream` 回溯，不维护序号列。
- **真相源与缓存**：分析成功 = 写入 analyses 一行 **且** 覆盖写簇内全部成员的 `llm_summary/llm_description/llm_keywords/llm_analyzed_at/llm_model_used/llm_is_relevant`。两步必须同成功同失败（先 analyses 后 events，events 更新沿用现有 rowcount 严格校验；analyses 写失败则整体失败不写 events）。
- **analysis_meta 键**（C++ 创建 events 库时写入，Python 只读）：
  - `bucket_epoch_offset`：见 §4.2。缺表或缺键 = 0（兼容存量库）。
- **schema 创建**：双端各自幂等 ensure（`CREATE TABLE IF NOT EXISTS`，模式沿用 `TimelineQueries.cpp:88-93` 的启动期 ALTER 惯例）。Python 侧集中在 `services/case_analysis/schema.py::ensure_cluster_analysis_schema(events_db)`，由 ClusterAnalyzer 入口、analyze-event-cluster 路由、回填脚本调用；C++ 侧在 timeline 查询入口 ensure。双端 DDL 必须与本节逐字一致（金测试校验，见 §4.4）。

### 3.3 存量数据回填

- 提供一次性脚本 `python_service/scripts/backfill_cluster_analyses.py`（幂等：已有 analyses 行的任务跳过）。
- 规则：从 per-event `llm_*` 按 `bucket_seconds=60, offset=0` 重建，`trigger_source='migrated'`，成员指纹按当前成员重算，`analysis_id_upstream=NULL`。
- 理由：历史时间线分析的真实 bucket 不可考，60s 是唯一可辩护的重建粒度；hash 失配的行诚实呈现为 stale。
- 回填是推荐步骤而非硬依赖：未回填的旧任务在时间线上会被判"未分析"并重析一次（诚实行为，成本一次性）。

## 4. 聚簇表达式规范（唯一权威定义）

### 4.1 规范表达式

**分组键三元组**：`(父目录, (timestamp − offset) / bucket_seconds, event_type)`。

父目录表达式（现行正确实现，保持不变）：

```sql
(CASE WHEN file_path LIKE '%/%'
      THEN RTRIM(file_path, REPLACE(file_path, '/', ''))
      ELSE '' END)
```

时间窗表达式：`((timestamp - {offset}) / {bucket_seconds})`，整数除法向零截断（SQLite/C++ 一致）。`offset`、`bucket_seconds` 必须来自服务端解析的整数，禁止字符串拼接用户输入以外的任何内容。

**规范源**：`investigation_evidence.py` 新增帮助函数（如 `bucket_expr(offset, seconds)` 与父目录常量），Python 两处消费（`read_timeline_group_members`、`cluster_analyzer.fetch_event_clusters`）一律引用；C++ `TimelineQueries.cpp` 保持原生拼接但表达式语义必须与规范源一致。

### 4.2 bucket_epoch_offset（时间窗本地对齐）

- **计算**：`offset = (86400 − (tz_offset_seconds mod 86400)) mod 86400`，其中 `tz_offset_seconds` 为服务器本地时区相对 UTC 的偏移（东八区 = 28800 → offset = 57600）。
- **写入时机**：C++ 创建 events 库时写入 `analysis_meta`（新任务从诞生起对齐；存量库缺省 0，行为不变）。
- **使用规则**：所有 bucket 表达式（管线取数、时间线 comprehensive/details、成员读取、analyses 坐标）统一使用任务库 meta 中的 offset。**同一任务的 offset 永不变更**（写一次）。
- **坐标换算**：`bucket_start_timestamp = bucket_index × bucket_seconds + bucket_epoch_offset`（offset=0 时退化为既有语义）；描述符提供的 `bucket_start_timestamp` 必须与该式一致，否则拒绝。
- **嵌套性**：所有 bucket 尺寸复用同一 offset，保证窗口嵌套（小时窗永不跨两个本地日窗；小时窗自动对齐本地整点）。
- **DST**：不建模，固定偏移。设置文档须声明（中国时区无 DST，主场景安全）。
- **负时间戳/零时间戳**：向零截断语义与现状一致；timestamp=0 的堆积事件落在 offset 附近的桶，行为可预期即可，不特判。

### 4.3 bucket_seconds 界限（D4）

- 协议层单一上限：**1 ≤ bucket_seconds ≤ 2592000**。`investigation_evidence.py` 的 `TIMELINE_MAX_BUCKET_SECONDS` 与 `TimelineQueries.cpp:101` 的 clamp 同步改为 2592000。
- UI 阶梯（`Timeline.jsx` 选项与 `autoBucketForSpan`）保持 ≤21600，不因协议上限放宽而变。
- 描述符校验（`validate_timeline_group_descriptor`）上限同步 2592000；旧描述符（无 offset 字段）合法，offset 缺省 0。

### 4.4 金测试（D13 验收物）

同一 fixture events 库（含正常行、timestamp=0 行、同目录多类型行、大窗跨天行），断言：
1. Python 规范源分组坐标 ≡ C++ comprehensive 分组坐标（逐行）；
2. `read_timeline_group_members` 按 descriptor 圈定的成员 id 集合 ≡ C++ 同坐标分组行所含成员（通过 details 端点）；
3. 双端 ensure-schema 后 `sqlite_master` 中两表 DDL 语义一致（列名/类型/序）。
Python 侧入 pytest，C++ 侧入 ctest，fixture 共享同一 JSON。

## 5. 自适应聚簇时间算法规范（D3）

1. **候选阶梯**（共享常量，与前端 `autoBucketForSpan` 同源收敛到一处定义）：
   `[60, 300, 900, 1800, 3600, 21600, 86400, 604800, 2592000]`。
2. **扫描**：对每个候选执行纯 SQL 聚合（无 LLM）：`簇数 = COUNT(DISTINCT 分组键)`、`最大单簇成员数`。
3. **选择**：取满足 `簇数 ≤ B` 的**最小** bucket；全部超预算则取阶梯最大值并在 run 记录与响应中显式告警。
4. **预算 B**：Settings `llm_max_event_clusters`（复用既有"有限分析上限"，避免第二个同义旋钮），代码默认 **200**，部署配置文件（`.env`/config，alias `LLM_MAX_EVENT_CLUSTERS`）设 **1500**。
5. **显式覆盖**：调用方可直接指定 bucket_seconds（合法域内），跳过自适应。
6. **dry-run 估算**：扫描结果（各候选的簇数、最大成员数、预计 map/reduce 调用数）通过估算端点暴露（§8），也是 run 的第一步骤。
7. 选中 bucket 与 offset 写入 run 记录——这是"已分析簇"页（Phase D）与可复现性的锚点。

## 6. 全量 map-reduce 分析规范（D6）

- **不采样原则**：每个事件必须进入至少一个 chunk 的 LLM 输入。现有两处截断**必须移除**：`cluster_analyzer.py:235-238` 的 `[:10]`、`_analysis.py:78-81` 的 `[:50]`。
- **chunk**：`Settings.cluster_analysis_chunk_size`，默认 200。行格式沿用紧凑格式 `- {timestamp}: {event_type} | {file_path} | {description}`；chunk 头部注明"本片为第 i/n 片，全簇共 M 条事件"。
- **map**：每 chunk 一次 LLM 调用，产出片级要点。
- **reduce**：片级摘要归并为簇结论（沿用现有四段式输出契约：简要总结/详细分析/关键词/取证价值）；片数 > 30 时按 30 份一批递归归并。并发受 `llm_max_concurrency`（正式进 `Settings`，默认 3）统一控制。
- **成本不变量**（写入设计文档与 run 统计）：`map_calls ≈ Σ ceil(成员数/CHUNK)`，与 bucket 选择基本无关；`reduce_calls ≈ 簇数`（受预算 B 约束）。
- **边界**：`MAX_CLUSTER_EVENTS_FOR_LLM=50`（`investigation_evidence.py:20`）属调查工作台证据上下文装配，**不适用本节，不动**。

## 7. "是否已分析"与 stale 判定规范（D7/D8/D9）

- **判定定义**：簇"已分析" ⇔ 存在同坐标（含 offset）的 analyses 行，且最新行成员指纹（count/min_id/max_id，SQL 侧；hash，Python 侧）与当前成员集一致。
- **时间线查询**：comprehensive 聚合查询对每簇附加 `COUNT(id)/MIN(id)/MAX(id)` 聚合与相关子查询 JOIN 最新 analyses 行，输出确定性的 `analysis_id / analyzed_at / is_stale / analysis_model`；`llm_summary/llm_description/llm_keywords` 改由该行填充（**字段名不变**，语义从"组内任意行"变为"最新分析版本"）。
- **前端自动分析**：判据 `!event.llm_summary` → `!event.analysis_id`。stale 簇**不进入**自动队列；UI 显示"成员已变化"徽标 + 人工重析按钮（徽标 UI 可落 Phase D，字段契约 Phase B2 定）。
- **手动分析/重析**：不做判定，总是追加新版本（D8）。
- **初次管线**：保持 `WHERE llm_analyzed_at IS NULL`（D9）；同时按 §5 自适应 bucket 全量覆盖（保证"所有事件都被分析过"由 run 语义保证，而非由跳过判据保证）。

## 8. API 契约

原则：**只增不改名**；旧行为的移除必须在本节登记。

### 8.1 新增（Phase C）

| 端点 | 语义 |
|---|---|
| `POST /api/llm/event-cluster-analysis/estimate` | body `{task_id}`；返回阶梯扫描表（各 bucket 的簇数/最大成员/预计 map+reduce 次数）与推荐 bucket。只读不执行 |
| `POST /api/llm/event-cluster-analysis/run` | body `{task_id, bucket_seconds?}`；省略 bucket 则自适应。后台执行（job 模式沿用 `multi_analysis.py` 的内存 job 注册表惯例），返回 `{job_id, run_id, bucket_seconds, ...}` |
| `GET /api/llm/event-cluster-analysis/run/{job_id}` | 进度/统计/失败清单 |
| `GET /api/llm/event-cluster-analyses` | query：`task_id`（必填）、`bucket_seconds`/`bucket_index`/`event_type`/`parent_directory`/`include_stale`；返回分析记录列表（含版本链字段），Phase D 的"已分析簇"页数据源 |

run 内部即"选 bucket → 全量 map-reduce → 写 analyses + 双写 → Graphiti → 统计落 run"，同时解决问题 6 的**任务级初析入口缺口**。

### 8.2 变更

- `POST /api/llm/analyze-event-cluster`（`routes/llm_endpoints/_analysis.py`）：
  - 成员装配从 `[:50]` 截断改为 §6 map-reduce；
  - 持久化从覆盖 events 改为"追加 analyses 行 + 双写 events"；
  - 落库成功后调用共享 Graphiti 摄入（§9），失败仅告警；
  - 响应增加 `analysis_id`；`group_descriptor` 支持可选 `bucket_epoch_offset`（缺省时服务端从 meta 解析，提供值与 meta 不一致 → 422）。
- `GET /api/forensics/timeline/comprehensive`（C++）：簇行新增 `analysis_id / analyzed_at / is_stale / analysis_model`；`llm_*` 字段名不变、来源变更（§7）。**此变更与前端判据切换必须同一提交锁步。**

### 8.3 退役（Phase B2，注释保留源码）

- C++：`POST /api/forensics/timeline/clusters/analyze`、`/clusters/reanalyze`、`/clusters/batch` 的路由注册、handler、Swagger 注册整体注释；`EventClusterAnalyzer` 类若无其他引用一并注释。
- C++：`GET /api/llm/case-analysis/{job_id}`（Python 侧，`_case.py:183`）——实施核实：`_analysis_jobs` 由 `_windows.py` 与 `reanalyze-files` 共享写入，前端 `getCaseAnalysisStatus` 在用，**保留该端点**；仅移除无人调用的 `run_case_analysis_background` 与前端 `startCaseAnalysis`/`pollCaseAnalysis` 死导出。
- Python：`_case.py:31` 死导入 `run_case_analysis_background`；`services/case_analysis/file_analyzer.py:628` 死方法 `analyze_event_clusters`（删前跑测试确认无引用）。
- Web：`caseAnalysisService.js` 的 `startCaseAnalysis` stub 及无人引用的导出（删前核实无 import）。
- `GET /api/forensics/timeline/clusters/analyzed` **不退役**：保留至 Phase D 切换数据源后再评估。

## 9. Graphiti 摄入规范（D10）

- **共享函数**：从 `cluster_analyzer.ingest_clusters_to_graphiti` 抽出单条分析摄入 `ingest_analysis_to_graphiti(task_id, analysis_row)`；管线批量与时间线路由共用。
- **episode 命名**：`事件簇分析: {event_type} @ {bucket_seconds}s/{bucket_index} @ {parent_directory} #a{analysis_id}`。
- **episode body**：JSON 含完整坐标、`analysis_id`、`analysis_id_upstream`、`member_count`、`created_at`、`trigger_source`、分析文本。`group_id = task_id` 不变。
- **幂等**：`ingested_at` 非空则跳过；重试安全。版本更替不删除旧 episode（证据链），读侧按 `analysis_id` 消歧。
- **失败策略**：摄入失败记日志并将 `ingested_at` 保持 NULL，不回滚落库，不阻断响应。

## 10. 前端契约与改动边界

| 文件 | 改动 | 阶段 |
|---|---|---|
| `web/src/pages/Timeline.jsx` | auto-analyze 判据 `!event.llm_summary` → `!event.analysis_id`；stale 不进自动队列；（D 期）stale 徽标与手动重析按钮 | B2（判据锁步）/ D（徽标） |
| `web/src/pages/AnalysisCenter.jsx` | `getAnalyzedEventClusters` 适配 analyses 数据源（版本链展示） | D |
| `web/src/services/forensicsService.js` | `analyzeEventCluster` 请求结构不变；新增 run/estimate/analyses 三个服务的封装 | C |
| `web/src/services/caseAnalysisService.js` | 清理死导出（§8.3） | B2 |
| `web/src/locales/en.js` / `zh.js` | 新增 stale/版本/run 相关文案键 | C/D 按需 |

## 11. 明确禁止事项（Out of Scope / 禁改清单）

1. 调查证据簇 key `cluster:v1:*` 及 `expand_timeline_group_rows` 的 `// 60` 投影（`investigation_evidence.py:48,144`，消费方 `investigation_service.py:309,417`）——不动，局限记录在案。
2. `MAX_CLUSTER_EVENTS_FOR_LLM=50`（调查工作台上下文装配）——不动。
3. per-event `llm_*` 列——不删不改名，只按 §3.2 双写。
4. 案件级三端点（multi-image / smart-create / incremental）的对外契约——不破坏；其内部经 `run_full_analysis` 获得新能力属于自然受益。
5. 初次管线 `llm_analyzed_at IS NULL` 跳过语义——保留（D9）。
6. 时间线 UI 阶梯取值——保持 ≤21600（§4.3）。
7. `GET /api/forensics/timeline/clusters/analyzed`——Phase D 前不得变更行为。
8. events 库既有表结构——只增表/索引，不改现有列。

## 12. 实施阶段划分与验收标准

> 顺序约束（评审锁定）：**B1 → B2 → C → D**；point 1（自适应）与 point 2（建表）完成前不得开始 point 5（已分析页）。每阶段独立可交付、可回滚，阶段末提交并跑全量验收命令。

### Phase B1 —— 数据地基（✅ 已实施 2026-09-15）

**范围**：§3 全部（两表 + meta 表 + ensure-schema + 回填脚本）；`Settings` 参数正式化（`llm_max_concurrency`、`cluster_analysis_budget=200`、`cluster_analysis_chunk_size=200`）；cluster_analyzer 写路径升级为"追加 analyses + 双写"（此阶段 bucket 仍 60s，自适应在 C 期）；描述符校验扩展 `bucket_epoch_offset`（可选字段）；SQL 收敛（§4.1）+ 金测试。

**验收**：
- pytest 新增：schema 幂等（重复 ensure 无副作用）、双写原子性（analyses 写成功且 events rowcount 校验通过；analyses 失败则 events 不变）、回填幂等、描述符 offset 校验、金测试 Python 侧。
- `make test-python` 全绿；存量用例（含 `test_llm_cluster_analysis_route.py`）不回归。

### Phase B2 —— 判定与消费端（✅ 已实施 2026-09-15）

**范围**：C++ comprehensive JOIN（§7/§8.2）+ 前端判据锁步切换（同一提交）；`analyze-event-cluster` 改造（map-reduce、版本追加、Graphiti 共享摄入、响应加 `analysis_id`）；§8.3 退役清单全项；问题清单第 6 项的跳过可观测化（`result["steps"]["event_clusters"] = {"skipped": true, reason}`）。

**验收**：
- ctest：comprehensive 新字段、JOIN 正确性（fixture）。
- pytest：路由级回归（版本追加、offset 422、Graphiti mock 失败不阻断）。
- vitest：Timeline 判据切换用例更新；`npm test -- --run` 与 `npm run lint` 不劣于基线。
- 手工冒烟：时间线换 bucket 后 auto-analyze 只析 `analysis_id` 为空的簇；重析产生版本链。

### Phase C —— 自适应与对齐（= 讨论点 1）（✅ 已实施 2026-09-15）

**范围**：§5 算法 + run 表写入；§8.1 四个新端点；界限放宽 2592000（双端同步，§4.3）；`bucket_epoch_offset` 全链路（C++ 建库写入 meta、全部表达式切换、C++ clamp 同步）；金测试扩展 offset 用例。

**验收**：
- pytest：阶梯选择算法（预算内最小、全超预算告警、显式覆盖）、offset 公式（UTC/东八区/半时区）、estimate 只读性。
- ctest：新上限 clamp、meta offset 读取、offset 表达式。
- 集成冒烟：对测试镜像跑 run，核对 run 记录的 bucket/统计与时间线复现分组一致。

### Phase D —— 已分析簇页（= 讨论点 5，最后）（✅ 已实施 2026-09-15）

**范围**：`GET /api/llm/event-cluster-analyses` 接管 `AnalysisCenter` 数据源（旧 `GET /clusters/analyzed` 保留一个版本周期后评估退役）；Timeline stale 徽标 + 人工重析按钮；i18n 文案；`docs/schema/EventsDB.md` 等文档收尾（§13.3）。

**验收**：vitest 页面适配用例；手工验收"已分析簇"页能按 run/bucket 过滤、显示版本链与 stale。

## 13. 工程规范

### 13.1 提交

- Conventional Commits（仓库现行惯例）：`feat(llm):`、`feat(web):`、`fix(cpp):`、`docs(specs):` 等。
- 锁步变更（§8.2 的 C++ JOIN + 前端判据）必须同一提交；一阶段至少一提交，禁止跨阶段混合提交。

### 13.2 测试命令（阶段验收最低要求）

```bash
# Python（改动侧必跑）
cd python_service && .venv/bin/python -m pytest tests/ -v        # 或 make test-python
# Web
cd web && npm test -- --run && npm run lint                       # lint 不劣于存量基线
# C++（触及 src/ 时必跑）
cmake --build build && cd build && ctest --output-on-failure      # 或 make test-cpp / make test
```

### 13.3 文档同步义务

| 阶段 | 必须同步的文档 |
|---|---|
| B1 | `docs/schema/EventsDB.md`、`docs/architecture/DatabaseSchema.md`（新表）；`docs/modules/python/httpserver` 涉及服务页 |
| B2 | `docs/api_reference/Python_REST_API.md`（analyze-event-cluster 行为）、`docs/api_reference/CPP_REST_API.md`（退役标注）；`docs/modules/web/Timeline` 相关页 |
| C | API 参考新增四端点；`docs/architecture/DataFlow.md` 簇分析段；`docs/tutorials` 涉及簇分析的操作段 |
| D | `docs/modules/web` 相关页；本 SPEC 状态改为"已实施"，锁定决策移交 schema/API 文档 |

### 13.4 兼容性规则

- API 只增不改名；响应新增字段不得破坏旧前端（Timeline 的 `llm_*` 字段名保持）。
- 旧描述符（无 offset）合法 = offset 0；存量 events 库（无 meta）= offset 0、行为不变。
- analyses 表为空的任务所有流程照常工作（时间线判"未分析"是诚实行为）。

## 14. 风险与回滚

| 风险 | 缓解 |
|---|---|
| map-reduce 全量分析在大镜像上耗时长 | dry-run 估算先行暴露成本；CHUNK/预算/并发三旋钮可调；run 统计可视化 |
| C++ JOIN 改动破坏时间线分页/计数 | count SQL 与 GROUP BY 匹配性有既有注释约束（`TimelineQueries.cpp:118-122`），金测试 + ctest 覆盖 |
| 双端 schema/表达式漂移 | §4.4 金测试为阶段验收硬性项 |
| 回填脚本误写 | 幂等 + 只 INSERT analyses 表 + `trigger_source='migrated'` 可识别；不触碰 events 行 |
| offset 使新旧分组坐标不可比 | meta 写一次永不变更；存量库保持 0；analyses 坐标含 offset，跨 offset 不误连 |
| Graphiti 重复摄入 | `ingested_at` 状态机 + episode 名含 analysis_id 可去重 |
| 整体回滚 | 新表/新字段均为增量，停写 analyses 即回到旧行为；无破坏性迁移 |

---

## 附录 A：涉及文件总清单（实施核对用）

**Python**：`services/investigation_evidence.py`（规范源/校验/界限）、`services/case_analysis/cluster_analyzer.py`（管线/共享摄入）、`services/case_analysis/schema.py`（新）、`scripts/backfill_cluster_analyses.py`（新）、`routes/llm_endpoints/_analysis.py`（路由改造）、`routes/event_cluster_analysis.py`（新，run/estimate/analyses）、`routes/case_analysis_endpoints/_case.py`（死导入清理/GET job 退役）、`services/case_analysis/file_analyzer.py`（死方法删除）、`httpserver/config.py`（Settings）、`case_analysis_parts/_pipelines.py`（跳过可观测化、run 对接）。

**C++**：`src/network/HTTPServer/Queries/TimelineQueries.cpp`（JOIN/meta/上限/表达式）、`routes/TimelineRoutes.cpp`（ensure-schema/参数）、`routes/EventClusterRoutes.cpp`（退役注释）、`EventClusterAnalyzer.{h,cpp}`（退役注释）、events 库创建处（meta 写入，定位见实现）。

**Web**：`pages/Timeline.jsx`、`pages/AnalysisCenter.jsx`、`services/forensicsService.js`、`services/caseAnalysisService.js`、`locales/en.js`、`locales/zh.js`。

**测试**：pytest（schema/双写/回填/算法/offset/路由回归/金测试）、ctest（comprehensive/clamp/meta/金测试）、vitest（判据/页面适配）、共享 fixture JSON。
