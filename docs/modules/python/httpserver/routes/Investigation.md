# Investigation 路由（python_service/httpserver/routes/investigation.py + investigation_workbench.py，前缀 /api/investigation 与 /api/investigation/workbench）

> **一句话**：二次调查的规范化 HTTP 表面——把 C++ 首轮分析出的证据冻结成快照、在其上跑带评审的二次 LLM 分析、维护调查事件与显式证据关联，并以只读工作台门面（facade）为前端 /investigation 页供数；工作台里一组"按设计固定 409"的端点是本地契约的边界声明。

## 1. 这组路由承担什么职责（为什么存在）

首轮（C++）分析结果会随重新解析漂移；二次调查需要一个**不可变的事实基线**。investigation.py 是"规范化（canonical）"路由：证据快照（C3）、二次分析与评审（C4b-2/C4c/C6）、调查事件与叙事版本（C7a-C7c）、事件-证据关联、事件刷新、只读工作台投影（C9a）与 Base KG + Overlay 图谱组合（C8b）。客户端可控字段只有 `task_id` 和 `evidence_key`，不接受任何路径（investigation.py:1-5）。

investigation_workbench.py 是**任务域门面**：自身零持久化，把"远端工作台"的响应形状翻译到本地服务之上（investigation_workbench.py:1-7）。它故意用独立命名空间（`/api/investigation/workbench`），不与扁平的 canonical 路由互相遮蔽——其中若干端点**按设计固定返回 409**，用来对外声明"这不属于本地 canonical 契约"（见第 5 节）。

## 2. 典型调用方（前端哪个页面/组件）

- 前端 `/investigation` 与 `/investigation/report` 页（web/src/routes.jsx:105-109 → `pages/Investigation/Investigation.jsx`、`pages/Investigation/FinalReportViewer.jsx`），全部经 **web/src/services/investigationService.js**：canonical 端点封装在 :19-276（snapshots/graph/evidence/analyses/events/report-evidence），workbench 门面封装在 :283-340（overview/bootstrap/analyze/accept/reject/final-reports）。
- 页面 hooks 佐证：`pages/Investigation/hooks/useInvestigationEvents.js:19-21` 调 `getOverview`、失败时退 `bootstrapInvestigation`；`hooks/useFinalReportViewer.js`、`hooks/useReportTraceback.js` 消费 final-reports 系列。
- 报告生成面板 `web/src/components/reports/GenerateReportPanel.jsx:9` 用 `listReportEvidence`（canonical R1 读）。
- 服务端没有其他调用方；C++ 不调这组路由。

## 3. 核心数据结构

**证据键（Evidence Key）是全组的身份语法**（services/evidence/keys.py:1-13 模块 docstring）：

```
file:<normalized_path>
cluster:v1:<unix_minute>:<encoded_event_type>   (event_type percent-encoded, UTF-8)
```

解析是纯函数 `parse_evidence_key`（keys.py:49-99），无 DB 访问；等价不变量（C1a）：规范化后同身份的输入产生同一 `canonical_key`。event_type 用百分号编码（C1b）是为了键语法永不依赖事件类型字符集——`foo:bar`、中文事件名都无须 v2 迁移。解析对畸形输入 fail-closed（非 UTF-8、坏转义直接 `InvalidEvidenceKeyError`，keys.py:32-46），绝不"修复"成相近身份：

```python
# keys.py:59-70（file 分支）
if evidence_key.startswith(_FILE_PREFIX):
    raw_path = evidence_key[len(_FILE_PREFIX):]
    if not raw_path:
        raise InvalidEvidenceKeyError("file evidence key missing path")
    normalized_path = normalize_evidence_path(raw_path)
    if not normalized_path:
        raise InvalidEvidenceKeyError("file evidence key has empty normalized path")
    return ParsedEvidenceKey(
        evidence_type="file",
        canonical_key=f"file:{normalized_path}",
        normalized_path=normalized_path,
    )
```

**快照载荷**是冻结的 Pydantic 模型（services/investigation/models.py:18-42）：

```python
# models.py:18-23、33-42（节选）
class FileSnapshotPayload(BaseModel):
    """Frozen initial state of a file Evidence (read from files.db at capture)."""
    model_config = ConfigDict(frozen=True)
    evidence_type: Literal["file"] = "file"
    normalized_path: str
    # ...
    # Initial Analysis, frozen as-is (never generated)
    initial_summary: Optional[str] = None
    initial_description: Optional[str] = None
    initial_keywords: Optional[str] = None
    initial_model: Optional[str] = None
    initial_analyzed_at: Optional[int] = None
```

