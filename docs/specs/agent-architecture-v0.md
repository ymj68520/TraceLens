# TraceLens Agent Architecture v0

**文档状态：** Architecture Baseline v0 — Frozen Decisions Consolidation  
**日期：** 2026-09-22  
**适用范围：** TraceLens Agent-driven Investigation / Correlation / Verification / Selective Graph / Report Generation  
**实现状态：** 设计基线；不表示全部代码已经实现。实现前必须重新检查当前仓库真实代码，若本文与仓库实现冲突，以当前仓库实现和 Evidence Integrity 约束为准。

---

## 1. 文档目的

本文把此前已经明确冻结的 TraceLens Agent 架构设计整理为一份单一、可实施、可审计的 `Agent Architecture v0`。它不是重新设计 TraceLens，也不是把现有 `Files / Timeline / KnowledgeGraph / AnalysisCenter / CaseIntelligence / Investigation / Report` 推倒重做，而是在现有稳定能力之上增加一个受控的 Agent Investigation Runtime。

本文使用三种状态标记：

| 标记 | 含义 |
|---|---|
| **FROZEN** | 已冻结的 v0 normative contract。除非明确发起架构变更，不应在实现阶段自行改义。 |
| **CALIBRATION** | 架构方向已定，但具体数值应通过 Benchmark 校准，不在设计阶段拍脑袋冻结。 |
| **TBD** | 之前讨论过但尚未形成最终 contract；实现前需要继续设计或仓库调查。 |

TraceLens Agent v0 的核心目标不是“让 LLM 更自由”，而是把 LLM/Agent 的自由限制在一个可追溯、可验证、可恢复的调查控制系统中：

> 自动流水线负责发现和解析；分析员提供案件语境；Agent/LLM 辅助组织、关联和解释真实 Evidence；任何重要调查结论最终都必须能够回溯到真实 Evidence。

---

## 2. TraceLens 不可破坏的取证分层

### 2.1 既有主链

```text
Evidence
  ↓
Parsing
  ↓
raw.db / events.db / files.db
  ↓
Initial Automated Analysis
  ↓
File Description / Event Cluster / Initial Semantic Artifacts
  ↓
Investigation
  ↓
Secondary Analysis / Correlation / Investigation Event
  ↓
Analyst Review
  ↓
Report Evidence
  ↓
Report
```

Agent Architecture v0 只能在这条链上增加受控能力，不能把不同层级混成一个“Agent Memory”。

### 2.2 必须始终区分的数据语义

```text
Raw Evidence
Parsed Data
Initial AI Analysis
Analyst Context
Secondary AI Analysis
Analyst Accepted Finding
Report Evidence
```

禁止：

- 修改原始 Evidence；
- 修改原 Hash、时间戳或原始解析事实；
- 覆盖 Initial Analysis 历史；
- 把 LLM 输出当 Evidence；
- 把 Analyst Note / Case Context 当 Evidence；
- 未经验证把推断提升为 FACT；
- 让 Report Writer 创建新的 Investigation Finding。

---

## 3. 现有 TraceLens 基础事实与 Evidence Identity

### 3.1 Task-owned storage

HTTP Task 的核心数据仍由 task-owned workspace 管理：

```text
data/tasks/<task_id>/
├── raw.db
├── events.db
├── files.db
└── investigation.db
```

Python 侧通过现有 trusted task lookup 获取路径，例如：

```python
service_manager.cpp_backend.get_task(task_id)
```

Agent Runtime 不允许长期保存任意 DB path 作为身份，更不允许模型提交 `files_db_path`、`events_db_path`、`investigation_db_path` 之类任意文件路径。Task 身份始终是 `task_id`，真实路径必须在执行边界内从 task-owned service 重新解析。

### 3.2 Evidence Identity — FROZEN

Evidence 身份为：

```text
(task_id, evidence_key)
```

典型 Evidence Key：

```text
file:<normalized_path>
cluster:v1:<unix_minute>:<encoded_event_type>
```

路径规范化规则：

```text
\ → /
压缩重复 /
去掉尾部 /
不 lowercase
不使用 os.path.normcase()
```

所有 Evidence 都通过：

```python
resolve_evidence(task_id, evidence_key)
```

解析。Agent、Graph、Report、Verifier 都不得绕过这个 resolver。

### 3.3 Snapshot — FROZEN

Evidence 第一次进入 Investigation 时执行：

```text
capture_if_absent()
```

Snapshot 只插不改；`Initial Analysis` 始终读取 Snapshot。Secondary Analysis、Agent、Graph、Report 不能覆盖它。

---

## 4. Agent Architecture v0 的目标与非目标

### 4.1 目标

Agent v0 解决当前固定/单次 LLM 分析在复杂案件中存在的几个问题：

- 关键 Evidence 分散在不同来源和时间窗口，单次 Prompt 容易漏检；
- 数千到数万 Evidence 不适合全量放入模型上下文；
- Full-task Graph/KG ingest 成本高、噪声大；
- 需要按 Question 迭代搜索、验证、相关性判断和跨源 Correlation；
- 需要区分 FACT / INFERENCE / HYPOTHESIS；
- 需要显式处理 contradiction、coverage、unresolved question；
- 需要让每个 Tool、Claim、Graph relation、Report citation 都能追溯 Evidence；
- 需要在本地模型能力有限、服务可能失败的前提下可恢复、可降级、可 Benchmark。

### 4.2 非目标

v0 不主动扩展：

```text
多人协作
复杂 RBAC / Authentication
Event Merge / Split
Relation-level 人工审核
Overlay 自动发布 Graphiti
全自动案件推理
Google Docs 级报告编辑器
通用 Shell / SQL / Filesystem Agent
任意长生命周期 Agent Memory
通用 DAG / Workflow Engine
```

也不主动重构稳定模块：

```text
Files
Timeline
KnowledgeGraph
AnalysisCenter
CaseIntelligence
```

新增功能优先级仍然是：

```text
新增模块
→ Facade / Adapter 复用
→ 最小修改稳定模块
→ 最后才考虑重构
```

---

## 5. 总体架构

### 5.1 总览 — FROZEN

```text
┌─────────────────────────────────────────────────────────────┐
│                        User / Analyst                       │
│ Evidence + Case Context + optional Goal / Directives       │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │ Case Framing /      │
                  │ Investigation       │
                  │ Charter             │
                  └──────────┬──────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│             Investigation Orchestrator (deterministic)      │
│ lifecycle / scheduling / concurrency / state / budget /     │
│ recovery / finalization                                    │
└───────┬───────────────────┬───────────────────┬─────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
 Supervisor           Source Specialist    Correlation Agent
 decision maker       profile + skills     bounded relations
        │                   │                   │
        └──────────────┬────┴──────────────┬────┘
                       │                   │
                       ▼                   ▼
                Tool Registry        Semantic Verifier
                only data-plane      milestone QC
                execution boundary
                       │
                       ▼
       Existing TraceLens Services / Evidence Resolver
                       │
        ┌──────────────┼─────────────────────┐
        ▼              ▼                     ▼
 Evidence Store   Investigation State   Selective Graph
 raw/events/files investigation.db      Graphiti/Neo4j
        │              │                     │
        └──────────────┴────────────┬────────┘
                                   ▼
                            Report Pipeline
```

### 5.2 三条主要平面

**Control Plane**

```text
Supervisor
→ Orchestrator
→ Delegations / Verification / Graph Requests
```

**Data Plane**

```text
Agent
→ ToolRegistry.execute()
→ Policy
→ Adapter
→ Existing TraceLens Service
→ Evidence / Observation
```

**State Plane**

```text
Working State
Trajectory
Canonical Investigation objects
Review status
Graph admission/materialization manifests
Finalization records
```

控制平面和数据平面必须分开。Supervisor delegation 不是 Tool Call；Agent Tool 也不能创建新的 Agent。

---

## 6. Ownership Matrix — FROZEN

