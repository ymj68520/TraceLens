# C++ REST API 参考文档

## 概述

C++ HTTP 服务运行在端口 **8080**，提供高性能的取证分析、任务管理和数据库查询功能。

**服务器地址**：`http://localhost:8080`

**API 文档**：
- Swagger UI: http://localhost:8080/api/docs/ui
- OpenAPI JSON: http://localhost:8080/api/docs/openapi
- Endpoint 列表: http://localhost:8080/api/docs/endpoints

**路由文件结构**：

API 端点分布在 `src/network/HTTPServer/routes/` 下的 29 个独立路由文件中：

| 路由文件 | 功能域 | 端点数 |
|----------|--------|--------|
| `TaskCRUDRoutes.cpp` | 任务 CRUD | 12 |
| `TaskBatchRoutes.cpp` | 批量操作 | 3 |
| `TaskMonitoringRoutes.cpp` | 任务监控 | 4 |
| `CaseCRUDRoutes.cpp` | 案例管理 | 6 |
| `TimelineRoutes.cpp` | 时间线分析 | 11 |
| `EventClusterRoutes.cpp` | 事件簇分析 | 4 |
| `FileAnalysisRoutes.cpp` | 文件分析 | 5 |
| `FileExtractionRoutes.cpp` | 文件提取 | 3 |
| `DLLAnalysisRoutes.cpp` | DLL 分析 | 7 |
| `StatisticsRoutes.cpp` | 统计分析 | 4 |
| `AndroidForensicsRoutes.cpp` | Android 取证 | 4 |
| `ExportRoutes.cpp` | 数据导出（TOON/JSON/CSV） | 4 |
| `SearchRoutes.cpp` | 全文搜索 | 3 |
| `SystemHealthRoutes.cpp` | 健康检查 | 5 |
| `SystemInfoRoutes.cpp` | 系统信息 | 5 |
| `SystemDocsRoutes.cpp` | API 文档 | 1 |
| `SystemEventRoutes.cpp` | 系统事件 | 2 |
| `SceneQueryRoutes.cpp` | 场景查询 | 2 |
| `OSSAnalysisRoutes.cpp` | OSS 分析启动和 AI 分析 | 6 |
| `OSSQueryRoutes.cpp` | OSS 对象和日志查询 | 2 |
| `OSSStatsRoutes.cpp` | OSS 统计信息 | 4 |
| `FilterRoutes.cpp` | 文件过滤配置管理 | 5 |

完整路由参考见 [RouteReference.md](../modules/cpp/network/routes/RouteReference.md)。

---

## 目录

