# 事件关联规则引擎

位置: `DatabaseManager/EventCorrelationEngine/`

## 目的
- 实现基于时间、源、目标等维度的事件关联分析
- 支持事件链分析和因果关系发现
- 提供关联结果的可视化表示
- 支持自定义关联规则

## 主要文件
- `EventCorrelationEngine.h` - 核心类和数据结构定义
- `EventCorrelationEngine.cpp` - 实现文件

## 核心功能

### 1. 多维度事件关联分析
- **时间关联**：分析时间窗口内的事件关联
- **来源关联**：分析同一来源的事件关联
- **目标关联**：分析同一目标的事件关联
- **文件路径关联**：分析同一文件路径的事件关联
- **进程关联**：分析同一进程的事件关联
- **用户关联**：分析同一用户的事件关联
- **IP地址关联**：分析同一IP地址的事件关联
- **服务关联**：分析同一服务的事件关联

### 2. 事件链分析
- 基于关联关系构建事件链
- 支持链式事件序列分析
- 提供事件链的时间顺序和类型分析

### 3. 因果关系发现
- 基于时间顺序和事件类型分析因果关系
- 计算因果关系置信度
- 支持中间事件分析

### 4. 可视化支持
- 生成Graphviz格式的关联图
- 生成事件链可视化
- 生成因果关系可视化

### 5. 规则管理
- 内置默认关联规则
- 支持加载自定义规则
- 支持启用/禁用规则
- 支持导出/导入规则

## 数据结构

### 事件关联结构
```cpp
struct EventCorrelation {
    int64_t eventId1;
    int64_t eventId2;
    std::string correlationType;
    double confidence;
    std::string description;
    // 其他事件属性...
};
```

### 事件链结构
```cpp
struct EventChain {
    int chainId;
    std::vector<int64_t> eventIds;
    std::vector<std::string> eventTypes;
    std::vector<int64_t> timestamps;
    std::vector<std::string> descriptions;
    double confidence;
    std::string chainType;
    std::string startEvent;
    std::string endEvent;
    int64_t startTime;
    int64_t endTime;
};
```

### 因果关系结构
```cpp
struct CausalRelationship {
    int64_t causeEventId;
    int64_t effectEventId;
    std::string causeEventType;
    std::string effectEventType;
    double confidence;
    std::string description;
    int64_t causeTimestamp;
    int64_t effectTimestamp;
    std::string mechanism;
    std::vector<int64_t> intermediateEvents;
};
```

### 关联规则结构
```cpp
struct CorrelationRule {
    std::string name;
    std::string description;
    std::vector<std::string> eventTypes1;
    std::vector<std::string> eventTypes2;
    int timeWindowSeconds;
    double minConfidence;
    std::string correlationType;
    bool enabled;
};
```

## 数据库结构

### 事件链表
- `event_chains` - 存储事件链信息
- `event_chain_links` - 存储事件链与事件的关联

### 因果关系表
- `causal_relationships` - 存储因果关系信息
- `causal_intermediate_events` - 存储中间事件信息

## 使用示例

### 基本使用
```cpp
// 创建事件关联引擎
EventCorrelationEngine::EventCorrelationEngine engine("events.db");

// 初始化引擎
if (engine.initialize()) {
    // 执行关联分析
    engine.analyzeCorrelations();
    
    // 获取事件链
    auto chains = engine.analyzeEventChains();
    
    // 发现因果关系
    auto causalRelationships = engine.discoverCausalRelationships();
    
    // 导出结果
    engine.exportCorrelations("correlations.json");
    engine.exportEventChains("event_chains.json");
    engine.exportCausalRelationships("causal_relationships.json");
    
    // 生成可视化
    std::string correlationsDot = engine.visualizeCorrelations();
    std::string eventChainsDot = engine.visualizeEventChains();
    std::string causalRelationshipsDot = engine.visualizeCausalRelationships();
    
    // 保存可视化结果
    std::ofstream corrDotFile("correlations.dot");
    corrDotFile << correlationsDot;
    corrDotFile.close();
}
```

### 自定义规则
```cpp
// 创建自定义规则
EventCorrelationEngine::CorrelationRule rule;
rule.name = "custom_network_rule";
rule.description = "网络活动与文件操作的关联";
rule.eventTypes1 = {"NETWORK_CONNECTION"};
rule.eventTypes2 = {"FILE_CREATED", "FILE_MODIFIED"};
rule.timeWindowSeconds = 300;
rule.minConfidence = 0.7;
rule.correlationType = "IP_ADDRESS";
rule.enabled = true;

// 添加规则
engine.addRule(rule);

// 保存规则
engine.saveRules("custom_rules.json");

// 加载规则
engine.loadCustomRules("custom_rules.json");
```

## 性能优化

1. **事件索引**：构建多维度事件索引，加快关联分析速度
2. **批处理**：使用事务批量插入数据，提高数据库操作性能
3. **并行处理**：可考虑使用线程池并行处理不同维度的关联分析
4. **增量分析**：支持增量分析，只处理新事件

## 扩展点

1. **自定义关联规则**：支持用户定义的关联规则
2. **机器学习集成**：可集成机器学习模型提高关联分析准确性
3. **实时分析**：支持实时事件流的关联分析
4. **多数据源集成**：支持从多个数据源获取事件进行关联分析
5. **可视化增强**：提供更丰富的可视化选项，如时间线视图、热力图等

## 注意事项

1. **性能考虑**：事件数量较大时，关联分析可能会消耗较多资源
2. **内存使用**：加载大量事件时需要注意内存使用
3. **置信度阈值**：根据实际场景调整置信度阈值，平衡准确性和召回率
4. **时间窗口**：根据事件类型和场景调整时间窗口大小

## 测试建议

1. **单元测试**：测试各个关联分析模块
2. **集成测试**：测试完整的关联分析流程
3. **性能测试**：测试不同规模事件集的处理性能
4. **准确性测试**：验证关联分析结果的准确性

## 输出文件

- `correlations.json` - 关联分析结果
- `event_chains.json` - 事件链分析结果
- `causal_relationships.json` - 因果关系分析结果
- `correlations.dot` - 关联可视化Graphviz文件
- `event_chains.dot` - 事件链可视化Graphviz文件
- `causal_relationships.dot` - 因果关系可视化Graphviz文件

## 依赖

- SQLite3 - 数据库存储
- nlohmann/json - JSON序列化/反序列化
- Graphviz (可选) - 可视化图形生成
