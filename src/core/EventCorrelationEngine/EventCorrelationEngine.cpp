#include "EventCorrelationEngine.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <sstream>
#include <algorithm>
#include <chrono>
#include <random>
#include <set>
#include <queue>
#include <fstream>

namespace EventCorrelationEngine {

EventCorrelationEngine::EventCorrelationEngine(const std::string& eventDbPath)
    : eventDbPath_(eventDbPath), eventDb_(nullptr) {
}

EventCorrelationEngine::~EventCorrelationEngine() {
    closeDatabase();
}

bool EventCorrelationEngine::initialize() {
    AuditLog::instance().log("SYSTEM", "EVENT_CORRELATION_ENGINE_INIT", "Initializing event correlation engine");
    
    if (!openDatabase()) {
        return false;
    }
    
    if (!createCorrelationTables()) {
        return false;
    }
    
    // 注册默认关联规则
    registerDefaultRules();
    
    AuditLog::instance().log("SYSTEM", "EVENT_CORRELATION_ENGINE_INIT_COMPLETE", "Event correlation engine initialized");
    return true;
}

void EventCorrelationEngine::registerDefaultRules() {
    // 基于时间的关联规则
    CorrelationRule timeRule;
    timeRule.ruleId = "time_based_rule";
    timeRule.name = "Time-based Correlation";
    timeRule.description = "Correlate events within a time window";
    timeRule.type = CorrelationRuleType::TIME_BASED;
    timeRule.condition = [](const EventCorrelation& c) { return c.confidence > 0.7; };
    timeRule.confidenceThreshold = 0.7;
    timeRule.timeWindow = 60; // 60秒
    timeRule.enabled = true;
    registerRule(timeRule);
    
    // 基于源的关联规则
    CorrelationRule sourceRule;
    sourceRule.ruleId = "source_based_rule";
    sourceRule.name = "Source-based Correlation";
    sourceRule.description = "Correlate events from the same source";
    sourceRule.type = CorrelationRuleType::SOURCE_BASED;
    sourceRule.condition = [](const EventCorrelation& c) { return c.confidence > 0.8; };
    sourceRule.confidenceThreshold = 0.8;
    sourceRule.timeWindow = 300; // 5分钟
    sourceRule.enabled = true;
    registerRule(sourceRule);
    
    // 基于目标的关联规则
    CorrelationRule targetRule;
    targetRule.ruleId = "target_based_rule";
    targetRule.name = "Target-based Correlation";
    targetRule.description = "Correlate events with the same target";
    targetRule.type = CorrelationRuleType::TARGET_BASED;
    targetRule.condition = [](const EventCorrelation& c) { return c.confidence > 0.8; };
    targetRule.confidenceThreshold = 0.8;
    targetRule.timeWindow = 300; // 5分钟
    targetRule.enabled = true;
    registerRule(targetRule);
    
    // 基于上下文的关联规则
    CorrelationRule contextRule;
    contextRule.ruleId = "context_based_rule";
    contextRule.name = "Context-based Correlation";
    contextRule.description = "Correlate events with similar context";
    contextRule.type = CorrelationRuleType::CONTEXT_BASED;
    contextRule.condition = [](const EventCorrelation& c) { return c.confidence > 0.6; };
    contextRule.confidenceThreshold = 0.6;
    contextRule.timeWindow = 600; // 10分钟
    contextRule.enabled = true;
    registerRule(contextRule);
    
    // 基于序列的关联规则
    CorrelationRule sequenceRule;
    sequenceRule.ruleId = "sequence_based_rule";
    sequenceRule.name = "Sequence-based Correlation";
    sequenceRule.description = "Correlate events in a specific sequence";
    sequenceRule.type = CorrelationRuleType::SEQUENCE_BASED;
    sequenceRule.condition = [](const EventCorrelation& c) { return c.confidence > 0.9; };
    sequenceRule.confidenceThreshold = 0.9;
    sequenceRule.timeWindow = 120; // 2分钟
    sequenceRule.enabled = true;
    registerRule(sequenceRule);
}

void EventCorrelationEngine::registerRule(const CorrelationRule& rule) {
    rules_.push_back(rule);
}

bool EventCorrelationEngine::analyzeCorrelations() {
    AuditLog::instance().log("SYSTEM", "EVENT_CORRELATION_ANALYSIS_START", "Starting event correlation analysis");
    
    correlations_.clear();
    
    // 执行各种类型的关联分析
    analyzeTimeBasedCorrelations();
    analyzeSourceBasedCorrelations();
    analyzeTargetBasedCorrelations();
    analyzeContextBasedCorrelations();
    analyzeSequenceBasedCorrelations();
    
    // 保存关联结果到数据库
    for (const auto& correlation : correlations_) {
        insertCorrelation(correlation);
    }
    
    AuditLog::instance().log("SYSTEM", "EVENT_CORRELATION_ANALYSIS_COMPLETE", "Event correlation analysis completed. Found " + std::to_string(correlations_.size()) + " correlations");
    return true;
}

std::vector<EventChain> EventCorrelationEngine::analyzeEventChains() {
    AuditLog::instance().log("SYSTEM", "EVENT_CHAIN_ANALYSIS_START", "Starting event chain analysis");
    
    buildEventChains();
    
    // 保存事件链到数据库
    for (const auto& chain : eventChains_) {
        insertEventChain(chain);
    }
    
    AuditLog::instance().log("SYSTEM", "EVENT_CHAIN_ANALYSIS_COMPLETE", "Event chain analysis completed. Found " + std::to_string(eventChains_.size()) + " event chains");
    return eventChains_;
}

std::vector<CausalRelationship> EventCorrelationEngine::discoverCausalRelationships() {
    AuditLog::instance().log("SYSTEM", "CAUSAL_RELATIONSHIP_DISCOVERY_START", "Starting causal relationship discovery");
    
    analyzeCausalRelationships();
    
    // 保存因果关系到数据库
    for (const auto& relationship : causalRelationships_) {
        insertCausalRelationship(relationship);
    }
    
    AuditLog::instance().log("SYSTEM", "CAUSAL_RELATIONSHIP_DISCOVERY_COMPLETE", "Causal relationship discovery completed. Found " + std::to_string(causalRelationships_.size()) + " causal relationships");
    return causalRelationships_;
}

std::vector<EventCorrelation> EventCorrelationEngine::getCorrelations() const {
    return correlations_;
}

std::vector<EventChain> EventCorrelationEngine::getEventChains() const {
    return eventChains_;
}

std::vector<CausalRelationship> EventCorrelationEngine::getCausalRelationships() const {
    return causalRelationships_;
}

bool EventCorrelationEngine::exportCorrelations(const std::string& outputPath) const {
    // 导出关联分析结果到JSON文件
    std::ofstream output(outputPath);
    if (!output.is_open()) {
        return false;
    }
    
    output << "{" << std::endl;
    output << "  \"correlations\": [" << std::endl;
    
    for (size_t i = 0; i < correlations_.size(); ++i) {
        const auto& corr = correlations_[i];
        output << "    {" << std::endl;
        output << "      \"eventId1\": " << corr.eventId1 << "," << std::endl;
        output << "      \"eventId2\": " << corr.eventId2 << "," << std::endl;
        output << "      \"correlationType\": \"" << corr.correlationType << "\"," << std::endl;
        output << "      \"confidence\": " << corr.confidence << "," << std::endl;
        output << "      \"description\": \"" << corr.description << "\"," << std::endl;
        output << "      \"strength\": \"" << static_cast<int>(corr.strength) << "\"," << std::endl;
        output << "      \"direction\": \"" << static_cast<int>(corr.direction) << "\"," << std::endl;
        output << "      \"timestamp\": " << corr.timestamp << "," << std::endl;
        output << "      \"ruleId\": \"" << corr.ruleId << "\"" << std::endl;
        output << "    }" << (i < correlations_.size() - 1 ? "," : "") << std::endl;
    }
    
    output << "  ]" << std::endl;
    output << "}" << std::endl;
    
    output.close();
    return true;
}

bool EventCorrelationEngine::exportEventChains(const std::string& outputPath) const {
    // 导出事件链到JSON文件
    std::ofstream output(outputPath);
    if (!output.is_open()) {
        return false;
    }
    
    output << "{" << std::endl;
    output << "  \"eventChains\": [" << std::endl;
    
    for (size_t i = 0; i < eventChains_.size(); ++i) {
        const auto& chain = eventChains_[i];
        output << "    {" << std::endl;
        output << "      \"chainId\": \"" << chain.chainId << "\"," << std::endl;
        output << "      \"confidence\": " << chain.confidence << "," << std::endl;
        output << "      \"description\": \"" << chain.description << "\"," << std::endl;
        output << "      \"startTime\": " << chain.startTime << "," << std::endl;
        output << "      \"endTime\": " << chain.endTime << "," << std::endl;
        output << "      \"involvedEntities\": [";
        for (size_t j = 0; j < chain.involvedEntities.size(); ++j) {
            output << "\"" << chain.involvedEntities[j] << "\"" << (j < chain.involvedEntities.size() - 1 ? "," : "");
        }
        output << "]" << std::endl;
        output << "    }" << (i < eventChains_.size() - 1 ? "," : "") << std::endl;
    }
    
    output << "  ]" << std::endl;
    output << "}" << std::endl;
    
    output.close();
    return true;
}

bool EventCorrelationEngine::exportCausalRelationships(const std::string& outputPath) const {
    // 导出因果关系到JSON文件
    std::ofstream output(outputPath);
    if (!output.is_open()) {
        return false;
    }
    
    output << "{" << std::endl;
    output << "  \"causalRelationships\": [" << std::endl;
    
    for (size_t i = 0; i < causalRelationships_.size(); ++i) {
        const auto& rel = causalRelationships_[i];
        output << "    {" << std::endl;
        output << "      \"causeEventId\": " << rel.causeEventId << "," << std::endl;
        output << "      \"effectEventId\": " << rel.effectEventId << "," << std::endl;
        output << "      \"confidence\": " << rel.confidence << "," << std::endl;
        output << "      \"description\": \"" << rel.description << "\"," << std::endl;
        output << "      \"timeDelay\": " << rel.timeDelay << "," << std::endl;
        output << "      \"mechanism\": \"" << rel.mechanism << "\"" << std::endl;
        output << "    }" << (i < causalRelationships_.size() - 1 ? "," : "") << std::endl;
    }
    
    output << "  ]" << std::endl;
    output << "}" << std::endl;
    
    output.close();
    return true;
}

std::string EventCorrelationEngine::visualizeCorrelations() const {
    // 生成DOT格式的可视化
    std::stringstream dot;
    dot << "digraph EventCorrelations {" << std::endl;
    dot << "  rankdir=LR;" << std::endl;
    dot << "  node [shape=box, style=filled, fillcolor=lightblue];" << std::endl;
    
    for (const auto& corr : correlations_) {
        dot << "  event" << corr.eventId1 << " -> event" << corr.eventId2 << " [";
        dot << "label=\"" << corr.correlationType << " (" << corr.confidence << ")\", ";
        
        // 根据强度设置颜色
        switch (corr.strength) {
            case CorrelationStrength::LOW:
                dot << "color=green";
                break;
            case CorrelationStrength::MEDIUM:
                dot << "color=yellow";
                break;
            case CorrelationStrength::HIGH:
                dot << "color=orange";
                break;
            case CorrelationStrength::CRITICAL:
                dot << "color=red";
                break;
        }
        
        dot << "];" << std::endl;
    }
    
    dot << "}" << std::endl;
    return dot.str();
}

std::string EventCorrelationEngine::visualizeEventChains() const {
    // 生成DOT格式的可视化
    std::stringstream dot;
    dot << "digraph EventChains {" << std::endl;
    dot << "  rankdir=TB;" << std::endl;
    dot << "  node [shape=box, style=filled, fillcolor=lightgreen];" << std::endl;
    
    for (const auto& chain : eventChains_) {
        // 为每个事件链创建子图
        dot << "  subgraph cluster_" << chain.chainId << " {" << std::endl;
        dot << "    label=\"" << chain.description << " (Confidence: " << chain.confidence << ")\"" << std::endl;
        
        // 递归添加节点和边
        std::function<void(const std::shared_ptr<EventChainNode>&)> addNode = [&](const std::shared_ptr<EventChainNode>& node) {
            dot << "    event" << node->eventId << " [label=\"" << node->eventType << "\n" << node->description << "\"];" << std::endl;
            for (const auto& child : node->children) {
                dot << "    event" << node->eventId << " -> event" << child->eventId << ";" << std::endl;
                addNode(child);
            }
        };
        
        if (chain.root) {
            addNode(chain.root);
        }
        
        dot << "  }" << std::endl;
    }
    
    dot << "}" << std::endl;
    return dot.str();
}

std::string EventCorrelationEngine::visualizeCausalRelationships() const {
    // 生成DOT格式的可视化
    std::stringstream dot;
    dot << "digraph CausalRelationships {" << std::endl;
    dot << "  rankdir=LR;" << std::endl;
    dot << "  node [shape=box, style=filled, fillcolor=lightyellow];" << std::endl;
    
    for (const auto& rel : causalRelationships_) {
        dot << "  event" << rel.causeEventId << " -> event" << rel.effectEventId << " [";
        dot << "label=\"" << rel.mechanism << " (" << rel.confidence << ")\", ";
        dot << "color=red, style=dashed";
        dot << "];" << std::endl;
    }
    
    dot << "}" << std::endl;
    return dot.str();
}

bool EventCorrelationEngine::openDatabase() {
    int rc = sqlite3_open(eventDbPath_.c_str(), &eventDb_);
    if (rc != SQLITE_OK) {
        std::cerr << "Cannot open event database: " << sqlite3_errmsg(eventDb_) << std::endl;
        return false;
    }
    return true;
}

void EventCorrelationEngine::closeDatabase() {
    if (eventDb_) {
        sqlite3_close(eventDb_);
        eventDb_ = nullptr;
    }
}

bool EventCorrelationEngine::createCorrelationTables() {
    // 创建关联表
    const char* createCorrelationsTable = R"(
    CREATE TABLE IF NOT EXISTS event_correlations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id1 INTEGER NOT NULL,
        event_id2 INTEGER NOT NULL,
        correlation_type TEXT NOT NULL,
        confidence REAL NOT NULL,
        description TEXT,
        strength INTEGER,
        direction INTEGER,
        timestamp INTEGER,
        rule_id TEXT,
        FOREIGN KEY (event_id1) REFERENCES events(id),
        FOREIGN KEY (event_id2) REFERENCES events(id)
    );
    )";
    
    // 创建事件链表
    const char* createEventChainsTable = R"(
    CREATE TABLE IF NOT EXISTS event_chains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chain_id TEXT NOT NULL,
        description TEXT,
        confidence REAL NOT NULL,
        start_time INTEGER,
        end_time INTEGER
    );
    )";
    
    // 创建事件链节点表
    const char* createEventChainNodesTable = R"(
    CREATE TABLE IF NOT EXISTS event_chain_nodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chain_id TEXT NOT NULL,
        event_id INTEGER NOT NULL,
        parent_event_id INTEGER,
        FOREIGN KEY (event_id) REFERENCES events(id),
        FOREIGN KEY (chain_id) REFERENCES event_chains(chain_id)
    );
    )";
    
    // 创建因果关系表
    const char* createCausalRelationshipsTable = R"(
    CREATE TABLE IF NOT EXISTS causal_relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cause_event_id INTEGER NOT NULL,
        effect_event_id INTEGER NOT NULL,
        confidence REAL NOT NULL,
        description TEXT,
        time_delay INTEGER,
        mechanism TEXT,
        FOREIGN KEY (cause_event_id) REFERENCES events(id),
        FOREIGN KEY (effect_event_id) REFERENCES events(id)
    );
    )";
    
    char* errMsg = nullptr;
    
    int rc = sqlite3_exec(eventDb_, createCorrelationsTable, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to create correlations table: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }
    
    rc = sqlite3_exec(eventDb_, createEventChainsTable, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to create event chains table: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }
    
    rc = sqlite3_exec(eventDb_, createEventChainNodesTable, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to create event chain nodes table: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }
    
    rc = sqlite3_exec(eventDb_, createCausalRelationshipsTable, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to create causal relationships table: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }
    
    // 创建索引
    const char* createIndices = R"(
    CREATE INDEX IF NOT EXISTS idx_event_correlations_event1 ON event_correlations(event_id1);
    CREATE INDEX IF NOT EXISTS idx_event_correlations_event2 ON event_correlations(event_id2);
    CREATE INDEX IF NOT EXISTS idx_event_chain_nodes_chain ON event_chain_nodes(chain_id);
    CREATE INDEX IF NOT EXISTS idx_causal_relationships_cause ON causal_relationships(cause_event_id);
    CREATE INDEX IF NOT EXISTS idx_causal_relationships_effect ON causal_relationships(effect_event_id);
    )";
    
    sqlite3_exec(eventDb_, createIndices, nullptr, nullptr, nullptr);
    
    return true;
}

