# TraceLens Agent v0 — Phase 6B: Graph Materialization / Provenance Reader / Retrieval Modes

## 0. Baseline / branch / commits

```text
baseline: 737c9953  (P6A frozen HEAD)
branch:   mvp/agent-v0-phase6-investigation-context-graph  (same branch)
schema:   investigation.db v15 -> v16 (additive)
```

| Commit | Content |
| --- | --- |
| `8fc6b739` | P6B-1 schema v16 + backend adapter + provenance strategy |
| `ff2bc01d` | P6B-2 materialization executor lifecycle + retry/restart |
| `da0896a3` | P6B-3 provenance-bound graph reader |
| (P6B-4) | hydration + retrieval-mode E2E + docs + freeze gate |

## 1. Repository findings

1. Graphiti ingest = `GraphitiIngestor.batch_ingest(episodes: List[EpisodeData],
   group_id) -> IngestionResult(total_episodes, successful, failed, errors)` —
   文本输入 + LLM 抽取。
2. 返回**只有计数与错误**，无 node/edge/episode uuid 结构化结果。
3. 查询侧 graphiti hybrid search 的 episodes 携带 uuid/name/content ——
   **确定性 episode name 可作绑定锚**（Strategy A/B 混合）。
4. group_id = task_id（task 级 namespace；investigation 无独立 group → reader
   必须本地二次验证，§54）。
5. Base KG 对象无 Evidence provenance → locator_only 分类（§40）。
6. `InvestigationGraphReader` 输出 `OverlayReadResult(events, event_links,
   selections, claims, evidence_types)`——保持不动（§35 选 B：新 facade）。
7. Base KG 与 overlay 由服务层组合（base_graph_provider）——未改。
8. v15 manifest id 唯一确定性 → retry 需要 attempt 维度 → **v16**。
9. Graphiti/Neo4j 故障在 SM 已按 optional-enhancement 降级——未改。

## 2. Schema v16

- `agent_graph_backend_bindings`（append-only sidecar）：binding_id、
  materialization_id、backend_kind/group/episode ref/name、object kind/ref、
  semantic_unit_id、provenance_json。backend object id 永非 canonical identity。
- `agent_graph_materializations` 新列：`attempt_no`（默认 1）、
  `retry_of_materialization_id`——首次 attempt 保持 NULL/1，P6A §28 replay
  幂等不受影响。
- trajectory 枚举 +4：started / activated / failed / retry_queued。
  v15→v16 additive，P1–P6A 数据保全，future v17 fail closed。

## 3. Adapter（§5-§9）

`GraphMaterializationAdapter`：deterministic、无 LLM、无 live DB 读取；
`ForensicGraphEpisodeV1 → GraphBackendEpisodeV1`（确定性 episode name
`tracelens:materialization:{id}`、per-unit body（assertion→evidence 映射）、
machine-readable provenance token）。文本 renderer 仅审计辅助。Graphiti 是
derived index executor，非 semantic authority（§9：backend 抽取的对象可信
上限由 frozen source episode 决定）。

## 4. Executor（§14-§32）

`GraphMaterializationExecutor(runtime_provider, backend_factory,
max_parallel=2)`，显式 dispatch（execute_materialization / execute_batch）：

- **claim**：queued→running 原子 CAS；第二 worker conflict，绝不双 ingest（§59）。
- **frozen input rule**（§7）：只读持久化 episode/decision/manifest；episode
  hash 对 manifest 校验，mismatch → `GRAPH_EPISODE_HASH_MISMATCH`。
- **provenance binding**（§10/§13）：确定性 episode-name 反查 backend ref；
  无法确认 → `GRAPH_PROVENANCE_UNRESOLVED` → failed（fail closed，不伪造）。
- **completion-time revalidation**（§17-§19）：Finding rejected/missing →
  invalidated；review_pending→accepted → stale（新 episode 必需，不改旧
  episode）；Evidence 失效 → invalidated——绝不让失效单元哪怕一瞬间 active。
- **activation**（§81）：bindings + active + trajectory 同一事务；binding 先于
  active 存在，否则整体回滚。
- **failure**（§82/§83）：guarded expected-status + episode hash；late worker
  不能把 invalidated→active 或 superseded→failed。
