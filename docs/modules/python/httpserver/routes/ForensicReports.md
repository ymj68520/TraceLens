# ForensicReports 路由（python_service/httpserver/routes/forensic_reports.py + report_evidence.py + report_generation.py + report_narrative.py，前缀 /api/reports）

> **一句话**：版本化取证报告的完整生命周期——A 链（快照报告版本：manifest/分类分页/全文检索）、R1（分析师显式报告证据绑定）、R2c（202 准入 + generation_id 精确轮询的 LLM 生成）与 R2d（任务域严格叙事只读）。

## 1. 这组路由承担什么职责（为什么存在）

报告必须像证据一样**可版本化、可引用、可回溯**。这组路由把"报告"拆成四个正交面：forensic_reports.py 维护报告**版本快照**（每个版本是一份落盘的冻结产物：manifest + 分类页 + 检索索引）；report_evidence.py 维护"哪些证据进报告"的**显式绑定**（分析师动作，不是隐式"最新已接受"）；report_generation.py 是**生成准入与轮询**（客户端只能给 task_id + requested_by，冻结输入完全由服务端从 R1 绑定组装）；report_narrative.py 是给 Viewer 的**任务域严格读**。四者共享 `{FORENSIC_REPORT_DIR}/reports.db` 与报告输出目录（config.py:214-215，默认 `build/data/reports`，别名 FORENSIC_REPORT_DIR）。

## 2. 典型调用方（前端哪个页面/组件）

- **A 链**：`web/src/services/reportDataSource.js:19-25`（GET/POST `/api/reports`）经 reportService.js 导出，供 `/forensic-report` 页（pages/ForensicReportPage.jsx:12）读版本列表/manifest/分类页/检索。
- **R2c/R2d**：`web/src/services/reportGenerationService.js:20/31/42`（`/api/reports/generate`、`/generations/{id}`、`/narrative/versions/{id}`），调用方是 ForensicReportPage.jsx:11 与 `components/reports/GenerateReportPanel.jsx:10`、`hooks/useReportGenerationPolling.js`。
- **R1**：`web/src/services/investigationService.js:242-276`（GET/POST/PUT `/api/reports/evidence`），供 `/investigation` 页在证据评审后绑定进报告（GenerateReportPanel.jsx:9 的 `listReportEvidence`）。
- 服务间：无——investigation_workbench 的 final-reports 是直接读 reports.db 的旁路只读视图（见 [Investigation.md](Investigation.md) 第 5 节），不经这些路由。

## 3. 核心数据结构

A 链的版本行模型（services/forensic_report/models.py:204-221）：

```python
# models.py:204-221（节选）
class ReportVersion(BaseModel):
    report_id: str
    version: int
    scope_type: ScopeType          # task | case（case 显式 501）
    scope_id: str
    status: ReportStatus           # queued/generating/ready/failed
    title: str
    task_ids: list[str]
    stage: str = "queued"
    progress: int = Field(default=0, ge=0, le=100)
    generated_at: str | None = None
    manifest_path: str | None = None
    warnings: list[AdapterWarning] = Field(default_factory=list)
    error: str | None = None
    # R2d explicit type marker: None = deterministic forensic snapshot
    # (every pre-existing row), 'llm_generation' = R2c narrative version.
    report_kind: str | None = None
```

谁写：ReportRepository 在 reports.db 落行，快照 writer 随阶段更新 status/stage/progress；谁读：全部 A 链 GET。`report_kind` 是 R2d 的判别标记——None=确定性快照（老行），`'llm_generation'`=R2c 叙事版本。关联的 `ReportRecord.record_id` 有硬校验（models.py:96-106）：必须 `rec_` + 64 位十六进制 SHA-256。

R2c 的请求/响应模型是"最小输入、最大可审计输出"（report_generation.py:59-85）：

```python
# report_generation.py:59-63
class GenerateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, max_length=256)
    requested_by: str = Field(min_length=1, max_length=256)

# report_generation.py:66-85（节选）
class GenerationStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    generation_id: str
    task_id: str
    status: str
    requested_by: str
    prompt_version: str
    input_schema_version: int
    input_hash: str
    report_id: Optional[str] = None
    produced_version: Optional[int] = None
    # ...
    error_code: Optional[str] = None
    report: Optional[dict] = None     # 仅 completed 时带 manifest
```

