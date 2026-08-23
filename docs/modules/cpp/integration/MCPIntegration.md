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

### 3.1 类结构与公开接口

类本身很薄（`MCPIntegration.h:34-108`）：公开面只有生命周期 + 工具注册 + 白名单三类方法；四个内置工具的 handler 与白名单判定是私有实现。自定义工具的回调签名定义在 `MCPIntegration.h:23`：

```cpp
// MCPIntegration.h:23
using MCPToolHandler = std::function<std::string(const std::string& argsJson)>;

// MCPIntegration.h:91-107（私有状态，节选）
std::shared_ptr<ModelRouter> router_;              // LLM 出口（注入）
std::unique_ptr<mcp::server> server_;              // cpp-mcp 服务器实例
int port_;                                        // 构造参数，默认 8890
bool running_ = false;
std::vector<std::string> allowedPaths_;           // 白名单（空 = 全放行）
std::map<std::string, MCPToolHandler> customHandlers_;  // name → 自定义回调

// 内置工具 handler（MCPIntegration.h:100-103）
std::string handleReadFile(const std::string& argsJson);
std::string handleAnalyzeFile(const std::string& argsJson);
std::string handleListFiles(const std::string& argsJson);
std::string handleGenerateDescription(const std::string& argsJson);
```

接口清单（均为真实签名）：

| 方法 | 语义 | 失败/边界行为 |
|---|---|---|
| `MCPIntegration(std::shared_ptr<ModelRouter> router, int port = 8890)` | 构造（不启动服务器） | — |
| `void start(bool blocking = false)` | 读 `MCP_HOST`、建 `mcp::server`、注册内置工具并启动；`blocking=false` 后台监听 | 已运行则直接 return（幂等） |
| `void stop()` / `bool isRunning() const` | 停止/状态；析构函数自动 `stop()` 兜底（`MCPIntegration.cpp:24-26`） | — |
| `void registerTool(name, description, parametersJson, handler)` | 注册自定义工具（见 3.3） | 服务器未启动时 handler 只进暂存表 |
| `void setAllowedPaths(const std::vector<std::string>&)` | 设置文件白名单 | 不持久化、不经 ConfigManager |
| `std::vector<std::string> getRegisteredTools() const` | 返回内置四件套 + 自定义工具名（`MCPIntegration.cpp:135-150`） | — |
| `int getPort() const` | 返回构造端口 | — |

`start()` 的真实装配过程（`MCPIntegration.cpp:28-53`）：

```cpp
// MCPIntegration.cpp:28-53（节选）
void MCPIntegration::start(bool blocking) {
    if (running_) {
        return;
    }
    // Create MCP server configuration
    mcp::server::configuration config;
    config.host = ConfigManager::instance().getMCPHost();   // MCP_HOST，默认 0.0.0.0
    config.port = port_;                                    // 构造参数，默认 8890

    server_ = std::make_unique<mcp::server>(config);
    server_->set_server_info("ForensicsLLMServer", "1.0.0");

    // Set capabilities
    mcp::json capabilities = {
        {"tools", mcp::json::object()}                      // 只声明 tools 能力
    };
    server_->set_capabilities(capabilities);

    // Register built-in tools
    registerBuiltinTools();

    // Start server
    running_ = true;
    server_->start(blocking);
}
```

值得注意：`running_` 在 `server_->start()` **之前**置 true——如果 start 内部失败，标志位与实际状态可能脱节（未接线状态下无实际影响，接线时值得改）。

### 3.2 内置工具：四件套

`start()` 时 `registerBuiltinTools()`（`MCPIntegration.cpp:152-213`）注册四个工具，全部用 cpp-mcp 的 `tool_builder` 声明参数 Schema。以 `analyze_file` 为例看声明形态（`MCPIntegration.cpp:172-183`）：

