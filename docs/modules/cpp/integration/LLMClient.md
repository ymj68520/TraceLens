# LLMClient（src/integration/LLMIntegration/LLMClient.{h,cpp}）

> **一句话**：一个极薄的 OpenAI 兼容 HTTP 客户端——把聊天消息拼成 `/v1/chat/completions` 请求、带上超时与重试发出去、再把 JSON 响应解析回 C++ 结构体，是整个系统访问大模型的唯一出口。

## 1. 为什么有这个模块

TraceLens 的大量分析环节（文件摘要、事件聚类、DLL 威胁研判、平台取证报告）都需要"把文本丢给大模型拿结论"。如果每个分析器都自己拼 HTTP、自己处理超时和 JSON，会出现：超时口径不一、重试逻辑重复、换一个模型服务商就要改十处代码。

LLMClient 把这些问题收敛到一个类里。它只有约 440 行实现，没有会话管理、没有流式输出、没有 token 计数器——刻意的"薄"。复杂的路由（多模型、故障转移）交给上层的 ModelRouter，内容预处理交给 FileTextProcessor。**"OpenAI 兼容"意味着**：LLMClient 不绑定任何厂商 SDK，只实现 OpenAI 定义的两个 HTTP 约定——

- `POST /v1/chat/completions`：请求体是 `{model, messages[], max_tokens, temperature, tools?}`，响应是 `{choices[0].message.content, tool_calls?}`；
- `GET /v1/models`：返回服务端可用模型列表。

只要一个推理服务实现了这两个端点，就能接入。实践中包括：LM Studio（本项目默认，`.env` 中 `LLM_BASE_URL=http://192.168.31.170:1234`）、Ollama 与 vLLM 的 OpenAI 兼容层、以及任何云厂商的兼容网关——此时把 `LLM_API_KEY` 填上即可，客户端会附加 `Authorization: Bearer <key>` 头（`authHeaders()`，`LLMClient.cpp:29-35`：仅在 key 非空时附加，本地 LM Studio 忽略该头，云网关强依赖它；一个 `if` 同时服务两种部署）。

## 2. 在系统中的位置

```
LLMAnalysisService / Windows/Linux/AndroidLLMAnalysisService / EventClusterAnalyzer
        │  （各服务自建一个 ModelRouter，注册模型）
        ▼
ModelRouter ──每个注册模型持有一个──► LLMClient ──HTTP──► LM Studio / vLLM / 云端兼容端点
        ▲
DLLAnalyzerLLMService、FileAnalyzer、MCPIntegration（经由 router 间接使用）
```

- **谁创建它**：几乎只有 `ModelRouter::addModel()`（`ModelRouter.cpp:21`）会构造 LLMClient——每个注册模型一个实例。业务代码不直接持有 LLMClient。
- **它调用谁**：cpp-httplib（取自第三方库 `libs/cpp-mcp/common/httplib.h`，CMake 在 `CMakeLists.txt:18` 打开 `CPPHTTPLIB_OPENSSL_SUPPORT`，因此 https 端点也可用）和 nlohmann::json。
- **配置从哪来**：`.env` → `ConfigManager`。

**六个消费服务与 env 全表**（配置键定义在 `src/core/ConfigManager/ConfigManager.cpp:86-122`，所有服务经 `getTextModelConfig()`（`:105-117`）装配；六个注册点：`LLMAnalysisService.cpp:38`、`WindowsLLMAnalysisService.cpp:29`、`LinuxLLMAnalysisService.cpp:29`、`AndroidLLMAnalysisService.cpp:30`、`EventClusterAnalyzer.cpp:29`、`DLLAnalyzerLLMService.cpp:90`）：

