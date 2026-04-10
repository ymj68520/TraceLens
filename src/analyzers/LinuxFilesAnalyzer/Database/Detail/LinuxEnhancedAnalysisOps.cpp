// LinuxEnhancedAnalysisOps.cpp
// Database operations for enhanced analysis (correlation, timeline, anomalies)

#include "LinuxAnalysisDatabase.h"
#include "LinuxQueryBuilder.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include "Detail/LinuxDatabaseHelpers.h"
#include <nlohmann/json.hpp>
#include <mutex>

using namespace LinuxAnalysis;
using json = nlohmann::json;

// ============================================================================
// Correlated Event Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertCorrelatedEvent(const CorrelatedEvent& event) {
    const char* sql = LinuxAnalysisSQL::INSERT_CORRELATED_EVENT;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT64(stmt, 1, event.startTimestamp);
    BIND_INT64(stmt, 2, event.endTimestamp);
    BIND_TEXT(stmt, 3, event.eventType);
    BIND_TEXT(stmt, 4, event.initiatingUser);
    BIND_TEXT(stmt, 5, event.initiatingProcess);
    BIND_TEXT(stmt, 6, vectorToJson(event.relatedEventIds));
    BIND_TEXT(stmt, 7, event.description);
    BIND_INT(stmt, 8, event.severity);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertCorrelatedEvents(const std::vector<CorrelatedEvent>& events) {
    beginTransaction();
    for (const auto& event : events) {
        if (!insertCorrelatedEvent(event)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<CorrelatedEvent> LinuxAnalysisDatabase::queryCorrelatedEvents(const std::string& whereClause) {
    std::vector<CorrelatedEvent> events;
    std::string sql = "SELECT start_timestamp, end_timestamp, event_type, initiating_user, initiating_process, related_event_ids, description, severity FROM linux_correlated_events";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return events;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        CorrelatedEvent event;
        event.startTimestamp = sqlite3_column_int64(stmt, 0);
        event.endTimestamp = sqlite3_column_int64(stmt, 1);
        event.eventType = safeColumnText(stmt, 2);
        event.initiatingUser = safeColumnText(stmt, 3);
        event.initiatingProcess = safeColumnText(stmt, 4);
        event.relatedEventIds = jsonToVector<std::string>(safeColumnText(stmt, 5));
        event.description = safeColumnText(stmt, 6);
        event.severity = sqlite3_column_int(stmt, 7);
        events.push_back(event);
    }

    return events;
}

std::vector<CorrelatedEvent> LinuxAnalysisDatabase::queryCorrelatedEventsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<CorrelatedEvent> events;

    std::string sql = "SELECT start_timestamp, end_timestamp, event_type, initiating_user, initiating_process, related_event_ids, description, severity FROM linux_correlated_events";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return events;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return events;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        CorrelatedEvent event;
        event.startTimestamp = sqlite3_column_int64(stmt, 0);
        event.endTimestamp = sqlite3_column_int64(stmt, 1);
        event.eventType = safeColumnText(stmt, 2);
        event.initiatingUser = safeColumnText(stmt, 3);
        event.initiatingProcess = safeColumnText(stmt, 4);
        event.relatedEventIds = jsonToVector<std::string>(safeColumnText(stmt, 5));
        event.description = safeColumnText(stmt, 6);
        event.severity = sqlite3_column_int(stmt, 7);
        events.push_back(event);
    }

    return events;
}

