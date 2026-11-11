# ForensicReports 路由（python_service/httpserver/routes/forensic_reports.py + report_evidence.py + report_generation.py + report_narrative.py + report_pipeline_tail.py，前缀 /api/reports）

> **一句话**：版本化取证报告的完整生命周期——A 链（快照报告版本：manifest/分类分页/全文检索）、R1（分析师显式报告证据绑定）、R2c（202 准入 + generation_id 精确轮询的 LLM 生成）、R2d（任务域严格叙事只读）与流水线尾闸（pipeline-tail：初次分析流的自动首份报告，C++ 完成门）。

## 1. 这组路由承担什么职责（为什么存在）

报告必须像证据一样**可版本化、可引用、可回溯**。这组路由把"报告"拆成五个正交面：forensic_reports.py 维护报告**版本快照**（每个版本是一份落盘的冻结产物：manifest + 分类页 + 检索索引）；report_evidence.py 维护"哪些证据进报告"的**显式绑定**（分析师动作，不是隐式"最新已接受"）；report_generation.py 是**生成准入与轮询**（客户端只能给 task_id + requested_by，冻结输入完全由服务端从 R1 绑定组装）；report_narrative.py 是给 Viewer 的**任务域严格读**；report_pipeline_tail.py 是**初次分析流水线的自动尾闸**（main.py:310-314 与其余四个同挂 /api/reports）——C++ 任务管线在知识图谱摄取完成后调用，确保每个任务在标记 COMPLETED 前已产出首份材料自主研判报告。五者共享 `{FORENSIC_REPORT_DIR}/reports.db` 与报告输出目录（config.py:320-321，默认 `build/data/reports`，别名 FORENSIC_REPORT_DIR）。

## 2. 典型调用方（前端哪个页面/组件）

- **A 链**：`web/src/services/reportDataSource.js:19-25`（GET/POST `/api/reports`）经 reportService.js 导出，供 `/forensic-report` 页（pages/ForensicReportPage.jsx:12）读版本列表/manifest/分类页/检索。
- **R2c/R2d**：`web/src/services/reportGenerationService.js:20/31/42`（`/api/reports/generate`、`/generations/{id}`、`/narrative/versions/{id}`），调用方是 ForensicReportPage.jsx:11 与 `components/reports/GenerateReportPanel.jsx:10`、`hooks/useReportGenerationPolling.js`。
- **R1**：`web/src/services/investigationService.js:242-276`（GET/POST/PUT `/api/reports/evidence`），供 `/investigation` 页在证据评审后绑定进报告（GenerateReportPanel.jsx:9 的 `listReportEvidence`）。
- 服务间：无——investigation_workbench 的 final-reports 是直接读 reports.db 的旁路只读视图（见 [Investigation.md](Investigation.md) 第 5 节），不经这些路由。

## 3. 核心数据结构

A 链的版本行模型（services/forensic_report/models.py:219-236）：

```python
# models.py:219-236（节选）
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

谁写：ReportRepository 在 reports.db 落行，快照 writer 随阶段更新 status/stage/progress；谁读：全部 A 链 GET。`report_kind` 是 R2d 的判别标记——None=确定性快照（老行），`'llm_generation'`=R2c 叙事版本。关联的 `ReportRecord.record_id` 有硬校验（models.py:111-121）：必须 `rec_` + 64 位十六进制 SHA-256。

R2c 的请求/响应模型是"最小输入、最大可审计输出"（report_generation.py:60-101）：

```python
# report_generation.py:60-64
class GenerateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, max_length=256)
    requested_by: str = Field(min_length=1, max_length=256)

# report_generation.py:82-101（节选）
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

R1 的请求模型（report_evidence.py:155-169）：`report_status` 只能 main/appendix（excluded 必须走显式 PUT——记录"考虑过但排除"）；`analysis_id` 是可选的**冻结**绑定（指向同证据的已接受分析）；身份恒为 `task_id` + canonical evidence_key，且经请求体/查询传递而非 URL 路径（canonical key 含斜杠，report_evidence.py:1-9）。

