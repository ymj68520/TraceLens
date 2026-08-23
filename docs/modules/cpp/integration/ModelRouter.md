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

每个注册模型对应一个 `ModelEntry`（`ModelRouter.h:108-115`），连同路由策略与轮询游标构成 router 的全部私有状态：

```cpp
// ModelRouter.h:107-133（节选）
struct ModelEntry {
    std::string name;
    LLMConfig config;
    ModelInfo info;
    std::unique_ptr<LLMClient> client;
    std::atomic<int> currentLoad{0};    // 正在进行的请求数，LoadBalance 用
    std::atomic<int> failureCount{0};   // 失败次数，Fallback 排序用
};

std::map<std::string, std::unique_ptr<ModelEntry>> models_;
RoutingStrategy strategy_ = RoutingStrategy::Fallback;   // 默认策略
std::string preferredModel_;      // 第一个注册的模型自动成为首选
std::string lastUsedModel_;       // getLastUsedModel() 的数据源
size_t roundRobinIndex_ = 0;      // RoundRobin 游标
mutable std::mutex mutex_;
```

逐字段看：`name` 是唯一键（`std::map` 保证）；`config/info` 是注册时的快照，之后不随 LLMClient 内部状态变化；`client` 独占持有——一个模型一个 HTTP 客户端，其重试锁（见 LLMClient.md 第 6 节）决定了该模型的吞吐上限；两个**原子**计数刻意放在锁外可读写，`chat()` 的网络 IO 段落不持 `mutex_` 也能安全更新。策略枚举定义在 `LLMDataTypes.h:180-186`：

```cpp
// LLMDataTypes.h:180-186
enum class RoutingStrategy {
    RoundRobin,     // Distribute evenly
    Priority,       // Use highest priority available
    Capability,     // Match by capability
    LoadBalance,    // Balance by current load
    Fallback        // Try in order until success
};
```

第一个注册的模型自动成为首选（`ModelRouter.cpp:26-28`）；`removeModel` 删掉首选时会改选 `models_.begin()->first`（按字典序，而非下一个注册者）。

### 3.2 五种路由策略

策略枚举默认 `Fallback`（`ModelRouter.h:118`）：

| 策略 | 选择逻辑 | 适用场景 |
|---|---|---|
| Priority | 可用且具备所需能力的模型中 priority 最高者（`ModelRouter.cpp:231-249`） | 明确的主备偏好 |
| Capability | 首选模型有能力就用它，否则退化为 Priority（`ModelRouter.cpp:251-265`） | 文本/视觉分工 |
| RoundRobin | 在合格模型间轮转下标（`ModelRouter.cpp:267-277`） | 均摊配额 |
| LoadBalance | 选 `currentLoad` 最小者（`ModelRouter.cpp:279-302`） | 多个对等端点分流 |
| Fallback | 按 priority 降序、failureCount 升序排列，**逐个真试到成功为止**（`ModelRouter.cpp:64-115`） | 容灾（默认） |

关键区别：前四种只是"挑一个"发请求，失败即返回失败；只有 Fallback 会在失败后自动换下一个模型重发，并在成功后把该模型的 `failureCount` 清零（`ModelRouter.cpp:100-103`）。这就是它成为默认值的原因——单模型注册时 Fallback 退化为"直接调用唯一模型"，多模型注册时自动获得容灾。

看两个代表性选择器的实现。Priority（`ModelRouter.cpp:231-249`）：

```cpp
LLMClient* ModelRouter::selectByPriority(ModelCapability cap) {
    ModelEntry* best = nullptr;
    int highestPriority = std::numeric_limits<int>::min();

    for (auto& [_, entry] : models_) {
        if (entry->info.available &&            // 可用性过滤：依赖 available 标志
            entry->info.hasCapability(cap) &&   // 能力过滤：调用方声明的 capabilities
            entry->info.priority > highestPriority) {
            highestPriority = entry->info.priority;
            best = entry.get();
        }
    }

    if (best) {
        lastUsedModel_ = best->name;            // 顺手记账
        return best->client.get();
    }
    return nullptr;                             // 无合格模型 → chat() 报 "No suitable model available"
}
```

