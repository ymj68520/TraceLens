# 组件库导览（Components）

## 为什么要有这篇文档

`web/src/components/` 有 12 个子目录、60+ 组件。它们不是均质的"UI 库"：common/ 是真
正的通用件，reports/ 与 case-intelligence/ 是面向数据契约的渲染器族，investigation/
workbench/ 整组只被一个死页面引用，timeline/ 只有一只抽屉。本文按组说明职责与复用
关系，并标出"看似通用实则无人使用"的成员（ThemeProvider、bare toastContext）。

## 代码位置

`web/src/components/`：common/、Layout/、reports/、renderers/（在 reports/ 内）、
case-intelligence/、investigation/（含 workbench/）、timeline/、files/、tasks/、
filters/、knowledge-graph/、llm-descriptions/。

## 核心概念

- **样式即约定**：通用组件基于 Tailwind 工具类 + `clsx` 合并（Button），全局 class
  （`glass/glass-strong/status-dot/bg-mesh-*`）定义在 `styles/index.css` 的
  `@layer components/base`（I18nTheming.md）。
- **渲染器注册表**：报告分类页的渲染按 `renderer` 名查 Map，未注册回落
  GenericTableRenderer——新增 artifact 类型无需改分发组件。
- **数据在页面、展示在组件**：抽屉/面板类组件全部受控（props 进、回调出），自己
  拉数据的只有阅读器族（IntelligenceReportReader）。

## 走读

### common/ — 通用件（14 个文件）

| 组件 | 职责 | 备注 |
|---|---|---|
| Button | 6 variant × 3 size + loading/icon，framer-motion 微动效（`Button.jsx:22-41`） | 全站按钮 |
| Card | 标题/副标题容器，可选 motion 入场 | 全站卡片 |
| Badge | 颜色 variant 的小标签 | 状态列 |
| Spinner / ProgressBar | 加载态 | Dashboard/Files |
| Modal | 遮罩点击关闭、打开时锁 body 滚动（`Modal.jsx:13-23`），7 档尺寸 | 各弹窗底座 |
| ConfirmDialog | 二次确认（取消/删除任务、删除案件） | Tasks/Cases |
| ErrorBoundary | 类组件兜底页，Try Again/Reload（`ErrorBoundary.jsx:13-28`） | App.jsx 挂载 |
| TaskSelector | 全局任务下拉，URL ↔ `currentTask` 同步 | Layout 头部 |
| TerminalOutput | 三 Tab 日志终端 | /terminal |
| ToastContext | ToastProvider + useToast | index.jsx 挂载 |
| toastContext.js / useToast.js | **孤儿**：裸 context 与第二个 useToast | 见"注意" |
| ThemeProvider | 复制了 App.jsx 的 dark class 逻辑 | **无消费者** |

Toast 系统值得展开：`ToastContext.jsx:21-35` 的实现是"模块级自建 context + Provider +
同文件 useToast"：

```js
const addToast = useCallback((type, message, duration = 5000) => {
    const id = ++toastId;
    setToasts((prev) => [...prev.slice(-4), { id, type, message }]);
    if (duration > 0) {
      timers.current[id] = setTimeout(() => removeToast(id), duration);
    }
    return id;
}, [removeToast]);

const toast = {
    success: (msg, dur) => addToast('success', msg, dur),
    error: (msg, dur) => addToast('error', msg, dur ?? 8000),
```

最多同时 5 条（`prev.slice(-4)` + 新条），error 默认 8s、warning 6s、其余 5s；容器
固定右上 `z-[9999]`，AnimatePresence 出场动画。而 `toastContext.js` 只是
`createContext(null)`，`useToast.js` 从它取 context——与 Provider 提供的不是同一个
context 实例。全站 8 个消费方里 7 个从 `ToastContext` 导入（正确），唯独
`pages/AnalysisCenter.jsx:13` 从 `useToast` 导入（渲染即抛错，见 Pages.md）。

### Layout/ — 应用骨架

`Layout.jsx`：固定左侧深色侧栏（17 个导航项 + 可选 Terminal 项）+ 顶部玻璃拟态头
（页面标题 + TaskSelector + 在线状态点）+ `<main>{children}</main>`。两个关键函数：
`getLinkUrl`（51-57 行，13 个任务上下文页透传 `task_id`）与 `isActive`（48-49 行，
`/reports/*` 前缀特判）。导航标签全走 `t()`（I18nTheming.md 的缺键问题即出在此）。

### reports/ — 取证快照报告渲染器族（14 文件）

页面侧由 ForensicReportPage 组装（Pages.md）；组件分工：

- `ReportWorkspace`：目录 + 正文 + 工具栏的工作区骨架，持有 `useReportCategory` 与
  `useReportSearch` 的结果；
