#pragma once

#include <string>
#include <vector>
#include <sqlite3.h>

namespace forensics {
namespace WindowsParser {

/**
 * @brief Chromium-based browser data parser
 * Handles parsing of Chrome, Edge, Opera, and other Chromium-based browsers
 */
class ChromiumBrowserParser {
public:
    /**
     * @brief Parse Chromium browser history
     * @param db SQLite database connection
     * @param browserName Name of the browser
     * @param targetDb Target analysis database
     * @return true if successful
     */
    static bool parseHistory(sqlite3* db, const std::string& browserName, sqlite3* targetDb);

    /**
     * @brief Parse Chromium browser downloads
     * @param db SQLite database connection
     * @param browserName Name of the browser
     * @param targetDb Target analysis database
     * @return true if successful
     */
    static bool parseDownloads(sqlite3* db, const std::string& browserName, sqlite3* targetDb);

    /**
     * @brief Parse Chromium browser cookies
     * @param db SQLite database connection
     * @param browserName Name of the browser
     * @param targetDb Target analysis database
     * @return true if successful
     */
    static bool parseCookies(sqlite3* db, const std::string& browserName, sqlite3* targetDb);

    /**
     * @brief Parse Chromium browser logins/passwords
     * @param db SQLite database connection
     * @param browserName Name of the browser
     * @param targetDb Target analysis database
     * @return true if successful
     */
    static bool parseLogins(sqlite3* db, const std::string& browserName, sqlite3* targetDb);

    /**
     * @brief Parse Chromium browser bookmarks
     * @param bookmarksJsonPath Path to bookmarks JSON file
     * @param browserName Name of the browser
     * @param targetDb Target analysis database
     * @return true if successful
     */
    static bool parseBookmarks(const std::string& bookmarksJsonPath,
                               const std::string& browserName,
                               sqlite3* targetDb);
};

} // namespace WindowsParser
} // namespace forensics