## 4. 端点语义分组（散文）

完整契约见 docs/api_reference/Python_REST_API.md 第 6 节。分组：

- **报告版本（A 链，forensic_reports.py）**：`POST /api/reports`（:120-121，**202** 启动快照生成）、`GET /api/reports`（:139，按 scope 列版本）、`GET /{report_id}/status`（:213）、`GET /{report_id}/manifest`（:221，返回冻结 manifest.json 字节）、`GET /{report_id}/categories/{category_id}/pages/{page}`（:226，分类分页）、`GET /{report_id}/search?q=`（:236，offset/limit 分页检索）。
- **报告证据（R1，report_evidence.py）**：`GET /evidence`（:68）、`POST /evidence`（:172）、`PUT /evidence`（:223，显式改状态或**重绑** analysis_id；R1 不定义解绑）。
- **生成（R2c，report_generation.py）**：`POST /generate`（:111，**202** 返回 generation_id）、`GET /generations/{generation_id}?task_id=`（:149，**精确 ID 轮询**，无"最新一次"回退；task 域不符即 404）。
- **叙事（R2d，report_narrative.py)**：`GET /narrative/versions/{report_id}?task_id=`（:55）——一个精确已发布叙事版本，只返回持久化版本行 + manifest，无 envelope 字节、无系统提示词、无文件路径（:1-11）。
- **流水线尾闸（report_pipeline_tail.py，C++ 专用）**：`POST /pipeline-tail`（:137，**202**）启动或挂接该任务的首阶段"材料自主研判"报告尾；`GET /pipeline-tail/status?task_id=`（:164-171）回报进度。语义约束：请求体与 R2c 同形（TailRequest，extra=forbid，:56-59）；`report_auto_generate_enabled` 关闭时 503（:145-146）；已有同模式报告版本时直接回 completed 短路（:154-157）；**任务只有等尾闸到 completed 才允许标 COMPLETED**（模块 docstring :1-8）。

## 5. 数据流（读什么库/服务、写什么）

**写**：`reports.db`（ReportRepository，{FORENSIC_REPORT_DIR} 下）+ 报告输出目录（staging 目录原子落盘 manifest.json、分类页文件、检索索引 SQLite——`search_documents` 表，services/forensic_report/search_index.py:12-40；写入流程见 snapshot_writer.py:157-280 的 staging→manifest 组装）。**读**：A 链文件端点经 `_file_response`（forensic_reports.py:82-106）把落盘文件读出并做严格 JSON 校验：

```python
# forensic_reports.py:78-106
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

R2c 的关键机制在准入服务（services/forensic_report/generation.py:369-414）：

```python
# generation.py:379-414（节选）
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

`admit` 只拿 task_id：经 C++ 校验任务身份 → `investigation_db_path_for_task` 找到该任务的 investigation.db → `ReportGenerationInputBuilder` 从 R1 绑定组装冻结 envelope（main/appendix 为空 → `no_report_evidence` → 路由层转 409，report_generation.py:128-131）→ 对 envelope 做规范化 JSON 的 SHA-256 得 `input_hash`（generation.py:413-414）后落 `reports.db` 准入行，`executor.submit` 后台执行（report_generation.py:143）；路由立即用严格读取回读当前行返回（:144-146）。类 docstring（generation.py:355-363）写明冻结动机：envelope 在一个读事务内组装完毕、准入行不可变，之后分析师改绑定/排除/新增证据都改不了已准入的输入。轮询端点 `include_report=row.status == "completed"`（:164）——manifest 只在完成态附带。

R1 绑定的服务端三重校验（task 存在、证据已捕获、analysis_id 属于同证据的已接受分析）在 services/investigation/report_evidence.py，冲突类型 `AnalysisBindingConflictError`/`ReportEvidenceConflictError` 映射 409。

R2d 的响应模型 `NarrativeReportResponse`（report_narrative.py:34-52）字段与 manifest 一一对应（version/generation_id/model/prompt_version/input_hash/sections/citations），读取走 `read_narrative_version_strict`（:64-66）——身份不符返回 None 即 404。