| 能力 | TraceLens | PydanticAI / LLM |
|---|---|---|
| Evidence identity / resolver | **Owner** | Consumer only |
| Task boundary | **Owner** | 无权修改 |
| Tool definitions / permissions | **Owner** | 调用已暴露工具 |
| Investigation persistence | **Owner** | 无直接 DB 权限 |
| Working State / revisions | **Owner** | Proposal only |
| Trajectory | **Owner** | 提供结构化 decision summary |
| Grounding validation | **Owner** | 无法绕过 |
| Claim assertion ceiling | **Owner** | 可推荐，不可突破 |
| Analyst Review | **Owner / Human** | 无权 accept/reject |
| Graph admission | **Owner** | Candidate / request only |
| Report publication | **Owner / Human workflow** | Writer only |
| Reasoning / planning | Runtime Agent | **Owner** |
| Structured Agent output | Contract validated | **Producer** |
| Tool choice within allowed set | Policy bounded | **Agent choice** |

一句话：

> PydanticAI 是 reasoning runtime，不是 Evidence、State、Truth 或 Workflow authority。

---

## 7. Agent Runtime Foundation: PydanticAI

### 7.1 框架选择 — FROZEN

Agent Runtime 基于 **PydanticAI**，而不是 OpenAI Agents SDK。

原因：

- 本地模型是主要/中间运行环境；
- Pydantic typed output、`RunContext`、Tool/Toolset、usage limits 与 TraceLens 风格匹配；
- provider neutrality 更适合本地模型切换；
- 可用于 Supervisor、Specialist、Correlation、Verifier 的统一 reasoning runtime；
- TraceLens 可以保持 Tool/State/Persistence 独立，避免框架锁定。

### 7.2 明确不采用的框架 ownership

v0 不把以下职责交给 PydanticAI Graph、Temporal、DBOS 或类似持久 workflow：

```text
Investigation state
Evidence identity
Tool permission
Trajectory truth
Agent lifecycle recovery
Canonical Claim/Review
Finalization
```

这些全部继续由 TraceLens 自己管理。

### 7.3 PydanticAI Adapter — TBD

框架接入的精确 contract 尚未最终冻结，包括：

```text
Agent factory
RunContext exact fields
local model provider adapter
retries / structured-output recovery
usage limits mapping
context refresh mapping
subagent invocation implementation
```

但无论实现细节如何，Adapter 必须保持薄层、可替换，不能让 PydanticAI object 成为持久状态。

---

## 8. Agent Hierarchy — FROZEN

独立 Agent 只在需要独立上下文、权限、目标或 stopping/validation logic 时创建。

### 8.1 `InvestigationSupervisor`

一个 Investigation 同时只有一个逻辑 Supervisor 控制流。职责：

```text
读取 compact Supervisor Context
选择当前关注事项
决定下一小批调查动作
整合已验证 Specialist/Correlation 结果
提出状态 transition proposals
请求 Verification / Graph Admission / Finalization
```

不承担：

```text
平台深度取证
直接 DB 写入
直接 Claim acceptance
直接 Graphiti ingest
Report publication
```

### 8.2 `SourceSpecialistAgent`

一个 Agent 实现，多种 Profile：

```text
Windows
Android
Linux
Memory
未来可扩展 iOS / macOS / Network
```

一次 Specialist Run：

```text
One Question × One Source Scope × bounded capability set
```

它是 short-lived、read + reason + propose，不直接修改 Working State。

### 8.3 `CorrelationAgent`

仅在存在真正的关系问题时使用：

```text
cross-source
cross-device
time/entity relation
activity sequence
material contradiction
identity relation
```

不负责平台深度 artifact 解析。

### 8.4 `SemanticVerifierAgent`

一个 Verifier，多种 mode：

```text
claim_sufficiency
correlation_sufficiency
question_closure
finalization_review
```

它是质量控制，不是 Analyst，不产生 accepted Finding。

### 8.5 不作为 Agent 的组件

```text
Grounding Validator
AssertionPolicy
GraphAdmissionPolicy
TrajectoryController
NoProgressDetector
SkillResolver
AttentionBuilder
FinalizationGate
Evidence Resolver
EntityIdentityPolicy
```

这些必须 deterministic-first。

---

## 9. Case Framing / Charter / Directive

### 9.1 输入模式 — FROZEN

用户并不需要提交专业 Investigation Goal。支持：

```text
Guided:
Evidence + Case Context
→ CaseFramingAgent 生成 Charter

Expert:
明确 User Goal
→ 保留原 Goal，AI 只 operationalize/decompose

Hybrid:
User Goal + Case Context
→ User Goal 优先
```

没有 Goal/Context 时进入 bounded General Triage，而不是全案无限探索。

### 9.2 Case Context — FROZEN

类型可包括：

```text
Reported Circumstances
Known External Information
User Concerns
Investigation Leads
```

全部标记：

```text
context_only
```

它们不是 Evidence，也不是 Fact。仅由 Analyst Note/Case Context 支撑的结论最多是 `HYPOTHESIS`。

### 9.3 Investigation Charter — FROZEN

Charter 是版本化调查契约，不是执行 Plan，也不是结果。

概念字段：

```text
charter_id
task_id
version
mode
objective
case_context
questions
source_scopes
time_scopes
priority_domains
constraints
playbooks
uncertainties
created_at
created_by
supersedes_version
```

Required Question 最终不能静默消失，必须成为：

```text
answered / supported
unresolved_with_reason
blocked / impossible
superseded by explicit contract change
```

### 9.4 Runtime Directive — FROZEN

运行时用户变更不覆盖 Charter 历史，而通过 immutable/versioned `InvestigationDirective`：

```text
add_goal
add_question
change_priority
restrict_scope
expand_scope
pause
```

Directive 优先于普通 Agent 决策，并触发 re-plan。

### 9.5 Case Framing internal contract — TBD

尚未最终冻结：

```text
CaseFramingInput / Output exact schema
framer 可见多少 source inventory
General Triage 的精确激活规则
Playbook 推荐的确定性/语义边界
Goal/Question decomposition 的 exact validation rules
```

---

## 10. Investigation Playbook — FROZEN

Playbook 是跨案件的专业调查方法学，不是固定 Workflow DSL。

```python
class InvestigationPlaybook(BaseModel):
    playbook_id: str
    version: str
    title: str
    description: str
    applicability: PlaybookApplicability
    coverage_dimensions: list[CoverageDimension]
    seed_questions: list[PlaybookQuestion]
    expansion_rules: list[ExpansionRule]
    completion_guidance: CompletionGuidance
    graph_guidance: GraphGuidance | None = None
```

Playbook 中禁止包含：

```text
固定 steps
具体 SQL
固定 tool_calls
平台 artifact ID
agent routing
```

### 10.1 三个核心定义

```text
coverage_dimensions = 不能轻易漏掉什么
seed_questions      = 通常应该从哪些问题开始
expansion_rules     = 发现什么以后应该考虑往哪里扩展
```

Coverage 状态：

```text
not_started
in_progress
covered
partial
unavailable
not_applicable
```

`covered` 表示“已经合理调查”，不表示发现可疑行为。

### 10.2 v0 初始 Playbook 候选

```text
general_triage
unauthorized_access
malware_compromise
data_exfiltration
insider_activity
account_misuse
communications_activity
timeline_reconstruction
```

具体 catalog 是否全部作为 v0 首批实现仍属于实施规划，不应因为本文列出就视为全部必须一次上线。

---

## 11. Source Specialist Profile / Skill / Toolset

### 11.1 四层模型 — FROZEN

```text
Agent Type
  ↓
Profile
  ↓
Skill
  ↓
Toolset
```

含义：

```text
SourceSpecialist = Agent 类型
Profile          = platform/source 专业边界
Skill            = 按需加载的专业调查知识
Toolset          = 实际执行能力
```

Profile 要薄，只放平台身份、长期 reasoning rules、supported source types、default toolsets、available skills、Evidence interpretation rules、limitations。

### 11.2 Skill 粒度 — FROZEN

Skill 按调查能力分组，不按单个 artifact：

```text
windows.authentication
windows.remote_access
windows.execution
windows.persistence
windows.file_activity
windows.usb
windows.browser
windows.network
```

Artifact-specific 知识可以存在 Skill 或 Tool description，但不要在 v0 建成上百个 per-artifact skill。

### 11.3 Pitfall 是一等内容

例如：

```text
file presence != execution
Prefetch absence != no execution
successful logon != unauthorized access
network logon != remote interactive logon
same IP != same actor/device
```

### 11.4 Skill Catalog — TBD

Profile/Skill contract 已冻结，但 Windows/Android/Linux/Memory 的 exact v0 catalog、每个 Skill 的具体规则尚未冻结。

