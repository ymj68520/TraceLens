// WindowsDBOperations_Lnk.cpp
// LNK file and Jump list insert/query operations

#include "WindowsAnalysisDatabase.h"

#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)



bool WindowsAnalysisDatabase::insertLnkFileInfo(const LnkFileInfo& info) {
    const char* sql = "INSERT INTO lnk_files (lnk_path, target_path, working_directory, arguments, icon_location, creation_time, modification_time, access_time, target_size, drive_type, volume_serial, netbios_name, relative_path, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, info.lnkPath);
    BIND_TEXT(stmt, 2, info.targetPath);
    BIND_TEXT(stmt, 3, info.workingDirectory);
    BIND_TEXT(stmt, 4, info.arguments);
    BIND_TEXT(stmt, 5, info.iconLocation);
    BIND_INT64(stmt, 6, info.creationTime);
    BIND_INT64(stmt, 7, info.modificationTime);
    BIND_INT64(stmt, 8, info.accessTime);
    BIND_INT64(stmt, 9, info.targetSize);
    BIND_TEXT(stmt, 10, info.driveType);
    BIND_TEXT(stmt, 11, info.volumeSerial);
    BIND_TEXT(stmt, 12, info.netBiosName);
    BIND_TEXT(stmt, 13, info.relativePath);
    BIND_TEXT(stmt, 14, info.description);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

std::vector<LnkFileInfo> WindowsAnalysisDatabase::queryLnkFiles(const std::string& whereClause) {
    std::vector<LnkFileInfo> results;
    std::string sql = "SELECT lnk_path, target_path, working_directory, arguments, icon_location, creation_time, modification_time, access_time, target_size, drive_type, volume_serial, netbios_name, relative_path, description FROM lnk_files";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LnkFileInfo info;
        info.lnkPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        info.targetPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        info.workingDirectory = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        info.arguments = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        info.iconLocation = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4)) ?: "";
        info.creationTime = sqlite3_column_int64(stmt, 5);
        info.modificationTime = sqlite3_column_int64(stmt, 6);
        info.accessTime = sqlite3_column_int64(stmt, 7);
        info.targetSize = sqlite3_column_int64(stmt, 8);
        info.driveType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9)) ?: "";
        info.volumeSerial = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10)) ?: "";
        info.netBiosName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11)) ?: "";
        info.relativePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 12)) ?: "";
        info.description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 13)) ?: "";
        results.push_back(info);
    }
    sqlite3_finalize(stmt);
    return results;
}

bool WindowsAnalysisDatabase::insertJumpListEntry(const JumpListEntry& entry) {
    const char* sql = "INSERT INTO jump_list_entries (app_id, entry_path, entry_name, access_time, creation_time, access_count, is_pinned) VALUES (?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, entry.appId);
    BIND_TEXT(stmt, 2, entry.entryPath);
    BIND_TEXT(stmt, 3, entry.entryName);
    BIND_INT64(stmt, 4, entry.accessTime);
    BIND_INT64(stmt, 5, entry.creationTime);
    BIND_INT(stmt, 6, entry.accessCount);
    BIND_INT(stmt, 7, entry.isPinned ? 1 : 0);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

std::vector<JumpListEntry> WindowsAnalysisDatabase::queryJumpListEntries(const std::string& whereClause) {
    std::vector<JumpListEntry> results;
    std::string sql = "SELECT app_id, entry_path, entry_name, access_time, creation_time, access_count, is_pinned FROM jump_list_entries";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        JumpListEntry entry;
        entry.appId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        entry.entryPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        entry.entryName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        entry.accessTime = sqlite3_column_int64(stmt, 3);
        entry.creationTime = sqlite3_column_int64(stmt, 4);
        entry.accessCount = sqlite3_column_int(stmt, 5);
        entry.isPinned = sqlite3_column_int(stmt, 6) != 0;
        results.push_back(entry);
    }
    sqlite3_finalize(stmt);
    return results;
}

