# 常见任务指南

本文档覆盖 TraceLens 的常用工作流：创建分析任务（HTTP / CLI）、查询进度与结果、时间线/文件/统计查询、提取、雕刻、全文搜索、报告、Graphiti 摄取、markitdown 转换，以及分布式 C/S 工作流。

约定：
- C++ 服务以 `http://localhost:8666` 为例（`./run.sh` 默认；`.env` 的 `HTTP_SERVER_PORT` 或 `make cpp` 默认 8080）；
- Python httpserver 固定 `http://localhost:8090`，C/S 服务 `http://localhost:8091`；
- CLI 均指仓库根目录下的 `./build/forensic_analyzer`。

---

## 1. 创建分析任务

### 1.1 HTTP（推荐，前端即走此接口）

```bash
curl -X POST http://localhost:8666/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/abs/path/evidence.E01",
    "scenarios": ["android", "linux"],
    "filter_profile": "telecom_fraud",
    "android_source": "tsk",
    "llm_analyze": true,
    "llm_mode": "smart",
    "file_carving": false,
    "xfs_mode": "auto"
  }'
```

`POST /tasks` 与 `POST /api/tasks` 等价。请求体字段（源自 `TaskCRUDRoutes::handle_create_task`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `image_path` | string（必填） | 镜像或数据源路径 |
| `scenarios` | string[] | 多选：`android` / `windows` / `linux` / `server_cloud` |
| `filter_profile` | string | `config/filter_profiles/` 下名称，默认 `general_forensics` |
| `android_source` | string | `tsk`（默认）/ `dir` / `zip` / `miui-backup`；非 tsk 不产出 `_raw.db` |
| `llm_analyze` / `llm_mode` | bool / string | AI 分析开关；`full` 或 `smart`（默认） |
| `file_carving` | bool | 文件雕刻（也接受 `options.file_carving`） |
| `xfs_mode` | string | `auto`（默认）/ `native` / `pure` |
| `db_output_dir` | string | 数据库输出目录（默认任务工作区） |
| `backup_password` | string | MIUI/Android 备份 AES 密码（不持久化） |
| `enable_decryption` / `key_file_dir` | bool / string | BitLocker/LUKS 解密开关与密钥目录 |
| `priority` / `metadata` / `dependencies` | - | 任务优先级、元数据、依赖任务 |

批量：`POST /api/tasks/batch-create`、`POST /api/tasks/batch-status`、`POST /api/tasks/batch-cancel`。

### 1.2 CLI

```bash
# 全量分析：产出 <镜像名>_raw.db / _events.db / _files.db
./build/forensic_analyzer evidence.E01

# 指定平台与数据源
./build/forensic_analyzer evidence.E01 --android-analyze --android-source tsk
./build/forensic_analyzer evidence.E01 --windows-analyze
./build/forensic_analyzer evidence.E01 --linux-analyze

# 应用过滤 profile（config/filter_profiles/ 下）
./build/forensic_analyzer evidence.E01 --filter-profile telecom_fraud

# 无 AI 环境
./build/forensic_analyzer evidence.E01 --no-ai
```

---

## 2. 查询任务进度与结果

```bash
# 任务列表 / 单个任务
curl http://localhost:8666/api/tasks/list
curl http://localhost:8666/api/tasks/<task_id>

# 进度（含当前阶段）
curl http://localhost:8666/api/tasks/<task_id>/progress

# 结果
curl http://localhost:8666/api/tasks/<task_id>/results

# 任务产出的数据库路径
curl http://localhost:8666/api/tasks/<task_id>/databases

# 统计与审计
curl http://localhost:8666/api/tasks/statistics
curl http://localhost:8666/api/tasks/<task_id>/audit-log

# 清理任务（也用于清掉僵死任务）
curl -X POST http://localhost:8666/api/tasks/cleanup

# 取消/删除
curl -X DELETE http://localhost:8666/api/tasks/<task_id>
```

任务状态持久化在 `data/tasks.json`（`data` 相对于可执行文件，通常 `build/data`），每个任务的工作区在 `data/tasks/<task_id>/`。

---

## 3. 时间线 / 文件 / 统计查询

全部位于 C++ 服务（`task_id` 参数指定任务，`db_path` 指定数据库）：

```bash
# 时间线（TimelineRoutes）
curl "http://localhost:8666/api/forensics/timeline/comprehensive?task_id=<id>"
# 其他端点：details / distribution / file-activity / suspicious-patterns /
#           user-activity / by-type / by-time-range / by-file / full / statistics-by-period

# 文件分析（FileAnalysisRoutes）
curl "http://localhost:8666/api/forensics/files/largest?task_id=<id>"
curl "http://localhost:8666/api/forensics/files/suspicious?task_id=<id>"
# 其他端点：recent / duplicates / extensions-analysis

# 统计（StatisticsRoutes）
curl "http://localhost:8666/api/forensics/statistics/overview?task_id=<id>"
# 其他端点：file-distribution / activity-patterns / deleted-files-analysis
```

