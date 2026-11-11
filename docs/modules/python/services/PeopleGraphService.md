# PeopleGraphService（python_service/httpserver/services/people_graph/ 子包：service/models/inference/projection/sources/storage）

> **一句话**：任务域的"人员发现与核查优先级"托管分析——从任务证据材料中逐字引用地发现自然人提及与关系（discovery），结合案情为每个目标建议核查顺序（assess），分析师可显式调整身份归组（identity_review）；每个动作是一条不可变 run 记录（investigation.db 的 graph_analysis_runs 表，DB 触发器背书），全程由共享的准入锁 + 单槽信号量 + owner epoch 管理，无摄取钩子、不写知识图谱。

## 1. 为什么有这个模块

二次调查域解决了"分析员对单条证据的推理"，但"这个案子里有哪些人、谁该先查"是跨材料的聚合问题，且 LLM 直接产出人物关系极易编造。本服务的设计全部围绕"**可验证的引用**"：提示词要求每个人物/关系必须带逐字 quote（inference.py:15 起 DISCOVER："quote必须逐字属于提供的文本并包含相应姓名"），`quote_ref`（inference.py:52-57）在服务端用 `text.find` 验证引用确实存在（不存在即 `QUOTE_OUTSIDE_SOURCE`），并标记 `ambiguous`（同一片段多次出现）；同名不等于同一人（提示词显式声明"相同姓名不代表同一人"），自动归组只认 18 位身份证号且"号码只是材料记载，不等于身份已核验"。分析结果作为**不可变版本**存进任务 investigation.db，`identity_history` 沿版本链携带——分析师的人工归组在后续自动分析中被 `_carry_identity`（service.py:181-196）延续而非覆盖。

定位声明在 service.py:18："Optional managed tasks in the existing Python process; no ingestion hook"——它是"可选托管任务"，不挂摄取回调、不发布报告。

## 2. 在系统中的位置

- **谁调用它**：routes/graphiti_endpoints/_people.py（`/api/graphiti` 前缀）：`POST /people-analysis/runs`（202）、`GET .../runs`（列表）、`GET .../runs/{run_id}`（状态）、`GET .../runs/{run_id}/graph`（投影视图）、`GET .../runs/{run_id}/targets/{target_id}`（溯源详情）、`POST .../runs/{run_id}/identity/review`（人工归组调整）、`POST .../runs/{run_id}/cancel`。前端 `web/src/services/peopleGraphService.js:4-10` 一一封装，消费方是 `/knowledge-graph` 页 PeopleGraphPanel。
- **ServiceManager**：`people_graph_service` 惰性属性（service_manager.py:577-583），以 (cpp_backend, llm, graph_provider) 构造；shutdown 序列里第 364 行参与关闭。
- **它调用谁**：CppBackendService（任务与库路径）、LLMService（discover/assess，`chat_completion` temperature=0、180s 超时，inference.py:39-47）、GraphitiService（`get_priority_snapshot` 取关系优先级覆盖，20s 超时，service.py:69-77/:132-138）、InvestigationRepository（storage.py:1 docstring："Additive tables owned by InvestigationRepository"）。
- **它被谁依赖**：EventGraphService **共享**本服务的管理器（owner epoch、队列、准入与关停，event_graph/service.py:9）——见 [EventGraphService.md](EventGraphService.md)。

## 3. 核心数据结构

**run 记录**（storage.py DDL，:16 起）：`graph_analysis_runs` 表——run_id(PK)、task_id、base_run_id、operation（discover|assess|identity_review|event_association）、status（CHECK running/completed/failed/cancelled）、owner_epoch、actor、phase/progress、input_json/input_hash、result_json/result_hash、error。两个不变量靠 DB 强制：

- **单活跃 run**：`CREATE UNIQUE INDEX ... ON graph_analysis_runs(task_id) WHERE status='running'`（:24-25）——同任务同时只能有一个在跑，第二并发准入直接 IntegrityError；
- **输入与终态不可变**：triggers `graph_analysis_input_immutable`（:26-31，八列任何修改即 ABORT）与 `graph_analysis_terminal_immutable`（:32 起，非 running 状态禁止 UPDATE）——与 forensic_report 域同一"不可变靠数据库不靠自觉"纪律。

**冻结输入**（service.py:91-114 start，冻结字典在 :105-108）：`{**request, case_description, task_case_hash, policy_version, discovery_prompt, priority_prompt, base_hash}`——策略与提示词版本随 run 冻结，事后可回答"这版结论是哪版提示词跑的"。上限常量（models.py:12-16）：MAX_FILES=500、MAX_TEXT=1_000_000、CHUNK_SIZE=3200/CHUNK_OVERLAP=200/MAX_CHUNKS=300。人员/关系模型（models.py:32 起 ExtractedPerson）：kind ∈ person|person_reference|account|organization——系统账号与组织被提示词显式排除出自然人。

## 4. 核心机制走读

### 4.1 生命周期与并发模型（service.py:95-178）

`start`（service.py:91-114）的顺序：关闭闸（`_accepting`）→ 任务与 store 定位（`_scope` :28-32，库路径只信 C++）→ **基线校验**（base_run_id 必须是同任务已完成且 operation ∈ discover/assess/identity_review 的 run，:96-100；assess 模式必须有 base，:101-102）→ 案情 ≤8000 字（:103-105）→ 冻结输入（:106-109）→ **准入锁内** store.admit + launch（:110-114）。执行体 `_execute`（:126 起）在 `self._slots`（Semaphore(1)，全局单槽）+ `asyncio.timeout(1800)` 内跑（:131）：discover 模式 = read_materials → discover（LLM 逐块）→ build_people → 可选优先级图快照；assess 模式 = deepcopy base 结果 + 重评分。**图快照失败不失败分析**（:150-154）——知识图谱不可读时 `graph_coverage.available=False` + 中文 warning"知识图谱暂不可读，人员发现仍保留；关系优先级未覆盖原图"，人员发现照常交付。取消/异常都保证落终态（:174-177，error 文案含异常**类型名**而非内容）。

