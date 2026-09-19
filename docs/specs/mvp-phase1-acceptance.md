# MVP 第一节点验收（甲方）范围与实施规范

> 分支：`mvp/phase1-acceptance`（自 Dev `58f205b` 切出，携带在途 Graphiti 门控 + phi-4 配置基线 `1072421`）
> 状态：定稿（本文件即本分支的验收口径）
> 关联：`docs/specs/llm-throughput-hardening.md`（Graphiti phi-4 / 前台门控的上游 SPEC）

---

## 1. 背景与目标

甲方第一节点验收 MVP。原则：**页面与模块入口面不减（总功能数量不变），重排深度**——
削减"组合案件"与"调查工作台"两个模块的内部功能，取消事件的 LLM 分析并使其不作为证据；
作为补偿，报告页面增加"文件时间线"与"文件标签→相关事件"两项能力，保持整体功能总量不变。

**2026-09-18 追加（第二次范围决策）**：甲方再裁剪**内存取证**与 **OSS 分析**两个模块——
此两模块整体移出 MVP 验收面（导航入口隐藏、页面不可达、分析端点 503），不受上述
"入口面不减"原则约束；机制沿用 §4.3 的开关-门控模式（§4.6/§4.7）。

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
| 调查工作台 | **削减**：LLM 二次分析/事件重摘要停用，Graph Tab 隐藏；cluster 事件播种保留（v7，2026-09-19 修订），事件仍不入报告证据；只读浏览与文件证据绑定保留 | §4.4 |
| 内存取证 | **裁剪（2026-09-18 追加）**：导航/页面移出验收面；CLI 旁路与 C++ 只读端点保留但不在验收范围 | §4.6 |
| OSS 分析 | **裁剪（2026-09-18 追加）**：导航/页面移出验收面，Python AI 端点 503；C++ OSS 端点本就未挂载（运行时 404），不动 | §4.7 |
| Graphiti 摄入大模型 | **固定 phi-4**（microsoft/phi-4，非推理 instruct 模型） | §3 |

Feature flags（`python_service/httpserver/config.py`，pydantic-settings，env 可覆盖；MVP 分支默认值即验收形态）：

| 环境变量 | 默认 | 含义 |
| --- | --- | --- |
| `EVENT_LLM_ANALYSIS_ENABLED` | `false` | 事件（簇）LLM 分析总开关 |
| `COMBINED_CASE_ENABLED` | `false` | 组合案件（跨镜像）功能开关 |
| `WORKBENCH_LLM_ENABLED` | `false` | 工作台 LLM 二次分析/事件重摘要开关 |
| `MEMORY_FORENSICS_ENABLED` | `false` | 内存取证模块开关（§4.6，裁剪恢复逃生舱） |
| `OSS_ANALYSIS_ENABLED` | `false` | OSS 分析模块开关（§4.7，裁剪恢复逃生舱） |
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

事件作为报告证据的唯一自动来源是工作台 bootstrap 的 cluster_seed。MVP：

1. bootstrap **保留 cluster 播种**（2026-09-19 修订：迁移到 repository-v7 单一写路径，
   `services/investigation_service.py` `bootstrap()`；否则工作台时间线永远为空、
   前端在 `initialized=false` 上无限重试 bootstrap）。播种复用集群既有 LLM 摘要，
   不发起任何 LLM 调用；事件→报告证据的排除由下述 2/3/4 兜底；
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
  - bootstrap cluster_seed 经 repository-v7 播种集群事件（见 §4.2 2026-09-19 修订）；
  - 只读端点（overview/events/evidence/graph/final-reports）保留。
- 前端 `pages/Investigation/Investigation.jsx`：
  - `MIDDLE_TABS`（:13-16）在开关关闭时移除图谱 Tab，仅保留时间线；
  - `AnalysisWorkspace` 的 LLM 按钮（二次分析/事件重摘要）隐藏；
  - 报告证据选择器（文件证据）保留。

### 4.6 内存取证裁剪（MEMORY_FORENSICS_ENABLED=false，2026-09-18 追加）

足迹事实（恢复时直接引用）：内存取证是 **CLI 旁路子命令**（`--memory-analyze` /
`--vol-symbols-dir`，`AnalysisOrchestrator.cpp:179-181` 分流至 `runMemoryAnalysis`），
产物为镜像旁库 `<image>_memory.db`（6 表，`memory_analysis_sql_tables.h`）；
HTTP 侧仅有 5 个只读端点 `/api/forensics/memory/{summary,processes,network,bash-history,boot-info}`
（`MemoryForensicsRoutes.cpp`，经 `ForensicsRoutes` 挂载，无库时 404）；
前端为 `/memory` 页 + 导航"内存取证"。**不在任务流水线上**：任务创建/分析管线零引用，
无 SceneType、无自动触发、无库迁移。

裁剪机制：

- 后端：`MEMORY_FORENSICS_ENABLED=false`（默认），经 `GET /api/system/features` 下发
  `memory_forensics_enabled`；Python 侧无内存取证端点，无需 503 门。
  C++ 只读端点与 CLI 子命令**保留不动**（§4.3 先例：C++ 数据面保留；无副作用，
  无 `_memory.db` 时自然 404）。volatility3 依赖、插件资源、`--memory-analyze` 帮助文本不动。
- 前端：`Layout.jsx` 导航"内存取证"按开关过滤；`routes.jsx` `/memory` 套
  `<FeatureGate flag="memory_forensics_enabled">`（路由保留，深链渲染停用告示，
  同 §4.3 /cases 模式）。
