# SPEC：文件分析重构（File Analysis Redesign）

> **状态**：已评审锁定（2026-09-15）；Phase 1-2 已实施（2026-09-16），Phase 3-7 待实施。
> **范围**：Web 拓扑下文件 LLM 分析的生成、存储、已分析判定、下游消费（事件簇分析 / Graphiti / 报告 / 调查证据）、知识图谱摄入与主流水线编排全链路。CLI 拓扑不在本 SPEC 范围内（§2 D2）。
> **性质**：与 [event-cluster-analysis-redesign.md](event-cluster-analysis-redesign.md) 同属过程规范文档，不随代码同步更新。
> **测试口径**：阶段验收使用 `make test-python-focused`；仓库级全量测试按惯例在全部阶段完成后统一执行。
> **分支**：Dev 工作区。

---

## 0. 背景与问题清单

调研确认的现状（锚点均为锁定时点的代码位置）：

1. **覆盖写无历史（P1）**：`persist_to_files_db` 纯 UPDATE/UPSERT（`python_service/httpserver/services/llm/llm_service.py:118-218`），重析、换案情重跑、交互式分析均静默覆盖旧描述，无版本、无 trigger 来源记录。
2. **"已分析"判定双轨盲区（P2）**：`analyze_files` 的跳过判定只查 `file_descriptions.description` 非空（`services/case_analysis/file_analyzer.py:51-81`），不看 `files.llm_analyzed_at`。C++ 初始/CLI 轮只写 `files.llm_*` 不写 `file_descriptions`（`src/network/HTTPServer/LLMAnalysisService.cpp:382`）→ CLI 已析文件在 Web 案情轮被全量重析且通用描述被覆盖丢失；反向地，交互式页面析过的文件会让案情轮跳过。
3. **双事实来源（P3）**：`files.llm_*` 与 `file_descriptions` 存同样内容但读方分裂——Files 页经 C++ HTTPServer 读前者（`FileAnalysisQueries.cpp`），报告与 LLMDescriptions 读后者（`report_generator.py:101`），Graphiti 实体读前者。
4. **Step3 并行时序空洞（P4）**：`run_full_analysis` 用 `asyncio.create_task` 让文件分析与簇分析并行（`case_analysis_parts/_pipelines.py:147-167`），簇分析构建证据时读不到本轮刚生成的文件描述。
5. **无 stale 传播（P5）**：文件重析后，图谱旧 episode（append 不删）、已持久化调查证据的 `initial_description`、已生成报告均不感知失效。
6. **输出启发式粗糙（P6）**：summary = `description[:200]` 首行、keywords = 中文 2-6 字正则抓取（`file_analyzer.py:178-184`）；`reanalyze_files` 串行 for 循环（`:294`）与 `analyze_files` 并发不对称；文件分析无任务级 estimate/run 端点。
7. **簇 episode 四处实现、双重摄入（C1，缺陷）**：`build_analysis_episodes`（`cluster_analyzer.py:782-827`，SPEC 格式，带 analysis_id 与 ingested 状态机）为真源，但仍有三处旧格式注入面：① `_pipelines.py:207-209/308-310` 把 `cluster_results` 传给 `file_analyzer.ingest_to_knowledge_graph` 的旧格式簇分支（`file_analyzer.py:551-579`）→ 同一批簇分析被两种格式双份摄入同一 task graph；② 手动 Ingest 按钮 path-A（`ingestion_job_parts/_worker.py:583`）以遗留 per-event `/60` GROUP BY 从 `llm_*` 缓存重建伪簇，经 `graphiti_parts/_ingest.py:324` 簇段喂入 task graph；③ `graphiti_parts/_ingest.py` 的 case 级方法 `ingest_case_data:128-181` 与 `ingest_case_data_incremental:522-581` 各有一处同款伪簇段（group_id 为 case_id，不构成 task graph 内重复，归 Phase 7 归一）。另 `windows_artifacts/windows_analyzer.py:447` 恒传 None（死参）。
8. **episode 分块三处硬编码（D1 起因）**：3000 字符字面量三处（`cluster_analyzer.py:801`、`:763`、`file_analyzer.py:517/536`），与 graphiti 层互不关联的 `GRAPHITI_MAX_EPISODE_TOKENS`（`graphiti_integration/config.py:47,108`）并存。
9. **episode reference_time 失真（D2 起因）**：全部 episode 的 `reference_time=datetime.now()`（摄取时刻），错用 Graphiti bi-temporal 模型的事件时间位，图谱时间推理失真。

## 1. 术语与坐标

