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

### 3.1 类骨架：HTTPServer 到底持有什么

```cpp
// HTTPserver.h:85-102
private:
    crow::App<> app_;
    TaskManager& task_manager_;
    asio::io_context& ioc_;

    // Modular Route Handlers
    TaskRoutes task_routes_;
    ForensicsRoutes forensics_routes_;
    SystemRoutes system_routes_;
    SearchRoutes search_routes_;
    CaseCRUDRoutes case_routes_;
    FilterRoutes filter_routes_;

    // Static file serving
    void setup_static_routes();
    std::string get_mime_type(const std::string& path);
    bool serve_static_file(crow::response& res, const std::string& relative_path);
```

四个私有字段的分工值得逐个看：`app_` 是 Crow 的路由表+HTTP 引擎，所有 CROW_ROUTE 宏最终注册到它身上；`task_manager_` 是**引用**而非值——它在构造函数里绑到 `TaskManager::instance()` 单例，HTTPServer 自己不创建也不拥有任务管理器；`ioc_` 是外部传入的 ASIO io_context（协程基础设施），当前代码只保存不使用，是为将来协程 handler 预留的口子；六个聚合器成员的**构造顺序就是路由注册顺序**，它们在初始化列表里依次拿到 `app_` 引用并完成端点注册。

### 3.2 构造函数即"路由装配表"

`HTTPServer` 自身不注册任何业务路由。它的构造函数只做两件事：拿 `TaskManager` 单例引用、构造六个聚合器。这是"组合式注册"：新增一组路由 = 写一个聚合器类 + 头文件加成员 + 初始化列表加一行。HTTPServer 对具体端点一无所知，符合单一职责。

```cpp
// HTTPserver.cpp:63-75
HTTPServer::HTTPServer(asio::io_context& ioc)
    : app_(),
      task_manager_(TaskManager::instance()),
      ioc_(ioc),
      task_routes_(app_),
      forensics_routes_(app_),
      system_routes_(app_),
      search_routes_(app_),
      case_routes_(app_),
      filter_routes_(app_)
{
    // Route handlers are initialized in their respective classes
}
```

初始化列表按**声明顺序**执行（C++ 规则：成员初始化顺序跟声明序而非列表序），所以六个聚合器一定在 `app_` 构造完成之后才注册路由——若有人调整头文件里成员声明顺序，把聚合器挪到 `app_` 之前，这里会直接编译失败或未定义行为，改动类骨架时要意识到这层隐含约束。`run()` 则更简单（HTTPserver.cpp:77-84）：先 `setup_static_routes()` 注册 catch-all，再 `app_.port(port).multithreaded().run()` 阻塞进入 Crow 的事件循环——`multithreaded()` 让 Crow 按硬件并发数起 worker 线程，这也是为什么所有 handler 必须线程安全（TaskManager 的大锁、SQLiteHelper 的每请求新连接，都是为此设计）。

### 3.3 静态托管与 SPA fallback

前端是 React SPA，带客户端路由（/tasks、/timeline 等页面 URL）。Crow 按注册顺序匹配，所以 catch-all 必须最后注册（`setup_static_routes` 在 `run()` 里最先调用，但它注册的 `/<path>` 是通配路由，业务路由 ` /api/...` 更具体、先被各聚合器注册）：

```cpp
// HTTPserver.cpp:109-137
CROW_ROUTE(app_, "/<path>")
.methods("GET"_method)
([this](const crow::request& req, const std::string& path){
    crow::response res;

    // Add CORS headers
    res.set_header("Access-Control-Allow-Origin", "*");
    // ...

    // Try to serve file from web/dist directory
    std::string web_dir = "web/dist"; // Relative to binary location
    std::string file_path = web_dir + "/" + path;

    if (serve_static_file(res, file_path)) {
        return res;
    }

    // Fallback to index.html for SPA routing
    std::string index_path = web_dir + "/index.html";
    if (serve_static_file(res, index_path)) {
        return res;
    }

    // File not found
    res.code = 404;
    res.write("Not Found");
    return res;
});
```

这个 handler 的三级回退决定了 SPA 的行为：先按字面路径找静态文件（`/assets/index-abc123.js` 命中真实文件）；找不到（`/timeline` 不是文件）回落 `index.html`，把路径交给前端路由器渲染对应页面；连 index.html 都没有说明前端没构建，返回 404。注意 `web_dir` 是**相对路径**（HTTPserver.cpp:120）——解析基准是进程工作目录而非可执行文件位置，这是 §6 工作目录耦合问题的根源。

