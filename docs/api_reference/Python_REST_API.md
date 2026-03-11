# Python REST API 参考文档

## 概述

Python HTTP 服务运行在端口 **8090**，提供知识图谱、LLM 分析和数据库导出功能。

**服务器地址**：`http://localhost:8090`

**API 文档**：
- Swagger UI: http://localhost:8090/docs
- ReDoc: http://localhost:8090/redoc
- OpenAPI JSON: http://localhost:8090/openapi.json

---

## 目录

1. [健康检查 API](#1-健康检查-api)
2. [Graphiti 知识图谱 API](#2-graphiti-知识图谱-api)
3. [LLM 分析 API](#3-llm-分析-api)
4. [数据库访问 API](#4-数据库访问-api)
5. [Office 文档 API](#5-office-文档-api)
6. [案例分析 API](#6-案例分析-api)
7. [系统信息 API](#7-系统信息-api)

---

## 1. 健康检查 API

### GET /health

**描述**：基础健康检查，检查服务是否运行。

**响应**：
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

### GET /health/live

**描述**：Kubernetes 存活探针。

**响应**：
```json
{
  "status": "alive"
}
```

### GET /health/ready

**描述**：Kubernetes 就绪探针，检查依赖服务状态。

**响应**：
```json
{
  "status": "healthy",
  "services": {
    "cpp_backend": {
      "status": "healthy",
      "url": "http://localhost:8080"
    },
    "graphiti": {
      "status": "healthy",
      "neo4j_uri": "neo4j://localhost:7687"
    },
    "llm": {
      "status": "healthy",
      "llm_base_url": "http://localhost:1234"
    }
  }
}
```

---

## 2. Graphiti 知识图谱 API

### POST /api/graphiti/ingest

**描述**：将取证数据摄取到知识图谱（后台任务）。

**请求体**：
```json
{
  "task_id": "task_abc123",
  "include_llm_descriptions": true,
  "batch_size": 50,
  "dry_run": false
}
```

**参数说明**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `include_llm_descriptions` | boolean | ❌ | false | 是否包含 LLM 描述 |
| `batch_size` | integer | ❌ | 50 | 批处理大小 |
| `dry_run` | boolean | ❌ | false | 试运行模式（不实际摄取） |

**响应**：
```json
{
  "success": true,
  "job_id": "job_xyz789",
  "status": "running",
  "message": "知识图谱摄取已启动",
  "estimated_time_seconds": 300
}
```

### POST /api/graphiti/search

**描述**：在知识图谱中搜索。

**请求体**：
```json
{
  "query": "malware documents",
  "task_id": "task_abc123",
  "limit": 50,
  "include_relationships": true
}
```

**参数说明**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | ✅ | - | 自然语言查询 |
| `task_id` | string | ✅ | - | 任务 ID |
| `limit` | integer | ❌ | 50 | 最大结果数 |
| `include_relationships` | boolean | ❌ | true | 是否包含关系 |

**响应**：
```json
{
  "success": true,
  "query": "malware documents",
  "results": [
    {
      "entity": {
        "name": "trojan.exe",
        "type": "FILE",
        "summary": "检测到可疑的可执行文件",
        "attributes": {
          "file_path": "/evidence/trojan.exe",
          "size": 2048576
        }
      },
      "relationships": [
        {
          "type": "LOCATED_IN",
          "target": {
            "name": "C:/Temp/trojan.exe",
            "type": "LOCATION"
          },
          "weight": 0.95
        }
      ],
      "score": 0.92
    }
  ],
  "total_results": 1
}
```

### GET /api/graphiti/entities

**描述**：获取知识图谱中的实体列表。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `entity_type` | string | ❌ | - | 过滤实体类型 |
| `limit` | integer | ❌ | 100 | 最大结果数 |
| `offset` | integer | ❌ | 0 | 偏移量 |

**响应**：
```json
{
  "success": true,
  "entities": [
    {
      "name": "document.pdf",
      "type": "FILE",
      "summary": "保密协议文档",
      "created_at": "2024-01-16T10:00:00Z"
    }
  ],
  "total_count": 150
}
```

### GET /api/graphiti/relationships

**描述**：获取知识图谱中的关系列表。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `relationship_type` | string | ❌ | - | 过滤关系类型 |
| `limit` | integer | ❌ | 100 | 最大结果数 |

**响应**：
```json
{
  "success": true,
  "relationships": [
    {
      "source": "document.pdf",
      "target": "/evidence/document.pdf",
      "type": "LOCATED_AT",
      "weight": 1.0
    }
  ],
  "total_count": 300
}
```

### GET /api/graphiti/graph

**描述**：获取图可视化数据（用于前端展示）。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `max_nodes` | integer | ❌ | 200 | 最大节点数 |

**响应**：
```json
{
  "success": true,
  "nodes": [
    {
      "id": "node_1",
      "label": "document.pdf",
      "type": "FILE",
      "size": 20
    }
  ],
  "edges": [
    {
      "source": "node_1",
      "target": "node_2",
      "label": "LOCATED_AT",
      "weight": 0.9
    }
  ],
  "stats": {
    "total_nodes": 150,
    "total_edges": 300
  }
}
```

### DELETE /api/graphiti/task/{task_id}

**描述**：删除任务的所有图谱数据。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 任务 ID |

**响应**：
```json
{
  "success": true,
  "deleted_nodes": 150,
  "deleted_edges": 300,
  "message": "图谱数据已删除"
}
```

---

## 3. LLM 分析 API

### POST /api/llm/analyze

**描述**：分析文本内容。

**请求体**：
```json
{
  "content": "这是一份保密协议...",
  "max_tokens": 1000,
  "model_type": "text"
}
```

**参数说明**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `content` | string | ✅ | - | 要分析的文本 |
| `max_tokens` | integer | ❌ | 1000 | 最大 token 数 |
| `model_type` | string | ❌ | text | text 或 vision |

**响应**：
```json
{
  "success": true,
  "summary": "保密协议文档",
  "description": "这是一份甲方与乙方的保密协议...",
  "keywords": ["保密", "协议", "合同"],
  "model_used": "qwen2.5:7b",
  "tokens_used": 500
}
```

### POST /api/llm/analyze/file

**描述**：上传文件并分析。

**请求**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | ✅ | 要分析的文件 |
| `model_type` | string | ❌ | text/vision |

**响应**：
```json
{
  "success": true,
  "file_name": "document.pdf",
  "summary": "法律文档",
  "description": "包含合同条款...",
  "keywords": ["法律", "合同"],
  "model_used": "qwen2.5:7b"
}
```

### POST /api/llm/batch-analyze

**描述**：批量分析文件。

**请求体**：
```json
{
  "task_id": "task_abc123",
  "file_types": ["documents", "images"],
  "limit": 100,
  "max_parallel": 5
}
```

**响应**：
```json
{
  "success": true,
  "job_id": "batch_job_456",
  "total_files": 100,
  "status": "running",
  "estimated_time_seconds": 600
}
```

### GET /api/llm/jobs/{job_id}/status

**描述**：查询批量分析任务状态。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `job_id` | string | ✅ | 任务 ID |

**响应**：
```json
{
  "success": true,
  "job_id": "batch_job_456",
  "status": "running",
  "progress": 45,
  "total": 100,
  "completed": 45,
  "failed": 2,
  "started_at": "2024-01-16T10:00:00Z",
  "estimated_completion": "2024-01-16T10:10:00Z"
}
```

### GET /api/llm/models

**描述**：获取可用的 LLM 模型列表。

**响应**：
```json
{
  "success": true,
  "models": {
    "text": [
      {
        "name": "qwen2.5:7b",
        "type": "local",
        "base_url": "http://localhost:1234",
        "available": true
      },
      {
        "name": "gpt-4",
        "type": "openai",
        "base_url": "https://api.openai.com/v1",
        "available": true
      }
    ],
    "vision": [
      {
        "name": "qwen-vl-plus",
        "type": "local",
        "base_url": "http://localhost:1234",
        "available": true
      }
    ]
  }
}
```

---

## 4. 数据库访问 API

### GET /api/db/tasks

**描述**：获取任务的数据库列表。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |

**响应**：
```json
{
  "success": true,
  "task_id": "task_abc123",
  "databases": [
    {
      "type": "files",
      "path": "/output/evidence_files.db",
      "size_bytes": 10485760,
      "table_count": 15
    },
    {
      "type": "events",
      "path": "/output/evidence_events.db",
      "size_bytes": 5242880,
      "table_count": 5
    }
  ]
}
```

### POST /api/db/query

**描述**：执行自定义 SQL 查询。

**请求体**：
```json
{
  "task_id": "task_abc123",
  "database_type": "files",
  "sql": "SELECT * FROM files WHERE size > 1048576 ORDER BY size DESC LIMIT 10",
  "limit": 100
}
```

**参数说明**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `database_type` | string | ✅ | - | 数据库类型（raw/events/files） |
| `sql` | string | ❌ | - | SQL 查询 |
| `limit` | integer | ❌ | 1000 | 最大行数 |

**响应**：
```json
{
  "success": true,
  "columns": ["id", "name", "path", "size", "category"],
  "rows": [
    [1, "document.pdf", "/evidence/document.pdf", 2048576, "documents"],
    [2, "database.db", "/evidence/database.db", 5242880, "databases"]
  ],
  "row_count": 2
}
```

### GET /api/db/tasks/{task_id}/export/toon

**描述**：导出任务数据为 TOON 格式。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 任务 ID |

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `include_llm` | boolean | ❌ | true | 包含 LLM 分析字段 |
| `filter` | string | ❌ | - | 过滤条件 |

**响应**：
```
TOON.schema: name | path | category | size | llm_summary | llm_keywords
# records[150]
document.pdf | /evidence/document.pdf | documents | 2048576 | 保密协议文档 | 保密,协议,合同
database.db | /evidence/database.db | databases | 5242880 | SQLite 数据库 | 数据库,SQLite
...
```

### GET /api/db/tasks/{task_id}/export/json

**描述**：导出任务数据为 JSON 格式。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 任务 ID |

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `database_type` | string | ✅ | - | 数据库类型 |
| `include_llm` | boolean | ❌ | true | 包含 LLM 分析 |
| `limit` | integer | ❌ | 1000 | 最大记录数 |

**响应**：
```json
{
  "success": true,
  "database_type": "files",
  "data": [
    {
      "id": 1,
      "name": "document.pdf",
      "path": "/evidence/document.pdf",
      "size": 2048576,
      "category": "documents",
      "llm_summary": "保密协议文档"
    }
  ],
  "count": 1
}
```

---

## 5. Office 文档 API

### POST /api/office/extract

**描述**：提取 Office 文档内容为 Markdown。

**请求**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | ✅ | Office 文档 |
| | | | | (.docx, .xlsx, .pptx) |

**响应**：
```json
{
  "success": true,
  "file_name": "document.docx",
  "file_type": "docx",
  "markdown": "# Document\\n\\n这是一份 Word 文档...",
  "metadata": {
    "author": "John Doe",
    "created": "2024-01-16T10:00:00Z",
    "pages": 10
  }
}
```

### POST /api/office/batch-extract

**描述**：批量提取 Office 文档。

**请求体**：
```json
{
  "task_id": "task_abc123",
  "file_type": "documents",
  "limit": 50
}
```

**响应**：
```json
{
  "success": true,
  "job_id": "office_job_789",
  "total_files": 50,
  "status": "running"
}
```

---

## 6. 案例分析 API

### POST /api/case/analyze

**描述**：执行完整的案例分析工作流。

**请求体**：
```json
{
  "task_id": "task_abc123",
  "analysis_options": {
    "include_llm_analysis": true,
    "include_graphiti": true,
    "include_timeline": true
  }
}
```

**响应**：
```json
{
  "success": true,
  "analysis_id": "analysis_xyz",
  "status": "running",
  "steps": [
    {
      "name": "LLM Analysis",
      "status": "pending"
    },
    {
      "name": "Graphiti Ingestion",
      "status": "pending"
    },
    {
      "name": "Timeline Generation",
      "status": "pending"
    }
  ]
}
```

### GET /api/case/analysis/{analysis_id}

**描述**：获取分析结果。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `analysis_id` | string | ✅ | 分析 ID |

**响应**：
```json
{
  "success": true,
  "analysis_id": "analysis_xyz",
  "status": "completed",
  "results": {
    "llm_analysis": {
      "total_files": 100,
      "analyzed_files": 80,
      "suspicious_files": 5
    },
    "graphiti": {
      "entities": 50,
      "relationships": 100
    },
    "timeline": {
      "events": 200,
      "time_span": "30 days"
    }
  }
}
```

---

## 7. 系统信息 API

### GET /api/system/info

**描述**：获取系统信息。

**响应**：
```json
{
  "success": true,
  "version": "1.0.0",
  "python_version": "3.11.0",
  "dependencies": {
    "fastapi": "0.104.1",
    "httpx": "0.25.2",
    "graphiti-core": "0.1.0"
  },
  "startup_time": "2024-01-16T10:00:00Z",
  "uptime_seconds": 3600
}
```

### GET /api/system/logs

**描述**：获取系统日志。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `level` | string | ❌ | INFO | 日志级别 |
| `lines` | integer | ❌ | 100 | 返回行数 |

**响应**：
```json
{
  "success": true,
  "logs": [
    {
      "timestamp": "2024-01-16T10:00:00Z",
      "level": "INFO",
      "logger": "httpserver.routes.llm",
      "message": "LLM analysis started for task_abc123"
    }
  ]
}
```

---

## 错误响应

所有 API 在出错时返回以下格式：

```json
{
  "success": false,
  "error": "错误描述",
  "detail": "详细错误信息（可选）",
  "status": 400
}
```

**常见 HTTP 状态码**：

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 速率限制

当前版本未实施速率限制，建议在生产环境中通过反向代理（Nginx）添加。

---

## 相关文档

- **[C++ REST API 参考](../api_reference/CPP_REST_API.md)** - C++ 服务 API
- **[FastAPI 主程序](../modules/python/httpserver/Main.md)** - Python 服务架构
- **[ServiceManager](../modules/python/httpserver/services/ServiceManager.md)** - 服务管理
- **[CppBackendClient](../modules/python/httpserver/services/CppBackendClient.md)** - C++ 后端通信

---

**最后更新**: 2026-03-11
**维护者**: ymj68520