- **retry**（§22-§25）：新 attempt 行（attempt_no+1，retry_of 绑定 failed 行）；
  replay 返回同一 attempt；仅 transient 后端失败可重试，invalidated/stale/
  provenance-failure 需要新语义 episode。
- **restart**（§26）：running → failed(GRAPH_RUNTIME_RESTART)、queued 保持、
  initialize 不自动 ingest；legacy sweep（recover_interrupted_agent_runtime）
  兼容报告 `obligations_expired` 等。
- **task deletion**（§20）：dispatch 前与 terminal write 前均用 live task
  record 解析 trusted store；task gone → skip，绝不写 stale path。

## 5. TraceLens Graph Reader（§34-§41, §47-§49, §76-§77）

`ProvenanceGraphReader`（facade，不动 `InvestigationGraphReader` 旧 API）。
过滤顺序（§36）：namespace → provenance binding → manifest 必须 **active**
（§37：queued/running/failed/stale/invalidated/superseded 全部立即过滤）→
frozen episode/unit resolve → mode 分类 → **current canonical re-check**
（§47：episode 冻结 review_pending 但 Finding 现 rejected → 查询时排除，
双保险；§48：Finding 已 accepted → 无误拒，冻结 provenance 保留并按当前
资格放行）。trust classes（§76）：`provenance_bound`（完整 materialization
lineage）/ `locator_only`（无 lineage，最多检索提示）。§75：backend 幻觉边
永不升级 canonical，semantic_authority 字段显式标注来源层级（§77）。

## 6. Hydration（§50-§52）

`hydrate_graph_result_to_evidence`：provenance_bound 对象的 Evidence refs
经 `resolve_evidence` 逐个解析；解析失败的对象排除并产生 invalidation
signal（§51 fail closed）。输出只含 resolver-valid Evidence refs——graph id
永不进入 hydration 输出（§43）。P7 Report citation 消费此契约。

## 7. Failure / degradation

Graphiti/Neo4j 不可用 → reader 空/受限结果 + 显式 limitation，绝不阻塞
Investigation（§55）；畸形 backend 结果过滤不崩溃（§71）；legacy Base KG
无 P6 provenance → locator_only，不得伪装 verified Finding（§56/§24）。
Graph 失败只影响 materialization availability 与 graph-assisted retrieval
（§29/§87：不成为 Finalization blocker）。

## 8. Tests

新增 51 个（全套件 903 → 930 passed + 1 opt-in skip，含既有回归）：

```text
test_agent_graph_backend.py           6  adapter 确定性/provenance token/fake backend 失败
test_agent_graph_materializer.py     11  §63/§64/§65 全矩阵（claim 原子/hash 校验/失效竞态/retry/restart/零 revision）
test_agent_graph_reader.py            8  §67-§71 全矩阵（逻辑状态/模式/current canonical/§54 泄漏/§75 幻觉/降级）
test_agent_graph_e2e.py               2  §72/§73 全链 E2E（hydration/report 过滤/accept 演化）
```

（schema v16 迁移矩阵并入 test_agent_schema_v15_migration.py 的 v16 用例。）

## 9. Known limitations / P7 deferred scope

- 生产 GraphitiEpisodeBackend 的 name→uuid 反查依赖 graphiti search API 的
  episode 名匹配；当前 SM adapter 先返回 fixture backend，真实后端启用由
  config 决定（fail-closed 设计使任何 API 偏差落 failed 而非错误信任）。
- 无 backend 物理 cleanup subsystem（§84：best-effort hook 留待需要时）。
- reader query budget（max_nodes/hops）未实现（§91，P8）。
- P7 才进入：ReportOutlinePlan / ChapterSpec / Retrieval Planner /
  Frozen ReportContextPack / Chapter Writer / Assertion Ledger /
  Consistency Review / 报告生成与发布集成。P6 的 report mode 只是过滤。

## 10. 最终不变量（§102）

```text
GraphCandidate != admission          Admission != materialization
Materialization success != semantic truth
Graph node != Evidence               Graph edge != Claim
review_pending != accepted           Graphiti != canonical persistence
Graph path != citation
```

证明链：Graph object → TraceLens materialization provenance → frozen
semantic unit → canonical Finding/Correlation/Evidence refs →
resolve_evidence() → real Evidence。
