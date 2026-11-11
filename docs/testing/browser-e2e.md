# 浏览器 E2E（browser-e2e）

本文盘点两套浏览器级测试资产：`scripts/browser_e2e.py`（Python 标准库 + CDP 的最小 Harness，Phase E/6C 隔离门）与 `web/scripts/` 下的 **10 个 Puppeteer 实浏览器脚本**（feature/model-routing 分支新增，覆盖任务创建流、IM 取证页、案情预设、分析预算与实战案件验收）。两套资产互补：前者零第三方依赖、隔离性最强；后者走真实点击路径与真实服务。

## 一、`scripts/browser_e2e.py`：Phase E 最小 Harness

### 6C 隔离要求（现行）

下文的历史命令**不得用于现场发布测试**：默认前端构建可能指向已存在的 8090 服务。现行 Harness 强制要求 `--mode ISOLATED_TEST`、全新网络命名空间、与当前源码一致的 field-build manifest，否则拒绝运行。它绑定随机 127.0.0.1 mock 实例、校验其身份、在首次导航前安装 CDP `Fetch` 拦截、绕过 Service Worker，并对意外请求直接失败；一个受控的"禁止合成目标"必须在其服务端收到请求之前被拦截。命名空间内只有 loopback，子 Chrome/proxy 进程无法触达宿主服务。

只构建到新的独立输出目录，绝不构建到在用的 `web/dist`：

```bash
source "$HOME/.nvm/nvm.sh" && nvm use 22
unshare -n -- python_service/.venv/bin/python scripts/field_frontend_build.py --output /tmp/APPROVED_NEW_6C_CANDIDATE
unshare -n -- env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY CHROME_BIN="$(cd web && node --input-type=module -e "import puppeteer from 'puppeteer'; console.log(await puppeteer.executablePath())")" python_service/.venv/bin/python scripts/browser_e2e.py --mode ISOLATED_TEST --field-mode --android-6b --dist /tmp/APPROVED_NEW_6C_CANDIDATE/web --output /tmp/tracelens-6c-browser.json
```

示例中的候选目录要替换为在受批准测试根下**显式新建**的目录；构建拒绝已存在的目标。`PRODUCTION_SMOKE` 未在本 Harness 中实现，需要单独显式批准与独立入口。缺失隔离或构建来源证明即测试失败，不会回退到 8666/8090/8091。

### 目的

`scripts/browser_e2e.py` 是 Phase E 与 D6-E7 收口的最小浏览器 Harness。它刻意避开 Playwright/Cypress/Puppeteer 依赖，只使用：

- 仓库内 `web/dist` 生产构建；
- Python 标准库 HTTP 服务与合成 API 响应；
- 本机已安装的 Chrome/Chromium 可执行文件；
- 经 localhost WebSocket 的 Chrome DevTools Protocol。

注意：这一"零 Puppeteer"原则只约束本脚本；仓库另有第二套 Puppeteer 脚本（见下节），其依赖来自 `web/node_modules`。

Harness 不使用真实证据、真实任务目录、外部 LLM、Neo4j、PostgreSQL 或 Redis。其 API 响应是确定性的，且只作用于合成任务 ID `phase-e-small`、`phase-e-medium`、`phase-e-large`。

### 调用方式

仓库根执行：

```bash
python3 scripts/browser_e2e.py \
  --dist web/dist \
  --output /tmp/tracelens-phase-e-browser.json
```

需要先构建前端：

```bash
cd web
npm run build
cd ..
python3 scripts/browser_e2e.py
```

输出对每个路由记录：导航耗时、近似首次有意义渲染耗时、DOM 节点数、资源数与传输体积（Chrome 报告时）、JS 堆用量（支持时）、可见任务标记与可见正文样本。

访问路由：

- `/files?task_id=phase-e-small`；
- `/investigation?taskId=phase-e-medium`；
- `/knowledge-graph?task_id=phase-e-medium`；
- `/case-intelligence?task_id=phase-e-large`。

随后从 small 合成任务切到 large 合成任务，检查可见任务标记不会残留旧值。图谱响应包含 `base_graph_unavailable`，因此无需 Graphiti 依赖即可观察"仅 overlay 渲染"的降级路径。

### 结果分类

- `PASS`：Chrome 启动、CDP 附加、路由加载、测量采集完成。
- `ENVIRONMENT BLOCKED`：Chrome/Chromium 不可用、CDP 不可达或浏览器无法导航到本地 Harness 服务。这不是产品意义上的通过。

Harness 仅对 `PASS` 退出 0，对环境阻塞退出 2；从不伪造运行时测量。

### 当前环境结论

