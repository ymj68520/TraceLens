# 知识图谱与取证报告教程

> **目标读者**：已完成镜像分析任务、需要把多任务证据汇入案件知识图谱并产出可审计报告/走完调查评审流程的取证分析师。
> **前置条件**：Neo4j 运行（`NEO4J_URI/NEO4J_PASSWORD`）+ LLM 端点同时加载推理与嵌入模型（[Installation](../getting-started/Installation.md) 4.4）；至少一个已完成的分析任务。
> **预计耗时**：60–90 分钟（摄取与报告生成为后台作业，含轮询等待）。
> **端口约定**：C++ 服务 `http://localhost:8666`（run.sh 默认），Python httpserver `http://localhost:8090`。

---

## 0. 场景设定

Linux 入侵教程与 Android 微信教程的两条线索要并案了：服务器镜像任务 `task_server` 与嫌疑人手机备份任务 `task_phone` 各自产出了文件描述、事件簇摘要、登录与聊天证据。你需要：把两份证据放进**同一个案件图谱**做跨镜像关联，生成**版本化、可引用回溯**的取证报告，最后在调查工作台里走完"证据 → 分析 → 评审 → 事件定版 → 终版报告发布"的流程，形成可出庭的作业链。

---

## 1. 前置检查与 Graphiti 自动触发机制

```bash
curl http://localhost:8090/health/ready
curl http://localhost:8090/api/graphiti/status
```

**预期看到**：`ready` 里 `cpp_backend` 为可用（硬依赖），`neo4j/llm` 状态可用（可选依赖，但本教程需要它们）；graphiti status 未显示 disabled。

**触发机制（任务完成即自动摄取）**：HTTP 任务在 FINALIZING 阶段 10% 处，C++ TaskManager 以 **fire-and-forget** 方式调用 `LLMPythonProxy::async_ingest(task_id, FULL)`——不阻塞任务收尾，失败只写审计 WARNING 不回滚任务。成功触发时：

- 审计日志新增 `GRAPHITI_INGESTION` 条目（含 job_id），`GET /api/tasks/<task_id>/audit-log` 可查；
- `graphiti_job_id` 存入任务记录并持久化到 `data/tasks.json`。

查询这次自动摄取的进度：

```bash
curl http://localhost:8090/api/graphiti/jobs          # 全部作业
curl http://localhost:8090/api/graphiti/jobs/<job_id> # 单个作业：status/progress/current_phase
```

需要重跑/补跑时（例如 LLM 曾不可用）：

```bash
curl -X POST http://localhost:8090/api/graphiti/ingest \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_server", "mode": "analyzed_only"}'
```

mode 语义：`full` 全量；`files_only` / `events_only` 按类；`analyzed_only` 只重摄取 `llm_analyzed_at IS NOT NULL` 的文件与事件簇（不重跑 LLM，最省）。

**为什么要看**：任务"completed"不等于"图谱就绪"——摄取是后台作业，跨过了它就直接查图谱会看到空图。

---

## 2. /knowledge-graph 页：检索、实体、关系

前端 `http://localhost:8666/knowledge-graph`，选中任务。对应端点（[Python REST API](../api_reference/Python_REST_API.md) 第 2 节）：

```bash
# 自然语言检索（混合检索 RRF，一次返回节点/边/facts 三层）
curl -X POST http://localhost:8090/api/graphiti/search \
  -H "Content-Type: application/json" \
  -d '{"query": "深夜登录服务器的 IP 与手机上联系人的关联", "task_id": "task_server"}'

# 实体 / 关系 / 可视化图数据
curl "http://localhost:8090/api/graphiti/entities?task_id=task_server"
curl "http://localhost:8090/api/graphiti/relationships?task_id=task_server"
curl "http://localhost:8090/api/graphiti/graph?task_id=task_server"

# 管理：已有图谱任务 / 删除某任务图谱（命名空间隔离）
curl http://localhost:8090/api/graphiti/tasks
curl -X DELETE http://localhost:8090/api/graphiti/tasks/task_server
```

**预期看到**：search 返回按分数排序的三层结果；图谱以 task_id 为命名空间（group_id）互相隔离，`DELETE .../tasks/<id>` 只删该任务的数据。Graphiti 不可用时 search 降级为 Neo4j 文本匹配（命中打固定分），仍能出结果但无语义排序。

**为什么要看**：图谱回答"某 IP/文件/账号/手机号还出现在哪些证据里"——这是单表 SQL 回答不了的跨证据问题。

---

## 3. 案件级多图谱（/cases 跨镜像分析）

### 3.1 建案并关联任务

