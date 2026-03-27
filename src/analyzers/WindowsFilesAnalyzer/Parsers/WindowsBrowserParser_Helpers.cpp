// WindowsBrowserParser_Helpers.cpp
// Helper functions and base methods for browser parsing

#include "WindowsBrowserParser.h"
#include <fstream>

namespace BrowserHelpers {

std::string browserTypeToString(BrowserType type) {
    switch (type) {
        case BrowserType::CHROME: return "Chrome";
        case BrowserType::EDGE: return "Edge";
        case BrowserType::FIREFOX: return "Firefox";
        case BrowserType::INTERNET_EXPLORER: return "Internet Explorer";
        case BrowserType::UNKNOWN: return "Unknown";
        default: return "Unknown";
    }
}

std::string extractProfileName(const std::string& path) {
    auto lastSlash = path.find_last_of("/\\");
    if (lastSlash != std::string::npos) {
        return path.substr(lastSlash + 1);
    }
    return "Default";
}

bool isValidSqliteDb(const std::string& path) {
    if (path.empty() || !std::filesystem::exists(path)) {
        return false;
    }

    sqlite3* db = nullptr;
    if (sqlite3_open_v2(path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) == SQLITE_OK) {
        sqlite3_close(db);
        return true;
    }
    return false;
}

} // namespace BrowserHelpers

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
}

bool WindowsBrowserParser::openDatabase(const std::string& dbPath, sqlite3** db) {
    if (dbPath.empty() || !std::filesystem::exists(dbPath)) {
        setError("Database file not found: " + dbPath);
        return false;
    }

    int rc = sqlite3_open_v2(dbPath.c_str(), db, SQLITE_OPEN_READONLY, nullptr);
    if (rc != SQLITE_OK) {
        setError("Failed to open database: " + std::string(sqlite3_errmsg(*db)));
        *db = nullptr;
        return false;
    }
    return true;
}

void WindowsBrowserParser::closeDatabase(sqlite3* db) {
    if (db) {
        sqlite3_close(db);
    }
}

std::string WindowsBrowserParser::visitTypeToString(int type) {
    // Chromium transition types
    switch (type) {
        case 0: return "LINK";
        case 1: return "TYPED";
        case 2: return "BOOKMARK";
        case 3: return "AUTO_SUBFRAME";
        case 4: return "MANUAL_SUBFRAME";
        case 5: return "GENERATED";
        case 6: return "AUTO_MARK";
        case 7: return "AUTO_COMPLETE";
        case 8: return "FORM_SUBMIT";
        case 12: return "RELOAD";
        default: return "UNKNOWN";
    }
}