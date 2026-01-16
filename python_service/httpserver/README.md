# ForensicsProject HTTP Server

Python HTTP 服务，为数字取证分析平台提供 RESTful API。

## 概述

本服务使用 FastAPI 框架构建，提供以下功能：

- **Graphiti 集成**：知识图谱数据摄入和搜索
- **LLM 分析**：AI 驱动的文件内容分析
- **数据库访问**：取证数据库查询和导出
- **健康监控**：服务状态和依赖检查

## 快速开始

### 安装依赖

```bash
cd python_service/httpserver
pip install -r requirements.txt
```

### 启动服务

```bash
# 从项目根目录
python -m python_service.httpserver.main

# 或使用启动脚本（同时启动 C++ 和 Python 服务）
./scripts/start_services.sh
```

### 配置

服务从项目根目录的 `.env` 文件读取配置：

```env
# Python HTTP 服务设置
PYTHON_HTTP_PORT=8090
PYTHON_HTTP_HOST=0.0.0.0
CPP_BACKEND_URL=http://localhost:8080
```

## API 文档

服务启动后，访问以下 URL 查看 API 文档：

- **Swagger UI**: http://localhost:8090/docs
- **ReDoc**: http://localhost:8090/redoc
- **OpenAPI JSON**: http://localhost:8090/openapi.json

## API 端点

### 健康检查

| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 基础健康检查 |
| `/health/live` | GET | Kubernetes 存活探针 |
| `/health/ready` | GET | Kubernetes 就绪探针 |
| `/api/system/info` | GET | 系统信息 |

### Graphiti 知识图谱

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/graphiti/ingest` | POST | 摄入任务数据 |
| `/api/graphiti/search` | POST | 图谱搜索 |
| `/api/graphiti/entities` | GET | 实体列表 |
| `/api/graphiti/relationships` | GET | 关系列表 |
| `/api/graphiti/status` | GET | 服务状态 |

### LLM 分析

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/llm/analyze` | POST | 分析内容 |
| `/api/llm/analyze/file` | POST | 分析上传文件 |
| `/api/llm/batch-analyze` | POST | 批量分析 |
| `/api/llm/batch-analyze/{job_id}` | GET | 批量任务状态 |
| `/api/llm/models` | GET | 可用模型列表 |
| `/api/llm/status` | GET | 服务状态 |

### 数据库访问

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/db/tasks` | GET | 任务列表 |
| `/api/db/tasks/{task_id}` | GET | 任务详情 |
| `/api/db/tasks/{task_id}/files` | GET | 任务文件列表 |
| `/api/db/tasks/{task_id}/events` | GET | 任务事件列表 |
| `/api/db/tasks/{task_id}/export/toon` | GET | TOON 格式导出 |
| `/api/db/tasks/{task_id}/export/json` | GET | JSON 格式导出 |
| `/api/db/query` | POST | 自定义查询 |

## 架构

```
httpserver/
├── main.py              # FastAPI 应用入口
├── config.py            # 配置管理
├── routes/              # API 路由
│   ├── health.py        # 健康检查
│   ├── graphiti.py      # 知识图谱
│   ├── llm.py           # LLM 分析
│   └── database.py      # 数据库访问
└── services/            # 业务逻辑
    ├── service_manager.py    # 服务协调
    ├── cpp_backend.py        # C++ 后端通信
    ├── graphiti_service.py   # Graphiti 集成
    └── llm_service.py        # LLM 集成
```

## 扩展性设计

服务架构支持未来扩展到其他通信协议：

- **当前**：HTTP/REST
- **未来**：gRPC、WebSocket、消息队列等

只需为每个服务添加新的协议适配器，无需修改核心业务逻辑。

## 与 C++ 服务协作

Python 服务通过 HTTP 与 C++ 后端通信：

```
┌─────────────────┐     HTTP     ┌─────────────────┐
│  Python Service │ ──────────▶  │   C++ Service   │
│    (8090)       │              │     (8080)      │
└─────────────────┘              └─────────────────┘
```

- C++ 服务处理磁盘镜像分析、任务管理
- Python 服务处理 LLM 分析、知识图谱集成