| env 键 | 默认值 | 用途 |
|---|---|---|
| `LLM_BASE_URL` | `http://192.168.31.170:1234` | 基础 URL（含路径前缀时会被拆分，见 3.3） |
| `LLM_ENDPOINT` | `/v1/chat/completions` | chat 端点路径 |
| `LLM_API_KEY` | `""` | Bearer 头；空则不发 |
| `LLM_TIMEOUT_SECONDS` | `120` | 连接/读/写三个超时共用 |
| `LLM_MAX_RETRIES` | `3` | 额外重试次数（实际最多 4 次尝试，见第 4 节） |
| `LLM_TEXT_BASE_URL` / `LLM_TEXT_MODEL` | 回落 `LLM_BASE_URL` / `gpt-oss` | 文本模型组（`:99-100`） |
| `LLM_TEXT_MAX_TOKENS` / `LLM_TEXT_TEMPERATURE` | `2048` / `0.7` | 采样参数 |
| `LLM_VISION_BASE_URL` / `LLM_VISION_MODEL` | 回落 `LLM_BASE_URL` / `qwen3-vl` | 视觉模型组（`getVisionModelConfig`，已就绪、无生产调用方） |
| `LLM_VISION_MAX_TOKENS` / `LLM_VISION_TEMPERATURE` | `4096` / `0.5` | 视觉采样参数 |

## 3. 核心概念与设计

### 3.1 核心数据结构：一个头文件管四种角色

LLMIntegration 层的数据契约全部集中在 `LLMDataTypes.h`。先看配置结构（`LLMDataTypes.h:14-30`）：

```cpp
struct LLMConfig {
    std::string baseUrl = "http://192.168.31.170:1234";  // OpenAI-compatible endpoint
    std::string endpoint = "/v1/chat/completions";
    std::string apiKey = "";  // Optional for local LM Studio
    std::string model = "";   // Model name, empty for auto-select
    int maxTokens = 2048;
    double temperature = 0.7;
    int timeoutSeconds = 60;
    int maxRetries = 3;
    // Context window management（LLMClient 不用，留给 FileAnalyzer）
    int contextLength = 4096;         // Total context window size in tokens
    int reservedTokens = 512;         // Reserved for system prompt + response
    double charsPerToken = 4.0;       // Estimated chars per token (Chinese ~1.5, English ~4)
    bool enableChunkedAnalysis = true;
    int maxChunks = 5;
};
```

逐字段读：前四个是连接四要素；`maxTokens/temperature` 原样进请求体；`timeoutSeconds/maxRetries` 驱动第 4 节的重试矩阵。后五个**上下文窗口管理**字段 LLMClient 自己完全不用——是留给 FileAnalyzer 做截断/分块预算的（见 FileAnalyzer.md）。一个结构体同时服务两层，省掉了层间传配置的样板代码。注意默认值分层：`LLMDataTypes.h:21` 的 `timeoutSeconds = 60` 只是**结构体缺省值**；生产路径全走 `getTextModelConfig()`，实际生效的是 `.env` 的 120 秒。

再看"一次对话"的三种载荷（节选自 `LLMDataTypes.h:102-145`）：

```cpp
struct ChatMessage {
    std::string role;        // "system", "user", "assistant", "tool"
    std::string content;     // Text content
    std::string name;        // Optional: function name for tool messages
    std::string toolCallId;  // Optional: for tool responses
    std::vector<ImageContent> images;  // Images to include with the message
    bool hasImages() const { return !images.empty(); }   // 3.4 节分支的开关
};
struct LLMResponse {               // :137-145
    std::string content;
    std::vector<ToolCall> toolCalls;   // ToolCall{id,name,arguments}，:128-132
    std::string finishReason;  // "stop", "tool_calls", "length"
    int promptTokens = 0;
    int completionTokens = 0;
    bool success = false;      // 只有 parseResponse() 提取到 choices 才置 true
    std::string errorMessage;
};
```

`ChatMessage` 是 OpenAI 消息格式的超集：`name/toolCallId` 为 tool-calling 回合准备，`images` 挂 `ImageContent`（base64 或 URL，`LLMDataTypes.h:69-77`）即变成视觉消息。`promptTokens/completionTokens` 从响应 `usage` 段抄回，FileAnalyzer 把它们累加进 `AnalysisResult.tokensUsed` 入库。

### 3.2 公开接口清单（LLMClient.h:44-98）

