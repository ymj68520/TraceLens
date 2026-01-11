// WindowsBrowserParser.cpp
// Implementation of comprehensive browser data parser

#include "WindowsBrowserParser.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <sstream>
#include <cstring>
#include <algorithm>
#include <filesystem>
#include <regex>

namespace fs = std::filesystem;

// ============================================================================
// BrowserHelpers Implementation
// ============================================================================

namespace BrowserHelpers {

BrowserType detectBrowserType(const std::string& dbPath) {
    std::string lowerPath = dbPath;
    std::transform(lowerPath.begin(), lowerPath.end(), lowerPath.begin(), ::tolower);

    if (lowerPath.find("chrome") != std::string::npos) {
        return BrowserType::CHROME;
    } else if (lowerPath.find("edge") != std::string::npos) {
        return BrowserType::EDGE;
    } else if (lowerPath.find("firefox") != std::string::npos ||
               lowerPath.find("mozilla") != std::string::npos) {
        return BrowserType::FIREFOX;
    } else if (lowerPath.find("iexplore") != std::string::npos ||
               lowerPath.find("internet explorer") != std::string::npos) {
        return BrowserType::INTERNET_EXPLORER;
    }
    return BrowserType::UNKNOWN;
}

std::string browserTypeToString(BrowserType type) {
    switch (type) {
        case BrowserType::CHROME: return "Chrome";
        case BrowserType::EDGE: return "Edge";
        case BrowserType::FIREFOX: return "Firefox";
        case BrowserType::INTERNET_EXPLORER: return "Internet Explorer";
        default: return "Unknown";
    }
}

int64_t chromiumTimeToUnix(int64_t chromiumTime) {
    // Chromium uses microseconds since 1601-01-01
    // Convert to Unix timestamp (seconds since 1970-01-01)
    if (chromiumTime <= 0) return 0;
    return (chromiumTime / 1000000) - 11644473600LL;
}

int64_t firefoxTimeToUnix(int64_t prTime) {
    // Firefox PRTime is microseconds since 1970-01-01
    if (prTime <= 0) return 0;
    return prTime / 1000000;
}

std::string extractProfileName(const std::string& path) {
    fs::path p(path);
    // Walk up to find profile folder
    // Chrome/Edge: .../User Data/ProfileName/...
    // Firefox: .../Profiles/xxx.ProfileName/...
    
    std::vector<std::string> parts;
    for (const auto& part : p) {
        parts.push_back(part.string());
    }
    
    for (size_t i = 0; i < parts.size(); ++i) {
        if (parts[i] == "User Data" && i + 1 < parts.size()) {
            return parts[i + 1];
        }
        if (parts[i] == "Profiles" && i + 1 < parts.size()) {
            return parts[i + 1];
        }
    }
    
    return "Default";
}

bool isValidSqliteDb(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) return false;
    
    char header[16];
    file.read(header, 16);
    
    // SQLite magic header: "SQLite format 3\0"
    return file.gcount() >= 16 && 
           std::memcmp(header, "SQLite format 3", 15) == 0;
}

} // namespace BrowserHelpers

// ============================================================================
// WindowsBrowserParser Implementation
// ============================================================================

WindowsBrowserParser::WindowsBrowserParser() {
}

WindowsBrowserParser::~WindowsBrowserParser() {
}

void WindowsBrowserParser::clear() {
    history_.clear();
    downloads_.clear();
    bookmarks_.clear();
    cookies_.clear();
    logins_.clear();
    lastError_.clear();
}

void WindowsBrowserParser::setError(const std::string& error) {
    lastError_ = error;
    AuditLog::instance().log("WARNING", "BROWSER_PARSER_ERROR", error);
}

bool WindowsBrowserParser::openDatabase(const std::string& dbPath, sqlite3** db) {
    // Open in read-only mode
    int rc = sqlite3_open_v2(dbPath.c_str(), db, SQLITE_OPEN_READONLY, nullptr);
    if (rc != SQLITE_OK) {
        setError("Failed to open database: " + dbPath + " - " + sqlite3_errmsg(*db));
        return false;
    }
    return true;
}

void WindowsBrowserParser::closeDatabase(sqlite3* db) {
    if (db) {
        sqlite3_close(db);
    }
}

int64_t WindowsBrowserParser::chromiumTimeToUnix(int64_t chromiumTime) {
    return BrowserHelpers::chromiumTimeToUnix(chromiumTime);
}

