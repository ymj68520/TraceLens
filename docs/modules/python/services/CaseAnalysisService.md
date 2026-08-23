# CaseAnalysisService（python_service/httpserver/services/case_analysis/ 子包 + case_file_filter.py + case_persistence.py + oss_filter_service.py + oss_analysis_service.py）

> **一句话**：案情驱动的分析编排层——以案件描述为输入，把"文件筛选（deterministic|llm 双模式，FILE_FILTER_MODE/FILTER_MAX_FILES）→ 提取 → 并行文件/事件簇描述 → 知识图谱摄取 → 综合报告"串成单镜像/跨镜像/增量三条流水线，并把筛选结果与报告持久回任务 `_files.db` 的 case_analysis 表。

## 1. 为什么有这个模块

C++ 流水线产出的是"全部文件"的清单，而分析员手里只有一句案情描述。系统需要一个地方回答三个问题：

1. **哪些文件值得看**——历史上用 LLM 按案情挑文件（不可复现、解析脆弱），现在默认改走 deterministic 模式：`files.db` 本身就是 C++ FileFilter 按场景 profile 过滤后的产物，直接全选即可复现；
2. **挑出来的文件怎么变成结论**——提取到本地、LLM 生成描述、事件簇并行分析、摄入 Graphiti、最后合成五章 Markdown 报告；
3. **多镜像/增量怎么办**——同一案件关联多个任务时聚合去重筛选、复用已分析任务、案例级图谱与报告。

FileFilter 的双模式开关 `FILE_FILTER_MODE=deterministic|llm` 与上限 `FILTER_MAX_FILES`（0=不限）都来自 Settings（config.py:280-292）。OSS 侧（`_oss.db` 的云存储对象）有一套同构但独立的 LLM 筛选服务。

## 2. 在系统中的位置

- **谁调用它**：routes/case_analysis_endpoints（`_helpers.get_case_analysis_service` 把服务懒缓存到 ServiceManager 上，注入 llm/cpp/graphiti，_helpers.py:20-40；`POST /api/llm/case-analysis` 起后台作业 + `GET /case-analysis/{job_id}` 轮询内存作业表 `_analysis_jobs`）；routes/oss_analysis.py（OSSFilterService/OSSAnalysisService 同样懒缓存，:130-153）；routes/multi_analysis.py（跨镜像入口）。
- **它调用谁**：LLMService（analyze）；CppBackendService（get_task、TOON 导出、文件提取）；GraphitiService（ingest_task_episodes / ingest_case_data）；windows_artifacts 服务（Windows 痕迹管线，经 `_windows` mixin）。
- **它被谁依赖**：routes/intelligence_report.py 只读它的 case_report 产物；forensic_report 的 AnalysisChaptersAdapter 读取 case_analysis 行作为章节来源。
- **链路**：前端"案情分析"页 → `/api/llm/case-analysis` → task_store 门卫 → 本服务后台作业 → `_files.db.case_analysis` + Graphiti 图谱 + case_report。

## 3. 核心数据结构

**（a）持久化表与状态枚举。** 筛选与报告都写在任务 `_files.db` 的 `case_analysis` 表（db_utils.py:45-62 建表）：

```python
# case_analysis/db_utils.py:45-62（节选）
def ensure_case_analysis_table(db_path: str):
    """Create case_analysis table if it doesn't exist."""
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS case_analysis (
                    task_id TEXT PRIMARY KEY,
                    case_description TEXT,
                    filtered_files TEXT,
                    case_report TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                )
            """)
            conn.commit()
```

- `task_id` 主键：一任务一份案情分析（重跑整体覆盖语义，靠 INSERT OR REPLACE）；
- `filtered_files`：JSON 数组字符串（选中路径列表）；`case_report`：五章 Markdown 全文；
- 报告写入用 `COALESCE((SELECT filtered_files ...), '[]')` 子查询保住已有筛选清单（db_utils.py:81-98），不会因重发报告清空筛选。

增量计划的状态机（db_utils.py:19-24）：

```python
class TaskAnalysisState(Enum):
    """任务分析状态枚举"""
    PENDING = "pending"           # 待分析
    ANALYZED = "analyzed"         # 已分析
    NEEDS_UPDATE = "needs_update" # 需要更新
    FAILED = "failed"             # 分析失败
```

四态支撑 `CaseAggregationManager.plan_incremental_analysis` 的 analyze/skip 决策（NEEDS_UPDATE 的来源任务变更后回退）。

## 4. 核心接口清单

