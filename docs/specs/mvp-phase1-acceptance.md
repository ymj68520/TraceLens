# MVP 第一节点验收（甲方）范围与实施规范

> 分支：`mvp/phase1-acceptance`（自 Dev `58f205b` 切出，携带在途 Graphiti 门控 + phi-4 配置基线 `1072421`）
> 状态：定稿（本文件即本分支的验收口径）
> 关联：`docs/specs/llm-throughput-hardening.md`（Graphiti phi-4 / 前台门控的上游 SPEC）

---

## 1. 背景与目标

甲方第一节点验收 MVP。原则：**页面与模块入口面不减（总功能数量不变），重排深度**——
削减"组合案件"与"调查工作台"两个模块的内部功能，取消事件的 LLM 分析并使其不作为证据；
作为补偿，报告页面增加"文件时间线"与"文件标签→相关事件"两项能力，保持整体功能总量不变。

## 2. 范围决策总表

| 模块 | 决策 | 实现机制 |
| --- | --- | --- |
| 取证阶段（镜像解析→raw.db/events.db/files.db/平台库） | **不变** | 不改动（存储引擎替换见 §8） |
| 数据库 SQLite → RocksDB | 替换（分阶段交付，见 §8） | 存储接口 + CF 映射 + 查询面重写 |
| 分析阶段 | **以文件为核心**：完成判定 = 范围内文件全部分析完成 **且** Graphiti 摄入完成 | §5 |
| 事件 LLM 分析 | **取消**（事件保留原始数据与展示，`events.llm_*` 恒为 NULL） | §4.1 |
| 事件作为报告证据 | **排除**（文件仍可为证据） | §4.2 |
| 报告页面 | **整体功能保留**，新增文件时间线 + 文件标签→相关事件 | §6 |
| 组合案件（/cases、/analysis-center、跨镜像分析） | **削减**：入口隐藏，创建/分析类端点停用 | §4.3 |
| 调查工作台 | **削减**：LLM 二次分析/事件重摘要停用，Graph Tab 隐藏，事件证据不播种；只读浏览与文件证据绑定保留 | §4.4 |
| Graphiti 摄入大模型 | **固定 phi-4**（microsoft/phi-4，非推理 instruct 模型） | §3 |

Feature flags（`python_service/httpserver/config.py`，pydantic-settings，env 可覆盖；MVP 分支默认值即验收形态）：

| 环境变量 | 默认 | 含义 |
| --- | --- | --- |
| `EVENT_LLM_ANALYSIS_ENABLED` | `false` | 事件（簇）LLM 分析总开关 |
| `COMBINED_CASE_ENABLED` | `false` | 组合案件（跨镜像）功能开关 |
| `WORKBENCH_LLM_ENABLED` | `false` | 工作台 LLM 二次分析/事件重摘要开关 |
| `GRAPHITI_LLM_MODEL` | `microsoft/phi-4` | Graphiti 摄入 LLM（空值也回落 phi-4，即"固定"） |
| `GRAPHITI_INGEST_WAIT_TIMEOUT_MIN` | `720`（C++ ConfigManager） | FINALIZING 等待摄入上限（与 Python 端 `GRAPHITI_JOB_TIMEOUT_HOURS=12` 对齐），0 = 恢复旧"不等待"行为 |

前端通过 `GET /api/system/features` 读取前三个开关（模块级缓存 + `useFeatures()` hook）。

## 3. Graphiti 摄入 LLM 固定 phi-4

**缺口修复（关键）**：生产摄入路径 `httpserver/services/graphiti_parts/_core.py:125 _build_graphiti_config()`
直接用 `settings.llm_text_model` 构造 `GraphitiConfig`，绕过了 `from_env()` 的 `GRAPHITI_LLM_MODEL`
槽位——任务图/案件图摄取实际仍在用 nemotron。修复：

1. `httpserver/config.py` 新增 `graphiti_llm_model: str = Field(default="microsoft/phi-4", env="GRAPHITI_LLM_MODEL")`；
2. `_build_graphiti_config()` 改用 `(settings.graphiti_llm_model or "").strip() or "microsoft/phi-4"`；
3. `graphiti_integration/config.py from_env()` 回退链改为 `GRAPHITI_LLM_MODEL` → **`microsoft/phi-4`**
   （去掉 `LLM_TEXT_MODEL` 环节：管线主模型将来换型不再影响摄入）；