| 术语 | 定义 |
|---|---|
| **文件分析记录（analysis）** | `file_analyses` 表一行，一次 LLM 文件分析的完整结果，**append-only** |
| **最新版本** | 同一 `file_path` 下 `id` 最大的分析记录 |
| **当前态** | `files.llm_*`（C++ 侧缓存）与 `file_descriptions`（Python 侧当前态 + 用户 `is_relevant` 标记）双写缓存的合称 |
| **已分析** | 存在同 `file_path` 的分析记录（§4） |
| **stale** | 最新记录的 `md5` 与 `files.md5` 不一致，或下游证据的存档时间早于最新分析时间（§9） |
| **trigger_source** | 分析来源枚举：`pipeline`（案情轮）/ `interactive`（/analyze 单析）/ `batch`（/batch）/ `reanalyze`（reanalyze-files）/ `migrated`（存量缓存归档） |
| **工件轮** | Windows 工件 LLM 分析（`services/windows_artifacts/windows_analyzer.py`），现状为独立手动端点 `POST /api/llm/windows-analysis` |

## 2. 锁定的设计决策

以下决策已在评审中拍板，实施阶段**不得擅改**；确需变更走 SPEC 修订。

| # | 决策 | 理由 |
|---|---|---|
| D1 | **Web 端必须要求 AI**：文件轮、簇轮、工件轮为强制步骤；LLM 不可达时不得静默跳过，按 §5.3 失败可见语义记录。CLI 端保留 `--no-ai` 模式（出范围） | 取证结论的完整性优先；"强制"必须可审计 |
| D2 | **范围仅 Web 拓扑**。C++ LLM 分析代码（`WindowsLLMAnalysisService` 等）保持 CLI 专用，本期不删不改；Web 流程中所有 LLM 分析统一在 Python 侧 | 避免跨进程 LLM 配置扩散；C++ 代码留作 CLI 资产 |
| D3 | 新建 `file_analyses`（append-only）作为真相源；`files.llm_*` 与 `file_descriptions` **保留，双写**为缓存；全部现有读方零迁移 | 复刻事件簇 SPEC D1/D2 成熟模式；写点唯一（`persist_to_files_db`），改动集中 |
| D4 | **已分析判定 = 同 `file_path` 存在分析记录**；`md5` 不一致只标记 stale，不触发重析。**换案情重跑不触发文件重析** | 评审明确；避免换案情即全量重析的 LLM 成本 |
| D5 | Python 读方对"当前分析"的查询统一收敛到 `services/case_analysis/file_schema.py` 提供的访问器（最新版本子查询）；缓存列仅供 C++ 读方与展示 | 单一事实入口，杜绝第三个查询变体 |
| D6 | stale 传播本期实施 L1-L3（§9）；L4（簇引用文件版本）仅在 D9-v1 落地时同步实施 | L4 的必要性完全取决于簇 prompt 是否注入文件描述 |
| D7 | 簇 episode builder 归一：保留 `cluster_analyzer.build_analysis_episodes` 为唯一实现，删除 `file_analyzer` 簇分支与 `_ingest.py` 簇分支 | 消除双重摄入缺陷；episode 名含 `#a{analysis_id}` 的可引用语义不破坏 |
| D8 | Step3 编排改为**文件轮先行、完成落库后簇轮启动**（取消两者并行） | 簇分析可见本轮带案情文件描述；消除调度顺序依赖 |
| D9 | 文件描述注入簇分析分两步：**v0** 只把 `related_file_summaries`（去重、≤20 文件、仅 summary）作为簇分析记录元数据存档并前端展示；**v1**（reduce 阶段注入 prompt）须以 v0 的真实数据 A/B 评测结论质量后再决；**若实施 v1，必须同步实施 D6-L4** | 平衡语义收益与 prompt 膨胀；代价（staleness 耦合）显式挂钩 |
| D10 | **工件轮并入 `run_full_analysis`**：与文件轮并行启动（工件读 `windows_*` 表，与文件轮无依赖），先于簇轮完成不作硬性要求；`windows-analysis` 手动端点保留，内部共享同一实现 | D1 的落地形态；不放宽 http_agent `--no-ai` 不变量 |
| D11 | episode 分块预算统一：唯一 token 预算源 `GRAPHITI_MAX_EPISODE_TOKENS`；episode `max_chars = floor(max_episode_tokens × 3)`（沿用 toon_transformer 保守字符比）；三处 3000 字面量全部改为引用共享常量 | 分块粒度由模型预算推导而非拍脑袋 |
| D12 | episode `reference_time` 改用取证时间：文件 episode = `files.mtime/ctime`；簇 episode = `cluster_start`；案情描述 episode 保持 `now()` | 修复 Graphiti bi-temporal 事件时间位错用 |
| D13 | Graphiti 初始化时探测 LM Studio 模型上下文（`/api/v0/models`，2s 超时，进程内缓存）：成功则 `max_episode_tokens = min(配置值, context × 0.15)`；失败静默回退配置值。探测代码封装于 `graphiti_integration` 内部 | LM Studio 已是既有依赖，探测不构成新依赖；失败语义天然成立 |
| D14 | `reanalyze_files` 并发化，复用 `llm_max_concurrency` Semaphore；逐文件异常隔离保持；进度回调保持计数式 | 与 `analyze_files` 对称；串行无独立理由 |
| D15 | 分析 prompt 升级为四段式结构化输出（简要总结/详细分析/关键词/取证价值），共用 lenient parser；**解析失败回退整段 description + 现有截断/正则逻辑，永不因解析失败丢弃分析**；`is_relevant` 不自动映射取证价值 | 对齐簇分析输出契约；模型服从性不可假设 |
| D16 | `is_relevant` 语义保持：被分析过默认进证据列表（首次落库默认 1），用户可取消；重析 upsert 不得重置用户标记；该字段留在 `file_descriptions`（当前态），不进 append-only 日志 | 现行为即评审确认的理论设计 |
| D17 | **可观测性**：分析结果与 `file_analyses` 记录新增 `extraction_method`（`markitdown` / `legacy:{ExtractorName}` / `vision` / `raw_text`），前端展示徽标。**markitdown 双入口（进程内 extractor 与 HTTP 路由 `routes/markitdown.py`）不收口**——二者已共享同一 locator/单例引擎/fallback 映射，服务不同进程域 | 提取方式本身是取证溯源信息；合并反造耦合 |
| D18 | 新增任务级端点 `POST /api/llm/file-analysis/{estimate,run}`（§8），对齐事件簇 SPEC §8.1 形态 | 补齐入口缺口；预算预估先行 |
| D19 | 存量缓存归档：persist 时发现 `files.llm_analyzed_at` 非空但无对应 `file_analyses` 行（CLI 轮产物），先以 `trigger_source='migrated'` 归档现有缓存再覆盖 | CLI→Web 交接时通用描述不无痕丢失 |