LoadBalance（`ModelRouter.cpp:279-302` 节选）：

```cpp
    ModelEntry* best = nullptr;
    int lowestLoad = std::numeric_limits<int>::max();

    for (auto* entry : available) {
        int load = entry->currentLoad.load();
        if (load < lowestLoad) {
            lowestLoad = load;
            best = entry;
        }
    }

    if (best) {
        best->currentLoad++;      // ← 选中即 +1，但非 Fallback 路径请求结束后无人 -1（见第 6 节）
        lastUsedModel_ = best->name;
        return best->client.get();
    }
    return nullptr;
```

注意 LoadBalance 在**选择器里**就 `currentLoad++`（调用方拿不到 entry 指针，无法在请求结束后归还），这个不对称是第 6 节"计数只增不减"问题的根源。

### 3.3 线程模型

模型表和策略字段用一把 `mutex_` 保护；`currentLoad`/`failureCount` 是原子量，可以在锁外读写。`chat()` 的非 Fallback 分支把"选客户端"整个放在锁内（`ModelRouter.cpp:120-140`），而真正的 `client->chat(messages)` 在锁外执行（`ModelRouter.cpp:147`）——选路是瞬时临界区，网络 IO 不占锁，这是正确的设计。唯一的例外是 Fallback 路径的 `failureCount`/`currentLoad` 更新：它们以短临界区包裹（`:87-98`），网络调用仍在锁外。

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

   `addModel()`（`ModelRouter.cpp:12-29`）立刻为该模型创建 LLMClient：

```cpp
// ModelRouter.cpp:12-29（节选）
void ModelRouter::addModel(const std::string& name,
                           const LLMConfig& config,
                           const ModelInfo& info) {
    std::lock_guard<std::mutex> lock(mutex_);

    auto entry = std::make_unique<ModelEntry>();
    entry->name = name;
    entry->config = config;
    entry->info = info;
    entry->client = std::make_unique<LLMClient>(config);   // 立即建连配置（不真正连网）

    models_[name] = std::move(entry);                      // 同名重复注册 = 覆盖旧条目

    // Set as preferred if first model
    if (preferredModel_.empty()) {
        preferredModel_ = name;
    }
}
```

   ModelInfo 的 capabilities 是**调用方声明**的，不是探测来的（LLMClient.listModels 给出的能力标签是占位假值，见 LLMClient.md 第 6 节）。
2. **调用**：`router_->chat(prompt, systemPrompt)` 便捷重载组装 system+user 两条消息后进入主 `chat()`（`ModelRouter.cpp:50-148`），默认要求 `ModelCapability::TextGeneration`。
3. **Fallback 主路径**：`getAvailableModels(cap)` 先按 `info.available && hasCapability(cap)` 过滤（`ModelRouter.cpp:334-342`），再排序——priority 高的在前，同 priority 时失败次数少的在前（`ModelRouter.cpp:71-77`）。随后逐个尝试（完整主干）：

