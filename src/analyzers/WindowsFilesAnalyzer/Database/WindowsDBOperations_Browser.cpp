// WindowsDBOperations_Browser.cpp
// Browser artifacts insert/query operations

#include "WindowsAnalysisDatabase.h"

#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)



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

// Browser history operations
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

std::vector<BrowserHistoryEntry> WindowsAnalysisDatabase::queryBrowserHistory(const std::string& whereClause) {
    return {}; // Stub implementation
}

// Browser download operations
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

std::vector<BrowserDownloadEntry> WindowsAnalysisDatabase::queryBrowserDownloads(const std::string& whereClause) {
    return {}; // Stub implementation
}

// Browser bookmark operations
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

std::vector<BrowserBookmarkEntry> WindowsAnalysisDatabase::queryBrowserBookmarks(const std::string& whereClause) {
    return {}; // Stub implementation
}

// Browser cookie operations
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

std::vector<BrowserCookieEntry> WindowsAnalysisDatabase::queryBrowserCookies(const std::string& whereClause) {
    return {}; // Stub implementation
}

// Browser login operations
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

std::vector<BrowserLoginEntry> WindowsAnalysisDatabase::queryBrowserLogins(const std::string& whereClause) {
    return {}; // Stub implementation
}

