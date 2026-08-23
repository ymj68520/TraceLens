# 页面走读（Pages）

## 为什么要有这篇文档

`web/src/routes.jsx` 注册了 23 条路径路由（外加 `/` 的 index 重定向，共 24 个路由项），
`web/src/pages/` 下却有更多页面文件——其中四个
（InvestigationGraph、Logs、LLMDescriptions、根目录的 Investigation.jsx）**没有任何路由
指向它们**，属于死代码；而侧栏又挂着一条指向不存在路由的链接。只看目录树无法判断
"哪个页面真的可达、数据从哪来"，因此本文按路由表逐页走读，并如实标注已知问题。

## 代码位置

- 路由表：`web/src/routes.jsx`（`appRoutes` 数组，27-134 行）
- 页面：`web/src/pages/`（含 `Investigation/`、`WeChatGraph/` 两个子目录）
- 侧栏导航：`web/src/components/Layout/Layout.jsx:23-46`
- 全局任务选择器：`web/src/components/common/TaskSelector.jsx`

## 核心概念

- **任务上下文靠 query 参数传播**：顶部 `TaskSelector` 把当前镜像任务写进 URL
  （`task_id` 或 `taskId`），`Layout.getLinkUrl()`（`Layout.jsx:51-57`）在 13 个
  task-context 页面之间跳转时自动透传该参数。页面自身再用 `useSearchParams` 读回。
- **两类数据获取模式**：任务/案件页走 Redux thunk（`fetchTasks` 等）；分析页大多
  "页面本地 state + service 直调"，配 `useStaleResource` / requestId 防陈旧模式（Hooks.md）。
- **登录态是假的**：`/login` 是 mock（见下文），路由层没有任何守卫——直接访问
  `/dashboard` 不需要登录。

## 走读（按路由顺序）

### /login — `pages/Login.jsx`（126 行）

纯 UI 页：动态 mesh 背景 + framer-motion 动效。提交逻辑在 `Login.jsx:12-30`：

```js
const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
        await new Promise((r) => setTimeout(r, 800));
        if (credentials.username && credentials.password) {
            localStorage.setItem('auth_token', 'mock_jwt_token_' + Date.now());
            localStorage.setItem('auth_user', credentials.username);
            navigate('/dashboard');
        } else {
            setError('请输入用户名和密码');
        }
```

**已知问题（mock 登录）**：不调任何后端，任意非空账密即发一个假 JWT 给 C++ 拦截器
（`services/api.js:50-52` 会把它塞进 `Authorization` 头）。真正的鉴权只在分布式模式
（`/distributed` 的 `cs_auth_token`）存在。

### / → 重定向 /dashboard

`routes.jsx:36-39`，`<Navigate to="/dashboard" replace/>`。

### /dashboard — `pages/Dashboard.jsx`（263 行）

- **数据**：`fetchTasks({limit:10})` + `fetchTaskStatistics()`（Redux）；健康检查直调
  `getSystemHealth`（C++）、`getPythonHealth`、`getGraphitiStatus`（Neo4j）、`getLLMStatus`、
  `getRedisStatus`（后四个 pythonApi），逐个 try/catch 更新 `depHealth` 卡片
  （`Dashboard.jsx:35-74`）。
- **交互**：`TOON Export` 按钮取第一个 completed 任务调 `exportToon`（`Dashboard.jsx:99-104`）。
- **自动刷新**：只有存在 running 任务时才按 `settings.refreshInterval` 轮询
  （`Dashboard.jsx:77-83`）。

### /tasks — `pages/Tasks.jsx`（228 行）

- **数据**：`fetchTasks(filters)` + `fetchCases()`；后台静默刷新交给 `useTaskAutoTrigger()`
  （`Tasks.jsx:63`，用 `fetchTasksSilent`，不闪 loading）。
- **交互**：创建任务/加入案件/勾选组案三种弹窗；取消/删除走 `ConfirmDialog` + thunk，
  结果用 `useToast()`（`ToastContext.jsx` 版本）提示（`Tasks.jsx:72-103`）。
