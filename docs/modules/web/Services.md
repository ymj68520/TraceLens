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

| 方法 | 端点 | 消费者 |
|---|---|---|
| `fetchTasks` / `listTasks` | GET `/api/tasks` | taskSlice（fetchTasks/fetchTasksSilent）、TaskSelector |
| `fetchTaskById` | GET `/api/tasks/{id}` | （备用） |
| `getTaskProgress` | GET `/api/tasks/{id}/progress` | taskSlice.fetchTaskProgress → useTaskPolling |
| `getTaskResults` | GET `/api/tasks/{id}/results` | AnalysisCenter（llm_results.descriptions） |
| `cancelTask(taskId, reason)` | DELETE `/api/tasks/{id}`（body 带 reason） | taskSlice.cancelTask → Tasks 页 |
| `deleteTask` | DELETE `/api/tasks/{id}` | taskSlice.deleteTask → Tasks/Cases 页 |
| `getTaskStatistics` | GET `/api/tasks/statistics` | taskSlice → Dashboard |
| `batchCreateTasks` / `batchGetTaskStatus` / `batchCancelTasks` | POST `/api/tasks/{batch-create,batch-status,batch-cancel}` | （暂无页面） |
| `getTaskAuditLog` / `updateTaskPriority` / `cleanupOldTasks` | GET/PUT/POST | （暂无页面） |
| `createTask` | POST `/api/tasks` | taskSlice.createTask、caseSlice.createCaseWithTasks |

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

| 方法 | 端点 | 消费者 |
|---|---|---|
| `analyzeContent` | POST `/api/llm/analyze` | Files、useFileLLMAnalysis |
| `analyzeFile`（multipart） | POST `/api/llm/analyze/file?model_type=` | （暂无页面） |
| `analyzeDLL` | POST `/api/llm/analyze/dll` | Files 页 |
| `startBatchAnalysis(taskId, options)` | POST `/api/llm/batch` | Files、useFileLLMAnalysis |
| `getBatchStatus` / `pollBatchStatus` | GET `/api/llm/batch/{jobId}` | 同上 |
| `getModels` / `getLLMStatus` | GET `/api/llm/{models,status}` | Settings、Dashboard、Files |
| `toggleFileRelevance` | POST `/api/llm/toggle-relevance` | AnalysisCenter |

`pollBatchStatus`（`llmService.js:101-158`）是带 AbortSignal 的标准轮询：`settled` 标志
防双 resolve、`cleanup` 清 timer 与事件监听。

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

## 协作

- Services ↔ Store.md：taskService/caseGroupService/filterService 被 slice 的 thunk 包裹；
  其余 service 由页面/hooks 直调。
- Services ↔ Hooks.md：`poll*` 系列的调用方、identity 绑定都写在 hooks 里。
- Services ↔ Pages.md：每个页面"调哪些 service"在页面小节列出。

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

**最后更新**: 2026-08-24（新建，解释式）
