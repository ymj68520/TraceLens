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
- **链路**：前端"调查工作台"页 → `/api/investigation/*` → 六个惰性服务 → 每任务 investigation.db；accepted 分析 → report_evidence → R2 报告信封。

## 3. 核心数据结构：schema v7 关键表

```python
# investigation/repository.py:109-133（节选）
CREATE TABLE IF NOT EXISTS evidence_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    evidence_type TEXT NOT NULL CHECK(evidence_type IN ('file', 'cluster')),
    normalized_path TEXT,
    unix_minute INTEGER,
    event_type TEXT,
    snapshot_json TEXT NOT NULL,
    captured_at INTEGER NOT NULL,
    UNIQUE(task_id, evidence_key),
    CHECK (
        (evidence_type = 'file'
            AND normalized_path IS NOT NULL
            AND unix_minute IS NULL
            AND event_type IS NULL)
        OR
        (evidence_type = 'cluster'
            AND normalized_path IS NULL
            AND unix_minute IS NOT NULL
            AND event_type IS NOT NULL)
    )
)
```

- `UNIQUE(task_id, evidence_key)`：证据身份的唯一性由 DB 约束兜底（capture_if_absent 的 ON CONFLICT 依赖它）；
- 判别 CHECK：file 证据必须带 normalized_path、cluster 证据必须带 (unix_minute, event_type)——**类型字段与载荷字段强绑定**，防"半个身份"入库；
- 不可变性不靠自觉：`trg_evsnap_no_update` 触发器直接 ABORT 任何 UPDATE（:137-143）。

```python
# investigation/repository.py:154-183（节选）
CREATE TABLE IF NOT EXISTS secondary_analyses (
    analysis_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    snapshot_id INTEGER NOT NULL REFERENCES evidence_snapshots(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN
        ('queued','running','review_pending','accepted','rejected','invalid','failed')),
    input_hash TEXT NOT NULL,
    input_envelope_json TEXT NOT NULL,
    prompt_version TEXT,
    description TEXT,
    summary TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT, review_pending_at TEXT, decided_at TEXT, decided_by TEXT,
    decision_reason TEXT, failed_at TEXT, error_code TEXT, error_message TEXT,
    grounding_status TEXT CHECK(
        grounding_status IS NULL
        OR grounding_status IN ('valid', 'partially_grounded', 'invalid')
    ),
    UNIQUE(task_id, evidence_key, version)
)
```

- `snapshot_id` 外键 ON DELETE RESTRICT：分析永远钉在一个具体快照上，快照不可删（本身也禁止 UPDATE），redo 是**新 version 行**指向可更新的新快照；
- `input_hash` + `input_envelope_json`：V2 信封冻结（执行时 hmac 复验）；`UNIQUE(task_id, evidence_key, version)` 保证版本串行；
- 状态机由两个触发器硬约束（:194-214）：非终态行只许合法迁移（`queued→running|failed`、`running→review_pending|failed`、`review_pending→accepted|rejected|invalid`），终态行禁止任何 UPDATE。

其余表族：`analysis_claims` + `claim_evidence_refs`（:239/:253）、`investigation_events` / `_versions` / `_evidence`（:312/:322/:337）、`investigation_event_refreshes`（:420/:448）、`report_evidence`（:600）。

## 4. 核心接口清单（规范栈）

| 接口（真实签名） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `InvestigationCaptureService.capture(task_id, evidence_key) -> EvidenceSnapshot` | 解析证据→二次 get_task 验活→capture_if_absent | 提交流程第一步 | 任务不活抛 EvidenceNotFoundError |
| `InvestigationRepository.capture_if_absent(resolved) -> EvidenceSnapshot` | 幂等捕获（已有即返回） | capture 服务（to_thread） | 跨任务证据抛 ValueError |
| `InvestigationRepository.create_analysis(snapshot, *, analyst_note, case_context, related_evidence, prompt_version) -> SecondaryAnalysis` | 冻结 V2 信封建 queued 行 | executor.submit | 事务内失败抛 |
| `SecondaryAnalysisExecutor.submit(task_id, evidence_key, analyst_note=..., ...) ` | 准入锁内先持久化后起后台任务 | routes/investigation.py | 返回 202 前即持久化 queued |
| `InvestigationRepository.review_analysis(...)` | 单事务决策并替换旧 accepted | review 服务 | 状态不合法抛 |
| `InvestigationRepository.claim_event_refresh(...)` | 原子认领刷新作业 | EventRefreshExecutor | 输家直接退出 |
| `InvestigationGraphReader`（各 get_*） | 唯一 GET 通道（ro+query_only） | Read/Graph 服务 | 损坏→EvidenceStoreError（503 语义） |
| `ReportEvidenceService.bind/...` | 显式钉扎 accepted 分析 | routes/report_evidence | 三重复核失败抛绑定冲突 |

## 5. 核心概念与设计

