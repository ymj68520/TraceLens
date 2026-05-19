// LinuxPersistenceOperations.cpp
// Database operations for persistence mechanism entries

#include "LinuxAnalysisDatabase.h"
#include "LinuxQueryBuilder.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include "Analysis/PersistenceDetector.h"
#include <iostream>
#include <sstream>
#include <mutex>

using namespace LinuxAnalysis;
using forensics::linux::PersistenceDetector;

// ============================================================================
// Persistence Entry Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertPersistenceEntry(const PersistenceEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_persistence_entries (
            persistence_type, risk_level, file_path, entry_name,
            command, arguments, username, schedule,
            is_enabled, is_suspicious, suspicious_reason, raw_content,
            parser_name, parser_version, source_file, source_line
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare persistence entry insert");
        return false;
    }

    std::string typeStr = PersistenceDetector::typeToString(entry.type);
    std::string riskStr = PersistenceDetector::riskToString(entry.risk);

    int idx = 1;
    sqlite3_bind_text(stmt, idx++, typeStr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, riskStr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.filePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.entryName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.command.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.arguments.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.username.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.schedule.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.isEnabled ? 1 : 0);
    sqlite3_bind_int(stmt, idx++, entry.isSuspicious ? 1 : 0);
    sqlite3_bind_text(stmt, idx++, entry.suspiciousReason.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.rawContent.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, idx++, entry.provenance.sourceLine);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert persistence entry");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertPersistenceEntries(const std::vector<PersistenceEntry>& entries) {
    if (entries.empty()) return true;

    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertPersistenceEntry(entry)) {
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

std::vector<PersistenceEntry> LinuxAnalysisDatabase::queryPersistenceEntriesSafe(const LinuxAnalysis::QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<PersistenceEntry> entries;

    std::string sql = "SELECT persistence_type, risk_level, file_path, entry_name, "
                      "command, arguments, username, schedule, "
                      "is_enabled, is_suspicious, suspicious_reason, raw_content, "
                      "parser_name, parser_version, source_file, source_line "
                      "FROM linux_persistence_entries " + qb.buildWhereClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_QUERY_FAILED, "Failed to query persistence entries");
        return entries;
    }

    // Bind parameters
    qb.bindParameters(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        PersistenceEntry entry;

        std::string typeStr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        if (typeStr == "RC_LOCAL") entry.type = PersistenceType::RC_LOCAL;
        else if (typeStr == "INIT_D_SCRIPT") entry.type = PersistenceType::INIT_D_SCRIPT;
        else if (typeStr == "SHELL_PROFILE") entry.type = PersistenceType::SHELL_PROFILE;
        else if (typeStr == "AUTHORIZED_KEYS") entry.type = PersistenceType::AUTHORIZED_KEYS;
        else if (typeStr == "LD_SO_PRELOAD") entry.type = PersistenceType::LD_SO_PRELOAD;
        else if (typeStr == "SUDOERS") entry.type = PersistenceType::SUDOERS;
        else if (typeStr == "UDEV_RULE") entry.type = PersistenceType::UDEV_RULE;
        else if (typeStr == "POLKIT_RULE") entry.type = PersistenceType::POLKIT_RULE;
        else if (typeStr == "XINETD_SERVICE") entry.type = PersistenceType::XINETD_SERVICE;
        else if (typeStr == "SYSTEMD_TIMER") entry.type = PersistenceType::SYSTEMD_TIMER;
        else if (typeStr == "AT_JOB") entry.type = PersistenceType::AT_JOB;
        else if (typeStr == "CRON_JOB") entry.type = PersistenceType::CRON_JOB;
        else if (typeStr == "SYSTEMD_SERVICE") entry.type = PersistenceType::SYSTEMD_SERVICE;
        else entry.type = PersistenceType::UNKNOWN_PERSISTENCE;

        std::string riskStr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        if (riskStr == "LOW") entry.risk = PersistenceRisk::LOW;
        else if (riskStr == "MEDIUM") entry.risk = PersistenceRisk::MEDIUM;
        else if (riskStr == "HIGH") entry.risk = PersistenceRisk::HIGH;
        else if (riskStr == "CRITICAL") entry.risk = PersistenceRisk::CRITICAL;

        entry.filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        entry.entryName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        entry.command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        entry.arguments = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
        entry.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
        entry.schedule = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        entry.isEnabled = sqlite3_column_int(stmt, 8) != 0;
        entry.isSuspicious = sqlite3_column_int(stmt, 9) != 0;
        entry.suspiciousReason = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
        entry.rawContent = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
        entry.provenance.parserName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 12));
        entry.provenance.parserVersion = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 13));
        entry.provenance.sourceFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 14));
        entry.provenance.sourceLine = sqlite3_column_int64(stmt, 15);

        entries.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return entries;
}