1. [任务管理 API](#1-任务管理-api)
2. [案例管理 API](#2-案例管理-api)
3. [取证分析 API](#3-取证分析-api)
4. [场景查询 API](#4-场景查询-api)
5. [DLL 分析 API](#5-dll-分析-api)
6. [OSS 对象存储分析 API](#6-oss-对象存储分析-api)
7. [文件过滤配置 API](#7-文件过滤配置-api)
8. [全文搜索 API](#8-全文搜索-api)
9. [系统信息 API](#9-系统信息-api)
10. [场景感知分析优化](#10-场景感知分析优化)

---

## 1. 任务管理 API

### POST /tasks

**描述**：创建新的取证分析任务。

**请求体**：
```json
{
  "image_path": "/path/to/evidence.E01",
  "case_name": "Case #123",
  "priority": "NORMAL",
  "scenarios": ["android", "windows"],
  "options": {
    "llm_analysis": true
  }
}
```

**参数说明**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `image_path` | string | ✅ | - | 磁盘镜像文件路径 |
| `case_name` | string | ❌ | - | 案例名称 |
| `priority` | string | ❌ | NORMAL | 任务优先级（LOW/NORMAL/HIGH/CRITICAL） |
| `scenarios` | array | ❌ | [] | 取证场景列表，见下方场景值 |
| `options` | object | ❌ | - | 分析选项 |

**取证场景值** (`scenarios`)：

| 值 | 说明 |
|------|------|
| `"android"` | Android 设备取证（SMS、联系人、通话记录、应用数据） |
| `"windows"` | Windows 系统取证（注册表、事件日志、Prefetch、浏览器历史） |
| `"linux"` | Linux 系统取证（系统日志、用户账户、Shell 历史、SSH） |
| `"server_cloud"` | 服务器/云环境取证（Docker、Nginx/Apache、K8s、云配置） |

> **场景感知优化**：指定场景后，文件分类阶段会自动为相关文件分配更高的场景优先级，LLM 分析阶段会优先处理场景相关的高优先级文件。详见 [场景感知分析优化](#场景感知分析优化)。

**分析选项**：

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `android_analyze` | boolean | false | 是否执行 Android 分析（已废弃，使用 `scenarios`） |
| `windows_analyze` | boolean | false | 是否执行 Windows 分析（已废弃，使用 `scenarios`） |
| `linux_analyze` | boolean | false | 是否执行 Linux 分析（已废弃，使用 `scenarios`） |
| `llm_analysis` | boolean | false | 是否执行 LLM 分析 |
| `file_carving` | boolean | false | 是否执行文件雕刻 |

> **向后兼容**：如果请求中没有 `scenarios` 但有 `android_analyze: true`，系统自动转换为 `scenarios: ["android"]`。

**响应**：
```json
{
  "success": true,
  "message": "Task created successfully",
  "data": {
    "task_id": "task_abc123",
    "status": "PENDING",
    "priority": "NORMAL",
    "created_at": "2024-01-16T10:00:00Z",
    "image_path": "/path/to/evidence.E01"
  },
  "timestamp": "Tue Jan 16 10:00:00 2024"
}
```

**HTTP 状态码**：
- `201` - 任务创建成功
- `400` - 请求参数无效
- `500` - 服务器内部错误

---

### GET /tasks/{task_id}

**描述**：获取指定任务的详细信息。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "id": "task_abc123",
    "case_name": "Case #123",
    "image_path": "/path/to/evidence.E01",
    "status": "RUNNING",
    "phase": "FILE_CLASSIFICATION",
    "priority": "NORMAL",
    "progress": 45,
    "error_message": "",
    "created_at": "2024-01-16T10:00:00Z",
    "started_at": "2024-01-16T10:00:05Z",
    "completed_at": null,
    "output_raw_db": "/output/task_abc123_raw.db",
    "output_events_db": "/output/task_abc123_events.db",
    "output_files_db": "/output/task_abc123_files.db",
    "metadata": {}
  }
}
```

**任务状态**：
- `PENDING` - 等待执行
- `RUNNING` - 正在运行
- `COMPLETED` - 已完成
- `FAILED` - 执行失败
- `CANCELLED` - 已取消

**任务阶段**：
- `INITIALIZING` - 初始化中
- `IMAGE_ANALYSIS` - 镜像分析
- `EVENT_EXTRACTION` - 事件提取
- `FILE_CLASSIFICATION` - 文件分类
- `LLM_ANALYSIS` - LLM 分析
- `ANDROID_ANALYSIS` - Android 分析
- `FINALIZING` - 完成中

---

### GET /tasks/{task_id}/results

**描述**：获取已完成任务的分析结果。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "task_id": "task_abc123",
    "status": "COMPLETED",
    "statistics": {
      "total_files": 50000,
      "deleted_files": 1500,
      "total_size": 10737418240,
      "duration_seconds": 300
    },
    "databases": [
      {
        "type": "raw",
        "path": "/output/task_abc123_raw.db",
        "size_bytes": 104857600
      },
      {
        "type": "events",
        "path": "/output/task_abc123_events.db",
        "size_bytes": 52428800
      },
      {
        "type": "files",
        "path": "/output/task_abc123_files.db",
        "size_bytes": 209715200
      }
    ]
  }
}
```

**HTTP 状态码**：
- `200` - 结果获取成功
- `202` - 任务仍在运行
- `404` - 任务不存在

---

### GET /api/tasks/list

**描述**：列出所有任务，支持过滤和分页。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `status` | string | ❌ | - | 按状态过滤 |
| `priority` | string | ❌ | - | 按优先级过滤 |
| `limit` | integer | ❌ | 50 | 返回结果数量 |
| `offset` | integer | ❌ | 0 | 分页偏移量 |

**响应**：
```json
{
  "success": true,
  "data": {
    "tasks": [
      {
        "id": "task_abc123",
        "case_name": "Case #123",
        "status": "COMPLETED",
        "priority": "NORMAL",
        "created_at": "2024-01-16T10:00:00Z"
      },
      {
        "id": "task_def456",
        "case_name": "Case #456",
        "status": "RUNNING",
        "priority": "HIGH",
        "created_at": "2024-01-16T11:00:00Z"
      }
    ],
    "total_count": 25,
    "pagination": {
      "limit": 50,
      "offset": 0,
      "has_more": false
    }
  }
}
```

---

### DELETE /api/tasks/{task_id}

**描述**：取消正在运行或等待中的任务。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 任务 ID |

**响应**：
```json
{
  "success": true,
  "message": "Task cancelled successfully",
  "data": {
    "task_id": "task_abc123",
    "previous_status": "RUNNING",
    "new_status": "CANCELLED"
  }
}
```

**HTTP 状态码**：
- `200` - 任务取消成功
- `400` - 任务无法取消（已完成或不存在）
- `500` - 服务器内部错误

---

### GET /api/tasks/{task_id}/progress

**描述**：获取任务的详细进度信息。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "task_id": "task_abc123",
    "status": "RUNNING",
    "phase": "FILE_CLASSIFICATION",
    "progress": 45,
    "phase_progress": 60,
    "estimated_time_remaining_seconds": 180,
    "started_at": "2024-01-16T10:00:00Z",
    "current_operation": "Classifying files...",
    "processed_files": 30000,
    "total_files": 50000
  }
}
```

---

### GET /api/tasks/statistics

**描述**：获取系统级任务统计信息。

**响应**：
```json
{
  "success": true,
  "data": {
    "total_tasks": 150,
    "by_status": {
      "PENDING": 10,
      "RUNNING": 5,
      "COMPLETED": 125,
      "FAILED": 8,
      "CANCELLED": 2
    },
    "by_priority": {
      "LOW": 30,
      "NORMAL": 100,
      "HIGH": 15,
      "CRITICAL": 5
    },
    "average_duration_seconds": 450,
    "total_processed_size_bytes": 1073741824000
  }
}
```

---

### POST /api/tasks/cleanup

**描述**：清理旧的已完成或失败的任务。

**请求体**：
```json
{
  "older_than_days": 30,
  "statuses": ["COMPLETED", "FAILED"],
  "delete_databases": true
}
```

**参数说明**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `older_than_days` | integer | ❌ | 7 | 清理多少天前的任务 |
| `statuses` | array | ❌ | 所有 | 要清理的任务状态列表 |
| `delete_databases` | boolean | ❌ | false | 是否删除相关数据库文件 |

**响应**：
```json
{
  "success": true,
  "message": "Cleanup completed",
  "data": {
    "tasks_deleted": 15,
    "databases_deleted": 45,
    "space_freed_bytes": 5368709120
  }
}
```

---

### POST /api/tasks/batch-create

**描述**：批量创建多个分析任务。

**请求体**：
```json
{
  "images": [
    "/path/to/evidence1.E01",
    "/path/to/evidence2.E01",
    "/path/to/evidence3.E01"
  ],
  "priority": "NORMAL",
  "options": {
    "android_analyze": true
  }
}
```

**响应**：
```json
{
  "success": true,
  "data": {
    "tasks": [
      {"task_id": "task_abc123", "image_path": "/path/to/evidence1.E01"},
      {"task_id": "task_def456", "image_path": "/path/to/evidence2.E01"},
      {"task_id": "task_ghi789", "image_path": "/path/to/evidence3.E01"}
    ],
    "total_created": 3
  }
}
```

---

### POST /api/tasks/batch-status

**描述**：批量获取多个任务的状态。

**请求体**：
```json
{
  "task_ids": [
    "task_abc123",
    "task_def456",
    "task_ghi789"
  ]
}
```

**响应**：
```json
{
  "success": true,
  "data": {
    "tasks": [
      {
        "task_id": "task_abc123",
        "status": "COMPLETED",
        "progress": 100
      },
      {
        "task_id": "task_def456",
        "status": "RUNNING",
        "progress": 45
      },
      {
        "task_id": "task_ghi789",
        "status": "FAILED",
        "error": "Disk read error"
      }
    ]
  }
}
```

---

### POST /api/tasks/batch-cancel

**描述**：批量取消多个任务。

**请求体**：
```json
{
  "task_ids": [
    "task_abc123",
    "task_def456"
  ]
}
```

**响应**：
```json
{
  "success": true,
  "data": {
    "results": [
      {"task_id": "task_abc123", "cancelled": true},
      {"task_id": "task_def456", "cancelled": false, "error": "Task already completed"}
    ],
    "total_cancelled": 1
  }
}
```

---

### GET /api/tasks/{task_id}/audit-log

**描述**：获取任务的审计日志。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "task_id": "task_abc123",
    "audit_log": [
      {
        "timestamp": "2024-01-16T10:00:00Z",
        "action": "TASK_CREATED",
        "user": "system",
        "details": "Task created by admin"
      },
      {
        "timestamp": "2024-01-16T10:00:05Z",
        "action": "PHASE_CHANGED",
        "user": "system",
        "details": "Phase changed from INITIALIZING to IMAGE_ANALYSIS"
      }
    ]
  }
}
```

---

### PUT /api/tasks/{task_id}/priority

**描述**：更新任务的优先级。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 任务 ID |

**请求体**：
```json
{
  "priority": "HIGH"
}
```

**响应**：
```json
{
  "success": true,
  "message": "Priority updated successfully",
  "data": {
    "task_id": "task_abc123",
    "previous_priority": "NORMAL",
    "new_priority": "HIGH"
  }
}
```

---

## 2. 案例管理 API

> 路由代码：`src/network/HTTPServer/routes/CaseCRUDRoutes.cpp`
> 案例管理器：`src/network/HTTPServer/CaseManager.h`

### GET /api/cases

**描述**：列出所有案例。

**响应**：
```json
{
  "success": true,
  "data": {
    "cases": [
      {
        "case_id": "case_001",
        "name": "Smith Investigation",
        "description": "Corporate fraud investigation",
        "status": "ACTIVE",
        "created_at": "2024-01-15T10:00:00Z",
        "task_count": 3
      }
    ],
    "total_count": 5
  }
}
```

---

### POST /api/cases

**描述**：创建新案例。

**请求体**：
```json
{
  "name": "Smith Investigation",
  "description": "Corporate fraud investigation",
  "tags": ["fraud", "corporate"]
}
```

**响应**：
```json
{
  "success": true,
  "data": {
    "case_id": "case_001",
    "name": "Smith Investigation",
    "status": "ACTIVE",
    "created_at": "2024-01-16T10:00:00Z"
  }
}
```

---

### GET /api/cases/{case_id}

**描述**：获取案例详情，包括关联的任务列表。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `case_id` | string | ✅ | 案例 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "case_id": "case_001",
    "name": "Smith Investigation",
    "description": "Corporate fraud investigation",
    "status": "ACTIVE",
    "created_at": "2024-01-15T10:00:00Z",
    "tasks": [
      {"task_id": "task_abc123", "image_path": "/evidence/disk1.E01", "status": "COMPLETED"},
      {"task_id": "task_def456", "image_path": "/evidence/disk2.E01", "status": "RUNNING"}
    ]
  }
}
```

---

### PUT /api/cases/{case_id}/tasks

**描述**：将任务添加到案例。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `case_id` | string | ✅ | 案例 ID |

**请求体**：
```json
{
  "task_id": "task_abc123"
}
```

---

### DELETE /api/cases/{case_id}

**描述**：删除案例（不删除关联的任务）。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `case_id` | string | ✅ | 案例 ID |

---

### PUT /api/cases/{case_id}/status

**描述**：更新案例状态。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `case_id` | string | ✅ | 案例 ID |

**请求体**：
```json
{
  "status": "CLOSED"
}
```

**案例状态**：
- `ACTIVE` - 活跃
- `CLOSED` - 已关闭
- `ARCHIVED` - 已归档

---

## 3. 取证分析 API

### Timeline Analysis

#### GET /api/forensics/timeline/comprehensive

**描述**：获取综合时间线（合并多个数据源）。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `start_time` | string | ❌ | - | 开始时间（ISO 8601） |
| `end_time` | string | ❌ | - | 结束时间（ISO 8601） |
| `limit` | integer | ❌ | 1000 | 最大事件数 |
| `event_types` | string | ❌ | - | 事件类型过滤（逗号分隔） |

**响应**：
```json
{
  "success": true,
  "data": {
    "task_id": "task_abc123",
    "timeline": [
      {
        "timestamp": "2024-01-15T10:30:00Z",
        "event_type": "FILE_CREATED",
        "description": "Created document.pdf",
        "source": "filesystem",
        "file_path": "/Users/john/Documents/document.pdf",
        "file_size": 2048576,
        "metadata": {}
      },
      {
        "timestamp": "2024-01-15T11:00:00Z",
        "event_type": "SMS_SENT",
        "description": "Sent SMS to +1234567890",
        "source": "android",
        "metadata": {
          "phone_number": "+1234567890",
          "message_preview": "Meeting at 3pm"
        }
      }
    ],
    "total_events": 5000,
    "time_range": {
      "start": "2024-01-01T00:00:00Z",
      "end": "2024-01-16T10:00:00Z"
    }
  }
}
```

---

#### GET /api/forensics/timeline/details

**描述**：获取特定时间簇的详细事件。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `cluster_id` | string | ✅ | - | 簇 ID |
| `limit` | integer | ❌ | 100 | 最大事件数 |

**响应**：
```json
{
  "success": true,
  "data": {
    "cluster_id": "cluster_123",
    "events": [
      {
        "id": 1,
        "timestamp": "2024-01-15T10:30:00Z",
        "event_type": "FILE_MODIFIED",
        "description": "Modified report.docx",
        "file_path": "/Users/john/Documents/report.docx"
      }
    ],
    "total_events": 50
  }
}
```

---

#### GET /api/forensics/timeline/distribution

**描述**：获取时间线事件的时间分布。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `granularity` | string | ❌ | hour | 时间粒度（hour/day/week/month） |

**响应**：
```json
{
  "success": true,
  "data": {
    "distribution": [
      {
        "time_bucket": "2024-01-15T10:00:00Z",
        "event_count": 150,
        "event_types": {
          "FILE_CREATED": 80,
          "FILE_MODIFIED": 50,
          "FILE_ACCESSED": 20
        }
      },
      {
        "time_bucket": "2024-01-15T11:00:00Z",
        "event_count": 120,
        "event_types": {
          "FILE_CREATED": 60,
          "FILE_MODIFIED": 40,
          "FILE_ACCESSED": 20
        }
      }
    ],
    "total_events": 5000
  }
}
```

---

#### GET /api/forensics/timeline/file-activity

**描述**：获取文件系统活动时间线。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `file_path` | string | ❌ | - | 文件路径过滤 |
| `limit` | integer | ❌ | 500 | 最大事件数 |

**响应**：
```json
{
  "success": true,
  "data": {
    "file_activity": [
      {
        "timestamp": "2024-01-15T10:30:00Z",
        "file_path": "/Users/john/Documents/report.docx",
        "action": "MODIFIED",
        "file_size": 1048576,
        "inode": 12345
      }
    ],
    "total_events": 1500
  }
}
```

---

#### GET /api/forensics/timeline/suspicious-patterns

**描述**：获取可疑活动模式。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "suspicious_events": [
      {
        "timestamp": "2024-01-15T02:00:00Z",
        "event_type": "FILE_DELETED",
        "severity": "HIGH",
        "description": "Sensitive file deleted at unusual time",
        "file_path": "/Users/john/Documents/secret.docx",
        "reason": "Deleted at 2 AM, outside normal working hours"
      },
      {
        "timestamp": "2024-01-15T15:30:00Z",
        "event_type": "FILE_CREATED",
        "severity": "MEDIUM",
        "description": "Executable created in temp directory",
        "file_path": "/tmp/unknown.exe",
        "reason": "Executable in temporary directory"
      }
    ],
    "total_suspicious": 15
  }
}
```

---

#### GET /api/forensics/timeline/user-activity

**描述**：获取用户活动时间线。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `user` | string | ❌ | - | 用户名过滤 |

**响应**：
```json
{
  "success": true,
  "data": {
    "user_activity": [
      {
        "timestamp": "2024-01-15T10:30:00Z",
        "user": "john",
        "activity_type": "FILE_ACCESS",
        "description": "Accessed confidential.pdf",
        "file_path": "/Users/john/Documents/confidential.pdf"
      }
    ],
    "total_activities": 300
  }
}
```

---

### Event Cluster Analysis

> 路由代码：`src/network/HTTPServer/routes/EventClusterRoutes.cpp`
> 分析器：`src/network/HTTPServer/EventClusterAnalyzer.h`

#### POST /api/forensics/timeline/clusters/analyze

**描述**：使用 LLM 分析事件簇，识别事件之间的关联和模式。

**请求体**：
```json
{
  "task_id": "task_abc123",
  "events": [
    {"timestamp": "2024-01-15T10:00:00Z", "event_type": "FILE_CREATED", "file_path": "/tmp/malware.exe"},
    {"timestamp": "2024-01-15T10:00:05Z", "event_type": "FILE_ACCESSED", "file_path": "/tmp/malware.exe"},
    {"timestamp": "2024-01-15T10:00:10Z", "event_type": "FILE_MODIFIED", "file_path": "/etc/hosts"}
  ]
}
```

**响应**：
```json
{
  "success": true,
  "data": {
    "cluster_id": "cluster_001",
    "analysis": {
      "summary": "Malware execution sequence detected",
      "risk_level": "HIGH",
      "patterns": ["file_creation_then_execution", "system_file_modification"],
      "recommendation": "Investigate malware.exe and hosts file changes"
    }
  }
}
```

---

#### POST /api/forensics/timeline/clusters/batch-analyze

**描述**：批量分析多个事件簇。

**请求体**：
```json
{
  "task_id": "task_abc123",
  "cluster_ids": ["cluster_001", "cluster_002", "cluster_003"]
}
```

---

#### POST /api/forensics/timeline/clusters/reanalyze

**描述**：重新分析已有的事件簇（使用更新的模型或参数）。

**请求体**：
```json
{
  "task_id": "task_abc123",
  "cluster_id": "cluster_001"
}
```

---

#### GET /api/forensics/timeline/clusters/analyzed

**描述**：获取已分析的事件簇列表。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `risk_level` | string | ❌ | - | 按风险级别过滤 |

---

### File Analysis

#### GET /api/forensics/files/largest

**描述**：获取镜像中最大的文件列表。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `limit` | integer | ❌ | 50 | 返回文件数 |

**响应**：
```json
{
  "success": true,
  "data": {
    "largest_files": [
      {
        "name": "database.db",
        "path": "/data/database.db",
        "size": 5368709120,
        "category": "databases",
        "deleted": false,
        "modified_time": "2024-01-15T10:00:00Z"
      },
      {
        "name": "backup.tar",
        "path": "/backup/backup.tar",
        "size": 2147483648,
        "category": "archives",
        "deleted": false,
        "modified_time": "2024-01-14T15:30:00Z"
      }
    ],
    "total_files": 50000
  }
}
```

---

#### GET /api/forensics/files/recent

**描述**：获取最近访问或修改的文件。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `sort_by` | string | ❌ | mtime | 排序字段（mtime/atime/ctime） |
| `limit` | integer | ❌ | 100 | 返回文件数 |

**响应**：
```json
{
  "success": true,
  "data": {
    "recent_files": [
      {
        "name": "document.docx",
        "path": "/Users/john/Documents/document.docx",
        "size": 1048576,
        "category": "documents",
        "modified_time": "2024-01-16T09:55:00Z",
        "accessed_time": "2024-01-16T10:00:00Z"
      }
    ],
    "total_files": 50000
  }
}
```

---

#### GET /api/forensics/files/suspicious

**描述**：获取可疑文件列表。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `limit` | integer | ❌ | 100 | 返回文件数 |

**响应**：
```json
{
  "success": true,
  "data": {
    "suspicious_files": [
      {
        "name": "hidden.exe",
        "path": "/Windows/Temp/hidden.exe",
        "size": 2048576,
        "category": "executables",
        "suspicion_reason": "Executable in temp directory",
        "severity": "HIGH"
      },
      {
        "name": "passwords.txt",
        "path": "/Users/john/passwords.txt",
        "size": 1024,
        "category": "documents",
        "suspicion_reason": "Filename contains sensitive keyword",
        "severity": "MEDIUM"
      }
    ],
    "total_suspicious": 25
  }
}
```

---

#### GET /api/forensics/files/duplicates

**描述**：获取重复文件列表（基于哈希值）。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `limit` | integer | ❌ | 50 | 返回组数 |

**响应**：
```json
{
  "success": true,
  "data": {
    "duplicate_groups": [
      {
        "hash": "a1b2c3d4e5f6",
        "size": 1048576,
        "count": 3,
        "files": [
          {
            "path": "/Users/john/Documents/report.docx",
            "modified_time": "2024-01-15T10:00:00Z"
          },
          {
            "path": "/Backup/report.docx",
            "modified_time": "2024-01-14T10:00:00Z"
          },
          {
            "path": "/Downloads/report.docx",
            "modified_time": "2024-01-13T10:00:00Z"
          }
        ],
        "wasted_space": 2097152
      }
    ],
    "total_wasted_space": 104857600
  }
}
```

---

#### GET /api/forensics/files/extensions-analysis

**描述**：获取文件扩展名统计分析。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "extension_stats": [
      {
        "extension": ".pdf",
        "count": 1500,
        "total_size": 5368709120,
        "average_size": 3579139,
        "category": "documents"
      },
      {
        "extension": ".jpg",
        "count": 8000,
        "total_size": 8589934592,
        "average_size": 1073741,
        "category": "images"
      }
    ],
    "total_extensions": 250,
    "total_files": 50000
  }
}
```

---

### File Extraction

#### POST /api/forensics/extract

**描述**：启动文件提取后台任务。

**请求体**：
```json
{
  "task_id": "task_abc123",
  "filters": {
    "extensions": [".pdf", ".docx", ".txt"],
    "patterns": ["*.log"],
    "categories": ["documents", "images"]
  },
  "output_dir": "/extracted_files",
  "preserve_structure": true
}
```

**参数说明**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `filters` | object | ❌ | - | 提取过滤条件 |
| `output_dir` | string | ❌ | - | 输出目录 |
| `preserve_structure` | boolean | ❌ | true | 是否保留目录结构 |

**响应**：
```json
{
  "success": true,
  "message": "Extraction job started",
  "data": {
    "job_id": "ext-12345678",
    "status": "RUNNING",
    "estimated_files": 5000
  }
}
```

---

#### GET /api/forensics/extract/status

**描述**：获取文件提取任务状态。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `job_id` | string | ✅ | - | 提取任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "job_id": "ext-12345678",
    "status": "RUNNING",
    "progress": 45,
    "files_extracted": 2250,
    "total_files": 5000,
    "bytes_extracted": 5368709120,
    "output_dir": "/extracted_files",
    "started_at": "2024-01-16T10:00:00Z",
    "estimated_completion": "2024-01-16T10:10:00Z"
  }
}
```

**提取状态**：
- `PENDING` - 等待开始
- `RUNNING` - 正在提取
- `COMPLETED` - 提取完成
- `FAILED` - 提取失败
- `CANCELLED` - 已取消

---

### Android Forensics

#### GET /api/forensics/android/communication-summary

**描述**：获取 Android 通信摘要（短信和通话）。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "communication": {
      "sms": {
        "total": 5000,
        "sent": 2500,
        "received": 2500,
        "top_contacts": [
          {
            "phone_number": "+1234567890",
            "message_count": 150,
            "last_contact": "2024-01-15T10:00:00Z"
          }
        ]
      },
      "calls": {
        "total": 1000,
        "incoming": 600,
        "outgoing": 400,
        "missed": 50,
        "total_duration_seconds": 18000
      }
    }
  }
}
```

---

#### GET /api/forensics/android/app-usage

**描述**：获取 Android 应用使用统计。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `limit` | integer | ❌ | 50 | 返回应用数 |

**响应**：
```json
{
  "success": true,
  "data": {
    "app_usage": [
      {
        "package_name": "com.whatsapp",
        "app_name": "WhatsApp",
        "usage_time_seconds": 3600,
        "last_used": "2024-01-16T09:00:00Z",
        "install_time": "2023-06-15T10:00:00Z"
      },
      {
        "package_name": "com.facebook.katana",
        "app_name": "Facebook",
        "usage_time_seconds": 2400,
        "last_used": "2024-01-16T08:30:00Z",
        "install_time": "2023-05-10T10:00:00Z"
      }
    ],
    "total_apps": 150
  }
}
```

---

#### GET /api/forensics/android/device-info

**描述**：获取 Android 设备信息。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "device_info": {
      "manufacturer": "Samsung",
      "model": "Galaxy S21",
      "android_version": "13",
      "build_number": "TP1A.220624.014",
      "serial_number": "R58CT123ABC",
      "imei": "123456789012345",
      "first_boot_time": "2023-01-15T10:00:00Z"
    }
  }
}
```

---

#### GET /api/forensics/android/media-analysis

**描述**：获取 Android 媒体文件分析。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "media_stats": {
      "images": {
        "count": 5000,
        "total_size": 5368709120,
        "formats": {
          "JPEG": 3000,
          "PNG": 1500,
          "GIF": 500
        }
      },
      "videos": {
        "count": 500,
        "total_size": 10737418240,
        "total_duration_seconds": 7200,
        "formats": {
          "MP4": 400,
          "AVI": 100
        }
      },
      "audio": {
        "count": 1000,
        "total_size": 2147483648,
        "total_duration_seconds": 10800,
        "formats": {
          "MP3": 800,
          "AAC": 200
        }
      }
    }
  }
}
```

---

### Statistics

#### GET /api/forensics/statistics/overview

**描述**：获取取证分析统计概览。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "overview": {
      "total_files": 50000,
      "deleted_files": 1500,
      "total_size": 107374182400,
      "file_categories": {
        "documents": 10000,
        "images": 15000,
        "videos": 2000,
        "audio": 3000,
        "archives": 5000,
        "executables": 2000,
        "databases": 500,
        "source_code": 3000,
        "web_files": 4000,
        "email_files": 1000,
        "system_files": 3000,
        "encrypted_files": 500,
        "unknown": 1000
      },
      "timeline_events": 25000,
      "android_artifacts": 5000,
      "windows_artifacts": 8000,
      "linux_artifacts": 2000
    }
  }
}
```

