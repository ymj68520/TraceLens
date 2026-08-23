# VisionAnalysis（src/analyzers/VisionAnalysis/VisionAnalyzer.{h,cpp}）

> **一句话**：多模态 LLM 的图像分析封装——把图片读成 base64、配上取证导向的 prompt、经 ModelRouter 发给视觉模型（默认 qwen3-vl），产出描述/OCR 文本/分析结论。
>
> **⚠️ 死代码（必读）**：本模块**已编译进主程序（CMakeLists 的 LIB_SOURCES 含 `VisionAnalyzer.cpp`），但全项目没有任何生产调用方**。唯一引用者是手工集成测试 `tests/llm_files_test.cpp`。HTTP 任务流水线、CLI、LLMAnalysisService 都不构造 `VisionAnalyzer`。本文按"它本来想做什么"来解释设计，同时明确标注哪些是未接线的现状。

## 1. 为什么有这个模块（设计意图）

文本证据有整条 LLM 链路（FileAnalyzer → ModelRouter → llm_* 列），但取证里另一大类证据——**照片、截图、扫描件**——在纯文本流水线里是"哑巴"：文件分类只会记一个 image/jpg，内容完全不可检索。这个模块的设计意图就是给图像证据补上同等能力：用视觉语言模型（头文件注释明确写的是 Qwen3-VL）做三类事——综合分析（画面里有什么、有什么取证意义）、自然语言描述（两三句话的摘要）、OCR 式文字提取（截图里的聊天记录、扫描件上的文字）。`compareImages` 还设计了双图对比（同一消息里放两张图让模型找差异），对应"同一目录下出现多个相似截图"这类场景。

架构上它是一个很薄的适配层：自己不做任何模型推理，全部委托给 `ModelRouter`（`src/integration/LLMIntegration/`）——把图片编码成 base64 的 `ImageContent`、拼进多模态 `ChatMessage`、以 `ModelCapability::Vision` 发起请求（`VisionAnalyzer.cpp:130`）。Router 负责选哪个模型、发到哪个端点。这个分层意味着：模块本身不关心模型部署在哪（本地 LM Studio/Ollama/vLLM 均可），激活它不需要动模型侧。

## 2. 核心数据结构

模块复用 LLM 集成层的通用类型（`LLMIntegration/LLMDataTypes.h`），自身只定义了类骨架（`VisionAnalyzer.h:21-133`）：

```cpp
// LLMDataTypes.h:69-77  多模态消息里的图片单元
struct ImageContent {
    std::string url;           // URL or base64 data URL
    std::string base64Data;    // Raw base64 encoded image
    std::string mimeType;      // e.g., "image/png", "image/jpeg"
    std::string detail = "auto"; // "low", "high", or "auto"
    bool isBase64() const { return !base64Data.empty(); }
    bool isUrl() const { return !url.empty() && base64Data.empty(); }
};

// LLMDataTypes.h:102-123  OpenAI 风格消息（节选）
struct ChatMessage {
    std::string role;     // "system", "user", "assistant", "tool"
    std::string content;  // Text content
    // Vision support
    std::vector<ImageContent> images;  // Images to include with the message
    ContentType contentType = ContentType::Text;
    ChatMessage(const std::string& r, const std::string& c, const ImageContent& img)
        : role(r), content(c), contentType(ContentType::Image) {
        images.push_back(img);
    }
};
```

`ImageContent` 的双通道设计（URL 或 base64）对应两类证据来源：URL 适合前端直传已托管的图片，base64 适合"本地证据文件读进来就发"。`detail` 字段映射 OpenAI 系视觉 API 的低/高精度档位——取证默认 auto，需要细读小字（如截图聊天记录）时由调用方改 high。`ChatMessage` 的 images 是数组，这正是 `compareImages` 能把两张图放同一条消息的结构基础。

**能力路由枚举**（`LLMDataTypes.h:45-53`）：

