# Agent v0 — Phase 5A: Entity / Deterministic Correlation / ProposedClaim / Grounding Foundation

## 0. Baseline / branch / commits

```text
baseline: eb7d5f12  (P4B frozen HEAD, "feat: close agent investigation loop")
branch:   mvp/agent-v0-phase5-correlation-grounding-verification
schema:   investigation.db v12 -> v13 (additive, append-only)
```

| Commit | Content |
| --- | --- |
| `86c0e8ad` | P5A-1 entity occurrence model + identity foundation + schema v13 |
| `59d22bcd` | P5A-2 deterministic correlation engine |
| `c6d5b42a` | P5A-3 proposed claim normalization + §45 resolver seam |
| (P5A-4) | grounding validator + support bundle + explicit pipeline entry + docs |

P5 整体保持 OPEN；P5B（CorrelationAgent / SemanticVerifierAgent /
AssertionPolicy / canonical review_pending closure）在冻结之后于同一分支继续。

## 1. Repository findings (investigation gate)

1. `SpecialistResultV1.claim_candidates` =
   `SpecialistClaimCandidate(candidate_id, text, assertion_class(FACT/INFERENCE/HYPOTHESIS), evidence_refs, limitations)`。
2. `entity_candidates` = `(candidate_id, raw_value, normalized_candidate?, entity_type_candidate?, evidence_refs)`；
   `correlation_candidates` = `(candidate_id, subject_ref, object_ref, relation_hint, evidence_refs, assertion_hint?)`。
3. P4B `AddPendingProposalReference.proposal_ref` 是任意字符串：StateTransitionPolicy 幂等追加进
   `pending_proposal_refs`，IntegrationDecisionValidator 只查类型不查内容。
4. 冻结前**没有** durable proposal 存储（只有 Working State ref）。
5. 调查库中**没有** canonical entity 存储；ContextPack 只留 `relevant_entity_refs` 占位。
6. Base KG = Graphiti 平台读取器（只读、职责不同）；除 path 归一
   （`normalize_evidence_path`，冻结语义：反斜杠归一、不小写）外无任何可复用 normalizer。
7. 可见性重建 `reconstruct_allowed_evidence_ids(initial_refs, observations)` 已是纯函数，但
   ContextPack 初始 refs **从未持久化**（delegation 只存 `context_hash`）——P5A 补齐。
8. rejected/invalid Secondary Analysis 经 `ANALYSIS_REJECTED/ANALYSIS_INVALID`
   （investigation_persistence.py）；事件级 `grounding_status`(valid/partially_grounded/invalid)
   是旧的 analysis 域概念，与 P5A claim grounding 无关（命名空间隔离）。
9. v12 可复用表：agent_investigations / agent_runs / agent_working_state_revisions /
   agent_delegations / agent_trajectory_events / agent_tool_observations /
   agent_delegation_results（append-only 触发器模板）。Evidence 语法只有
   `file:<path>` 与 `cluster:v1:<minute>:<event_type>`。

## 2. EntityOccurrence contract (`agent_entities.py`)

- `entity-occurrence:v1`，frozen + `extra=forbid`。
- 每个 occurrence 绑定**一个真实 Evidence ref**：必须 parse + resolve 成功才生成；
  无 ref / 未解析 / 跨任务 / 不可见的 candidate 一律跳过并记 limitation（§14）。
- `occurrence_id = "entocc:" + sha256(canonical(task_id, evidence_ref, entity_type,
  source_field, raw, normalized, role))[:24]`（§8，与输入顺序无关）。
- 提取源：`SpecialistResultV1.entity_candidates`（§13；不重解析原始 forensic DB）。
  `entity_type_candidate` 必须在 registry 中；模型自报的 normalized 值不信任，
  由 IdentityPolicy 重算。
- temporal anchor 来自 Evidence 自身（file → mtime；cluster → window），确定性。
- `derive_entity_auto_links`：只对 `auto_link_allowed=True`（强标识）分组连接；
  link 是 immutable occurrence rows 的纯派生物，不落表、重启可重算（§16）。

