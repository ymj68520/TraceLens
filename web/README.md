# TraceLens Web 前端

React 单页应用，为 TraceLens 数字取证分析平台提供 Web 界面。开发模式下由 Vite 运行在端口 3000；生产构建后由 C++ 服务托管。

## 技术栈

- **React 18** + **Vite 5**（纯 JavaScript，无 TypeScript）
- **Redux Toolkit 2** 状态管理
- **react-router 6**（`createBrowserRouter`）
- **Tailwind CSS 3**
- **axios** HTTP 客户端
- **d3** + **react-force-graph-2d**（图可视化）
- **recharts**（图表）
- **framer-motion**（动画）、**react-virtuoso**（虚拟列表）
- 测试：**Vitest 2** + **Testing Library**（jsdom 环境），48 个与源码同目录的测试文件（`*.test.jsx`）

## 常用命令

```bash
cd web
npm install        # 安装依赖（Node.js 18+）

npm run dev        # 开发服务器（Vite，端口 3000，带代理与热重载）
npm run build      # 生产构建 → dist/
npm run preview    # 预览构建结果
npm test           # 运行 Vitest 测试
npm run test:watch # 测试监听模式
npm run lint       # ESLint（--max-warnings 0，零警告门槛）
npm run format     # Prettier 格式化
```

## 环境变量

前端自身目录下没有 `.env`，环境变量统一来自**仓库根目录的 `.env`**（`vite.config.js` 通过 `loadEnv(mode, '..', '')` 读取上级目录）：

| 变量 | 作用 | 默认值 |
|------|------|--------|
| `VITE_API_BASE_URL` | C++ 后端 API 基地址 | 空（同源相对路径，走 Vite 代理） |
| `VITE_PYTHON_API_URL` | Python 服务地址 | `http://<主机名>:8090`（按浏览器访问的主机名动态推导） |
| `VITE_CS_API_URL` | 分布式 C/S 服务地址 | `http://<主机名>:8091` |
| `VITE_CPP_API_URL` | C++ 后端绝对地址（导出为 `CPP_BASE_URL`） | `http://<主机名>:<CPP_PORT>` |
| `VITE_CPP_PROXY_TARGET` | Vite 开发代理中 C++ 的目标地址 | `http://localhost:8080` |
| `VITE_CPP_PORT` / `HTTP_SERVER_PORT` | C++ 端口推导 | `8080`（本仓库 `.env` 中 `HTTP_SERVER_PORT=8666`） |

跨机访问时，Python/C/S 地址默认基于 `window.location.hostname` 拼接，保证从任意机器访问都能连到服务器；上述 `VITE_*` 变量可覆盖。

## 开发代理（vite.config.js）

开发服务器（端口 3000）按以下规则转发请求：

| 前缀 | 目标 |
|------|------|
| `/tasks` | C++ 后端（`VITE_CPP_PROXY_TARGET`，默认 8080） |
| `/api`（兜底） | C++ 后端（同上） |
| `/api/reports`、`/api/graphiti`、`/api/llm`、`/api/office`、`/api/db`、`/api/wechat`、`/api/investigation` | Python 服务 `http://localhost:8090` |
| `/csapi`（去前缀） | 分布式 C/S 服务 `http://localhost:8091` |

## API 客户端（src/services/api.js）

三个独立 axios 实例：

- **`api`**（默认导出）：C++ 后端，同源相对路径；请求拦截器附加 `Bearer auth_token`（localStorage），401 时清除 token 并跳转 `/login`。
- **`pythonApi`**：Python 服务（8090），60 秒超时（LLM 请求较慢）。
- **`csApi`**：分布式 C/S 服务（8091），使用独立的 `cs_auth_token`；401 仅清除分布式 token，不跳转登录页。

## 路由页面（src/routes.jsx）