---

#### GET /api/forensics/statistics/file-distribution

**描述**：获取文件大小和类型分布统计。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "size_distribution": [
      {
        "range": "0-1KB",
        "count": 5000,
        "total_size": 2560000
      },
      {
        "range": "1KB-100KB",
        "count": 25000,
        "total_size": 524288000
      },
      {
        "range": "100KB-1MB",
        "count": 15000,
        "total_size": 5368709120
      },
      {
        "range": ">1MB",
        "count": 5000,
        "total_size": 101681099520
      }
    ],
    "type_distribution": {
      "documents": {"count": 10000, "percentage": 20},
      "images": {"count": 15000, "percentage": 30}
    }
  }
}
```

---

#### GET /api/forensics/statistics/activity-patterns

**描述**：获取活动模式统计。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "hourly_activity": [
      {"hour": 0, "event_count": 50},
      {"hour": 1, "event_count": 30},
      {"hour": 9, "event_count": 500},
      {"hour": 10, "event_count": 800}
    ],
    "daily_activity": [
      {"day": "2024-01-15", "event_count": 5000},
      {"day": "2024-01-16", "event_count": 6000}
    ],
    "peak_hours": [10, 11, 14, 15],
    "quiet_hours": [0, 1, 2, 3, 4, 5]
  }
}
```

