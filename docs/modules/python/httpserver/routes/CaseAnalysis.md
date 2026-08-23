# CaseAnalysis 路由（python_service/httpserver/routes/case_analysis.py + case_analysis_endpoints/ + multi_analysis.py + intelligence_report.py，前缀 /api/llm）

> **一句话**：案件维度分析的三条腿——单任务案情描述与二次分析（case_analysis_endpoints）、多镜像案件的 CRUD/跨镜像 LLM 分析/增量复用（multi_analysis），以及 `/case-intelligence` 只读取证研判报告读端（intelligence_report）；其中旧的 `POST /api/llm/case-analysis` 生成器已固定 410 退役。

## 1. 这组路由承担什么职责（为什么存在）

case_analysis.py 本体只是**聚合器**：把 `_case.py`、`_windows.py`、intelligence_report.py 三个子路由 include 进同一个 `/api/llm` 挂载点（case_analysis.py:37-40），公共面不变。multi_analysis.py 独立挂载（main.py:238），负责案件（ForensicCase）这一层：案件记录的 CRUD 是 C++ 后端的**代理**，跨镜像分析是 Python 的 LLM 编排。intelligence_report.py 是刻意与版本化报告（/api/reports）和旧生成器分开的**只读 reader**（intelligence_report.py:1-14）：只读任务元数据、files.db、events.db 和五章节 LLM 报告文本，从不把 case_analysis 表当原始证据、从不变异源库。

## 2. 典型调用方（前端哪个页面/组件）

- **_case / _windows**：`web/src/services/caseAnalysisService.js`（case-description :13、分析轮询 :38、case-report :78、filtered-files :86、reanalyze-files :98），主要消费者是 `/analysis-center` 页（pages/AnalysisCenter.jsx:15）。
- **multi_analysis**：`web/src/services/caseGroupService.js`（cases CRUD :12-21、associate-tasks :33、multi-image-analysis+轮询 :47-56、case-report-by-case :64、delete :89），消费者是 `/cases` 多镜像案件页（pages/Cases.jsx:18 `pollMultiAnalysis`、caseSlice 的 `startCrossAnalysis`）。
- **intelligence_report**：`web/src/services/intelligenceReportService.js`（report/records/search/metadata GET+PUT :13-49），消费者是 `/case-intelligence` 页（pages/CaseIntelligence.jsx，配套 CaseIntelligence.test.jsx）。

## 3. 端点语义分组（散文）

完整契约见 docs/api_reference/Python_REST_API.md 第 4/5 节。分组：

- **案情与二次分析（_case.py）**：`POST /case-description`（:39，持久化经 C++ 任务系统 tasks.json，转发失败仅 warning）；`POST /case-analysis`（:80-92，**固定 410**，见第 5 节）；`POST /reanalyze-files`（:95，用户不满首次描述时带 hint 的二次分析，可多文件同 hint）；读侧 `GET /case-analysis/{job_id}`、`GET /case-report/{task_id}`、`GET /case-report-by-case/{case_id}`、`GET /filtered-files/{task_id}`（:183-:325）。
- **Windows 取证（_windows.py）**：`POST /windows-analysis`（:31）、`GET /windows-report/{task_id}`（:103）、`GET /windows-export/{task_id}/toon`（:153）。
- **智能报告读端（intelligence_report.py）**：`GET /intelligence-report/{task_id}`（:895，目录树 + 各节统计）、`GET .../records`（:964，分类分页记录）、`GET .../search`（:1107，跨分类检索）、`GET/PUT .../metadata`（:1220/:1231，报告元数据回写）。
- **案件与多镜像（multi_analysis.py）**：案件 CRUD 代理（`POST/GET /cases`、`GET/DELETE /cases/{id}`、`POST /cases/{id}/tasks`，:98-177）；`POST /cases/{id}/associate-tasks`（:180，读取每个任务真实 `_files.db` 预置 analyzed/pending 状态行，使后续跨镜像分析**复用**已完成任务）；`POST /multi-image-analysis`（:220）+ `GET /multi-image-analysis/{job_id}` 轮询（:311）；增量族 `POST /cases/smart-create`（:322）、`POST /cases/{id}/tasks/incremental`（:360）、`GET /cases/{id}/analysis-status`（:397）、`POST /cases/{id}/incremental-analysis`（:418）。

