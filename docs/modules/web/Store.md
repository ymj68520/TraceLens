# 状态管理（Store / Redux Toolkit）

## 为什么要有这篇文档

前端没有引入 RTK Query 或 redux-persist，全局状态是"7 个手写 slice + 一个手动持久化的
settings"的组合。哪些状态进 Redux、哪些留在页面本地 state、哪些写 localStorage，
边界全靠约定。本文逐 slice 说明 state 形状、关键 reducer/thunk、持久化键位，以及
两个容易误判的事实：`dataSlice` 注册了但**无人消费**；主题相关的 `uiSlice.theme` 与
`settingsSlice.theme` 是**两份平行状态**。

## 代码位置

`web/src/store/`：index.js（组装）、taskSlice.js、caseSlice.js、settingsSlice.js、
uiSlice.js、dataSlice.js、intelligenceSlice.js、filterSlice.js。

## 核心概念

- **只有两个 slice 真正承载业务数据**（tasks/cases），其余分别是设置（settings）、
  UI 骨架（ui）、进度看板（intelligence）、过滤器档案（filter）与空壳（data）。
- **持久化只有一处**：settingsSlice 手写 localStorage 读写（键 `forensics_settings`），
  项目没有用 redux-persist。token 类持久化（`auth_token` / `cs_auth_token` /
  `auth_user`）由 api.js 和 Login 页直接操作 localStorage，不经 Redux。
- **thunk 的错误约定**：全部 `rejectWithValue(error.response?.data || error.message)`，
  又因为拦截器已把错误增强为 `{message,status,statusText,data,config}`，页面拿到的是
  这个对象（`err?.message` 可直接渲染）。

## 走读

### store/index.js — 组装

`web/src/store/index.js:10-20`：

```js
export const store = configureStore({
  reducer: {
    tasks:        taskReducer,
    ui:           uiReducer,
    data:         dataReducer,
    settings:     settingsReducer,
    intelligence: intelligenceReducer,
    cases:        caseReducer,
    filter:       filterReducer,
  },
});
```

七个键就是全局 state 的顶层形状；`index.jsx` 挂载（Overview.md）。

### taskSlice.js — 任务域（163 行）

state 形状（`taskSlice.js:94-102`）：

```js
initialState: {
  tasks: [],
  currentTask: null,
  statistics: null,
  status: 'idle',   // 'idle' | 'loading' | 'succeeded' | 'failed'
  error: null,
  filters: { status: 'all', priority: 'all' },
  pagination: { total: 0, limit: 20, offset: 0 },
},
```

七个 thunk：`createTask`、`fetchTasks`、`fetchTasksSilent`、`fetchTaskProgress`、
`cancelTask`、`deleteTask`、`fetchTaskStatistics`。核心区分是**普通拉取与静默拉取**
（`taskSlice.js:28-41` 的注释写明动机）：

```js
/**
 * Silent background refresh — does NOT set status='loading'.
 * Use this for polling so the UI doesn't flash/re-render.
 */
export const fetchTasksSilent = createAsyncThunk(
  'tasks/fetchSilent',
  async (params = {}, { rejectWithValue }) => { ... }
);
```

`extraReducers` 里 `fetchTasks.pending` 置 `status='loading'`（页面显示 Spinner），
而 `fetchTasksSilent.fulfilled` 只更新 `tasks`/`pagination`，完全不碰 `status`
（`taskSlice.js:130-134`）——这是从"Tasks 页每 5 秒闪一次 loading"的老问题里拆出来的
（同见 hooks/useTaskAutoTrigger.js 头注释）。其他细节：

- `fetchTaskProgress.fulfilled` 同时 patch `tasks[i]` 与 `currentTask`（137-142 行）；
- `cancelTask` 直接把本地状态置 `cancelled`（乐观更新，145-148 行）；
- 同步 reducer：`setFilters`（浅合并）、`clearError`、`updateTaskProgress`、
  `setCurrentTask`（TaskSelector 用它同步 URL ↔ store，`TaskSelector.jsx:28-30`）。

