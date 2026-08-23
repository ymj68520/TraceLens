# ConfigManager（src/core/ConfigManager/）

> **一句话**：进程级单例的配置读取层，用 cpp-dotenv 加载 `.env` 文件，为 LLM、线程池、数据库 PRAGMA、全文检索等所有子系统提供带类型和默认值的 getter——C++ 服务与 Python 服务通过同一个 `.env` 共享配置。

## 1. 为什么有这个模块

TraceLens 是三服务协作的系统（C++ forensic_analyzer :8080、Python httpserver :8090、分布式 server :8091），加上前端。如果每个服务各持一份配置，LLM 地址、端口、超时这些值很快会失去同步：改了 C++ 侧的 LLM 端点，Python 侧还在打旧地址。项目选择 `.env` 作为唯一配置源，Python 侧用 python-dotenv 读，C++ 侧就是本模块（基于 `libs/cpp-dotenv`，`ConfigManager.cpp:2` 的 `#include "dotenv.h"`）。

第二个动机是**默认值兜底**。取证工具常被部署在离线环境，一个缺失的配置项不应该让进程起不来。ConfigManager 的每个 getter 都带编译期默认值（如 `THREAD_POOL_SIZE` 缺省 4、`HTTP_SERVER_PORT` 缺省 8080），`.env` 只覆盖需要改的项。这让"克隆仓库→build→直接跑"成为可能。

最后，它还承担**配置寻址**：从哪个目录找 `.env`？程序可能从仓库根、build/ 或安装目录启动，模块按优先级搜索多个候选位置（见第 4 节），其中借助 PathManager 的 exeDir/projectRoot，与 PathManager.md 第 5 节描述的启动时序呼应。

## 2. 在系统中的位置

ConfigManager 位于基础设施层，依赖只有 cpp-dotenv 和 PathManager（仅用于找配置文件）。上游是唯一的：`main.cpp:56` 在进程启动时调用一次 `load(".env")`。下游几乎是所有子系统：

- **TaskManager/ThreadPool**：`THREAD_POOL_SIZE`（`ConfigManager.cpp:138`）；
- **DatabaseManager**：`DB_BUSY_TIMEOUT_MS`/`DB_JOURNAL_MODE`/`DB_SYNCHRONOUS_OFF`（`ConfigManager.cpp:146-148`，在 `DatabaseManager.cpp:28-36` 被消费）；
- **LLM 栈**：base url、文本/视觉模型名、超时重试（`ConfigManager.cpp:86-135`），组装成 `llm::LLMConfig` 交给 LLMIntegration；
- **FullTextSearch**：缓存大小、内容截断、snippet 长度（`ConfigManager.cpp:151-154`）；
- **FileClassifier**：`EXTRA_<类别>_EXTS` 动态扩展名（`ConfigManager.cpp:159-173`）；
- **AuditLog**：`AUDIT_LOG_DB` 等（在 `main.cpp:69-74` 由调用方读取后组装 AuditLogConfig）。

它不调用任何业务模块；HTTP 服务端口 `HTTP_SERVER_PORT`（默认 8080）也是从这里读的（`ConfigManager.cpp:140`）。

## 3. 核心概念与设计

**"全局 env + 即时读"而非"快照对象"**。`load()` 把键值灌进 cpp-dotenv 的全局 `dotenv::env`，此后每个 getter 每次都实时查这个 map（`ConfigManager.cpp:50-53`）。没有 `reload()`、没有 `set()`，配置在进程生命周期内不可变——这简化了并发（无锁读全局 map）也符合"改配置重启服务"的运维习惯。代价是单测无法注入配置，只能靠准备临时 `.env` 文件。

**四层类型转换**，全部带失败回退到默认值（`ConfigManager.cpp:50-83`）：

- `get(key, default)`：空串视为未设置返回默认；
- `getInt`：`std::stoi` 异常（如 `"4abc"`）回退默认；
- `getDouble` 同理；
- `getBool`：接受 `true/1/yes/on` 与 `false/0/no/off`（大小写不敏感），其余回退默认——比裸字符串比较宽容，因为 `.env` 生态里这几种写法都常见。

