// WindowsDBOperations_System.cpp
// MFT entries, Windows Services, Scheduled Tasks, Amcache, SRUM insert/query operations

#include "WindowsAnalysisDatabase.h"

#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)



// MFT entry operations
bool WindowsAnalysisDatabase::insertMftEntry(const MftEntryInfo& entry) {
    const char* sql = "INSERT INTO mft_entries (entry_number, file_name, file_path, parent_entry, logical_size, physical_size, creation_time, modification_time, access_time, mft_modification_time, fn_creation_time, fn_modification_time, is_directory, is_deleted, has_ads, permissions) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_INT64(stmt, 1, entry.entryNumber);
    BIND_TEXT(stmt, 2, entry.fileName);
    BIND_TEXT(stmt, 3, entry.filePath);
    BIND_INT64(stmt, 4, entry.parentEntry);
    BIND_INT64(stmt, 5, entry.logicalSize);
    BIND_INT64(stmt, 6, entry.physicalSize);
    BIND_INT64(stmt, 7, entry.creationTime);
    BIND_INT64(stmt, 8, entry.modificationTime);
    BIND_INT64(stmt, 9, entry.accessTime);
    BIND_INT64(stmt, 10, entry.mftModificationTime);
    BIND_INT64(stmt, 11, entry.fnCreationTime);
    BIND_INT64(stmt, 12, entry.fnModificationTime);
    BIND_INT(stmt, 13, entry.isDirectory ? 1 : 0);
    BIND_INT(stmt, 14, entry.isDeleted ? 1 : 0);
    BIND_INT(stmt, 15, entry.hasAds ? 1 : 0);
    BIND_TEXT(stmt, 16, entry.permissions);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

std::vector<MftEntryInfo> WindowsAnalysisDatabase::queryMftEntries(const std::string& whereClause) {
    std::vector<MftEntryInfo> results;
    std::string sql = "SELECT entry_number, file_name, file_path, parent_entry, logical_size, physical_size, creation_time, modification_time, access_time, mft_modification_time, fn_creation_time, fn_modification_time, is_directory, is_deleted, has_ads, permissions FROM mft_entries";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        MftEntryInfo entry;
        entry.entryNumber = sqlite3_column_int64(stmt, 0);
        entry.fileName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        entry.filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        entry.parentEntry = sqlite3_column_int64(stmt, 3);
        entry.logicalSize = sqlite3_column_int64(stmt, 4);
        entry.physicalSize = sqlite3_column_int64(stmt, 5);
        entry.creationTime = sqlite3_column_int64(stmt, 6);
        entry.modificationTime = sqlite3_column_int64(stmt, 7);
        entry.accessTime = sqlite3_column_int64(stmt, 8);
        entry.mftModificationTime = sqlite3_column_int64(stmt, 9);
        entry.fnCreationTime = sqlite3_column_int64(stmt, 10);
        entry.fnModificationTime = sqlite3_column_int64(stmt, 11);
        entry.isDirectory = sqlite3_column_int(stmt, 12) != 0;
        entry.isDeleted = sqlite3_column_int(stmt, 13) != 0;
        entry.hasAds = sqlite3_column_int(stmt, 14) != 0;
        entry.permissions = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 15)) ?: "";
        results.push_back(entry);
    }
    sqlite3_finalize(stmt);
    return results;
}

// Windows service operations
bool WindowsAnalysisDatabase::insertWindowsService(const WindowsServiceInfo& service) {
    const char* sql = "INSERT INTO windows_services (service_name, display_name, image_path, start_type, service_type, account_name, description, is_running) VALUES (?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, service.serviceName);
    BIND_TEXT(stmt, 2, service.displayName);
    BIND_TEXT(stmt, 3, service.imagePath);
    BIND_TEXT(stmt, 4, service.startType);
    BIND_TEXT(stmt, 5, service.serviceType);
    BIND_TEXT(stmt, 6, service.accountName);
    BIND_TEXT(stmt, 7, service.description);
    BIND_INT(stmt, 8, service.isRunning ? 1 : 0);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

std::vector<WindowsServiceInfo> WindowsAnalysisDatabase::queryWindowsServices(const std::string& whereClause) {
    std::vector<WindowsServiceInfo> results;
    std::string sql = "SELECT service_name, display_name, image_path, start_type, service_type, account_name, description, is_running FROM windows_services";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        WindowsServiceInfo service;
        service.serviceName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        service.displayName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        service.imagePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        service.startType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        service.serviceType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4)) ?: "";
        service.accountName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5)) ?: "";
        service.description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6)) ?: "";
        service.isRunning = sqlite3_column_int(stmt, 7) != 0;
        results.push_back(service);
    }
    sqlite3_finalize(stmt);
    return results;
}

