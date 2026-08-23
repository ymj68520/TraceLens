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

## 4. 工作流程走读

启动时的加载序列（`ConfigManager.cpp:17-44`）：

1. 组装候选路径列表：显式传入的 `envPath`、`<exeDir>/.env`、`<projectRoot>/.env`（仅当 PathManager 已初始化，`:26-31`）、然后 `../`、`../../`、`../../../` 三个上级目录（`:18-23`）。顺序就是优先级：显式指定 > 可执行文件旁边 > 项目根 > 各级父目录。
2. 逐个检查存在性，第一个存在的文件调用 `dotenv::env.load_dotenv(path, false, true)`（`:33-40`），成功即置 `loaded_ = true` 返回。**先找到的文件全胜**，不做多文件合并。
3. 找不到任何文件时 `load()` 返回 false——进程不死，所有 getter 回退默认值，`main.cpp` 也不检查返回值，所以"忘写 .env"表现为"用默认配置跑"，通常体现为 LLM 打向默认地址失败。

运行期的典型读取，以 DatabaseManager 初始化为例（`DatabaseManager.cpp:28-36`）：`getDBBusyTimeoutMs()` → `getInt("DB_BUSY_TIMEOUT_MS", 5000)` → `dotenv::env["DB_BUSY_TIMEOUT_MS"]` 命中返回，未命中返回 5000。

## 5. 与其他模块的协作

- **PathManager**：load 时消费 exeDir/projectRoot（`ConfigManager.cpp:26-31`）；main.cpp 随后反向把 PROJECT_ROOT/DATA_DIR 写回 PathManager（`main.cpp:60-65`）。两个单例在启动期互相喂，之后互不相扰。
- **DatabaseManager**：三个 DB PRAGMA 配置的消费点（`DatabaseManager.cpp:29-36`）。`DB_JOURNAL_MODE=WAL` 是全系统写库不卡磁盘的关键（详见 DatabaseManager.md 第 6 节）。
- **ThreadPool/TaskManager 与 LLMIntegration**：共享 `THREAD_POOL_SIZE`——调大它同时增加任务并发与 LLM 并发，联动效应见 ThreadPool.md 第 5 节。
- **FileClassifier**：`EXTRA_*_EXTS` 在分类器初始化扩展映射时合并进基础映射（调用方 `FileClassifier.cpp:26-29` 的 initialize 系列）。
- **AuditLog**：main.cpp 手工搬运三个键（`main.cpp:70-72`），因为 AuditLogConfig 是构造期一次性参数而非运行期查询——两种配置消费模式的对照。
- 出错时行为：所有 getter 不抛异常（转换有 try/catch），`load` 吞掉文件解析异常（`:35-39`）；配置错误的最终表现是"走了默认值"，需要靠日志或行为异常反推。

## 6. 注意事项与已知问题

- **无运行期更新**：改 `.env` 必须重启进程；也没有 `set()` 接口，测试想覆盖配置只能写临时 `.env`（`tests/UnitTest/test_config_manager.cpp` 即如此）。
- **默认值硬编码在 getter 里**而非集中表，想知道"某键不填会是什么"只能读对应 getter 源码（本文引用的行号即权威位置）。改默认值时注意同步 `.env.example`/部署文档。
- `getBool` 不认识的值（如 `"enable"`）静默回退默认，容易掩盖拼写错误。
- `LOG_LEVEL`/`LOG_FILE`/`DEBUG_OUTPUT_MODE` 三个 getter（`ConfigManager.cpp:181-183`）当前无消费者（Logger 未接线，见 Logger.md 第 2 节）——改它们不会影响任何行为。
- Python 服务读取同名 `.env` 但解析逻辑独立（python-dotenv），新增键时两侧默认值需人工保持一致。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_config_manager.cpp`（注册于 `tests/CMakeLists.txt:764`，测试名 `ConfigManagerTests`）。
- 手工验证默认值链：临时移走 `.env` 后启动服务，观察日志中 LLM 地址是否变为 `http://192.168.31.170:1234`（`ConfigManager.cpp:86` 的默认值）。
- 扩展新配置项的步骤：(1) 在头文件加 getter 声明（按 LLM/系统/DB 等分区放置）；(2) 在 `ConfigManager.cpp` 对应分区实现，带默认值；(3) `.env.example` 补文档；(4) 调用方 import 单例直接用。若键名可由类别推导（如 `EXTRA_<X>_EXTS` 模式），优先复用第 3 节的约定式读取。

**最后更新**: 2026-08-23（解释式重写）
