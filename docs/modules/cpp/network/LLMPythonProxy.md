# LLMPythonProxy（src/network/HTTPServer/LLMPythonProxy.{h,cpp}）

> **一句话**：C++ 通往 Python FastAPI 服务的 HTTP 客户端单例——核心职责是 Graphiti 知识图谱摄取的异步作业（提交 job、查状态、取消、等待），顺带健康检查与按任务清图。

## 1. 为什么有这个模块

Graphiti（实体-关系知识图谱）的构建依赖 Python 生态（LLM 编排、Neo4j、社区检测等），C++ 进程不打算重写这套东西。于是职责切分为：**C++ 负责重活**（镜像解析、工件提取、SQLite 产出），**Python 负责智力活**（图谱化、案件级推理）。LLMPythonProxy 就是这两个世界之间唯一的双向通道，它把"跨进程异步作业"包装成 C++ 友好的同步函数 + 轮询 API。

## 2. 在系统中的位置

```
TaskManager::start_analysis (TaskManagerAnalysis.cpp:558-583)
    └─ 任务完成后 fire-and-forget ──POST /api/graphiti/ingest──▶ Python FastAPI (:8090)
TaskManager::delete_task (TaskManager.cpp:340)                        │
    └─ 删除任务时清图 ──DELETE /api/graphiti/tasks/{id}──▶          ▼
                                                       Graphiti → Neo4j 知识图谱
C++ 侧保存 job_id 于 AnalysisTask.graphiti_job_id（TaskManagerAnalysis.cpp:573）
前端 /knowledge-graph、/investigation 页 ←── 经 Python 侧查询图谱
```

- **base URL**：单例构造时取 `ConfigManager::getPythonServiceUrl()`（LLMPythonProxy.h:68-71），即环境变量 `PYTHON_SERVICE_URL`，默认 `http://localhost:8090`（PYTHON_HTTP_PORT，ConfigManager.cpp:142）。
- 客户端是 cpp-httplib，**每次调用新建 Client**（无连接池、无状态），超时按端点设置（连接 5-10s、读 10-30s）。
- 消费方矩阵：本代理只覆盖 **C++ 侧写路径**（提交摄取、取消、删图）；前端读图谱直接调 Python 服务；案件级 LLM 分析（multi_analysis）也走 Python 侧自己的路由，不经本代理。

## 3. 核心数据结构

### 3.1 IngestionMode：摄取范围的四个档位

```cpp
// src/network/HTTPServer/LLMPythonProxy.h:15-33
enum class IngestionMode {
    FULL,           // Ingest files, events, and all platform data with File entities
    FILES_ONLY,     // Update file entities only (skip events)
    EVENTS_ONLY,    // Sync events to existing files
    SINGLE_FILE     // Single file update
};

inline std::string to_string(IngestionMode mode) {
    switch (mode) {
        case IngestionMode::FULL: return "full";
        case IngestionMode::FILES_ONLY: return "files_only";
        case IngestionMode::EVENTS_ONLY: return "events_only";
        case IngestionMode::SINGLE_FILE: return "single_file";
        default: return "full";
    }
}
```

枚举在 C++ 侧 stringify 成小写串放进请求体（`{"task_id": ..., "mode": "full"}`），Python 侧按字符串分派。主流水线只用 FULL；FILES_ONLY/EVENTS_ONLY 为增量同步预留；SINGLE_FILE 配合 `async_ingest_file` 的 file_id 使用。

### 3.2 JobStatus：跨进程作业状态的镜像

```cpp
// src/network/HTTPServer/LLMPythonProxy.h:38-52
struct JobStatus {
    std::string job_id;
    std::string status;       // PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    int progress = 0;         // 0-100
    std::string current_phase;
    std::string created_at;
    std::string started_at;
    std::string completed_at;
    std::string error;
    nlohmann::json result;

    bool is_complete() const {
        return status == "COMPLETED" || status == "FAILED" || status == "CANCELLED";
    }
};
```

字段与 Python 侧 job 管理器的响应体一一对应；`status` 是字符串而非枚举，因此能承载三个**非 Python 协议内的本地哨兵值**：`"unknown"`（默认初值）、`"not_found"`（HTTP 非 200）、`"error"`（本地异常）——调用方判终态时必须把这三个也算进去，`wait_for_job_completion` 正是这么做的（§5.3）。

## 4. 核心概念与设计

### 4.1 作业模型：提交-轮询，不阻塞流水线

Graphiti 摄取可能比分析本身还久，所以所有 ingest 系方法都是**提交即返回 job_id**（PENDING 入队），由 Python 侧后台执行。C++ 不开线程等它——任务状态机在提交成功那一刻就与图谱摄取解耦（摄取失败不影响任务 COMPLETED，TaskManagerAnalysis.cpp:579-583）。

作业生命周期（`JobStatus.status`）：

```
PENDING → RUNNING → COMPLETED
                 ↘ FAILED / CANCELLED        is_complete() = 三种终态之一
```

