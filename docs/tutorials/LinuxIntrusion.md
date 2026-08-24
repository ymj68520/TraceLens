# Linux 入侵排查端到端教程

> **目标读者**：需要在一台 Linux 服务器镜像上完成"入侵时间线还原 → 持久化定位 → 攻击链归因"的取证分析师。
> **前置条件**：已完成 [快速入门](../getting-started/QuickStart.md)（setup.sh 安装 + `cp .env.example .env`）；建议配置 LLM 端点（`LLM_BASE_URL`），无 LLM 也可走完全流程但会缺少 AI 摘要。
> **预计耗时**：60–90 分钟（含镜像生成与全量分析）。
> **端口约定**：本文 curl 一律用 `http://localhost:8666`（`./run.sh` 未设置 `HTTP_SERVER_PORT` 时的默认；若你用 `make cpp` 或在 `.env` 设了 `HTTP_SERVER_PORT=8080`，请相应替换）。

---

## 0. 场景设定

某公司一台对外提供 SSH 服务的 Ubuntu 服务器被运维发现 CPU 占用异常。安全团队关闭了机器、用 `dd` 制作了一块完整磁盘镜像 `ubuntu_real.img`（本教程用项目自带的脚本生成一块"真实感"镜像代替）。你的任务是回答四个问题：**攻击者何时进来、以什么账号进来、在机器上做了什么、留下了什么持久化机制**。

---

## 1. 准备镜像

没有真实案件镜像时，先生成测试镜像（需要 sudo，脚本会挂载 loop 设备并复制本机真实系统内容）：

```bash
sudo bash scripts/create_ubuntu_real_image.sh
# 产出 tests/ubuntu_real.img：GPT + FAT32 EFI + ext4 根分区，
# 表观 900MiB 的稀疏文件，含真实 /etc、/var/log（auth/syslog/journal/wtmp/btmp）、
# shell 历史、轮转 .gz 日志、已删除文件（供雕刻）等取证要素
```

有现成 ext4/E01 镜像可直接用下一步，注意保留原始证据、对**副本**做分析。

**预期看到**：脚本按 `[1/7]…[7/7]` 分步输出，最后打印分区布局；`ls -lh tests/ubuntu_real.img` 表观 900M、`du -h` 实际占用约 200–300M。

**为什么要看**：这块镜像刻意覆盖了 Linux 取证的常见难点（中文文件名、轮转日志、utmp/wtmp 二进制、已删除文件），后面每一步查询都能在它上面得到非空结果。

---

## 2. 启动服务并创建任务

```bash
./run.sh        # 编译 + 启动 C++(:8666) / Python(:8090) / C/S(:8091)，健康检查 C++ 为硬门槛
```

浏览器打开 `http://localhost:8666/`（mock 登录：任意用户名密码），或直接用 curl 创建任务：

```bash
curl -X POST http://localhost:8666/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/abs/path/tests/ubuntu_real.img",
    "scenarios": ["linux"],
    "filter_profile": "virus_intrusion",
    "llm_analyze": true,
    "llm_mode": "smart"
  }'
```

字段依据（`TaskCRUDRoutes::handle_create_task`，见 [C++ REST API](../api_reference/CPP_REST_API.md) 第 1 节）：

- `scenarios`：多选 `android / windows / linux / server_cloud`。也可以**留空不传**——后端 SceneDetector 会探测未过滤 raw.db 的标记路径自动补场景，并在审计日志写一条 `SCENE_DETECTED`（含各平台命中数）。
- `filter_profile`：`config/filter_profiles/` 下的名称，入侵场景推荐 `virus_intrusion`（也可 `general_forensics`）。
- `llm_analyze / llm_mode`：`smart`（默认，优先相关文件）或 `full`。

**预期看到**：返回 `201`，body 含 `id`（形如 `task_xxx`）、`status: "created"`、`scenarios`。

**为什么要看**：任务 ID 是后续所有查询的钥匙；场景选错会导致平台分析器不跑（例如忘了选 `linux` 就不会有 linux.db）。

---

## 3. 跟踪进度与产物库

```bash
curl http://localhost:8666/api/tasks/<task_id>/progress
curl http://localhost:8666/api/tasks/<task_id>/databases
```

任务阶段依次为 `initializing → image_analysis → event_extraction → file_classification → llm_analysis → platform_analysis → finalizing`。任务工作区在 `data/tasks/<task_id>/`（`data` 相对于可执行文件，通常是 `build/data`），产出：

```
data/tasks/<task_id>/raw.db       # 事实层：files / partitions
data/tasks/<task_id>/events.db    # 时间线事件
data/tasks/<task_id>/files.db     # 文件分类 + 场景列 + LLM 列
data/tasks/<task_id>/linux.db     # LINUX 场景工件库（73 张 linux_* 表）
```

