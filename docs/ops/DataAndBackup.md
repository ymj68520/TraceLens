# 运行数据管理与备份手册（DataAndBackup）

> 适用场景：日常查看 / 清理任务数据、审计库查询与导出、任务删除、备份与恢复、磁盘治理。
> 前置：C++ 服务从 `build/` 目录启动时，运行数据根为 `build/data/`（`DATA_DIR=data` 是相对可执行文件目录的值，`PathManager.cpp:60-66`）。下文以 `build/data/` 为基准路径。

## 速查卡

```bash
# 数据全景
ls build/data/                       # tasks.json  tasks/  audit/  logs/  reports/
du -sh build/data/tasks/* | sort -rh | head    # 磁盘大户排行

# 任务清单 / 单任务审计
python3 -c "import json;[print(t['id'],t.get('status')) for t in json.load(open('build/data/tasks.json'))]"
curl -s "http://localhost:8666/api/tasks/<task_id>/audit-log?limit=50&offset=0"

# 审计库直查（注意带 -wal 的一致性，先停服或用 .backup）
sqlite3 build/forensics_audit.db "SELECT COUNT(*) FROM audit_logs;"
sqlite3 build/forensics_audit.db "SELECT * FROM audit_logs WHERE task_id='<id>' ORDER BY timestamp DESC LIMIT 10;"

# 审计导出（JSON/CSV）
sqlite3 build/forensics_audit.db ".mode json" "SELECT * FROM audit_logs;" > audit.json
sqlite3 -header -csv build/forensics_audit.db "SELECT id,task_id,timestamp,action,details,user_id FROM audit_logs;" > audit.csv

# 一致性备份审计库（在线安全）
sqlite3 build/forensics_audit.db ".backup '/backup/forensics_audit_$(date +%F).db'"

# 删除任务（RUNNING 任务先用 batch-cancel 取消；无单任务 cancel 端点）
curl -X POST http://localhost:8666/api/tasks/batch-cancel -H 'Content-Type: application/json' \
     -d '{"task_ids":["<task_id>"]}'
curl -X DELETE http://localhost:8666/api/tasks/<task_id>
```

## 1. data/ 目录全景

背景：`PathManager::ensureDirectories()`（`PathManager.cpp:42-48`）在 C++ 启动时创建固定骨架；每个分析任务的所有产物独立成一个目录，SQLite 按任务分库（无全局大库）。

```
build/data/
├── tasks.json          # 任务注册表（所有任务的元数据/状态，TaskManager 持久化）
├── tasks/<task_id>/    # 每任务独立目录
│   ├── raw.db               # 原始文件系统清单（files/partitions 表）
│   ├── raw.db.filtered      # 过滤画像（filter_profile）作用后的精简库
│   ├── events.db            # 时间线事件
│   ├── files.db             # 文件分类 + LLM 分析结果（llm_summary 等列）
│   ├── android.db / oss.db / windows.db / linux.db   # 场景分析库（按所选场景生成）
│   ├── extracted_files/     # 提取出的文件（磁盘大户）
│   ├── extracted_text/      # 提取的文本
│   └── carved_files/        # 文件雕复输出（启用 file_carving 时，TaskManagerAnalysis.cpp:535）
├── audit/              # PathManager 口径的审计目录（见 §2 的双路径说明）
├── logs/               # 应用日志（forensics.log，LOG_FILE）
└── reports/            # 报告输出（FORENSIC_REPORT_DIR 默认 build/data/reports）
```

`tasks.json` 条目含 `image_path`、`extraction_directory`、`filter_profile`、`status`、时间戳等；任务库命名由 `PathManager::getTaskDbPaths()`（`PathManager.cpp:102-115`）决定。

验证：`curl -s http://localhost:8666/api/tasks/list`；单任务库列表 `curl -s "http://localhost:8666/api/system/databases?task_id=<id>"`（返回 raw/events/files 三库路径与大小，`SystemInfoRoutes.cpp:65-117`）。

失败排查：找不到预期数据时先确认 C++ 服务的启动 cwd——DATA_DIR 是相对路径，从别的目录裸启 `forensic_analyzer` 会新建一套空 `data/`。`.env` 中 `PROJECT_ROOT`/`DATA_DIR`（绝对路径）可强制锁定（`src/main.cpp:60-66`）。

## 2. forensics_audit.db：位置、WAL、轮转、导出