```cpp
mcp::tool tool = mcp::tool_builder("analyze_file")
    .with_description("Analyze a file and generate a summary using LLM")
    .with_string_param("path", "Path to the file to analyze", true)     // true = 必填
    .with_boolean_param("include_keywords", "Extract keywords from content", false)
    .build();

server_->register_tool(tool,
    [this](const mcp::json& params, const std::string&) -> mcp::json {
        std::string result = handleAnalyzeFile(params.dump());   // 参数序列化回 JSON 字符串
        return {{{"type", "text"}, {"text", result}}};           // MCP text 内容块
    });
```

四个工具的全貌（handler 位置）：

| 工具 | 参数 | 行为 |
|---|---|---|
| `read_file` | path（必填）、max_bytes | 读原始文件内容（`MCPIntegration.cpp:260-274`） |
| `analyze_file` | path、include_keywords | 读文件（上限 50KB）→ 拼 prompt → 经 router 调 LLM 出摘要（`MCPIntegration.cpp:276-322`） |
| `list_files` | path、recursive | 列目录，返回带 size/extension 的 JSON 数组（`MCPIntegration.cpp:324-371`） |
| `generate_description` | paths（逗号分隔多路径） | 汇总每个文件的头 2KB 预览 → LLM 生成整组文件的自然语言描述（`MCPIntegration.cpp:373-441`） |

设计上的分工很清楚：`read_file`/`list_files` 是纯本地操作，`analyze_file`/`generate_description` 才走 LLM——外部 AI 可以只用便宜的浏览工具，把"理解"留给自己的模型，也可以显式借用 TraceLens 配置的模型。

### 3.3 路径白名单：唯一的防线

`isPathAllowed()`（`MCPIntegration.cpp:215-232`）是所有文件操作的守门人，完整实现：

```cpp
// MCPIntegration.cpp:215-232
bool MCPIntegration::isPathAllowed(const std::string& path) const {
    if (allowedPaths_.empty()) {
        return true;  // No restrictions
    }

    fs::path absPath = fs::absolute(path);
    for (const auto& allowed : allowedPaths_) {
        fs::path allowedAbs = fs::absolute(allowed);
        // Check if path starts with allowed path
        auto [iter, _] = std::mismatch(
            allowedAbs.begin(), allowedAbs.end(),
            absPath.begin(), absPath.end());
        if (iter == allowedAbs.end()) {
            return true;
        }
    }
    return false;
}
```

工作机制：`std::mismatch` 并行比较两条路径的**字符**，当 allowed 迭代器先耗尽（`iter == allowedAbs.end()`）说明 allowed 是 path 的字符级前缀，即放行。两件事值得注意：其一，**默认不设限**——白名单为空时任意路径可读，接线时必须显式调用 `setAllowedPaths()`；其二，前缀匹配是**字符级**而非路径段级，`/data` 会放行 `/database`。同时注意它用的是 `fs::absolute`（拼 CWD）而非 `canonical`（解析符号链接），符号链接指向白名单外文件的场景不会被拦截。对外暴露服务前这三点都应修正（见第 6 节）。

### 3.4 自定义工具注册与"暂存"语义

`registerTool()`（`MCPIntegration.cpp:66-125`）把 JSON Schema 的 `properties`/`required` 翻译成 `tool_builder` 的 `with_string_param`/`with_number_param`/`with_boolean_param` 调用，然后把 C++ 回调包进 cpp-mcp 的 lambda。Schema 翻译核心（`MCPIntegration.cpp:88-111` 节选）：

```cpp
// MCPIntegration.cpp:88-111（节选）：JSON Schema → tool_builder 参数
if (params.contains("properties")) {
    for (auto& [key, value] : params["properties"].items()) {
        std::string type = value.value("type", "string");
        std::string desc = value.value("description", "");
        bool required = /* 遍历 params["required"] 查找 key */;
        if (type == "string")              builder.with_string_param(key, desc, required);
        else if (type == "number" || type == "integer") builder.with_number_param(key, desc, required);
        else if (type == "boolean")        builder.with_boolean_param(key, desc, required);
    }
}
```