可直接用 sqlite3 查库：

```bash
sqlite3 <镜像名>_files.db "SELECT category, COUNT(*) FROM files GROUP BY category ORDER BY 2 DESC;"
sqlite3 <镜像名>_events.db ".tables"
```

---

## 4. 提取文件

CLI（对已生成的 raw 库按通配符/扩展名提取）：

```bash
./build/forensic_analyzer --database <镜像名>_raw.db \
    --extract-file "*.log" --output-dir extracted_logs

./build/forensic_analyzer --database <镜像名>_raw.db \
    --extract-ext ".doc,.docx,.pdf" --output-dir extracted_docs --include-deleted
```

HTTP（异步任务，基于已完成分析的任务提取；`mode`: `all` / `extension` / `name` / `deleted`，后两者需 `pattern`）：

```bash
curl -X POST http://localhost:8666/api/forensics/extract \
  -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "mode": "name", "pattern": "*.log", "output_dir": "logs"}'

curl http://localhost:8666/api/forensics/extract/status        # 全部任务状态
curl http://localhost:8666/api/forensics/extract/<job_id>      # 单个任务
```

> `output_dir` 只能是相对路径（会被限制在任务的提取目录内，绝对路径与 `..` 会被拒绝）；默认输出在任务提取目录下。

---

## 5. 文件雕刻（恢复已删除文件）

```bash
./build/forensic_analyzer evidence.E01 --carve --carve-out carved_files
```

HTTP 任务方式：创建任务时传 `"file_carving": true`（或 `options.file_carving`）。

---

## 6. 全文索引与搜索

```bash
# CLI：对目录建索引，然后搜索
./build/forensic_analyzer --index /path/to/textdir
./build/forensic_analyzer --search "关键词"

# HTTP（q 必填；index/limit/offset 可选）
curl "http://localhost:8666/api/search/fulltext?q=关键词&limit=50"
curl -X POST http://localhost:8666/api/search/index
```

底层为 Xapian（libxapian）。

---

## 7. 生成报告

```bash
# Markdown 报告（不需要 AI/LLM）
./build/forensic_analyzer evidence.E01 --report --report-path report.md

# 提取文件并转文本（需 python_service 运行中；配合平台分析）
./build/forensic_analyzer evidence.E01 --linux-analyze --dump-text --dump-text-max-size 500M
```

深度报告（叙事、证据引用、最终报告组装）由 Python 服务提供：`/api/reports/*`（forensic_reports / report_evidence / report_generation / report_narrative 四组路由）与 `/api/investigation/*`（调查工作台），详见 `http://localhost:8090/docs`。

---

## 8. 专项分析

```bash
# 内存取证（Volatility3）→ 产出 <镜像名>_memory.db
# 先取对应内核的 ISF 符号（一次性）：
./scripts/build-vol3-isf.sh 6.8.0-110-generic
./build/forensic_analyzer mem.lime --memory-analyze --vol-symbols-dir ~/.cache/volatility3/symbols

# DLL 分析 → <镜像名>_dll.db
./build/forensic_analyzer evidence.E01 --analyze-dlls --dll-threshold 30
./build/forensic_analyzer evidence.E01 --analyze-dlls-only --dll-db /path/dll.db --no-verify-signatures

# 微信 / Android 备份解密
./build/forensic_analyzer backup/ --android-analyze --android-source miui-backup --backup-password-stdin
./build/forensic_analyzer evidence.E01 --android-analyze --wechat-password '<SQLCipher 密码>'

# 磁盘加密（BitLocker / LUKS / VeraCrypt）；密钥文件约定 <imageBase>.part<N>.key
./build/forensic_analyzer disk.img --decrypt --key-dir /path/to/keys --key-password-stdin

# XFS 模式
./build/forensic_analyzer xfs.img --xfs-mode native   # auto / native / pure
```

---

## 9. Graphiti 知识图谱摄取与查询（Python :8090）

前置：Neo4j 运行 + LLM 端点同时加载推理与嵌入模型（见 [Installation.md](Installation.md) 4.4）。

