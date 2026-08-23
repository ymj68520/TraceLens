# Health 路由（python_service/httpserver/routes/health.py，无前缀 + /api/system 杂项）

> **一句话**：回答进程与依赖两个层面的"活着吗 / 能干活吗"——liveness 只看进程，readiness 把 C++ 当硬依赖、Neo4j/LLM/Redis 当可选依赖，是部署探针与排障的第一入口。

## 这组路由承担什么职责

Kubernetes 风格的探针三件套，外加两个"寄居"端点（Redis 状态与系统信息，历史上放在这，实际挂 `/api/system` 前缀）。它体现的部署哲学是：**进程存活与依赖可用分开判断**——Python 服务可以在 Neo4j、LLM、Redis 全挂的情况下仍然"活着但只读降级"，此时重启它毫无意义。

## 典型调用方

- 编排/监控探针：`/health`（拉起判定）、`/health/live`（重启判定）、`/health/ready`（接流判定）。
- 前端 Settings/系统页：`web/src/services/systemService.js` 里 `pythonApi.get('/health')`（:42）与 `pythonApi.get('/api/system/redis/status')`（:47）打到本组；注意同文件的 `api.get('/api/system/info')`（:8）用的是 **C++ 基座**——那是 C++ 侧同名端点，Python 的 `/api/system/info` 当前没有已知前端调用方（可达但闲置）。

## 核心数据结构与端点签名

三个响应模型都在本文件内定义（health.py:21-42）：

```python
# health.py:21-42
class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str
    uptime_seconds: float

class ReadinessResponse(BaseModel):
    ready: bool
    checks: Dict[str, Any]
    timestamp: str

class SystemInfoResponse(BaseModel):
    service: str
    version: str
    python_version: str
    config: Dict[str, Any]
    timestamp: str
```

字段语义：`uptime_seconds` 由模块级 `_start_time = time.time()`（health.py:46，import 时刻起算）在每次请求时差值计算——它是"模块加载至今"而非"进程启动至今"；`ReadinessResponse.checks` 是各依赖的开放式 dict（键为 cpp_backend/neo4j/llm/redis），刻意不建强类型模型，方便加探针不破坏契约。

端点签名（全部 GET，均 200）：

- `GET /health` → `HealthResponse`（health.py:49-67，status 恒 "healthy"）
- `GET /health/live` → `HealthResponse`（:70-89，status 恒 "alive"）
- `GET /health/ready` → `ReadinessResponse`（:92-191，见下节判定逻辑）
- `GET /api/system/redis/status`（:194-230）——Redis 连接细节（connected / in_use / 掩码后的 URL / 可选 error）
- `GET /api/system/info` → `SystemInfoResponse`（:233-266）——版本、Python 版本、配置摘要

## 数据流（读写什么）

`/health/ready` 的检查顺序与降级判定（health.py:106-185），核心结构：

```python
# health.py:106-127（硬依赖段的骨架）
checks = {}
all_ready = True

# Check C++ backend connectivity
try:
    from ..services import get_service_manager
    service_manager = get_service_manager()
    cpp_status = await service_manager.cpp_backend.health_check()
    checks["cpp_backend"] = {
        "status": "connected" if cpp_status else "disconnected",
        "url": settings.cpp_backend_url,
    }
    if not cpp_status:
        all_ready = False
except Exception as e:
    logger.warning(f"Readiness check failed (cpp_backend): {e}", exc_info=True)
    checks["cpp_backend"] = {
        "status": "error",
        # Exception class only: transport errors embed internal URLs/paths.
        "error": type(e).__name__,
    }
    all_ready = False
```

1. **C++ 后端（硬依赖）**：调 `cpp_backend.health_check()`（即 `GET /api/health` 200 判定，cpp_backend.py:136-148）；失败置 `all_ready=False`（:118-119）。**只有它能让 ready=false**——没有 C++，任务查询、文件、导出全不可用。
2. **Neo4j/Graphiti（可选）**：失败只标记 disconnected/unavailable，不影响 ready（:129-144）。
3. **LLM（可选）**：同上（:146-161）。两个可选分支同构：

```python
# health.py:129-161（节选，两个可选依赖的同构分支）
# Check Neo4j connectivity (if graphiti is enabled)
try:
    service_manager = get_service_manager()
    neo4j_status = await service_manager.graphiti_service.health_check()
    checks["neo4j"] = {
        "status": "connected" if neo4j_status else "disconnected",
        "uri": settings.neo4j_uri,
    }
except Exception as e:
    logger.warning(f"Readiness check failed (neo4j): {e}", exc_info=True)
    checks["neo4j"] = {
        "status": "unavailable",
        "error": type(e).__name__,
    }
    # Neo4j is optional, don't fail readiness

# Check LLM service availability
try:
    llm_status = await service_manager.llm_service.health_check()
    checks["llm"] = {
        "status": "available" if llm_status else "unavailable",
        "url": settings.llm_text_base_url,
    }
except Exception as e:
    # ...同构：status=unavailable + type(e).__name__，不影响 all_ready
```