## 3. EntityTypeRegistry (`agent_identity.py`)

`entity-type-registry:v1`，**候选 taxonomy 不冻结**，只注册当前可确定性支持的 10 类：

```text
email / phone / domain / url      -> scoped, global namespace
ip                                -> weak ("same IP ≠ same person/device")
file_hash (md5/sha1/sha256)       -> strong, auto-link sanctioned
path                              -> source-scoped (require source_scope_id)
user_account                      -> realm composite；无 realm = weak
host                              -> source-scoped (require source_scope_id)
process                           -> host(+temporal)；PID 跨 host 永不同一
```

每类 `EntityTypeDefinition(entity_type, version, identity_scope, normalizer_id,
match_class, auto_link, required_qualifiers, allowed_namespaces, limitations)`，
`catalog_hash()` 覆盖全部定义——policy 任何变化都会移动 hash（§53）。

## 4. IdentityPolicy

`identity-policy:v1`，确定性 resolve：raw → canonical（只做表示归一）→ match_key
（scoped 构造）→ IdentityClass（strong / scoped / weak）→ auto_link_allowed
（仅 strong 且 registry 批准）。违规值抛 `IdentityNormalizationError`（fail closed）。
无 LLM merge、无 same-person 推理（§10/§11）。

## 5. DeterministicCorrelationEngine (`agent_correlation.py`)

非 Agent、无模型调用。输入 durable occurrences，输出有界 `correlation-candidate:v1`。
六条规则按稳定优先级（同规则内按 correlation_id 排序，截断确定性）：

| # | relation_family | derivation | assertion_hint |
| --- | --- | --- | --- |
| 1 | same_content_hash | deterministic_match | inference |
| 2 | normalized_identifier_match | deterministic_match | inference |
| 3 | composite_account_match | deterministic_match | inference |
| 4 | url_domain_structure | deterministic_match | inference |
| 5 | structured_co_occurrence | artifact_explicit | observed |
| 6 | temporal_overlap | deterministic_match | hypothesis |

- weak 命名空间（ip / bare account / process）永不进入 identifier 桶（§21 无 pair 爆炸）。
- `causal_status ∈ {not_assessed, non_causal, causal_hypothesis}`；
  `causal_confirmed` 与 `semantic_inference` 在 P5A 不存在（§19/§20）。
  temporal-only 永不 causal，候选自带 limitation。
- bounds：`max_candidates=200`、`temporal_window_seconds=3600`——临时默认，
  config 化，P8 校准（§21）。

## 6. ProposedClaim + ProposalNormalizer (`agent_claims.py`)

- `proposed-claim:v1`：frozen；`proposal_id`/`input_hash` 由单一 before-validator
  从语义字段全量重算（task/investigation、source delegation+result hash+candidate id、
  canonical text、assertion class、sorted evidence refs —— §25）。set-like 字段
  canonical 排序去重：候选/refs 顺序变化不动 id（§55）。
- 来源限定（§24）：`claim_candidates` + 安全映射的 correlation 候选。Working State
  散文 / Analyst Note / Supervisor summary / ToolObservation summary 永不是来源。
- Normalizer 确定性优先（§27/§28）：whitespace canonical；compound 只在显式独立陈述
  分隔符（`;` `；` `。` `||` 换行）上拆分，evidence 全量继承、不重归属（带 warning）；
  连接词 compound（" and "、"并且"、"随后"…）保留原句 + warning，不改写。
  不发明 Evidence、不升级 assertion class。
- §30 冻结硬规则：`FACT + 无 evidence` → 确定性降级 `HYPOTHESIS` + warning
  （`FACT_DOWNGRADED_NO_EVIDENCE`）。
- Correlation → claim 映射（§46）：same-hash → INFERENCE（文本只说 digest 相同，
  拷贝/传输叙事不可达）；co-occurrence → FACT（artifact 直接记录）；temporal →
  HYPOTHESIS；缺 occurrence 引用时映射 fail closed 返回 None。