int64_t WindowsBrowserParser::firefoxTimeToUnix(int64_t prTime) {
    return BrowserHelpers::firefoxTimeToUnix(prTime);
}

std::string WindowsBrowserParser::visitTypeToString(int type) {
    // Chromium visit types
    switch (type) {
        case 0: return "link";
        case 1: return "typed";
        case 2: return "bookmark";
        case 3: return "auto_subframe";
        case 4: return "manual_subframe";
        case 5: return "generated";
        case 6: return "start_page";
        case 7: return "form_submit";
        case 8: return "reload";
        case 9: return "keyword";
        case 10: return "keyword_generated";
        default: return "other";
    }
}

// ============================================================================
// Chrome/Edge (Chromium) Parsing
// ============================================================================

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
        "FROM urls u "
        "LEFT JOIN visits v ON u.id = v.url "
        "ORDER BY v.visit_time DESC "
        "LIMIT 10000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        setError("Failed to prepare history query: " + std::string(sqlite3_errmsg(db)));
        return false;
    }

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserHistoryEntry entry;
        entry.browserName = browserName;
        entry.profileName = profileName;

        const char* url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        entry.url = url ? url : "";

        const char* title = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        entry.title = title ? title : "";

        entry.visitCount = sqlite3_column_int(stmt, 2);
        entry.visitTime = chromiumTimeToUnix(sqlite3_column_int64(stmt, 3));
        entry.visitDuration = sqlite3_column_int64(stmt, 4) / 1000; // Convert to ms

        int transition = sqlite3_column_int(stmt, 5);
        entry.visitType = visitTypeToString(transition & 0xFF);
        entry.isRedirect = (transition & 0xC0000000) != 0;

        // Check if this was a redirect by looking at from_visit
        int64_t fromVisit = sqlite3_column_int64(stmt, 6);
        if (fromVisit > 0 && entry.visitType == "link") {
            entry.isRedirect = true;
        }

        history_.push_back(entry);
        count++;
    }

    sqlite3_finalize(stmt);

    AuditLog::instance().log("INFO", "BROWSER_HISTORY_PARSED",
        browserName + " history: " + std::to_string(count) + " entries from " + profileName);

    return true;
}

bool WindowsBrowserParser::parseChromiumDownloads(sqlite3* db, const std::string& browserName,
                                                   const std::string& profileName) {
    const char* query = 
        "SELECT current_path, target_path, start_time, received_bytes, total_bytes, "
        "state, end_time, mime_type, original_mime_type, referrer, "
        "tab_url, tab_referrer_url, site_url "
        "FROM downloads "
        "ORDER BY start_time DESC "
        "LIMIT 5000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        // Downloads table might not exist in older versions
        return true;
    }

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserDownloadEntry entry;
        entry.browserName = browserName;
        entry.profileName = profileName;

        const char* currentPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        const char* targetPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        entry.targetPath = targetPath ? targetPath : (currentPath ? currentPath : "");
        
        // Extract filename from path
        entry.fileName = fs::path(entry.targetPath).filename().string();

        entry.startTime = chromiumTimeToUnix(sqlite3_column_int64(stmt, 2));
        entry.receivedBytes = sqlite3_column_int64(stmt, 3);
        entry.fileSize = sqlite3_column_int64(stmt, 4);

        int state = sqlite3_column_int(stmt, 5);
        switch (state) {
            case 0: entry.state = "in_progress"; break;
            case 1: entry.state = "complete"; break;
            case 2: entry.state = "cancelled"; break;
            case 3: entry.state = "interrupted"; break;
            default: entry.state = "unknown"; break;
        }

        entry.endTime = chromiumTimeToUnix(sqlite3_column_int64(stmt, 6));
        
        const char* mimeType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        entry.mimeType = mimeType ? mimeType : "";

        const char* referrer = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9));
        entry.referrer = referrer ? referrer : "";

        const char* tabUrl = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
        entry.url = tabUrl ? tabUrl : "";

        downloads_.push_back(entry);
        count++;
    }

    sqlite3_finalize(stmt);

    AuditLog::instance().log("INFO", "BROWSER_DOWNLOADS_PARSED",
        browserName + " downloads: " + std::to_string(count) + " entries from " + profileName);

    return true;
}