4. `small_model` 继续跟随 `llm_model`（沿用 llm-throughput SPEC B2 决策）；
5. `.env.example` 补 `GRAPHITI_LLM_MODEL=microsoft/phi-4` 文档。

验收：`tests/unit/test_graphiti_model_config.py` 更新为固定 phi-4 语义；新增 `_core.py` 配置构造断言。

## 4. 功能削减与停用

### 4.1 事件 LLM 分析取消（EVENT_LLM_ANALYSIS_ENABLED=false）

- 后端：
  - `routes/llm_endpoints/_analysis.py` `POST /api/llm/analyze-event-cluster` → 503；
  - `routes/event_cluster_analysis.py` `POST /event-cluster-analysis/run` → 503
    （`estimate` 为纯 SQL 预估，保留；`GET .../analyses` 历史记录查询保留）；
  - 管线 Round C 跳过：`services/case_analysis/case_analysis_parts/_pipelines.py:363-385`；
  - Graphiti 摄取端 `fetch_pending_cluster_analyses` 天然取不到新行，无需改动。
- 前端：
  - `pages/Timeline.jsx` 自动分析 effect（268-334）与 AI 分析/重分析按钮（376-459）按开关守卫；
  - 簇抽屉 `ClusterInvestigationDrawer` 的 AI 面板按开关隐藏。
- 兼容性：C++ 时间线 `TimelineQueries.cpp:135` 读 `events.llm_*`（ai_cols）在无分析时已优雅降级
  （`analysis_id = null`），展示面零改动。

### 4.2 事件不作为报告证据

事件作为证据的唯一自动来源是工作台 bootstrap 的 cluster_seed
（`services/investigation_service.py:454-467` `link_evidence(..., "event_cluster", ...)`）。MVP：

1. bootstrap 保留（工作台 overview 初始化），但**跳过 cluster 证据播种与快照**；
2. `routes/report_evidence.py` `_canonical_key`（:46-50）拒绝 `cluster:` 前缀键 → 422；
3. 报告装配兜底过滤：`services/forensic_report/generation.py` admission（:113-146）与快照装载
   （:269-274）跳过 `evidence_type == "cluster"`；
4. 案件报告 `_load_event_cluster_evidence`（`services/case_analysis/report_generator.py:250-258`）
   按开关跳过（组合案件已停用，此为休眠保险）。

文件证据（`file:<path>`）不受影响：证据绑定、report_evidence 选择器、报告生成全部照常。

### 4.3 组合案件削减（COMBINED_CASE_ENABLED=false）

- 后端 `routes/multi_analysis.py`：`POST /api/llm/cases`、`/{id}/tasks`、`/{id}/associate-tasks`、
  `/multi-image-analysis`、`/cases/smart-create`、`/{id}/incremental-analysis`、`DELETE` → 503；
  `GET /api/llm/cases*` 保留（返回空/既有数据只读）。
- 前端：隐藏导航 `/cases`、`/analysis-center`（`components/Layout/Layout.jsx:26,30`）；
  任务页"创建案件/加入案件"入口按钮隐藏。
- C++ `/api/cases`（CaseCRUDRoutes.cpp）数据面保留不动（无副作用）。

### 4.4 调查工作台削减（WORKBENCH_LLM_ENABLED=false）

- 后端 `routes/investigation_workbench.py`：
  - `POST /{task}/evidence/analyze`（:291）与 `POST /{task}/events/{id}/refresh`（:354）→ 503；
  - bootstrap cluster_seed 跳过证据播种（见 §4.2）；
  - 只读端点（overview/events/evidence/graph/final-reports）保留。
- 前端 `pages/Investigation/Investigation.jsx`：
  - `MIDDLE_TABS`（:13-16）在开关关闭时移除图谱 Tab，仅保留时间线；
  - `AnalysisWorkspace` 的 LLM 按钮（二次分析/事件重摘要）隐藏；
  - 报告证据选择器（文件证据）保留。

