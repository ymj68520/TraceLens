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

## 13. 高级工作流

本节是五个端到端流程的完整走读：多镜像案件、调查工作台、全文索引策略、TOON 消费、
审计日志。每步给出可直接复制的命令与背后的调用链（谁代理谁、状态存在哪）。

### 13.1 多镜像案件完整流程（含 Python 代理链路）

场景：同一案件的 3 个镜像（手机 + 两台电脑），要统一关联分析并出案件级结论。

**第 1 步：为每个镜像创建任务**（C++ :8666，可带各自适合的过滤画像）：

```bash
# 手机镜像走 Android 逻辑提取；电脑镜像各选场景
curl -X POST http://localhost:8666/api/tasks -H "Content-Type: application/json" \
  -d '{"image_path": "/evidence/phone_miui.bak.dir", "scenarios": ["android"],
       "android_source": "miui-backup", "backup_password": "...", "llm_analyze": true}'
curl -X POST http://localhost:8666/api/tasks -H "Content-Type: application/json" \
  -d '{"image_path": "/evidence/pc1.E01", "scenarios": ["windows"], "filter_profile": "data_breach"}'
curl -X POST http://localhost:8666/api/tasks -H "Content-Type: application/json" \
  -d '{"image_path": "/evidence/pc2.dd", "scenarios": ["linux"], "filter_profile": "data_breach"}'
```

等待完成（可轮询 `batch-status` 或看前端 Tasks 页）。**注意：跨镜像分析要求参与任务
已完成分析**（associate-tasks 也只接受已完成的任务）。

**第 2 步：创建案件并挂任务**（Python :8090）：

```bash
curl -X POST http://localhost:8090/api/llm/cases -H "Content-Type: application/json" \
  -d '{"name": "2026-08 数据泄露案", "description": "三设备关联分析",
       "task_ids": ["task_aaa", "task_bbb", "task_ccc"]}'
# → 201，返回 case_id
```

**代理链路**（重要，排障时用）：这一步的调用链是
`浏览器 pythonApi → POST :8090/api/llm/cases → Python multi_analysis.py → C++ POST /api/cases →
CaseManager 落 cases.json`——Python 案件域是 C++ 案件后端的**代理/编排层**，不是独立
存储。因此 `GET http://localhost:8666/api/cases` 与 `GET :8090/api/llm/cases` 看到
同一份数据。已完成的旧任务也可事后挂入（复用分析态不重跑）：

```bash
curl -X POST http://localhost:8090/api/llm/cases/<case_id>/associate-tasks \
  -H "Content-Type: application/json" -d '{"task_ids": ["task_older"]}'
```

**第 3 步：发起跨镜像分析并轮询**：

```bash
# 发起（files_db_paths 为弃用的精确校验提示，权威路径由服务端从 task 解析）
curl -X POST http://localhost:8090/api/llm/multi-image-analysis -H "Content-Type: application/json" \
  -d '{"case_id": "<case_id>", "task_ids": ["task_aaa","task_bbb","task_ccc"],
       "files_db_paths": ["/x/files.db","/y/files.db","/z/files.db"],
       "case_description": "关注外发文档与异常登录", "max_filter_files": 400}'
# → {"job_id": "...", ...}

# 轮询 job（返回 status/progress{stage,message}/result）
watch -n 3 'curl -s http://localhost:8090/api/llm/multi-image-analysis/<job_id>'
```

**回写链路**：job 结束时 Python 会回调 `PUT http://localhost:8666/api/cases/<case_id>/status`
（`{"status":"completed","cross_analysis_job_id":"<job_id>"}`；失败回 `failed`，不阻断）。
之后前端 Cases 页显示完成，`cross_analysis_job_id` 持久化在案件记录里（cases.json）。

**第 4 步：取案件级结论**：

```bash
curl http://localhost:8090/api/llm/cases/<case_id>/analysis-status   # 聚合分析状态
curl http://localhost:8090/api/llm/case-report-by-case/<case_id>     # 案件级报告
# 增量追加新任务时：
curl -X POST http://localhost:8090/api/llm/cases/<case_id>/tasks/incremental \
  -H "Content-Type: application/json" -d '{"task_ids": ["task_new"]}'
```

前端入口：`/cases` 页"组建案件/加入案件"，`createCaseWithTasks` thunk 就是上述
1-2 步的四步编排（详见 [modules/web/Store.md](../modules/web/Store.md)）。

### 13.2 调查工作台全流程（证据→分析→评审→事件→报告发布）