```bash
# 建案（C++ 案件管理，也经前端 /cases 页操作）
curl -X POST http://localhost:8666/api/cases \
  -H "Content-Type: application/json" \
  -d '{"name": "2026-08 电信诈骗并案", "description": "服务器 + 嫌疑人手机", "task_ids": ["task_server", "task_phone"]}'

curl http://localhost:8666/api/cases            # 案件列表
curl http://localhost:8666/api/cases/<case_id>  # 详情（含任务）
```

### 3.2 跨镜像分析与案件图摄取（Python 侧编排）

```bash
# 关联已完成分析的任务（Python 代理/编排层）
curl -X POST http://localhost:8090/api/llm/cases/<case_id>/associate-tasks \
  -H "Content-Type: application/json" \
  -d '{"task_ids": ["task_server", "task_phone"]}'

# 多镜像关联分析（后台 job；前置是各任务的 files_db_paths）
curl -X POST http://localhost:8090/api/llm/multi-image-analysis \
  -H "Content-Type: application/json" \
  -d '{"case_id": "<case_id>", "task_ids": ["task_server", "task_phone"],
       "files_db_paths": ["/abs/build/data/tasks/task_server/files.db",
                          "/abs/build/data/tasks/task_phone/android.db"],
       "case_description": "诈骗案并案：服务器入侵痕迹与手机聊天关联"}'
curl http://localhost:8090/api/llm/multi-image-analysis/<job_id>   # 轮询状态
```

多镜像分析流水线内部会调用 `GraphitiService.ingest_case_data(case_id, task_ids, files_db_paths)`：读取各镜像中 `is_relevant=1` 的文件描述，打 `[IMG{n}]` 来源标签汇入 **case_id 命名空间的案件图**（与各任务图并存）。增量补任务用 `POST /api/llm/cases/{case_id}/tasks/incremental` 或 `incremental-analysis`（只摄取新任务，episode 带 `related_tasks` 供抽取器建立跨任务边）。

**预期看到**：analysis-status 走向完成；案件图查询复用第 2 节端点、把 `task_id` 换成 `case_id` 语义即可（服务层 `_get_case_graph`）。

**为什么要看**：任务图谱隔离是隔离噪声的手段，案件图谱才是并案推理的场地。

> **历史坑（已修复）**：案例级摄取曾存在 NameError（`_ingest.py` 缺 `from pathlib import Path`），导致 `ingest_case_data` 的聚合块全部落入 except、**案例图静默为空**，日志特征是 "Failed to aggregate files from image"。该问题已于 **2026-08-24 修复**；若你运行旧版本并看到该 warning，升级后重跑摄取即可（[GraphitiService](../modules/python/services/GraphitiService.md) 注意事项）。

---

## 4. 取证报告（/case-intelligence 页）

前端 `http://localhost:8666/case-intelligence` 是报告阅读器：切换"取证快照报告"（版本化快照）与"情报研判报告"两个视图；真正的研判工作区在 `/analysis-center`。三条报告链路（[ForensicReportService](../modules/python/services/ForensicReportService.md)）按需选用：

### 4.1 确定性快照报告（A 链，不经 LLM）

```bash
# 创建报告版本（scope_type 当前实现只支持 task；case 会返回 501）
curl -X POST http://localhost:8090/api/reports \
  -H "Content-Type: application/json" \
  -d '{"scope_type": "task", "scope_id": "task_server"}'      # → 202 + report_id

curl http://localhost:8090/api/reports/<report_id>/status
curl http://localhost:8090/api/reports/<report_id>/manifest
curl "http://localhost:8090/api/reports/<report_id>/categories/<category_id>/pages/1"
curl "http://localhost:8090/api/reports/<report_id>/search?q=cron"
```

**预期看到**：快照目录把任务 `_files.db` 证据渲染成分页 JSON，每页带 sha256、含全文索引（search.sqlite3）；`report_versions` 表以 `UNIQUE(scope_type, scope_id, version)` 记录版本——重跑生成**新版本**，旧版不可变。

### 4.2 LLM 叙事报告（R2 链）

```bash
# 前置：任务已登记报告证据（无证据返回 409）——通常经调查工作台第 5 节的 report-evidence 流程完成
curl -X POST http://localhost:8090/api/reports/generate \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_server", "requested_by": "analyst_zhang"}'   # → 202 + generation_id

curl http://localhost:8090/api/reports/generations/<generation_id>   # 轮询状态
curl http://localhost:8090/api/reports/narrative/versions/<report_id>
```

