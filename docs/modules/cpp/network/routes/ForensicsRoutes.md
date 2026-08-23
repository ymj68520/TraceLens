# ForensicsRoutes（src/network/HTTPServer/routes/ForensicsRoutes.cpp 及 11 个子路由文件）

> **职责**：任务**结果侧**的只读查询大门——时间线、文件分析、统计、Android/MIUI、内存、DLL、系统事件、导出、文件提取、场景查询共 11 组子路由，全部围绕"拿 task_id → 解析产出库 → SQLiteHelper 查询"这一条链。
> **端点全量清单**：见 [CPP_REST_API.md](../../../../api_reference/CPP_REST_API.md) 与 [RouteReference.md](./RouteReference.md)。

## 1. 这组路由承担什么

任务完成后，调查员的全部"看结果"动作都在这里：时间线页翻事件与簇、文件页找大文件/可疑文件/重复文件、统计页看分布、Android 页看通信与应用、内存页看进程、导出成 CSV/JSON。写操作只有两类：**触发文件提取作业**与**触发事件簇重分析**——其余全是 SELECT。

它与 TaskRoutes 的分界线：TaskRoutes 管"任务的生命周期"，ForensicsRoutes 管"任务产出的内容"。

## 2. 典型调用方

| 前端页面 | 主要消费的子路由 |
|---|---|
| /timeline 时间线页（含簇抽屉） | timeline/* 全套 + timeline/clusters/*（EventClusterRoutes） |
| /files 文件页 | files/largest、files/recent、files/suspicious、files/duplicates、files/extensions-analysis |
| /statistics 统计页 | statistics/overview、file-distribution、activity-patterns、deleted-files-analysis |
| /android 页 | android/communication-summary、app-usage、device-info、media-analysis、miui-* 全套、llm-summary |
| /memory 页 | memory/summary、processes、network、bash-history、boot-info |
| 导出/报告 | export/events/{csv,json,visualization} |
| 文件提取对话框 | /api/forensics/extract（异步作业） |

## 3. 端点分组与语义

### 3.1 聚合器本身几乎为空

`ForensicsRoutes` 构造函数组合 11 个子路由成员（ForensicsRoutes.cpp:31-45）；自己保留了一套**遗留的提取作业跟踪表**（create/get/update/cleanup_extraction_job，:51-119），注释说明文件提取路由现在自管作业、这些方法"kept for potential backward compatibility"——读代码时可跳过：

```cpp
// ForensicsRoutes.cpp:31-45
ForensicsRoutes::ForensicsRoutes(crow::App<>& app)
    : task_manager_(TaskManager::instance()),
      timeline_routes_(app),
      event_cluster_routes_(app),
      export_routes_(app),
      file_analysis_routes_(app),
      file_extraction_routes_(app),
      statistics_routes_(app),
      android_forensics_routes_(app),
      memory_forensics_routes_(app),
      system_event_routes_(app),
      dll_analysis_routes_(app),
      scene_query_routes_(app) {
    // Route handlers are registered by the sub-route constructors
}
```

11 个成员的初始化列表就是本组的全部端点归属表：TimelineRoutes、EventClusterRoutes、ExportRoutes、FileAnalysisRoutes、FileExtractionRoutes、StatisticsRoutes、AndroidForensicsRoutes、MemoryForensicsRoutes、SystemEventRoutes、DLLAnalysisRoutes、SceneQueryRoutes。遗留作业跟踪方法操作的是 `extraction_jobs_` map + `extraction_mutex_`，但没有任何路由再调它们——FileExtractionRoutes 内部有自己的作业表。真正活跃的只有 `generate_job_id()` 的静态副本（两处实现完全相同，ForensicsRoutes.cpp:18-29 与 RouteHelpers.cpp:22-33）。

### 3.2 时间线组（TimelineRoutes + EventClusterRoutes）

- `timeline/comprehensive`：一网打尽的主查询，支持时间范围/类型过滤、分页，`cluster_events=true` 时按 60 秒窗聚簇（与 EventClusterAnalyzer 同语义）；
- `timeline/details`：展开某簇的明细（time_window+event_type+parent_dir 三元组定位，bucket_seconds 须与聚簇一致）；
- 辅助视角：by-type / by-time-range / by-file / full / distribution / statistics-by-period / file-activity / suspicious-patterns / user-activity；
- **clusters/ 组是写端点**：analyze/batch-analyze/reanalyze 触发 LLM 簇分析（复用 EventClusterAnalyzer），analyzed 读取已分析簇——这是时间线页簇抽屉里"AI 分析"按钮的后端。

主查询 handler 的参数解析是本组的模板：

```cpp
// TimelineRoutes.cpp:112-148（handle_timeline_comprehensive，节选）
crow::response TimelineRoutes::handle_timeline_comprehensive(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string start_time = params.get("start_time") ? params.get("start_time") : "";
    std::string end_time = params.get("end_time") ? params.get("end_time") : "";
    std::string event_type = params.get("event_type") ? params.get("event_type") : "";
    int limit = params.get("limit") ? std::stoi(params.get("limit")) : 1000;
    int offset = params.get("offset") ? std::stoi(params.get("offset")) : 0;
    bool cluster = params.get("cluster") ? (std::string(params.get("cluster")) == "true") : false;
    // Clustering time window in seconds. Default 60 (backward compatible).
    // Clamped to [1, 86400] inside the query layer.
    int bucket_seconds = params.get("bucket") ? std::stoi(params.get("bucket")) : 60;

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        // ...
    }

    try {
        std::string raw_db = RouteHelpers::get_database_path(task_id, "raw");
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
        json result = SQLiteHelper::get_comprehensive_timeline(raw_db, events_db, start_time, end_time, limit, offset, event_type, cluster, bucket_seconds);
        // ...
```

三层职责一目了然：handler 只做"解析参数→缺 task_id 即 400→解析库路径→转发"；SQL 构造、聚簇、防御全在 SQLiteHelper。注意**注意 URL 参数名是 `cluster`/`bucket`**，而 SQLiteHelper 形参名是 `cluster_events`/`bucket_seconds`——前端文档与 C++ 签名之间隔着一次改名。task_id 不存在时 `get_database_path` 抛 runtime_error，被 catch 转 500——这就是 §5 说的"404 语义混杂"。

`timeline/details` 的参数兼容层更厚（TimelineRoutes.cpp:150-184）：`window`/`bucket_index` 互为别名、`parent`/`dir` 互为别名，**两者同时给出且不一致时 400**（"bucket_index and window must match"）——新旧前端字段名共存期的典型防御；bucket_seconds 同样默认 60 且必须与聚簇时一致。

### 3.3 文件与统计组

files/* 全部映射 SQLiteHelper::FileAnalysisQueries（largest/recent/suspicious/duplicates/extensions-analysis + llm 结果）；statistics/* 映射 StatisticsQueries。语义上都是"一个维度一个端点"的平铺设计，参数基本是 task_id + limit。

### 3.4 Android/MIUI 组（AndroidForensicsRoutes，14 个端点）

最大的一组：通信摘要/应用使用/设备信息/媒体分析四个通用端点，加上 MIUI 离线备份的 overview/installed-apps/db-inventory，以及 QQNT、微信两族 artifacts/records/overview 端点（敏感字段默认脱敏，revealSensitive 参数控制）。数据全部来自 `android.db`（经 RouteHelpers 的多级回退解析）。

```cpp
// AndroidForensicsRoutes.cpp:390-398（QQNT records 的脱敏开关读取）
const int limit = params.get("limit") ? std::max(1, std::atoi(params.get("limit"))) : 100;
const int offset = params.get("offset") ? std::max(0, std::atoi(params.get("offset"))) : 0;
const bool revealSensitive = params.get("reveal_sensitive") &&
    std::string(params.get("reveal_sensitive")) == "1";
res.set_header("Content-Type", "application/json");
res.write(SQLiteHelper::get_miui_qqnt_records(
    database, kind,
    params.get("query") ? params.get("query") : "", limit, offset,
    revealSensitive).dump());
```

脱敏在查询层做（`get_miui_qqnt_records`/`get_miui_wechat_records` 的 revealSensitive 形参直传 SQLiteHelper），路由层只负责字符串→bool；显式传 `1` 才明文，其他任何值（true/yes/缺省）都是脱敏——默认安全的取向。顺带注意这里 limit/offset 用的是 `std::max` 下限保护而非 SQLiteHelper::clamp_limit，防的是 0/负数，不设上限——各子路由的防御纪律不完全统一。

### 3.5 专项组

- **memory/***：读 `_memory.db`（Volatility 产物），路径解析见 RouteHelpers.cpp:72-86 的 `_raw` 后缀剥离逻辑；
- **dlls/***：DLL 异常分析端点组（含独立的 analyze 触发与 health）；
- **system/events|summary**：系统事件视图；
- **export/***：事件导出三格式；自定义 `query` 参数必须通过 `SQLiteHelper::is_readonly_select` 校验；
- **/api/forensics/extract**：异步文件提取作业（提交→轮询 extract/status）。