场景：对已完成任务做**二次调查**——证据只读，分析员产出可溯源的二级分析与事件，
最终发布终版报告。全部端点在 Python :8090 的 `/api/investigation/workbench/{task_id}`
下（前端 `/investigation?task_id=` 页即此流程的 UI）。

```bash
TID=task_aaa
WB=http://localhost:8090/api/investigation/workbench/$TID

# ① 总览；若 initialized=false 则 bootstrap（默认 mode=cluster_seed，从事件簇播种）
curl $WB
curl -X POST $WB/bootstrap -H "Content-Type: application/json" -d '{}'

# ② 事件与证据：浏览 bootstrap 生成的事件，看某事件的挂接证据
curl $WB/events
curl $WB/events/<event_id>/evidence
curl "$WB/evidence/detail?evidence_key=<key>"

# ③ 对证据启动二级分析 job（异步），轮询到终态
curl -X POST $WB/evidence/analyze -H "Content-Type: application/json" \
  -d '{"evidence_key": "<key>", "hint": "关注时间窗口内的外发行为"}'
curl $WB/analysis-jobs/<job_id>          # 1.5s 间隔轮询，completed/failed/invalid 终止

# ④ 评审：采纳分析结论（驳回端点按设计固定 409，见下）
curl -X POST $WB/analysis/<analysis_id>/accept

# ⑤ 事件版本与声明：刷新叙事产生新版本，采纳版本/声明使 claims 生效
curl -X POST $WB/events/<event_id>/refresh
curl $WB/events/<event_id>/versions
curl -X POST $WB/events/<event_id>/versions/<version_id>/accept
curl $WB/events/<event_id>/claims/effective      # 当前生效声明
curl $WB/claims/<claim_id>                        # 声明溯源（引用了哪些 evidence）

# ⑥ 组装报告：登记报告证据集 → 生成终版报告 → 发布
curl -X POST $WB/report-evidence -H "Content-Type: application/json" -d '{...}'
curl $WB/final-reports
curl $WB/final-reports/<report_id>/markdown      # 或 /html、/print
curl -X POST $WB/final-reports/<report_id>/publish
```

**契约边界（不是故障）**：workbench 域中 `events/<id>/review`、版本/声明的 `reject`、
`notes` 的 POST 都是**已注册但固定返回 409** 的端点——审阅语义只存在于冻结契约域
（`/api/investigation/analyses/{id}/review`），本地工作台明确不提供。

前端对应：`/investigation` 三栏工作台（左证据/中事件时间线/右分析区）+ 右上角
Final Report Viewer（`/investigation/report?task_id=`）。R2 报告（`/api/reports/generate`，
202 准入 + exact 轮询）是另一条独立链路，适合"快照式"报告而非调查叙事。

### 13.3 全文索引策略：大任务先 filter 后 index

大镜像直接对全量提取目录建索引又慢又大（Xapian 索引体积≈文本量级）。推荐顺序：
**过滤 → 提取 → 索引 → 检索**。

```bash
TID=task_aaa
# ① 任务创建时就选过滤画像（产出 _filtered.db，raw.db 不动）：
#    POST /api/tasks 带 "filter_profile": "telecom_fraud"
#    已有任务也可补做：POST /api/filter/apply {"task_id": TID, "profile_name": "telecom_fraud"}

# ② 只把过滤命中的文件提取到任务提取目录（相对路径，限制在任务工作区内）
curl -X POST http://localhost:8666/api/forensics/extract -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$TID\", \"mode\": \"all\", \"output_dir\": \"filtered_out\"}"
curl "http://localhost:8666/api/forensics/extract/status?job_id=<job_id>"   # 等到 completed

# ③ 对提取目录建索引（source/index 均必填；索引路径必须在 FTS_ALLOWED_ROOT 允许的根内）
curl -X POST http://localhost:8666/api/search/index -H "Content-Type: application/json" \
  -d "{\"source_path\": \"/abs/build/data/tasks/$TID/filtered_out\",
       \"index_path\": \"/abs/build/data/tasks/$TID/search_index_${TID:0:8}\"}"

# ④ 检索（q 必填，index 指向上一步的索引路径）
curl "http://localhost:8666/api/search/fulltext?q=转账&index=/abs/build/data/tasks/$TID/search_index_${TID:0:8}&limit=50"
```

前端 `/search` 页自动推导这两个值：索引名 `search_index_<taskId 前 8 位>`、源路径取
任务的 `extraction_directory`（缺失则回退 `../build/data/tasks/<taskId>/extracted_files`，
`web/src/pages/Search.jsx:21-33`）。CLI 等价物：`--index <目录>` 后 `--search "关键词"`。

