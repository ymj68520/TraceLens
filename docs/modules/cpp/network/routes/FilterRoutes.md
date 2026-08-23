# FilterRoutes（src/network/HTTPServer/routes/FilterRoutes.cpp）

> **职责**：文件过滤画像的 REST 管理面——列出/查看/创建/删除 `config/filter_profiles/` 下的 JSON 画像，以及手动把某画像应用到某个任务的 raw.db（`POST /api/filter/apply`）。
> **端点全量清单**：见 [CPP_REST_API.md](../../../../api_reference/CPP_REST_API.md) 与 [RouteReference.md](./RouteReference.md)。
> **特殊性**：这组路由是**全服务唯一**使用统一 `ApiResponse` 封装（`{success, message, data, timestamp, pagination, error_code}`）的路由——响应形状与其它所有路由不同。

## 1. 这组路由承担什么

[FileFilter](../../../cpp/core/FileFilter.md) 的画像原本只能靠改文件；本组路由把它变成可运营能力：前端"过滤画像编辑器"（web/src/components/filters/FilterProfileEditor.jsx、ScenarioPicker 等，经 redux filterSlice → services/filterService.js）可以列内置画像、查看规则细节、保存自定义画像、删除自定义画像；`/api/filter/apply` 则提供"对已完成任务的 raw.db 重放一个画像"的手动入口。

## 2. 典型调用方