## 4. 数据流（读什么库/服务、写什么）

**案件 CRUD 是纯代理**：httpx 直连 `settings.cpp_backend_url` 的 `/api/cases*`（multi_analysis.py:107-115 等），Python 不存案件记录。**跨镜像分析的 D2b 信任边界**在启动端点里：

```python
# multi_analysis.py:243-249（节选）
trusted = await task_store.resolve_task_files_db(task_id)
task_store.validate_legacy_db_path(supplied_path, trusted)
```

每个分析目标都由服务端从 task_id 解析；请求里并行的 `files_db_paths` 只是"精确校验的过时提示"，绝非权威（:235-249 注释）。作业状态存**进程内存字典** `_jobs`（:30）——后台 `asyncio.create_task` 跑 `run_multi_image_analysis`，同时 PUT C++ 案例状态 analysing/completed/failed（:267-305）；服务重启丢作业状态。分析本体经 `get_case_analysis_service()`（dependencies 注入）编排 LLM，结果回写各任务 `_files.db` 的 LLM 列。

**intelligence_report 直读 SQLite**：`_connect_ro` 以只读方式打开任务 files.db/events_db（intelligence_report.py:195-198），目录统计用 `COUNT(*)` + `is_deleted`/`scene_relevant`/`llm_is_relevant`（:766-:814）；五章节来自 `_files.db` 里 `case_analysis.case_report` 的 Markdown 按已知章节标题切分（`_load_chapter_markdown`，:815-862）；metadata 是**唯一写路径**——在 files.db 里确保 metadata 表后 upsert（`_ensure_metadata_table`/`_save_metadata`，:271-336）。

## 5. 边界与已知状态（410 退役/内存作业/私有属性）

- **410 退役**：`POST /api/llm/case-analysis` 固定返回 410 "legacy case analysis generation has been retired; use report generation"（_case.py:89-92）——旧的单任务报告生成器已删，**现行替代**是 `/api/reports` 快照报告 + R2c 生成（见 [ForensicReports.md](ForensicReports.md)）以及 multi_analysis 的案件级分析。任何把旧端点当活接口的调用都会拿到 410；`GET /case-analysis/{job_id}` 仍服务于 reanalyze-files 的作业轮询（caseAnalysisService.js:38），不要与退役端点混淆。
- **内存作业**：multi/incremental 的 job_id 查询只在本进程 `_jobs` 里命中，重启后 404（multi_analysis.py:30、:314-317）——与 /api/reports 的持久化 generation 轮询是两种不同持久级。
- **私有属性穿透**：`GET /cases/{id}/analysis-status` 直接摸 `svc._case_aggregation`（multi_analysis.py:411-414），是路由层访问服务私有成员的例外，重构时需留意。
- intelligence_report 的所有统计读失败都降级为 0 计数并 warning（:780-:813 各 `except sqlite3.Error`），不会让整页 500。
- 案件删除**不**删关联任务（multi_analysis.py:147 docstring 明示）；C++ 状态更新失败被吞（`except Exception: pass`，:273-274）——分析仍继续，只是案件状态可能滞后。

## 6. 如何验证

- `python_service/tests/unit/test_case_analysis_routes.py`（case-analysis 410 与 _case 契约）、`test_intelligence_report_routes.py`（目录/分页/检索/metadata）、`test_multi_deterministic_filter.py`（多镜像过滤确定性）、`test_d2b_db_ownership.py` / `test_d2b_task_store.py`（files_db_paths 提示校验）。
- 前端契约：`web/src/pages/CaseIntelligence.test.jsx`。
- 手工链路：`POST /api/llm/cases` → `POST /api/llm/cases/{id}/associate-tasks` → `POST /api/llm/multi-image-analysis` → 轮询 job → `GET /api/llm/case-report-by-case/{id}`。

相关阅读：[ForensicReports.md](ForensicReports.md)（410 的现行替代）、[LLM.md](LLM.md)（同前缀的通用分析与 reanalyze 的底层）、[HTTPRoutes.md](../HTTPRoutes.md)。

**最后更新**: 2026-08-23（新建，解释式）