---

## 12. Skill Resolver + Dynamic Context Assembly — FROZEN

### 12.1 `SkillResolver`

是 deterministic-first orchestration service，不是 Agent。

输入：

```text
profile/version
current question
coverage dimensions
playbook bindings
source/time scopes
known entity types
available artifact families
constraints
```

输出：

```text
selected skill/version
role = primary/supporting
reason codes
candidate toolsets
unavailable capabilities
warnings
```

决策优先级：

```text
coverage mapping
> question semantic hints
> known entities
> available artifact families
```

语义 classifier 以后只有 Benchmark 证明必要才引入。

### 12.2 SourceCapabilityManifest — PARTIALLY FROZEN / TBD DETAILS

必须存在 source/platform capability manifest，供 SkillResolver 知道：

```text
当前 Source 实际有哪些 artifact family
有哪些 Tool capability
哪些数据缺失/不可用
```

但 manifest 的 exact schema、生成路径、partial availability 表示和 hash/version 规则仍需冻结。

### 12.3 SpecialistContextPack — FROZEN

Agent Context 不是聊天历史，而是当前任务的编译结果：

> **Context 不是历史记录，Context 是当前任务的编译结果。**

典型层次：

```text
L0 System invariants
L1 current Investigation Contract
L2 Profile
L3 selected Skills
L4 relevant Working State
L5 Evidence / Graph hints
L6 Tool definitions
L7 output contract
```

只注入当前 Question 所需内容。

### 12.4 Evidence Hydration — FROZEN

统一模式：

```text
Compact Context
→ Reference
→ On-demand Hydration
```

Evidence 不批量全文塞入 context。先用 `EvidenceDigest`，需要细节时再通过 `get_evidence` 等 Tool hydrate。

大型 Tool result 返回 `ToolObservation` digest，原始/完整结果由 runtime 保存，通过 pagination / inspect 再展开。

---

## 13. Tool Contract + Tool Registry — FROZEN

### 13.1 最高边界

> **Tool Registry 是 Agent 与 TraceLens 数据/状态之间唯一允许的执行边界。**

禁止 Agent 直接访问：

```text
SQLite
filesystem
Graphiti / Neo4j
repository object
service_manager internal object
shell
arbitrary HTTP localhost endpoints
```

### 13.2 ToolDefinition

概念 contract：

```python
class ToolDefinition(BaseModel):
    tool_id: str
    version: str
    title: str
    description: str
    input_model: str
    output_model: str
    category: str
    access: Literal["read", "propose", "mutate"]
    scope: str
    evidence_behavior: str
    cost_class: str
    pagination: str | None
    allowed_agent_types: list[str]
```

`task_id` 不作为模型参数暴露，而从可信 `ForensicToolContext` 注入。

### 13.3 ToolObservation

```python
class ToolObservation(BaseModel):
    observation_id: str
    tool_id: str
    tool_version: str
    summary: str
    data: object
    evidence_refs: list[str]
    entity_refs: list[str]
    result_count: int
    truncated: bool
    continuation: str | None
    warnings: list[str]
    limitations: list[str]
```

Tool summary 不是 Evidence。

### 13.4 Registry execution pipeline

```text
resolve tool
→ permission check
→ source scope check
→ input schema validation
→ budget / duplicate / loop check
→ adapter → existing service
→ normalize observation
→ validate Evidence refs
→ persist observation
→ append trajectory event
→ return compact result
```

### 13.5 `allowed_evidence_ids` — FROZEN

Claim 只能引用真正向模型暴露过的 Evidence。即使模型猜中了一个真实 `evidence_key`，如果当前 run 未通过 context/tool 暴露它，也必须拒绝。

### 13.6 禁止给 Agent 的能力

```text
accept/reject canonical Claim/Event/Analysis
publish report
delete Evidence
execute arbitrary SQL
execute shell
arbitrary filesystem read/write
raw DB write
direct Graphiti ingest
change task path/hash
```

### 13.7 Canonical Tool Catalog — TBD

候选包括：

```text
get_task_context
search_evidence
get_evidence
search_files
search_timeline
find_related_evidence
find_temporal_neighbors
search_entity_occurrences
get_existing_analyses
get_existing_claims
search_investigation_graph
get_graph_neighbors
query_platform_artifacts
inspect_observation
request_graph_admission
propose_analysis
propose_event
link_event_evidence
request_event_refresh
```

但 exact v0 Tool Surface 和每个 Tool 的 exact schema 尚未冻结。

---

## 14. Investigation Working State + Trajectory — FROZEN

核心定义：

> **Working State = 当前调查状态的最小可执行投影；Trajectory = 导致状态形成的不可变 append-only Action Trace。**

以及：

> **Trajectory is Action Trace, not Thought Trace.**

TraceLens 不保存、也不需要保存模型私有 Chain-of-Thought。Trajectory 只记录可审计的 action、observation、state change、reason code 和必要的 decision summary。

### 14.1 Working State 主要内容

```text
investigation/run/task identity
revision + state_hash + previous_state_hash
charter reference
objective
working questions
active playbooks
coverage states
evidence working set
entity refs
hypotheses
finding refs
contradictions
graph refs
scopes
directives
progress state
budget state
timestamps
```

Working State 保存引用和调查语义，不复制完整 Evidence。

### 14.2 WorkingQuestion

来源：

```text
charter
user_directive
supervisor_discovery
specialist_discovery
playbook
```

优先级：

```text
required
high
normal
exploratory
```

状态：

```text
open
in_progress
answered
unresolved
blocked
deferred
superseded
```

Disposition：

```text
supported
not_supported
inconclusive
unavailable
not_applicable
```

### 14.3 Hypothesis

状态：

```text
active
supported
weakened
rejected
retired
```

Hypothesis 是调查工具，不是 Fact。

### 14.4 Contradiction

严重度：

```text
low
material
critical
```

状态：

```text
open
resolved
explained
unresolved
```

Material/Critical contradiction 可以自动产生 resolution question，但必须由正常状态转换管理。

### 14.5 Persistence pattern

轻量 append-only / materialized revision：

```text
agent_trajectory_events
agent_working_state_revisions
agent_tool_observations
```

不引入通用 Event Sourcing 基础设施。

---

## 15. Investigation Orchestrator Contract + State Machine — FROZEN

### 15.1 定义

> **Investigation Orchestrator = Investigation 生命周期 + Agent Run 生命周期 + Delegation 调度 + 串行状态提交 + 恢复/取消 + Finalization 的确定性执行内核。**

Supervisor 决定“下一步做什么”；Orchestrator 决定“是否允许、如何执行、什么时候提交、失败后如何恢复”。

### 15.2 三层生命周期

```text
Investigation
  ├── Agent Run #1
  │    ├── Delegation A
  │    └── Delegation B
  ├── Agent Run #2
  └── ...
```

#### InvestigationStatus

```text
ready
active
paused
completed
cancelled
```

`completed`、`cancelled` 是终态。`completed` 不 reopen；后续调查新建 Investigation 并建立 continuation provenance。

#### AgentRunStatus

```text
queued
running
completed
failed
cancelled
```

RunStopReason 可以包括：

```text
finalized
budget_exhausted
user_paused
no_progress
directive_replan
runtime_restart
cancelled
internal_failure
```

Run 结束不等于 Investigation 完成。

#### DelegationStatus

```text
queued
running
completed
failed
cancelled
stale
```

### 15.3 主循环

```text
PLAN
  ↓
EXECUTE
  ↓
INTEGRATE
  ↓
EVALUATE
  ↓
PLAN ...
```

**PLAN**：加载最新 State、应用 Directive、构建 Attention、编译 Supervisor Context、调用 Supervisor、校验 decision。  
**EXECUTE**：先持久化 queued intent，再调度 read-only Specialist/Correlation/Verifier/Graph request。  
**INTEGRATE**：ResultValidator → MergeGuard → Supervisor Integration → StateTransitionPolicy → atomic revision。  
**EVALUATE**：确定性 Progress/No-progress/Budget/Finalization eligibility。

### 15.4 并发模型

> **并行读取，串行语义提交。**

一个 Investigation 同时最多一个 active Orchestrator Run；Run 内允许多个 read-only Specialist 并行。所有 semantic state mutation 通过唯一串行 Integration path 提交。

