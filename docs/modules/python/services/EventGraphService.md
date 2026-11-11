# EventGraphService（python_service/httpserver/services/event_graph/ 子包：service/models/inference/snapshot）

> **一句话**：调查事件 ↔ 证据 ↔ 人员版本的关联分析——从 investigation.db 的一次性只读快照出发（事件、证据、精确叙事），可选绑定一个已完成的人员图谱版本，LLM 产出"事件-证据-人"关联结构；同一张 graph_analysis_runs 表（operation=event_association），完整复用 PeopleGraphService 的 owner epoch、单槽准入与关停，自身零独立管理状态。

## 1. 为什么有这个模块

调查工作台的中栏时间线给出了事件与证据，人员图谱给出了人；"哪个事件牵涉哪些证据、哪些人"的关联则是第三步。本服务把这一步做成与人员图谱同构的版本化分析：输入是一个**冻结快照**（snapshot.py:1 docstring："One read transaction; exact event narratives and evidence snapshots, no bootstrap"——只读既有调查数据，绝不触发 bootstrap 或补捕获），输出是带逐字引用的关联结构，连同 freshness 三态（调查数据是否已变、人员材料是否已变、是否有更新的人员版本）一起随图返回——分析结论与它所依据的数据版本永远一起出现。

定位声明（event_graph/service.py:11-12 类 docstring）："Shares the people manager's owner epoch, queue, admission and shutdown"——它不自己管并发，`__init__(self, manager)`（:13-14）直接持有 PeopleGraphService 实例，由 ServiceManager 在 people_graph_service 首次访问时挂载（service_manager.py:586-590 `manager.event_views = EventGraphService(manager)`）。

## 2. 在系统中的位置

- **谁调用它**：routes/graphiti_endpoints/_events.py：`GET /event-views`（:42-48，**免分析**的活快照投影）、`GET /event-views/detail`（:50-56，带 source_version 的精确回查）、`POST /event-analysis/runs`（:58，202）、`GET .../runs`（:66）、`GET .../runs/{id}`（:74）、`GET .../runs/{id}/graph`（:82）、`GET .../runs/{id}/detail`（:90）、`POST .../runs/{id}/cancel`（:98）。前端 `web/src/services/eventGraphService.js:4-11` 封装，消费方是 `/knowledge-graph` 页 EventGraphPanel/EventGraphCanvas。
- **它调用谁**：PeopleGraphService（`_scope`/`_slots`/`_admission`/`launch`/`_public` 全部借用）；InvestigationGraphReader（snapshot.py 经 investigation.graph 的 `_project_overlay` 投影）；LLMService（inference.analyze）。
- **它被谁依赖**：无——关系追溯前端面板是最终消费者。

## 3. 核心数据结构

**ViewFilter**（models.py:12-22）：`view ∈ events|evidence|associations`、query、focus_id、relation_kind（九种：event_evidence/shared_evidence/analysis_evidence/analysis_claim/claim_evidence/mentioned_in/participation_candidate/related_candidate/inconsistent_candidate）、max_nodes ≤1000、offset/limit。九种关系把"候选推断"与"已确认关联"分开命名——`*_candidate` 后缀的关系永远不是事实断言。

**StartRequest**（models.py:24-31）：task_id、`people_run_id`（可选，正则 `^pg_[a-f0-9]{32}$`——人员版本引用是强类型哈希形状，:26）、`event_ids`（≤50）、case_description ≤8000、requested_by、max_pairs ≤500 默认 100（:30）。**冻结输入**（service.py:61-65）：请求 + `{snapshot, snapshot_hash, selected_event_ids, people, people_result_hash, task_case_hash, policy_version, prompt_version}`——快照与其 digest 一起冻结，后续 freshness 就是拿这份 hash 对比现状。

**run 行**：与人员图谱同一张 `graph_analysis_runs` 表，`OPERATION = "event_association"`（models.py:7-9 的版本三元组）区分；单活跃唯一索引、终态不可变触发器同样生效（见 [PeopleGraphService.md](PeopleGraphService.md) 第 3 节）。

## 4. 核心机制走读

### 4.1 快照：一次读事务的确定性投影（snapshot.py）

`read_snapshot(path, task_id)`（:16-58+）：库不存在返回**全空结构**（含 `store_exists: False` 的 coverage，:17-27——语义"还没有调查数据"而不是错误）；存在则 `InvestigationGraphReader` 在**单个 BEGIN 事务**内读 overlay，事件截 EVENT_LIMIT=500、来源截 SOURCE_LIMIT=2000、共享证据上限 SHARED_LIMIT=5000（:11-13）；来源文本有 1MB 文本 / 4MB payload 双预算（:37），每条截 6000 字符；android_artifact 类证据的 raw_text 用 `record_fields` 的规范化 JSON（kind=android_record，:46-48）。缺失证据节点按 canonical evidence key 补齐为 `evidence:<key>` 节点（:33-38，"Stable source identities are canonical evidence keys, never display names"）。快照是纯函数式的：同一份 investigation.db 状态必得同一 snapshot digest。

### 4.2 start：快照冻结 + 人员绑定 + 借用准入（service.py:35-68）

