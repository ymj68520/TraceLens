# 测试体系（Vitest + React Testing Library）

## 为什么要有这篇文档

前端有 48 个测试文件、没有独立 jest 配置——Vitest 直接复用 `vite.config.js` 的
`test` 块。测试的价值集中在三类资产：路由表断言（routes.test）、轮询 hooks 的
时序用例（deferred promise 模式）、service 层的 axios mock 断言（端点/编码契约）。
读懂这三类模式，新增测试就不必重新发明轮子；同时要注意**死代码页面也有测试**，
绿灯不等于页面可达。

## 代码位置

- 配置：`web/vite.config.js:14-19`（test 块）
- 全局 setup：`web/src/test/setup.js`
- 渲染助手：`web/src/test/renderWithRouter.jsx`
- 测试文件：与被测对象同目录共置（`*.test.js(x)`），共 48 个

## 核心概念

- **零配置复用**：Vitest 读 `vite.config.js`，不需要 `vitest.config.js`；
  `globals: true` 意味着测试文件可以不 import `describe/test/expect`（部分文件仍
  显式导入，风格混用但不报错）。
- **mock 分层**：service 测试 mock `./api`（axios 实例级）；hook 测试 mock service
  或 react-redux；组件测试 mock 重子组件/页面级依赖。
- **依赖注入是可测性的来源**：`FixtureReportDataSource`、hooks 第二参的
  `fetchGeneration` 等注入点让时序测试无需 fake timers。

## 走读

### 配置块

`web/vite.config.js:14-19`：

```js
test: {
  environment: 'jsdom',
  globals: true,
  setupFiles: './src/test/setup.js',
  css: true,
},
```

逐项：jsdom 提供 DOM；globals 免 import；`css: true` 让组件测试处理 CSS import
（Tailwind 的 `@apply` 类）；无 `coverage` 配置。运行方式：`npm test`（watch）、
`npm run test:watch`、CI 用 `npx vitest run`。

### setup.js — cleanup 与 matchMedia

`web/src/test/setup.js` 全文做两件事：

```js
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => cleanup());

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query) => ({ matches: false, media: query, onchange: null,
    addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {},
    dispatchEvent: () => false, }),
});
```

`@testing-library/jest-dom/vitest` 注册 `toBeInTheDocument/toHaveAttribute` 等匹配器
（Vitest 版入口）；自动 cleanup 防止测试间 DOM 泄漏；matchMedia 桩是 jsdom 缺失该
API 的标准补丁（Tailwind/forms 相关组件需要）。

### renderWithRouter 助手

`web/src/test/renderWithRouter.jsx:1-7`：

```js
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

export function renderWithRouter(ui, { route = '/' } = {}) {
  window.history.pushState({}, 'Test page', route);
  return render(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>);
}
```

两步：先把真实 `window.history` 推到目标 route（让组件内 `useLocation` 之外的
浏览器 API 读到正确路径），再用 `MemoryRouter` 包裹渲染。局限：**不含 Redux
Provider 与 ToastProvider**——需要 store 的组件测试（Layout、TaskSelector）都自己
`configureStore` 一个最小 store；需要 toast 的组件需自带 Provider 或 mock。更完整的
路由断言则绕开渲染，直接用 `matchRoutes`（见下）。

### 48 个测试文件的分布

| 目录 | 数量 | 代表文件 |
|---|---|---|
| src/pages/（根） | 7 | routes.test.jsx、CaseIntelligence.test.jsx、ForensicReportPage.generation.test.jsx、LegacyReportRedirect.test.jsx、（死页面）InvestigationGraph.test.jsx、Investigation.test.jsx |
| src/pages/Investigation/ | 7 | Investigation.test.jsx、FinalReportViewer.test.jsx、finalReportIntegrity.test.js、hooks/×4 |
| src/hooks/ | 9 | useReportGenerationPolling.test.js、useTaskAutoTrigger.test.js、useStaleResource.test.js 等 |
| src/services/ | 7 | llmService(.polling).test.js、investigationService、reportDataSource、reportService、ossService、forensicsService |
| src/components/ | 16 | Layout、TaskSelector、reports 族×7、InvestigationGraphCanvas、workbench/ReportEvidenceForm |
| src/pages/WeChatGraph/hooks | 1 | useWeChatGraph.test.js |
| src/test/ | 1 | smoke.test.jsx |

### 代表性测试 1：routes.test.jsx — 不渲染的路由表断言