## 3. 数据模型规范

### 3.1 新表 DDL（权威版本）

落库位置：任务 `_files.db`（与 `file_descriptions` 同库）。SQLite 保留字注意：不用 `trigger` 作列名。

```sql
CREATE TABLE IF NOT EXISTS file_analyses (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id              TEXT    NOT NULL,
    file_path            TEXT    NOT NULL,   -- normalize_evidence_path 规范化路径
    md5                  TEXT    NOT NULL DEFAULT '',
    summary              TEXT    NOT NULL DEFAULT '',
    description          TEXT    NOT NULL DEFAULT '',
    keywords             TEXT    NOT NULL DEFAULT '',
    model                TEXT    NOT NULL DEFAULT '',
    extraction_method    TEXT    NOT NULL DEFAULT '',
    trigger_source       TEXT    NOT NULL,
    analysis_id_upstream INTEGER,
    created_at           INTEGER NOT NULL,
    ingested_at          INTEGER
);
CREATE INDEX IF NOT EXISTS idx_fa_path     ON file_analyses(file_path, id DESC);
CREATE INDEX IF NOT EXISTS idx_fa_task     ON file_analyses(task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fa_path_md5 ON file_analyses(file_path, md5);
```

### 3.2 字段语义与不变量

- **append-only**：`file_analyses` 只允许 INSERT；唯一允许的 UPDATE 是把 `ingested_at` 从 NULL 改为时间戳（Graphiti 摄入状态机，§9-L3）。任何其他 UPDATE/DELETE 都是 bug。
- **写入原子性**：一次成功分析 = 单事务内依次完成 ① `UPDATE files SET llm_*`（保留现行 rowcount 严格校验与 fail-closed 语义，`llm_service.py:141-185`）→ ② `INSERT INTO file_analyses` → ③ upsert `file_descriptions`（沿用现行 `ON CONFLICT DO UPDATE`，**不得触碰 `is_relevant`**，D16）。任一步失败整体回滚。D19 的归档 INSERT 在 ② 之前同事务执行。
- **规范化**：`file_path` 一律经 `normalize_evidence_path` 归一后写入（与 `files.path` 身份一致，现行行为保持）。
- **is_relevant 归属**：仅存于 `file_descriptions`，首次 INSERT 默认 1；`file_analyses` 不含该列（用户标记是当前态，不是分析结果）。
- **schema 创建**：`services/case_analysis/file_schema.py::ensure_file_analysis_schema(files_db)` 幂等 ensure，由 `persist_to_files_db` 入口与 file-analysis 路由调用；模式沿用 `_ensure_file_descriptions_schema` 惯例。

### 3.3 统一访问器（D5）

`file_schema.py` 提供（全部只读）：

