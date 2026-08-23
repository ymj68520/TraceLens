# HTTP 路由总览（python_service/httpserver/routes/）

> **一句话**：`routes/` 目录是 Python 服务对外的 REST 表面——约 20 个路由模块按领域拆分、由 main.py 统一挂载，每组的语义与数据流在 `routes/*.md` 子文档展开。

## 这组路由承担什么职责

路由层是纯粹的"HTTP 适配器"：解析请求参数（Pydantic 模型）、做任务归属/路径安全校验、把工作委托给 ServiceManager 暴露的服务、把结果包成响应模型。**业务逻辑不在这一层**——所有实质工作在 `httpserver/services/` 的服务对象里，路由只负责契约。目录里两个值得注意的结构约定：

- **聚合器模式**：大路由模块（graphiti.py、llm.py 等）已拆成子包（`graphiti_endpoints/`、`llm_endpoints/`、`case_analysis_endpoints/`、`wechat_graph_endpoints/`），聚合器文件（如 graphiti.py:49-54）只是把子模块的 router 串起来并 re-export Pydantic 模型，对 main.py 的公共表面不变。
- **模型分离**：请求/响应模型放在平级的 `*_models.py`（graphiti_models.py、llm_models.py 等），避免子模块间循环导入。

聚合器的真实样子（llm.py 是最小的一个）：

```python
# routes/llm.py:17-35（全文的核心部分）
from .llm_endpoints import _analysis, _management
from .llm_models import (  # noqa: F401
    AnalyzeRequest, AnalyzeResponse, BatchAnalyzeRequest,
    BatchAnalyzeResponse, BatchStatusResponse, ModelInfo,
    ModelsResponse, LLMStatusResponse, ToggleRelevanceRequest,
    EventClusterAnalyzeRequest, ToggleClusterRelevanceRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()
router.include_router(_analysis.router)
router.include_router(_management.router)
```

模块 docstring（llm.py:7-11）明确列出分工：`_analysis.py` 承载 analyze / analyze/file / analyze-event-cluster / batch / batch status，`_management.py` 承载 models / status / 两个 toggle；re-export 的模型仅供外部 import 兼容。

## 典型调用方

| 调用方 | 主要使用的路由组 |
|---|---|
| 前端 `/knowledge-graph` 页（web/src/services/graphitiService.js） | `/api/graphiti/*`（pythonApi） |
| 前端 `/files`、`/analysis-center`、`/llm-descriptions` 页（llmService.js:29-92、forensicsService.js:39-62、associationService.js:28-58） | `/api/llm/*`、`/api/associations/*` |
| 前端 `/case-intelligence`（intelligenceReportService.js:13-49、caseGroupService.js:12-89） | `/api/llm/intelligence-report/*`、`/api/llm/cases*`、`/api/reports/*` |
| 前端 `/investigation` 与调查工作台（investigationService.js:19-349） | `/api/investigation/*`、`/api/reports/evidence*` |
| 前端 `/logs` 页（web/src/pages/Logs.jsx:20,37） | `/api/system/logs/{service}`（SSE 变体同前缀） |
| 前端 `/wechat-graph` 页（wechatService.js:12-89） | `/api/wechat/*` |
| 前端 `/oss` 页（ossService.js:9-60，用 `api` C++ 基座） | 名义上 `/api/forensics/oss/*`（实际 404，见 [routes/OssAnalysis.md](./routes/OssAnalysis.md)） |
| C++ `LLMPythonProxy`（src/network/HTTPServer/LLMPythonProxy.cpp:63-138） | `POST /api/graphiti/ingest`、`/ingest/file`、`/ingest/events`（服务间调用） |
| C++ `MarkitdownProxy`（src/integration/LLMIntegration/MarkitdownProxy.cpp:89-214） | `POST /api/markitdown/convert-one`、`/convert`、`GET /status` |
| C++ `OfficeAnalyzer`（src/analyzers/OfficeAnalyzer/OfficeAnalyzer.cpp:105） | `POST /api/office/parse` |

前端经 `web/src/services/api.js` 的 `pythonApi`（`http://<host>:8090`，timeout 60s，api.js:38-44）访问本组；跨机访问时 baseURL 用浏览器 host 动态推导（api.js:12-17）。