2026-08-18 记录：系统 Chrome 存在、CDP 控制端点可应答，但 headless Chrome 未完成对本地合成 HTTP 服务的导航，Harness 保持 `ENVIRONMENT BLOCKED`，未声明前端运行时 PASS。失败发生在 React 路由执行之前，不构成产品代码修改的依据。

## 二、`web/scripts/`：Puppeteer 实浏览器脚本（10 个，本分支新增）

依赖 puppeteer（`web/package.json` 依赖，装在 `web/node_modules`），从仓库根或 `web/` 目录用 `node web/scripts/<脚本>.mjs` 直接运行——**`web/package.json` 没有为它们包装 npm script**（`npm test` 仍是 Vitest 单测门）。截图默认落 `/tmp`（脚本各自定义）。除非特别说明，脚本对失败用 `PASS/FAIL` 逐项打印并以非零码退出。

### 脚本清单

| 脚本（行数） | 测什么 | 前置 |
| --- | --- | --- |
| `e2e-static-server.mjs`（117） | 基础设施：起构建前端的静态服务并只代理 API 前缀（`/python/*`、`/api/*`→Python；`/tasks`、`/api/tasks*`→C++），保留 SPA 回退；修复 Vite dev 代理把客户端路由 `/tasks` 也重写的深链问题 | `web/dist` 已构建；后端服务在线；`--port 4173` |
| `e2e-analysis-budget.mjs`（356） | 任务级分析文件预算（llm_max_files）两个建任务入口：任务列表默认"使用系统默认"不发字段/选 300 发 300/自定义 1234 发 1234/越界前端拦截；案件管理多镜像案件透传 `llmMaxFiles`。断言以 CDP 捕获的 `POST /api/tasks` 请求体为准（axios 走 XHR）；跑完自动删除测试任务 | **vite dev server（默认 3000）** + C++ 后端 |
| `e2e-case-background-presets.mjs`（287） | 案情背景预设主路径：任务页→创建任务→展开预设面板→切换分组→选中预设→验证文本填入→手动改动回退自定义→套用推荐场景→提交 | 前端已构建 + 后端在线 |
| `e2e-case-background-presets-entries.mjs`（190） | 预设在其余四个入口的可用性：案件管理新建多镜像案件、任务列表组建案件、证据判定页案情背景编辑、取证报告二次研判的本轮案情 | 同上 |
| `e2e-ios-task.mjs`（293） | iOS 取证任务全流程：打开建任务流→选 iOS 源→输入备份路径→提交→跟随任务进入 Android/iOS 工件视图→验证解析行展示；测试自建自删任务，证据只读 | live 双服务（默认经 4173）；**`E2E_IOS_BACKUP`** 指向未加密 iTunes/Finder 备份 |
| `e2e-vivo-task.mjs`（285） | vivo 备份取证任务全流程（同上点击路径与自清理语义） | live 双服务；**`E2E_VIVO_BACKUP`** 指向 vivo(iQOO) 备份目录 |
| `e2e-whatsapp-im.mjs`（250） | 三平台 IM 取证页：WhatsApp 与微信/QQ 并列为一级平台——切换平台、打开导入对话框、导入真实 iOS WhatsApp 库、逐个标签页验证解析数据 | live 双服务；**`E2E_WHATSAPP_DIR`** 指向含 ChatStorage.sqlite（可选 ContactsV2/CallHistory）的目录 |
| `e2e-ios-evidence.mjs`（206） | iOS 证据路径：与 `browser_e2e.py` 不同**不 mock API**，驱动构建前端对 live Python/C++ 服务点击真实控件；证据只读，只对配置的收件箱提交预检任务 | live 双服务；`--stage preflight` 或 `--stage all` |
| `verify-investigation-page.mjs`（108） | 文件中心调查工作台整页验收：左列"文件关联调查事件"计数与列表、左列事件行→右列事件面板切换、返回文件工作台、时间线节点展开文件卡与佐证事件块、事件链接切换面板；汇总 JSON 报告 + 截图 | 对每个已完成任务运行；`BASE`（默认 `http://127.0.0.1:8666` 直连 C++，不经静态服务）、`OUT`（默认 `/tmp/shots/final`） |
| `verify-real-case-reports-and-im.mjs`（252） | **实战案件验收**：对 7 大镜像任务（Windows/Linux/阿里云/iOS/小米/ vivo/OPPO 雷电快取，均为 E01/RAW/备份真实检材入库）逐一验证取证研判报告生成状态，再逐个验证 IM 即时通讯关系图（微信 49 节点、QQ 47 节点、vivo/OPPO 任务图谱） | `BASE` **硬编码** `http://127.0.0.1:4173`（必须先起 `e2e-static-server`）；**7 个 taskId 硬编码在脚本内**（实战案件入库后的 UUID，换环境需改源码）；截图落 `../gui-test-screenshots/real-evidence-verify` |