背景：审计日志（任务创建/删除/取消、DB_INIT 等动作）写入独立 SQLite 库，由 `AuditLog` 单例管理，WAL 模式 + `synchronous=NORMAL`（`AuditLog.cpp:101-112`）。

### 2.1 实际位置（两套口径，注意）

- **实际运行位置：`build/forensics_audit.db`**（当前环境实测存在，含 `-wal`/`-shm`）。原因：`src/main.cpp:70` 读取 `AUDIT_LOG_DB`，默认相对路径 `forensics_audit.db`，相对**进程 cwd**（= build/）解析。
- `PathManager::getAuditDbPath()` 声明的口径是 `data/audit/forensics_audit.db`（`PathManager.cpp:88-90`），`ensureDirectories` 也会建好 `data/audit/` 目录——但当前 main.cpp 未使用该路径，`build/data/audit/` 实测为空。仓库根的 `forensics_audit.db` 是历史上从根目录启动留下的。
- 若要让审计库落进 `data/audit/`：在 `.env` 设 `AUDIT_LOG_DB=<绝对路径>/build/data/audit/forensics_audit.db`。

### 2.2 WAL 与查询一致性

WAL 模式下最近写入可能在 `-wal` 文件里。只读查询的安全做法：
1. 服务运行中：用 `sqlite3 <db> ".backup '目标'"` 做在线快照（自动处理 WAL）；
2. 服务已停：直接拷贝 `.db` + `-wal` + `-shm` 三个文件，或先 `sqlite3 <db> "PRAGMA wal_checkpoint(TRUNCATE);"` 再拷 `.db`。

### 2.3 轮转与保留现状（如实说明）

`AuditLogConfig` 默认 `max_db_size_mb=100`、`retention_days=30`（`AuditLogDataTypes.h:47-58`），类里实现了 `rotate()`（超 100MB 时改名 `.YYYYMMDD_HHMMSS.backup` 并重建，`AuditLog_Queries.cpp:258-298`）与 `cleanup(retention_days)`（删旧 + VACUUM，`AuditLog_Queries.cpp:219-256`）、`exportToFile(path, json|csv)`（`AuditLog_Queries.cpp:300-332`）——**但仓库内没有任何调用方触发 rotate/cleanup**（启动参数只接了 db_path/cache_size/enable_wal，`main.cpp:68-74`）。因此当前现状是：**审计库不轮转、不自动清理，需人工治理**。`exportToFile` 同样未挂 HTTP 路由，导出走 §速查卡的 sqlite3 命令。

### 2.4 HTTP 查询

`GET /api/tasks/<task_id>/audit-log?limit=50&offset=0`（`TaskMonitoringRoutes.cpp:17`，返回该任务的审计记录）。无全局审计查询端点，全量分析用 sqlite3。

## 3. 任务删除的边界（终端写保护 / TOCTOU 防复活）

背景：删除不是简单 `rm -rf`——后台 LLM/图谱分析线程可能还在跑，直接删目录会被延迟写入"复活"。完整设计见 `docs/hardening/d4b-lifecycle-resource-fixes.md`。

`TaskManager::delete_task`（`TaskManager.cpp:313-360`）流程：
1. 从内存 map 移除 + 立即保存 `tasks.json`（UI 即刻不可见）；
2. 请求 Python 侧删除该任务的 Graphiti 图数据（`LLMPythonProxy::deleteGraphitiData`）；
3. 清理该任务的 LLM 临时提取目录 `<tmp>/forensics_llm_extract/<task_id>/`（D4b）；
4. **非 RUNNING** 任务：立即 `remove_all(task_dir)`；**RUNNING** 任务：只标记取消，由后台线程退出时自查任务已消失后再删目录。

D4b 加固后的终端写保护（`docs/hardening/d4b` B 节）：后台执行器每次**终端写**前都要 ① 查询可信任务注册表确认任务仍存活 → ② 当前可信路径与提交时路径严格相等 → ③ 以 SQLite `mode=rw` 打开（不存在即失败，**不 mkdir/不自愈**）。任务在活性检查后、写库前被删（TOCTOU 窗口）会在"只读打开"处失败关闭，不会重建目录。结论：**删除后 LLM 结果被丢弃，不留 failed 行、不留墓碑**。