注意两处措辞差异是刻意的信息量：Neo4j 用 connected/disconnected（布尔探测），LLM 用 available/unavailable（探测的是模型端点能否出模型列表）；status=error 仅保留给"探测本身抛异常"。

4. **Redis（可选）**：经 IngestionJobManager 查询；不可用回退内存模式，不影响 ready（:163-185）。URL 经 `mask_url_credentials` 掩码（:175），因为 Redis URL 可能内嵌密码——该函数（config.py:305-321）把 password 段换成 `***`，urlsplit 解析失败时整体返回 `"***"`：

```python
# health.py:163-178（节选）
job_manager = service_manager.ingestion_job_manager
if job_manager is not None:
    redis_status = await job_manager.redis_health_check()
    checks["redis"] = {
        "status": redis_status["status"],
        "connected": redis_status["connected"],
        "in_use": redis_status["in_use"],
        # Masked: the raw redis URL can embed the password.
        "url": mask_url_credentials(settings.redis_url),
    }
else:
    checks["redis"] = {"status": "unavailable", "error": "IngestionJobManager not initialized"}
```

`redis_health_check`（ingestion_job_parts/_manager.py:179-208）区分两个语义：`in_use` 是初始化时是否启用了 Redis（回退内存后恒 False），`connected` 是当下 ping 是否通——`in_use=True, connected=False, status="error"` 是"配了 Redis 但刚才 ping 失败"的典型态。

`/api/system/info` 的 `config` 摘要（health.py:255-264）只暴露 8 个非敏感项：http_port/http_host/cpp_backend_url/neo4j_uri/llm_text_model/llm_vision_model/log_level/platform——密码、API key 均不在其中。

所有异常分支只回 `type(e).__name__`（如 :125-126）——传输层异常消息里带内部 URL/路径，不能进响应体。这一纪律与 main.py 的全局 500 处理器一致。

## 边界与已知状态

- readiness 检查的是**依赖连通性**，不是业务健康：C++ 通了但正在跑大任务，ready 仍是 true。
- Graphiti 的健康检查在服务"initialized-but-disabled"（Neo4j 缺失的降级态）下返回 False，readiness 会如实显示 disconnected，但服务整体照常工作——排障时别急着"修 Neo4j"除非你需要图谱功能。
- `SystemInfoResponse.config` 暴露的是配置摘要而非全量 settings（health.py:255-264），敏感项（密码、API key）不在其中。
- 本模块不含日志端点；`/api/system/logs*` 在 routes/system.py（注意 routes/system_logs.py 是未注册的死代码，详见 [HTTPRoutes.md](../HTTPRoutes.md)）。
- readiness 是**串行**探测四依赖（逐个 await），Neo4j/LLM 探测慢会拖长响应但没有单独超时包裹——靠各服务内部超时（如 Neo4j driver 的 connect/query 5s）兜底；探针超时配得比 5s 紧的话要留意。
- 涉及 env：`CPP_BACKEND_URL`（默认 http://localhost:8080）、`NEO4J_URI`（neo4j://127.0.0.1:7687）、`LLM_TEXT_BASE_URL`/`LLM_VISION_BASE_URL`、`REDIS_URL`（redis://localhost:6379）——分别出现在各 checks 的 url 字段里。

## 如何验证与扩展

- `python_service/tests/unit/test_startup_reliability.py` 覆盖降级启动后的服务状态；CORS/信息脱敏相关见 `test_cors_config.py`、`test_d1_error_sanitization.py`。
- 手工验证矩阵：停 C++ → `ready:false` 且 cpp_backend disconnected；停 Neo4j → `ready:true` 但 neo4j unavailable；停 Redis → `ready:true` 且 redis `in_use:false`。
- 新增可选依赖探针：在 readiness_check 里加 try/except 块，**默认不要**把它算进 `all_ready`——只有新增硬依赖才改语义。

相关阅读：[httpserver/Main.md](../Main.md)（lifespan 与降级启动）、[httpserver/services/ServiceManager.md](../services/ServiceManager.md)（health_check 汇总）。

## 二轮深化 A：端点全表与响应字段级契约

| 端点 | 方法 | 请求参数 | 响应模型 | 状态码 |
|---|---|---|---|---|
| `/health` | GET | 无 | HealthResponse | 恒 200 |
| `/health/live` | GET | 无 | HealthResponse | 恒 200 |
| `/health/ready` | GET | 无 | ReadinessResponse | 恒 200（语义看 `ready` 字段） |
| `/api/system/redis/status` | GET | 无 | 无模型（裸 dict） | 恒 200 |
| `/api/system/info` | GET | 无 | SystemInfoResponse | 200（OpenAPI 声明了 500 但 handler 内无抛点） |

