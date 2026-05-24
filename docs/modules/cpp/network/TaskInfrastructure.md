# TaskInfrastructure - 任务基础设施组件

> **模块定位**: TaskManager 的内部支撑组件，负责任务执行、持久化、序列化和监控

---

## 1. 概述

TaskManager 的功能由以下组件协作完成：

| 组件 | 文件 | 职责 |
|------|------|------|
| TaskAnalysisRunner | `TaskAnalysisRunner.h` | 执行分析任务 |
| TaskPersistence | `TaskPersistence.h` | JSON 持久化 |
| TaskSerialization | `TaskSerialization.h` | JSON 序列化 |
| TaskWatchdog | `TaskWatchdog.h` | 检测停滞任务 |

---

## 2. TaskAnalysisRunner

### 位置

`src/network/HTTPServer/TaskAnalysisRunner.h`

### 功能

负责实际执行取证分析任务，包括进度跟踪和取消检查。

```cpp
class TaskAnalysisRunner {
public:
    explicit TaskAnalysisRunner(TaskManager& manager);

    // 执行分析任务
    void start_analysis(const std::string& task_id);

    // 检查任务是否被取消
    bool is_task_cancelled(const std::string& task_id) const;

private:
    // 根据阶段进度计算总体百分比
    int calculate_overall_percentage(TaskPhase phase, int phase_percentage);
};
```

### 阶段权重

| 阶段 | 权重 | 说明 |
|------|------|------|
| INITIALIZING | 5% | 初始化 |
| IMAGE_ANALYSIS | 30% | 镜像分析 |
| EVENT_EXTRACTION | 15% | 事件提取 |
| FILE_CLASSIFICATION | 20% | 文件分类 |
| LLM_ANALYSIS | 20% | LLM 分析 |
| ANDROID_ANALYSIS | 8% | 平台分析 |
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
3. 如果 `execution_start_time` 距今超过阈值（默认 2 小时）
4. 且 `phase_percentage` 未变化
5. 将任务标记为 FAILED
6. 调用 `save_callback` 持久化状态

---

## 6. 组件关系

```
TaskManager
    ├── TaskAnalysisRunner   (执行分析)
    ├── TaskPersistence      (持久化)
    ├── TaskSerialization    (序列化)
    └── TaskWatchdog         (监控)
```

这些组件是 TaskManager 的内部实现细节，外部代码不应直接使用。所有任务操作应通过 TaskManager 的公开 API 进行。

---

**最后更新**: 2026-05-19
