#pragma once
#ifndef EVENT_CORRELATION_ENGINE_H
#define EVENT_CORRELATION_ENGINE_H

#include <string>
#include <vector>
#include <map>
#include <memory>
#include <sqlite3.h>
#include <functional>

namespace EventCorrelationEngine {


// 事件关联规则类型
enum class CorrelationRuleType {
    TIME_BASED,        // 基于时间的关联
    SOURCE_BASED,      // 基于源的关联
    TARGET_BASED,      // 基于目标的关联
    CONTEXT_BASED,     // 基于上下文的关联
    SEQUENCE_BASED,    // 基于序列的关联
    CUSTOM             // 自定义规则
};

// 事件关联强度
enum class CorrelationStrength {
    LOW,        // 低强度关联
    MEDIUM,     // 中等强度关联
    HIGH,       // 高强度关联
    CRITICAL    // 关键关联
};

// 事件关联方向
enum class CorrelationDirection {
    UNI,        // 单向关联
    BI,         // 双向关联
    UNKNOWN     // 未知方向
};

// 事件关联结构体
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

// 事件链节点
struct EventChainNode {
    int64_t eventId;
    std::string eventType;
    int64_t timestamp;
    std::string description;
    std::vector<std::shared_ptr<EventChainNode>> children;
    std::vector<std::shared_ptr<EventChainNode>> parents;
    double confidence; // 节点置信度
    std::string path;  // 文件路径或其他上下文
};

// 事件链
struct EventChain {
    std::string chainId;
    std::shared_ptr<EventChainNode> root;
    std::vector<std::shared_ptr<EventChainNode>> nodes;
    double confidence; // 链条置信度
    std::string description; // 链条描述
    int64_t startTime; // 开始时间
    int64_t endTime;   // 结束时间
    std::vector<std::string> involvedEntities; // 涉及的实体
};

// 关联规则结构体
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

// 因果关系
struct CausalRelationship {
    int64_t causeEventId;
    int64_t effectEventId;
    double confidence; // 因果置信度
    std::string description; // 因果描述
    int64_t timeDelay; // 时间延迟（秒）
    std::string mechanism; // 因果机制
};

// 事件关联规则引擎
class EventCorrelationEngine {
public:
    explicit EventCorrelationEngine(const std::string& eventDbPath);
    ~EventCorrelationEngine();

    // 初始化引擎
    bool initialize();

    // 注册关联规则
    void registerRule(const CorrelationRule& rule);
    
    // 注册默认规则
    void registerDefaultRules();

    // 执行关联分析
    bool analyzeCorrelations();

    // 执行事件链分析
    std::vector<EventChain> analyzeEventChains();

    // 发现因果关系
    std::vector<CausalRelationship> discoverCausalRelationships();

    // 获取关联事件
    std::vector<EventCorrelation> getCorrelations() const;

    // 获取事件链
    std::vector<EventChain> getEventChains() const;

    // 获取因果关系
    std::vector<CausalRelationship> getCausalRelationships() const;

    // 导出关联分析结果
    bool exportCorrelations(const std::string& outputPath) const;

    // 导出事件链
    bool exportEventChains(const std::string& outputPath) const;

    // 导出因果关系
    bool exportCausalRelationships(const std::string& outputPath) const;

    // 可视化关联分析结果
    std::string visualizeCorrelations() const;

    // 可视化事件链
    std::string visualizeEventChains() const;

    // 可视化因果关系
    std::string visualizeCausalRelationships() const;

private:
    std::string eventDbPath_;
    sqlite3* eventDb_;
    std::vector<CorrelationRule> rules_;
    std::vector<EventCorrelation> correlations_;
    std::vector<EventChain> eventChains_;
    std::vector<CausalRelationship> causalRelationships_;

    // 数据库操作
    bool openDatabase();
    void closeDatabase();
    bool createCorrelationTables();
    bool insertCorrelation(const EventCorrelation& correlation);
    bool insertEventChain(const EventChain& chain);
    bool insertCausalRelationship(const CausalRelationship& relationship);

    // 关联分析方法
    void analyzeTimeBasedCorrelations();
    void analyzeSourceBasedCorrelations();
    void analyzeTargetBasedCorrelations();
    void analyzeContextBasedCorrelations();
    void analyzeSequenceBasedCorrelations();

    // 事件链构建
    std::shared_ptr<EventChainNode> buildEventChainNode(int64_t eventId);
    void buildEventChains();

    // 因果关系分析
    void analyzeCausalRelationships();

    // 工具方法
    double calculateTimeCorrelation(int64_t time1, int64_t time2, int timeWindow);
    double calculateSourceCorrelation(const std::string& source1, const std::string& source2);
    double calculateTargetCorrelation(const std::string& target1, const std::string& target2);
    double calculateContextCorrelation(const std::string& context1, const std::string& context2);

    // 获取事件信息
    std::map<std::string, std::string> getEventInfo(int64_t eventId);
};

} // namespace EventCorrelationEngine

#endif // EVENT_CORRELATION_ENGINE_H
