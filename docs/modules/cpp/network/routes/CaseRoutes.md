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

Python 代理层的转发代码（以建案为例）：

```python
# python_service/httpserver/routes/multi_analysis.py:98-115
@router.post("/api/llm/cases", status_code=201)
async def create_case(
    req: CreateCaseRequest,
    settings: Settings = Depends(get_settings),
    raw_request: Request = None,
):
    """Create a ForensicCase via C++ backend and return the new case object."""
    try:
        logger.info(f"[CREATE_CASE] Received request: name={req.name}, description={req.description}, task_ids={req.task_ids}")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{settings.cpp_backend_url}/api/cases",
                json=req.model_dump(),
            )
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()
```

前端**从不直连** C++ 的 `/api/cases`（web/src 全量检索无命中）——Python 的 multi_analysis 路由是它的唯一线上调用方，同时负责附加能力（associate-tasks 预热复用状态、multi-image-analysis 编排）。联调抓包时要在 Python 侧或 C++ 侧分别看，别只盯浏览器请求。

## 3. 路由注册面

六个端点在构造函数里一次性挂完：

```cpp
// src/network/HTTPServer/routes/CaseCRUDRoutes.cpp:10-40（节选）
CaseCRUDRoutes::CaseCRUDRoutes(crow::App<>& app)
    : case_manager_(CaseManager::instance()) {

    CROW_ROUTE(app, "/api/cases").methods("GET"_method)([this](const crow::request& req) {
        return handle_list_cases(req);
    });

    CROW_ROUTE(app, "/api/cases").methods("POST"_method)([this](const crow::request& req) {
        return handle_create_case(req);
    });

    CROW_ROUTE(app, "/api/cases/<string>").methods("GET"_method)(
        [this](const crow::request& req, const std::string& id) {
            return handle_get_case(req, id);
        });

    CROW_ROUTE(app, "/api/cases/<string>/tasks").methods("PUT"_method)(
        [this](const crow::request& req, const std::string& id) {
            return handle_add_tasks(req, id);
        });

    CROW_ROUTE(app, "/api/cases/<string>").methods("DELETE"_method)(
        [this](const crow::request& req, const std::string& id) {
            return handle_delete_case(req, id);
        });

    CROW_ROUTE(app, "/api/cases/<string>/status").methods("PUT"_method)(
        [this](const crow::request& req, const std::string& id) {
            return handle_update_status(req, id);
        });
}
```

两个形状事实：① `case_manager_` 是**引用成员**绑定单例（构造即 `CaseManager::instance()`），本组不自持状态；② **没有通用的 `PUT /api/cases/<string>`**——改 name/description 无处可去（§6）。

## 4. 端点分组与语义

**案件本体**：

- `GET /api/cases`：全量列表 + total（:44-54）；
- `POST /api/cases`：body `{name, description, task_ids[]}`，缺省 name 为 "Unnamed Case"（:61-66）；成功 201 返回完整案件 JSON；
- `GET /api/cases/{id}`：查不到（fc.id 为空判据）→ 404（:79-92）；
- `DELETE /api/cases/{id}`：只删案件记录，**不级联任务**（CaseManager.delete_case 只擦 map，见 CaseManager.md §3.4）→ 200。

**子资源（注意都是 PUT，没有通用的 PUT /api/cases/{id}）**：

- `PUT /api/cases/{id}/tasks`：body 必须含 `task_ids` 数组，逐个 `add_task`（去重）后返回最新案件（:94-114）；
- `PUT /api/cases/{id}/status`：**双职责**端点，实现值得细看：

```cpp
// src/network/HTTPServer/routes/CaseCRUDRoutes.cpp:131-154（节选）
auto body = json::parse(req.body);
if (body.contains("status")) {
    std::string s = body["status"];
    CaseStatus cs = CaseStatus::OPEN;
    if (s == "analysing") cs = CaseStatus::ANALYSING;
    else if (s == "completed") cs = CaseStatus::COMPLETED;
    else if (s == "failed")    cs = CaseStatus::FAILED;
    case_manager_.update_status(case_id, cs);
}
if (body.contains("cross_analysis_job_id")) {
    case_manager_.set_cross_analysis_job(case_id, body["cross_analysis_job_id"]);
}
res.set_header("Content-Type", "application/json");
res.write(case_to_json(case_manager_.get_case(case_id)).dump());
```

