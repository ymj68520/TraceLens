# httpserver 服务入口（python_service/httpserver/main.py、config.py）

> **一句话**：构建 FastAPI 应用、挂载全部中间件与路由，并在 lifespan 中驱动 ServiceManager 完成"分层超时、可降级"的服务启动——它是 Python 侧唯一的进程入口。

## 1. 为什么有这个模块

TraceLens 是双服务架构：C++ 服务（:8080）负责磁盘镜像解析、任务管理和 SQLite 产出；Python 服务负责 C++ 不擅长的部分——LLM 分析、Graphiti 知识图谱、报告生成。这个模块回答的问题是：**Python 进程如何以一个可预测的方式启动起来，并且在依赖（C++、Neo4j、LLM、Redis）部分不可用时仍然活着**。它自己不实现任何业务逻辑，而是把"应用装配"集中在一处，让路由和服务可以各自独立演进。

## 2. 在系统中的位置

- **谁启动它**：开发/部署环境以 `python -m httpserver.main`（工作目录为 `python_service/`）启动；`__main__` 直落 `run_server()`（main.py:291-292），由 uvicorn 监听 `PYTHON_HTTP_HOST:PYTHON_HTTP_PORT`（默认 0.0.0.0:8090，config.py:133-134）。
- **谁调用它**：前端（web/src 中经由各 service 模块）直连 :8090 的 REST API；C++ 的 `LLMPythonProxy`（src/network/HTTPServer/LLMPythonProxy.cpp:63,104,138）在取证流水线结束后反向调用 `/api/graphiti/ingest*` 触发图谱摄取。
- **它调用谁**：通过 ServiceManager 间接持有 CppBackendService（HTTP → C++ :8080）、GraphitiService（Neo4j + graphiti-core）、LLMService（OpenAI 兼容推理端点）、IngestionJobManager（可选 Redis）。
- 前端的三个 axios 客户端在 `web/src/services/api.js` 定义：`pythonApi`（baseURL `http://<host>:8090`，timeout 60s——LLM 请求慢，api.js:38-44）、`api`（C++ 同源相对路径，timeout 30s）、`csApi`（:8091 分布式服务）。baseURL 由浏览器当前 host 动态拼接（api.js:12-17），跨机访问时 localhost 不会误指向客户端自身。

## 3. 核心概念与设计

**（a）create_app() 是唯一的装配点。** `create_app()`（main.py:74）创建 FastAPI 实例（文档开在 `/docs`、`/redoc`，main.py:108-110），然后按固定顺序叠加四层横切关注点：

1. **CORS**（main.py:114-125）：来源来自 `PYTHON_CORS_ORIGINS`（JSON 数组，config.py:236-271）。注意一个容易被忽略的规范细节：当来源是通配 `["*"]` 时必须关闭 `allow_credentials`——CORS 规范禁止通配来源与凭据共存，浏览器会直接拒绝。
2. **请求日志中间件**（main.py:128-153）：每个请求记录方法、路径、状态码、耗时与客户端 IP。
3. **全局 500 处理器**（main.py:156-171）：未捕获异常的完整 traceback 只进服务端日志；响应体是固定文案 `"An unexpected error occurred"`。这是刻意为之——异常消息可能携带文件系统路径和内部端点细节，即使在 DEBUG 下也不外泄（见 main.py:159-161 的注释）。
4. **422 处理器**（main.py:174-188）：Pydantic 校验失败时把请求体和错误明细写入日志，响应则返回结构化的 errors 列表。

CORS 段的真实实现值得逐行看（通配判断就一行，但它守的是浏览器硬性行为）：

