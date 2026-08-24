# CaseAnalysis 路由（python_service/httpserver/routes/case_analysis.py + case_analysis_endpoints/ + multi_analysis.py + intelligence_report.py，前缀 /api/llm）

> **一句话**：案件维度分析的三条腿——单任务案情描述与二次分析（case_analysis_endpoints）、多镜像案件的 CRUD/跨镜像 LLM 分析/增量复用（multi_analysis），以及 `/case-intelligence` 只读取证研判报告读端（intelligence_report）；其中旧的 `POST /api/llm/case-analysis` 生成器已固定 410 退役。

## 1. 这组路由承担什么职责（为什么存在）

case_analysis.py 本体只是**聚合器**：把 `_case.py`、`_windows.py`、intelligence_report.py 三个子路由 include 进同一个 `/api/llm` 挂载点（case_analysis.py:37-40），公共面不变。multi_analysis.py 独立挂载（main.py:238），负责案件（ForensicCase）这一层：案件记录的 CRUD 是 C++ 后端的**代理**，跨镜像分析是 Python 的 LLM 编排。intelligence_report.py 是刻意与版本化报告（/api/reports）和旧生成器分开的**只读 reader**（intelligence_report.py:1-14）：只读任务元数据、files.db、events.db 和五章节 LLM 报告文本，从不把 case_analysis 表当原始证据、从不变异源库（metadata 表除外，见第 4 节）。

## 2. 典型调用方（前端哪个页面/组件）

- **_case / _windows**：`web/src/services/caseAnalysisService.js`（case-description :13、分析轮询 :38、case-report :78、filtered-files :86、reanalyze-files :98），主要消费者是 `/analysis-center` 页（pages/AnalysisCenter.jsx:15）。
- **multi_analysis**：`web/src/services/caseGroupService.js`（cases CRUD :12-21、associate-tasks :33、multi-image-analysis+轮询 :47-56、case-report-by-case :64、delete :89），消费者是 `/cases` 多镜像案件页（pages/Cases.jsx:18 `pollMultiAnalysis`、caseSlice 的 `startCrossAnalysis`）。
- **intelligence_report**：`web/src/services/intelligenceReportService.js`（report/records/search/metadata GET+PUT :13-49），消费者是 `/case-intelligence` 页（pages/CaseIntelligence.jsx，配套 CaseIntelligence.test.jsx）。

## 3. 核心数据结构

multi_analysis 的作业状态与请求模型（multi_analysis.py:30-49）：

```python
# multi_analysis.py:30-31
# In-memory job store (same pattern as case_analysis.py)
_jobs: Dict[str, Dict[str, Any]] = {}

# multi_analysis.py:42-49
class MultiImageAnalysisRequest(BaseModel):
    case_id: str           = Field(..., description="案件 ID（C++ 后端）")
    task_ids: List[str]    = Field(..., description="所有任务 ID（顺序与 files_db_paths 对应）")
    files_db_paths: List[str] = Field(..., description="_files.db 路径列表")
    case_description: str  = Field(..., description="案情描述")
    max_filter_files: int  = Field(default=400, ge=1, le=2000)
```

逐字段：`task_ids` 与 `files_db_paths` **必须等长**（:229-233 校验）且按索引配对——但后者只是"精确校验的过时提示"（见第 4 节 D2b 段）；`max_filter_files` 限制确定性过滤的文件上限（默认 400）。`_jobs` 是模块级 dict，作业行形如 `{job_id, case_id, status, progress:{stage,message}, result, error, created_at}`（:256-264）——**进程内存态**，重启即失。案件状态查询模型 `CaseAnalysisStatusResponse`（:81-95）给出 per-task 的 analysis_status/files_count/analyzed_files_count 等聚合。

_case 族的作业注册表是 `_helpers.py` 里的另一个内存 dict（case_analysis_endpoints/_helpers.py:18-20），reanalyze 写入的行带 kind 标记（_case.py:150-157）：