真正的文件伺服与缓存策略在 `serve_static_file`：

```cpp
// HTTPserver.cpp:162-192（节选）
bool HTTPServer::serve_static_file(crow::response& res, const std::string& file_path) {
    if (!fs::exists(file_path) || !fs::is_regular_file(file_path)) {
        return false;
    }
    // ...
    std::ostringstream content;
    content << file.rdbuf();

    std::string mime_type = get_mime_type(file_path);
    res.set_header("Content-Type", mime_type);

    // Add cache headers for static assets
    std::string ext = fs::path(file_path).extension().string();
    if (ext == ".js" || ext == ".css" || ext == ".png" ||
        ext == ".jpg" || ext == ".jpeg" || ext == ".gif" ||
        ext == ".svg" || ext == ".ico" || ext == ".woff" ||
        ext == ".woff2" || ext == ".ttf") {
        res.set_header("Cache-Control", "public, max-age=31536000"); // 1 year
    }

    res.code = 200;
    res.write(content.str());
    return true;
}
```

资源扩展名（js/css/图片/字体）设一年缓存——Vite 构建的资源文件名带内容哈希，文件变了名字就变，长缓存是安全的；HTML 不缓存，保证用户总能拿到引用最新资源入口。`get_mime_type`（HTTPserver.cpp:194-212）是一张手写扩展名表，未命中的扩展名一律 `application/octet-stream`（浏览器走下载而非渲染，顺带避免了把未知文件当 HTML 执行的风险）。根路由 `/` 同理返回 index.html（HTTPserver.cpp:140）；前端未构建时返回带构建指引的 404 文案（HTTPserver.cpp:155）。

### 3.4 CORS 的两套实现

- 静态路由内联写死 `Access-Control-Allow-Origin: *`（HTTPserver.cpp:92-94、115-117）；
- 所有 API 路由统一调用 `RouteHelpers::add_cors_headers`（routes/RouteHelpers.cpp:12-20），读取环境变量 `CORS_ALLOW_ORIGIN`，可收敛为白名单，默认仍是 `*`。

HTTPserver.cpp:91-103 还定义了一个"全局 CORS 中间件" lambda，但它**从未被挂载**——是未启用的草稿代码，读代码时不要被它误导（lambda 内对 OPTIONS 请求返回 204 并 `return true` 的写法暗示它本想作为 Crow middleware 使用，注释"Register global middleware - but we need to use it differently"也印证了这只是个半成品）。实际的 OPTIONS 预检由各聚合器自己兜底——TaskRoutes 就为此注册了 16 个逐路径 OPTIONS 路由（见 routes/TaskRoutes.md §3.1）。

### 3.5 ApiResponse：想统一却没统一的响应封装

```cpp
// HTTPserver.h:35-64
struct ApiResponse {
    bool success = true;        ///< Operation success status
    std::string message;        ///< Human-readable message
    nlohmann::json data;        ///< Response payload
    std::string timestamp;      ///< ISO 8601 server time
    nlohmann::json pagination;  ///< Pagination metadata
    std::string error_code;     ///< Application-specific error code

    nlohmann::json to_json() const;
    static ApiResponse create_success(const std::string& msg = "", const nlohmann::json& data = nullptr);
    static ApiResponse create_error(const std::string& msg, const std::string& error_code = "");
};
```

`to_json()`（HTTPserver.cpp:21-34）只在 `pagination`/`error_code` 非空时输出对应键——成功响应不会带空的 `pagination: {}` 噪声。工厂方法的实现里藏着一个有价值的注释：

```cpp
// HTTPserver.cpp:36-49（节选）
ApiResponse ApiResponse::create_success(const std::string& msg, const nlohmann::json& data) {
    ApiResponse response;
    response.success = true;
    response.message = msg;
    // NOTE: Do not use `data ? data : ...` here — nlohmann's operator bool()
    // converts the value to a bool and throws type_error.302 for any non-bool
    // JSON (e.g. an object or array). Use is_null() to detect "no payload".
    response.data = data.is_null() ? nlohmann::json::object() : data;
    // ...
}
```

nlohmann 的 `operator bool()` 是"是否可转为 bool"而非"是否有值"，对象/数组直接抛 type_error.302——这是该库最常踩的坑之一，作者用注释把它固化在工厂里，任何复用此结构的人都被保护。

**但全局只有 FilterRoutes 真正使用它**；其余路由直接返回裸 JSON，错误时是 `{"error": ...}`。写 API 客户端时不要假设统一外壳。

## 4. 工作流程走读

