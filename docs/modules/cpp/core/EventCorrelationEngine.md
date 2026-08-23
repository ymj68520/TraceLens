# EventCorrelationEngine（src/core/EventCorrelationEngine/）

> **一句话**：对 events.db 做两两关联分析的规则引擎——按时间窗、同源、同文件、上下文相似度、固定序列五种规则找出事件对，再把关联对组装成事件链、推导因果关系，结果写回 events.db 并可导出 JSON/dot。注意：它目前只被单元测试直接调用，生产流水线没有触发入口。

## 1. 为什么有这个模块

时间线解决"发生了什么"，但原始事件流是几十万条孤立记录。调查者真正要找的是**模式**："登录失败之后 60 秒内出现新文件"、"同一个 inode 先创建后修改再删除"、"下载之后立刻执行"。逐条人肉比对不现实，需要一个能把"事件对之间有关系"这个判断批量算出来的组件。

设计上选择了最可解释的路径：**显式规则 + 阈值**，而不是统计学习。每条规则声明自己的时间窗与置信度阈值，产出的每条关联都带 rule_id、confidence、strength/direction——调查者看到关联结果能直接反推"为什么这两件事被关联"，这在取证语境里比黑盒模型更重要。代价是规则集合固定、无法发现未预设的模式（第 6 节会讨论）。

三个分析层次递进：**关联**（两事件相关）→ **事件链**（把关联对连成图/链，还原一次活动的全貌）→ **因果**（在满足时间先后的关联上给"原因→结果"的标注）。置信度逐层打折（因果 = 关联 × 0.9，`Detail/EventChainBuilder.cpp:190`），体现"越往上推断越不确定"的原则。

## 2. 在系统中的位置

先澄清一个高频混淆——仓库里有**三个名字相近但完全不同的东西**：

1. **EventCorrelationEngine**（本模块，`src/core/EventCorrelationEngine/`）：独立引擎，读 events.db 的 events 表，产出 event_correlations/event_chains/causal_relationships 等表。
2. **EventCorrelationExtractor**（`src/core/DatabaseManager/EventExtractor/Detail/EventCorrelationExtractor.cpp`）：不是独立引擎，而是 EventExtractor 的一个成员函数文件；其 `EventExtractor::analyzeEventCorrelations()`（`:31-80`）构造本引擎的实例并驱动它——是"引擎的包装器 + 导出器"（额外导出 JSON 与 Graphviz dot 文件）。**但该函数目前无生产调用方**（全仓库检索只有定义），所以包装器与引擎一起处于"未接线"状态。
3. **LogCorrelationEngine**（`src/analyzers/LinuxFilesAnalyzer/Analysis/LogCorrelationEngine.h:21`）：LinuxFilesAnalyzer 内部的日志关联器，输入输出都在 Linux 分析库体系内，与本模块无代码关系。

另外，HTTP 流水线 LLM_ANALYSIS 阶段用的 **EventClusterAnalyzer**（`src/network/HTTPServer/EventClusterAnalyzer.cpp`）是第四种东西：按时间窗把事件**聚类**后交给 LLM 摘要——它不产生事件对关联，与本模块互补而非替代。

依赖方向：本引擎只依赖 SQLite 与 AuditLog；被（理论上）EventExtractor 使用。events.db 的 events 表结构由 EventExtractor 建好（见 EventExtractor.md 第 3 节），引擎自己只补建四张分析结果表（`Detail/EventCorrelationEngineCore.cpp:121-221`）。

## 3. 核心概念与设计

**规则即数据**。`CorrelationRule`（`EventCorrelationEngine.h:78-87`）携带类型、`std::function` 条件、置信度阈值、时间窗。`registerDefaultRules()`（`EventCorrelationEngineCore.cpp:35-95`）注册五条内置规则：