bool WindowsBrowserParser::parseChromiumCookies(sqlite3* db, const std::string& browserName,
                                                 const std::string& profileName) {
    // Try new schema first (Chrome 80+)
    const char* query = 
        "SELECT host_key, name, path, creation_utc, expires_utc, last_access_utc, "
        "is_secure, is_httponly, is_persistent, samesite "
        "FROM cookies "
        "ORDER BY last_access_utc DESC "
        "LIMIT 5000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        return true; // Cookies table might have different schema
    }

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserCookieEntry entry;
        entry.browserName = browserName;
        entry.profileName = profileName;

        const char* domain = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        entry.domain = domain ? domain : "";

        const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        entry.name = name ? name : "";

        const char* path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        entry.path = path ? path : "";

        entry.creationTime = chromiumTimeToUnix(sqlite3_column_int64(stmt, 3));
        entry.expirationTime = chromiumTimeToUnix(sqlite3_column_int64(stmt, 4));
        entry.lastAccessTime = chromiumTimeToUnix(sqlite3_column_int64(stmt, 5));

        entry.isSecure = sqlite3_column_int(stmt, 6) != 0;
        entry.isHttpOnly = sqlite3_column_int(stmt, 7) != 0;
        entry.isPersistent = sqlite3_column_int(stmt, 8) != 0;

        int sameSite = sqlite3_column_int(stmt, 9);
        switch (sameSite) {
            case 0: entry.sameSite = "no_restriction"; break;
            case 1: entry.sameSite = "lax"; break;
            case 2: entry.sameSite = "strict"; break;
            default: entry.sameSite = "unspecified"; break;
        }

        cookies_.push_back(entry);
        count++;
    }

    sqlite3_finalize(stmt);

    AuditLog::instance().log("INFO", "BROWSER_COOKIES_PARSED",
        browserName + " cookies: " + std::to_string(count) + " entries from " + profileName);

    return true;
}

bool WindowsBrowserParser::parseChromiumLogins(sqlite3* db, const std::string& browserName,
                                                const std::string& profileName) {
    const char* query = 
        "SELECT origin_url, action_url, username_value, password_value, "
        "date_created, date_last_used, date_password_modified, times_used "
        "FROM logins "
        "ORDER BY date_last_used DESC "
        "LIMIT 1000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        return true;
    }

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserLoginEntry entry;
        entry.browserName = browserName;
        entry.profileName = profileName;

        const char* originUrl = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        entry.url = originUrl ? originUrl : "";

        const char* actionUrl = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        entry.actionUrl = actionUrl ? actionUrl : "";

        const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        entry.username = username ? username : "";

        // Password is encrypted - store as hex for analysis
        const void* passwordBlob = sqlite3_column_blob(stmt, 3);
        int passwordSize = sqlite3_column_bytes(stmt, 3);
        if (passwordBlob && passwordSize > 0) {
            std::stringstream ss;
            for (int i = 0; i < std::min(passwordSize, 100); ++i) {
                ss << std::hex << std::setfill('0') << std::setw(2) 
                   << (int)(reinterpret_cast<const uint8_t*>(passwordBlob)[i]);
            }
            entry.encryptedPassword = ss.str();
        }

        entry.dateCreated = chromiumTimeToUnix(sqlite3_column_int64(stmt, 4));
        entry.dateLastUsed = chromiumTimeToUnix(sqlite3_column_int64(stmt, 5));
        entry.dateModified = chromiumTimeToUnix(sqlite3_column_int64(stmt, 6));
        entry.timesUsed = sqlite3_column_int(stmt, 7);

        logins_.push_back(entry);
        count++;
    }

    sqlite3_finalize(stmt);

    AuditLog::instance().log("INFO", "BROWSER_LOGINS_PARSED",
        browserName + " logins: " + std::to_string(count) + " entries from " + profileName);

    return true;
}