- `ReportDirectory` / `CategorySection` / `CategoryPagination`：目录树、分类节、分页；
- `ReportSearch`：搜索框 + 命中跳转（消费 `searchState.next/previous/activation`）；
- `VersionHistory`：版本列表单选；
- `GenerateReportPanel`：R2 生成入口（admission + `useReportGenerationPolling` +
  ERROR_HINTS 错误文案表，`GenerateReportPanel.jsx:12-26`）；
- `NarrativeReportView`：`report_kind==='llm_generation'` 的叙事版只读视图；
- `CitationTracebackPanel`：引用回溯面板；
- `ReportStatusPanel` / `ReportToolbar`：状态徽章与工具栏。

**渲染器注册表**是这组的扩展点（`renderers/registry.js:4-15`）：

```js
const renderers = new Map([
  ['table', GenericTableRenderer],
  ['key_value', KeyValueRenderer],
]);

export function registerReportRenderer(name, component) {
  renderers.set(name, component);
}

export function getReportRenderer(name) {
  return renderers.get(name) || GenericTableRenderer;
}
```

manifest 里每个 category 带 renderer 名；`registerReportRenderer` 允许按需注册新
渲染器而不改 registry 本体，未知名回落表格渲染。配套还有
`AttachmentList`/`RecordBadges`。`FixtureReportDataSource`（Services.md）+ 注册表让
ReportWorkspace 的测试可以完全离线。

### case-intelligence/ — 研判报告阅读器

`report-reader/IntelligenceReportReader.jsx`（216 行）是三栏阅读器：左
`ReportReaderDirectory`（目录树）、中 `ReportReaderContent`（按节点 kind 渲染）、
底 `ReportReaderPagination` + `ReportReaderSearch`；`ReportMetadataEditor` 编辑案件/
证据元数据。数据自己拉（`intelligenceReportService` 四个方法），分页用 `reqIdRef`
防陈旧（`IntelligenceReportReader.jsx:86-93`）。`sections/` 子目录是各 artifact 的
节渲染器（CaseInfo/DeviceInfo/EvidenceInfo/SmsThreads/GenericArtifactTable +
metadataFields/reportSectionUtils 工具）。另外两个抽屉：`ClusterFilesDrawer` /
`FileClustersDrawer`（Cluster↔File 双向关联，消费 associationService，被
AnalysisCenter 使用）。`markdownRenderer.jsx` 提供 Markdown 渲染。

### investigation/ — 调查图谱与 workbench

- `InvestigationGraphCanvas.jsx`（95 行）：ForceGraph2D 的 canvas 自绘封装。
  按 `node.label` 取半径（InvestigationEvent 7 / Evidence 6 / Analysis 6 / Claim 4，
  `InvestigationGraphCanvas.jsx:14-19`），选中画光环 + 白描边，`isUnconfirmed`
  （review_pending 回落态）画虚线圈，缩放 ≥1.2 才画标签（24-70 行）。
- `investigationGraphConstants.js`：颜色/tooltip/unconfirmed 判定，独立成模块并配测试。
- `workbench/`（12 文件）：EvidenceListPanel、EventTimelinePanel、GraphTabPanel、
  DetailPanel（609 行主面板）+ 7 个表单（CaptureEvidence/CreateEvent/LinkEvidence/
  RefreshNarrative/ReportEvidence/ReviewDecision/SubmitAnalysis）。
  **该目录只被死页面 `pages/Investigation.jsx` 引用**；GraphTabPanel 头注释
  （1-6 行）说明它复用 Canvas + useInvestigationGraph，"前端从不增删节点，一切以
  服务端 selection 为准"。`refreshSignal` 递增即重读服务端图谱（19-26 行）。

### timeline/ — 簇调查抽屉

`ClusterInvestigationDrawer.jsx`（193 行）：右滑抽屉（AnimatePresence + spring），
三块内容——AI 分析结论（无 `llm_summary` 时显示 Analyze 按钮，有则 Reanalyze，
`ClusterInvestigationDrawer.jsx:69-89`）、簇内文件路径过滤、Virtuoso 虚拟文件列表。
`clusterKey`（26-31 行）把 `group_descriptor` 序列化成 Set 的 key，供
`analyzingClusters` 去重。全部 props 受控，数据/动作在 Timeline 页。

### files/、tasks/、filters/、knowledge-graph/、llm-descriptions/ — 页面子组件

- `files/`（7 个）：FilesHeader、FileFilters、ExtractionControls、FileListTable、
  ExtensionAnalysisTab、OfficePreviewTab、ReanalyzeModal——把 1047 行的 Files 页拆薄。
- `tasks/`（5 个）：TaskTable（状态/进度/优先级列 + 操作）、CreateTaskModal、
  CreateCaseModal、AddTasksToCaseModal、ComposeCaseModal。