- 任务→案件的反查表是纯前端 map（`Tasks.jsx:54-60`）。

### /cases — `pages/Cases.jsx`（429 行）

多镜像案件管理：`fetchCases` / `createCaseWithTasks`（四步 thunk，见 Store.md）/
`startCrossAnalysis`；跨镜像分析进度用 `pollMultiAnalysis`（caseGroupService）按
`polling[caseId]` 本地 state 轮询（`Cases.jsx:45-49`）。删除支持"仅案件 / 案件+任务"
两种（`deleteCase` / `deleteCaseWithTasks`）。

### /timeline — `pages/Timeline.jsx`（897 行）

最重的分析页之一：

- **状态全部在 URL**：`page/type/date/start/end/cluster/view/bucket` 七个 query 参数
  （`Timeline.jsx:80-91`），`updateParams` 统一写入，可分享、可回退。
- **数据**：`getComprehensiveTimeline`（主列表，聚合簇）、`getTimelineDistribution`
  （分布图）、`getTimelineDetails`（抽屉里簇内明细），全部 C++ `api`。
- **AI 研判**：`analyzeEventCluster` / `reanalyzeEventCluster` 走 **pythonApi**
  `/api/llm/analyze-event-cluster`，前端把簇的 `group_descriptor` 校验后原样上送
  （`forensicsService.js:14-43`）；完成后 `dispatch(setRefreshFlag({type:'clusters'}))`
  通知研判中心（`Timeline.jsx:306`）。
- **聚簇窗口**：`auto` 档按事件总跨度映射 60s~6h（`Timeline.jsx:64-71` 的
  `autoBucketForSpan`）。
- **交互**：簇点击打开 `ClusterInvestigationDrawer`（右滑抽屉，含 AI 分析、簇内文件
  过滤、Virtuoso 虚拟列表）；列表本体也是 Virtuoso。

### /files — `pages/Files.jsx`（1047 行，最大页面）

- **数据**：`getLargestFiles` + `getExtensionAnalysis`（C++）；LLM 描述来自
  `getLLMStatus`；DLL 分析 `analyzeDLL`（pythonApi）。
- **批量 LLM**：`handleBatchAnalyze`（`Files.jsx:463-507`）调
  `startBatchAnalysis(taskId, {filePaths, modelType})` 后 dispatch `setBatchJob` 并轮询
  `pollBatchStatus`；挂载时检测 `intelligenceSlice.activeBatchJobs[taskId]` 自动续轮询
  （`Files.jsx:66-73`）。
- **其他交互**：文件提取（`startExtraction`/`pollExtractionStatus`）、二次分析弹窗
  （`reanalyzeFiles`）、Office 预览（`officeService.parseFile`）、Graphiti 一键导入
  （`ingestTaskData`，`Files.jsx:510-527`）。
- 子组件拆在 `components/files/`（Header/Filters/ExtractionControls/FileListTable/
  ExtensionAnalysisTab/OfficePreviewTab/ReanalyzeModal）。

### /wechat-graph — `pages/WeChatGraph/WeChatGraph.jsx`（懒加载）

唯一 `React.lazy` 的路由（见 Overview.md）。壳组件把全部逻辑委托给
`pages/WeChatGraph/hooks/useWeChatGraph.js`，布局 = SearchBar + ForceGraph2D 画布 +
右侧面板（选中边→ChatPanel 聊天记录分页；选中节点→PersonDetail；默认→CommunityLegend）+
底部 TimelineSlider。数据全部来自 `wechatService`（pythonApi `/api/wechat/*`）。

### /oss — `pages/OSS.jsx`（376 行）

OSS 对象存储分析。**已知问题（/oss 页 404）**：页面读数据的 6 个端点
`GET /api/forensics/oss/{objects,logs,summary,stats/storage-class,stats/extensions,buckets}`
（`services/ossService.js:24-63`）在 C++ 后端**均未实现**——`src/network/HTTPServer/routes/
OSSAnalysisRoutes.cpp` 只注册了 `analyze`、`analyze/status`、`ai/*`、`download` 六条路由。
因此分析可以启动（`startAnalysis`+`pollAnalysisStatus`，`OSS.jsx:90-100`），但 summary/
objects/logs/buckets 各 Tab 的加载会全部 404，页面只能显示错误态。