bool EventCorrelationEngine::insertCorrelation(const EventCorrelation& correlation) {
    const char* query = R"(
    INSERT INTO event_correlations (event_id1, event_id2, correlation_type, confidence, description, strength, direction, timestamp, rule_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
    )";
    
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, query, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        return false;
    }
    
    sqlite3_bind_int64(stmt, 1, correlation.eventId1);
    sqlite3_bind_int64(stmt, 2, correlation.eventId2);
    sqlite3_bind_text(stmt, 3, correlation.correlationType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_double(stmt, 4, correlation.confidence);
    sqlite3_bind_text(stmt, 5, correlation.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 6, static_cast<int>(correlation.strength));
    sqlite3_bind_int(stmt, 7, static_cast<int>(correlation.direction));
    sqlite3_bind_int64(stmt, 8, correlation.timestamp);
    sqlite3_bind_text(stmt, 9, correlation.ruleId.c_str(), -1, SQLITE_TRANSIENT);
    
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    return rc == SQLITE_DONE;
}

bool EventCorrelationEngine::insertEventChain(const EventChain& chain) {
    // 插入事件链
    const char* chainQuery = R"(
    INSERT INTO event_chains (chain_id, description, confidence, start_time, end_time)
    VALUES (?, ?, ?, ?, ?);
    )";
    
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, chainQuery, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        return false;
    }
    
    sqlite3_bind_text(stmt, 1, chain.chainId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, chain.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_double(stmt, 3, chain.confidence);
    sqlite3_bind_int64(stmt, 4, chain.startTime);
    sqlite3_bind_int64(stmt, 5, chain.endTime);
    
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    if (rc != SQLITE_DONE) {
        return false;
    }
    
    // 插入事件链节点
    const char* nodeQuery = R"(
    INSERT INTO event_chain_nodes (chain_id, event_id, parent_event_id)
    VALUES (?, ?, ?);
    )";
    
    // 递归插入节点
    std::function<bool(const std::shared_ptr<EventChainNode>&, int64_t)> insertNode = [&](const std::shared_ptr<EventChainNode>& node, int64_t parentEventId) {
        sqlite3_stmt* nodeStmt;
        int rc = sqlite3_prepare_v2(eventDb_, nodeQuery, -1, &nodeStmt, nullptr);
        if (rc != SQLITE_OK) {
            return false;
        }
        
        sqlite3_bind_text(nodeStmt, 1, chain.chainId.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_int64(nodeStmt, 2, node->eventId);
        if (parentEventId > 0) {
            sqlite3_bind_int64(nodeStmt, 3, parentEventId);
        } else {
            sqlite3_bind_null(nodeStmt, 3);
        }
        
        rc = sqlite3_step(nodeStmt);
        sqlite3_finalize(nodeStmt);
        
        if (rc != SQLITE_DONE) {
            return false;
        }
        
        for (const auto& child : node->children) {
            if (!insertNode(child, node->eventId)) {
                return false;
            }
        }
        
        return true;
    };
    
    if (chain.root) {
        return insertNode(chain.root, 0);
    }
    
    return true;
}

