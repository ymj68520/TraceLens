#include "../EventCorrelationEngine.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <sstream>

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

} // namespace EventCorrelationEngine