`web/src/routes.test.jsx:4-22` 先把四个重组件 mock 成空函数（避免拖入整棵依赖树），
再直接断言 `appRoutes` 结构：

```js
vi.mock('./pages/CaseIntelligence', () => ({
  default: function CaseIntelligence() { return null; },
}));
...
import { appRoutes } from './routes';

test('exposes report migration routes without replacing the legacy redirect', () => {
  const childRoutes = appRoutes.find((route) => route.path === '/').children;
  const legacyRoute = childRoutes.find((route) => route.path === 'case-report');
  ...
  expect(matchRoutes(appRoutes, '/case-intelligence?taskId=t1')).not.toBeNull();
```

要点：`appRoutes` 被导出正是为了这种测试（routes.jsx:27）；`matchRoutes` 静态匹配
路径，比渲染整个 RouterProvider 快且稳。该文件守护的是"报告路由迁移不破坏旧跳转"
的契约（两个 test：迁移路由存在 + legacy 重定向指向 TaskReportRedirect/
CaseReportRedirect）。

### 代表性测试 2：hooks 的 axios/时序 mock 模式

**模式 A：mock react-redux + service（useTaskAutoTrigger.test.js:7-14）**

```js
vi.mock('react-redux', () => ({
  useDispatch: vi.fn(),
  useSelector: vi.fn(),
}));

vi.mock('../store/taskSlice', () => ({
  fetchTasksSilent: vi.fn((filters) => ({ type: 'tasks/fetchTasksSilent', payload: filters })),
}));
```

配合 `useSelector.mockImplementation((selector) => selector({...最小 state}))` 与
`useDispatch.mockReturnValue(dispatch)`，hook 在无真实 store 的环境下运行；
`renderHook` + `waitFor` 验证 dispatch 次数与参数（35-36 行）。

**模式 B：deferred promise 逐步推进轮询（useReportGenerationPolling.test.js:8-16、27-56）**

```js
function deferred() {
  let resolve; let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve; reject = nextReject;
  });
  return { promise, resolve, reject };
}

const steps = [deferred(), deferred(), deferred()];
const fetchGeneration = vi.fn()
  .mockReturnValueOnce(steps[0].promise)
  .mockReturnValueOnce(steps[1].promise)
  .mockReturnValueOnce(steps[2].promise);
```

测试用 `await act(async () => steps[i].resolve(generation('admitted')))` 逐步放行
每次轮询的响应，从而精确断言：terminal 后不再发请求（`toHaveBeenCalledTimes(3)`）、
task 切换后旧响应被丢弃（"task switch drops the late response"用例，82-101 行）、
503 瞬时错误继续轮询（103-131 行，注意第 107-109 行先 `rejected.catch(()=>{})`
压制 unhandled rejection 的注释）、null submission 从不轮询（133-141 行）。
`intervalMs: 0` 让 `setTimeout` 立即触发，全程不需要 fake timers。

**模式 C：service 测试 mock axios 实例（llmService.test.js:5、reportService.test.js:5）**

```js
vi.mock('./api', () => ({ pythonApi: { post: vi.fn() } }));
...
pythonApi.post.mockResolvedValue({ success: true });
await analyzeDLL({ filePath: '/tmp/test.dll', filesDbPath: '/tmp/files.db' });
expect(pythonApi.post).toHaveBeenCalledWith('/api/llm/analyze/dll', {
  file_path: '/tmp/test.dll', files_db_path: '/tmp/files.db', prompt: null,
});
```

`reportService.test.js:13-24` 进一步断言 `encodeURIComponent` 行为（categoryId 里的
`/` 被编码成 `%2F`）——这是 URL 契约测试的范本。

### 代表性测试 3：组件测试的最小 store

`web/src/components/Layout/Layout.test.jsx:10-25` 展示了"局部真 store + mock 掉重
依赖"的组合：

```js
function renderLayout(route) {
  const store = configureStore({
    reducer: {
      settings: () => ({ theme: 'light', showTerminal: false, language: 'zh' }),
      ui: () => ({ sidebarOpen: true }),
    },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[route]}>
        <Layout><div>report content</div></Layout>
      </MemoryRouter>
    </Provider>,
  );
}
```