`status` 字符串（小写 open/analysing/completed/failed）走 `update_status`，`cross_analysis_job_id` 走 `set_cross_analysis_job`，两者可同时出现——跨镜像分析的 job id 回填就走这里（Python 编排完成后转发，multi_analysis.py:271 构造 `{"status": "analysing", "cross_analysis_job_id": job_id}`）。两个隐患都在这段里：**未知 status 静默落为 OPEN**（if-else 链没有 else 分支报错，拼错 "analyzing" 会得到 "open" 而非 400）；**案件不存在时 update/set 静默 no-op**，末尾 get_case 返回空对象照常序列化成 200——PUT 一个不存在的 id 得不到 404。

**序列化约定**（case_to_json，:158-173）：

```cpp
// src/network/HTTPServer/routes/CaseCRUDRoutes.cpp:158-173
json CaseCRUDRoutes::case_to_json(const ForensicCase& fc) const {
    auto epoch_ms = [](auto tp) {
        return std::chrono::duration_cast<std::chrono::milliseconds>(
            tp.time_since_epoch()).count();
    };
    return {
        {"id",                    fc.id},
        {"name",                  fc.name},
        {"description",           fc.description},
        {"task_ids",              fc.task_ids},
        {"status",                status_to_string(fc.status)},
        {"cross_analysis_job_id", fc.cross_analysis_job_id},
        {"created_at",            epoch_ms(fc.created_at)},
        {"updated_at",            epoch_ms(fc.updated_at)},
    };
}
```

status 全小写字符串；created_at/updated_at 为毫秒 epoch——与 tasks.json 里大写的任务状态并存，脚本处理时逐处确认（与 CaseManager.md §7 的提醒一致）。注意 REST 层**不回显** case_db_path/total_files_analyzed/task_analysis_states——这三个增量字段只在 cases.json 落盘，线上 API 看不见它们。

## 5. 数据从哪来

- 全部读写经 `CaseManager::instance()`（构造时注入成员，:11）——内存 map + 每次变更全量 dump `data/cases.json`；
- **不查任何任务的 SQLite 库**：task_ids 是纯字符串引用，任务详情由前端另行调任务接口；
- 跨镜像分析本体不在本组：C++ 只保管 job id，分析在 Python 侧执行。

## 6. 常见错误与边界

- **悬空 task_id**：删任务不会摘除案件里的引用（也不归这组路由管）；GET 案件返回的 task_ids 可能含有已删除任务，前端渲染要容忍任务 404。
- **没有通用的 PUT /api/cases/{id}**：想改 name/description 没有端点（CaseManager 也无对应方法）——只能删了重建；别按 REST 直觉发 PUT。
- **status 值校验宽松**：未知字符串静默落为 OPEN（§4 的 if-else 链），拼错 "analyzing"（单 l）会得到 "open" 而非 400。
- **PUT 到不存在的案件返回 200 空对象**：update_status/set_cross_analysis_job 对不存在 id 静默 no-op，get_case 返回空 ForensicCase 后 case_to_json 照常序列化（:144-148）——与 GET/DELETE 的 404 行为不一致。
- **错误响应形状不统一**：本组用 `{error: …}`（:74、86），没有 FilterRoutes 那种 ApiResponse 封装——跨路由写客户端时注意。
- **代理链路上的 404 语义叠加**：Python 代理转发 C++ 的 404 时可能再包一层自己的错误体（multi_analysis.py 的 HTTPException detail=r.text）；排查"案件不存在"要区分是 Python 侧找不到还是 C++ 侧 404。
- **非原子持久化**（继承自 CaseManager）：写 cases.json 中途崩溃会损坏文件，解析失败时全部案件丢失——路由层无感知。

## 7. 如何验证与扩展

- 冒烟（直接打 C++）：`curl -X POST :8080/api/cases -d '{"name":"t","task_ids":["<id>"]}'` → `curl :8080/api/cases` → `curl -X PUT :8080/api/cases/<id>/status -d '{"status":"analysing","cross_analysis_job_id":"job-1"}'` → `cat data/cases.json` 核对落盘 → `curl -X DELETE` 后确认任务本身仍在（不级联）。
- 扩展：新案件字段改 CaseManager 的 save/load 与本文件 case_to_json（:158-173）三处同步（注意增量字段目前连 REST 都不回显，加了要考虑是否暴露）；新增端点沿用"handler → CaseManager 方法 → case_to_json"三段式；若要给案件加派生统计（如完成度），在路由层算，别把派生值落盘（与 CaseManager.md §8 建议一致）。

## 8. 端点全表（6 个，二轮补全）