- `filters/`（3 个）：FilterProfileSelector/FilterProfileEditor/ScenarioPicker，
  消费 filterSlice。
- `knowledge-graph/`（4 个）：SearchTab/EntitiesTab/RelationshipsTab + graphConstants
  （NODE_COLORS 共享色板）。
- `llm-descriptions/`（2 个）：LLMTaskSelector、LLMReanalyzeModal——**只被死页面
  LLMDescriptions.jsx 使用**，同属死代码。

## 复用关系总图

```
index.jsx ─ ToastProvider(common/ToastContext) ┐
App.jsx ─ ErrorBoundary ─ Layout(common+TaskSelector) ┤
  └ Outlet → 各页面                                │
       ForensicReportPage → reports/* → renderers/registry ─┘（注册表扩展）
       CaseIntelligence → case-intelligence/report-reader/*
       AnalysisCenter  → case-intelligence/{ClusterFilesDrawer,FileClustersDrawer}
       Timeline        → timeline/ClusterInvestigationDrawer
       Files           → files/*
       Tasks/Cases     → tasks/* + ConfirmDialog + Modal
       (死) pages/Investigation.jsx → investigation/workbench/* → InvestigationGraphCanvas
       (死) pages/InvestigationGraph.jsx → InvestigationGraphCanvas
```

## 二轮补充走读：两个代表性组件的关键代码

### InvestigationGraphCanvas.nodeCanvasObject — canvas 自绘节点

`web/src/components/investigation/InvestigationGraphCanvas.jsx:24-70`（节选）：

```jsx
const NODE_RADIUS = {
    InvestigationEvent: 7,
    Evidence: 6,
    Analysis: 6,
    Claim: 4,
};

const nodeCanvasObject = useCallback((node, ctx, globalScale) => {
    const radius = NODE_RADIUS[node.label] || 5;
    const color = getNodeColor(node);
    const isSelected = selectedNodeId && node.id === selectedNodeId;

    // Halo / glow
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius + (isSelected ? 5 : 2), 0, 2 * Math.PI);
    ctx.fillStyle = color + (isSelected ? '70' : '30');   // 8 位 hex 透明度
    ctx.fill();
    ...
    // review_pending fallback 的 Analysis/Claim：虚线描边标注 Unconfirmed
    if (isUnconfirmed(node)) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius + 2, 0, 2 * Math.PI);
        ctx.setLineDash([3, 3]);
        ...
    }
    if (globalScale >= 1.2) {                              // 缩放足够才画标签
        ctx.font = `${11 / globalScale}px Sans-Serif`;
        ...
    }
}, [selectedNodeId]);
```

逐块解释：

- `NODE_RADIUS[node.label]`：**半径即类型编码**——事件最大（7），证据/分析次之（6），
  claim 最小（4），不用图例也能一眼分层；
- 光环 + `color + '70'/'30'`：直接在 6 位 hex 后拼两位透明度实现选中高亮（选中更实、
  未选中只留淡晕），零依赖的 canvas 惯用法；
- `isUnconfirmed(node)`（来自 `investigationGraphConstants`，独立成模块并配测试）画
  虚线圈——`review_pending` 的 Analysis/Claim 在视觉上与已采纳的区分开，这是
  "前端从不增删节点，一切以服务端 selection 为准"原则在渲染层的表达；
- `globalScale >= 1.2` 才 `fillText`：缩小视图时省掉数百个文本绘制的性能保护；
  `11 / globalScale` 让标签在缩放中保持恒定屏幕像素大小。

### ClusterInvestigationDrawer.clusterKey — 簇身份的前端序列化

`web/src/components/timeline/ClusterInvestigationDrawer.jsx:26-32`：

```js
const clusterKey = (c) => JSON.stringify(c?.group_descriptor || {
    bucket_index: c?.bucket_index,
    bucket_seconds: c?.bucket_seconds,
    event_type: c?.event_type,
    parent_directory: c?.parent_directory || '',
});
```

- 首选后端下发的 `group_descriptor`（唯一可信身份），只有旧数据没有 descriptor 时才
  用散落的四个字段拼一个等价对象——兜底字段的选取与后端簇定义（CPP_REST_API.md
  2.2 节：`time_window+event_type` 唯一标识簇，`parent_directory` 可选）一致；
- `JSON.stringify` 做 key 让 `analyzingClusters: Set<string>` 可以 O(1) 判断"该簇是否
  正在分析"（Timeline 页的 `clusterIdentity` 是同一逻辑的另一份实现——见 Pages.md
  走读，两处需同步演进）。

### Button — variant/size 的查表实现

`web/src/components/common/Button.jsx:23-41`（节选）是"样式即约定"的代表：

