// WindowsDBOperations.cpp
// Data access operations for WindowsAnalysisDatabase
// All insert* and query* methods are implemented here

#include "WindowsAnalysisDatabase.h"
#include <sstream>

// Helper macro for binding text
#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

// Helper macro for binding int64
#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

// Helper macro for binding int
#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)

// ============================================================================
// Insert Method Implementations
// ============================================================================

bool WindowsAnalysisDatabase::insertRegistryValue(const RegistryValue& value) {
    const char* sql = "INSERT INTO registry_values (hive_path, hive_type, key_path, value_name, value_type, value_data, last_modified, forensic_importance) VALUES (?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, value.hivePath);
    BIND_TEXT(stmt, 2, value.hiveType);
    BIND_TEXT(stmt, 3, value.keyPath);
    BIND_TEXT(stmt, 4, value.valueName);
    BIND_TEXT(stmt, 5, value.valueType);
    BIND_TEXT(stmt, 6, value.valueData);
    BIND_INT64(stmt, 7, value.lastModified);
    BIND_TEXT(stmt, 8, value.forensicImportance);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

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

bool WindowsAnalysisDatabase::insertPrefetchInfo(const PrefetchInfo& info) {
    const char* sql = "INSERT INTO prefetch_files (file_path, executable_name, executable_path, prefetch_hash, run_count, last_run_time, creation_time, referenced_files, referenced_directories) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, info.filePath);
    BIND_TEXT(stmt, 2, info.executableName);
    BIND_TEXT(stmt, 3, info.executablePath);
    BIND_TEXT(stmt, 4, info.prefetchHash);
    BIND_INT(stmt, 5, info.runCount);
    BIND_INT64(stmt, 6, info.lastRunTime);
    BIND_INT64(stmt, 7, info.creationTime);

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

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

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

bool WindowsAnalysisDatabase::insertUserInfo(const WindowsUserInfo& user) {
    const char* sql = "INSERT INTO user_accounts (rid, username, full_name, comment, last_login, password_last_set, account_expires, password_expires, account_flags, is_admin, home_directory, profile_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_INT(stmt, 1, user.rid);
    BIND_TEXT(stmt, 2, user.username);
    BIND_TEXT(stmt, 3, user.fullName);
    BIND_TEXT(stmt, 4, user.comment);
    BIND_INT64(stmt, 5, user.lastLogin);
    BIND_INT64(stmt, 6, user.passwordLastSet);
    BIND_INT64(stmt, 7, user.accountExpires);
    BIND_INT64(stmt, 8, user.passwordExpires);
    BIND_TEXT(stmt, 9, user.accountFlags);
    BIND_INT(stmt, 10, user.isAdmin ? 1 : 0);
    BIND_TEXT(stmt, 11, user.homeDirectory);
    BIND_TEXT(stmt, 12, user.profilePath);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

bool WindowsAnalysisDatabase::insertUSBDevice(const USBDeviceInfo& device) {
    const char* sql = "INSERT INTO usb_devices (vendor_id, product_id, serial_number, device_description, friendly_name, device_class, first_connected, last_connected, last_drive_letter) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, device.vendorId);
    BIND_TEXT(stmt, 2, device.productId);
    BIND_TEXT(stmt, 3, device.serialNumber);
    BIND_TEXT(stmt, 4, device.deviceDescription);
    BIND_TEXT(stmt, 5, device.friendlyName);
    BIND_TEXT(stmt, 6, device.deviceClass);
    BIND_INT64(stmt, 7, device.firstConnected);
    BIND_INT64(stmt, 8, device.lastConnected);
    BIND_TEXT(stmt, 9, device.lastDriveLetter);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

bool WindowsAnalysisDatabase::insertRecycleBinEntry(const RecycleBinEntry& entry) {
    const char* sql = "INSERT INTO recycle_bin (recycle_file_path, original_path, file_name, deletion_time, original_size, user_sid) VALUES (?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, entry.recycleFilePath);
    BIND_TEXT(stmt, 2, entry.originalPath);
    BIND_TEXT(stmt, 3, entry.fileName);
    BIND_INT64(stmt, 4, entry.deletionTime);
    BIND_INT64(stmt, 5, entry.originalSize);
    BIND_TEXT(stmt, 6, entry.userSid);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

bool WindowsAnalysisDatabase::insertBrowserArtifact(const BrowserArtifact& artifact) {
    const char* sql = "INSERT INTO browser_artifacts (browser_name, artifact_type, url, title, timestamp, visit_count, local_path, file_size) VALUES (?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, artifact.browserName);
    BIND_TEXT(stmt, 2, artifact.artifactType);
    BIND_TEXT(stmt, 3, artifact.url);
    BIND_TEXT(stmt, 4, artifact.title);
    BIND_INT64(stmt, 5, artifact.timestamp);
    BIND_INT(stmt, 6, artifact.visitCount);
    BIND_TEXT(stmt, 7, artifact.localPath);
    BIND_INT64(stmt, 8, artifact.fileSize);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

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

// Batch insert methods
bool WindowsAnalysisDatabase::insertRegistryValues(const std::vector<RegistryValue>& values) {
    if (values.empty()) return true;

    beginTransaction();
    for (const auto& value : values) {
        if (!insertRegistryValue(value)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
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

// Browser data insertion methods
bool WindowsAnalysisDatabase::insertBrowserHistory(const BrowserHistoryEntry& entry) {
    const char* sql = "INSERT INTO browser_history (browser_name, profile_name, url, title, visit_time, visit_duration, visit_count, visit_type, is_redirect, referrer) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, entry.browserName);
    BIND_TEXT(stmt, 2, entry.profileName);
    BIND_TEXT(stmt, 3, entry.url);
    BIND_TEXT(stmt, 4, entry.title);
    BIND_INT64(stmt, 5, entry.visitTime);
    BIND_INT64(stmt, 6, entry.visitDuration);
    BIND_INT(stmt, 7, entry.visitCount);
    BIND_TEXT(stmt, 8, entry.visitType);
    BIND_INT(stmt, 9, entry.isRedirect ? 1 : 0);
    BIND_TEXT(stmt, 10, entry.referrer);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

bool WindowsAnalysisDatabase::insertBrowserHistories(const std::vector<BrowserHistoryEntry>& entries) {
    if (entries.empty()) return true;

    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertBrowserHistory(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

bool WindowsAnalysisDatabase::insertBrowserDownload(const BrowserDownloadEntry& entry) {
    const char* sql = "INSERT INTO browser_downloads (browser_name, profile_name, url, target_path, file_name, file_size, start_time, end_time, state, mime_type, referrer, received_bytes, danger_accepted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, entry.browserName);
    BIND_TEXT(stmt, 2, entry.profileName);
    BIND_TEXT(stmt, 3, entry.url);
    BIND_TEXT(stmt, 4, entry.targetPath);
    BIND_TEXT(stmt, 5, entry.fileName);
    BIND_INT64(stmt, 6, entry.fileSize);
    BIND_INT64(stmt, 7, entry.startTime);
    BIND_INT64(stmt, 8, entry.endTime);
    BIND_TEXT(stmt, 9, entry.state);
    BIND_TEXT(stmt, 10, entry.mimeType);
    BIND_TEXT(stmt, 11, entry.referrer);
    BIND_INT64(stmt, 12, entry.receivedBytes);
    BIND_INT(stmt, 13, entry.dangerAccepted ? 1 : 0);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

bool WindowsAnalysisDatabase::insertBrowserDownloads(const std::vector<BrowserDownloadEntry>& entries) {
    if (entries.empty()) return true;

    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertBrowserDownload(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

bool WindowsAnalysisDatabase::insertBrowserBookmark(const BrowserBookmarkEntry& entry) {
    const char* sql = "INSERT INTO browser_bookmarks (browser_name, profile_name, url, title, folder_path, date_added, date_modified) VALUES (?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, entry.browserName);
    BIND_TEXT(stmt, 2, entry.profileName);
    BIND_TEXT(stmt, 3, entry.url);
    BIND_TEXT(stmt, 4, entry.title);
    BIND_TEXT(stmt, 5, entry.folderPath);
    BIND_INT64(stmt, 6, entry.dateAdded);
    BIND_INT64(stmt, 7, entry.dateModified);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

bool WindowsAnalysisDatabase::insertBrowserBookmarks(const std::vector<BrowserBookmarkEntry>& entries) {
    if (entries.empty()) return true;

    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertBrowserBookmark(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

bool WindowsAnalysisDatabase::insertBrowserCookie(const BrowserCookieEntry& entry) {
    const char* sql = "INSERT INTO browser_cookies (browser_name, profile_name, domain, name, path, creation_time, expiration_time, last_access_time, is_secure, is_http_only, is_persistent, same_site) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, entry.browserName);
    BIND_TEXT(stmt, 2, entry.profileName);
    BIND_TEXT(stmt, 3, entry.domain);
    BIND_TEXT(stmt, 4, entry.name);
    BIND_TEXT(stmt, 5, entry.path);
    BIND_INT64(stmt, 6, entry.creationTime);
    BIND_INT64(stmt, 7, entry.expirationTime);
    BIND_INT64(stmt, 8, entry.lastAccessTime);
    BIND_INT(stmt, 9, entry.isSecure ? 1 : 0);
    BIND_INT(stmt, 10, entry.isHttpOnly ? 1 : 0);
    BIND_INT(stmt, 11, entry.isPersistent ? 1 : 0);
    BIND_TEXT(stmt, 12, entry.sameSite);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

bool WindowsAnalysisDatabase::insertBrowserCookies(const std::vector<BrowserCookieEntry>& entries) {
    if (entries.empty()) return true;

    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertBrowserCookie(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

bool WindowsAnalysisDatabase::insertBrowserLogin(const BrowserLoginEntry& entry) {
    const char* sql = "INSERT INTO browser_logins (browser_name, profile_name, url, action_url, username, encrypted_password, date_created, date_last_used, date_modified, times_used) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, entry.browserName);
    BIND_TEXT(stmt, 2, entry.profileName);
    BIND_TEXT(stmt, 3, entry.url);
    BIND_TEXT(stmt, 4, entry.actionUrl);
    BIND_TEXT(stmt, 5, entry.username);
    BIND_TEXT(stmt, 6, entry.encryptedPassword);
    BIND_INT64(stmt, 7, entry.dateCreated);
    BIND_INT64(stmt, 8, entry.dateLastUsed);
    BIND_INT64(stmt, 9, entry.dateModified);
    BIND_INT(stmt, 10, entry.timesUsed);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

bool WindowsAnalysisDatabase::insertBrowserLogins(const std::vector<BrowserLoginEntry>& entries) {
    if (entries.empty()) return true;

    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertBrowserLogin(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

// ============================================================================
// Query Method Implementations
// ============================================================================

std::vector<RegistryValue> WindowsAnalysisDatabase::queryRegistryValues(const std::string& whereClause) {
    std::vector<RegistryValue> results;
    std::string sql = "SELECT hive_path, hive_type, key_path, value_name, value_type, value_data, last_modified, forensic_importance FROM registry_values";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        RegistryValue value;
        value.hivePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        value.hiveType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        value.keyPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        value.valueName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        value.valueType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4)) ?: "";
        value.valueData = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5)) ?: "";
        value.lastModified = sqlite3_column_int64(stmt, 6);
        value.forensicImportance = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7)) ?: "";
        results.push_back(value);
    }
    sqlite3_finalize(stmt);
    return results;
}

std::vector<EventLogEntry> WindowsAnalysisDatabase::queryEventLogs(const std::string& whereClause) {
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

std::vector<PrefetchInfo> WindowsAnalysisDatabase::queryPrefetchFiles(const std::string& whereClause) {
    std::vector<PrefetchInfo> results;
    std::string sql = "SELECT file_path, executable_name, executable_path, prefetch_hash, run_count, last_run_time, creation_time, referenced_files, referenced_directories FROM prefetch_files";
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
        info.runCount = sqlite3_column_int(stmt, 4);
        info.lastRunTime = sqlite3_column_int64(stmt, 5);
        info.creationTime = sqlite3_column_int64(stmt, 6);
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
        results.push_back(info);
    }
    sqlite3_finalize(stmt);
    return results;
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

std::vector<WindowsUserInfo> WindowsAnalysisDatabase::queryUserAccounts(const std::string& whereClause) {
    std::vector<WindowsUserInfo> results;
    std::string sql = "SELECT rid, username, full_name, comment, last_login, password_last_set, account_expires, password_expires, account_flags, is_admin, home_directory, profile_path FROM user_accounts";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        WindowsUserInfo user;
        user.rid = sqlite3_column_int(stmt, 0);
        user.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        user.fullName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        user.comment = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        user.lastLogin = sqlite3_column_int64(stmt, 4);
        user.passwordLastSet = sqlite3_column_int64(stmt, 5);
        user.accountExpires = sqlite3_column_int64(stmt, 6);
        user.passwordExpires = sqlite3_column_int64(stmt, 7);
        user.accountFlags = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8)) ?: "";
        user.isAdmin = sqlite3_column_int(stmt, 9) != 0;
        user.homeDirectory = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10)) ?: "";
        user.profilePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11)) ?: "";
        results.push_back(user);
    }
    sqlite3_finalize(stmt);
    return results;
}

std::vector<USBDeviceInfo> WindowsAnalysisDatabase::queryUSBDevices(const std::string& whereClause) {
    std::vector<USBDeviceInfo> results;
    std::string sql = "SELECT vendor_id, product_id, serial_number, device_description, friendly_name, device_class, first_connected, last_connected, last_drive_letter FROM usb_devices";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        USBDeviceInfo device;
        device.vendorId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        device.productId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        device.serialNumber = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        device.deviceDescription = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        device.friendlyName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4)) ?: "";
        device.deviceClass = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5)) ?: "";
        device.firstConnected = sqlite3_column_int64(stmt, 6);
        device.lastConnected = sqlite3_column_int64(stmt, 7);
        device.lastDriveLetter = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8)) ?: "";
        results.push_back(device);
    }
    sqlite3_finalize(stmt);
    return results;
}

std::vector<RecycleBinEntry> WindowsAnalysisDatabase::queryRecycleBinEntries(const std::string& whereClause) {
    std::vector<RecycleBinEntry> results;
    std::string sql = "SELECT recycle_file_path, original_path, file_name, deletion_time, original_size, user_sid FROM recycle_bin";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        RecycleBinEntry entry;
        entry.recycleFilePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        entry.originalPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        entry.fileName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        entry.deletionTime = sqlite3_column_int64(stmt, 3);
        entry.originalSize = sqlite3_column_int64(stmt, 4);
        entry.userSid = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5)) ?: "";
        results.push_back(entry);
    }
    sqlite3_finalize(stmt);
    return results;
}

std::vector<BrowserArtifact> WindowsAnalysisDatabase::queryBrowserArtifacts(const std::string& whereClause) {
    std::vector<BrowserArtifact> results;
    std::string sql = "SELECT browser_name, artifact_type, url, title, timestamp, visit_count, local_path, file_size FROM browser_artifacts";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserArtifact artifact;
        artifact.browserName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        artifact.artifactType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        artifact.url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        artifact.title = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        artifact.timestamp = sqlite3_column_int64(stmt, 4);
        artifact.visitCount = sqlite3_column_int(stmt, 5);
        artifact.localPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6)) ?: "";
        artifact.fileSize = sqlite3_column_int64(stmt, 7);
        results.push_back(artifact);
    }
    sqlite3_finalize(stmt);
    return results;
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

// Browser query methods (stub implementations)
std::vector<BrowserHistoryEntry> WindowsAnalysisDatabase::queryBrowserHistory(const std::string& whereClause) {
    return {};
}

std::vector<BrowserDownloadEntry> WindowsAnalysisDatabase::queryBrowserDownloads(const std::string& whereClause) {
    return {};
}

std::vector<BrowserBookmarkEntry> WindowsAnalysisDatabase::queryBrowserBookmarks(const std::string& whereClause) {
    return {};
}

std::vector<BrowserCookieEntry> WindowsAnalysisDatabase::queryBrowserCookies(const std::string& whereClause) {
    return {};
}

std::vector<BrowserLoginEntry> WindowsAnalysisDatabase::queryBrowserLogins(const std::string& whereClause) {
    return {};
}
