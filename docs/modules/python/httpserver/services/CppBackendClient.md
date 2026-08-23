# CppBackendClient / CppBackendService（python_service/httpserver/services/cpp_backend.py）

> **一句话**：通往 C++ 取证后端（:8080）的唯一异步 HTTP 通道——带重试、错误页检测和"客户端侧补齐"（过滤/分页/包装解包），把 C++ 端点的不一致挡在服务层之内。

## 1. 为什么有这个模块

C++ 后端是任务与取证数据的权威来源（任务列表、文件记录、时间线、TOON 导出、文件抽取）。Python 侧几乎所有功能都要向它要数据，但 C++ 的 REST 表面有几处"毛边"：错误时可能返回 HTML 错误页而非 JSON；文件列表端点不支持服务端过滤/分页；响应有时是裸 list 有时是包装 dict。如果每个调用方都自己处理这些，会到处重复且行为不一。CppBackendService 把这些一致性处理收敛到一个带连接池的 httpx 客户端后面。

## 2. 在系统中的位置

- **谁调用它**：ServiceManager 启动时初始化（service_manager.py:124-130）；routes/database.py、routes/llm_endpoints、graphiti_endpoints（任务存在性检查）、forensic_report/investigation 各服务（任务元数据、数据库路径解析）都经 `service_manager.cpp_backend` 使用。
- **它调用谁**：仅 C++ HTTP 服务（`CPP_BACKEND_URL`，默认 http://localhost:8080，config.py:141）。

## 3. 核心概念与设计

**（a）统一请求内核 `_request()`（cpp_backend.py:79-134）。** 所有 JSON 端点共用它，四条规则：

1. **重试**：默认 3 次、间隔 1s（:96、:133）；启动/恢复路径可传更短的 timeout/retry_delay（见 `list_tasks` 的 0.25s，:171）。
2. **HTML 检测**：C++ 出错时可能吐 HTML 错误页，Content-Type 含 `text/html` 就直接返回 `{"success": False, "error": "Backend returned HTML"}`（:100-109），避免下游对着 HTML 做 `.get()` 崩掉。
3. **HTTP >= 400**：记录响应文本到日志，返回失败 dict（:110-118）。
4. **传输异常**：重试耗尽后只返回异常**类名**（:124-131）——连接错误的消息里带内部 URL，不能外泄。

**（b）连接池与超时。** `initialize()`（:49-60）建带池的客户端（keepalive 10 / 上限 20，30s 超时）；`client` 属性兜底懒建（:69-77）。

**（c）客户端侧补齐。** C++ 的 `/api/forensics/files/largest` 不支持过滤分页，于是：`get_task_files` 在客户端按 category 过滤（:233-235）；`get_task_files_paginated` 用 `limit = page_size + offset` 拉取后切片，同时兼容裸 list / `{"largest_files": [...]}` / `{"files": [...]}` 三种包装（:258-283）。这是刻意的技术债——真服务端分页需要新 C++ 端点（:250-252 注释明说）。

**（d）TOON 流解析。** `get_files_toon_stream`（:387-427）拿 TOON 文本后按行拆分：`TOON.schema:` 行抽成 schema，其余进 data_lines——供分批送 LLM 而不撑爆上下文（:393-398 docstring）。

## 4. 工作流程走读：一次文件列表请求

前端 `GET /api/db/tasks/{id}/files?page=2&page_size=50` → database 路由调 `get_task_files_paginated(task_id, page=2, page_size=50)`（:238）→ 计算 offset=50，请求 C++ `/api/forensics/files/largest?task_id=...&limit=100`（:254-258）→ 解包响应（list 或包装 dict，:259-265）→ 客户端过滤 file_type/extension/deleted_only（:267-275）→ 切片 `[50:100]` 并返回 `{files, total_count}`（:277-283）。

另一个值得走读的路径是 `get_task`（:174-201）：task_id 先 `quote` 防 path 注入（:182-184，且 `.`/`..` 直接拒收），再**校验响应身份**——C++ 返回的 `id` 必须与请求一致才算命中（:197），最后补齐历史字段别名 `image_name ← image_path`（:199-200）。这两处防御解释了为什么上层敢直接信任 task 元数据。

## 5. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| ServiceManager | 生命周期拥有者；`_cpp_backend_ready` 是上层服务的硬门槛 |
| routes/database.py | 任务/文件/事件/导出的数据通道 |
| routes/llm_endpoints、graphiti_endpoints | 任务存在性检查（404 语义来源） |
| forensic_report / investigation 服务 | 任务元数据与 `output_files_db`/`output_events_db` 路径来源 |
| llm/file_analyzer | 间接：经 task_info 拿 extraction_directory 解析证据路径 |

C++ 端点使用清单（全部经由本类）：`GET /api/health`、`/api/tasks/list`、`/api/tasks/{id}`、`/api/tasks/{id}/databases`、`/api/forensics/files/largest`、`/api/forensics/timeline/comprehensive`、`POST /api/forensics/extract`、`GET /api/forensics/extract/status`、`GET /api/forensics/export/toon`、`GET /api/forensics/export/events/json`。

## 6. 注意事项与已知问题

- 深分页放大传输（见 3c）；大任务的第 N 页会拉 N×page_size 条。
- `export_toon`/`export_json` 不走 `_request` 的重试/HTML 检测（直接 `self.client.get`，:373-385、:429-442），C++ 抖动时这两个方法最脆弱。
- 失败一律以 `{"success": False, "error": ...}` dict 返回而非抛异常——调用方**必须**检查 success，漏检会把错误 dict 当数据用。
- `_request` 会 log payload 与响应前 200 字符（:91、:122），排查方便，但注意别把带敏感内容的请求开到 DEBUG 以上的日志采集里。

## 7. 如何验证与扩展

- 相关单测：`python_service/tests/unit/test_database_models.py`（经由 database 路由的契约）、`test_d2b_task_store.py`（任务元数据信任链）；C++ 侧契约见 docs/api_reference/CPP_REST_API.md。
- 手工验证：停掉 C++ 后调 `/health/ready`（应 `ready:false`），或直接观察 `_request` 的 HTML 检测日志。
- 新增 C++ 端点封装：优先走 `_request()`（自动获得重试/HTML/错误处理）；需要流式或纯文本（如 TOON）时才直连 client，并自行处理状态码。

相关阅读：[httpserver/services/ServiceManager.md](./ServiceManager.md)、[httpserver/routes/Database.md](../routes/Database.md)。

**最后更新**: 2026-08-23（解释式重写）