```jsx
const variants = {
  primary:
    'bg-gradient-to-r from-primary-600 to-primary-500 text-white hover:from-primary-500 hover:to-primary-400 focus:ring-primary-500 shadow-md hover:shadow-glow-primary active:scale-[0.97]',
  secondary:
    'bg-slate-200/80 text-slate-800 hover:bg-slate-300/80 focus:ring-slate-400 dark:bg-slate-700/60 dark:text-slate-200 dark:hover:bg-slate-600/60 active:scale-[0.97]',
  danger:
    'bg-gradient-to-r from-rose-600 to-rose-500 text-white hover:from-rose-500 hover:to-rose-400 focus:ring-rose-500 shadow-md hover:shadow-glow-danger active:scale-[0.97]',
  outline:
    'border-2 border-primary-500/50 text-primary-600 dark:text-primary-400 hover:bg-primary-50/50 dark:hover:bg-primary-950/30 focus:ring-primary-500 active:scale-[0.97]',
  ghost:
    'text-slate-600 dark:text-slate-400 hover:bg-slate-100/60 dark:hover:bg-slate-800/60 focus:ring-slate-400 active:scale-[0.97]',
};
const sizes = {
  sm: 'px-3.5 py-1.5 text-sm gap-1.5',
  md: 'px-5 py-2.5 text-sm gap-2',
  lg: 'px-7 py-3 text-base gap-2.5',
};
const classes = clsx(base, variants[variant] || variants.primary, sizes[size], className);
```

- 每个 variant 都是完整的明/暗双色字符串（`dark:` 变体内联），调用方不需要知道主题
  存在——这是全站组件暗色化的基本手法；
- `variants[variant] || variants.primary`：非法值静默回落主样式，与渲染器注册表的
  "未知名回落表格"同一取向（宁可降级不可崩）；
- `active:scale-[0.97]` 按压缩放 + `shadow-glow-*`（styles/index.css 定义）是按钮的
  全部动效，无独立 CSS 文件。

## 与后端契约的对应

组件层是响应字段的"最终消费者"，与契约的对应集中在三处（对照
[ServiceContracts.md](../../reference/ServiceContracts.md)）：

1. **reports/ 渲染器族 ↔ 报告 manifest 契约**：manifest 每个 category 携带 `renderer`
   名，`renderers/registry.js` 按名查 Map、未注册回落 GenericTableRenderer——新增
   artifact 类型（后端 report_evidence/report_generation 的产出）只需前端注册渲染器，
   不改分发组件。分页读 `GET /api/reports/{id}/categories/{cid}/pages/{page}`、检索
   `GET /api/reports/{id}/search`（返回 `{total, offset, limit, ...}`）的字段被
   ReportWorkspace/ReportSearch 直接渲染。
2. **GenerateReportPanel ↔ 202 准入 + 状态机**：面板的进度文案跟着
   `useReportGenerationPolling` 的 `admitted/running/completed/failed` 走，ERROR_HINTS
   表（`GenerateReportPanel.jsx:12-26`）覆盖的 409（无报告证据）等错误码与
   Python_REST_API.md §6.3 的响应语义一致（另见 ErrorCodes.md §5.3 的 410/409 契约）。
3. **InvestigationGraphCanvas ↔ 调查图只读契约**：节点只有
   `InvestigationEvent/Evidence/Analysis/Claim` 四类（半径表），`isUnconfirmed` 的
   review_pending 回落语义来自 `/api/investigation` 域的审阅模型；canvas 组件不发起
   任何请求，图结构完全由服务端 `selection` 决定（GraphTabPanel 头注释）。

## 注意

1. **不要引用 `common/useToast` / `common/toastContext`**——应从
   `common/ToastContext` 导入；AnalysisCenter 的崩溃即由此而来（Pages.md）。
2. **`ThemeProvider` 是死组件**：App.jsx 内联了同样逻辑，二者并存会让人误以为有两
   套主题机制；实际只有 `settings.theme` 一份生效状态。
3. **`investigation/workbench/` 与 `llm-descriptions/` 是死组件组**，除非先恢复对应
   路由，否则不要在其上叠加新功能。
4. Modal 打开时会锁 `document.body.style.overflow`（`Modal.jsx:13-23`），嵌套弹窗
   关闭顺序异常时可能出现滚动锁残留（unmount 时统一 `unset` 兜底）。

## 验证

```bash
cd web && npx vitest run src/components/
# 覆盖：Layout、TaskSelector、reports 族（含 registry/GenericTableRenderer）、
# InvestigationGraphCanvas、workbench/ReportEvidenceForm、reader sections。
# 死组件组的测试仍会跑——通过不代表组件可达。
```

**最后更新**: 2026-08-24（二轮深化：补代码走读与契约对应）