| 端点 | 方法 | 请求 | 成功 | 失败 | 源码 |
|---|---|---|---|---|---|
| /api/cases | GET | — | 200 `{cases:[case...], total}`（恒 200） | 无 | CaseCRUDRoutes.cpp:44-54 |
| /api/cases | POST | `{name="Unnamed Case", description="", task_ids[]（非数组则忽略）}` | 201 case JSON | 400 `{error}` | :56-77 |
| /api/cases/{id} | GET | — | 200 case JSON | 404 `{error:"Case not found", case_id}` | :79-92 |
| /api/cases/{id}/tasks | PUT | `{task_ids[]}`（必填数组） | 200 case JSON（追加后） | 400（缺数组/JSON 坏）；**案件不存在也是 200 空对象** | :94-114 |
| /api/cases/{id} | DELETE | — | 200 `{success:true, message:"Case deleted"}` | 404 | :116-129 |
| /api/cases/{id}/status | PUT | `{status?, cross_analysis_job_id?}`（至少其一有意义；都缺也 200 原样返回） | 200 case JSON | 400（JSON 坏） | :131-154 |

case JSON 8 键（:158-173）：id、name、description、task_ids[]、status（小写）、cross_analysis_job_id、created_at、updated_at（毫秒）。**不含**增量三字段（case_db_path/total_files_analyzed/task_analysis_states——只落盘不出网，CaseManager.md §9 已记契约缺口）。

## 9. 新走读分支：Python 代理的调用全景（谁在什么时候打这 6 个端点）

grep `cpp_backend_url}/api/cases` 的全部命中（python_service），按业务流排列：

| Python 端点/函数 | 调用的 C++ 端点 | 业务时机 | 源码 |
|---|---|---|---|
| POST /api/llm/cases | POST /api/cases | 前端建案 | multi_analysis.py:109 |
| GET /api/llm/cases | GET /api/cases | 前端列案 | :127 |
| GET /api/llm/cases/{id} | GET /api/cases/{id} | 前端案件详情 | :137 |
| DELETE /api/llm/cases/{id} | DELETE /api/cases/{id} | 前端删案 | :150 |
| PUT /api/llm/cases/{id}/tasks（含 associate 复用预热） | PUT /api/cases/{id}/tasks | 挂任务/预热分析态 | :172、:380 |
| multi-image-analysis 启动 | PUT /api/cases/{id}/status（status=analysing + job_id） | 跨镜像分析开始 | :270 |
| 分析完成/失败回写 | PUT /api/cases/{id}/status（completed/failed） | 作业终态 | :294、:303 |
| CaseAggregationManager | PUT tasks ×2、DELETE、GET | 聚合流程 | case_aggregation_manager.py:162/226/287 |
| 分析管线建案 | POST /api/cases | _pipelines | _pipelines.py:546 |

三层结构的风险点：**每次代理调用都是独立 httpx.AsyncClient(timeout=10)**（:107 附近）——C++ 端 CaseManager 锁内做 JSON 落盘时若超过 10s（案件极多时），Python 侧超时报错但 C++ 侧实际已写成功，出现"Python 报错但重试发现已存在"的语义分叉。PUT tasks 的逐条加锁（CaseManager.md §10.2）让这个窗口随 task_ids 数量线性放大。

## 10. 配置影响表（CaseRoutes 视角）

| 配置 | 默认 | 消费点 | 说明 |
|---|---|---|---|
| `CPP_BACKEND_URL` | http://localhost:8080 | multi_analysis.py 的代理基址 | 配错时 Python 案件 API 整体失败（表现为前端 /cases 页报错） |
| `DATA_DIR` | data | cases.json 路径 | CaseManager 侧 |
| `HTTP_SERVER_PORT` | 8080（run.sh 回退 8666 漂移） | 代理目标的实际端口 | 与 CPP_BACKEND_URL 必须一致——run.sh 的 8666 漂移在这里咬人：CPP_BACKEND_URL 默认 8080 而 run.sh 起在 8666 时案件域全断 |
| （本组无直接 env） | — | — | handler 不读任何环境变量 |

## 11. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 |
|---|---|---|
| 被调 | multi_analysis.py（6 端点 9 处调用） | §9 全表 |
| 被调 | case_aggregation_manager.py（3 处） | 聚合流程 |
| 被调 | _pipelines.py:546 | 建案 |
| 不被前端直调 | web/src | 零引用（§2 已记） |
| 调用 | CaseManager::instance()（构造注入引用成员） | 全部 handler |
| 挂载 | HTTPServer 构造列表第 5 位 | HTTPserver.cpp:71 |
| Swagger 注册 | **0 条**（CaseCRUDRoutes 无 RegisterEndpoint） | openapi.json 盲区 |
| 间接 | TaskManager | 无直接调用（task_id 纯字符串） |

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