```cpp
// ModelRouter.cpp:64-115（节选）
if (strategy_ == RoutingStrategy::Fallback) {
    std::vector<ModelEntry*> available;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        available = getAvailableModels(requiredCapability);
        // Sort by priority (highest first) then by failure count (lowest first)
        std::sort(available.begin(), available.end(),
            [](const ModelEntry* a, const ModelEntry* b) {
                if (a->info.priority != b->info.priority)
                    return a->info.priority > b->info.priority;
                return a->failureCount.load() < b->failureCount.load();
            });
    }   // 排序在锁内完成，下面的尝试循环不持表锁

    if (available.empty()) {
        response.errorMessage = "No suitable model available";
        return response;
    }

    for (auto* entry : available) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            lastUsedModel_ = entry->name;
            entry->currentLoad++;
        }

        response = entry->client->chat(messages);   // 锁外真正调 LLM（含 client 自身的重试）

        {
            std::lock_guard<std::mutex> lock(mutex_);
            entry->currentLoad--;
        }

        if (response.success) {
            std::lock_guard<std::mutex> lock(mutex_);
            entry->failureCount = 0;  // Reset failure count on success
            return response;
        }

        entry->failureCount++;        // 原子量，锁外自增；继续下一个模型
    }

    // All models failed
    response.errorMessage = "All models failed. Last error: " + response.errorMessage;
    return response;
}
```

   四个值得咀嚼的细节：① 排序快照在锁内做一次，尝试循环期间表可能被并发修改（新注册的模型本轮不会参与）；② 每个模型的尝试都完整继承 LLMClient 内部的 4 次重试——N 个模型全挂的最坏等待是 N×4 次 HTTP 尝试的退避总和；③ 失败信息只保留**最后一个**模型的错误（"Last error"），中间模型的失败原因只存在于各自 LLMClient 的 lastError 里；④ 成功清零 failureCount 意味着"间歇性故障模型"会被反复放回队首。
4. **返回后**：调用方可用 `getLastUsedModel()`（`ModelRouter.cpp:205-208`）知道这次实际用了哪个模型（FileAnalyzer 把它写进 `AnalysisResult.modelUsed`）。
5. **运维操作**：`refreshAvailability()`（`ModelRouter.cpp:188-196`）逐个 `testConnection()` 刷新 `info.available` 标志并复位成功者的失败计数；`getConfig()`（`ModelRouter.cpp:210-229`）返回首选模型的 LLMConfig——FileAnalyzer 靠它读上下文窗口预算（无模型时返回静态默认配置，保证引用永远有效）。

### 公开接口清单（ModelRouter.h:37-105）

| 方法（真实签名节选） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `void addModel(name, config, info)` | 注册模型并立刻创建 LLMClient；首个注册者成为 preferred | 六个服务初始化 | — |
| `void removeModel(name)` / `setStrategy(RoutingStrategy)` / `setPreferredModel(name)` | 删条目（删首选则改选字典序第一）/ 改策略 / 改首选 | 无生产调用方（默认 Fallback） | 未知名静默忽略 |
| `LLMResponse chat(const std::vector<ChatMessage>&, ModelCapability = TextGeneration)` | 主入口，按策略选路执行 | 各服务、FileAnalyzer、MCPIntegration | 无模型 → "No models registered"；选不到 → "No suitable model available"；Fallback 全败 → "All models failed. Last error: ..." |
| `LLMResponse chat(prompt, systemPrompt = "")` | 便捷重载（强制 TextGeneration） | 绝大多数调用点 | 同上 |
| `getModelNames()` / `getModelInfo(name)` / `hasAvailableModels()` | 注册表与可用性查询 | 测试 | 未知名返回空 ModelInfo |
| `void refreshAvailability()` | 逐个 testConnection 刷新 available | 无生产调用方（见第 6 节） | — |
| `std::string getLastUsedModel() const` | 上次实际使用的模型名 | FileAnalyzer 记账 | — |
| `const LLMConfig& getConfig() const` | 首选模型的配置（无模型返回静态默认） | FileAnalyzer 算上下文预算 | 引用永远有效 |

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| LLMClient | 每个模型条目独占一个实例；router 不自己发 HTTP |
| ConfigManager | 模型配置来源：`LLM_TEXT_*`（`getTextModelConfig`）与 `LLM_VISION_*`（`getVisionModelConfig`，当前无生产调用方） |
| FileAnalyzer | 构造函数注入 `shared_ptr<ModelRouter>`，所有分析请求走 `router_->chat()`；同时用 `router_->getConfig()` 拿上下文预算、`getLastUsedModel()` 记账 |
| MCPIntegration | 同样注入 router；MCP 工具 `analyze_file`/`generate_description` 的 LLM 部分经 router 完成 |
| 六个业务服务 | 每服务一个 router 实例、一个模型——router 之间互不共享（无全局单例） |

## 6. 注意事项与已知问题