## 5. 分析流水管线重定义（以文件为核心 + 完成判定）

流水：`镜像进入 → 取证阶段（不变）→ [存储引擎 RocksDB，见 §8] → 文件分析 → Graphiti 摄入 → 完成`。

**完成判定改造**（现状：`TaskManagerAnalysis.cpp:709-710` FINALIZING 触发 fire-and-forget 摄入后立即
COMPLETED，不等 Graphiti）：

1. 文件维度：C++ 主链 `LLM_ANALYSIS`（:444-503）同步完成 `analyzeAllFiles/analyzeSmartFiles`
   后才进入 FINALIZING，"范围内文件全部分析完成"在此天然成立（范围 = filter_profile →
   filtered.db）；口径以 `analysis_progress` / `file_analyses`（`analysis_stats` total/analyzed/pending）
   为准，写入任务日志。
2. 摄入维度：FINALIZING 改为**等待摄入完成**：
   - `async_ingest` 返回 job_id 后轮询 `LLMPythonProxy::get_job_status(job_id)`
     （`LLMPythonProxy.cpp:141`，现成的 `wait_for_job_completion` 也可用），直至终态；
   - 轮询期间每轮刷新 `progress.phase_start_time` + `phase_description="等待知识图谱摄入"`（看门狗心跳，防误杀）；
   - `COMPLETED` → 任务 `COMPLETED`；`FAILED` → 重试 `async_ingest` 至多 2 次，仍失败 → 任务
     `FAILED`（error_details 注明 graphiti ingestion failed）；
   - 超时（`GRAPHITI_INGEST_WAIT_TIMEOUT_MIN`，默认 720，与 Python 端作业上限对齐）→ 任务 `FAILED`；
     设为 0 恢复旧"不等待"行为（逃生舱）。重试次数 `GRAPHITI_INGEST_RETRIES`（默认 2）、
     轮询间隔 `GRAPHITI_INGEST_POLL_SECONDS`（默认 10）。
3. 门控回环保持：`ingestion_gate.py:40-43` FINALIZING 自触发不自阻塞语义不变（gate 仅在
   LLM_ANALYSIS/PLATFORM_ANALYSIS 期间暂停摄入）。
4. 逻辑 Android 短路路径（:261-276）同样适用等待逻辑。

## 6. 报告页面

### 6.1 文件时间线（新增，"调查工作台时间线"同款交互、数据源换文件）

- 组件：`web/src/pages/Investigation/components/FileTimestampTimeline.jsx`（卡片列表风格对齐
  `InvestigationTimeline.jsx`），挂载于 `FinalReportViewer.jsx` 主列（报告头部之后）。
- 数据源：**筛选文件**（`case_analysis.filtered_files` 范围，无则全量）× 每文件四时间戳
  `crtime/mtime/atime/ctime`。**注意**：files.db（分类库）只有 mtime/ctime，四时间戳必须读
  filtered.db/raw.db（`FileFilter.cpp:277-295` 全四列）。
- 新端点：`GET /api/investigation/workbench/{task_id}/file-timeline`
  （实现落于 `/api/associations/file-timeline`，与 file-events 同面；python 读任务库路径，
  返回 `[{path,name,size,crtime,mtime,atime,ctime,earliest,latest}]`，按最早时间升序 + `axis`）。
- 轴范围：全部文件四时间戳的 min → max；每文件渲染至多 4 个标记（创建/修改/访问/变更着色区分）。

### 6.2 文件标签 → 索引文件 + 相关事件（保留并接通）

- 现状：`components/case-intelligence/markdownRenderer.jsx` 支持 `[[file:<path>]]` 徽章，
  但 `ReportReaderContent.jsx:102` 把 handler 桩死为 no-op。MVP 接通：
  - 点击文件徽章 → 打开文件抽屉：文件基本信息 + **相关事件列表** +
    "在文件页打开"（`/files?task_id=...`）索引跳转；
  - 相关事件数据源：`events.db WHERE file_path = ?`（**不依赖 LLM 簇**——簇分析已停用，
    `FileClustersDrawer`/`/api/associations/file-clusters` 的簇关联在 MVP 下为空）。
  - 新端点：`GET /api/associations/file-events?task_id=...&path=...`
    （exact path 命中为空时按 basename LIKE 兜底）。
