# 叙事报告生成完整流程与阶段边界

- 调研基线：`feature/model-routing` 当前工作树（2026-10-27）
- 范围：Python `python_service/httpserver/services/forensic_report/` 的 R2 叙事链、
  `routes/report_generation.py` / `routes/report_narrative.py` / `routes/report_pipeline_tail.py`、
  C++ 流水线尾门、前端 Report 页面
- 方法：只读代码走查 + 关键测试对照；未修改生产代码

## 0. 结论先行

系统里存在**两种“两阶段”**，不要把二者混为一谈：

| 层次 | 阶段 | 代码标识 | 谁触发 | 产出 |
|---|---|---|---|---|
| 产品层 | 首次：材料自主研判 | `analysis_mode="evidence_only"`，envelope schema 5，prompt `final-report:evidence-only:v4` | 流水线尾自动 + 页面手动 | 报告 A（无案情） |
| 产品层 | 二次：案情对照研判 | `analysis_mode="case_guided"`，envelope schema 5，prompt `final-report:case-guided:v4` | 仅页面手动，必须选 A 为基线 | 报告 B（复用 A 冻结材料 + 本次案情） |
| 单次生成内部 | 分析（研判） | `materialize_images` → `_classify_evidence` → `discover_directions` → `compare_directions`（仅 B） | 执行器 | 已校验 `InvestigationDirection` / `DirectionComparison` / 分类 |
| 单次生成内部 | 整理（成文） | `induce_themes` → `pack_themes_into_chapters` → `write_chapters` → `render_stage_report` | 执行器 | 章节正文 + 引用清单 + 审计结构 |

**最关键的一条边界**：单次生成内部，分析阶段的产物是“带逐字引文与字符区间的调查方向”；
整理阶段只能重组这些方向，**不能新增事实或引文**。硬保证体现在两处：

1. 章节写入器的输入只有已校验方向及其引文（`_chapter_write_row`，
   `generation_stages.py:1258`）；
2. 章节引用不是模型输出的，而是由方向的 `supporting_refs` / `counter_refs`
   反查材料后**确定性生成**（`_direction_citations`，`generation_stages.py:2358`；
   `render_stage_report`，`generation_stages.py:2430`）。

但要注意：这是**引用/溯源边界**，不是逐句事实核验。正文措辞仍由模型生成，
代码只做“不得否认本章材料、不得写频次清单、不得泄漏内部 ID、长度/标题约束”等
形态校验（`_parse_chapter_section`，`generation_stages.py:1304`），没有逐句
把正文断言回查到方向。报告正文的“可审计性”由引用清单承担，而不是由每一句话承担。

另外还有一条**默认的第三种模式**（不属于“两阶段”）：页面默认的“综合取证报告”
（`analysis_mode=None`，envelope schema 4，prompt `final-report:v4`）。它走的是
旧的分组大纲 + 逐章 section 链路，模型会自己输出 citation，再由
`validate_report_citations` 对报告证据边界和冻结 analysis/claim 身份做硬校验
（`generation_execution.py:154`）。两阶段 A/B 与它在输入、提示词、引用生成方式上
都不同，详见 §7。

---

## 1. 端到端总览

```
任务完成前（C++ 流水线尾）
  TaskManager::wait_for_pipeline_report
    → POST /api/reports/pipeline-tail
      → auto_generate_pipeline_report
        → seed_analyzed_files（登记入报证据）
        → ensure_evidence_copies（C++ 抽取文件副本）
        → admission.admit(analysis_mode="evidence_only")
        → executor.submit(generation_id)
      → 轮询 GET /api/reports/pipeline-tail/status
    → 只有报告 A 完成，任务才 COMPLETED

页面手动（两阶段）
  GenerateReportPanel
    → POST /api/reports/generate
      ├─ analysis_mode="evidence_only"：冻结中立材料，生成 A
      └─ analysis_mode="case_guided"：校验 A 为基线，复用 A 冻结材料，生成 B
    → 轮询 GET /api/reports/generations/{generation_id}?task_id=...
    → completed 后 GET /api/reports/narrative/versions/{report_id}?task_id=...
    → NarrativeReportView 渲染 sections + citations + stage_analysis

执行器内部（A/B 共用，B 多一步 compare）
  claim → 重算 canonical + 校验 input_hash
    → materialize_images（A：真实读取/图像一次；B：直接复用 A 的材料）
    → _classify_evidence（六维分类，best-effort）
    → discover_directions（逐批研判，逐字引文校验）
    → compare_directions（仅 B，逐基线方向对照）
    → induce_themes（局部主题 + 全局合并）
    → pack_themes_into_chapters（确定性分层 + LPT 装箱，固定章数）
    → write_chapters（逐章成文，可分段/重试）
    → render_stage_report（确定性拼装范围章/案情章/差异章/核查建议章）
    → validate_report_citations（边界硬校验）
    → publish manifest.json（staging + os.replace）
    → complete_generation_publication（同事务分配 version + ready 行）
```

入口与路由挂载：

- `python_service/httpserver/main.py:310-335`：`/api/reports` 前缀挂载
  `report_pipeline_tail`、`forensic_reports`、`report_evidence`、
  `report_generation`、`report_narrative`。
- C++ 侧：`src/network/HTTPServer/TaskManagerAnalysis.cpp:366`
  `wait_for_pipeline_report`；`src/network/HTTPServer/LLMPythonProxy.cpp:367`
  `trigger_report_tail`。

---

## 2. 阶段一：准入（冻结输入）

### 2.1 请求契约

`routes/report_generation.py:60-86`：

```python
analysis_mode: Literal["evidence_only", "case_guided"] | None = None
base_report_id: str | None = None
case_description: str | None = None
```

校验规则（`model_validator`）：