**预期看到**：准入行冻结 `input_hash`（LLM 只见冻结字节），生成完成后状态 ready；叙事章节带证据引用，引用回溯可到冻结信封里的证据 ID——引用无效的 FACT 会被降级为 HYPOTHESIS（[InvestigationService](../modules/python/services/InvestigationService.md) 第 1 节第 3 条）。

**为什么要看**：这是"AI 写报告但每个结论可回查证据"的机制核心；409 时先回工作台补证据绑定，不要绕过。

### 4.3 情报研判报告（历史 Chain B 视图）

`/case-intelligence` 页默认展示取证快照/叙事报告；加 `?tab=intelligence` 切到历史情报视图，对应 `routes/intelligence_report.py`：

```bash
curl http://localhost:8090/api/llm/intelligence-report/task_server           # 分章节正文
curl http://localhost:8090/api/llm/intelligence-report/task_server/records   # 报告记录
curl "http://localhost:8090/api/llm/intelligence-report/task_server/search?q=登录"
curl -X PUT http://localhost:8090/api/llm/intelligence-report/task_server/metadata \
  -H "Content-Type: application/json" -d '{"title": "2026-08 并案研判"}'
```

**预期看到**：章节正文来自此前多镜像/案件分析流水线写入的研判记录；`search` 是报告内检索。注意这条是**历史兼容链路**——当前报告工作流默认走 R2 叙事链（4.2），旧内容必须显式加 query 才能看到（前端注释原话）。

---

## 5. 调查工作台（/investigation：证据 → 分析 → 评审 → 事件版本 → 终版报告）

前端 `http://localhost:8666/investigation`，选任务。API 走 `/api/investigation`（规范栈）与 `/api/investigation/workbench`（按任务聚合门面），完整端点表见 [Python REST API](../api_reference/Python_REST_API.md) 第 7/8 节。标准流程：

```bash
BASE=http://localhost:8090/api/investigation

# ① 引导初始化（生成事件/证据骨架）
curl -X POST $BASE/workbench/task_server/bootstrap

# ② 捕获证据快照（证据身份 = task_id + evidence_key；
#    键语法冻结为 file:<规范化路径> 或 cluster:v1:<unix_minute>:<百分号编码的事件类型>）
curl -X POST $BASE/snapshots -H "Content-Type: application/json" \
  -d '{"task_id": "task_server", "evidence_key": "file:/etc/cron.d/backdoor"}'

# ③ 启动二级分析（后台 LLM，202；可带 analyst_note / case_context / related_evidence）
curl -X POST $BASE/analyses -H "Content-Type: application/json" \
  -d '{"task_id": "task_server", "evidence_key": "file:/etc/cron.d/backdoor",
       "analyst_note": "疑似挖矿持久化，重点看执行链"}'
curl $BASE/analyses/<analysis_id>          # 轮询：queued → running → review_pending
curl $BASE/analyses/<analysis_id>/claims   # 分析声明（含引用）

# ④ 评审（对精确版本记 accept/reject/invalid 决策；重做分析永远生成新版本行）
curl -X POST $BASE/analyses/<analysis_id>/review -H "Content-Type: application/json" \
  -d '{"decision": "accepted", "comment": "证据链完整"}'

# ⑤ 调查事件与版本（创建事件连带不可变 v1 叙事版本；refresh 生成新版本）
curl -X POST $BASE/events -H "Content-Type: application/json" \
  -d '{"task_id": "task_server", "title": "攻击者建立 cron 持久化"}'
curl -X POST $BASE/events/<event_id>/evidence -H "Content-Type: application/json" \
  -d '{"task_id": "task_server", "evidence_key": "file:/etc/cron.d/backdoor"}'
curl -X POST $BASE/events/<event_id>/refresh          # → 201，触发事件刷新
curl $BASE/events/<event_id>/versions                 # 版本历史

# ⑥ 终版报告（把钉扎的合法 Section 装配成 FinalReport 并发布）
curl $BASE/workbench/task_server/final-reports
curl $BASE/workbench/task_server/final-reports/<report_id>/markdown
curl -X POST $BASE/workbench/task_server/final-reports/<report_id>/publish
```

**预期看到**：二次分析状态机 `queued → running → review_pending → accepted/rejected/invalid`，终态零出度；事件版本链与声明（claims）都有持久化溯源；终版报告派生 markdown/html/print 多种渲染。

**为什么要看**：这是把"机器产出"变成"可出庭结论"的流程——每一步决策都留痕，证据快照不可变（触发器直接 ABORT 任何 UPDATE）。

### 5.1 研判工作区（/analysis-center）

`/case-intelligence` 页头部的"研判工具"按钮跳转到 `/analysis-center`——这是当前版本的**研判工作区**（案情背景、证据卡片、事件簇、报告预览；见 `pages/CaseIntelligence.jsx` 头注释）。典型用法：

