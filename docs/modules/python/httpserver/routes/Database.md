# Database 路由（python_service/httpserver/routes/database.py，前缀 /api/db）

> **一句话**：把 C++ 产出的取证 SQLite 数据（任务、文件、时间线事件）以只读、分页、可导出的形式暴露给前端，是前端浏览取证结果的查询窗口。

## 这组路由承担什么职责

C++ 分析磁盘镜像后会生成任务元数据和 `<image>_files.db` / `<image>_events.db` 等数据库。这组路由**不直接打开这些库**（除导出外），而是把查询转发给 CppBackendService，再把 C++ 的原始响应整形为统一的 `{success, ..., total_count, page, page_size, timestamp}` 分页结构。职责边界：参数校验与响应建模在这里，数据获取与（客户端侧）过滤/分页补齐在 CppBackendService。

## 典型调用方

前端任务/文件/时间线相关页面（web/src 中调用 `/api/db/tasks*` 的 forensicsService 等）。这组是纯前端面向的只读接口，C++ 不会调用它。

## 端点分组语义

完整契约见 docs/api_reference/Python_REST_API.md，此处讲分组：

- **任务**：`GET /api/db/tasks`（列表，database.py:97）、`GET /api/db/tasks/{task_id}`（详情，:138，404 语义由"C++ 找不到该任务"触发）。
- **任务数据库**：`GET /api/db/tasks/{task_id}/databases`（:170）——列出该任务产出的所有 db 文件，是前端决定还能查什么的前置接口。
- **文件**：`GET /api/db/tasks/{task_id}/files`（:202）——支持 file_type / extension / deleted_only / include_llm 过滤；注意 `include_llm=False` 时 llm_description 置 None（:244），用于在未跑 LLM 分析时减小负载。
- **事件**：`GET /api/db/tasks/{task_id}/events`（:270）——event_type 与时间范围过滤。
- **导出**：`GET .../export/toon`（:328，StreamingResponse，`application/x-toon`，文件名 `{task_id}_export.toon`，:349-355）与 `GET .../export/json`（:368）。

## 数据流（读写什么）

纯**读路径**：路由 → `service_manager.cpp_backend` → C++ REST。两个关键事实：

1. **分页是"补齐"出来的**。C++ 的 largest-files 端点不支持页码，CppBackendService 用 `limit = page_size + offset` 拉全量后客户端切片（cpp_backend.py:253-278）；file_type/extension/deleted_only 同样是客户端过滤（:267-275）。代价：深翻页会把前面所有页的数据都传一遍。database.py 只是如实地把这套补齐结果包装返回。
2. **响应模型是收敛层**。FileRecord/EventRecord（database.py:26-68）把 C++ 字段缺省补齐（`f.get(...)` 全带默认值），前端因此不必处理 C++ 端的字段演化。

## 边界与已知状态

- 全组只读：没有任何 POST/PUT/DELETE；写路径（LLM 分析回写、相关性开关）在 `/api/llm`。
- 错误统一转 5xx + 简短 detail（如 "file records are unavailable"，database.py:259），内部异常文本不外泄。
- `database_type` 查询参数（export/json，:370）目前只对 events 导出生效（CppBackendService.export_json 固定调 events 端点，cpp_backend.py:441）；其他库型的导出需要新的 C++ 端点。
- 深分页性能受客户端分页策略制约（见上）；大任务翻到很后面的页会明显变慢。

## 如何验证与扩展

- 模型契约：`python_service/tests/unit/test_database_models.py`。
- 客户端过滤/分页补齐行为：CppBackendService 的相关单测（见 [httpserver/services/CppBackendClient.md](../services/CppBackendClient.md) 第 7 节）。
- 手工验证：`curl 'http://localhost:8090/api/db/tasks'` → 取 task_id → `curl '.../tasks/{id}/files?page=1&page_size=10'`。
- 扩展方向：若要真服务端分页，需要在 C++ 增加带 offset 的端点，然后把 `get_task_files_paginated` 换成直传——路由层几乎不用动，这正是"补齐逻辑藏在服务层"的好处。

相关阅读：[HTTPRoutes.md](../HTTPRoutes.md)、[httpserver/services/CppBackendClient.md](../services/CppBackendClient.md)。

**最后更新**: 2026-08-23（解释式重写）