**预期看到**：进度接口返回 `overall_percentage` 递增与当前 `phase_description`；databases 接口返回各库路径与 `count`。分析完成后任务状态 `completed`。

**为什么要看**：先确认 linux.db 真的生成了再往下查；若 `scenarios` 漏选，这里不会出现 linux.db，需要重新建任务。

---

## 4. 在 /timeline 页排查可疑时段

打开前端 `http://localhost:8666/timeline`，选中任务。对应后端端点（均需 `task_id` 参数，详见 [C++ REST API](../api_reference/CPP_REST_API.md) 2.1）：

```bash
# 综合时间线：按 300 秒聚簇，返回事件簇
curl "http://localhost:8666/api/forensics/timeline/comprehensive?task_id=<task_id>&cluster=true&bucket=300&limit=500"

# 可疑活动模式（登录后短时间大量改写、深夜批量删除等启发式）
curl "http://localhost:8666/api/forensics/timeline/suspicious-patterns?task_id=<task_id>"

# 事件时间分布（按小时聚合，用来找"异常活跃时段"）
curl "http://localhost:8666/api/forensics/timeline/distribution?task_id=<task_id>"
```

对可疑的事件簇发起 LLM 分析（`time_window` 是整数分钟桶——事件时间戳除以 60 的商；`event_type` 共同唯一标识一个簇，可从 comprehensive 结果的簇数据里取）：

```bash
curl -X POST http://localhost:8666/api/forensics/timeline/clusters/analyze \
  -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "time_window": 28166666, "event_type": "CREATED"}'
```

**预期看到**：comprehensive 返回的事件簇应覆盖镜像时间范围；LLM 分析完成后 events 表对应行会带上 `llm_summary / llm_keywords / llm_is_relevant` 字段（前端时间线页的"AI 分析"标签页可查看）。文案是模型生成的定性描述，**不要**把其中的数字当计数依据——计数一律回到 SQL 查证。

**为什么要看**：时间线簇是"攻击者在某时段集中活动"的第一手线索，LLM 摘要帮你快速读簇，但立案证据要靠第 5 步的表查证。

---

## 5. linux.db 关键表查证（SQL）

以下 SQL 针对任务工作区的 linux.db。表结构定义在 `src/core/DatabaseManager/SQL/linux_analysis_sql_tables.h`（全部带 `linux_` 前缀），完整清单见 [DatabaseSchema](../architecture/DatabaseSchema.md) 第 7 节。

```bash
cd build/data/tasks/<task_id>   # sqlite3 操作建议先切到任务目录
```

### 5.1 登录排查（linux_login_records）

```sql
-- 非工作时段 / 远程来源的成功登录
SELECT username, terminal, remote_host,
       datetime(login_time, 'unixepoch', 'localtime') AS login_at,
       datetime(logout_time, 'unixepoch', 'localtime') AS logout_at,
       is_success
FROM linux_login_records
WHERE is_success = 1
ORDER BY login_time DESC;

-- 同一来源 IP 的失败次数（暴力破解迹象，可与 auth.log 相互印证）
SELECT remote_host, COUNT(*) AS fails
FROM linux_login_records
WHERE is_success = 0 AND remote_host IS NOT NULL
GROUP BY remote_host ORDER BY fails DESC;
```

**预期看到**：应包含镜像中 wtmp/auth.log 还原出的登录会话；测试镜像里能看到本机真实历史登录。列名注意是 `login_time`（Unix 秒）而非字符串时间。

**为什么要看**：回答"何时、何 IP、哪个账号进来"。

### 5.2 持久化机制（linux_persistence_entries）

```sql
-- 高风险持久化项（cron / systemd / rc.local / shell rc 等）
SELECT persistence_type, risk_level, file_path, entry_name, command,
       username, is_enabled, is_suspicious, suspicious_reason
FROM linux_persistence_entries
WHERE is_suspicious = 1 OR risk_level IN ('HIGH', 'CRITICAL')
ORDER BY risk_level;
```

**预期看到**：正常系统会有大量合法 cron/systemd 条目（风险低），重点看 `is_suspicious=1` 或 `command` 指向 `/tmp`、`/dev/shm`、陌生 base64 的行；测试镜像含真实 root crontab 与 systemd 单元。

**为什么要看**：持久化是"攻击者还会回来"的证据，也是处置清单的直接来源。

### 5.3 反取证/日志篡改（linux_tampering_findings）

