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

## 3. 核心数据模型

```cpp
// Swagger.h:12-35
class Swagger {
public:
    struct Parameter {
        std::string name;
        std::string in; // query, path, header, cookie
        std::string description;
        bool required = false;
        std::string type = "string";
    };

    struct Response {
        int code;
        std::string description;
        nlohmann::json schema; // Optional schema
    };

    struct Operation {
        std::string method;
        std::string summary;
        std::string description;
        std::vector<std::string> tags;
        std::vector<Parameter> parameters;
        std::vector<Response> responses;
    };

    static Swagger& instance();
    // ...
private:
    mutable std::mutex mutex_;
    std::map<std::string, std::vector<Operation>> paths_;
};
```

数据模型的形状决定了文档的能力边界：

- `paths_` 是 **path → Operation 向量**：同一路径的 GET/POST 各占一个 Operation，注册顺序即向量顺序（先注册的先渲染）；
- `Parameter.type` 默认 "string"，OpenAPI 渲染时直接变成 `schema: {type: ...}`——参数类型是**声明式**的，没有从 handler 代码反推类型的机制；
- `Response.schema` 可选，绝大多数注册只给 code+description；
- **没有 requestBody 字段**——这是"POST body 字段无处安放"问题的结构性根源（§6）；
- `mutex_` 全程加锁（读渲染也锁），虽然写入只发生在启动阶段的单线程构造期。

## 4. 核心接口

| 方法 | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `instance()`（Swagger.cpp:6-9） | Meyers 单例，首次调用构造 | 所有路由类构造函数 | 无 |
| `RegisterEndpoint(path, method, summary, description, tags, parameters, responses)`（h:49-57） | 追加一条 Operation 到 paths_[path] | 各路由构造函数（唯一写入口） | 无返回值；同一路径方法重复注册会得到重复条目，无去重 |
| `GetSwaggerJSON()`（h:63，实现 cpp:35-108） | 渲染 OpenAPI 3.0 文档 | SystemDocsRoutes::handle_docs_openapi（SystemDocsRoutes.cpp:115-130） | 纯内存操作不抛错 |

注册与渲染的实现：

```cpp
// Swagger.cpp:13-33
void Swagger::RegisterEndpoint(
    const std::string& path,
    const std::string& method,
    const std::string& summary,
    const std::string& description,
    const std::vector<std::string>& tags,
    const std::vector<Parameter>& parameters,
    const std::vector<Response>& responses
) {
    std::lock_guard<std::mutex> lock(mutex_);

    Operation op;
    op.method = method;
    op.summary = summary;
    op.description = description;
    op.tags = tags;
    op.parameters = parameters;
    op.responses = responses;

    paths_[path].push_back(op);
}
```

注意 `paths_[path]` 的语义：`operator[]` 会在键不存在时默认构造空向量再 push_back——新路径自动建条目，无需预注册。参数列表是**按值**复制进 Operation（vector 整体拷贝），注册发生在构造期、量级几十次，性能无关紧要。每个参数是一个 brace-init 列表 `{name, in, description, required}`（五元时再加 type），按 Parameter 字段声明序对应——这也是为什么各注册点的参数字面量有固定的四段式形态。

## 5. 核心概念与设计

### 5.1 与 SystemDocsRoutes 手写清单的"事实源"之争

服务里存在两份端点文档（SystemRoutes.md §3.4 已有结论，此处保持一致）：

- **Swagger 注册表**（本模块）：由各路由构造时的 RegisterEndpoint 喂入，openapi.json 由此生成，**与代码同步、是事实源**；
- **`GET /api/docs/endpoints` 的手写 JSON 清单**（SystemDocsRoutes.cpp:27-60 硬编码常量）：会过时（例如它列的 android/memory/filter/cases 端点并不全），**只能当历史参考**。

结论：任何"这个服务有哪些端点"的问题，以 `/api/docs/openapi.json` 为准。

### 5.2 Crow 路径 → OpenAPI 路径的启发式转换

Crow 用 `<string>/<int>` 占位，OpenAPI 用 `{param}`。`GetSwaggerJSON` 做机械替换：

```cpp
// Swagger.cpp:47-62（渲染循环开头，节选）
for (const auto& [path, operations] : paths_) {
    // Convert Crow path syntax to OpenAPI syntax if needed (e.g., /api/extract/<string> -> /api/extract/{job_id})
    // Simple heuristic: replace <string>, <int> etc with {}

    std::string openapi_path = path;
    size_t pos = 0;
    while ((pos = openapi_path.find("<string>", pos)) != std::string::npos) {
        openapi_path.replace(pos, 8, "{param}");
        pos += 7;
    }
    pos = 0;
    while ((pos = openapi_path.find("<int>", pos)) != std::string::npos) {
        openapi_path.replace(pos, 5, "{id}");
        pos += 4;
    }
```

替换后 `pos += 7`（而非 8）是有意为之：跳回一个字符让连续的 `<string><string>` 不会被漏检——replace 后新串在 pos..pos+6 位置，下一次 find 从 pos+7 起仍能命中紧随其后的下一个占位符。因此**同一资源的路径参数名在文档里不保真**——`<string>` 一律变 `{param}`、`<int>` 一律变 `{id}`，与注册时 Parameter 里写的参数名（通常叫 task_id/job_id）对不上号。FilterRoutes 等新代码干脆注册时直接写 `{name}` 字面量（FilterRoutes.cpp:46），反而绕开了转换。两种风格并存是当前实际状态。

### 5.3 渲染：method 转小写作为 operation key