### settingsSlice.js — 唯一持久化的 slice（67 行）

`web/src/store/settingsSlice.js:3-29` 是完整的持久化机制：

```js
const SETTINGS_KEY = 'forensics_settings';

const loadSettings = () => {
  try {
    const saved = localStorage.getItem(SETTINGS_KEY);
    return saved ? JSON.parse(saved) : {};
  } catch (error) { console.error('Failed to load settings:', error); return {}; }
};

const saveSettings = (settings) => {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch (error) { console.error('Failed to save settings:', error); }
};
```

state 初值（33-42 行）用展开合并：`{apiUrl, pythonApiUrl, refreshInterval:5000,
autoRefresh:true, theme:'light', language:'en', itemsPerPage:20, showTerminal:false,
...loadSettings()}`——localStorage 里的旧值覆盖默认值，实现"启动即恢复"。两个
reducer：`updateSettings` 用 `Object.assign(state, payload)` 后立即 `saveSettings`
（45-48 行）；`resetSettings` 重置为默认（但注意：**不含 `showTerminal`**，50-58 行，
重置后开关保持原值）。主题的生效链：`updateSettings({theme:'dark'})` → App.jsx 的
effect 给 `<html>` 加 `dark` class（Overview.md / I18nTheming.md）。

已知边角：`apiUrl`/`pythonApiUrl` 字段默认值在模块加载时按当前 host 推导
（`settingsSlice.js:7-11`），且 Settings 页可编辑，但**没有任何请求方读取它们**——
实际请求地址由 `services/api.js` 的环境变量推导决定（Pages.md 的 /settings 小节）。

### intelligenceSlice.js — 任务级进度看板（81 行，无 thunk）

三块 state（`intelligenceSlice.js:5-15`）：

```js
initialState: {
  // Report generation jobs: { [taskId]: { jobId, status, progress, currentStep, detail } }
  activeAnalysisJobs: {},
  // File batch analysis jobs: { [taskId]: { jobId, status, progress, message } }
  activeBatchJobs: {},
  refreshFlags: { files: false, clusters: false },
},
```

- `activeBatchJobs`：Files 页 `handleBatchAnalyze` 后 `setBatchJob({taskId, jobId})`；
  换页回来时靠它"自动续轮询"（`Files.jsx:66-73`）——这是把页面局部进度提升到全局的
  核心原因（刷新页面仍会丢，因为它不持久化）。
- `refreshFlags`：Timeline 分析完簇后置 `clusters:true`（`Timeline.jsx:306`），
  AnalysisCenter 消费后 `clearRefreshFlag`（`AnalysisCenter.jsx:11`）——跨页面的
  "数据已变脏"信号。
- 全部 reducer 都是同步的：`setAnalysisJob/updateAnalysisProgress/clearAnalysisJob`、
  `setBatchJob/updateBatchProgress/clearBatchJob`、`setRefreshFlag/clearRefreshFlag`。

### caseSlice.js — 案件域（203 行）

state：`{cases:[], status, error, activeJobId}`。最有意思的 thunk 是
`createCaseWithTasks`（`caseSlice.js:27-69`），四步编排：

```js
// Step 1 — create individual tasks for each NEW image path
const createdTasks = await Promise.all(
  imagePaths.map((path) => taskService.createTask({
    image_path: path, priority, case_description: description,
    llm_analyze: true, llm_mode: 'smart', android_analyze: androidAnalyze,
  }))
);
// Step 2 — merge associated (already-completed) task IDs, de-duplicated
const taskIds = [...new Set([...newTaskIds, ...associateTaskIds])];
// Step 3 — create case linking all tasks
const newCase = await caseGroupSvc.createCase(name, description, taskIds);
// Step 4 — pre-populate analysis state ... (associateTasksToCase)
```

（节选自 `caseSlice.js:31-57`，注释保留原文）。Step 4 失败被 catch 为非致命
（"case was created; reuse-state can be repaired later"，56-62 行）。其余 thunk：
`fetchCases`、`startCrossAnalysis`（fulfilled 后置 `activeJobId` 并把案件标
`analysing`，183-187 行）、`associateTasks`、`deleteCase`（仅删案件记录）、
`deleteCaseWithTasks`（`Promise.allSettled` 尽力删任务再删案件，125-135 行）。

