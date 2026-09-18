// LinuxHostInfoOperations.cpp
// Host identity database operations (linux_host_info).

#include "LinuxAnalysisDatabase.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include <iostream>

using namespace LinuxAnalysis;

// Helper macros for binding (mirrors the other Detail/*Operations.cpp files)
#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

// ============================================================================
// Host Information
// ============================================================================

bool LinuxAnalysisDatabase::insertHostInfo(const LinuxHostInfo& host) {
    const char* sql = LinuxAnalysisSQL::INSERT_HOST_INFO;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }

    BIND_TEXT(stmt, 1, host.hostname);
    BIND_TEXT(stmt, 2, host.distro);
    BIND_TEXT(stmt, 3, host.distroVersion);
    BIND_TEXT(stmt, 4, host.kernelVersion);
    BIND_TEXT(stmt, 5, host.architecture);
    BIND_TEXT(stmt, 6, host.timezone);
    BIND_TEXT(stmt, 7, host.machineId);
    BIND_INT(stmt, 8, host.kernelModulesInstalled);
    BIND_INT64(stmt, 9, host.collectedAt);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}