bool EventCorrelationEngine::insertCausalRelationship(const CausalRelationship& relationship) {
    const char* query = R"(
    INSERT INTO causal_relationships (cause_event_id, effect_event_id, confidence, description, time_delay, mechanism)
    VALUES (?, ?, ?, ?, ?, ?);
    )";
    
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, query, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        return false;
    }
    
    sqlite3_bind_int64(stmt, 1, relationship.causeEventId);
    sqlite3_bind_int64(stmt, 2, relationship.effectEventId);
    sqlite3_bind_double(stmt, 3, relationship.confidence);
    sqlite3_bind_text(stmt, 4, relationship.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 5, relationship.timeDelay);
    sqlite3_bind_text(stmt, 6, relationship.mechanism.c_str(), -1, SQLITE_TRANSIENT);
    
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    return rc == SQLITE_DONE;
}

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
    
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, query, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        return;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        int64_t eventId1 = sqlite3_column_int64(stmt, 0);
        int64_t time1 = sqlite3_column_int64(stmt, 1);
        const char* type1 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        const char* path1 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        const char* source1 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        
        int64_t eventId2 = sqlite3_column_int64(stmt, 5);
        int64_t time2 = sqlite3_column_int64(stmt, 6);
        const char* type2 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        const char* path2 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
        const char* source2 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9));
        
        double confidence = calculateTimeCorrelation(time1, time2, 60);
        
        if (confidence > 0.7) {
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
    }
    
    sqlite3_finalize(stmt);
}

