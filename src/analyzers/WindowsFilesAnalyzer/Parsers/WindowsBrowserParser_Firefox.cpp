// WindowsBrowserParser_Firefox.cpp
// Firefox browser parsing

#include "WindowsBrowserParser.h"

bool WindowsBrowserParser::parseFirefox(const std::string& placesDbPath,
                                         const std::string& profileName) {
    sqlite3* db = nullptr;
    bool success = false;

    if (openDatabase(placesDbPath, &db)) {
        parseFirefoxHistory(db, profileName);
        parseFirefoxDownloads(db, profileName);
        parseFirefoxBookmarks(db, profileName);
        closeDatabase(db);
        success = true;
    }

    // Parse logins from logins.json
    std::string loginsPath = fs::path(placesDbPath).parent_path().string() + "/logins.json";
    if (std::filesystem::exists(loginsPath)) {
        parseFirefoxLogins(loginsPath, profileName);
    }

    return success;
}

bool WindowsBrowserParser::parseFirefoxHistory(sqlite3* db, const std::string& profileName) {
    const char* query =
        "SELECT p.url, p.title, h.visit_date, p.rev_host, p.visit_count "
        "FROMmoz_historyvisits h JOIN moz_places p ON h.place_id = p.id "
        "ORDER BY h.visit_date DESC LIMIT 10000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        setError("Failed to prepare Firefox history query");
        return false;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserHistoryEntry entry;
        entry.browserName = "Firefox";
        entry.profileName = profileName;
        entry.url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        entry.title = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        entry.visitTime = sqlite3_column_int64(stmt, 2);
        entry.visitCount = sqlite3_column_int(stmt, 4);
        entry.visitType = "LINK";

        history_.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return true;
}

bool WindowsBrowserParser::parseFirefoxDownloads(sqlite3* db, const std::string& profileName) {
    const char* query =
        "SELECT name, source, target, dateAdded, endTime, state, size "
        "FROM moz_downloads ORDER BY dateAdded DESC LIMIT 5000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserDownloadEntry entry;
        entry.browserName = "Firefox";
        entry.profileName = profileName;
        entry.fileName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        entry.url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        entry.targetPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        entry.startTime = sqlite3_column_int64(stmt, 3);
        entry.endTime = sqlite3_column_int64(stmt, 4);
        entry.state = std::to_string(sqlite3_column_int(stmt, 5));
        entry.fileSize = sqlite3_column_int64(stmt, 6);

        downloads_.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return true;
}

bool WindowsBrowserParser::parseFirefoxCookies(sqlite3* db, const std::string& profileName) {
    const char* query =
        "SELECT host, name, value, path, creationTime, expiry, lastAccessed, "
        "isSecure, isHttpOnly "
        "FROM moz_cookies ORDER BY creationTime DESC LIMIT 5000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserCookieEntry entry;
        entry.browserName = "Firefox";
        entry.profileName = profileName;
        entry.domain = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        entry.name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        entry.path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        entry.creationTime = sqlite3_column_int64(stmt, 4);
        entry.expirationTime = sqlite3_column_int64(stmt, 5);
        entry.lastAccessTime = sqlite3_column_int64(stmt, 6);
        entry.isSecure = sqlite3_column_int(stmt, 7) != 0;
        entry.isHttpOnly = sqlite3_column_int(stmt, 8) != 0;
        entry.isPersistent = true;
        entry.sameSite = "no_restriction";

        cookies_.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return true;
}

bool WindowsBrowserParser::parseFirefoxLogins(const std::string& loginsJsonPath,
                                              const std::string& profileName) {
    std::ifstream file(loginsJsonPath);
    if (!file.is_open()) {
        return false;
    }

    try {
        Json j;
        file >> j;

        if (j.contains("logins") && j["logins"].is_array()) {
            for (const auto& login : j["logins"]) {
                BrowserLoginEntry entry;
                entry.browserName = "Firefox";
                entry.profileName = profileName;
                entry.url = login.value("hostname", "");
                entry.actionUrl = login.value("hostname", "");
                entry.username = login.value("username", "");
                entry.encryptedPassword = "***";
                entry.dateCreated = login.value("timeCreated", 0);
                entry.dateLastUsed = login.value("timeLastUsed", 0);
                entry.timesUsed = login.value("timesUsed", 0);

                logins_.push_back(entry);
            }
        }
    } catch (...) {
        // Ignore parsing errors
    }

    return true;
}

bool WindowsBrowserParser::parseFirefoxBookmarks(sqlite3* db, const std::string& profileName) {
    const char* query =
        "SELECT p.url, b.title, b.dateAdded, b.parent, b.position, f.title "
        "FROM moz_bookmarks b "
        "LEFT JOIN moz_places p ON b.fk = p.id "
        "LEFT JOIN moz_bookmarks f ON b.parent = f.id "
        "WHERE b.type = 1 "
        "ORDER BY b.dateAdded DESC LIMIT 5000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        if (sqlite3_column_type(stmt, 0) != SQLITE_NULL) {
            BrowserBookmarkEntry entry;
            entry.browserName = "Firefox";
            entry.profileName = profileName;
            entry.url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
            entry.title = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
            entry.dateAdded = sqlite3_column_int64(stmt, 2);
            entry.folderPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5)) ?: "";

            bookmarks_.push_back(entry);
        }
    }

    sqlite3_finalize(stmt);
    return true;
}