**LLM 配置的继承结构**。视觉/文本模型可以各自指定 base url，不指定则继承通用 `LLM_BASE_URL`（`ConfigManager.cpp:100, 119`）：

```cpp
std::string ConfigManager::getTextBaseUrl() const { return get("LLM_TEXT_BASE_URL", getLLMBaseUrl()); }
std::string ConfigManager::getVisionBaseUrl() const { return get("LLM_VISION_BASE_URL", getLLMBaseUrl()); }
```

这两行实现了"一套部署只填一个 LLM_BASE_URL 就够；混布两个模型服务时再分别覆盖"。`getTextModelConfig()`/`getVisionModelConfig()` 把散装项组装成 `llm::LLMConfig` 结构（`ConfigManager.cpp:105-135`），调用方一次拿到完整配置，模型默认名 `gpt-oss`（文本）/`qwen3-vl`（视觉）也在这里。

**约定式键名**。`getExtraExtensions("IMAGE")` 拼出 `EXTRA_IMAGE_EXTS` 并按逗号切分、去空白（`ConfigManager.cpp:159-173`）——新增一个类别的扩展名支持不需要写任何解析代码。

### 3.1 核心数据结构

模块自身几乎无状态——唯一成员是 `bool loaded_`（`ConfigManager.h:126`），真实状态存在 cpp-dotenv 的全局 `dotenv::env`（字符串 map）。两个值得认识的结构：

