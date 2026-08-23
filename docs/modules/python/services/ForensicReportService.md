# ForensicReportService（python_service/httpserver/services/forensic_report/ 子包 + final_report_*.py + office_service.py）

> **一句话**：版本化取证报告域——`{FORENSIC_REPORT_DIR}/reports.db` 记录不可变报告版本与"冻结准入→执行→发布"状态机，SnapshotWriter 把任务证据写成带哈希分页/全文索引的快照目录，ReportGenerationExecutor 走 LLM 叙事报告链路（202+轮询），final_report_* 与 office_service 分别负责终版报告的确定性装配/展示和 Office 文档解析。

## 1. 为什么有这个模块

取证结论必须可复现、可审计、不可篡改。系统需要三条互不相同的报告链路：

1. **确定性快照报告（A 链）**：不经 LLM，把 C++ 产出的 `<image>_files.db` 里的结构化文件证据渲染成分页 JSON + manifest，每页带 sha256；
2. **LLM 叙事报告（R2 链）**：从二次调查域冻结的 Report Evidence 信封出发，经"准入（冻结 input_hash）→ 执行（LLM 只见冻结字节）→ 引用校验 → 原子发布"生成中文叙事报告；
3. **终版报告装配（4A-4E/final 链）**：把显式钉扎（pinned）的合法 Section 装配成带 claim/citation 清单与整体哈希的 FinalReport，并派生 markdown/html/print 展示。

这三条链共同的基础设施是：SQLite 版本表（`report_versions` / `report_generation_inputs`）、staging+`os.replace` 原子发布、symlink/越界检查、以及 Readitdown 式的"读路径绝不创建存储"。office_service.py 则是 Office 四种格式 → Markdown 的独立解析器，被抽取器体系（OfficeServiceAdapter）复用。

## 2. 在系统中的位置

- **谁调用它**：ServiceManager 在 C++ 后端就绪后按序装配（service_manager.py:133-141 初始化 ForensicReportService；:193-211 初始化 ReportGenerationExecutor，均为 12s 可选服务预算）；routes/forensic_reports.py（A 链：POST 202 + status/manifest/page/search 轮询，:103-154）；routes/report_generation.py（R2 链：`POST /generate` 202 + 精确 ID 轮询，:95/:136）；routes/report_narrative.py 与 investigation_workbench（经 narrative_reader 读已发布叙事版）；legacy InvestigationService（final_report_* 装配链，见注意事项）。
- **它调用谁**：CppBackendService（任务/数据库路径）；LLMService.chat_completion（R2c 叙事生成）；SQLite（reports.db、任务 `_files.db` 只读、快照内 search.sqlite3）。
- **结构**：`forensic_report/`（service/repository/snapshot_writer/source_resolver/adapters/generation* 五期文件）、平级 `final_report_assembly.py` / `final_report_repository.py` / `final_report_presentation.py`、`office_service.py`。

## 3. 核心数据结构

**（a）版本表（reports.db 的两张表）。** `report_versions` 以 `UNIQUE(scope_type, scope_id, version)` 记录 queued→generating→ready/failed 状态机（repository.py:35-53）；`report_generation_inputs` 是 R2b 冻结准入行（:68-89），靠四个触发器硬约束（:92-169，详见下）。真实 DDL 节选：

```python
# forensic_report/repository.py:35-53（节选）
CREATE TABLE IF NOT EXISTS report_versions (
    report_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    task_ids_json TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    generated_at TEXT,
    manifest_path TEXT,
    offline_bundle_path TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    created_at TEXT NOT NULL,
    report_kind TEXT,
    UNIQUE(scope_type, scope_id, version)
);
```

- `report_id`：全局主键（新报告=新 ID）；`version`：同 scope 内递增（BEGIN IMMEDIATE + MAX(version)+1 分配，:234-258）；
- `scope_type/scope_id`：当前只有 task（CASE 直接 NotImplementedError）；
- `task_ids_json`：多任务快照的证据来源清单；`manifest_path` 指向快照目录内 manifest.json；
- `report_kind`：NULL=确定性快照（历史行语义），`llm_generation`=R2c 叙事版（:57-59 注释）。

```python
# forensic_report/repository.py:68-89（节选）
CREATE TABLE IF NOT EXISTS report_generation_inputs (
    generation_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'admitted',
    requested_by TEXT NOT NULL,
    input_schema_version INTEGER NOT NULL,
    prompt_version TEXT NOT NULL,
    input_envelope_json TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    report_id TEXT,
    produced_version INTEGER,
    model TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT, completed_at TEXT, failed_at TEXT,
    error_code TEXT, error_message TEXT,
    CHECK (scope_type = 'task' AND scope_id = task_id)
);
```