| 方法（真实签名节选） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `bool testConnection()` | `GET /v1/models` 当探针 | ModelRouter::refreshAvailability | 非 200 或传输失败 → false，`lastError_` 记原因 |
| `LLMResponse chat(const std::vector<ChatMessage>&, const std::string& toolsJson = "")` | 主对话入口 | ModelRouter（唯一） | 重试耗尽 → `success=false` + errorMessage |
| `LLMResponse chat(const std::string& prompt, const std::string& systemPrompt = "")` | system+user 便捷重载 | ModelRouter 的便捷 `chat()` | 同上（转调主 chat） |
| `std::vector<ModelInfo> listModels()` | 解析 `/v1/models` 为 ModelInfo | 暂无生产调用方 | 非 200/解析异常 → 空向量 + lastError_ |
| `void setConfig(const LLMConfig&)` | 热更新配置并**重建** HTTP 客户端（`LLMClient.cpp:264-267`） | 无生产调用方 | — |
| `setModel/getModel/isReady/getLastError` | 换模型名 / 状态查询 | 无生产调用方 / 调试 | — |

类是不可拷贝的（`LLMClient.h:37-38` delete 拷贝构造/赋值），因为持有 `unique_ptr<httplib::Client>`；私有成员 `basePath_` 的存在理由见下一节（`LLMClient.h:103-106` 的注释原话）。

### 3.3 URL 拆分：为什么不能把 baseUrl 直接喂给 httplib

httplib 的字符串构造函数只接受 `scheme://host:port`；URL 里一旦带路径（例如反向代理 `https://gw.corp/step_plan`），其内部正则解析失败，会被静默当成 80 端口的主机名，表现为莫名的 "Could not establish connection"。因此 `initHttpClient()`（`LLMClient.cpp:101-130`）先把 baseUrl 手工拆成"可连接端点 + 路径前缀"：

```cpp
// LLMClient.cpp:101-130（节选）
size_t searchFrom = 0;
auto schemePos = baseUrl.find("://");
if (schemePos != std::string::npos) searchFrom = schemePos + 3;  // 跳过 scheme
auto pathPos = baseUrl.find('/', searchFrom);
if (pathPos != std::string::npos) {
    basePath_ = baseUrl.substr(pathPos);          // 例："/step_plan"
    while (!basePath_.empty() && basePath_.back() == '/') basePath_.pop_back();
    schemeHostPort = baseUrl.substr(0, pathPos);  // 例："https://gw.corp"
}
// httplib::Client 只喂 scheme://host:port；连接/读/写三个 set_*_timeout
// 统一用同一个 timeoutSeconds（没有分别调参的口子）。
```

关键点：① `searchFrom` 跳过 `scheme://`，避免把 `//` 后的第一个空路径段误当路径；② 前缀尾部 `/` 被剥掉，保证后续拼接不产生 `//`；③ **连接/读/写三个超时没有分别调参的口子**——`LLM_TIMEOUT_SECONDS=120` 意味着最坏情况一次尝试可以挂 3×120s；④ 整个函数持 `mutex_`，与 `chat()` 的锁是同一把，热更新（`setConfig` → `initHttpClient`）与请求互斥。

前缀 `basePath_` 存在成员里（`LLMClient.h:103-106`），之后每个请求路径都由 `joinEndpoint()`（`LLMClient.cpp:19-26`）拼接。该函数还处理一个边角：若前缀本身以 `/v1` 结尾，而端点又是 `/v1/chat/completions`，会去掉重复的 `/v1`，避免拼出 `/v1/v1/...`（`https://gw/step_plan/v1` + `/v1/chat/completions` → `/step_plan/v1/chat/completions`）。

### 3.4 请求构造与视觉多模态

`buildRequestBody()`（`LLMClient.cpp:283-363`）把 `ChatMessage` 数组序列化为 OpenAI 格式。关键分支——消息带图片时 `content` 从字符串换成数组（`LLMClient.cpp:301-340` 节选）：