- `latest_analysis(files_db, file_path) -> Optional[dict]`：最新版本记录；
- `LATEST_ANALYSIS_JOIN`：SQL 片段（`JOIN file_analyses fa ON fa.id = (SELECT MAX(id) FROM file_analyses WHERE file_path = ?)`），供批量查询；
- `analysis_stats(files_db) -> dict`：总数/已分析数/stale 数（§8 estimate 数据源）。

存量 Python 读方（报告、证据解析、Graphiti 摄入）继续读缓存列，**不在本期迁移**（零风险原则）；所有**新增**当前态查询必须走本模块，禁止第三处直写 SQL。

### 3.4 存量归填（D19）

- 无需独立回填脚本：归档发生在**首次覆盖时**（persist 路径内联，同事务），幂等性由"存在 `trigger_source='migrated'` 行则跳过"保证。
- 归档行字段映射：`summary/description/keywords/model ← files.llm_*`，`created_at ← files.llm_analyzed_at`，`md5 ← files.md5`，`extraction_method=''`（不可考），`analysis_id_upstream=NULL`。
- 未经过归档路径的库（纯 Web 新任务）不受影响。

## 4. "已分析"判定规范（D4）

- **判定**：文件已分析 ⇔ `EXISTS(SELECT 1 FROM file_analyses WHERE file_path = :normalized)`。
- **管线跳过**：`analyze_files` 的 `already_described` 预检（`file_analyzer.py:51-81`）从查 `file_descriptions` 切换为查 `file_analyses`。跳过结果沿用现行合并返回语义（返回已有描述，标注未重析）。
- **换案情**：不触发重析（D4 锁定）。案情上下文差异记录为已知局限：如需按新案情刷新描述，走 `reanalyze-files` 显式入口。
- **stale 标记**：最新记录 `md5 ≠ files.md5` → 展示层 stale 徽标（§9-L2），不自动重析。
- **手动重析**：不做任何已分析判断，总是追加新版本，`analysis_id_upstream` 指向被替代记录 id（对齐事件簇 SPEC D8）。

## 5. 主流水线编排规范

### 5.1 编排结构（D8/D10）

`run_full_analysis`（`case_analysis_parts/_pipelines.py`）Step3 由"双任务并行"改为：

```
Step3a  工件轮（analyze_windows_artifacts） ∥ 文件轮（generate_file_descriptions）
        —— 两者无数据依赖，并行启动
Step3b  簇轮（analyze_and_ingest_clusters）—— 在文件轮完成落库之后启动
Step4   Graphiti 摄入（文件 episode + 簇 episode，各自内部状态机）
Step5   报告（不变）
```

工件轮的进度与结果并入 `result["steps"]["artifacts"]`；events_db 缺失时簇轮的 visible-skip 记录（现行 `_pipelines.py:168-175`）保持。

### 5.2 簇轮可见性前提（D8 的收益锚点）

簇轮启动时，本轮文件描述已全部落库（`files.llm_*` + `file_analyses` + `file_descriptions`）。C3-v1（若实施）依赖此前提；v0 的 `related_file_summaries` 元数据同样在簇轮内读取。

### 5.3 失败可见语义（D1）

- LLM 端点不可达、或某轮整体失败 → `result["steps"][轮名] = {"failed": True, "reason": ...}`，任务终态标记 `partial`；**禁止**静默跳过或降级为"无分析成功"。
- 单文件失败沿用现行逐文件 error 隔离（不因个别文件失败中断整轮）。
- 对齐事件簇 SPEC §0 问题 6 的 visible-skip 先例；前端任务详情页展示 partial 状态（Phase 3 一并落地）。

## 6. Graphiti 摄入规范

### 6.1 builder 归一（D7）

- 唯一簇 episode 实现：`cluster_analyzer.build_analysis_episodes`（SPEC 格式：episode 名含 `#a{analysis_id}`，`ingested_at` 状态机，失败不回滚落库）。
- 删除（Phase 1）：`case_analysis/file_analyzer.py:551-579` 簇分支及 `cluster_descriptions` 参数；`graphiti_parts/_ingest.py::ingest_task_episodes` 的簇段及参数；`windows_analyzer.py:447` 实参与形参。
- 手动 Ingest path-A 重接（Phase 1）：`ingestion_job_parts/_worker.py` 删除遗留 `/60` 伪簇 SQL，改为读取 `event_cluster_analyses WHERE ingested_at IS NULL`，并经共享 `ingest_analysis_record_to_graphiti` 逐行补摄（幂等：成功即标记 ingested_at，失败留 NULL 供下次补摄）。自本阶段起，task 级簇 episode 的格式与摄入所有权唯一归属 `cluster_analyzer`。
- case 级簇段归一（Phase 7）：`ingest_case_data` / `ingest_case_data_incremental` 的伪簇段切换 `build_analysis_episodes` 数据源（`event_cluster_analyses`），保留 case 级 group_id 与 source_image 标签语义。
- `ingest_to_knowledge_graph`（file_analyzer 与 windows_analyzer 两处）收敛为仅处理各自的分析结果；文件 episode 段以 `_ingest.py` 的丰富 body（keywords/md5/category/is_relevant 进 body）为准归一，episode 名升级为 `文件分析: {file_path} #fa{id}`（Phase 7 与 L3 状态机同期）。