四个响应体的逐字段契约：

**HealthResponse（health.py:21-26）**

| 字段 | 类型 | 取值来源 | 说明 |
|---|---|---|---|
| status | str | 字面量 "healthy"（/health）或 "alive"（/health/live） | 区分两个探针的稳定标记 |
| timestamp | str | `datetime.now().isoformat()` | **本地时间、无时区后缀**——跨时区聚合日志时需注意 |
| version | str | 硬编码 "1.0.0"（:65、:86） | 与 FastAPI(title version) main.py:107、`report_generator_version` 默认值三处各自硬编码，无单一来源 |
| uptime_seconds | float | `time.time() - _start_time`（:46） | 模块 import 时刻起算（含路由注册），早于 uvicorn 监听几毫秒 |

**ReadinessResponse.checks 各键的子字段（契约上 `Dict[str, Any]`，实际形状固定）**

| 键 | 正常形态 | 异常形态 | 对 ready 的影响 |
|---|---|---|---|
| cpp_backend | `{status: connected\|disconnected, url}` | `{status: "error", error: <异常类名>}` | **唯一能置 ready=false 的键**（:118-119、:127） |
| neo4j | `{status: connected\|disconnected, uri}` | `{status: "unavailable", error}` | 不影响（:144 注释明说） |
| llm | `{status: available\|unavailable, url}` | `{status: "unavailable", error}` | 不影响 |
| redis | `{status, connected, in_use, url}` | `{status: "unavailable", error: "IngestionJobManager not initialized"}`（job_manager 为 None）或 `{status: "unavailable", error: <类名>}` | 不影响 |

**`/api/system/redis/status` 裸 dict（health.py:213-230）**

| 字段 | 类型 | 说明 |
|---|---|---|
| connected | bool | 当下 ping 结果 |
| in_use | bool | 初始化时是否真的启用了 Redis（内存回退后恒 False） |
| status | str | job_manager 内部状态字 |
| error | str \| None | **该端点独有**——正常路径也带这个键（值 None）；readiness 内嵌的 redis 检查正常路径**没有** error 键，两处形状不完全一致 |
| url | str | mask_url_credentials 处理后的 REDIS_URL |
| timestamp | str | 同上 isoformat |

**SystemInfoResponse.config 固定 8 键**（:255-264）：http_port、http_host、cpp_backend_url、neo4j_uri、llm_text_model、llm_vision_model、log_level、platform——枚举封闭，加配置项要改代码。

## 二轮深化 B：readiness 判定真值表

四个依赖 × 三种观测态对 `ready` 的影响（源码推导）：

| C++ | Neo4j | LLM | Redis | ready | 典型场景 |
|---|---|---|---|---|---|
| connected | connected | available | in_use | true | 全依赖就绪 |
| connected | disconnected | unavailable | 未配置 | true | 只用基础分析（无图谱/LLM/Redis） |
| connected | unavailable(error) | unavailable(error) | unavailable(error) | **true** | 三个可选依赖全抛异常——探针自身问题不影响接流 |
| disconnected | 任意 | 任意 | 任意 | **false** | C++ 宕机或网络分区 |
| error(异常) | 任意 | 任意 | 任意 | **false** | cpp_backend 属性访问抛异常（如 shutting_down 态） |

注意最后一行：readiness 里 `service_manager.cpp_backend` 是属性访问（:113），在 ServiceManager 处于 initializing/shutting_down/stopped 态时抛 RuntimeError → except 分支 → ready=false。也就是说**关机窗口期的 readiness 会短暂变 false**，编排器据此摘流量正是预期行为。

## 二轮深化 C：新走读——redis_status 的双形态分支

```python
# health.py:209-230（节选）
service_manager = get_service_manager()
job_manager = service_manager.ingestion_job_manager
if job_manager is None:
    return {
        "connected": False,
        "in_use": False,
        "status": "unavailable",
        "url": mask_url_credentials(settings.redis_url),
        "timestamp": datetime.now().isoformat(),
    }

health = await job_manager.redis_health_check()
return {
    "connected": health["connected"],
    "in_use": health["in_use"],
    "status": health["status"],
    "error": health.get("error"),
    ...
}
```

逐块解释：`ingestion_job_manager` 是 ServiceManager 里**唯一不惰性重建**的管理器属性（service_manager.py:663-667）——启动期 Redis 初始化失败时它是 None，于是走第一分支返回 `in_use:false` 的固定形态（没有 error 键）；非 None 时转发 `redis_health_check()` 的完整结果，**恒有 error 键**（值可为 None）。前端 Dashboard 的 Redis 状态卡（systemService.getRedisStatus）区分"未启用"与"启用但断连"就靠这两个形态：前者 `in_use=false`，后者 `in_use=true, connected=false`。与 readiness 内嵌检查（上一节）的第三点差异：readiness 版本在异常时返回 `{"status": "unavailable", "error": <类名>}`（:180-184），本端点没有外层 try/except——`redis_health_check()` 若抛异常会直接冒泡成全局 500（固定文案），而它内部实现（ingestion_job_parts/_manager.py:179-208）自己 catch 了网络错误，实际很难触达。