- **`selectByFallback()` 是半成品死代码**（`ModelRouter.cpp:304-324`）：函数内注释自述"真正的回退循环在 chat() 里"；它对排序列表做了一次"返回第一个"的循环（`for` 体内首轮即 `return`，循环形同虚设），且没有被任何分支调用（switch 的 default 走 `selectByPriority`）。读代码时不要被它误导。
- **LoadBalance 的负载只增不减**：`selectByLoadBalance()` 选中时 `currentLoad++`（`ModelRouter.cpp:297`），但非 Fallback 路径在请求结束后没有对应的 `--`（Fallback 路径有，`ModelRouter.cpp:96-98`）。长时间运行后所有模型的 load 单调上升，LoadBalance 逐渐失效。启用该策略前必须先修。
- **`info.available` 初始恒为 true 且无人刷新**：生产服务从不调 `refreshAvailability()`，"可用性"过滤实际形同虚设；Fallback 的容灾靠的是"真试失败再换"，而不是 available 标志。
- **failureCount 无衰减**：Fallback 排序中失败多的模型靠后，但没有过期/衰减机制；一次网络抖动造成的失败会一直压低该模型，直到它下一次成功才清零。
- **chat() 读取 `strategy_` 未加锁**（`ModelRouter.cpp:64`）：与 `setStrategy()` 并发时理论上存在数据竞争；实践中策略在初始化期设定后不变，风险低但值得知道。
- **视觉模型未接线**：`VisionAnalyzer`（`src/analyzers/VisionAnalysis/`）接收 router 构造，但目前没有任何服务构造它；要启用视觉分析需注册带 `ModelCapability::Vision` 的模型并确认端点支持 image_url 消息。
- **多模型全败时错误只留最后一条**（`ModelRouter.cpp:113`）：排障时中间模型的失败原因需要看各自客户端/服务端日志。

## 7. 如何验证与扩展

**验证**：
1. 修改任一 LLM 服务的初始化代码，用 `addModel()` 注册两个模型（priority 一高一低，指向不同端口），不设策略（默认 Fallback），停掉高优先级端点后发起分析——请求应落到备用模型，`getLastUsedModel()` 返回备模型名。
2. 单元测试思路：注册两个 mock 端点（返回固定 JSON），断言 Fallback 的尝试顺序符合 priority 降序、failureCount 升序；断言 RoundRobin 下标循环取模；断言 LoadBalance 首选 load=0 的模型。
3. `getModelNames()` / `getModelInfo()` 可直接断言注册表状态。

**扩展方向**：
- 注册视觉模型：在某个服务里 `addModel("vision", configManager.getVisionModelConfig(), {Vision, ImageAnalysis})`，并以 `chat(messages, ModelCapability::Vision)` 调用——配合 LLMClient 的多模态消息即可打通图片研判。
- 修复 LoadBalance 计数：把"请求结束减载"从 Fallback 分支提炼到公共路径（让 chat() 在拿到 client 指针的同时拿到 entry 指针，finally 语义减载）。
- 全局共享：若多个服务需要共用同一组模型与失败统计，可把 router 提为进程级单例；当前每服务独立意味着失败统计互不可见。

## 8. 策略 × 状态交互矩阵（二轮补全）

五种策略对 ModelEntry 状态的读写差异全表（"选择器"指 §3.2 的四个 selectBy* + chat 内联的 Fallback 循环）：

| 策略 | 读 available | 读 failureCount | 写 currentLoad | 写 lastUsedModel_ | 失败后换模型 |
|---|---|---|---|---|---|
| Fallback（默认） | 是（过滤） | 是（排序） | +1/-1 配对（:88-98） | 每次尝试前（:89） | **是**（循环到成功） |
| Priority | 是 | 否 | 否 | 选中时（:245） | 否 |
| Capability | 是（首选+回退两次查） | 否 | 否 | 选中时 | 否 |
| RoundRobin | 是 | 否 | 否 | 选中时（:275） | 否 |
| LoadBalance | 是 | 否 | **只 +1**（:297，§6 已记不减） | 选中时 | 否 |