- `analysis_mode=None`：不能带 `base_report_id` / `case_description`；
- `evidence_only`：不能带基线或案情；
- `case_guided`：必须带 `base_report_id`。

客户端**不能提交**证据列表、analysis ID、citation、prompt 版本、模型或 envelope
（`report_generation.py:1-7` 模块注释；`admit` 参数签名也只接受任务、操作人、阶段、
基线与案情，`generation.py:369-377`）。

### 2.2 两种准入分支

**（a）默认综合报告 / v4**：`analysis_mode is None` 时，
`ReportGenerationInputBuilder.assemble(prompt_version="final-report:v4")`
（`generation.py:98`）在一个只读事务里读 `investigation.db` 的
`report_evidence`：

- 跳过 `excluded`（审计状态，永不作为生成输入）；
- 跳过 `cluster:` 前缀（MVP 约定事件簇不入报）；
- 对每条 `main` / `appendix` 读取冻结 `evidence_snapshots`；
- 若 `analysis_id` 非空，复验该 analysis 属于同一证据、状态为 `accepted`，
  并读取其 claims 与 `claim_evidence_refs`（`generation.py:208-289`）；
- `allowed_report_evidence_ids` = main + appendix 的 evidence_key 排序去重。

**（b）两阶段 A/B / v5**：`_stage_envelope`（`generation.py:430`）先走同一
builder 得到当前入报范围，然后：

- A（`evidence_only`）：
  - 要求 investigation store 存在且有入报证据；
  - `sanitize_items` 剥掉 `bound_analysis` 与派生字段（`generation_sources.py:58`）；
  - `freeze_materials` 从**实际文件字节/派生记录**重新冻结内容
    （`generation_sources.py:160`），不读 `file_analyses` / `files.llm_*` 旧摘要；
  - 生成 `NeutralMaterial`（别名 `m0001...`，文本最多 4000 字符，
    记录 source_sha256 / content_sha256 / 限制标记）；
  - 计算 `evidence_scope_hash = material_scope_hash(materials)`；
  - 构造 `ReportGenerationEnvelopeV5`（`forensic_report/models.py:545`），
    `case_description=""`、`baseline=None`。
- B（`case_guided`）：
  - 案情取显式提交值；未提交时回退任务 `case_description`
    （“包含案情”开关语义，`generation.py:449-452`）；空或超过 8000 字拒绝；
  - 基线必须是本任务、已 `ready`、`report_kind='llm_generation'`、
    `stage_analysis.analysis_mode='evidence_only'` 的 A（`generation.py:454-466`）；
  - 回读 A 的 admission 行，要求 `completed`、`report_id` 匹配、`task_id` 匹配；
  - 重新解析 A 的 envelope 并做四重一致性校验：
    canonical 重算哈希 == 记录的 `input_hash`；
    `manifest.input_hash == original.input_hash`；
    `stage.evidence_scope_hash == frozen.evidence_scope_hash`；
    `validate_materialized_sources(frozen.neutral_materials, stage.materials)`；
  - 再读一次 A 的 manifest 并与已解析 manifest 全量比较（防冻结期间被改）；
  - 冻结 `BaselineContext{report_id, report_sha256, input_hash,
    evidence_scope_hash, materials, directions, priorities, text_models}`；
  - 构造 B 的 V5 envelope：复用 A 的 `main/appendix/allowed_ids/neutral_materials/
    evidence_scope_hash`，只新增案情与 baseline。

### 2.3 冻结与持久化

`_persist_envelope`（`generation.py:412`）：

1. `canonical_json(envelope)`（`investigation/acquisition.py:37`，排序键、
   紧凑分隔符）；
2. `input_hash = SHA-256(canonical)`；
3. 插入 `report_generation_inputs`（`repository.py:79`）：
   `generation_id / task_id / scope / status='admitted' / requested_by /
   input_schema_version / prompt_version / input_envelope_json / input_hash /
   created_at`。

冻结区的数据库级约束（`repository.py:103-169`）：

- `trg_report_generation_input_frozen`：插入后禁止 UPDATE 冻结字段；
- `trg_report_generation_input_no_delete`：禁止删除；
- 状态机：`admitted → running|failed`、`running → completed|failed`；
- `completed` 必须带 `report_id / produced_version / model / completed_at`；
- `failed` 不得引用已发布版本；
- 终态行整体不可变。

**边界结论**：准入阶段不做任何 LLM 调用；A 的 `input_hash` 从冻结完成起不可变，
后续分析员 rebind / 新增 accepted / 改入报范围都不会改变已准入的 A。

---

## 3. 阶段二：执行（分析 → 整理）

执行器 `ReportGenerationExecutor._execute`（`generation_execution.py:448`）。

### 3.1 执行前校验（每次都做）

1. `claim_generation`：`admitted → running`，并发只有一个赢家
   （`repository.py:485`）；
2. `parse_generation_envelope`：按 schema_version 分派严格模型；
3. 重新 canonical 化并与 `input_envelope_json` 逐字节比较、`hmac.compare_digest`
   校验 `input_hash`；任一不符 → `input_integrity_error`；
4. 校验 `(schema_version, prompt_version)` 在
   `REPORT_GENERATION_ENVELOPE_COMPAT` 内且与行记录一致；否则
   `unsupported_input_contract`（`generation_prompts.py:38`）。

### 3.2 分析阶段（Analysis）

#### （1）材料物化 `materialize_images`（`generation_stages.py:143`）

- A：遍历 `neutral_materials`；
  - 非图像原样使用；
  - 图像调用一次视觉模型（`NEUTRAL_IMAGE_PROMPT_V1`，**不带案情**），
    成功则替换为 `kind="machine_visual"`，保留 source_sha256、
    限制标记 `MACHINE_VISUAL_NOT_ORIGINAL_TEXT`；失败则 `unavailable`
    + `NEUTRAL_VISUAL_FAILED`，不会把错误文本当观察。