// Scheduled task operations
bool WindowsAnalysisDatabase::insertScheduledTask(const ScheduledTaskInfo& task) {
    const char* sql = "INSERT INTO scheduled_tasks (task_name, task_path, author, description, action_type, action_path, arguments, trigger_type, last_run_time, next_run_time, status, run_as) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, task.taskName);
    BIND_TEXT(stmt, 2, task.taskPath);
    BIND_TEXT(stmt, 3, task.author);
    BIND_TEXT(stmt, 4, task.description);
    BIND_TEXT(stmt, 5, task.actionType);
    BIND_TEXT(stmt, 6, task.actionPath);
    BIND_TEXT(stmt, 7, task.arguments);
    BIND_TEXT(stmt, 8, task.triggerType);
    BIND_INT64(stmt, 9, task.lastRunTime);
    BIND_INT64(stmt, 10, task.nextRunTime);
    BIND_TEXT(stmt, 11, task.status);
    BIND_TEXT(stmt, 12, task.runAs);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

std::vector<ScheduledTaskInfo> WindowsAnalysisDatabase::queryScheduledTasks(const std::string& whereClause) {
    std::vector<ScheduledTaskInfo> results;
    std::string sql = "SELECT task_name, task_path, author, description, action_type, action_path, arguments, trigger_type, last_run_time, next_run_time, status, run_as FROM scheduled_tasks";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        ScheduledTaskInfo task;
        task.taskName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        task.taskPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        task.author = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        task.description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        task.actionType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4)) ?: "";
        task.actionPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5)) ?: "";
        task.arguments = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6)) ?: "";
        task.triggerType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7)) ?: "";
        task.lastRunTime = sqlite3_column_int64(stmt, 8);
        task.nextRunTime = sqlite3_column_int64(stmt, 9);
        task.status = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10)) ?: "";
        task.runAs = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11)) ?: "";
        results.push_back(task);
    }
    sqlite3_finalize(stmt);
    return results;
}

// Amcache entry operations
bool WindowsAnalysisDatabase::insertAmcacheEntry(const AmcacheEntry& entry) {
    const char* sql = "INSERT INTO amcache_entries (file_path, file_hash, file_name, company_name, product_name, product_version, file_description, file_size, link_time, last_modified, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, entry.filePath);
    BIND_TEXT(stmt, 2, entry.fileHash);
    BIND_TEXT(stmt, 3, entry.fileName);
    BIND_TEXT(stmt, 4, entry.companyName);
    BIND_TEXT(stmt, 5, entry.productName);
    BIND_TEXT(stmt, 6, entry.productVersion);
    BIND_TEXT(stmt, 7, entry.fileDescription);
    BIND_INT64(stmt, 8, entry.fileSize);
    BIND_INT64(stmt, 9, entry.linkTime);
    BIND_INT64(stmt, 10, entry.lastModified);
    BIND_TEXT(stmt, 11, entry.language);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

std::vector<AmcacheEntry> WindowsAnalysisDatabase::queryAmcacheEntries(const std::string& whereClause) {
    std::vector<AmcacheEntry> results;
    std::string sql = "SELECT file_path, file_hash, file_name, company_name, product_name, product_version, file_description, file_size, link_time, last_modified, language FROM amcache_entries";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AmcacheEntry entry;
        entry.filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        entry.fileHash = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        entry.fileName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        entry.companyName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        entry.productName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4)) ?: "";
        entry.productVersion = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5)) ?: "";
        entry.fileDescription = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6)) ?: "";
        entry.fileSize = sqlite3_column_int64(stmt, 7);
        entry.linkTime = sqlite3_column_int64(stmt, 8);
        entry.lastModified = sqlite3_column_int64(stmt, 9);
        entry.language = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10)) ?: "";
        results.push_back(entry);
    }
    sqlite3_finalize(stmt);
    return results;
}

// SRUM entry operations
bool WindowsAnalysisDatabase::insertSrumEntry(const SrumEntry& entry) {
    const char* sql = "INSERT INTO srum_entries (app_name, user_name, timestamp, bytes_received, bytes_sent, foreground_duration, background_duration, cpu_time_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, entry.appName);
    BIND_TEXT(stmt, 2, entry.userName);
    BIND_INT64(stmt, 3, entry.timestamp);
    BIND_INT64(stmt, 4, entry.bytesReceived);
    BIND_INT64(stmt, 5, entry.bytesSent);
    BIND_INT64(stmt, 6, entry.foregroundDuration);
    BIND_INT64(stmt, 7, entry.backgroundDuration);
    BIND_INT64(stmt, 8, entry.cpuTimeMs);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

std::vector<SrumEntry> WindowsAnalysisDatabase::querySrumEntries(const std::string& whereClause) {
    std::vector<SrumEntry> results;
    std::string sql = "SELECT app_name, user_name, timestamp, bytes_received, bytes_sent, foreground_duration, background_duration, cpu_time_ms FROM srum_entries";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SrumEntry entry;
        entry.appName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        entry.userName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        entry.timestamp = sqlite3_column_int64(stmt, 2);
        entry.bytesReceived = sqlite3_column_int64(stmt, 3);
        entry.bytesSent = sqlite3_column_int64(stmt, 4);
        entry.foregroundDuration = sqlite3_column_int64(stmt, 5);
        entry.backgroundDuration = sqlite3_column_int64(stmt, 6);
        entry.cpuTimeMs = sqlite3_column_int64(stmt, 7);
        results.push_back(entry);
    }
    sqlite3_finalize(stmt);
    return results;
}