```python
# case_analysis_endpoints/_case.py:150-157
_analysis_jobs[job_id] = {
    "kind": "reanalyze",
    "status": "running",
    "current_step": "重新分析",
    "detail": f"正在重新分析 {len(request.file_paths)} 个文件...",
    "task_id": request.task_id,
    "result": None,
}
```

轮询端靠 `kind in {"reanalyze","windows"}` 放行（:193-197）——这是退役 410 与存活轮询共存机制的一半；另一半是服务实例的懒加载注入（_helpers.py:23-43）：`get_case_analysis_service` 把 llm_service/cpp_backend（必需）与 graphiti_service（可选，失败仅 warning）动态挂到 ServiceManager 私有属性上缓存——与 oss_analysis 同属"绕过正式生命周期"的实用主义模式。

## 3.5 案情描述的持久化转发

`POST /case-description` 不落任何 Python 侧存储，而是直连 C++ 任务系统（tasks.json）：

```python
# case_analysis_endpoints/_case.py:57-69（节选）
# Forward to C++ backend to persist in tasks.json
try:
    cpp_url = settings.cpp_backend_url
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.put(
            f"{cpp_url}/api/tasks/{request.task_id}",
            json={"case_description": request.case_description},
        )
        if resp.status_code not in (200, 204):
            logger.warning(f"C++ backend returned {resp.status_code} for case description update")
except Exception as e:
    logger.warning(f"Could not forward case description to C++ backend: {e}")
```

注意"成功"语义：**C++ 转发失败时端点仍返回 success:true**（仅 warning）——前端拿到 200 不等于案情描述已持久化；后续 multi/reanalyze 读取 case_description 时若 tasks.json 里没有，会拿到空串并以空案情继续跑。这是已知的有意取舍（保存流程不因 C++ 抖动中断）。

## 4. 端点语义分组（散文）

完整契约见 docs/api_reference/Python_REST_API.md 第 4/5 节。分组：

- **案情与二次分析（_case.py）**：`POST /case-description`（:39，持久化经 C++ 任务系统 tasks.json，转发失败仅 warning）；`POST /case-analysis`（:80-92，**固定 410**，见第 5 节）；`POST /reanalyze-files`（:95，用户不满首次描述时带 hint 的二次分析，可多文件同 hint）；读侧 `GET /case-analysis/{job_id}`、`GET /case-report/{task_id}`、`GET /case-report-by-case/{case_id}`、`GET /filtered-files/{task_id}`（:183-:325）。
- **Windows 取证（_windows.py）**：`POST /windows-analysis`（:31）、`GET /windows-report/{task_id}`（:103）、`GET /windows-export/{task_id}/toon`（:153）。
- **智能报告读端（intelligence_report.py）**：`GET /intelligence-report/{task_id}`（:895，目录树 + 各节统计）、`GET .../records`（:964，分类分页记录）、`GET .../search`（:1107，跨分类检索）、`GET/PUT .../metadata`（:1220/:1231，报告元数据回写）。
- **案件与多镜像（multi_analysis.py）**：案件 CRUD 代理（`POST/GET /api/llm/cases`、`GET/DELETE /cases/{id}`、`POST /cases/{id}/tasks`，:98-177）；`POST /cases/{id}/associate-tasks`（:180，读取每个任务真实 `_files.db` 预置 analyzed/pending 状态行，使后续跨镜像分析**复用**已完成任务）；`POST /multi-image-analysis`（:220）+ `GET /multi-image-analysis/{job_id}` 轮询（:311）；增量族 `POST /cases/smart-create`（:322）、`POST /cases/{id}/tasks/incremental`（:360）、`GET /cases/{id}/analysis-status`（:397）、`POST /cases/{id}/incremental-analysis`（:418）。

## 5. 数据流（读什么库/服务、写什么）

**案件 CRUD 是纯代理**：httpx 直连 `settings.cpp_backend_url` 的 `/api/cases*`（multi_analysis.py:107-115 等），Python 不存案件记录。**跨镜像分析的 D2b 信任边界**在启动端点里（multi_analysis.py:229-249）：