### 15.5 Admission transaction

执行任何异步 Agent work 前必须先：

```text
BEGIN TX
persist Supervisor decision/audit
INSERT delegation(s) status=queued
persist admission records
COMMIT
→ then start executor
```

禁止先 `asyncio.create_task()` 再写 DB。

### 15.6 Restart recovery

服务重启后：

```text
running Agent Run → failed(runtime_restart)
queued/running Delegation → failed(runtime_restart)
active Investigation → paused(runtime_restart)
```

Working State 保留最后一次 committed revision。不恢复旧 coroutine、模型 conversation 或中间 generation。恢复时创建新 Run 从最新 State 重新 PLAN。

### 15.7 现有异步能力继续复用

Graph Materialization、Secondary Analysis、Event Refresh 继续由各自既有 Executor 管理。Orchestrator只负责 admission、依赖、观察和状态编排，不重新实现超级 Job Scheduler。

---

## 16. Delegation Protocol — FROZEN

Delegation 控制面：

```text
Supervisor
→ Orchestrator
→ Specialist / Correlation / Verifier
```

Tool 数据面：

```text
Agent
→ ToolRegistry
→ TraceLens Services
```

两者严格分开。

### 16.1 Delegation unit

```text
One Question
× One Source Scope
× bounded capability set
```

Delegation 冻结：

```text
question
source/time scope
state revision
context hash
profile version
skill versions
resolved toolset hash
budget
```

### 16.2 MergeGuard

旧 revision 不自动 stale。MergeGuard 检查语义依赖：

```text
question still active?
source scope changed?
referenced Evidence invalidated?
relevant Directive changed?
assumptions invalid?
```

只有依赖实质失效时 result 才 `stale`。

### 16.3 Group behavior

第一版只需要简单：

```text
parallel_all
sequential
```

并行 group 等待 `all_terminal`，不是 `all_successful`。失败 worker 也作为 FailureDigest 进入 Integration，避免永久等待。

---

## 17. Supervisor Integration + State Transition Policy — FROZEN

### 17.1 核心边界

> **Supervisor 可以解释结果并提出状态变化，但不能直接修改 Working State。**

Integration mode：

```text
Tools = none
```

输入为 `IntegrationContextPack`，只包含 Validated Agent Results 与相关 Working State slice。

### 17.2 Typed Transition Proposal

Supervisor 不返回完整新 State，也不输出通用 JSON Patch，只能输出领域级 transition：

```text
QuestionTransition
CreateQuestion
EvidenceRelevanceTransition
AddEntityReference
CreateHypothesis
HypothesisTransition
CreateContradiction
ContradictionTransition
CoverageTransition
AddFindingReference
AddPendingProposalReference
```

Supervisor 无权直接：

```text
Create canonical Finding
Accept/reject Claim
Modify hard source/time scope
Modify Graph materialization state
Publish report
```

### 17.3 StateTransitionPolicy

完全 deterministic，检查：

```text
authority
legal transition
basis/provenance refs
task/scope
verification requirement
cross-transition invariants
idempotency
```

Policy 可以拒绝，不替 Supervisor 做新的案件语义判断。

### 17.4 Atomic semantic commit

一次 `SupervisorIntegrationDecision` 是一个原子语义提交单元。除安全 normalization / idempotent noop 外，不做“非法一项但偷偷提交其余项”的部分 commit。

### 17.5 Working State invariants

至少包括：

```text
W1 task/investigation identity immutable
W2 required charter question cannot disappear
W3 answered question must have disposition
W4 terminal coverage must have closure basis
W5 every Evidence ref resolves inside task
W6 Finding refs point to canonical persisted object
W7 Hypothesis never equals canonical Finding
W8 critical contradiction cannot silently disappear
W9 Supervisor cannot expand scope directly
W10 Agent cannot create accepted/rejected review status
W11 Graph lifecycle cannot be mutated through Working State
W12 one semantic commit increments revision exactly once
```

---

## 18. Supervisor Attention Set / AttentionPolicy — FROZEN WITH CALIBRATIONS

### 18.1 核心定义

内部可以继续叫 `AttentionQueue`，但真实语义是：

> **由当前 Working State 确定性计算出的“当前不能被忽略、值得 Supervisor 关注的未解决事项集合”。**

不是 FIFO，不是 Step List，不是固定 Workflow。

> **AttentionPolicy 决定“什么不能被忽略”；Supervisor 决定“现在怎样调查它”。**

### 18.2 Projection inputs

```text
Working State
Charter
Directives
Pending Verification
Delegation state
Coverage state
Progress signals
Budget state
```

AttentionSet 不作为 canonical DB truth；每轮重新计算。为审计，只需把 Supervisor 当时看到的 Attention Window、policy version、state revision 和 hash 写入 Trajectory。

### 18.3 Priority bands

不使用 LLM 数值 importance score。采用 band：

```text
P0 CONTROL
P1 CORRECTNESS BLOCKER
P2 INVESTIGATION OBLIGATION
P3 ACTIVE PROGRESS
P4 SUPPORTING / OPPORTUNISTIC
P5 EXPLORATORY
```

典型映射：

```text
P0: semantic portion of User Directive
P1: critical contradiction / blocking mandatory verification
P2: required question / required coverage gap
P3: high-priority question / material contradiction / important lead
P4: normal question / supporting coverage / graph/corroboration opportunity
P5: evidence-backed exploratory lead
```

### 18.4 Eligibility / blocking

AttentionBuilder 先确定：

```text
eligible
blocked
suppressed
```

`blocked_by` 表示当前缺失的调查信息，不规定必须调用哪个 Tool，因此不会变成 workflow DAG。

### 18.5 Priority propagation

只有明确 `blocks` 依赖才可以继承父 Required Question 的有效 attention priority。`supports` / `explores` 不自动继承 required 级别。

### 18.6 Semantic coalescing

Question 与 Coverage 如果实质上是同一调查义务，应合并成一个 primary AttentionItem，另一个作为 related coverage/question ref，避免重复 Delegation。

Pending Verification 可以按同一 Question/semantic unit 做 milestone batch。

### 18.7 Exploration

P5 必须至少有真实 Evidence ref 或 validated Entity/Correlation ref，纯 LLM imagination 不进入 Attention。

预算紧张且高优先义务堆积时 P5 可以被 deterministic suppression；核心义务稳定推进且预算健康时允许有限 Exploration。

### 18.8 CALIBRATION：两项不冻结

以下两项明确留给 Benchmark：

1. P1 内 `critical contradiction` 与 `blocking verification` 是否需要更细排序；
2. Exploration Allowance / Attention Window 中具体保留多少低优先级对象。

此外，所有具体数量型参数（window 大小、batch 数量等）均不在设计阶段固定。

---

## 19. Entity Model + Correlation — FROZEN

### 19.1 核心原则

> **Entity Model 解决稳定识别/规范化；Correlation 解决调查相关关系。Normalization != Identity Resolution；Temporal proximity != Causality。**

实体从真实 Evidence-backed occurrence 开始：

```text
EntityOccurrence
→ Entity Identifier
→ optional Resolved Entity
```

优先 linking，而不是 aggressive merge。

### 19.2 EntityOccurrence

概念字段：

```text
occurrence_id
task/source scope
evidence_ref
entity_type
raw_value
normalized_value
match_key
namespace
role
TemporalRef
source_field
extraction_method
verification status
```

### 19.3 IdentityPolicy

按 entity type 决定：

```text
identity_scope
normalizer
auto_link
qualifiers
```

例：

```text
SHA256 → strong global identifier
path → source-scoped
username → host/domain/realm composite
IP → same identifier does not imply same person/device
PID → host + time scoped
```

### 19.4 Deterministic Correlation first

优先：

```text
exact hash
normalized identifier
composite account
URL/domain
file/device identifier
time overlap
structured co-occurrence
```

然后再把 bounded candidates 交给 CorrelationAgent 做语义解释。

### 19.5 Correlation relation

结构至少包含：

```text
relation type
subject/object refs
derivation = artifact_explicit / deterministic_match / semantic_inference
assertion = observed / inference / hypothesis
evidence refs
support = identity / temporal / content / structural
limitations
causal_status
```

`temporal_only` 不能自动升级成 causality。

### 19.6 Entity taxonomy / relation registry — TBD