```python
# main.py:114-125
# Configure CORS. Origins come from PYTHON_CORS_ORIGINS (default ["*"]).
# A wildcard origin cannot be combined with credentials per the CORS spec
# (browsers reject it), so only enable credentials when origins are explicit.
_cors_origins = settings.cors_origins
_allow_credentials = _cors_origins != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

`settings.cors_origins` 是 property（config.py:243-246），背后 `_parse_cors_origins`（config.py:248-271）先按 JSON 数组解析，失败则退回逗号分隔；裸 `"*"` 归一成 `["*"]`。也就是说：只要运维配了显式来源列表，凭据（cookie/Authorization）才可用；否则浏览器端 fetch 携带凭据会被规范层拒绝。

**（b）lifespan 驱动服务生命周期。** FastAPI 的 lifespan（main.py:42-71）在启动时调用 `ServiceManager.initialize()`（main.py:55），随后 `init_dependencies()`（dependencies.py:15）把管理器交给依赖注入层；关闭时对称地调用 `shutdown()`。关键点：**启动失败不会让进程退出**——异常只被 warning（main.py:59-60），服务以降级模式继续跑。真正的超时/回滚控制在 ServiceManager 内部（见 [httpserver/services/ServiceManager.md](./services/ServiceManager.md)）。

```python
# main.py:50-71（节选）
try:
    # Import services here to avoid circular imports
    from .services import get_service_manager
    service_manager = get_service_manager()
    await service_manager.initialize()
    # Initialize dependency injection system
    from .dependencies import init_dependencies
    init_dependencies(service_manager)
except Exception as e:
    logger.warning(f"Some services failed to initialize: {e}")

yield

# Shutdown: Cleanup services
logger.info("Shutting down Python HTTP Service")
try:
    from .services import get_service_manager
    service_manager = get_service_manager()
    await service_manager.shutdown()
except Exception as e:
    logger.warning(f"Error during shutdown: {e}")
```

两个工程细节：服务模块**在函数体内导入**而不是模块顶部——启动前先完成 app 装配，避免"服务模块导入失败导致整个进程起不来"；yield 前后的 try/except 都只 warning 不 re-raise，与第 6 节"尽量活着"的部署哲学一致。注意 `initialize()` 内部 30s 超时后仍会抛出——但被这里的 `except Exception` 捕获后进程照常进入 yield（开始服务请求）。

**（c）分层超时预算是配置的核心。** config.py:150-156 定义了一组刻意分离的时间预算：

| env | 字段 | 默认 | 消费者 |
|---|---|---|---|
| `CPP_STARTUP_REQUEST_TIMEOUT` | cpp_startup_request_timeout | 5.0s | 启动/恢复期对 C++ 的单次请求超时 |
| `CPP_RECOVERY_TIMEOUT` | cpp_recovery_timeout | 8.0s | 重启恢复（resume_unfinished 等）总预算 |
| `NEO4J_CONNECT_TIMEOUT` / `NEO4J_QUERY_TIMEOUT` | neo4j_connect/query_timeout | 5.0s | Graphiti/Migration/Ingestion 的 Neo4j 驱动参数 |
| `OPTIONAL_SERVICE_INIT_TIMEOUT` | optional_service_init_timeout | 12.0s | 每个可选服务初始化的 `wait_for` 上限 |
| `PYTHON_STARTUP_TIMEOUT` | startup_timeout | 30.0s | `_run_initialization` 的 `asyncio.timeout` 总预算 |

它们与推理超时（`LLM_TIMEOUT_SECONDS=120`，config.py:182）互不侵扰——"启动要快、分析可以慢"。对应源码：

```python
# config.py:150-156
# Startup/recovery budgets are intentionally separate from inference timeout.
cpp_startup_request_timeout: float = Field(default=5.0, alias="CPP_STARTUP_REQUEST_TIMEOUT")
cpp_recovery_timeout: float = Field(default=8.0, alias="CPP_RECOVERY_TIMEOUT")
neo4j_connect_timeout: float = Field(default=5.0, alias="NEO4J_CONNECT_TIMEOUT")
neo4j_query_timeout: float = Field(default=5.0, alias="NEO4J_QUERY_TIMEOUT")
optional_service_init_timeout: float = Field(default=12.0, alias="OPTIONAL_SERVICE_INIT_TIMEOUT")
startup_timeout: float = Field(default=30.0, alias="PYTHON_STARTUP_TIMEOUT")
```

**（d）.env 的发现与项目根解析。** `find_env_file()`（config.py:18-26）从 cwd 向上找 `.env`；`get_project_root()`（config.py:29-38）优先信 `.env` 里的 `PROJECT_ROOT`，否则用 `config.py → httpserver → python_service` 的相对位置自动推断。这决定了报告输出目录等相对路径最终落在哪里。`get_settings()` 带 `@lru_cache`（config.py:324-327），Settings 实例进程内唯一；`Settings.model_config` 用 `extra="ignore"`（config.py:125-130），未知 env 变量不会让启动失败。

其余常被消费的 env（默认值见 config.py）：`CPP_BACKEND_URL=http://localhost:8080`（:141）、`LLM_TEXT_MODEL=openai/gpt-oss-20b` / `LLM_VISION_MODEL=qwen/qwen3-vl-4b`（:173,178）、`FORENSIC_REPORT_DIR=build/data/reports`（:214-216）、`REDIS_URL=redis://localhost:6379`（:187）、`NEO4J_URI=neo4j://127.0.0.1:7687`（:196）。