## 6. 边界与已知状态（409/500/501/降级）

- **501**：`scope_type=case` 的报告生成显式 `NotImplementedError` → 路由转 501 "report scope type is not supported"（forensic_reports.py:133-135；services/forensic_report/service.py:102-103）——任务域是唯一支持的 scope。
- **409**：`no_report_evidence`（生成无证据可写，report_generation.py:128-131）、绑定/重复冲突（R1 的 :194-201）；A 链文件在报告未就绪时 `RuntimeError` → 409 "report is not ready"（forensic_reports.py:66-67、:87-88）。
- **500 完整性 token**：资源完整性（`_RESOURCE_INTEGRITY_DETAIL`）与检索索引不可用（`_SEARCH_INTEGRITY_DETAIL`）都是固定短句，不泄内部异常（forensic_reports.py:25-26）。
- **不透明缺失**：R2d 的跨任务 report_id 与不存在的 report_id 同样返回 404，不可区分（report_narrative.py:7-10）；轮询同理（task 域强校验，report_generation.py:159-163）。
- R1 的 PUT 要求至少给 `report_status` 或 `analysis_id` 之一，否则 422（report_evidence.py:234-238）；省略 `analysis_id` 表示"保持当前冻结绑定"，绝不自动跟随新版本。
- 服务重启恢复：`resume_unfinished` 会把未完成的版本标记为 `service_restart` 失败并要求新建版本（service.py:93-99），客户端不会永远轮询一个死任务。
- env：`FORENSIC_REPORT_DIR`（默认 build/data/reports）、`FORENSIC_REPORT_GENERATOR_VERSION`（默认 1.0.0，写入 manifest）。

## 7. 如何验证

- 路由层：`python_service/tests/unit/forensic_report/test_routes.py`（A 链）、`test_report_generation_routes.py`（202/轮询/409）、`test_report_narrative_routes.py`（R2d 严格读）；R1 由 `tests/unit/investigation/test_report_evidence_routes.py` 覆盖。
- 服务层：`tests/unit/forensic_report/`（repository/snapshot_writer/search_index/generation_admission/generation_execution/models/ids）。
- 前端契约：`web/src/services/reportService.test.js`、`reportDataSource.test.js`、`pages/ForensicReportPage.generation.test.jsx`。
- 活体链路：`make acceptance-analyst`（docs/testing/live-integration.md Journey B 第 6-7 步：R1 精确 analysis_id 绑定 → 生成 → 轮询 → manifest 引用回指精确 Evidence/Analysis/Claim ID）。

相关阅读：[Investigation.md](Investigation.md)（R1 绑定的上游评审流）、[LLM.md](LLM.md)（旧 410 生成器的退役历史）。

## 8. 二轮深化 A：端点全表（17 个，含参数与状态码）

| 端点 | 方法 | 请求要点 | 成功码 | 错误码 |
|---|---|---|---|---|
| /api/reports | POST | `{scope_type,scope_id,task_ids,title}`（case→501） | **202** | 501、503、422 |
| /api/reports | GET | query `scope_type`+`scope_id` | 200 | 422 |
| /api/reports/tasks/{task_id} | DELETE | 路径 `task_id`（C++ 任务删除路径调用；级联清理版本/快照/翻译缓存，保留不可变的 generation 输入行） | 200 | 409 生成中、500 清理不完整、503 |
| /{report_id}/status | GET | — | 200 | 404、503 |
| /{report_id}/manifest | GET | — | 200（冻结 JSON 字节） | 404、409 未就绪、500 完整性 |
| /{report_id}/categories/{category_id}/pages/{page} | GET | 路径参数 | 200 | 404、409、500 完整性 |
| /{report_id}/search | GET | query `q`（必填）、`offset=0`、`limit` | 200 | 404、409、500 索引完整性 |
| /api/reports/evidence | GET | query `task_id` | 200 | 503 |
| /api/reports/evidence/file-candidates | GET | query `task_id`（必填）、`search`、`status`、`analyzed`、`page`、`page_size`（纯读侧候选列表） | 200 | 404、503 |
| /api/reports/evidence/seed-analyzed | POST | `{task_id,added_by}`（初管全量入报，幂等，已有判定一律跳过） | 200 | 404、409、503 |
| /api/reports/evidence | POST | 严格 body（见 R1 模型） | 200/201 | 404、409、422、503 |
| /api/reports/evidence | PUT | `report_status` 或 `analysis_id` 至少其一 | 200 | 404、409、422、503 |
| /api/reports/generate | POST | `{task_id,requested_by}`（extra=forbid） | **202** | **409** no_report_evidence、404、422、503 |
| /api/reports/generations/{generation_id} | GET | query `task_id`（域强校验） | 200 | 404（含跨任务不可区分） |
| /api/reports/narrative/versions/{report_id} | GET | query `task_id` | 200 | 404（跨任务同形态） |
| /api/reports/pipeline-tail | POST | 同 R2c 形状的 TailRequest（extra=forbid，C++ 专用） | **202** | 503（关闭或服务不可用） |
| /api/reports/pipeline-tail/status | GET | query `task_id` | 200 | 404 未启动 |

