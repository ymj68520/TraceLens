# InvestigationService（二次调查域：services/investigation/ 子包 + investigation_service.py + investigation_persistence.py + investigation_evidence.py + evidence/ + claim_provenance_reader.py + citation_validation.py）

> **一句话**：分析员主导的二次调查域——以 `(task_id, evidence_key)` 为证据身份，把初次流水线产出（`_files.db`/`_events.db`）当作只读源，在每任务 `investigation.db` 里维护"快照 → 版本化二次分析 → 结论采纳 → 事件语义版本刷新 → 报告证据绑定"的完整审计链，并用严格只读 Reader 与 D4b 活任务写边界保证 fail-closed。

## 1. 为什么有这个模块

初次分析（LLM 批量描述）是机器产出、不可篡改；但取证工作真正发生的地方是"分析员看了证据之后写下推理、同事复核、最终采纳进报告"。这个域要解决四件事：

1. **证据身份与信任边界**：证据键必须规范化且永不跨任务解析；数据库路径只信 C++ `get_task` 返回值；
2. **版本化与不可变**：二次分析是状态机（queued→running→review_pending→accepted/rejected/invalid/failed），redo 生成新版本行而非改旧行；分析员笔记在提交时冻结快照；
3. **引用落地（grounding）**：LLM 声称的每条 claim 只能引用冻结信封里的证据 ID，FACT 无有效引用降级为 HYPOTHESIS；
4. **事故恢复**：重启/关机/任务被删时，任何终态写入不得复活不存在的存储。

注意本域存在**两代实现**（见第 6 节）：规范栈是 `investigation/` 子包（schema v7，ServiceManager 管理的路由全走它）；legacy 栈是 `investigation_service.py` + `investigation_persistence.py`（schema v3，含 final-report 装配编排，当前无路由入口）。

## 2. 在系统中的位置

- **谁调用它（规范栈）**：routes/investigation.py（`POST /api/investigation/analyses` 202 + 精确 ID 轮询，:120；snapshots/events/evidence/graph 全套）；routes/investigation_workbench.py（远程兼容门面，最终报告读 R2 narrative）；routes/report_evidence.py（R1 绑定）；routes/report_generation.py（R2 准入）。ServiceManager 持有 InvestigationCaptureService/Review/Event/Graph/Read/ReportEvidence 六个惰性服务与 SecondaryAnalysisExecutor、EventRefreshExecutor 两个启动期执行器（service_manager.py:430-643，均要求 cpp_backend_ready）。
- **它调用谁**：CppBackendService（任务与库路径）；LLMService（chat_completion/analyze）；GraphitiService（图组合的 Base KG，惰性注入）；SQLite（investigation.db 与只读源库）。
- **它被谁依赖**：forensic_report 的 R2 准入直接读本域的 report_evidence/evidence_snapshots 表（generation.py:113-281）。

## 3. 核心概念与设计

**（a）证据键与解析（evidence/ 子包）。** 冻结格式：`file:<normalized_path>` 与 `cluster:v1:<unix_minute>:<percent-encoded event_type>`（keys.py 模块头）。`parse_evidence_key`（keys.py:53-85）是纯函数：file 键经 `normalize_evidence_path` 规范化；cluster 键严格拒绝畸形 percent-escape 与非 UTF-8（`_decode_event_type`，:26-41，因为 `unquote` 的 U+FFFD 替换会让不同坏键坍缩成同一身份）。`EvidenceResolver`（resolver.py，R1-R8 不变量）只读打开 `get_task` 给出的库，文件走精确 path 匹配、cluster 按 `(minute, event_type)` 重算，任何"找不到"都 fail-closed 抛 `EvidenceNotFoundError`，而库打不开是 `EvidenceStoreError`（exceptions.py 明确区分 404 与 503 语义）。

**（b）快照与仓储（investigation/repository.py，schema v7）。** `SUPPORTED_SCHEMA_VERSION = 7`（:103），表族：`evidence_snapshots`（:110）、`secondary_analyses`（:155）、`analysis_claims` + `claim_evidence_refs`（:239/:253）、`investigation_events` / `_versions` / `_evidence`（:312/:322/:337）、`investigation_event_refreshes`（:420/:448）、`report_evidence`（:600）。关键机制：

- 构造函数会建目录/迁移/自愈，`open_existing`（:713）则拒绝不存在的库——D4b 终态写入专用；
- 状态机以 `SECONDARY_TRANSITIONS` 表达（models.py:138-148）：`queued→running|failed`、`running→review_pending|failed`、`review_pending→accepted|rejected|invalid`，终态集合零出度（:150-157）；
- `persist_claims`（:2041）在**写事务内**重新推导允许引用集（G11），调用 grounding 纯函数后落库；
- `review_analysis`（:1815）单事务替换旧 accepted 并执行落地规则；`claim_event_refresh`（:2600）原子认领。

