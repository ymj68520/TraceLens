# LLMClient（src/integration/LLMIntegration/LLMClient.{h,cpp}）

> **一句话**：一个极薄的 OpenAI 兼容 HTTP 客户端——把聊天消息拼成 `/v1/chat/completions` 请求、带上超时与重试发出去、再把 JSON 响应解析回 C++ 结构体，是整个系统访问大模型的唯一出口。

## 1. 为什么有这个模块

TraceLens 的大量分析环节（文件摘要、事件聚类、DLL 威胁研判、平台取证报告）都需要"把文本丢给大模型拿结论"。如果每个分析器都自己拼 HTTP、自己处理超时和 JSON，会出现：超时口径不一、重试逻辑重复、换一个模型服务商就要改十处代码。

LLMClient 把这些问题收敛到一个类里。它只有约 440 行实现，没有会话管理、没有流式输出、没有 token 计数器——刻意的"薄"。复杂的路由（多模型、故障转移）交给上层的 ModelRouter，内容预处理交给 FileTextProcessor。

**"OpenAI 兼容"意味着什么**：LLMClient 不绑定任何厂商 SDK，只实现 OpenAI 定义的两个 HTTP 约定——

- `POST /v1/chat/completions`：请求体是 `{model, messages[], max_tokens, temperature, tools?}`，响应是 `{choices[0].message.content, tool_calls?}`；
- `GET /v1/models`：返回服务端可用模型列表。

只要一个推理服务实现了这两个端点，就能接入。实践中包括：LM Studio（本项目默认，`.env` 中 `LLM_BASE_URL=http://192.168.31.170:1234`）、Ollama 与 vLLM 的 OpenAI 兼容层、以及任何云厂商的兼容网关——此时把 `LLM_API_KEY` 填上即可，客户端会附加 `Authorization: Bearer <key>` 头（本地服务忽略该头也无所谓，见 `LLMClient.cpp:29-35`）。

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
- **配置从哪来**：`.env` → `ConfigManager`。关键键与默认值（`src/core/ConfigManager/ConfigManager.cpp:86-90`）：`LLM_BASE_URL`（默认 `http://192.168.31.170:1234`）、`LLM_ENDPOINT`（默认 `/v1/chat/completions`）、`LLM_API_KEY`、`LLM_TIMEOUT_SECONDS`（默认 120）、`LLM_MAX_RETRIES`（默认 3）。

## 3. 核心概念与设计

### 3.1 配置结构 LLMConfig

定义在 `LLMDataTypes.h:14-30`。除了连接四要素（baseUrl/endpoint/apiKey/model），还带着**上下文窗口管理**字段：`contextLength`（默认 4096 token）、`reservedTokens`、`charsPerToken`（默认 4.0，中文约 1.5）、`enableChunkedAnalysis`/`maxChunks`。这些字段 LLMClient 自己不用，是留给 FileAnalyzer 做截断/分块预算的（见 FileAnalyzer.md）。一个结构体同时服务两层，省掉了在层间传递配置的样板代码。

注意默认值的分层：`LLMDataTypes.h:21` 里 `timeoutSeconds = 60` 只是**结构体缺省值**；生产路径上所有服务都通过 `ConfigManager::getTextModelConfig()`（`ConfigManager.cpp:105-117`）构造配置，实际生效的是 `.env` 的 120 秒。

### 3.2 URL 拆分：为什么不能把 baseUrl 直接喂给 httplib

httplib 的字符串构造函数只接受 `scheme://host:port`；URL 里一旦带路径（例如反向代理 `https://gw.corp/step_plan`），其内部正则解析失败，会被静默当成 80 端口的主机名，表现为莫名的 "Could not establish connection"。因此 `initHttpClient()`（`LLMClient.cpp:101-130`）先把 baseUrl 手工拆成"可连接端点 + 路径前缀"：

```cpp
auto pathPos = baseUrl.find('/', searchFrom);   // 跳过 scheme:// 之后找第一个 '/'
if (pathPos != std::string::npos) {
    basePath_ = baseUrl.substr(pathPos);       // 例："/step_plan"
    schemeHostPort = baseUrl.substr(0, pathPos); // 例："https://gw.corp"
}
httpClient_ = std::make_unique<httplib::Client>(schemeHostPort);
```