// ============================================================================
// Attack Chain Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertAttackChain(const AttackChain& chain) {
    const char* sql = LinuxAnalysisSQL::INSERT_ATTACK_CHAIN;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, chain.chainId);
    BIND_TEXT(stmt, 2, chain.attackType);
    // Serialize events vector to JSON
    json eventsJson = json::array();
    for (const auto& event : chain.events) {
        json eventJson;
        eventJson["start_timestamp"] = event.startTimestamp;
        eventJson["end_timestamp"] = event.endTimestamp;
        eventJson["event_type"] = event.eventType;
        eventJson["initiating_user"] = event.initiatingUser;
        eventJson["initiating_process"] = event.initiatingProcess;
        eventJson["related_event_ids"] = event.relatedEventIds;
        eventJson["description"] = event.description;
        eventJson["severity"] = event.severity;
        eventsJson.push_back(eventJson);
    }
    BIND_TEXT(stmt, 3, eventsJson.dump());
    BIND_TEXT(stmt, 4, chain.timeline);
    BIND_TEXT(stmt, 5, chain.summary);
    BIND_DOUBLE(stmt, 6, chain.confidence);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertAttackChains(const std::vector<AttackChain>& chains) {
    beginTransaction();
    for (const auto& chain : chains) {
        if (!insertAttackChain(chain)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<AttackChain> LinuxAnalysisDatabase::queryAttackChains(const std::string& whereClause) {
    std::vector<AttackChain> chains;
    std::string sql = "SELECT chain_id, attack_type, events, timeline, summary, confidence FROM linux_attack_chains";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return chains;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AttackChain chain;
        chain.chainId = safeColumnText(stmt, 0);
        chain.attackType = safeColumnText(stmt, 1);

        // Parse events from JSON
        const char* eventsJson = safeColumnText(stmt, 2);
        if (eventsJson) {
            try {
                json eventsArray = json::parse(eventsJson);
                for (const auto& eventJson : eventsArray) {
                    CorrelatedEvent event;
                    if (eventJson.contains("start_timestamp")) event.startTimestamp = eventJson["start_timestamp"];
                    if (eventJson.contains("end_timestamp")) event.endTimestamp = eventJson["end_timestamp"];
                    if (eventJson.contains("event_type")) event.eventType = eventJson["event_type"];
                    if (eventJson.contains("initiating_user")) event.initiatingUser = eventJson["initiating_user"];
                    if (eventJson.contains("initiating_process")) event.initiatingProcess = eventJson["initiating_process"];
                    if (eventJson.contains("related_event_ids")) event.relatedEventIds = eventJson["related_event_ids"].get<std::vector<std::string>>();
                    if (eventJson.contains("description")) event.description = eventJson["description"];
                    if (eventJson.contains("severity")) event.severity = eventJson["severity"];
                    chain.events.push_back(event);
                }
            } catch (const std::exception& e) {
                std::cerr << "Error parsing events JSON: " << e.what() << std::endl;
            }
        }

        chain.timeline = safeColumnText(stmt, 3);
        chain.summary = safeColumnText(stmt, 4);
        chain.confidence = static_cast<float>(sqlite3_column_double(stmt, 5));
        chains.push_back(chain);
    }

    return chains;
}

std::vector<AttackChain> LinuxAnalysisDatabase::queryAttackChainsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<AttackChain> chains;

    std::string sql = "SELECT chain_id, attack_type, events, timeline, summary, confidence FROM linux_attack_chains";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return chains;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return chains;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AttackChain chain;
        chain.chainId = safeColumnText(stmt, 0);
        chain.attackType = safeColumnText(stmt, 1);

        // Parse events from JSON
        const char* eventsJson = safeColumnText(stmt, 2);
        if (eventsJson) {
            try {
                json eventsArray = json::parse(eventsJson);
                for (const auto& eventJson : eventsArray) {
                    CorrelatedEvent event;
                    if (eventJson.contains("start_timestamp")) event.startTimestamp = eventJson["start_timestamp"];
                    if (eventJson.contains("end_timestamp")) event.endTimestamp = eventJson["end_timestamp"];
                    if (eventJson.contains("event_type")) event.eventType = eventJson["event_type"];
                    if (eventJson.contains("initiating_user")) event.initiatingUser = eventJson["initiating_user"];
                    if (eventJson.contains("initiating_process")) event.initiatingProcess = eventJson["initiating_process"];
                    if (eventJson.contains("related_event_ids")) event.relatedEventIds = eventJson["related_event_ids"].get<std::vector<std::string>>();
                    if (eventJson.contains("description")) event.description = eventJson["description"];
                    if (eventJson.contains("severity")) event.severity = eventJson["severity"];
                    chain.events.push_back(event);
                }
            } catch (const std::exception& e) {
                std::cerr << "Error parsing events JSON: " << e.what() << std::endl;
            }
        }

        chain.timeline = safeColumnText(stmt, 3);
        chain.summary = safeColumnText(stmt, 4);
        chain.confidence = static_cast<float>(sqlite3_column_double(stmt, 5));
        chains.push_back(chain);
    }

    return chains;
}

