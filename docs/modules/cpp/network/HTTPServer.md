# HTTPServer（src/network/HTTPServer/HTTPserver.{h,cpp}）

> **一句话**：整个 C++ 后端的入口——持有 Crow 多线程 HTTP 服务、装配六组路由聚合器、并把 React 前端作为静态文件托管出来，使 TraceLens 成为"单进程即全栈"的取证平台。

## 1. 为什么有这个模块

取证分析传统上是命令行工具的天下，但一次镜像分析动辄数小时，调查员需要随时查看进度、翻阅结果。把分析能力包成 REST API 并同进程托管 Web 前端，带来三个好处：

- **异步任务模型**：HTTP 请求秒回，长耗时分析在 TaskManager 的线程池里跑，前端轮询进度。
- **零部署分离**：前端构建产物（web/dist）由同一个进程伺服，打开浏览器即可用，不需要单独的 Nginx。
- **可编排**：Python 服务（Graphiti 知识图谱）、Xapian 全文搜索等都可以通过 HTTP 与之协作。

## 2. 在系统中的位置

```
浏览器 (React SPA, web/dist)
   │  HTTP
   ▼
HTTPServer (Crow, 多线程)          ── 对外唯一入口
   ├─ 6 个路由聚合器（见下）
   ├─ TaskManager 单例（任务执行）
   ├─ SQLiteHelper（查询任务产出库）
   └─ 静态文件托管（SPA fallback）
```

- **谁启动它**：`main.cpp:103` 经 `AnalysisOrchestrator::runHTTPServer(cmdArgs.http_port)` 拉起。
- **它构造谁**：构造函数按序实例化六个路由聚合器成员（HTTPserver.cpp:63-75）：`TaskRoutes`、`ForensicsRoutes`、`SystemRoutes`、`SearchRoutes`、`CaseCRUDRoutes`、`FilterRoutes`。各聚合器构造时向共享的 `crow::App<>` 注册自己的端点，并继续向下组合子路由组（详见 routes/ 目录各文档）。
- **重要**：`OSSRoutes` 聚合器**从未在这里被构造**，所有 `/api/forensics/oss/*` 端点运行时 404（原因与历史见 routes/OSSRoutes.md）。

## 3. 核心概念与设计

### 3.1 构造函数即"路由装配表"

`HTTPServer` 自身不注册任何业务路由。它的构造函数只做两件事：拿 `TaskManager` 单例引用、构造六个聚合器（HTTPserver.cpp:63-75）。这是"组合式注册"：新增一组路由 = 写一个聚合器类 + 头文件加成员 + 初始化列表加一行。HTTPServer 对具体端点一无所知，符合单一职责。

### 3.2 静态托管与 SPA fallback

前端是 React SPA，带客户端路由（/tasks、/timeline 等页面 URL）。Crow 按注册顺序匹配，所以 catch-all 必须最后注册（`setup_static_routes` 在 `run()` 里最先调用，但它注册的 `/<path>` 是通配路由，业务路由 ` /api/...` 更具体、先被各聚合器注册）：

- `CROW_ROUTE(app_, "/<path>")`（HTTPserver.cpp:109）先尝试从 `web/dist` 伺服真实文件（HTTPserver.cpp:120，**相对路径**，进程工作目录必须在构建产物目录附近）；
- 找不到则回落到 `index.html`（HTTPserver.cpp:127-131），交给前端路由器；
- 根路由 `/` 同理（HTTPserver.cpp:140）；前端未构建时返回带构建指引的 404 文案（HTTPserver.cpp:155）。

静态资源（js/css/图片/字体）设一年缓存（HTTPserver.cpp:186），HTML 不缓存——标准 SPA 缓存策略。

### 3.3 CORS 的两套实现

- 静态路由内联写死 `Access-Control-Allow-Origin: *`（HTTPserver.cpp:92-94、115-117）；
- 所有 API 路由统一调用 `RouteHelpers::add_cors_headers`（routes/RouteHelpers.cpp:12-20），读取环境变量 `CORS_ALLOW_ORIGIN`，可收敛为白名单，默认仍是 `*`。

HTTPserver.cpp:91-103 还定义了一个"全局 CORS 中间件" lambda，但它**从未被挂载**——是未启用的草稿代码，读代码时不要被它误导。

### 3.4 ApiResponse：想统一却没统一的响应封装

`ApiResponse`（HTTPserver.h:35-64）设计了统一的 `{success, message, data, timestamp, pagination, error_code}` 外壳，工厂方法在 HTTPserver.cpp:36-61。**但全局只有 FilterRoutes 真正使用它**；其余路由直接返回裸 JSON，错误时是 `{"error": ...}`。写 API 客户端时不要假设统一外壳。

## 4. 工作流程走读

一次"打开浏览器 → 建任务 → 看结果"的旅程：

1. `GET /` 命中根路由（HTTPserver.cpp:140），返回 `web/dist/index.html`；`/tasks` 等深层路径经 catch-all（HTTPserver.cpp:109）回落到同一 HTML。
2. 页面发 `POST /api/tasks`。Crow 多线程 worker（`app_.port(port).multithreaded().run()`，HTTPserver.cpp:83）接住请求，匹配到 TaskCRUDRoutes 的 handler。
3. handler 调 `TaskManager::instance().create_task(...)` 并触发 `start_analysis`，请求立刻返回 201（细节见 routes/TaskRoutes.md）。
4. 前端轮询 `/api/tasks/{id}/progress`——直接读 TaskManager 内存态。
5. 任务完成后前端改调 `/api/forensics/*`，handler 经 `SQLiteHelper` 查询任务的 SQLite 产出库。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| TaskManager | HTTPServer 持有单例引用；任务类路由是它的 REST 门面 |
| 六个路由聚合器 | 构造期注册端点；HTTPServer 不感知具体端点 |
| SQLiteHelper | 结果查询路由的数据访问层 |
| LLMPythonProxy | Graphiti 摄取（TaskManager 触发，不经过 HTTPServer 本身） |
| web/dist | 静态托管目录；相对路径耦合启动位置 |

## 6. 注意事项与已知问题

- **工作目录耦合**：`web/dist` 为相对路径（HTTPserver.cpp:120），换目录启动进程前端会 404。
- **OSSRoutes 未注册**：历史遗留死代码，见 routes/OSSRoutes.md；OSS 页面调不通不是 bug。
- **CORS 默认全开**：`*` 意味着任意网页可调用 API；生产环境应设置 `CORS_ALLOW_ORIGIN`。
- **未挂载的 CORS lambda**：HTTPserver.cpp:91-103 是死代码。
- **ApiResponse 仅 FilterRoutes 使用**：不要在 API 客户端里依赖统一响应结构。

## 7. 如何验证与扩展

- **验证**：`curl http://localhost:8080/api/health` 确认存活；`curl -I http://localhost:8080/` 看 HTML 与 CORS 头；访问不存在的路径应返回 index.html（SPA fallback 生效标志）。
- **扩展新路由组**：模仿 `SystemRoutes`（构造函数三行组合子路由），在 HTTPserver.h:91-96 加成员、HTTPserver.cpp:63-75 初始化列表加一行。静态托管无需改动。

**最后更新**: 2026-08-23（解释式重写）