void EventCorrelationEngine::analyzeSourceBasedCorrelations() {
    // 基于源的关联分析
    const char* query = R"(
    SELECT e1.id, e1.timestamp, e1.event_type, e1.source_id,
           e2.id, e2.timestamp, e2.event_type, e2.source_id
    FROM events e1
    JOIN events e2 ON e1.id < e2.id AND e1.source_id = e2.source_id
    WHERE ABS(e1.timestamp - e2.timestamp) <= 300
    ORDER BY e1.source_id, e1.timestamp;
    )";
    
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, query, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        return;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        int64_t eventId1 = sqlite3_column_int64(stmt, 0);
        int64_t time1 = sqlite3_column_int64(stmt, 1);
        const char* type1 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        const char* source1 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        
        int64_t eventId2 = sqlite3_column_int64(stmt, 4);
        int64_t time2 = sqlite3_column_int64(stmt, 5);
        const char* type2 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
        const char* source2 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        
        double confidence = calculateSourceCorrelation(source1, source2);
        
        if (confidence > 0.8) {
            EventCorrelation corr;
            corr.eventId1 = eventId1;
            corr.eventId2 = eventId2;
            corr.correlationType = "same_source";
            corr.confidence = confidence;
            corr.description = "Events from the same source";
            corr.strength = CorrelationStrength::HIGH;
            corr.direction = CorrelationDirection::BI;
            corr.timestamp = std::min(time1, time2);
            corr.ruleId = "source_based_rule";
            
            correlations_.push_back(corr);
        }
    }
    
    sqlite3_finalize(stmt);
}

