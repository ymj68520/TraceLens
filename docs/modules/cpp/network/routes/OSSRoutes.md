# OSSRoutes（src/network/HTTPServer/routes/OSSRoutes.cpp 及 OSSAnalysisRoutes/OSSQueryRoutes/OSSStatsRoutes）

> **⚠️ 未注册：运行时 404。** `HTTPServer` 只构造了六个路由聚合器（TaskRoutes/ForensicsRoutes/SystemRoutes/SearchRoutes/CaseCRUDRoutes/FilterRoutes，HTTPserver.cpp:63-75），**从未实例化 OSSRoutes**——本组定义的 `/api/forensics/oss/*` 端点在运行时全部未注册，请求一律 404。前端 /oss 页（OSS.jsx）因此调不通，这不是部署问题，是代码现状。

## 1. 这组路由（本应）承担什么

按代码意图，它规划了阿里云 OSS（对象存储）取证的完整 REST 面：analyze（启动分析作业）、objects/logs（查询分析结果）、summary/stats/*（统计）、ai/filter、ai/analyze（Python 服务协作的 AI 分析）、download（对象下载）。

## 2. 为什么是死代码：历史与证据

未注册的证据在 HTTPServer 的构造初始化列表里，一目了然：

```cpp
// src/network/HTTPServer/HTTPserver.cpp:63-73
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
```

六个成员初始化完毕，没有第七个 `oss_routes_(app_)`。路由注册发生在聚合器构造函数里（CROW_ROUTE 宏向 app_ 挂 handler），**没被构造 = 没被注册**，Crow 对未知路径回 404。

一系列 TODO 注释还原了时间线：OSSAnalysisRoutes.cpp:232-235 写着 "TODO: Integrate with Python service ... Implementation Plan: Tasks 8-11"、:271-279 写着 "Task 6 (C++ Backend - Download Endpoint)"。可以判断：当时按实施计划先写了**路由骨架**（含 Swagger 注册），等 OSSClient 与 Python 侧能力就绪后再接线；但聚合器从未被挂进 HTTPServer 的构造列表，后续真实的 server/cloud 场景走了完全不同的路径（见 §6），这组骨架就永远停在了"已编译、未注册"状态。

即便手动注册，多数端点也拿不到真数据（见 §4）——**双层未完成**。

## 3. 聚合器本身长什么样

```cpp
// src/network/HTTPServer/routes/OSSRoutes.cpp:10-28
std::string OSSRoutes::generate_job_id() {
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, 15);
    const char* hex = "0123456789abcdef";
    std::stringstream ss;
    ss << "oss-";
    for (int i = 0; i < 8; i++) {
        ss << hex[dis(gen)];
    }
    return ss.str();
}

OSSRoutes::OSSRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    // Delegate to modular route handlers
    OSSAnalysisRoutes analysis_routes(app);
    OSSQueryRoutes query_routes(app);
    OSSStatsRoutes stats_routes(app);
}
```

聚合器模式与 FilterRoutes 一样"构造即注册"：构造 OSSRoutes 会依次栈上构造三个子路由对象，各自的构造函数把 CROW_ROUTE 挂到 app 上。`generate_job_id` 生成 `oss-` + 8 位十六进制（约 43 亿空间）——但注意**同一份函数在 OSSAnalysisRoutes.cpp:12-23 原样重复了一份**，聚合器自己这份从未被调用。

## 4. 端点分组与"如果调用会怎样"

> 完整端点清单见 [CPP_REST_API.md](../../../../api_reference/CPP_REST_API.md) 与 [RouteReference.md](./RouteReference.md)。下表是语义 + 实际实现状态。

| 组 | 端点（/api/forensics/oss/...） | 设计语义 | 实现现状（假设已注册） |
|---|---|---|---|
| 聚合器 | — | 组合三个子路由（OSSRoutes.cpp:23-28） | 从未被 HTTPServer 构造 → **运行时 404** |
| 分析 | POST analyze、GET analyze/status | 后台 OSS 分析作业 | 占位实现：起线程睡 100ms 即"完成"，status 恒回 completed（OSSAnalysisRoutes.cpp:222-229） |
| AI | POST ai/filter、ai/analyze，GET ai/status | 转发 Python 服务 | 恒 503 "Python LLM service not available"（:231-269、:296-319） |
| 下载 | POST download | OSSClient 下载对象 | 恒 501 "not yet implemented"（:271-294） |
| 查询 | GET objects、GET logs | 查分析产物 | 恒返回空数组占位（OSSQueryRoutes.cpp:54-65、:94-105） |
| 统计 | GET summary、stats/storage-class、stats/extensions、buckets | 汇总统计 | 恒返回全零占位（OSSStatsRoutes.cpp:75-80+） |

### 4.1 分析作业的"占位完成"实现

```cpp
// src/network/HTTPServer/routes/OSSAnalysisRoutes.cpp:135-156、222-229（节选）
std::string job_id = generate_job_id();

{
    std::lock_guard<std::mutex> lock(jobs_mutex_);
    // Store job_id and task_id mapping
    job_ids_[job_id] = task_id;
}

// Start async analysis (placeholder)
std::thread([this, job_id, task_id]() {
    run_analysis_job(job_id, task_id);
}).detach();

json response;
response["success"] = true;
response["message"] = "OSS analysis job started";
response["job_id"] = job_id;
response["status"] = "pending";
res.code = 202;
// ...
void OSSAnalysisRoutes::run_analysis_job(const std::string& job_id, const std::string& task_id) {
    // Placeholder implementation - actual analysis would go here
    // For now, just mark as completed after a brief delay
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    std::lock_guard<std::mutex> lock(jobs_mutex_);
    // Job completed - in a real implementation, this would update status
}
```

POST 立即回 202 + job_id（接口形状是真的），后台线程 `run_analysis_job` 睡 100ms 后**什么都不更新**就返回。GET analyze/status（:173-220）根本不读任何状态字段，查到 job_id 就硬编码回 `status: "completed", progress: 100`——即使强行注册，这套"作业"也只是空壳自嗨。还有第三层问题（技术深化新发现）：§3 的三个子路由对象是**聚合器构造函数里的栈对象，构造完即析构**，而它们的 CROW_ROUTE lambda 捕获的是各自的 `this`——真注册了，handler 一被调用就是悬空指针（job_ids_ 随宿主对象早已销毁）。"补一行初始化就能复活"并不成立，子路由必须改为成员或堆持有。

### 4.2 AI 端点：诚实的 503

```cpp
// src/network/HTTPServer/routes/OSSAnalysisRoutes.cpp:231-249
crow::response OSSAnalysisRoutes::handle_ai_filter_start(const crow::request& req) {
    // TODO: Integrate with Python service /api/forensics/oss/ai/filter
    // This will forward to OSSFilterService.filter_oss_objects()
    // See: python_service/httpserver/routes/oss_analysis.py
    // Implementation Plan: Tasks 8-11 (Python Service Implementation)
    // ...
    response["error"] = "Python LLM service not available";
    response["message"] = "AI filtering requires Python service integration (see Tasks 8-11 in implementation plan)";
    res.code = 503;  // Service Unavailable - Python service not yet integrated
```

与占位假成功不同，AI 组三个端点（ai/filter、ai/analyze、ai/status）**明确拒绝**：503 + 指向实施计划的说明。注释还点名了预期对接的 Python 模块（oss_analysis.py 的 OSSFilterService/OSSAnalysisService）。download 端点同理回 501（:271-294）。查询/统计组则是第三种姿态：返回形状正确但恒空/恒零的 JSON（如 OSSStatsRoutes.cpp:75-82 的 total_objects/total_size 全 0）。

## 5. 典型调用方（标注：调不通）

- **/oss 页（OSS.jsx）**：设计上的消费者，当前所有请求 404——**该页面在现版本不可用，属已知状态**。
- Swagger/OpenAPI 文档：各端点构造时注册过 Swagger 元数据（如 OSSAnalysisRoutes.cpp:35-42 注册 analyze 的 202/400 响应），openapi.json 里可能出现这些路径，**文档里有 ≠ 运行时可用**，自动化客户端勿据此生成调用。