- `[[event:...]]` 徽章 handler 保留（MVP 下不会再产生新事件分析引用，历史报告仍可跳时间线）。

## 7. 验收清单

- [ ] 两块 E01/测试镜像全链：任务在 Graphiti 摄入 COMPLETED 后才置 COMPLETED（看门狗零误杀）
- [ ] 摄入日志确认模型为 `microsoft/phi-4`（httpserver 生产路径，非仅 CLI）
- [ ] 时间线页无任何自动/手动事件 AI 分析动作；`events.llm_analyzed_at` 恒 NULL
- [ ] 报告证据列表无任何 `event_cluster`/`cluster:` 项；`POST /api/reports/evidence` 提交 cluster 键 → 422
- [ ] 导航无"案件组合/研判中心"入口；对应创建/分析 API → 503
- [ ] 工作台无图谱 Tab、无 LLM 二次分析按钮；文件证据绑定与报告生成正常
- [ ] 最终报告页出现文件时间线（四时间戳、min→max 轴）；点击报告内文件标签弹出文件+相关事件抽屉
- [ ] python 单测 / web 测试 / C++ 构建全绿

## 8. RocksDB 替换 SQLite（设计与分阶段交付）

**范围**：每任务分析库（raw.db、events.db、files.db、filtered.db、平台库 android/windows/linux/oss）、
审计库、案件库、investigation.db、reports.db。分布式 C/S 的 PostgreSQL 栈不在范围内。

**接缝**（现状无统一仓储层）：
- C++：`DatabaseManager`（唯一连接封装）、`SQL/*.h`（schema 即代码）、`SQLiteHelper + Queries/*.cpp`（路由查询）、各 analyzer `Database/*` 写入类；
- Python：`case_analysis/file_schema.py`、`schema.py`、`db_utils.py`、`llm_service.persist_to_files_db`、`ingestion_job_parts/_worker.py`、`investigation/repository.py`、`graphiti_integration/database_reader/*`、`forensic_report/adapters/sqlite_task.py`。

**映射设计**：每库 → 一个 RocksDB 实例（目录同名去 `.db`），表 → Column Family；
主键/rowid → key（大端定长编码保证有序扫描），行 → MessagePack/FlatBuffers value；
外键/索引（`files.path`、`events.timestamp`、`file_path UNIQUE` 等）→ 独立索引 CF
（key=索引列值+rowid）支撑点查与范围扫；视图/统计（`file_summary`、`event_statistics`、
`timeline`、hourly_activity）→ 写入时同步维护的预聚合 CF；事务 → WriteBatch；
`ingested_at IS NULL` 类扫描 → 专门的 pending 索引 CF。

**分阶段**（✅ 已交付 / 🔜 待做）：
- ✅ **R0 依赖验证**：Python `rocksdict 0.3.29`（已入 `python_service/requirements.txt` 与 venv）；
  C++ `librocksdb-dev 8.9.1`（apt，含 librocksdb8.9 运行库）——两端 API 冒烟通过。
- ✅ **R1 存储基石 + 试点**：
  - Python：`python_service/storage/rocksdb_store.py`（CF 声明式打开/重开发现、字节进出、
    WriteBatch、前缀有序扫、`_meta` 记账；测试 9 例）；
  - Python 迁移工具：`storage/sqlite_migrate.py` + `scripts/migrate_sqlite_to_rocksdb.py`
    （表→CF、rowid 大端键/WITHOUT ROWID 走 `pk:` JSON 键、BLOB base64 编解码、DDL/列/键控
    元数据入 `_meta`、`--verify` 全量 parity；测试 7 例 + 仓库真实 `forensics_audit.db`
    583 行迁移校验演练通过）；
  - C++：`src/core/KVStore/KVStore.h`（接口：put/erase/get/write_batch/scan_prefix/
    count_prefix + `encode_rowid`）+ `RocksKVStore`（ListColumnFamilies 合并重开、父目录
    自建、异常传播 Status）；gtest 6 例（tests/CMakeLists.txt 按 rocksdb 是否存在条件注册，
    缺库机器跳过不阻塞）。