```bash
# 摄取任务数据（mode: full / files_only / events_only / analyzed_only）
curl -X POST http://localhost:8090/api/graphiti/ingest \
  -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "mode": "full"}'
# 变体：POST /api/graphiti/ingest/file（单文件）、/api/graphiti/ingest/events（仅事件）

# 摄取任务状态
curl http://localhost:8090/api/graphiti/jobs
curl http://localhost:8090/api/graphiti/jobs/<job_id>
curl -X DELETE http://localhost:8090/api/graphiti/jobs/<job_id>

# 查询
curl -X POST http://localhost:8090/api/graphiti/search \
  -H "Content-Type: application/json" \
  -d '{"query": "可疑可执行文件", "task_id": "<task_id>"}'
curl "http://localhost:8090/api/graphiti/entities?task_id=<task_id>"
curl "http://localhost:8090/api/graphiti/relationships?task_id=<task_id>"
curl "http://localhost:8090/api/graphiti/graph?task_id=<task_id>"

# 服务状态 / 已有图谱 / 清理
curl http://localhost:8090/api/graphiti/status
curl http://localhost:8090/api/graphiti/tasks
curl -X DELETE http://localhost:8090/api/graphiti/tasks/<task_id>
```

摄取任务队列由 Redis 持久化（未装 Redis 时退化为内存，重启丢失，见 [Troubleshooting.md](Troubleshooting.md)）。

---

## 10. markitdown 文档转 Markdown（Python :8090）

```bash
# 单文件转换
curl -X POST http://localhost:8090/api/markitdown/convert \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/abs/path/doc.docx"}'

# 可用性 / 支持格式
curl http://localhost:8090/api/markitdown/status

# 任务工作区内镜像转换（input_root 下每个文件 → 对应 Markdown）
curl -X POST http://localhost:8090/api/markitdown/convert-one -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "file_path": "...", "input_root": "..."}'
curl -X POST http://localhost:8090/api/markitdown/batch-convert -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "input_dir": "..."}'
```

---

## 11. 分布式 C/S 工作流（Python :8091）

场景：中心服务端（server.main）管理多个取证客户端。客户端注册 → 服务端下发命令 → 客户端轮询取命令并执行 → 上报结果。

```bash
BASE=http://localhost:8091

# 1) 管理员登录拿 JWT（auth 路由，用户体系见 server/api/auth.py）
curl -X POST $BASE/api/auth/login -H "Content-Type: application/json" \
  -d '{"username": "...", "password": "..."}'        # → {"access_token": "...", ...}

# 2) 注册客户端（registration_token 由组织管理员预先生成；hostname 必填，
#    capabilities 描述客户端能力，返回客户端凭证）
curl -X POST $BASE/api/clients/register \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"registration_token": "<token>", "hostname": "lab-client-1", "capabilities": {...}}'

# 3) 给客户端下发命令（command_type: analyze_disk / extract_file / health_check）
curl -X POST $BASE/api/commands \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"client_id": "<client_id>", "command_type": "health_check",
       "parameters": {}, "priority": "normal", "ttl_hours": 24}'

# 4) 客户端侧：凭客户端凭证轮询待执行命令
curl "$BASE/api/commands/poll" -H "Authorization: Bearer <client_token>"
#    执行后回报状态：
curl -X POST $BASE/api/commands/<command_id>/status -H "Authorization: Bearer <client_token>" \
  -H "Content-Type: application/json" -d '{"status": "done"}'

# 5) 客户端上报任务结果 / 服务端查询
curl -X POST $BASE/api/tasks/<task_id>/results -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" -d '[ {...} ]'
curl $BASE/api/tasks/<task_id>/results -H "Authorization: Bearer <token>"
curl $BASE/api/tasks/<task_id>/llm-analyses -H "Authorization: Bearer <token>"

# 辅助
curl $BASE/api/commands/client/<client_id> -H "Authorization: Bearer <token>"  # 某客户端全部命令
curl -X POST $BASE/api/commands/expire -H "Authorization: Bearer <token>"     # 过期清理
curl $BASE/api/clients/<client_id>/images -H "Authorization: Bearer <token>"  # 客户端上报的镜像
```

依赖 PostgreSQL（`DATABASE_URL`）；数据库不可用时服务降级启动（`/health` 显示 `database: degraded`）。前端 `Distributed` 页面即对应此工作流（经 `/csapi` 代理）。

---

## 12. 测试数据与配置

```bash
# 生成测试镜像（scripts/）
bash scripts/create_test_image.sh              # 基础 ext4 test_image.img
bash scripts/create_android_image.sh           # Android 测试镜像
bash scripts/create_multipartition_image.sh    # 多分区
bash scripts/create_ubuntu_real_image.sh       # 更真实的 Ubuntu 系统镜像（推荐）

# 过滤 profile（config/filter_profiles/*.json）
ls config/filter_profiles/
# general_forensics.json  telecom_fraud.json  data_breach.json  virus_intrusion.json

# Volatility3 ISF 符号
./scripts/build-vol3-isf.sh <内核版本>           # 如 6.8.0-110-generic
```

---

## 相关文档

- **[快速入门](QuickStart.md)** - 30 分钟路径
- **[开发指南](Development.md)** - 目录结构与代码位置
- **[故障排查](Troubleshooting.md)** - 症状 → 原因 → 命令

---

**最后更新**: 2026-08-23（以代码为准重写）