## 4. 工作流程走读：一次冷启动

进程入口 `run_server()` → `get_app()` → `create_app()`。中间件与异常处理器注册完毕后，`_register_routes(app)`（main.py:197-246）把约 20 个路由模块挂到各自前缀下：

```python
# main.py:199-210（节选）
from .routes import health, graphiti, llm, database, office, case_analysis, system, \
    associations, oss_analysis, multi_analysis, dll, markitdown, wechat_graph, \
    forensic_reports, investigation, investigation_workbench, report_evidence, \
    report_generation, report_narrative

# Health routes (no prefix)
app.include_router(health.router, tags=["Health"])

# API routes
app.include_router(graphiti.router, prefix="/api/graphiti", tags=["Graphiti"])
app.include_router(llm.router, prefix="/api/llm", tags=["LLM"])
app.include_router(case_analysis.router, prefix="/api/llm", tags=["Case Analysis"])
app.include_router(
    forensic_reports.router,
    prefix="/api/reports",
    tags=["Forensic Reports"],
)
# ...
```

完整挂载表（main.py:202-246）：health 无前缀（:202）、`/api/graphiti`（:205）、`/api/llm`（:206，注意 case_analysis 模块也挂在 `/api/llm` 下，:207，dll 模块再次同前缀，:244）、四个报告路由共用 `/api/reports`（:208-227）、`/api/investigation/workbench` 先于 `/api/investigation` 注册（:228-237，长前缀在前避免路径遮蔽歧义）、multi_analysis 无前缀自带 `/api/llm/*` 全路径（:238）、`/api/associations`（:239）、`/api/db`（:240）、`/api/office`（:241）、oss_analysis 无前缀自带 `/api/forensics/oss/ai`（:242）、`/api/system`（:243）、`/api/markitdown`（:245）、`/api/wechat`（:246）。

uvicorn 开始监听后触发 lifespan：ServiceManager 按依赖顺序初始化各服务（C++ 硬依赖 → 报告 → Graphiti 12s 上限 → LLM → 三个执行器 → 任务/迁移管理器），任何一个失败都被吞掉并降级。此时 `GET /health` 立即返回 healthy（进程活着），但 `GET /health/ready` 会依据 C++ 连通性给出真实就绪状态（见 [routes/Health.md](./routes/Health.md)）。

一个值得知道的坑：`routes/system_logs.py` 的 router **没有**在 `_register_routes` 里注册（main.py:199 的导入列表中没有它）——它是死代码；实际生效的日志端点来自 `routes/system.py`。

