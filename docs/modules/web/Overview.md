# Web 前端架构总览（Overview）

## 为什么要有这篇文档

TraceLens 是"一个仓库、三个后端、一个前端"的结构：C++ 取证引擎（Crow，默认 :8080）、
Python FastAPI 智能服务（:8090）、分布式 C/S 服务（python_service/server，:8091），全部由
`web/` 下这一个 SPA 消费。三个后端、三套鉴权、三种数据契约，任何一个环节的地址推导或
代理规则出错，页面就会整片离线。本文从入口链、构建、HTTP 客户端、代理表四个维度把
前端骨架讲清楚，是其余七篇模块文档的地图。

## 代码位置

- 入口与路由：`web/src/index.jsx`、`web/src/App.jsx`、`web/src/routes.jsx`
- HTTP 客户端：`web/src/services/api.js`
- 构建与开发服务器：`web/vite.config.js`、`web/package.json`
- 全局样式：`web/src/styles/index.css`、`web/tailwind.config.js`
- 页面骨架：`web/src/components/Layout/Layout.jsx`

技术栈（`web/package.json`）：React 18.2 + Vite 5 + Redux Toolkit 2 + react-router-dom 6 +
Tailwind 3 + axios 1.6；可视化用 d3 / react-force-graph-2d / recharts；动效 framer-motion；
图标 lucide-react；虚拟列表 react-virtuoso。**没有 TypeScript**，全部是 `.js/.jsx`。

## 核心概念

1. **入口链**：`index.html` → `src/index.jsx`（挂载 Provider/Toast/Router）→ `src/routes.jsx`
   （`createBrowserRouter`）→ `src/App.jsx`（主题 + ErrorBoundary + Layout + `<Outlet/>`）。
2. **三个 axios 客户端**：`api`（C++ 后端，同源相对路径）、`pythonApi`（:8090）、`csApi`
   （:8091），共用"响应拦截器直接返回 `response.data`"的解包约定。
3. **动态 host 推导**：Python/C/S 客户端不用写死 `localhost`，而是按浏览器当前访问的
   hostname 拼端口，保证跨机访问可用。
4. **Vite 代理**：开发态把同源请求按前缀分发给三个后端；生产态 C++ 端口仍走相对路径。

## 走读

### 入口链

`web/src/index.jsx:10-18` 是整个应用的挂载点，Provider 嵌套顺序决定了一切上层能力的可用性：

```jsx
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Provider store={store}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </Provider>
  </React.StrictMode>
);
```

逐块解释：

- `Provider store`：Redux store（见 Store.md），任何路由下的页面都能读 `state.tasks` 等；
- `ToastProvider`：来自 `components/common/ToastContext.jsx`，向全部页面注入 `useToast()`；
- `RouterProvider`：路由树由 `routes.jsx:136` 的 `createBrowserRouter(appRoutes)` 创建，
  `appRoutes` 被导出供 `routes.test.jsx` 直接做 `matchRoutes` 断言（见 Testing.md）。

`web/src/App.jsx:7-25` 只做两件事：监听 `state.settings.theme` 给 `<html>` 加/去 `dark`
class（暗色主题开关，Tailwind `darkMode: 'class'`），以及用 `ErrorBoundary` 包住
`Layout + <Outlet/>`——任何页面渲染抛错都只会落到兜底 UI 而不是白屏。

路由树（`web/src/routes.jsx:27-134`）分两层：`/login` 独立成页（无侧栏），其余 23 个
子路由项（含 index 重定向与 `/reports/task|case` 两条迁移路由）全部挂在 `path: '/'`
的 `App` 下；`index: true` 用 `<Navigate to="/dashboard" replace/>`
重定向。唯一懒加载的页面是微信关系图：

```jsx
const WeChatGraph = React.lazy(() => import('./pages/WeChatGraph/WeChatGraph'));
```

（`web/src/routes.jsx:25`），对应路由 `wechat-graph` 包了 `<React.Suspense fallback={...}>`
（`routes.jsx:69-75`）。构建产物里能看到独立的 `WeChatGraph-*.js` chunk。

### 构建（vite.config.js）

`web/vite.config.js:66-79` 的 `build` 块做了两件值得注意的事：

```js
build: {
  outDir: 'dist',
  assetsDir: 'assets',
  sourcemap: true,
  rollupOptions: {
    output: {
      manualChunks: {
        'react-vendor': ['react', 'react-dom', 'react-router-dom'],
        'd3-vendor': ['d3'],
        'redux-vendor': ['@reduxjs/toolkit', 'react-redux'],
      },
    },
  },
},
```