| 接口（真实签名） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `run_full_analysis(task_id, files_db_path, case_description, max_filter_files=200, run_filtering=True, report_only=False, progress_callback=None) -> Dict` | 单镜像全流水线 | `/api/llm/case-analysis` 后台作业 | 步骤错误记入 result["steps"]，报告仍尝试生成 |
| `run_multi_image_analysis(case_id, task_ids, files_db_paths, ...) -> Dict` | 跨镜像：聚合筛选→分发→逐任务复用→案例级图谱+报告 | routes/multi_analysis | 同上 |
| `run_smart_case_analysis(case_id, case_description, ...) -> Dict` | 建案→扫描关联→增量分析 | smart 入口 | 同上 |
| `run_incremental_analysis(case_id, plan, ...) -> Dict` | 只分析 plan 出的新任务并复用旧描述 | smart 流水线 | 同上 |
| `FileFilter.filter_files_by_case(files_db_path, case_description, max_files=200, batch_size=50, use_streaming=True, task_id=None) -> Dict` | 双模式筛选入口 | run_full_analysis 第 1 步 | deterministic 零 LLM；llm 模式异常回退 legacy |
| `MultiImageFilter.filter_files_multi(...)` | 跨镜像聚合去重筛选 | run_multi 第 1 步 | 同上 |
| `ReportGenerator.generate_final_report(...)` | 聚合 is_relevant 描述成报告 | 流水线末步 | 图谱缺席落 REPORT_FALLBACK_TEMPLATE |
| `CaseAggregationManager.plan_incremental_analysis / execute_incremental_analysis(analyze_func=...)` | 增量计划/执行 | smart 流水线 | 计划错误抛 |
| `OSSFilterService.filter_oss_objects(...)` / `OSSAnalysisService.analyze_oss_objects` | OSS 筛选 / 分析（stub） | routes/oss_analysis | 见 6(f) |

## 5. 核心概念与设计

**（a）Mixin 组装 + 依赖注入。** `CaseAnalysisService` 是三个 mixin 的多继承壳（case_analysis_service.py:39-65）：`_core`（注入与委托）、`_windows`（Windows 痕迹）、`_pipelines`（三条流水线）。服务由路由层构造，`set_llm_service/set_cpp_backend/set_graphiti_service` 逐个注入；`_initialize_modules` 只有在 **LLM 与 C++ 都就绪**时才实例化 FileFilter/MultiImageFilter/FileAnalyzer/ReportGenerator/ClusterAnalyzer/CaseAggregationManager（_core.py:58-73），Graphiti 缺席只是降级（图谱步骤记 skipped）。

**（b）主流水线 `run_full_analysis`（_pipelines.py:33-354）。** 三种模式由 `run_filtering`/`report_only` 与库状态决定：

```python
# case_analysis_parts/_pipelines.py:78-88（节选）
has_existing_filtered = False
if not run_filtering:
    from ..db_utils import get_filtered_files_from_db
    existing_filtered = get_filtered_files_from_db(files_db_path, task_id)
    if not existing_filtered:
        logger.info(f"[CASE_ANALYSIS] Task {task_id}: No filtered files found in database, auto-enabling filtering")
        run_filtering = True
    else:
        logger.info(f"[CASE_ANALYSIS] Task {task_id}: Found {len(existing_filtered)} existing filtered files, skipping filter step")
        filtered_files = existing_filtered
        has_existing_filtered = True
```

report-only 直接跳到报告；`run_filtering=False` 时先查库里有无已筛选文件，没有则**自动开启筛选**（防"空跑"）；正常路径是 filter → extract → 并行 describe+cluster → KG 摄取 → report。文件描述与事件簇分析是 `asyncio.create_task` 并行（:153-167），KG 失败非致命（:194-221）。`run_multi_image_analysis`（:356-502）先做跨镜像筛选并把结果**按库分发持久**，再对每个任务以 `run_filtering=False` 复用主流水线，最后案例级图谱 + 跨镜像报告。`run_smart_case_analysis`（:504-609）建案→扫描关联→增量分析；`run_incremental_analysis`（:611-799）只分析 plan 出的新任务并复用旧描述。

**（c）FileFilter 双模式（file_filter.py）。** 入口 `filter_files_by_case`（:53-107）按 `settings.file_filter_mode` 分发；非 `llm` 一律走 `_filter_files_deterministic`（:109-157）：

```python
# case_analysis/file_filter.py:122-148（节选）
records = self._get_file_list_from_db(files_db_path)
paths = sorted({r.get("path", "") for r in records if r.get("path")})
total_files = len(paths)

cap = int(getattr(self.settings, "filter_max_files", 0) or 0)
if cap > 0:
    selected = paths[:cap]
    logger.info(
        f"[FILE_FILTER] Deterministic cap applied: {len(selected)}/{total_files} "
        f"(filter_max_files={cap})"
    )
else:
    selected = paths

if max_files and max_files > 0:
    logger.info(
        f"[FILE_FILTER] max_files={max_files} ignored in deterministic mode; "
        f"using settings.filter_max_files={cap}"
    )

# Mirror the LLM path's task_id extraction so callers that omit task_id
# still persist under the real UUID (avoids a silent data-placement
# divergence where the deterministic path would write to "_latest").
if not task_id:
    task_match = re.search(r'tasks/([a-f0-9-]+)/', files_db_path)
    task_id = task_match.group(1) if task_match else "_latest"
self._persist_filtered_files(files_db_path, task_id, selected)
```

