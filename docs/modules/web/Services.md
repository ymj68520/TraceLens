# 服务层（Services）

## 为什么要有这篇文档

`web/src/services/` 下有 24 个文件、200 余个导出（含默认导出），它们是前端与三个后端之间
**唯一的边界**。页面从不直接 `axios.get`，全部经由 service。本文给出每个 service 的
"方法 ↔ 后端端点 ↔ 页面消费者"三向映射，排查接口问题时可从任一端反查另外两端。
所有客户端实例（`api` / `pythonApi` / `csApi`）见 Overview.md；service 层的统一约定是：
**函数返回的是拦截器解包后的 `response.data`**。

## 代码位置

`web/src/services/`：api.js、taskService、forensicsService、extractionService、
systemService、searchService、memoryService、ossService、llmService、caseAnalysisService、
caseGroupService、graphitiService、investigationService、reportService、reportDataSource、
reportGenerationService、intelligenceReportService、associationService、wechatService、
officeService、filterService、csAuthService/csClientService/csTaskService。

## 核心概念

- **客户端归属即后端归属**：`import api from './api'` = C++ :8080（同源代理）；
  `import { pythonApi }` = Python :8090；`import { csApi }` = 分布式 :8091。
  读一个 service 文件的第一行 import 就知道它打到谁。
- **轮询内置在 service 里**：`pollExtractionStatus`、`pollBatchStatus`、
  `pollMultiAnalysis`、`pollCaseAnalysis`、`pollAnalysisJob`（investigation）都以
  Promise + `setTimeout` 递归实现，页面只拿 `onProgress` 回调。
- **轮询身份必须是 exact id**：R 系列冻结契约（investigationService、
  reportGenerationService）反复强调"绝不回退到 latest"，见下文走读。

## 走读

### taskService.js — C++ 任务 CRUD（`api`）

| 方法 | 端点 | 响应字段要点（后端 handler） | 消费者 |
|---|---|---|---|
| `fetchTasks` / `listTasks` | GET `/api/tasks` | `{tasks:[task 对象], pagination:{total,limit,offset,has_more}, filters}`；task 对象见下注 | taskSlice（fetchTasks/fetchTasksSilent）、TaskSelector |
| `fetchTaskById` | GET `/api/tasks/{id}` | 单个 task 对象（`task_to_json` 全字段） | （备用） |
| `getTaskProgress` | GET `/api/tasks/{id}/progress` | `{task_id, status, progress:{current_phase, phase_percentage, overall_percentage, phase_description}}` | taskSlice.fetchTaskProgress → useTaskPolling |
| `getTaskResults` | GET `/api/tasks/{id}/results` | 未完成 **202** `{status, message:"Task not completed yet", task_id}`；完成 200 `{task_id, status:"completed", results, output_files_db}` + 可选 `llm_results/output_descriptions_db` | AnalysisCenter（llm_results.descriptions） |
| `cancelTask(taskId, reason)` | DELETE `/api/tasks/{id}`（body 带 reason） | `{success:true, task_id, message:"Task deleted successfully"}`；不存在 404 | taskSlice.cancelTask → Tasks 页 |
| `deleteTask` | DELETE `/api/tasks/{id}` | 同上（同一 handler，区别只在 body） | taskSlice.deleteTask → Tasks/Cases 页 |
| `getTaskStatistics` | GET `/api/tasks/statistics` | `TaskManager::get_task_statistics()` 原始 JSON（总数、按状态/优先级分布） | taskSlice → Dashboard |
| `batchCreateTasks` 等 3 个 | POST `/api/tasks/{batch-create,batch-status,batch-cancel}` | create: 201 `{success, task_ids, count}`；status: `{statuses:[{task_id,status,progress}\|{task_id,error}], count}`；cancel: `{success, cancelled_task_ids, cancelled_count}` | （暂无页面） |
| `getTaskAuditLog` / `updateTaskPriority` / `cleanupOldTasks` | GET/PUT/POST | audit: `{task_id, logs:[{timestamp(ms),action,details,user_id}], count}`；priority: `{success, task_id, new_priority}`（**只回显不生效**，源码注释自认）；cleanup: `{success, removed_count, message}` | （暂无页面） |
| `createTask` | POST `/api/tasks` | **201** `{id, status:"created", priority, scenarios, llm_analyze, llm_mode, file_carving, filter_profile, android_source, dependencies_count}`；非法 400 文本 `Invalid request: <原因>` | taskSlice.createTask、caseSlice.createCaseWithTasks |