// ============================================================================
// Timeline Event Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertTimelineEvent(const LinuxTimelineEvent& event) {
    const char* sql = LinuxAnalysisSQL::INSERT_TIMELINE_EVENT;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT64(stmt, 1, event.timestamp);
    BIND_TEXT(stmt, 2, event.sourceType);
    BIND_TEXT(stmt, 3, event.eventType);
    BIND_TEXT(stmt, 4, event.description);
    BIND_TEXT(stmt, 5, event.username);
    BIND_TEXT(stmt, 6, event.ipAddress);
    BIND_TEXT(stmt, 7, event.details);
    BIND_INT(stmt, 8, event.confidence);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertTimelineEvents(const std::vector<LinuxTimelineEvent>& events) {
    beginTransaction();
    for (const auto& event : events) {
        if (!insertTimelineEvent(event)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<LinuxTimelineEvent> LinuxAnalysisDatabase::queryTimelineEvents(const std::string& whereClause) {
    std::vector<LinuxTimelineEvent> events;
    std::string sql = "SELECT timestamp, source_type, event_type, description, username, ip_address, details, confidence FROM linux_timeline_events";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return events;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxTimelineEvent event;
        event.timestamp = sqlite3_column_int64(stmt, 0);
        event.sourceType = safeColumnText(stmt, 1);
        event.eventType = safeColumnText(stmt, 2);
        event.description = safeColumnText(stmt, 3);
        event.username = safeColumnText(stmt, 4);
        event.ipAddress = safeColumnText(stmt, 5);
        event.details = safeColumnText(stmt, 6);
        event.confidence = sqlite3_column_int(stmt, 7);
        events.push_back(event);
    }

    return events;
}

std::vector<LinuxTimelineEvent> LinuxAnalysisDatabase::queryTimelineEventsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<LinuxTimelineEvent> events;

    std::string sql = "SELECT timestamp, source_type, event_type, description, username, ip_address, details, confidence FROM linux_timeline_events";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return events;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return events;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxTimelineEvent event;
        event.timestamp = sqlite3_column_int64(stmt, 0);
        event.sourceType = safeColumnText(stmt, 1);
        event.eventType = safeColumnText(stmt, 2);
        event.description = safeColumnText(stmt, 3);
        event.username = safeColumnText(stmt, 4);
        event.ipAddress = safeColumnText(stmt, 5);
        event.details = safeColumnText(stmt, 6);
        event.confidence = sqlite3_column_int(stmt, 7);
        events.push_back(event);
    }

    return events;
}

// ============================================================================
// Timeline Gap Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertTimelineGap(const TimelineGap& gap) {
    const char* sql = LinuxAnalysisSQL::INSERT_TIMELINE_GAP;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT64(stmt, 1, gap.startTime);
    BIND_INT64(stmt, 2, gap.endTime);
    BIND_INT64(stmt, 3, gap.duration);
    BIND_TEXT(stmt, 4, gap.description);
    BIND_INT(stmt, 5, gap.isSuspicious ? 1 : 0);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertTimelineGaps(const std::vector<TimelineGap>& gaps) {
    beginTransaction();
    for (const auto& gap : gaps) {
        if (!insertTimelineGap(gap)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<TimelineGap> LinuxAnalysisDatabase::queryTimelineGaps(const std::string& whereClause) {
    std::vector<TimelineGap> gaps;
    std::string sql = "SELECT start_time, end_time, duration, description, is_suspicious FROM linux_timeline_gaps";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return gaps;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        TimelineGap gap;
        gap.startTime = sqlite3_column_int64(stmt, 0);
        gap.endTime = sqlite3_column_int64(stmt, 1);
        gap.duration = sqlite3_column_int64(stmt, 2);
        gap.description = safeColumnText(stmt, 3);
        gap.isSuspicious = sqlite3_column_int(stmt, 4) != 0;
        gaps.push_back(gap);
    }

    return gaps;
}

std::vector<TimelineGap> LinuxAnalysisDatabase::queryTimelineGapsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<TimelineGap> gaps;

    std::string sql = "SELECT start_time, end_time, duration, description, is_suspicious FROM linux_timeline_gaps";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return gaps;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return gaps;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        TimelineGap gap;
        gap.startTime = sqlite3_column_int64(stmt, 0);
        gap.endTime = sqlite3_column_int64(stmt, 1);
        gap.duration = sqlite3_column_int64(stmt, 2);
        gap.description = safeColumnText(stmt, 3);
        gap.isSuspicious = sqlite3_column_int(stmt, 4) != 0;
        gaps.push_back(gap);
    }

    return gaps;
}

