# MCPIntegration（src/integration/LLMIntegration/MCPIntegration.{h,cpp}）

> **一句话**：把 TraceLens 的文件读取与 LLM 分析能力包装成一个 MCP（Model Context Protocol）服务器，让 Claude Desktop、IDE Agent 等外部 AI 客户端能以标准"工具调用"的方式访问取证数据——注意：代码已编译进二进制，但目前没有任何生产代码启动它。

## 1. 为什么有这个模块

### MCP 是什么

MCP 是一个开放协议，为"AI 应用如何使用外部工具"定义了统一约定：基于 JSON-RPC 2.0，服务器向客户端声明自己有哪些**工具**（tools，带名字、描述和参数 JSON Schema），客户端（通常是 AI 聊天应用）把工具清单交给大模型，模型在对话中决定调用哪个工具、传什么参数，客户端再把调用转发回服务器执行。一句话：**MCP 把"函数调用"从单次请求里解耦成跨进程、跨厂商的可发现服务**。

### 这个模块解决什么

TraceLens 平时的方向是"自己调 LLM"（LLMClient/ModelRouter）。MCPIntegration 反过来：**让别人的 AI 调 TraceLens**。典型场景：

- 取证人员在 Claude Desktop 或其他支持 MCP 的客户端里问"帮我看看这个取证目录里有什么可疑文件"——AI 通过 `list_files` 浏览目录、`read_file` 抽查内容、`analyze_file` 触发 TraceLens 的 LLM 分析管线，全程不需要把证据文件复制粘贴进聊天窗；
- 证据留在本机，AI 只拿到工具返回的结果，配合 `setAllowedPaths()` 的白名单可以限制可访问范围。

## 2. 在系统中的位置

```
外部 AI 客户端（Claude Desktop / IDE Agent / 自研脚本）
        │  MCP 协议（HTTP + SSE，JSON-RPC 2.0）
        ▼
mcp::server（第三方库 libs/cpp-mcp，CMakeLists.txt:515-520 链入）
        │  工具回调
        ▼
MCPIntegration ──► ModelRouter（构造时注入）──► LLMClient ──► LLM 端点
   │
   └── 直接读本地文件系统（受 allowedPaths_ 白名单约束）
```

- **谁调用它**：当前**没有**生产调用方。`MCPIntegration.cpp` 在 `CMakeLists.txt:470` 被编进 `forensic_analyzer`，但全仓库搜索没有任何地方构造它——MCP 服务器在现行二进制里从不运行。它是一块"能力已就绪、等待接线"的集成件（详见第 6 节）。
- **它调用谁**：`libs/cpp-mcp` 的 `mcp::server`（HTTP + SSE 传输，见 `libs/cpp-mcp/include/mcp_server.h:384-387` 的 `handle_sse`/`handle_jsonrpc`）；文件系统（std::filesystem）；注入进来的 ModelRouter。
- **配置**：监听 host 读 `ConfigManager::getMCPHost()`（`src/core/ConfigManager/ConfigManager.cpp:143`，键 `MCP_HOST`，默认 `0.0.0.0`）；端口来自构造函数参数，默认 8890（`MCPIntegration.h:41`）。

## 3. 核心概念与设计

### 3.1 内置工具：四件套

`start()` 时 `registerBuiltinTools()`（`MCPIntegration.cpp:152-213`）注册四个工具，全部用 cpp-mcp 的 `tool_builder` 声明参数 Schema：

| 工具 | 参数 | 行为 |
|---|---|---|
| `read_file` | path（必填）、max_bytes | 读原始文件内容（`MCPIntegration.cpp:260-274`） |
| `analyze_file` | path、include_keywords | 读文件（上限 50KB）→ 拼 prompt → 经 router 调 LLM 出摘要（`MCPIntegration.cpp:276-322`） |
| `list_files` | path、recursive | 列目录，返回带 size/extension 的 JSON 数组（`MCPIntegration.cpp:324-371`） |
| `generate_description` | paths（逗号分隔多路径） | 汇总每个文件的头 2KB 预览 → LLM 生成整组文件的自然语言描述（`MCPIntegration.cpp:373-441`） |