void EventCorrelationEngine::analyzeTargetBasedCorrelations() {
    // 基于目标的关联分析
    const char* query = R"(
    SELECT e1.id, e1.timestamp, e1.event_type, e1.file_path,
           e2.id, e2.timestamp, e2.event_type, e2.file_path
    FROM events e1
    JOIN events e2 ON e1.id < e2.id AND e1.file_path = e2.file_path
    WHERE ABS(e1.timestamp - e2.timestamp) <= 300
    ORDER BY e1.file_path, e1.timestamp;
    )";
    
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, query, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        return;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        int64_t eventId1 = sqlite3_column_int64(stmt, 0);
        int64_t time1 = sqlite3_column_int64(stmt, 1);
        const char* type1 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        const char* path1 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        
        int64_t eventId2 = sqlite3_column_int64(stmt, 4);
        int64_t time2 = sqlite3_column_int64(stmt, 5);
        const char* type2 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
        const char* path2 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        
        double confidence = calculateTargetCorrelation(path1, path2);
        
        if (confidence > 0.8) {
            EventCorrelation corr;
            corr.eventId1 = eventId1;
            corr.eventId2 = eventId2;
            corr.correlationType = "same_file";
            corr.confidence = confidence;
            corr.description = "Events affecting the same file";
            corr.strength = CorrelationStrength::HIGH;
            corr.direction = CorrelationDirection::BI;
            corr.timestamp = std::min(time1, time2);
            corr.ruleId = "target_based_rule";
            
            correlations_.push_back(corr);
        }
    }
    
    sqlite3_finalize(stmt);
}