```cpp
// LLMClient.cpp:301-340（节选：content 从字符串换成数组）
if (msg.hasImages()) {
    json contentArray = json::array();
    if (!msg.content.empty())
        contentArray.push_back({{"type", "text"}, {"text", sanitizeUtf8(msg.content)}});
    for (const auto& img : msg.images) {
        json imageObj;
        imageObj["type"] = "image_url";
        json imageUrl;
        if (img.isBase64()) {
            // Format: data:image/jpeg;base64,{base64_data}
            std::string mimeType = img.mimeType.empty() ? "image/jpeg" : img.mimeType;
            imageUrl["url"] = "data:" + mimeType + ";base64," + img.base64Data;
        } else if (img.isUrl()) {
            imageUrl["url"] = img.url;
        }
        // ... detail 字段（"low"/"high"/"auto"）控制视觉 token 预算 ...
        imageObj["image_url"] = imageUrl;
        contentArray.push_back(imageObj);
    }
    msgObj["content"] = contentArray;      // 数组形态（视觉）
} else {
    msgObj["content"] = sanitizeUtf8(msg.content);   // 字符串形态（标准文本）
}
```

这正是 OpenAI 视觉模型的约定：`content` 是 `[{type:"text"},{type:"image_url"}]` 数组，base64 图片包装成 `data:image/jpeg;base64,...` 数据 URL——发文本还是发图，对调用方只是"消息里塞没塞 ImageContent"的差别。

`toolsJson` 参数是可选的工具定义 JSON 字符串；非空时原样解析塞进 `tools` 字段并设 `tool_choice: "auto"`（`LLMClient.cpp:353-360`），解析失败则静默跳过（请求照发，只是不带工具）——一个 try/catch 吞掉的降级，调用方无法感知 tools 没带上。

### 3.5 响应解析：为推理模型做的三件事

`parseResponse()`（`LLMClient.cpp:365-437`）除了提取 `choices[0].message.content` 和 `tool_calls`，还处理三类真实世界的问题。前两件的核心代码：

```cpp
// LLMClient.cpp:376-403（节选）
if (message.contains("content") && !message["content"].is_null())
    response.content = message["content"].get<std::string>();

// Reasoning models (e.g. qwen3.x) can exhaust the token budget on
// chain-of-thought and return empty content with the answer in
// reasoning_content. Fall back to it so results are not silently
// stored as empty text.
if (response.content.empty() && message.contains("reasoning_content") &&
    !message["reasoning_content"].is_null() &&
    message["reasoning_content"].is_string())
    response.content = message["reasoning_content"].get<std::string>();

// Some reasoning models inline <think>...</think> in content;
// strip those blocks so stored descriptions stay clean.
if (response.content.find("<think>") != std::string::npos) {
    std::string& s = response.content;
    size_t start;
    while ((start = s.find("<think>")) != std::string::npos) {
        size_t end = s.find("</think>", start);
        if (end == std::string::npos) { s.erase(start); break; }  // 未闭合：删到串尾
        s.erase(start, end - start + 8);
    }
}
```

三件事逐条读：① **reasoning_content 回退**——qwen3 等推理模型可能把 token 预算耗在思维链上，`content` 为空、答案在 `reasoning_content` 里，检测到空 content 时回退取后者，避免结果被静默存成空串；② **剥离 `<think>` 块**——有些模型把思维链内联在 content 里，循环删除 `<think>...</think>`，未闭合标签（输出被 max_tokens 截断时常见）删到串尾；③ **tool_calls.arguments 兼容**（`LLMClient.cpp:412-415`）——规范里 arguments 是字符串化 JSON，但有的服务端返回对象，`is_string()` 走 `get<std::string>()`、否则 `dump()` 还原，两种形态都接受。

### 3.6 UTF-8 清洗：取证数据的现实

取证样本里的 wtmp、Cp1252 文本、二进制日志常常混有非法 UTF-8 字节，而 nlohmann::json 的 `dump()` 遇到这种输入会抛 `type_error.316`，历史上曾让整个分析阶段中断。`sanitizeUtf8()`（`LLMClient.cpp:41-88`）在序列化前逐字节校验：