前缀 `basePath_` 存在成员里（`LLMClient.h:103-106`），之后每个请求路径都由 `joinEndpoint()`（`LLMClient.cpp:19-26`）拼接。该函数还处理一个边角：若前缀本身以 `/v1` 结尾，而端点又是 `/v1/chat/completions`，会去掉重复的 `/v1`，避免拼出 `/v1/v1/...`。

### 3.3 请求构造与视觉多模态

`buildRequestBody()`（`LLMClient.cpp:283-363`）把 `ChatMessage` 数组序列化为 OpenAI 格式。有一个关键分支：当消息带图片（`msg.hasImages()`，图片由 `ImageContent` 结构承载，支持 base64 或 URL，`LLMDataTypes.h:69-77`）时，`content` 字段不再是字符串，而是 `[{type:"text"},{type:"image_url"}]` 数组——这正是 OpenAI 视觉模型的约定。base64 图片会被包装成 `data:image/jpeg;base64,...` 数据 URL（`LLMClient.cpp:320-323`）。也就是说，发文本还是发图，对调用方只是"消息里塞没塞 ImageContent"的差别。

`toolsJson` 参数是可选的工具定义 JSON 字符串；非空时原样解析塞进 `tools` 字段并设 `tool_choice: "auto"`（`LLMClient.cpp:353-360`），解析失败则静默跳过（请求照发，只是不带工具）。

### 3.4 响应解析：为推理模型做的三件事

`parseResponse()`（`LLMClient.cpp:365-437`）除了提取 `choices[0].message.content` 和 `tool_calls`，还处理三类真实世界的问题：

1. **reasoning_content 回退**（`LLMClient.cpp:384-388`）：qwen3 等推理模型可能把 token 预算耗在思维链上，`content` 为空、答案在 `reasoning_content` 里。客户端检测到空 content 时回退取后者，避免结果被静默存成空串。
2. **剥离 `<think>` 块**（`LLMClient.cpp:392-403`）：有些模型把思维链直接内联在 content 里，解析时循环删除 `<think>...</think>` 片段，保证入库的描述干净。
3. **tool_calls.arguments 兼容**（`LLMClient.cpp:412-415`）：规范里 arguments 是字符串化的 JSON，但有的服务端返回对象，两种形态都接受。

### 3.5 UTF-8 清洗：取证数据的现实

取证样本里的 wtmp、Cp1252 文本、二进制日志常常混有非法 UTF-8 字节，而 nlohmann::json 的 `dump()` 遇到这种输入会抛 `type_error.316`，历史上曾让整个分析阶段中断。`sanitizeUtf8()`（`LLMClient.cpp:41-88`）在序列化前逐字节校验 UTF-8 序列（含过长编码、代理区、超过 U+10FFFF 的拒绝），把非法序列替换为 `?`。这是一个"宁可丢一个字节，不可炸掉任务"的取舍。

## 4. 工作流程走读

以一次最典型的调用为例：`FileAnalyzer` 想让模型总结一个文件。

1. **构造**：服务初始化时 `ModelRouter::addModel()` 用 `ConfigManager` 给出的 LLMConfig 构造 LLMClient，构造函数转调 `initHttpClient()`（`LLMClient.cpp:90-97, 101-130`），完成 URL 拆分、创建 httplib::Client、设置连接/读/写三个超时（都用同一个 `timeoutSeconds`）。
2. **发起对话**：`chat(prompt, systemPrompt)` 便捷重载（`LLMClient.cpp:208-215`）把 system+user 两条消息组装后转给主 `chat()`。
3. **构造请求体**：`buildRequestBody()` 填入 model/max_tokens/temperature/messages（以及可选的图片数组和 tools），全部文本先过 `sanitizeUtf8`。
4. **发送与重试**（`LLMClient.cpp:171-202`）：

