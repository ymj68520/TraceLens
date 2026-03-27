#include "../EventCorrelationEngine.h"
#include "AuditLog/AuditLog.h"
#include <algorithm>
#include <sstream>

namespace EventCorrelationEngine {

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

} // namespace EventCorrelationEngine