| 路由 | 页面 | 说明 |
|------|------|------|
| `/login` | Login | **mock 登录**：任意账号密码即写入 localStorage（`auth_token`/`auth_user`），无真实鉴权 |
| `/dashboard` | Dashboard | 任务统计 + 五服务依赖健康卡（C++ 后端 / Python 服务 / Neo4j / Redis / LLM） |
| `/tasks` | Tasks | 任务表 + 创建任务弹窗：镜像路径、数据源（`tsk` 磁盘镜像 / `dir` Android 目录 / `zip` / `miui-backup` MIUI 备份）、场景多选、优先级、备份密码、XFS 模式、过滤配置（filter profile）；创建案件 = 多镜像生成多任务 |
| `/cases` | Cases | 跨镜像案件管理 + 多镜像分析 |
| `/timeline` | Timeline | 虚拟化时间线 + 分布图 + 事件簇调查抽屉 + LLM 簇分析 |
| `/files` | Files | 文件列表 / 提取 / Office 预览 / LLM 分析 / Graphiti 摄取触发 / 相关性切换 |
| `/android` | Android | MIUI / QQNT / 微信工件查看 |
| `/memory` | Memory | 内存取证 |
| `/wechat-graph` | WeChatGraph | 微信关系力导向图（React.lazy 懒加载） |
| `/oss` | OSS | OSS 存储分析 |
| `/search` | Search | 全文搜索 |
| `/statistics` | Statistics | 统计分析 |
| `/settings` | Settings | 语言（en/zh）、暗色主题、LLM/Graphiti 状态等 |
| `/knowledge-graph` | KnowledgeGraph | Graphiti 图谱搜索 / 实体 / 关系 |
| `/case-intelligence` | CaseIntelligence | 智能报告 + 取证报告双 tab |
| `/analysis-center` | AnalysisCenter | 分析工作台：证据卡、事件簇、文件关联 |
| `/investigation` | Investigation | 二次调查工作台 |
| `/investigation/report` | FinalReportViewer | 终版报告查看 / 发布 / 完整性校验 |
| `/reports/task/:taskId`、`/reports/case/:caseId`、`/case-report` | LegacyReportRedirect | 旧报告链接重定向到 case-intelligence |
| `/terminal` | Terminal | 隐藏页，仅当设置 `showTerminal` 开启时出现在导航（默认关闭） |
| `/distributed` | Distributed | 分布式 C/S 冒烟页 |

## 状态管理与国际化

- Redux slices（`src/store/`）：`taskSlice`、`caseSlice`、`dataSlice`、`filterSlice`、`intelligenceSlice`、`settingsSlice`、`uiSlice`。
- i18n：`src/locales/{en,zh}.js` + `src/hooks/useTranslation.js`。

## 生产构建与部署

```bash
cd web && npm run build   # 产物 → web/dist/
```

生产环境前端由 **C++ 服务从 `web/dist` 托管**：仓库根 `run.sh` 在构建阶段执行 `npm run build`，并把 `web/dist` 同步到 `build/web/dist`（C++ 二进制按相对路径读取）。部署后直接用浏览器访问 C++ 服务端口即可，无需单独的前端服务器。

## 目录结构

```
web/
├── src/
│   ├── pages/          # 页面组件（含 Investigation/、WeChatGraph/ 子目录）
│   ├── components/     # 组件（Layout、tasks、timeline、files、android 等）
│   ├── services/       # API 服务层（api.js 及各领域 service）
│   ├── store/          # Redux slices
│   ├── hooks/          # 自定义 Hooks（含 useTranslation）
│   ├── locales/        # i18n 文案（en.js / zh.js）
│   ├── styles/         # 全局样式
│   ├── test/           # 测试 setup
│   ├── utils/          # 工具函数
│   ├── App.jsx / index.jsx / routes.jsx
│   └── *.test.jsx      # 与源码同目录的测试（共 48 个）
├── index.html
├── vite.config.js / tailwind.config.js / postcss.config.js
└── package.json
```

注意：`web/` 目录下还残留历史 CMake 构建产物（`CMakeCache.txt`、`cmake_install.cmake`、`CTestTestfile.cmake` 等），它们不是前端代码，构建入口已改为根目录 `run.sh`（npm 直接构建）。

---

**最后更新**: 2026-08-23（以代码为准重写）