客户端能提交的只有两个字段（多余 422）；响应携带 prompt_version/input_schema_version/input_hash 三件套——同一 envelope 的 SHA-256 指纹，用于事后验证"生成输入没有漂移"。

R1 的请求模型（report_evidence.py:71-85）：`report_status` 只能 main/appendix（excluded 必须走显式 PUT——记录"考虑过但排除"）；`analysis_id` 是可选的**冻结**绑定（指向同证据的已接受分析）；身份恒为 `task_id` + canonical evidence_key，且经请求体/查询传递而非 URL 路径（canonical key 含斜杠，report_evidence.py:1-9）。

## 4. 端点语义分组（散文）

完整契约见 docs/api_reference/Python_REST_API.md 第 6 节。分组：

- **报告版本（A 链，forensic_reports.py）**：`POST /api/reports`（:103，**202** 启动快照生成）、`GET /api/reports`（:122，按 scope 列版本）、`GET /{report_id}/status`（:131）、`GET /{report_id}/manifest`（:139，返回冻结 manifest.json 字节）、`GET /{report_id}/categories/{category_id}/pages/{page}`（:144，分类分页）、`GET /{report_id}/search?q=`（:154，offset/limit 分页检索）。
- **报告证据（R1，report_evidence.py）**：`GET /evidence`（:53）、`POST /evidence`（:88）、`PUT /evidence`（:138，显式改状态或**重绑** analysis_id；R1 不定义解绑）。
- **生成（R2c，report_generation.py）**：`POST /generate`（:95，**202** 返回 generation_id）、`GET /generations/{generation_id}?task_id=`（:128，**精确 ID 轮询**，无"最新一次"回退；task 域不符即 404）。
- **叙事（R2d，report_narrative.py)**：`GET /narrative/versions/{report_id}?task_id=`（:51）——一个精确已发布叙事版本，只返回持久化版本行 + manifest，无 envelope 字节、无系统提示词、无文件路径（:1-11）。

## 5. 数据流（读什么库/服务、写什么）

**写**：`reports.db`（ReportRepository，{FORENSIC_REPORT_DIR} 下）+ 报告输出目录（staging 目录原子落盘 manifest.json、分类页文件、检索索引 SQLite——`search_documents` 表，services/forensic_report/search_index.py:12-40；写入流程见 snapshot_writer.py:157-280 的 staging→manifest 组装）。**读**：A 链文件端点经 `_file_response`（forensic_reports.py:65-89）把落盘文件读出并做严格 JSON 校验：

```python
# forensic_reports.py:61-89
def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")

def _file_response(loader: Any, *args: Any) -> Response:
    try:
        path = Path(loader(*args))
    except KeyError as exc:
        raise _not_found() from exc
    except RuntimeError as exc:
        raise _not_ready() from exc
    except (TypeError, ValueError, OSError) as exc:
        raise _resource_integrity_error() from exc

    try:
        payload = path.read_bytes()
        json.loads(
            payload.decode("utf-8"),
            parse_constant=_reject_nonstandard_json_constant,  # 拒绝 NaN/Infinity
        )
    except (
        RecursionError, ValueError, OSError,
        UnicodeDecodeError, json.JSONDecodeError,
    ) as exc:
        raise _resource_integrity_error() from exc
    return Response(content=payload, media_type="application/json")
```

三层异常映射（loader 的 KeyError→404、RuntimeError→409 "report is not ready" 、其余→500 完整性 token）；`parse_constant` 钩子把 `NaN`/`Infinity` 等非标准常量也拒掉——任何解析失败都归一为 500 "report resource integrity error"——宁可报完整性错误也不吐半坏数据。

R2c 的关键机制在准入服务（services/forensic_report/generation.py:305-335）：

```python
# generation.py:312-332（节选）
task = await self._cpp_backend.get_task(task_id)
if not isinstance(task, dict) or task.get("id") != task_id:
    raise EvidenceNotFoundError("task not found")
try:
    db_path = investigation_db_path_for_task(task)
except EvidenceStoreError:
    raise ReportGenerationInputError("no_report_evidence", ...) from None
# ...
builder = ReportGenerationInputBuilder(db_path, task_id)
envelope = await asyncio.to_thread(builder.assemble, prompt_version)
if not envelope.main_evidence and not envelope.appendix_evidence:
    raise ReportGenerationInputError("no_report_evidence", ...)
envelope_json = canonical_json(envelope)
input_hash = hashlib.sha256(envelope_json.encode("utf-8")).hexdigest()
```