## 二轮深化 D：调用方关联矩阵

| 调用方 | 端点 | 用途 |
|---|---|---|
| web/src/services/systemService.js:42（getPythonHealth） | GET /health | Dashboard Python 服务卡片 |
| web/src/services/systemService.js:47（getRedisStatus） | GET /api/system/redis/status | Dashboard Redis 卡片 |
| 编排器/run.sh 健康等待 | GET /health/ready（探针推荐）或 /health | 拉起判定 |
| （无前端调用方） | GET /health/live、/api/system/info | 可达但闲置（systemService 的 /api/system/info 走 C++ 基座同名端点） |
| ServiceManager.health_check | （间接） | 三依赖汇总的另一条平行路径，见 ServiceManager.md 第 13 节——两者判定口径不同（health_check 会把 C++ 异常降 overall=degraded，readiness 置 ready=false，语义等价但字段不同） |

## 二轮深化 E：配置影响表

| env | 默认 | 出现位置 |
|---|---|---|
| CPP_BACKEND_URL | http://localhost:8080 | checks.cpp_backend.url（:116）、/api/system/info（:258） |
| NEO4J_URI | neo4j://127.0.0.1:7687 | checks.neo4j.uri（:136）、info（:259） |
| LLM_TEXT_BASE_URL | http://192.168.31.170:1234 | checks.llm.url（:153） |
| REDIS_URL | redis://localhost:6379 | 两处 Redis 端点的 url（掩码后，:175、:218、:228） |
| PYTHON_HTTP_PORT / PYTHON_HTTP_HOST | 8090 / 0.0.0.0 | info（:256-257） |
| LLM_TEXT_MODEL / LLM_VISION_MODEL | openai/gpt-oss-20b / qwen/qwen3-vl-4b | info（:260-261） |
| LOG_LEVEL | INFO | info 回显（:262）——**仅回显**，不驱动日志级别（见 Main.md 第 14 节） |

## 二轮深化 F：readiness 最坏延迟预算（串行无总超时，新走读）

`/health/ready` 没有整体超时包裹，四项检查**串行**执行，每项的内部上限各不相同（源码核对）：

| 检查 | 实现链 | 单项最坏耗时 | 依据 |
|---|---|---|---|
| cpp_backend | `client.get("/api/health")`（cpp_backend.py:144） | **30s** | 复用池化客户端的默认 `httpx.Timeout(30.0)`（cpp_backend.py:56） |
| neo4j | `_check_neo4j_connection`（graphiti_parts/_core.py:157） | ≈5s | Neo4j 驱动 connect/query 超时（Settings 默认 5s） |
| llm | `model_manager.health_check` → 先 text 后 vision 各一次 `GET /v1/models`（model_manager.py:79-94、:104-111） | **240s** | 持久客户端超时 = `llm_timeout_seconds`（默认 120s，llm_service.py:65-67、:71-73），两次串行 |
| redis | `redis_health_check` ping | ≈数秒 | 连接池超时（connect 5s） |

最坏合计约 **4.7 分钟**——注意这是"依赖挂起（accept 后不响应）"而不是"连接拒绝"的形态；连接拒绝通常毫秒级返回。两个工程结论：编排探针的超时务必小于依赖挂起场景（否则探针先死）；`llm_timeout_seconds` 同时承担"推理超时"与"探活超时"两个角色是已知的耦合点——想缩短 readiness 延迟不能直接调小它，会误伤长推理。`check_model_status` 在无持久客户端时走的临时客户端反而只有 10s 超时（model_manager.py:113-115）——两条路径超时预算不同。

## 二轮深化 G：手工验证矩阵（curl）

```bash
# 全绿基线
curl -s localhost:8090/health/ready | python3 -m json.tool
# 停 C++：ready:false，checks.cpp_backend.status=disconnected
# 停 Neo4j：ready:true，checks.neo4j.status=disconnected（Graphiti 降级态）
# 停 LLM：ready:true，checks.llm.status=unavailable
# 停 Redis：ready:true，checks.redis.in_use=false（内存回退）
# 关机窗口（向进程发 SIGTERM 后立刻探测）：ready:false，cpp_backend.status=error=RuntimeError
curl -s localhost:8090/api/system/redis/status   # 对比 in_use/connected 两维
curl -s localhost:8090/api/system/info           # 8 键配置摘要
```

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
