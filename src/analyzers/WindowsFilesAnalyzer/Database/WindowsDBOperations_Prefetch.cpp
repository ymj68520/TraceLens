// WindowsDBOperations_Prefetch.cpp
// Prefetch file insert/query operations

#include "WindowsAnalysisDatabase.h"
#include <sstream>
#include <nlohmann/json.hpp>

#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)



bool WindowsAnalysisDatabase::insertPrefetchInfo(const PrefetchInfo& info) {
    const char* sql = "INSERT INTO prefetch_files (file_path, executable_name, executable_path, prefetch_hash, run_count, last_run_time, creation_time, referenced_files, referenced_directories, parse_status, parse_error, parser_version, all_run_times, raw_run_times) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, info.filePath);
    BIND_TEXT(stmt, 2, info.executableName);
    BIND_TEXT(stmt, 3, info.executablePath);
    BIND_TEXT(stmt, 4, info.prefetchHash);
    if (info.runCount) sqlite3_bind_int64(stmt, 5, *info.runCount); else sqlite3_bind_null(stmt, 5);
    if (info.lastRunTime) sqlite3_bind_int64(stmt, 6, *info.lastRunTime); else sqlite3_bind_null(stmt, 6);
    if (info.creationTime) sqlite3_bind_int64(stmt, 7, *info.creationTime); else sqlite3_bind_null(stmt, 7);

    // Convert vectors to comma-separated strings
    std::string refFilesStr, refDirsStr;
    for (size_t i = 0; i < info.referencedFiles.size(); i++) {
        if (i > 0) refFilesStr += ",";
        refFilesStr += info.referencedFiles[i];
    }
    for (size_t i = 0; i < info.referencedDirectories.size(); i++) {
        if (i > 0) refDirsStr += ",";
        refDirsStr += info.referencedDirectories[i];
    }

    BIND_TEXT(stmt, 8, refFilesStr);
    BIND_TEXT(stmt, 9, refDirsStr);

    BIND_TEXT(stmt, 10, info.parseStatus);
    BIND_TEXT(stmt, 11, info.parseError);
    BIND_TEXT(stmt, 12, info.parserVersion);
    const auto times=nlohmann::json(info.allRunTimes).dump();
    const auto raw=nlohmann::json(info.rawRunTimes).dump();
    BIND_TEXT(stmt, 13, times);
    BIND_TEXT(stmt, 14, raw);
    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

std::vector<PrefetchInfo> WindowsAnalysisDatabase::queryPrefetchFiles(const std::string& whereClause) const {
    std::vector<PrefetchInfo> results;
    std::string sql = "SELECT file_path, executable_name, executable_path, prefetch_hash, run_count, last_run_time, creation_time, referenced_files, referenced_directories, parse_status, parse_error, parser_version, all_run_times, raw_run_times FROM prefetch_files";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        PrefetchInfo info;
        info.filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        info.executableName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        info.executablePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        info.prefetchHash = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        if (sqlite3_column_type(stmt, 4)!=SQLITE_NULL) info.runCount = sqlite3_column_int64(stmt, 4);
        if (sqlite3_column_type(stmt, 5)!=SQLITE_NULL) info.lastRunTime = sqlite3_column_int64(stmt, 5);
        if (sqlite3_column_type(stmt, 6)!=SQLITE_NULL) info.creationTime = sqlite3_column_int64(stmt, 6);
        // Parse comma-separated referenced files/directories
        std::string refFilesStr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7)) ?: "";
        std::string refDirsStr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8)) ?: "";
        // Split by comma (simplified parsing)
        if (!refFilesStr.empty()) {
            std::istringstream ss(refFilesStr);
            std::string item;
            while (std::getline(ss, item, ',')) {
                if (!item.empty()) info.referencedFiles.push_back(item);
            }
        }
        if (!refDirsStr.empty()) {
            std::istringstream ss(refDirsStr);
            std::string item;
            while (std::getline(ss, item, ',')) {
                if (!item.empty()) info.referencedDirectories.push_back(item);
            }
        }
        info.parseStatus = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9)) ?: "legacy_unverified";
        info.parseError = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10)) ?: "";
        info.parserVersion = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11)) ?: "";
        try {
            info.allRunTimes = nlohmann::json::parse(reinterpret_cast<const char*>(sqlite3_column_text(stmt,12)) ?: "[]").get<std::vector<int64_t>>();
            info.rawRunTimes = nlohmann::json::parse(reinterpret_cast<const char*>(sqlite3_column_text(stmt,13)) ?: "[]").get<std::vector<uint64_t>>();
        } catch (const nlohmann::json::exception&) {
            info.parseStatus="partial"; info.parseError="STORED_PREFETCH_TIMES_INVALID";
        }
        results.push_back(info);
    }
    sqlite3_finalize(stmt);
    return results;
}

