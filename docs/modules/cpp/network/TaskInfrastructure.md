# TaskInfrastructure - 任务基础设施组件

> **模块定位**: TaskManager 的内部支撑组件，负责任务执行、持久化、序列化和监控

---

## 1. 概述

TaskManager 的功能由以下组件协作完成：

| 组件 | 文件 | 职责 |
|------|------|------|
| TaskManager::start_analysis | `TaskManagerAnalysis.cpp` | 执行分析流水线（成员函数实现） |
| TaskPersistence | `TaskPersistence.h` | JSON 持久化 |
| TaskSerialization | `TaskSerialization.h` | JSON 序列化 |
| TaskWatchdog | `TaskWatchdog.h` | 检测停滞任务 |

> 注：`src/network/HTTPServer/TaskAnalysisRunner.h` 是一个**未被任何代码引用的遗留头文件**（无对应 .cpp、无 include），不要在其上开发；实际的阶段权重与进度计算在 `TaskManager.cpp::calculate_overall_percentage`。

---

## 2. 任务执行（TaskManagerAnalysis.cpp）

### 位置

`src/network/HTTPServer/TaskManagerAnalysis.cpp`（`TaskManager::start_analysis`，在 ThreadPool 的工作线程中运行）

### 功能

执行完整取证分析流水线，包括进度跟踪和取消检查（`cancellation_requested` 原子标志）。

### 阶段权重

`TaskManager.cpp::calculate_overall_percentage` 中的实际权重（总进度 = 已完成阶段权重之和 + 当前阶段 × 阶段内百分比）：

| 阶段 | 权重 | 说明 |
|------|------|------|
| INITIALIZING | 5% | 初始化 |
| IMAGE_ANALYSIS | 25% | 镜像分析 |
| EVENT_EXTRACTION | 10% | 事件提取 |
| FILE_CLASSIFICATION | 15% | 文件分类 |
| LLM_ANALYSIS | 20% | LLM 文件/事件簇分析 |
| PLATFORM_ANALYSIS | 20% | 平台分析（Android/Windows/Linux/Server） |
| FILE_CARVING | 3% | 签名雕刻 |
| FINALIZING | 2% | 完成 |

---

## 3. TaskPersistence

### 位置

`src/network/HTTPServer/TaskPersistence.h`

### 功能

任务状态的 JSON 文件持久化。

```cpp
class TaskPersistence {
public:
    // 保存任务到 JSON 文件
    static void save_tasks(
        const std::map<std::string, AnalysisTask>& tasks,
        const std::string& tasksPath
    );

    // 从 JSON 文件加载任务
    static void load_tasks(
        std::map<std::string, AnalysisTask>& tasks,
        const std::string& tasksPath,
        std::unordered_set<std::string>& runningTaskIds
    );

    // 清理孤立的任务目录
    static void cleanup_orphan_directories(
        const std::map<std::string, AnalysisTask>& tasks
    );
};
```

### 持久化时机

- 任务创建时
- 任务状态变更时
- 进度更新时（节流）
- 服务关闭时

### 恢复机制

启动时自动加载任务：
1. 从 JSON 文件读取任务列表
2. 将之前标记为 RUNNING/PENDING 的任务加入 `runningTaskIds`
3. 这些任务会被标记为 FAILED（因为进程已重启）
4. 清理不再存在的任务目录

---

## 4. TaskSerialization

### 位置

`src/network/HTTPServer/TaskSerialization.h`

### 功能

提供 `TaskProgress` 和 `AnalysisTask` 的 JSON 序列化/反序列化。

```cpp
namespace forensics {
    void to_json(nlohmann::json& j, const TaskProgress& p);
    void from_json(const nlohmann::json& j, TaskProgress& p);
    void to_json(nlohmann::json& j, const AnalysisTask& t);
    void from_json(const nlohmann::json& j, AnalysisTask& t);
}
```

### 序列化格式

```json
{
    "id": "task_abc123",
    "image_path": "/evidence/disk.E01",
    "status": "RUNNING",
    "priority": "HIGH",
    "progress": {
        "current_phase": "IMAGE_ANALYSIS",
        "phase_percentage": 45,
        "overall_percentage": 18,
        "phase_description": "Analyzing filesystem..."
    },
    "created_time": "2024-01-01T10:00:00Z",
    "llm_analyze": true,
    "llm_mode": "smart",
    "case_description": "Fraud investigation"
}
```

---

## 5. TaskWatchdog

### 位置

`src/network/HTTPServer/TaskWatchdog.h`

### 功能

监控停滞任务，每 60 秒检查一次。如果任务在 RUNNING 状态超过阈值时间而没有进度更新，将其标记为 FAILED。

```cpp
class TaskWatchdog {
public:
    TaskWatchdog(
        std::map<std::string, AnalysisTask>& tasks,
        const std::atomic<bool>& shutdown,
        std::function<void()> save_callback
    );

    // 运行看门狗循环
    void run();
};
```

### 检测逻辑

1. 每 60 秒遍历所有任务
2. 检查 RUNNING 状态的任务
3. 如果 RUNNING/PENDING 状态持续超过 `TASK_WATCHDOG_STALE_MINUTES`（默认 30 分钟）而无进度更新
4. 且 `phase_percentage` 未变化
5. 将任务标记为 FAILED
6. 调用 `save_callback` 持久化状态

---

## 6. 组件关系

```
TaskManager
    ├── TaskManagerAnalysis.cpp (start_analysis 执行分析流水线)
    ├── TaskPersistence      (持久化)
    ├── TaskSerialization    (序列化)
    └── TaskWatchdog         (监控)
```

这些组件是 TaskManager 的内部实现细节，外部代码不应直接使用。所有任务操作应通过 TaskManager 的公开 API 进行。

---

**最后更新**: 2026-08-23（以代码为准修正：TaskAnalysisRunner.h 为未引用遗留文件；阶段权重与阶段名对齐 TaskManager.cpp）