## 9. 二轮深化 B：ReportStatus 版本状态机（models.py:38-42）

`queued → generating → ready | failed`，外加一条恢复边：

| 转移 | 触发 | 伴随列更新 |
|---|---|---|
| → queued | POST /api/reports 落行 | stage="queued"、progress=0 |
| queued → generating | 快照 writer 接手 | stage/progress 随阶段推进（0-100，ge/le 由模型约束） |
| generating → ready | staging 目录原子落盘完成 | generated_at、manifest_path、warnings |
| generating → failed | 任一阶段异常 | error |
| （恢复边）admitted/generating → failed | 服务重启 `resume_unfinished`（service.py:93-99） | error 指明 `service_restart`，客户端须新建版本 |

`report_kind` 旁路标记：None=确定性快照行、`'llm_generation'`=R2c 发布事务写入的叙事版本——同一张表两种产物靠它区分，R2d 只回后者。

## 10. 二轮深化 C：generation 生命周期状态机（DB 触发器背书，repository.py:103-180）

`report_generation_inputs.status` 三态 + 终态不可变，**由六个数据库触发器强制**（不是服务层约定）：

| 触发器 | 强制的不变量 |
|---|---|
| trg_report_generation_input_frozen | 准入后 identity/scope/requester/prompt_version/envelope 字节/input_hash/created_at 九列**任何修改即 ABORT** |
| trg_report_generation_input_no_delete | 行不可删除（审计轨迹） |
| trg_report_generation_status_transition | 合法转移仅：admitted→running\|failed、running→completed\|failed、自环 |
| trg_report_generation_completed_invariants | completed 必须带 report_id+produced_version+model+completed_at |
| trg_report_generation_failed_invariants | failed 必须 failed_at 非空且**不得**引用任何已发布版本 |
| trg_report_generation_terminal_immutable | 终态行的执行列（时间戳/model/版本/错误）全部冻结 |

状态流转：`admitted`（准入落行，DEFAULT 'admitted'，repository.py:84）→ `running`（executor 接手）→ `completed`（发布事务写 report_id+produced_version）或 `failed`（error_code 如 `llm_unavailable`（generation_execution.py:501，LLM 服务缺失时持久失败）与 `service_restart`（:321，重启恢复把 stale admitted/running 打失败））。轮询端点据此返回：completed 附 manifest、failed 带 error_code/error_message。

## 11. 二轮深化 D：reports.db 表契约（2 张表）

**report_versions（repository.py:46-64）**：16 列——report_id（PK）、version、scope_type、scope_id、status、title、task_ids_json、stage、progress（DEFAULT 0）、generated_at、manifest_path、offline_bundle_path、warnings_json（DEFAULT '[]'）、error、created_at、report_kind；UNIQUE(scope_type,scope_id,version) + 索引 idx_report_scope（scope+version DESC，列表查询走它）。

