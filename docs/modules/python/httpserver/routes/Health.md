# Health 路由（python_service/httpserver/routes/health.py，无前缀 + /api/system 杂项）

> **一句话**：回答进程与依赖两个层面的"活着吗 / 能干活吗"——liveness 只看进程，readiness 把 C++ 当硬依赖、Neo4j/LLM/Redis 当可选依赖，是部署探针与排障的第一入口。

## 这组路由承担什么职责

Kubernetes 风格的探针三件套，外加两个"寄居"端点（Redis 状态与系统信息，历史上放在这，实际挂 `/api/system` 前缀）。它体现的部署哲学是：**进程存活与依赖可用分开判断**——Python 服务可以在 Neo4j、LLM、Redis 全挂的情况下仍然"活着但只读降级"，此时重启它毫无意义。

## 典型调用方

- 编排/监控探针：`/health`（拉起判定）、`/health/live`（重启判定）、`/health/ready`（接流判定）。
- 前端 Settings/系统页（web/src/services/systemService.js 调 `/api/system/info`、`/api/system/redis/status`）。

## 端点分组语义

- `GET /health`（health.py:49）：恒返回 healthy + uptime。只证明事件循环在跑。
- `GET /health/live`（:70）：同上，语义上给重启探针用。
- `GET /health/ready`（:92）：真正的就绪判定，见下节。
- `GET /api/system/redis/status`（:194）：Redis 连接细节（connected / in_use / 掩码后的 URL）。
- `GET /api/system/info`（:233）：版本、Python 版本、关键配置摘要（端口、C++ URL、Neo4j URI、模型名）。

## 数据流（读写什么）

`/health/ready` 的检查顺序与降级判定（health.py:106-185）：

1. **C++ 后端（硬依赖）**：调 `cpp_backend.health_check()`；失败置 `all_ready=False`（:118-119）。**只有它能让 ready=false**——没有 C++，任务查询、文件、导出全不可用。
2. **Neo4j/Graphiti（可选）**：失败只标记 disconnected/unavailable，不影响 ready（:129-144）。
3. **LLM（可选）**：同上（:146-161）。
4. **Redis（可选）**：经 IngestionJobManager 查询；不可用回退内存模式，不影响 ready（:163-185）。URL 经 `mask_url_credentials` 掩码（:175），因为 Redis URL 可能内嵌密码。

所有异常分支只回 `type(e).__name__`（如 :125-126）——传输层异常消息里带内部 URL/路径，不能进响应体。这一纪律与 main.py 的全局 500 处理器一致。

## 边界与已知状态

- readiness 检查的是**依赖连通性**，不是业务健康：C++ 通了但正在跑大任务，ready 仍是 true。
- Graphiti 的健康检查在服务"initialized-but-disabled"（Neo4j 缺失的降级态）下返回 False，readiness 会如实显示 disconnected，但服务整体照常工作——排障时别急着"修 Neo4j"除非你需要图谱功能。
- `SystemInfoResponse.config` 暴露的是配置摘要而非全量 settings（health.py:255-264），敏感项（密码、API key）不在其中。
- 本模块不含日志端点；`/api/system/logs*` 在 routes/system.py（注意 routes/system_logs.py 是未注册的死代码，详见 [HTTPRoutes.md](../HTTPRoutes.md)）。

## 如何验证与扩展

- `python_service/tests/unit/test_startup_reliability.py` 覆盖降级启动后的服务状态；CORS/信息脱敏相关见 `test_cors_config.py`、`test_d1_error_sanitization.py`。
- 手工验证矩阵：停 C++ → `ready:false` 且 cpp_backend disconnected；停 Neo4j → `ready:true` 但 neo4j unavailable；停 Redis → `ready:true` 且 redis `in_use:false`。
- 新增可选依赖探针：在 readiness_check 里加 try/except 块，**默认不要**把它算进 `all_ready`——只有新增硬依赖才改语义。

相关阅读：[httpserver/Main.md](../Main.md)（lifespan 与降级启动）、[httpserver/services/ServiceManager.md](../services/ServiceManager.md)（health_check 汇总）。

**最后更新**: 2026-08-23（解释式重写）
