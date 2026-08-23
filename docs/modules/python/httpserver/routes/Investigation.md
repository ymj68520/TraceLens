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

## 3. 端点语义分组（散文）

完整契约见 docs/api_reference/Python_REST_API.md 第 7/8 节。分组语义：

- **快照**：`POST /snapshots`（investigation.py:70）——resolve + capture 一条证据，已有快照直接胜出（幂等）。
- **二次分析**：`POST /analyses`（:120，**202**）提交后台 LLM 分析（analyst_note/case_context/related_evidence 在创建时冻结进 envelope）；`GET /analyses/{id}`（:191，SQLite 为真源）、`GET /analyses`（:204，历史分析在源证据消失后仍可查）、`POST /analyses/{id}/review`（:164，对**精确版本**记一次显式 accept/reject 决策）。
- **调查事件**：`POST /events`（:277，201，连带不可变 v1 叙事版本）、`GET /events`/`GET /events/{id}`（:296/:311，读不建库）、`GET /events/{id}/versions`（:328）、`POST/GET /events/{id}/evidence`（:347/:377，resolve+capture 后 INSERT-only 关联）、`POST /events/{id}/refresh`（:406，201，显式刷新准入）与 `GET .../refreshes`（:431）。
- **只读投影（C9a）**：`GET /evidence`（:469）、`GET /evidence/snapshot`（:487，绝不按需补抓）、`GET /analyses/{id}/claims`（:515，只返回该精确版本持久化的 claims，无投影无回退）。
- **图谱**：`GET /graph`（:552）——Base KG 与 Overlay 组合，`max_base_nodes` 只约束 Base KG 读取。
- **工作台门面**：`GET /{task_id}`（overview 聚合，investigation_workbench.py:215）、bootstrap（:223）、events 系列（:232-:366）、evidence detail/analyze/analysis-jobs/accept/reject（:275-:348）、report-evidence 三件套（:405-:439）、`graph/local`（:442）、final-reports 列表/详情/markdown/html/print（:454-:516）。

## 4. 数据流（读什么库/服务、写什么）

**写目标只有一个：任务目录下的 investigation.db**。路径由 `investigation_db_path_for_task` 从 cpp_backend 返回的可信 files.db/events.db 路径推导（services/investigation/paths.py:16-40，目录不一致即 fail-closed），绝不接受客户端路径。读侧经 EvidenceResolver 打开 files.db/events.db；快照捕获的关键不变量在 `InvestigationRepository.capture_if_absent`：

```python
# services/investigation/repository.py:1481-1497（节选）
existing = self.get_snapshot(resolved.evidence_key)   # S1: 已有快照胜出
if existing is not None:
    return existing
...
conn.execute("BEGIN IMMEDIATE")                       # S3
conn.execute("INSERT INTO evidence_snapshots ... "
             "ON CONFLICT(task_id, evidence_key) DO NOTHING")
```

这段解释了验收语义：**identical snapshots**（重复捕获返回同一冻结 payload，源 files.db 的 SHA-256 不变——docs/testing/live-integration.md 的 F 系列与 Journey B 即按此验收）。

二次分析的执行顺序（services/investigation/execution.py:146-205）：Phase 1 在准入锁**外**先捕获主证据 + 逐个捕获 related_evidence（规范化去重、确定性排序，same logical input → same input_hash）；Phase 2 持锁**先持久化排队记录再启动后台任务**（E1），worker 复用同一 db_path（E11）。图谱组合（services/investigation/graph.py:234 起）Base KG 失败时优雅降级为 `base_graph_available=false` + 固定告警 token，而 Investigation 库损坏则 503 fail-closed，绝不伪装成空 overlay。

workbench 门面的 final-reports 是另一条读路径：直接只读打开 `{FORENSIC_REPORT_DIR}/reports.db`（`PRAGMA query_only`，investigation_workbench.py:461-471），再用 strict reader 读 manifest 并组装为前端期望的报告视图（sections/claim_manifest/hash，:170-212）。

## 5. 边界与已知状态（409/404/501/降级）

**固定 409 是这组文档最重要的契约边界**——5 个处理函数按设计直接抛 409，表示"远端工作台有此操作、本地 canonical 契约没有"：

| 端点（/api/investigation/workbench 下） | 位置 | 409 detail 要点 |
|---|---|---|
| `POST /{t}/events/{e}/review` | investigation_workbench.py:250-252 | 事件评审不在本地契约 |
| `POST /{t}/events/{e}/versions/{v}/accept` 与 `/reject` | :369-372 | 事件语义版本评审不在本地契约 |
| `POST /{t}/events/{e}/versions/{v}/claims/{c}/accept` 与 `/reject` | :382-385 | 事件 claim 评审不在本地契约 |
| `POST /{t}/notes` | :393-396 | 分析师笔记需要显式 schema 决策 |
| `POST /{t}/final-reports/{r}/publish` | :525-528 | 发布归 canonical R2 报告流所有 |

配套的"软桩"：`GET .../claims`（含 effective）恒返回 `[]`（:375-379）、`GET /{t}/notes` 恒返回 `note: null`（:399-402）、`GET /{t}/claims/{id}` 恒 404（:388-390）、publication 恒 null（:519-522）。前端 investigationService.js 仍封装了这些调用（:304-318 等），拿到 409/null 即静默降级——这是设计而非故障。

其余边界：bootstrap 忽略请求体直接返回 overview（`del request`，:223-229）；canonical 侧冲突语义为 409（评审冲突 :186、证据链接已存在 :369-372、刷新已在途 :423-426）；服务未就绪统一 503；`extra="forbid"` 让多余字段 422。事件"读写不对称"：GET 永不创建 investigation.db（无库即 `[]`）。

## 6. 如何验证

- 路由层：`python_service/tests/unit/test_investigation_routes.py`（快照/分析）、`test_investigation_review_routes.py`、`test_investigation_event_routes.py`、`test_investigation_read_routes.py`（C9a 只读不变量）、`test_investigation_graph_routes.py`（降级/fail-closed）。
- 服务层：`tests/unit/investigation/`（acquisition/execution/review/event/refresh/report_evidence/graph/repository、phase_c 端到端流）。
- 前端契约：`web/src/services/investigationService.test.js`、`web/src/pages/Investigation.test.jsx`、`FinalReportViewer.test.jsx`。
- 活体链路：`make acceptance-analyst`（docs/testing/live-integration.md Journey B：analyses→review→events→evidence→graph→report 全链，含快照完整性与 files.db SHA-256 不变）。

相关阅读：[ForensicReports.md](ForensicReports.md)（R1/R2c/R2d 与本组的报告证据/生成衔接）、[HTTPRoutes.md](../HTTPRoutes.md)。

**最后更新**: 2026-08-23（新建，解释式）