## 6. 数据本来要从哪来（以及现在 OSS 数据的真实去向）

设计上 objects/logs/summary 查询的应是某个 OSS 分析产出库；但真实的 server/cloud 取证路径与此无关：

- 任务选 `server_cloud` 场景时，TaskManager 在 PLATFORM_ANALYSIS 阶段调 **LinuxFilesAnalyzer::analyzeServerCloudArtifacts**，产出写进任务目录的 `_oss.db`（TaskManagerAnalysis.cpp:502-517）；
- 该库经 ForensicsRoutes 族的通用查询（statistics/files 等）即可访问。

即：**OSS/云场景的分析能力活在任务流水线里，这组 REST 骨架从未接上它**。

## 7. 常见错误与边界（现状下的正确预期）

- 调 `/api/forensics/oss/*` 得到 Crow 的 404——不是任务不存在、不是权限问题；
- 前端 OSS 页报网络错误，根因同上；
- 不要因为 Swagger/openapi.json 里出现这些路径就认为可用（§5）；
- `OSSRoutes_new.cpp/h`（14 行）是另一层遗留残骸，同样未使用；
- 即便补上注册，§4.1 的占位实现与栈上析构问题意味着"能调通"也拿不到真数据——复活工作量比一行初始化大得多。

## 8. 处置建议（如何"复活"或了断）