- `sourcemap: true`：生产包带 sourcemap，方便线上报错回溯到源码；
- `manualChunks`：手动拆出 `react-vendor` / `d3-vendor` / `redux-vendor` 三个长缓存包
  （`web/dist/assets/` 下已能看到对应的产物文件），业务代码变动时 vendor chunk 的 hash
  不变，浏览器可继续用缓存。

`vite.config.js:14-19` 还内嵌了 Vitest 配置（`environment: 'jsdom'`、`globals: true`、
`setupFiles: './src/test/setup.js'`、`css: true`），详见 Testing.md。

### 三个 axios 客户端（services/api.js）

`web/src/services/api.js:29-44` 创建前两个客户端：

```js
const api = axios.create({
  baseURL: API_BASE_URL,           // '' → 同源相对路径，走 Vite 代理
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000, // 30 seconds
});

const pythonApi = axios.create({
  baseURL: PYTHON_API_BASE_URL,    // http://<当前host>:8090
  headers: { 'Content-Type': 'application/json' },
  timeout: 60000, // 60 seconds (LLM 请求可能较慢)
});
```

端口与地址推导（`api.js:4-26`）：

- `CPP_PORT = VITE_CPP_PORT || HTTP_SERVER_PORT || '8080'`，`PYTHON_PORT='8090'`，
  `CS_PORT='8091'`；
- `currentHost()`（`api.js:12-17`）在浏览器环境取 `window.location.hostname`，注释明确
  说明了动机：跨机访问时 `localhost` 会指向客户端自身，导致 Dashboard 全部离线；
- 环境变量覆盖顺序：`VITE_API_BASE_URL`（C++）、`VITE_PYTHON_API_URL`、`VITE_CPP_API_URL`、
  `VITE_CS_API_URL`。`CPP_BASE_URL` / `PYTHON_API_BASE_URL` 被导出给 Terminal 页展示端口
  （`pages/Terminal.jsx:6-11`）。

三个客户端的拦截器行为**有意不同**（这是本项目 token 语义的核心）：

| 客户端 | token 键 | 401 行为 | 响应解包 |
|---|---|---|---|
| `api`（C++） | `localStorage.auth_token` | 清 token 并 `window.location.href='/login'`（`api.js:73-77`） | `response.data` |
| `pythonApi` | 无鉴权 | 不跳转 | `response.data` |
| `csApi` | `localStorage.cs_auth_token` | 仅清 `cs_auth_token`，**不跳转**（`api.js:168-171`，注释：分布式鉴权独立于本地模式） | `response.data` |

`csApi` 的创建见 `api.js:131-140`，注释点明它与 `pythonApi`（旧版 httpserver :8090）和
`api`（C++ :CPP_PORT）三者互不相同。所有拦截器都带 `console.log` 请求/响应日志（如
`api.js:54、66`），开发期方便，生产期噪音大（Terminal 页的 web 日志 Tab 会原样收录，
见 I18nTheming.md）。

### Vite 代理表（开发态）

`web/vite.config.js:4-10` 先合并当前目录与**上级目录**（仓库根）的 env 文件：

```js
const env = { ...loadEnv(mode, process.cwd(), ''), ...loadEnv(mode, '..', '') };
const cppTarget = env.VITE_CPP_PROXY_TARGET
  || `http://localhost:${env.HTTP_SERVER_PORT || '8080'}`;
```

代理规则（`vite.config.js:22-64`）按前缀从长到短排列，短前缀 `/api` 兜底：

| 前缀 | 目标 | 说明 |
|---|---|---|
| `/csapi` | `http://localhost:8091` | `rewrite` 去掉 `/csapi` 前缀 |
| `/tasks` | `cppTarget`（:8080） | C++ 任务接口 |
| `/api/reports`、`/api/graphiti`、`/api/llm`、`/api/office`、`/api/db`、`/api/wechat`、`/api/investigation` | `http://localhost:8090` | Python 服务 |
| `/api`（兜底） | `cppTarget` | C++ 其余接口（forensics/system/search/filter…） |

注意一个不对称：`pythonApi` 在浏览器里**直连** `http://<host>:8090`（不经过代理，依赖
Python 服务开 CORS），而 `api` 走同源相对路径 + 代理。生产部署时 `api` 的相对路径仍然
成立（前端与 C++ 同源），`pythonApi` 则必须保证 8090 可达。

### 环境变量清单

| 变量 | 作用 | 读取处 |
|---|---|---|
| `VITE_CPP_PROXY_TARGET` | 开发代理的 C++ 目标 | `vite.config.js:9` |
| `HTTP_SERVER_PORT` | C++ 端口兜底（代理与客户端两处） | `vite.config.js:10`、`api.js:4` |
| `VITE_CPP_PORT` | C++ 客户端端口 | `api.js:4` |
| `VITE_API_BASE_URL` | C++ 客户端 baseURL | `api.js:21` |
| `VITE_PYTHON_API_URL` | Python 客户端 baseURL | `api.js:23` |
| `VITE_CPP_API_URL` | 导出的 CPP_BASE_URL | `api.js:25` |
| `VITE_CS_API_URL` | 分布式客户端 baseURL | `api.js:131` |