### /search — `pages/Search.jsx`（284 行）

全文检索：`searchFulltext`（`/api/search/fulltext`）与 `createSearchIndex`
（`/api/search/index`），均 C++。索引名/源路径按当前任务自动推导
（`Search.jsx:21-22`：`search_index_<taskId 前 8 位>`、任务提取目录）。

### /statistics — `pages/Statistics.jsx`（229 行）

单端点页：`getStatisticsOverview(taskId)`（C++）。出错时兜底 `{overview:{}}` 防崩溃
（`Statistics.jsx:41`）。

### /settings — `pages/Settings.jsx`（296 行）

- **设置持久化**：`updateSettings`/`resetSettings`（settingsSlice，写入 localStorage
  `forensics_settings`，见 Store.md / I18nTheming.md）。
- **信息卡**：LLM 状态/模型（`getLLMStatus`+`getModels`）、Neo4j 连接测试
  （`getGraphitiStatus`）、`showTerminal` 开关（控制侧栏是否出现 Terminal 入口，
  `Layout.jsx:44-46`）。
- **注意**：`settings.apiUrl` / `pythonApiUrl` 只是展示性字段，实际请求地址由 `api.js`
  的环境变量/host 推导决定，改这里不会改变请求目标。

### /knowledge-graph — `pages/KnowledgeGraph.jsx`（783 行）

Graphiti 知识图谱工作台：导入（`ingestTaskData`/`reingestAnalyzedData` + `getJobStatus`
轮询）、搜索（`searchGraph`）、实体/关系分页（`listEntities`/`listRelationships`）、
可视化（`getGraphData`，ForceGraph2D）。Tab 子组件在 `components/knowledge-graph/`。

### /case-intelligence — `pages/CaseIntelligence.jsx`（99 行）

"证据研判"阅读器壳，双 Tab（`CaseIntelligence.jsx:25-27`）：

```jsx
const [reportTab, setReportTab] = useState(
    () => (searchParams.get('tab') === 'intelligence' ? 'intelligence' : 'forensic'),
);
```

- `intelligence` Tab → `IntelligenceReportReader`（`/api/llm/intelligence-report/*`，
  历史 LLM 研判报告，三栏阅读器，见 Components.md）；
- `forensic` Tab（默认）→ `ForensicReportPage`（R2 取证快照报告，`/api/reports/*`）。
- scope 由 URL 决定：有 `case_id` 用 case scope，否则 `task_id`（`CaseIntelligence.jsx:29-31`）。
- task 上下文时右上角"返回调查工作台"链到 `/investigation?taskId=…`（`CaseIntelligence.jsx:74-83`）。

### /analysis-center — `pages/AnalysisCenter.jsx`（652 行）

"研判中心"：案情描述、LLM 证据卡片、事件簇、Cluster↔File 双向关联抽屉
（`associationService`）、二次分析弹窗（`reanalyzeFiles`）。

**已知问题（页面崩溃）**：`AnalysisCenter.jsx:13` 导入的是
`import { useToast } from '../components/common/useToast';`，而该文件读取的 context
（`components/common/toastContext.js` 的裸 `createContext(null)`）**从未被任何 Provider
提供**——index.jsx 挂的 `ToastProvider` 提供的是 `ToastContext.jsx` 内部自建的另一个
context 实例。于是 `AnalysisCenter.jsx:43` 的 `const toast = useToast()` 在渲染期抛
`useToast must be used within ToastProvider`，被 App 层 ErrorBoundary 接住，
**/analysis-center 整页表现为错误兜底 UI**（其余页面都从 `ToastContext.jsx` 导入，
不受影响）。

### /investigation — `pages/Investigation/Investigation.jsx`（74 行）