### 6.2 reference_time（D12）

| episode 类别 | reference_time | 来源 |
|---|---|---|
| 文件分析 | `files.mtime`（缺省 `ctime`），`datetime.fromtimestamp(..., tz=UTC)` | persist 结果携带或摄入时回查 files 行 |
| 事件簇分析 | `cluster_start` | fetch 已查出，传入 `build_analysis_episodes` |
| 案情描述 | `datetime.now()`（可选案件创建时间） | 不变 |

### 6.3 分块预算统一（D11）与上下文探测（D13）

- 共享常量/Settings：`episode_chunk_max_chars = floor(max_episode_tokens × 3)`；`cluster_analyzer` 两处与 `file_analyzer` 一处全部改为引用，禁止新字面量。
- 探测：`graphiti_integration` 初始化时 `GET {text_base_url}/api/v0/models`（2s 超时），匹配所选模型的 context length；成功 → `max_episode_tokens = min(配置值, floor(context × 0.15))`；失败/超时/字段缺失 → 配置值，仅记日志。进程内缓存，失败后本进程不再重试。探测不新增任何调用方可见行为。

## 7. 输出质量与交互规范

### 7.1 结构化输出（D15）

- prompt 侧：`prompts.py` 五组模板（`TEXT_ANALYSIS_*`、`CASE_FILE_ANALYSIS_TEMPLATE`、`CASE_VISION_*`、`FILE_REANALYSIS_*`）追加输出格式段，对齐簇分析四段式：`1. 简要总结 2. 详细分析 3. 关键词 4. 取证价值`。
- 解析侧：新增共用 lenient parser（建议落 `prompts.py` 或 `services/llm/` 内），按段标题切分；`summary/keywords` 从对应段提取。**解析失败不抛错**：整段文本作为 description 落库，summary/keywords 退化为现行截断/正则逻辑。
- 存量混格式容忍：报告聚合与前端按 summary/keywords 语义读取，不假设格式统一。
- `取证价值`（高/中/低）仅落档于分析记录（可存 `file_analyses` 附加列或 description 内），**不自动写 `is_relevant`**（D16）。

### 7.2 并发（D14）

`reanalyze_files` 改 `asyncio.gather` + `asyncio.Semaphore(llm_max_concurrency)`；逐文件 try/except 保持；进度回调改为与 `analyze_files` 相同的 `(processed, total, file_path)` 计数式（现行调用方已兼容该形态）。

### 7.3 可观测（D17）

- 提取层：`MarkitdownExtractor.extract_to_markdown` 回退三处（`:74-83`、`:107-114`、`:125-136`）在返回时携带实际使用的 extractor 标识（基类返回值签名扩展，自 MarkitdownExtractor 始）。
- 分析层：结果 dict 增加 `extraction_method`；`persist_to_files_db` 落入 `file_analyses.extraction_method`。
- 展示层：LLMDescriptions / Files 页徽标（Phase 2 一并落地）。
- markitdown 读错误包装防护（`markitdown_extractor.py:100-102`）保持；双入口不收口（D17）。

## 8. API 契约

原则：**只增不改名**（对齐事件簇 SPEC §8）。

### 8.1 新增（Phase 6）

| 端点 | 语义 |
|---|---|
| `POST /api/llm/file-analysis/estimate` | body `{task_id}`；返回 `{filtered_total, analyzed, pending, stale, estimated_llm_calls, estimated_chars}`。只读不执行 |
| `POST /api/llm/file-analysis/run` | body `{task_id, file_paths?}`；缺省 file_paths 时复用已筛选文件列表（`get_filtered_files_from_db`）。后台 job（沿用 `_analysis_jobs` 内存注册表惯例），跳过判定按 §4；返回 `{job_id, ...}` |
| `GET /api/llm/file-analysis/run/{job_id}` | 进度/统计/失败清单 |
| `GET /api/llm/file-analyses` | query：`task_id`（必填）、`file_path`（可选）；返回分析记录版本链（Phase 7 前端历史视图的数据源） |

### 8.2 变更

- `POST /api/llm/reanalyze-files`（`case_analysis_endpoints/_case.py:94-104`）：内部并发化（D14）；响应逐文件增加 `analysis_id`；落库走 trigger_source=`reanalyze`。
- `POST /api/llm/analyze` / `/analyze/file` / `/batch`：trigger_source 分别为 `interactive`/`batch`；响应增加 `analysis_id`、`extraction_method`（渐进，不破坏旧字段）。