**产物结构 `llm::LLMConfig`**（`src/integration/LLMIntegration/LLMDataTypes.h:14-30`，getter 组装的目标类型）：

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

    // Context window management
    int contextLength = 4096;         // Total context window size in tokens
    int reservedTokens = 512;         // Reserved for system prompt + response
    double charsPerToken = 4.0;       // Estimated characters per token (Chinese ~1.5, English ~4)
    bool enableChunkedAnalysis = true; // Enable chunked analysis for large files
    int maxChunks = 5;                // Maximum chunks for analysis
};
```

注意 `getTextModelConfig()` 只填前 8 个字段（`ConfigManager.cpp:105-116`），上下文管理四项（contextLength/reservedTokens/charsPerToken/enableChunkedAnalysis）**不来自 .env 的这几组 getter**，保留结构体默认值；`getContextLength()`（`LLM_CONTEXT_LENGTH`，`:176`）是独立 getter，由 LLM 层另行消费。`charsPerToken=4.0` 的注释点明它是估算值，中文语料实际约 1.5——做分块预算时这是个已知偏差源。

**键空间一览**（`.env` 全量键与 C++ 侧默认值，行号为 getter 实现位置）：

| 分区 | 键 = 默认值 | 行 | 消费方 |
|---|---|---|---|
| LLM 通用 | `LLM_BASE_URL`="http://192.168.31.170:1234"、`LLM_ENDPOINT`="/v1/chat/completions"、`LLM_API_KEY`=""、`LLM_TIMEOUT_SECONDS`=120、`LLM_MAX_RETRIES`=3、`LLM_MAX_FILES`=500、`LLM_MAX_EVENT_CLUSTERS`=0(不限)、`LLM_MAX_CONTENT_LENGTH`=10000、`LLM_SKIP_BINARY`=true | :86-97 | LLMIntegration/分析路由 |
| 文本模型 | `LLM_TEXT_BASE_URL`(继承)、`LLM_TEXT_MODEL`="gpt-oss"、`LLM_TEXT_MAX_TOKENS`=2048、`LLM_TEXT_TEMPERATURE`=0.7 | :100-103 | getTextModelConfig |
| 视觉模型 | `LLM_VISION_BASE_URL`(继承)、`LLM_VISION_MODEL`="qwen3-vl"、`LLM_VISION_MAX_TOKENS`=4096、`LLM_VISION_TEMPERATURE`=0.5 | :119-122 | getVisionModelConfig |
| 系统性能 | `THREAD_POOL_SIZE`=4、`MAX_BATCH_SIZE`=100、`HTTP_SERVER_PORT`=8080、`HTTP_SERVER_HOST`="0.0.0.0"、`PYTHON_SERVICE_URL`="http://localhost:8090"(拼 `PYTHON_HTTP_PORT`)、`MCP_HOST`="0.0.0.0" | :138-143 | TaskManager/HTTP 服务/MarkitdownProxy |
| 数据库 | `DB_BUSY_TIMEOUT_MS`=5000、`DB_JOURNAL_MODE`="WAL"、`DB_SYNCHRONOUS_OFF`=false | :146-148 | DatabaseManager |
| 全文检索 | `SEARCH_MAX_CACHE_SIZE`=1000、`SEARCH_MAX_CONTENT_LENGTH`=50000、`SEARCH_SNIPPET_LENGTH`=150、`SEARCH_DEFAULT_LIMIT`=10 | :151-154 | FullTextSearch |
| 分析阈值 | `LOG_MAX_DISPLAY_FILES`=20、`FILE_ANALYSIS_MAX_CONTENT`=10000、`FILE_ANALYSIS_MAX_KEYWORDS`=10、`LLM_CONTEXT_LENGTH`=4096 | :157, 174-176 | 展示层/LLM 层 |
| 存储/日志 | `DB_OUTPUT_DIR`="./output"、`DB_NAME`="forensics.db"、`LOG_LEVEL`="INFO"、`LOG_FILE`="forensics.log"、`DEBUG_OUTPUT_MODE`="stdout" | :179-183 | 后三个无消费者 |
| 审计 | `AUDIT_LOG_DB`/`AUDIT_LOG_CACHE_SIZE`/`AUDIT_LOG_WAL` | main.cpp:70-72 | AuditLog（手工搬运） |
| 动态扩展名 | `EXTRA_<CATEGORY>_EXTS`="" | :159-173 | FileClassifier |

### 3.2 核心接口清单

| 签名（ConfigManager.h） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `static ConfigManager& instance()` | 取单例 | 全部消费者 | 不会失败 |
| `bool load(envPath=".env")` | 按优先级搜并加载第一个存在的 .env | main.cpp:56 | 找不到/解析异常返回 false，getter 继续用默认值 |
| `bool isLoaded() const` | 是否加载成功 | 诊断 | 恒可用 |
| `std::string get(key, default="") const` | 原始字符串读（空串视为未设） | 各 getter 内部 + 直接取原始键 | 未命中返回默认 |
| `int getInt(key, default=0)` / `double getDouble(...)` | 数值转换读 | 各数值 getter | `stoi/stod` 抛异常回退默认 |
| `bool getBool(key, default=false)` | 宽容布尔读（8 种写法） | 开关类 getter | 不认识的值回退默认 |
| `llm::LLMConfig getTextModelConfig() const` | 组装文本模型完整配置 | LLMIntegration | 不会失败（全默认值兜底） |
| `llm::LLMConfig getVisionModelConfig() const` | 组装视觉模型完整配置 | LLMIntegration | 同上 |
| `std::vector<std::string> getExtraExtensions(categoryName) const` | 读 `EXTRA_<X>_EXTS` 逗号分隔表 | FileClassifier | 空键返回空 vector |

## 4. 工作流程走读

启动时的加载序列（`ConfigManager.cpp:17-44`）：

1. 组装候选路径列表：显式传入的 `envPath`、`<exeDir>/.env`、`<projectRoot>/.env`（仅当 PathManager 已初始化，`:26-31`）、然后 `../`、`../../`、`../../../` 三个上级目录（`:18-23`）。顺序就是优先级：显式指定 > 可执行文件旁边 > 项目根 > 各级父目录。
2. 逐个检查存在性，第一个存在的文件调用 `dotenv::env.load_dotenv(path, false, true)`（`:33-40`），成功即置 `loaded_ = true` 返回。**先找到的文件全胜**，不做多文件合并。
3. 找不到任何文件时 `load()` 返回 false——进程不死，所有 getter 回退默认值，`main.cpp` 也不检查返回值，所以"忘写 .env"表现为"用默认配置跑"，通常体现为 LLM 打向默认地址失败。

运行期的典型读取，以 DatabaseManager 初始化为例（`DatabaseManager.cpp:28-36`）：`getDBBusyTimeoutMs()` → `getInt("DB_BUSY_TIMEOUT_MS", 5000)` → `dotenv::env["DB_BUSY_TIMEOUT_MS"]` 命中返回，未命中返回 5000。

### 4.1 代码走读：load() 的多路径搜索（ConfigManager.cpp:17-44）

```cpp
bool ConfigManager::load(const std::string& envPath) {
    std::vector<std::string> searchPaths = {
        envPath,
        "../" + envPath,
        "../../" + envPath,
        "../../../" + envPath
    };

    try {
        auto& pm = forensics::PathManager::instance();
        if (pm.isInitialized()) {
            searchPaths.insert(searchPaths.begin() + 1, (pm.getExeDir() / envPath).string());
            searchPaths.insert(searchPaths.begin() + 2, (pm.getProjectRoot() / envPath).string());
        }
    } catch (...) {}

    for (const auto& path : searchPaths) {
        if (!std::filesystem::exists(path)) continue;
        try {
            dotenv::env.load_dotenv(path, false, true);
            loaded_ = true;
            return true;
        } catch (...) {}
    }

    loaded_ = false;
    return false;
}
```

逐块解释：搜索表先放静态候选（CWD 与三级父目录），再用 `insert(begin()+1/+2)` 把 PathManager 推导的两个位置**楔进第 2、3 顺位**——静态表在前的顺序保证"显式传参永远第一"，PathManager 候选压过 `../` 系。两处 `catch (...)` 都是刻意的静默：PathManager 未初始化（首启时序问题）只是少了两个候选，不该让配置加载失败；单个文件解析异常则继续试下一个候选。`load_dotenv(path, false, true)` 的第二参 false = 不覆盖已有环境变量、第三参 true = 覆盖此前已加载的 dotenv 值——即重复调用 load 时后加载的文件胜出（但生产只调一次）。循环里"第一个存在的文件全胜"意味着 build/ 目录下若有残留 `.env`，会**静默压过仓库根**——这是部署时最常见的配置不生效原因。

### 4.2 代码走读：getBool 的宽容解析（ConfigManager.cpp:75-83）

```cpp
bool ConfigManager::getBool(const std::string& key, bool defaultValue) const {
    std::string value = get(key);
    if (value.empty()) return defaultValue;
    std::string lower_val = value;
    std::transform(lower_val.begin(), lower_val.end(), lower_val.begin(), ::tolower);
    if (lower_val == "true" || lower_val == "1" || lower_val == "yes" || lower_val == "on") return true;
    if (lower_val == "false" || lower_val == "0" || lower_val == "no" || lower_val == "off") return false;
    return defaultValue;
}
```

逐块解释：`.env` 生态没有布尔规范，`True`/`TRUE`/`yes`/`on`/`1` 都有人写，所以先统一小写再比对 8 个字面量。注意**未命中与拼错同路**：`"enable"`、`"Y"` 这类值走最后一行返回默认值，调用方无法区分"用户明确写了错值"和"没写"——这是把容错当特性卖的典型代价，排查时应直接 `dotenv::env["KEY"]` 看原始值。`::tolower` 是 C 函数，逐字符转换 ASCII；非 ASCII 字节传入是 UB 但对布尔字面量无实际影响。

### 4.3 代码走读：getExtraExtensions 的约定式解析（ConfigManager.cpp:159-173）

```cpp
std::vector<std::string> ConfigManager::getExtraExtensions(const std::string& categoryName) const {
    std::string key = "EXTRA_" + categoryName + "_EXTS";
    std::string value = get(key, "");
    std::vector<std::string> exts;
    if (value.empty()) return exts;
    
    std::istringstream iss(value);
    std::string ext;
    while (std::getline(iss, ext, ',')) {
        ext.erase(0, ext.find_first_not_of(" \t"));
        ext.erase(ext.find_last_not_of(" \t") + 1);
        if (!ext.empty()) exts.push_back(ext);
    }
    return exts;
}
```

逐块解释：键名由类别参数拼接（`"IMAGE"` → `EXTRA_IMAGE_EXTS`），新增类别零代码。`getline(iss, ext, ',')` 按逗号切分后，两行 erase 是手写 trim：`find_first_not_of(" \t")` 找到首个非空白位置裁掉前导，`find_last_not_of + 1` 裁掉尾随（全空白串会 erase 成空，再由 `!ext.empty()` 过滤）。返回的扩展名**不强制带点也不统一大小写**——`webp` 与 `.webp`、`JPG` 与 `jpg` 是否等价取决于消费方 FileClassifier 的映射合并逻辑（`FileClassifier.cpp:26-29` 一带），扩展这个约定时要连带检查下游是否归一化。

## 5. 与其他模块的协作

- **PathManager**：load 时消费 exeDir/projectRoot（`ConfigManager.cpp:26-31`）；main.cpp 随后反向把 PROJECT_ROOT/DATA_DIR 写回 PathManager（`main.cpp:60-65`）。两个单例在启动期互相喂，之后互不相扰。
- **DatabaseManager**：三个 DB PRAGMA 配置的消费点（`DatabaseManager.cpp:29-36`）。`DB_JOURNAL_MODE=WAL` 是全系统写库不卡磁盘的关键（详见 DatabaseManager.md 第 6 节）。
- **ThreadPool/TaskManager 与 LLMIntegration**：共享 `THREAD_POOL_SIZE`——调大它同时增加任务并发与 LLM 并发，联动效应见 ThreadPool.md 第 5 节。
- **FileClassifier**：`EXTRA_*_EXTS` 在分类器初始化扩展映射时合并进基础映射（调用方 `FileClassifier.cpp:26-29` 的 initialize 系列）。
- **AuditLog**：main.cpp 手工搬运三个键（`main.cpp:70-72`），因为 AuditLogConfig 是构造期一次性参数而非运行期查询——两种配置消费模式的对照。
- **Python 服务**：读同一个 `.env`（python-dotenv），`PYTHON_HTTP_PORT`（默认 8090）被 C++ 侧拼进 `PYTHON_SERVICE_URL` 默认值（`:142`）——跨服务寻址的粘合点。
- 出错时行为：所有 getter 不抛异常（转换有 try/catch），`load` 吞掉文件解析异常（`:35-39`）；配置错误的最终表现是"走了默认值"，需要靠日志或行为异常反推。

## 6. 注意事项与已知问题

- **无运行期更新**：改 `.env` 必须重启进程；也没有 `set()` 接口，测试想覆盖配置只能写临时 `.env`（`tests/UnitTest/test_config_manager.cpp` 即如此）。
- **默认值硬编码在 getter 里**而非集中表，想知道"某键不填会是什么"只能读对应 getter 源码（本文引用的行号即权威位置）。改默认值时注意同步 `.env.example`/部署文档。
- `getBool` 不认识的值（如 `"enable"`）静默回退默认，容易掩盖拼写错误。
- `LOG_LEVEL`/`LOG_FILE`/`DEBUG_OUTPUT_MODE` 三个 getter（`ConfigManager.cpp:181-183`）当前无消费者（Logger 未接线，见 Logger.md 第 2 节）——改它们不会影响任何行为。
- Python 服务读取同名 `.env` 但解析逻辑独立（python-dotenv），新增键时两侧默认值需人工保持一致。
- **搜索顺序陷阱**：build/ 下的 `.env` 优先于仓库根（第 4.1 节），配置"改了没生效"先查有没有第二个 .env。
- `getLLMMaxEventClusters()` 对非正值做了钳制（`return value > 0 ? value : 0`，`:92-95`），是少数带合法性约束的 getter；其余数值键（如负的线程数）原样透传给消费方。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_config_manager.cpp`（注册于 `tests/CMakeLists.txt:764`，测试名 `ConfigManagerTests`）。
- 手工验证默认值链：临时移走 `.env` 后启动服务，观察日志中 LLM 地址是否变为 `http://192.168.31.170:1234`（`ConfigManager.cpp:86` 的默认值）。
- 扩展新配置项的步骤：(1) 在头文件加 getter 声明（按 LLM/系统/DB 等分区放置）；(2) 在 `ConfigManager.cpp` 对应分区实现，带默认值；(3) `.env.example` 补文档；(4) 调用方 import 单例直接用。若键名可由类别推导（如 `EXTRA_<X>_EXTS` 模式），优先复用第 3 节的约定式读取。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