**（a）证据键与解析（evidence/ 子包）。** 冻结格式：`file:<normalized_path>` 与 `cluster:v1:<unix_minute>:<percent-encoded event_type>`（keys.py 模块头）。`parse_evidence_key`（keys.py:53-85）是纯函数：file 键经 `normalize_evidence_path` 规范化；cluster 键严格拒绝畸形 percent-escape 与非 UTF-8（`_decode_event_type`，:26-41，因为 `unquote` 的 U+FFFD 替换会让不同坏键坍缩成同一身份）。`EvidenceResolver`（resolver.py，R1-R8 不变量）只读打开 `get_task` 给出的库，文件走精确 path 匹配、cluster 按 `(minute, event_type)` 重算，任何"找不到"都 fail-closed 抛 `EvidenceNotFoundError`，而库打不开是 `EvidenceStoreError`（exceptions.py 明确区分 404 与 503 语义）。

**（b）capture_if_absent：幂等捕获的精确代码。** 这是"快照"语义的核心（repository.py:1474-1523）：

```python
# investigation/repository.py:1481-1521（节选）
# S1: existing snapshot wins; do not touch the source DB.
existing = self.get_snapshot(resolved.evidence_key)
if existing is not None:
    return existing

# Build the candidate fully OUTSIDE the write transaction (S5: mode=ro, no LLM).
try:
    candidate = build_snapshot_candidate(resolved)
except (EvidenceNotFoundError, EvidenceStoreError):
    # A concurrent winner may have just captured it (and source may have shifted).
    existing = self.get_snapshot(resolved.evidence_key)
    if existing is not None:
        return existing
    raise

with self._connect() as conn:
    conn.execute("BEGIN IMMEDIATE")  # S3
    conn.execute(
        """
        INSERT INTO evidence_snapshots
            (task_id, evidence_key, evidence_type, normalized_path,
             unix_minute, event_type, snapshot_json, captured_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id, evidence_key) DO NOTHING
        """,
        (candidate.task_id, candidate.evidence_key, candidate.evidence_type,
         candidate.normalized_path, candidate.unix_minute, candidate.event_type,
         canonical_json(candidate.payload), candidate.captured_at),
    )
    row = conn.execute(
        "SELECT * FROM evidence_snapshots WHERE task_id = ? AND evidence_key = ?",
        [self.task_id, candidate.evidence_key],
    ).fetchone()
    conn.commit()
```

四层并发/失败语义：先查后建（S1，已存在即赢）；候选体在**写事务之外**用 mode=ro 构造（S5，写锁不跨源库读取）；`BEGIN IMMEDIATE` 写锁（S3）；`ON CONFLICT DO NOTHING` + 事务内回读——两个并发捕获者只有一个的 INSERT 生效，但**都**能读到同一行返回同一快照。构造失败时再查一次（并发赢家可能刚刚赢下）。CaptureService（service.py:29-44）在 resolver 之外**故意做第二次 get_task** 验活，再 `asyncio.to_thread` 执行同步 SQLite。

**（c）快照载荷模型（investigation/models.py）。** `FileSnapshotPayload`（:18-44）冻结文件初态（含初次 LLM 描述原样）；`ClusterSnapshotPayload`（:45-64）的 initial_* 一律 None——簇身份是 2 元组而簇分析写在 3 元组粒度，宁可空也不编造（S7）。`acquisition.py` 在捕获时刻用 `mode=ro` 重读源库；`canonical_json`（S8）保证同输入同字节。

**（d）Grounding（investigation/grounding.py）。** 纯函数、无 DB 无 LLM：`derive_allowed_evidence_ids`（:29）只从冻结信封推导（G2-G4）；`GroundingValidator`（:46，`_validate_one` :65）用**精确规范 ID 匹配**（不解释 LLM 的 ref 字符串），无效引用剥离并记 warning；FACT 无有效引用降级 HYPOTHESIS（G7）；`grounded` 只表示"引用合法"不代表语义证实（G8）。`compute_analysis_grounding`（:103）聚合为 valid/partially_grounded/invalid。

**（e）执行器（E1-E11 不变量，execution.py:3-15）。** `SecondaryAnalysisExecutor.submit`（:146-210）在准入锁内**先持久化 queued 行再启动后台任务**（E1）；canonical 化 related keys（parse→dedupe→去自引用→排序，保证同输入同 input_hash）。`_execute`（:241-446）：existing-store-only 打开（:254）→ `queued→running` 认领（输家直接退出，:263-277）→ 信封哈希 `hmac.compare_digest` 复验（:279-291）→ schema/prompt 兼容表（:316-329）→ prompt 只由信封构建（E3，:340）→ LLM 错误分类为稳定 error_code（`_classify_llm_error`，:53-66，DB 里不落内部 URL/栈）→ 按 prompt 输出契约落 review_pending（`complete_analysis_for_review`，E5 永不自动 accepted）。**D4b 活任务写边界**（live_store.py:35-76）：终态写入前重新 get_task 校验存活与路径身份，任一不确定即丢弃结果不写（防复活已删任务的库）。重启恢复（E9，:514-577）分页扫描全部任务，把 stale queued/running 判 `service_restart`。`EventRefreshExecutor`（event_refresh_execution.py）镜像同一纪律处理事件语义刷新（V2 信封、claim 的 supports/contradicts 关系）。