- **前端过滤组件**：`web/src/services/filterService.js` 封装了全部 5 个端点（fetchFilterProfiles / fetchFilterProfileDetail / createFilterProfile / deleteFilterProfile / applyFilter），消费方是任务创建流程里的画像/场景选择组件（components/filters/*）；
- **脚本/运维**：画像即 JSON 文件，REST 与手工编辑等效——CI 里可以用 POST 固化标准画像。

## 3. 端点分组与语义

### 3.1 画像 CRUD（4 条）

- `GET /api/filter/profiles`：枚举目录内 .json（FileFilter::listProfiles，坏画像跳过），返回 `{filename, name, description}[]` + count（FilterRoutes.cpp:98-133）；
- `GET /api/filter/profiles/{name}`：读单画像，回显 include/exclude 条件与 combine_mode（:139-180）；
- `POST /api/filter/profiles`：upsert 语义——文件已存在则 200 "Profile updated"，否则 201 "Profile created"（:245-312 的 is_update 分支）；服务端重建完整画像 JSON（缺省值兜底）后 pretty-dump 落盘；
- `DELETE /api/filter/profiles/{name}`：删文件；内置画像拒绝删除（403 FORBIDDEN）。

**内置画像保护**：`general_forensics / telecom_fraud / data_breach / virus_intrusion` 四个名字在 POST（覆盖，:225-239）与 DELETE（:365-379）两处硬编码拒绝——它们是流水线默认值的依赖（AnalysisOrchestrator 默认 general_forensics），被删/被改坏会伤及所有未指定画像的任务。

**路径安全闸**（所有接受名字的端点都先过这道）：

```cpp
// src/network/HTTPServer/routes/FilterRoutes.cpp:16-24
// Path traversal guard — rejects names containing directory separators or traversal sequences
static bool isValidProfileName(const std::string& name) {
    if (name.empty()) return false;
    if (name.find("..") != std::string::npos) return false;
    if (name.find('/') != std::string::npos) return false;
    if (name.find('\\') != std::string::npos) return false;
    if (name.find('\0') != std::string::npos) return false;
    return true;
}
```

拒绝空名、`..`、`/`、`\`、NUL——防目录穿越读/写任意文件。名字最终拼进 `profilesDir + "/" + name + ".json"`（:161、:245、:355），没有这道闸 `../../data/tasks` 之类的名字就能越界。

### 3.2 手动应用（1 条）

`POST /api/filter/apply`（:398-440）的判定链（节选）：

```cpp
// src/network/HTTPServer/routes/FilterRoutes.cpp:432-474（节选）
// Get task's raw.db path
auto& taskMgr = TaskManager::instance();
auto task = taskMgr.get_task(task_id);
if (task.id.empty()) {
    auto resp = ApiResponse::create_error("Task not found: " + task_id, "NOT_FOUND");
    res.code = 404;
    // ...
}

std::string rawDbPath = task.output_raw_db;
if (rawDbPath.empty() || !fs::exists(rawDbPath)) {
    auto resp = ApiResponse::create_error("Raw database not found for task: " + task_id, "DB_NOT_FOUND");
    res.code = 404;
    // ...
}

// Generate filtered db path
std::string filteredDbPath = rawDbPath;
// Replace _raw.db with _filtered.db
size_t pos = filteredDbPath.rfind("_raw.db");
if (pos != std::string::npos) {
    filteredDbPath.replace(pos, 7, "_filtered.db");
} else {
    filteredDbPath += ".filtered";
}

FileFilter filter;
auto stats = filter.applyFilterByName(rawDbPath, filteredDbPath, profile_name);

json data = {
    {"task_id", task_id},
    {"profile_name", profile_name},
    {"filtered_db", filteredDbPath},
    {"total_files", stats.total_files},
    {"included_files", stats.included_files},
    {"excluded_files", stats.excluded_files}
};

auto resp = ApiResponse::create_success("Filter applied successfully", data);
res.code = 200;
```

流程：查 TaskManager 拿 `task.output_raw_db` → 按 `_raw.db → _filtered.db` 命名规则生成目标路径（**字符串替换**，与流水线的产物命名约定耦合；任务库不叫 `_raw.db` 结尾时退化为加 `.filtered` 后缀）→ `FileFilter::applyFilterByName` 同步跑 → 返回 total/included/excluded 计数与 filtered_db 路径。任务或 raw.db 不存在分别 404（NOT_FOUND / DB_NOT_FOUND）。注意**全程不改 task 对象**——§5 的"不回写"问题就埋在这里。

### 3.3 POST 重建画像的 exclude 降配（已知不一致）

```cpp
// src/network/HTTPServer/routes/FilterRoutes.cpp:255-293（节选）
// Include condition
if (body.contains("include") && body["include"].is_object()) {
    json inc = body["include"];
    profile["include"] = {
        {"extensions", inc.value("extensions", json::array())},
        {"path_patterns", inc.value("path_patterns", json::array())},
        {"filename_patterns", inc.value("filename_patterns", json::array())},
        {"min_size", inc.value("min_size", 0)},
        {"max_size", inc.value("max_size", 0)},
        {"include_deleted", inc.value("include_deleted", true)},
        {"include_allocated", inc.value("include_allocated", true)}
    };
}
// ...
// Exclude condition
if (body.contains("exclude") && body["exclude"].is_object()) {
    json exc = body["exclude"];
    profile["exclude"] = {
        {"extensions", exc.value("extensions", json::array())},
        {"path_patterns", exc.value("path_patterns", json::array())},
        {"filename_patterns", exc.value("filename_patterns", json::array())}
    };
}
```

include 分支重建**七项**（含 min_size/max_size/include_deleted/include_allocated），exclude 分支只保留**三项**（extensions/path_patterns/filename_patterns）——而 FileFilter 的 FilterCondition 本身支持全部七维（conditionToJson/jsonToCondition 都有，:520-542）。通过 REST 写"exclude 大于某尺寸"的画像会被静默降配，直接改文件才保得住。这是服务端重建逻辑与数据模型的脱节，不是有意设计。

## 4. ApiResponse 封装：只有这组在用

```cpp
// src/network/HTTPServer/HTTPserver.h:35-41
struct ApiResponse {
    bool success = true;        ///< Operation success status
    std::string message;        ///< Human-readable message
    nlohmann::json data;        ///< Response payload
    std::string timestamp;      ///< ISO 8601 server time
    nlohmann::json pagination;  ///< Pagination metadata
    std::string error_code;     ///< Application-specific error code
```

实现要点（HTTPserver.cpp:21-61）：`to_json()` 只在非空时输出 pagination/error_code 字段；`create_success` 把 null data 归一为空对象——注释特别警告不要用 `data ? ...`（nlohmann 的 operator bool 对非布尔 JSON 抛 type_error.302，要用 is_null()）；`create_error` 置 success=false + error_code。全库检索它的使用面：**仅 FilterRoutes.cpp**（加上定义处的 HTTPserver）——其余路由（Task/Case/Search/Forensics…）各自手拼响应体。这是一次"统一响应格式"的试验性落地，尚未推广。后果两面：写客户端时 Filter 组可以统一解包（error_code 机器可读，如 VALIDATION_ERROR / FORBIDDEN / NOT_FOUND / DIR_NOT_FOUND / DB_NOT_FOUND / PARSE_ERROR / WRITE_ERROR）；但也意味着**同一服务两套响应形状并存**，通用错误处理代码要兼容两种。

另一个细节：timestamp 注释写 ISO 8601，实现用的却是 `std::ctime` 截断换行（HTTPserver.cpp:44-47）——形如 "Wed Aug 23 10:00:00 2026"，**非**严格 ISO 8601；推广前要先修。

## 5. 常见错误与边界

- **apply 不回写任务字段**：手动 apply 生成的 `_filtered.db` **不会**替换 `task.output_raw_db`（对比流水线路径 TaskManagerAnalysis.cpp:291-297 会替换）——已完成的任务继续以 raw.db 为结果库；filtered.db 只是摆在旁边的一份副本。指望"apply 后任务结果就变了"是常见误解（§3.2 代码可见全程无 task 写操作）。
- **apply 是同步阻塞的**：几十万文件的库过滤要几十秒，HTTP 超时/网关超时风险自担；没有 job/进度查询端点。
- **pagination 字段恒为 null**：ApiResponse 有这个字段但 FilterRoutes 从不填——解包时别假设它有值。
- **POST 的 exclude 条件丢字段**：§3.3，exclude 分支只保留三项——**已知不一致**。
- **目录找不到时行为分裂**：列表/详情/删除返回 500 DIR_NOT_FOUND；创建则退而创建相对路径 `config/filter_profiles`（:240-243，取决于服务 CWD）。
- **内置画像清单两处硬编码**（POST 与 DELETE 各一份），加第五个内置画像要改两处 + config 目录三处同步。

## 6. 如何验证与扩展

- 冒烟：`curl :8080/api/filter/profiles | jq .data.count`（应为 4+）；POST 一个自定义画像 → 确认 201 与文件落盘 → POST 同名再确认 200（update）→ DELETE 后 GET 应 404；`curl -X POST :8080/api/filter/apply -d '{"task_id":"<id>","profile_name":"telecom_fraud"}'` 核对计数与任务 output_raw_db 未变。
- 扩展：新匹配维度（如 mtime）需 FileFilter 与本路由的 jsonToCondition/conditionToJson（:532-555）同步；修 exclude 降配只需把 §3.3 的 exclude 分支补齐四个字段；若 ApiResponse 要推广到其它路由组，注意 timestamp 的 ctime 问题先修再推。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