- **复活**：实现 OSSAnalysisRoutes 的真实作业（run_analysis_job 需改为持久的作业表 + 真实分析，产出写入任务 `_oss.db`，status 端点读真状态；子路由对象改为 HTTPServer 成员持有，修掉 §4.1 的悬空 `this`）→ 在 HTTPserver.cpp:63-75 初始化列表加 `oss_routes_(app_)` 一行；Swagger 注册已就绪。
- **了断**：删除 OSSRoutes/OSSAnalysisRoutes/OSSQueryRoutes/OSSStatsRoutes/OSSRoutes_new 及前端 /oss 页入口，避免后来者反复踩坑；server/cloud 场景继续走 LinuxFilesAnalyzer 路径（本仓库已有文档口径：分析器在流水线中活跃）。

## 9. 端点全表（12 个，假设已注册的完整契约，二轮补全）

所有端点的请求/响应契约（从 handler 源码提取；**当前全部 404，此表是"复活时"或"对照前端"用的规格**）：

| 端点 | 方法 | 请求 | 响应（占位实现下） | 源码 |
|---|---|---|---|---|
| oss/analyze | POST | body：`task_id`（必填） | 202 `{success:true, message:"OSS analysis job started", job_id:"oss-XXXXXXXX", status:"pending"}`；400 task_id 缺失/JSON 坏 | OSSAnalysisRoutes.cpp:118-171 |
| oss/analyze/status | GET | query：`job_id`（必填） | 200 `{job_id, task_id, status:"completed", progress:100}`（**硬编码**）；404 Job not found；400 | :173-220 |
| oss/ai/filter | POST | （不读 body） | **恒 503** `{success:false, error:"Python LLM service not available", message:...Tasks 8-11...}` | :231-249 |
| oss/ai/analyze | POST | （不读 body） | 恒 503（同上文案） | :251-269 |
| oss/ai/status | GET | query：`job_id`（必填） | 恒 503 | :296-319 |
| oss/download | POST | body 设计含 bucket/key 等 | **恒 501** "not yet implemented" | :271-294 |
| oss/objects | GET | query：task_id（必填）、bucket、prefix、limit（默认 100，stoi 无钳制） | 200 `{task_id, bucket, prefix, objects:[], count:0, limit}`（空数组占位） | OSSQueryRoutes.cpp:28-65 |
| oss/logs | GET | query：task_id（必填）、start_time、end_time、operation | 200 `{task_id, start_time, end_time, operation, logs:[], count:0}` | :67-105 |
| oss/summary | GET | query：task_id（必填） | 200 `{task_id, total_objects:0, total_size:0, total_buckets:0, analyzed_at:<now ms>}`（全零） | OSSStatsRoutes.cpp:60-89 |
| oss/stats/storage-class | GET | task_id 必填 | 200 `stats:[]` 空数组 | :91+ |
| oss/stats/extensions | GET | task_id 必填 | 同上 | |
| oss/buckets | GET | task_id 必填 | 同上 | |

