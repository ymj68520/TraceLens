# VisionAnalysis（src/analyzers/VisionAnalysis/VisionAnalyzer.{h,cpp}）

> **一句话**：多模态 LLM 的图像分析封装——把图片读成 base64、配上取证导向的 prompt、经 ModelRouter 发给视觉模型（默认 qwen3-vl），产出描述/OCR 文本/分析结论。
>
> **⚠️ 死代码（必读）**：本模块**已编译进主程序（CMakeLists 的 LIB_SOURCES 含 `VisionAnalyzer.cpp`），但全项目没有任何生产调用方**。唯一引用者是手工集成测试 `tests/llm_files_test.cpp`。HTTP 任务流水线、CLI、LLMAnalysisService 都不构造 `VisionAnalyzer`。本文按"它本来想做什么"来解释设计，同时明确标注哪些是未接线的现状。

## 1. 为什么有这个模块（设计意图）

文本证据有整条 LLM 链路（FileAnalyzer → ModelRouter → llm_* 列），但取证里另一大类证据——**照片、截图、扫描件**——在纯文本流水线里是"哑巴"：文件分类只会记一个 image/jpg，内容完全不可检索。这个模块的设计意图就是给图像证据补上同等能力：用视觉语言模型（头文件注释明确写的是 Qwen3-VL）做三类事——综合分析（画面里有什么、有什么取证意义）、自然语言描述（两三句话的摘要）、OCR 式文字提取（截图里的聊天记录、扫描件上的文字）。`compareImages` 还设计了双图对比（同一消息里放两张图让模型找差异），对应"同一目录下出现多个相似截图"这类场景。

架构上它是一个很薄的适配层：自己不做任何模型推理，全部委托给 `ModelRouter`（`src/integration/LLMIntegration/`）——把图片编码成 base64 的 `ImageContent`、拼进多模态 `ChatMessage`、以 `ModelCapability::Vision` 发起请求（`VisionAnalyzer.cpp:130`）。Router 负责选哪个模型、发到哪个端点。这个分层意味着：模块本身不关心模型部署在哪（本地 LM Studio/Ollama/vLLM 均可），激活它不需要动模型侧。

## 2. 在流水线中的位置（现状：没有位置）

**验证过的现状**：

- 构造 `VisionAnalyzer` 的代码只存在于 `tests/llm_files_test.cpp`（手工跑的集成测试，测试里从 `ConfigManager` 读 `LLM_VISION_MODEL`/`LLM_VISION_BASE_URL` 注册视觉模型后调用）。
- `src/` 下的任何流水线代码（TaskManager、AnalysisOrchestrator、LLMAnalysisService、EventClusterAnalyzer、平台分析器）都不引用它。
- CMakeLists 把它编进 `forensic_analyzer` 主二进制（LIB_SOURCES 段，与 OSSAnalyzer 相邻的注释块）。

因此它的"应有位置"目前只存在于设计里：最自然的挂接点是 LLM 文件分析链（`FileAnalyzer`/`LLMAnalysisService`）——当文件分类判定为图片时走 `analyzeImage` 而不是文本读取，把结果写进 files 表的 `llm_description` 等列。要做这个接线，`AnalysisResult`（`LLMIntegration/LLMDataTypes.h`）与文件分析的落库结构已经对齐。

配置就绪情况：`ConfigManager` 已经有配套键——`LLM_VISION_BASE_URL`（缺省回退 `LLM_BASE_URL`）与 `LLM_VISION_MODEL`（默认 `qwen3-vl`），见 `src/core/ConfigManager/ConfigManager.cpp:119-126`。也就是说 .env 配好视觉模型端点后，模块随时可用，只差调用方。

## 3. 证据来源与覆盖范围（按设计能力）

- **支持的图片格式**（`isSupportedImage`，`VisionAnalyzer.cpp:381-391`）：`.jpg/.jpeg/.png/.gif/.bmp/.webp/.tiff/.tif`，按扩展名判断。
- **"支持"的视频格式**（`isSupportedVideo`）：`.mp4/.avi/.mov/.mkv/.webm/.flv/.wmv`——但 `analyzeVideo` 是**存根**：只做存在性和格式检查，然后返回 "Video frame extraction not yet implemented. Please extract key frames manually and use analyzeImage()"（第 319-326 行）。注释说明完整实现需要 ffmpeg 抽帧。视频证据当前走不通。
- 输入途径两种：文件路径（`analyzeImage`，内部读文件转 base64）或直接给 base64 数据（`analyzeImageData`，供上游已持有内存数据的场景）。