推论：只有 Fallback 让 failureCount 有意义（其它策略不读它，失败计数白攒）；只有 Fallback/LoadBalance 碰 currentLoad。混用策略时状态语义不一致是潜在坑。

**RoundRobin 的 off-by-one（新发现）**：`roundRobinIndex_ = (roundRobinIndex_ + 1) % available.size()`（:273）——初始 0，首次调用直接跳到 1，**索引 0 的模型在第一轮永远排不到**；且 available.size() 变化时（注册/移除模型）游标语义漂移（模数变化）。单模型下 `(0+1)%1=0` 恰好无害——又一个"单模型现状掩盖了多模型 bug"的实例，与 LoadBalance 计数不减同族。

## 9. 新走读分支：三个入口的失败形态（二轮）

chat() 的三种"结构性失败"（非网络失败）各有独立响应形态，调用方判错时要分开处理：

1. **空注册表**（:54-61）：锁内查 `models_.empty()` → `errorMessage = "No models registered"`、success=false。服务初始化时 addModel 抛异常（如 ConfigManager 返回非法配置导致 LLMClient 构造失败）就会进入这条路径——表现为所有 LLM 调用秒失败。
2. **无合格模型**（:80-83 Fallback / :142-145 其他策略）：available 过滤后为空（能力不匹配或 available=false）→ "No suitable model available"。注意 available 初始恒 true 且无人刷新（§6），实际触发主要靠能力过滤——要求 Vision 却只注册了 TextGeneration 时。
3. **全模型失败**（:112-114）：循环走完 → "All models failed. Last error: <最后一个模型的错误>"。中间模型的错误被丢弃。

三者都是 `success=false` 的 LLMResponse——上层服务（如 Linux 系列的"逐条作废"循环）只看 success，不区分形态；排障时靠 errorMessage 前缀区分："No models registered"（初始化问题）/"No suitable"（能力声明问题）/"All models failed"（端点问题）。

## 10. 配置影响表（ModelRouter 视角）

| 配置 | 默认 | 消费链 | 说明 |
|---|---|---|---|
| `LLM_TEXT_BASE_URL` / `LLM_TEXT_MODEL` | 回落 LLM_BASE_URL / gpt-oss | ConfigManager.cpp:100-101 → getTextModelConfig → addModel | 六个服务共用同一工厂——所有 router 的"default"模型同配置 |
| `LLM_TEXT_MAX_TOKENS` / `LLM_TEXT_TEMPERATURE` | 2048 / 0.7 | 同上 | C++ 侧默认（Python 侧 4096——Environment.md 已记漂移） |
| `LLM_VISION_*` 五项 | 见 Environment.md | getVisionModelConfig | **已就绪零调用**——接视觉模型时的现成入口 |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | 120 / 3 | LLMConfig → LLMClient | N 模型 Fallback 最坏 N×4 次尝试 |
| `LLM_CONTEXT_LENGTH` | 4096（.env.example 写 163840） | LLMConfig.contextLength → FileAnalyzer 预算 | router 的 getConfig() 转发（§4 第 5 步） |
| （路由策略无 env） | Fallback 硬编码 | strategy_ 默认值 | 换策略只能改代码调 setStrategy |

## 11. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 |
|---|---|---|
| 被 constructs | 六个服务的 initialize | 各自 make_shared + addModel("default"/"dll_analyzer") |
| 被注入 | FileAnalyzer / MCPIntegration 构造参数 | 只调 chat/getConfig/getLastUsedModel |
| 持有 | N × LLMClient（unique_ptr） | addModel 即建 |
| 读 | ConfigManager 两个工厂 | 文本/视觉配置 |
| 死位 | removeModel/setStrategy/setPreferredModel/refreshAvailability/hasAvailableModels/getModelNames/getModelInfo/getClient（私有，:131，无调用方）/selectByFallback | 零生产调用方 |
| 不共享 | 各服务独立实例 | 失败统计互不可见（§7 扩展方向已记） |

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