操作（注意：**没有单任务 cancel 端点**；取消走 `POST /api/tasks/batch-cancel`，请求体 `{task_ids:[...], reason?}`，`TaskBatchRoutes.cpp:37`）：
```bash
# RUNNING 任务建议先取消（delete 虽会内部置 cancellation_requested，但显式取消可先观察状态收敛）
curl -X POST http://localhost:8666/api/tasks/batch-cancel -H 'Content-Type: application/json' \
     -d '{"task_ids":["<id>"]}'
sleep 5; curl -s http://localhost:8666/api/tasks/<id>         # 确认 status=cancelled
curl -X DELETE http://localhost:8666/api/tasks/<id>           # 路由到 handle_cancel_task → delete_task
```

验证：`build/data/tasks/<id>/` 消失（RUNNING 任务稍等后台线程退出）；`tasks.json` 中无该 id；Neo4j 侧该任务 group_id 的图数据被删（`wipe` 见 ExternalServices.md）。
失败排查：目录删不掉通常是后台线程仍持有文件句柄——等数分钟后复查；孤儿目录（有目录无注册项）会在下次启动时由 `TaskPersistence::cleanup_orphan_directories`（`TaskManager.cpp:69`）清掉。

## 4. 备份什么 / 怎么恢复

背景：**文件级备份即可**——本项目 SQLite 按任务独立分库、无跨库事务、无服务端集中写（C/S 的 PostgreSQL 是另一套，见 ExternalServices.md），不存在"必须用 pg_dump 级工具做一致性快照"的耦合。

备份清单（按重要性）：

| 内容 | 路径 | 说明 |
|------|------|------|
| 任务注册表 | `build/data/tasks.json` | 必备，否则目录成了孤儿（下次启动被清理！） |
| 任务分析库 | `build/data/tasks/<id>/`（`*.db`，可选含 `extracted_files/`） | 取证结论所在 |
| 审计库 | `build/forensics_audit.db`（含 -wal/-shm 或先 checkpoint） | 取证留痕，法规要求时必备 |
| 报告 | `build/data/reports/` | 已生成的报告 |
| 知识图谱 | Neo4j（不在 data/ 内） | 按需；或接受"图谱可由库重摄取" |
| 配置 | `.env`（注意含密钥，备份介质要加密） | |
| C/S 业务库 | PostgreSQL `tracelens` | `pg_dump tracelens > ...`，与本地栈无关 |

操作（冷备，最稳）：
```bash
./run.sh 前台 Ctrl+C 停服
tar -czf tracelens-data-$(date +%F).tgz build/data build/forensics_audit.db* .env
```

在线备（只备库不备提取文件）：
```bash
sqlite3 build/forensics_audit.db ".backup 'bk/audit.db'"
for d in build/data/tasks/*/; do for f in "$d"*.db; do sqlite3 "$f" ".backup 'bk/$(basename $d)_$(basename $f)'"; done; done
cp build/data/tasks.json bk/
```

恢复：停服 → 解包/回拷到原路径 → 启动。C++ 启动时 `load_tasks()` 读 `tasks.json` 恢复任务列表，旧库缺列时由"探测 + ALTER"自愈（见 UpgradeMigration.md §3）。跨机器恢复注意：`tasks.json` 里存的是绝对路径（`image_path`、`extraction_directory`），镜像文件不在原路径时任务会显示路径失效。

## 5. 磁盘占用治理

背景：实测单个中型任务目录可达 ~100MB，多任务累积快；真正的大头是提取/雕复出来的**文件本体**而非 SQLite。

排行与清理：
```bash
du -sh build/data/tasks/* | sort -rh | head
du -sh build/data/tasks/*/extracted_files build/data/tasks/*/carved_files 2>/dev/null | sort -rh | head
find build/data/tasks -name "*.filtered" -size +100M            # 过滤库也可再生
du -sh /usr/share/neo4j 2>/dev/null                              # 图谱数据在 Neo4j 侧
```

策略：
1. **保留库、删文件本体**：取证结论都在 `*.db`，`extracted_files/`/`carved_files/` 可在报告出具后删除（如需再提取，重新跑任务或保留镜像）。
2. **删整个任务**：走 §3 的 DELETE 端点（联动图谱/临时目录），不要手 `rm` 目录（会变孤儿目录，虽然启动时会清，但图谱数据残留）。
3. **图谱瘦身**：`python_service/wipe_neo4j.py` 全量清空（谨慎，见 ExternalServices.md）；或按任务删（delete_task 已联动）。
4. **审计库**：人工 `cleanup` 语义 = `DELETE FROM audit_logs WHERE timestamp < <cutoff_ms>; VACUUM;`（参照 `AuditLog_Queries.cpp:228-250`）。
5. 临时目录：LLM 提取临时文件在 `<tmp>/forensics_llm_extract/<task_id>/`，正常由 RAII/删除任务清理，崩溃残留可手工清。