前半（generation_id..created_at）是**冻结区**：`trg_report_generation_input_frozen`（:92-107）禁止 UPDATE、`trg_report_generation_input_no_delete`（:108-112）禁止删除；后半是执行生命周期列。四个触发器：状态机只许 `admitted→running|failed`、`running→completed|failed`（:122-131）；completed 必须带 report_id/produced_version/model/completed_at（:133-142）；failed 不得引用已发布版本（:143-152）；终态行整体不可变（:153-169）。

**（b）快照 manifest（Pydantic 模型，落盘为 manifest.json）。**

```python
# forensic_report/models.py:183-201
class ReportManifest(BaseModel):
    schema_version: str = "1.0"
    report_id: str
    version: int
    scope_type: ScopeType
    scope_id: str
    status: ReportStatus
    title: str
    generated_at: str
    generated_by: str
    generator_version: str
    platforms: list[str]
    task_ids: list[str]
    evidence: list[EvidenceSource]
    directory: list[dict[str, Any]]
    categories: list[CategoryIndex]
    source_fingerprints: dict[str, SourceFingerprint]
    warnings: list[AdapterWarning]
    integrity: dict[str, Any] = Field(default_factory=dict)
```

逐字段：`directory` 是目录树（哪些 category 目录存在）；`categories` 是每类证据的分页索引（CategoryIndex：category_id/page_size/page_count/record_count/页哈希清单）；`source_fingerprints` 按 `evidence_id:名字` 键记录每个源库的指纹（mtime/size，防 TOCTOU）；`warnings` 是适配器级降级记录（probe_failed/category_failed）；`integrity` 预留整体校验信息。读路径 `_ready_manifest_path` 校验目录布局与 manifest 一致后才放行。

## 4. 核心概念与设计

**（a）两套存储，一个根目录。** 装配公式在 service_manager.py:392-415：`root = FORENSIC_REPORT_DIR`（默认 `build/data/reports`，config.py:214-216），`ReportRepository(root / "reports.db")` + `SnapshotWriter(root / "snapshots", FORENSIC_REPORT_GENERATOR_VERSION)` + `build_default_adapters()`。版本分配用 `BEGIN IMMEDIATE + MAX(version)+1 + INSERT` 单事务（:234-258、:511-535），`_assert_mutable`（:264-271）保证 ready/failed 版本不可变。

**（b）A 链：快照写入。** `SnapshotWriter.write`（snapshot_writer.py:169-279）在 `.staging/<report_id>` 里构建，最终目录为 `<scope_type>/<safe_segment(scope_id)>/<report_id>`，`os.replace` 原子发布（:275）；`_ReportClaim`（:95-154）用 POSIX flock（Windows/无 fcntl 时退化为 PID 哨兵文件 + `_process_state` 存活检测，:39-92）做跨进程互斥。每类证据写入 `_write_category`（:281-401）：

```python
payload["sha256"] = hashlib.sha256(_canonical_json(payload)).hexdigest()
relative = category_dir.relative_to(staging) / f"{page_number}.json"
(work_dir / f"{page_number}.json").write_bytes(_canonical_json(payload))
```

页分片先在 `sha256` 字段加入前对规范 JSON 求哈希（docstring :160-163，避免自引用），失败时回滚已并入主索引的搜索文档（:394-398）。manifest 的组装与原子发布（:247-276）：

```python
# forensic_report/snapshot_writer.py:247-275（节选）
manifest = ReportManifest(
    report_id=version.report_id,
    version=version.version,
    scope_type=version.scope_type,
    scope_id=version.scope_id,
    status=ReportStatus.READY,
    title=title,
    generated_at=datetime.now(timezone.utc).isoformat(),
    generated_by="TraceLens",
    generator_version=self.generator_version,
    platforms=sorted(platforms),
    task_ids=version.task_ids,
    evidence=evidence,
    directory=self._build_directory(evidence, indexes),
    categories=indexes,
    source_fingerprints={
        f"{item.evidence_id}:{name}": fingerprint
        for item in evidence
        for name, fingerprint in item.source_fingerprints.items()
    },
    warnings=warnings,
)
(staging / "manifest.json").write_bytes(
    _canonical_json(manifest.model_dump(mode="json"))
)
final_dir.parent.mkdir(parents=True, exist_ok=True)
if final_dir.exists():
    raise FileExistsError(f"immutable report already exists: {final_dir}")
os.replace(staging, final_dir)
```