二次调查三栏工作台（左 Event+Evidence 面板 / 中 InvestigationTimeline / 右
AnalysisWorkspace）。数据链：`useInvestigationEvents(taskId)` 先 `getOverview`，若
`!initialized` 则 `bootstrapInvestigation`（`mode:'cluster_seed'`），再
`getInvestigationEvents`（`pages/Investigation/hooks/useInvestigationEvents.js:14-31`）。
全部端点在 `/api/investigation/workbench/{taskId}/...`（pythonApi）。claim 可溯源：
`traceClaim` 展开引用的 evidence_keys（`Investigation.jsx:38-42`）。

### /investigation/report — `pages/Investigation/FinalReportViewer.jsx`（325 行）

最终报告阅读器：`useFinalReportViewer`（列表+详情，requestId 防陈旧）、
`useReportTraceback`（引用回溯）、`useFinalReportPublication`（发布事实）、
`useFinalReportPresentation`（markdown/html/print 切换）、`checkFinalReportIntegrity`
（完整性校验，`pages/Investigation/finalReportIntegrity.js`）。

### /reports/task/:taskId、/reports/case/:caseId、/case-report — Legacy 重定向

`pages/LegacyReportRedirect.jsx:23-32` 三个组件全部 `<Navigate>` 到 `/case-intelligence`
并携带 `task_id`/`case_id`。注意 `pages/reportRedirectTarget.js` 里还有一份带
`&tab=forensic` 的同逻辑，但**无任何导入方**（死代码）。

### /terminal — `pages/Terminal.jsx`（104 行）

壳 + `TerminalOutput`（见 I18nTheming.md 的日志通道分析）。三个端口卡片从
`CPP_BASE_URL`/`PYTHON_API_BASE_URL` 解析展示。

### /distributed — `pages/Distributed.jsx`（102 行）

分布式 C/S 冒烟页（非产品页）：`csLogin`（form-encoded OAuth2 密码流）→ 存
`cs_auth_token` → `listClients` + `csMe` 回显 JSON，证明 `/csapi` 代理链路通
（`Distributed.jsx:20-41`）。默认账号 `super_admin/admin123` 硬编码在表单初始值里。

## 死代码页面（无路由，勿误改）

| 文件 | 行数 | 说明 |
|---|---|---|
| `pages/InvestigationGraph.jsx` | 307 | C8c 独立图谱页；侧栏 `/investigation-graph` 链接指向它但路由不存在（见下） |
| `pages/Investigation.jsx` | 580 | C9b/C9c/C10/R1 的旧版三栏 Workbench 壳；`components/investigation/workbench/*` 12 个组件**只**被它引用 |
| `pages/Logs.jsx` | 176 | 旧日志页，功能已被 `/terminal` 的 TerminalOutput 取代 |
| `pages/LLMDescriptions.jsx` | 507 | 旧 AI 描述页，功能并入 `/files` 与 `/analysis-center` |

它们各自仍保留测试（`InvestigationGraph.test.jsx`、`Investigation.test.jsx` 等），
测试通过不代表页面可达。

## 已知问题清单

1. **侧栏死链 `/investigation-graph`**：`Layout.jsx:32` 生成该链接，`routes.jsx` 无此路由。
   点击后 createBrowserRouter 找不到匹配，整页落到默认错误页。
2. **侧栏缺 i18n 键**：`Layout.jsx:32-33` 用的 `nav.investigation_graph` /
   `nav.investigation_workbench` 在 `locales/en.js`、`locales/zh.js` 中都不存在，
   `t()` 回退为原样返回 key，中文界面侧栏会直接显示英文键名字符串。
3. **mock 登录**（上文）。
4. **/oss 读端点后端未实现**（上文）。
5. **/analysis-center 渲染即抛错**（上文 useToast 导入错误）。

## 验证

```bash
cd web && npm run dev
# 逐条访问：/dashboard /tasks /cases /timeline?task_id=<id> /files?task_id=<id>
# /knowledge-graph /case-intelligence?task_id=<id> /investigation?task_id=<id>
# 预期失败的：/investigation-graph（无路由）、/analysis-center（ErrorBoundary）、
# /oss 各数据 Tab（后端 404）
cd web && npx vitest run src/routes.test.jsx   # 路由表断言
```

**最后更新**: 2026-08-24（新建，解释式）