v0 候选 entity types：

```text
user_account
email
phone
host
device
external_storage
ip
domain
url
file_instance
file_hash
path
process_image
application
```

候选 relation family：

```text
identity
temporal
sequence
communication
transfer
execution
reference
cross_source_match
contradiction
causal_hypothesis
```

但 exact taxonomy、normalizer、identity scope、qualifier、relation constraints 尚未最终冻结。

---

## 20. Grounding + Semantic Verification — FROZEN

### 20.1 最重要的区分

> **Grounding 回答 Evidence 引用是否真实、合法、task-scoped 且实际向模型可见；Semantic Verification 回答这些 Evidence 是否足以支撑 Claim 的具体语义。**

`grounded != proven`。

### 20.2 Pipeline

```text
Specialist / Correlation
→ ProposedClaim
→ ProposalNormalizer
→ Deterministic Grounding Validator
→ GroundingResult
→ EvidenceSupportBundleBuilder
→ SemanticVerifierAgent
→ SemanticVerificationResult
→ AssertionPolicy
→ ClaimDisposition
→ canonical Investigation object
→ review_pending
→ Analyst Review
```

### 20.3 ProposedClaim

```text
proposal_id
text
assertion_class = FACT / INFERENCE / HYPOTHESIS
evidence_refs
source_question_ids
source_delegation_id
relationship_refs
temporal_scope
limitations
```

ProposalNormalizer 应拆分 compound claim，但不能静默改义。

### 20.4 Grounding

检查：

```text
Evidence key syntax
task boundary
resolve_evidence
allowed_evidence_ids visibility
invalid/rejected analysis
Graph/Observation/LLM text not masquerading as Evidence
FACT has evidence refs
ref type allowed
```

状态：

```text
grounded
partially_grounded
ungrounded
invalid
```

FACT 没有 refs：确定性降级为 HYPOTHESIS + warning，而不是让它作为 FACT 继续。

### 20.5 Semantic support

不使用伪精确 confidence 数字。状态：

```text
sufficient
partially_sufficient
insufficient
contradicted
indeterminate
```

Verifier 必须检查 unsupported parts、contradicting evidence、alternative explanations、missing evidence。

### 20.6 Assertion classes

```text
FACT
= Evidence 直接记录或确定性导出

INFERENCE
= 多个真实 Evidence 支持的语义结论，但不是任一 Evidence 直接陈述

HYPOTHESIS
= 值得继续调查，但 Evidence 尚不足以形成稳定结论
```

### 20.7 AssertionPolicy

高风险语义至少包括：

```text
causality
attack chain
actor attribution
unauthorized / malicious intent
same real-world entity
data exfiltration conclusion
persistence interpretation
credential compromise
anti-forensics intent
cross-device behavior merge
```

这些默认需要 semantic verification，并受 deterministic assertion ceiling 约束。

Agent 自动 pipeline 的 canonical 最高状态是：

```text
review_pending
```

只有 Analyst Review 可以进入 `accepted/rejected`。

### 20.8 Exact AssertionPolicy registry — TBD

`deterministic_only / semantic_required / semantic_on_demand` 的 exact registry、每种 assertion type 的最低 support requirement 与 ceiling 尚未全部冻结。

---

## 21. Investigation Context Graph / Graph Admission — FROZEN

### 21.1 Graphiti 的定位

> **Investigation Context Graph 是 Investigation Working Set 的选择性、派生、可丢弃、可重建的语义索引。**

它不是：

```text
Evidence Store
Investigation Persistence
canonical Entity Store
canonical Claim Store
full-task KG truth
```

权威优先级：

```text
Evidence / investigation.db
>
Graphiti / Neo4j
```

### 21.2 Selective flow

```text
Full Evidence Space
→ deterministic / semantic retrieval
→ Investigation Working Set
→ Graph Candidate
→ Graph Admission Policy
→ Frozen ForensicGraphEpisode
→ Graph Materialization
→ Investigation Context Graph
```

### 21.3 Graph Admission != Materialization

`GraphCandidate` 是 Agent/Supervisor 的建议；`GraphAdmissionPolicy` 是确定性安全边界；`GraphMaterialization` 才是异步 Graphiti execution。

Decision：

```text
admit
defer
not_admitted
```

不要使用 accepted/rejected，避免和 Analyst Review 混淆。

### 21.4 可以 materialize 的语义层

1. Evidence-derived structured context；
2. Grounded/verified semantic findings；
3. validated correlations / accepted or review-pending semantic units，并携带 review status。

默认禁止把以下内容写成 graph fact：

```text
Analyst Note
Case Context
Agent reasoning
ungrounded hypothesis
```

### 21.5 Investigation vs Report retrieval mode

```text
investigation mode:
Evidence-derived
+ accepted
+ verified review_pending (clearly unconfirmed)

report mode:
Evidence-derived
+ accepted semantics only
```

### 21.6 Frozen episode

Graph materialization 输入必须冻结并 hash。Graphiti 只执行 frozen semantic slice，不重新读取不断变化的 DB 状态。

Episode 粒度：

> 一个可独立理解的 investigation semantic unit，而不是一条 DB row，也不是整个 case。

允许 micro-batching，但必须保留 assertion → Evidence provenance。

### 21.7 Logical invalidation > physical cleanup

SQLite materialization manifest 是逻辑有效性的权威：

```text
queued
running
active
failed
stale
invalidated
superseded
```

`stale/invalidated/superseded` 应立即从 TraceLens Graph Reader 过滤；Graphiti 物理 cleanup 可以延迟。

所有 Graph query 都通过 TraceLens Adapter，返回的 node/edge 必须能映射回 materialization + Evidence/Claim/Correlation provenance。无 provenance graph object 不进入 Agent Context。

### 21.8 Report 只用 Graph 定位

> **KG locates; Evidence Store proves.**

Graph path 是导航/理解辅助，最终 Citation 必须 hydrate 回真实 Evidence。

### 21.9 Graph exact admission rules — TBD / CALIBRATION

尚未最终冻结：

```text
自动 admit/defer 的 exact rule table
graph budget 数值
episode batch size
priority numeric limits
input_hash exact field list
graph episode schema exact fields
```

方向已冻结，具体阈值通过 Benchmark 校准。

---

## 22. FinalizationGate — FROZEN

### 22.1 定义

> **Finalization 判断的是 Investigation execution closure，不是 Analyst acceptance，也不是 Report publication。**

完成意味着：

> 当前 Charter/Directive 下所有不能忽略的调查义务，都已经进入明确、可审计的终态。

并不要求案件所有问题都有确定答案。

### 22.2 Pipeline

```text
Supervisor request_finalize
→ FinalizationRequest
→ deterministic integrity/runtime preflight
→ Investigation closure preflight
→ optional/required final semantic review
→ FinalizationGate
→ PASS / DENY / STALE
→ atomic Finalization Commit
```

PASS 后：

```text
complete
complete_with_limitations
```

### 22.3 Hard blockers

不能降级成 limitation 的 blocker 包括：

```text
invalid task/investigation identity
untrusted/unavailable investigation.db integrity
Working State invariant failure
cross-task / invalid provenance
state revision stale
unapplied User Directive
finalization-relevant queued/running Delegation
completed but unintegrated Delegation result
unresolved state transition conflict
mandatory grounding/verification invalidity
required Question still open/in_progress/deferred
required Coverage still not_started/in_progress
critical contradiction still open
```

### 22.4 Required Question terminal states

允许：

```text
answered
unresolved
blocked
superseded (only explicit contract change)
```

`answered` 必须有 disposition；`unresolved` 必须记录已调查内容、Evidence、缺失内容和 limitation；`blocked` 必须有系统可验证 blocker。

`not_supported` 是合法完整结果，不等于 limitation。

### 22.5 Required Coverage

允许：

```text
covered
partial
unavailable
not_applicable
```

`partial` / `unavailable` 产生 limitation；`not_applicable` 若规则满足不自动算 limitation。

完整性要求是“明确 disposition”，不是“全部 covered”。

### 22.6 Critical Contradiction

不能以 `open` 完成，但可成为：

```text
resolved
explained
unresolved
```

`unresolved` 是合法终态，必须附 refs、attempted resolution、impact 和 limitation，随后 `complete_with_limitations`。

### 22.7 Capability failure policy

分三类：