bool WindowsBrowserParser::parseChromiumBookmarks(const std::string& bookmarksJsonPath,
                                                   const std::string& browserName,
                                                   const std::string& profileName) {
    // Read bookmarks JSON file
    std::ifstream file(bookmarksJsonPath);
    if (!file) {
        return true; // Bookmarks file might not exist
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    std::string content = buffer.str();

    // Simple regex-based parsing for bookmark URLs
    // Format: "url": "https://..."
    std::regex urlRegex("\"url\"\\s*:\\s*\"([^\"]+)\"");
    std::regex nameRegex("\"name\"\\s*:\\s*\"([^\"]+)\"");
    std::regex dateAddedRegex("\"date_added\"\\s*:\\s*\"(\\d+)\"");

    std::sregex_iterator urlIt(content.begin(), content.end(), urlRegex);
    std::sregex_iterator end;

    int count = 0;
    size_t pos = 0;
    while (urlIt != end) {
        BrowserBookmarkEntry entry;
        entry.browserName = browserName;
        entry.profileName = profileName;
        entry.url = (*urlIt)[1].str();

        // Find associated name (search backwards)
        size_t urlPos = urlIt->position();
        std::string context = content.substr(std::max(0UL, urlPos - 500), 500);
        
        std::smatch nameMatch;
        if (std::regex_search(context, nameMatch, nameRegex)) {
            entry.title = nameMatch[1].str();
        }

        std::smatch dateMatch;
        if (std::regex_search(context, dateMatch, dateAddedRegex)) {
            entry.dateAdded = chromiumTimeToUnix(std::stoll(dateMatch[1].str()));
        }

        bookmarks_.push_back(entry);
        ++urlIt;
        count++;
    }

    AuditLog::instance().log("INFO", "BROWSER_BOOKMARKS_PARSED",
        browserName + " bookmarks: " + std::to_string(count) + " entries from " + profileName);

    return true;
}

// ============================================================================
// Firefox Parsing
// ============================================================================

bool WindowsBrowserParser::parseFirefox(const std::string& placesDbPath,
                                         const std::string& profileName) {
    sqlite3* db = nullptr;
    if (!openDatabase(placesDbPath, &db)) {
        return false;
    }

    bool success = true;
    success &= parseFirefoxHistory(db, profileName);
    success &= parseFirefoxDownloads(db, profileName);
    success &= parseFirefoxBookmarks(db, profileName);

    closeDatabase(db);

    // Parse cookies from separate file
    std::string cookiesPath = fs::path(placesDbPath).parent_path().string() + "/cookies.sqlite";
    if (fs::exists(cookiesPath)) {
        sqlite3* cookiesDb = nullptr;
        if (openDatabase(cookiesPath, &cookiesDb)) {
            parseFirefoxCookies(cookiesDb, profileName);
            closeDatabase(cookiesDb);
        }
    }

    return success;
}

bool WindowsBrowserParser::parseFirefoxHistory(sqlite3* db, const std::string& profileName) {
    const char* query = 
        "SELECT p.url, p.title, p.visit_count, h.visit_date, h.visit_type "
        "FROM moz_places p "
        "LEFT JOIN moz_historyvisits h ON p.id = h.place_id "
        "WHERE p.url NOT LIKE 'place:%' "
        "ORDER BY h.visit_date DESC "
        "LIMIT 10000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        setError("Failed to prepare Firefox history query: " + std::string(sqlite3_errmsg(db)));
        return false;
    }

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserHistoryEntry entry;
        entry.browserName = "Firefox";
        entry.profileName = profileName;

        const char* url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        entry.url = url ? url : "";

        const char* title = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        entry.title = title ? title : "";

        entry.visitCount = sqlite3_column_int(stmt, 2);
        entry.visitTime = firefoxTimeToUnix(sqlite3_column_int64(stmt, 3));

        // Firefox visit types
        int visitType = sqlite3_column_int(stmt, 4);
        switch (visitType) {
            case 1: entry.visitType = "link"; break;
            case 2: entry.visitType = "typed"; break;
            case 3: entry.visitType = "bookmark"; break;
            case 4: entry.visitType = "embed"; break;
            case 5: entry.visitType = "redirect_permanent"; break;
            case 6: entry.visitType = "redirect_temporary"; break;
            case 7: entry.visitType = "download"; break;
            case 8: entry.visitType = "framed_link"; break;
            default: entry.visitType = "other"; break;
        }

        history_.push_back(entry);
        count++;
    }

    sqlite3_finalize(stmt);

    AuditLog::instance().log("INFO", "BROWSER_HISTORY_PARSED",
        "Firefox history: " + std::to_string(count) + " entries from " + profileName);

    return true;
}

bool WindowsBrowserParser::parseFirefoxDownloads(sqlite3* db, const std::string& profileName) {
    const char* query = 
        "SELECT a.content, a.dateAdded "
        "FROM moz_annos a "
        "JOIN moz_anno_attributes aa ON a.anno_attribute_id = aa.id "
        "WHERE aa.name = 'downloads/destinationFileURI' "
        "ORDER BY a.dateAdded DESC "
        "LIMIT 5000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        return true; // Downloads might use different storage
    }

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserDownloadEntry entry;
        entry.browserName = "Firefox";
        entry.profileName = profileName;

        const char* content = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        if (content) {
            // Parse file:// URI
            std::string uri(content);
            if (uri.substr(0, 7) == "file://") {
                entry.targetPath = uri.substr(7);
                entry.fileName = fs::path(entry.targetPath).filename().string();
            }
        }

        entry.startTime = firefoxTimeToUnix(sqlite3_column_int64(stmt, 1));
        entry.state = "complete";

        downloads_.push_back(entry);
        count++;
    }

    sqlite3_finalize(stmt);

    return true;
}

