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
7. [多镜像分析 API](#7-多镜像分析-api)
8. [WeChat 关系图谱 API](#8-wechat-关系图谱-api)
9. [事件关联 API](#9-事件关联-api)
10. [OSS 分析 API](#10-oss-分析-api)
11. [DLL 分析 API](#11-dll-分析-api)
12. [Markitdown 文档转换 API](#12-markitdown-文档转换-api)
13. [系统信息 API](#13-系统信息-api)

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
  "mode": "full",
  "include_llm_descriptions": true,
  "batch_size": 50
}
```

**参数说明**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | string | ✅ | - | 任务 ID |
| `mode` | string | ❌ | full | 摄取模式：`full`, `files_only`, `events_only`, `analyzed_only` |
| `include_llm_descriptions` | boolean | ❌ | true | 是否包含 LLM 描述 |
| `batch_size` | integer | ❌ | 50 | 批处理大小（1-500） |

**摄取模式说明**：

- **`full`**: 完整摄取模式
  - 摄取所有文件、事件和平台数据
  - 包含 Android、Windows、Linux 专项分析结果
  - 适用于首次摄取或全面更新

- **`files_only`**: 仅更新文件实体
  - 仅更新文件实体信息
  - 不处理事件和关系
  - 适用于文件元数据变更后的快速同步

- **`events_only`**: 同步事件到现有文件
  - 将事件附加到已存在的文件实体
  - 不创建新文件实体
  - 适用于事件数据的增量更新

- **`analyzed_only`**: **新增** - 仅重新摄取 AI 分析文件和事件集群
  - 仅处理 `llm_analyzed_at IS NOT NULL` 的文件
  - 仅为已分析文件附加事件
  - 不会重新运行 LLM 分析
  - 适用于 AI 分析完成后更新知识图谱

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

## 14. AI 文件过滤增强配置

### 概述

AI 文件过滤系统已增强，提供更强大的响应解析、智能重复处理和边缘情况恢复能力。

### 新增组件

#### LLMResponseParser

**位置**: `services/case_analysis/llm_response_parser.py`

处理各种 LLM 响应格式：
- 带/不带 markdown 代码块的 JSON
- 不同的字段名称（selected_files、filtered_files、files）
- 数组或字典格式
- 嵌入 JSON 的文本

#### FileMatcher

**位置**: `services/case_analysis/file_matcher.py`

智能文件匹配与重复解析：
- 复合评分（路径语义 + 新鲜度 + 大小 + 深度）
- 可配置权重
- 置信度评分

**默认评分权重**:
- 路径语义: 0.4
- 新鲜度: 0.3
- 大小: 0.2
- 深度: 0.1

#### FilterResultValidator

**位置**: `services/case_analysis/filter_validator.py`

验证和修复结果：
- 处理无效响应
- 修剪多余文件
- 移除无效项
- 低置信度检测

#### FilterLockManager

**位置**: `services/case_analysis/concurrent_filter.py`

防止并发过滤冲突：
- 任务级异步锁
- 超时支持
- 单例模式

### 环境配置

在 `.env` 文件中添加以下配置：

```env
# 启用增强解析器
ENABLE_ENHANCED_PARSER=true

# 配置评分权重
SCORE_WEIGHT_PATH_SEMANTIC=0.4
SCORE_WEIGHT_FRESHNESS=0.3
SCORE_WEIGHT_SIZE=0.2
SCORE_WEIGHT_DEPTH=0.1

# 并发控制
ENABLE_CONCURRENT_LOCK=true
LOCK_TIMEOUT=300
```

### 使用说明

增强组件自动启用，无需更改 API 调用。

如需手动控制，可使用特性标志：
```python
from httpserver.config import LLMFilterConfig

filter_config = LLMFilterConfig(
    enable_enhanced_parser=True,
    enable_smart_dedup=True,
    score_weight_path_semantic=0.5,  # 自定义权重
)
```

### 测试

运行相关测试：
```bash
cd python_service
.venv/bin/pytest tests/unit/test_concurrent_filter.py -v
.venv/bin/pytest tests/unit/test_llm_response_parser.py -v
.venv/bin/pytest tests/unit/test_file_matcher.py -v
.venv/bin/pytest tests/unit/test_filter_validator.py -v
.venv/bin/pytest tests/integration/test_file_filter_integration.py -v
```

### 迁移指南

增强功能向后兼容。现有代码继续工作，并在需要时自动回退到传统解析。

在自定义代码中启用新功能：
```python
from services.case_analysis.llm_response_parser import LLMResponseParser
from services.case_analysis.file_matcher import FileMatcher
from services.case_analysis.filter_validator import FilterResultValidator

parser = LLMResponseParser(settings)
matcher = FileMatcher(settings)
validator = FilterResultValidator(settings)

# 在过滤管道中使用
parse_result = parser.parse_filter_response(llm_response, batch_files)
validated = validator.validate_and_repair(parse_result, batch_files, max_files)
matched = matcher.match_files(validated.items, batch_files, case_context)
```

### 相关文档

- **[AI 过滤增强详细文档](../AI_FILTER_ENHANCEMENTS.md)** - 完整的组件文档

---

## 7. 多镜像分析 API

多镜像分析 API 支持跨多个磁盘镜像的关联分析，通过案例（Case）组织多个任务。

### POST /api/llm/cases

**描述**：创建新案例。

**请求体**：
```json
{
  "name": "案件名称",
  "description": "案件描述",
  "task_ids": ["task_1", "task_2"]
}
```

### GET /api/llm/cases

**描述**：列出所有案例。

### GET /api/llm/cases/{case_id}

**描述**：获取案例详情。

### DELETE /api/llm/cases/{case_id}

**描述**：删除案例。

### POST /api/llm/cases/{case_id}/tasks

**描述**：向案例添加任务。

**请求体**：
```json
{
  "task_ids": ["task_3", "task_4"]
}
```

### POST /api/llm/multi-image-analysis

**描述**：启动多镜像分析任务。

**请求体**：
```json
{
  "case_id": "case_123",
  "analysis_type": "full|quick",
  "description": "分析目标描述"
}
```

### GET /api/llm/multi-image-analysis/{job_id}

**描述**：获取多镜像分析任务状态。

### POST /api/llm/cases/smart-create

**描述**：智能创建案例（自动关联相关任务）。

### POST /api/llm/cases/{case_id}/tasks/incremental

**描述**：增量添加任务到案例。

### GET /api/llm/cases/{case_id}/analysis-status

**描述**：获取案例分析状态。

### POST /api/llm/cases/{case_id}/incremental-analysis

**描述**：触发增量分析。

---

## 8. WeChat 关系图谱 API

WeChat 关系图谱 API 提供微信聊天记录的图分析能力，包括 PageRank 社交影响力分析、社区发现、聊天记录查询等。

### GET /api/wechat/graph

**描述**：获取 WeChat 关系图谱数据。

**查询参数**：
- `task_id` (string, required)
- `min_weight` (int, optional, default 1) - 最小边权重

### GET /api/wechat/graph/timeline

**描述**：获取 WeChat 通信时间线。

**查询参数**：
- `task_id` (string, required)
- `start_time` (int, optional)
- `end_time` (int, optional)

### GET /api/wechat/graph/community

**描述**：获取 WeChat 社区发现结果（Louvain 算法）。

**查询参数**：`task_id` (string, required)

### GET /api/wechat/graph/person/{username}

**描述**：获取特定用户的社交网络详情。

**路径参数**：`username` (string) - 微信用户名

**查询参数**：`task_id` (string, required)

### GET /api/wechat/chat

**描述**：获取聊天记录。

**查询参数**：
- `task_id` (string, required)
- `talker` (string, optional) - 对话者
- `limit` (int, default 100)

### GET /api/wechat/chat/group

**描述**：获取群聊记录。

**查询参数**：
- `task_id` (string, required)
- `chatroom_name` (string, required)

### GET /api/wechat/owner

**描述**：获取微信账号所有者信息。

**查询参数**：`task_id` (string, required)

### GET /api/wechat/contacts

**描述**：获取微信联系人列表。

**查询参数**：`task_id` (string, required)

### POST /api/wechat/graph/invalidate

**描述**：清除图谱缓存。

**请求体**：
```json
{
  "task_id": "string"
}
```

---

## 9. 事件关联 API

事件关联 API 提供事件簇与文件之间的关联查询能力。

### POST /api/associations/cluster-files

**描述**：获取事件簇关联的文件。

**请求体**：
```json
{
  "task_id": "string",
  "cluster_id": "string",
  "time_window_seconds": 300
}
```

### POST /api/associations/file-clusters

**描述**：获取文件关联的事件簇。

**请求体**：
```json
{
  "task_id": "string",
  "file_path": "/path/to/file",
  "time_window_seconds": 300
}
```

---

## 10. OSS 分析 API

Python 侧 OSS 分析 API 提供 AI 驱动的 OSS 对象过滤和分析能力。

### POST /api/forensics/oss/ai/filter

**描述**：使用 LLM 过滤 OSS 对象。

**请求体**：
```json
{
  "task_id": "string",
  "description": "查找与案件相关的文档",
  "model": "qwen2.5:7b"
}
```

### POST /api/forensics/oss/ai/analyze

**描述**：使用 LLM 分析 OSS 对象内容。

**请求体**：
```json
{
  "task_id": "string",
  "object_ids": [1, 2, 3],
  "model": "qwen2.5:7b"
}
```

---

## 11. DLL 分析 API

### POST /api/llm/analyze/dll

**描述**：使用 LLM 分析 DLL/共享库文件的安全性。

**请求体**：
```json
{
  "task_id": "string",
  "dll_path": "/path/to/file.dll",
  "model": "qwen2.5:7b"
}
```

---

## 12. Markitdown 文档转换 API

Markitdown API 提供将各种文档格式转换为 Markdown 的能力。

### POST /api/markitdown/convert

**描述**：将文件转换为 Markdown 格式。

**请求体**（multipart/form-data）：
- `file` (file) - 要转换的文件

**响应**：
```json
{
  "success": true,
  "data": {
    "markdown": "# Document Title\n\nContent...",
    "content_type": "application/pdf",
    "filename": "document.pdf"
  }
}
```

### GET /api/markitdown/status

**描述**：检查 Markitdown 服务状态。

---

## 13. 系统信息 API

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

**最后更新**: 2026-06-06
**维护者**: ymj68520