**（f）读侧与图。** `InvestigationGraphReader`（graph_reader.py）是唯一 GET 通道：`mode=ro + PRAGMA query_only`，损坏/版本不支持→`EvidenceStoreError`（fail closed），绝不把"读不了"伪装成"没有调查数据"（B2/B3）。`InvestigationReadService`（read.py，C9a）在此之上提供证据清单/单快照/精确 claim 读，缺库即"无发现"。`InvestigationGraphService`（graph.py，C8b）组合 overlay（本域不可变行）与 Base KG（Graphiti），错误不对称是冻结契约：Base KG 挂了→`base_graph_available=false` + 固定警告 + HTTP 200；investigation 库挂了→503；两边实体永不按显示名合并（G9）。`ReportEvidenceService`（report_evidence.py，R1）：`analysis_id` 是分析员显式钉扎的"同一证据的某个 accepted 分析"，写入事务内三重复核（同任务/同证据/状态 accepted），绝不是"最新 accepted"指针。

**（g）legacy 栈（investigation_service.py / investigation_persistence.py / investigation_evidence.py / investigation_errors.py）。** `InvestigationPersistence`（schema v3，:36）提供 `get_investigation_db_path`（:68-81，files.db → 同目录 investigation.db）、`accept_analysis`（invalid 不可采纳、partial 需显式确认）、`recover_interrupted_jobs` 等同族机制；`InvestigationService` 类（investigation_service.py:188-1697）在其上编排 bootstrap 种子事件（:409-469）、二次分析作业（:662-919，含 `_ground_claims` :921-981）、事件版本刷新（:1086-1194）、以及 4A-4E+final 报告装配编排（:1292-1600）。`investigation_evidence.py` 定义旧键工具与上限常量（MAX_CLUSTER_EVENTS_FOR_LLM=50、MAX_RELATED_EVIDENCE=20、MAX_CONTENT_CHARS=8000，:20-22）；`investigation_errors.py` 是域错误层次；`claim_provenance_reader.py` 用 `mode=ro` 读单条历史事件 claim 及其证据链（`get_claim`，:39-65）；`citation_validation.py` 是纯函数引用图构建器：CIT- 前缀编号（:22）、`CitationGraphBuilder.build`（:222）对 dataset 校验证据 report-ready/快照存在/钉扎分析合法并输出自哈希（:149）。

## 6. 注意事项与已知问题

- **双栈并存**：legacy `InvestigationService` 类当前**没有任何路由实例化**（全仓只有 `report_rendering.py:499` 复用其 `extract_json_payload`）；4A-4E/final 装配编排因此处于"机制完整、无线上入口"状态，Workbench 的 final-reports 端点实际读 R2 narrative manifest。两套 schema（v3 与 v7）的 investigation.db 互不兼容，排查时先看 `PRAGMA user_version`。
- **`CancelledError` 后的同步清理**：execution.py:404-432 特意用同步 transition（取消态下任何 await 会重抛 CancelledError），这段是少数允许阻塞事件循环的例外，别"顺手优化"成异步。
- 执行器初始化在 ServiceManager 里只有 12s 预算；恢复扫描按任务分页（page_size=100），任务很多时启动恢复可能吃满预算——超时属于容忍路径（服务仍启动，恢复不完整）。
- 事件语义版本与事件"needs_refresh"标记联动：采纳分析会 `_mark_related_events_dirty`（repository.py:1769-1813），忘记这层传播会导致报告读到陈旧语义。
- legacy `investigation_service.get_job` 的内存作业字典重启即失（:1023-1032），持久状态以 SQLite 为准（`get_job_async` 兜底，:1034-1053）。
- 并发语义总结：capture 幂等（ON CONFLICT+回读）；分析认领单赢家（queued→running CAS）；review 单事务替换 accepted；事件刷新 claim_event_refresh 原子认领——同一证据的多版本并发 redo 安全，但"同一 analysis_id 的双重 review"由状态机触发器拒绝。

## 7. 如何验证（python_service/tests/unit/）

- 规范栈：`investigation/test_investigation_repository.py`（状态机/迁移/v7 校验）、`test_investigation_execution.py`（E1-E11）、`test_investigation_grounding.py`（G 规则）、`test_investigation_secondary.py`、`test_investigation_completion.py`、`test_investigation_refresh_execution.py`、`test_d4b_task_deletion_boundary.py`（活任务边界）、`test_phase_c_*`（六条端到端流）、`test_investigation_paths.py`、`evidence/test_keys.py`、`evidence/test_resolver.py`；路由层 `test_investigation_routes.py`（202+轮询）、`test_investigation_*_routes.py`、`test_report_evidence_routes.py`、`test_service_manager_investigation.py`。
- legacy 栈：`test_investigation_persistence.py`、`test_investigation_evidence.py`、`test_claim_provenance_reader.py`、`test_report_dataset.py`、`test_citation_validation.py`。
- 手工链路：`POST /api/investigation/analyses` → 轮询至 review_pending → `POST .../review {"decision":"accepted"}` → `GET /api/investigation/evidence`；`sqlite3 <task>/investigation.db "PRAGMA user_version"` 应为 7。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