**（c）快照载荷模型（investigation/models.py）。** `FileSnapshotPayload`（:18-44）冻结文件初态（含初次 LLM 描述原样）；`ClusterSnapshotPayload`（:45-64）的 initial_* 一律 None——簇身份是 2 元组而簇分析写在 3 元组粒度，宁可空也不编造（S7）。`acquisition.py` 在捕获时刻用 `mode=ro` 重读源库并在**写事务之外**完整构造 `SnapshotCandidate`；`canonical_json`（S8）保证同输入同字节。

**（d）Grounding（investigation/grounding.py）。** 纯函数、无 DB 无 LLM：`derive_allowed_evidence_ids`（:29）只从冻结信封推导（G2-G4）；`GroundingValidator`（:46，`_validate_one` :65）用**精确规范 ID 匹配**（不解释 LLM 的 ref 字符串），无效引用剥离并记 warning；FACT 无有效引用降级 HYPOTHESIS（G7）；`grounded` 只表示"引用合法"不代表语义证实（G8）。`compute_analysis_grounding`（:103）聚合为 valid/partially_grounded/invalid。

**（e）执行器（E1-E11 不变量，execution.py:3-15）。** `SecondaryAnalysisExecutor.submit`（:146-210）在准入锁内**先持久化 queued 行再启动后台任务**（E1）；canonical 化 related keys（parse→dedupe→去自引用→排序，保证同输入同 input_hash）。`_execute`（:241-446）：existing-store-only 打开（:254）→ `queued→running` 认领（输家直接退出，:263-277）→ 信封哈希 `hmac.compare_digest` 复验（:279-291）→ schema/prompt 兼容表（:316-329）→ prompt 只由信封构建（E3，:340）→ LLM 错误分类为稳定 error_code（`_classify_llm_error`，:53-66，DB 里不落内部 URL/栈）→ 按 prompt 输出契约落 review_pending（`complete_analysis_for_review`，E5 永不自动 accepted）。**D4b 活任务写边界**（live_store.py:35-76）：终态写入前重新 get_task 校验存活与路径身份，任一不确定即丢弃结果不写（防复活已删任务的库）。重启恢复（E9，:514-577）分页扫描全部任务，把 stale queued/running 判 `service_restart`。`EventRefreshExecutor`（event_refresh_execution.py）镜像同一纪律处理事件语义刷新（V2 信封、claim 的 supports/contradicts 关系）。

**（f）读侧与图。** `InvestigationGraphReader`（graph_reader.py）是唯一 GET 通道：`mode=ro + PRAGMA query_only`，损坏/版本不支持→`EvidenceStoreError`（fail closed），绝不把"读不了"伪装成"没有调查数据"（B2/B3）。`InvestigationReadService`（read.py，C9a）在此之上提供证据清单/单快照/精确 claim 读，缺库即"无发现"。`InvestigationGraphService`（graph.py，C8b）组合 overlay（本域不可变行）与 Base KG（Graphiti），错误不对称是冻结契约：Base KG 挂了→`base_graph_available=false` + 固定警告 + HTTP 200；investigation 库挂了→503；两边实体永不按显示名合并（G9）。`ReportEvidenceService`（report_evidence.py，R1）：`analysis_id` 是分析员显式钉扎的"同一证据的某个 accepted 分析"，写入事务内三重复核（同任务/同证据/状态 accepted），绝不是"最新 accepted"指针。

**（g）legacy 栈（investigation_service.py / investigation_persistence.py / investigation_evidence.py / investigation_errors.py）。** `InvestigationPersistence`（schema v3，:36）提供 `get_investigation_db_path`（:68-81，files.db → 同目录 investigation.db）、`accept_analysis`（invalid 不可采纳、partial 需显式确认）、`recover_interrupted_jobs` 等同族机制；`InvestigationService` 类（investigation_service.py:188-1697）在其上编排 bootstrap 种子事件（:409-469）、二次分析作业（:662-919，含 `_ground_claims` :921-981）、事件版本刷新（:1086-1194）、以及 4A-4E+final 报告装配编排（:1292-1600）。`investigation_evidence.py` 定义旧键工具与上限常量（MAX_CLUSTER_EVENTS_FOR_LLM=50、MAX_RELATED_EVIDENCE=20、MAX_CONTENT_CHARS=8000，:20-22）；`investigation_errors.py` 是域错误层次；`claim_provenance_reader.py` 用 `mode=ro` 读单条历史事件 claim 及其证据链（`get_claim`，:39-65）；`citation_validation.py` 是纯函数引用图构建器：CIT- 前缀编号（:22）、`CitationGraphBuilder.build`（:222）对 dataset 校验证据 report-ready/快照存在/钉扎分析合法并输出自哈希（:149）。