```text
integrity_critical
semantic_required
optional_enhancement
```

- `integrity_critical` 失败：DENY；
- `semantic_required` 失败：不能降低 correctness 标准，必须先把依赖的 Claim/Question 安全降级为 HYPOTHESIS/unresolved/blocked，再决定 Finalization；
- `optional_enhancement`（如 Graphiti）：不直接阻止完成。

Runtime bug 不能伪装成“Evidence 不存在”。必须先走 recovery/retry，之后明确记录 `blocked_by_runtime_failure`。

### 22.8 Budget / no-progress

```text
budget_exhausted
no_progress
```

都是 Run-level stop signal，不是 Question disposition，也不能直接触发 completed。必须先让相关 obligation 形成明确终态。

### 22.9 Final semantic review policy

`FinalizationPolicy` 明确：

```text
best_effort
required
```

`best_effort`：

```text
pass → continue
issues_found → DENY / re-plan
unavailable → 若所有 object-level mandatory verification 已满足或安全降级，可 complete_with_limitations
```

`required`：

```text
pass → continue
issues_found → DENY
unavailable/failed → DENY / pause
```

Requirement 取 system/organization/investigation/charter 中最严格值；Supervisor/LLM 无权临场放宽。

Final review 是最后的 semantic consistency checkpoint，不能替代 object-level mandatory verification。

### 22.10 `completed` immutable terminal

`Investigation.completed` 正式定义为不可 reopen 的终态。

后续：

```text
new Evidence
new Goal
corrective investigation
follow-up analysis
```

均新建 Investigation：

```text
I2 continues_from I1/F1
```

而不是 `completed → active`。

### 22.11 FinalizationRecord

Finalization 成功必须保存不可变记录，绑定：

```text
final Working State revision/hash
completion mode
Question dispositions
Coverage dispositions
unresolved contradictions
limitations
remaining nonblocking questions
pending analyst reviews
final verification status
policy version
input hash
completed_at
```

Finalization record 与 `investigation.status=completed`、Run terminal state、Trajectory event 必须在同一原子事务提交。

---

## 23. Report Retrieval Planner + Report Context Pack — FROZEN

### 23.1 总原则

> **报告章节不是从整个案件中总结出来，而是从一个经过调查、筛选、关系检索和 Evidence hydration 后冻结的章节级 Evidence Pack 中生成。**

Pipeline：

```text
Report Outline
→ ChapterSpec
→ Report Retrieval Planner
→ Retrieval Plan
→ anchors + accepted semantics + Graph navigation + deterministic expansion
→ candidate Evidence
→ rank / dedup / hydrate / budget
→ Frozen ReportContextPack
→ Chapter Writer
→ Citation / Semantic Validation
```

### 23.2 Planner 不是 Investigator

Report Retrieval Planner 只决定“为当前章节需要找什么”，不创建新的 Investigation Finding、Working State 或 Graph truth。

### 23.3 Anchor → Expansion

优先从：

```text
Report Evidence
Accepted Claims
Accepted Investigation Events
Accepted Analyses
Chapter topic / entity / time scope
```

建立 anchor，再有限 Graph/Entity/Timeline expansion，而不是重新全文扫描全案。

### 23.4 Context roles

Context Pack 中区分：

```text
anchor evidence
supporting evidence
retrieved context evidence
```

它们进入 Context 不会偷偷修改 `report_evidence.status`。

### 23.5 Hydration depth

```text
Digest
Structured
Detailed
```

根据 Evidence role 与 token budget 选择，而不是全部全文。

### 23.6 Dedup / independence

必须避免：

```text
同一原 Evidence
→ Timeline view
→ Initial Analysis
→ Accepted Claim
→ Graph edge
```

被模型误认为多个独立证据源。

同时保留真正的跨源 corroboration，例如 Windows Event、Browser History、File metadata、Network artifact。

### 23.7 Citation allowlist

Chapter Writer 只能引用 `ReportContextPack.allowed_citation_refs`。即使模型猜到案件中真实存在但 Pack 未暴露的 Evidence，也必须验证失败。

Graph ID 永远不进入 Citation Allowlist。

### 23.8 Review status

`review_pending` semantic object 不进入 report mode。其底层原始 Evidence 若独立通过 Retrieval 被找到，可以作为真实 Evidence 进入 Context；但 review_pending 推断文本不能作为 accepted factual context。

### 23.9 Report Retrieval 不形成第二条 Investigation pipeline

若报告阶段发现重大新方向，应产生 Investigation lead / gap，回到 Investigation，而不是由 Writer 自行形成新结论。

---

## 24. Report Outline / Chapter Planning / Chapter Writer — FROZEN

### 24.1 Report structure

采用：

```text
Stable Core
+
Dynamic Investigation Chapters
```

Playbook != Report Chapter。Playbook 是调查方法，Chapter 是值得报告的结果组织。

### 24.2 ReportOutlinePlanner

短生命周期 Planner，输入：

```text
Report Template
Investigation Charter
Required Question dispositions
Accepted Findings / Events
Report Evidence selections
Coverage / Limitations
```

输出版本化 `ReportOutlinePlan`。用户可以修改 outline，修改生成新版本，不覆盖历史。

### 24.3 Chapter generation modes

```text
deterministic
evidence_narrative
synthesis
```

典型：

```text
Evidence Inventory / Methodology / Appendix → deterministic
Investigation Findings → evidence_narrative
Executive Summary / Conclusion → synthesis
```

### 24.4 Writer boundary

理想 v0：

```text
Chapter Writer tools = 0
```

输入只包括：

```text
ChapterSpec
Frozen ReportContextPack
Narrative Policy
Output Contract
```

> **Report Writer 可以改变表达方式，但不能提高结论强度。**

如果 Investigation 只有 `INFERENCE`，Report 不能写成 `FACT`。

Direct Evidence 只允许 Writer 表达它直接记录的事实；高级语义必须来自 accepted Claim/Event 等 canonical basis。

### 24.5 Structured assertion output

Report Draft 应保留 assertion 原子单位：

```text
text
assertion_class = FACT / INFERENCE / HYPOTHESIS / LIMITATION
basis_type
basis_refs
Evidence refs
citation refs
```

其中：

```text
basis_refs
```

回答“为什么 Writer 有资格表达这层语义”，而 `citation_refs` 回到最终 Evidence 证明链。

### 24.6 Executive Summary / Conclusion 后生成

先完成并验证 detailed chapters，然后用：

```text
ChapterDigest
ReportAssertionLedger
Required Question dispositions
Major Limitations
```

生成 Executive Summary / Conclusion。不要重新读取整个案件。

### 24.7 Cross-chapter consistency

deterministic-first 检查：

```text
same Evidence immutable fields
same accepted Claim assertion class
entity/time consistency
invalid/rejected refs
frozen report version refs
```

再由 Semantic Consistency Reviewer 对 Chapter Digests / Assertion Ledger 做语义一致性检查。Reviewer 无 retrieval tools，不能自己重新调查案件。

### 24.8 Report Template exact v1 — TBD

`forensic_investigation_report:v1` 的 exact core sections、required/optional section policy、default ordering 和 narrative rules 仍需最终定稿。

---

## 25. Evaluation / Benchmark Framework — FROZEN

### 25.1 四层评估

```text
Result Quality
+
Investigation Process Quality
+
Cost / Performance
+
Reliability / Reproducibility
```

不使用单一 “TraceLens Score”。采用：

```text
Hard Gates
+
Quality Dashboard
+
Cost Dashboard
```

### 25.2 Truth Manifest

Ground Truth 不是一段参考报告，而是结构化 manifest：

```text
critical evidence
supporting evidence
irrelevant evidence
expected questions
confirmed claims
acceptable inferences
unsupported/prohibited overclaims
expected relations
expected coverage
known ambiguities
unavailable truth
```

真值允许：

```text
confirmed
unsupported
indeterminate
```

而不是强迫所有问题 true/false。

### 25.3 三层 Evidence availability

```text
Ground Truth Evidence
↓
Parser Reachable Evidence
↓
Agent Discoverable Evidence
```

Agent Recall 的主要分母应基于当前 TraceLens 底层真正 reachable 的关键 Evidence，避免把 Parser limitation 错算成 Agent failure。

### 25.4 Result metrics

核心包括：