```python
# multi_analysis.py:229-249（节选）
if len(req.task_ids) != len(req.files_db_paths):
    raise HTTPException(status_code=400,
        detail="task_ids and files_db_paths must have the same length")

# Each analysis target is resolved server-side from its own task_id
# (D2b); the parallel files_db_paths entries are deprecated exact-
# validated hints, never the authority.
from ..services import task_store

trusted_paths = []
for task_id, supplied_path in zip(req.task_ids, req.files_db_paths):
    try:
        trusted = await task_store.resolve_task_files_db(task_id)
        task_store.validate_legacy_db_path(supplied_path, trusted)
    except task_store.TaskStoreError as exc:
        if exc.code == task_store.TASK_NOT_FOUND:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    trusted_paths.append(str(trusted))
```

每个分析目标都由服务端从 task_id 解析；请求里并行的 `files_db_paths` 只是"精确校验的过时提示"，绝非权威（:235-249 注释）。校验通过后：作业写入 `_jobs`、`asyncio.create_task(_run())` 后台跑 `run_multi_image_analysis`（复用 trusted_paths），同时 PUT C++ 案例状态 analysing → completed/failed（:267-305）；服务重启丢作业状态。分析本体经 `get_case_analysis_service()`（dependencies 注入）编排 LLM，结果回写各任务 `_files.db` 的 LLM 列。reanalyze-files 走同一条纪律：`task_store.resolve_task_files_db` + `validate_legacy_db_path`（_case.py:131-148），案情描述缺省时从任务记录回落（:140-141）。

**intelligence_report 直读 SQLite**：`_connect_ro` 以只读方式打开任务 files.db/events_db（intelligence_report.py:194-198）：

```python
# intelligence_report.py:194-198
def _connect_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10)
```

`mode=ro` URI 保证读路径不可能意外写库（写侧另有 `_connect_rw`，仅 metadata 用）。目录统计用 `COUNT(*)` + `is_deleted`/`scene_relevant`/`llm_is_relevant`（:766-:814）；五章节来自 `_files.db` 里 `case_analysis.case_report` 的 Markdown 按已知章节标题切分（`_load_chapter_markdown`，:815-862）；metadata 是**唯一写路径**——在 files.db 里确保 metadata 表后 upsert（`_ensure_metadata_table`/`_save_metadata`，:271-336）。

## 6. 边界与已知状态（410 退役/内存作业/私有属性）

- **410 退役**：`POST /api/llm/case-analysis` 固定返回 410 "legacy case analysis generation has been retired; use report generation"（_case.py:89-92）——旧的单任务报告生成器已删，**现行替代**是 `/api/reports` 快照报告 + R2c 生成（见 [ForensicReports.md](ForensicReports.md)）以及 multi_analysis 的案件级分析。任何把旧端点当活接口的调用都会拿到 410；`GET /case-analysis/{job_id}` 仍服务于 reanalyze-files 的作业轮询（caseAnalysisService.js:38），不要与退役端点混淆——轮询端对 reanalyze/windows 类作业照常 200，对其它 kind 反手 410（_case.py:193-197）。
- **内存作业**：multi/incremental 的 job_id 查询只在本进程 `_jobs` 里命中，重启后 404（multi_analysis.py:30、:314-317）——与 /api/reports 的持久化 generation 轮询是两种不同持久级。
- **私有属性穿透**：`GET /cases/{id}/analysis-status` 直接摸 `svc._case_aggregation`（multi_analysis.py:411-414），是路由层访问服务私有成员的例外，重构时需留意。
- intelligence_report 的所有统计读失败都降级为 0 计数并 warning（:780-:813 各 `except sqlite3.Error`），不会让整页 500。
- 案件删除**不**删关联任务（multi_analysis.py:147 docstring 明示）；C++ 状态更新失败被吞（`except Exception: pass`，:273-274）——分析仍继续，只是案件状态可能滞后。
- env：`FILE_FILTER_MODE`（deterministic|llm，默认 deterministic——过滤模式切换）、`FILTER_MAX_FILES`（0=不限）、`CPP_BACKEND_URL`。

## 7. 如何验证