| rule_id | 时间窗 | 置信度阈值 | 关联含义 |
|---|---|---|---|
| time_based_rule | 60 秒 | >0.7 | 事件发生在同一分钟内（same_time） |
| source_based_rule | 300 秒 | >0.8 | 同一 source_id（same_source） |
| target_based_rule | 300 秒 | >0.8 | 同一 file_path（same_file） |
| context_based_rule | 600 秒 | >0.6 | system_context 相似（same_context） |
| sequence_based_rule | 120 秒 | >0.9 | 固定序列模式（sequence） |

（表为源码规则的摘要，定义见上述行号。）注意规则结构虽然存在，但五条 analyze 方法实际把窗口和阈值**硬编码在 SQL/判断里**，`rules_` 更多是元数据记录——扩展时别指望只加规则对象就生效，要写对应的 analyze 方法。

**置信度函数刻意简单**（`Detail/EventCorrelationUtils.cpp`）：时间相关度在窗口内线性从 1.0 衰减到 0.7（`:6-17`）；源/目标相等即 1.0 否则 0（`:19-25`）；上下文用逐字符相同比例（`:27-43`）。0.7 的下限有明确注释依据：`analyzeTimeBasedCorrelations` 用 `>= 0.7` 而非 `> 0.7`，因为窗口边界（正好 60 秒）的置信度恰为 0.7，仍属"窗口内"（`EventCorrelationAnalyzer.cpp:61-65` 的注释）。

**关联查询全部是自连接**：`FROM events e1 JOIN events e2 ON e1.id < e2.id WHERE ABS(e1.timestamp - e2.timestamp) <= <窗>`（如 `EventCorrelationAnalyzer.cpp:31-38`）。`e1.id < e2.id` 保证每对只出现一次；窗口条件先在 SQL 里粗筛，置信度阈值在 C++ 侧精筛。`e1.id < e2.id` 与时间先后无关（id 是插入序），所以方向标注多为 BI。

**序列规则**是唯一的方向性（UNI）来源：把全部事件按时间排序后扫相邻对，命中三种固定模式（FILE_CREATED→FILE_MODIFIED、LOGIN→PROCESS_CREATED、NETWORK_CONNECTION→FILE_DOWNLOADED，`EventCorrelationAnalyzer.cpp:263-288`）给 0.95 置信度。这里的 `FILE_DOWNLOADED` 等类型名与 EventExtractor 的 normalizeEventType 输出（`WEB_BROWSER_DOWNLOAD` 等）并不对齐——见第 6 节。

**事件链 = 关联图的连通分量**。`buildEventChains()`（`EventChainBuilder.cpp:43-154`）把关联对按 eventId 建邻接表，从任一未访问事件 BFS 展开成一条链（节点间按关联方向建父子边，双向关联会形成互相父子，`:95-108`）；根取链内最早事件（`:117-120`），链置信度是节点均值。落库时用 `visitedNodes` 集合切断环——双向关联会产生环，不防就无限递归 INSERT（`EventCorrelationEngineCore.cpp:283-289` 的注释记录了这个真实修过的挂死）。

**因果**只在满足时间先后（time1 < time2）的关联上推导，mechanism 按 correlationType 映射（sequence→Temporal sequence、same_file→Same file interaction、same_source→Same source action），置信度 ×0.9 且须 >0.7（`EventChainBuilder.cpp:170-216`）。

### 3.1 核心数据结构（EventCorrelationEngine.h:40-97）

```cpp
struct EventCorrelation {
    int64_t eventId1;
    int64_t eventId2;
    std::string correlationType;  // same_user, same_time, same_process, same_ip, same_file
    double confidence;            // 关联置信度 (0-1)
    std::string description;      // 关联描述
    CorrelationStrength strength; // 关联强度
    CorrelationDirection direction; // 关联方向
    int64_t timestamp;            // 关联时间戳
    std::string ruleId;           // 关联规则ID
};

struct CorrelationRule {
    std::string ruleId;
    std::string name;
    std::string description;
    CorrelationRuleType type;
    std::function<bool(const EventCorrelation&)> condition;
    double confidenceThreshold; // 置信度阈值
    int timeWindow; // 时间窗口（秒）
    bool enabled; // 是否启用
};

struct CausalRelationship {
    int64_t causeEventId;
    int64_t effectEventId;
    double confidence; // 因果置信度
    std::string description; // 因果描述
    int64_t timeDelay; // 时间延迟（秒）
    std::string mechanism; // 因果机制
};
```

