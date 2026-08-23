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

## 10. 注册清单全表与覆盖率审计（二轮补全）

对全部 routes/*.cpp 做逐文件 `RegisterEndpoint` 统计（每处调用一条），并与该文件实际注册的 `CROW_ROUTE` 数对照，得到下面的覆盖率矩阵。**这是"openapi.json 里能看到什么"的权威答案**：

### 10.1 运行时真正生效的注册（44 条）

| 路由文件 | RegisterEndpoint 条数 / 路由条数 | 已注册端点 | 未注册（可调用但文档缺席） |
|---|---|---|---|
| TimelineRoutes.cpp | 7 / 11 | comprehensive、distribution、by-type、by-time-range、by-file、full、statistics-by-period | details、file-activity、suspicious-patterns、user-activity |
| TaskCRUDRoutes.cpp | 7 / 12 | GET/POST `/tasks`、GET `/tasks/{id}`、GET `/tasks/{id}/results`、DELETE `/api/tasks/{id}`、POST `/api/tasks/cleanup`、GET `/api/tasks/{id}/databases` | GET/POST `/api/tasks`、GET `/api/tasks/list`、GET `/api/tasks/{id}`（含 PUT）、GET `/api/tasks/{id}/results` |
| TaskBatchRoutes.cpp | 3 / 3 | batch-create、batch-status、batch-cancel | 无 |
| TaskMonitoringRoutes.cpp | 2 / 4 | GET `/api/tasks/statistics`、PUT `/api/tasks/{id}/priority` | **GET progress、GET audit-log**（前端最核心的轮询端点不在文档里） |
| AndroidForensicsRoutes.cpp | 7 / 14 | app-usage、miui-overview、miui-installed-apps、miui-db-inventory、llm-summary、miui-qqnt-overview、miui-wechat-overview | communication-summary、device-info、media-analysis、miui-qqnt-artifacts、miui-qqnt-records、miui-wechat-artifacts、miui-wechat-records |
| FilterRoutes.cpp | 5 / 5 | profiles GET/POST、profiles/{name} GET/DELETE、apply POST | 无 |
| EventClusterRoutes.cpp | 4 / 4 | clusters/{analyze,batch-analyze,reanalyze,analyzed} | 无 |
| ExportRoutes.cpp | 3 / 4 | export/events/{json,csv,visualization} | **export/toon** |
| SearchRoutes.cpp | 2 / 2 | fulltext、index | 无 |
| SystemEventRoutes.cpp | 2 / 2 | system/{events,summary} | 无 |
| FileAnalysisRoutes.cpp | 1 / 5 | files/largest | recent、suspicious、duplicates、extensions-analysis |
| FileExtractionRoutes.cpp | 1 / 3 | POST extract | GET extract/{job_id}、GET extract/status（前端轮询靠它） |

### 10.2 完全零注册的路由文件（活路由、零文档）

以下 8 个文件的端点**全部不在 openapi.json 中**，但运行时可调用：

| 路由文件 | 路由条数 | 缺席的端点族 |
|---|---|---|
| CaseCRUDRoutes.cpp | 6 | `/api/cases` 全族（前端 Cases 页在用） |
| DLLAnalysisRoutes.cpp | 7 | `/api/forensics/dlls` 全族 |
| MemoryForensicsRoutes.cpp | 5 | `/api/forensics/memory` 全族（Memory 页） |
| StatisticsRoutes.cpp | 4 | `/api/forensics/statistics` 全族（Statistics 页） |
| SceneQueryRoutes.cpp | 2 | `/api/tasks/{id}/{scene-stats,scene-artifacts}` |
| SystemHealthRoutes.cpp | 5 | `/api/system/health`、`/api/health*` 全族（**连健康检查都没进文档**） |
| SystemInfoRoutes.cpp | 5 | `/api/system/info`、`databases`、`database-schema/{name}`、`/api/export/{task_id}`、`logs` |
| SystemDocsRoutes.cpp | 4 | `/api/docs` 全族（文档端点自身不自描述） |

### 10.3 编写了注册但永不执行的 12 条（OSS 家族）

OSSAnalysisRoutes（6）、OSSStatsRoutes（4）、OSSQueryRoutes（2）各自写了完整的 RegisterEndpoint 调用，但它们唯一的构造入口 `OSSRoutes` 从未被 HTTPServer 实例化（见 HTTPServer.md §8.4）——**这 12 条注册与 404 端点一起沉睡**。推论：openapi.json 的实际 path 数是 44 条 Operation 对应的路径去重数，用 `jq '.paths | length'` 核对应以 §10.1 为基线，而不是全仓 route 总数（约 110）。

### 10.4 审计结论

"注册靠自觉"（§8）的实际缺口比想象大：44 生效 / 约 110 运行时端点 ≈ **40% 覆盖率**。前端高频依赖的 progress、extract/status、cases 全族、health 全族都不在文档里。把 §10.1/10.2 的清单变成补注册的工单即可机械地提升到 100%。

## 11. 渲染产物的字段级契约（数据契约细节）

`GetSwaggerJSON()` 的输出形状（以 `/api/search/fulltext` 为例，逐字段对应 Swagger.cpp:35-108 的渲染代码）：

| openapi.json 路径 | 来源字段 | 代码位置 | 备注 |
|---|---|---|---|
| `openapi` | 字面量 `"3.0.0"` | Swagger.cpp:39 | 恒定 |
| `info.title` | 字面量 `"ForensicsProject C++ Service"` | :41 | 与 SystemInfoRoutes 的服务名常量独立维护 |
| `info.version` | 字面量 `"1.0.0"` | :43 | 与构建版本无联动 |
| `paths.{p}.{m}.summary` | `Operation.summary` | :68 | 空串也会输出 |
| `paths.{p}.{m}.description` | `Operation.description` | :69 | 同上 |
| `paths.{p}.{m}.tags` | `Operation.tags`（vector→array） | :70 | 空时输出 `[]` |
| `paths.{p}.{m}.parameters[].{name,in,description,required}` | Parameter 四元组 | :75-78 | `in` 无枚举校验，写错值原样透传 |
| `paths.{p}.{m}.parameters[].schema.type` | `Parameter.type`（默认 "string"） | :79 | 无默认值/枚举支持 |
| `paths.{p}.{m}.responses.{code}.description` | `Response.description` | :86 | code 经 `std::to_string` 变字符串键 |
| `paths.{p}.{m}.responses.{code}.content` | `Response.schema` 非空时 | :87-93 | 仅 `application/json` 一种 media type |

缺失键（对照 OpenAPI 3.0 规范）：`servers`、`components`、`securitySchemes`、requestBody（模型层就没有）、`operationId`、`deprecated`。用 openapi-generator 之类的工具生成客户端时，这些缺失会导致生成的客户端没有鉴权与 body 类型。

## 12. 并发细节补充

- `mutex_` 是 `mutable std::mutex`（Swagger.h:73），`GetSwaggerJSON` 是 const 成员也要锁——读路径 `doc["paths"][openapi_path] = path_item`（Swagger.cpp:104）在锁内完成整棵 JSON 构造，44 条 Operation 的渲染是微秒级，锁不构成瓶颈。
- 写入全部发生在 HTTPServer 构造期（主线程、聚合器构造函数里），运行期唯一读者是 `/api/docs/openapi.json` 的 Crow worker 线程——**先写后读、无交错**，锁实际是防御性的。
- Meyers 单例（Swagger.cpp:6-9）保证跨翻译单元唯一；构造发生在第一个路由类构造时（TaskRoutes 最先），析构在 main 返回后、静态销毁阶段——与 Crow app 的生命周期无交叉。

## 13. tags 分布与参数统计（44 条注册的画像）

对 §10.1 的 44 条生效注册做标签统计（grep 各 RegisterEndpoint 的 tags 实参）：

| tag | 端点数 | 说明 |
|---|---|---|
| Tasks | 12 | CRUD 7 + batch 3 + statistics/priority 2 |
| Forensics, Timeline | 7 | 全部 TimelineRoutes |
| Forensics, Timeline, AI | 4 | EventCluster 四件套 |
| Forensics, Android | 7 | AndroidForensics 的已注册半 |
| Forensics, Export | 3 | events/{json,csv,visualization} |
| Filter | 5 | FilterRoutes 全量（唯一 100% 覆盖的路由组） |
| Search | 2 | 全量 |
| Forensics, OSS | 6+4+2=12 | **永不生效**（§10.3） |

高频参数（注册表里声明最多的）：`task_id`（query，required，27 次）、`limit`（5 次，integer）、`id`（path，5 次）、`start_time`（2 次，注意描述串不一致——一个写 "ISO" 一个没写，注册质量参差的缩影）。

**openapi.json 验证命令集**（可直接粘贴）：

```bash
curl -s localhost:8080/api/docs/openapi.json | jq '.openapi'                      # "3.0.0"
curl -s localhost:8080/api/docs/openapi.json | jq '.paths | keys | length'        # 生效路径数（按 §10.1 去重口径核对）
curl -s localhost:8080/api/docs/openapi.json | jq '[.paths | keys[] | select(startswith("/api/forensics/oss"))] | length'   # 0 —— OSS 永不出现（§12）
curl -s localhost:8080/api/docs/openapi.json | jq '.paths."/api/search/fulltext".get.parameters'
curl -s localhost:8080/api/docs/openapi.json | jq '[.paths[][].tags[]] | group_by(.) | map({tag: .[0], n: length}) | sort_by(-.n)'
```

## 14. 渲染输出的形状陷阱（消费方注意）

用 openapi.json 做代码生成/校验时四个已知陷阱（均可从 §11 的字段表推出，这里给结论）：

1. **路径参数名无意义**：`/api/tasks/{param}` 的参数名叫 {param}，与 parameters 里声明的 name（id/task_id）不一致——生成的客户端函数签名参数名会是 param；
2. **POST 无 requestBody**：所有 POST 端点在文档里都是"无 body 定义"——生成器会产出无参或可选 body 的客户端，调用方要自己读源码确认字段（本文档各 routes 篇的契约表就是为此存在）；
3. **responses 无 schema**：除了少数带 schema 的注册，绝大多数响应是纯 description——无法做响应类型校验；
4. **同名路径双注册覆盖**：`path_item[method_lower] = operation` 是赋值——若同一 (path, method) 注册两次，后注册的胜出（§8 已记，当前代码无此情形，扩展时留意）。

## 15. 补注册工单清单（按 §10 审计结论）

把覆盖率从 40% 提到 100% 的机械工作量：

| 优先级 | 目标 | 条数 | 理由 |
|---|---|---|---|
| P0 | TaskMonitoringRoutes 的 progress、audit-log | 2 | 前端最核心轮询端点不在文档 |
| P0 | CaseCRUDRoutes 全族 | 6 | Python 代理依赖的契约 |
| P1 | FileExtractionRoutes 的 status/{job_id}；ExportRoutes 的 toon | 2 | 轮询/导出 |
| P1 | FileAnalysisRoutes 余 4；AndroidForensics 余 7 | 11 | 页面在用 |
| P2 | DLL/Memory/Statistics/SceneQuery 四文件 | 18 | 页面在用 |
| P2 | SystemHealth/Info/Docs 三文件 | 14 | 自描述完整性 |
| （不做） | OSS 12 条 | — | 端点本身 404，注册无意义 |

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
