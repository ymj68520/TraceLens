# CaseManager - 案例管理器

> **模块定位**: 单例模式的案例管理器，将多个分析任务组织到一个取证案例中，支持跨镜像分析

---

## 1. 模块概述

### 位置

`src/network/HTTPServer/CaseManager.h`

### 设计目标

在复杂取证调查中，一个案件可能涉及多个磁盘镜像。CaseManager 将相关的分析任务组织到一个 `ForensicCase` 中，支持：
- 跨镜像关联分析
- 增量式任务添加
- 案例级别的状态管理和持久化

### 架构定位

```
CaseManager (单例)
    ↓
┌─────────────────────────────────┐
│  ForensicCase                   │
│  ├── task_ids[]                 │
│  ├── CaseStatus                 │
│  ├── cross_analysis_job_id      │
│  └── task_analysis_states{}     │
└─────────────────────────────────┘
    ↓
TaskManager (任务管理)
    ↓
LLMPythonProxy (跨镜像分析)
```

---

## 2. 数据结构

### ForensicCase

```cpp
struct ForensicCase {
    std::string id;                           // UUID
    std::string name;                         // 案例标题
    std::string description;                  // 案例描述（传递给 LLM）
    std::vector<std::string> task_ids;        // 包含的任务 ID 列表
    CaseStatus status;                        // OPEN, ANALYSING, COMPLETED, FAILED
    std::string cross_analysis_job_id;        // Python 后台任务 ID

    std::chrono::system_clock::time_point created_at;
    std::chrono::system_clock::time_point updated_at;

    // 增量分析字段
    std::string case_db_path;                 // 案例级状态数据库路径
    int total_files_analyzed = 0;             // 已分析文件总数
    std::map<std::string, TaskAnalysisState> task_analysis_states;
};
```

### CaseStatus

```cpp
enum class CaseStatus {
    OPEN,        // 任务仍在运行或未分析
    ANALYSING,   // 跨镜像 LLM 分析进行中
    COMPLETED,   // 跨镜像报告已生成
    FAILED       // 跨镜像分析失败
};
```

---

## 3. API 参考

### 获取实例

```cpp
auto& caseMgr = CaseManager::instance();
```

### CRUD 操作

```cpp
// 创建案例
std::string case_id = caseMgr.create_case(
    "Case 2024-001",
    "Data breach investigation",
    {"task_001", "task_002"}
);

// 添加任务到案例
caseMgr.add_task(case_id, "task_003");

// 获取案例
ForensicCase case = caseMgr.get_case(case_id);

// 获取所有案例
auto all_cases = caseMgr.get_all_cases();

// 删除案例（不删除包含的任务）
caseMgr.delete_case(case_id);
```

### 状态管理

```cpp
// 更新案例状态
caseMgr.update_status(case_id, CaseStatus::ANALYSING);

// 设置跨分析任务 ID
caseMgr.set_cross_analysis_job(case_id, "python_job_123");
```

### 持久化

```cpp
// 手动保存
caseMgr.save_cases();

// 加载（启动时自动调用）
caseMgr.load_cases();
```

案例数据持久化到 `data/cases.json`。

---

## 4. REST API

通过 `CaseCRUDRoutes` 暴露 HTTP 端点：

```bash
# 创建案例
POST /api/cases
{
    "name": "Case 2024-001",
    "description": "Data breach investigation",
    "task_ids": ["task_001", "task_002"]
}

# 获取所有案例
GET /api/cases

# 获取单个案例
GET /api/cases/{case_id}

# 添加任务到案例
POST /api/cases/{case_id}/tasks
{
    "task_id": "task_003"
}

# 删除案例
DELETE /api/cases/{case_id}

# 触发跨镜像分析
POST /api/cases/{case_id}/analyze
{
    "description": "Find connections between images"
}
```

---

## 5. 跨镜像分析流程

1. 用户创建案例并添加多个任务
2. 所有任务完成后，触发跨镜像分析
3. CaseManager 通过 LLMPythonProxy 调用 Python 服务
4. Python 服务执行：
   - 文件筛选和聚类
   - 跨镜像 LLM 分析
   - 生成综合报告
5. CaseManager 更新案例状态为 COMPLETED

---

**最后更新**: 2026-05-19