```cpp
enum class ModelCapability {
    TextGeneration,
    CodeGeneration,
    Summarization,
    Analysis,
    Translation,
    Vision,           // Image/video understanding
    ImageAnalysis     // Specialized image analysis
};
```

`router_->chat(messages, ModelCapability::Vision)` 按能力选模型——注册表里任何一个 capabilities 含 Vision 的模型都可承接，不绑定具体型号。

### 2.1 核心接口清单

`VisionAnalyzer`（`VisionAnalyzer.h:21-133`）的公开 API：

| 方法 | 语义 | 调用方 | 失败行为 |
|------|------|--------|---------|
| `VisionAnalyzer(std::shared_ptr<ModelRouter>)` | 注入路由器并初始化默认 prompt | 仅 `tests/llm_files_test.cpp` | — |
| `AnalysisResult analyzeImage(imagePath)` | 文件路径入口：存在性/格式/router 三重检查后发起多模态分析 | 同上（生产接线点见第 6 节） | 逐项检查失败都返回带 errorMessage 的结果 |
| `AnalysisResult analyzeImageData(base64, mime)` | 内存数据入口（上游已持有 base64 时） | 预留 | 空数据/无 router 报错 |
| `AnalysisResult analyzeWithPrompt(path, prompt)` | 自定义 prompt 分析 | 预留 | 同上 |
| `std::string extractText(path)` / `describeImage(path)` | OCR 式取文 / 2-3 句描述（换 prompt 的同一管道） | 预留 | 错误串 |
| `std::vector<AnalysisResult> analyzeBatch(paths)` | 批量，每张触发进度回调 | 预留 | 单张失败不影响下一张 |
| `AnalysisResult analyzeVideo(path, maxFrames=5)` | **存根**：格式检查后返回 "not yet implemented" | 无 | 见第 3 节 |
| `std::string compareImages(path1, path2)` | 双图同消息对比 | 预留 | 错误串 |
| `setAnalysisPrompt/setDescriptionPrompt/setOCRPrompt/setProgressCallback` | prompt 与进度定制 | 预留 | — |
| `static isSupportedImage(path)` / `isSupportedVideo(path)` | 按扩展名判格式 | 预留 | — |

## 3. 证据来源与覆盖范围（按设计能力）

- **支持的图片格式**（`isSupportedImage`，`VisionAnalyzer.cpp:381-391`）：`.jpg/.jpeg/.png/.gif/.bmp/.webp/.tiff/.tif`，按扩展名判断。
- **"支持"的视频格式**（`isSupportedVideo`）：`.mp4/.avi/.mov/.mkv/.webm/.flv/.wmv`——但 `analyzeVideo` 是**存根**：

```cpp
// VisionAnalyzer.cpp:305-327（节选）
AnalysisResult VisionAnalyzer::analyzeVideo(const std::string& videoPath, int maxFrames) {
    // ... 存在性与 isSupportedVideo 检查后：
    if (!fs::exists(videoPath)) { /* ... */ }
    // Note: Full video analysis would require ffmpeg for frame extraction
    // For now, return a placeholder indicating the limitation
    result.errorMessage = "Video frame extraction not yet implemented. "
                          "Please extract key frames manually and use analyzeImage().";
    result.description = "Video analysis requires frame extraction. File: " + videoPath;
    return result;
}
```

注释说明完整实现需要 ffmpeg 抽帧；`maxFrames` 参数（头文件注释"Reserved for future frame extraction support"）已预留但未消费。视频证据当前走不通——错误消息里给的变通办法是"人工抽关键帧后走 analyzeImage"。
- 输入途径两种：文件路径（`analyzeImage`，内部读文件转 base64）或直接给 base64 数据（`analyzeImageData`，供上游已持有内存数据的场景）。

## 4. 解析机制走读（作为能力说明）

**链路一：单图分析（`analyzeImage`，`VisionAnalyzer.cpp:89-147`）。**

