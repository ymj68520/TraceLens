# SystemRoutes（src/network/HTTPServer/routes/SystemRoutes.cpp 及 SystemHealth/SystemInfo/SystemDocs）

> **职责**：运维与自描述面——健康检查（存活/就绪/依赖）、系统与数据库信息、日志查看、结果导出触发，以及把本服务自己的 API 文档（Swagger 注册表 + OpenAPI JSON）伺服出去。
> **端点全量清单**：见 [CPP_REST_API.md](../../../../api_reference/CPP_REST_API.md) 与 [RouteReference.md](./RouteReference.md)。

## 1. 这组路由承担什么

三个受众三种需求：**监控/编排系统**要探活与健康信号（部署探针、告警）；**运维**要看有哪些库、多大、日志说了什么；**前后端开发者**要一份活的端点清单（/api/docs UI 与 openapi.json）。注意这组路由里挂着一个"异类"——`POST /api/export/{task_id}`（结果导出触发）在 SystemInfoRoutes 里注册，属于历史归位问题而非语义归属。

## 2. 典型调用方

- **K8s/负载均衡探针**：/api/health/live（存活）、/api/health/ready（就绪）；
- **Dashboard/监控面板**：/api/system/health 的任务统计摘要（total/running/failed）；
- **设置页/调试**：/api/system/info（能力自述）、/api/system/databases、/api/system/logs；
- **开发联调**：/api/docs（文档 UI）、/api/docs/openapi.json（代码生成/Postman 导入）。

## 3. 端点分组与语义

### 3.1 聚合结构

