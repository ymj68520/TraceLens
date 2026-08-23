# RouteReference - C++ 路由总览

> **模块定位**: `src/network/HTTPServer/routes/` 下全部路由文件的端点索引（按已注册的 CROW_ROUTE 整理）。详细的请求/响应字段见 [API 参考](../../../../api_reference/CPP_REST_API.md) 与运行时 Swagger（`/api/docs`）。

路由由 `HTTPServer` 构造的聚合器注册：`TaskRoutes`、`ForensicsRoutes`、`SystemRoutes`、`SearchRoutes`、`CaseCRUDRoutes`、`FilterRoutes`。另有静态路由 `GET /` 与 `GET /<path>` 托管 `web/dist` 的 React SPA。

---

## 任务管理

### TaskCRUDRoutes / TaskBatchRoutes / TaskMonitoringRoutes / TaskRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET/POST | `/tasks` | 简化任务接口（创建/列表） |
| GET | `/tasks/{task_id}` | 任务详情（简化） |
| GET | `/tasks/{task_id}/results` | 任务结果（简化） |
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/list` | 列出所有任务（带筛选） |
| POST | `/api/tasks` | 创建分析任务 |
| GET/PUT | `/api/tasks/{task_id}` | 获取/更新任务 |
| DELETE | `/api/tasks/{task_id}` | 删除任务 |
| GET | `/api/tasks/{task_id}/results` | 任务结果 |
| POST | `/api/tasks/cleanup` | 清理已完成任务 |
| GET | `/api/tasks/{task_id}/databases` | 任务关联数据库列表 |
| POST | `/api/tasks/batch-create` | 批量创建任务 |
| POST | `/api/tasks/batch-status` | 批量查询状态 |
| POST | `/api/tasks/batch-cancel` | 批量取消任务 |
| GET | `/api/tasks/{task_id}/progress` | 任务进度 |
| GET | `/api/tasks/{task_id}/audit-log` | 任务审计日志 |
| GET | `/api/tasks/statistics` | 任务统计 |
| PUT | `/api/tasks/{task_id}/priority` | 更新优先级 |

（TaskRoutes.cpp 另为上述路径注册 16 个 OPTIONS CORS 预检路由。）

### SceneQueryRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/tasks/{task_id}/scene-stats` | 场景文件统计 |
| GET | `/api/tasks/{task_id}/scene-artifacts` | 场景工件查询 |

---

## 案例管理

### CaseCRUDRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET/POST | `/api/cases` | 列出/创建案例 |
| GET/DELETE | `/api/cases/{case_id}` | 获取/删除案例 |
| PUT | `/api/cases/{case_id}/tasks` | 添加任务到案例 |
| PUT | `/api/cases/{case_id}/status` | 更新案例状态 |

---

## 取证分析（ForensicsRoutes 聚合）

### TimelineRoutes

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

### EventClusterRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/forensics/timeline/clusters/analyze` | LLM 分析事件簇 |
| POST | `/api/forensics/timeline/clusters/batch-analyze` | 批量分析事件簇 |
| POST | `/api/forensics/timeline/clusters/reanalyze` | 重新分析事件簇 |
| GET | `/api/forensics/timeline/clusters/analyzed` | 已分析的事件簇 |

### FileAnalysisRoutes / FileExtractionRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/files/largest` | 最大文件列表 |
| GET | `/api/forensics/files/recent` | 最近修改的文件 |
| GET | `/api/forensics/files/suspicious` | 可疑文件 |
| GET | `/api/forensics/files/duplicates` | 重复文件 |
| GET | `/api/forensics/files/extensions-analysis` | 扩展名分析 |
| POST | `/api/forensics/extract` | 启动文件提取任务 |
| GET | `/api/forensics/extract/{job_id}` | 查询提取任务 |
| GET | `/api/forensics/extract/status` | 全部提取任务状态 |

### DLLAnalysisRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/dlls` | 列出分析的 DLL/可执行文件 |
| GET | `/api/forensics/dlls/{dll_id}` | DLL 详情 |
| GET | `/api/forensics/dlls/suspicious` | 可疑 DLL |
| GET | `/api/forensics/dlls/statistics` | DLL 分析统计 |
| GET | `/api/forensics/dlls/{dll_id}/anomalies` | DLL 异常 |
| POST | `/api/forensics/dlls/analyze` | 触发 DLL 分析 |
| GET | `/api/forensics/dlls/health` | DLL 分析服务健康检查 |

### StatisticsRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/statistics/overview` | 统计概览 |
| GET | `/api/forensics/statistics/file-distribution` | 文件分布 |
| GET | `/api/forensics/statistics/activity-patterns` | 活动模式 |
| GET | `/api/forensics/statistics/deleted-files-analysis` | 已删除文件分析 |

### AndroidForensicsRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/android/communication-summary` | 通信摘要 |
| GET | `/api/forensics/android/app-usage` | 应用使用统计 |
| GET | `/api/forensics/android/device-info` | 设备信息 |
| GET | `/api/forensics/android/media-analysis` | 媒体文件分析 |
| GET | `/api/forensics/android/miui-overview` | MIUI 备份概览 |
| GET | `/api/forensics/android/miui-installed-apps` | MIUI 已装应用 |
| GET | `/api/forensics/android/miui-db-inventory` | MIUI 数据库清单 |
| GET | `/api/forensics/android/miui-qqnt-overview` | QQNT 概览 |
| GET | `/api/forensics/android/miui-qqnt-artifacts` | QQNT 工件 |
| GET | `/api/forensics/android/miui-qqnt-records` | QQNT 记录 |
| GET | `/api/forensics/android/miui-wechat-overview` | 微信概览 |
| GET | `/api/forensics/android/miui-wechat-artifacts` | 微信工件 |
| GET | `/api/forensics/android/miui-wechat-records` | 微信记录 |
| GET | `/api/forensics/android/llm-summary` | Android LLM 汇总 |

### MemoryForensicsRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/memory/summary` | 内存分析摘要 |
| GET | `/api/forensics/memory/processes` | 进程列表 |
| GET | `/api/forensics/memory/network` | 网络连接 |
| GET | `/api/forensics/memory/bash-history` | Bash 历史 |
| GET | `/api/forensics/memory/boot-info` | 启动信息 |

### SystemEventRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/system/events` | 系统事件 |
| GET | `/api/forensics/system/summary` | 系统事件摘要 |

### ExportRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/forensics/export/toon` | TOON 格式导出 |
| GET | `/api/forensics/export/events/json` | 事件导出（JSON） |
| GET | `/api/forensics/export/events/csv` | 事件导出（CSV） |
| GET | `/api/forensics/export/events/visualization` | 事件导出（可视化格式） |

### OSS 路由（未注册）

`OSSRoutes/OSSAnalysisRoutes/OSSQueryRoutes/OSSStatsRoutes` 虽被编译（定义 `/api/forensics/oss/*` 系列端点），但 `HTTPServer` 从未实例化 `OSSRoutes`，**运行时这些端点不存在**。详见 [OSSRoutes.md](OSSRoutes.md)。

---

## 全文搜索

### SearchRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/search/fulltext` | 全文搜索 |
| POST | `/api/search/index` | 建立索引 |

---

## 系统监控与文档

### SystemHealthRoutes / SystemInfoRoutes / SystemDocsRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/system/health` | 系统健康检查 |
| GET | `/api/health` | 健康检查（别名） |
| GET | `/api/health/live` | 存活探针 |
| GET | `/api/health/ready` | 就绪探针 |
| GET | `/api/health/dependencies` | 依赖服务状态 |
| GET | `/api/system/info` | 系统信息 |
| GET | `/api/system/databases` | 可用数据库列表 |
| GET | `/api/system/database-schema/{db_type}` | 数据库 Schema |
| POST | `/api/export/{task_id}` | 导出任务结果 |
| GET | `/api/system/logs` | 系统日志 |
| GET | `/api/docs/endpoints` | API 端点列表 |
| GET | `/api/docs/database-schema` | 数据库 Schema 文档 |
| GET | `/api/docs/openapi.json` | OpenAPI JSON |
| GET | `/api/docs` | Swagger UI |

---

## 文件过滤

### FilterRoutes

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/filter/profiles` | 过滤配置列表 |
| GET | `/api/filter/profiles/{name}` | 过滤配置详情 |
| POST | `/api/filter/profiles` | 创建过滤配置 |
| DELETE | `/api/filter/profiles/{name}` | 删除过滤配置 |
| POST | `/api/filter/apply` | 应用过滤配置 |

---

## 辅助模块

### RouteHelpers (`RouteHelpers.cpp`)

路由辅助工具：通用错误响应构建、请求参数解析、`get_database_path(task_id, kind)` 任务数据库路径解析。

### TaskHelpers (`TaskHelpers.cpp`)

任务相关辅助工具：任务 ID 生成、任务状态转换。

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

各路由大多返回**裸领域 JSON**（任务对象、事件数组等）；失败时返回 `{"error": "..."}` 并携带 4xx/5xx 状态码（部分路由附 `error_code`，枚举见 `src/core/ErrorHandling/ErrorHandling.h`）。

统一的 `ApiResponse` 封装（`HTTPServerDataTypes.h`：`success/message/data/timestamp/pagination/error_code`）**目前仅 FilterRoutes 使用**：

```json
{
    "success": true,
    "message": "...",
    "data": { ... },
    "timestamp": "...",
    "pagination": { "page": 1, "pageSize": 100, "total": 1234 }
}
```

---

**最后更新**: 2026-08-23（按 routes/ 源码重写：修正搜索路由方法、OSS 未注册说明、补齐 Android/Memory/Scene/Filter/Docs 端点）