前端 ossService（ossService.js）9 个方法与上表一一对应（analyze/analyze/status/objects/logs/summary/stats×2/buckets）——**全部 404**；Services.md 所说"startAnalysis/getAnalysisStatus 可用"仅指前端函数无语法错误、轮询逻辑本身能跑，网络层照样 404。pollAnalysisStatus（:73 附近）在 FAILED 分支读 `status.error_message`——而占位 status 响应根本没有这个字段（只有 error），复活时的字段命名要对齐。

## 10. 新走读分支：占位实现的内存语义（假设已注册）

### 10.1 job_ids_ map 的生命周期缺陷（悬空 this 的补充细节）

analyze 的 202 响应真实可信地入表（job_ids_[job_id]=task_id，:138-142），后台线程 detach 跑 run_analysis_job。但如 §4.1 已记：三个子路由是聚合器构造函数的**栈对象**，构造结束即析构——`job_ids_`、`jobs_mutex_` 随之销毁。时间线上：析构发生在 HTTPServer 构造期（进程启动时），而 detach 的线程还要睡 100ms 再锁 mutex——**锁一个已析构的 mutex 是 UB**，即使进程没立刻崩，后续请求读 job_ids_ 也是悬空读。这比"拿不到真数据"更严重：是启动期的数据竞争，修复必须先把子路由改成成员（§8 复活步骤第一条）。

### 10.2 analyze/status 的"查无此 job"分支是唯一诚实的路径

handle_analyze_status（:173-220）是全组唯一有真实分支逻辑的 handler：job_id 缺失 400 → map 查不到 404 → 查到则硬编码 completed/100。也就是说若真注册，重启后所有 job 查询都会 404（map 是内存态），只有当次会话内提交的 job 能拿到假 completed——排障时"OSS 分析永远秒完成"是占位实现的直接证据。

### 10.3 查询/统计组的参数回显模式

objects/logs/summary 等查询端点把请求参数原样回显进响应（task_id/bucket/prefix/start_time...）再配空数组/零值——**响应形状是完整设计好的**（字段名、嵌套结构都定稿了），只差数据源。复活这些端点时不需要重新设计契约，把占位 JSON 换成从 `_oss.db` 查询的结果即可；前端 OSS.jsx 也已经按这套形状渲染。

## 11. 配置影响表（OSSRoutes 视角）

| 配置 | 默认 | 关系 | 说明 |
|---|---|---|---|
| `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` / `OSS_ENDPOINT` / `OSS_REGION` | 空/空/空/cn-hangzhou | **仅 Python 侧**（config.py:190-193） | C++ 这组路由不读任何 OSS 凭证——download 端点 501 的原因之一就是没有 OSSClient 接线；libs/aliyun-oss-cpp-sdk 已在仓库但未被路由引用 |
| `CORS_ALLOW_ORIGIN` | `*` | RouteHelpers | 各 handler 都调 add_cors_headers |
| （无 OSS 专有 C++ env） | — | — | C++ 侧 OSS 配置面为零 |

