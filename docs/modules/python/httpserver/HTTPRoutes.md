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

相关阅读：[Main.md](./Main.md)（挂载与 lifespan）、各 `routes/*.md` 子文档。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
