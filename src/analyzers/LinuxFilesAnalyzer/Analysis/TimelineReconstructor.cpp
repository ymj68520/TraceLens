// TimelineReconstructor.cpp
// Implementation of timeline reconstructor

#include "TimelineReconstructor.h"
#include "Database/LinuxAnalysisDatabase.h"
#include "AuditLog/AuditLog.h"
#include <sqlite3.h>
#include <algorithm>

namespace LinuxAnalysis {

TimelineReconstructor::TimelineReconstructor(const std::string& dbPath)
    : dbPath_(dbPath) {
}

Timeline TimelineReconstructor::buildTimeline() {
    Timeline timeline;

    // Merge events from all sources
    timeline.events = mergeEvents();

    // Identify gaps
    timeline.gaps = identifyGaps(timeline.events);

    AuditLog::instance().log("SUCCESS", "TIMELINE_RECONSTRUCTED",
        "Timeline has " + std::to_string(timeline.events.size()) +
        " events and " + std::to_string(timeline.gaps.size()) + " gaps");

    return timeline;
}

std::vector<LinuxTimelineEvent> TimelineReconstructor::mergeEvents() {
    std::vector<LinuxTimelineEvent> events;

    sqlite3* db = nullptr;
    if (sqlite3_open_v2(dbPath_.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        AuditLog::instance().log("ERROR", "TIMELINE_DB_OPEN_FAILED",
            "Failed to open database: " + dbPath_);
        return events;
    }

    // Collect events from different sources
    // System logs
    const char* logQuery = "SELECT timestamp, 'system', SUBSTR(message, 1, 100), "
                           "NULL, NULL, NULL FROM linux_system_logs ORDER BY timestamp;";
    addEventsFromQuery(db, logQuery, events);

    // Authentication data
    const char* authQuery = "SELECT timestamp, 'auth', 'Login: ' || username, "
                           "username, NULL, NULL FROM linux_auth_data ORDER BY timestamp;";
    addEventsFromQuery(db, authQuery, events);

    // Shell history
    const char* shellQuery = "SELECT timestamp, 'shell', command, "
                           "username, NULL, NULL FROM linux_shell_history ORDER BY timestamp;";
    addEventsFromQuery(db, shellQuery, events);

    // Network connections (if available)
    const char* netQuery = "SELECT timestamp, 'network', 'Connection from ' || remote_addr, "
                          "NULL, remote_addr, NULL FROM linux_network_connections ORDER BY timestamp;";
    addEventsFromQuery(db, netQuery, events);

    sqlite3_close(db);

    // Sort by timestamp
    std::sort(events.begin(), events.end(),
        [](const LinuxTimelineEvent& a, const LinuxTimelineEvent& b) {
            return a.timestamp < b.timestamp;
        });

    // Remove duplicates (same timestamp and description)
    events.erase(
        std::unique(events.begin(), events.end(),
            [](const LinuxTimelineEvent& a, const LinuxTimelineEvent& b) {
                return a.timestamp == b.timestamp && a.description == b.description;
            }),
        events.end());

    return events;
}

std::vector<TimelineGap> TimelineReconstructor::identifyGaps(
    const std::vector<LinuxTimelineEvent>& events) {

    std::vector<TimelineGap> gaps;

    if (events.size() < 2) {
        return gaps;
    }

    // Analyze time gaps between consecutive events
    for (size_t i = 1; i < events.size(); ++i) {
        int64_t gapDuration = events[i].timestamp - events[i-1].timestamp;

        // Look for gaps longer than 1 hour (3600 seconds)
        if (gapDuration > 3600 && isSuspiciousGap(gapDuration, i)) {
            TimelineGap gap;
            gap.startTime = events[i-1].timestamp;
            gap.endTime = events[i].timestamp;
            gap.duration = gapDuration;
            gap.description = "Gap of " + std::to_string(gapDuration / 60) + " minutes";
            gap.isSuspicious = true;

            gaps.push_back(gap);
        }
    }

    return gaps;
}

LinuxTimelineEvent TimelineReconstructor::createTimelineEvent(
    const std::string& source,
    const std::string& type,
    const std::string& description,
    int64_t timestamp) {

    LinuxTimelineEvent event;
    event.timestamp = timestamp;
    event.sourceType = source;
    event.eventType = type;
    event.description = description;
    event.confidence = 1;

    return event;
}

bool TimelineReconstructor::isSuspiciousGap(int64_t gapDuration, int64_t eventCount) {
    // Gap is suspicious if:
    // - Longer than 1 hour
    // - Occurs during active period (based on surrounding event count)
    // - Duration is unusually long (more than 24 hours)

    if (gapDuration > 86400) { // More than 24 hours
        return true;
    }

    if (gapDuration > 3600 && eventCount > 10) {
        // Gap during active period
        return true;
    }

    return false;
}

// Helper function to add events from SQL query
void TimelineReconstructor::addEventsFromQuery(
    sqlite3* db,
    const char* query,
    std::vector<LinuxTimelineEvent>& events) {

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        return;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxTimelineEvent event;
        event.timestamp = sqlite3_column_int64(stmt, 0);

        const char* source = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        const char* type = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        const char* desc = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        const char* user = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        const char* ip = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));

        if (source) event.sourceType = source;
        if (type) event.eventType = type;
        if (desc) event.description = desc;
        if (user) event.username = user;
        if (ip) event.ipAddress = ip;

        event.confidence = 1;

        events.push_back(event);
    }

    sqlite3_finalize(stmt);
}

bool Timeline::hasUnexplainedGaps() const {
    return std::any_of(gaps.begin(), gaps.end(),
        [](const TimelineGap& gap) {
            return gap.isSuspicious;
        });
}

} // namespace LinuxAnalysis