配套三个枚举（h:16-38）：`CorrelationRuleType` 六值（TIME/SOURCE/TARGET/CONTEXT/SEQUENCE/CUSTOM）、`CorrelationStrength` 四档（LOW…CRITICAL）、`CorrelationDirection` 三态（UNI/BI/UNKNOWN）。逐组解释：`EventCorrelation` 是引擎的原子产出，`eventId1/eventId2` 引用 events 表自增 id（**不是 inode**），`correlationType` 注释列出的取值（same_user/same_ip…）比五条规则实际产出的（same_time/same_source/same_file/same_context/sequence）更宽——注释是设想集，代码是现实集；`timestamp` 存"对中较早时间"（time_based 路径 `std::min(time1,time2)`）。`CorrelationRule.condition` 是唯一的函数成员——为"规则可编程"预留，但五条内置规则的 analyze 路径并不调用它（见上述"规则是元数据"注意）。`CausalRelationship` 比 EventCorrelation 多出 `timeDelay`（因果间隔秒数，前端渲染时间差用）与 `mechanism`（人类可读的机制名），`causeEventId/effectEventId` 的方向性替代了 1/2 的无序对。另有 `EventChainNode/EventChain`（h:54-75）：节点带 children/parents 双向 `shared_ptr` 数组（图而非链），链聚合 nodes/confidence/start-end 时间与 involvedEntities。

### 3.2 核心接口清单

| 签名（EventCorrelationEngine.h） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `explicit EventCorrelationEngine(eventDbPath)` | 记录库路径 | EventExtractor 包装器、测试 | 无 |
| `bool initialize()` | 开库（busy_timeout 5s）+ 建四张结果表 + 注册默认规则 | 调用流程第一步 | 失败返回 false |
| `bool analyzeCorrelations()` | 依序跑五个 analyze 方法并落库 event_correlations | 包装器/测试 | 单维 SQL 失败静默跳过，整体仍返回 true |
| `vector<EventChain> analyzeEventChains()` | 关联对 → 连通分量链，落库 event_chains | 同上 | 依赖上一步结果，空关联得空链 |
| `vector<CausalRelationship> discoverCausalRelationships()` | 时间有序关联 → 因果，落库 | 同上 | 同上 |
| `vector<EventCorrelation> getCorrelations() const` 等三个 getter | 取内存结果 | 导出/测试 | 无 |
| `bool exportCorrelations/exportEventChains/exportCausalRelationships(outputPath) const` | 结果写 JSON | 包装器的导出段 | 写文件失败返回 false |
| `string visualizeCorrelations() const` 等三个 visualize | 生成 Graphviz dot 文本 | 包装器 | 无（纯字符串拼装） |

## 4. 工作流程走读

以（测试中的）典型调用为序：

1. 构造 `EventCorrelationEngine engine(eventsDbPath)` 并 `initialize()`（`EventCorrelationEngineCore.cpp:17-33`）：开库（busy_timeout 5 秒防锁竞争，`:101-112`）→ 建四张结果表与索引（`:121-221`）→ 注册默认规则（`:29`）。
2. `analyzeCorrelations()`（`EventCorrelationAnalyzer.cpp:8-27`）：依次跑五个 analyze 方法，命中的关联进内存 `correlations_`，最后逐条 `insertCorrelation` 写 event_correlations 表。
3. `analyzeEventChains()`（`EventChainBuilder.cpp:12-24`）：基于上一步的关联构图 BFS，链与节点写入 event_chains/event_chain_nodes。
4. `discoverCausalRelationships()`（`:156-168`）：扫关联对推因果，写 causal_relationships。
5. （包装器才会做的）`exportCorrelations/exportEventChains/exportCausalRelationships` 出 JSON，`visualize*` 出 Graphviz dot 文本（`Detail/EventCorrelationExporter.cpp`）。