### 8.3 内部签名变更（非 API）

- `ingest_to_knowledge_graph`（file_analyzer / windows_analyzer / `_core.py` 委托）：移除 `cluster_descriptions` 参数（D7）。
- `_pipelines.py` Step3 结构调整（§5.1）。

## 9. stale 传播规范（D6）

| 层 | 对象 | 机制 | 阶段 |
|---|---|---|---|
| L1 自动新鲜 | `files.llm_*`、`file_descriptions`、报告动态聚合、证据解析 `initial_description` | 读的就是当前态，重析即生效；无需机制 | 无（现状即成立） |
| L2 证据 stale 标记 | 调查证据库中 file 证据行 | 持久层已存 `source_updated_at`（= 入证据时的 `llm_analyzed_at` 快照，`investigation_persistence.py:318,913-928`）；查询层比对 `当前 llm_analyzed_at > source_updated_at` → `is_stale`；前端证据列表徽标 | Phase 7 |
| L3 图谱历史 | Graphiti episode | append-only + `#fa{id}` 命名 + `file_analyses.superseded_by` 链 + 重析成功后按 `ingested_at` 状态机补摄新 episode（复用簇侧 `mark_analysis_ingested` 模式）；旧 episode 不删（证据链） | Phase 7 |
| L4 簇引用文件版本 | `event_cluster_analyses` | **仅当 D9-v1 实施**：簇分析行记录分析时刻成员文件 `max(llm_analyzed_at)`，文件重析后簇标记 stale | 条件 |

## 10. 前端契约与改动边界

| 文件 | 改动 | 阶段 |
|---|---|---|
| `web/src/pages/LLMDescriptions.jsx` | extraction_method 徽标；分析历史入口（§8.1 第四端点） | 2 / 7 |
| `web/src/pages/Files.jsx` | extraction_method 徽标；stale 徽标（md5 失配） | 2 / 7 |
| 事件簇详情视图 | `related_file_summaries` 展示（D9-v0） | 5 |
| 任务详情页 | partial 终态展示（§5.3） | 3 |
| `web/src/services/llmService.js` / `caseAnalysisService.js` | file-analysis 四端点封装；reanalyze 响应新字段 | 6 |

## 11. 明确禁止事项（Out of Scope / 禁改清单）

1. **http_agent `--no-ai` 不变量**（`src/http_agent/command_executor.cpp:75`，"client never runs the LLM"）——不得放宽或绕过。
2. **文件证据 key** `file:{normalize_forensic_path(path)}`（`investigation_evidence.py:18,67-69`）与簇 key `cluster:v1:*`（事件簇 SPEC D12）——不动。
3. `files.llm_*` 列与 `file_descriptions` 表——不删不改名，只按 §3.2 双写。
4. `file_descriptions.is_relevant`——用户控制状态；重析 upsert 不得重置；首次落库默认 1（D16）。
5. `persist_to_files_db` 的 fail-closed 语义（目标库不存在拒绝写他处）与 `normalize_evidence_path` 身份归一——保持。
6. C++ 读方兼容：`FileAnalysisQueries.cpp`、`TOONExporter.cpp` 依赖 `files.llm_*` 列持续有值——双写不得断。
7. 案件级三端点（multi-image / smart-create / incremental）对外契约——不破坏；内部经 `run_full_analysis` 获得新能力属自然受益。
8. markitdown HTTP 路由 `routes/markitdown.py`（CLI `MarkitdownProxy` 跨进程依赖）——保留。
9. `_files.db` 既有表结构——只增表/索引，不改现有列。
10. 事件簇 SPEC §11 全部红线继续有效；本 SPEC 任何改动不得触碰其管辖面。
11. C++ LLM 分析代码（`WindowsLLMAnalysisService`、`LLMIntegration/FileAnalyzer` 等）——本期不删不改（D2，CLI 资产）；Web 流程不得新增对它的调用。
12. `MAX_CLUSTER_EVENTS_FOR_LLM=50`、`MAX_RELATED_EVIDENCE=20` 等调查工作台装配常量——不动。

## 12. 实施阶段划分与验收标准

> 顺序约束：**Phase 1 → 2 → 3 → 4 → 5 → 6 → 7**；Phase 2（数据地基）完成前不得开始 Phase 6/7。每阶段独立可交付、可回滚，阶段末提交并跑验收命令。

### Phase 1 —— 双重摄入清理（C1）（✅ 已实施 2026-09-16）

**范围**：§6.1 删除清单全项；`_pipelines.py` 两处调用停传 `cluster_results`；`_worker.py` 手动 Ingest 簇段重接为 analyses 表补摄（§6.1）；相关测试更新。