**report_generation_inputs（:79-100）**：19 列——generation_id（PK）、task_id、scope_type、scope_id、status（DEFAULT 'admitted'）、requested_by、input_schema_version、prompt_version、input_envelope_json、input_hash、report_id、produced_version、model、created_at、started_at、completed_at、failed_at、error_code、error_message；**CHECK(scope_type='task' AND scope_id=task_id)** 在 DB 层封死 case 域；索引 idx_report_generation_task(task_id,created_at) 支撑"任务下的生成历史"查询。

R1 的绑定行不在 reports.db——在任务各自的 investigation.db `report_evidence` 表（见 [Investigation.md](Investigation.md) 第 10 节），生成准入经 `investigation_db_path_for_task` 跨库读取。

## 12. 二轮深化 E：新走读——terminal_immutable 的工程含义（并发收口）

```python
# repository.py:164-180（节选）
CREATE TRIGGER IF NOT EXISTS trg_report_generation_terminal_immutable
BEFORE UPDATE ON report_generation_inputs
FOR EACH ROW
WHEN OLD.status IN ('completed', 'failed') AND (
    NEW.status IS NOT OLD.status
    OR NEW.started_at IS NOT OLD.started_at
    ... (八列逐列比较)
)
BEGIN
    SELECT RAISE(ABORT, 'report generation terminal row is immutable');
END
```

逐块解释：终态行允许的唯一"更新"是不改任何执行列的等值写（每列 `IS NOT` 比较兼容 NULL）。工程含义有两点：① **迟到的 worker 与重启恢复不会互相覆盖**——一个已经 completed 的 generation，即使有滞留的旧协程试图把它改回 failed（例如发布成功后 LLM 连接才超时），数据库直接 ABORT，发布结果不丢；② 恢复逻辑 `initialize`（generation_execution.py:310-323）只敢碰 admitted/running 行，terminal 行的命中会以 IntegrityError 暴露编程错误而不是静默改历史。这与 investigation 侧 EV4 触发器（版本不可 UPDATE）构成同一套"不可变靠数据库不靠自觉"的纪律。

## 13. 二轮深化 F：pipeline-tail 的僵尸生成自愈（report_pipeline_tail.py）

尾闸是初次分析流的最后一步，它的可靠性问题被写在常量旁（report_pipeline_tail.py:27-32）："A 'running' entry whose generation stopped advancing is a zombie: the in-memory record survives, but nothing is executing behind it. Without this check the status endpoint reported 'running' forever... every retry reused the same dead generation (observed on PC.E01)."

```python
# report_pipeline_tail.py:25-32、:37-53（节选）
GENERATION_TIMEOUT_S = 3600
POLL_INTERVAL_S = 10
STALE_RUNNING_S = 900

def _is_stale(entry: dict) -> bool:
    if entry.get("state") != "running":
        return False
    updated = entry.get("updated_at")
    if not updated:
        return True
    return (time.time() - updated) > STALE_RUNNING_S
```

三道防线：① 等待循环本身是活性证明——`_wait_generation` 每次轮询都会刷新 entry 的 `updated_at`（:88-92 注释："This loop is the only thing proving the tail is alive"），所以健康的等待永远不会被判僵尸；② 15 分钟无进展即判 stale，POST 与 GET 两侧都会在入口处把僵尸条目**重置回 idle** 并记 `stale_generation_reset`（:47-53），于是重试可以干净地重新准入，而不是永远复用一个死 generation；③ 单个 generation 内部还有 60 分钟硬超时（`report_tail_timeout`，:94-95）。另一个语义细节：`auto_generate_pipeline_report` 返回 `skipped` 时尾闸记为 **completed 而非 failed**（:115-124）——纯逻辑手机源没有 `files` 表、无可 seed 证据，"没东西可生成"是分析成功任务的正常形态，记 failed 会让 C++ 完成门误杀好任务。幂等闸：executor 已有 `evidence_only` 模式报告版本时直接短路 completed（:154-157），重摄入或手动生成不会被重复。

**最后更新**: 2026-11-10（补流水线尾闸 report_pipeline_tail.py）