---

#### GET /api/forensics/statistics/deleted-files-analysis

**描述**：获取已删除文件分析统计。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "deleted_files": {
      "total": 1500,
      "by_category": {
        "documents": 500,
        "images": 300,
        "videos": 100,
        "archives": 200
      },
      "recoverable": 1200,
      "total_size": 5368709120,
      "deletion_time_distribution": [
        {"date": "2024-01-15", "count": 100},
        {"date": "2024-01-14", "count": 80}
      ]
    }
  }
}
```

---

### Export

#### GET /api/forensics/export/toon

**描述**：导出取证数据为 TOON 格式（Token-Oriented Object Notation）。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `database_type` | string | ❌ | files | 数据库类型 |
| `include_llm` | boolean | ❌ | true | 包含 LLM 分析字段 |
| `limit` | integer | ❌ | 1000 | 最大记录数 |

**响应**：
```
TOON.schema: name | path | category | size | llm_summary | llm_keywords
# records[150]
document.pdf | /evidence/document.pdf | documents | 2048576 | 保密协议文档 | 保密,协议,合同
database.db | /evidence/database.db | databases | 5242880 | SQLite 数据库 | 数据库,SQLite
...
```

---

### Memory Forensics

> 路由代码：`src/network/HTTPServer/routes/MemoryForensicsRoutes.cpp`
> 数据来源：`--memory-analyze` 生成的 `<镜像名>_memory.db`（Volatility3）。
> 数据库以只读方式打开；若任务无 `_memory.db`，返回 `404 {"error":"memory db not found"}`。

所有端点均接受查询参数 `task_id`（string，必填）。

#### GET /api/forensics/memory/summary

**描述**：返回各表行数概览。

**响应**：
```json
{ "processes": 128, "network_connections": 34, "bash_history": 57, "sockets": 40 }
```

#### GET /api/forensics/memory/processes

**描述**：进程列表（来自 `linux.pslist`）。可选 `search` 参数按进程名过滤（已参数化绑定，防注入）。

**响应**：字段 `pid, ppid, comm, uid, state, thread_count`，最多 1000 行，按 `pid` 排序。

#### GET /api/forensics/memory/network

**描述**：网络连接（来自 `linux.sockstat`）。

**响应**：字段 `pid, comm, protocol, local_addr, local_port, foreign_addr, foreign_port, state`。

#### GET /api/forensics/memory/bash-history

**描述**：Bash 历史（来自 `linux.bash`）。可选 `keyword` 参数按命令过滤（参数化绑定）。

**响应**：字段 `pid, comm, command, history_index`。

#### GET /api/forensics/memory/boot-info

**描述**：启动信息（来自 `linux.boottime`）。

**响应**：键值对 `key, value`（如 `boot_time`）。

---

## 4. 场景查询 API

> 路由代码：`src/network/HTTPServer/routes/SceneQueryRoutes.cpp`

场景查询 API 提供对已完成任务的场景文件统计和场景制品查询功能。这些端点用于了解场景感知分析的结果，包括各场景的文件分布、相关文件数量和 LLM 分析覆盖情况。

### GET /api/tasks/{id}/scene-stats

**描述**：获取指定任务的场景文件统计信息，按场景类型分组。返回各场景的文件总数、相关文件数、总大小和 LLM 分析覆盖情况。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 任务 ID |

**响应**：
```json
{
  "task_id": "task_abc123",
  "scene_stats": [
    {
      "scene_type": "android",
      "total_files": 1500,
      "relevant_files": 450,
      "total_size": 1073741824,
      "llm_analyzed_files": 400
    },
    {
      "scene_type": "windows",
      "total_files": 3200,
      "relevant_files": 890,
      "total_size": 2147483648,
      "llm_analyzed_files": 750
    }
  ],
  "artifact_stats": [
    {
      "scene_type": "android",
      "artifact_count": 500,
      "analyzed_count": 420
    },
    {
      "scene_type": "windows",
      "artifact_count": 1200,
      "analyzed_count": 1050
    },
    {
      "scene_type": "linux",
      "artifact_count": 0,
      "analyzed_count": 0
    }
  ]
}
```

**响应字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID |
| `scene_stats` | array | 按场景类型分组的文件统计 |
| `scene_stats[].scene_type` | string | 场景类型（android/windows/linux/server_cloud） |
| `scene_stats[].total_files` | integer | 该场景下的文件总数 |
| `scene_stats[].relevant_files` | integer | 被标记为场景相关的文件数 |
| `scene_stats[].total_size` | integer | 文件总大小（字节） |
| `scene_stats[].llm_analyzed_files` | integer | 已完成 LLM 分析的文件数 |
| `artifact_stats` | array | 按场景类型分组的制品统计 |
| `artifact_stats[].scene_type` | string | 场景类型 |
| `artifact_stats[].artifact_count` | integer | 制品总数 |
| `artifact_stats[].analyzed_count` | integer | 已完成 LLM 分析的制品数 |

**HTTP 状态码**：
- `200` - 查询成功
- `400` - task_id 为空
- `404` - 任务不存在
- `500` - 服务器内部错误（数据库打开失败等）

**备注**：
- `scene_stats` 查询 `files` 表中 `scene_type IS NOT NULL` 的记录，按 `scene_type` 分组统计。
- `artifact_stats` 分别查询 `android_artifacts`、`windows_artifacts`、`linux_artifacts` 表。如果某个制品表不存在，对应的统计项会返回 `artifact_count: 0`。
- `llm_analyzed_files` 和 `analyzed_count` 通过 `llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0` 判断。

---

### GET /api/tasks/{id}/scene-artifacts

**描述**：获取指定任务中特定场景类型的制品列表，支持分页。返回制品详情及关联的源文件信息。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 任务 ID |

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `scene_type` | string | ✅ | - | 场景类型（`android`、`windows`、`linux`） |
| `limit` | integer | ❌ | 100 | 每页返回数量 |
| `offset` | integer | ❌ | 0 | 分页偏移量 |

**响应**：
```json
{
  "task_id": "task_abc123",
  "scene_type": "android",
  "artifacts": [
    {
      "id": 1,
      "file_id": 42,
      "artifact_type": "sms",
      "artifact_data": "{\"address\":\"+1234567890\",\"body\":\"Hello\",\"date\":\"2024-01-15T10:00:00Z\"}",
      "extracted_at": 1705312800,
      "llm_summary": "普通问候短信",
      "llm_description": "一条发送给 +1234567890 的短信，内容为 Hello",
      "llm_keywords": "短信,问候,通讯",
      "llm_analyzed_at": 1705312900,
      "llm_model_used": "qwen2.5-7b",
      "file_name": "mmssms.db",
      "file_path": "/data/data/com.android.providers.telephony/databases/mmssms.db",
      "file_size": 204800
    },
    {
      "id": 2,
      "file_id": 43,
      "artifact_type": "contact",
      "artifact_data": "{\"display_name\":\"John\",\"phone_number\":\"+1234567890\"}",
      "extracted_at": 1705312801,
      "llm_summary": "",
      "llm_description": "",
      "llm_keywords": "",
      "llm_analyzed_at": 0,
      "llm_model_used": "",
      "file_name": "contacts2.db",
      "file_path": "/data/data/com.android.providers.contacts/databases/contacts2.db",
      "file_size": 102400
    }
  ],
  "total": 500,
  "limit": 100,
  "offset": 0
}
```

**响应字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID |
| `scene_type` | string | 场景类型 |
| `artifacts` | array | 制品列表 |
| `artifacts[].id` | integer | 制品 ID |
| `artifacts[].file_id` | integer | 关联的源文件 ID（`files` 表外键） |
| `artifacts[].artifact_type` | string | 制品类型（如 sms、contact、call_log、registry 等） |
| `artifacts[].artifact_data` | string | 制品数据（JSON 字符串） |
| `artifacts[].extracted_at` | integer | 提取时间（Unix 时间戳） |
| `artifacts[].llm_summary` | string | LLM 生成的摘要 |
| `artifacts[].llm_description` | string | LLM 生成的详细描述 |
| `artifacts[].llm_keywords` | string | LLM 生成的关键词（逗号分隔） |
| `artifacts[].llm_analyzed_at` | integer | LLM 分析完成时间（Unix 时间戳，0 表示未分析） |
| `artifacts[].llm_model_used` | string | 分析使用的模型名称 |
| `artifacts[].file_name` | string | 源文件名 |
| `artifacts[].file_path` | string | 源文件路径 |
| `artifacts[].file_size` | integer | 源文件大小（字节） |
| `total` | integer | 该场景类型的制品总数 |
| `limit` | integer | 当前每页数量 |
| `offset` | integer | 当前偏移量 |

**HTTP 状态码**：
- `200` - 查询成功（包括制品表不存在时返回空列表）
- `400` - 参数错误（scene_type 缺失或无效）
- `404` - 任务不存在
- `500` - 服务器内部错误

**scene_type 有效值**：
- `android` - 查询 `android_artifacts` 表（SMS、联系人、通话记录等）
- `windows` - 查询 `windows_artifacts` 表（注册表、事件日志等）
- `linux` - 查询 `linux_artifacts` 表（系统日志、用户账户等）

> **安全说明**：`scene_type` 参数经过白名单验证（仅接受 android/windows/linux），防止 SQL 注入。制品表名通过字符串拼接构造，但因已验证输入值，不存在注入风险。

**分页示例**：
```bash
# 获取第一页（前 100 条 Android 制品）
curl "http://localhost:8080/api/tasks/task_abc123/scene-artifacts?scene_type=android&limit=100&offset=0"