**验收**：pytest——签名回归（四处公开摄入函数不再含 `cluster_descriptions`）；file 分析摄入只产 `文件分析` episode；worker 补摄只读 `event_cluster_analyses`（遗留 `llm_*` 缓存行被忽略）且成功后 `ingested_at` 落值；完整管线后 Graphiti mock 收到的簇 episode 全部为 `#a{id}` 格式且数量等于簇数（无旧格式重复）。`make test-python-focused` 全绿。

### Phase 2 —— 数据地基（B1 + D17 + D19）（✅ 已实施 2026-09-16）

**范围**：§3 全部（新表 + ensure-schema + 统一访问器 + 原子写路径改造 + 判定切换 + 内联归档）；`extraction_method` 后端全链路（提取层 → 结果 → 落库）。实施记录：前端徽标推迟至 Phase 7——LLMDescriptions 页与 Files 页均经 C++ HTTPServer 取数（`getTaskResults` / `/api/files`），Python 侧先行暴露会在无消费方的情况下跨语言改 C++ API，违背"读方零迁移"原则；与 §10 徽标行标注的 "2 / 7" 中 "7" 一致。

**验收**：pytest——schema 幂等（重复 ensure 无副作用）、三写原子性（任一失败整体回滚）、判定切换（`file_descriptions` 有行但 `file_analyses` 无行时不再跳过；反之跳过）、归档幂等（二次覆盖不重复归档）、fail-closed 不回归。手工冒烟：Files 页 / 报告 / TOON 导出零变化（读方零迁移验证）。

### Phase 3 —— 编排与并发（C2 + D10 + §5.3 + D14）（✅ 已实施 2026-09-16）

**范围**：Step3 重构（§5.1）；工件轮并入与 `result["steps"]["artifacts"]`；失败可见语义与 partial 终态（后端 + 前端任务详情）；`reanalyze_files` 并发化。实施记录：编排逻辑收敛到 `CaseAnalysisPipelinesMixin._execute_analysis_rounds`（初析/复用两分支共用，可独立驱动测试）；partial 经 `AnalysisStatusResponse.result.partial` 自然透出，前端为三处轮询消息的 partial 分支（纯展示改动，无新增组件测试，以存量 200 项 vitest + 与 Dev 一致的 lint 基线验证）。

**验收**：pytest——编排顺序（文件轮完成事件先于簇轮启动）、工件轮失败不阻断文件/簇轮但使任务 partial、reanalyze 并发上限为 `llm_max_concurrency`；vitest——任务详情 partial 展示。

### Phase 4 —— Graphiti 预算与时间（D11 + D12 + D13）

**范围**：§6.2 / §6.3 全项；三处 3000 字面量清除。

**验收**：pytest——reference_time 断言（文件 episode = mtime、簇 episode = cluster_start）、chunk 常量推导公式、探测 mock（成功缩限/失败回退/超时回退）；grep 断言仓库内无新增 3000 分块字面量（CI 可选）。

### Phase 5 —— 簇上下文 v0（C3-v0）

**范围**：簇分析记录元数据 `related_file_summaries`（去重、≤20、仅 summary，来自 `file_analyses` 最新版本）；事件簇详情前端展示。

**验收**：pytest——元数据生成（去重/截断/空描述容忍）；A/B 评测准备：对 test_image.img 真实簇留存 v0 结论样本，作为 D9-v1 决策依据。

### Phase 6 —— 结构化输出与任务级端点（D15 + D18）

**范围**：§7.1 五组 prompt + lenient parser；§8.1 四端点；§8.2 响应字段。

**验收**：pytest——parser 对标准/缺段/纯文本输入的降级行为（永不抛错）、estimate 只读性、run 的跳过判定与 job 生命周期；vitest——服务封装。

### Phase 7 —— stale 传播与图谱状态机（B4-L2/L3；若 v1 已决则含 L4）

**范围**：§9-L2 证据 stale 比对与徽标；§9-L3 `superseded_by` + `#fa{id}` 命名 + `ingested_at` 补摄状态机 + 文件 episode body 归一（§6.1 尾项）；v1 决策：若实施，`related_file_summaries` 进 reduce prompt + L4 同步。

**验收**：pytest——stale 比对（重析后旧证据行 is_stale、未重析不受影响）、补摄幂等（ingested_at 状态机）、superseded 链完整；手工验收——重析一文件后图谱出现新 episode 且旧 episode 保留。

## 13. 工程规范

### 13.1 提交

- Conventional Commits：`feat(llm):`、`fix(llm):`、`feat(web):` 等；一阶段至少一提交，禁止跨阶段混合提交。

### 13.2 测试命令（阶段验收最低要求）