顺序：服务关停闸（`m._accepting`，:36-38）→ `_snapshot`（任务定位 + store + to_thread 快照，:14-18）→ 空事件直接拒绝（"当前没有已登记调查事件"，:40-41）→ **解引用 people_run_id**（必须同任务已完成版本，未给则取最新 discover/assess 完成版作材料上下文，:45-52）→ `bind_people`（把人员版本的 mentions 映射进事件上下文，:60）→ 冻结输入（:61-65）→ `store.admit`（锁内）→ `m.launch`（复用人员管理器的任务注册与清理）。执行体 `_execute`（:70-82）同样在 `m._slots` + 1800s 超时内：`inference.analyze`（LLM 关联）→ coverage 补 selected/not_selected → store.finish；取消/异常落终态的文案与人员侧同款。

### 4.3 live 视图与版本回查（`live` :20-33、`detail` :117-149）

`GET /event-views` 走 `live()`——**不做任何分析**，直接投影当前快照（filters 过滤）；`GET /event-views/detail`（无 run_id）要求调用方带上当初视图响应里的 `source_version`，digest 不符即 RunConflict"当前调查数据已变化，请刷新图谱后回查"（:129）——回查明细必须与看到的版本严格一致，杜绝"图是旧的、明细是新的"混搭。带 run_id 的 detail 则用冻结快照 + 分析结果合并节点/边，按 source_ids 集合归并出支撑来源（:130-148）。

### 4.4 freshness 三态（service.py:84-102）

status/graph 响应附 freshness：`investigation`（现读快照 digest vs 冻结 snapshot_hash → unchanged/changed/unavailable）、`people_materials`（绑定人员版本的 `source_changes` 漂移检查，未绑定则 not_selected）、`newer_people_version`（是否存在更新的已完成人员版本）、`task_case_changed`。四项合起来回答"这版关联还能信吗"，与人员图谱的 freshness 同构但多了版本间依赖。

## 5. 数据流（读什么库、写什么）

**读**：任务 investigation.db（快照：overlay 事件/证据/证据快照 payload；以及绑定人员 run 的 result）——全部只读；`source_changes` 复用人员侧的漂移探针。**写**：仅 `graph_analysis_runs` 表的 event_association 行（store.admit/progress/finish，经 PeopleGraphStore 同一套连接纪律 ro 默认/rw 显式）。不写调查数据、不写知识图谱。

## 6. 边界与已知状态

- **无调查数据不是错误**：空快照可投影（空 events/evidence/associations 视图），start 才会因"无可分析事件"拒绝。
- **每任务单活跃**：与人员图谱共享同一张表与唯一索引——同一任务的人员分析和事件关联分析也互斥（同一 DB 约束天然覆盖）。
- **人员绑定是松耦合**：绑定的是 `people_run_id + people_result_hash`，人员版本后续更新不自动重跑事件分析，差异由 freshness.newer_people_version 显式暴露。
- **取消与关停**：借 `m._tasks` 注册与 shutdown——EventGraphService 自身没有 cancel 之外的生命周期方法。
- **relation_kind 白名单**：ViewFilter 层枚举闭合，未知 kind 422（Pydantic Literal）。

## 7. 如何验证

- 单测：`python_service/tests/unit/` 下 event_graph 测试（快照确定性/绑定/freshness/九关系投影）；路由测试 graphiti_endpoints/_events（RunConflict→409、版本不符→409）。
- 前端契约：`web/src/services/eventGraphService.js`、`components/knowledge-graph/EventGraphPanel.test.jsx`、`EventGraphCanvas`。
- 活体验证：`/knowledge-graph` 事件关联视图——先在调查工作台 bootstrap 一个任务 → 打开 event-views 活视图 → 发起 event-analysis run → 完成后核对 freshness.investigation=unchanged → 改动调查数据后 detail 回查应 409 并提示刷新。

相关阅读：[PeopleGraphService.md](PeopleGraphService.md)（被借用的管理器）、[InvestigationService.md](InvestigationService.md)（快照数据的来源域）、[Graphiti.md](../httpserver/routes/Graphiti.md)（挂载前缀）。

## 8. 二轮深化 A：为什么快照在 start 时读而不是执行时读

`start` 在冻结输入时就把 `snapshot` 整体塞进 input_json（service.py:61-65），而 `_execute` 只用这份冻结副本调 LLM。两个理由：① **版本一致性**——准入到执行之间调查数据可能变化（分析员在另一个面板 accept 了一条分析），若执行时再读，run 的结论会混搭两个时刻的数据；快照冻结让 run 的语义严格是"对这一版数据的分析"。② **审计可重放**——input_json 里有完整快照 + snapshot_hash，事后无需依赖 investigation.db 仍保持原状即可核对"这个结论依据的是哪些事件叙事与哪些证据文本"。代价是 run 行变大（事件叙事全文入库），由 EVENT_LIMIT/SOURCE_LIMIT/文本预算三重上限约束（snapshot.py:11-13/:37）。freshness 机制则是这份冻结的镜像：正因为冻结不跟随现状，才需要显式的"已变化"信号。

**最后更新**: 2026-11-10（新建：事件关联图谱服务文档）
