# 国际化、主题与终端日志（I18n / Theming / TerminalOutput）

## 为什么要有这篇文档

项目没有引入 i18next 或 theme 库：双语是"两个键值对象 + 一个 20 行 hook"，暗色主题是
"Redux 字段 + `<html>` class + Tailwind dark: 前缀"，设置持久化是手写 localStorage。
机制简单，但正因为简单，**缺键不会报错而是原样显示键名**、**平行主题状态会让人改错
地方**。本文把这三件事及其交叉点（Settings 页、TerminalOutput 的多通道日志）讲透。

## 代码位置

- 词表：`web/src/locales/en.js`、`web/src/locales/zh.js`（各 86 行）
- Hook：`web/src/hooks/useTranslation.js`
- 主题：`web/src/App.jsx`（生效点）、`web/src/components/common/ThemeProvider.jsx`
  （死代码）、`web/tailwind.config.js`（darkMode）、`web/src/styles/index.css`
- 设置：`web/src/store/settingsSlice.js`、`web/src/pages/Settings.jsx`
- 日志：`web/src/components/common/TerminalOutput.jsx`、`web/src/hooks/useWebSocket.js`、
  `web/src/pages/Terminal.jsx`

## 核心概念

- **键表机制**：词表是扁平对象 `'nav.dashboard': 'Dashboard'`；`t(key)` 查当前语言
  表，缺失回退英文表，再缺失**返回 key 原文**。
- **主题链**：`settingsSlice.theme`（唯一真源）→ App.jsx effect → `<html>.dark` →
  Tailwind `darkMode:'class'` 下的 `dark:` 变体。
- **设置持久化**：任何 `updateSettings` 都整体 JSON 化写入 localStorage
  `forensics_settings`；启动时展开合并进初值（Store.md）。

## 走读

### useTranslation — 20 行的 i18n

`web/src/hooks/useTranslation.js:1-19` 全文核心：

```js
const locales = { en, zh };

export const useTranslation = () => {
    const { language } = useSelector((state) => state.settings);

    const t = (key) => {
        const currentLocale = locales[language] || locales.en;
        return currentLocale[key] || key;
    };

    return { t, language };
};
```

逐块解释：

- 语言只存于 Redux（settingsSlice 初值 `'en'`，持久化后随 localStorage 恢复），
  **没有 URL/cookie 同步**——换语言刷新后仍保留（localStorage），但无法通过链接分享
  语言偏好；
- `locales[language] || locales.en`：非法值兜底英文表；
- `currentLocale[key] || key`：**键缺失的可见后果**。

词表覆盖范围（en.js/zh.js 各约 80 键）：`nav.*`（17 项）、`app.title`、`sidebar.*`、
`system.*`、`settings.*`（16 项）、`timeline.*`（约 30 项）、`terminal.*`（5 项）。
大量页面（Dashboard/Files/Investigation 等）是硬编码中文/英文混排，并不走 `t()`——
词表只覆盖 Layout、Settings、Timeline、Terminal 四处。

**已知缺键**：Layout 侧栏使用的 `nav.investigation_graph`（`Layout.jsx:32`）与
`nav.investigation_workbench`（`Layout.jsx:33`）在两张词表里都不存在，因此无论中英
文，侧栏这两项都显示原始键名字符串 `nav.investigation_graph` /
`nav.investigation_workbench`。此外 workbench 死组件组用到的
`investigation_workbench.*` 系列键同样整组缺失（死代码，不可见）。

### 主题（暗色模式）

生效链只有三步，`web/src/App.jsx:10-16`：

```js
useEffect(() => {
  if (theme === 'dark') {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }
}, [theme]);
```

配套开关在 `web/tailwind.config.js:81`：`darkMode: 'class'`——即所有 `dark:` 变体
由 `<html>` 的 class 决定，与系统偏好无关（没有 `prefers-color-scheme` 侦测）。
`styles/index.css` 提供成对的明暗原语：

- `bg-mesh-light` / `bg-mesh-dark`（15-29 行）：多Radial 渐变网格背景，Layout 外层
  使用（`Layout.jsx:60`）；
- `glass` / `glass-strong`（35-47 行）：玻璃拟态卡片（半透明 + backdrop-blur +
  shadow-glass），Modal/头栏/面板通用；
- `status-dot-online/offline/checking`（67-78 行）：带辉光的在线状态点；
- 暗色滚动条（105-110 行）、选区色（113-116 行）。

`components/common/ThemeProvider.jsx` 是同一逻辑的组件化版本（多设置了
`root.style.colorScheme`），**但 App.jsx 并未使用它**——它是被内联实现取代的遗留。
`uiSlice.theme` + `setTheme` 是另一份平行假状态（无消费者），改主题请走
`updateSettings({theme})`（Store.md"注意"）。

### 设置持久化（settingsSlice）

localStorage 键 `forensics_settings`（`settingsSlice.js:3`），读写函数见 Store.md。
Settings 页是唯一编辑入口（`Settings.jsx:26-34`）：

