# C++ REST API 路由参考

> 本文档列出 C++ Crow 服务器（端口 8080）的所有 REST API 端点。
> 路由代码位于 `src/network/HTTPServer/routes/` 目录下。

---

## 任务管理

### TaskCRUDRoutes (`TaskCRUDRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/tasks` | 列出所有任务（兼容端点） |
| POST | `/tasks` | 创建任务（兼容端点） |
| GET | `/tasks/{task_id}` | 获取任务详情（兼容端点） |
| GET | `/tasks/{task_id}/results` | 获取任务结果（兼容端点） |
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/list` | 列出所有任务（带筛选） |
| POST | `/api/tasks` | 创建分析任务 |
| GET | `/api/tasks/{task_id}` | 获取任务详情 |
| PUT | `/api/tasks/{task_id}` | 更新任务 |
| DELETE | `/api/tasks/{task_id}` | 取消/删除任务 |
| POST | `/api/tasks/cleanup` | 清理已完成任务 |
| GET | `/api/tasks/{task_id}/databases` | 获取任务关联的数据库列表 |

### TaskBatchRoutes (`TaskBatchRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/tasks/batch-create` | 批量创建任务 |
| POST | `/api/tasks/batch-status` | 批量查询任务状态 |
| POST | `/api/tasks/batch-cancel` | 批量取消任务 |

### TaskMonitoringRoutes (`TaskMonitoringRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/tasks/{task_id}/progress` | 获取任务进度 |
| GET | `/api/tasks/{task_id}/audit-log` | 获取任务审计日志 |
| GET | `/api/tasks/statistics` | 获取任务统计信息 |
| PUT | `/api/tasks/{task_id}/priority` | 更新任务优先级 |

---

## 案例管理

### CaseCRUDRoutes (`CaseCRUDRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/cases` | 列出所有案例 |
| POST | `/api/cases` | 创建案例 |
| GET | `/api/cases/{case_id}` | 获取案例详情 |
| PUT | `/api/cases/{case_id}/tasks` | 添加任务到案例 |
| DELETE | `/api/cases/{case_id}` | 删除案例 |
| PUT | `/api/cases/{case_id}/status` | 更新案例状态 |

---

## 时间线分析

### TimelineRoutes (`TimelineRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/timeline/comprehensive` | 综合时间线 |
| GET | `/api/forensics/timeline/details` | 时间线详情（簇内事件） |
| GET | `/api/forensics/timeline/distribution` | 时间线分布统计 |
| GET | `/api/forensics/timeline/file-activity` | 文件活动时间线 |
| GET | `/api/forensics/timeline/suspicious-patterns` | 可疑模式检测 |
| GET | `/api/forensics/timeline/user-activity` | 用户活动分析 |
| GET | `/api/forensics/timeline/by-type` | 按事件类型筛选 |
| GET | `/api/forensics/timeline/by-time-range` | 按时间范围筛选 |
| GET | `/api/forensics/timeline/by-file` | 按文件筛选 |
| GET | `/api/forensics/timeline/full` | 完整时间线 |
| GET | `/api/forensics/timeline/statistics-by-period` | 按时间段统计 |

### EventClusterRoutes (`EventClusterRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/forensics/timeline/clusters/analyze` | 分析事件簇 |
| POST | `/api/forensics/timeline/clusters/batch-analyze` | 批量分析事件簇 |
| POST | `/api/forensics/timeline/clusters/reanalyze` | 重新分析事件簇 |
| GET | `/api/forensics/timeline/clusters/analyzed` | 获取已分析的事件簇 |

---

## 文件分析

### FileAnalysisRoutes (`FileAnalysisRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/files/largest` | 最大文件列表 |
| GET | `/api/forensics/files/recent` | 最近修改的文件 |
| GET | `/api/forensics/files/suspicious` | 可疑文件 |
| GET | `/api/forensics/files/duplicates` | 重复文件 |
| GET | `/api/forensics/files/extensions-analysis` | 文件扩展名分析 |

### FileExtractionRoutes (`FileExtractionRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/forensics/extract` | 启动文件提取任务 |
| GET | `/api/forensics/extract/{job_id}` | 查询提取任务状态 |
| GET | `/api/forensics/extract/status` | 查询所有提取任务状态 |

---

## DLL 分析

### DLLAnalysisRoutes (`DLLAnalysisRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/dlls` | 列出所有分析的 DLL |
| GET | `/api/forensics/dlls/{dll_id}` | 获取 DLL 详情 |
| GET | `/api/forensics/dlls/suspicious` | 获取可疑 DLL |
| GET | `/api/forensics/dlls/statistics` | DLL 分析统计 |
| GET | `/api/forensics/dlls/{dll_id}/anomalies` | 获取 DLL 异常 |
| POST | `/api/forensics/dlls/analyze` | 触发 DLL 分析 |
| GET | `/api/forensics/dlls/health` | DLL 分析服务健康检查 |

---

## 统计分析

### StatisticsRoutes (`StatisticsRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/statistics/overview` | 统计概览 |
| GET | `/api/forensics/statistics/file-distribution` | 文件分布分析 |
| GET | `/api/forensics/statistics/activity-patterns` | 活动模式分析 |
| GET | `/api/forensics/statistics/deleted-files-analysis` | 已删除文件分析 |

---

## Android 取证

### AndroidForensicsRoutes (`AndroidForensicsRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/android/communication-summary` | 通信摘要 |
| GET | `/api/forensics/android/app-usage` | 应用使用统计 |
| GET | `/api/forensics/android/device-info` | 设备信息 |
| GET | `/api/forensics/android/media-analysis` | 媒体文件分析 |

---

## 数据导出

### ExportRoutes (`ExportRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/export/toon` | TOON 格式导出 |
| GET | `/api/forensics/export/events/json` | 事件导出（JSON） |
| GET | `/api/forensics/export/events/csv` | 事件导出（CSV） |
| GET | `/api/forensics/export/events/visualization` | 事件导出（可视化格式） |

---

## 全文搜索

### SearchRoutes (`SearchRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/search/fulltext` | 全文搜索 |
| POST | `/api/search/index` | 索引文件 |
| GET | `/api/search/status` | 搜索服务状态 |

---

## OSS 分析

### OSSRoutes (`OSSRoutes.cpp`, `OSSAnalysisRoutes.cpp`, `OSSQueryRoutes.cpp`, `OSSStatsRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/oss/analyze` | 启动 OSS 分析 |
| GET | `/api/oss/status` | OSS 分析状态 |
| GET | `/api/oss/results` | OSS 分析结果 |
| GET | `/api/oss/query` | OSS 数据查询 |
| GET | `/api/oss/statistics` | OSS 统计信息 |

---

## 系统监控

### SystemHealthRoutes (`SystemHealthRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/system/health` | 系统健康检查 |
| GET | `/api/health` | 健康检查（别名） |
| GET | `/api/health/live` | Kubernetes 存活探针 |
| GET | `/api/health/ready` | Kubernetes 就绪探针 |
| GET | `/api/health/dependencies` | 依赖服务状态 |

### SystemInfoRoutes (`SystemInfoRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/system/info` | 系统信息 |
| GET | `/api/system/databases` | 可用数据库列表 |
| GET | `/api/system/database-schema/{db_type}` | 数据库 Schema |
| POST | `/api/export/{task_id}` | 导出任务结果 |
| GET | `/api/system/logs` | 系统日志 |

### SystemDocsRoutes (`SystemDocsRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/docs/endpoints` | API 端点列表 |

### SystemEventRoutes (`SystemEventRoutes.cpp`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/system/events` | 系统事件 |
| GET | `/api/system/events/summary` | 系统事件摘要 |

---

## 辅助模块

### RouteHelpers (`RouteHelpers.cpp`)

路由辅助工具，提供：
- 通用错误响应构建
- 请求参数解析
- 任务验证

### TaskHelpers (`TaskHelpers.cpp`)

任务相关辅助工具，提供：
- 任务 ID 生成
- 任务状态转换
- 进度计算

---

## 通用参数

### 任务标识参数

所有取证分析端点都需要 `task_id` 参数：

```
GET /api/forensics/timeline/comprehensive?task_id=task_123
```

### 分页参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 1000 | 最大返回记录数 |
| `offset` | int | 0 | 跳过记录数 |

### 时间参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `start_time` | string | 开始时间（ISO 8601 或 Unix 时间戳） |
| `end_time` | string | 结束时间 |
| `hours` | int | 最近 N 小时 |

---

## 响应格式

### 成功响应

```json
{
    "success": true,
    "data": { ... },
    "execution_time_ms": 45
}
```

### 错误响应

```json
{
    "success": false,
    "error": "Error message",
    "error_code": "TASK_NOT_FOUND"
}
```

---

**最后更新**: 2026-05-19