设计上的分工很清楚：`read_file`/`list_files` 是纯本地操作，`analyze_file`/`generate_description` 才走 LLM——外部 AI 可以只用便宜的浏览工具，把"理解"留给自己的模型，也可以显式借用 TraceLens 配置的模型。

### 3.2 路径白名单：唯一的防线

`isPathAllowed()`（`MCPIntegration.cpp:215-232`）是所有文件操作的守门人：

```cpp
if (allowedPaths_.empty()) {
    return true;  // No restrictions —— 未配置即全放行
}
fs::path absPath = fs::absolute(path);
for (const auto& allowed : allowedPaths_) {
    // std::mismatch：allowed 是 path 的字符级前缀即通过
}
```

两件事值得注意：其一，**默认不设限**——白名单为空时任意路径可读，接线时必须显式调用 `setAllowedPaths()`；其二，前缀匹配是**字符级**而非路径段级，`/data` 会放行 `/database`。对外暴露服务前这两点都应修正（见第 6 节）。

### 3.3 自定义工具注册与"暂存"语义

`registerTool()`（`MCPIntegration.cpp:66-125`）把 JSON Schema 的 `properties`/`required` 翻译成 `tool_builder` 的 `with_string_param`/`with_number_param`/`with_boolean_param` 调用，然后把 C++ 回调（签名 `std::function<std::string(const std::string& argsJson)>`，见 `MCPIntegration.h:23`）包进 cpp-mcp 的 lambda。一个细节：如果服务器尚未 `start()`，handler 只存进 `customHandlers_` 暂存（`MCPIntegration.cpp:70-73`）——但当前实现里暂存的工具不会在之后的 `start()` 中被真正注册（`registerBuiltinTools` 只注册内置四件套），先 register 后 start 的顺序会丢自定义工具。

### 3.4 错误约定

工具回调统一用字符串返回值，出错时以 `"Error: ..."` 开头（如 `MCPIntegration.cpp:235-236, 267`）。调用方（外部 AI）靠这个前缀区分失败与正常文本。这是一个够用但不严格的约定——文件内容本身以 "Error:" 开头时会被误判（`handleAnalyzeFile` 在 `MCPIntegration.cpp:288` 就这样判断读取是否失败）。

## 4. 工作流程走读

假设接线后一次典型交互（外部客户端调用 `analyze_file`）：

1. **启动**：持有方先建好 ModelRouter（注册了模型），然后 `MCPIntegration mcp(router, 8890); mcp.start(false);`。`start()`（`MCPIntegration.cpp:28-53`）读取 `MCP_HOST`、构造 `mcp::server`、设置服务器信息 `"ForensicsLLMServer" 1.0.0`、声明 `tools` 能力、注册内置工具，最后 `server_->start(blocking)`——`blocking=false` 时在后台线程监听。
2. **能力发现**：外部客户端按 MCP 规范连接 SSE 端点并发送 `initialize`/`tools/list`，cpp-mcp 返回四个内置工具（加已注册的自定义工具）的 Schema。
3. **模型决策**：客户端的 AI 看到工具清单，决定调用 `analyze_file` 并给出 `{"path": "/evidence/suspect.log"}`。
4. **执行**（`handleAnalyzeFile`，`MCPIntegration.cpp:276-322`）：
   - 解析参数，`readFileContent(path, 50000)` 读至多 50KB（超限截断，防止超大证据把上下文打爆）；
   - 白名单校验失败或文件不存在时直接返回 `"Error: ..."`；
   - 拼一个结构化 system prompt（要求输出摘要 + 主题 + 可选关键词），文件内容作 user prompt；
   - `router_->chat(userPrompt, systemPrompt)`——走的是与平台内部分析完全相同的路由/重试/模型链路；
   - 成功返回 `response.content`，失败返回 `"Error: LLM analysis failed - <原因>"`。
