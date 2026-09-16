# 删除功能清理加固（2026-09-16）

## 0. 背景与证据

对全系统 8 个删除入口做了代码调研 + 活体删除测试（自建一次性任务/案件/导入/配置，
Neo4j 播种测试节点验证清理）。结论：各删除动作本身正常，但发现三个"关联内容没删干净"
缺陷与两个低危问题：

| # | 缺陷 | 证据 |
|---|------|------|
| F1 | 案件删除只删 C++ cases.json 记录：案件级 Neo4j 图谱（group_id=case_id）永久孤儿；`<data>/cases/<case_id>/`（跨镜像案件分析 DB）不删 | 活体：删除案件后播种的 2 节点 1 关系原样残留 |
| F2 | 任务删除不摘除案件引用：案件的 `task_ids` 保留死 ID + `task_analysis_states` 残留 | 活体：删任务后 GET case 仍列出该 ID |
| F3 | `POST /api/tasks/cleanup` 只做内存+tasks.json 擦除，不删目录/图谱/scratch → Neo4j 幽灵图谱（KG 页列表读 Neo4j） | 代码：TaskManager::cleanup_completed_tasks 原实现 |
| F4 | 删除图谱不取消在跑摄取 job（kg_sync/队列），job 完成会把已删图谱"复活"成部分图谱 | 代码：delete 路由不触达 ingestion_job_manager |
| F5 | `delete_task_graph` 无论是否命中都返回 success=True "Graph deleted" | 活体：对不存在图谱重复删除仍报 deleted |

下游既有守护（case_aggregation_manager 对缺失 files_db 有 exists() 跳过），所以 F2 不会崩，
但案件统计长期计入死任务。

## 1. 修复设计

### F1 案件删除全链清理（Python 侧收口）

UI 的案件删除唯一路径是 `DELETE /api/llm/cases/{case_id}`（web caseGroupService → python
multi_analysis → C++ proxy）。在该端点 C++ 记录删除成功后追加两步 best-effort 清理，
结果逐项入响应体（`graph_deleted` / `case_data_removed`）：

1. `ingestion_job_manager.cancel_jobs_for_task(case_id)`（与 F4 同机制）；
2. `graphiti_service.delete_task_graph(case_id)` — 案件级图谱以 case_id 为 group_id，
   复用按 group_id 的 DETACH DELETE；
3. `_purge_case_data_dir(case_id)` — 删 `<data>/cases/<case_id>/`。守卫：id 仅允许
   hex/破折号（`[0-9a-fA-F-]{8,64}`），且 resolve 后必须位于 cases 根之内。

C++ `DELETE /api/cases/{id}` 语义不变（仅删记录）；python 侧收口覆盖全部 UI 路径。

### F2 任务删除摘除案件引用（C++）

`CaseManager::remove_task_from_all_cases(task_id)`：遍历 cases_，从 `task_ids` 移除、
`task_analysis_states` 抹除，有变更才重写 cases.json。
`TaskManager::delete_task` 在内存擦除作用域**之外**调用它（无锁嵌套；CaseManager 不反向
依赖 TaskManager，无死锁环）。

### F3 cleanup 复用完整删除（C++）

`cleanup_completed_tasks` 改为两段式：锁内只收集受害者 ID，锁外逐个
`add_audit_log(CLEANUP)` + `delete_task(id)` —— 目录、Neo4j 图谱（python 代理）、
LLM scratch、案件引用与 UI 手动删除完全同构。返回值语义不变（成功删除数）。

### F4 删除前取消在跑摄取（Python）

- `queue_kg_sync_job` 现在把 asyncio.Task 句柄存入 `self._kg_sync_tasks`；
  `_run_kg_sync_job` 在 finally 中弹除。
- `cancel_job` 对 kg_sync job 在状态翻 CANCELLED 后 `task.cancel()` 真正中断 runner
  （runner 内 CancelledError → CANCELLED，链路原有）。
- 新增 `cancel_jobs_for_task(task_id)`：list_jobs(task_id) 过滤 pending/running 逐个取消。
- `DELETE /api/graphiti/tasks/{task_id}` 路由在删图谱**之前**调用它（响应新增
  `cancelled_jobs` 计数）。C++ 任务删除经此路由，自动获得同等保护。

### F5 删除计数如实（Python）

`delete_task_graph` 不再无条件 True：专用 `_run` 里 `result.consume()` 取
`summary.counters.nodes_deleted`，返回 `nodes_deleted > 0`；缓存失效在成功路径照旧
执行（0 节点也失效，防止 list 缓存陈旧）。路由消息维持 deleted/not found 二态。

## 2. 不变量与边界

- 任务删除四清理面（内存+tasks.json、目录、跨服务图谱代理、scratch）行为不变，仅增案件摘除。
- `delete_task` 在任务 RUNNING 时仍走既有延迟清理（RAII 守护，TaskManagerAnalysis.cpp）
  + 启动孤儿目录清扫；本次不改动该路径。
- 案件删除不删关联任务（与前端"仅删案件"语义一致；"删案件及任务"由前端先逐个删任务）。
- `_purge_case_data_dir` 只认目录型残留；案件 DB 若被分析进程持有写句柄，rmtree 可能失败，
  此时响应 `case_data_removed=false` 并留日志（不阻塞案件记录删除）。
- F3 的 cleanup 端点逐任务串行调 python 代理（每次 10s 读超时上限）；大批量旧任务下
  耗时线性，属维护操作可接受。

## 3. 测试

- `tests/unit/test_graphiti_read_path_hardening.py`：FakeResult 升级支持
  `consume()→counters.nodes_deleted`；新增 TestDeleteTaskGraph×4（真删 True / 0 节点
  False 且缓存仍失效 / 查询失败 False / DELETE 语句按 group_id 定向）。
- `tests/unit/test_kg_ingestion_dispatch.py`：新增 TestCancelJobsForTask×3（RUNNING
  kg_sync 被真正中断并置 CANCELLED / 终态与其他任务跳过 / 未知任务 0）。
- `tests/unit/test_case_deletion_cleanup_route.py`（新）：路由级×5（全清 + C++ 404
  短路不触清理 + 图谱失败仍删目录 + 敌意 id 无法逃出 cases 根 + 目录缺失如实报 False）。
- C++：`forensic_analyzer` 全量重编译通过（TaskManager/CaseManager/路由均重编）。
- 活体复测：两端服务重启后重演"案件+播种图谱+假案件 DB 目录+关联任务"场景（见 §4）。

## 4. 活体复测记录（2026-09-16）

- 建案件 → 建任务并关联 → Neo4j 播种案件图谱 + 伪造 `data/cases/<cid>/` →
  删任务：案件 `task_ids` 不再含死 ID（F2 生效）→ 删案件：响应
  `graph_deleted=true, case_data_removed=true`，Neo4j 计数 0、目录消失（F1 生效）。
- 对不存在图谱 `DELETE /api/graphiti/tasks/<ghost>` → `success=false, message="not
  found"`（F5 生效）。

## 5. 余留

- 单 episode 摄取 5 分钟量级（LM Studio 单模型串行）不变，根治需给 graphiti 抽取单独小模型
  （见 kg-ingestion-hardening.md §4）。
- `list_task_graphs` 会把案件级图谱一并列入 KG 页"任务图谱"下拉（group 维度不区分
  task/case），本次未处理。
- cs 认证网关（8091, server.main）有 client/registration-token 两个 DELETE，前端未接线，
  独立产品面，不在本次范围。