```bash
# Python（改动侧必跑；全量测试按统一口径延后）
cd python_service && .venv/bin/python -m pytest tests/ -v -k focused   # 或 make test-python-focused
# Web（触及 web/ 时必跑）
cd web && npm test -- --run && npm run lint                            # lint 不劣于存量基线
# C++：本 SPEC 不触及 src/，无需 ctest；若例外触及则必跑
```

### 13.3 文档同步义务

| 阶段 | 必须同步的文档 |
|---|---|
| 2 | `docs/architecture/DatabaseSchema.md`（file_analyses 表）；`docs/modules/python/services/LLMService.md`（双写与判定）；`docs/reference/Environment.md`（如新增 Settings） |
| 3 | `docs/architecture/DataFlow.md` 案情流水线段（编排变更） |
| 4 | `docs/modules/python` Graphiti 集成相关页（预算/探测） |
| 6 | `docs/api_reference/Python_REST_API.md`（四新端点 + 响应字段）；`docs/modules/python/httpserver/routes/LLM.md` |
| 7 | `docs/schema/EventsDB.md` 无涉；`docs/modules/web` 证据/描述页；本 SPEC 状态改为"已实施"，锁定决策移交 schema/API 文档 |

### 13.4 兼容性规则

- API 只增不改名；响应新增字段不得破坏旧前端。
- `file_analyses` 为空的任务所有流程照常工作（管线会诚实重析一次，成本一次性）。
- 探测失败（离线/非 LM Studio 端点）一切行为与今日一致（配置值兜底）。

## 14. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 三写原子性在并发下死锁/超时 | 沿用现行 `sqlite3.connect(timeout=10)` 单写点串行化；Phase 2 并发用例覆盖 |
| 判定切换导致全量重析（成本冲击） | estimate 端点先行暴露规模（Phase 6）；Phase 2 切换前后用 test_image.img 冒烟核对 pending 数 |
| 结构化输出模型服从性差 | lenient parser 永不失败（§7.1）；Phase 6 用真实双模型（gpt-oss / nemotron）冒烟 |
| D9-v1 注入导致簇 prompt 膨胀 | v1 以 v0 A/B 数据决策 + reduce-only 注入（膨胀单次化）；不实施则零风险 |
| LM Studio 探测引入启动延迟/失败 | 2s 超时 + 进程内缓存 + 静默回退；失败路径与今日行为逐字节一致 |
| stale 徽标误报（mtime 缺失等） | L2 比对键是 `llm_analyzed_at`（分析轮写入，非文件系统属性），不依赖 mtime |
| 整体回滚 | 新表/新字段均为增量；停写 `file_analyses` 并还原判定查询即回到旧行为；无破坏性迁移 |

---

## 附录 A：涉及文件总清单（实施核对用）

**Python**：`services/llm/llm_service.py`（persist 三写/归档/trigger_source）、`services/case_analysis/file_schema.py`（新：DDL + 访问器）、`services/case_analysis/file_analyzer.py`（判定切换、簇分支删除、reanalyze 并发、extraction_method、episode reference_time）、`services/case_analysis/cluster_analyzer.py`（chunk 常量、related_file_summaries、reference_time 传参）、`services/case_analysis/case_analysis_parts/_pipelines.py`（Step3 重构、停传 cluster_results、artifacts 步骤、失败可见）、`services/case_analysis/case_analysis_parts/_core.py`（委托签名）、`services/case_analysis/schema.py`（如需共享常量）、`services/graphiti_parts/_ingest.py`（ingest_task_episodes 簇段删除 Phase 1；case 级簇段与文件段归一 Phase 7）、`services/windows_artifacts/windows_analyzer.py`（死参清理）、`services/ingestion_job_parts/_worker.py`（手动 Ingest 簇 gap-fill 重接，Phase 1）、`services/investigation_persistence.py`（L2 stale 比对）、`services/document_extractor.py` + `services/extractors/markitdown_extractor.py`（extraction_method 返回）、`prompts.py`（结构化输出段）、`httpserver/config.py`（episode 预算 Settings）、`routes/llm_endpoints/_analysis.py`（trigger_source/响应字段）、`routes/case_analysis_endpoints/_case.py`（reanalyze）、`routes/file_analysis.py`（新：estimate/run/run 状态/版本链）。

**C++**：无（D2；红线 1/6 仅约束性行为）。

**Web**：`pages/LLMDescriptions.jsx`、`pages/Files.jsx`、任务详情视图（partial/stale/extraction 徽标）、簇详情视图（related_file_summaries）、`services/llmService.js`、`services/caseAnalysisService.js`、`locales/en.js`、`locales/zh.js`。

**测试**：pytest（schema/原子性/判定/归档/编排/parser/探测 mock/stale/补摄）、vitest（徽标/partial/服务封装）、test_image.img 手工冒烟（Phase 2/5/7）。