## 二轮补充走读：任务上下文与鉴权头

### TaskSelector — URL ↔ store 的双向同步

"当前在分析哪个镜像任务"是全应用最重要的上下文，而它的权威载体既不是 Redux 也不是
context，而是 **URL query 参数**。`web/src/components/common/TaskSelector.jsx:24-35`
实现了 URL → store 的回灌与反方向的补写：

```js
useEffect(() => {
  const urlTaskId = searchParams.get('taskId') || searchParams.get('task_id');
  if (urlTaskId && tasks.length > 0) {
    const task = tasks.find((t) => t.id === urlTaskId);
    if (task && (!currentTask || currentTask.id !== urlTaskId)) {
      dispatch(setCurrentTask(task));           // URL 有值 → 回灌 store
    }
  } else if (!urlTaskId && currentTask && isRelevantPage) {
    const paramName = location.pathname.startsWith('/case-report') ? 'taskId' : 'task_id';
    setSearchParams({ ...Object.fromEntries(searchParams), [paramName]: currentTask.id });
  }                                            // URL 无值但页面需要 → 从 store 补写
}, [searchParams, tasks, dispatch, currentTask, isRelevantPage, setSearchParams, location.pathname]);
```

逐块解释：

- `searchParams.get('taskId') || searchParams.get('task_id')`：兼容两种拼写。历史路由
  `/reports/task/:taskId` 用驼峰，任务上下文页用下划线——`handleTaskChange`（37-55 行）
  切换任务时**两个键都先删再写一个**，保证 URL 上永远不会同时残留两个互相矛盾的 id；
- 第一个分支是"链接进入"：用户从分享的 URL 直接打开 `/timeline?task_id=xxx`，
  `fetchTasks` 已在 18-22 行把列表拉齐，这里把命中的任务对象写进 `currentTask`；
- 第二个分支是"导航进入"：直接点侧栏进入任务页而 URL 上没带 id 时，用 store 里记住的
  最近任务回填 URL——这解释了"换任务后跳到别的任务页，任务能跟着走"的体验；
- `relevantPaths`（15 行）只覆盖 11 个任务上下文前缀，Dashboard/Tasks/Cases 等全局页
  不渲染选择器也不写参数（57 行 `if (!isRelevantPage) return null`）。

### Layout.getLinkUrl — 侧栏的任务上下文透传

`web/src/components/Layout/Layout.jsx:48-57` 是上面机制的另一半（store/URL → 新链接）：

```js
const isActive = (path) =>
  location.pathname === path ||
  (location.pathname.startsWith('/reports/') && path.startsWith('/reports/'));

const getLinkUrl = (href) => {
  const taskContextPages = ['/timeline', '/files', '/case-intelligence', '/analysis-center',
    '/knowledge-graph', '/investigation-graph', '/investigation', '/android', '/memory',
    '/wechat-graph', '/oss', '/search', '/statistics'];
  if (currentTaskId && taskContextPages.includes(href)) {
    return `${href}?task_id=${currentTaskId}`;
  }
  return href;
};
```

- `currentTaskId` 取自 `searchParams.get('task_id')`（18 行），即"本页 URL 上的任务"；
- `getLinkUrl` 只在跳向 13 个任务上下文页时追加 `?task_id=`，跳 Dashboard 等全局页则
  保持干净 URL——于是"任务选择"可以一路跟着用户在分析页之间跳转；
- 两份列表并不一致：TaskSelector 的 `relevantPaths` 有 `/statistics`、`/llm-descriptions`
  （死路由）、`/case-report`，而 `taskContextPages` 多了 `/memory`、`/wechat-graph`。
  后果是：在 `/statistics` 上选任务会写 URL，但侧栏跳走时不透传——两处清单需要人工保持
  同步，是这条机制最脆的点。

### api 拦截器 — token 注入与错误增强

`web/src/services/api.js:47-90`（C++ 客户端）值得整段读一次，它是全部 service 错误
约定的源头：

```js
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;   // mock 登录的假 JWT 也照发
  }
  console.log('API Request:', config.method?.toUpperCase(), config.url, config.data);
  return config;
}, /* ... */);

api.interceptors.response.use(
  (response) => {
    console.log('API Response:', response.config.url, response.status, response.data);
    return response.data;                              // 全局解包：service 层拿到的就是 body
  },
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token');
      window.location.href = '/login';                 // 仅本地 token 走整页跳转
    }
    const enhancedError = {                            // 页面 catch 到的是这个形状
      message: error.message,
      status: error.response?.status,
      statusText: error.response?.statusText,
      data: error.response?.data,
      config: error.config,
    };
    return Promise.reject(enhancedError);
  },
);
```

