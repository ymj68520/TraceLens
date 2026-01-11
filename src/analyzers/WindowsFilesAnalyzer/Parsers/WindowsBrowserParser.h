// WindowsBrowserParser.h
// Comprehensive browser data parser for Windows forensic analysis
// Supports: Chrome, Edge (Chromium), Firefox, Internet Explorer

#pragma once
#ifndef WINDOWS_BROWSER_PARSER_H
#define WINDOWS_BROWSER_PARSER_H

#include <string>
#include <vector>
#include <cstdint>
#include <memory>
#include <sqlite3.h>
#include "WindowsDataTypes.h"  // Use unified data structures

// ============================================================================
// Browser Data Structures
// ============================================================================
// NOTE: All browser data structures (BrowserType, BrowserProfile, 
// BrowserHistoryEntry, BrowserDownloadEntry, etc.) are now defined in
// WindowsDataTypes.h for unified usage across the project.


// ============================================================================
// Browser Parser Class
// ============================================================================

class WindowsBrowserParser {
public:
    WindowsBrowserParser();
    ~WindowsBrowserParser();

    // Set the extraction directory (where browser files are extracted)
    void setExtractDirectory(const std::string& path) { extractDir_ = path; }

    // Parse browser data from extracted profile
    bool parseProfile(const BrowserProfile& profile);

    // Convenience methods to parse specific browsers from standard paths
    bool parseChrome(const std::string& historyDbPath, const std::string& profileName = "Default");
    bool parseEdge(const std::string& historyDbPath, const std::string& profileName = "Default");
    bool parseFirefox(const std::string& placesDbPath, const std::string& profileName = "default");

    // Get parsed data
    std::vector<BrowserHistoryEntry> getHistory() const { return history_; }
    std::vector<BrowserDownloadEntry> getDownloads() const { return downloads_; }
    std::vector<BrowserBookmarkEntry> getBookmarks() const { return bookmarks_; }
    std::vector<BrowserCookieEntry> getCookies() const { return cookies_; }
    std::vector<BrowserLoginEntry> getLogins() const { return logins_; }

    // Statistics
    size_t getHistoryCount() const { return history_.size(); }
    size_t getDownloadCount() const { return downloads_.size(); }
    size_t getBookmarkCount() const { return bookmarks_.size(); }

    // Error handling
    std::string getLastError() const { return lastError_; }
    bool hasError() const { return !lastError_.empty(); }
    void clearError() { lastError_.clear(); }

    // Clear all parsed data
    void clear();

private:
    // Chrome/Edge parsing (Chromium-based)
    bool parseChromiumHistory(sqlite3* db, const std::string& browserName, 
                              const std::string& profileName);
    bool parseChromiumDownloads(sqlite3* db, const std::string& browserName,
                                const std::string& profileName);
    bool parseChromiumCookies(sqlite3* db, const std::string& browserName,
                              const std::string& profileName);
    bool parseChromiumLogins(sqlite3* db, const std::string& browserName,
                             const std::string& profileName);
    bool parseChromiumBookmarks(const std::string& bookmarksJsonPath,
                                const std::string& browserName,
                                const std::string& profileName);

    // Firefox parsing
    bool parseFirefoxHistory(sqlite3* db, const std::string& profileName);
    bool parseFirefoxDownloads(sqlite3* db, const std::string& profileName);
    bool parseFirefoxCookies(sqlite3* db, const std::string& profileName);
    bool parseFirefoxLogins(const std::string& loginsJsonPath,
                            const std::string& profileName);
    bool parseFirefoxBookmarks(sqlite3* db, const std::string& profileName);

    // Helper methods
    bool openDatabase(const std::string& dbPath, sqlite3** db);
    void closeDatabase(sqlite3* db);
    int64_t chromiumTimeToUnix(int64_t chromiumTime);
    int64_t firefoxTimeToUnix(int64_t prTime);
    std::string visitTypeToString(int type);
    void setError(const std::string& error);

    // Parsed data storage
    std::vector<BrowserHistoryEntry> history_;
    std::vector<BrowserDownloadEntry> downloads_;
    std::vector<BrowserBookmarkEntry> bookmarks_;
    std::vector<BrowserCookieEntry> cookies_;
    std::vector<BrowserLoginEntry> logins_;

    std::string extractDir_;
    std::string lastError_;
};

// ============================================================================
// Helper Functions
// ============================================================================

namespace BrowserHelpers {

/**
 * Detect browser type from database path
 */
BrowserType detectBrowserType(const std::string& dbPath);

/**
 * Get human-readable browser name
 */
std::string browserTypeToString(BrowserType type);

/**
 * Convert Chromium timestamp (microseconds since 1601-01-01) to Unix timestamp
 */
int64_t chromiumTimeToUnix(int64_t chromiumTime);

/**
 * Convert Firefox PRTime (microseconds since 1970-01-01) to Unix timestamp
 */
int64_t firefoxTimeToUnix(int64_t prTime);

/**
 * Extract profile name from path
 */
std::string extractProfileName(const std::string& path);

/**
 * Check if file is a valid SQLite database
 */
bool isValidSqliteDb(const std::string& path);

} // namespace BrowserHelpers

#endif // WINDOWS_BROWSER_PARSER_H