- B：直接返回 `envelope.baseline.materials`，先 `validate_materialized_sources`
  做身份/哈希/文本一致性校验；**不再调用视觉模型**。
- 若没有任何 `text` 且状态非 `unavailable` 的材料 → 抛
  `NEUTRAL_SOURCES_UNAVAILABLE`，整次生成失败（`generation_execution.py:673-674`）。

材料冻结硬限制（`generation_sources.py:21-25`）：
单文件 64 MiB；每份文本最多 4000 字符；全报告文本预算 200 万字符；
单图 2 MiB、总计 8 MiB。超限/缺失/哈希变化/路径歧义/不支持格式 →
保留为 `unavailable` 并写明限制码，不用旧摘要补齐。

#### （2）六维分类 `_classify_evidence`（`generation_execution.py:709`）

- A：通用核查问题 4 条（资金、人员账号、通讯网络位置、正常业务/虚构解释），
  来自 `GENERIC_QUESTIONS`（`generation_stages.py:113-118`）；
- B：在通用问题之外，追加由本次案情切分出的 `qNNN` 问题
  （`classification_questions`，`generation_classification.py:41-54`）；
- 每批 6 份材料（`BATCH_SIZE`），材料多于一批时并发扇出；
- 分类依据随模式不同（`generation_classification.py:52-96`）：
  - 两阶段（v5，传入 `materials`）用本轮冻结文本 `source.text[:1200]` 作为
    `basis_text`，`basis_type` 为 `neutral_material` / `machine_visual` /
    `android_record`；
  - 综合报告（v4，不传 `materials`）用 `initial_summary` +
    `initial_description` 拼接，`basis_type` 为 `initial_analysis` 或
    `metadata`。**v4 的分类依据包含历史 AI 摘要**，这是它与两阶段
    “只用冻结原文”的一条实质差异（不改变证据快照或人工决定，
    但分类理由的来源层级不同）；
- 模型只输出 topics / relations / key_issue / reason / basis_quote；
  **优先级由服务端确定性计算**（`generation_classification.py:139-145`）：
  - P1：存在 `inconsistent`，或 `supports` 且 `key_issue`；
  - P2：存在 `supports`；
  - P3：只有 `background`；
  - 否则 `unassessed`；
- `basis_quote` 必须逐字来自该材料的 basis_text（允许空白折叠）；
- 协议失败重试一次并带错误提示；仍失败该批保持 `unassessed`；
  provider 不可用也保持 `unassessed`，不阻断报告；
- 非 HTTP、非协议类异常向上抛，避免“静默未分类却发布报告”。

**边界结论**：分类是“辅助标注”，不是人工复核结论；它不会改变入报集合、
证据快照或任何人工决定。分类失败是**可降级**的。

#### （3）调查方向发现 `discover_directions`（`generation_stages.py:301`）

- 只使用有文本且非 `unavailable` 的材料；
- 按**请求字节预算**与条数双重装箱（`_pack_batches`，
  `generation_stages.py:183`）；单条材料超预算时单独成批，请求守卫会诚实拒绝；
- 每批一次 LLM 调用，并发受 `report_concurrency` 限制（默认 8，
  且受 `llm_max_concurrency` 约束；`generation_stages.py:47-63`）；
- 输出经 `parse_directions`（`generation_stages.py:267`）硬校验：
  - `supporting_refs` / `counter_refs` 的 quote 必须逐字出现在本次发送文本
    **且**出现在完整冻结文本中；quote 过长时回退到“仍逐字出现的最长前缀”，
    不接受改写；
  - `observation` 必须有 supporting_refs；
  - `hypothesis` 必须有 `missing_information` 或 `alternative_explanations`；
  - A 模式不接受 `case_context_quote`，也不接受非 `material` origin；
  - B 模式下，没有材料支持、仅有案情引文的方向只能是 `hypothesis`，
    origin=`case_only`；
  - 同源重复（source_group 相同）会追加“不能计作独立佐证”的缺失信息；
  - 方向 ID 由输出内容确定性哈希生成（`d_<sha256[:24]>`）。
- 首批全部批次失败 → `NO_VALIDATED_NEUTRAL_ANALYSIS`，整次失败；
  部分批次失败 → 记录 `DIRECTION_BATCH_REJECTED_n` 警告，继续；
- 材料数超过一批时做一次有界跨批复核（`CROSS_REVIEW_BATCH=16`），
  只接收已校验引文，原始方向始终保留。

#### （4）案情对照 `compare_directions`（仅 B，`generation_stages.py:396`）

- 对 A 的**每一条** baseline direction 逐一比较，并发扇出；
- 输入 = 本次案情 + A 的基线方向 + A 的原始引文片段 +
  本轮相关方向（`current_directions_not_evidence`，明确标注不是证据）；
- 输出经硬校验：
  - `baseline_direction_id` 必须匹配；
  - `supported/revised` 必须有 supporting_refs；
  - `weakened/contradicted` 必须有 counter_refs；
  - `case_only` 必须有案情引文且不能有材料引用；
  - 所有引文必须逐字出现在发送文本与冻结文本中；
- 失败（校验不过/预算超限）→ 该方向记为 `insufficient` +
  `COMPARISON_REJECTED_<direction_id>` 警告，**保留 A 的原始方向，不删除、不改写**；
- 输出 `DirectionComparison` 覆盖 A 的全部方向（`StageAnalysis` 校验器强制
  每个 baseline direction 恰好出现一次，`forensic_report/models.py:893-945`）。

**边界结论**：分析阶段的硬边界是“所有事实性引用都能回查到冻结材料中的逐字片段”。
模型可以提出假设，但假设必须自带缺失信息/竞争性解释；仅案情提出的内容只能以
`case_only` 假设存在，不能升级为材料观察。