- 恢复：设 `MEMORY_FORENSICS_ENABLED=true` 重启 python 服务即整模块回归（导航/页面/CLI）。

### 4.7 OSS 分析裁剪（OSS_ANALYSIS_ENABLED=false，2026-09-18 追加）

足迹事实（恢复时直接引用）：OSS = 阿里云对象存储取证（C++ `OSSAnalyzer` + `oss.db` 三表 +
Python LLM 过滤/分析）。**C++ OSS 路由从未挂载**（`HTTPserver.h:91-96` 未实例化，
运行时 404——编译但不服务），前端 `/oss` 页调用的即是这批死端点；Python
`/api/forensics/oss/ai/{filter,analyze}` 活但无前端调用方。**不在任务流水线上**：
独立手动入口，`platform_analyze` 开关不涉及。

裁剪机制：

- 后端：`OSS_ANALYSIS_ENABLED=false`（默认），`routes/oss_analysis.py` 两个 POST
  （`/api/forensics/oss/ai/filter`、`/api/forensics/oss/ai/analyze`）→ 503
  （`require_oss_analysis` 门，同 §4.3 `require_combined_case` 模式）；
  `GET /api/system/features` 下发 `oss_analysis_enabled`。C++ 侧不动（本就 404）。
- 前端：`Layout.jsx` 导航"OSS 分析"按开关过滤；`routes.jsx` `/oss` 套
  `<FeatureGate flag="oss_analysis_enabled">`。
- 恢复：设 `OSS_ANALYSIS_ENABLED=true` 重启 python 服务即恢复 AI 端点与入口
  （注意：C++ 数据面端点要真正可用是另一个量级的接线工作，见
  `docs/modules/cpp/network/HTTPServer.md` 对 12 个未挂载端点的记录）。

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
- [ ] 导航无"内存取证/OSS 分析"入口；`/memory`、`/oss` 深链渲染停用告示；
      `POST /api/forensics/oss/ai/*` → 503
- [ ] 工作台无图谱 Tab、无 LLM 二次分析按钮；文件证据绑定与报告生成正常
- [ ] 最终报告页出现文件时间线（四时间戳、min→max 轴）；点击报告内文件标签弹出文件+相关事件抽屉
- [ ] python 单测 / web 测试 / C++ 构建全绿

## 8. RocksDB 替换 SQLite——已评估并撤销（决策记录，2026-09-18）

> **决定**：不替换数据库，全系统恢复并保留 SQLite。本节仅保留决策要点，
> 原 R0–R6 分阶段设计与试点实现（提交 `d3ff1de`/`53987e8`/`6c18d20`）已于
> `26870fe`/`5c87813`/`a0541bc` 整体回退。

**评估过程中确立的事实**（如未来重提此方向，直接引用，勿重复试点）：
- 每任务一组 SQLite 库（raw/events/files/filtered/平台库）+ 审计/案件/调查/报告库；
  任务库为 C++/Python 两侧共写，其余各库单语言独占（案件/调查/报告=仅 Python，审计=仅 C++）。
- rocksdict（Python 绑定）固定 comparator 名 "rocksdict"，与标准 librocksdb
  （BytewiseComparator）的库文件互不兼容——两侧无法打开彼此的存储。
- RocksDB 为单进程写锁；多进程只能一写多读（C API `open_for_read_only` + WAL 重放，
  快照隔离与新鲜度语义已用 ctypes 探针实测验证）。
- 可行的终态设计是"单写者委托式"：C++ 唯一持写、Python 读走 ctypes C API、
  写走 HTTP 委托端点（对称于既有 `recordFileAnalysisResult`）。

**撤销原因**：甲方决定不更换数据库，保留 SQLite 终态。依赖清理：
rocksdict（venv）与 librocksdb-dev/librocksdb8.9（系统）均已卸载。

### 4.5 补遗：workbench investigation 库 v3/v7 双模块治理（已完成）

活体验证暴露的历史欠账：`investigation_persistence.py`（v3 结构）与
`investigation/repository.py`（v7 结构）曾对同一 investigation.db 各自建表，
同名表列集不同，导致新任务首次证据绑定必 503。治理结果（`36c151e`）：

- **v7 是唯一 schema**：`_ensure_v7_store` 保证新任务建库即 v7；空的 v3 遗留库
  自动重建为 v7；含数据的 v3 库 fail-closed（提示人工迁移，现场无此类库）；
- **persistence 不再污染 v7**：`_ensure_schema` 对 v7 库直接返回，永不降级
  `user_version`；
- **recover 查询容错**：v7 库上缺失的 v3 表使 recovery 变为 no-op；
- **辅助表供给**：`analyst_notes` 与 `evidence_analysis_versions`（v3 独有、
  无同名冲突）由 `_ensure_v7_store` 按需补建，分析员笔记与 recovery 查询可用；
- **事件类 notes**：被上游 canonical-schema 守卫挡下（409，R1 设计即如此），
  与本治理无关。

`bootstrap` / file 证据绑定（200）/ cluster 键拒绝（422）/ notes 守卫（409）
已在活体 v7 库上复测通过。

## 9. 开放问题（不阻塞本节点）

1. RocksDB 是否必须覆盖 C++ 取证库（raw.db 等）——本 SPEC 按全量设计、按 §8 分阶段交付；
   若甲方口径仅为"分析阶段数据库"，R1-R3 可裁剪。
2. phi-4 固定后，`LLM_TEXT_MODEL` 变更不再影响摄入（预期行为，需在部署文档注明）。
