// LinuxJournalOperations.cpp
// Database operations for systemd-journald journal entries

#include "LinuxDatabaseHelpers.h"
#include <sstream>

using forensics::linux::JournalAnomalyType;

// ============================================================================
// Journal Entry Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertJournalEntry(const JournalEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_journal_entries (
            realtime_timestamp, monotonic_timestamp, boot_id,
            systemd_unit, user_unit, pid, uid, gid,
            comm, exe, cmdline, transport,
            message, message_id, syslog_identifier, priority, cursor_id,
            parser_name, parser_version, source_file, source_offset,
            source_inode, source_hash, parse_error, raw_record, confidence,
            llm_summary, llm_description, llm_keywords, llm_analyzed_at, llm_model_used
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare journal insert");
        return false;
    }

    int idx = 1;
    sqlite3_bind_int64(stmt, idx++, entry.realtimeTimestamp);
    sqlite3_bind_int64(stmt, idx++, entry.monotonicTimestamp);
    sqlite3_bind_text(stmt, idx++, entry.bootId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.systemdUnit.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.userUnit.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.pid);
    sqlite3_bind_int(stmt, idx++, entry.uid);
    sqlite3_bind_int(stmt, idx++, entry.gid);
    sqlite3_bind_text(stmt, idx++, entry.comm.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.exe.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.cmdline.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.transport.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.message.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.messageId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.syslogIdentifier.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.priority.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.cursor.c_str(), -1, SQLITE_TRANSIENT);

    // Evidence provenance
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, idx++, entry.provenance.sourceOffset);
    sqlite3_bind_int64(stmt, idx++, entry.provenance.sourceInode);
    sqlite3_bind_text(stmt, idx++, entry.provenance.sourceHash.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parseError.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.rawRecord.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.provenance.confidence);

    // LLM fields (initially null)
    sqlite3_bind_null(stmt, idx++);
    sqlite3_bind_null(stmt, idx++);
    sqlite3_bind_null(stmt, idx++);
    sqlite3_bind_null(stmt, idx++);
    sqlite3_bind_null(stmt, idx++);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert journal entry");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertJournalEntries(const std::vector<JournalEntry>& entries) {
    if (entries.empty()) return true;

    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertJournalEntry(entry)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) {
        commitTransaction();
    } else {
        rollbackTransaction();
    }

    return allSuccess;
}

std::vector<JournalEntry> LinuxAnalysisDatabase::queryJournalEntriesSafe(
    const LinuxAnalysis::QueryBuilder& qb) {

    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<JournalEntry> results;

    std::string sql = "SELECT id, realtime_timestamp, monotonic_timestamp, boot_id, "
                      "systemd_unit, user_unit, pid, uid, gid, "
                      "comm, exe, cmdline, transport, "
                      "message, message_id, syslog_identifier, priority, cursor_id, "
                      "parser_name, parser_version, source_file, source_offset, "
                      "source_inode, source_hash, parse_error, raw_record, confidence "
                      "FROM linux_journal_entries";
    std::string whereClause = qb.buildWhereClause();
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_QUERY_FAILED, "Failed to prepare journal query");
        return results;
    }

    qb.bindParameters(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        JournalEntry entry;
        int idx = 0;

        // Skip id
        idx++;
        entry.realtimeTimestamp = sqlite3_column_int64(stmt, idx++);
        entry.monotonicTimestamp = sqlite3_column_int64(stmt, idx++);
        entry.bootId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.systemdUnit = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.userUnit = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.pid = sqlite3_column_int(stmt, idx++);
        entry.uid = sqlite3_column_int(stmt, idx++);
        entry.gid = sqlite3_column_int(stmt, idx++);
        entry.comm = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.exe = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.cmdline = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.transport = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.messageId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.syslogIdentifier = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.priority = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.cursor = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));

        // Provenance
        entry.provenance.parserName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.provenance.parserVersion = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.provenance.sourceFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.provenance.sourceOffset = sqlite3_column_int64(stmt, idx++);
        entry.provenance.sourceInode = sqlite3_column_int64(stmt, idx++);
        entry.provenance.sourceHash = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.provenance.parseError = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.provenance.rawRecord = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.provenance.confidence = sqlite3_column_int(stmt, idx++);

        results.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return results;
}

std::vector<JournalEntry> LinuxAnalysisDatabase::queryJournalEntries(
    const std::string& whereClause) {
    // Deprecated: use queryJournalEntriesSafe with QueryBuilder
    LinuxAnalysis::QueryBuilder qb;
    return queryJournalEntriesSafe(qb);
}

// ============================================================================
// Boot Session Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertBootSession(const BootSession& session) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT OR REPLACE INTO linux_boot_sessions (
            boot_id, start_time, end_time, entry_count
        ) VALUES (?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare boot session insert");
        return false;
    }

    sqlite3_bind_text(stmt, 1, session.bootId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 2, session.startTime);
    sqlite3_bind_int64(stmt, 3, session.endTime);
    sqlite3_bind_int(stmt, 4, session.entryCount);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert boot session");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertBootSessions(const std::vector<BootSession>& sessions) {
    if (sessions.empty()) return true;

    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& session : sessions) {
        if (!insertBootSession(session)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) {
        commitTransaction();
    } else {
        rollbackTransaction();
    }

    return allSuccess;
}