# 获取第二页
curl "http://localhost:8080/api/tasks/task_abc123/scene-artifacts?scene_type=android&limit=100&offset=100"

# 获取 Windows 注册表制品
curl "http://localhost:8080/api/tasks/task_abc123/scene-artifacts?scene_type=windows&limit=50"
```

---

## 5. DLL 分析 API

> 路由代码：`src/network/HTTPServer/routes/DLLAnalysisRoutes.cpp`
> 分析器：`src/analyzers/DLLAnalyzer/Core/DLLAnalyzer.h`

### GET /api/forensics/dlls

**描述**：列出所有已分析的 DLL/共享库。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `limit` | integer | ❌ | 100 | 返回数量 |
| `offset` | integer | ❌ | 0 | 分页偏移 |

**响应**：
```json
{
  "success": true,
  "data": {
    "dlls": [
      {
        "id": 1,
        "name": "kernel32.dll",
        "path": "/Windows/System32/kernel32.dll",
        "size": 1048576,
        "format": "PE",
        "threat_score": 0.1,
        "is_signed": true,
        "anomaly_count": 0
      },
      {
        "id": 2,
        "name": "suspicious.dll",
        "path": "/tmp/suspicious.dll",
        "size": 512000,
        "format": "PE",
        "threat_score": 8.5,
        "is_signed": false,
        "anomaly_count": 3
      }
    ],
    "total_count": 150
  }
}
```

---

### GET /api/forensics/dlls/{dll_id}

**描述**：获取 DLL 详细信息，包括 PE/ELF 头、导入导出表、异常列表。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dll_id` | integer | ✅ | DLL 记录 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "id": 2,
    "name": "suspicious.dll",
    "path": "/tmp/suspicious.dll",
    "format": "PE",
    "pe_header": {
      "machine": "AMD64",
      "subsystem": "WINDOWS_GUI",
      "timestamp": "2024-01-10T08:00:00Z",
      "image_base": 0x10000000
    },
    "imports": ["kernel32.dll", "ntdll.dll", "ws2_32.dll"],
    "exports": ["DllMain", "InitConnection"],
    "sections": [
      {".text": {"size": 204800, "entropy": 6.5}},
      {".rdata": {"size": 102400, "entropy": 5.2}},
      {".data": {"size": 51200, "entropy": 3.1}}
    ],
    "threat_score": 8.5,
    "anomalies": [
      {"type": "HIGH_ENTROPY", "section": ".text", "severity": "HIGH"},
      {"type": "SUSPICIOUS_IMPORTS", "detail": "ws2_32.dll (network)", "severity": "MEDIUM"},
      {"type": "NO_SIGNATURE", "severity": "MEDIUM"}
    ]
  }
}
```

---

### GET /api/forensics/dlls/suspicious

**描述**：获取可疑 DLL 列表（威胁评分高于阈值）。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `threshold` | float | ❌ | 5.0 | 威胁评分阈值 |
| `limit` | integer | ❌ | 50 | 返回数量 |

---

### GET /api/forensics/dlls/statistics

**描述**：获取 DLL 分析统计信息。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "total_dlls": 150,
    "by_format": {"PE": 120, "ELF": 30},
    "by_risk": {"LOW": 100, "MEDIUM": 35, "HIGH": 12, "CRITICAL": 3},
    "signed_count": 85,
    "unsigned_count": 65,
    "average_threat_score": 2.3,
    "top_anomaly_types": [
      {"type": "HIGH_ENTROPY", "count": 15},
      {"type": "NO_SIGNATURE", "count": 65},
      {"type": "SUSPICIOUS_IMPORTS", "count": 8}
    ]
  }
}
```