bool WindowsBrowserParser::parseFirefoxCookies(sqlite3* db, const std::string& profileName) {
    const char* query = 
        "SELECT host, name, path, creationTime, expiry, lastAccessed, "
        "isSecure, isHttpOnly, sameSite "
        "FROM moz_cookies "
        "ORDER BY lastAccessed DESC "
        "LIMIT 5000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        return true;
    }

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserCookieEntry entry;
        entry.browserName = "Firefox";
        entry.profileName = profileName;

        const char* domain = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        entry.domain = domain ? domain : "";

        const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        entry.name = name ? name : "";

        const char* path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        entry.path = path ? path : "";

        entry.creationTime = firefoxTimeToUnix(sqlite3_column_int64(stmt, 3));
        entry.expirationTime = sqlite3_column_int64(stmt, 4); // Already Unix timestamp
        entry.lastAccessTime = firefoxTimeToUnix(sqlite3_column_int64(stmt, 5));

        entry.isSecure = sqlite3_column_int(stmt, 6) != 0;
        entry.isHttpOnly = sqlite3_column_int(stmt, 7) != 0;

        int sameSite = sqlite3_column_int(stmt, 8);
        switch (sameSite) {
            case 0: entry.sameSite = "none"; break;
            case 1: entry.sameSite = "lax"; break;
            case 2: entry.sameSite = "strict"; break;
            default: entry.sameSite = "unspecified"; break;
        }

        cookies_.push_back(entry);
        count++;
    }

    sqlite3_finalize(stmt);

    AuditLog::instance().log("INFO", "BROWSER_COOKIES_PARSED",
        "Firefox cookies: " + std::to_string(count) + " entries from " + profileName);

    return true;
}

bool WindowsBrowserParser::parseFirefoxLogins(const std::string& loginsJsonPath,
                                               const std::string& profileName) {
    // Firefox stores logins in logins.json
    std::ifstream file(loginsJsonPath);
    if (!file) {
        return true;
    }

    // Basic JSON parsing for login entries
    std::stringstream buffer;
    buffer << file.rdbuf();
    std::string content = buffer.str();

    std::regex hostnameRegex("\"hostname\"\\s*:\\s*\"([^\"]+)\"");
    std::regex usernameRegex("\"encryptedUsername\"\\s*:\\s*\"([^\"]+)\"");
    
    // Just count entries for now - actual parsing would need proper JSON library
    std::sregex_iterator it(content.begin(), content.end(), hostnameRegex);
    std::sregex_iterator end;

    int count = 0;
    while (it != end) {
        BrowserLoginEntry entry;
        entry.browserName = "Firefox";
        entry.profileName = profileName;
        entry.url = (*it)[1].str();
        logins_.push_back(entry);
        ++it;
        count++;
    }

    AuditLog::instance().log("INFO", "BROWSER_LOGINS_PARSED",
        "Firefox logins: " + std::to_string(count) + " entries from " + profileName);

    return true;
}

bool WindowsBrowserParser::parseFirefoxBookmarks(sqlite3* db, const std::string& profileName) {
    const char* query = 
        "SELECT b.title, p.url, b.dateAdded, b.lastModified "
        "FROM moz_bookmarks b "
        "JOIN moz_places p ON b.fk = p.id "
        "WHERE b.type = 1 AND p.url NOT LIKE 'place:%' "
        "ORDER BY b.dateAdded DESC "
        "LIMIT 5000";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        return true;
    }

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        BrowserBookmarkEntry entry;
        entry.browserName = "Firefox";
        entry.profileName = profileName;

        const char* title = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        entry.title = title ? title : "";

        const char* url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        entry.url = url ? url : "";

        entry.dateAdded = firefoxTimeToUnix(sqlite3_column_int64(stmt, 2));
        entry.dateModified = firefoxTimeToUnix(sqlite3_column_int64(stmt, 3));

        bookmarks_.push_back(entry);
        count++;
    }

    sqlite3_finalize(stmt);

    AuditLog::instance().log("INFO", "BROWSER_BOOKMARKS_PARSED",
        "Firefox bookmarks: " + std::to_string(count) + " entries from " + profileName);

    return true;
}