注意事项：

- `FTS_ALLOWED_ROOT`（默认 PathManager 数据目录）约束索引路径——索引放到任务目录内
  天然合规，放系统其他位置会被拒绝（防任意文件读取）；
- 二进制文件不会被索引出有用内容；如需文档文本，可先对提取目录跑 markitdown
  batch-convert（§10）再对 Markdown 输出目录建索引；
- 重复建同名索引会重建，大任务建议一次建好多次复用（`index` 参数按路径寻址）。

### 13.4 TOON 导出与消费示例

TOON 是"首行 schema + 管道符分隔行"的紧凑文本格式（比 JSON 省 30-60% token），用于
把文件证据喂给 LLM。

```bash
TID=task_aaa
# 导出（C++ 直出；fields 选列、filter 过滤行）
curl "http://localhost:8666/api/forensics/export/toon?task_id=$TID&include_llm=true" -o task.toon
# Python 侧等价端点（/api/db 前缀）
curl "http://localhost:8090/api/db/tasks/$TID/export/toon" -o task.toon
head -3 task.toon
```

输出形如（首行声明列序，`# records[n]` 预告规模，每行一条记录）：

```text
TOON.schema: name | path | size | category | llm_summary | ...
# records[123]
photo.jpg | /dcim/photo.jpg | 204800 | Images | A photo of ...
report.docx | /docs/report.docx | 40960 | Documents | 2026Q2 财务报表...
```

**消费方式一（人工）**：把 task.toon 全文粘贴进任意 LLM 对话，附一句
"按首行 schema 对齐列"，即可提问（找异常、聚类、写摘要）。这是零代码路径。

**消费方式二（程序分批）**：Python 的 CppBackendService 提供 TOON 流式切分——
`get_files_toon_stream(batch_size, include_llm)` 把导出文本按 `TOON.schema:` 行与数据行
切开，返回 `{schema, data_lines, total_files, batch_size}`，供下游按批送入 LLM
（Graphiti 摄取的 TOONTransformer 同源）。批量阈值建议从 50 行/批起步，
按模型上下文调整。

**消费方式三（Windows 报告）**：`GET /api/llm/windows-export/{task_id}/toon` 输出
Windows 场景分析结论的 TOON 形态，可直接并入案件卷宗。

### 13.5 审计日志查询工作流

审计库是独立的 SQLite（默认 `forensics_audit.db`，**相对服务进程 CWD**——run.sh 启动
即 `build/` 下；仓库根出现的同名文件是 CWD 漂移所致，见 AuditLog 模块文档第 7 节）。
单表 `audit_logs(task_id, timestamp(Unix 毫秒), action, details, user_id)`，WAL 模式。

**HTTP 路径**（任务维度，最常用）：

```bash
# 最近 50 条（limit/offset 分页）
curl "http://localhost:8666/api/tasks/task_aaa/audit-log?limit=50&offset=0"
# → {"task_id": "...", "logs": [{"timestamp": 1724...123, "action": "...", "details": "...", "user_id": "..."}], "count": 50}
```

**sqlite3 直查**（跨任务汇总、时间窗、动作分布——HTTP 不提供这些维度）：

```bash
sqlite3 build/forensics_audit.db "SELECT action, COUNT(*) FROM audit_logs GROUP BY 1 ORDER BY 2 DESC;"
sqlite3 build/forensics_audit.db "SELECT datetime(timestamp/1000,'unixepoch','localtime'), action, user_id
  FROM audit_logs WHERE task_id='task_aaa' ORDER BY timestamp DESC LIMIT 20;"
sqlite3 build/forensics_audit.db "SELECT task_id, COUNT(*) FROM audit_logs
  WHERE timestamp > (strftime('%s','now','-24 hours')*1000) GROUP BY task_id;"
```

**工作流建议**：出报告前跑一遍"任务动作清单"（第二条查询），把关键动作
（创建/过滤/提取/LLM 分析）与时间戳纳入证据保管链叙述；`user_id` 在本地模式多为
空/默认值，分布式模式下来自 JWT 身份。审计不可关（任务存在即写），写入经缓存批量
落库，读接口优先读缓存。

---

## 相关文档

- **[快速入门](QuickStart.md)** - 30 分钟路径
- **[开发指南](Development.md)** - 目录结构与代码位置
- **[故障排查](Troubleshooting.md)** - 症状 → 原因 → 命令

---

**最后更新**: 2026-08-24（扩充：高级工作流/深挖工具箱/产出导览）