## 4. 数据从哪张表来

统一模式：`task_id` + `db` 类型 → `RouteHelpers::get_database_path`（RouteHelpers.cpp:35-90）→ SQLiteHelper 对应域模块：

| 端点组 | 产出库 | SQLiteHelper 模块 |
|---|---|---|
| timeline/*、system/events | `_events.db`（events 表） | TimelineQueries / StatisticsQueries |
| files/*、statistics/file-* | `_files.db`（files、file_descriptions 表） | FileAnalysisQueries / StatisticsQueries |
| statistics/overview、deleted-files | `_raw.db` + `_files.db` + `_events.db` | StatisticsQueries |
| android/*、miui-* | `android.db` | AndroidQueries |
| memory/* | `_memory.db` | MemoryForensicsRoutes 内联查询 |
| clusters/*（分析写入） | `_events.db` 簇 LLM 列 | EventClusterAnalyzer（非 SQLiteHelper） |

android 类型路径解析的三级回退（RouteHelpers.cpp:48-66）：任务 metadata 里的 `android_db` → output_files_db 同目录的 `android.db` → raw 库去后缀推导 `<base>_android.db` → 最后兜底 output_files_db 本身。逻辑 Android 任务（miui-backup 等）在流水线里把 android.db 同时写进 metadata 与 output_files_db（TaskManagerAnalysis.cpp:647-653），保证任何一级回退都命中。memory 类型的 `_raw` 剥离（:76-86）是为了对齐 MemoryAnalyzer 的命名约定：`img_raw.db → img_memory.db` 而非 `img_raw_memory.db`。

## 5. 常见错误与边界

- **404 语义混杂**：task_id 不存在（RouteHelpers 抛 runtime_error）与"库文件还没生成"都可能以 404/错误 JSON 返回——任务未完成就调结果端点是常见时序问题，前端应以任务状态为先导。
- **limit 未钳制的端点存在**：新代码都应走 clamp_limit；给老端点传超大 limit 可能拖垮大库。（comprehensive 的钳制在查询层兜底，TimelineQueries.cpp:95-96；但 std::stoi 解析失败会直接抛异常转 500——传 `limit=abc` 得到 500 而非 400。）
- **bucket_seconds 错位**：details 端点的 bucket 必须与聚簇时一致（默认 60），否则簇明细为空。
- **导出自定义 query 被拒**：含分号/注释/非 SELECT 关键词一律 400——这是特性不是 bug（防注入）。
- **extract 作业是内存态**：服务重启后未完成作业的状态查询 404。
- **两个 generate_job_id 副本**：ForensicsRoutes.cpp:18-29 与 RouteHelpers.cpp:22-33 逐字符相同——改一处忘另一处会得到格式不一致的 job id（前缀都是 `ext-`，目前无害）。

## 6. 如何验证与扩展

- 冒烟：完成任务后依次 curl `timeline/comprehensive?task_id=...&cluster_events=true`（注意参数名实为 `cluster`）、`files/largest?task_id=...&limit=5`、`android/communication-summary?task_id=...`，与 `sqlite3 data/tasks/<id>/*.db` 的行数互相印证。
- 扩展新查询端点：选好所属域 → 在 SQLiteHelper 对应 Queries 文件加方法 → 子路由文件注册端点（+Swagger RegisterEndpoint）→ 若是新域则建子路由类并在 ForensicsRoutes.cpp:31-45 挂载。

## 7. 端点全表（62 个，按子路由，二轮补全）

各子路由注册的全部端点（与 HTTPServer.md §8.2 同源、此处按查询域组织并标注参数）。除标注外均为 GET、必带 query 参数 `task_id`：

| 子路由 | 端点（路径后缀省略 /api/forensics/） | 特有参数 |
|---|---|---|
| TimelineRoutes（11） | timeline/comprehensive | start_time、end_time、event_type、limit(1000)、offset、**cluster**（="true"）、**bucket**(60) |
| | timeline/details | time_window 或 window/bucket_index（别名，冲突 400）、event_type、parent 或 parent_directory/dir（别名）、search、limit、offset、bucket(60) |
| | timeline/distribution、timeline/full（limit/offset）、timeline/statistics-by-period（period=hour/day/week/month） | — |
| | timeline/by-type（event_type 必填）、timeline/by-time-range（start_time/end_time 必填 int64）、timeline/by-file（file_path 必填） | — |
| | timeline/file-activity（file_path/inode 可选）、timeline/suspicious-patterns、timeline/user-activity | — |
| EventClusterRoutes（4） | timeline/clusters/analyze（POST，**410 弃用桩**）、clusters/batch-analyze（POST：task_id+clusters[]）、clusters/reanalyze（POST：task_id+time_window+event_type+parent_directory）、clusters/analyzed | 见 EventClusterAnalyzer.md §9 |
| ExportRoutes（4） | export/toon（POST）、export/events/json、export/events/csv、export/events/visualization | query（只读 SELECT 校验）、output 路径 |
| FileAnalysisRoutes（5） | files/largest（limit=50）、files/recent（hours="24"）、files/suspicious、files/duplicates、files/extensions-analysis | — |
| FileExtractionRoutes（3） | extract（POST：task_id+file_ids[]+mode 等）、extract/{job_id}、extract/status?job_id= | 作业态内存 |
| StatisticsRoutes（4） | statistics/overview、file-distribution、activity-patterns、deleted-files-analysis | — |
| AndroidForensicsRoutes（14） | android/{communication-summary,app-usage,device-info,media-analysis,llm-summary} | — |
| | android/miui-{overview,installed-apps,db-inventory} | — |
| | android/miui-qqnt-{overview,artifacts,records}、android/miui-wechat-{overview,artifacts,records} | artifacts：category/status/query/limit(100,max≥1)/offset(max≥0)；records：kind/query/limit/offset/**reveal_sensitive**（="1" 才明文） |
| MemoryForensicsRoutes（5） | memory/{summary,processes,network,bash-history,boot-info} | 读 `_memory.db` |
| SystemEventRoutes（2） | system/events（start_time/end_time/limit/offset）、system/summary | — |
| DLLAnalysisRoutes（7） | dlls、dlls/{int id}、dlls/suspicious、dlls/statistics、dlls/health、dlls/{int id}/anomalies、dlls/analyze（POST） | id 为 int 路径参数 |
| SceneQueryRoutes（2） | /api/tasks/{id}/scene-stats、/api/tasks/{id}/scene-artifacts（scene_type 白名单三选一、limit=100、offset=0） | 前缀挂在 /api/tasks 下 |

前端调用方对照（Services.md）：Timeline 页消费 9 个 timeline 端点 + clusters；Files 页消费 files 五件套 + extract 三件套；Statistics 四件套；Android 页消费 14 个 android 端点全量；Memory 五件套；systemService.exportToon 打 export/toon。

## 8. 数据库路径解析契约（RouteHelpers::get_database_path 全分支）

所有端点的第一步都经此函数（RouteHelpers.cpp:35-90），完整分支表（task_id 不存在抛 runtime_error→handler catch→500/400 视 handler 而定）：

| db_type | 解析顺序 | 兜底 |
|---|---|---|
| raw | `task.output_raw_db` 直返 | 无（可能为空串） |
| events | `task.output_events_db` 直返 | 无 |
| files | `task.output_files_db` 直返 | 无 |
| android | ① metadata["android_db"] 且存在 → ② output_files_db 同目录 `android.db` 且存在 → ③ raw 库去扩展名 + `_android.db` 且存在 → ④ output_files_db 本身（存在时）→ ⑤ ③的路径（**明知不存在也返回**，让查询层报错） | :48-66 |
| dll | ① metadata["dll_db"] → ② raw 去扩展名 + `_dll.db`（**不查存在性**） | :67-71 |
| memory | ① metadata["memory_db"] → ② raw 去扩展名再**剥 `_raw` 后缀** + `_memory.db`（不查存在性） | :72-86 |
| 其他 | throw "Unknown database type" | :87-89 |

三处不对称值得注意：android 走完整存在性探测链；dll/memory 只做命名推导**不查存在**（文件不存在时错误延迟到 sqlite3_open）；raw/events/files 直接返回任务字段——任务没跑到对应阶段时是空串，`sqlite3_open("")` 会**创建空库**（SQLite 语义：空路径或不存在均可打开，写时才落盘）——SQLiteHelper 的 open 失败分支通常不触发，查询返回空数组，表现为"端点 200 + 空结果"而非 404。这是排障"任务没完成却拿到空数据"的根源。

## 9. 新走读分支：extract 作业生命周期（FileExtractionRoutes 自管）

提取作业不走 TaskManager，是 handler 进程内的 map 态（重启即失，§5 已记）：

1. **提交**（POST /api/forensics/extract）：body 含 task_id、file_ids[]、mode（"allocated"/"deleted" 决定 ExtractionMode）、输出目录等；生成 `ext-` + 8 hex 的 job id（RouteHelpers::generate_job_id，:22-33），作业入 map，状态 queued；
2. **执行**：handler 内起后台工作（从 raw.db 找 inode → TSK 抽取 → 写输出目录），逐文件更新作业进度；
3. **轮询**（GET /api/forensics/extract/status?job_id=）：前端 pollExtractionStatus（extractionService.js:50-111）以 2s 级间隔轮询，带 AbortSignal 与 15 分钟绝对 deadline；
4. **终态**：completed（带 output_path）或 failed（带 error）。

URL 溯源细节（FileExtractionRoutes.cpp 内）：`find("/api/forensics/extract/")` 的字符串操作用于从 referer/回调推断 job id——这类基于 URL 前缀的解析是历史遗留，直接以 status 端点为准即可。

## 10. 配置影响表（ForensicsRoutes 视角）

| 配置 | 默认 | 消费点 | 说明 |
|---|---|---|---|
| `CORS_ALLOW_ORIGIN` | `*` | RouteHelpers.cpp:16-17 | 所有 API 响应头的唯一来源；设白名单即全组收敛 |
| `FTS_ALLOWED_ROOT` | 未设=不限制 | SearchRoutes.cpp:20（不在本组，对照用） | 检索白名单 |
| `SEARCH_*` 四项 | 1000/50000/150/10 | FullTextSearch | 不经 SQLiteHelper，不适用本组 |
| `DB_JOURNAL_MODE` 等 | WAL/5000 | 写侧建库 | 查询侧不受控（见 SQLiteHelper.md §10） |
| （bucket/limit/reveal_sensitive 无 env） | 60/各默认/hardcode | 各 handler | 全部只能 URL 参数调 |

## 11. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 |
|---|---|---|
| 被调 | forensicsService（timeline/files/android/statistics 族）、extractionService（extract 三件套）、memoryService（五件套）、systemService.exportToon | Services.md |
| 调用 | RouteHelpers::get_database_path / add_cors_headers / generate_job_id | 每端点首步 |
| 调用 | SQLiteHelper 六域查询 | 数据层 |
| 调用 | EventClusterAnalyzer（clusters 写端点） | 唯一非 SELECT 主路径 |
| 调用 | TaskManager::instance().get_task | 路径解析的 task 字段来源 |
| 挂载 | HTTPServer 构造列表第 2 位 | HTTPserver.cpp:68 |
| Swagger | 28 条注册（Timeline 7 + Android 7 + EventCluster 4 + Export 3 + SystemEvent 2 + FileAnalysis 1 + FileExtraction 1 + OSS 0） | 覆盖率见 Swagger.md §10 |

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