一次"打开浏览器 → 建任务 → 看结果"的旅程：

1. `GET /` 命中根路由（HTTPserver.cpp:140），返回 `web/dist/index.html`；`/tasks` 等深层路径经 catch-all（HTTPserver.cpp:109）回落到同一 HTML。
2. 页面发 `POST /api/tasks`。Crow 多线程 worker（`app_.port(port).multithreaded().run()`，HTTPserver.cpp:83）接住请求，匹配到 TaskCRUDRoutes 的 handler。
3. handler 调 `TaskManager::instance().create_task(...)` 并触发 `start_analysis`，请求立刻返回 201（细节见 routes/TaskRoutes.md）。
4. 前端轮询 `/api/tasks/{id}/progress`——直接读 TaskManager 内存态。
5. 任务完成后前端改调 `/api/forensics/*`，handler 经 `SQLiteHelper` 查询任务的 SQLite 产出库。

### 4.1 一个请求在进程内的完整链路（关联信息）

| 前端动作 | 路由聚合器 | 实际 handler/子路由 | 数据终点的模块与文件 |
|---|---|---|---|
| 提交镜像（POST /api/tasks） | TaskRoutes | TaskCRUDRoutes::handle_create_task（TaskCRUDRoutes.cpp:127） | TaskManager::create_task → data/tasks.json |
| 看进度（GET /{id}/progress） | TaskRoutes | TaskMonitoringRoutes（TaskMonitoringRoutes.cpp:46） | TaskManager 内存态 tasks_ |
| 翻时间线（GET timeline/comprehensive） | ForensicsRoutes | TimelineRoutes（TimelineRoutes.cpp:112） | RouteHelpers::get_database_path → SQLiteHelper/TimelineQueries → `_events.db` |
| 全文检索（GET /api/search/fulltext） | SearchRoutes | handle_fulltext_search（SearchRoutes.cpp:68） | XapianSearcher → 索引目录（不经 SQLite） |
| 看 API 文档（GET /api/docs/openapi.json） | SystemRoutes | SystemDocsRoutes（SystemDocsRoutes.cpp:115） | Swagger 单例注册表 |

这张表也是排障时的"URL → 代码"索引：拿到一个 404/500，先定位聚合器，再看子路由文件，最后落到数据层。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| TaskManager | HTTPServer 持有单例引用；任务类路由是它的 REST 门面 |
| 六个路由聚合器 | 构造期注册端点；HTTPServer 不感知具体端点 |
| SQLiteHelper | 结果查询路由的数据访问层 |
| LLMPythonProxy | Graphiti 摄取（TaskManager 触发，不经过 HTTPServer 本身） |
| web/dist | 静态托管目录；相对路径耦合启动位置 |
| Swagger | 各聚合器构造时顺带 RegisterEndpoint；出口在 SystemDocsRoutes |

## 6. 注意事项与已知问题

- **工作目录耦合**：`web/dist` 为相对路径（HTTPserver.cpp:120），换目录启动进程前端会 404。修复要么改成基于可执行文件路径解析，要么在启动脚本里 `cd` 到约定目录。
- **OSSRoutes 未注册**：历史遗留死代码，见 routes/OSSRoutes.md；OSS 页面调不通不是 bug。
- **CORS 默认全开**：`*` 意味着任意网页可调用 API；生产环境应设置 `CORS_ALLOW_ORIGIN`。
- **未挂载的 CORS lambda**：HTTPserver.cpp:91-103 是死代码。
- **ApiResponse 仅 FilterRoutes 使用**：不要在 API 客户端里依赖统一响应结构。
- **静态文件整文件读入内存**：`serve_static_file` 用 `file.rdbuf()` 一次性读入再写出（HTTPserver.cpp:173-174），没有流式传输；对 js/css 这类 MB 级资源无碍，但若有人往 web/dist 放大文件（如演示视频）会占用等量内存。

## 7. 如何验证与扩展

- **验证**：`curl http://localhost:8080/api/health` 确认存活；`curl -I http://localhost:8080/` 看 HTML 与 CORS 头；访问不存在的路径应返回 index.html（SPA fallback 生效标志）；`curl -I .../assets/<某js>` 应看到 `Cache-Control: public, max-age=31536000`。
- **扩展新路由组**：模仿 `SystemRoutes`（构造函数三行组合子路由），在 HTTPserver.h:91-96 加成员、HTTPserver.cpp:63-75 初始化列表加一行。静态托管无需改动。记住成员声明顺序必须保持在 `app_` 之后（§3.2）。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
