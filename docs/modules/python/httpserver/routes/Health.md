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

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