## 7. Grounding (`agent_grounding.py`)

- `grounding-result:v1`，status ∈ `grounded / partially_grounded / ungrounded / invalid`。
- `DeterministicGroundingValidator`（`deterministic-grounding-validator:v1`）非 Agent、
  零 LLM，按 §32 顺序：contract → key 语法 → task 边界（跨 task = invalid，§37 fail
  closed）→ resolve → 可见性 → invalid/rejected analysis 约束（analysis/obs/graph/LLM
  形态 ref 全被 key 语法拒绝，§34/§35 结构性满足）→ 类型白名单（§38
  `EvidenceRefPolicy`：仅 `file`/`cluster`，来自真实语法）→ FACT 证据要求
  （防御性二次降级）→ status 计算。
- 状态规则（§36）：integrity 违规（malformed / 跨 task / 冒充 / 禁用类型）→ invalid；
  无 valid ref → ungrounded（well-formed 但不可见同属此列，§56 明确）；
  部分 valid → partially_grounded；全 valid+visible+allowed → grounded。
  **grounded ≠ 语义充分**：过度断言的 claim 在合法证据上依然 grounded（测试固定）。
- `grounding_id` 确定性覆盖 (proposal, validator version, policy version,
  input_hash)；input_hash 覆盖可见集——可见性变化 ⇒ 新 grounding 版本行，历史不覆盖
  （§43，UNIQUE(task,inv,grounding_id) + UNIQUE(task,inv,proposal_id,policy_version)）。
- 可见性权威（§33）：默认由 durable provenance 重建 =
  `agent_delegation_evidence_scopes`（v13 新增，ContextPack 初始 refs 首次持久化）
  ∪ 成功 ToolObservation refs，按 delegation 过滤、重启重建一致。
  Correlation 派生 proposal 用显式 union provenance set（`extra_proposal_provenance`），
  绝不因"Evidence 真实存在"自动视为看过。

## 8. EvidenceSupportBundle (`agent_support_bundle.py`)

`evidence-support-bundle:v1`，P5B SemanticVerifier 的冻结输入。只含 grounding
验证过的 refs；每 item = ref + digest（解析元数据字段）+ 可选有界 excerpt
（`HydrationPolicy`：digest_first_bounded，max_items=32 / max_excerpt_chars=512，
P8 可调）+ provenance。同输入 ⇒ 同 bundle_id；grounding 变化 ⇒ bundle_id 变化。
builder 不输出 sufficient/contradicted/confidence 等任何语义支持状态（§40，
P5B 专属）。

## 9. Persistence / provenance chain (schema v13)

v12 → v13 additive：trajectory 枚举 +4（`entity_occurrences_recorded`、
`correlation_candidates_recorded`、`claim_grounding_recorded`、
`claim_proposals_recorded`，载荷仅 counts/指针），六张 append-only 表
（no_update/no_delete 触发器 + composite FK + 自然 id UNIQUE）：

```text
agent_entity_occurrences      UNIQUE(task,inv,occurrence_id)      CHECK verification_status='verified'
agent_correlation_candidates  UNIQUE(task,inv,correlation_id)     CHECK derivation/assertion/causal 枚举
agent_claim_proposals         UNIQUE(task,inv,proposal_id)        CHECK assertion_class
agent_grounding_results       UNIQUE(task,inv,grounding_id) + UNIQUE(task,inv,proposal_id,version)
agent_evidence_support_bundles UNIQUE(task,inv,bundle_id)
agent_delegation_evidence_scopes UNIQUE(task,inv,delegation_id)   INSERT-once，replay hash 不符即 conflict
```

硬约束遵守（§49）：无 verifier 结果表、无 assertion disposition 表、无
review_pending Finding 表、无 Graph 表。

审计链完整（§47）：Evidence → occurrence(occurrence_id, input_hash) →
match（match_key/namespace/policy hash）→ correlation(correlation_id, input_hash) →
proposal(proposal_id, input_hash) → grounding(grounding_id, input_hash) →
bundle(bundle_id, input_hash)，每步含 policy/version 与 created_at。

