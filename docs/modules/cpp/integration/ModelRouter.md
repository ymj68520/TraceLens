# ModelRouter（src/integration/LLMIntegration/ModelRouter.{h,cpp}）

> **一句话**：多模型调度器——持有一组带元数据的 LLMClient，按策略（优先级/能力/轮询/负载/故障回退）决定一次 LLM 请求发给谁，是所有 LLM 服务与底层 HTTP 客户端之间唯一的中介。

## 1. 为什么有这个模块

如果全系统只用一个模型、一个端点，那直接用 LLMClient 就够了。但取证场景对模型的需求天然是分层的：

- **故障转移**：本地 LM Studio 挂了或过载时，切到备用端点继续分析，而不是整个取证任务失败；
- **成本/速度分层**：摘要、关键词这类廉价任务走小模型，深度研判走大模型（priority 体现偏好）；
- **能力分工**：文本日志分析用文本模型，截图/界面图像研判必须用视觉模型——两类模型的 baseUrl/model 名通常都不同。

把"选哪个模型"的决策集中到一处，业务服务只需说"我要一次 TextGeneration 能力的对话"，而不必关心背后有几个端点、谁活着。这就是 ModelRouter 存在的理由。配置层已经为此预留了独立的 `LLM_TEXT_*` / `LLM_VISION_*` 环境变量组（`src/core/ConfigManager/ConfigManager.cpp:100-122`，`LLM_TEXT_BASE_URL` 缺省回落到 `LLM_BASE_URL`），对应 `getTextModelConfig()` / `getVisionModelConfig()` 两个工厂方法。

## 2. 在系统中的位置

```
network/HTTPServer:                                analyzers:
  LLMAnalysisService.cpp:38                          DLLAnalyzer/Core/DLLAnalyzerLLMService.cpp:90
  WindowsLLMAnalysisService.cpp:29
  LinuxLLMAnalysisService.cpp:29                     （EventClusterAnalyzer.cpp:29 在 network 下）
  AndroidLLMAnalysisService.cpp:30
        │ 各自 new ModelRouter + addModel(...)
        ▼
   ModelRouter ── name → ModelEntry{config, info, unique_ptr<LLMClient>} ──► LLMClient
        ▲
   FileAnalyzer / MCPIntegration 构造时接收 shared_ptr<ModelRouter>，只调 router->chat()
```

六个服务（五个 LLM 分析服务 + DLLAnalyzerLLMService）各自持有一个 ModelRouter 实例，并在初始化时注册模型。**当前现实**：每个服务都只注册了一个名为 `"default"`（DLL 分析为 `"dll_analyzer"`）的文本模型——`getVisionModelConfig()` 已就绪但还没有生产调用方，多模型的潜力尚未兑现。这也是为什么理解这个类的结构比记住它的现状更重要：它是按"多模型"设计的，接线只接了一根。

## 3. 核心概念与设计

### 3.1 ModelEntry：一个模型的全部状态

每个注册模型对应一个 `ModelEntry`（`ModelRouter.h:108-115`）：配置、元数据、独占的 LLMClient，外加两个原子计数——`currentLoad`（正在进行的请求数，LoadBalance 用）和 `failureCount`（失败次数，Fallback 排序用）。模型表是 `std::map<name, unique_ptr<ModelEntry>>`，名字是唯一键；第一个注册的模型自动成为首选（`ModelRouter.cpp:26-28`）。

### 3.2 五种路由策略

策略枚举定义在 `LLMDataTypes.h:180-186`，默认 `Fallback`（`ModelRouter.h:118`）：

| 策略 | 选择逻辑 | 适用场景 |
|---|---|---|
| Priority | 可用且具备所需能力的模型中 priority 最高者（`ModelRouter.cpp:231-249`） | 明确的主备偏好 |
| Capability | 首选模型有能力就用它，否则退化为 Priority（`ModelRouter.cpp:251-265`） | 文本/视觉分工 |
| RoundRobin | 在合格模型间轮转下标（`ModelRouter.cpp:267-277`） | 均摊配额 |
| LoadBalance | 选 `currentLoad` 最小者（`ModelRouter.cpp:279-302`） | 多个对等端点分流 |
| Fallback | 按 priority 降序、failureCount 升序排列，**逐个真试到成功为止**（`ModelRouter.cpp:64-115`） | 容灾（默认） |

关键区别：前四种只是"挑一个"发请求，失败即返回失败；只有 Fallback 会在失败后自动换下一个模型重发，并在成功后把该模型的 `failureCount` 清零（`ModelRouter.cpp:100-103`）。这就是它成为默认值的原因——单模型注册时 Fallback 退化为"直接调用唯一模型"，多模型注册时自动获得容灾。

### 3.3 线程模型

模型表和策略字段用一把 `mutex_` 保护；`currentLoad`/`failureCount` 是原子量，可以在锁外读写。`chat()` 的非 Fallback 分支把"选客户端"整个放在锁内（`ModelRouter.cpp:120-140`），而真正的 `client->chat(messages)` 在锁外执行（`ModelRouter.cpp:147`）——选路是瞬时临界区，网络 IO 不占锁，这是正确的设计。

## 4. 工作流程走读

以 WindowsLLMAnalysisService 初始化后的一次调用为例：

1. **注册**（服务初始化，`WindowsLLMAnalysisService.cpp:27-33`）：