```cpp
// Swagger.cpp:83-101（响应/方法序列化，节选）
operation["responses"] = nlohmann::json::object();
for (const auto& resp : op.responses) {
    nlohmann::json r;
    r["description"] = resp.description;
    if (!resp.schema.is_null()) {
        r["content"] = {
            {"application/json", {
                {"schema", resp.schema}
            }}
        };
    }
    operation["responses"][std::to_string(resp.code)] = r;
}

// Convert method to lowercase
std::string method_lower = op.method;
std::transform(method_lower.begin(), method_lower.end(), method_lower.begin(), ::tolower);

path_item[method_lower] = operation;
```

OpenAPI 规范要求 responses 以**字符串状态码**为键（"200" 而非 200）、operation 以小写 HTTP 方法为键——这两处转换正是为合规。响应 schema 只在非 null 时输出 content 包装，没有 schema 的响应就是纯 description（所以 Swagger UI 里多数端点的 Response Model 显示为空）。

## 6. 注册条目样例与工作流程

**注册**（各路由构造函数里逐个调用），例如搜索路由注册查询参数（SearchRoutes.cpp:41-53）：

```cpp
Swagger::instance().RegisterEndpoint(
    "/api/search/fulltext", "GET",
    "Full-text search", "Search for text content across analyzed files.", {"Search"},
    {
        {"q", "query", "Search query term", true},
        {"index", "query", "Index path", false},
        {"limit", "query", "Results limit", false, "integer"},
        {"offset", "query", "Pagination offset", false, "integer"}
    },
    {{200, "Search results"}, {400, "Missing query or parameters"}, {500, "Internal server error"}}
);
```

`q/index/limit/offset` 这些前端真正依赖的查询参数，唯一权威描述就在这里。四个参数字面量按 `{name, in, description, required[, type]}` 对应 Parameter 字段序——`limit` 带第五段 "integer"，其余默认 string。渲染后的形态（可对照 openapi.json）：

```json
"/api/search/fulltext": {
  "get": {
    "summary": "Full-text search",
    "tags": ["Search"],
    "parameters": [
      {"name": "q", "in": "query", "description": "Search query term",
       "required": true, "schema": {"type": "string"}}, ...
    ],
    "responses": {"200": {"description": "Search results"}, ...}
  }
}
```

**渲染** `GetSwaggerJSON`（Swagger.cpp:35-108）：openapi=3.0.0，info 的 title/version 硬编码（"ForensicsProject C++ Service" / "1.0.0"，:40-44，与构建版本无联动）；遍历 paths_ 做路径转换、参数/响应序列化、method 转小写。

**出口**（SystemDocsRoutes.cpp:112 起）：`/api/docs/openapi.json` 返回 `openapi.dump(2)`（带缩进，便于人读）；`/api/docs` 返回内嵌 HTML 页（SystemDocsRoutes.cpp:136-163），从 unpkg CDN 拉 Swagger UI 5.11.0 并指向同源 openapi.json 渲染——离线环境下该页会因 CDN 不可达而白屏，但 openapi.json 端点不受影响。

## 7. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| SystemDocsRoutes | 唯一 HTTP 出口（openapi.json + UI 页）；它自己的手写 endpoints 清单是"次级、会过时"的那一份 |
| 所有路由类 | 写入方；在构造函数里 CROW_ROUTE 与 RegisterEndpoint 成对出现 |
| 前端/CI/Postman | 消费 openapi.json 做代码生成或导入；`jq '.paths | keys | length'` 可当端点数冒烟检查 |

成对出现的实例（TaskCRUDRoutes.cpp:15-30）：`CROW_ROUTE(app, "/tasks").methods("GET"_method)` 之后紧跟 RegisterEndpoint("/tasks", "GET", ...)——两段代码之间没有任何机制约束，全靠 review 保证同步。

## 8. 注意事项与已知问题

- **注册靠自觉**：没有机制强制每个 CROW_ROUTE 都配一次 RegisterEndpoint——漏注册的端点在 openapi.json 里缺席但依然可调用。审计新路由时对照"CROW_ROUTE 数 vs 注册数"。
- **无 requestBody 支持**：模型里只有 query/path 参数与响应 schema；POST body 的字段说明无处安放（POST /api/filter/apply 的 task_id/profile_name、POST /api/tasks 的整个请求体都没进文档），OpenAPI 消费方看到的是无 body 定义的 POST。
- **版本/标题硬编码**："1.0.0" 与 SystemRoutes 的 version 常量各自为政，不会随构建更新。
- **路径参数名不保真**（§5.2）：`<string>` 一律显示为 `{param}`，与 FilterRoutes 的 `{name}` 风格混用。
- **启动后注册无意义**：单例在首次 `instance()` 时构造，路由全部在 HTTPServer 构造期注册完毕；运行期再 RegisterEndpoint 虽线程安全，但 openapi.json 端点每次请求都会看到（无快照语义）——目前没有这样的动态注册方。
- **无去重**：同一 (path, method) 被注册两次会在 vector 里出现两条 Operation，渲染时后者覆盖前者（`path_item[method_lower] = operation` 是赋值），前者静默丢失——目前代码没有这种情况，但扩展时要留意。

## 9. 如何验证与扩展

- **验证**：`curl -s localhost:8080/api/docs/openapi.json | jq '.paths | keys[]' | wc -l` 与 RouteReference.md 对比；抽查 `.paths."/api/search/fulltext".get.parameters` 应含 q（required=true）。
- **扩展**：① 支持 requestBody——Operation 加 `nlohmann::json request_body` 字段并在渲染处输出，POST 路由逐步补；② 统一路径风格——新代码一律注册 `{name}` 字面量（向 FilterRoutes 看齐），旧 `<string>` 注册逐步迁移；③ 校验工具——写个小脚本 grep `CROW_ROUTE(` 与注册表比对，把"漏注册"变成 CI 可见。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
