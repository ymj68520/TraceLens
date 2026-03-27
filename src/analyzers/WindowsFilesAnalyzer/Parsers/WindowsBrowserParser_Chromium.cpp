// WindowsBrowserParser_Chromium.cpp
// Chromium-based browser parsing (Chrome, Edge, Brave, etc.)

#include "WindowsBrowserParser.h"

bool WindowsBrowserParser::parseChrome(const std::string& historyDbPath,
                                        const std::string& profileName) {
    return parseProfile({
        BrowserType::CHROME,
        "Chrome",
        profileName,
        fs::path(historyDbPath).parent_path().string(),
        historyDbPath,
        historyDbPath, // Downloads in same DB
        fs::path(historyDbPath).parent_path().string() + "/Bookmarks",
        fs::path(historyDbPath).parent_path().string() + "/Cookies",
        fs::path(historyDbPath).parent_path().string() + "/Login Data",
        fs::path(historyDbPath).parent_path().string() + "/Preferences"
    });
}

bool WindowsBrowserParser::parseEdge(const std::string& historyDbPath,
                                      const std::string& profileName) {
    return parseProfile({
        BrowserType::EDGE,
        "Edge",
        profileName,
        fs::path(historyDbPath).parent_path().string(),
        historyDbPath,
        historyDbPath,
        fs::path(historyDbPath).parent_path().string() + "/Bookmarks",
        fs::path(historyDbPath).parent_path().string() + "/Cookies",
        fs::path(historyDbPath).parent_path().string() + "/Login Data",
        fs::path(historyDbPath).parent_path().string() + "/Preferences"
    });
}

bool WindowsBrowserParser::parseProfile(const BrowserProfile& profile) {
    bool success = false;

    // Parse history
    if (!profile.historyDbPath.empty()) {
        sqlite3* db = nullptr;
        if (openDatabase(profile.historyDbPath, &db)) {
            if (profile.browserType == BrowserType::CHROME ||
                profile.browserType == BrowserType::EDGE) {
                parseChromiumHistory(db, profile.browserName, profile.profileName);
                parseChromiumDownloads(db, profile.browserName, profile.profileName);
            } else if (profile.browserType == BrowserType::FIREFOX) {
                parseFirefoxHistory(db, profile.profileName);
                parseFirefoxDownloads(db, profile.profileName);
                parseFirefoxBookmarks(db, profile.profileName);
            }
            closeDatabase(db);
            success = true;
        }
    }

    // Parse cookies (separate DB for Chromium)
    if (!profile.cookiesDbPath.empty() && profile.cookiesDbPath != profile.historyDbPath) {
        sqlite3* db = nullptr;
        if (openDatabase(profile.cookiesDbPath, &db)) {
            if (profile.browserType == BrowserType::CHROME ||
                profile.browserType == BrowserType::EDGE) {
                parseChromiumCookies(db, profile.browserName, profile.profileName);
            } else if (profile.browserType == BrowserType::FIREFOX) {
                parseFirefoxCookies(db, profile.profileName);
            }
            closeDatabase(db);
        }
    }

    // Parse bookmarks (JSON for Chromium)
    if (!profile.bookmarksPath.empty()) {
        if (profile.browserType == BrowserType::CHROME ||
            profile.browserType == BrowserType::EDGE) {
            parseChromiumBookmarks(profile.bookmarksPath, profile.browserName,
                                   profile.profileName);
        }
    }

    // Parse logins
    if (!profile.loginsDbPath.empty()) {
        sqlite3* db = nullptr;
        if (openDatabase(profile.loginsDbPath, &db)) {
            if (profile.browserType == BrowserType::CHROME ||
                profile.browserType == BrowserType::EDGE) {
                parseChromiumLogins(db, profile.browserName, profile.profileName);
            }
            closeDatabase(db);
        }
    }

    return success;
}

bool WindowsBrowserParser::parseChromiumHistory(sqlite3* db, const std::string& browserName,
                                                 const std::string& profileName) {
    const char* query =
        "SELECT u.url, u.title, u.visit_count, v.visit_time, v.visit_duration, "
        "v.transition, v.from_visit "
        "FROM visits v JOIN urls u ON v.url = u.id "
        "ORDER BY v.visit_time DESC LIMIT 10000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        setError("Failed to prepare history query");
        return false;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserHistoryEntry entry;
        entry.browserName = browserName;
        entry.profileName = profileName;
        entry.url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        entry.title = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        entry.visitCount = sqlite3_column_int(stmt, 2);
        entry.visitTime = sqlite3_column_int64(stmt, 3);
        entry.visitDuration = sqlite3_column_int64(stmt, 4);
        entry.visitType = visitTypeToString(sqlite3_column_int(stmt, 5));
        entry.isRedirect = (sqlite3_column_int(stmt, 5) == 3); // AUTO_SUBFRAME
        entry.referrer = "";

        history_.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return true;
}

