// LinuxTamperingOperations.cpp
// Database operations for log tampering findings

#include "LinuxAnalysisDatabase.h"
#include "LinuxQueryBuilder.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include "Analysis/LogTamperingDetector.h"
#include <iostream>
#include <sstream>
#include <mutex>

using namespace LinuxAnalysis;

// ============================================================================
// Tampering Finding Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertTamperingFinding(const forensics::linux::TamperingFinding& finding) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_tampering_findings (
            tampering_type, severity, description, log_source,
            timestamp_start, timestamp_end, evidence, related_files,
            parser_name, parser_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare tampering finding insert");
        return false;
    }

    // Convert type to string
    std::string typeStr;
    switch (finding.type) {
        case forensics::linux::TamperingType::LOG_CLEARED: typeStr = "LOG_CLEARED"; break;
        case forensics::linux::TamperingType::ROTATION_GAP: typeStr = "ROTATION_GAP"; break;
        case forensics::linux::TamperingType::TIME_REVERSAL: typeStr = "TIME_REVERSAL"; break;
        case forensics::linux::TamperingType::TIME_WINDOW_GAP: typeStr = "TIME_WINDOW_GAP"; break;
        case forensics::linux::TamperingType::CROSS_LOG_INCONSISTENCY: typeStr = "CROSS_LOG_INCONSISTENCY"; break;
        case forensics::linux::TamperingType::JOURNAL_MISSING: typeStr = "JOURNAL_MISSING"; break;
        case forensics::linux::TamperingType::AUDITD_INTERRUPTED: typeStr = "AUDITD_INTERRUPTED"; break;
        case forensics::linux::TamperingType::DUPLICATE_TIMESTAMPS: typeStr = "DUPLICATE_TIMESTAMPS"; break;
        case forensics::linux::TamperingType::TIMESTAMP_ANOMALY: typeStr = "TIMESTAMP_ANOMALY"; break;
        case forensics::linux::TamperingType::LOG_PATTERN_BREAK: typeStr = "LOG_PATTERN_BREAK"; break;
        default: typeStr = "UNKNOWN"; break;
    }

    int idx = 1;
    sqlite3_bind_text(stmt, idx++, typeStr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, static_cast<int>(finding.severity));
    sqlite3_bind_text(stmt, idx++, finding.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.logSource.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, idx++, finding.timestampStart);
    sqlite3_bind_int64(stmt, idx++, finding.timestampEnd);
    sqlite3_bind_text(stmt, idx++, finding.evidence.c_str(), -1, SQLITE_TRANSIENT);

    // Serialize related files
    std::string relatedFilesStr;
    for (size_t i = 0; i < finding.relatedFiles.size(); i++) {
        if (i > 0) relatedFilesStr += ",";
        relatedFilesStr += finding.relatedFiles[i];
    }
    sqlite3_bind_text(stmt, idx++, relatedFilesStr.c_str(), -1, SQLITE_TRANSIENT);

    sqlite3_bind_text(stmt, idx++, finding.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(LinuxAnalysis::ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert tampering finding");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertTamperingFindings(const std::vector<forensics::linux::TamperingFinding>& findings) {
    if (findings.empty()) return true;

    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& finding : findings) {
        if (!insertTamperingFinding(finding)) {
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
