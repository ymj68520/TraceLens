# TraceLens Web 前端

React 单页应用，为 TraceLens 数字取证分析平台提供 Web 界面。开发模式下由 Vite 运行在端口 3000；生产构建后由 C++ 服务托管。

## 技术栈

- **React 18** + **Vite 5** + **TypeScript 5**（strict 模式，全面类型化）
- **Redux Toolkit 2** 状态管理（typed hooks：`useAppDispatch` / `useAppSelector`）
- **react-router 6**（`createBrowserRouter`）
- **Tailwind CSS 3**（ink 中性色 + accent 青色的扁平设计体系，`darkMode: 'class'`）
- **Radix UI** 无头原语（dialog / dropdown-menu / tooltip）+ **sonner** 通知 + **cmdk** 命令面板
- **axios** HTTP 客户端（响应拦截器直接解包 payload，服务层按业务类型标注）
- **react-force-graph-2d**、**d3**、**recharts**（图表与力导向图）、**react-virtuoso**（虚拟列表）
- 字体经 **fontsource 本地打包**（Inter Variable + JetBrains Mono），内网/离线环境零外部字体请求
- 测试：**Vitest 2** + **Testing Library**（jsdom 环境）

## 常用命令

```bash
cd web
npm install        # 安装依赖（Node.js 18+）

npm run dev        # 开发服务器（Vite，端口 3000，带代理与热重载）
npm run build      # 生产构建 → dist/
npm run preview    # 预览构建结果
npm test           # 运行 Vitest 全量测试（npx vitest run，当前 280 用例）
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
  main.tsx            # 入口：Provider + RouterProvider + ToastProvider（fontsource 字体在此引入）
  routes.tsx          # 路由表（21 个路由页面，含登录与 404）+ 旧报告地址重定向
  App.tsx             # 主题切换 + Layout + ErrorBoundary
  types/              # 后端负载类型（ForensicTask / ForensicCase / EventCluster …）
  lib/                # constants（状态/优先级 chip 映射）、utils、validation、appEvents、exportUtils
  locales/            # zh / en 文案 + keys.d.ts（键集合编译期一致，见「国际化」）
  services/           # api.ts（C++ / Python / C-S 三后端 axios 客户端）+ 20 余个按领域服务模块
  store/              # Redux slices：tasks / cases / settings / intelligence / filter
  hooks/              # useStaleResource、useTaskPolling、useTaskAutoTrigger、useWebSocket、
                      # useTranslation、useUrlState、useKeyboardShortcuts、useAppNotifications
  styles/             # index.css：设计令牌应用层、动画与 prefers-reduced-motion 覆盖
  components/
    layout/           # 侧边栏 + 顶栏外壳、命令面板（cmdk）、通知中心
    ui/               # 设计系统原语：Badge / BrandLogo / Button / Card / ConfirmDialog / Drawer /
                      # DropdownMenu / EmptyState / ErrorBoundary / FormField / Modal / PageScaffold /
                      # ProgressBar / Spinner / Toast / Tooltip
    tasks/            # 任务表、建任务/组案/关联弹窗、任务选择器
    files/            # 大文件表、扩展名分析、Office 预览、提取面板
    timeline/         # 筛选栏、分布图、事件簇虚拟列表、簇详情抽屉
    investigation/    # 证据详情 + 二次分析面板
    case-intel/       # 历史研判报告阅读器
    graph/ search/ llm/ reports/ shortcuts/ workbench/ …   # 其余领域组件
  pages/              # 21 个路由页面 + 页面子模块：
                      #   analysis/（二次分析队列/历史/diff 导出）、android/、memory/、oss/、
                      #   wechat/（微信图谱面板）、knowledgegraph/、investigation/、report/、
                      #   tools/（哈希/编解码/正则/时间戳/网络计算器等小工具）、dashboard/
  test/               # vitest setup + 组件 / 路由 / 小工具单元测试（280 用例）
```

## 设计系统要点

- **设计令牌**：Tailwind 扩展 `ink`（冷灰中性色，50–950）与 `accent`（青色，50–950）两组色板；accent 只用于链接、激活态与主按钮，其余一律中性色。暗色模式经 `darkMode: 'class'` + `dark:` 变体。
- **页面骨架**：`components/ui/PageScaffold.tsx` 提供 PageHeader（图标色块 + 标题/副标题/actions）、统计条、分段控件与骨架屏，全部页面共用，保证 21 个页面一个产品观感。
- **动画约定**：短促克制的进入类动效（`animate-fade-in` / `animate-rise` / `animate-slide-in-right` / `animate-scale-in`，0.15–0.3s；`shimmer` 用于加载骨架），无弹跳、无缩放回弹。
- **可访问性**：`styles/index.css` 全局响应 `prefers-reduced-motion: reduce`，关闭动画/过渡。
- 扁平卡片 + 发丝边框，无大面积渐变/毛玻璃。
- 文案一律中文（界面语言可在设置页切换为 English）。
- 所有页面优先通过 URL query（`task_id` / `case_id`）携带上下文，顶栏任务选择器负责同步。
- 轮询类 hook（`useStaleResource`、`useTaskAutoTrigger`、`pollExtractionStatus` 等）均带防陈旧/可中止语义。

## 测试

```bash
npx vitest run     # 全量单测（等价 npm test）
npx vitest         # watch 模式
```

- **Vitest 2** + **@testing-library/react**，jsdom 环境（`vite.config.ts` 内联 test 配置），当前 **280 用例 / 26 个测试文件**，全绿是合入门槛。
- 全局 setup 在 `src/test/setup.ts`（jest-dom 匹配器、自动 cleanup、`matchMedia` stub）。
- 覆盖范围：路由表、布局壳、设计系统原语（Modal / Drawer / Badge / FormField / PageScaffold …）、任务表、命令面板，以及 `pages/tools/` 各小工具的纯计算逻辑（哈希、MD5 向量、时间戳、正则、编码、网络计算器等）。

## 国际化（i18n）

- `locales/zh.ts` 为基准词表（`satisfies LocaleDict` 声明，保留点号命名空间的字面量键）；`locales/en.ts` 标注为 `Record<TranslationKey, string>`。
- `TranslationKey = keyof typeof zh`（`locales/keys.d.ts`），因此 **zh / en 键集合不一致会直接编译报错**，不会漏翻上线。
- 消费端 `useTranslation()`：字面量键有自动补全与拼写检查，动态模板键（如 `` `task.status.${status}` ``）仍可传入。