> task 对象字段（`TaskHelpers::task_to_json`）：`id, image_path, status, priority, message,
> output_files_db, output_raw_db, output_events_db, progress{current_phase, phase_percentage,
> overall_percentage, phase_description}, timestamps{created, started, completed,
> execution_time_seconds}(Unix 毫秒), scenarios, scenario_databases, android_analyze,
> android_source, llm_analyze, llm_mode, file_carving, filter_profile, case_description,
> xfs_mode, db_output_dir, extraction_directory, cancellation_requested, dependencies,
> dependents_count, metadata, error_details`。前端 Files 页 reanalyze 用的
> `output_files_db`（别名 `output_files_db_path`）、Cases 页建案用的 `status` 都在其中。

注意 `cancelTask` 与 `deleteTask` 是**同一个 DELETE 端点**，区别仅在于是否带
`{data:{reason}}`（`taskService.js:23-29`）。

### forensicsService.js — C++ 取证数据 + 一个 Python 混入（`api` + `pythonApi`）

Timeline 族：`getComprehensiveTimeline` / `getTimelineDetails` / `getTimelineDistribution` /
`getTimelineDetails` / `getFileActivity` / `getSuspiciousPatterns` / `getUserActivity` /
`getAnalyzedEventClusters` → `/api/forensics/timeline/*`，消费者 Timeline、AnalysisCenter。
Files 族：`getLargestFiles` / `getRecentFiles` / `getSuspiciousFiles` / `getDuplicateFiles` /
`getExtensionAnalysis` → `/api/forensics/files/*`，消费者 Files。
Android/MIUI 族（10 个 `getMiui*` + `getAndroid*`）→ `/api/forensics/android/*`，消费者
Android 页。Statistics 族（4 个）→ `/api/forensics/statistics/*`，消费者 Statistics。

唯一的 Python 混入是事件簇 AI 研判（`forensicsService.js:33-67`）：

```js
export const analyzeEventCluster = async (taskId, cluster) => {
  ...
  const groupDescriptor = getClusterDescriptor(cluster);
  return await pythonApi.post('/api/llm/analyze-event-cluster', {
    task_id: taskId,
    group_descriptor: groupDescriptor,
  });
};
```