### uiSlice.js — 布局骨架（70 行）

`{sidebarOpen:true, theme:'light', notifications:[], loading:false,
modal:{open:false,type:null,data:null}}`。同步 reducer：`toggleSidebar`/`setSidebarOpen`
（Layout 折叠按钮）、`addNotification`/`removeNotification`、`setLoading`、`openModal`/
`closeModal`。**实际被消费的只有 sidebar 与 modal**：Tasks 页用 `openModal({type})`
驱动创建任务等弹窗（`Tasks.jsx:23`）；`notifications` 没有对应 UI（toast 实际走
ToastContext）；`ui.theme` 没有任何组件读取——主题真正生效的是 `settings.theme`
（App.jsx）。

### dataSlice.js — 注册但无人消费（58 行）

`{tasks:[], timeline:[], files:[], androidData:null, statistics:null, searchResults:null,
cache:{}}` + `setTimeline/setFiles/setAndroidData/setStatistics/setSearchResults/
setCache/clearCache/invalidateCache`（`dataSlice.js:14-43`）。全仓库检索不到任何
`state.data` 选择器或这些 action 的 dispatch（`store/index.js:4` 注册除外）——它是
早期"页面数据进 Redux"方案的遗留，各页面后来都改为本地 state + service 直调。
**结论：dataSlice 目前是死状态，可安全移除或作为新全局缓存的落点。**

### filterSlice.js — 过滤器档案（131 行）

四个 thunk 包 filterService：`fetchProfiles`（成功取 `response?.data?.profiles || []`，
注意这里多剥了一层 `.data`——因为 filterService 走 C++ `api`，拦截器已解包一次，
这里再取 `.data` 是对 C++ 响应体 `{data:{profiles}}` 的适配，`filterSlice.js:11-21`）、
`fetchProfileDetail`（独立的 `detailStatus`，pending 时立即清旧详情防串档，98-101 行）、
`saveProfile`、`removeProfile`。消费者：`components/filters/FilterProfileSelector/
FilterProfileEditor` 与 Files 页。

## 协作

- taskSlice ↔ taskService（全部 7 个方法）；caseSlice ↔ caseGroupService + taskService；
  filterSlice ↔ filterService。
- settingsSlice ↔ Settings 页 ↔ useTranslation（读 `language`）↔ App.jsx（读 `theme`）
  ↔ useTaskAutoTrigger/Dashboard（读 `autoRefresh/refreshInterval/itemsPerPage`）。
- intelligenceSlice ↔ Files/Timeline/AnalysisCenter 三个页面的进度与脏标记桥接。
- uiSlice.modal ↔ Tasks 页三弹窗。

## 注意

1. **两份 theme**：`settings.theme`（真）与 `ui.theme`（假）。改主题请 dispatch
   `updateSettings({theme})`，`setTheme`（uiSlice）不会生效。
2. **`resetSettings` 不重置 `showTerminal`**（`settingsSlice.js:49-58` 对照 33-42 行）。
3. **`fetchTasksSilent` 没有 rejected 处理**——后台轮询失败静默吞掉（调用方
   useTaskAutoTrigger 自己 console.warn）。
4. localStorage 里与前端相关的键一共四个：`forensics_settings`（本文件）、
   `auth_token`/`auth_user`（mock 登录）、`cs_auth_token`（分布式）。

## 验证

```bash
cd web && npx vitest run src/hooks/useTaskAutoTrigger.test.js  # 验证 fetchTasksSilent 分支
# 浏览器：DevTools → Application → Local Storage → 查看 forensics_settings
# 在 /settings 切换主题/语言/每页条数后刷新页面，确认恢复；
# Redux DevTools 观察 tasks/fetchSilent 每 5s 一次且 status 不变。
```

**最后更新**: 2026-08-24（新建，解释式）