注意三重 `final_dir.exists()` 防重检查（进入 claim 前后、发布前各一次）：manifest 写完才发布，`os.replace` 对目录是原子改名——读者要么看到旧状态（无目录），要么看到完整快照，绝无半成品。`safe_segment`（ids.py:22-26）把任意 scope_id 变成 `NFKC slug(≤48)-sha256[:12]`，`stable_record_id`（:7-19）保证记录 ID 可复现。平台适配器目前只有 `SqliteTaskReportAdapter`（adapters/sqlite_task.py）：`probe` 检查 files 表存在（:23-37），`categories` 声明 `evidence.files`（page_size=50，:49-59），`iter_records` 以 `mode=ro` URI 只读、按 `_file_fields` 白名单选列、上限 500 条（:63-100、:143-146、:17-22），`_severity` 按 scene_priority 分五档（:173-187）。

**（c）A 链：读路径 confinement。** ForensicReportService 的读方法全部走 `_confined_report_path`/`_reject_symlinks`（service.py:243-266）：resolve 后必须 `relative_to` 报告根，逐组件拒绝符号链接；`_ready_manifest_path`（:268-289）还校验目录布局等于当前布局或 legacy `safe_segment(report_id)` 布局，防止 DB 被篡改后读到根外文件。`get_page_path`（:297-313）只接受 manifest 里登记过的页；`search`（:315-322）打开快照内 `search.sqlite3` 的只读句柄（search_index.py:41-58 校验 schema，`instr` 子串大小写折叠匹配，:126-155）。`resume_unfinished`（service.py:84-90）把重启遗留的 queued/generating 版本判为 `service_restart` 失败——失败原因持久化时是固定脱敏字符串（:176-183 注释）。

**（d）R2 链：冻结准入与执行。** `ReportGenerationAdmissionService.admit`（generation.py:305-346）从任务的 investigation.db 只读读出 Report Evidence 信封（`mode=ro + query_only`，单读事务防 mixed-epoch，:86-106），canonical JSON 一次序列化 + sha256 冻结进 `report_generation_inputs`。`ReportGenerationExecutor._execute`（generation_execution.py:284-457）：

1. `claim_generation` 原子 admitted→running，并发输家直接返回不写失败（repository.py:430-449）；
2. R2C3：重新 canonical 化并 `hmac.compare_digest` 校验持久化 envelope 与 input_hash（:295-318）；schema↔prompt 版本兼容表不匹配即 `unsupported_input_contract`（:319-332）；
3. LLM 只见冻结信封渲染出的 prompt（R2C1/R2C2），`llm_service` 为 None 时以 `llm_unavailable` 持久失败（:340-345）；
4. 结构化输出解析失败→`structured_output_invalid`；`validate_report_citations`（:72-110）强制每条引用落在冻结证据边界、精确 analysis_id/claim_id 内；
5. R2C5：先 `GenerationReportWriter.publish` 原子发布（staging+`os.replace`，布局 `snapshots/task/<safe_segment(task_id)>/<safe_segment(report_id)>`，generation_writer.py:37-66），再在**一个事务**里分配 ready 版本 + 完成 generation（`complete_generation_publication`，repository.py:481-555）——版本永远与 manifest 同时可见。重启恢复把 stale admitted/running 判 `service_restart`，绝不重放 LLM（:216-229）。读侧 `read_narrative_version_strict`（narrative_reader.py:48-99）以 (task_id, report_id) 精确读、跨任务/快照 ID 一律不透明 miss。

**（e）final 链：确定性装配与发布门。** `FinalReportAssembler.assemble`（final_report_assembly.py:309-845）是纯函数：校验 dataset/citation_graph/section_plan 三方自哈希与互相钉扎（:389-434）、每个非空 Section 必须显式绑定 pending 校验的 Candidate + 有效的 Validation（:493-630 十五组哈希对）、重放 render 输入哈希与 claim coverage 清单（:662-763），任一错误整体 invalid；成功则产出带 `final_report_hash` 的 `FinalReportVersion`（canonical 内容排序键 + sha256，:153-190）。`FinalReportRepository`（final_report_repository.py）只存成功版本：`create_assembled` 在 BEGIN IMMEDIATE 里分配版本并复验哈希（:112-188）；`publish`（:252-320）是显式发布门——必须 assembled+valid+哈希一致才写 `final_report_publications`（幂等，:287-289）。展示层 `final_report_presentation.py`：`validate_final_report_for_presentation`（:58-118）复验哈希、五节 SEC-001..005 结构、claim/citation 清单与段落并集一致；markdown 输出全量转义（:121-128），HTML 带 `default-src 'none'` CSP（:17-21）且 screen/print 双模式（:203-246），`presentation_hash` 只对响应字节求值（:249-251）。