注释（`forensicsService.js:10-13`）说明动机："彻底切换到 Python 服务执行，不再使用
C++ 侧的 LLM 逻辑"。前端先用 `getClusterDescriptor`（14-31 行）校验 `bucket_index/
bucket_seconds/event_type` 三个整数/字符串字段，非法直接抛错，不发请求。
`reanalyzeEventCluster` 同端点，多带一句中文 prompt（62-66 行）。

### extractionService.js — C++ 异步文件提取（`api`）

| 方法 | 端点 | 消费者 |
|---|---|---|
| `startExtraction` | POST `/api/forensics/extract` | Files 页、useFileExtraction |
| `getExtractionStatus` | GET `/api/forensics/extract/status?job_id=` | 同上 |
| `pollExtractionStatus` | （组合轮询） | 同上 |

`pollExtractionStatus`（`extractionService.js:50-111`）是全仓库最防御性的轮询：支持
`AbortSignal`、15 分钟绝对 deadline、`isCurrent(taskId, jobId)` 身份回调、以及
`status.task_id !== expectedTaskId` 的跨任务污染检查——任一失败即抛错停止。

### systemService / searchService / memoryService / ossService / filterService — C++ 其余

- `systemService`：`/api/system/{health,info,databases,database-schema/*}`、
  `/api/docs/*`、`/api/export/{taskId}`、`/api/health/{dependencies,live}`、
  `exportToon`（POST `/api/forensics/export/toon`）→ Dashboard/Terminal/Settings；
  `getPythonHealth`（pythonApi `/health`）、`getRedisStatus`（pythonApi
  `/api/system/redis/status`）→ Dashboard。
- `searchService`：`searchFulltext`（GET `/api/search/fulltext?q=&index=`）、
  `createSearchIndex`（POST `/api/search/index`）→ Search 页。
- `memoryService`：5 个 `getMemory*` → `/api/forensics/memory/*` → Memory 页。
- `ossService`：见 Pages.md——6 个读端点后端未实现，会 404；`startAnalysis` /
  `getAnalysisStatus` / `pollAnalysisStatus` 可用。
- `filterService`：`/api/filter/profiles` CRUD + `/api/filter/apply` → filterSlice →
  FileFilters / FilterProfileSelector 组件。

### llmService.js — Python LLM（`pythonApi`）

| 方法 | 端点 | 响应字段要点（后端 handler） | 消费者 |
|---|---|---|---|
| `analyzeContent` | POST `/api/llm/analyze` | `AnalyzeRequest`：`task_id?/file_path?/content?/model_type(text\|vision)/prompt?/max_tokens(1-8192)/temperature(0-2)/files_db_path?` | Files、useFileLLMAnalysis |
| `analyzeFile`（multipart） | POST `/api/llm/analyze/file?model_type=` | 上传文件分析 | （暂无页面） |
| `analyzeDLL` | POST `/api/llm/analyze/dll` | body `{file_path, files_db_path, prompt?}`（service 层组装） | Files 页 |
| `startBatchAnalysis(taskId, options)` | POST `/api/llm/batch` | 后台 job；Files 页消费 `result.job_id` | Files、useFileLLMAnalysis |
| `getBatchStatus` / `pollBatchStatus` | GET `/api/llm/batch/{jobId}` | Files 页消费 `status.files_processed/files_total/message` 与终态 `results:[{file_path, analysis:{summary,description,keywords}}]` | 同上 |
| `getModels` / `getLLMStatus` | GET `/api/llm/{models,status}` | models：text/vision 列表；status：服务状态（Settings/Files 兜底 `{status:'error'}`） | Settings、Dashboard、Files |
| `toggleFileRelevance` | POST `/api/llm/toggle-relevance` | 切换文件相关性标记 | AnalysisCenter |

`pollBatchStatus`（`llmService.js:101-158`）是带 AbortSignal 的标准轮询：`settled` 标志
防双 resolve、`cleanup` 清 timer 与事件监听。

### 端点 → 响应字段要点速查（按 service 汇总）

下表把其余 service 的"前端最关心字段"汇总成一列，全部推导自后端 handler（与
[CPP_REST_API.md](../../api_reference/CPP_REST_API.md)、
[Python_REST_API.md](../../api_reference/Python_REST_API.md) 一致）：

| Service.方法 | 端点（归属） | 响应字段要点 |
|---|---|---|
| forensics.getComprehensiveTimeline | `/api/forensics/timeline/comprehensive`（C++） | `{timeline:[事件\|簇], metadata:{total_events}}`；`cluster=true` 时簇带 `group_descriptor{bucket_index,bucket_seconds,event_type,parent_directory}`、`cluster_count`、`llm_summary?` |
| forensics.getTimelineDetails | `.../timeline/details`（C++） | `{events:[...]}`；簇内明细按 descriptor 定位 |
| forensics.getTimelineDistribution | `.../timeline/distribution`（C++） | `{distribution:[{event_date, event_type, count}]}` |
| forensics.getAnalyzedEventClusters | `.../timeline/clusters/analyzed`（C++） | 已分析簇列表（`task_id` 必填） |
| forensics.getLargestFiles | `/api/forensics/files/largest`（C++） | 文件数组（Python 侧 CppBackendService 兼容裸数组或 `{largest_files\|files}` 包装——同一端点两种形态的历史遗留） |
| forensics.getExtensionAnalysis | `.../files/extensions-analysis`（C++） | 扩展名统计 |
| extraction.startExtraction | `/api/forensics/extract`（C++） | 含 `job_id`；`mode∈{all,extension,name,deleted}`，非法 400 |
| extraction.getExtractionStatus | `.../extract/status?job_id=`（C++） | `{status, task_id, error_details?, message?, ...}`——`task_id` 是轮询方做跨任务污染检查的依据 |
| system.getSystemHealth | `/api/system/health`（C++） | `{status:"healthy", timestamp(ms), version, task_management{total_tasks,running_tasks,failed_tasks,system_load}, services{...}}` |
| system.getPythonHealth | `/health`（Python） | `{status, timestamp, version:"1.0.0", uptime_seconds}` |
| system.getRedisStatus | `/api/system/redis/status`（Python） | `{connected, in_use, status, url(已脱敏), timestamp}` |
| system.exportToon | `/api/forensics/export/toon`（C++） | 原始 TOON 文本（首行 `TOON.schema:`） |
| search.searchFulltext | `/api/search/fulltext`（C++） | 匹配文档列表 + 分页；`q` 必填 |
| search.createSearchIndex | `/api/search/index`（C++） | `source_path`/`index_path` 均必填，缺 400 |
| filter.fetchProfiles | `/api/filter/profiles`（C++） | **ApiResponse 封装** `{success, message, data, timestamp, pagination, error_code}`（全后端唯一使用该外壳的路由组）——filterSlice 因此多剥一层 `.data` |
| graphiti.ingestTaskData | `/api/graphiti/ingest`（Python） | `IngestionResponse {job_id, status:"PENDING", message}`；前端只消费 `job_id` |
| graphiti.getJobStatus | `/api/graphiti/jobs/{job_id}`（Python） | `{job_id, status(大写), progress:int, current_phase, created_at, started_at?, completed_at?, error?, result?}` |
| graphiti.getGraphData | `/api/graphiti/graph`（Python） | `{nodes:[], links:[]}`（ForceGraph2D 直接可吃） |
| caseGroup.createCase | `/api/llm/cases`（Python） | **201**；`CreateCaseRequest {name, description="", task_ids?[]}` |
| caseGroup.startMultiAnalysis→pollMultiAnalysis | `/api/llm/multi-image-analysis{,/{job_id}}`（Python） | job dict `{job_id, case_id, status(running/completed/failed), progress{stage,message}, result?, error?}`；404=job 不存在 |
| investigation（workbench 组） | `/api/investigation/workbench/{taskId}/*`（Python） | overview：`{initialized, event_count, analysis_count, report_evidence_count}`；events：`{events:[...]}`；analysis-jobs：`{status∈queued/running/...}` |
| reportGeneration.generateReport | `/api/reports/generate`（Python） | **202**（admission）；body 仅 `{task_id, requested_by}`，`extra="forbid"` 拒绝多余字段 |
| reportGeneration.getReportGeneration | `/api/reports/generations/{id}?task_id=`（Python） | `{status∈admitted/running/completed/failed, ...}`——exact 轮询，无 latest 回退 |
| reportDataSource.listVersions | `/api/reports?scope_type=&scope_id=`（Python） | 版本数组（queued/generating/ready/failed） |
| intelligenceReport.* | `/api/llm/intelligence-report/{task_id}[/records\|/search\|/metadata]`（Python） | 分章节正文 / 记录 / 检索 / 元数据 |
| association.clusterFiles 等 | `/api/associations/{cluster-files,file-clusters}`（Python） | 关联对列表；无对应数据库 400 |
| wechat.* | `/api/wechat/*`（Python） | 全部 GET 需 `task_id` 查询参数 |
| office.parseFile | `/api/office/parse`（Python） | `{success, content(Markdown), ...}`；需 `task_id` 或 `workspace_root` 锚定工作区 |
| cs.csLogin | `/api/auth/login`（C/S :8091） | `TokenResponse {access_token, token_type:"bearer", expires_in:3600}`；**form-encoded**，JSON 422 |

### caseAnalysisService / caseGroupService / graphitiService — Python 业务域

- `caseAnalysisService`（`pythonApi`）：`saveCaseDescription`（POST
  `/api/llm/case-description`）、`getCaseAnalysisStatus`+`pollCaseAnalysis`（GET
  `/api/llm/case-analysis/{jobId}`，3s 间隔）、`getCaseReport`、`getFilteredFiles`、
  `reanalyzeFiles`（POST `/api/llm/reanalyze-files`）→ AnalysisCenter、Files 二次分析。
  **`startCaseAnalysis` 已退役**：函数体只剩
  `throw new Error('legacy case analysis generation has been retired; use report generation')`
  （`caseAnalysisService.js:29-31`），调用方应为 R2 报告生成。
- `caseGroupService`：案件 CRUD（`/api/llm/cases*`）+ 跨镜像分析（`/api/llm/multi-image-analysis*`）
  + `associateTasksToCase`（预填分析态，已分析任务复用不重跑）→ caseSlice / Cases 页。
- `graphitiService`：10 个方法（ingest/search/entities/relationships/status/tasks/delete/
  job/graph）→ `/api/graphiti/*` → KnowledgeGraph、Files 页导入按钮。

### investigationService.js — 调查域全集（`pythonApi`，420 行）

最大的 service，两组 API：

**冻结契约组（C3~R1 阶段）**——方法名与端点一一对应，注释里写明契约编号：

| 方法 | 端点 |
|---|---|
| `captureInvestigationSnapshot` | POST `/api/investigation/snapshots` |
| `getInvestigationGraph` | GET `/api/investigation/graph?max_base_nodes=` |
| `listInvestigationEvidence` / `getInvestigationSnapshot` | GET `/api/investigation/evidence(+/snapshot)` |
| `listInvestigationAnalyses` / `getInvestigationAnalysis` / `createSecondaryAnalysis` / `reviewSecondaryAnalysis` / `listInvestigationAnalysisClaims` | GET/POST `/api/investigation/analyses*` |
| `listInvestigationEvents` 及 6 个 Event 读方法 / `createInvestigationEvent` / `linkInvestigationEventEvidence` / `startInvestigationEventRefresh` | `/api/investigation/events*` |
| `listReportEvidence` / `addReportEvidence` / `updateReportEvidence` | GET/POST/PUT `/api/reports/evidence` |

**Workbench 组**（283-361 行）——统一前缀函数 + 30 余个端点：

```js
const workbenchBase = (taskId) => `/api/investigation/workbench/${encodeURIComponent(taskId)}`;

export const getOverview = (taskId) => pythonApi.get(workbenchBase(taskId));
export const bootstrapInvestigation = (taskId, options = {}) =>
    pythonApi.post(`${workbenchBase(taskId)}/bootstrap`, { mode: 'cluster_seed', ...options });
```

（`investigationService.js:283-287`）。涵盖 events/evidence/notes/analysis-jobs/
analysis accept+reject/versions+claims/refresh/report-evidence/final-reports×6/
claims provenance，以及 `pollAnalysisJob`（1.5s 间隔，completed/failed/invalid 终止）。
消费者：`/investigation` 与 `/investigation/report` 两个路由页 + 一组轮询 hooks
（Hooks.md）。**冻结契约组目前只被死代码页面 `pages/Investigation.jsx` 使用**，
在线页面走 workbench 组。

### 报告三件套 — `reportDataSource` / `reportService` / `reportGenerationService`

`reportDataSource.js` 定义抽象基类 + 两个实现：

```js
export class HttpReportDataSource extends ReportDataSource {
  constructor(client) { super(); this.client = client; }
  listVersions(scopeType, scopeId) {
    return this.client.get('/api/reports', { params: { scope_type: scopeType, scope_id: scopeId } });
  }
  ...
}
export class FixtureReportDataSource extends ReportDataSource { ... }
```

（节选自 `reportDataSource.js:12-29、62`）。`FixtureReportDataSource` 是只读夹具实现，
专供 `useReportVersion` 等 hooks 的测试注入（Testing.md）。`reportService.js:4-10`
把 `HttpReportDataSource(pythonApi)` 实例化为单例 `reportDataSource` 并转发 6 个方法
（listVersions/createVersion/getStatus/getManifest/getCategoryPage/search）。

`reportGenerationService.js` 只消费 R2c 冻结契约（文件头注释 1-12 行）：POST
`/api/reports/generate`（请求体仅 `task_id + requested_by`，evidence/prompt/envelope
全部服务端冻结）、GET `/api/reports/generations/{generation_id}?task_id=`（exact 轮询，
"绝无 latest 回退"）、GET `/api/reports/narrative/versions/{report_id}`（已发布叙事版）。
消费者：ForensicReportPage + GenerateReportPanel + useReportGenerationPolling。

### intelligenceReportService / associationService / wechatService / officeService

- `intelligenceReportService`：`/api/llm/intelligence-report/{task_id}[/records|/search|/metadata]`
  → IntelligenceReportReader（case-intelligence 的 intelligence Tab）。
- `associationService`：POST `/api/associations/{cluster-files,file-clusters}` +
  5 个纯前端异常分级工具函数（`formatAnomalyType` 等，76-140 行）→ AnalysisCenter
  双抽屉。
- `wechatService`：9 个方法 → `/api/wechat/*` → useWeChatGraph。
- `officeService`：`parseFile`（POST `/api/office/parse`）、`getSupportedFormats` →
  Files 页 Office 预览 Tab。

### cs* 三件套 — 分布式 C/S（`csApi` :8091）

`csAuthService` 的登录是 OAuth2 密码流，**必须 form-encoded**（`csAuthService.js:3-11`）：

```js
export const csLogin = (username, password) => {
  const form = new URLSearchParams();
  form.append('username', username);
  form.append('password', password);
  return csApi.post('/api/auth/login', form);
};
```

注释说明：端点依赖 `OAuth2PasswordRequestForm`，JSON body 会 422；传 `URLSearchParams`
让 axios 自动改 `application/x-www-form-urlencoded`。另有 `csRefresh`/`csMe`；
`csClientService.listClients/getClient`、`csTaskService` 的 4 个分布式任务方法。目前
唯一消费者是 `/distributed` 冒烟页。

### 走读：pollExtractionStatus — service 层轮询的防御性样板

`web/src/services/extractionService.js:52-110` 是全仓库写得最防御的轮询器，值得整段读
（节选核心）：

```js
export const pollExtractionStatus = async (jobId, onProgress, interval = 1000, options = {}) => {
  const { taskId, expectedTaskId = taskId, signal,
          timeoutMs = 15 * 60 * 1000, isCurrent = () => true } = options;
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (callback, value) => {          // ① 单次 settle 保护
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      callback(value);
    };
    const poll = async () => {
      if (signal?.aborted || !isCurrent(taskId, jobId) || Date.now() > deadline) {
        finish(reject, /* AbortError 或 timeout */);  // ② 调度前三重身份检查
        return;
      }
      const status = await getExtractionStatus(jobId, signal);
      if (signal?.aborted || !isCurrent(expectedTaskId, jobId)) {
        finish(reject, new Error('Extraction job is no longer current'));  // ③ 响应后再查一次
        return;
      }
      if (status.task_id && expectedTaskId && status.task_id !== expectedTaskId) {
        finish(reject, new Error('Extraction job belongs to another task')); // ④ 服务端身份核对
        return;
      }
      onProgress?.(status);
      if (status.status === 'completed') finish(resolve, status);
      else if (status.status === 'failed' || status.status === 'cancelled') {
        const error = new Error(status.error_details || status.message || 'Extraction failed');
        error.status = status;                      // ⑤ 把终态行挂到 error 上
        finish(reject, error);
      } else {
        timer = setTimeout(poll, interval);
      }
    };
    poll();
  });
};
```

逐块解释：

- ① `settled` 标志保证 resolve/reject 只会发生一次（AbortSignal 事件、超时、正常终态
  可能竞争）；
- ②③ **调度前与响应后各做一次 `isCurrent(taskId, jobId)`**——页面切换任务后，即使
  请求已在途，晚到的响应也不会写回新任务的 UI；
- ④ 是唯一做"服务端身份核对"的轮询器：后端返回的 `status.task_id` 若与预期不符，
  视为跨任务污染直接抛错（`GET /api/forensics/extract/status` 的响应包含 `task_id`
  才使这成为可能，见上表）；
- ⑤ `error.status = status` 让调用方能在 catch 里拿到完整的失败行（`error_details`
  优先于 `message`）。

## 协作

- Services ↔ Store.md：taskService/caseGroupService/filterService 被 slice 的 thunk 包裹；
  其余 service 由页面/hooks 直调。
- Services ↔ Hooks.md：`poll*` 系列的调用方、identity 绑定都写在 hooks 里。
- Services ↔ Pages.md：每个页面"调哪些 service"在页面小节列出。

## 与后端契约的对应

Service 层是前端对三份契约的唯一消费面，逐条对应
[ServiceContracts.md](../../reference/ServiceContracts.md)：

1. **解包约定**：所有 service 函数返回拦截器解包后的 `response.data`（Overview.md），
   即后端 handler 的**原始响应体**——C++ 侧除 `/api/filter/*` 外不套 ApiResponse 外壳
   （CPP_REST_API.md"响应约定"），因此 filterSlice 需要再多剥一层 `.data`（Store.md）。
2. **状态字面量大小写**：C++ 任务状态全小写（`completed/failed/...`，TaskHelpers），
   Python Graphiti 作业状态全大写（`COMPLETED/FAILED/CANCELLED`，`_jobs.py:52` 统一
   大写化）。KnowledgeGraph 页比较大写、Tasks/Timeline 比小写——两套并存是有意的，
   改动任一侧都会静默破坏轮询终止条件（ServiceContracts.md §2 漂移点 4）。
3. **202 准入语义**：`/api/reports`（版本创建）与 `/api/reports/generate`（生成）都
   返回 **202** 而非 201——"admitted，异步执行中"。`useReportGenerationPolling` 的
   `admitted/running` 继续轮询集合正对应这个语义。
4. **exact id 轮询**：R 系列冻结契约（`reportGenerationService`、investigation 部分
   端点）要求"绝不回退到 latest"；`getReportGeneration(taskId, generationId)` 的双参
   签名就是为此设计。ServiceContracts.md §9 未发现该契约的漂移。
5. **form-encoded 特例**：C/S 登录 `OAuth2PasswordRequestForm` 要求
   `application/x-www-form-urlencoded`，`csLogin` 用 `URLSearchParams` 实现（cs* 三件套
   走读）。Python_REST_API.md §16.2 的 curl 示例与之等价。
6. **已知漂移提醒**：`/api/markitdown/*` 前端不直调（仅 C++ 调，OfficeAnalyzer/
   MarkitdownProxy）；`files/largest` 无服务端分页（Python 侧取全量再切片，
   ServiceContracts.md §9-6"假分页"）——前端 Files 页应传合理 `limit`。

## 注意

1. **`caseAnalysisService.startCaseAnalysis` 已是 throw 存根**，新代码请走
   `reportGenerationService.generateReport`。
2. `forensicsService.analyzeEventClustersBatch`（48-51 行）只是 `Promise.all` 并发单簇
   请求，无并发上限——批量分析请用 `llmService.startBatchAnalysis` 的后端批处理。
3. `associationService` 里残留大量调试 `console.log`（21-44 行）。
4. 死代码 service：暂无整文件级死 service，但 taskService 的 batch-*/audit-log/
   priority/cleanup、llmService 的 analyzeFile 目前没有页面调用。

## 验证

```bash
cd web && npx vitest run src/services/   # 8 个 service 测试文件
# 手工：起后端后访问对应页面，DevTools Network 按端点前缀过滤核对方法↔端点映射。
```

**最后更新**: 2026-08-24（二轮深化：补代码走读与契约对应）
