# TaskAnalysisRuns 路由（python_service/httpserver/routes/event_cluster_analysis.py + file_analysis.py，前缀 /api/llm）

> **一句话**：单任务两级 LLM 分析的"估算→后台运行→作业查询→记录真源"四件套——事件簇分析（对 `_events.db` 的簇级研判，受 MVP 开关门控）与文件分析（对 `_files.db` 的逐文件描述，含 C++ 流水线回写真源的 record 端点），两者互为镜像：同款模块级内存作业注册表、同款 append-only 记录表。

## 1. 这组路由承担什么职责（为什么存在）

`/api/llm` 前缀下原有的批量/事件簇端点是"案件维度"的；这两个文件给**单个任务**提供了案件流之外的独立入口（file_analysis.py:1-7 docstring："Mirrors the event-cluster-analysis endpoint family: an estimate (read-only budget preview), a background run (job convention of the newest route modules — a module-level registry), run status, and the analysis-record version chain"）。四个动作各有含义：

- **estimate** 是纯只读的预算预演——"这次 run 会花多少 LLM 调用/字符"，让前端在按下按钮前能展示成本；
- **run** 是后台作业（`asyncio.create_task` + 模块级 `_run_jobs` 字典，单进程、尽力而为状态）；
- **run/{job_id}** 轮询作业进度；
- **记录查询端点**（`/event-cluster-analyses`、`/file-analyses`）读**append-only 记录表**——分析结果的真源（truth source），作业字典只是进度，重启即丢，记录表才跨重启存在。

挂载：event_cluster_analysis 由 main.py:309 注册（`/api/llm`）；file_analysis 由 llm.py:37 include 进同一前缀（main.py:307）。

## 2. 典型调用方（前端哪个页面/组件）

- `/analysis-center` 页：事件簇的估算/运行/轮询（`web/src/services/llmService.js` 的 run 系列）；`GET /event-cluster-analyses` 是研判中心 Phase D 页数据源（event_cluster_analysis.py:193 docstring）。
- `/files`、`/case-intelligence`：文件分析记录链（`/file-analyses` 的 version chain）与 C++ 回写的 record 端点的间接消费者。
- **C++ 流水线**是 `/file-analysis/record` 的直接调用方（file_analysis.py:187-201 类 docstring：SPEC E——C++ 此前手工同步 display-cache 写、跳过 append-only `file_analyses` 真源行；现在逐条 POST 到这里，让经过测试的 Python 三写路径保持唯一写者）。

## 3. 核心数据结构

**内存作业条目**（两文件同构）：`_run_jobs[job_id] = {job_id, task_id, status: running|completed|failed, processed, total, detail/summary/error, started_at, finished_at}`（event_cluster_analysis.py:118-127、file_analysis.py:111 起）。单进程尽力而为：进程重启清零，作业不恢复。

**事件簇记录坐标**（`/event-cluster-analyses` 的过滤维度，:181-191）：`(task_id, bucket_epoch_offset, bucket_seconds, bucket_index, event_type, parent_directory)` 唯一定位一簇；`latest_only=True`（默认）用 `id IN (SELECT MAX(id) ... GROUP BY 六坐标)` 取每坐标最新版本（:215-221）——记录是版本链，坐标相同的新分析追加而非覆盖。`include_file_summaries` 走**批量**附件查询（:249-260，注释写明单记录版在 200 行页面上是 >40s 的 N+1）。

**文件分析记录**（`/file-analyses`，file_analysis.py:165-183）：`list_analyses(files_db, task_id, file_path, limit)` 追加只读，`file_path` 可选（单文件的版本链）；写入只能走 record 端点的三写路径。record 请求体（FileAnalysisRecordRequest，:187-201）：task_id/file_path/description/summary/keywords（逗号分隔）/model_used/extraction_method（markitdown/raw_text/vision/metadata_only）。

## 4. 端点语义分组（散文）

**事件簇（event_cluster_analysis.py）**：
- `POST /event-cluster-analysis/estimate`（:55-78）：纯 SQL 阶梯扫描（`estimate_bucket_ladder` + `choose_bucket`，无 LLM 调用）——返回各候选窗口的簇数估计与推荐 `bucket_seconds`，预算基准是 `settings.llm_max_event_clusters`（:65-70）。
- `POST /event-cluster-analysis/run`（:81-168）：**MVP 门控**——`settings.event_llm_analysis_enabled` 为假时固定 503（"Event LLM analysis is disabled in this build (MVP)"，:90-94）；`bucket_seconds` 显式给定时校验 1..TIMELINE_MAX_BUCKET_SECONDS（:95-101，常量来自 services/investigation_evidence.py）。任务级 `case_description` 取自 C++ 任务记录（:108-109）；ClusterAnalyzer 拿 llm_service 与可选 graphiti_service（:111-115）。worker 协程保证作业必有终态（except 分支置 failed，:151-158），完成 detail 是中文摘要（"N 个簇新分析，M 个已最新，K 个失败"，:139-141），失败簇单列 `failures`。
- `GET /event-cluster-analysis/run/{job_id}`（:171-176）；`GET /event-cluster-analyses`（:179-268，真源查询，旧任务缺表按空列表返回而不是 500——:226-238 的注释明确这是为了不打断页面加载）。