void EventCorrelationEngine::analyzeContextBasedCorrelations() {
    // 基于上下文的关联分析
    const char* query = R"(
    SELECT e1.id, e1.timestamp, e1.event_type, e1.file_path, e1.system_context,
           e2.id, e2.timestamp, e2.event_type, e2.file_path, e2.system_context
    FROM events e1
    JOIN events e2 ON e1.id < e2.id
    WHERE ABS(e1.timestamp - e2.timestamp) <= 600
    ORDER BY e1.timestamp;
    )";
    
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, query, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        return;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        int64_t eventId1 = sqlite3_column_int64(stmt, 0);
        int64_t time1 = sqlite3_column_int64(stmt, 1);
        const char* type1 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        const char* path1 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        const char* context1 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        
        int64_t eventId2 = sqlite3_column_int64(stmt, 5);
        int64_t time2 = sqlite3_column_int64(stmt, 6);
        const char* type2 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        const char* path2 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
        const char* context2 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9));
        
        double confidence = calculateContextCorrelation(context1 ? context1 : "", context2 ? context2 : "");
        
        if (confidence > 0.6) {
            EventCorrelation corr;
            corr.eventId1 = eventId1;
            corr.eventId2 = eventId2;
            corr.correlationType = "same_context";
            corr.confidence = confidence;
            corr.description = "Events with similar context";
            corr.strength = CorrelationStrength::MEDIUM;
            corr.direction = CorrelationDirection::BI;
            corr.timestamp = std::min(time1, time2);
            corr.ruleId = "context_based_rule";
            
            correlations_.push_back(corr);
        }
    }
    
    sqlite3_finalize(stmt);
}

