# TaskRoutes（src/network/HTTPServer/routes/TaskRoutes.cpp 及 TaskCRUDRoutes/TaskBatchRoutes/TaskMonitoringRoutes）

> **职责**：任务全生命周期的 REST 门面——创建/查询/删除/批量/监控五组端点，全部落在 TaskManager 单例上；`/tasks` 与 `/api/tasks` 双前缀并存，并为 16 个路径注册了 OPTIONS 预检。
> **端点全量清单**：见 [CPP_REST_API.md](../../../../api_reference/CPP_REST_API.md) 与 [RouteReference.md](./RouteReference.md)。

## 1. 这组路由承担什么

前端"任务页"的一切交互都从这里走：提交镜像开始分析、轮询进度与阶段、查看结果摘要、取消/删除、批量提交一批镜像。此外系统健康页（运行中任务数）与看板也间接消费这里的统计数据。这组路由是**唯一的任务写入口**——任务的创建、取消、删除语义都在 handler 里定型。

## 2. 典型调用方

- **/tasks 任务页（Tasks.jsx）**：创建表单（POST /api/tasks）、任务列表轮询（GET /api/tasks?status=...）、进度条（GET /api/tasks/{id}/progress）、删除按钮（DELETE /api/tasks/{id}）、批量操作（batch-create/batch-status/batch-cancel）。
- **Dashboard/健康检查**：GET /api/tasks/statistics。
- **脚本/CI**：常走 `/tasks` 短前缀（与 `/api/tasks` 完全等价，同一 handler）。

## 3. 端点分组与语义

### 3.1 组合结构

`TaskRoutes` 是纯聚合器：构造 TaskCRUDRoutes + TaskBatchRoutes + TaskMonitoringRoutes 三个子聚合器（TaskRoutes.cpp:9-18），自己只额外注册 **16 个 OPTIONS 预检路由**（TaskRoutes.cpp:20-134）——因为部分浏览器预检不命中通用 CORS 逻辑，这里逐路径兜底返回 204：

```cpp
// TaskRoutes.cpp:20-34（OPTIONS 注册样式，16 个同构中的前两个）
void TaskRoutes::register_cors_handlers(crow::App<>& app) {
    // CORS OPTIONS handlers for /tasks routes
    CROW_ROUTE(app, "/tasks").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        RouteHelpers::RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/tasks/<string>").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });
    // ...（/tasks/<string>/results、/api/tasks 全家、batch-*、audit-log、priority、databases）
```

每个预检 handler 都是同一模板：加 CORS 头 + 204 No Content。16 个路径 = `/tasks` 系 3 个 + `/api/tasks` 系 13 个（含 list/progress/statistics/cleanup/batch-*/audit-log/priority/databases）。第一个 handler 里 `RouteHelpers::RouteHelpers::add_cors_headers` 的双重限定是笔误式写法（C++ 注入类名规则让它恰好合法），其余 15 个都是正常的 `RouteHelpers::add_cors_headers`——行为一致，纯代码卫生问题。新只读端点上线时，这个清单要手动补一条，否则部分浏览器会把预检打向无 OPTIONS 的路由导致跨域失败。

### 3.2 创建任务（POST /tasks、POST /api/tasks）

核心在 `handle_create_task`（TaskCRUDRoutes.cpp:127-262）。请求体的字段解析段：

```cpp
// TaskCRUDRoutes.cpp:131-138、156-177（字段解析，节选）
auto body = json::parse(req.body);
std::string image_path = body["image_path"];

// Task priority
TaskPriority priority = TaskPriority::NORMAL;
if (body.contains("priority")) {
    priority = TaskHelpers::priority_from_string(body["priority"]);
}

// ...

// Forensic scenarios (multi-select)
std::vector<ForensicScenario> scenarios;
if (body.contains("scenarios")) {
    for (const auto& s : body["scenarios"]) {
        std::string val = s.get<std::string>();
        auto scenario = string_to_scenario(val);
        if (scenario.has_value()) {
            scenarios.push_back(scenario.value());
        }
    }
} else if (body.value("android_analyze", false)) {
    // Backward compat: old android_analyze flag
    scenarios = {ForensicScenario::ANDROID};
}

// XFS mode
XFSMode xfs_mode = XFSMode::Auto;
if (body.contains("xfs_mode")) {
    std::string mode_str = body["xfs_mode"];
    if (mode_str == "native") xfs_mode = XFSMode::Native;
    else if (mode_str == "pure") xfs_mode = XFSMode::Pure;
}
```