`SystemRoutes` 构造函数组合 SystemHealthRoutes + SystemInfoRoutes + SystemDocsRoutes 三个子路由（SystemRoutes.cpp:8-13），自身零逻辑——是新增路由组时最简的模仿模板。三个子路由构造函数各自 CROW_ROUTE，均无 Swagger 注册（本组是文档的"伺服者"，自己反而不进注册表——openapi.json 里因此看不到 /api/docs/* 自身，属自指豁免）。

### 3.2 健康检查组（SystemHealthRoutes.cpp:13-31）

- `/api/system/health` 与 `/api/health`（同义双路径）：聚合 TaskManager 统计的"富健康"视图——status/version/task_management（total/running/failed/system_load）/services 清单（SystemHealthRoutes.cpp:34-62）；
- `/api/health/live`：纯存活，不做任何依赖检查（:64-77）——探针快速失败用；
- `/api/health/ready` 与 `/api/health/dependencies`：就绪与依赖细节，检查会涉及下游（Python 服务等）可达性。

语义分工是标准 K8s 套路：live 判"进程要不要重启"，ready 判"能不能接流量"。富健康的实现：

```cpp
// SystemHealthRoutes.cpp:34-62（handle_system_health，节选）
crow::response SystemHealthRoutes::handle_system_health(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        auto task_stats = TaskManager::instance().get_task_statistics();

        json health;
        health["status"] = "healthy";
        health["timestamp"] = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
        health["version"] = "1.0.0";
        health["task_management"]["total_tasks"] = task_stats["total_tasks"];
        health["task_management"]["running_tasks"] = task_stats["by_status"]["running"];
        health["task_management"]["failed_tasks"] = task_stats["by_status"]["failed"];
        health["task_management"]["system_load"] = "low";
        health["services"]["http_server"] = "running";
        health["services"]["task_manager"] = "running";
        health["services"]["database_access"] = "available";
        // ...
```

关键在读法：`status`/`services` 是**写死的常量**，唯一真实的数据源是从 TaskManager 拉来的三个数字；`system_load` 恒为 "low"（没有采样逻辑）。只有 get_task_statistics 抛异常才会走 catch 返回 500/unhealthy——所以"healthy"的语义实际是"TaskManager 大锁没死锁"。就绪探针的检查面更实一些：

```cpp
// SystemHealthRoutes.cpp:83-106（handle_health_ready，节选）
bool ready = true;
json checks;

// Check task manager
try {
    auto stats = TaskManager::instance().get_task_statistics();
    checks["task_manager"]["status"] = "ready";
    checks["task_manager"]["total_tasks"] = stats["total_tasks"];
} catch (const std::exception& e) {
    checks["task_manager"]["status"] = "error";
    checks["task_manager"]["error"] = e.what();
    ready = false;
}

checks["database"]["status"] = "ready";

json health;
health["ready"] = ready;
health["checks"] = checks;
// ...
res.code = ready ? 200 : 503;
```

ready 的判定=task_manager 检查不抛错；`database` 检查是**无条件 ready**（没有真的开 SQLite 试连）；失败时返回 503 语义码——这是全组唯一会返回非 200 成功码的探针端点，编排层应据此摘流量。dependencies 端点（:118-148）更进一步列出 llm_service/python_service 的配置值，但全部是"configured/optional"的静态标记，不做真实探测——注释里的 status 字符串是配置状态而非可达状态。

### 3.3 系统信息组（SystemInfoRoutes.cpp:11-29）

- `/api/system/info`：静态能力自述（名称/版本/特性列表/支持镜像格式，:32-63）——**硬编码 JSON**，加新能力要改代码；
- `/api/system/databases?task_id=`：列出该任务产出库及文件大小（:65-100+），无 task_id 时列全局可见库；
- `/api/system/database-schema/<db_type>`：按类型返回表结构说明；
- `/api/system/logs`：读服务日志；
- `POST /api/export/<task_id>`：触发该任务结果导出（挂在 info 组属历史位置）。

database-schema 也是硬编码 JSON（SystemInfoRoutes.cpp:118-160），只认识 raw/files/events 三类，未知类型 400：

```cpp
// SystemInfoRoutes.cpp:118-160（节选）
if (db_type == "raw") {
    schema = {
        {"type", "raw"},
        {"tables", {
            {"files", {
                {"columns", {"id", "path", "name", "size", "mtime", "atime", "ctime", "inode", "deleted", "content_hash"}}
            }},
            {"partitions", {
                {"columns", {"id", "number", "start", "length", "description", "fs_type"}}
            }}
        }}
    };
} else if (db_type == "files") {
    // ...
```

与 docs/database-schema 端点（SystemDocsRoutes.cpp:85-102）是**第三份**表结构描述——三处描述（真实建表 SQL、本端点、docs 端点）各自手工维护，列名一旦演进就会出现"描述与库不符"的漂移。

databases 端点的数据组装：

```cpp
// SystemInfoRoutes.cpp:76-99（节选）
if (!task_id.empty()) {
    AnalysisTask task = task_manager_.get_task(task_id);
    if (!task.id.empty()) {
        if (!task.output_raw_db.empty() && std::filesystem::exists(task.output_raw_db)) {
            databases.push_back({
                {"type", "raw"},
                {"path", task.output_raw_db},
                {"size", std::filesystem::file_size(task.output_raw_db)}
            });
        }
        if (!task.output_events_db.empty() && std::filesystem::exists(task.output_events_db)) {
            // ...
        }
        if (!task.output_files_db.empty() && std::filesystem::exists(task.output_files_db)) {
            // ...
        }
    }
}
```

三个 if 同构（events/files 各查一次 exists + file_size）。只列 raw/events/files 三类——android.dll/memory 等专项库**不在此清单**（要用 TaskRoutes 的 databases 端点或 metadata 才能发现）；`exists()` 先行防的是 file_size 对不存在文件抛异常；task_id 无效时**静默返回空列表而非 404**（`task.id.empty()` 分支只跳过填充），与 TaskRoutes 的 404 纪律不同——调用方拿空数组时要能区分"任务不存在"与"任务还没产出库"，当前响应无法区分。这个端点与 `/api/tasks/{id}/databases`（TaskCRUDRoutes.cpp:527-585）功能高度重叠，差异只在 size 字段与空目录行为。

### 3.4 文档组（SystemDocsRoutes.cpp:10-24）

四个端点：`/api/docs/endpoints`（**手写维护的端点清单 JSON**，:27-60+）、`/api/docs/database-schema`、`/api/docs/openapi.json`、`/api/docs`（简易 UI 页）。要区分两份"文档事实"：Swagger 单例注册表（各路由构造时 RegisterEndpoint 喂入，openapi.json 由此生成，**与代码同步**）与 endpoints 端点里的手写清单（**会过时**）——优先信前者。

openapi.json 端点就是一层薄转发（SystemDocsRoutes.cpp:115-130）：`Swagger::instance().GetSwaggerJSON()` → `dump(2)` 写回。UI 页（:136-168）是内嵌 HTML 字符串，从 unpkg CDN 加载 Swagger UI 5.11.0 指向同源 openapi.json——离线环境 UI 白屏但 JSON 端点不受影响。

手写清单与注册表的具体差距（SystemDocsRoutes.cpp:31-68）：它只列了 task_management/forensics/system/search 四组约 25 条，没有 cases/filter/clusters/extract/memory/dlls/miui 等后来加的端点，且用 `<id>` 而非 `{id}` 的 Crow 占位风格——与 openapi.json 对比即可看出漂移程度。

## 4. 数据从哪来

- 健康统计：`TaskManager::get_task_statistics()`（内存态，源头 data/tasks.json）；
- databases：`AnalysisTask` 的 output_*_db 字段 + `std::filesystem::file_size`；
- logs：日志文件（PathManager 的 logs 目录）；
- docs：Swagger 注册表（内存）/ 手写 JSON 常量；
- 本组**不查任何业务 SQLite 表**（导出触发端点内部另行调用导出逻辑）。

## 5. 常见错误与边界

- **health 的 "healthy" 近乎无条件**：handle_system_health 只要 TaskManager 统计不抛异常就返回 healthy，running 任务很多也不会变 degraded——告警策略别指望它分级（system_load 恒 "low"、services 三项恒 "running/available"，全是常量）。
- **version 硬编码 "1.0.0"**：与构建版本无联动；Swagger 文档里的 1.0.0 是另一处独立硬编码。
- **info 的特性清单会漂移**：新增能力忘了改就误导调用方（如 file_carving/LLM 簇分析均不在 features 列表里）。
- **endpoints 手写清单与真实路由可能不一致**：以 openapi.json/Swagger 注册表为准。
- **dependencies 检查的超时**：Python 服务慢时 ready 探针可能抖动，编排层需配容忍——实际上 dependencies 不做真实探测（§3.2），真正的抖动源是 ready 里的 get_task_statistics 在大锁被占时的等待。
- **databases 空列表的歧义**：task_id 无效与无产出库都返回空数组（§3.3）。
- **本组端点不在 openapi.json 里**：文档组/健康组自己没注册 Swagger 条目——用 openapi.json 做端点审计时会漏掉这批。

## 6. 如何验证与扩展

- 冒烟：`curl /api/health/live` 秒回 alive；`curl /api/system/health | jq .task_management`；`curl /api/docs/openapi.json | jq '.paths | keys | length'` 对比 RouteReference.md 的端点数；`curl /api/health/ready -i` 看正常时应为 200。
- 扩展：健康维度（如磁盘水位、线程池队列长度）加在 SystemHealthRoutes 并考虑让 status 出现 degraded 档位——现有代码里 status 从未被赋过第二种植；新路由组照抄 SystemRoutes.cpp:8-13 的三行聚合模式。

## 7. 端点全表（14 个，二轮补全）

| 端点 | 方法 | 参数 | 响应要点 | 源码 |
|---|---|---|---|---|
| /api/system/health、/api/health | GET | — | status/version/timestamp/task_management{total_tasks,running_tasks,failed_tasks,system_load}/services（§3.2 语义） | SystemHealthRoutes.cpp:34-62 |
| /api/health/live | GET | — | `{status:"alive",timestamp}` 恒 200 | :64-77 |
| /api/health/ready | GET | — | `{ready:bool, checks{task_manager,database}}`；失败 503 | :83-106 |
| /api/health/dependencies | GET | — | 依赖清单（配置态标记，无真实探测） | :118-148 |
| /api/system/info | GET | — | 名称/版本/特性/镜像格式（硬编码） | SystemInfoRoutes.cpp:32-63 |
| /api/system/databases | GET | query：task_id（可选） | 有 task_id 时 `[{type,path,size}]`（exists 过滤）；无 task_id 时全局库清单 | :65-100 |
| /api/system/database-schema/{db_type} | GET | 路径：raw/files/events | 硬编码表结构；未知类型 400 | :118-160 |
| /api/export/{task_id} | POST | body 可选 `format`（默认 json，**不校验取值**） | **应答式桩**（§8.1）：404 任务不存在 / 400 未完成 / 200 路径回显 | :168-224 |
| /api/system/logs | GET | query：lines（默认 100，≤1000 钳制） | `{service:"cpp-backend", logs[{timestamp,level,message}], total_count}` | :226-305 |
| /api/docs/endpoints | GET | — | 手写清单（会过时，§3.4） | SystemDocsRoutes.cpp:27-60 |
| /api/docs/database-schema | GET | — | 第二份硬编码表结构 | :85-102 |
| /api/docs/openapi.json | GET | — | Swagger 注册表渲染（dump(2)） | :115-130 |
| /api/docs | GET | — | Swagger UI HTML（CDN 5.11.0） | :136-168 |

前端调用方（Services.md）：systemService.getSystemHealth/getSystemInfo/getDatabases/getDatabaseSchema/getDocs*→Dashboard/Settings/Terminal；getExportStatus→`/api/export/{taskId}`；health/live、health/dependencies→Dashboard。

## 8. 新走读分支（二轮）

### 8.1 POST /api/export/{task_id} 是"应答式桩"（新发现）

handle_export_task（SystemInfoRoutes.cpp:168-224）的完整行为：查任务 → 不存在 404 → **未完成 400**（带 `status` 字段但值是**枚举整数**而非字符串——`static_cast<int>(task.status)`，与其他端点的小写串风格不一致，前端要按数字解析）→ 完成则解析 body 的 `format`（默认 "json"，任意值透传不校验）→ 返回三库路径 + "Export available at specified database paths"。**没有任何导出动作发生**——不打包、不写文件、format 参数无消费者。前端 systemService 里对应的调用拿到的是路径清单而非导出产物；真正的导出走 ExportRoutes 的 `/api/forensics/export/events/*` 或 `/api/forensics/export/toon`。这个端点是"预留接口占位"的现状。

### 8.2 /api/system/logs 的三级日志路径回退与格式解析

handle_system_logs（:226-305）的路径回退链：`PathManager.getLogFilePath()`（规范的 logs 目录）→ `logs/forensic_analyzer.log`（相对 CWD）→ `forensic_analyzer.log`（CWD 根）——**后两级是相对路径**，与 HTTPServer 静态托管的 web/dist 同款工作目录耦合；三级都不存在时返回空 logs 数组（200，不是 404）。

格式解析假设日志行形如 `[时间] LEVEL 消息`（:271-280）：首字符 `[` 且找到 `]` 才切出 timestamp；level 从 `] ` 后取到下一个空格；解析不出时整行作 message、level 归 INFO。**整个文件先全量读入内存**（:259-263 的 all_lines vector）再取尾部 N 行——大日志文件（数百 MB）时一次请求占等量内存；lines 钳制 `min(stoi, 1000)` 只限返回条数不限读取量。

### 8.3 health 的 timestamp 用 steady_clock

handle_system_health 的 timestamp 取 `steady_clock::now().time_since_epoch()`（:41-42）——steady 纪元通常是开机时间，**不是 Unix epoch**：这个字段对前端展示"当前时间"毫无意义，只能当单调递增序号用。对照 TaskProgress 的 phase_start_time 同用 steady_clock（那里是刻意的），此处更像笔误——若前端要显示时间应改 system_clock。

## 9. 配置影响表（SystemRoutes 视角）

| 配置 | 默认 | 消费点 | 说明 |
|---|---|---|---|
| `CORS_ALLOW_ORIGIN` | `*` | RouteHelpers | 全组响应头 |
| `HTTP_SERVER_PORT` / `HTTP_SERVER_HOST` | 8080 / 0.0.0.0 | info 端点回显（经 ConfigManager） | host 变量不影响实际绑定（HTTPServer.md §10 已记） |
| `PYTHON_SERVICE_URL` | http://localhost:8090 | dependencies 端点的 llm/python 服务条目 | 仅回显配置，不探测 |
| `LLM_BASE_URL` 等 | 见 Environment.md | dependencies 端点 | 同上 |
| `DATA_DIR` | data | databases/logs 端点的路径基 | PathManager 源 |
| （version/features/schema 无 env） | 硬编码 | info、schema 两端点 | 改版本要改代码 |

## 10. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 |
|---|---|---|
| 被调 | systemService（9 个方法） | Dashboard/Settings/Terminal 页 |
| 被调 | 探针/编排层（推测的 K8s 用法） | live/ready |
| 调用 | TaskManager::get_task_statistics | health/ready 的唯一动态数据 |
| 调用 | PathManager | databases/logs 路径 |
| 调用 | Swagger 单例 | openapi.json |
| 无调用 | SQLite（业务表） | 本组不查业务库 |
| 挂载 | HTTPServer 构造列表第 3 位 | HTTPserver.cpp:69 |
| Swagger 注册 | **0 条**（本组自身不注册） | openapi.json 审计盲区（§5） |

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