## 4. 工作流程走读：一次二次分析（规范栈）

`POST /api/investigation/analyses`（202）→ `executor.submit(task_id, evidence_key, analyst_note=...)`（execution.py:146）→ capture 主证据快照（CaptureService.capture，service.py:34-48，故意做第二次 get_task 验活）→ canonical 化 related → 准入锁内 `create_analysis`（冻结 V2 信封 + input_hash）→ `asyncio.create_task(_execute)` → 认领 running → 哈希复验 → `build_user_prompt(envelope)`（E3）→ `chat_completion` → `parse_structured_analysis_response`（structured.py:30，拒绝 markdown 围栏/重复键/JSON 常量）→ `complete_analysis_for_review`（repository 内做 grounding 重推导）→ 前端轮询 `GET /analyses/{id}`（严格 Reader）→ 分析员 `POST .../review`（review.py:26-58 → `review_analysis` 单事务）→ accepted 结果进入 R1/R2 报告链。

## 5. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| CppBackendService | 唯一可信任务/库路径来源；D4b 写边界依赖它验活 |
| LLMService | 执行器唯一的推理通道；输出必须过结构化+grounding 双关 |
| forensic_report（R1/R2） | report_evidence 表与 evidence_snapshots 是报告准入信封来源 |
| GraphitiService | 图组合的 Base KG（惰性 lambda 注入，宕机降级不熔断端点） |
| routes/investigation、investigation_workbench、report_evidence、report_generation | 规范栈的全部 HTTP 面 |
| final_report_*（见 ForensicReportService.md） | legacy 装配链的下游，仅由本域 legacy 类编排 |

## 6. 注意事项与已知问题

- **双栈并存**：legacy `InvestigationService` 类当前**没有任何路由实例化**（全仓只有 `report_rendering.py:499` 复用其 `extract_json_payload`）；4A-4E/final 装配编排因此处于"机制完整、无线上入口"状态，Workbench 的 final-reports 端点实际读 R2 narrative manifest。两套 schema（v3 与 v7）的 investigation.db 互不兼容，排查时先看 `PRAGMA user_version`。
- **`CancelledError` 后的同步清理**：execution.py:404-432 特意用同步 transition（取消态下任何 await 会重抛 CancelledError），这段是少数允许阻塞事件循环的例外，别"顺手优化"成异步。
- 执行器初始化在 ServiceManager 里只有 12s 预算；恢复扫描按任务分页（page_size=100），任务很多时启动恢复可能吃满预算——超时属于容忍路径（服务仍启动，恢复不完整）。
- 事件语义版本与事件"needs_refresh"标记联动：采纳分析会 `_mark_related_events_dirty`（repository.py:1769-1813），忘记这层传播会导致报告读到陈旧语义。
- legacy `investigation_service.get_job` 的内存作业字典重启即失（:1023-1032），持久状态以 SQLite 为准（`get_job_async` 兜底，:1034-1053）。

## 7. 如何验证（python_service/tests/unit/）

- 规范栈：`investigation/test_investigation_repository.py`（状态机/迁移/v7 校验）、`test_investigation_execution.py`（E1-E11）、`test_investigation_grounding.py`（G 规则）、`test_investigation_secondary.py`、`test_investigation_completion.py`、`test_investigation_refresh_execution.py`、`test_d4b_task_deletion_boundary.py`（活任务边界）、`test_phase_c_*`（六条端到端流）、`test_investigation_paths.py`、`evidence/test_keys.py`、`evidence/test_resolver.py`；路由层 `test_investigation_routes.py`（202+轮询）、`test_investigation_*_routes.py`、`test_report_evidence_routes.py`、`test_service_manager_investigation.py`。
- legacy 栈：`test_investigation_persistence.py`、`test_investigation_evidence.py`、`test_claim_provenance_reader.py`、`test_report_dataset.py`、`test_citation_validation.py`。
- 手工链路：`POST /api/investigation/analyses` → 轮询至 review_pending → `POST .../review {"decision":"accepted"}` → `GET /api/investigation/evidence`；`sqlite3 <task>/investigation.db "PRAGMA user_version"` 应为 7。

**最后更新**: 2026-08-23（新建，解释式）