---

### GET /api/forensics/dlls/{dll_id}/anomalies

**描述**：获取特定 DLL 的异常详情。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dll_id` | integer | ✅ | DLL 记录 ID |

---

### POST /api/forensics/dlls/analyze

**描述**：触发 DLL 分析任务。

**请求体**：
```json
{
  "task_id": "task_abc123",
  "verify_signatures": true,
  "threshold": 5.0
}
```

---

### GET /api/forensics/dlls/health

**描述**：DLL 分析服务健康检查。

**响应**：
```json
{
  "success": true,
  "data": {
    "status": "healthy",
    "pe_parser": "available",
    "elf_parser": "available",
    "database": "connected"
  }
}
```

---

## 6. OSS 对象存储分析 API

OSS（Object Storage Service）分析 API 提供阿里云 OSS 对象存储的取证分析能力，包括对象枚举、访问日志分析、AI 智能过滤和统计查询。

### POST /api/forensics/oss/analyze

**描述**：启动 OSS 分析任务。

**请求体**：
```json
{
  "access_key_id": "string",
  "access_key_secret": "string",
  "endpoint": "oss-cn-hangzhou.aliyuncs.com",
  "bucket": "my-bucket",
  "mode": "api|local|inventory|access_log",
  "local_path": "/path/to/local/data"
}
```

**响应**：
```json
{
  "success": true,
  "data": {
    "task_id": "uuid",
    "status": "running"
  }
}
```

### GET /api/forensics/oss/analyze/status

**描述**：获取 OSS 分析任务状态。

**查询参数**：`task_id` (string, required)

### POST /api/forensics/oss/ai/filter

**描述**：启动 AI 智能过滤 OSS 对象。

**请求体**：
```json
{
  "task_id": "string",
  "description": "查找与案件相关的文档",
  "model": "qwen2.5:7b"
}
```

### POST /api/forensics/oss/ai/analyze

**描述**：启动 AI 分析已过滤的 OSS 对象。

**请求体**：
```json
{
  "task_id": "string",
  "object_ids": [1, 2, 3],
  "model": "qwen2.5:7b"
}
```

### POST /api/forensics/oss/download

**描述**：下载 OSS 对象到本地进行分析。

**请求体**：
```json
{
  "task_id": "string",
  "object_key": "path/to/file.pdf"
}
```

### GET /api/forensics/oss/ai/status

**描述**：获取 AI 分析状态。

**查询参数**：`task_id` (string, required)

### GET /api/forensics/oss/objects

**描述**：查询 OSS 对象列表。

**查询参数**：
- `task_id` (string, required)
- `bucket` (string, optional)
- `prefix` (string, optional)
- `extension` (string, optional)
- `limit` (int, default 100)
- `offset` (int, default 0)

### GET /api/forensics/oss/logs

**描述**：获取 OSS 访问日志。

**查询参数**：
- `task_id` (string, required)
- `start_time` (int, optional)
- `end_time` (int, optional)
- `operation` (string, optional)

### GET /api/forensics/oss/summary

**描述**：获取 OSS 分析摘要统计。

**查询参数**：`task_id` (string, required)

### GET /api/forensics/oss/stats/storage-class

**描述**：获取存储类型统计。

**查询参数**：`task_id` (string, required)

### GET /api/forensics/oss/stats/extensions

**描述**：获取文件扩展名统计。

**查询参数**：`task_id` (string, required)

### GET /api/forensics/oss/buckets

**描述**：获取 Bucket 列表。

**查询参数**：`task_id` (string, required)

---

## 7. 文件过滤配置 API

文件过滤 API 提供过滤配置文件的管理和应用能力，支持按扩展名、路径模式、文件大小等条件过滤文件。

### GET /api/filter/profiles

**描述**：列出所有可用的过滤配置文件。

**响应**：
```json
{
  "success": true,
  "data": {
    "profiles": ["default", "documents_only", "images_only", "custom_profile"]
  }
}
```

### GET /api/filter/profiles/{name}

**描述**：获取指定过滤配置文件的详细信息。

**路径参数**：`name` (string) - 配置文件名称

**响应**：
```json
{
  "success": true,
  "data": {
    "name": "documents_only",
    "conditions": {
      "extensions": [".pdf", ".doc", ".docx"],
      "path_patterns": ["*/Documents/*"],
      "min_size": 0,
      "max_size": 104857600,
      "include_deleted": false
    },
    "combine_mode": "ExcludeWins"
  }
}
```

### POST /api/filter/profiles

**描述**：创建或更新过滤配置文件。

**请求体**：
```json
{
  "name": "custom_profile",
  "conditions": {
    "extensions": [".jpg", ".png", ".gif"],
    "path_patterns": ["*/Pictures/*", "*/Photos/*"],
    "min_size": 1024,
    "max_size": 52428800,
    "include_deleted": true,
    "include_allocated": true
  },
  "combine_mode": "ExcludeWins"
}
```

### DELETE /api/filter/profiles/{name}

**描述**：删除自定义过滤配置文件。

**路径参数**：`name` (string) - 配置文件名称

### POST /api/filter/apply

**描述**：将过滤配置应用到指定任务。

**请求体**：
```json
{
  "task_id": "string",
  "profile_name": "documents_only"
}
```

---

## 8. 全文搜索 API

### POST /api/search/index

**描述**：创建或更新全文搜索索引。

**请求体**：
```json
{
  "task_id": "task_abc123",
  "directory": "/extracted_files",
  "force_reindex": false
}
```

**参数说明**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `directory` | string | ✅ | - | 要索引的目录 |
| `force_reindex` | boolean | ❌ | false | 是否强制重新索引 |

**响应**：
```json
{
  "success": true,
  "message": "Indexing started",
  "data": {
    "job_id": "index-12345678",
    "directory": "/extracted_files",
    "estimated_files": 10000
  }
}
```

---

### GET /api/search

**描述**：执行全文搜索查询。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | ✅ | - | 搜索查询 |
| `task_id` | string | ❌ | - | 任务 ID |
| `path_filter` | string | ❌ | - | 路径过滤 |
| `extension_filter` | string | ❌ | - | 扩展名过滤 |
| `limit` | integer | ❌ | 100 | 最大结果数 |
| `offset` | integer | ❌ | 0 | 分页偏移量 |

**搜索语法**：
- `keyword` - 简单搜索
- `"exact phrase"` - 精确短语
- `keyword1 AND keyword2` - 与操作
- `keyword1 OR keyword2` - 或操作
- `keyword NOT excluded` - 非操作
- `key*` - 通配符
- `filename:.txt` - 字段搜索

**响应**：
```json
{
  "success": true,
  "data": {
    "query": "malware AND password",
    "total_matches": 150,
    "results": [
      {
        "file_path": "/extracted_files/report.txt",
        "score": 0.95,
        "snippet": "...detected <b>malware</b> with <b>password</b> stealing...",
        "file_size": 1024,
        "modified_time": "2024-01-15T10:00:00Z"
      },
      {
        "file_path": "/extracted_files/log.txt",
        "score": 0.85,
        "snippet": "...<b>malware</b> infection via stolen <b>password</b>...",
        "file_size": 2048,
        "modified_time": "2024-01-15T11:00:00Z"
      }
    ],
    "pagination": {
      "limit": 100,
      "offset": 0,
      "has_more": true
    }
  }
}
```

---

## 9. 系统信息 API

### Health Checks

#### GET /api/health

**描述**：基础健康检查。

**响应**：
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "Tue Jan 16 10:00:00 2024"
}
```