- ✅ **R2 写入面试点（raw.db 双运行窗口）**：
  - `src/core/KVStore/RowCodec.h/.cpp`：跨语言行编码（与 Python `encode_value` 字节级
    一致：sort_keys + compact + `\uXXXX` 转义 + BLOB `{"__blob_b64__":...}`），golden 测试
    双侧互锁；
  - `src/core/KVStore/SqliteRocksMirror.h/.cpp`：**整库镜像**策略——不逐个 hook 各 analyzer
    的 INSERT（TSK/native XFS/OSS 各有写入点），SQLite 落盘后一次性镜像到旁路 `.rocks`，
    幂等、源只读、SQLite 仍是真源；C++ `verify()` 用 XOR-SHA256 顺序无关校验，
    Python `verify` 已改为同一算法；
  - 主管线接线：`TaskManagerAnalysis.cpp` IMAGE_ANALYSIS 完成后镜像 `files`+`partitions`
    到 `<raw>.rocks`（`ROCKSDB_MIRROR_RAW=0` 关闭；任何镜像故障只记 WARNING 不失败流水线）；
  - 无 rocksdb 库的机器编译 throwing stub，二进制完整可构建；
  - gtest 9 例（含 Python 黄金字节互锁、篡改检出、幂等、WITHOUT ROWID）。
  - **引擎口径**：rocksdict 绑定固定 comparator 名 "rocksdict"，与标准 librocksdb
    （BytewiseComparator）写的库**互不兼容**——两侧存储引擎不互通是既定事实；跨语言
    契约 = 行字节格式（RowCodec==encode_value，双侧 golden 测试锁定）+ 键编码 + `_meta`
    约定。C++ 写的库用 C++ verify 验，Python 写的库用 Python verify 验。
- ✅ **R3 查询面（首段：镜像读路径）**：
  - `src/core/KVStore/RocksRawReader.h/.cpp`：镜像只读访问器（keying 元数据、rowid 点查、
    有序全表扫、行数），路径无 `CURRENT` 标记即抛异常——这是查询层回退 SQLite 的触发器；
    无 rocksdb 库机器编译 stub（同样抛异常，走回退）；
  - 首个接线：`SQLiteHelper::get_largest_files`（`/api/forensics/files/largest`）改为
    **RocksDB 优先回退 SQLite**——旁路 `.rocks` 存在且带 files keying 时内存过滤
    `size > 0` + 降序 + limit（响应带 `source: "rocksdb_mirror"`），否则原 SQL 路径不变；
    gtest 4 例（keying/点查/有序扫/largest 语义/缺库抛错）；
  - 聚合类查询（statistics/timeline JOIN）继续走 SQLite，待各自索引 CF 重写后迁移。
- ✅ **R4 Python 读侧（首段）**：`storage/rocks_mirror_reader.py`——C++ RocksRawReader
  对应物（`open_mirror_or_none` 语义、`list_cf` 全家声明打开、rowid 点查/有序扫/内存
  WHERE）；测试 4 例。r4 后续：graphiti database_reader/file_schema 接入该开关。
- 🔜 R5 案件/调查/报告库迁移；
- 🔜 R6 移除 SQLite 依赖（迁移工具已就绪；届时需选定单一引擎口径统一两侧）。

**风险**：SQL 语义（JOIN/GROUP BY/LIKE 搜索）需应用层重写，统计与搜索面工作量最大；
sqlite3 CLI 排障工具链失效（迁移工具的 `_meta` + 后续 dump 工具缓解）；R2-R4 期间双写
兼容窗口的回归成本。键/值编解码与 CF 命名已在 R1 定型（两端口径一致），后续阶段不再变动。

## 9. 开放问题（不阻塞本节点）

1. RocksDB 是否必须覆盖 C++ 取证库（raw.db 等）——本 SPEC 按全量设计、按 §8 分阶段交付；
   若甲方口径仅为"分析阶段数据库"，R1-R3 可裁剪。
2. phi-4 固定后，`LLM_TEXT_MODEL` 变更不再影响摄入（预期行为，需在部署文档注明）。
