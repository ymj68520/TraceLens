#include "../EventCorrelationEngine.h"
#include <algorithm>

namespace EventCorrelationEngine {

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