**（f）office_service.py。** `parse_file` 按后缀分发到 `_parse_xlsx`（openpyxl 只读+公式值）/`_parse_xls`（xlrd）/`_parse_pptx`（python-pptx，标题占位符类型 1/3 转 `###`）/`_parse_ppt`（外部 `catppt` 子进程，60s 超时），全部经 `asyncio.to_thread` 卸载以免阻塞事件循环（office_service.py:48-58 注释）；进程级单例 `get_office_service`（:237-242）。解析失败返回 `Error parsing ...` 字符串而不是抛异常（调用方需自行检测）。

## 5. 工作流程走读：一次 LLM 叙事报告

`POST /api/reports/generate`（202，routes/report_generation.py:95-122）→ `admit(task_id, requested_by)`（generation.py:305）：get_task → investigation.db 信封装配 → sha256 → 冻结行落库 → `executor.submit(generation_id)`（generation_execution.py:231-258，调度失败也持久 `execution_schedule_failed`）→ 后台 `_execute`：claim → 哈希复验 → prompt → `chat_completion` → 结构化解析 → 引用校验 → `writer.publish`（原子目录）→ `complete_generation_publication`（单事务 ready 版本+completed）→ 前端轮询 `GET .../generations/{id}`（严格只读，:136）直到 completed/failed，再经 narrative/workbench 读 manifest。

## 6. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| ServiceManager | 装配 reports.db / snapshots 根、12s 预算、失败回滚 |
| investigation 域（R1） | report_evidence 行是 R2 准入信封的唯一来源 |
| LLMService | 仅 R2c 执行器调用 chat_completion；LLM 缺失时以 llm_unavailable 持久失败 |
| CppBackendService | 任务元数据与 `_files.db` 路径（SourceResolver 冻结源指纹，source_resolver.py:23-48 含 TOCTOU 检查） |
| routes/forensic_reports、report_generation、report_narrative、investigation_workbench | A 链/R2 链/叙事读的 HTTP 面 |
| extractors（OfficeServiceAdapter） | office_service 被 `extractors/office.py` 包装为 .xlsx/.xls/.pptx/.ppt 的 markitdown 回退 |

## 7. 注意事项与已知问题

- **CASE 作用域未实现**：`start` 对 ScopeType.CASE 直接 `NotImplementedError`（service.py:93-94）。
- **final_report_* 链当前无路由入口**：装配/发布/展示的编排方法全部挂在 legacy `InvestigationService` 类上（investigation_service.py:1378-1600），该类没有任何路由实例化；Workbench 的 `/final-reports` 端点实际读的是 R2 narrative manifest（investigation_workbench.py:160-212）。相关机制仍由单测直接覆盖（见第 8 节）。
- `SnapshotWriter` 的 sqlite_task 适配器有 500 条 fallback 上限（sqlite_task.py:22），大库快照会截断——需要完整证据时应新增适配器而不是调上限。
- `office_service` 的 `_parse_ppt` 依赖系统 `catppt`（catdoc 包），缺失时返回错误文本字符串；PPT 解析无 OCR。
- reports.db 无清理策略：版本只增不减；`.locks/`、`.staging/` 残留由写入方负责清理。
- A 链搜索是 SQLite 子串匹配（非 FTS），超大快照的 LIKE 扫描性能有限。
- 原子性边界：`os.replace` 只保证目录级原子可见；reports.db 的版本行与目录的一致性由"先目录后事务"的顺序（R2C5）或失败回滚（resume_unfinished）弥补，进程在两步之间崩溃会留下"目录在、版本行 queued/generating"的残局，重启由 resume 判 service_restart。

## 8. 如何验证（python_service/tests/unit/）

- A 链：`forensic_report/test_repository.py`（触发器/版本分配/不可变）、`test_snapshot_writer.py`（staging/原子发布/页哈希）、`test_service.py`（生命周期/重启恢复/confinement）、`test_source_resolver.py`、`test_sqlite_task_adapter.py`、`test_ids.py`、`test_search_index.py`、`test_routes.py`（202+轮询契约）。
- R2 链：`forensic_report/test_generation_admission.py`、`test_generation_execution.py`（R2C1-R2C7）、`test_report_generation_routes.py`、`test_report_narrative_routes.py`、`test_analysis_adapter.py`。
- final 链：`test_final_report_assembly.py`、`test_final_report_repository.py`、`test_final_report_presentation.py`；配套 `test_report_dataset.py`、`test_citation_validation.py`、`test_section_planning.py`、`test_report_rendering.py` 等。
- 手工链路：`POST /api/reports`（202）→ `GET /api/reports/{id}/status` 至 ready → `GET .../manifest`、`.../categories/evidence.files/pages/1`、`.../search?q=`；`sqlite3 build/data/reports/reports.db "SELECT report_id,version,status,report_kind FROM report_versions"`。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