```text
Critical Evidence Recall
Relevant Evidence Precision
Critical / Relevant Evidence Yield
Unsupported FACT Rate
Assertion Overstatement Rate
Causal Overreach Rate
Actor Attribution Overreach
Question Disposition Accuracy
Premature Closure Rate
Applicable Coverage Completion
Unjustified Coverage Closure
Correlation Recall / Precision
False Entity Merge Rate
Citation Validity
Citation Completeness
Semantic Citation Sufficiency
Report Assertion Strength Violation Rate
```

### 25.5 Process metrics

Trajectory 可直接提供：

```text
Productive Tool Call Ratio
Duplicate Call Rate
Zero-yield Call Rate
No-progress Episodes
Time / Tool Calls to First Critical Evidence
Question Advancement Rate
Coverage Advancement Rate
```

Progress 不由 LLM 自评，而由确定性状态变化计算。

### 25.6 Graph metrics

重点比较 Full KG 与 Selective Graph：

```text
Graphiti materialization count
Graphiti LLM calls
Graph build wall time
GPU/token cost
Materialized Evidence ratio
Graph Retrieval Precision/Yield
Cross-source Correlation Recall
Report Retrieval Recall
Graph Materialization Utility
```

### 25.7 Cost / Context metrics

记录：

```text
wall time
model calls
input/output tokens
peak context tokens
tool calls
expensive tool calls
specialist runs
verifier calls
graph materializations
evidence hydrations
GPU seconds / VRAM peak when available
```

重点观察 Context Compression：

```text
Evidence Space
→ Working Set
→ Graph semantic units
→ Report candidates
→ ReportContextPack
→ actual model tokens
```

### 25.8 Reliability

保存：

```text
model name/hash
quantization
runtime/version
generation parameters
context window/tokenizer
prompt versions
Playbook/Skill versions
Tool Registry hash
Assertion/Attention/Finalization policy versions
Graph schema version
Case dataset hash
```

同一 Case 允许重复运行并观察 recall、claim、question、tool-call、report assertion variance。

### 25.9 Benchmark Tiers

```text
T0 deterministic contract tests
T1 single device + clear Goal
T2 complex single-device reasoning/noise
T3 multi-device / cross-source / Graph / Report
T4 future large real-world performance acceptance
```

必须包含 Negative Cases 和诱导 Case Context，测试 false positive、malicious-intent overreach、confirmation bias resistance。

### 25.10 Ablation

至少支持：

```text
Current baseline
Agent Supervisor + Tools
+ Playbook/Specialist
+ Correlation
+ Semantic Verifier
+ Selective Graph
Full target architecture
```

Graph 单独比较：

```text
Agent + no Graph
Agent + Full Graph
Agent + Selective Graph
```

### 25.11 Benchmark corpus / acceptance thresholds — TBD

Framework 已冻结，但 exact Case corpus、Truth Manifest 实例、ablation set、hard-gate threshold 和质量目标仍需独立设计并跑数据后冻结。

---

## 26. Persistence and Data Ownership

### 26.1 Canonical truth 继续留在现有 Investigation 层

Agent Runtime 不应建立第二套 Evidence/Claim/Event truth。

继续复用现有：

```text
Evidence Snapshot
Secondary Analysis
Analyst Review
Investigation Event / Version / Evidence links
Event Refresh
Report generation / citation manifest
```

Working State 只保存这些 canonical object 的 refs。

### 26.2 Agent-specific logical persistence

概念上 v0 需要：

```text
investigations
agent_runs
agent_delegations
agent_tool_observations
agent_trajectory_events
agent_working_state_revisions
```

Graph：

```text
graph_admissions
graph_materializations
graph_provenance_links
```

Charter/Directive 的 exact table design 尚未冻结。

不要为：

```text
plan
attention queue
progress signal
context pack
supervisor decision
integration context
```

每个概念都单独建表。大量 ephemeral artifact 可以使用 typed JSON + hash + Trajectory 引用表达。

### 26.3 SQLite correctness model

虽然 Agent Runtime 会并发执行多个 read-only Agent worker，但 semantic state 写入始终串行，因此不要求为了 Agent 架构立即替换 SQLite。

核心模型：

```text
1 Investigation
→ 1 active Orchestrator Run
→ N parallel read-only workers
→ 1 serial Integration writer
```

这样能够保留现有 SQLite、task lifecycle 和 InvestigationRepository 设计。

---

## 27. Failure, Recovery and Concurrency Rules — FROZEN

### 27.1 Task lifecycle > Agent lifecycle

任何 terminal write / semantic commit 前都必须重新确认：

```text
task still exists
investigation belongs to task
trusted task-owned DB still valid
```

不能使用 submit-time DB path 在 Task 删除后继续 terminal write。

### 27.2 Cooperative cancellation

Pause / Directive change：

```text
Investigation → paused / replan
active Delegation → cancel_requested
Orchestrator stops admitting new work
```

已完成结果可以持久化，但未通过 MergeGuard/Integration 就不能污染 Working State。

### 27.3 Idempotency

Integration 需要 stable idempotency key，例如由：

```text
investigation
state revision
source result hashes
integration policy version
```

计算。Crash 后相同 result 重试不能重复创建 Question/Hypothesis。

### 27.4 Failure is explicit state, not missing row

Agent、Verifier、Graph、Report 等异步执行失败必须形成明确 terminal state 与 reason code。SQLite 是最终状态来源。

---

## 28. Added / Modified / Reused Boundary

这一节是实现阶段的架构边界，不代表具体文件名已经冻结。

### 28.1 Added — Agent v0 新增能力

预计新增模块职责：

```text
agent_runtime/
  PydanticAI thin adapter
  agent factories / typed contracts

investigation_orchestrator/
  lifecycle / state machine / action admission

working_state/
  revisions / trajectory / observations

attention/
  AttentionBuilder / AttentionPolicy

skills/
  profiles / skill resolver / context assembler

tools/
  canonical ToolRegistry / adapters / policies

correlation/
  entity occurrence / identity policy / deterministic correlation

verification/
  grounding / semantic verifier / assertion policy

graph_context/
  admission / frozen episode / materialization manifest / reader filter

report_runtime/
  outline / retrieval / context pack / writer / consistency

benchmarks/
  forensic agent benchmark harness / Truth Manifest / scoring
```

实际目录需服从仓库当前结构。

### 28.2 Reused — 优先直接复用

```text
service_manager.cpp_backend.get_task(task_id)
resolve_evidence(task_id, evidence_key)
Evidence Snapshot / capture_if_absent()
InvestigationRepository
existing Secondary Analysis executor
Analyst Review API/service
Investigation Event persistence
Event Refresh executor
Files/Timeline associations
AnalysisCenter task context / job polling patterns
existing LLM configuration/provider layer where suitable
existing Graph reader/adapter capabilities where safe
R2 Report frozen input / citation validation / immutable manifest concepts
```

### 28.3 Modified — 最小影响

可能需要最小修改：

```text
API route registration
router/navigation
TaskSelector
locale
Investigation UI entry / status views
existing service facades to expose safe internal adapters
```

不得因为 Agent v0 顺便重构 Files/Timeline/KnowledgeGraph/AnalysisCenter/CaseIntelligence。

---

## 29. Proposed Implementation Sequencing — NOT YET FROZEN

以下是根据 frozen architecture 推导出的**建议实施顺序**，不是已经冻结的 Phase contract；真正实施前要先调查当前仓库。

### Phase A — Runtime skeleton without autonomous investigation

目标：建立不依赖模型质量的运行时骨架。

```text
Investigation / Run / Delegation persistence
Working State revision + Trajectory
Orchestrator state machine
AttentionBuilder
StateTransitionPolicy
FinalizationGate deterministic preflight
recovery / idempotency tests
```

此阶段可使用 fake Supervisor/Specialist 驱动测试。

### Phase B — Read-only Agent data plane

```text
PydanticAI thin adapter
ToolDefinition / ToolRegistry
initial canonical read-only tools
SourceCapabilityManifest
Windows first SourceSpecialist profile
SkillResolver
ContextAssembler
```

先不允许 Agent propose/mutate canonical Investigation objects。

### Phase C — Investigation reasoning loop

```text
Supervisor PLAN
Specialist delegation
Integration mode
Question / Coverage / Hypothesis / Contradiction transitions
NoProgressDetector
bounded parallelism
```