reducer 直接用返回字面量的函数充当"冻结 state"，再 mock 掉 TaskSelector
（`vi.mock('../common/TaskSelector', ...)`，第 8 行）。断言走角色查询：
`getByRole('link', { name: '证据研判' })` 且 `toHaveAttribute('href', '/case-intelligence?task_id=task-1')`
——守护侧栏的 query 透传契约。`TaskSelector.test.jsx` 同构（mock taskSlice 的两个
action、断言三个路由下出现 combobox）。`CaseIntelligence.test.jsx:7-15` 则把两个
重子视图 mock 成带 testid 的 div，验证 tab 切换与 scope 传递——组件壳测试的标准打法。

### smoke.test.jsx

最小冒烟：`renderWithRouter(<Smoke/>)` + `getByRole('heading')`，验证 jsdom + RTL +
路由助手的基线可用。

## 协作

- Testing ↔ Overview.md：test 块内嵌于 vite.config.js；
- Testing ↔ Hooks.md：三个轮询 hooks 的行为契约由 deferred 用例锁定；
- Testing ↔ Services.md：`FixtureReportDataSource` 与 `HttpReportDataSource` 的双实现
  是报告组件可离线测试的基础；
- Testing ↔ Pages.md：routes.test/CaseIntelligence.test 守护路由迁移；死页面的测试
  （InvestigationGraph.test、根目录 Investigation.test）仍在跑。

## 二轮补充走读：两条最值得抄的测试

### "task switch drops the late response"（§23）— 防陈旧不变量的可执行规格

`web/src/hooks/useReportGenerationPolling.test.js:81-98`：

```js
test('task switch drops the late response of the old generation (§23)', async () => {
  const late = deferred();
  const next = deferred();
  const fetchGeneration = vi.fn()
    .mockReturnValueOnce(late.promise)     // 第 1 次轮询（任务 A）→ 先挂起
    .mockReturnValueOnce(next.promise);    // 切到任务 B 后的第 2 次 → 也挂起
  const { result, rerender } = renderHook(
    ({ submission }) => useReportGenerationPolling(submission, { intervalMs: 0, fetchGeneration }),
    { initialProps: { submission: SUBMISSION_A } },
  );

  await act(async () => rerender({ submission: SUBMISSION_B }));   // 切任务
  await act(async () => late.resolve(generation('completed', 'rg_1')));  // A 的响应晚到
  await act(async () => next.resolve(generation('admitted', 'rg_2', { task_id: 't2' })));

  await waitFor(() => expect(result.current.generation?.generation_id).toBe('rg_2'));
  // Task A 的晚返回 completed 绝不写入 B 的状态，也绝不携带 A 的 report。
  expect(result.current.generation.report_id).toBeUndefined();
});
```

逐块解释：

- 两个 deferred 把"先发出 A 的请求、后切到 B、A 的响应最后才回来"这一竞态**手工
  排成确定顺序**——不依赖 fake timers、不依赖真实网络时序；
- 断言分两层：正向（`generation_id === 'rg_2'`）与反向（`report_id` 为 undefined——
  completed 的响应本来会带 report，没带上就证明它被丢弃了）；
- 该用例与 hook 的 `identityRef` 实现互为规格：改坏 identity 判断，这条测试立刻红。

### CaseIntelligence.test.jsx — 壳组件的 testid 协议

`web/src/pages/CaseIntelligence.test.jsx:5-16`：

```js
vi.mock('../components/case-intelligence/report-reader/IntelligenceReportReader', () => ({
  default: ({ taskId }) => <div data-testid="legacy-reader">legacy:{taskId}</div>,
}));

vi.mock('./ForensicReportPage', () => ({
  default: ({ scopeType, scopeId }) => (
    <div data-testid="forensic-page">forensic:{scopeType}:{scopeId}</div>
  ),
}));
```

- mock 组件把**收到的 props 渲染进字符串**（`forensic:{scopeType}:{scopeId}`），
  断言即可验证"壳组件把 URL 正确翻译成了 scope"——不用渲染真阅读器，也不用 mock
  任何 service；
- 三个用例覆盖默认 tab、`?tab=intelligence` 切换、case/task 双 scope——正好是
  Pages.md 里 CaseIntelligence 的三条行为契约。

### useTaskAutoTrigger.test.js — "无 store 跑 hook"的完整最小样本

`web/src/hooks/useTaskAutoTrigger.test.js:1-50`（节选）把模式 A 展开到可复制：