1. 顶部选择任务/案件上下文，先填**案情描述**（`POST /api/llm/case-description` 会转发持久化到 C++ 任务系统，作为后续 LLM 分析的上下文）；
2. 证据卡片对文件/事件簇逐个标记相关性（`POST /api/llm/toggle-relevance` 等）；
3. 报告预览联动 `/case-intelligence` 的两个报告视图。

**为什么要看**：工作台（/investigation）管"评审与版本"，研判中心管"筛选与上下文"——两者配合才是完整的人工分析环节。

---

## 排坑清单

1. **任务 completed ≠ 图谱就绪**：自动摄取是 fire-and-forget，用 `graphiti_job_id` 轮询确认完成再查图谱；摄取失败不影响任务状态，容易漏看。
2. **旧版本的案例图静默为空**：NameError 已于 2026-08-24 修复；看到 "Failed to aggregate files from image" warning 即为旧版症状，升级重摄取（第 3 节注记）。
3. **Neo4j 密码为空是最常见配置错误**：`initialize()` 只告警并把服务置 disabled，图谱端点统一软失败——先 `curl :8090/api/graphiti/status` 再查代码。
4. **摄取队列在 Redis 缺席时是内存态**：重启丢失（回退实现），重启后需要重新触发摄取；[Troubleshooting](../getting-started/Troubleshooting.md) 有 Redis 排查。
5. **固定 409 的端点是契约边界不是故障**：工作台的 `POST .../events/{id}/review`、`.../versions/{id}/reject`、`claims/{id}/reject`、`POST .../notes` 按设计返回 409（[Python REST API](../api_reference/Python_REST_API.md) 第 8 节注记）。
6. **`POST /api/llm/case-analysis` 已退役（410）**：旧链路统一走 report generation（`POST /api/reports/generate`）。
7. **报告生成 409 = 无报告证据**：先经调查工作台的 report-evidence 流程绑定证据再 generate，不要直接绕（第 4.2 节）。
8. **`POST /api/reports` 的 `scope_type=case` 尚未实现**：service 层直接 `NotImplementedError`（路由表现为 501）；案件级的"报告"当前靠任务级 R2 报告 + 案件图/多镜像分析组合呈现，前端 case 上下文页会回落到可用视图。
9. **进度可能瞬时回跳**：摄取作业的进度回调用 fire-and-forget 异步更新，顺序不保证，轮询端做单调显示处理（[IngestionJobManager](../modules/python/services/IngestionJobManager.md)）。
10. **案件图查询别用错命名空间**：任务图端点带 `task_id`，案件图在服务层走 `_get_case_graph(case_id)`；跨镜像分析没跑完就查案件图，得到空图是正常时序问题，先查 `analysis-status`。

---

## 延伸阅读

- [GraphitiService](../modules/python/services/GraphitiService.md) — episode 化摄取、命名空间隔离、检索降级
- [ForensicReportService](../modules/python/services/ForensicReportService.md) — 三条报告链路与版本表/触发器约束
- [InvestigationService](../modules/python/services/InvestigationService.md) — 二次调查域 schema v7 与状态机
- [Python REST API](../api_reference/Python_REST_API.md) 第 2/5/6/7/8 节 — 端点参数全表
- [Linux 入侵排查教程](LinuxIntrusion.md) / [Android 微信取证教程](AndroidWechat.md) — 产出任务的上游流程

---


## 练习与扩展实验

- [ ] 练习 1：按本教程流程走一遍后，把关键中间结果（job_id/表行数/端点响应）记录成你自己的实验日志模板。
- [ ] 练习 2：故意制造一次失败（如停掉 Neo4j/输错令牌），观察降级表现并对照 Concurrency/Security 文档的解释。
- [ ] 练习 3：把教程中的 curl 换成你趁手的客户端（httpie/Postman），沉淀成集合。
- [ ] 扩展实验 A：对比"成功路径"与"练习 2 的失败路径"在审计日志/服务日志里的痕迹差异。
- [ ] 扩展实验 B：用最小 fixture（TestFixtures 里的生成脚本）替代真实证据复现全流程，估算耗时量级。
- [ ] 扩展实验 C：将本教程产出接入报告链（/api/reports），完成"证据→报告"闭环一次。
- [ ] 思考题：这条链路的哪一环是 fire-and-forget？失败了主流程会怎样？（对照 DataFlow 第六幕。）
- [ ] 思考题：如果把本流程放进 C/S 模式（agent 执行），哪些步骤要换端点？（对照 ServiceContracts。）
**最后更新**: 2026-08-24（新建，教程）