解析风格有明确的分层：必填字段 `body["image_path"]` 直接下标——缺失时 nlohmann 抛异常，被外层 catch 转成 400（:257-260）；可选字段一律 `contains()/value()` 给默认值；**非法值静默回落**——拼错的 scenario 字符串被 `string_to_scenario` 返回 nullopt 后丢弃（不报错），拼错的 xfs_mode 落到 Auto。这对客户端宽容但也会掩盖拼写错误（scenarios 数组全错 = 空数组 = 触发 SceneDetector 自动探测，行为反而合理）。

请求体语义（常用字段）：

- `image_path`（必填）：镜像/数据源路径；
- `priority`：**小写** low/normal/high/critical（TaskHelpers::priority_from_string，TaskHelpers.cpp:99-105）；
- `scenarios`：字符串数组 android/windows/linux/server_cloud（旧的 `android_analyze` 布尔仍兼容，:166-169）；
- `llm_analyze` + `llm_mode`（full|smart，默认 smart）、`case_description`；
- `filter_profile`（空则 TaskManager 默认 general_forensics）、`xfs_mode`（native|pure|auto）、`db_output_dir`；
- 解密：`enable_decryption`/`key_file_dir`（兼容旧拼写 key_dir，:192-194）/`decrypt_password`；
- Android 逻辑源：`android_source`（tsk|dir|zip|miui-backup）+ `backup_password`；
- `file_carving`（同时接受顶层与 `options.file_carving` 两种拼写，:203-209）;
- `metadata`（string→string 映射）、`dependencies`（task_id+required）。

流程是一次**原子创建**（全部参数一次进 create_task，TaskCRUDRoutes.cpp:211-230）→ 依赖满足则立刻 start_analysis（:233-235）→ 201 返回任务摘要。依赖未满足的任务停在 PENDING 等待。

### 3.3 查询与监控

- 列表 GET /tasks（status/priority 过滤 + limit/offset 分页，:394-461）；
- 详情 **GET 与 PUT /api/tasks/{id} 是同一个 handler**（TaskCRUDRoutes.cpp:85-87）——PUT 实为 GET 别名，不做任何更新；
- 进度 GET /api/tasks/{id}/progress（TaskMonitoringRoutes.cpp:46-80，返回阶段/阶段百分比/总百分比）；
- 审计 GET /api/tasks/{id}/audit-log（:98-139）；统计 GET /api/tasks/statistics（:82-96）；
- **PUT /api/tasks/{id}/priority 是 no-op**：解析新优先级后直接返回 success，注释直言 "This would need to be implemented in TaskManager / For now, return success"（TaskMonitoringRoutes.cpp:148-149）——前端显示"已更新"但实际什么都没变，排查优先级问题时别被它骗。

```cpp
// TaskMonitoringRoutes.cpp:141-157（no-op 全貌）
crow::response TaskMonitoringRoutes::handle_update_task_priority(const crow::request& req, const std::string& task_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        TaskPriority new_priority = TaskHelpers::priority_from_string(body["priority"]);

        // Note: This would need to be implemented in TaskManager
        // For now, return success
        json response = {
            {"success", true},
            {"task_id", task_id},
            {"new_priority", TaskHelpers::priority_to_string(new_priority)}
        };

        res.set_header("Content-Type", "application/json");
        res.write(response.dump());
    } catch (const std::exception& e) {
        // ...
    }
    return res;
}
```