只认 string/number/integer/boolean 三类——array/object 型参数会被静默丢弃（Schema 不完整但工具仍注册）。一个细节：如果服务器尚未 `start()`，handler 只存进 `customHandlers_` 暂存（`MCPIntegration.cpp:70-73`）——但当前实现里暂存的工具不会在之后的 `start()` 中被真正注册（`registerBuiltinTools` 只注册内置四件套），先 register 后 start 的顺序会丢自定义工具。

### 3.5 错误约定

工具回调统一用字符串返回值，出错时以 `"Error: ..."` 开头（如 `MCPIntegration.cpp:235-236, 267`）。调用方（外部 AI）靠这个前缀区分失败与正常文本。这是一个够用但不严格的约定——文件内容本身以 "Error:" 开头时会被误判（`handleAnalyzeFile` 在 `MCPIntegration.cpp:288` 用 `content.substr(0, 6) == "Error:"` 判断读取是否失败，`handleGenerateDescription` 在 `:414` 同样判法）。异常兜底是每个 handler 最外层的 `catch (const std::exception&) → "Error: " + e.what()`（如 `:271-273`）——JSON 参数解析失败不会让服务器线程崩溃。

## 4. 工作流程走读

假设接线后一次典型交互（外部客户端调用 `analyze_file`）：

1. **启动**：持有方先建好 ModelRouter（注册了模型），然后 `MCPIntegration mcp(router, 8890); mcp.start(false);`。`start()`（`MCPIntegration.cpp:28-53`）读取 `MCP_HOST`、构造 `mcp::server`、设置服务器信息 `"ForensicsLLMServer" 1.0.0`、声明 `tools` 能力、注册内置工具，最后 `server_->start(blocking)`——`blocking=false` 时在后台线程监听。
2. **能力发现**：外部客户端按 MCP 规范连接 SSE 端点并发送 `initialize`/`tools/list`，cpp-mcp 返回四个内置工具（加已注册的自定义工具）的 Schema。
3. **模型决策**：客户端的 AI 看到工具清单，决定调用 `analyze_file` 并给出 `{"path": "/evidence/suspect.log"}`。
4. **执行**（`handleAnalyzeFile`，`MCPIntegration.cpp:276-322`，核心段）：

```cpp
// 读文件内容（先过白名单与存在性检查，见 readFileContent :234-258）
std::string content = readFileContent(path, 50000);  // Limit to 50KB
if (content.substr(0, 6) == "Error:") {
    return content;                                  // 读取失败原样透传 "Error: ..."
}

if (!router_) {
    return "Error: No LLM router configured";
}

// Build analysis prompt
std::string systemPrompt =
    "You are a file analysis assistant. Analyze the following file content and provide:\n"
    "1. A concise summary (2-3 sentences)\n"
    "2. The main purpose or topic of the file\n";
if (includeKeywords) {
    systemPrompt += "3. Key terms or concepts (comma-separated list)\n";
}
systemPrompt += "\nRespond in a structured format.";

std::string userPrompt = "File: " + path + "\n\nContent:\n" + content;

// Get LLM response
auto response = router_->chat(userPrompt, systemPrompt);   // 与平台内部完全相同的链路

if (!response.success) {
    return "Error: LLM analysis failed - " + response.errorMessage;
}
return response.content;
```

   走读要点：`readFileContent(path, 50000)` 读至多 50KB（超限截断，防止超大证据把上下文打爆，`MCPIntegration.cpp:249-252` 的定长 read）；白名单校验失败或文件不存在时直接返回 `"Error: ..."`；`router_->chat()` 走的是与平台内部分析完全相同的路由/重试/模型链路（含 LLMClient 的 4 次重试与 `<think>` 清洗）；成功返回 `response.content`，失败返回 `"Error: LLM analysis failed - <原因>"`。