void EventCorrelationEngine::analyzeSequenceBasedCorrelations() {
    // 基于序列的关联分析
    // 这里实现一个简单的序列分析，寻找常见的事件序列
    const char* query = R"(
    SELECT id, timestamp, event_type, file_path, source_id
    FROM events
    ORDER BY timestamp;
    )";
    
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, query, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        return;
    }
    
    std::vector<std::tuple<int64_t, int64_t, std::string, std::string, std::string>> events;
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        int64_t id = sqlite3_column_int64(stmt, 0);
        int64_t timestamp = sqlite3_column_int64(stmt, 1);
        const char* eventType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        const char* filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        const char* sourceId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        
        events.emplace_back(id, timestamp, eventType ? eventType : "", filePath ? filePath : "", sourceId ? sourceId : "");
    }
    
    sqlite3_finalize(stmt);
    
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
}

std::shared_ptr<EventChainNode> EventCorrelationEngine::buildEventChainNode(int64_t eventId) {
    auto eventInfo = getEventInfo(eventId);
    if (eventInfo.empty()) {
        return nullptr;
    }
    
    auto node = std::make_shared<EventChainNode>();
    node->eventId = eventId;
    node->eventType = eventInfo["event_type"];
    node->timestamp = std::stoll(eventInfo["timestamp"]);
    node->description = eventInfo["description"];
    node->path = eventInfo["file_path"];
    node->confidence = 1.0;
    
    return node;
}

void EventCorrelationEngine::buildEventChains() {
    eventChains_.clear();
    
    // 基于关联构建事件链
    std::map<int64_t, std::vector<EventCorrelation>> eventCorrelations;
    for (const auto& corr : correlations_) {
        eventCorrelations[corr.eventId1].push_back(corr);
        eventCorrelations[corr.eventId2].push_back(corr);
    }
    
    // 构建事件链
    std::set<int64_t> processedEvents;
    for (const auto& [eventId, corrs] : eventCorrelations) {
        if (processedEvents.count(eventId)) {
            continue;
        }
        
        // 构建事件链
        EventChain chain;
        chain.chainId = "chain_" + std::to_string(std::chrono::system_clock::now().time_since_epoch().count());
        chain.confidence = 0.0;
        
        // 广度优先搜索构建链条
        std::queue<int64_t> eventQueue;
        eventQueue.push(eventId);
        processedEvents.insert(eventId);
        
        std::map<int64_t, std::shared_ptr<EventChainNode>> nodeMap;
        
        while (!eventQueue.empty()) {
            int64_t currentEventId = eventQueue.front();
            eventQueue.pop();
            
            auto node = buildEventChainNode(currentEventId);
            if (!node) {
                continue;
            }
            
            nodeMap[currentEventId] = node;
            chain.nodes.push_back(node);
            
            // 查找相关事件
            for (const auto& corr : eventCorrelations[currentEventId]) {
                int64_t relatedEventId = (corr.eventId1 == currentEventId) ? corr.eventId2 : corr.eventId1;
                if (!processedEvents.count(relatedEventId)) {
                    eventQueue.push(relatedEventId);
                    processedEvents.insert(relatedEventId);
                    
                    // 添加父子关系
                    auto relatedNode = buildEventChainNode(relatedEventId);
                    if (relatedNode) {
                        nodeMap[relatedEventId] = relatedNode;
                        if (corr.direction == CorrelationDirection::UNI) {
                            if (corr.eventId1 == currentEventId) {
                                node->children.push_back(relatedNode);
                                relatedNode->parents.push_back(node);
                            } else {
                                node->parents.push_back(relatedNode);
                                relatedNode->children.push_back(node);
                            }
                        } else {
                            node->children.push_back(relatedNode);
                            node->parents.push_back(relatedNode);
                            relatedNode->children.push_back(node);
                            relatedNode->parents.push_back(node);
                        }
                    }
                }
            }
        }
        
        // 设置根节点和时间范围
        if (!chain.nodes.empty()) {
            // 选择最早的事件作为根节点
            chain.root = *std::min_element(chain.nodes.begin(), chain.nodes.end(),
                [](const std::shared_ptr<EventChainNode>& a, const std::shared_ptr<EventChainNode>& b) {
                    return a->timestamp < b->timestamp;
                });
            
            // 计算时间范围
            chain.startTime = chain.root->timestamp;
            chain.endTime = chain.root->timestamp;
            for (const auto& node : chain.nodes) {
                chain.startTime = std::min(chain.startTime, node->timestamp);
                chain.endTime = std::max(chain.endTime, node->timestamp);
            }
            
            // 计算链条置信度
            double totalConfidence = 0.0;
            for (const auto& node : chain.nodes) {
                totalConfidence += node->confidence;
            }
            chain.confidence = totalConfidence / chain.nodes.size();
            
            // 生成描述
            std::stringstream desc;
            desc << "Event chain with " << chain.nodes.size() << " events";
            chain.description = desc.str();
            
            // 提取涉及的实体
            std::set<std::string> entities;
            for (const auto& node : chain.nodes) {
                if (!node->path.empty()) {
                    entities.insert(node->path);
                }
            }
            chain.involvedEntities.assign(entities.begin(), entities.end());
            
            eventChains_.push_back(chain);
        }
    }
}