### Phase D — Correlation + verification

```text
EntityOccurrence / IdentityPolicy
DeterministicCorrelationEngine
CorrelationAgent
ProposedClaim pipeline
Grounding Validator
SemanticVerifier
AssertionPolicy
```

### Phase E — Selective Investigation Context Graph

```text
GraphCandidate
GraphAdmissionPolicy
Frozen episode
Materialization manifest
Graph Reader filtering/provenance
investigation/report retrieval modes
```

### Phase F — Agent-aware Report

```text
ReportOutlinePlan
ChapterSpec
Retrieval Planner
ReportContextPack
Chapter Writer
Assertion Ledger
Consistency Review
```

### Phase G — Benchmark / acceptance

```text
Truth Manifest
baseline + ablation harness
negative cases
large-case performance
failure-layer attribution
```

完成 benchmark 后再校准 Attention Window、Graph budget、tool limits 等数值参数。

---

## 30. 明确尚未冻结的内容

为了防止“架构文档生成后就被误认为所有细节都决定了”，以下项目仍然是 TBD / CALIBRATION：

### 30.1 Runtime adapter / prompt infrastructure

```text
PydanticAI RunContext exact contract
Agent factory exact API
model/provider adapter exact implementation
structured-output retry policy
Prompt / Contract Registry exact format
prompt composition/version registry
```

### 30.2 Case framing

```text
CaseFramingInput / Output schema
General Triage exact trigger
Case Framing 可见 source inventory 范围
Playbook activation exact rules
```

### 30.3 Capabilities / skills / tools

```text
SourceCapabilityManifest exact schema
Canonical Tool Catalog v0 exact list/schema
ArtifactFamily registry
Windows/Android/Linux/Memory exact Skill Catalog
```

### 30.4 Entity / verification policy

```text
Entity v0 exact taxonomy
IdentityPolicy registry
Correlation relation registry
AssertionPolicy exact semantic type table
```

### 30.5 Graph

```text
GraphAdmissionPolicy exact v0 rules
ForensicGraphEpisode exact schema
Graph budget
micro-batch size
Graph priority limits
input_hash exact composition
```

### 30.6 Report

```text
forensic_investigation_report:v1 exact section contract
section-level default policies
```

### 30.7 Benchmark

```text
Benchmark corpus
Truth Manifest concrete cases
acceptance hard-gate thresholds
ablation exact runtime configurations
```

### 30.8 明确留给 Benchmark 的数值参数

```text
max active skills
max skill transitions
per-run tool count/window
No-progress threshold N
parallel delegation count
Graph hop count
Graph batch size / budget
Context token budget
Attention Window size
Exploration Allowance
P1 internal ordering nuance
```

---

## 31. Core v0 Invariants

下面这些可以作为 architecture-level acceptance checklist。

### Evidence / Identity

```text
A1 Agent 不能修改原 Evidence / hash / timestamp。
A2 所有 Evidence refs 必须 task-scoped resolve。
A3 Initial Analysis Snapshot 不被 Secondary/Agent 覆盖。
A4 LLM/Graph/Observation/Case Context 永远不成为 Evidence Source。
```

### Agent / Tool

```text
A5 Agent 不直接访问 SQLite/filesystem/Graphiti/repository。
A6 ToolRegistry 是唯一 Agent data-plane execution boundary。
A7 task_id/path 等敏感 scope 由 runtime 注入，不由模型决定。
A8 Claim 只能引用 allowed_evidence_ids 中实际暴露过的 Evidence。
```

### State / Orchestration

```text
A9 一个 Investigation 同时只有一个 active Orchestrator Run。
A10 Agent workers 可并行读，但 Working State 语义提交串行。
A11 Specialist/Correlation/Verifier 不直接修改 Working State。
A12 Supervisor 只提 transition proposal，StateTransitionPolicy 决定合法性。
A13 Trajectory 记录 Action Trace，不记录/依赖私有 CoT。
A14 Restart 从 committed Working State 继续，不恢复模型 conversation/coroutine。
```

### Semantic quality

```text
A15 grounded 只表示 Evidence ref 合法，不等于语义充分。
A16 FACT / INFERENCE / HYPOTHESIS 必须保持区分。
A17 高风险 assertion 受 AssertionPolicy ceiling 与 semantic verification 约束。
A18 Agent pipeline 的 canonical 最高状态为 review_pending。
A19 accepted/rejected 只由 Analyst Review 产生。
```

### Graph

```text
A20 Graph 是选择性派生索引，不是 Truth Store。
A21 Graph object 无 TraceLens provenance 不可进入可信 Agent Context。
A22 stale/invalidated materialization 必须逻辑过滤，物理 cleanup 可延迟。
A23 Graph path 不能直接作为 Report Evidence citation。
```

### Finalization

```text
A24 Finalization 要求所有 blocking obligation 明确终态，不要求所有问题都有肯定答案。
A25 mandatory semantic operation 失败时必须降低结论强度，而不是降低验证标准。
A26 completed 是 immutable terminal；继续调查创建新的 Investigation。
```

### Report

```text
A27 Report Retrieval 不成为隐藏的 Investigation pipeline。
A28 Report Writer 无 Tool，不创建新的调查级 inference。
A29 Writer 可以改变表达，不能提高 assertion strength。
A30 Report citation 必须来自 frozen Context Pack allowlist，并最终回到真实 Evidence。
```

---

## 32. End-to-End Reference Flow

```text
User supplies Evidence + Case Context / optional Goal
        ↓
Case Framing (optional)
        ↓
Versioned Investigation Charter
        ↓
Create Investigation + initial Working State
        ↓
Start Agent Run
        ↓
AttentionBuilder
        ↓
Supervisor PLAN
        ↓
DecisionValidator
        ↓
Admission Transaction
        ↓
Parallel Source Specialist / Correlation / Verifier work
        ↓
ToolRegistry
        ↓
Existing TraceLens Services
        ↓
ToolObservations + Evidence refs
        ↓
Validated Agent Results
        ↓
MergeGuard
        ↓
Supervisor Integration (no tools)
        ↓
Typed StateTransitionProposals
        ↓
StateTransitionPolicy
        ↓
Atomic Working State Revision
        ↓
Proposed Claims
        ↓
Grounding → Semantic Verification → AssertionPolicy
        ↓
Canonical review_pending Findings
        ↓
Analyst Review → accepted/rejected
        ↓
Selective Graph Admission / Materialization as useful
        ↓
Repeat PLAN / EXECUTE / INTEGRATE / EVALUATE
        ↓
FinalizationRequest
        ↓
Deterministic preflight
        ↓
Final Semantic Review according to FinalizationPolicy
        ↓
Immutable FinalizationRecord
        ↓
Investigation completed
        ↓
Report Outline
        ↓
Chapter Retrieval → Frozen ReportContextPack
        ↓
Chapter Writer / deterministic renderer
        ↓
Citation + Semantic + Cross-chapter validation
        ↓
Immutable Report Version
```

---

## 33. Architecture Summary

Agent Architecture v0 的本质不是给 TraceLens 增加一个“万能 Agent”，而是把调查过程拆成几个责任明确、可替换、可审计的层：

```text
Evidence Store
= 真实依据

Investigation Working State
= 当前调查到了哪里

Trajectory
= 系统如何走到这里

Supervisor
= 下一步调查决策

Orchestrator
= 调度、生命周期、并发、事务与恢复

Specialist
= 平台专业调查

Correlation
= 关系问题

Grounding / Verifier
= 引用真实性与语义充分性

Investigation Context Graph
= 选择性关系索引

Analyst Review
= 人类最终确认

Report Context Pack
= 章节级冻结 Evidence 输入

Report Writer
= 表达，不调查

Benchmark
= 判断架构是否真的提高 Evidence recall、降低过度推断并控制成本
```

最终应始终遵守三句话：

> **Working State 告诉 Agent“现在在哪里”；Trajectory 告诉系统“怎么走到这里”；Evidence 告诉分析员“凭什么得出结论”。**

> **KG locates; Evidence Store proves.**

> **新 Agent 架构是否成功，不取决于它分析得更多，而取决于它是否以更少的无效搜索和更低的语义过度推断，找到更多真正关键的 Evidence，并形成更可验证、更可审计的调查结论。**
