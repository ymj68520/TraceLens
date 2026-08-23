# CaseRoutes（src/network/HTTPServer/routes/CaseCRUDRoutes.cpp，后端 CaseManager）

> **职责**：案件（ForensicCase）的 REST CRUD 门面——建/查/列/删案件、往案件挂任务、更新案件状态与跨镜像分析作业号，全部落在 CaseManager 单例（data/cases.json）。
> **端点全量清单**：见 [CPP_REST_API.md](../../../../api_reference/CPP_REST_API.md) 与 [RouteReference.md](./RouteReference.md)。

## 1. 这组路由承担什么

把"多个分析任务组织成一个取证案件"的能力暴露成 HTTP：前端 /cases 页据此建案、挂任务、看状态、发起跨镜像分析。本组路由自身零业务逻辑——每个 handler 都是"解析 JSON → 调 CaseManager 一个方法 → 序列化回包"的三段式，案件的持久化、状态机、悬空引用等语义全部在 [CaseManager](../CaseManager.md)，排障先去那边。

## 2. 典型调用方

调用链比表面多一跳，这是本组路由最重要的拓扑事实：

```
浏览器 /cases 页（web/src/pages/Cases.jsx）
  └─ redux caseSlice → caseGroupService.js（pythonApi 基址）
       └─ Python 服务 /api/llm/cases*（httpserver/routes/multi_analysis.py:98-180）
            └─ 代理转发到 C++ /api/cases*（settings.cpp_backend_url）  ← 本组路由在这里
                 └─ CaseManager 单例 → data/cases.json
```

前端**从不直连** C++ 的 `/api/cases`（web/src 全量检索无命中）——Python 的 multi_analysis 路由是它的唯一线上调用方，同时负责附加能力（associate-tasks 预热复用状态、multi-image-analysis 编排）。联调抓包时要在 Python 侧或 C++ 侧分别看，别只盯浏览器请求。

## 3. 端点分组与语义

六条路由（CaseCRUDRoutes.cpp:13-39），两组语义：

**案件本体**：

- `GET /api/cases`：全量列表 + total（:44-54）；
- `POST /api/cases`：body `{name, description, task_ids[]}`，缺省 name 为 "Unnamed Case"（:61-66）；成功 201 返回完整案件 JSON；
- `GET /api/cases/{id}`：查不到（fc.id 为空判据）→ 404（:79-92）；
- `DELETE /api/cases/{id}`：只删案件记录，**不级联任务**（CaseManager.delete_case 只擦 map，见 CaseManager.md §3.3）→ 200。

**子资源（注意都是 PUT，没有通用的 PUT /api/cases/{id}）**：

- `PUT /api/cases/{id}/tasks`：body 必须含 `task_ids` 数组，逐个 `add_task`（去重）后返回最新案件（:94-114）；
- `PUT /api/cases/{id}/status`：**双职责**端点——`status` 字符串（小写 open/analysing/completed/failed）走 `update_status`，`cross_analysis_job_id` 走 `set_cross_analysis_job`，两者可同时出现（:131-154）。跨镜像分析的 job id 回填就走这里（Python 编排完成后转发，multi_analysis.py:270、294）。

序列化约定（case_to_json，:158-173）：status 全小写字符串；created_at/updated_at 为毫秒 epoch——与 tasks.json 里大写的任务状态并存，脚本处理时逐处确认（与 CaseManager.md §6 的提醒一致）。

## 4. 数据从哪来

- 全部读写经 `CaseManager::instance()`（构造时注入成员，:11）——内存 map + 每次变更全量 dump `data/cases.json`；
- **不查任何任务的 SQLite 库**：task_ids 是纯字符串引用，任务详情由前端另行调任务接口；
- 跨镜像分析本体不在本组：C++ 只保管 job id，分析在 Python 侧执行。

## 5. 常见错误与边界

- **悬空 task_id**：删任务不会摘除案件里的引用（也不归这组路由管）；GET 案件返回的 task_ids 可能含有已删除任务，前端渲染要容忍任务 404。
- **没有通用的 PUT /api/cases/{id}**：想改 name/description 没有端点（CaseManager 也无对应方法）——只能删了重建；别按 REST 直觉发 PUT。
- **status 值校验宽松**：未知字符串静默落为 OPEN（:138-142 的 if-else 链没有 else 分支报错），拼错 "analyzing"（单 l）会得到 "open" 而非 400。
- **错误响应形状不统一**：本组用 `{error: …}`（:74、86），没有 FilterRoutes 那种 ApiResponse 封装——跨路由写客户端时注意。
- **代理链路上的 404 语义叠加**：Python 代理转发 C++ 的 404 时可能再包一层自己的错误体；排查"案件不存在"要区分是 Python 侧找不到还是 C++ 侧 404。
- **非原子持久化**（继承自 CaseManager）：写 cases.json 中途崩溃会损坏文件，解析失败时全部案件丢失——路由层无感知。

## 6. 如何验证与扩展

- 冒烟（直接打 C++）：`curl -X POST :8080/api/cases -d '{"name":"t","task_ids":["<id>"]}'` → `curl :8080/api/cases` → `curl -X PUT :8080/api/cases/<id>/status -d '{"status":"analysing","cross_analysis_job_id":"job-1"}'` → `cat data/cases.json` 核对落盘 → `curl -X DELETE` 后确认任务本身仍在（不级联）。
- 扩展：新案件字段改 CaseManager 的 save/load 与本文件 case_to_json（:158-173）三处同步；新增端点沿用"handler → CaseManager 方法 → case_to_json"三段式；若要给案件加派生统计（如完成度），在路由层算，别把派生值落盘（与 CaseManager.md §7 建议一致）。

**最后更新**: 2026-08-23（新建，解释式）