5. **收尾**：结果以 MCP text 内容回给客户端，AI 继续推理，可能接着调 `read_file` 深挖或 `list_files` 换目录。析构函数 `stop()` 兜底关停（`MCPIntegration.cpp:24-26`）。

**错误处理一览**：

| 故障点 | 返回 | 说明 |
|---|---|---|
| 白名单拒绝 | `Error: Path not allowed`（`:236`） | 空白名单时永不触发 |
| 文件不存在/打不开 | `Error: File not found` / `Error: Cannot open file`（`:240, 245`） | |
| 参数缺失/JSON 坏 | `Error: path parameter is required` / `Error: <exception>` | handler 最外层 catch |
| router 未注入或 chat 失败 | `Error: No LLM router configured` / `Error: LLM analysis failed - ...` | 继承 router/LLMClient 的重试 |
| list_files 目录不存在 | `Error: Directory not found`（`:339`） | |

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
- **字符级前缀匹配**：`/data` 放行 `/database`（`std::mismatch` 按字符比较，`MCPIntegration.cpp:224-227`）；且 `fs::absolute` 不解析符号链接。应改为逐路径段比较或用 `std::filesystem::relative` 判定包含关系。
- **自定义工具的注册顺序依赖**：服务器启动后 `registerTool()` 才真正生效；启动前注册的只被暂存而不会补注册（见 3.4）。
- **目录遍历无上限**：`list_files` 的 recursive 模式对超大目录会生成巨大 JSON 响应，没有分页或条数上限。
- **Schema 翻译只覆盖标量参数**：array/object 类型的 properties 被静默丢弃（3.4 节）。

## 7. 如何验证与扩展

**验证**（接线后）：
1. 冒烟：`curl <host>:8890` 确认 SSE 端点存活；用任何 MCP 客户端（如 `libs/cpp-mcp` 自带的示例、Claude Desktop 的远程服务器配置）连上后执行 `tools/list`，应看到四个内置工具。
2. 白名单：`setAllowedPaths({"/tmp/evidence"})` 后调 `read_file` 读白名单外路径，应得到 `"Error: Path not allowed"`；再试 `/tmp/evidence-secret` 验证第 6 节提到的前缀漏洞。
3. LLM 链路：`analyze_file` 一个小文本文件，返回应是模型生成的摘要；把 LLM 端点停掉再调，应得到 `"Error: LLM analysis failed - ..."`。

**扩展方向**：
- 补上配置读取：让 `start()` 从 ConfigManager 读 `MCP_SERVER_PORT`/`MCP_ALLOWED_PATHS`，与 `.env.example` 对齐；
- 暴露平台真正的分析能力：注册 `analyze_windows_events`、`analyze_android_db` 之类调用现有分析器的工具，MCP 的价值才从"文件浏览器"升级为"取证助手"；
- 修复 3.4 的暂存语义与第 6 节的前缀匹配问题。

## 8. 四工具的参数 Schema 全表（二轮补全）

registerBuiltinTools（MCPIntegration.cpp:152-213）用 tool_builder 声明的完整 Schema——外部 AI 在 `tools/list` 里看到的就是这份：

| 工具 | 参数 | 类型 | 必填 | Schema 默认语义 | handler 实际默认 |
|---|---|---|---|---|---|
| read_file | path | string | 是 | — | 缺失 → "Error: path parameter is required" |
| | max_bytes | number | 否 | 0 = unlimited | `args.value("max_bytes", 0)`（:264）——**0 时全量读入**，与描述一致但无上限保护 |
| analyze_file | path | string | 是 | — | 同上 |
| | include_keywords | boolean | 否 | （Schema 未声明默认） | **handler 默认 true**（:280）——AI 不传参数时也抽关键词，prompt 多一段 |
| list_files | path | string | 是 | — | — |
| | recursive | boolean | 否 | — | 默认 false（:328） |
| generate_description | paths | string（**逗号分隔多路径**，非数组） | 是 | — | 逐个 trim 空白后拆分（:383-393）；空串项丢弃 |