```js
vi.mock('react-redux', () => ({
  useDispatch: vi.fn(),
  useSelector: vi.fn(),
}));

vi.mock('../store/taskSlice', () => ({
  fetchTasksSilent: vi.fn((filters) => ({ type: 'tasks/fetchTasksSilent', payload: filters })),
}));

test('refreshes tasks without creating a legacy report when a task is completed', async () => {
  const dispatch = vi.fn(() => ({
    unwrap: vi.fn().mockResolvedValue({
      tasks: [{ id: 'task-1', status: 'completed', output_files_db: '/tmp/files.db' }],
    }),
  }));
  useDispatch.mockReturnValue(dispatch);
  useSelector.mockImplementation((selector) => selector({
    tasks: { filters: { status: 'all' } },
    settings: { autoRefresh: true, refreshInterval: 60_000 },
  }));

  const { unmount } = renderHook(() => useTaskAutoTrigger());
  await waitFor(() => expect(dispatch).toHaveBeenCalledTimes(1));
  expect(fetchTasksSilent).toHaveBeenCalledWith({ status: 'all' });
  unmount();
});
```

逐块解释：

- mock 掉的 `fetchTasksSilent` 返回**普通 action 对象**（不是真 thunk）——hook 只调用
  dispatch，不 care 中间件；`dispatch` 的返回值造一个带 `unwrap` 的对象以匹配
  `.unwrap()` 调用点；
- `useSelector.mockImplementation((selector) => selector({...最小 state}))` 是关键一行：
  selector 由被测 hook 传入，喂给它一个只含所需分支的字面量 state——不需要
  `configureStore`；
- `refreshInterval: 60_000` 让 interval 不触发，测试只验证"立即一次"的 dispatch；
  `unmount()` 在断言后清理（该文件未依赖自动 cleanup 也安全）；
- 用例名本身就是行为契约：任务 completed 时**只静默刷新、不再触发 legacy 报告**
  （R2 工作流把报告生成改为显式的回归守护）。

## 与后端契约的对应

测试目录里有两类"契约守护测试"，对应关系如下（对照
[ServiceContracts.md](../../reference/ServiceContracts.md)）：

1. **URL 契约测试**：`reportService.test.js:13-24` 断言 `encodeURIComponent` 把
   categoryId 里的 `/` 编码为 `%2F`——守护的是
   `GET /api/reports/{report_id}/categories/{category_id}/pages/{page}` 的路径参数
   契约（未编码的 `/` 会被 FastAPI 路由劈开，404）。
2. **请求体形状测试**：`llmService.test.js` 断言 `analyzeDLL` 发出的 body 是
   `{file_path, files_db_path, prompt}`（snake_case）——Python 侧
   `AnalyzeRequest`/`DLLAnalyzeRequest` 的字段名契约由这条测试在前端锁定。
3. **状态机契约测试**：三个轮询 hooks 的 deferred 用例锁定 `admitted/running`、
   `queued/running` 继续集合与终态停止——与 Python_REST_API.md §6.3/§7/§8 的状态机
   逐字对应。后端改状态字面量时，这批测试是最早的报警器（比页面行为更早）。
4. **路由迁移契约**：`routes.test.jsx` 的 `matchRoutes` 断言守护 `/reports/task/:taskId`
   → `/case-intelligence` 的迁移不破坏旧跳转（Pages.md 走读）。
5. **反向提醒**：`ossService.test.js`、`investigationService.test.js` 等只断言请求
   形状，不断言响应——后端响应字段的回归（如 `files` → `largest_files` 改名）不会被
   前端测试抓住，只能靠 Services.md 的"端点→响应字段要点"表人工核对。

## 注意

1. **绿灯 ≠ 可达**：`pages/InvestigationGraph.test.jsx`、`pages/Investigation.test.jsx`
   测试的是无路由页面（Pages.md 死代码清单），清理死代码时应连测试一起删。
2. **renderWithRouter 不带 store/toast**——复用前先确认被测组件是否需要补 Provider。
3. **没有 coverage 统计**（test 块未配 coverage），无法量化盲区；从文件分布看，
   pages 大文件（Files/Timeline/Cases/KnowledgeGraph）与 common 大件
   （ConfirmDialog/TerminalOutput）无直接测试。
4. `globals: true` 下测试文件可以省 import，但新增文件建议保持显式导入（仓库主流
   风格仍是显式）。

## 验证

```bash
cd web && npx vitest run            # 全量 48 个文件
cd web && npx vitest run src/routes.test.jsx
cd web && npx vitest run src/hooks/useReportGenerationPolling.test.js
cd web && npm run lint              # ESLint（--max-warnings 0）
```

**最后更新**: 2026-08-24（二轮深化：补代码走读与契约对应）
