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

## 8. 全端点清单（注册表视角，二轮补全）

下表是**运行时真正注册到 `crow::App` 的全部端点**，按聚合器 → 子路由文件组织（来源：各 routes/*.cpp 中的 `CROW_ROUTE` 宏逐文件统计）。这是排障"URL→代码"的权威索引，与 routes/RouteReference.md 互补（后者含参数与响应细节）。

### 8.1 TaskRoutes（3 个子路由成员 + 16 个 OPTIONS 兜底）

| 子路由文件 | 注册端点（方法见名） |
|---|---|
| TaskCRUDRoutes.cpp | POST/GET `/tasks`、GET/DELETE `/tasks/<string>`、GET `/tasks/<string>/results`、POST/GET `/api/tasks`、GET `/api/tasks/list`、GET/PUT/DELETE `/api/tasks/<string>`、GET `/api/tasks/<string>/results`、POST `/api/tasks/cleanup`、GET `/api/tasks/<string>/databases` |
| TaskBatchRoutes.cpp | POST `/api/tasks/batch-create`、POST `/api/tasks/batch-status`、POST `/api/tasks/batch-cancel` |
| TaskMonitoringRoutes.cpp | GET `/api/tasks/<string>/progress`、GET `/api/tasks/<string>/audit-log`、GET `/api/tasks/statistics`、PUT `/api/tasks/<string>/priority` |
| TaskRoutes.cpp 自身 | 仅 16 个 OPTIONS 预检路由（`/tasks`、`/tasks/<string>`、`/tasks/<string>/results`、`/api/tasks`、`/api/tasks/list`、`/api/tasks/<string>`、`/api/tasks/<string>/{results,progress,audit-log,priority,databases}`、`/api/tasks/{statistics,cleanup,batch-create,batch-status,batch-cancel}`），全部 204 |

注意 `/tasks`（无 `/api` 前缀）是 TaskCRUDRoutes 注册的**遗留别名**，前端 Services 层不再调用，但仍在伺服。SceneQueryRoutes 注册的 `/api/tasks/<string>/{scene-stats,scene-artifacts}` 虽然挂在 `/api/tasks/` 前缀下，却是由 **ForensicsRoutes** 的 `scene_query_routes_` 成员注册的（SceneQueryRoutes.cpp:8-9 附近）——按 URL 前缀找代码会找错聚合器。

### 8.2 ForensicsRoutes（11 个子路由成员）

| 子路由文件 | 注册端点 |
|---|---|
| TimelineRoutes.cpp | 11 个：`/api/forensics/timeline/{comprehensive,details,distribution,file-activity,suspicious-patterns,user-activity,by-type,by-time-range,by-file,full,statistics-by-period}` |
| EventClusterRoutes.cpp | 4 个：`/api/forensics/timeline/clusters/{analyze,batch-analyze,reanalyze,analyzed}` |
| ExportRoutes.cpp | 4 个：`/api/forensics/export/toon`、`/api/forensics/export/events/{json,csv,visualization}` |
| FileAnalysisRoutes.cpp | 5 个：`/api/forensics/files/{largest,recent,suspicious,duplicates,extensions-analysis}` |
| FileExtractionRoutes.cpp | 3 个：POST `/api/forensics/extract`、GET `/api/forensics/extract/<string>`、GET `/api/forensics/extract/status` |
| StatisticsRoutes.cpp | 4 个：`/api/forensics/statistics/{overview,file-distribution,activity-patterns,deleted-files-analysis}` |
| AndroidForensicsRoutes.cpp | 14 个：`/api/forensics/android/{communication-summary,app-usage,device-info,media-analysis,llm-summary}` + 9 个 `miui-*` |
| MemoryForensicsRoutes.cpp | 5 个：`/api/forensics/memory/{summary,processes,network,bash-history,boot-info}` |
| SystemEventRoutes.cpp | 2 个：`/api/forensics/system/{events,summary}` |
| DLLAnalysisRoutes.cpp | 7 个：`/api/forensics/dlls`、`/api/forensics/dlls/<int>`、`/api/forensics/dlls/{suspicious,statistics,analyze,health}`、`/api/forensics/dlls/<int>/anomalies` |
| SceneQueryRoutes.cpp | 2 个：`/api/tasks/<string>/{scene-stats,scene-artifacts}`（前缀例外，见上） |

### 8.3 SystemRoutes / SearchRoutes / CaseCRUDRoutes / FilterRoutes

| 聚合器 | 子路由文件 | 注册端点 |
|---|---|---|
| SystemRoutes | SystemHealthRoutes.cpp | 5 个：`/api/system/health`、`/api/health`、`/api/health/{live,ready,dependencies}` |
| | SystemInfoRoutes.cpp | 5 个：`/api/system/info`、`/api/system/databases`、`/api/system/database-schema/<string>`、`/api/export/<string>`、`/api/system/logs` |
| | SystemDocsRoutes.cpp | 4 个：`/api/docs/{endpoints,database-schema,openapi.json}`、`/api/docs` |
| SearchRoutes | 自身 | 2 个：GET `/api/search/fulltext`、POST `/api/search/index` |
| CaseCRUDRoutes | 自身 | 6 个：GET/POST `/api/cases`、GET/PUT/DELETE `/api/cases/<string>`、GET `/api/cases/<string>/tasks`、PUT `/api/cases/<string>/status` |
| FilterRoutes | 自身 | 5 个：GET/POST `/api/filter/profiles`、GET/PUT/DELETE `/api/filter/profiles/<string>`、POST `/api/filter/apply` |

### 8.4 从未注册的端点（死注册代码）

OSS 家族 4 个路由文件共 12 个端点全部**编译进二进制但运行时 404**，因为唯一的组装点 `OSSRoutes` 构造函数（OSSRoutes.cpp:23-28）从未被调用：

| 文件 | 端点 |
|---|---|
| OSSAnalysisRoutes.cpp | `/api/forensics/oss/{analyze,analyze/status,ai/filter,ai/analyze,download,ai/status}` |
| OSSQueryRoutes.cpp | `/api/forensics/oss/{objects,logs}` |
| OSSStatsRoutes.cpp | `/api/forensics/oss/{summary,stats/storage-class,stats/extensions,buckets}` |

另一个细节：OSSRoutes.cpp:25-27 用**局部变量**构造三个子路由（而非像 ForensicsRoutes 那样用成员），即使将来有人补一行 `OSSRoutes oss_routes_(app_)`，子路由对象在构造函数结束即析构——好在 Crow 的 CROW_ROUTE 把 handler 拷进 app 的路由表，析构不影响已注册端点，但这份"局部变量组装"写法与 ForensicsRoutes.h:79 注释"must be members to avoid dangling pointers"的团队约定相悖，复活 OSS 时应顺手改掉。

## 9. 新走读分支：静态托管的边界路径

### 9.1 非 GET 方法打到静态路由

`/<path>` 与 `/` 都只注册了 `"GET"_method`（HTTPserver.cpp:110、141）。Crow 对"路径匹配但方法不匹配"的请求返回 **405 Method Not Found**（Crow 内部即 404 路由表未命中 + 方法不匹配逻辑，实际返回 405 响应码），而不会落到 SPA fallback——因为 fallback 本身也是 GET-only。实测推论：

- `POST /some/spa/path` → 405（不是 index.html，也不是 JSON 错误）；
- `OPTIONS /` → 同样 405——静态路由**没有**像 API 路由那样配 OPTIONS 兜底，跨域预检只有打到 `/api/*` 才能拿到 204。前端与后端同源部署时这无碍；若把 SPA 与 API 拆到不同源，静态资源的预检会失败。

### 9.2 目录穿越的天然防线与残余风险

catch-all 拼路径是 `web_dir + "/" + path`（HTTPserver.cpp:121），没有显式防 `..`。实际防线来自 `serve_static_file` 的 `fs::is_regular_file` 检查（HTTPserver.cpp:163）：`web/dist/../src/main.cpp` 这类路径展开后仍是磁盘上的常规文件，**会**被读出来——`..` 并没有被过滤。也就是说，`GET /../src/main.cpp` 若 Crow 把 `<path>` 解码成 `../src/main.cpp`，理论上可读取 web/dist 之外的文件。Crow 的 `<path>` 参数以 `/` 分隔，`..` 段会原样进入 handler。这是一个低危但真实的信息泄露面（进程对工作目录的读权限即泄露边界），加固做法是在拼接后做 `fs::canonical` 前缀校验。

### 9.3 `app_.loglevel(crow::LogLevel::Warning)` 的副作用

`setup_static_routes` 的第一行（HTTPserver.cpp:88）把 Crow 日志级别压到 Warning——意思是每个请求的 access log（INFO 级）不再打印，只有路由注册冲突、异常等告警会出现在 stdout。排障"请求到底进没进后端"时不能依赖 Crow 日志，要用 `curl -v` 或抓包；这也解释了为什么运行期 stdout 相对安静。

## 10. 配置影响表（HTTPServer 视角）

HTTPServer 自身不读任何环境变量（`grep getenv HTTPserver.cpp` 为空），但它的行为被以下配置间接决定：

| 配置 | 默认 | 作用点 | 与 HTTPServer 的关系 |
|---|---|---|---|
| `HTTP_SERVER_PORT` | 代码缺省 8080（HTTPserver.h:83）；**run.sh 缺省 8666** | main→AnalysisOrchestrator→`run(port)` | 传给 `app_.port(port)`。run.sh:79 `CPP_PORT="${HTTP_SERVER_PORT:-8666}"`——.env 不写该变量时 run.sh 起在 8666，而代码内缺省是 8080，两侧漂移 |
| `HTTP_SERVER_HOST` | `0.0.0.0` | ConfigManager.cpp:141 | 仅被 `/api/system/info` 回显；**Crow 监听地址写死为全部接口**（`app_.port(port)` 未调 `.bind()`），该变量不影响实际绑定 |
| `CORS_ALLOW_ORIGIN` | `*` | RouteHelpers.cpp:16-17 | 只作用于 API 路由响应头；静态路由的 `*` 是硬编码（HTTPserver.cpp:115），设白名单**收敛不了**静态侧 |
| `DATA_DIR` | `data` | main.cpp:65 | 决定 `data/tasks/` 相对 CWD 的位置，间接决定静态路由之外所有任务数据寻址基准 |
| `THREAD_POOL_SIZE` | `4` | TaskManager.cpp:23 | Crow worker 数量 = `std::thread::hardware_concurrency()`（Crow `multithreaded()` 默认），与分析线程池无关；两者是两套并发度 |

## 11. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 | 说明 |
|---|---|---|---|
| 被调（构造） | AnalysisOrchestrator | AnalysisOrchestrator.cpp 的 runHTTPServer | 进程内唯一构造点，传 io_context 与端口 |
| 被调（请求） | web/dist SPA | `GET /`、`GET /<path>` | 浏览器唯一入口；静态三级回退 |
| 被调（请求） | taskService 等 24 个前端 service | `/api/tasks/*` 等 | 见 docs/modules/web/Services.md 的三向映射 |
| 持有 | TaskManager 单例引用 | 构造函数 HTTPserver.cpp:65 | 引用而非拥有；析构顺序上 HTTPServer 先于 TaskManager 单例销毁即可 |
| 持有 | 6 个路由聚合器（值成员） | HTTPserver.h:91-96 | 构造即注册；析构时 Crow app 仍在，路由表随 app_ 一起销毁 |
| 持有 | asio::io_context 引用 | HTTPserver.h:88 | 仅保存不使用（协程预留） |
| 不持有但同进程 | LLMPythonProxy | TaskManager 内部调用 | Graphiti 摄取不经 HTTP 回环，直接进程内 HTTP 客户端打到 8090 |
| 不持有 | OSSRoutes | 无任何构造点 | §8.4；唯一一个编译存在但运行时缺席的聚合器 |

## 12. MIME 表全量（get_mime_type 的 13 项）

HTTPserver.cpp:194-212 的完整映射（未命中兜底 `application/octet-stream`）：

| 扩展名 | Content-Type | 扩展名 | Content-Type |
|---|---|---|---|
| .html | text/html | .svg | image/svg+xml |
| .css | text/css | .ico | image/x-icon |
| .js | application/javascript | .woff | font/woff |
| .json | application/json | .woff2 | font/woff2 |
| .png | image/png | .ttf | font/ttf |
| .jpg / .jpeg | image/jpeg | .eot | application/vnd.ms-fontobject |
| .gif | image/gif | （其余） | application/octet-stream |

两个值得注意的细节：`.json` 会以 `application/json` 伺服——若有人把敏感配置放进 web/dist，浏览器同源策略下任何页面都能 fetch 它；`.map`（source map）不在表内，落 octet-stream 走下载——前端构建带 map 文件时 DevTools 无法直接加载源码映射（排障小坑）。

## 13. 请求处理管线：从 accept 到 handler

一次请求在 Crow 内的完整路径（结合 HTTPserver.cpp 的配置点）：

1. **accept**：`app_.port(port).multithreaded().run()`（:83）——Crow 按 `hardware_concurrency()` 起 worker 线程池，每个 worker 独立 epoll 循环接受连接；
2. **日志**：`app_.loglevel(crow::LogLevel::Warning)`（:88）压掉 per-request 的 INFO access log——生产 stdout 只有警告；
3. **路由匹配**：Crow 按注册顺序查路由表。**注册顺序**：六个聚合器（构造期）→ `/<path>` catch-all（run() 里 setup_static_routes 最先调用但 `/<path>` 是通配，具体 `/api/...` 仍优先匹配）→ `/` 根路由最后。路径参数路由（`/api/tasks/<string>`）在静态路由（`/api/tasks/list`）之后注册时，Crow 的 trie 匹配让静态段优先——这就是 list/statistics 不被 `<string>` 吞掉的机制保证（handler 层的保留字守卫是第二道防线）；
4. **方法匹配**：路径命中但方法不在 `.methods(...)` 列表 → 405（routing.h:1490）；
5. **handler 执行**：worker 线程内同步执行——handler 里做慢操作（如 batch-analyze 的同步 LLM 循环）直接占住该 worker；
6. **响应**：handler 返回的 crow::response 由 worker 写回。没有全局后处理中间件——CORS 头必须每个 handler 自己加（RouteHelpers::add_cors_headers 或手写 set_header）。

## 14. 排障速查表（HTTPServer 层）

| 症状 | 首查 | 根因候选 |
|---|---|---|
| 前端 404（所有页面） | `ls web/dist` 与进程 CWD | web/dist 相对路径耦合（§6）；未构建前端 |
| 静态资源 200 但 JS 报 MIME 错 | §12 表 | 自定义扩展名未进表 |
| API 404 但代码里有 CROW_ROUTE | HTTPserver.cpp:63-75 初始化列表 | 聚合器未挂载（OSSRoutes 即此）；或保留字守卫（TaskRoutes） |
| API 405 | handler 的 .methods(...) | 方法不匹配；静态路由 GET-only（§9.1） |
| OPTIONS 预检失败 | TaskRoutes.cpp:20-134 的 16 条 | 新端点没补 OPTIONS；静态路由无 OPTIONS |
| 请求到了但 stdout 无日志 | HTTPserver.cpp:88 | loglevel=Warning 压掉了 access log |
| 跨域失败但 API 正常 | CORS_ALLOW_ORIGIN / RouteHelpers | 白名单不含前端 origin；静态路由硬编码 `*` 与 API 白名单不一致 |
| 端口不是 8080 | run.sh:79 vs .env | run.sh 回退 8666 漂移（§10） |

## 15. 常见任务配方

### 配方 15.1：注册一个新路由组（聚合器 → 构造 → Swagger → vite 前缀四步）

**目标**：新增一组 `/api/xxx/*` 端点（一个聚合器类 + 若干 handler），Swagger 可见、前端 dev 模式可调。

**步骤**：

1. **写聚合器**：在 `src/network/HTTPServer/routes/` 新建 `XxxRoutes.{h,cpp}`，模仿 `SystemRoutes`（SystemRoutes.cpp:6-13——构造函数只做子路由组合）或直接写端点的 `FilterRoutes`（FilterRoutes.cpp:6-9 用 `CROW_ROUTE(app, "/api/filter/profiles").methods("GET"_method)(...)`）。构造签名统一 `XxxRoutes(crow::App<>& app)`，构造体内完成全部 CROW_ROUTE 注册。
2. **构造挂载**：`HTTPserver.h:85-102` 私有区加成员 `XxxRoutes xxx_routes_;`（**必须声明在 `app_` 之后**，成员按声明序初始化，§3.2），`HTTPserver.cpp:63-75` 初始化列表追加 `xxx_routes_(app_)`。漏掉这步就是 OSSRoutes 的命运——编译通过、运行时 404（§8.4）。
3. **补 Swagger**：每个端点后跟一个 `Swagger::instance().RegisterEndpoint("/api/xxx", "GET", 摘要, 描述, {"分类"}, {参数列表}, {响应码表})`（完整七参样例见 FilterRoutes.cpp:31-43；头文件 `#include "../../Swagger/Swagger.h"`）。不注册则 `/api/docs/openapi.json` 与 Swagger UI 看不到该端点。
4. **vite 前缀**（仅开发模式需要）：若新前缀不是 `/api/tasks` 等已被代理的路径，在 `web/vite.config.js` 的 `server.proxy`（:22 起）加一项，如 C++ 后端写 `'/api/xxx': { target: cppTarget, changeOrigin: true }`；Python 侧（8090/8091）参照 `/api/reports`、`/csapi` 的写法（后者带 rewrite 去前缀）。生产模式不受影响（同源托管）。

**注意**：新聚合器里的子路由对象要用**成员**而非构造函数局部变量（ForensicsRoutes.h:79 有 "must be members to avoid dangling pointers" 的团队约定；OSSRoutes.cpp:25-27 的局部变量写法是反面教材，虽因 CROW_ROUTE 拷贝 handler 而侥幸可用）；若 URL 前缀落在 `/api/tasks/` 下，记得扩 TaskCRUDRoutes.cpp:268-276 的保留字守卫列表，防止被 `/api/tasks/<string>` 吞掉。

**验证**：重启后 `curl -i http://localhost:<port>/api/xxx` 通；`curl .../api/docs/endpoints` 列表里出现新端点；前端 dev server（3000 端口）里 fetch 同路径经代理可达；`curl -X OPTIONS -i` 返回 204（若按配方 15.3 补了预检）。

### 配方 15.2：为现有路由加参数校验

**目标**：给一个直接 `std::stoi` 裸读 query 参数的 handler（如 `/api/forensics/files/largest` 的 limit）加上缺省、范围钳制与非法值 400，避免 `stoi("abc")` 抛未捕获异常。

**步骤**（以 FileAnalysisRoutes.cpp:41-57 为模板）：

1. **读参与缺省**：`int limit = params.get("limit") ? std::stoi(params.get("limit")) : 50;`（:45）——先判空再 stoi，`nullptr` 转 string 是 UB。
2. **把裸 stoi 包进校验**：stoi 对非数字串抛 `std::invalid_argument`，当前 handler 外层只有兜业务异常的 try（:53-61 会把它误报成 500）。校验的正确姿势是在读参处先过一层：
   ```cpp
   int limit = 50;
   if (auto* s = params.get("limit")) {
       try { limit = std::stoi(std::string(s)); } catch (...) { /* 400 */ }
       if (limit < 1) limit = 1; if (limit > 500) limit = 500;  // clamp
   }
   ```
3. **必填项走 400 早退**：task_id 为空时 `res.code = 400` + `{"error", "task_id parameter is required"}`（:47-52），这是全库统一错误形态。
4. **同步 Swagger 参数表**：RegisterEndpoint 的第五参补 `{"limit", "query", "Number of files to return", false, "integer"}`（FileAnalysisRoutes.cpp:19 已有此写法），让文档与实际校验一致。

**注意**：错误响应沿用各路由现状返回 `{"error": ...}` 裸 JSON（ApiResponse 外壳只有 FilterRoutes 用，§3.5），不要在个别路由引入新外壳造成不一致；`TaskMonitoringRoutes` 的 audit-log limit 参数至今无 stoi 保护（limit=abc 直接 500），排查类似问题时可对照。

**验证**：`curl ".../largest?task_id=<id>&limit=abc"` 得 400 而非 500；`limit=99999` 被钳到上限且 SQL 正常返回；缺 task_id 时 400 文案正确。

### 配方 15.3：为新端点加 CORS 预检（OPTIONS）

**目标**：跨域前端（SPA 与 API 不同源部署时）对带自定义头/非简单方法的请求先发 OPTIONS 预检，Crow 不会自动应答，需要逐路径注册。

**步骤**（固定模式，照抄 TaskRoutes.cpp:22-34）：

```cpp
CROW_ROUTE(app, "/api/xxx/<string>").methods("OPTIONS"_method)([](const crow::request& req, const std::string& id){
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.code = 204;
    return res;
});
```

三要素缺一不可：`.methods("OPTIONS"_method)` 显式注册方法、`RouteHelpers::add_cors_headers(res)`（RouteHelpers.cpp:12-20，读 `CORS_ALLOW_ORIGIN` 环境变量，回 Allow-Origin/Methods/Headers 三头）、`res.code = 204`（No Content 是预检的标准应答）。路径必须与真实端点**完全同形**（`<string>` 占位符一致），否则 trie 匹配不上。

**注意**：

- 预检路由要与业务路由注册在同一聚合器构造期（注册顺序无碍，方法不同不冲突）；TaskRoutes.cpp:14-134 现存 16 条就是这个模式的手工展开——新端点忘补时症状是浏览器 console 报 CORS 但 curl 直调正常（排障表 §14 有此行）。
- Allow-Headers 列表写死为 `Content-Type, Authorization, X-Requested-With`（RouteHelpers.cpp:19）——前端若发其他自定义头（如 X-Api-Key），预检仍会失败，需在 RouteHelpers 里扩，这是全局一处改动。
- 静态路由（`/<path>`、`/`）没有 OPTIONS 兜底且 GET-only（§9.1），跨域预检打到非 /api 路径会得 405，属已知边界。

**验证**：`curl -X OPTIONS -i -H "Origin: http://other.host" http://localhost:<port>/api/xxx/abc` 返回 204 且响应头含三个 Access-Control-*；浏览器 Network 面板预检请求绿色通过。