---

#### GET /api/health/live

**描述**：Kubernetes 存活探针。

**响应**：
```
OK
```

**HTTP 状态码**：
- `200` - 服务存活
- `503` - 服务不可用

---

#### GET /api/health/ready

**描述**：Kubernetes 就绪探针。

**响应**：
```json
{
  "status": "ready",
  "dependencies": {
    "database": "healthy",
    "task_manager": "healthy"
  }
}
```

**HTTP 状态码**：
- `200` - 服务就绪
- `503` - 服务未就绪

---

#### GET /api/health/dependencies

**描述**：检查依赖服务状态。

**响应**：
```json
{
  "success": true,
  "data": {
    "dependencies": [
      {
        "name": "SQLite",
        "status": "healthy",
        "details": "Database connections available"
      },
      {
        "name": "Xapian",
        "status": "healthy",
        "details": "Search index available"
      }
    ],
    "overall_status": "healthy"
  }
}
```

---

### System Information

#### GET /api/system/info

**描述**：获取系统信息。

**响应**：
```json
{
  "success": true,
  "data": {
    "version": "1.0.0",
    "build_date": "2024-01-15T10:00:00Z",
    "compiler": "GCC 11.4.0",
    "platform": "Linux",
    "architecture": "x86_64",
    "uptime_seconds": 3600,
    "memory_usage": {
      "current": 536870912,
      "peak": 1073741824
    },
    "active_tasks": 5,
    "total_tasks_processed": 150
  }
}
```

---

#### GET /api/system/databases

**描述**：列出任务的数据库文件。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |

**响应**：
```json
{
  "success": true,
  "data": {
    "task_id": "task_abc123",
    "databases": [
      {
        "type": "raw",
        "path": "/output/task_abc123_raw.db",
        "size_bytes": 104857600,
        "table_count": 3
      },
      {
        "type": "events",
        "path": "/output/task_abc123_events.db",
        "size_bytes": 52428800,
        "table_count": 8
      },
      {
        "type": "files",
        "path": "/output/task_abc123_files.db",
        "size_bytes": 209715200,
        "table_count": 15
      }
    ]
  }
}
```

---

#### GET /api/system/database-schema/{db_type}

**描述**：获取特定数据库类型的模式。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `db_type` | string | ✅ | 数据库类型（raw/events/files/android/windows/linux） |

**响应**：
```json
{
  "success": true,
  "data": {
    "database_type": "files",
    "schema": [
      {
        "table_name": "documents",
        "columns": [
          {"name": "id", "type": "INTEGER", "primary_key": true},
          {"name": "name", "type": "TEXT", "nullable": false},
          {"name": "path", "type": "TEXT", "nullable": false},
          {"name": "size", "type": "INTEGER", "nullable": false},
          {"name": "llm_summary", "type": "TEXT", "nullable": true}
        ]
      },
      {
        "table_name": "images",
        "columns": [
          {"name": "id", "type": "INTEGER", "primary_key": true},
          {"name": "name", "type": "TEXT", "nullable": false},
          {"name": "width", "type": "INTEGER", "nullable": true},
          {"name": "height", "type": "INTEGER", "nullable": true}
        ]
      }
    ]
  }
}
```