```sql
SELECT tampering_type, severity,
       datetime(timestamp_start, 'unixepoch', 'localtime') AS start_at,
       datetime(timestamp_end, 'unixepoch', 'localtime') AS end_at,
       description, log_source, evidence
FROM linux_tampering_findings
ORDER BY severity DESC, timestamp_start;
```

**预期看到**：可能的类型包括日志清空、轮转序列缺号（如 auth.log.2 消失）、时间倒流等；每条带时间区间与证据描述。测试镜像若轮转日志齐全，此表可能为空——空表本身就是"未见篡改"的结论，写进报告。

**为什么要看**：解释"为什么时间线上有一段是空的"；与 `linux_timeline_gaps`（时间线空档表）交叉看。

### 5.4 攻击链（linux_attack_chains）

```sql
-- 规则引擎（Sigma 风格 + MITRE ATT&CK 映射）组装的攻击链
SELECT chain_id, attack_type, summary, confidence, timeline
FROM linux_attack_chains;

-- 规则命中明细（T1110 暴力破解 / T1053 可疑 cron / T1078 异常登录等）
SELECT rule_name, attack_stage, attck_technique, severity, description
FROM linux_rule_matches
ORDER BY severity DESC;
```

**预期看到**：`attack_chains` 每行是"Initial Access → Execution → Persistence → …"顺序的事件 ID 序列与摘要；`confidence` 是引擎给的定性分。无入侵行为的镜像上应为空。

**为什么要看**：这是 LinuxFilesAnalyzer 五个推理引擎（关联/时间线/异常/篡改/规则）的最终结论层，直接对应报告的"攻击链"章节；但**链上每个环节都要回到 login_records/persistence 等明细表核实**。

### 5.5 辅助：shell 历史与 auditd

```sql
SELECT username, command, datetime(timestamp, 'unixepoch', 'localtime') AS at
FROM linux_shell_history ORDER BY timestamp DESC;

SELECT datetime(timestamp, 'unixepoch', 'localtime') AS at, syscall_name, exe,
       argv, success, auid
FROM linux_audit_events
WHERE exe LIKE '%/tmp/%' OR exe LIKE '%/dev/shm%'
ORDER BY timestamp;
```

---

## 6. 生成报告

```bash
# 确定性 Markdown 报告（不需要 AI）
./build/forensic_analyzer tests/ubuntu_real.img --report --report-path linux_case_report.md
```

**预期看到**：`linux_case_report.md` 包含镜像概览、文件分类统计等章节；平台工件明细在任务库里，报告中以引用形式出现。

深度叙事报告（叙事章节、证据引用、版本化快照）由 Python 服务提供，流程在 [知识图谱与报告教程](KnowledgeGraphReports.md) 第 5 节展开，此处不重复。

**为什么要看**：报告是交付物；`--report` 路径零依赖，可作为"最小可信产出"兜底。

---

## 7. Graphiti 摄取与图谱查询

任务完成时（FINALIZING 阶段），C++ TaskManager 已 **fire-and-forget** 触发一次 FULL 模式 Graphiti 摄取（`LLMPythonProxy::async_ingest`），`graphiti_job_id` 会写进任务记录，审计日志出现 `GRAPHITI_INGESTION` 条目。手工重跑/补跑：

```bash
# 摄取（前置：Neo4j 运行 + LLM 同时具备推理与嵌入模型）
curl -X POST http://localhost:8090/api/graphiti/ingest \
  -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "mode": "analyzed_only"}'

# 查询 job 进度
curl http://localhost:8090/api/graphiti/jobs/<job_id>

# 自然语言检索 / 实体 / 关系
curl -X POST http://localhost:8090/api/graphiti/search \
  -H "Content-Type: application/json" \
  -d '{"query": "可疑的定时任务", "task_id": "<task_id>"}'
curl "http://localhost:8090/api/graphiti/entities?task_id=<task_id>"
curl "http://localhost:8090/api/graphiti/graph?task_id=<task_id>"
```

**预期看到**：job 状态从 `PENDING` 走到完成；search 返回节点/边/facts 三层结果（混合检索 RRF 排序）。Neo4j 未配置时 `/api/graphiti/status` 显示 disabled，主流程不受影响。

**为什么要看**：图谱回答"这个 IP/文件/账号还出现在哪些证据里"这类跨文件问题，是手工 SQL 之外的第二视角。细节见 [GraphitiService](../modules/python/services/GraphitiService.md)。

---

## 8. CLI 旁路对照（--linux-analyze）

HTTP 任务之外的独立路径，适合快速验证或脚本化：

```bash
./build/forensic_analyzer tests/ubuntu_real.img --linux-analyze --no-ai
```