```cpp
// LLMClient.cpp:44-53, 69-85（节选）
for (size_t i = 0; i < in.size();) {
    unsigned char c = static_cast<unsigned char>(in[i]);
    size_t need = 0;
    if (c < 0x80) { out.push_back(static_cast<char>(c)); ++i; continue; }
    else if ((c & 0xE0) == 0xC0) need = 2;    // 按首字节定序列长度
    else if ((c & 0xF0) == 0xE0) need = 3;
    else if ((c & 0xF8) == 0xF0) need = 4;
    // ... 逐个校验 need-1 个连续字节 (10xx xxxx)，拼出 codepoint；拒绝
    //     overlong encodings / UTF-16 surrogates (U+D800-DFFF) / > U+10FFFF ...
    if (valid) { out.append(in, i, need); i += need; }
    else       { out.push_back('?'); ++i; }   // 非法序列 → '?'，且只前进 1 字节
}
```

非法序列替换为 `?` 且只前进一个字节（不吞掉后续合法字节）；拒绝**过长编码**（如 3 字节编码 ASCII）、**代理区**与**超 U+10FFFF** 值。这是一个"宁可丢一个字节，不可炸掉任务"的取舍。

## 4. 工作流程走读

以一次最典型的调用为例：`FileAnalyzer` 想让模型总结一个文件。

1. **构造**：`ModelRouter::addModel()` 用 `ConfigManager` 给出的 LLMConfig 构造 LLMClient，构造函数转调 `initHttpClient()`（`LLMClient.cpp:90-97, 101-130`），完成 URL 拆分、创建 httplib::Client、设置三个超时。
2. **发起对话**：`chat(prompt, systemPrompt)` 便捷重载（`LLMClient.cpp:208-215`）组装 system+user 两条消息后转给主 `chat()`；`buildRequestBody()` 填入 model/max_tokens/temperature/messages（及可选的图片数组和 tools），全部文本先过 `sanitizeUtf8`。
3. **发送与重试**（`LLMClient.cpp:171-202` 节选，注释为本文所加）：

```cpp
int retries = 0;
while (retries <= config_.maxRetries) {          // maxRetries=3 → 最多 4 次尝试（首试含在 while 内）
    std::lock_guard<std::mutex> lock(mutex_);    // 每次尝试单独持锁
    auto res = httpClient_->Post(joinEndpoint(basePath_, config_.endpoint),
                                 requestHeaders, requestBody, "application/json");
    if (!res) {                                  // 网络层失败（连接/超时/断流）
        lastError_ = "Request failed: " + httplib::to_string(res.error());
        retries++;
        if (retries <= config_.maxRetries) {
            std::this_thread::sleep_for(std::chrono::milliseconds(500 * retries)); // 线性退避
            continue;
        }
        response.errorMessage = lastError_;      // 重试耗尽
        return response;
    }
    if (res->status == 200) return parseResponse(res->body);   // 唯一成功出口
    lastError_ = "Server error: " + std::to_string(res->status) + " - " + res->body;
    retries++;                                   // 非 200 一律计入重试（含 4xx）
    if (retries <= config_.maxRetries)
        std::this_thread::sleep_for(std::chrono::milliseconds(500 * retries));
}
response.errorMessage = lastError_;
return response;
```

   重试对"网络错误"和"非 200 状态码"一视同仁；`while` 条件是 `retries <= maxRetries`，**首试不消耗重试额度，`LLM_MAX_RETRIES=3` 实际是 1+3=4 次尝试**；退避是线性的（0.5s、1s、1.5s）；每次尝试都在 `mutex_` 保护下进行。
4. **解析响应**：HTTP 200 后交给 `parseResponse()`，按 3.5 节规则提取 content/tool_calls/usage。`parseResponse()` 内部的 JSON 异常（如服务端返回 HTML 错误页）被 catch 成 `errorMessage = "Failed to parse response: ..."`——**传输成功但解析失败按失败处理，不重试**（重试循环在它之前就返回了）。
5. **健康检查**：`testConnection()`（`LLMClient.cpp:132-152`）用 `GET /v1/models` 当探针，返回 200 视为可达。`listModels()`（`LLMClient.cpp:217-252`）复用同一端点把模型列表解析成 `ModelInfo`。

**错误处理矩阵**：