三个要点：`return response.data` 是"函数返回值即响应体"约定的实现点（Services.md 的
前提）；`enhancedError` 让页面可以直接 `err?.message` 渲染、`err?.response?.status`
在 Files 页做 400/404/500 分级文案；401 整页跳转只此一处，`csApi` 的同名逻辑**不跳转**
（`api.js:168-171`，注释写明分布式鉴权独立于本地模式）。

## 与后端契约的对应

本篇的四块内容（入口链、构建、客户端、代理表）与
[ServiceContracts.md §7 前端 ↔ 双后端](../../reference/ServiceContracts.md)是同一事实的
两种视角，核对结论一致：

1. **代理表**：`vite.config.js:22-64` 的前缀表与 ServiceContracts.md §7.1 逐条相同
   （`/csapi` rewrite 剥前缀 → :8091；`/api/{reports,graphiti,llm,office,db,wechat,
   investigation}` → :8090；`/tasks` 与 `/api` 兜底 → C++）。已知漂移：
   `/api/markitdown` 不在专属前缀表里，dev 下若前端直调会落入 `/api` 兜底错打到 C++
   （当前无前端调用方，属潜在坑）。
2. **双形态**：dev 走 vite :3000 代理；prod 由 C++ `HTTPserver.cpp:109-151` 托管
   `web/dist`，Python/C/S 走 `http://<host>:8090/8091` 绝对地址直连（依赖 Python 开
   CORS、依赖 `currentHost()` 推导）。
3. **端口回退差异**：前端 `api.js:4` 的兜底是 `8080`，而 `run.sh:79` 的兜底是 `8666`
   ——改端口部署时除 `.env` 的 `HTTP_SERVER_PORT` 外还要同步
   `CPP_BACKEND_URL`/`PYTHON_SERVICE_URL`（ServiceContracts.md 附录 B 的五条检查清单）。
4. **健康探针三口径**：前端 Dashboard 消费 `getSystemHealth`（C++ `/api/system/health`）
   与 `getPythonHealth`（Python `/health`）；而 C++ 探 Python 也用 `/health`，Python 探
   C++ 用 `/api/health`，run.sh 探 C++ 用 `/api/system/health`——三个口径并存见
   ServiceContracts.md §9-8。

## 协作

- 入口链 ↔ Store.md：`index.jsx` 挂的 store 由 7 个 slice 组成（`store/index.js:10-20`）；
- 入口链 ↔ Pages.md：`routes.jsx` 的完整路由表在 Pages.md 逐页走读；
- 客户端 ↔ Services.md：`api.js` 导出的三个客户端被 24 个 service 文件消费；
- 构建 ↔ Testing.md：`vite.config.js` 的 `test` 块就是 Vitest 的全部配置；
- 主题 ↔ I18nTheming.md：`App.jsx` 的 dark class 切换是主题机制的执行点。

## 注意

1. **登录是 mock**：`pages/Login.jsx:17-21` 任意用户名+密码即写
   `auth_token = 'mock_jwt_token_' + Date.now()` 并跳 `/dashboard`；页面底部文案
   "Demo: 任意用户名 + 密码即可登录"（`Login.jsx:118`）。`api` 拦截器会把这个假 token
   真的塞进 `Authorization` 头发给 C++ 后端。
2. **`api.js:186` 的导出有个小坑**：`PYTHON_API_BASE_URL as PYTHON_BASE_URL` 与原名同时
   导出，`Terminal.jsx` 用别名、`TerminalOutput.jsx` 用原名，指向同一字符串。
3. **无路由的侧栏链接**：`Layout.jsx:32` 指向 `/investigation-graph`，但 `routes.jsx`
   没有该路由（详见 Pages.md"已知问题"）。
4. **拦截器的 401 跳转**只存在于 `api`；`pythonApi` 401 只抛错不清理，依赖各页面 catch。

## 验证

```bash
cd web && npm run dev     # :3000，访问 http://localhost:3000/dashboard
cd web && npm run build   # 产出 dist/，检查 assets/ 下 vendor chunk 拆分
cd web && npm test        # Vitest，48 个测试文件（见 Testing.md）
```

- 跨机访问验证：用局域网 IP 打开 :3000，Dashboard 的 Python/Neo4j/Redis 卡片应在线
  （依赖 `currentHost()` 推导）；
- 代理验证：DevTools Network 里 `/api/tasks` 应是同源请求（经代理到 :8080），
  `/api/llm/...` 是直连 `<host>:8090`。

**最后更新**: 2026-08-24（二轮深化：补代码走读与契约对应）
