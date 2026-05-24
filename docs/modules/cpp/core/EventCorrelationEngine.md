# EventCorrelationEngine - 事件关联分析引擎

> **模块定位**: 对时间线事件进行关联分析，发现事件之间的因果关系和模式，构建事件链

---

## 1. 模块概述

### 位置

`src/core/EventCorrelationEngine/EventCorrelationEngine.h`

### 设计目标

在数字取证中，单个事件往往不足以说明问题。EventCorrelationEngine 通过分析事件之间的时间、来源、目标和上下文关联，帮助调查人员发现隐藏的模式和因果关系。

### 核心能力

- **多维关联**: 基于时间、来源、目标、上下文、序列等多个维度进行关联分析
- **事件链构建**: 将相关事件串联成有向事件链，还原攻击或操作序列
- **因果发现**: 自动发现事件之间的因果关系和时间延迟
- **置信度评估**: 每个关联和因果关系都带有置信度评分
- **可视化导出**: 支持关联结果的文本可视化和 JSON 导出

---

## 2. 核心概念

### 关联规则类型

```cpp
enum class CorrelationRuleType {
    TIME_BASED,      // 基于时间窗口的关联
    SOURCE_BASED,    // 基于来源（同一用户/进程）的关联
    TARGET_BASED,    // 基于目标（同一文件/IP）的关联
    CONTEXT_BASED,   // 基于上下文（同目录/同会话）的关联
    SEQUENCE_BASED,  // 基于序列（因果顺序）的关联
    CUSTOM           // 自定义规则
};
```

### 关联强度

```cpp
enum class CorrelationStrength {
    LOW,       // 低强度（可能相关）
    MEDIUM,    // 中等强度（很可能相关）
    HIGH,      // 高强度（几乎确定相关）
    CRITICAL   // 关键关联（直接因果）
};
```

### 关联方向

```cpp
enum class CorrelationDirection {
    UNI,     // 单向（A → B）
    BI,      // 双向（A ↔ B）
    UNKNOWN  // 未知方向
};
```

---

## 3. 数据结构

### EventCorrelation

两个事件之间的关联：

```cpp
struct EventCorrelation {
    int64_t eventId1;
    int64_t eventId2;
    std::string correlationType;   // same_user, same_time, same_process, same_ip, same_file
    double confidence;             // 0-1
    std::string description;
    CorrelationStrength strength;
    CorrelationDirection direction;
    int64_t timestamp;
    std::string ruleId;
};
```

### EventChain

一组有序的关联事件：

```cpp
struct EventChain {
    std::string chainId;
    std::shared_ptr<EventChainNode> root;
    std::vector<std::shared_ptr<EventChainNode>> nodes;
    double confidence;
    std::string description;
    int64_t startTime;
    int64_t endTime;
    std::vector<std::string> involvedEntities;
};
```

### CausalRelationship

事件之间的因果关系：

```cpp
struct CausalRelationship {
    int64_t causeEventId;
    int64_t effectEventId;
    double confidence;
    std::string description;
    int64_t timeDelay;       // 时间延迟（秒）
    std::string mechanism;   // 因果机制描述
};
```

### CorrelationRule

自定义关联规则：

```cpp
struct CorrelationRule {
    std::string ruleId;
    std::string name;
    std::string description;
    CorrelationRuleType type;
    std::function<bool(const EventCorrelation&)> condition;
    double confidenceThreshold;
    int timeWindow;    // 时间窗口（秒）
    bool enabled;
};
```

---

## 4. API 参考

### 初始化

```cpp
EventCorrelationEngine engine("/path/to/events.db");
engine.initialize();
```

### 规则管理

```cpp
// 注册自定义规则
CorrelationRule rule;
rule.ruleId = "rapid_file_access";
rule.name = "Rapid File Access";
rule.type = CorrelationRuleType::TIME_BASED;
rule.timeWindow = 60;  // 60 秒内
rule.confidenceThreshold = 0.8;
rule.condition = [](const EventCorrelation& c) {
    return c.confidence >= 0.8;
};
engine.registerRule(rule);

// 注册默认规则集
engine.registerDefaultRules();
```

### 执行分析

```cpp
// 执行关联分析
bool success = engine.analyzeCorrelations();

// 分析事件链
auto chains = engine.analyzeEventChains();

// 发现因果关系
auto causal = engine.discoverCausalRelationships();
```

### 获取结果

```cpp
// 获取所有关联
auto correlations = engine.getCorrelations();

// 获取事件链
auto chains = engine.getEventChains();

// 获取因果关系
auto causal = engine.getCausalRelationships();
```

### 导出和可视化

```cpp
// 导出为 JSON
engine.exportCorrelations("/output/correlations.json");
engine.exportEventChains("/output/chains.json");
engine.exportCausalRelationships("/output/causal.json");

// 文本可视化
std::string viz = engine.visualizeCorrelations();
std::string chainViz = engine.visualizeEventChains();
std::string causalViz = engine.visualizeCausalRelationships();
```

---

## 5. 内置关联分析方法

| 方法 | 说明 |
|------|------|
| `analyzeTimeBasedCorrelations()` | 在时间窗口内关联事件 |
| `analyzeSourceBasedCorrelations()` | 关联同一来源（用户/进程）的事件 |
| `analyzeTargetBasedCorrelations()` | 关联同一目标（文件/IP）的事件 |
| `analyzeContextBasedCorrelations()` | 基于上下文关联事件 |
| `analyzeSequenceBasedCorrelations()` | 基于事件序列关联 |

### 相关性计算

```cpp
double calculateTimeCorrelation(int64_t time1, int64_t time2, int timeWindow);
double calculateSourceCorrelation(const std::string& source1, const std::string& source2);
double calculateTargetCorrelation(const std::string& target1, const std::string& target2);
double calculateContextCorrelation(const std::string& context1, const std::string& context2);
```

---

## 6. 典型使用场景

### 场景1: 检测文件篡改链

```
事件1: USER_A 访问 /etc/passwd (T+0s)
事件2: USER_A 修改 /etc/passwd (T+5s)
事件3: USER_A 执行 useradd 命令 (T+10s)
事件4: 新用户登录 (T+30s)
→ 发现: 完整的账户创建链，置信度 0.95
```

### 场景2: 检测数据外泄

```
事件1: 进程X 读取 database.db (T+0s)
事件2: 进程X 创建 temp.zip (T+2s)
事件3: 进程X 连接 external-ip (T+5s)
→ 发现: 数据外泄模式，置信度 0.85
```

---

## 7. 数据库集成

分析结果存储在 `_events.db` 的关联表中：

```sql
CREATE TABLE event_correlations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id_1 INTEGER,
    event_id_2 INTEGER,
    correlation_type TEXT,
    confidence REAL,
    description TEXT,
    strength TEXT,
    direction TEXT,
    rule_id TEXT,
    timestamp INTEGER
);

CREATE TABLE event_chains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id TEXT,
    confidence REAL,
    description TEXT,
    start_time INTEGER,
    end_time INTEGER,
    involved_entities TEXT
);

CREATE TABLE causal_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cause_event_id INTEGER,
    effect_event_id INTEGER,
    confidence REAL,
    description TEXT,
    time_delay INTEGER,
    mechanism TEXT
);
```

---

**最后更新**: 2026-05-19