```cpp
// VisionAnalyzer.cpp:113-138（节选）
    // Create image content
    ImageContent imgContent = createImageContent(imagePath);
    if (imgContent.base64Data.empty()) {
        result.errorMessage = "Failed to load image";
        return result;
    }

    // Create message with image
    ChatMessage msg("user", analysisPrompt_, imgContent);

    std::vector<ChatMessage> messages;
    messages.push_back(ChatMessage("system",
        "You are an expert image analyst. Analyze images thoroughly and provide "
        "detailed, accurate descriptions. Focus on forensically relevant details."));
    messages.push_back(msg);

    // Route to vision model
    auto response = router_->chat(messages, ModelCapability::Vision);

    if (!response.success) {
        result.errorMessage = "Vision analysis failed: " + response.errorMessage;
        return result;
    }

    result.description = response.content;
    result.summary = response.content.substr(0, std::min(size_t(300), response.content.size()));
    result.modelUsed = router_->getLastUsedModel();
    result.tokensUsed = response.promptTokens + response.completionTokens;
```

做什么：`createImageContent` 把文件读成字节并 base64 编码（附上按扩展名推断的 MIME 类型），然后组装消息：system 提示词声明"专业图像分析师，关注取证相关细节"，user 消息由 `analysisPrompt_` 加图片内容构成。`router_->chat(messages, ModelCapability::Vision)` 返回后填充 `AnalysisResult`：描述全文、前 300 字符做摘要、模型名、token 数（prompt+completion 求和）、耗时。前置检查按"存在性 → 格式 → router → 读图"的顺序短路，任何一个失败都返回带 errorMessage 的结果而非抛异常。三个 prompt（analysis/description/ocr）都可以用 setter 覆盖，适配不同案情侧重（如电信诈骗案可换成"重点识别聊天截图中的转账信息"）——默认值在 `initDefaultPrompts`（第 70-87 行）：

```cpp
// VisionAnalyzer.cpp:83-86
    ocrPrompt_ =
        "Extract all text visible in this image. Return only the text content, "
        "preserving the original layout as much as possible. If no text is visible, "
        "respond with 'No text detected'.";
```

OCR prompt 的三个约束（只要文本/保布局/无字时明确说无）让截图证据变成可全文检索的文本——设计上这是图像证据进入搜索/时间线体系的关键一步。

**链路二：手写 base64 编码器（`VisionAnalyzer.cpp:17-61`）。** 模块没有链 OpenSSL，而是自带了一个 45 行的标准 base64 编码器（3 字节→4 字符、尾部补 `=`）。为什么手写：避免为了一个编码函数引入加密库依赖，且 base64 是纯查表算法无安全风险。注意 base64 会使数据放大约 33%，一张 5MB 的照片编码后近 7MB——多模态请求体和 token 消耗都随之增长。

**链路三：批量与对比（`analyzeBatch`/`compareImages`）。** 批量对路径列表逐个调 `analyzeImage`，每张完成触发进度回调（UI 可用）；`compareImages` 把两张图放进同一条消息让模型描述异同：

```cpp
// VisionAnalyzer.cpp:330-352（节选）
    ChatMessage msg;
    msg.role = "user";
    msg.content = "Compare these two images. Describe their similarities and differences. "
                  "Note any significant changes between them.";
    msg.images.push_back(img1);
    msg.images.push_back(img2);
    msg.contentType = ContentType::Image;
```

双图对比直接利用 `ChatMessage::images` 是向量这一点——两次 `push_back` 后模型在同一轮里看到两张图，输出异同描述。两者都是纯编排，无新机制。

## 5. 与 LLM 的协作

本模块本身就是 LLM 协作件，且是项目里唯一使用**多模态消息**（`ImageContent` 挂在 `ChatMessage` 上）的代码。它依赖 `ModelRouter` 的 Vision 能力路由：调用方需先 `router->addModel(...)` 注册一个 `capabilities` 含 `ModelCapability::Vision` 的模型（枚举定义在 `LLMIntegration/LLMDataTypes.h:45-53`，测试 `llm_files_test.cpp:38-45` 是现成的注册示例）。不配置视觉模型时所有调用返回 "Vision analysis failed" 类错误，不会崩溃。

