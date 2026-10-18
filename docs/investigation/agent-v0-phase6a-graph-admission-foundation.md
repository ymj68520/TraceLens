# TraceLens Agent v0 — Phase 6A: Graph Admission / Frozen Episode / Materialization Manifest

## 0. Baseline / branch / commits

```text
baseline: 5f565265  (P5 frozen HEAD, freeze follow-up included)
branch:   mvp/agent-v0-phase6-investigation-context-graph
schema:   investigation.db v14 -> v15 (additive)
```

| Commit | Content |
| --- | --- |
| `697b807f` | P6A-1 schema v15 + GraphCandidate/admission contracts |
| `2c954b1f` | P6A-2 ForensicGraphEpisode frozen input |
| `4e2938dc` | P6A-3 materialization manifest state machine + atomic admission |
| `1a793dfc` | P6A-4 invalidation foundation + §35 E2E + docs |

P6A 止于 **frozen episode + queued manifest**；不写 Graphiti/Neo4j（P6B）。

## 1. Repository findings（§3 十二问要点）

1. Base KG 摄取 = GraphitiService（`graphiti_parts/_ingest.py`）的文本
   `add_episode` + LLM 抽取——**没有**结构化 frozen episode API（P6B 需 adapter）。
2. Investigation Graph Overlay 只读 facade 已存在：
   `InvestigationGraphReader`（task-scoped、mode=ro）——P6A 不改。
3. 现有 graph 读侧无 materialization provenance——P6A 的 manifest/provenance
   manifest 正是补此。
4. 无任何 materialization/job/status 表 → v15。
5. Graphiti 无法直接吃 frozen episode → P6B adapter 翻译；episode contract
   backend-neutral（§55）。
6. Graphiti/Neo4j 不可用时 SM 已按 optional-enhancement 降级（lazy per-GET
   warning）——与 §31 一致，未改。
7/8. P5 Finding reader：`get/list_investigation_findings(status=...)`，
   review_pending/accepted/rejected + 全 provenance。
9. P5 correlation 只有 deterministic candidates 与 semantic proposals——
   **无 canonical validated correlation**：P6A 的 validated_correlation kind
   预留但当前无生产候选来源（§39 不伪装）。
10. Base KG（`base_graph_provider`）与 overlay reader 由服务层组合，未改。
11. frontend/graph route 无改动。
12. v14 无法容纳 manifest → **v15**。

## 2. GraphCandidateV1（§6-§12）

- `graph-candidate:v1`：proposal，非 admission、非 authority；candidate_id/
  input_hash 由内容确定性派生（set-like 字段 canonical 排序）。
- kind registry `graph-candidate-kind-registry:v1`：evidence_derived_context /
  verified_finding / validated_correlation（versioned，可扩展）。
- 证据边界（§9）：必须 evidence refs 或 canonical semantic object→evidence；
  builder 从 P5 Finding（rejected 连 propose 都拒绝）与纯 typed evidence
  context（如 Evidence↔sha256 occurrence）确定性构建，无 LLM（§37/§38）。
- `GraphCandidateValidator`（§42）：unknown kind / provenance 缺失 /
  evidence key 畸形 / cross-task / forbidden source（analyst_note、
  case_context、agent_reasoning、llm_chain_of_thought、provider_response、
  supervisor_summary、tool_observation_summary、verifier_prose）→ 非法候选
  不进 policy。

## 3. GraphAdmissionPolicy（§13-§18, §47-§48）

- `graph-admission-policy:v1`，deterministic、versioned、`policy_hash` 覆盖
  budget + review 规则 + forbidden-source 规则。
- 词汇精确 `admit / defer / not_admitted`（不与 Analyst Review 混淆）。
- 硬边界（§11，非 calibration）：无 provenance、forbidden source、rejected/
  unknown finding → NOT_ADMITTED；ungrounded hypothesis 无 evidence/findings
  支持 → NOT_ADMITTED。
- verified review_pending → ADMIT 且 resolved_provenance 携带
  `finding_status:<ref>=review_pending`（unconfirmed 显式保留，§12）；
  未验证 review_pending → DEFER；budget 耗尽 → DEFER（§48，provisional seam：
  max_active=50 / max_episode_units=16 / max_candidates_per_cycle=32，P8 校准）。
- §18：admit 仅 = 允许物化；Graphiti 成败属于 manifest 生命周期。

## 4. ForensicGraphEpisodeV1（§19-§23, §49, §52, §55）

- 仅 admit 候选可冻结（defer/not_admitted raise）。
- 微批 = 每 admit 候选一个 `GraphSemanticUnit`，自带 assertion→Evidence 映射
  （unit.evidence_refs）；provenance manifest 每 unit 记录 unit→candidate→
  admission decision→refs→review status（§52 envelope 的数据基底）。