确定性模式零 LLM、排序去重后按 `FILTER_MAX_FILES` 截断（排序保证可复现），显式忽略调用方 `max_files`（:136-140 的日志），并镜像 LLM 路径的 task_id 提取逻辑持久化（:143-148，避免静默写到 `_latest`）。LLM 模式是流式 TOON 批处理（:177-336）：C++ `get_files_toon_stream` 导出 schema+行，按 batch_size 分批喂 LLM，解析走"LLMResponseParser → FilterResultValidator.validate_and_repair → FileMatcher.match_files"三段增强管线（:359-429），零命中或校验失败回退 legacy 解析器；顶层异常整体回退 `_filter_files_by_case_legacy`（:330-336）。`enable_concurrent_lock` 打开时经 `FilterLockManager.filter_with_lock` 串行化同任务并发筛选（:90-99）。`MultiImageFilter`（multi_image_filter.py）继承 FileFilter：deterministic 路径聚合+跨镜像去重后统一 cap（:110-168）；LLM 路径给路径打 `[IMG{n}]` 标签去重（:80-95），`_distribute_and_persist`（:263-296）把选中 tagged 路径映射回各库分别持久。

**（d）持久化：db_utils.py 而非 CasePersistence。** 筛选与报告都写在任务 `_files.db` 的 `case_analysis` 表（上文 DDL）。`persist_filtered_files`（db_utils.py:64-78）先于后续步骤落库，使失败后可恢复；`get_case_db_path`（:375）给跨镜像报告解析案例级库。**`case_persistence.py` 与 `case_file_filter.py` 是两份几乎逐行相同的 `CasePersistence` 类，当前都没有任何 import 方**（见第 6 节）。

**（e）报告与聚合。** `ReportGenerator.generate_final_report`（report_generator.py:46）聚合库里 is_relevant 描述（DB 聚合优先于传入描述），图谱可用时用 Graphiti 检索增强章节、否则落 `REPORT_FALLBACK_TEMPLATE`；跨镜像报告聚合多个 `_files.db` 并用案例级图。`CaseAggregationManager`（case_aggregation_manager.py:42）负责扫描完成任务、`plan_incremental_analysis`（:421）决定 analyze/skip 集合、`execute_incremental_analysis`（:489）以注入的 analyze_func 执行。

**（f）OSS 侧。** `OSSFilterService.filter_oss_objects`（oss_filter_service.py:46-80）读 `_oss.db` 的 `oss_objects` 表（:236-269），自己拼 TOON schema（:271-298），LLM 批筛后解析：三级匹配（精确→忽略大小写→子串，:434-459）+ 失败时"把每个对象 key 当词在响应全文里搜"的激进回退（:468-479），结果持久经 mixin 的 `_persist_filtered_objects`。`OSSAnalysisService`（oss_analysis_service.py）是**显式 stub**：`analyze_oss_objects` 返回未实现提示（:52-58），`start_analysis` 只生成 job_id 维持 API 契约（:60-83）。

## 6. 注意事项与已知问题

- **两份死代码持久化类**：`case_persistence.py` 与 `case_file_filter.py` 内容近乎相同（含同样的分类表扫描 `get_file_list_from_db`），均无 importer；真实持久化在 `case_analysis/db_utils.py`。改 case_analysis 表结构时别改错文件。
- **作业状态只在内存**：`_analysis_jobs` 进程重启即失，轮询端点对旧 job_id 返回 not found；筛选清单与报告本身在 DB 里可恢复。
- deterministic 模式忽略 `max_files` 参数是有意行为（以 `FILTER_MAX_FILES` 为准），调用方传大值不会生效。
- LLM 筛选解析的最终防线是 legacy 文本匹配，可能把"提及而非选择"的文件也算进来——这是可用性优先的取舍，审计筛选结果请以持久化的 filtered_files 为准。
- OSSAnalysisService 是 stub：`POST /api/oss/analyze` 会成功返回 job_id 但没有任何实际分析；OSS 筛选的"子串匹配"策略比文件侧更激进。
- `run_incremental_analysis` 第 4 步聚合描述时构造的是 `[{"task_id":..., "has_analysis": True}] * stats["analyzed_files"]` 占位字典（_pipelines.py:776-778），报告实际内容靠 ReportGenerator 回库聚合，不要误以为这里传了真描述。
- 并发语义：同一任务的并发筛选由 FilterLockManager（可开关）串行化；未开锁时两次并发 run_full_analysis 都会写 case_analysis（INSERT OR REPLACE，后写覆盖），筛选清单可能互不一致——重跑前先确认无在途作业。

## 7. 如何验证（python_service/tests/unit/）

- `test_deterministic_filter.py`（deterministic 模式/截断/持久化）、`test_multi_deterministic_filter.py`（跨镜像聚合分发）、`test_filter_validator.py`、`test_file_matcher.py`、`test_llm_response_parser.py`、`test_filter_config.py`（LLMFilterConfig）、`test_cluster_analyzer.py`、`test_case_analysis_routes.py`（作业 202/轮询契约与 task_store 门卫）。
- 手工链路：`FILE_FILTER_MODE=deterministic` 下 `POST /api/llm/case-analysis` → 轮询 job → `GET /api/llm/case-report/{task_id}`；`sqlite3 <task>/files.db "SELECT task_id, json_array_length(filtered_files), length(case_report) FROM case_analysis"`。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