谁写：捕获时由 files.db 的当前行一次性物化（缺字段保持 NULL——快照永不生成数据）；谁读：二次分析 envelope、R1 绑定、工作台初始分析展示。`frozen=True` 使实例不可变，配合 `canonical_json` 序列化保证同一证据重复捕获字节一致。ClusterSnapshotPayload（:45-65）的 initial_* 恒为 None（S7：簇身份是二段式 `(unix_minute,event_type)`，而簇 LLM 分析写在三段式粒度上，无法确定性回填——宁缺毋造）。

**二次分析状态机**（models.py:108-148）：`queued → running|failed`、`running → review_pending|failed`、`review_pending → accepted|rejected|invalid`；终态零出度——重做分析永远新建版本行，不改历史。评审决策 `AnalysisReviewDecision` 只有 accepted/rejected/invalid 三值。

**路由层请求模型**全部 `extra="forbid"`（多余字段 422）。快照请求是严格两字段（investigation.py:50-57）：

```python
# investigation.py:50-57
class CaptureEvidenceRequest(BaseModel):
    """Strict public boundary: exactly task_id + evidence_key."""
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)
```

创建分析请求（:89-106）在两字段之上加 `analyst_note`/`case_context`（≤20 000 字符，纯文本——CCTX1：笔记不是证据）与 `related_evidence`（≤20 个 evidence_key，创建时冻结进 envelope）。

## 4. 端点语义分组（散文）

完整契约见 docs/api_reference/Python_REST_API.md 第 7/8 节。分组语义：

- **快照**：`POST /snapshots`（investigation.py:70）——resolve + capture 一条证据，已有快照直接胜出（幂等）。
- **二次分析**：`POST /analyses`（:120，**202**）提交后台 LLM 分析；`GET /analyses/{id}`（:191，SQLite 为真源）、`GET /analyses`（:204，历史分析在源证据消失后仍可查）、`POST /analyses/{id}/review`（:164，对**精确版本**记一次显式 accept/reject 决策）。
- **调查事件**：`POST /events`（:277，201，连带不可变 v1 叙事版本）、`GET /events`/`GET /events/{id}`（:296/:311，读不建库）、`GET /events/{id}/versions`（:328）、`POST/GET /events/{id}/evidence`（:347/:377，resolve+capture 后 INSERT-only 关联）、`POST /events/{id}/refresh`（:406，201，显式刷新准入）与 `GET .../refreshes`（:431）。
- **只读投影（C9a）**：`GET /evidence`（:469）、`GET /evidence/snapshot`（:487，绝不按需补抓）、`GET /analyses/{id}/claims`（:515，只返回该精确版本持久化的 claims，无投影无回退）。
- **图谱**：`GET /graph`（:552）——Base KG 与 Overlay 组合，`max_base_nodes`（默认 200，1-1000）只约束 Base KG 读取。
- **工作台门面**：`GET /{task_id}`（overview 聚合，investigation_workbench.py:215）、bootstrap（:223）、events 系列（:232-:366）、evidence detail/analyze/analysis-jobs/accept/reject（:275-:348）、report-evidence 三件套（:405-:439）、`graph/local`（:442）、final-reports 列表/详情/markdown/html/print（:454-:516）。

## 5. 数据流（读什么库/服务、写什么）

**写目标只有一个：任务目录下的 investigation.db**。路径由 `investigation_db_path_for_task` 从 cpp_backend 返回的可信 files.db/events.db 路径推导（services/investigation/paths.py:16-40，目录不一致即 fail-closed），绝不接受客户端路径。读侧经 EvidenceResolver 打开 files.db/events.db；快照捕获的关键不变量在 `InvestigationRepository.capture_if_absent`：

```python
# services/investigation/repository.py:1474-1516（节选）
def capture_if_absent(self, resolved: ResolvedEvidence) -> EvidenceSnapshot:
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
        conn.execute("BEGIN IMMEDIATE")                       # S3
        conn.execute(
            "INSERT INTO evidence_snapshots ... "
            "ON CONFLICT(task_id, evidence_key) DO NOTHING",
            (...),
        )
```

这段解释了验收语义：**identical snapshots**（重复捕获返回同一冻结 payload，源 files.db 的 SHA-256 不变——docs/testing/live-integration.md 的 F 系列与 Journey B 即按此验收）。三个不变量各就各位：S1 已有快照胜出；S5 候选在写事务外构建（只读模式、无 LLM 调用，缩短写锁窗口）；S3 `BEGIN IMMEDIATE` + `ON CONFLICT DO NOTHING` 让并发捕获只有一个赢家，随后 SELECT 读回胜者行（含"输者读赢家"路径）。

二次分析的执行顺序（services/investigation/execution.py:146-205）：