handler 只做了"解析→回显"两步，`new_priority` 从未传给任何 TaskManager 方法（因为不存在这样的方法，见 TaskManager.md §8）；异常分支只回 400。注意它连任务是否存在都不查——对不存在的 task_id 调 PUT priority 也返回 success，加剧了误导。

进度端点的响应形态（TaskMonitoringRoutes.cpp:60-69）：`{task_id, status, progress{current_phase, phase_percentage, overall_percentage, phase_description}}`——phase 名是小写蛇形（TaskHelpers::phase_to_string），与 tasks.json 里的大写（TaskSerialization.cpp:24-32）又不同。

### 3.4 删除与清理

- DELETE /api/tasks/{id} 走 `handle_cancel_task`→`delete_task`（TaskCRUDRoutes.cpp:90-92、463-494）：内存移除 + tasks.json 落盘 + Python 侧清 Graphiti + 清 LLM 抽取临时目录 + 删任务目录（运行中的任务由工作线程退出时兜底删）；
- POST /api/tasks/cleanup 按小时数清理终态旧任务（:496-525），body 可选 `max_age_hours` 默认 24；注意 cleanup **只删内存记录**（TaskManager.cpp:449-467），磁盘目录要等下次重启的孤儿清理（TaskPersistence.cpp:74-99）才消失。

### 3.5 结果与批量

- GET /tasks/{id}/results（:294-392）：未完成返回 202；完成后带**缓存**返回，但缓存会做"LLM 证据再校验"——若 `_files.db` 在缓存生成后新写入了 file_descriptions（Python 案例分析或手动标注都可能写），缓存作废重建（:319-350）；`llm_results` 的判定**探测数据库而非看 llm_analyze 标志**（:360-375 注释解释了原因）。

```cpp
// TaskCRUDRoutes.cpp:325-350（缓存再校验，节选）
std::string cached_result = task_manager_.get_cached_result(task_id);
if (!cached_result.empty()) {
    try {
        json cached = json::parse(cached_result);
        const json& cached_descs = cached.value("llm_results",
            json::object()).value("descriptions", json::array());
        bool cache_has_evidence = cached_descs.is_array() && !cached_descs.empty();

        bool db_has_evidence = false;
        if (!task.output_files_db.empty()) {
            auto probe = SQLiteHelper::get_llm_results(task.output_files_db);
            const auto& descs = probe.contains("descriptions")
                ? probe["descriptions"] : json::array();
            db_has_evidence = descs.is_array() && !descs.empty();
        }

        if (cache_has_evidence || !db_has_evidence) {
            res.set_header("Content-Type", "application/json");
            res.write(cached_result);
            return res;
        }
        // Cache is stale (DB gained evidence) — rebuild below.
    } catch (...) {
        // Malformed cache — fall through to rebuild.
    }
}
```

判定矩阵：缓存有证据→直接用；缓存没有但库也没有→缓存仍新鲜，直接用；缓存没有而库有了→缓存过期，走下面的重建路径（重新 get_file_summary + get_llm_results + cache_result 落缓存）。注释（:360-365）解释了为什么探测库而不是看 `task.llm_analyze`：file_descriptions 有三个写入方（C++ 流水线、Python 案例分析服务 persist_to_files_db、手动标注 toggle），标志位无法反映后两者。代价是**每次命中缓存都要开一次 SQLite**——用一次廉价的探测换取证据列表永不过期。缓存 JSON 损坏时 catch-all 兜住并重建，缓存系统不会因坏数据卡死。

- 批量三件套 batch-create/batch-status/batch-cancel（TaskBatchRoutes.cpp:13-48）：create 是循环调 create_task 并逐个尝试启动（:50-79）。

## 4. 数据从哪来：任务字段 ↔ JSON 键的映射