### 4.2 方法面：五个 Graphiti 操作 + 两个管理操作

| 方法（真实签名） | HTTP | 用途与失败行为 |
|---|---|---|
| `std::string async_ingest(task_id, mode=FULL)` | POST /api/graphiti/ingest | 任务级摄取；解析响应 job_id 并打日志（cpp:63-72）；任何失败返回 `""` |
| `std::string async_ingest_file(int64_t file_id, task_id, force=false)` | POST /api/graphiti/ingest/file | 单文件更新；请求体字段名是 `update_analysis`（cpp:98-102），不是 force |
| `std::string async_ingest_events(task_id, const json& events)` | POST /api/graphiti/ingest/events | 事件批量同步；events 为 JSON 数组透传 |
| `JobStatus get_job_status(job_id)` | GET /api/graphiti/jobs/{id} | 查进度；非 200 → status="not_found"，异常 → "error"+error 文本（cpp:185-192） |
| `bool cancel_job(job_id)` | DELETE /api/graphiti/jobs/{id} | 取消；200 时还看响应体 `success` 字段，404 返回 false（cpp:205-211） |
| `bool isServiceAvailable()` | GET /health | 5s 超时探活；异常返回 false（cpp:12-23） |
| `bool deleteGraphitiData(task_id)` | DELETE /api/graphiti/tasks/{id} | 删任务时清图；**200 与 404 都算成功**（"本来就没有"也算删干净，LLMPythonProxy.cpp:36-37） |

### 4.3 错误哲学：返回空值，不抛异常

所有方法 catch-all 后返回 `""` / false / 带 error 字段的 JobStatus。调用方（TaskManager）只需判空，不必为代理层的网络细节写 try。副作用是**故障只剩 stderr 日志**，前端看不到图谱摄取失败——设计取舍。

## 5. 核心代码走读

### 5.1 提交：async_ingest

```cpp
// src/network/HTTPServer/LLMPythonProxy.cpp:49-86
std::string LLMPythonProxy::async_ingest(
    const std::string& task_id,
    IngestionMode mode)
{
    try {
        httplib::Client cli(python_service_url_);
        cli.set_connection_timeout(10);
        cli.set_read_timeout(30);

        nlohmann::json body = {
            {"task_id", task_id},
            {"mode", to_string(mode)}
        };

        auto res = cli.Post("/api/graphiti/ingest", body.dump(), "application/json");

        if (res && res->status == 200) {
            auto response = nlohmann::json::parse(res->body);
            if (response.contains("job_id")) {
                std::string job_id = response["job_id"].get<std::string>();
                std::cout << "LLMPythonProxy: Triggered Graphiti ingestion for task "
                          << task_id << ", job_id: " << job_id << std::endl;
                return job_id;
            }
        }

        if (res) {
            std::cerr << "LLMPythonProxy::async_ingest failed: HTTP "
                      << res->status << " - " << res->body << std::endl;
        } else {
            std::cerr << "LLMPythonProxy::async_ingest failed: connection error" << std::endl;
        }
    } catch (const std::exception& e) {
        std::cerr << "LLMPythonProxy::async_ingest exception: " << e.what() << std::endl;
    }

    return "";
}
```

三个观察：① 连接 10s / 读 30s——提交本身很快，30s 是给 Python 侧排队确认的余量；② **失败不重试**：HTTP 非 200、响应缺 job_id、连接错误、JSON 解析异常四条路全部直接落空串，唯一痕迹是 stderr（连接错误时连 body 都没有）；③ 成功路径的 stdout 日志（"Triggered Graphiti ingestion ... job_id: ..."）是运维确认链路活着的抓手（§8 验证就靠它）。`async_ingest_file` / `async_ingest_events` 是同构拷贝，仅 body 字段与端点不同。

### 5.2 查询：get_job_status 的三态语义

```cpp
// src/network/HTTPServer/LLMPythonProxy.cpp:158-195（节选）
JobStatus LLMPythonProxy::get_job_status(const std::string& job_id) {
    JobStatus status;
    status.job_id = job_id;
    status.status = "unknown";
    status.progress = 0;
    status.current_phase = "unknown";
    // ...
        if (res && res->status == 200) {
            auto response = nlohmann::json::parse(res->body);
            status.status = response.value("status", "unknown");
            status.progress = response.value("progress", 0);
            status.current_phase = response.value("current_phase", "");
            status.created_at = response.value("created_at", "");
            // ...
        } else {
            status.status = "not_found";
        }
    } catch (const std::exception& e) {
        std::cerr << "LLMPythonProxy::get_job_status exception: " << e.what() << std::endl;
        status.status = "error";
        status.error = e.what();
    }
    return status;
}
```

正常态从 Python 响应逐字段 `value()` 拷贝（缺字段容错）；非 200 折叠成 `"not_found"`；本地异常折叠成 `"error"`。**调用方无法区分"Python 说没有这个 job"和"Python 根本没起"**——两者都是终态处理（见下），排障要结合 isServiceAvailable()。