```python
# execution.py:167-205（节选）
# Phase 1: capture primary + related evidence (OUTSIDE the admission lock).
snapshot = await self._capture_service.capture(task_id, evidence_key)
# Canonicalize related evidence: parse → dedupe → discard primary → sort.
primary_key = snapshot.evidence_key
canonical_related: set[str] = set()
for raw_key in related_evidence:
    parsed = parse_evidence_key(raw_key)
    canonical_related.add(parsed.canonical_key)
canonical_related.discard(primary_key)
ordered_related = tuple(sorted(canonical_related))
# CCTX3/CCTX4: resolve + capture each related evidence in the SAME task.
for rel_key in ordered_related:
    await self._capture_service.capture(task_id, rel_key)
# ...
# Phase 2: admission lock — check accepting + E1 persist + register task.
async with self._admission_lock:
    if not self._accepting:
        raise RuntimeError("executor is shutting down")
    repo = InvestigationRepository(db_path, task_id)
    analysis = await asyncio.to_thread(repo.create_analysis, ...)
    # E11: pass the SAME db_path — worker never re-derives it.
    bg_task = asyncio.create_task(self._execute(analysis.analysis_id, task_id, db_path))
```

Phase 1 在准入锁**外**先捕获主证据 + 逐个捕获 related_evidence（规范化去重、去自引用、确定性排序，same logical input → same input_hash）；Phase 2 持锁**先持久化排队记录再启动后台任务**（E1），worker 复用同一 db_path（E11）。读侧 `get_analysis` 走 strict `mode=ro` reader（execution.py:212-225）——写路径的 Repository 构造器会在库不存在时**创建**它，GET 绝不能触发建库（C10 §14/E13）。图谱组合（services/investigation/graph.py:234 起）Base KG 失败时优雅降级为 `base_graph_available=false` + 固定告警 token，而 Investigation 库损坏则 503 fail-closed，绝不伪装成空 overlay。

workbench 门面的 final-reports 是另一条读路径：直接只读打开 `{FORENSIC_REPORT_DIR}/reports.db`（`PRAGMA query_only`，investigation_workbench.py:461-471），再用 strict reader 读 manifest 并组装为前端期望的报告视图（sections/claim_manifest/hash，:170-212）。

## 6. 边界与已知状态（409/404/501/降级）

**固定 409 是这组文档最重要的契约边界**——5 个处理函数按设计直接抛 409，表示"远端工作台有此操作、本地 canonical 契约没有"：

| 端点（/api/investigation/workbench 下） | 位置 | 409 detail 要点 |
|---|---|---|
| `POST /{t}/events/{e}/review` | investigation_workbench.py:250-252 | 事件评审不在本地契约 |
| `POST /{t}/events/{e}/versions/{v}/accept` 与 `/reject` | :369-372 | 事件语义版本评审不在本地契约 |
| `POST /{t}/events/{e}/versions/{v}/claims/{c}/accept` 与 `/reject` | :382-385 | 事件 claim 评审不在本地契约 |
| `POST /{t}/notes` | :393-396 | 分析师笔记需要显式 schema 决策 |
| `POST /{t}/final-reports/{r}/publish` | :525-528 | 发布归 canonical R2 报告流所有 |

配套的"软桩"：`GET .../claims`（含 effective）恒返回 `[]`（:375-379）、`GET /{t}/notes` 恒返回 `note: null`（:399-402）、`GET /{t}/claims/{id}` 恒 404（:388-390）、publication 恒 null（:519-522）。前端 investigationService.js 仍封装了这些调用（:304-318 等），拿到 409/null 即静默降级——这是设计而非故障。

其余边界：bootstrap 忽略请求体直接返回 overview（`del request`，:223-229）；canonical 侧冲突语义为 409（评审冲突 :186、证据链接已存在 :369-372、刷新已在途 :423-426）；服务未就绪统一 503（各 Depends 工厂捕获 RuntimeError）；`extra="forbid"` 让多余字段 422。事件"读写不对称"：GET 永不创建 investigation.db（无库即 `[]`）。

## 7. 如何验证

- 路由层：`python_service/tests/unit/test_investigation_routes.py`（快照/分析）、`test_investigation_review_routes.py`、`test_investigation_event_routes.py`、`test_investigation_read_routes.py`（C9a 只读不变量）、`test_investigation_graph_routes.py`（降级/fail-closed）。
- 服务层：`tests/unit/investigation/`（acquisition/execution/review/event/refresh/report_evidence/graph/repository、phase_c 端到端流）。
- 前端契约：`web/src/services/investigationService.test.js`、`web/src/pages/Investigation.test.jsx`、`FinalReportViewer.test.jsx`。
- 活体链路：`make acceptance-analyst`（docs/testing/live-integration.md Journey B：analyses→review→events→evidence→graph→report 全链，含快照完整性与 files.db SHA-256 不变）。

相关阅读：[ForensicReports.md](ForensicReports.md)（R1/R2c/R2d 与本组的报告证据/生成衔接）、[HTTPRoutes.md](../HTTPRoutes.md)。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