三步之间有数据依赖：没有关联就没有链，没有链/关联就没有因果——调用方必须按序执行（或像包装器那样全调）。

### 4.1 代码走读：时间关联的自连接与边界注释（EventCorrelationAnalyzer.cpp:29-88）

```cpp
void EventCorrelationEngine::analyzeTimeBasedCorrelations() {
    // 基于时间的关联分析
    const char* query = R"(
    SELECT e1.id, e1.timestamp, e1.event_type, e1.file_path, e1.source_id,
           e2.id, e2.timestamp, e2.event_type, e2.file_path, e2.source_id
    FROM events e1
    JOIN events e2 ON e1.id < e2.id
    WHERE ABS(e1.timestamp - e2.timestamp) <= 60
    ORDER BY e1.timestamp;
    )";
    // ... prepare 失败静默 return（:40-44），逐行取 10 列（:46-58）
        double confidence = calculateTimeCorrelation(time1, time2, 60);

        // >= 0.7: calculateTimeCorrelation returns exactly 0.7 at the window
        // boundary (its documented floor for "within the window"). A strict
        // > 0.7 wrongly excluded events exactly 60s apart, which ARE "within
        // 60 seconds".
        if (confidence >= 0.7) {
            EventCorrelation corr;
            corr.eventId1 = eventId1;
            corr.eventId2 = eventId2;
            corr.correlationType = "same_time";
            corr.confidence = confidence;
            corr.description = "Events occurred within 60 seconds";
            corr.strength = CorrelationStrength::MEDIUM;
            corr.direction = CorrelationDirection::BI;
            corr.timestamp = std::min(time1, time2);
            corr.ruleId = "time_based_rule";

            correlations_.push_back(corr);
        }
    // ... finalize（:86）
```

逐块解释：JOIN 条件 `e1.id < e2.id` 是**去重的关键**——自连接天然产生 (A,B) 与 (B,A) 两份，id 全序砍掉一半；配合 `ABS(时间差)` 的对称性，语义正好是"每个无序对一次"。时间窗硬编码 60（与 rules_ 表里的 time_based_rule.timeWindow=60 是两处数据，改一处不改另一处就漂移——"规则即数据"未贯彻的实锤）。置信度两段式：SQL 只做廉价粗筛（ABS<=60），C++ 侧 `calculateTimeCorrelation` 算线性衰减分；**四行英文注释记录了一次真实 bug 修复**：严格 `> 0.7` 会排除恰好间隔 60 秒的对，而衰减函数在窗口边界正好取到 0.7 下限——边界含闭与否必须与衰减函数的定义对齐。direction=BI 是因为 id 序不保证时间序；timestamp 取 min 让关联拥有确定的时间锚点。

### 4.2 代码走读：序列规则的相邻对扫描（EventCorrelationAnalyzer.cpp:262-289）

```cpp
    // 分析事件序列
    for (size_t i = 0; i < events.size() - 1; ++i) {
        auto& [id1, time1, type1, path1, source1] = events[i];
        auto& [id2, time2, type2, path2, source2] = events[i + 1];

        // 检查时间间隔
        if (time2 - time1 <= 120) {
            // 检查常见序列模式
            if ((type1 == "FILE_CREATED" && type2 == "FILE_MODIFIED") ||
                (type1 == "LOGIN" && type2 == "PROCESS_CREATED") ||
                (type1 == "NETWORK_CONNECTION" && type2 == "FILE_DOWNLOADED")) {

                EventCorrelation corr;
                corr.eventId1 = id1;
                corr.eventId2 = id2;
                corr.correlationType = "sequence";
                corr.confidence = 0.95;
                corr.description = "Event sequence: " + type1 + " -> " + type2;
                corr.strength = CorrelationStrength::HIGH;
                corr.direction = CorrelationDirection::UNI;
                corr.timestamp = time1;
                corr.ruleId = "sequence_based_rule";

                correlations_.push_back(corr);
            }
        }
    }
```