```js
const handleSettingChange = (key, value) => {
  dispatch(updateSettings({ [key]: value }));
};

const handleReset = () => {
  if (window.confirm(t('settings.reset_confirm'))) {
    dispatch(resetSettings());
  }
};
```

可编辑项：`apiUrl`/`pythonApiUrl`（展示性，无实际效果——请求地址由 api.js 决定）、
theme、language、itemsPerPage（Timeline 分页大小）、refreshInterval、autoRefresh、
showTerminal（控制侧栏 Terminal 入口，`Layout.jsx:44-46`）。重置**不含 showTerminal**
（Store.md 注意 2）。

### TerminalOutput — 三通道日志终端

`web/src/components/common/TerminalOutput.jsx` 是 /terminal 页主体，三个 Tab
（cpp/python/web）各有取数通道：

**通道 1：REST 回填**（`TerminalOutput.jsx:87-115`）——挂载即拉：

```js
const endpoints = {
  cpp: `${PYTHON_BASE}/api/system/logs/cpp`,
  python: `${PYTHON_BASE}/api/system/logs/python`,
};
const response = await fetch(endpoint);
if (response.ok) {
  const data = await response.json();
  setLogs(prev => ({ ...prev, [source]: data.logs || [] }));
}
```

注意端点在 **Python 服务**（`http://<host>:8090/api/system/logs/...`），由 Python 侧
代读 C++ 日志；用原生 `fetch` 而非 axios（不经过拦截器解包，因此手动 `response.json()`）。

**通道 2：SSE 实时流**（49-84 行）——切 Tab 时 `startStreaming` 打开
`EventSource(`${PYTHON_BASE}/api/system/logs-stream/${source}`)`，onmessage 解析
JSON 后 `slice(-499)` 截断防内存膨胀；onerror 关流置非流式。

**通道 3：web 前端日志**（118-159 行）——直接劫持 `console.log/error/warn`：包装
函数把参数序列化成 `{timestamp, level, message}` 推进 `window.forensics_web_logs`
（会话级伪持久化，上限 500 条）再调原方法。卸载时还原三个原函数。副作用：页面里
所有 console 输出（包括 api.js 拦截器的请求/响应日志）都会进入该缓冲。

**WebSocket 通道（存在但从不激活）**：162-181 行定义了 `wsHandlers`（`cpp_log`/
`python_log` 消息类型）并调用：

```js
const { connected } = useWebSocket(
  taskId ? `${WS_BASE}/ws/tasks/${taskId}/logs` : `${WS_BASE}/ws/logs`,
  wsHandlers,
  { enabled: !!taskId }
);
```

`WS_BASE` 由 `CPP_BASE_URL` 的 http→ws 换算而来（第 9 行）。但 Terminal 页渲染
`<TerminalOutput maxHeight="600px" />` **不传 taskId**（`pages/Terminal.jsx:99`），
`enabled` 恒 false，`useWebSocket` 的 `connect` 直接 return（`useWebSocket.js:20`）。
也就是说实时日志实际全靠 SSE，WebSocket 分支是按任务订阅日志的预留路径。

### 与 Settings 的联动汇总

| 设置键 | 生效点 |
|---|---|
| theme | App.jsx dark class → 全站 `dark:` 变体 |
| language | useTranslation 词表选择 |
| itemsPerPage | Timeline 分页（`Timeline.jsx:81`） |
| refreshInterval / autoRefresh | useTaskAutoTrigger、Dashboard 轮询 |
| showTerminal | Layout 侧栏 Terminal 入口 |
| apiUrl / pythonApiUrl | 无（展示性） |

## 协作

- useTranslation ↔ settingsSlice（language）；词表 ↔ Layout/Settings/Timeline/Terminal。
- 主题 ↔ tailwind.config.js ↔ styles/index.css；切换入口 Settings 页。
- TerminalOutput ↔ systemService 同域端点（Python 代读）、useWebSocket（预留）、
  api.js 拦截器日志（被动进入 web Tab）。

## 注意

1. **新增文案请同时补 en/zh 两张表**，否则界面直接显示键名（现状已有 2 个侧栏项
   中招）。
2. **不要用 `ThemeProvider` 或 `uiSlice.setTheme`** 改主题，它们都不在生效链上。
3. `TerminalOutput` 的 console 劫持只在组件挂载期间生效；多次挂载/卸载安全（还原
   逻辑成对），但 web Tab 的 `window.forensics_web_logs` 跨挂载保留。
4. SSE/REST 日志端点都在 Python :8090，C++ 独立部署时 /terminal 的 cpp Tab 取决于
   Python 能否读到 C++ 日志文件。

## 验证

```bash
cd web && npm run dev
# 1) /settings 切"深色"：全站即时变暗，刷新后保持；检查 <html class="dark">。
# 2) 切"中文"：侧栏出现"仪表盘"等；同时确认 nav.investigation_graph 两项仍显示键名。
# 3) localStorage 查看 forensics_settings 内容。
# 4) /terminal（先在设置里打开 showTerminal）：观察 SSE 连接
#    /api/system/logs-stream/cpp 与 web Tab 收录的拦截器日志。
```

**最后更新**: 2026-08-24（新建，解释式）