## 6. tasks.json 与常见数据故障

背景：`tasks.json` 是任务注册表，`TaskManager::save_tasks_internal()`（`TaskManager.cpp:53-61`）在每次任务变更后整体重写；启动时 `load_tasks()` 读取并顺手清理孤儿目录。

- **tasks.json 损坏（非法 JSON）**：启动时加载失败 → 任务列表为空 → **下次保存时孤儿目录会被 `cleanup_orphan_directories` 清掉**。所以发现列表突然变空时**立即停服**，从备份恢复 tasks.json（这也是把 tasks.json 放进备份清单的原因）。
- **手工检查/修复**：
```bash
python3 -m json.tool build/data/tasks.json > /dev/null && echo OK    # 语法校验
# 修复思路：从备份恢复；无备份时手工剔除损坏条目（每条是一个任务对象）
```
- **任务目录在但列表没有**：先停服再决定——不要在有服务运行时手改 tasks.json（服务退出时会用内存态覆盖你的修改）。

## 7. 场景库一览（跨库解读任务目录）

背景：`PathManager::getTaskDbPaths()`（`PathManager.cpp:102-115`）固定七库命名，按任务所选场景（`scenarios`：ANDROID/WINDOWS/LINUX/SERVER_CLOUD，见 `docs/features/forensic-scenario-selection.md`）生成其中若干：

| 文件 | 生成条件 | 内容 |
|------|---------|------|
| `raw.db` | 总是 | 文件清单/分区表 |
| `raw.db.filtered` | 选了 filter_profile 且过滤成功 | 过滤后的精简清单（后续阶段的实际输入） |
| `events.db` | 总是 | 时间线事件 |
| `files.db` | 总是 | 分类 + LLM 列（llm_summary/llm_keywords/...） |
| `android.db` / `windows.db` / `linux.db` / `oss.db` | 选中对应场景 | 场景特化分析结果 |

恢复验证时按"先 raw 后场景"顺序抽查：raw.db 的 files 行数 ≈ 镜像文件数；files.db 的 llm_* 列在启用过 LLM 时非空。

## 与代码的对应

| 机制 | 位置 |
|------|------|
| data/ 骨架与子目录 | `src/core/PathManager/PathManager.cpp:42-48, 60-98` |
| 每任务库命名 | `src/core/PathManager/PathManager.cpp:102-115` |
| 审计库路径配置（AUDIT_LOG_DB，默认相对 cwd） | `src/main.cpp:68-74` |
| 审计 WAL + synchronous=NORMAL | `src/core/AuditLog/AuditLog.cpp:101-112` |
| 审计默认配置（100MB/30d/batch=1 立即写） | `src/core/AuditLog/AuditLogDataTypes.h:47-58` |
| rotate/cleanup/exportToFile（实现存在、未接线） | `src/core/AuditLog/AuditLog_Queries.cpp:219-256, 258-298, 300-332` |
| 任务审计查询端点 | `src/network/HTTPServer/routes/TaskMonitoringRoutes.cpp:17` |
| delete_task 全流程（图谱联动/scratch/延迟删目录） | `src/network/HTTPServer/TaskManager.cpp:313-360`（cancel 语义 `:291-311`） |
| 取消端点（batch-cancel，无单任务 cancel） | `src/network/HTTPServer/routes/TaskBatchRoutes.cpp:37, 134-146` |
| 孤儿目录清理 | `src/network/HTTPServer/TaskManager.cpp:63-70`（load_tasks 内） |
| 终端写保护/TOCTOU 防复活（D4b） | `docs/hardening/d4b-lifecycle-resource-fixes.md` B 节 |
| 任务库列表端点 | `src/network/HTTPServer/routes/SystemInfoRoutes.cpp:15-29, 65-117` |
| carved_files 输出目录 | `src/network/HTTPServer/TaskManagerAnalysis.cpp:535-536` |
| 报告输出目录默认值 | `python_service/httpserver/config.py:214-216`（FORENSIC_REPORT_DIR=build/data/reports） |
| tasks.json 读写/孤儿清理 | `src/network/HTTPServer/TaskManager.cpp:48-70` |
| 场景库命名（七库） | `src/core/PathManager/PathManager.cpp:102-115` |

**最后更新**: 2026-08-24（新建，运维手册）