### 配方 15.4：加一个静态资源路径/类型

**目标**：让 web/dist 下新放的资源（新扩展名文件、或需要伺服的额外目录）被正确伺服——正确的 Content-Type 与缓存策略。

**步骤**：

1. **普通文件**：直接放进 `web/dist/`（经前端构建或手工），catch-all `/<path>`（HTTPserver.cpp:109-137）自动伺服，无需改代码。
2. **新扩展名**：`get_mime_type`（HTTPserver.cpp:194-212）的 hand-written 表补一个分支（如 `.wasm → application/wasm`），否则落 `application/octet-stream` 浏览器走下载。
3. **要长缓存的资源**：`serve_static_file`（HTTPserver.cpp:162-192）的扩展名白名单（:134-138，现含 js/css/png/jpg/jpeg/gif/svg/ico/woff/woff2/ttf）补上扩展名，命中即加 `Cache-Control: public, max-age=31536000`。前提是文件名带内容哈希（Vite 产物天然满足）；不带哈希的文件别加长缓存，否则更新不生效。
4. **web/dist 之外的目录**：当前没有机制——`web_dir` 硬编码 `"web/dist"`（:120）且相对 CWD（§6）。要么把文件软链/拷贝进 web/dist，要么改 `setup_static_routes` 加第二前缀路由（改动时注意 §9.2 的目录穿越风险，拼接后应做 `fs::canonical` 前缀校验）。

**注意**：`.json` 会以 `application/json` 同源伺服（§12），敏感配置别放 web/dist；`.map` 不在 MIME 表，DevTools 加载不了 source map（已知小坑，顺手可补 `application/json`）。`serve_static_file` 整文件读入内存（§6），大文件（演示视频等）会占等量内存。

**验证**：`curl -I http://localhost:<port>/<新路径>` 看 200 + 正确 Content-Type；带缓存的扩展名应见 `Cache-Control: public, max-age=31536000`；`curl -I .../不存在的深层路径` 回落 index.html（SPA fallback 正常）。

**最后更新**: 2026-08-24（补：常见任务配方）
