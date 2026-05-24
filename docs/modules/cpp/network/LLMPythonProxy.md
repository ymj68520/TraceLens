# LLMPythonProxy - Python LLM 服务代理

> **模块定位**: C++ 与 Python FastAPI 服务之间的 HTTP 代理，转发 LLM 分析和 Graphiti 知识图谱请求

---

## 1. 模块概述

### 位置

`src/network/HTTPServer/LLMPythonProxy.h`

### 设计目标

C++ 服务器专注于高性能分析，而 LLM 和知识图谱操作由 Python 服务处理。LLMPythonProxy 提供：
- 透明的 HTTP 代理层
- 异步任务管理（fire-and-forget + 轮询）
- 服务健康检查
- 统一的错误处理

### 架构定位

```
C++ Server (port 8080)
    ↓
LLMPythonProxy (HTTP 客户端)
    ↓
Python FastAPI (port 8090)
    ↓
┌─────────────────────────────┐
│  LLM Service                │
│  Graphiti Service           │
│  Database Service           │
└─────────────────────────────┘
```

---

## 2. 数据结构

### IngestionMode

```cpp
enum class IngestionMode {
    FULL,          // 完整摄取（文件 + 事件 + 平台数据）
    FILES_ONLY,    // 仅更新文件实体
    EVENTS_ONLY,   // 仅同步事件
    SINGLE_FILE    // 单文件更新
};
```

### JobStatus

```cpp
struct JobStatus {
    std::string job_id;
    std::string status;        // PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    int progress = 0;          // 0-100
    std::string current_phase;
    std::string created_at;
    std::string started_at;
    std::string completed_at;
    std::string error;
    nlohmann::json result;

    bool is_complete() const;  // status == COMPLETED/FAILED/CANCELLED
};
```

---

## 3. API 参考

### 获取实例

```cpp
auto& proxy = LLMPythonProxy::instance();
```

### 案例分析

```cpp
// 启动跨镜像案例分析
std::string job_id = proxy.startCaseAnalysis(
    "task_123",
    "/output/files.db",
    "Data breach investigation",
    200  // 最大文件数
);

// 轮询状态
auto status = proxy.getCaseAnalysisStatus(job_id);

// 等待完成（带进度回调）
bool success = proxy.waitForCompletion(
    job_id,
    [](const std::string& step, const std::string& detail) {
        std::cout << step << ": " << detail << std::endl;
    },
    3000,   // 轮询间隔 (ms)
    3600    // 超时 (秒)
);
```

### Graphiti 知识图谱

```cpp
// 触发摄取（异步）
std::string job_id = proxy.async_ingest("task_123", IngestionMode::FULL);

// 单文件摄取
std::string job_id = proxy.async_ingest_file(456, "task_123", false);

// 事件摄取
nlohmann::json events = R"([{"type": "CREATED", "file": "test.txt"}])"_json;
std::string job_id = proxy.async_ingest_events("task_123", events);

// 查询任务状态
JobStatus status = proxy.get_job_status(job_id);

// 取消任务
proxy.cancel_job(job_id);

// 等待完成
bool success = proxy.wait_for_job_completion(job_id, progressCallback);

// 删除知识图谱数据
proxy.deleteGraphitiData("task_123");
```

### 服务状态

```cpp
// 检查 Python 服务是否可用
bool available = proxy.isServiceAvailable();
```

---

## 4. 配置

Python 服务 URL 通过 ConfigManager 配置：

```env
# .env
PYTHON_SERVICE_URL=http://localhost:8090
```

---

## 5. 错误处理

- HTTP 连接失败：返回空字符串或空 JSON
- 服务不可用：`isServiceAvailable()` 返回 false
- 任务超时：`waitForCompletion()` 返回 false
- 所有 HTTP 错误会被捕获并记录到日志

---

## 6. 与旧版 LLMAnalysisService 的关系

- **LLMAnalysisService**: 直接在 C++ 中调用 LLM API（已弃用）
- **LLMPythonProxy**: 通过 Python 服务间接调用 LLM（推荐）

新功能应使用 LLMPythonProxy，旧版 LLMAnalysisService 保留以兼容现有代码。

---

**最后更新**: 2026-05-19