- **任务列表/详情/进度/统计**：TaskManager 内存态（data/tasks.json 的运行时镜像）；详情 JSON 由 `TaskHelpers::task_to_json`（TaskHelpers.cpp:11-97）组装；
- **results 摘要与 LLM 证据**：`SQLiteHelper::get_file_summary` 与 `get_llm_results`（FileAnalysisQueries）直接查任务的 `_files.db`；
- **databases 端点**：AnalysisTask 上的 output_*_db 字段。
- 产出库路径解析统一走 `RouteHelpers::get_database_path`。

`task_to_json` 是"内存结构→API 形态"的唯一映射点，关键字段对照：

| AnalysisTask 字段 | API JSON 键 | 转换 |
|---|---|---|
| status | `status` | 小写化（TaskHelpers.cpp:117-126） |
| progress.current_phase | `progress.current_phase` | 蛇形小写（:128-140） |
| progress.overall_percentage | `progress.overall_percentage` | 直传 |
| scenarios | `scenarios` + `android_analyze`（兼容旧字段） | scenario_to_string；`get_android_analyze()` 计算属性 |
| created/started/completed_time | `timestamps.{created,started,completed,execution_time_seconds}` | 毫秒时间戳；耗时只在终态计算 |
| —（不来自 task 字段） | `scenario_databases` | 现场查 PathManager 路径 + exists() 过滤（:33-49） |
| — | `extraction_directory` | PathManager::getTaskExtractDir 现算 |
| cancellation_requested | `cancellation_requested` | atomic load |
| error_details / metadata / dependencies | 同名键 | 直传/逐项展开 |

`scenario_databases` 是唯一"响应里带现场文件系统探测"的字段——列表页每行都要做 N 次 exists()，任务多时是隐性开销。

## 5. 常见错误与边界

- **状态值大小写**：API 返回小写（pending/running/completed/failed/cancelled，TaskHelpers.cpp:117-126）；`?status=RUNNING` 过滤会得到空列表。tasks.json 里则是大写，两套别混。
- **路径碰撞守卫**：GET /api/tasks/{id} 拦截 `list/statistics/cleanup/batch-*` 等保留字（TaskCRUDRoutes.cpp:269-276），否则它们会被 `<string>` 通配吃掉。守卫返回 404 `{"error":"Task not found"}` 而非转发到真正的端点——`GET /api/tasks/list` 能正常工作靠的是它自己的静态路由（:73-75）先被匹配，守卫是 handler 层的第二道防线（防保留字被当任务 ID 处理；真实任务 ID 是 UUID，撞名实际不可能，属防御性编程）。
- **PUT 的两种"假"**：PUT /{id} 是只读别名、PUT /{id}/priority 是 no-op——客户端不要依赖 PUT 语义。
- **创建请求缺 image_path**：json 解析直接抛异常 → 400 "Invalid request"（:257-260），错误信息较粗糙（只带 nlohmann 的异常文本，不会指明缺哪个字段）。
- **批量创建无部分失败语义**：一批路径中某个路径非法不影响其他，返回的 task_ids 数组可能少于输入（create_task 从不失败，但非法路径要到 start_analysis 才 FAILED——所以 task_ids 其实总是等长，"部分失败"表现为部分任务秒变 FAILED）。
- **limit 解析无钳制**：列表端点 `std::stoi(req.url_params.get("limit"))`（:409-411）没有 clamp，传 `limit=0` 会让分页切片为空——与 ForensicsRoutes 的 clamp_limit 纪律不一致。

## 6. 如何验证与扩展

- curl 冒烟：`POST /api/tasks`（最小 body `{"image_path":"..."}`）→ 轮询 progress → completed 后 GET results → DELETE 后 GET 应 404。
- 扩展：新任务字段在 handle_create_task 解析 → 传入 create_task（TaskManager.cpp:73-89 的参数表已很长，考虑改用 struct）；新只读监控端点放 TaskMonitoringRoutes 并在 TaskRoutes.cpp:20-134 补对应 OPTIONS 预检 + Swagger RegisterEndpoint（成对出现，见 Swagger.md §7）。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