Schema/handler 的两处错位值得记录：include_keywords 的默认值只存在于 handler（Schema 层 AI 看不到"默认开启"的事实）；paths 用逗号分隔字符串而非 JSON 数组是 MCP Schema 翻译层只支持标量（§3.4）的连带后果——外部 AI 传含逗号文件名的路径会被错误切分。

**响应包装**：所有工具结果统一包成 MCP text 内容块 `[{"type":"text","text":<结果>}]`（:166 等）——list_files 的 JSON 数组也是 dump(2) 后塞进 text 字段的**字符串**，不是结构化 content 块；AI 侧拿到的是"看起来像 JSON 的文本"，自己再解析。

## 9. 新走读分支：generate_description 的静默跳过与降级（二轮）

handleGenerateDescription（:373-441）与其他工具的错误策略不同——**白名单外或不存在路径被静默 continue**（:402-405），不报错不出现在结果里：

```cpp
// MCPIntegration.cpp:401-409（节选）
for (const auto& p : paths) {
    if (!isPathAllowed(p)) {
        continue;              // ← 静默跳过，与 read_file 的 "Error: Path not allowed" 不同
    }
    if (fs::exists(p)) {
        fileInfo << "File: " << p << "\n";
        // size/2KB 预览...
    }
}
```

后果：传十个路径、九个被白名单挡掉时，AI 拿到的是一份只描述一个文件的"整组描述"，**没有任何信号说明漏了九个**——对话里 AI 会自信地总结"这组文件是……"。对比 read_file/analyze_file 的显式 Error 约定，这是四件套里唯一"宽容失败"的工具，接线后是最容易产生误导性结论的路径。修复方向：跳过时在 prompt 或结果里注明 "skipped N paths (not allowed/missing)"。

**整组全被跳过时**：fileInfo 为空串 → 仍会调 router_->chat（空内容 prompt）→ 拿回一个对"空"的描述。没有任何分支短路。

## 10. 配置影响表（全集）

| 配置 | 默认 | 消费点 | 状态 |
|---|---|---|---|
| `MCP_HOST` | `0.0.0.0` | ConfigManager.cpp:143 → start() :35 | **唯一被读的 MCP 配置**；不在 .env.example |
| （端口） | 8890（构造参数默认，h:41） | 构造注入 | 无 env；.env.example 的 MCP_SERVER_PORT=8890 未接线 |
| `MCP_SERVER_PORT/HOST`、`MCP_ALLOWED_PATHS` | — | 无读取点 | **未接线**（§6 已记） |
| 白名单 | 空 = 全放行 | setAllowedPaths()（:131-133） | 程序化设置，无持久化 |
| `LLM_TEXT_*`（经注入的 router） | 见 Environment.md | analyze_file/generate_description 的模型 | 与主链路共享配置 |
| server_info | "ForensicsLLMServer"/"1.0.0" 硬编码 | :39 | 与服务版本无联动 |

## 11. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 |
|---|---|---|
| 无被调 | 全仓库 | 零生产构造点（§2） |
| 依赖（设计） | libs/cpp-mcp 的 mcp::server/tool_builder | HTTP+SSE JSON-RPC |
| 依赖（注入） | shared_ptr<ModelRouter> | 两个 LLM 工具的出口 |
| 依赖 | ConfigManager | 仅 getMCPHost |
| 读 | 本地文件系统（白名单约束） | read_file/list_files/analyze_file/generate_description |
| 平行实现 | FileAnalyzer | 独立的"文件→LLM"路径（§5）；prompt/截断策略互不相同（50KB vs FileAnalyzer 的 LLM_MAX_CONTENT_LENGTH） |
| 死位 | registerTool 自定义工具（start 前暂存丢失） | 无调用方；整个类处于未接线状态 |

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