```cpp
auto config = configManager.getTextModelConfig();          // .env 的 LLM_TEXT_* / LLM_*
router_ = std::make_shared<llm::ModelRouter>();
router_->addModel("default", config, llm::ModelInfo{
    "default", "text",
    {llm::ModelCapability::TextGeneration, llm::ModelCapability::Analysis}});
```

   `addModel()`（`ModelRouter.cpp:12-29`）立刻为该模型创建 LLMClient。ModelInfo 的 capabilities 是**调用方声明**的，不是探测来的（LLMClient.listModels 给出的能力标签是占位假值，见 LLMClient.md 第 6 节）。
2. **调用**：`router_->chat(prompt, systemPrompt)` 便捷重载组装 system+user 两条消息后进入主 `chat()`（`ModelRouter.cpp:50-148`），默认要求 `ModelCapability::TextGeneration`。
3. **Fallback 主路径**：`getAvailableModels(cap)` 先按 `info.available && hasCapability(cap)` 过滤（`ModelRouter.cpp:334-342`），再排序——priority 高的在前，同 priority 时失败次数少的在前（`ModelRouter.cpp:71-77`）。随后逐个尝试：

```cpp
for (auto* entry : available) {
    entry->currentLoad++;                     // 锁内更新负载
    response = entry->client->chat(messages); // 锁外真正调 LLM
    entry->currentLoad--;
    if (response.success) { entry->failureCount = 0; return response; }
    entry->failureCount++;                    // 记账，继续下一个模型
}
response.errorMessage = "All models failed. Last error: " + response.errorMessage;
```

4. **返回后**：调用方可用 `getLastUsedModel()`（`ModelRouter.cpp:205-208`）知道这次实际用了哪个模型（FileAnalyzer 把它写进 `AnalysisResult.modelUsed`）。
5. **运维操作**：`refreshAvailability()`（`ModelRouter.cpp:188-196`）逐个 `testConnection()` 刷新 `info.available` 标志并复位成功者的失败计数；`getConfig()`（`ModelRouter.cpp:210-229`）返回首选模型的 LLMConfig——FileAnalyzer 靠它读上下文窗口预算（无模型时返回静态默认配置，保证引用永远有效）。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| LLMClient | 每个模型条目独占一个实例；router 不自己发 HTTP |
| ConfigManager | 模型配置来源：`LLM_TEXT_*`（`getTextModelConfig`）与 `LLM_VISION_*`（`getVisionModelConfig`，当前无生产调用方） |
| FileAnalyzer | 构造函数注入 `shared_ptr<ModelRouter>`，所有分析请求走 `router_->chat()`；同时用 `router_->getConfig()` 拿上下文预算、`getLastUsedModel()` 记账 |
| MCPIntegration | 同样注入 router；MCP 工具 `analyze_file`/`generate_description` 的 LLM 部分经 router 完成 |
| 六个业务服务 | 每服务一个 router 实例、一个模型——router 之间互不共享（无全局单例） |

## 6. 注意事项与已知问题

- **`selectByFallback()` 是半成品死代码**（`ModelRouter.cpp:304-324`）：函数内注释自述"真正的回退循环在 chat() 里"；它对排序列表做了一次"返回第一个"的循环，且没有被任何分支调用（switch 的 default 走 `selectByPriority`）。读代码时不要被它误导。
- **LoadBalance 的负载只增不减**：`selectByLoadBalance()` 选中时 `currentLoad++`（`ModelRouter.cpp:297`），但非 Fallback 路径在请求结束后没有对应的 `--`（Fallback 路径有，`ModelRouter.cpp:96-98`）。长时间运行后所有模型的 load 单调上升，LoadBalance 逐渐失效。启用该策略前必须先修。
- **`info.available` 初始恒为 true 且无人刷新**：生产服务从不调 `refreshAvailability()`，"可用性"过滤实际形同虚设；Fallback 的容灾靠的是"真试失败再换"，而不是 available 标志。
- **failureCount 无衰减**：Fallback 排序中失败多的模型靠后，但没有过期/衰减机制；一次网络抖动造成的失败会一直压低该模型，直到它下一次成功才清零。
- **chat() 读取 `strategy_` 未加锁**（`ModelRouter.cpp:64`）：与 `setStrategy()` 并发时理论上存在数据竞争；实践中策略在初始化期设定后不变，风险低但值得知道。
- **视觉模型未接线**：`VisionAnalyzer`（`src/analyzers/VisionAnalysis/`）接收 router 构造，但目前没有任何服务构造它；要启用视觉分析需注册带 `ModelCapability::Vision` 的模型并确认端点支持 image_url 消息。

## 7. 如何验证与扩展

**验证**：
1. 修改任一 LLM 服务的初始化代码，用 `addModel()` 注册两个模型（priority 一高一低，指向不同端口），不设策略（默认 Fallback），停掉高优先级端点后发起分析——请求应落到备用模型，`getLastUsedModel()` 返回备模型名。
2. 单元测试思路：注册两个 mock 端点（返回固定 JSON），断言 Fallback 的尝试顺序符合 priority 降序、failureCount 升序；断言 RoundRobin 下标循环取模。
3. `getModelNames()` / `getModelInfo()` 可直接断言注册表状态。

**扩展方向**：
- 注册视觉模型：在某个服务里 `addModel("vision", configManager.getVisionModelConfig(), {Vision, ImageAnalysis})`，并以 `chat(messages, ModelCapability::Vision)` 调用——配合 LLMClient 的多模态消息即可打通图片研判。
- 修复 LoadBalance 计数：把"请求结束减载"从 Fallback 分支提炼到公共路径。
- 全局共享：若多个服务需要共用同一组模型与失败统计，可把 router 提为进程级单例；当前每服务独立意味着失败统计互不可见。

**最后更新**: 2026-08-23（解释式重写）