## 4. 解析机制走读（作为能力说明）

**链路一：单图分析（`analyzeImage`，`VisionAnalyzer.cpp:89-147`）。** 依次做存在性/格式/router 检查，`createImageContent` 把文件读成字节并 base64 编码（手写编码器在第 20-61 行，无 OpenSSL 依赖）附上 MIME 类型，然后组装消息：system 提示词声明"专业图像分析师，关注取证相关细节"，user 消息由 `analysisPrompt_`（四点要求：详细描述/关键对象与人物/可见文字/图像语境，`initDefaultPrompts` 第 71-77 行）加图片内容构成。`router_->chat(messages, ModelCapability::Vision)` 返回后填充 `AnalysisResult`：描述全文、前 300 字符做摘要、模型名、token 数、耗时。三个 prompt（analysis/description/ocr）都可以用 setter 覆盖，适配不同案情侧重（如电信诈骗案可换成"重点识别聊天截图中的转账信息"）。

**链路二：OCR 式文字提取（`extractText`/`ocrPrompt_`）。** 与链路一相同管道，仅换 prompt：要求"只返回文字内容、尽量保留原始布局、无文字时回答 No text detected"。这让截图证据变成可全文检索的文本——设计上这是图像证据进入搜索/时间线体系的关键一步。

**链路三：批量与对比（`analyzeBatch`/`compareImages`）。** 批量对路径列表逐个调 `analyzeImage`，每张完成触发进度回调（UI 可用）；`compareImages` 把两张图放进同一条消息让模型描述异同（第 329-358 行区域）。两者都是纯编排，无新机制。

## 5. 与 LLM 的协作

本模块本身就是 LLM 协作件，且是项目里唯一使用**多模态消息**（`ImageContent` 挂在 `ChatMessage` 上）的代码。它依赖 `ModelRouter` 的 Vision 能力路由：调用方需先 `router->addModel(...)` 注册一个 `capabilities` 含 `ModelCapability::Vision` 的模型（枚举定义在 `LLMIntegration/LLMDataTypes.h:45-53`，测试 `llm_files_test.cpp:38-45` 是现成的注册示例）。不配置视觉模型时所有调用返回 "Vision analysis failed" 类错误，不会崩溃。

## 6. 与其他模块的协作 / 注意事项

- **死代码状态再强调**：功能完整（除视频）、配置键就绪、无调用方。若团队决定不启用，可从 CMakeLists 移除以减二进制体积；若要启用，最小改法是在 `FileAnalyzer` 的内容提取分支里对图片类型改调 `VisionAnalyzer`。
- **依赖**：仅内部模块（ModelRouter/ConfigManager）+ 标准库，无 OpenCV/ffmpeg 等外部依赖——这也是视频功能做不了的原因（抽帧需要 ffmpeg）。
- **无单测**：`tests/UnitTest/` 里没有对应文件，只有需要真实视觉模型端点的手工测试；激活前建议先补离线单测（mock router）。
- **大图风险**：base64 会放大约 33%，多模态请求体和 token 消耗随图片尺寸增长，接线时需要尺寸/数量上限（参照 LLMAnalysisService 的 maxFiles/maxContentLength 模式）。

## 7. 如何验证与扩展

- 手工验证：配好 `LLM_VISION_BASE_URL`/`LLM_VISION_MODEL`（或复用 `LLM_BASE_URL`）后跑 `tests/llm_files_test.cpp` 对应的可执行目标，看真实模型的输出质量。
- 激活路径：在 `LLMAnalysisService`/`FileAnalyzer` 里按文件类型分流——图片走 `VisionAnalyzer::analyzeImage`，结果写入 files 表已有的 `llm_*` 列；OCR 文本可同时喂给 FullTextSearch 索引。
- 补视频能力：实现 `analyzeVideo` 的抽帧（popen ffmpeg 每 N 秒取关键帧到临时目录，逐帧复用 `analyzeImage`，聚合结论），`maxFrames` 参数已预留。

**最后更新**: 2026-08-23（解释式重写）