- episode_id/input_hash 覆盖契约版本、identity、canonical 排序的候选/决策
  ids、unit digests、全部 ref 集、review statuses、source revision/hash、
  policy version/hash——输入顺序不变则 hash 不变；review status 或 evidence
  变化 → 不同 hash（新 episode，绝不 UPDATE 旧 episode，§23）。
- backend-neutral：无 graphiti/neo4j/cypher/db_path/callback 字段（静态测试）。

## 5. Materialization Manifest（§24-§32, §45）

- `agent_graph_materializations`：SQLite 是 graph 逻辑有效性权威。状态精确
  `queued/running/active/failed/stale/invalidated/superseded`；状态机触发器：
  queued→running|invalidated；running→active|failed|invalidated；active→
  stale|invalidated|superseded；failed/stale→superseded；终态无出边、永不回
  running（重试 = 新 attempt，P6B）；identity 字段不可变；lifecycle 时间戳
  （started/activated/terminal）由迁移推进自动维护。
- `admit_graph_candidate`（§66 显式入口）：单事务 = 重校验 durable 候选 →
  policy 评估 → INSERT 不可变 decision →（admit）INSERT episode + queued
  manifest → trajectory（graph_episode_frozen / graph_materialization_queued）。
  任一失败整体回滚——admit 而 episode/manifest 缺失结构上不可能（§26）。
- 幂等（§28）：确定性 manifest id（episode_id+backend_kind+investigation），
  相同输入 replay 不重复排队；defer/not_admitted 只持久化 decision（§27）。
- Manifest 变更消费 **零** Working State revision（§45）；PLAN→EXECUTE→
  INTEGRATE→EVALUATE 循环未改（§66）。

## 6. Invalidation / supersession（§33-§36, §60）

`evaluate_graph_invalidation`（确定性 sweep，作用于 queued/running/active）：
- backing Finding → rejected 或消失 → **invalidated**（原物化单元不再合法）
- review_pending → accepted → 旧 slice **stale**（保留但不 trusted
  retrieval）；accepted 语义需要新 candidate/episode/manifest（§36），随后
  `supersede_graph_materialization` 绑定 supersedes 指针并把旧 active 置
  superseded
- Evidence refs 不再 resolve → invalidated
- 无关 Finding 变化 → 无效果
逻辑失效完全独立于物理清理（§34）：P6A 无任何 Graphiti 删除/写入调用
（§63 静态扫描）；P6B reader 按状态过滤。

## 7. Read-side contract stubs（§50-§51）

`GraphReaderMode`（investigation/report）冻结；`retrieval_eligible`：
accepted 两模式均 eligible；review_pending 仅 investigation + verified；
rejected/unknown 任何模式均不可。`GraphProvenanceEnvelope`：无
materialization provenance 的 envelope 不可构造。执行在 P6B。

## 8. Schema v15

四表：candidates / admission_decisions / episodes（均 INSERT-only 触发器）
+ materializations（状态机触发器 ×2）。trajectory 枚举 +5（§44，未加
`graph_materialization_completed`——P6A 不执行 backend）。v14→v15 additive，
P1–P5 数据保全；future v16 fail closed；`_ensure_v7_store` legacy 元组扩至
`(7..14)`。

## 9. Tests

新增 70 个（全套件 853 → 903 passed + 1 opt-in skip）：

```text
test_agent_schema_v15_migration.py        5  fresh/v14→v15 保全/append-only/manifest 守卫/新事件/future v16
test_agent_graph_admission.py            17  §56/§57 全矩阵（候选边界+准入规则+词汇+模式分类）
test_agent_graph_episode.py               7  §58 全矩阵（仅 admit 可冻结/hash 规范化/微批/无后端绑定）
test_agent_graph_manifest.py              9  §59/§61 全矩阵（原子 admit/replay 幂等/零 revision/回滚）
test_agent_graph_invalidation.py          5  §35/§36/§60 E2E + §63 静态扫描
```

## 10. Known limitations / P6B deferred scope

- manifest queued 之后的执行（Graphiti add 翻译、retry/restart recovery、
  running→active/failed 推进的生产触发器）全在 P6B；P6A 只有测试内模拟推进。
- validated_correlation kind 当前无生产候选来源（P5 无 canonical correlation
  对象——按 §39 不伪装）。
- budget 是单机确定性 seam（无跨进程配额）。
- read-side 仅契约 stub；provenance filtering / investigation/report 检索/
  Evidence hydration 全部 P6B。
- 原则不变：**KG locates; Evidence Store proves.**
