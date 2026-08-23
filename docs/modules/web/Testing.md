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

**最后更新**: 2026-08-24（新建，解释式）