`admit` 只拿 task_id：经 C++ 校验任务身份 → `investigation_db_path_for_task` 找到该任务的 investigation.db → `ReportGenerationInputBuilder` 从 R1 绑定组装冻结 envelope（main/appendix 为空 → `no_report_evidence` → 路由层转 409，report_generation.py:109-112）→ 对 envelope 做规范化 JSON 的 SHA-256 得 `input_hash`（generation.py:331-332）后落 `reports.db` 准入行，`executor.submit` 后台执行（report_generation.py:122）；路由立即用严格读取回读当前行返回（:123-125）。类 docstring（generation.py:291-298）写明冻结动机：envelope 在一个读事务内组装完毕、准入行不可变，之后分析师改绑定/排除/新增证据都改不了已准入的输入。轮询端点 `include_report=row.status == "completed"`（:143）——manifest 只在完成态附带。

R1 绑定的服务端三重校验（task 存在、证据已捕获、analysis_id 属于同证据的已接受分析）在 services/investigation/report_evidence.py，冲突类型 `AnalysisBindingConflictError`/`ReportEvidenceConflictError` 映射 409。

R2d 的响应模型 `NarrativeReportResponse`（report_narrative.py:32-49）字段与 manifest 一一对应（version/generation_id/model/prompt_version/input_hash/sections/citations），读取走 `read_narrative_version_strict`（:60-62）——身份不符返回 None 即 404。

## 6. 边界与已知状态（409/500/501/降级）

- **501**：`scope_type=case` 的报告生成显式 `NotImplementedError` → 路由转 501 "report scope type is not supported"（forensic_reports.py:116-119；services/forensic_report/service.py:92-93）——任务域是唯一支持的 scope。
- **409**：`no_report_evidence`（生成无证据可写，report_generation.py:110-112）、绑定/重复冲突（R1 的 :109-116）；A 链文件在报告未就绪时 `RuntimeError` → 409 "report is not ready"（forensic_reports.py:49-51、:70-71）。
- **500 完整性 token**：资源完整性（`_RESOURCE_INTEGRITY_DETAIL`）与检索索引不可用（`_SEARCH_INTEGRITY_DETAIL`）都是固定短句，不泄内部异常（forensic_reports.py:19-20）。
- **不透明缺失**：R2d 的跨任务 report_id 与不存在的 report_id 同样返回 404，不可区分（report_narrative.py:7-10）；轮询同理（task 域强校验，report_generation.py:139-142）。
- R1 的 PUT 要求至少给 `report_status` 或 `analysis_id` 之一，否则 422（report_evidence.py:148-152）；省略 `analysis_id` 表示"保持当前冻结绑定"，绝不自动跟随新版本。
- 服务重启恢复：`resume_unfinished` 会把未完成的版本标记为 `service_restart` 失败并要求新建版本（service.py:105-112），客户端不会永远轮询一个死任务。
- env：`FORENSIC_REPORT_DIR`（默认 build/data/reports）、`FORENSIC_REPORT_GENERATOR_VERSION`（默认 1.0.0，写入 manifest）。

## 7. 如何验证

- 路由层：`python_service/tests/unit/forensic_report/test_routes.py`（A 链）、`test_report_generation_routes.py`（202/轮询/409）、`test_report_narrative_routes.py`（R2d 严格读）；R1 由 `tests/unit/investigation/test_report_evidence_routes.py` 覆盖。
- 服务层：`tests/unit/forensic_report/`（repository/snapshot_writer/search_index/generation_admission/generation_execution/models/ids）。
- 前端契约：`web/src/services/reportService.test.js`、`reportDataSource.test.js`、`pages/ForensicReportPage.generation.test.jsx`。
- 活体链路：`make acceptance-analyst`（docs/testing/live-integration.md Journey B 第 6-7 步：R1 精确 analysis_id 绑定 → 生成 → 轮询 → manifest 引用回指精确 Evidence/Analysis/Claim ID）。

相关阅读：[Investigation.md](Investigation.md)（R1 绑定的上游评审流）、[LLM.md](LLM.md)（旧 410 生成器的退役历史）。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
