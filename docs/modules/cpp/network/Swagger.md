# Swagger（src/network/Swagger/Swagger.{h,cpp}）

> **一句话**：进程内单例的 OpenAPI 注册表——各路由类在构造时把端点（路径/方法/摘要/参数/响应）喂进来，`GetSwaggerJSON()` 把它渲染成 OpenAPI 3.0 文档，经 `/api/docs/openapi.json` 与 Swagger UI 页面（`/api/docs`）对外输出。

## 1. 为什么有这个模块

Crow 框架不内省路由：真实注册了哪些端点、参数是什么，只存在于代码里。多轮迭代后"文档漂移"必然发生——要么手写清单过时，要么新端点忘了记。本模块的思路是**注册即文档**：每个路由文件在 `CROW_ROUTE` 旁边立刻 `RegisterEndpoint`，两者物理上同处一个构造函数，新增路由时"忘了注册文档"至少与"忘了写路由"同难度。openapi.json 由此生成，**与代码同步**。

## 2. 在系统中的位置

```
各路由类构造函数（HTTPServer 启动时实例化，HTTPserver.cpp:66-73）
  ├─ TaskRoutes / SearchRoutes / FilterRoutes / … 每个 CROW_ROUTE 旁调用
  └─ Swagger::instance().RegisterEndpoint(path, method, summary, …)   ← 唯一写入口
                                            │ 单例内存 map<string, vector<Operation>>
                                            ▼
SystemDocsRoutes（routes/SystemDocsRoutes.cpp）
  ├─ GET /api/docs/openapi.json ──▶ GetSwaggerJSON()  ← 唯一读出口
  └─ GET /api/docs             ──▶ 简易 Swagger UI 页（加载上面的 JSON）
```

写读分离清晰：除测试外没人直接摸 `paths_`；文档消费者只有 SystemDocsRoutes 一处。

## 3. 核心概念与设计

### 3.1 数据模型：path → operations

`paths_` 是 `map<path, vector<Operation>>`（Swagger.h:74）：同一路径的 GET/POST 各是一个 `Operation{method, summary, description, tags, parameters, responses}`（h:28-36）。`Parameter` 描述 name/in(query|path|header|cookie)/required/type（h:14-20）；`Response` 是 code + description + 可选 JSON schema（h:22-26）。全部加锁（mutex_），虽然实际写入只发生在启动阶段的单线程构造期。

### 3.2 与 SystemDocsRoutes 手写清单的"事实源"之争

服务里存在两份端点文档（SystemRoutes.md §3.4 已有结论，此处保持一致）：

- **Swagger 注册表**（本模块）：由各路由构造时的 RegisterEndpoint 喂入，openapi.json 由此生成，**与代码同步、是事实源**；
- **`GET /api/docs/endpoints` 的手写 JSON 清单**（SystemDocsRoutes.cpp:27-60 硬编码常量）：会过时（例如它列的 android/memory/filter/cases 端点并不全），**只能当历史参考**。

结论：任何"这个服务有哪些端点"的问题，以 `/api/docs/openapi.json` 为准。

### 3.3 Crow 路径 → OpenAPI 路径的启发式转换

Crow 用 `<string>/<int>` 占位，OpenAPI 用 `{param}`。`GetSwaggerJSON` 做机械替换：`<string>` → `{param}`、`<int>` → `{id}`（Swagger.cpp:52-62）。因此**同一资源的路径参数名在文档里不保真**——而 FilterRoutes 等新代码干脆注册时直接写 `{name}` 字面量（FilterRoutes.cpp:46），反而绕开了转换。两种风格并存是当前实际状态。

## 4. 工作流程走读

**注册**（Swagger.cpp:13-33）：各路由构造函数里逐个调用，例如搜索路由注册查询参数：

```cpp
Swagger::instance().RegisterEndpoint(
    "/api/search/fulltext", "GET",
    "Full-text search", "...", {"Search"},
    { {"q", "query", "Search query term", true},
      {"index", "query", "Index path", false},
      {"limit", "query", "Results limit", false, "integer"},
      {"offset", "query", "Pagination offset", false, "integer"} },
    {{200, "Search results"}, ...});
```

（摘自 SearchRoutes.cpp:41-53。）`q/index/limit/offset` 这些前端真正依赖的查询参数，唯一权威描述就在这里。

**渲染** `GetSwaggerJSON`（Swagger.cpp:35-108）：openapi=3.0.0，info 的 title/version 硬编码（"ForensicsProject C++ Service" / "1.0.0"，:40-44，与构建版本无联动）；遍历 paths_ 做路径转换、参数/响应序列化、method 转小写作为 operation key（:98-101）。

**出口**（SystemDocsRoutes.cpp:112 起）：`/api/docs/openapi.json` 返回渲染结果；`/api/docs` 返回内嵌的 HTML 页（加载该 JSON 渲染 UI）。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| SystemDocsRoutes | 唯一 HTTP 出口（openapi.json + UI 页）；它自己的手写 endpoints 清单是"次级、会过时"的那一份 |
| 所有路由类 | 写入方；在构造函数里 CROW_ROUTE 与 RegisterEndpoint 成对出现 |
| 前端/CI/Postman | 消费 openapi.json 做代码生成或导入；`jq '.paths | keys | length'` 可当端点数冒烟检查 |

## 6. 注意事项与已知问题

- **注册靠自觉**：没有机制强制每个 CROW_ROUTE 都配一次 RegisterEndpoint——漏注册的端点在 openapi.json 里缺席但依然可调用。审计新路由时对照"CROW_ROUTE 数 vs 注册数"。
- **无 requestBody 支持**：模型里只有 query/path 参数与响应 schema；POST body 的字段说明无处安放（POST /api/filter/apply 的 task_id/profile_name 就没进文档），OpenAPI 消费方看到的是无 body 定义的 POST。
- **版本/标题硬编码**："1.0.0" 与 SystemRoutes 的 version 常量各自为政，不会随构建更新。
- **路径参数名不保真**（§3.3）：`<string>` 一律显示为 `{param}`，与 FilterRoutes 的 `{name}` 风格混用。
- **启动后注册无意义**：单例在首次 `instance()` 时构造，路由全部在 HTTPServer 构造期注册完毕；运行期再 RegisterEndpoint 虽线程安全，但 openapi.json 端点每次请求都会看到（无快照语义）——目前没有这样的动态注册方。

## 7. 如何验证与扩展

- **验证**：`curl -s localhost:8080/api/docs/openapi.json | jq '.paths | keys[]' | wc -l` 与 RouteReference.md 对比；抽查 `.paths."/api/search/fulltext".get.parameters` 应含 q（required=true）。
- **扩展**：① 支持 requestBody——Operation 加 `nlohmann::json request_body` 字段并在渲染处输出，POST 路由逐步补；② 统一路径风格——新代码一律注册 `{name}` 字面量（向 FilterRoutes 看齐），旧 `<string>` 注册逐步迁移；③ 校验工具——写个小脚本 grep `CROW_ROUTE(` 与注册表比对，把"漏注册"变成 CI 可见。

**最后更新**: 2026-08-23（新建，解释式）