### 环境变量速查

| 变量 | 默认 | 用于 |
| --- | --- | --- |
| `E2E_BASE_URL` | `http://127.0.0.1:4173`（analysis-budget 为 `3000`） | 各 e2e 脚本的前端地址 |
| `E2E_SHOT_DIR` | `/tmp/tracelens-e2e` | analysis-budget 截图目录 |
| `E2E_IMAGE_PATH` | 仓库根 `test_image.img` | analysis-budget 的任务镜像 |
| `E2E_IOS_BACKUP` | 无（缺失即抛错） | e2e-ios-task |
| `E2E_VIVO_BACKUP` | 无（缺失即抛错） | e2e-vivo-task |
| `E2E_WHATSAPP_DIR` | 无（缺失即抛错） | e2e-whatsapp-im |
| `BASE` / `OUT` | `http://127.0.0.1:8666` / `/tmp/shots/final` | verify-investigation-page |

### 典型运行序列

```bash
# 0) 构建前端 + 准备服务（C++ 8666 / Python 8090 在线）
cd web && npm run build && cd ..
node web/scripts/e2e-static-server.mjs --port 4173        # 终端 A，保持运行

# 1) 需要真实备份的任务流（各自自建自删任务）
E2E_IOS_BACKUP=/path/to/itunes_backup node web/scripts/e2e-ios-task.mjs
E2E_VIVO_BACKUP=/path/to/vivo_backup  node web/scripts/e2e-vivo-task.mjs
E2E_WHATSAPP_DIR=/path/to/whatsapp_dir node web/scripts/e2e-whatsapp-im.mjs
node web/scripts/e2e-ios-evidence.mjs --stage all

# 2) 纯前端交互流（对 live 后端提交真实任务）
node web/scripts/e2e-case-background-presets.mjs
node web/scripts/e2e-case-background-presets-entries.mjs
# analysis-budget 走 vite dev（3000）：cd web && npm run dev 后
E2E_BASE_URL=http://127.0.0.1:3000 node web/scripts/e2e-analysis-budget.mjs

# 3) 页面验收
BASE=http://127.0.0.1:8666 node web/scripts/verify-investigation-page.mjs
node web/scripts/verify-real-case-reports-and-im.mjs      # 需 4173 + 实战案件已入库
```

## 范围边界

- `scripts/browser_e2e.py` 收口 E1 的可复现性要求，不是完整的真实后端 Journey B 门。Python Investigation/Report 测试、C++ CTest、手机备份 CLI/HTTP E2E（见 CppTestCatalog.md 域十）与前端 Vitest 仍是独立门。真实跨服务/浏览器 Journey B 仍需要一次性 C++/Python 栈与确定性 fake provider 路径（`scripts/acceptance/live_services.py --profile analyst --serve` 提供该拓扑）。
- `web/scripts/` 的任务流脚本（ios/vivo/whatsapp/预设/预算）**直接对 live 服务写真实任务**（除声明的自清理外），不适合指向生产实例；`e2e-ios-evidence` 与各 verify 脚本则声明证据只读。
- 现场发布级验证仍以 6C 隔离 Harness 为准；Puppeteer 脚本是开发/验收辅助，没有网络命名空间隔离。

## 已发现的测试层面问题

1. **两套 Harness 的隔离等级完全不同却没有交叉引用**：`browser_e2e.py` 强制 `unshare -n` 隔离，而 `web/scripts/*.mjs` 直接打 `127.0.0.1` live 服务并创建真实任务；误把后者当"现场发布门"使用会污染在用环境。
2. **`verify-real-case-reports-and-im.mjs` 硬编码 7 个实战案件 taskId 与 `BASE=4173`**：换机器/换案件批次必须改源码，且无 taskId 存在性预检（任务缺失时逐项 FAIL 而非跳过）。
3. **`web/package.json` 无 npm script 包装**：10 个脚本只能靠本文档记住调用方式，`npm run` 不可发现它们。
4. **`e2e-analysis-budget.mjs` 默认端口与其余脚本不一致**（3000 vite dev vs 4173 静态服务），且默认 `E2E_IMAGE_PATH` 是**绝对路径**（`/home/ymj68520/...`），换环境必改。
5. **`e2e-ios-task` / `e2e-vivo-task` / `e2e-whatsapp-im` 需要真实手机备份目录**：仓库不提供这些 fixture，脚本对缺失环境是硬失败（而非 skip），CI 不可直接复用。

**最后更新**: 2026-11-10（feature/model-routing 分支改版：并入 web/scripts/ 10 个 Puppeteer 脚本清点）