- `python_service/tests/unit/test_case_analysis_routes.py`（case-analysis 410 与 _case 契约）、`test_intelligence_report_routes.py`（目录/分页/检索/metadata）、`test_multi_deterministic_filter.py`（多镜像过滤确定性）、`test_d2b_db_ownership.py` / `test_d2b_task_store.py`（files_db_paths 提示校验）。
- 前端契约：`web/src/pages/CaseIntelligence.test.jsx`。
- 手工链路：`POST /api/llm/cases` → `POST /api/llm/cases/{id}/associate-tasks` → `POST /api/llm/multi-image-analysis` → 轮询 job → `GET /api/llm/case-report-by-case/{id}`。

相关阅读：[ForensicReports.md](ForensicReports.md)（410 的现行替代）、[LLM.md](LLM.md)（同前缀的通用分析与 reanalyze 的底层）、[HTTPRoutes.md](../HTTPRoutes.md)。

## 8. 二轮深化 A：端点全表（27 个）

**_case.py（7 个）**

| 端点 | 方法 | 请求要点 | 成功码 | 特殊码 |
|---|---|---|---|---|
| /api/llm/case-description | POST | task_id+case_description | 200 | C++ 转发失败仍 200（warning） |
| /api/llm/case-analysis | POST | — | — | **固定 410** |
| /api/llm/case-analysis/{job_id} | GET | — | 200 | 404；kind 不在 {reanalyze,windows} → 410 |
| /api/llm/reanalyze-files | POST | task_id+file_paths[]+hint | 202/200 | 404、400（D2b） |
| /api/llm/case-report/{task_id} | GET | — | 200 | 404 |
| /api/llm/case-report-by-case/{case_id} | GET | — | 200 | 404 |
| /api/llm/filtered-files/{task_id} | GET | — | 200 | 404 |

**_windows.py（3 个）**：`POST /windows-analysis`（202 风格作业）、`GET /windows-report/{task_id}`、`GET /windows-export/{task_id}/toon`（TOON 流）。

**intelligence_report.py（5 个）**：`GET /intelligence-report/{task_id}`（目录树+统计）、`GET .../records?category=&offset=&limit=`（分类分页）、`GET .../search?q=`（跨分类）、`GET .../metadata`、`PUT .../metadata`（唯一写路径，metadata 表 upsert）。

**multi_analysis.py（12 个）**

| 端点 | 方法 | 成功码 | 备注 |
|---|---|---|---|
| /api/llm/cases | POST/GET | 200 | 纯代理 C++ /api/cases |
| /api/llm/cases/{id} | GET/DELETE | 200 | 删除不级联删任务 |
| /api/llm/cases/{id}/tasks | POST | 200 | 代理 |
| /api/llm/cases/{id}/associate-tasks | POST | 200 | 预置 analyzed 状态行（复用） |
| /api/llm/cases/smart-create | POST | 200 | 智能建案 |
| /api/llm/cases/{id}/tasks/incremental | POST | 200 | 增量追加 |
| /api/llm/cases/{id}/analysis-status | GET | 200 | 摸 svc._case_aggregation（私有穿透） |
| /api/llm/cases/{id}/incremental-analysis | POST | 200 | 增量分析（同样走 _jobs） |
| /api/llm/multi-image-analysis | POST | 200 | 400（长度不等）、404/400（D2b） |
| /api/llm/multi-image-analysis/{job_id} | GET | 200 | 404（内存态丢失） |

## 9. 二轮深化 B：内存作业状态机（两个注册表对照）

| 维度 | multi_analysis._jobs（:30） | _helpers._analysis_jobs（:18-20） |
|---|---|---|
| 状态值 | running → completed \| failed（:259/:289/:299；无 pending/cancelled） | running → 终态（reanalyze/windows kind） |
| 进度 | `progress: {stage, message}` 由服务层 progress_cb 回写（:277-278） | `current_step`/`detail` 字符串 |
| error | 固定文案 "multi-image analysis failed"（:300，**不含 str(e)**） | 同风格 |
| 副信道 | PUT C++ `/api/cases/{id}/status`：analysing → completed/failed（:267-306） | 无 |
| 持久级 | 进程内存 | 进程内存 |