bool WindowsBrowserParser::parseChromiumDownloads(sqlite3* db, const std::string& browserName,
                                                    const std::string& profileName) {
    const char* query =
        "SELECT current_path, target_path, start_time, end_time, state, "
        "received_bytes, total_bytes, mime_type, url, danger_type "
        "FROM downloads ORDER BY start_time DESC LIMIT 5000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserDownloadEntry entry;
        entry.browserName = browserName;
        entry.profileName = profileName;
        entry.targetPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        entry.fileName = fs::path(entry.targetPath).filename().string();
        entry.startTime = sqlite3_column_int64(stmt, 2);
        entry.endTime = sqlite3_column_int64(stmt, 3);
        entry.state = std::to_string(sqlite3_column_int(stmt, 4));
        entry.receivedBytes = sqlite3_column_int64(stmt, 5);
        entry.fileSize = sqlite3_column_int64(stmt, 6);
        entry.mimeType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7)) ?: "";
        entry.url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8)) ?: "";

        downloads_.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return true;
}

bool WindowsBrowserParser::parseChromiumCookies(sqlite3* db, const std::string& browserName,
                                                const std::string& profileName) {
    const char* query =
        "SELECT host, name, value, path, creation_utc, expires_utc, "
        "last_access_utc, is_secure, is_httponly, same_site "
        "FROM cookies ORDER BY creation_utc DESC LIMIT 5000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserCookieEntry entry;
        entry.browserName = browserName;
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

        int sameSite = sqlite3_column_int(stmt, 9);
        entry.sameSite = (sameSite == 0) ? "no_restriction" :
                        (sameSite == 1) ? "lax" :
                        (sameSite == 2) ? "strict" : "unsupported";

        cookies_.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return true;
}

bool WindowsBrowserParser::parseChromiumLogins(sqlite3* db, const std::string& browserName,
                                                const std::string& profileName) {
    const char* query =
        "SELECT origin_url, action_url, username_value, password_value, "
        "date_created, date_last_used, count "
        "FROM logins ORDER BY date_created DESC LIMIT 1000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserLoginEntry entry;
        entry.browserName = browserName;
        entry.profileName = profileName;
        entry.url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        entry.actionUrl = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        entry.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        entry.encryptedPassword = "***"; // Never store actual passwords
        entry.dateCreated = sqlite3_column_int64(stmt, 4);
        entry.dateLastUsed = sqlite3_column_int64(stmt, 5);
        entry.timesUsed = sqlite3_column_int(stmt, 6);

        logins_.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return true;
}

bool WindowsBrowserParser::parseChromiumBookmarks(const std::string& bookmarksJsonPath,
                                                   const std::string& browserName,
                                                   const std::string& profileName) {
    // Chromium bookmarks are stored as JSON in Bookmarks file
    std::ifstream file(bookmarksJsonPath);
    if (!file.is_open()) {
        return false;
    }

    try {
        Json j;
        file >> j;

        if (j.contains("roots")) {
            auto& roots = j["roots"];
            parseBookmarkFolder(roots, browserName, profileName, "");
        }
    } catch (...) {
        // Ignore parsing errors
    }

    return true;
}

void WindowsBrowserParser::parseBookmarkFolder(const Json& folder,
                                                const std::string& browserName,
                                                const std::string& profileName,
                                                const std::string& parentPath) {
    std::string folderName = folder.value("name", "Unnamed");

    // Parse children
    if (folder.contains("children")) {
        for (const auto& child : folder["children"]) {
            if (child.contains("type")) {
                std::string type = child["type"];
                if (type == "folder") {
                    parseBookmarkFolder(child, browserName, profileName,
                                       parentPath + "/" + folderName);
                } else if (type == "url") {
                    BrowserBookmarkEntry entry;
                    entry.browserName = browserName;
                    entry.profileName = profileName;
                    entry.url = child.value("url", "");
                    entry.title = child.value("name", "");
                    entry.folderPath = parentPath + "/" + folderName;
                    entry.dateAdded = child.value("date_added", 0);
                    entry.dateModified = child.value("date_modified", 0);

                    bookmarks_.push_back(entry);
                }
            }
        }
    }
}