**文件分析（file_analysis.py）**：
- `POST /file-analysis/estimate`（:47-84）：`pending` = 过滤文件集中无分析记录的数量（:66-71）——"run 将执行的准确工作量"；`estimated_llm_calls = pending`，`estimated_chars = pending × max(file_analysis_max_content, 0)`（默认 10000，:80-84）。
- `POST /file-analysis/run`（:87-155）：目标 = 显式 `file_paths` 或任务过滤文件集（:98-100）；空集 400"先跑 case 过滤或传 file_paths"（:106-108）；有真值记录的文件按流水线 §4 语义跳过（:92-93 docstring）。
- `GET /file-analysis/run/{job_id}`（:157-161）；`GET /file-analyses`（:165-183）。
- `POST /file-analysis/record`（:205-240）：C++ 回写入口——`files_db` 只从任务记录解析（"D2b trust source"，:216-217 docstring：调用方无法把写重定向到任意数据库）；LLM 服务缺失 503（:219）；三写持久化失败 500（:232-236）；成功后同轮生成文件级调查事件（:238-240 注释：工作台左栏无需单独刷新）。

## 5. 数据流（读什么库、写什么）

**读**：任务记录（C++ `get_task`）→ `output_events_db`（事件簇）或 `output_files_db`（文件分析）——库路径永远来自服务端任务记录，客户端只给 task_id（`_resolve_task_files`，file_analysis.py:37-44；`_resolve_events_db`，event_cluster_analysis.py:47-53；无库即 400 "No files/events database for this task"）。

**写**：事件簇 run 写 `_events.db` 的 `event_cluster_analyses` 表（经 ClusterAnalyzer）；文件分析 run 与 record 都写 `_files.db`（`llm_service.persist_to_files_db` 的原子三写——display 缓存列 + 真源行 + 事件）。记录表是 append-only：坐标相同的重复分析产生新版本行，`latest_only` 过滤决定读者看到哪版。

作业状态**只存在于内存**（两文件的模块级 `_run_jobs`），与记录表分离是有意的：作业是"这次运行进行到哪"，记录是"历史上得出过什么结论"。

## 6. 边界与已知状态（错误码/降级）

- **503 门控**：事件簇 run 的 MVP 开关（event_cluster_analysis.py:90-94）；文件分析 record 的 LLM 服务缺失（file_analysis.py:219）。估算端点不受门控（纯 SQL，任何时候可预算）。
- **404**：作业 id 不存在（两文件的 get_status）——进程重启后旧 job_id 一律 404，前端必须回到记录查询端点重建视图。
- **400**：任务无对应库（400 不 404——任务存在但没产物）；空候选集；record 的持久化失败是 500（真源写入失败视为服务器错误，:232-236）。
- **事件簇缺表退化**：老任务无 `event_cluster_analyses` 表 → 空页 200（:226-238），语义"没有分析过"而不是"出错"。
- 内存作业注册表无清理线程——作业条目常驻直到进程重启（条目小，属可接受的运维面）。

## 7. 如何验证

- 前端契约：`web/src/services/llmService.js`（run/轮询）、`clusterAnalysisMapper.js(.test.js)`（事件簇记录→UI 模型）；`pages/AnalysisCenter` 系列。
- 服务层：`python_service/tests/unit/` 下 case_analysis（cluster_analyzer/file_schema/db_utils）测试。
- 活体验证：对同一任务先 estimate 后 run，`estimated_llm_calls` 应与 run 结束后的新增记录数同量级；用 C++ 流水线跑一个任务，`GET /file-analyses` 应能看到每文件的追加版本（验证 record 端点成为唯一写者）。

相关阅读：[CaseAnalysis.md](CaseAnalysis.md)（同前缀的案件维度分析）、[LLM.md](LLM.md)（llm_endpoints 的旧 analyze-event-cluster 端点）、services 侧 CaseAnalysisService.md（ClusterAnalyzer 与三写持久化的实现）。

## 8. 二轮深化 A：estimate/run 分离的预算纪律

两个 estimate 端点体现了同一条纪律：**成本必须可预演**。事件簇版（event_cluster_analysis.py:55-78）返回整个阶梯（每个候选 bucket_seconds 的簇数估计），`choose_bucket` 按 `llm_max_event_clusters` 预算推荐窗口——"窗口选多大"本质是"这一轮想花多少 LLM 调用"，决策依据由 estimate 给出而非拍脑袋。文件分析版（file_analysis.py:74-84）更进一步：`estimated_llm_calls` 恒等于 `pending`（每文件恰好一次调用），`estimated_chars` 用 `file_analysis_max_content` 估算——因为目标集是确定性的（过滤文件集减去已有真源记录），估算不是猜而是**计划**。两个 run 都不设服务端预算上限（预算约束在前端按 estimate 决定是否发起），这是"analyst-in-the-loop"的成本模型：服务端保证忠实执行，成本决策留给发起人。

## 9. 二轮深化 B：为什么 record 端点存在（SPEC E 的单一写者原则）

file_analysis.py:187-201 的类 docstring 记录了这次收敛：C++ 流水线此前"maintained a hand-synced copy of the display-cache writes and skipped the append-only `file_analyses` truth row entirely"——即同一份分析结果在 C++ 与 Python 各写一份缓存，而真源行根本没写。后果是两份缓存可能漂移、且无版本链可查。修复方向不是让 C++ 写对三写，而是让 C++ **只发 HTTP**（POST /file-analysis/record），三写的全部细节收敛回经过测试的 Python 路径（:218-219："the tested Python three-write path stays the single writer"）。配套的信任设计：`files_db_path` 从任务记录解析（D2b），请求体里没有库路径字段——HTTP 调用方表达"哪个文件的什么结论"，不表达"写到哪个文件"。这是多服务系统里典型的"能力收敛"模式：谁拥有存储语义，谁就独占写路径。

**最后更新**: 2026-11-10（新建：任务级事件簇/文件分析运行路由文档）