配置侧已经就绪（`ConfigManager.cpp:118-123`）：

```cpp
// ConfigManager.cpp:118-121
std::string ConfigManager::getVisionBaseUrl() const { return get("LLM_VISION_BASE_URL", getLLMBaseUrl()); }
std::string ConfigManager::getVisionModel() const { return get("LLM_VISION_MODEL", "qwen3-vl"); }
int ConfigManager::getVisionMaxTokens() const { return getInt("LLM_VISION_MAX_TOKENS", 4096); }
double ConfigManager::getVisionTemperature() const { return getDouble("LLM_VISION_TEMPERATURE", 0.5); }
```

也就是说 .env 配好 `LLM_VISION_BASE_URL`/`LLM_VISION_MODEL`（缺省回退 `LLM_BASE_URL` 与 `qwen3-vl`）后，模块随时可用，只差调用方。

## 6. 在流水线中的位置（现状：没有位置）

**验证过的现状**：

- 构造 `VisionAnalyzer` 的代码只存在于 `tests/llm_files_test.cpp`（手工跑的集成测试，测试里从 `ConfigManager` 读 `LLM_VISION_MODEL`/`LLM_VISION_BASE_URL` 注册视觉模型后调用）。
- `src/` 下的任何流水线代码（TaskManager、AnalysisOrchestrator、LLMAnalysisService、EventClusterAnalyzer、平台分析器）都不引用它。
- CMakeLists 把它编进 `forensic_analyzer` 主二进制（LIB_SOURCES 段，与 OSSAnalyzer 相邻的注释块）。

因此它的"应有位置"目前只存在于设计里：最自然的挂接点是 LLM 文件分析链（`FileAnalyzer`/`LLMAnalysisService`）——当文件分类判定为图片时走 `analyzeImage` 而不是文本读取，把结果写进 files 表的 `llm_description` 等列。要做这个接线，`AnalysisResult`（`LLMIntegration/LLMDataTypes.h`）与文件分析的落库结构已经对齐。

## 7. 与其他模块的协作 / 注意事项

- **死代码状态再强调**：功能完整（除视频）、配置键就绪、无调用方。若团队决定不启用，可从 CMakeLists 移除以减二进制体积；若要启用，最小改法是在 `FileAnalyzer` 的内容提取分支里对图片类型改调 `VisionAnalyzer`。
- **依赖**：仅内部模块（ModelRouter/ConfigManager）+ 标准库，无 OpenCV/ffmpeg 等外部依赖——这也是视频功能做不了的原因（抽帧需要 ffmpeg）。
- **无单测**：`tests/UnitTest/` 里没有对应文件，只有需要真实视觉模型端点的手工测试；激活前建议先补离线单测（mock router）。
- **大图风险**：base64 会放大约 33%，多模态请求体和 token 消耗随图片尺寸增长，接线时需要尺寸/数量上限（参照 LLMAnalysisService 的 maxFiles/maxContentLength 模式）。

## 8. 如何验证与扩展

- 手工验证：配好 `LLM_VISION_BASE_URL`/`LLM_VISION_MODEL`（或复用 `LLM_BASE_URL`）后跑 `tests/llm_files_test.cpp` 对应的可执行目标，看真实模型的输出质量。
- 激活路径：在 `LLMAnalysisService`/`FileAnalyzer` 里按文件类型分流——图片走 `VisionAnalyzer::analyzeImage`，结果写入 files 表已有的 `llm_*` 列；OCR 文本可同时喂给 FullTextSearch 索引。
- 补视频能力：实现 `analyzeVideo` 的抽帧（popen ffmpeg 每 N 秒取关键帧到临时目录，逐帧复用 `analyzeImage`，聚合结论），`maxFrames` 参数已预留。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