状态机注释：multi 作业创建即 running（与 FileAnalyzer 批量一致、与 Graphiti 作业不同——后者有 pending 排队态）；C++ 案件状态是**尽力而为的第二真源**：三处 PUT 里只有第一处（analysing）包了 `except Exception: pass`（:272-274），completed/failed 两处若 C++ 宕机会把异常留在后台 task 里（asyncio 默默记录），案件状态可能滞留在 analysing。

## 10. 二轮深化 C：新走读——multi-image-analysis 的 C++ 状态联动分支

```python
# multi_analysis.py:267-306（骨架）
try:
    async with httpx.AsyncClient(timeout=5) as client:
        await client.put(
            f"{settings.cpp_backend_url}/api/cases/{req.case_id}/status",
            json={"status": "analysing", "cross_analysis_job_id": job_id},
        )
except Exception:
    pass

async def _run():
    async def progress_cb(stage: str, msg: str):
        _jobs[job_id]["progress"] = {"stage": stage, "message": msg}
    try:
        result = await svc.run_multi_image_analysis(..., progress_callback=progress_cb)
        _jobs[job_id]["status"] = "completed"
        _jobs[job_id]["result"] = result
        async with httpx.AsyncClient(timeout=5) as client:
            await client.put(..., json={"status": "completed"})
    except Exception as e:
        logger.error(f"[MULTI_ANALYSIS] Job {job_id} failed: {e}", exc_info=True)
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = "multi-image analysis failed"
        async with httpx.AsyncClient(timeout=5) as client:
            await client.put(..., json={"status": "failed"})
```

逐块解释：① 开局 PUT 携带 `cross_analysis_job_id`——C++ 侧案件记录因此能反查 Python 作业 ID（前端 Cases 页展示分析中状态的数据源）；② progress_cb 是服务层→路由层的唯一进度通道，stage/message 原样透传给轮询端点；③ except 分支记完整 traceback 到日志但对外只给固定文案——**脱敏纪律在这里是对的**；④ 尾部两个 PUT 未包 try/except：C++ 不可用时 _run 协程以异常收场，`_jobs` 状态已先行写对（completed/failed），但 C++ 案件状态永久停在 analysing——排障看到"案件一直分析中但作业早已 completed"时先查这三个 PUT。

## 11. 二轮深化 D：intelligence_report 数据契约要点

- `_connect_ro`（:194-198）：`file:<percent-encoded>?mode=ro` URI + timeout=10——路径含中文/空格也安全（quote(safe='/')）；对照 `_connect_rw` 仅 metadata 表使用。
- 目录树统计的三个口径列：`is_deleted`（删除文件单独成组）、`scene_relevant`、`llm_is_relevant`——与 files 表的列名一一对应（[FilesDB.md](../../../../schema/FilesDB.md)）。
- 五章节来源：`case_analysis.case_report` 的 Markdown 按已知标题切分（`_load_chapter_markdown`，:815-862）——章节标题集合是隐式契约，改名即切不出章节。
- metadata 表：`_ensure_metadata_table` 建表后 upsert（:271-336），键为 task 维度；PUT 端点接受任意 JSON 值（无 Pydantic 深度校验）。

## 12. 二轮深化 E：前端调用矩阵（与 web/Services.md 对齐）

| 前端方法 | 端点 | 页面 |
|---|---|---|
| saveCaseDescription（caseAnalysisService.js:13） | POST /case-description | AnalysisCenter |
| getCaseAnalysisStatus+pollCaseAnalysis（:38） | GET /case-analysis/{job_id} | 同上（3s 轮询） |
| getCaseReport / getFilteredFiles / reanalyzeFiles（:78/:86/:98） | 对应 GET/POST | Files 二次分析 |
| startCaseAnalysis（:29-31） | （throw 存根） | **已退役**，调用方应改走报告生成 |
| caseGroupService 全族（:12-89） | /api/llm/cases*、multi-image-analysis | /cases 页 |
| intelligenceReportService（:13-49） | /intelligence-report/* | /case-intelligence |

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