### 3.3 整理阶段（Organizing）

整理阶段由 `_generate_staged` 调用（`generation_execution.py:687-695`）：

```python
narrative = await compose_stage_narrative(
    envelope, materials, directions, comparisons, provider, concurrency=...)
response, stage = render_stage_report(
    envelope, materials, directions, comparisons, warnings, narrative)
```

#### （1）主题归纳 `induce_themes`（`generation_stages.py:705`）

- 按请求预算把方向切片；
- 每片让模型只做归类，输出 `{themes:[{name, ids}], no_theme:[...]}`；
- 校验：只能出现输入中的 direction_id，不得遗漏/编造；
- 全局合并（`STAGE_THEME_MERGE_SYSTEM_V1`）：把局部主题并为全局主题，
  合并后单主题方向数不得超过 25；合并失败则降级使用局部主题；
- 确定性后处理：
  - 超 25 条的主题按局部边界拆分或按确定性分片；
  - `_consolidate_themes` 按名称共享关键词合并碎片；
  - `_split_case_critical`：把远控/木马/外联等“案件关键对象”的观察
    单独拉成“重点可疑对象”主题；带否定的提及（“未显示与 Quasar 的关联”）
    不会被误判；
  - `_split_no_finding_and_hypotheses`：把“解析为空/失败/无实质”类方向
    汇入“材料解析限制与空记录”，把假设类方向汇入“待验证推断与可疑关联”，
    观察与其同名假设成对移动；
- 某片主题归纳失败 → 该片方向进入未归类桶，最终以领先工件命名，
  不丢方向；全部失败 → `NO_VALIDATED_THEME`，回退到批次叙事，
  再回退到片段渲染。

#### （2）章节装箱 `pack_themes_into_chapters`（`generation_stages.py:1138`）

- 目标叙事章数固定 `_TARGET_NARRATIVE_CHAPTERS = 10`；
- 保留层（假设/关键对象/解析限制）各占一章，且至少给发现留 1 章；
- 过大的主题按 1.2 倍均衡章大小拆分，并给每片一个可区分的标签；
- 用 LPT（Longest Processing Time first）确定性装箱，保证：
  - 每个主题恰好进入一章；
  - 章数由代码决定，不随模型输出漂移；
  - 同主题在各章使用相同主题名；
- 最终渲染阶段还有 `_MAX_REPORT_CHAPTERS = 20` 的硬上限，
  超出的叙事批次不合并进最后一章，而是丢弃并记
  `NARRATIVE_OVERFLOW_DROPPED_n_CHARS` 警告（`generation_stages.py:2472`）。

#### （3）逐章成文 `write_chapters`（`generation_stages.py:1760`）

- 每章输入：`chapter_topics` + 该章全部 `directions`（含 title/kind/description/
  supporting/counter/missing_information/alternative_explanations）；
- 章过大时按请求预算拆成多个 part；part 有角色（first/middle/last），
  只有第一段可写引言、最后一段可写结论，避免“多段拼接成多个报告”；
- 输出硬校验（`_parse_chapter_section`）：
  - 必须为 `{heading, content}`；
  - 正文不少于 300 字符、超过 4000 字符按句界裁剪；
  - 不得出现“本章未提供任何发现/无法作出任何结论”这类否认本章材料的表述；
  - 不得出现内部 `mNNNN` / `direction_id` / `evidence_key`；
  - 标题不超过 24 字，超长按自然边界缩短；
- 若原文是频次清单，追加一次改写提示；仍不合格则用确定性压缩
  （`_compress_inventories`）；
- 章节标题优先由单独的标题模型生成；若标题是裸库名（KERNEL32 等）、
  裸标识符或名词碎片，则回退到主题名或“对象 + 动作”标签；
- 所有 part 写完后合并为一个 chapter，正文用 `_strip_repeated_scaffolding`
  去掉重复的开头/收尾；
- 某章写入失败 → 记 `CHAPTER_SECTION_REJECTED_n` 警告，继续其它章；
  全部章失败 → 回退到片段渲染。

#### （3b）全案总述与表后总结 `compose_case_overview` / `compose_recall_summary`

两个后置小调用，都在章节成文之后执行，因此只能重述已有章节：

- `compose_case_overview`：输入是**章节标题 + 各章小结 + 支撑度最高的 12 条方向 +
  入报统计**，不喂原始材料。输出两到三段（350–700 字）总述，先说全案呈现什么、
  再说最值得追查的具体对象与关键参数、最后区分已支持观察与待核假设。任何失败
  （异常、空响应、含内部 ID、过短）都回退到 `_deterministic_overview`：用材料数、
  观察/假设条数、被引材料数与最强对象名说话，保证首章不会因为这些调用失败而变薄。
- `compose_recall_summary`：只接收召回表自己的数字（`scope`）与前 10 行，
  写 40–120 字的表后总结。若模型把"未进入正文的材料"说成"已召回但未被引用"
  （与表注相反），`_RECALL_SUMMARY_CONTRADICTION_RE` 会识别并改用确定性句子。

两者的模型包装解包统一走 `_plain_models_text`：任意单字符串 JSON 对象都会被展开，
避免 `{"overview":"…"}` 直接发布成正文（真实 v5 首轮曾发生）。

#### （4）确定性拼装 `render_stage_report`（`generation_stages.py:2970`）

输出的章节顺序固定为：

1. **案件总述与证据召回**（首章）：内容 = 全案总述 + **原研判范围与方法段落原文**；
   该章携带 `recall_table`（证据召回表）与 `summary`（表后总结）；
   **章节级 `citation_ids` 仍为空**（方法说明不认领全报告引用，引用由表内行与后续章节承担）；