```cpp
int retries = 0;
while (retries <= config_.maxRetries) {          // maxRetries=3 → 最多 4 次尝试
    auto res = httpClient_->Post(joinEndpoint(basePath_, config_.endpoint), ...);
    if (!res) { /* 网络层失败：计入重试 */ }
    if (res->status == 200) return parseResponse(res->body);
    lastError_ = "Server error: " + std::to_string(res->status) + " - " + res->body;
    retries++;
    if (retries <= config_.maxRetries)
        std::this_thread::sleep_for(std::chrono::milliseconds(500 * retries)); // 线性退避
}
```

   重试对"网络错误"和"非 200 状态码"一视同仁；退避是线性的（0.5s、1s、1.5s）。每次尝试都在 `mutex_` 保护下进行。
5. **解析响应**：HTTP 200 后交给 `parseResponse()`，按 3.4 节的规则提取 content/tool_calls/usage，成功时置 `response.success = true`。
6. **健康检查**：`testConnection()`（`LLMClient.cpp:132-152`）用 `GET /v1/models` 当探针，返回 200 视为可达。`listModels()`（`LLMClient.cpp:217-252`）复用同一端点把模型列表解析成 `ModelInfo`。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| ModelRouter | 唯一的常规创建者；每个注册模型持有一个 LLMClient，路由策略决定这次请求用哪一个 |
| FileAnalyzer / MCPIntegration | 经由 router 间接调用，从不直接 new LLMClient |
| ConfigManager | 所有连接参数的来源（`.env`），`setConfig()` 可运行时热更新并重建 HTTP 客户端（`LLMClient.cpp:264-267`） |
| cpp-mcp（第三方） | 提供 httplib 头文件与 TLS 宏开关，见 `CMakeLists.txt:15-18, 234-235` |
| MarkitdownProxy（同目录） | 另一个方向的外部调用：C++ 调 Python 服务的 `/api/markitdown/*`，与 LLMClient 无直接代码依赖，但同属"integration 层的 HTTP 出口" |

## 6. 注意事项与已知问题

- **4xx 也重试**：`chat()` 对所有非 200 都重试，包括 400/401 这类重试不可能救活的错误。配置 `LLM_MAX_RETRIES=3` 时一次坏请求最多浪费 3 次退避等待。若要优化，可对 4xx（除 429）立即失败。
- **单个客户端是串行的**：重试循环持有 `mutex_`，意味着同一个 LLMClient 的并发 chat 会在 HTTP 层排队。FileAnalyzer 的批量并行（线程池）只在"读文件/转换"阶段真正并行，LLM 调用最终仍串行过这把锁。要真正并发，需要每个 worker 一个 client（目前各服务只注册一个模型）。
- **listModels 的能力信息是假的**：它给每个发现的模型统一贴上 TextGeneration/Summarization/Analysis 三个能力（`LLMClient.cpp:238-243`），并没有向服务端查询真实能力，`supportsVision` 恒为 false。基于 capability 的路由不要依赖它。
- **`testConnection` 语义偏严**：要求 `/v1/models` 返回 200；个别兼容实现只实现 chat 端点时会被误判为不可达。
- **两处 UTF-8 清洗实现不一致**：本文件的 `sanitizeUtf8`（严格，拒绝过长编码/代理区）与 `FileTextProcessor::sanitizeUTF8`（宽松，只查连续字节）规则不同，属历史并存，修改时注意两处都要改。

## 7. 如何验证与扩展

**验证**：
1. 起一个 LM Studio（或任意兼容端点），`.env` 里指向它，跑任一 LLM 分析接口后看后端日志的 `Server error:`/`Request failed:` 前缀即可区分服务端错误与网络错误。
2. 单元测试思路：构造 `LLMConfig` 指向本地 mock（例如用 python 起一个返回固定 JSON 的 /v1/chat/completions），分别断言：重试次数 = maxRetries+1；含 `<think>` 的响应被清洗；非法 UTF-8 输入不再让请求构造抛异常。
3. `testConnection()` 可作为最小连通性冒烟（注意上一节的语义限制）。

**扩展方向**：
- 要支持流式输出：httplib 支持 chunked 响应回调，但需要改 `chat()` 的响应处理路径，并给 LLMResponse 增量语义——工作量在调用方协议，不在 HTTP 层。
- 要按模型并发：给 LLMClient 增加实例池，或在 ModelRouter 里对同一模型注册多个 entry。
- 要更精细的错误分类：在 `chat()` 里区分可重试（网络、5xx、429）与不可重试（其余 4xx）。

**最后更新**: 2026-08-23（解释式重写）