## 端点分组语义（地图，非全表）

完整端点清单见 **docs/api_reference/Python_REST_API.md**；这里只给导航（挂载点均在 main.py:202-246）。

路由模块清单（源文件 → 挂载前缀 → 模型文件）：

| 模块 | 前缀 | 模型 | 子包 |
|---|---|---|---|
| health.py | （无） | 文件内 | — |
| graphiti.py | /api/graphiti | graphiti_models.py | graphiti_endpoints/（5 模块 17 端点） |
| llm.py | /api/llm | llm_models.py | llm_endpoints/（2 模块 9 端点） |
| case_analysis.py | /api/llm | case_analysis_models.py | case_analysis_endpoints/ + intelligence_report.py |
| dll.py | /api/llm | 文件内 | — |
| forensic_reports.py / report_evidence.py / report_generation.py / report_narrative.py | /api/reports | 各文件内 / services 层 | — |
| investigation.py | /api/investigation | services/investigation 模型 | — |
| investigation_workbench.py | /api/investigation/workbench | 文件内 | — |
| multi_analysis.py | （自带 /api/llm/*） | 文件内 | — |
| database.py | /api/db | 文件内 | — |
| office.py / markitdown.py | /api/office、/api/markitdown | 文件内 | — |
| oss_analysis.py | （自带 /api/forensics/oss/ai） | 文件内 | — |
| system.py | /api/system | 文件内 | — |
| associations.py | /api/associations | 文件内 | — |
| wechat_graph.py | /api/wechat | wechat_graph_models.py | wechat_graph_endpoints/（2 模块） |
| system_logs.py | **未注册（死代码）** | — | — |

分组语义：

- **Health（无前缀）**：`/health`、`/health/live`、`/health/ready`，以及寄居在此模块的 `/api/system/redis/status`、`/api/system/info`。→ [routes/Health.md](./routes/Health.md)
- **`/api/graphiti`**：图谱摄取（ingest / ingest-file / ingest-events，支持 `max_episodes`）、后台作业（jobs）、图结构迁移（migrate）、查询（search / entities / relationships）、状态与可视化（status / tasks / graph）。→ [routes/Graphiti.md](./routes/Graphiti.md)
- **`/api/llm`**：内容与图像分析、事件簇分析、批量分析作业、模型状态、相关性开关；同前缀下还挂着 case_analysis（案情描述、二次分析）与 dll 两个模块。→ [routes/LLM.md](./routes/LLM.md)
- **`/api/db`**：对 C++ 产出数据库的**只读**查询与导出（tasks / databases / files / events / export/toon / export/json）。→ [routes/Database.md](./routes/Database.md)
- **`/api/reports`**（4 个模块）：取证报告的生成、证据绑定、渲染与叙事读取。→ [routes/ForensicReports.md](./routes/ForensicReports.md)
- **`/api/investigation`**（+ `/workbench`）：调查捕获、审查、事件刷新、图谱组装。→ [routes/Investigation.md](./routes/Investigation.md)
- **其余**：`/api/office`（Office 文档转换）、`/api/markitdown`（MarkItDown 转换，task 工作区门控）、`/api/system`（日志/SSE）、`/api/wechat`（微信图谱）、`/api/associations`、multi_analysis 与 oss_analysis（无前缀，自有路径）。

## 数据流（读写什么）

所有路由共享同一条依赖链：`get_service_manager()`（dependencies.py:23）→ 各服务。读写面概览：

- **读 C++ 的 SQLite 产出**：`/api/db` 与 `/api/llm` 的分析端点经 CppBackendService 或 task_store 拿到 `<image>_files.db` / `<image>_events.db` 路径后直接 sqlite3 读（如 llm_endpoints/_analysis.py:60 的事件簇读取）。
- **写 C++ 的 SQLite 产出**：LLM 分析结果通过 LLMService.persist_to_files_db/​persist_to_events_db 回写 `llm_*` 列（服务层职责，路由只传参）。
- **读写 Neo4j**：`/api/graphiti` 摄取（写）与查询/可视化（读），经 GraphitiService。
- **后台作业**：批量分析、图谱摄取都返回 job_id，前端轮询 `/api/llm/batch/{id}` 或 `/api/graphiti/jobs/{id}`。

路由→服务的解析链有两层。简单路由直接从单例取服务：

```python
# 各路由文件的统一模式（如 llm_endpoints/_analysis.py:40-41）
from ...services import get_service_manager
service_manager = get_service_manager()
result = await service_manager.llm_service.analyze(...)
```

而 investigation/forensic_reports/report_generation 等强生命周期路由走 FastAPI `Depends` 工厂，把"服务未就绪"翻译成 503：

```python
# routes/report_generation.py:50-56（节选）
def get_report_generation_executor(
    manager: ServiceManager = Depends(_get_service_manager),
) -> ReportGenerationExecutor:
    try:
        return manager.report_generation_executor
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
```

两种写法的区别不只是风格：`get_service_manager()` 是进程级单例（services/__init__.py re-export service_manager.get_service_manager），而 Depends 工厂在**每次请求**时经 ServiceManager 属性访问触发 `_require_service_access()` 状态校验（service_manager.py:375-381），shutting_down/stopped 状态下立刻 503，不会把半死服务交给 handler。

## 边界与已知状态

- **410 退役端点**：`POST /api/llm/case-analysis`（以及旧的 `GET /api/llm/case-analysis/{job_id}`）固定返回 410"legacy case analysis generation has been retired"（case_analysis_endpoints/_case.py:80-92）。旧链路已退役，替代物是 multi_analysis / report 服务——文档若还把它们列为活端点即为错误。退役实现只有三行：

```python
# case_analysis_endpoints/_case.py:88-92
async def start_case_analysis(request: CaseAnalysisRequest, ...):
    """Return the retired contract without scheduling the legacy writer."""
    raise HTTPException(
        status_code=410,
        detail="legacy case analysis generation has been retired; use report generation",
    )
```

- **409/契约边界**：报告与调查路由对状态机违规（如对已完成作业重复提交）返回 409 一类契约错误，细节见 Python_REST_API.md。
- **死代码**：`routes/system_logs.py` 的 router 未在 main.py:199 注册，任何对它的引用都无效；日志端点以 `routes/system.py` 为准。
- **错误文案纪律**：路由异常统一转成简短 HTTPException detail（如 "file analysis failed"），内部异常文本不进响应——与 main.py 全局 500 处理器同一策略。已知偏离此纪律的点：graphiti `_query.py`/`_ingest.py` 的 detail 传 `str(e)`（_query.py:73）、oss_analysis 两个端点（oss_analysis.py:86-88、:121-123）、wechat `_graph.py` 的兜底 500（_graph.py:64-66）。
- **进度/状态三种持久级**：`/api/llm/batch` 与 multi_analysis 的 job 存进程内存（重启即 404）；`/api/graphiti/jobs` 优先 Redis（重启可查，内存回退）；`/api/reports/generations` 持久化在 reports.db——排障时先分清是哪一种。

## 如何验证与扩展

- 路由契约测试集中在 `python_service/tests/unit/`：`test_case_analysis_routes.py`、`test_intelligence_report_routes.py`、`test_investigation_*_routes.py`、`test_wechat_graph_routes.py`、`test_markitdown_routes.py`、`test_dll_route.py` 等。
- 新增端点：放进对应领域模块（或新建子包 + 聚合器），模型放 `*_models.py`，main.py 注册前缀，契约补进 `docs/api_reference/Python_REST_API.md`。
- 契约核对清单：请求模型是否 `extra="forbid"`（canonical 族路由必须）、错误 detail 是否固定短句、job 状态是否说明持久级。

## 完整端点全表（二轮深化，152 个，源码核对）

以下全表由各路由源码的 `@router.*` 装饰器逐一核对生成（含门面背后的子模块），路径均为最终完整路径（挂载前缀已拼入）。这是本目录的权威表面清单，与 `docs/api_reference/Python_REST_API.md` 互为校对物。

**Health（health.py，5 个）**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 进程存活总检（含依赖探测） |
| GET | `/health/live` | 轻量心跳 |
| GET | `/health/ready` | 就绪检查（C++ 连通性门控） |
| GET | `/api/system/redis/status` | Redis 状态（URL 脱敏回显） |
| GET | `/api/system/info` | 配置快照 |

**Graphiti（graphiti_endpoints/，17 个）**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/graphiti/ingest` | 按任务摄取图谱 |
| POST | `/api/graphiti/ingest/file` | 单文件摄取 |
| POST | `/api/graphiti/ingest/events` | 事件库摄取 |
| GET | `/api/graphiti/jobs` | 作业列表 |
| GET | `/api/graphiti/jobs/{job_id}` | 作业状态 |
| DELETE | `/api/graphiti/jobs/{job_id}` | 取消/删除作业 |
| POST | `/api/graphiti/migrate/task/{task_id}` | 单任务图结构迁移 |
| POST | `/api/graphiti/migrate/deduplicate` | 实体去重 |
| GET | `/api/graphiti/migrate/status/{task_id}` | 迁移状态 |
| POST | `/api/graphiti/migrate/cleanup/{task_id}` | 清理任务图谱数据 |
| POST | `/api/graphiti/search` | 图谱语义检索 |
| GET | `/api/graphiti/entities` | 实体列表 |
| GET | `/api/graphiti/relationships` | 关系列表 |
| GET | `/api/graphiti/status` | 服务状态 |
| GET | `/api/graphiti/tasks` | 已摄取任务列表 |
| DELETE | `/api/graphiti/tasks/{task_id}` | 删除任务全部图谱数据 |
| GET | `/api/graphiti/graph` | 可视化图数据 |

**LLM（llm_endpoints/，9 个）**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/llm/analyze` | 文本/内容分析 |
| POST | `/api/llm/analyze/file` | 文件分析（multipart） |
| POST | `/api/llm/analyze-event-cluster` | 事件簇 AI 研判 |
| POST | `/api/llm/batch` | 启动批量分析作业 |
| GET | `/api/llm/batch/{job_id}` | 批量作业状态（内存态） |
| GET | `/api/llm/models` | 可用模型列表 |
| GET | `/api/llm/status` | LLM 服务状态 |
| POST | `/api/llm/toggle-relevance` | 文件相关性人工开关 |
| POST | `/api/llm/toggle-cluster-relevance` | 事件簇相关性开关 |

**Case Analysis（case_analysis_endpoints/ + intelligence_report.py，15 个）**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/llm/case-description` | 保存案情描述 |
| POST | `/api/llm/case-analysis` | **410 退役**（固定 Gone） |
| GET | `/api/llm/case-analysis/{job_id}` | 旧作业状态（退役链路） |
| POST | `/api/llm/reanalyze-files` | 二次筛选分析 |
| GET | `/api/llm/case-report/{task_id}` | 单镜像案情报告 |
| GET | `/api/llm/case-report-by-case/{case_id}` | 跨镜像报告 |
| GET | `/api/llm/filtered-files/{task_id}` | 筛选结果文件集 |
| POST | `/api/llm/windows-analysis` | Windows 工件分析作业 |
| GET | `/api/llm/windows-report/{task_id}` | Windows 报告 |
| GET | `/api/llm/windows-export/{task_id}/toon` | 导出 TOON |
| GET | `/api/llm/intelligence-report/{task_id}` | 情报报告读取 |
| GET | `/api/llm/intelligence-report/{task_id}/records` | 记录分页 |
| GET | `/api/llm/intelligence-report/{task_id}/search` | 报告内检索 |
| GET | `/api/llm/intelligence-report/{task_id}/metadata` | 元数据 |
| PUT | `/api/llm/intelligence-report/{task_id}/metadata` | 更新元数据 |

**DLL（dll.py，1 个）**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/llm/analyze/dll` | DLL 依赖分析（转发 C++） |

**Reports（4 模块，12 个）**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/reports` | 创建报告版本（202） |
| GET | `/api/reports` | 版本列表 |
| GET | `/api/reports/{report_id}/status` | 版本状态 |
| GET | `/api/reports/{report_id}/manifest` | 版本清单 |
| GET | `/api/reports/{report_id}/categories/{category_id}/pages/{page}` | 分类分页正文 |
| GET | `/api/reports/{report_id}/search` | 报告内检索 |
| GET | `/api/reports/evidence` | 证据列表 |
| POST | `/api/reports/evidence` | 新增证据 |
| PUT | `/api/reports/evidence` | 更新证据 |
| POST | `/api/reports/generate` | 触发生成（R2c 冻结契约） |
| GET | `/api/reports/generations/{generation_id}` | 生成状态（exact id 轮询） |
| GET | `/api/reports/narrative/versions/{report_id}` | 已发布叙事版 |

**Investigation 冻结契约（investigation.py，17 个）**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/investigation/snapshots` | 捕获调查快照 |
| GET | `/api/investigation/evidence` | 证据列表 |
| GET | `/api/investigation/evidence/snapshot` | 快照证据 |
| POST | `/api/investigation/analyses` | 创建二次分析 |
| GET | `/api/investigation/analyses` | 分析列表 |
| GET | `/api/investigation/analyses/{analysis_id}` | 单条分析 |
| GET | `/api/investigation/analyses/{analysis_id}/claims` | 分析声明 |
| POST | `/api/investigation/analyses/{analysis_id}/review` | 审查结论 |
| POST | `/api/investigation/events` | 创建调查事件 |
| GET | `/api/investigation/events` | 事件列表 |
| GET | `/api/investigation/events/{event_id}` | 单事件 |
| GET | `/api/investigation/events/{event_id}/versions` | 事件版本链 |
| POST | `/api/investigation/events/{event_id}/evidence` | 绑定证据 |
| GET | `/api/investigation/events/{event_id}/evidence` | 事件证据 |
| POST | `/api/investigation/events/{event_id}/refresh` | 触发事件刷新 |
| GET | `/api/investigation/events/{event_id}/refreshes` | 刷新历史 |
| GET | `/api/investigation/graph` | 调查图谱 |

**Investigation Workbench（investigation_workbench.py，35 个）**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/investigation/workbench/{task_id}` | 工作台总览 |
| POST | `…/bootstrap` | 初始化调查（mode=cluster_seed） |
| GET | `…/events` | 事件列表 |
| GET | `…/events/{event_id}` | 单事件 |
| POST | `…/events/{event_id}/review` | 事件审查 |
| GET | `…/events/{event_id}/evidence` | 事件证据 |
| POST | `…/events/{event_id}/evidence/link` | 关联证据 |
| POST | `…/events/{event_id}/refresh` | 触发刷新 |
| GET | `…/events/{event_id}/refreshes` | 刷新记录 |
| GET | `…/events/{event_id}/versions` | 版本链 |
| POST | `…/events/{event_id}/versions/{version_id}/accept` | 接受版本 |
| POST | `…/events/{event_id}/versions/{version_id}/reject` | 拒绝版本 |
| GET | `…/events/{event_id}/versions/{version_id}/claims` | 版本声明 |
| GET | `…/events/{event_id}/claims/effective` | 生效声明集 |
| POST | `…/events/{event_id}/versions/{version_id}/claims/{claim_id}/accept` | 接受声明 |
| POST | `…/events/{event_id}/versions/{version_id}/claims/{claim_id}/reject` | 拒绝声明 |
| GET | `…/claims/{claim_id}` | 单声明 |
| GET | `…/evidence/detail` | 证据详情 |
| POST | `…/evidence/analyze` | 证据分析作业 |
| GET | `…/evidence/analysis` | 证据分析结果 |
| GET | `…/analysis-jobs/{job_id}` | 分析作业状态 |
| POST | `…/analysis/{analysis_id}/accept` | 接受二次分析 |
| POST | `…/analysis/{analysis_id}/reject` | 拒绝二次分析 |
| POST | `…/notes` | 新增笔记 |
| GET | `…/notes` | 笔记列表 |
| GET | `…/report-evidence` | 报告证据列表 |
| PUT | `…/report-evidence` | 更新报告证据 |
| POST | `…/report-evidence/remove` | 移除报告证据 |
| GET | `…/graph/local` | 任务局部图 |
| GET | `…/final-reports` | 终版报告列表 |
| GET | `…/final-reports/{report_id}` | 终版报告 |
| GET | `…/final-reports/{report_id}/markdown` | Markdown 渲染 |
| GET | `…/final-reports/{report_id}/html` | HTML 渲染 |
| GET | `…/final-reports/{report_id}/print` | 打印视图 |
| GET | `…/final-reports/{report_id}/publication` | 发布状态 |
| POST | `…/final-reports/{report_id}/publish` | 发布报告 |

（表中 `…` = `/api/investigation/workbench/{task_id}`。）

**Multi-Image Analysis（multi_analysis.py，12 个，无挂载前缀）**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/llm/cases` | 创建案件 |
| GET | `/api/llm/cases` | 案件列表 |
| GET | `/api/llm/cases/{case_id}` | 案件详情 |
| DELETE | `/api/llm/cases/{case_id}` | 删除案件（回调 C++） |
| POST | `/api/llm/cases/{case_id}/tasks` | 追加任务 |
| POST | `/api/llm/cases/{case_id}/associate-tasks` | 关联已分析任务（复用不重跑） |
| POST | `/api/llm/cases/smart-create` | 智能建案 |
| POST | `/api/llm/cases/{case_id}/tasks/incremental` | 增量追加 |
| GET | `/api/llm/cases/{case_id}/analysis-status` | 聚合分析状态 |
| POST | `/api/llm/cases/{case_id}/incremental-analysis` | 增量分析 |
| POST | `/api/llm/multi-image-analysis` | 跨镜像分析作业 |
| GET | `/api/llm/multi-image-analysis/{job_id}` | 作业状态 |

**Associations / Database / Office / System / Markitdown / OSS / WeChat（共 29 个）**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/associations/cluster-files` | 簇↔文件关联 |
| POST | `/api/associations/file-clusters` | 文件↔簇关联 |
| GET | `/api/db/tasks` | 任务（含库路径） |
| GET | `/api/db/tasks/{task_id}` | 任务详情 |
| GET | `/api/db/tasks/{task_id}/databases` | 产出库列表 |
| GET | `/api/db/tasks/{task_id}/files` | files.db 只读查询 |
| GET | `/api/db/tasks/{task_id}/events` | events.db 只读查询 |
| GET | `/api/db/tasks/{task_id}/export/toon` | TOON 导出 |
| GET | `/api/db/tasks/{task_id}/export/json` | JSON 导出 |
| POST | `/api/office/parse` | Office 解析（C++ 调用） |
| GET | `/api/office/supported-types` | 支持类型 |
| POST | `/api/forensics/oss/ai/filter` | OSS 智能筛选 |
| POST | `/api/forensics/oss/ai/analyze` | OSS 智能分析 |
| GET | `/api/system/logs` | 日志入口 |
| GET | `/api/system/logs/{service}` | 服务日志读取 |
| GET | `/api/system/logs-stream/{service}` | 日志 SSE |
| POST | `/api/markitdown/convert` | 批量转换（task 门控） |
| POST | `/api/markitdown/convert-one` | 单文件转换 |
| POST | `/api/markitdown/batch-convert` | 批量转换（另一形态） |
| GET | `/api/markitdown/status` | 转换器状态 |
| GET | `/api/wechat/chat` | 单聊记录 |
| GET | `/api/wechat/chat/group` | 群聊记录 |
| GET | `/api/wechat/owner` | 账号主人 |
| GET | `/api/wechat/contacts` | 联系人 |
| GET | `/api/wechat/graph` | 微信关系图 |
| GET | `/api/wechat/graph/timeline` | 消息时间线 |
| GET | `/api/wechat/graph/community` | 社区发现 |
| GET | `/api/wechat/graph/person/{username}` | 单人画像 |
| POST | `/api/wechat/graph/invalidate` | 图缓存失效 |

合计：5+17+9+15+1+12+17+35+12+29 = **152**。`routes/system_logs.py` 的端点不在表内（未注册）；`routes/investigation_workbench.py` 的 35 个端点全部以 task_id 为第一路径段，天然任务隔离。

相关阅读：[Main.md](./Main.md)（挂载与 lifespan）、各 `routes/*.md` 子文档。

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