2. **本次案情（待核语境）**：仅 B，原文正文，附一句"仅作调查语境"的小结；
3. 叙事章节：来自 `narrative`，每章 `citation_ids` 由 `_direction_citations`
   从该章方向的引文反查材料得到；每章带自己的 `summary`（见 §3.3(3)）；
4. 若没有方向：**调查方向与限制**（带确定性小结）；
5. **与首次研判的差异**：仅 B，按状态汇总，只点名 `contradicted/revised/case_only`
   中最多 12 项，其余计数；带按状态统计的小结；
6. **人工核查建议**：从各方向的 `missing_information` 去重排序生成核查清单，
   并统计未展开的分析/覆盖限制；带确定性小结。

**证据召回表（`EvidenceRecallTable`）是纯确定性的**：每行由一个已被某章引用的
`citation_id` 反查材料得到，字段为 `citation_id / evidence_key / evidence_name /
material_type / priority / topics / reference_count / chapter_count /
material_status`。排序按 `reference_count` 降序、`chapter_count` 降序、材料登记顺序，
上限 `_RECALL_TABLE_LIMIT = 40` 行；被截断、可用但未引用、不可读三类情况写进 `notes`，
因此表后总结里的数字与表本身永远一致（实测 393 份 / 788 处引用 / 402 份未进入正文）。

兜底：若 `narrative is None`，按每 8 条方向生成
“材料自主发现（n）”或“案情对照发现（n）”片段章节，每条方向包含
支持/相反引文、缺失信息、其他解释、仅案情提示，并带确定性小结。
**报告不会因为整理阶段失败而整体失败**；它降级为结构化片段，
此时不渲染召回表（没有章节就没有被引材料）。

同时构造 `StageAnalysis`（`forensic_report/models.py:893`）：

- `analysis_mode`、`evidence_scope_hash`、`case_description`、
  `case_context_hash`（B）、`baseline_report_id/hash`（B）、
  `materials`、`directions`、`comparisons`、`baseline_directions`、
  `baseline_priorities`、`warnings`、`text_models`、`baseline_text_models`；
- 校验器强制：
  - 材料 id/key 唯一，且不携带 media bytes；
  - A 不得带案情、基线、比较、非 material origin；
  - B 必须带案情哈希与基线身份，比较覆盖每个基线方向恰好一次；
  - 所有引文在冻结材料中的 `[character_start:character_end]` 必须逐字相等；
  - 方向不得引用基线之外的方向。

### 3.4 发布与完成

`_execute` 后续（`generation_execution.py:530-590`）：

1. `validate_report_citations(response, envelope)`：
   - v5 路径的 citation 由材料确定性生成（每条 `evidence_key` 都在
     `allowed_report_evidence_ids`，`analysis_id/claim_id` 均为 None），
     因此天然通过；
   - v4/v1-v3 路径这里是真正的硬门：引用必须在报告证据边界内，
     analysis 必须等于冻结绑定的 `analysis_id`，claim 必须是该分析内
     精确 claim_id，不能按文本匹配、不能自动附加更新版本的 analysis。
2. 构造 `GenerationReportManifest`（`forensic_report/models.py:946`）：
   `schema_version=1.2`、`report_kind='llm_generation'`、`report_id`、
   `generation_id`、`task_id`、`title`、`prompt_version`、`input_hash`、
   `model`、`sections`、`citations`、`evidence_classifications`、
   `stage_analysis`；
3. `GenerationReportWriter.publish`（`generation_writer.py:46`）：
   - 目标目录已存在 → `FileExistsError`（不可变）；
   - 写 `.staging/<report_id>/manifest.json`（canonical JSON）；
   - `os.replace(staging, final_dir)` 原子发布；
   - 失败清理 staging；
4. `complete_generation_publication`（`repository.py:536`）：
   **一个 `BEGIN IMMEDIATE` 事务**内完成：
   - `MAX(version)+1` 分配本任务下一个版本号；
   - 插入 `report_versions` 行：`ready`、`progress=100`、
     `report_kind='llm_generation'`、`manifest_path`（相对路径）；
   - 更新 generation 行：`completed`、`report_id`、`produced_version`、`model`。

**边界结论**：版本行只在成功发布后出现；失败不会留下 Viewer 可见的半成品。
若在 `os.replace` 成功与事务提交之间崩溃，磁盘上最多留下一个不可见的孤儿目录，
重启恢复会把 `admitted/running` 行标为 `failed(service_restart)`，不自动重放。

---

## 4. 阶段 A 与阶段 B 的边界（逐项）

| 维度 | A：材料自主研判 | B：案情对照研判 |
|---|---|---|
| 触发 | 流水线尾自动；页面手动 | 仅页面手动 |
| 前置 | 任务有入报证据 | 必须有一份 `ready` 的 A |
| 案情 | 强制为空；任务标题/备注/旧摘要/已接受分析/入报绑定的 analysis 全部剥离 | 只加入显式提交的案情（或“包含案情”开关回退的任务案情）；不覆盖任务案情、不覆盖 A |
| 证据 | 从原字节/派生记录重新冻结（`neutral_materials`） | 原样复用 A 的 `neutral_materials`；不重新读取、不重新冻结 |
| 视觉 | 图像调用一次视觉模型，结果只作机器观察 | 复用 A 的机器观察，不再调用视觉模型 |
| 方向 | 只能来自材料；`origin='material'` | 可来自材料（`reinterpreted`/`new_candidate`）或仅案情（`case_only` 假设） |
| 对照 | 无 | 对 A 的每条方向逐一给 `supported/revised/weakened/contradicted/insufficient/case_only`；失败保留 A 并标 `insufficient` |
| 分类问题 | 4 条通用核查问题 | 通用问题 + 本次案情切分问题 |
| 基线优先级 | 无 | 冻结 A 的分类优先级用于对照 |
| 文本模型 | 记录本轮模型 | 记录本轮模型，并与 A 的 `text_models` 比较；不同则警告 |
| 版本 | 新版本、新 report_id、新 input_hash | 新版本、新 report_id、新 input_hash；A 的 manifest 字节不变 |
| 自动重跑 | 已有 A 或已有在途生成则跳过 | 无自动运行 |