**预期看到**：在**镜像同目录**产出 `ubuntu_real_raw.db`、`ubuntu_real_events.db`、`ubuntu_real_files.db` 三件套；CLI 模式平台工件**并入 `_files.db`**（没有独立的 linux.db，见 [DatabaseSchema](../architecture/DatabaseSchema.md) 第 1 节产出位置表）。因此 CLI 旁路的查证 SQL 要对着 `_files.db` 里的 `linux_*` 表执行，表名与第 5 步完全一致。

**为什么要看**：两条路径（HTTP 任务 vs CLI）表结构同源（SQL-as-headers），可以互为对照验证解析器的稳定性；差异仅在落库位置与是否有 LLM/审计。

---

## 排坑清单

1. **表名都带 `linux_` 前缀**：是 `linux_login_records` 而不是 `login_records`。所有建表 SQL 在 `src/core/DatabaseManager/SQL/linux_analysis_sql_tables.h`，拿不准先 `sqlite3 linux.db ".tables"`。
2. **events.db 的 `event_correlations` / `event_chains` 恒空**：EventCorrelationEngine 未接入任务流水线（[DatabaseSchema](../architecture/DatabaseSchema.md) 第 3/8 节），跨事件推理请用 linux.db 的 `linux_correlated_events` / `linux_attack_chains`。
3. **端口二义性**：`run.sh` 默认 8666，`make cpp` 与 `.env HTTP_SERVER_PORT` 默认 8080（[快速入门](../getting-started/QuickStart.md) 第 6 节备注）。curl 报 404/连接拒绝先核对端口。
4. **`create_ubuntu_real_image.sh` 需要 root**，且会复制本机 `/etc`、日志等真实内容——演示环境镜像可能携带本机敏感信息（脚本刻意不含 SSH 私钥），不要外发。
5. **CLI 与 HTTP 的库位置不同**：CLI 写镜像同目录，HTTP 写 `data/tasks/<task_id>/`；混用查询时先 `GET /api/tasks/<id>/databases` 确认路径。
6. **LLM 摘要里的数字不可信**：模型可能复述或编造计数；计数一律以 SQL `COUNT(*)` 为准（本文所有"预期看到"均不承诺具体数字）。
7. **自动场景检测依赖未过滤 raw.db**：filter profile 会丢系统噪声，SceneDetector 在过滤之前跑（TaskManagerAnalysis 的 1.4b 步骤）；自定义 profile 剔除 `/etc` 类路径不影响检测，但手改管线时要注意顺序。
8. **服务器/云场景复用同一套表**：SERVER_CLOUD 场景实际执行 `analyzeLinuxData()`，产物是任务目录下的 `oss.db`（linux_* 表族，与阿里云 OSS 取证的 oss.db 同名不同物，见 [DatabaseSchema](../architecture/DatabaseSchema.md) 第 8 节）。

---

## 延伸阅读

- [LinuxFilesAnalyzer 模块文档](../modules/cpp/analyzers/LinuxFilesAnalyzer.md) — 21 个 Phase 与五个推理引擎的实现走读
- [数据库模式](../architecture/DatabaseSchema.md) — linux.db 73 张表分组速查
- [C++ REST API](../api_reference/CPP_REST_API.md) — 时间线/任务/事件簇端点全表
- [常见任务](../getting-started/CommonTasks.md) — 提取、雕刻、全文搜索等工作流
- [知识图谱与报告教程](KnowledgeGraphReports.md) — 从本任务的产物继续走向报告与调查工作台

---


## 练习与扩展实验

- [ ] 练习 1：把本教程的时间窗参数换到镜像的另一时段，重跑第 3 步查询，对比事件量分布。
- [ ] 练习 2：只改 WHERE 的一个条件（如按用户名/按目录），观察结果形态变化。
- [ ] 练习 3：用 SqlCookbook 的 ATTACH 模式把本教程两张表的查询合成一条联查。
- [ ] 扩展实验 A：给同镜像换一个 filter_profile 重跑任务，用"raw 与 filtered 对账"（SqlCookbook 第 2 条）量化画像效果。
- [ ] 扩展实验 B：触发对应平台的 LLM 重分析（/api/llm/analyze/file 或 windows-analysis），对比 llm_analyzed_at 前后的覆盖差异。
- [ ] 扩展实验 C：开启 file_carving 重跑，比较 carved_files/ 与时间线删除事件的数量关系。
- [ ] 思考题：如果时间线在案发时段完全静默，列出三种可能解释及各自的验证查询（提示：时钟/清除/过滤）。
- [ ] 思考题：本教程哪一步的结论会因为"已知恒空表"而不可靠？对照 schema 文档的已知边界复核。
**最后更新**: 2026-08-24（新建，教程）