逐块解释：序列规则与前四条不同，**不走 SQL 自连接**——先全量取 events 排序（时间序）进内存 vector，然后只扫**相邻对**（i 与 i+1）。这带来一个隐含语义：匹配的是"时间上紧挨着的两件事"，若 A→B 中间插入了任何第三事件 C（哪怕 C 与模式无关），相邻对变成 A-C、C-B，序列**不再命中**——它检测的是"连续两拍"，不是"60 秒内先 A 后 B"。结构化绑定（`auto& [id1, time1, ...]`）直接解 tuple，五个变量里 path1/source1 在本函数甚至未被使用（留给扩展）。三种模式是硬编码白名单，方向 UNI + 0.95 高置信度（序列是引擎里最强的证据形态）；类型串与 normalizeEventType 输出的错位（LOGIN/FILE_DOWNLOADED 不存在）使前两条模式在生产数据上大概率空转——第三条 NETWORK_CONNECTION 同样取决于平台 import 是否产出该串。

### 4.3 代码走读：因果推导的门控链（EventChainBuilder.cpp:170-216）

```cpp
    for (const auto& corr : correlations_) {
        // 只考虑单向关联和有时间顺序的关联
        if (corr.direction == CorrelationDirection::UNI || corr.eventId1 < corr.eventId2) {
            auto event1Info = getEventInfo(corr.eventId1);
            auto event2Info = getEventInfo(corr.eventId2);

            if (event1Info.empty() || event2Info.empty()) {
                continue;
            }

            int64_t time1 = std::stoll(event1Info["timestamp"]);
            int64_t time2 = std::stoll(event2Info["timestamp"]);

            // 确保时间顺序
            if (time1 < time2) {
                // 计算因果置信度
                double causalConfidence = corr.confidence * 0.9; // 因果置信度略低于关联置信度

                // 检查是否符合因果模式
                std::string mechanism = "";
                if (corr.correlationType == "sequence") {
                    mechanism = "Temporal sequence";
                } else if (corr.correlationType == "same_file") {
                    mechanism = "Same file interaction";
                } else if (corr.correlationType == "same_source") {
                    mechanism = "Same source action";
                }

                if (!mechanism.empty() && causalConfidence > 0.7) {
                    // ... 组装 CausalRelationship（rel.timeDelay = time2 - time1 等，:204-212）
                }
            }
        }
    }
```

逐块解释：因果是关联的**严格子集**，四道门按序收紧——(1) 方向门：UNI 关联（序列产出）或 id 有序的对才考虑；(2) 存在门：两个事件都能查到（getEventInfo 按 eventId 反查 events 表，空则弃）；(3) 时间门：time1 < time2 严格小于（同时事件不可能有因果）；(4) 机制门：只有三种 correlationType 有资格谈因果，same_time/same_context 这类纯巧合关联被拒之门外。`confidence * 0.9` 的折损是有方向的认知立场——"相关不蕴含因果"，宁可漏报不可虚报，这正是取证报告能站住脚的前提；折损后仍须 >0.7 意味着原始置信度低于约 0.78 的关联连因果候选都不是。mechanism 从 correlationType 映射而来，是给人读的因果解释标签——报告里"为什么 A 导致 B"的答案就是它。注意因果不建新边，只在既有关联上**加注方向与机制**：链分析用关联构图，因果分析给边定向，两者共用同一份 correlations_。

## 5. 与其他模块的协作