硬性不可越界：

- B 不能把 B 当基线（`test_task_scope_and_stage_guards`）；
- B 的 `evidence_scope_hash` 必须等于 A，材料身份三元组
  `(material_id, evidence_key, source_sha256)` 必须一致；
- B 不能重新读取 live 文件或重新冻结材料
  （`test_second_stage_reuses_exact_baseline_after_live_files_and_adoption_change`
  用 monkeypatch 让 `freeze_materials` 直接抛错来证明）；
- A 不能带案情/基线/比较（V5 模型校验器 + `StageAnalysis` 校验器双重约束）；
- 已发布 A 的 manifest 在 B 生成前后字节不变。

---

## 5. 分析阶段与整理阶段的边界（单次生成内部）

| 维度 | 分析 | 整理 |
|---|---|---|
| 目标 | 从材料中提炼可回查的观察、假设、分类、对照 | 把已校验发现组织成可读章节与核查建议 |
| 输入 | 冻结材料（A：真实读取；B：A 的材料） | 已校验 `InvestigationDirection` + `DirectionComparison` + 材料 |
| 模型输出 | 分类、方向（含逐字引文）、对照 | 主题分组、章节标题、章节正文 |
| 硬校验 | quote 逐字匹配；observation 必须有支持；hypothesis 必须有缺失/替代解释；case_only 只能 hypothesis；比较必须有对应支持/相反引文 | 章节不得否认本章材料；不得输出内部 ID；长度/标题约束；引用由方向反查生成 |
| 失败语义 | 分类可降级为 unassessed；单批方向失败记警告；**首批全失败则整次失败**；比较失败降级 insufficient | 主题归纳失败回退批次叙事；章节写入失败跳过该章；整理整体失败回退片段渲染；超出章数上限丢弃并警告 |
| 产物 | `stage_analysis.directions / comparisons / evidence_classifications` | `sections` + `citations`（material-level） |
| 事实边界 | 强（每条引用可回查冻结文本字符区间） | 引用强、措辞弱（正文不逐句回查；提示词约束“不得新增事实”） |

**边界的代码位置**：

- 分析结束、整理开始的交界：
  `discover_directions` / `compare_directions` 返回
  `tuple[InvestigationDirection]` / `tuple[DirectionComparison]`；
  `compose_stage_narrative` 接收它们（`generation_stages.py:1923`）。
- 整理阶段禁止新引文：
  `_chapter_write_row` 只暴露已校验的 supporting/counter 引文
  （`generation_stages.py:1258`）；`_direction_citations` 只从这些 refs
  反查材料（`generation_stages.py:2358`）。
- 整理阶段禁止新证据/新 analysis：
  V5 envelope 的 `neutral_materials` 与 `allowed_report_evidence_ids` 一一对应；
  `sanitize_items` 已把 `bound_analysis` 置空；V5 校验器禁止
  `bound_analysis` 与任何派生字段（`forensic_report/models.py:560-566`）。

---

## 6. 读取侧边界

### 6.1 轮询

`GET /api/reports/generations/{generation_id}?task_id=...`
（`routes/report_generation.py:149`）：

- 按 exact `generation_id` 读取，无“latest”回退；
- `row.task_id != task_id` 与不存在同样返回 404（不泄露跨任务存在性）；
- 读取用 `read_generation_strict`：`mode=ro` + `PRAGMA query_only`，
  不创建、不迁移、不自愈（`generation_execution.py:254`）；
- `completed` 时附带已发布 manifest（`_status_response`），
  但**不返回 envelope、system prompt、provider 配置或文件系统路径**。

### 6.2 阅读已发布版本

`GET /api/reports/narrative/versions/{report_id}?task_id=...`
（`routes/report_narrative.py:55`）：

- 只接受 `scope_type='task'`、`scope_id=task_id`、
  `report_kind='llm_generation'` 的版本；跨任务或确定性快照 id
  一律 opaque miss → 404；
- 通过 `read_narrative_version_strict`（`narrative_reader.py:48`）：
  `mode=ro` + `query_only`，manifest 通过 writer 的受限布局读取，
  校验 `manifest.report_id/task_id/scope_id` 与版本行一致；
- 返回：版本行 + manifest 的 `sections / citations /
  evidence_classifications / stage_analysis`；
- 不返回 envelope 字节、prompt、provider 数据、绝对路径；
- 损坏 → 503（fail-closed）。

### 6.3 前端

- `ForensicReportPage` 用 `useReportVersion` 拉版本列表；
  `report_kind === 'llm_generation'` → 渲染 `NarrativeReportView`，
  否则走确定性快照的目录/分页工作区
  （`web/src/pages/ForensicReportPage.jsx:54`；
  `web/src/hooks/useReportVersion.js:192`）；
- `NarrativeReportView` 只消费 persisted manifest：
  - `citations` 按 `citation_id` 建表，点击 = 精确查表，不做正则/Markdown/
    路径推导（`NarrativeReportView.jsx:135`）；
  - 两阶段报告（有 `stage_analysis`）打开引用时展示 `StageSourcePanel`
    的冻结材料，而不是当前 Investigation 的实时记录；
  - 非两阶段报告展示 `CitationTracebackPanel`，再用当前 investigation
    做可选增强；增强失败保留冻结身份并提示“详细记录当前不可读取”；
  - 未知 `citation_id` 只显示“未知引用”，不猜测；