std::vector<BootSession> LinuxAnalysisDatabase::queryBootSessionsSafe(
    const LinuxAnalysis::QueryBuilder& qb) {

    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<BootSession> results;

    std::string sql = "SELECT boot_id, start_time, end_time, entry_count "
                      "FROM linux_boot_sessions";
    std::string whereClause = qb.buildWhereClause();
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_QUERY_FAILED, "Failed to prepare boot session query");
        return results;
    }

    qb.bindParameters(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BootSession session;
        int idx = 0;

        session.bootId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        session.startTime = sqlite3_column_int64(stmt, idx++);
        session.endTime = sqlite3_column_int64(stmt, idx++);
        session.entryCount = sqlite3_column_int(stmt, idx++);

        results.push_back(session);
    }

    sqlite3_finalize(stmt);
    return results;
}

std::vector<BootSession> LinuxAnalysisDatabase::queryBootSessions(
    const std::string& whereClause) {
    // Deprecated: use queryBootSessionsSafe with QueryBuilder
    LinuxAnalysis::QueryBuilder qb;
    return queryBootSessionsSafe(qb);
}

// ============================================================================
// Journal Anomaly Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertJournalAnomaly(const JournalAnomaly& anomaly) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_journal_anomalies (
            anomaly_type, description, timestamp, severity,
            parser_name, parser_version, source_file
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare journal anomaly insert");
        return false;
    }

    // Convert anomaly type to string
    std::string typeStr;
    switch (anomaly.type) {
        case JournalAnomalyType::VACUUM_DETECTED: typeStr = "VACUUM_DETECTED"; break;
        case JournalAnomalyType::TRUNCATION_DETECTED: typeStr = "TRUNCATION_DETECTED"; break;
        case JournalAnomalyType::TIME_JUMP_DETECTED: typeStr = "TIME_JUMP_DETECTED"; break;
        case JournalAnomalyType::MISSING_BOOT: typeStr = "MISSING_BOOT"; break;
        case JournalAnomalyType::CORRUPTED_ENTRY: typeStr = "CORRUPTED_ENTRY"; break;
        case JournalAnomalyType::GAP_DETECTED: typeStr = "GAP_DETECTED"; break;
        default: typeStr = "UNKNOWN"; break;
    }

    sqlite3_bind_text(stmt, 1, typeStr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, anomaly.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 3, anomaly.timestamp);
    sqlite3_bind_int(stmt, 4, anomaly.severity);

    // Provenance (from journal parser)
    sqlite3_bind_text(stmt, 5, "JournalParser", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 6, "1.0.0", -1, SQLITE_STATIC);
    sqlite3_bind_null(stmt, 7);  // source_file will be set by caller if needed

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert journal anomaly");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertJournalAnomalies(const std::vector<JournalAnomaly>& anomalies) {
    if (anomalies.empty()) return true;

    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& anomaly : anomalies) {
        if (!insertJournalAnomaly(anomaly)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) {
        commitTransaction();
    } else {
        rollbackTransaction();
    }

    return allSuccess;
}

std::vector<JournalAnomaly> LinuxAnalysisDatabase::queryJournalAnomaliesSafe(
    const LinuxAnalysis::QueryBuilder& qb) {

    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<JournalAnomaly> results;

    std::string sql = "SELECT anomaly_type, description, timestamp, severity "
                      "FROM linux_journal_anomalies";
    std::string whereClause = qb.buildWhereClause();
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_QUERY_FAILED, "Failed to prepare journal anomaly query");
        return results;
    }

    qb.bindParameters(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        JournalAnomaly anomaly;
        int idx = 0;

        std::string typeStr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        anomaly.description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        anomaly.timestamp = sqlite3_column_int64(stmt, idx++);
        anomaly.severity = sqlite3_column_int(stmt, idx++);

        // Convert string to enum
        if (typeStr == "VACUUM_DETECTED") anomaly.type = JournalAnomalyType::VACUUM_DETECTED;
        else if (typeStr == "TRUNCATION_DETECTED") anomaly.type = JournalAnomalyType::TRUNCATION_DETECTED;
        else if (typeStr == "TIME_JUMP_DETECTED") anomaly.type = JournalAnomalyType::TIME_JUMP_DETECTED;
        else if (typeStr == "MISSING_BOOT") anomaly.type = JournalAnomalyType::MISSING_BOOT;
        else if (typeStr == "CORRUPTED_ENTRY") anomaly.type = JournalAnomalyType::CORRUPTED_ENTRY;
        else if (typeStr == "GAP_DETECTED") anomaly.type = JournalAnomalyType::GAP_DETECTED;

        results.push_back(anomaly);
    }

    sqlite3_finalize(stmt);
    return results;
}
