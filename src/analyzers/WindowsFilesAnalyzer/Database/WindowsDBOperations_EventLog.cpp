// WindowsDBOperations_EventLog.cpp
// Event log insert/query operations

#include "WindowsAnalysisDatabase.h"

#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)



bool WindowsAnalysisDatabase::insertEventLogEntry(const EventLogEntry& entry) {
    const char* sql = "INSERT INTO event_logs (record_id, log_source, event_id, level, timestamp, source, message, computer_name, user_sid, channel) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_INT64(stmt, 1, entry.recordId);
    BIND_TEXT(stmt, 2, entry.logSource);
    BIND_INT(stmt, 3, entry.eventId);
    BIND_TEXT(stmt, 4, entry.level);
    BIND_INT64(stmt, 5, entry.timestamp);
    BIND_TEXT(stmt, 6, entry.source);
    BIND_TEXT(stmt, 7, entry.message);
    BIND_TEXT(stmt, 8, entry.computerName);
    BIND_TEXT(stmt, 9, entry.userSid);
    BIND_TEXT(stmt, 10, entry.channel);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

bool WindowsAnalysisDatabase::insertEventLogEntries(const std::vector<EventLogEntry>& entries) {
    if (entries.empty()) return true;

    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertEventLogEntry(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<EventLogEntry> WindowsAnalysisDatabase::queryEventLogs(const std::string& whereClause) const {
    std::vector<EventLogEntry> results;
    std::string sql = "SELECT record_id, log_source, event_id, level, timestamp, source, message, computer_name, user_sid, channel FROM event_logs";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        EventLogEntry entry;
        entry.recordId = sqlite3_column_int64(stmt, 0);
        entry.logSource = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        entry.eventId = sqlite3_column_int(stmt, 2);
        entry.level = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        entry.timestamp = sqlite3_column_int64(stmt, 4);
        entry.source = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5)) ?: "";
        entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6)) ?: "";
        entry.computerName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7)) ?: "";
        entry.userSid = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8)) ?: "";
        entry.channel = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9)) ?: "";
        results.push_back(entry);
    }
    sqlite3_finalize(stmt);
    return results;
}