- `GenerateReportPanel` 三个模式：
  `narrative`（默认）、`evidence_only`、`case_guided`
  （`web/src/components/reports/GenerateReportPanel.jsx:220-236`）。

---

## 7. 三种报告模式的区别（避免混淆）

| 模式 | `analysis_mode` | envelope | prompt | 输入 | 引用如何产生 | manifest |
|---|---|---|---|---|---|---|
| 综合取证报告 | `None` | schema 4 | `final-report:v4` | `report_evidence` main/appendix + 可选绑定 analysis；任务案情 | 模型逐章输出 citation，`validate_report_citations` 硬校验边界 + 冻结 analysis/claim 身份 | schema 1.1，含 classification，无 stage_analysis |
| 首次材料自主研判 | `evidence_only` | schema 5 | `final-report:evidence-only:v4` | 中立冻结材料；无案情、无旧摘要、无绑定 analysis | 由方向引文确定性反查材料，模型不输出 citation | schema 1.2，含 stage_analysis + classification |
| 二次案情对照研判 | `case_guided` | schema 5 | `final-report:case-guided:v4` | A 的冻结材料 + A 的 directions/priorities + 本次案情 | 同上 | schema 1.2，含 stage_analysis（含 comparisons + baseline） |

注意命名容易误读：

- v5 两阶段当前使用的 prompt 版本字符串是 `...:v4`（`generation.py:447,491`），
  而 envelope schema 是 **5**；manifest schema 是 **1.2**。
  历史 `...:v1/v2/v3` 行仍按其记录契约执行（`REPORT_GENERATION_ENVELOPE_COMPAT`），
  因此同一次升级不需要回填旧报告。
- `:v3 → :v4` 只改变**成文形态**（首章总述 + 证据召回表 + 每章小结），
  分析阶段（分类 / 方向发现 / 案情对照）的提示词与校验完全未变。
- `final-report:v1` 仅是遗留单发契约，准入已不再产生；
  历史 schema 1-3 的行仍可按记录契约执行。
- v5 两阶段**不会**把已接受 analysis 带入报告：`sanitize_items` 置空
  `bound_analysis`，V5 校验器禁止其存在。因此两阶段的
  `citation_manifest` 只有 material-level 身份（`evidence_key`），
  没有 `analysis_id` / `claim_id`。这是与 v4 综合报告的关键区别。

---

## 8. 失败与降级矩阵

| 失败点 | 代码 | 结果 | 是否留下可见版本 |
|---|---|---|---|
| 无入报证据 | `generation.py:391-397` | 409 `no_report_evidence` | 否 |
| B 缺基线/案情/基线无效 | `generation.py:454-466` | 409 `baseline_required` / `case_context_required` / `invalid_baseline` | 否 |
| 输入哈希/契约不符 | `generation_execution.py:466-500` | `input_integrity_error` / `unsupported_input_contract` | 否 |
| LLM 未初始化 | `generation_execution.py:499` | `llm_unavailable` | 否 |
| 无可读中立材料 | `generation_execution.py:674` | `neutral_sources_unavailable` | 否 |
| 方向首批全失败 | `generation_stages.py:370` | `no_validated_neutral_analysis` → `stage_analysis_invalid` | 否 |
| 引用越界/身份不符（v4） | `generation_execution.py:154` | `citation_invalid` | 否 |
| 发布失败 | `generation_execution.py:581-590` | `publication_error` | 否 |
| 服务重启/关闭 | executor `initialize/shutdown` | `service_restart` / `service_shutdown`，不自动重放 | 否 |
| 分类协议失败 | `generation_execution.py:757-790` | 保持 `unassessed`，报告继续 | 是（分类降级） |
| 单批方向失败 | `generation_stages.py:362-369` | 警告并继续其它批 | 是（覆盖降级） |
| 比较失败 | `generation_stages.py:456-467` | `insufficient` + 警告，保留 A | 是（差异降级） |
| 主题归纳失败 | `generation_stages.py:1903-1914` | 回退批次叙事，再回退片段 | 是（结构降级） |
| 单章写入失败 | `generation_stages.py:1864-1870` | 跳过该章 + 警告 | 是（章节缺失） |
| 叙事超章数上限 | `generation_stages.py:2472-2483` | 丢弃超出部分 + `NARRATIVE_OVERFLOW_DROPPED_n_CHARS` | 是（内容裁剪） |

错误码分类：`_classify_generation_error`（`generation_execution.py:140`）
把 `httpx.ReadTimeout` / `ConnectError` / `HTTPStatusError` 映射为
`llm_timeout` / `llm_connection_error` / `llm_http_error`，其余为
`execution_error`；错误信息均为固定字符串，不泄露 provider URL 或路径。

---

## 9. 关键不变量（可作为验收清单）

1. **准入冻结**：A 的 `input_envelope_json` 与 `input_hash` 插入即不可变；
   任何后续 rebind / 新 accepted / 入报变化都不改变已准入 A。
2. **B 只读 A**：B 不重新读取源文件、不重新冻结、不调用视觉模型；
   A 的 manifest 字节在 B 生成前后不变。
3. **证据范围守恒**：V5 `neutral_materials` 的 evidence_key 列表必须
   等于 `allowed_report_evidence_ids`；每份入报证据恰好一个材料，
   不可用的也保留为 `unavailable`。
4. **引文逐字可回查**：方向的 supporting/counter quote 必须同时出现在
   发送文本与完整冻结文本中；`StageAnalysis` 再次校验
   `text[character_start:character_end] == quote`。
5. **比较全覆盖**：B 的 comparisons 必须覆盖 A 的每个 direction 恰好一次；
   失败也必须以 `insufficient` 出现，不能消失。
6. **整理不新增引用**：章节 citation 由方向 refs 反查材料生成；
   模型不输出 citation（v5）。
7. **发布原子性**：manifest 先原子落盘，版本行与 generation 完成同事务提交；
   失败无可见版本。