## 5. 对外/对内接口清单

| 函数 | 签名 | 语义 |
|---|---|---|
| `create_app` | `(settings: Optional[Settings] = None) -> FastAPI`（main.py:74） | 唯一装配点；构建 app 并注册中间件/处理器/路由；同时写入模块级 `_app` |
| `get_app` | `() -> FastAPI`（main.py:249） | 返回全局实例，未创建则惰性 `create_app()`；`run_server` 经它拿 app 避免模块导入问题 |
| `run_server` | `(host=None, port=None, reload=False, workers=1)`（main.py:257） | 参数缺省回落 `settings.python_http_host/port`，最终 `uvicorn.run(app, ...)` |
| `lifespan` | `@asynccontextmanager`（main.py:42） | 启动期 initialize + DI，关闭期 shutdown；两侧异常都只 warning |
| `find_env_file` | `() -> Optional[Path]`（config.py:18） | cwd 逐级向上找 `.env`，找不到返回 None |
| `get_project_root` | `@lru_cache () -> Path`（config.py:30） | PROJECT_ROOT 优先，否则 `Path(__file__).parents[2]` |
| `mask_url_credentials` | `(url: str) -> str`（config.py:305） | 把 URL 中 password 换成 `***`；解析失败整体返回 `"***"`。被 `/health/ready` 与 `/api/system/redis/status` 用于 Redis URL 脱敏 |

## 6. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| `services/service_manager.py` | lifespan 的启动/关闭全部委托给它；本模块不感知具体服务 |
| `dependencies.py` | `init_dependencies()` 之后，路由通过 `get_service_manager()` 拿到同一实例（dependencies.py:23-27） |
| `routes/*` | 只在 `_register_routes` 处耦合（导入 + 前缀），新增路由只需在此加一行 |
| `config.py` | 所有环境变量的唯一出口；路由与服务统一 `Depends(get_settings)` 读取 |
| 前端 `web/src/services/api.js` | `pythonApi` 的 baseURL/timeout（60s）是 :8090 契约的客户端侧约定 |

## 7. 注意事项与已知问题

- **启动失败 ≠ 进程失败**：设计意图是"尽量活着"。排查时看启动日志中的 warning 行，而不是期待容器重启。
- 全局 500/`/health/ready` 等响应刻意不携带异常文本（只给 `type(e).__name__`），定位问题必须看服务端日志。
- `routes/system_logs.py` 未注册（死代码），日志功能在 `routes/system.py`；不要往前者里加端点。
- C++ 端的 `LLMPythonProxy` 会主动调 Python，因此 Python 服务晚于 C++ 启动不会丢数据，但摄取请求会失败重试。
- `run_server(reload=True/workers>1)` 直接传 app 对象给 uvicorn（main.py:282-288），reload/workers 参数在该调用形态下实际不生效（uvicorn 需要 import string 才支持多 worker/reload）——生产多 worker 需要改为 `uvicorn httpserver.main:get_app` 工厂式启动。

## 8. 如何验证与扩展

- 启动行为：`python_service/tests/unit/test_startup_reliability.py`（分层超时与降级路径）。
- CORS 通配/凭据规则：`tests/unit/test_cors_config.py`。
- 错误脱敏（500 固定文案、422 结构）：`tests/unit/test_d1_error_sanitization.py`。
- 手工验证：`python -m httpserver.main` 后访问 `http://localhost:8090/docs`（Swagger）与 `http://localhost:8090/health/ready`。
- 新增一组路由：在 `routes/` 建模块 → 在 `_register_routes`（main.py:197）加 `include_router` → 端点契约同步到 `docs/api_reference/Python_REST_API.md`。

相关阅读：[HTTPRoutes.md](./HTTPRoutes.md)（路由总览）、[httpserver/services/ServiceManager.md](./services/ServiceManager.md)（启动编排细节）。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