// ============================================================================
// Anomaly Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertAnomaly(const Anomaly& anomaly) {
    const char* sql = LinuxAnalysisSQL::INSERT_ANOMALY;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, anomaly.anomalyType);
    BIND_TEXT(stmt, 2, anomaly.description);
    BIND_INT(stmt, 3, anomaly.severity);
    BIND_DOUBLE(stmt, 4, anomaly.confidence);
    BIND_TEXT(stmt, 5, vectorToJson(anomaly.evidenceIds));
    BIND_TEXT(stmt, 6, anomaly.mitigation);
    BIND_INT64(stmt, 7, anomaly.detectedAt);
    BIND_TEXT(stmt, 8, anomaly.anomalySubtype);
    BIND_TEXT(stmt, 9, anomaly.additionalData);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertAnomalies(const std::vector<Anomaly>& anomalies) {
    beginTransaction();
    for (const auto& anomaly : anomalies) {
        if (!insertAnomaly(anomaly)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<Anomaly> LinuxAnalysisDatabase::queryAnomalies(const std::string& whereClause) {
    std::vector<Anomaly> anomalies;
    std::string sql = "SELECT anomaly_type, description, severity, confidence, evidence_ids, mitigation, detected_at, anomaly_subtype, additional_data FROM linux_anomalies";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return anomalies;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        Anomaly anomaly;
        anomaly.anomalyType = safeColumnText(stmt, 0);
        anomaly.description = safeColumnText(stmt, 1);
        anomaly.severity = sqlite3_column_int(stmt, 2);
        anomaly.confidence = static_cast<float>(sqlite3_column_double(stmt, 3));
        anomaly.evidenceIds = jsonToVector<std::string>(safeColumnText(stmt, 4));
        anomaly.mitigation = safeColumnText(stmt, 5);
        anomaly.detectedAt = sqlite3_column_int64(stmt, 6);
        anomaly.anomalySubtype = safeColumnText(stmt, 7);
        anomaly.additionalData = safeColumnText(stmt, 8);
        anomalies.push_back(anomaly);
    }

    return anomalies;
}

std::vector<Anomaly> LinuxAnalysisDatabase::queryAnomaliesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<Anomaly> anomalies;

    std::string sql = "SELECT anomaly_type, description, severity, confidence, evidence_ids, mitigation, detected_at, anomaly_subtype, additional_data FROM linux_anomalies";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return anomalies;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return anomalies;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        Anomaly anomaly;
        anomaly.anomalyType = safeColumnText(stmt, 0);
        anomaly.description = safeColumnText(stmt, 1);
        anomaly.severity = sqlite3_column_int(stmt, 2);
        anomaly.confidence = static_cast<float>(sqlite3_column_double(stmt, 3));
        anomaly.evidenceIds = jsonToVector<std::string>(safeColumnText(stmt, 4));
        anomaly.mitigation = safeColumnText(stmt, 5);
        anomaly.detectedAt = sqlite3_column_int64(stmt, 6);
        anomaly.anomalySubtype = safeColumnText(stmt, 7);
        anomaly.additionalData = safeColumnText(stmt, 8);
        anomalies.push_back(anomaly);
    }

    return anomalies;
}