- **EventExtractor**：宿主关系。引擎消费 EventExtractor 建的 events 表（依赖 normalized_type/source_id/file_path 等列的语义，这些列的填充见 EventExtractor.md 第 3 节）；包装器 `analyzeEventCorrelations()`（`EventCorrelationExtractor.cpp:31-80`）是二者唯一的桥，且当前无调用方。
- **AuditLog**：初始化与各分析步骤写审计（EVENT_CORRELATION_ENGINE_INIT、EVENT_CORRELATION_ANALYSIS_COMPLETE、CAUSAL_RELATIONSHIP_DISCOVERY_* 等，`EventCorrelationEngineCore.cpp:18,31`）。
- **EventClusterAnalyzer / LLM 栈**：不交互但常被比较——聚类走 LLM 摘要、关联走规则，产物表也不同（events 的 llm_* 列 vs event_correlations 表）。
- 出错时行为：开库/建表失败返回 false；单条 analyze 的 SQL 失败静默返回（如 `EventCorrelationAnalyzer.cpp:41-44`），表现为该维度关联缺失，`analyzeCorrelations` 整体仍返回 true——调用方需要靠审计记录判断实际完成度。
- 表契约：只读 events；写 event_correlations / event_chains / event_chain_nodes / causal_relationships 四张表（含索引，`EventCorrelationEngineCore.cpp:121-221`）。

## 6. 注意事项与已知问题

- **生产未接线（最重要的现状）**：HTTP/CLI 流水线都不调用关联分析；事件相关性在生产 events.db 里通常只有空表。接入点应在 TaskManagerAnalysis 的 EVENT_EXTRACTION 之后（或作为独立阶段），调 `EventExtractor::analyzeEventCorrelations()` 即可复用导出逻辑。
- **O(n²) 复杂度**：五个自连接里三个没有除时间窗外的索引辅助粗筛，大时间窗（600 秒）在密集事件流上会产生海量候选对。接线前必须评估数据量，或先给 events(timestamp) 建索引、缩小窗口。
- **序列规则与标准化类型脱节**：`analyzeSequenceBasedCorrelations` 匹配的 `LOGIN`/`PROCESS_CREATED`/`FILE_DOWNLOADED` 与 normalizeEventType 的实际输出（`USER_LOGIN_SUCCESS`、`PROCESS_CREATED` 有但 `LOGIN` 无、`WEB_BROWSER_DOWNLOAD`）部分对不上——当前生产数据下序列关联大概率空转。修复需对照 `EventCorrelationExtractor.cpp:270-313` 的映射表逐个核对。
- 上下文相似度是逐字符比较，对"同前缀不同后缀"的长 system_context 会给出虚高分数；且 FILE_SYSTEM 事件的 system_context 多为空串（空即 0 分），该规则实际主要作用于平台 import 的事件。
- `src/core/DatabaseManager/EventCorrelationEngine/` 目录只剩一个过时 README（指向不存在的文件布局），实际代码在 `src/core/EventCorrelationEngine/`——目录名撞车加剧了第 2 节的混淆，阅读时认准路径。
- **窗口/阈值双源**：rules_ 表中的 timeWindow/confidenceThreshold 与 analyze 方法里的硬编码值是两份独立数据（60/300/600/120 秒与 0.7/0.8/0.6/0.95），调参时两处都要改。
- 序列规则只看相邻对：中间插入无关事件即断链（见 4.2），需要"窗口内先后"语义时应改为滑动窗口内查找。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_event_correlation_engine.cpp`（`tests/CMakeLists.txt:1048`，测试名 `EventCorrelationEngineTests`），含 `discoverCausalRelationships` 的用例（该文件 :120）。
- 手工验证：拿一个已有 events.db 跑测试目标，或临时在 CLI 加调用后检查 `sqlite3 <events.db> "SELECT correlation_type, COUNT(*) FROM event_correlations GROUP BY 1"`、导出的 `.dot` 用 `dot -Tpng` 渲染。
- 扩展新关联维度：在 `EventCorrelationAnalyzer.cpp` 加一个 `analyzeXxxCorrelations`（自连接 + 置信度函数放 `EventCorrelationUtils.cpp`）+ 在 `analyzeCorrelations`（`:14-18`）挂上 + `registerDefaultRules` 补元数据。想让"规则对象真正驱动分析"是更大的重构：把 SQL 参数化出 rule 的 window/threshold。
- 修复序列规则：以 `normalizeEventType` 的输出集为准重写 `:270-272` 的模式表，并为每类平台事件补典型序列（如 PREFETCH_EXECUTION 之后同文件的 FILE_DELETED）。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