8. **读取只读**：所有新 GET 使用 `mode=ro` + `query_only`，
   不构造 repository、不迁移、不自愈。
9. **跨任务隔离**：generation 与 narrative 读取都要求 `task_id` 精确匹配；
   跨任务 id 与不存在不可区分。
10. **整理可降级、分析不可静默**：分类/比较/主题/单章失败可降级并留痕；
    但“没有可读材料”“首批方向全部未通过校验”“输入完整性失败”
    必须整次失败，不能发布空壳报告。

---

## 10. 验证与测试入口

后端（`python_service/tests/unit/forensic_report/`）：

- `test_report_stages.py`：A/B 输入隔离、A 哈希不变、B 复用 A 冻结材料、
  case_only 不伪造支持、比较失败保留基线、不可读源不回退旧摘要、
  图像只读一次、阶段守卫、哈希/符号链接越界、SQLite 只读样本、
  转写复用、方向契约拒绝案例污染。
- `test_generation_admission.py`：准入与 envelope 冻结。
- `test_generation_execution.py`：执行器、哈希校验、发布、恢复。
- `test_chapter_packing.py`：章节装箱确定性。
- `test_theme_induction.py`：主题归纳与合并。
- `test_stage_narrative.py`：叙事章节渲染、引用、ID 清洗、标题派生、章数上限；
  v5 形态（每章小结、全案总述与其回退、证据召回表的计数/上限/分类标签/未引用说明、
  重复套话开头清理、JSON 包装解包、表后总结自相矛盾检测）。
- `test_report_narrative_routes.py`：narrative 读取的 task scope / opaque miss。
- `test_report_generation_routes.py`：generate 路由契约。

前端：

- `web/src/components/reports/GenerateReportPanel.test.jsx`：三模式提交。
- `web/src/components/reports/StageAnalysisPanel.test.jsx`：阶段面板、基线回链。
- `web/src/components/reports/NarrativeReportView.*`：引用查表、冻结材料溯源；
  首章（正文 → 召回表 → 表后总结）的 DOM 顺序、表格行点击与正文引用同路径、
  无小结的旧报告保持原样。
- `web/src/components/reports/EvidenceRecallTable.jsx`：召回表只读渲染
  （`data-testid="evidence-recall-table"` / `recall-row` / `recall-citation-<id>`）。
- `web/src/pages/ForensicReportPage.generation.test.jsx`：完成后精确版本选择、
  历史版本不被劫持。

无头浏览器回归（两套）：

1. `node scripts/report_stages_browser.mjs`（合成后端，不启动模型）：
   覆盖两阶段提交、基线、历史版本、慢请求/任务切换、重试/防重复、
   案情输入保护、冻结溯源等。23 个场景。
2. `node scripts/report_layout_browser.mjs`（**真实后端 + 真实报告**）：
   `REPORT_LAYOUT_TASK_ID=<task> REPORT_LAYOUT_REPORT_ID=<report>` 启动 vite
   dev（带真实 /api 代理），在 1440/1024/768/390 四个视口逐章测量：
   - 组件位置漂移：章节卡片的标题/正文/召回表/小结是否都在卡内，
     小结是否在正文之下、召回表是否在小结之前，章节之间是否垂直交错；
   - 文字重叠：报告区内每个可见文本元素两两取矩形交集，再用
     `elementFromPoint` 确认确实有视觉遮挡（排除滚动容器裁剪造成的假重叠）；
   - 横向溢出：右边界是否超出视口（左侧离屏抽屉是响应式预期，不算溢出）；
   - 召回表：表头/单元格是否互相压字、小屏是否按预期进入横向滚动；
   - 内部 ID 泄漏：正文/小结/表内是否出现 `mNNNN`。
   产出 `layout-report.json` 与逐章截图。

**注意**：两套脚本都必须从 `web/` 目录上下文运行 Tailwind（脚本内已
`process.chdir(webRoot)`）。从仓库根目录直接跑会让 `content` glob 匹配不到
`src/`，生成的页面没有工具类 CSS——所有元素退化为满宽块，表现为大量
"文字重叠"假阳性与宽度断言失败。容器内以 root 运行还需要 `--no-sandbox`。

---

## 11. 一句话总结

**产品层**是“首次材料自主研判（无案情）→ 二次案情对照研判（复用 A 的冻结材料，
只加入本次案情）”的显式两阶段；**单次生成内部**是“分析（材料物化 → 分类 →
逐批发现方向 → 仅 B 的逐方向案情对照）→ 整理（主题归纳 → 确定性装箱 →
逐章成文 → 每章小结 → 全案总述 → 确定性拼装）”。两段的硬边界是**已校验方向集**：
分析阶段保证每条事实性引用逐字可回查，整理阶段只允许重组这些方向、
引用由方向反查产生，不得新增证据、不得把仅案情提出的内容升格为材料事实。

**v5 成文形态**（`:v4` 提示词起）：首章 = 全案总述 + 研判范围与方法原文 +
证据召回表 + 表后总结；其余章节各带一句本章小结。总述与小结都是**后置调用**，
输入只有已完成的章节与统计，因此它们只能重述、不能引入新事实；
召回表完全由代码从"章节实际引用了哪些材料"反查生成，模型不参与。

边界之外的已知软点（应如实记录，不应宣称已解决）：

- 整理阶段正文措辞没有逐句事实核验，只有引用/溯源与形态校验；
- 分类是辅助标注，失败可降级为 `unassessed`；
- 两阶段报告不消费已接受 analysis（`bound_analysis` 被剥离），
  因此其 citation manifest 只有 material-level 身份；
- `analysis_mode=None` 的综合报告仍走 v4 的模型自出 citation 链路，
  与两阶段的“引用确定性生成”不是同一契约。