原子性（§42/§60）：`record_grounded_proposal` 单事务 = proposal + grounding
(+bundle) + trajectory；`_insert_or_replay` 只把自然 id UNIQUE 冲突当作幂等重放，
CHECK/FK/NOT NULL 违规一律回滚——dangling grounding / 半单位结构上不可能。

## 10. Boundaries enforced (tests)

- §61：P5A 持久化零 revision 消耗（revision 1 之后仍无 revision 2）。
- §62：production 模块无 `SemanticVerifierAgent / CorrelationAgent /
  AssertionPolicy / SemanticVerificationResult / ClaimDisposition /
  claim_sufficiency` 等定义（AST 级扫描）。
- §65：`agent_orchestrator.py` / `service_manager.py` 不引用任何 P5A 模块与
  `process_specialist_proposals`——管线只有显式入口，P4 cycle 行为不变。
- §45：`IntegrationDecisionValidator(proposal_ref_resolver=...)` seam；orchestrator
  生产路径恒注入 repo-backed resolver，未持久化的 proposal ref 以
  `INTEGRATION_PROPOSAL_REF_UNRESOLVED` fail closed；无 resolver 的直接模块使用
  保持 P4B 行为。

## 11. Tests

新增 81 个（全套件 697 → 778 passed + 1 opt-in skip）：

```text
test_agent_schema_v13_migration.py    6   fresh/v12→v13 保全/append-only/新事件/future v14 fail closed/scope 持久
test_agent_identity_policy.py         9   §53 全矩阵（normalization≠identity、strong/weak、qualifier、policy hash）
test_agent_entity_occurrence.py      11   §52 全矩阵（确定性 id、source-scoped、auto-link、幂等、跨 task 拒绝）
test_agent_correlation.py            12   §54 全矩阵（六规则、temporal 永不 causal、排序、bounds、持久化）
test_agent_claims.py                 14   §55 全矩阵 + §45 seam（降级、拆分/保留、映射、持久化、resolver）
test_agent_grounding.py              17   §56/§57 全矩阵 + §65 入口 E2E + §61 revision 不变
test_agent_support_bundle.py          4   §58 全矩阵
test_agent_grounding_atomicity.py     6   §60 注入矩阵（CHECK/字段/轨迹/bundle 失败全回滚）
test_agent_p5a_boundaries.py          3   §62/§65 静态边界扫描
```

## 12. Known limitations

- 实体类型目录是保守起步集；扩展 = registry 新定义 + normalizer，不动架构。
- compound 拆分不重归属 evidence（每子句继承全集 + limitation）；更细粒度归属
  属于语义工作（P5B+）。
- correlation 引擎只消费 occurrence-derived 关系；evidence 元数据直读（如
  same-device 结构关系）留待 P5B 按需接入。
- `_ensure_v7_store` 的 legacy 元组自 P4B 起漏掉 v11/v12（存储会被拒），P5A-1 修复为
  `(7..12)`；另有 `agent_integration.py` 函数内 `from .evidence...` 相对导入深度错误
  （P4B 潜伏、未触发路径），P5A-4 修正为 `..evidence`。
- grounding policy version 目前恒为 1；policy 演进语义（多版本并存读侧）P8 前不需要。

## 13. P5B deferred scope

CorrelationAgent；SemanticVerifierAgent（claim_sufficiency / correlation_sufficiency /
question_closure / finalization_review）；SemanticVerificationResult；AssertionPolicy；
ClaimDisposition；canonical Investigation semantic object；review_pending；
Analyst Review handoff。语义支持状态（sufficient / partially_sufficient /
insufficient / contradicted / indeterminate）到 P5B 才出现。P5A 完成后仍保持：

```text
GroundingResult.grounded = "引用的 Evidence 合法、真实、task-scoped、且确实向
                           产生该 proposal 的 Agent 暴露过"
                         ≠ "Evidence 证明了该 Claim"
```
