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

## 3. 核心概念与设计

### 3.1 作业模型：提交-轮询，不阻塞流水线

Graphiti 摄取可能比分析本身还久，所以所有 ingest 系方法都是**提交即返回 job_id**（PENDING 入队），由 Python 侧后台执行。C++ 不开线程等它——任务状态机在提交成功那一刻就与图谱摄取解耦（摄取失败不影响任务 COMPLETED，TaskManagerAnalysis.cpp:579-583）。

作业生命周期（`JobStatus.status`，LLMPythonProxy.h:38-52）：

```
PENDING → RUNNING → COMPLETED
                 ↘ FAILED / CANCELLED        is_complete() = 三种终态之一
```

### 3.2 方法面：五个 Graphiti 操作 + 两个管理操作

| 方法 | HTTP | 用途 |
|---|---|---|
| `async_ingest(task_id, mode)` | POST /api/graphiti/ingest | 任务级摄取；mode: full/files_only/events_only/single_file（LLMPythonProxy.h:15-33） |
| `async_ingest_file(file_id, task_id, force)` | POST /api/graphiti/ingest/file | 单文件更新（可要求先重分析） |
| `async_ingest_events(task_id, events)` | POST /api/graphiti/ingest/events | 同步时间线事件到已有文件实体 |
| `get_job_status(job_id)` | GET /api/graphiti/jobs/{id} | 查进度（progress 0-100 + current_phase） |
| `cancel_job(job_id)` | DELETE /api/graphiti/jobs/{id} | 取消运行/排队中的作业 |
| `isServiceAvailable()` | GET /health | Python 服务可达性（5s 超时） |
| `deleteGraphitiData(task_id)` | DELETE /api/graphiti/tasks/{id} | 删任务时清图谱；**200 与 404 都算成功**（"本来就 没有"也算删干净，LLMPythonProxy.cpp:36-37） |

### 3.3 错误哲学：返回空值，不抛异常

所有方法 catch-all 后返回 `""` / false / 带 error 字段的 JobStatus（如 get_job_status 失败时 status="not_found"/"error"，cpp:158-195）。调用方（TaskManager）只需判空，不必为代理层的网络细节写 try。副作用是**故障只剩 stderr 日志**，前端看不到图谱摄取失败——设计取舍。

### 3.4 wait_for_job_completion：同步等待的兜底

`wait_for_job_completion`（cpp:220-253）轮询直到终态或超时（默认 3s 间隔 / 3600s 上限），带进度回调。当前主流水线不使用它（fire-and-forget），它服务于需要"图谱就绪再继续"的调用方（如未来的同步导出场景）。

## 4. 工作流程走读

**任务完成 → 图谱更新**（TaskManagerAnalysis.cpp:558-583）：

1. 流水线尾声调 `proxy.async_ingest(task_id, IngestionMode::FULL)`；
2. 代理 POST /api/graphiti/ingest，解析响应里的 job_id 并打印日志（cpp:63-72）；失败返回空串；
3. TaskManager 把 job_id 写入 `task.graphiti_job_id` 并立即持久化（TaskManagerAnalysis.cpp:573-574）——前端可凭它在 Python 侧查摄取进度；
4. 若 Python 服务没起，仅打印 Warning + 审计 WARNING，任务照常 COMPLETED。

**删除任务 → 清理图谱**：`delete_task` 调 `deleteGraphitiData(id)`（TaskManager.cpp:340-341），Neo4j 中该任务的实体/关系被删除，避免图谱残留孤儿数据。

## 5. 与其他模块的协作

- **TaskManager**：两个触发点（完成摄取、删除清图）；job_id 借 AnalysisTask 持久化。
- **ConfigManager**：PYTHON_SERVICE_URL / PYTHON_HTTP_PORT。
- **Python FastAPI 服务**：真正的 Graphiti 编排（LLM 抽取实体、写 Neo4j）；另提供案件级分析（CaseManager 存其 job id）。
- **前端知识图谱页**：不经过本代理，直接调 Python 服务读图——本代理只服务 C++ 侧的写路径。

## 6. 注意事项与已知问题

- **job_id 无本地索引**：C++ 只在 AnalysisTask 上存最近一次 job_id；任务被删后 job 仍在 Python 侧运行片刻，属最终一致窗口。
- **失败只进日志**：Python 服务宕机时摄取静默丢失（不重试、不补偿）。若图谱完整性重要，需要外部对账（对比任务与图谱实体数）。
- **头文件注释的 deprecated 说法**：LLMPythonProxy.h:60-61 称 C++ LLMAnalysisService 已弃用——不准确，见 LLMAnalysisService.md §1 的澄清；反向地，本模块并非所有 LLM 流量的代理，只是 Graphiti 通道。
- **无连接复用**：每调用新建 httplib::Client，高频单文件摄取时可优化为复用连接。

## 7. 如何验证与扩展

- **验证**：起 Python 服务后跑完一个任务，stdout 应出现 "Triggered Graphiti ingestion ... job_id: ..."；`curl :8090/api/graphiti/jobs/<job_id>` 观察状态流转；停掉 Python 服务再跑任务，确认任务仍 COMPLETED 且日志只有 Warning。
- **扩展**：新增 Python 侧能力时，按现有模式加一个"POST 返回 job_id"的方法 + 可选的 get_job_status 复用；若要引入重试，建议只在 async_ingest 一处加（幂等由 Python 侧按 task_id 保证）。

**最后更新**: 2026-08-23（解释式重写）