### 4.2 引用验证（inference.py:52-57 quote_ref）

每条 LLM 输出的 quote 都要过服务端 `text.find`：找不到即 `QUOTE_OUTSIDE_SOURCE`（该条目被拒而非整轮失败），找到但同文本再次出现则 `ambiguous=True`——模糊引用降级为候选信号而不是证据。`ask`（:39-47）的三重护栏：180s 超时；`finish_reason == "length"` 即 `MODEL_OUTPUT_TRUNCATED`（截断输出绝不当结论解析）；content 超 80k 即非法。

### 4.3 人工归组是第一等版本（service.py:246-262 revise_identity）

identity_review 不是"修改结果"而是**再落一条 run**（revise_identity :245-261）：先验 base 已完成、材料未变（`source_changes` 漂移即 RunConflict"材料来源已变化，请先重新发现人员"）；`identity_revision`（projection.py）**先在内存里验证分区合法性**，再进准入锁 admit + finish——验证失败不产生任何持久化痕迹。新 run 的 input 继承 base 全部冻结字段 + identity_decision，`_carry_identity`（:181-196）则在后续 discover 中把 `manually_*` 状态的归组（其 mention_ids 仍在新材料中的部分）搬到新版本，搬移数量进 coverage（identity_groups_carried / not_carried）。

### 4.4 freshness：结论的新鲜度是响应的一部分（`_current` service.py:56-83）

每次 status/graph/detail 都带 ；freshness（10s 内存缓存，>100 条全清）：`materials_changed`（源材料漂移）、`task_case_changed`（案情哈希对比冻结值）、`graph_state`（对结果里冻结的 graph_revision 重算 digest 对比，不可用时 unavailable）——前端据此提示"这版结论可能已过时"，而服务端永不悄悄作废旧版本。

## 5. 数据流（读什么库、写什么）

**读**：任务证据材料（sources.read_materials：任务 investigation.db 的证据快照 + files.db 文本，MAX_FILES/MAX_TEXT 上限）；知识图谱优先级快照（graph_provider，只读）。**写**：仅任务 investigation.db 的 `graph_analysis_runs` 表（PeopleGraphStore 经 InvestigationRepository.prepare_graph_analysis_storage 建表——DDL 循环 storage.py:39-41，prepare 调用 :57）——LLM 输出的结构化结果整体存 result_json。不写 Neo4j、不写知识图谱、不发布报告。

## 6. 边界与已知状态

- **每任务单活跃 run**：DB 唯一部分索引强制；RunConflict → 路由 409。
- **LLM 失败不污染旧版本**：任何异常落 failed 且"既有结果保留"（:172-176）；失败码只含异常类型名。
- **图快照是尽力而为**：不可用时人员发现仍完成（graph_coverage.available=False + warning）。
- **取消有两条边界**（cancel :262-273）：cancel 前 handle 已存在 → cancel 协程并落终态；从未启动过（先于第一个指令被取消）也要在此边界补落 durable 行——不留悬空 running 行。
- **shutdown 序列**（:275-282）：先关 `_accepting` 闸（锁内取快照）→ cancel 全部 → 逐个落"服务关闭中断分析"终态；EventGraphService 共用此关停。
- **freshness 缓存 10s**：审计准确性让位于面板轮询开销，可接受因为底层判定是纯读。

## 7. 如何验证

- 单测：`python_service/tests/unit/` 下 people_graph 测试（quote 验证/身份归组/版本链/存储触发器）；路由测试 graphiti_endpoints/_people（409/404/422 映射）。
- 前端契约：`web/src/services/peopleGraphService.js`、`components/knowledge-graph/PeopleGraphPanel.test.jsx`、`PeopleGraphCanvas`。
- 活体验证：`/knowledge-graph` 人员图谱视图发起 discover → 完成后点开一个人物核对 refs 的逐字引用确实出现在来源文本里 → 手动合并两个同名候选 → 再发起 discover，确认人工归组被携带（coverage.identity_groups_carried ≥ 1）。

相关阅读：[EventGraphService.md](EventGraphService.md)（共享管理器的姊妹服务）、[InvestigationService.md](InvestigationService.md)（investigation.db 的属主与证据域）、[Graphiti.md](../httpserver/routes/Graphiti.md)（挂载前缀与图快照来源）。

## 8. 二轮深化 A：为什么人工归组要先验证后落库

`revise_identity`（service.py:246-262）的顺序是精心安排的：`identity_revision` 在**准入锁外**先跑——它对 base 结果做纯函数式的分区重排（把 request 里的 merge/split 决策应用上去），任何非法操作（把不存在的 mention 挪走、把已核验身份拆散等）在这一步抛 ValueError，路由转 422，**数据库里不产生任何行**。然后才在锁内 admit + finish 一气呵成。这个顺序保证了两个性质：① run 记录的"已完成"必然对应一个合法结果——不存在"落了一条 identity_review run 但结果是坏的"中间态；② 单活跃约束不会被失败的验证占住——若先 admit 后验证，验证失败还得回滚删行，而 graph_analysis_terminal_immutable 触发器让已落行不可变，删除就是对抗数据库。先算后写的代价是验证与落库之间结果可能被并发改动——但 base 的 result_hash 已冻结在 input 里，且单活跃索引保证没有并发 run 在写，这个窗口是安全的。

**最后更新**: 2026-11-10（新建：人员图谱托管分析服务文档）
