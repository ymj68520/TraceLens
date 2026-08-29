# TraceLens Web 前端

React 单页应用，为 TraceLens 数字取证分析平台提供 Web 界面。开发模式下由 Vite 运行在端口 3000；生产构建后由 C++ 服务托管。

## 技术栈

- **React 18** + **Vite 5** + **TypeScript 5**（strict 模式，全面类型化）
- **Redux Toolkit 2** 状态管理（typed hooks：`useAppDispatch` / `useAppSelector`）
- **react-router 6**（`createBrowserRouter`）
- **Tailwind CSS 3**（ink 中性色 + accent 青色的扁平设计体系）
- **axios** HTTP 客户端（响应拦截器直接解包 payload，服务层按业务类型标注）
- **react-force-graph-2d**、**recharts**、**react-virtuoso**（虚拟列表）
- 测试：**Vitest 2** + **Testing Library**（jsdom 环境）

## 常用命令

```bash
cd web
npm install        # 安装依赖（Node.js 18+）

npm run dev        # 开发服务器（Vite，端口 3000，带代理与热重载）
npm run build      # 生产构建 → dist/
npm run preview    # 预览构建结果
npm test           # 运行 Vitest 测试
npm run typecheck  # tsc --noEmit
npm run lint       # ESLint（--max-warnings 0，零警告门槛）
npm run format     # Prettier 格式化
```

## 环境变量

前端自身目录下没有 `.env`，环境变量统一来自**仓库根目录的 `.env`**（`vite.config.ts` 通过 `loadEnv(mode, '..', '')` 读取上级目录）：

| 变量 | 作用 | 默认值 |
|------|------|--------|
| `VITE_API_BASE_URL` | C++ 后端 API 基地址 | 空（同源相对路径，走 Vite 代理） |
| `VITE_PYTHON_API_URL` | Python 服务地址 | `http://<主机名>:8090`（按浏览器访问的主机名动态推导） |
| `VITE_CS_API_URL` | 分布式 C/S 服务地址 | `http://<主机名>:8091` |
| `VITE_CPP_PROXY_TARGET` | 开发时代理到 C++ 后端的地址 | `http://localhost:${HTTP_SERVER_PORT或8080}` |

## 目录结构

```
src/
  main.tsx            # 入口：Provider + RouterProvider + ToastProvider
  routes.tsx          # 路由表 + 旧报告地址重定向
  App.tsx             # 主题切换 + Layout + ErrorBoundary
  types/              # 后端负载类型（ForensicTask / ForensicCase / EventCluster …）
  lib/                # 常量（状态/优先级 chip 映射）与工具（formatBytes 等）
  locales/            # zh / en 文案
  services/           # 三个后端客户端（api / pythonApi / csApi）+ 按领域的服务模块
  store/              # Redux slices：tasks / cases / settings / intelligence / filter
  hooks/              # useStaleResource、useTaskPolling、useTaskAutoTrigger、useWebSocket …
  components/
    layout/           # 侧边栏 + 顶栏外壳
    ui/               # 设计系统原语：Card / Button / Badge / Modal / Toast / Spinner …
    tasks/            # 任务表、建任务/组案/关联弹窗、任务选择器
    files/            # 大文件表、扩展名分析、Office 预览、提取面板
    timeline/         # 筛选栏、分布图、事件簇虚拟列表、簇详情抽屉
    investigation/    # 证据详情 + 二次分析面板
    case-intel/       # 历史研判报告阅读器
  pages/              # 18 个页面；dashboard/ 下另有 ServiceHealthStrip 子组件
  test/               # vitest setup + smoke / routes 测试
```

## 设计约定

- 扁平卡片 + 发丝边框，无大面积渐变/毛玻璃；accent 青色只用于链接、激活态与主按钮。
- 文案一律中文（界面语言可在设置页切换为 English）。
- 所有页面优先通过 URL query（`task_id` / `case_id`）携带上下文，顶栏任务选择器负责同步。
- 轮询类 hook（`useStaleResource`、`useTaskAutoTrigger`、`pollExtractionStatus` 等）均带防陈旧/可中止语义。