void EventCorrelationEngine::analyzeCausalRelationships() {
    causalRelationships_.clear();
    
    // 基于关联和时间顺序分析因果关系
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
                    CausalRelationship rel;
                    rel.causeEventId = corr.eventId1;
                    rel.effectEventId = corr.eventId2;
                    rel.confidence = causalConfidence;
                    rel.description = "Cause: " + event1Info["event_type"] + ", Effect: " + event2Info["event_type"];
                    rel.timeDelay = time2 - time1;
                    rel.mechanism = mechanism;
                    
                    causalRelationships_.push_back(rel);
                }
            }
        }
    }
}

double EventCorrelationEngine::calculateTimeCorrelation(int64_t time1, int64_t time2, int timeWindow) {
    int64_t timeDiff = std::abs(time1 - time2);
    if (timeDiff > timeWindow) {
        return 0.0;
    }
    if (timeWindow == 0) {
        return 1.0;
    }
    // Calculate confidence that ranges from 1.0 (0s difference) to 0.7 (timeWindow difference)
    double confidence = 1.0 - (static_cast<double>(timeDiff) / timeWindow) * 0.3;
    return std::max(0.7, confidence);
}

double EventCorrelationEngine::calculateSourceCorrelation(const std::string& source1, const std::string& source2) {
    return source1 == source2 ? 1.0 : 0.0;
}

double EventCorrelationEngine::calculateTargetCorrelation(const std::string& target1, const std::string& target2) {
    return target1 == target2 ? 1.0 : 0.0;
}

double EventCorrelationEngine::calculateContextCorrelation(const std::string& context1, const std::string& context2) {
    if (context1.empty() || context2.empty()) {
        return 0.0;
    }
    
    // 简单的上下文相似度计算
    int commonChars = 0;
    int minLength = std::min(context1.length(), context2.length());
    
    for (int i = 0; i < minLength; ++i) {
        if (context1[i] == context2[i]) {
            commonChars++;
        }
    }
    
    return static_cast<double>(commonChars) / std::max(context1.length(), context2.length());
}

std::map<std::string, std::string> EventCorrelationEngine::getEventInfo(int64_t eventId) {
    std::map<std::string, std::string> info;
    
    const char* query = R"(
    SELECT timestamp, event_type, file_path, description, source_id, system_context
    FROM events
    WHERE id = ?;
    )";
    
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, query, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        return info;
    }
    
    sqlite3_bind_int64(stmt, 1, eventId);
    
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        info["timestamp"] = std::to_string(sqlite3_column_int64(stmt, 0));
        
        const char* eventType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        info["event_type"] = eventType ? eventType : "";
        
        const char* filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        info["file_path"] = filePath ? filePath : "";
        
        const char* description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        info["description"] = description ? description : "";
        
        const char* sourceId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        info["source_id"] = sourceId ? sourceId : "";
        
        const char* systemContext = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
        info["system_context"] = systemContext ? systemContext : "";
    }
    
    sqlite3_finalize(stmt);
    return info;
}

} // namespace EventCorrelationEngine