5. **收尾**：结果以 MCP text 内容回给客户端，AI 继续推理，可能接着调 `read_file` 深挖或 `list_files` 换目录。析构函数 `stop()` 兜底关停（`MCPIntegration.cpp:24-26`）。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| ModelRouter | 构造注入；`analyze_file`/`generate_description` 的 LLM 部分全部经 router，与 FileAnalyzer 共用同一条模型链路 |
| libs/cpp-mcp | 协议实现（JSON-RPC over HTTP+SSE）与 `tool_builder`/`server` API；同时是 httplib 头文件的来源 |
| ConfigManager | 只取 `MCP_HOST`（`getMCPHost()`）；端口与白名单不走 ConfigManager（见第 6 节） |
| FileAnalyzer | 职责近似但独立实现：MCP 工具的分析 prompt 更简单，不复用 FileAnalyzer 的 markitdown 管线/截断/结构化解析——两条并行的"文件→LLM"路径 |

## 6. 注意事项与已知问题

- **未接线**：全仓库无生产调用方，MCP 服务器在当前二进制中不会启动。要在 HTTP 服务里启用，最小接线是：在某个服务的初始化中构造 ModelRouter → `MCPIntegration mcp(router, port); mcp.setAllowedPaths(...); mcp.start(false);`。
- **`.env.example` 与代码脱节**：`.env.example:53-62` 声明了 `MCP_SERVER_PORT`、`MCP_SERVER_HOST`、`MCP_ALLOWED_PATHS`，但**没有任何代码读取这三个键**——实际读的是 `MCP_HOST`（默认 `0.0.0.0`），端口只认构造参数（默认 8890），白名单只认 `setAllowedPaths()`。改配置不会生效，别被示例文件误导。
- **默认 0.0.0.0 + 空白名单**：一旦接线而忘记设白名单，等于向所有网卡暴露无限制文件读取。上线前应默认绑定 127.0.0.1，并把白名单为空的语义改为拒绝。
- **字符级前缀匹配**：`/data` 放行 `/database`（`std::mismatch` 按字符比较，`MCPIntegration.cpp:224-227`）；应改为逐路径段比较或用 `std::filesystem::relative` 判定包含关系。
- **自定义工具的注册顺序依赖**：服务器启动后 `registerTool()` 才真正生效；启动前注册的只被暂存而不会补注册（见 3.3）。
- **目录遍历无上限**：`list_files` 的 recursive 模式对超大目录会生成巨大 JSON 响应，没有分页或条数上限。

## 7. 如何验证与扩展

**验证**（接线后）：
1. 冒烟：`curl <host>:8890` 确认 SSE 端点存活；用任何 MCP 客户端（如 `libs/cpp-mcp` 自带的示例、Claude Desktop 的远程服务器配置）连上后执行 `tools/list`，应看到四个内置工具。
2. 白名单：`setAllowedPaths({"/tmp/evidence"})` 后调 `read_file` 读白名单外路径，应得到 `"Error: Path not allowed"`；再试 `/tmp/evidence-secret` 验证第 6 节提到的前缀漏洞。
3. LLM 链路：`analyze_file` 一个小文本文件，返回应是模型生成的摘要；把 LLM 端点停掉再调，应得到 `"Error: LLM analysis failed - ..."`。

**扩展方向**：
- 补上配置读取：让 `start()` 从 ConfigManager 读 `MCP_SERVER_PORT`/`MCP_ALLOWED_PATHS`，与 `.env.example` 对齐；
- 暴露平台真正的分析能力：注册 `analyze_windows_events`、`analyze_android_db` 之类调用现有分析器的工具，MCP 的价值才从"文件浏览器"升级为"取证助手"；
- 修复 3.3 的暂存语义与第 6 节的前缀匹配问题。

**最后更新**: 2026-08-23（解释式重写）