### 5.3 同步等待：wait_for_job_completion

```cpp
// src/network/HTTPServer/LLMPythonProxy.cpp:220-253（节选）
while (true) {
    auto elapsed = std::chrono::steady_clock::now() - start;
    if (elapsed > timeout) {
        std::cerr << "LLMPythonProxy: Timeout waiting for job completion" << std::endl;
        return false;
    }

    JobStatus status = get_job_status(job_id);

    if (progress_callback) {
        progress_callback(status.progress, status.current_phase);
    }

    if (status.status == "COMPLETED") {
        return true;
    } else if (status.status == "FAILED" || status.status == "CANCELLED" || status.status == "not_found") {
        if (!status.error.empty()) {
            std::cerr << "LLMPythonProxy: Job failed - " << status.error << std::endl;
        }
        return false;
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(poll_interval_ms));
}
```

默认 3s 间隔 / 3600s 上限（h:160-165 的参数默认值）；超时用 steady_clock 计量，不受系统时间跳变影响。注意终态判定把本地哨兵 `"not_found"` 与 FAILED/CANCELLED 同等对待，但 `"error"` 和 `"unknown"` **不在终态列表里**——Python 服务全程宕机时每轮 poll 都返回 "error"，循环会一直空转到 3600s 超时。当前主流水线不使用此方法（fire-and-forget），它服务于需要"图谱就绪再继续"的调用方（如未来的同步导出场景）。

### 5.4 调用方：TaskManager 的 fire-and-forget

```cpp
// src/network/HTTPServer/TaskManagerAnalysis.cpp:564-578（节选）
try {
    auto& proxy = forensics::LLMPythonProxy::instance();
    std::string graphiti_job_id = proxy.async_ingest(task_id, forensics::IngestionMode::FULL);

    if (!graphiti_job_id.empty()) {
        add_audit_log(task_id, "GRAPHITI_INGESTION",
            "Triggered Graphiti knowledge graph ingestion (job_id: " + graphiti_job_id + ")");

        // Store the Graphiti job ID for potential status tracking
        task.graphiti_job_id = graphiti_job_id;
        save_tasks_internal();
    } else {
        std::cerr << "Warning: Failed to trigger Graphiti ingestion for task " << task_id << std::endl;
        add_audit_log(task_id, "WARNING", "Failed to trigger Graphiti ingestion");
    }
}
```

job_id 写进 AnalysisTask 并立即持久化——前端可凭它在 Python 侧查摄取进度；空串只记 WARNING 审计，任务照常走向 COMPLETED（外层 catch 亦只记 WARNING，:579-583）。**删除任务 → 清理图谱**：`delete_task` 调 `deleteGraphitiData(id)`（TaskManager.cpp:340-341），Neo4j 中该任务的实体/关系被删除，避免图谱残留孤儿数据。

## 6. 与其他模块的协作

- **TaskManager**：两个触发点（完成摄取、删除清图）；job_id 借 AnalysisTask 持久化。
- **ConfigManager**：PYTHON_SERVICE_URL / PYTHON_HTTP_PORT（默认 8090）。
- **Python FastAPI 服务**：真正的 Graphiti 编排（LLM 抽取实体、写 Neo4j）；另提供案件级分析（CaseManager 存其 job id）。
- **前端知识图谱页**：不经过本代理，直接调 Python 服务读图——本代理只服务 C++ 侧的写路径。

## 7. 注意事项与已知问题

- **job_id 无本地索引**：C++ 只在 AnalysisTask 上存最近一次 job_id；任务被删后 job 仍在 Python 侧运行片刻，属最终一致窗口。
- **失败只进日志**：Python 服务宕机时摄取静默丢失（不重试、不补偿）。若图谱完整性重要，需要外部对账（对比任务与图谱实体数）。
- **头文件注释的 deprecated 说法**：LLMPythonProxy.h:60-61 称 C++ LLMAnalysisService 已弃用——不准确，见 LLMAnalysisService.md §1 的澄清；反向地，本模块并非所有 LLM 流量的代理，只是 Graphiti 通道。
- **无连接复用**：每调用新建 httplib::Client，高频单文件摄取时可优化为复用连接。
- **wait_for_job_completion 的 "error" 死等**：见 §5.3，服务宕机时空转到超时。

## 8. 如何验证与扩展

- **验证**：起 Python 服务后跑完一个任务，stdout 应出现 "Triggered Graphiti ingestion ... job_id: ..."；`curl :8090/api/graphiti/jobs/<job_id>` 观察状态流转；停掉 Python 服务再跑任务，确认任务仍 COMPLETED 且日志只有 Warning。
- **扩展**：新增 Python 侧能力时，按现有模式加一个"POST 返回 job_id"的方法 + 可选的 get_job_status 复用；若要引入重试，建议只在 async_ingest 一处加（幂等由 Python 侧按 task_id 保证）。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