## 12. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 | 说明 |
|---|---|---|---|
| 无被调（404） | 前端 ossService 9 方法 | 全部 404 | Services.md 的 OSS 条目 |
| 无被调 | Swagger 注册 | **12 条注册永不执行**（子路由构造函数里的 RegisterEndpoint 随栈对象一起消失） | openapi.json 实际不含 OSS 路径——§5 的"可能出现"要修正：**一定不出现**，因为注册代码从未运行 |
| 设计依赖 | python oss_analysis.py | TODO 注释点名 | 未实现 |
| 设计依赖 | aliyun-oss-cpp-sdk | libs/ 已存在 | 未接线 |
| 平行实现 | LinuxFilesAnalyzer::analyzeServerCloudArtifacts | `_oss.db` 真实生产者 | 与本组无代码关联 |
| 遗留 | OSSRoutes_new.cpp/h | 14 行 | 另一层残骸 |
| 遗留 | OSSRoutes::generate_job_id | oss- 前缀 | 聚合器里这份从未被调（子类有自己的副本） |

**修正一条既有表述**：§5 说 openapi.json 里"可能出现这些路径"——按 §12 的推理链，子路由构造函数从未运行，RegisterEndpoint 从未执行，**openapi.json 实际不含任何 /api/forensics/oss/* 路径**（可用 `curl /api/docs/openapi.json | jq '.paths | keys | map(select(startswith("/api/forensics/oss")))'` 验证为空数组）。

## 13. OSSRoutes_new.cpp 全文（第二层残骸）

14 行的完整内容（另一份等价聚合器，同样未使用）：

```cpp
#include "OSSRoutes_new.h"
#include "OSSAnalysisRoutes.h"
#include "OSSQueryRoutes.h"
#include "OSSStatsRoutes.h"

namespace forensics {
OSSRoutes::OSSRoutes(crow::App<>& app) {
    OSSAnalysisRoutes analysis(app);
    OSSQueryRoutes query(app);
    OSSStatsRoutes stats(app);
}
} // namespace forensics
```

与 OSSRoutes.cpp 的差异：无 generate_job_id、无 task_manager_ 引用——纯粹的"三个栈对象组装"。同样命中 §10.1 的栈析构问题。两份聚合器 + 四个子路由文件 + 前端 ossService + OSS.jsx 页面 = 这套死代码的总表面积约 1000 行。

## 14. 前端 pollAnalysisStatus 与占位后端的协议错位（逐字段）

ossService.js:65-83 的轮询器与 §9 占位实现的字段契约对不上号的点：

| 前端读取 | 占位后端提供 | 错位后果 |
|---|---|---|
| `status.status === 'COMPLETED'`（大写） | `status: "completed"`（小写） | **永不 resolve**——即使端点活着也死循环轮询 |
| `status.error_message`（FAILED 分支） | `error`（无 error_message 键） | 拒绝时错误消息恒 undefined → 兜底文案 |
| onProgress(status) 透传整个响应 | `{job_id, task_id, status, progress}` | 页面若读 progress 可用（100），其余字段错位 |
| 无超时上限 | — | 配合永不 COMPLETED → 无限轮询（无 AbortSignal） |

也就是说：**就算把聚合器接回 HTTPServer，前端 OSS 页也用不了**——大小写与字段名两处协议错位需要同步修。这是"双层未完成"（§2）之外的第三层：前后端协议本身也没对齐过。

## 15. 处置核对清单（复活前的完整工单）

1. 删或并 OSSRoutes_new.cpp（与 OSSRoutes.cpp 二选一）；
2. 子路由改成员持有（修 §4.1/§10.1 悬空 this）；
3. run_analysis_job 换真实作业表（对接 `_oss.db` 或新建作业持久化）；
4. status 端点读真状态（不硬编码 completed）；
5. 前后端状态值大小写对齐（COMPLETED vs completed——建议跟全仓小写惯例）；
6. error_message/error 字段对齐；
7. HTTPServer 初始化列表加 oss_routes_；
8. openapi.json 重新核验（§12 的 12 条注册将开始生效）。

了断路径（删除）则对应删 5 个后端文件 + ossService.js + OSS.jsx + 路由注册（若有）+ 文档口径统一到 LinuxFilesAnalyzer 的 server_cloud 路径。

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