| 故障 | 表现 | 处理 |
|---|---|---|
| 连接失败/超时/断流 | `res` 为空 | 计入重试，线性退避，最多 4 次 |
| 非 200（含 400/401/429/5xx） | `lastError_ = "Server error: <status> - <body>"` | 同上（4xx 也重试，见第 6 节） |
| 200 但 body 非法 JSON | `parseResponse` 抛异常被捕获 | 直接失败返回，**不重试** |
| toolsJson 非法 | `buildRequestBody` 内 catch | 静默丢弃 tools，请求照发 |
| 文本含非法 UTF-8 | — | `sanitizeUtf8` 替换为 `?`，不影响请求 |

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| ModelRouter | 唯一的常规创建者；每个注册模型持有一个 LLMClient，路由策略决定这次请求用哪一个 |
| FileAnalyzer / MCPIntegration | 经由 router 间接调用，从不直接 new LLMClient |
| ConfigManager | 所有连接参数的来源（`.env`），`setConfig()` 可运行时热更新并重建 HTTP 客户端 |
| cpp-mcp（第三方） | 提供 httplib 头文件与 TLS 宏开关，见 `CMakeLists.txt:15-18, 234-235` |
| MarkitdownProxy（同目录） | 另一个方向的外部调用：C++ 调 Python 服务的 `/api/markitdown/*`，与 LLMClient 无直接代码依赖，但同属"integration 层的 HTTP 出口" |

## 6. 注意事项与已知问题

- **4xx 也重试**：`chat()` 对所有非 200 都重试，包括 400/401 这类重试不可能救活的错误。配置 `LLM_MAX_RETRIES=3` 时一次坏请求最多浪费 3 次退避等待。若要优化，可对 4xx（除 429）立即失败。
- **单个客户端是串行的**：重试循环持有 `mutex_`（每次尝试各持一次，`LLMClient.cpp:173`），意味着同一个 LLMClient 的并发 chat 会在 HTTP 层排队。FileAnalyzer 的批量并行（线程池）只在"读文件/转换"阶段真正并行，LLM 调用最终仍串行过这把锁。要真正并发，需要每个 worker 一个 client（目前各服务只注册一个模型）。
- **listModels 的能力信息是假的**：它给每个发现的模型统一贴上 TextGeneration/Summarization/Analysis 三个能力（`LLMClient.cpp:238-243`），并没有向服务端查询真实能力，`supportsVision` 恒为 false。基于 capability 的路由不要依赖它。
- **`testConnection` 语义偏严**：要求 `/v1/models` 返回 200；个别兼容实现只实现 chat 端点时会被误判为不可达。
- **两处 UTF-8 清洗实现不一致**：本文件的 `sanitizeUtf8`（严格，拒绝过长编码/代理区）与 `FileTextProcessor::sanitizeUTF8`（宽松，只查连续字节）规则不同，属历史并存，修改时注意两处都要改。
- **`parseResponse` 失败不重试**：服务端偶发返回截断 JSON 时（网络正常、200 但 body 坏），该次调用直接失败——重试保护只覆盖传输层，不覆盖解析层。

## 7. 如何验证与扩展

**验证**：
1. 起一个 LM Studio（或任意兼容端点），`.env` 里指向它，跑任一 LLM 分析接口后看后端日志的 `Server error:`/`Request failed:` 前缀即可区分服务端错误与网络错误。
2. 单元测试思路：构造 `LLMConfig` 指向本地 mock（例如用 python 起一个返回固定 JSON 的 /v1/chat/completions），分别断言：重试次数 = maxRetries+1；含 `<think>`（含未闭合形态）的响应被清洗；`reasoning_content`-only 响应回退成功；非法 UTF-8 输入不再让请求构造抛异常。
3. `testConnection()` 可作为最小连通性冒烟（注意上一节的语义限制）。

**扩展方向**：
- 要支持流式输出：httplib 支持 chunked 响应回调，但需要改 `chat()` 的响应处理路径，并给 LLMResponse 增量语义——工作量在调用方协议，不在 HTTP 层。
- 要按模型并发：给 LLMClient 增加实例池，或在 ModelRouter 里对同一模型注册多个 entry。
- 要更精细的错误分类：在 `chat()` 里区分可重试（网络、5xx、429）与不可重试（其余 4xx）。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