---

#### GET /api/system/logs

**描述**：获取系统日志。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `lines` | integer | ❌ | 100 | 返回行数 |
| `level` | string | ❌ | INFO | 日志级别 |

**响应**：
```json
{
  "success": true,
  "data": {
    "logs": [
      {
        "timestamp": "2024-01-16T10:00:00Z",
        "level": "INFO",
        "message": "Task task_abc123 started"
      },
      {
        "timestamp": "2024-01-16T10:00:05Z",
        "level": "INFO",
        "message": "Image analysis started"
      }
    ],
    "total_lines": 100
  }
}
```

---

### Documentation

#### GET /api/docs/endpoints

**描述**：获取所有 API 端点列表。

**响应**：
```json
{
  "success": true,
  "data": {
    "endpoints": [
      {
        "path": "/tasks",
        "method": "POST",
        "description": "Create a new analysis task",
        "tags": ["Tasks"]
      },
      {
        "path": "/api/forensics/timeline/comprehensive",
        "method": "GET",
        "description": "Get comprehensive timeline",
        "tags": ["Forensics", "Timeline"]
      }
    ],
    "total_endpoints": 83
  }
}
```

---

#### GET /api/docs/database-schema

**描述**：获取所有数据库模式的完整文档。

**响应**：
```json
{
  "success": true,
  "data": {
    "schemas": {
      "raw": {
        "description": "Raw file system metadata",
        "tables": ["files", "partitions"]
      },
      "events": {
        "description": "Timeline events",
        "tables": ["events", "creation_events", "modification_events"]
      },
      "files": {
        "description": "Classified files by type",
        "tables": ["documents", "images", "videos", "executables"]
      }
    }
  }
}
```

---

#### GET /api/docs/openapi

**描述**：获取 OpenAPI/Swagger JSON 规范。

**响应**：OpenAPI 3.0 JSON 规范

---

#### GET /api/docs/ui

**描述**：获取 Swagger UI HTML 页面。

**响应**：HTML 页面（Swagger UI）

---

### Export

#### GET /api/export/results/{task_id}

**描述**：导出任务结果。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 任务 ID |

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `format` | string | ❌ | json | 导出格式（json/csv/toon） |
| `include_llm` | boolean | ❌ | true | 包含 LLM 分析 |

**响应**：
```json
{
  "success": true,
  "data": {
    "task_id": "task_abc123",
    "format": "json",
    "results": [
      {
        "name": "document.pdf",
        "path": "/evidence/document.pdf",
        "category": "documents",
        "size": 2048576,
        "llm_summary": "Legal document"
      }
    ],
    "total_results": 50000
  }
}
```

---

## 错误响应

所有 API 在出错时返回以下格式：

```json
{
  "success": false,
  "message": "错误描述",
  "error_code": "ERROR_CODE",
  "timestamp": "Tue Jan 16 10:00:00 2024"
}
```

**常见 HTTP 状态码**：

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 202 | 已接受（任务异步执行） |
| 204 | 无内容（DELETE 成功） |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |
| 503 | 服务不可用 |

---

## CORS 支持

所有端点支持 CORS（跨域资源共享）：

**响应头**：
```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization, X-Requested-With
```

---

## 速率限制

当前版本未实施速率限制。建议在生产环境中通过反向代理（如 Nginx）添加速率限制保护。

---

## 认证

当前版本未实施认证机制。建议在生产环境中添加以下认证方式之一：

- **JWT Token**: 基于 JSON Web Token 的认证
- **API Key**: API 密钥认证
- **OAuth 2.0**: 标准 OAuth 2.0 授权框架

---

## 10. 场景感知分析优化

场景感知分析是本工具的核心优化特性，通过在任务创建时指定取证场景（`scenarios` 参数），系统会在分析管线的多个阶段自动优化处理策略。

### 场景类型

| 场景 | 值 | 关键路径/文件 | 分析器 |
|------|-----|--------------|--------|
| Android | `android` | `/data/data/com.android.providers.*`、`.db` 文件 | `AndroidAnalyzer` |
| Windows | `windows` | `Windows/System32/config`、`.evtx`、`Prefetch` | `WindowsFilesAnalyzer` |
| Linux | `linux` | `/var/log`、`/etc`、`.bash_history`、`/home` | `LinuxFilesAnalyzer` |
| 服务器/云 | `server_cloud` | `/var/lib/docker`、`/etc/nginx`、`/etc/kubernetes` | `LinuxFilesAnalyzer`（扩展） |

### 优化阶段

#### 1. 文件分类阶段

在文件分类阶段（`FileClassifier`），系统根据选定的场景对每个文件计算**场景优先级**（`scene_priority`）和**场景相关性**（`scene_relevant`）：

- **scene_priority**（0-100）：文件与场景的关联程度
  - `CRITICAL` (100)：场景核心数据文件（如 Android 的 SMS 数据库）
  - `HIGH` (75)：场景重要辅助文件（如 Android 的联系人数据库）
  - `MEDIUM` (50)：场景一般相关文件（如 Android 的应用 APK）
  - `LOW` (25)：场景边缘相关文件（如通用配置文件）
  - `IRRELEVANT` (0)：与场景无关

- **scene_relevant**（布尔值）：文件是否值得在当前场景下深入分析

这些值存储在 `files` 表的 `scene_type`、`scene_priority`、`scene_relevant` 字段中。

#### 2. LLM 分析阶段

LLM 分析服务根据场景优先级对文件进行排序，优先分析高优先级的场景相关文件：

```
分析顺序：CRITICAL (100) → HIGH (75) → MEDIUM (50) → LOW (25)
```

这确保在有限的 LLM 分析时间内，最有价值的场景文件得到优先处理。

#### 3. 制品提取阶段

平台分析器（Android/Windows/Linux/Server）将提取的制品存入场景专属的制品表：

| 场景 | 制品表 | 制品类型 |
|------|--------|---------|
| Android | `android_artifacts` | sms, contact, call_log, app_usage, device_info, media |
| Windows | `windows_artifacts` | registry, event_log, prefetch, browser_history, jump_list |
| Linux | `linux_artifacts` | system_log, user_account, shell_history, auth_data, cron_job |
| 服务器/云 | `linux_artifacts` | docker_container, nginx_config, k8s_config, ci_pipeline |

### 查询场景分析结果

通过以下 API 端点查询场景分析结果：

1. **查看场景统计**：`GET /api/tasks/{id}/scene-stats`
   - 了解各场景的文件分布和 LLM 分析覆盖情况

2. **浏览场景制品**：`GET /api/tasks/{id}/scene-artifacts?scene_type=android`
   - 分页查看特定场景的所有提取制品

### 最佳实践

1. **明确选择场景**：创建任务时明确指定 `scenarios` 参数，而不是依赖旧版 `android_analyze` 标志
2. **多场景组合**：对于混合环境（如同时包含 Android 和 Windows 数据的镜像），可同时指定多个场景
3. **监控 LLM 覆盖**：通过 `scene-stats` 端点检查 `llm_analyzed_files` 与 `relevant_files` 的比率，评估分析覆盖度
4. **按需查询制品**：使用分页参数 (`limit`/`offset`) 避免一次加载过多制品数据

---

## 相关文档

- **[Python REST API 参考](./Python_REST_API.md)** - Python 服务 API
- **[快速入门指南](../getting-started/QuickStart.md)** - 服务启动和使用
- **[HTTPServer 模块文档](../modules/cpp/network/HTTPServer.md)** - C++ HTTP 服务器架构
- **[TaskManager 模块文档](../modules/cpp/network/TaskManager.md)** - 任务管理器
- **[取证场景选择](../features/forensic-scenario-selection.md)** - 场景选择系统详细设计

---

**最后更新**: 2026-06-06
**维护者**: ymj68520
