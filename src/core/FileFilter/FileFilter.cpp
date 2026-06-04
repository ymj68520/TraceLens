#include "FileFilter.h"
#include "PathManager/PathManager.h"
#include "AuditLog/AuditLog.h"

#include <nlohmann/json.hpp>
#include <fstream>
#include <iostream>
#include <algorithm>
#include <filesystem>
#include <regex>
#include <sstream>

namespace forensics {

namespace fs = std::filesystem;
using json = nlohmann::json;

// ============================================================================
// Construction / Destruction
// ============================================================================

FileFilter::FileFilter() = default;
FileFilter::~FileFilter() = default;

// ============================================================================
// Profile loading
// ============================================================================

FilterProfile FileFilter::loadProfile(const std::string& profilePath) {
    std::ifstream file(profilePath);
    if (!file.is_open()) {
        throw std::runtime_error("Cannot open filter profile: " + profilePath);
    }

    json j;
    try {
        j = json::parse(file);
    } catch (const json::parse_error& e) {
        throw std::runtime_error("Invalid JSON in profile " + profilePath + ": " + e.what());
    }

    FilterProfile profile;
    profile.name = j.value("profile_name", "unnamed");
    profile.description = j.value("description", "");
    profile.version = j.value("version", "1.0.0");

    // Parse combine_mode
    std::string mode = j.value("combine_mode", "exclude_wins");
    if (mode == "include_wins") {
        profile.combine_mode = FilterCombineMode::IncludeWins;
    } else if (mode == "include_only") {
        profile.combine_mode = FilterCombineMode::IncludeOnly;
    } else {
        profile.combine_mode = FilterCombineMode::ExcludeWins;
    }

    // Parse include condition
    if (j.contains("include")) {
        auto& inc = j["include"];
        if (inc.contains("extensions"))
            profile.include.extensions = inc["extensions"].get<std::vector<std::string>>();
        if (inc.contains("path_patterns"))
            profile.include.path_patterns = inc["path_patterns"].get<std::vector<std::string>>();
        if (inc.contains("filename_patterns"))
            profile.include.filename_patterns = inc["filename_patterns"].get<std::vector<std::string>>();
        profile.include.min_size = inc.value("min_size", (int64_t)0);
        profile.include.max_size = inc.value("max_size", (int64_t)0);
        profile.include.include_deleted = inc.value("include_deleted", true);
        profile.include.include_allocated = inc.value("include_allocated", true);
    }

    // Parse exclude condition
    if (j.contains("exclude")) {
        auto& exc = j["exclude"];
        if (exc.contains("extensions"))
            profile.exclude.extensions = exc["extensions"].get<std::vector<std::string>>();
        if (exc.contains("path_patterns"))
            profile.exclude.path_patterns = exc["path_patterns"].get<std::vector<std::string>>();
        if (exc.contains("filename_patterns"))
            profile.exclude.filename_patterns = exc["filename_patterns"].get<std::vector<std::string>>();
        profile.exclude.min_size = exc.value("min_size", (int64_t)0);
        profile.exclude.max_size = exc.value("max_size", (int64_t)0);
        profile.exclude.include_deleted = exc.value("include_deleted", true);
        profile.exclude.include_allocated = exc.value("include_allocated", true);
    }

    return profile;
}

std::vector<std::tuple<std::string, std::string, std::string>>
FileFilter::listProfiles(const std::string& profilesDir) {
    std::vector<std::tuple<std::string, std::string, std::string>> result;

    if (!fs::exists(profilesDir) || !fs::is_directory(profilesDir)) {
        return result;
    }

    for (const auto& entry : fs::directory_iterator(profilesDir)) {
        if (entry.is_regular_file() && entry.path().extension() == ".json") {
            try {
                auto profile = loadProfile(entry.path().string());
                result.emplace_back(
                    entry.path().filename().string(),
                    profile.name,
                    profile.description
                );
            } catch (const std::exception& e) {
                // Skip invalid profiles
                std::cerr << "Warning: Skipping invalid profile "
                          << entry.path().filename() << ": " << e.what() << std::endl;
            }
        }
    }

    return result;
}

// ============================================================================
// Glob / pattern matching
// ============================================================================

bool FileFilter::matchGlob(const std::string& pattern, const std::string& text) {
    // Convert glob pattern to regex
    // Supports: * (any chars), ? (single char)
    std::string regexStr;
    regexStr.reserve(pattern.size() * 2);

    for (size_t i = 0; i < pattern.size(); ++i) {
        char c = pattern[i];
        switch (c) {
            case '*':
                regexStr += ".*";
                break;
            case '?':
                regexStr += '.';
                break;
            case '.':
            case '(':
            case ')':
            case '+':
            case '^':
            case '$':
            case '|':
            case '[':
            case ']':
            case '{':
            case '}':
            case '\\':
                regexStr += '\\';
                regexStr += c;
                break;
            default:
                regexStr += c;
                break;
        }
    }

    try {
        std::regex re(regexStr, std::regex::icase);
        return std::regex_match(text, re);
    } catch (const std::regex_error&) {
        // Fallback: simple contains check
        return text.find(pattern) != std::string::npos;
    }
}

bool FileFilter::matchPathPatterns(const std::vector<std::string>& patterns,
                                   const std::string& path) {
    if (patterns.empty()) return false;

    // Normalize path separators
    std::string normalizedPath = path;
    std::replace(normalizedPath.begin(), normalizedPath.end(), '\\', '/');

    for (const auto& pattern : patterns) {
        std::string normalizedPattern = pattern;
        std::replace(normalizedPattern.begin(), normalizedPattern.end(), '\\', '/');

        if (matchGlob(normalizedPattern, normalizedPath)) {
            return true;
        }

        // Also check if path contains the pattern as a substring
        // (for patterns like "*/com.tencent.mm/*" matching deep paths)
        if (normalizedPattern.find('*') != std::string::npos) {
            // Extract the core part between wildcards for substring matching
            std::string core;
            for (char c : normalizedPattern) {
                if (c != '*') core += c;
            }
            if (!core.empty() && normalizedPath.find(core) != std::string::npos) {
                return true;
            }
        }
    }
    return false;
}

bool FileFilter::matchFilenamePatterns(const std::vector<std::string>& patterns,
                                       const std::string& filename) {
    if (patterns.empty()) return false;

    for (const auto& pattern : patterns) {
        if (matchGlob(pattern, filename)) {
            return true;
        }
    }
    return false;
}

std::string FileFilter::getExtension(const std::string& filename) {
    auto pos = filename.rfind('.');
    if (pos == std::string::npos) return "";

    std::string ext = filename.substr(pos);
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    return ext;
}

bool FileFilter::matchExtensions(const std::vector<std::string>& extensions,
                                 const std::string& filename) {
    if (extensions.empty()) return false;

    std::string ext = getExtension(filename);
    if (ext.empty()) return false;

    for (const auto& allowedExt : extensions) {
        std::string lowerAllowed = allowedExt;
        std::transform(lowerAllowed.begin(), lowerAllowed.end(), lowerAllowed.begin(), ::tolower);
        if (ext == lowerAllowed) {
            return true;
        }
    }
    return false;
}

// ============================================================================
// Condition matching
// ============================================================================

bool FileFilter::matchesCondition(const std::string& name, const std::string& path,
                                  int64_t size, int is_deleted, int is_allocated,
                                  const FilterCondition& condition) {
    // Check allocation/deletion filters
    if (!condition.include_deleted && is_deleted) return false;
    if (!condition.include_allocated && !is_allocated) return false;

    // Check size range
    if (condition.min_size > 0 && size < condition.min_size) return false;
    if (condition.max_size > 0 && size > condition.max_size) return false;

    // If no content filters specified, matches by default
    bool hasContentFilter = !condition.extensions.empty() ||
                           !condition.path_patterns.empty() ||
                           !condition.filename_patterns.empty();

    if (!hasContentFilter) return true;

    // Check extensions
    if (matchExtensions(condition.extensions, name)) return true;

    // Check path patterns
    if (matchPathPatterns(condition.path_patterns, path)) return true;

    // Check filename patterns
    if (matchFilenamePatterns(condition.filename_patterns, name)) return true;

    return false;
}

// ============================================================================
// Database operations
// ============================================================================

bool FileFilter::createFilteredSchema(sqlite3* db) {
    const char* sql = R"(
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inode INTEGER,
            name TEXT,
            path TEXT,
            size INTEGER,
            atime INTEGER,
            mtime INTEGER,
            ctime INTEGER,
            crtime INTEGER,
            type TEXT,
            md5 TEXT,
            is_deleted INTEGER,
            is_allocated INTEGER,
            permissions TEXT,
            uid INTEGER,
            gid INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_files_inode ON files(inode);
        CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
        CREATE INDEX IF NOT EXISTS idx_files_type ON files(type);
        CREATE INDEX IF NOT EXISTS idx_files_deleted ON files(is_deleted);
    )";

    char* errMsg = nullptr;
    int rc = sqlite3_exec(db, sql, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Error creating filtered schema: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }
    return true;
}

// ============================================================================
// Main filter operation
// ============================================================================

FilterStats FileFilter::applyFilter(const std::string& sourceDbPath,
                                    const std::string& filteredDbPath,
                                    const FilterProfile& profile) {
    FilterStats stats;

    // Open source database
    sqlite3* sourceDb = nullptr;
    if (sqlite3_open(sourceDbPath.c_str(), &sourceDb) != SQLITE_OK) {
        std::cerr << "Error opening source database: " << sqlite3_errmsg(sourceDb) << std::endl;
        if (sourceDb) sqlite3_close(sourceDb);
        return stats;
    }

    // Create filtered database
    sqlite3* filteredDb = nullptr;
    if (sqlite3_open(filteredDbPath.c_str(), &filteredDb) != SQLITE_OK) {
        std::cerr << "Error creating filtered database: " << sqlite3_errmsg(filteredDb) << std::endl;
        if (filteredDb) sqlite3_close(filteredDb);
        sqlite3_close(sourceDb);
        return stats;
    }

    // Set performance pragmas
    sqlite3_exec(filteredDb, "PRAGMA journal_mode=WAL;", nullptr, nullptr, nullptr);
    sqlite3_exec(filteredDb, "PRAGMA synchronous=NORMAL;", nullptr, nullptr, nullptr);
    sqlite3_busy_timeout(filteredDb, 5000);

    if (!createFilteredSchema(filteredDb)) {
        sqlite3_close(filteredDb);
        sqlite3_close(sourceDb);
        return stats;
    }

    // Begin transaction for bulk insert
    sqlite3_exec(filteredDb, "BEGIN TRANSACTION;", nullptr, nullptr, nullptr);

    // Prepare insert statement
    const char* insertSql = R"(
        INSERT INTO files (inode, name, path, size, atime, mtime, ctime, crtime,
                          type, md5, is_deleted, is_allocated, permissions, uid, gid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    )";
    sqlite3_stmt* insertStmt = nullptr;
    if (sqlite3_prepare_v2(filteredDb, insertSql, -1, &insertStmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing insert statement" << std::endl;
        sqlite3_exec(filteredDb, "ROLLBACK;", nullptr, nullptr, nullptr);
        sqlite3_close(filteredDb);
        sqlite3_close(sourceDb);
        return stats;
    }

    // Read all files from source
    const char* selectSql = R"(
        SELECT inode, name, path, size, atime, mtime, ctime, crtime,
               type, md5, is_deleted, is_allocated, permissions, uid, gid
        FROM files;
    )";
    sqlite3_stmt* selectStmt = nullptr;
    if (sqlite3_prepare_v2(sourceDb, selectSql, -1, &selectStmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing select statement: " << sqlite3_errmsg(sourceDb) << std::endl;
        sqlite3_finalize(insertStmt);
        sqlite3_exec(filteredDb, "ROLLBACK;", nullptr, nullptr, nullptr);
        sqlite3_close(filteredDb);
        sqlite3_close(sourceDb);
        return stats;
    }

    std::cout << "[FileFilter] Applying profile: " << profile.name << std::endl;
    std::cout << "[FileFilter] Description: " << profile.description << std::endl;

    // Process each file
    while (sqlite3_step(selectStmt) == SQLITE_ROW) {
        stats.total_files++;

        // Extract fields
        int64_t inode = sqlite3_column_int64(selectStmt, 0);
        const char* namePtr = reinterpret_cast<const char*>(sqlite3_column_text(selectStmt, 1));
        const char* pathPtr = reinterpret_cast<const char*>(sqlite3_column_text(selectStmt, 2));
        int64_t size = sqlite3_column_int64(selectStmt, 3);
        int64_t atime = sqlite3_column_int64(selectStmt, 4);
        int64_t mtime = sqlite3_column_int64(selectStmt, 5);
        int64_t ctime = sqlite3_column_int64(selectStmt, 6);
        int64_t crtime = sqlite3_column_int64(selectStmt, 7);
        const char* typePtr = reinterpret_cast<const char*>(sqlite3_column_text(selectStmt, 8));
        const char* md5Ptr = reinterpret_cast<const char*>(sqlite3_column_text(selectStmt, 9));
        int is_deleted = sqlite3_column_int(selectStmt, 10);
        int is_allocated = sqlite3_column_int(selectStmt, 11);
        const char* permPtr = reinterpret_cast<const char*>(sqlite3_column_text(selectStmt, 12));
        int uid = sqlite3_column_int(selectStmt, 13);
        int gid = sqlite3_column_int(selectStmt, 14);

        std::string name = namePtr ? namePtr : "";
        std::string path = pathPtr ? pathPtr : "";

        // Apply filter logic
        bool included = false;

        switch (profile.combine_mode) {
            case FilterCombineMode::IncludeOnly:
                // Only include rules apply
                included = matchesCondition(name, path, size, is_deleted, is_allocated,
                                          profile.include);
                break;

            case FilterCombineMode::IncludeWins:
                // Include takes priority
                if (matchesCondition(name, path, size, is_deleted, is_allocated,
                                    profile.include)) {
                    included = true;
                } else if (!matchesCondition(name, path, size, is_deleted, is_allocated,
                                            profile.exclude)) {
                    // Not excluded either — include if include rules are non-empty
                    included = !profile.include.extensions.empty() ||
                              !profile.include.path_patterns.empty() ||
                              !profile.include.filename_patterns.empty();
                }
                break;

            case FilterCombineMode::ExcludeWins:
            default:
                // Default: if exclude matches, skip; otherwise check include
                if (matchesCondition(name, path, size, is_deleted, is_allocated,
                                    profile.exclude)) {
                    included = false;
                } else {
                    included = matchesCondition(name, path, size, is_deleted, is_allocated,
                                              profile.include);
                }
                break;
        }

        if (included) {
            stats.included_files++;

            // Bind and insert
            sqlite3_bind_int64(insertStmt, 1, inode);
            sqlite3_bind_text(insertStmt, 2, name.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(insertStmt, 3, path.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_int64(insertStmt, 4, size);
            sqlite3_bind_int64(insertStmt, 5, atime);
            sqlite3_bind_int64(insertStmt, 6, mtime);
            sqlite3_bind_int64(insertStmt, 7, ctime);
            sqlite3_bind_int64(insertStmt, 8, crtime);
            sqlite3_bind_text(insertStmt, 9, typePtr ? typePtr : "", -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(insertStmt, 10, md5Ptr ? md5Ptr : "", -1, SQLITE_TRANSIENT);
            sqlite3_bind_int(insertStmt, 11, is_deleted);
            sqlite3_bind_int(insertStmt, 12, is_allocated);
            sqlite3_bind_text(insertStmt, 13, permPtr ? permPtr : "", -1, SQLITE_TRANSIENT);
            sqlite3_bind_int(insertStmt, 14, uid);
            sqlite3_bind_int(insertStmt, 15, gid);

            sqlite3_step(insertStmt);
            sqlite3_reset(insertStmt);
        } else {
            stats.excluded_files++;
        }
    }

    sqlite3_finalize(selectStmt);
    sqlite3_finalize(insertStmt);

    // Commit transaction
    sqlite3_exec(filteredDb, "COMMIT;", nullptr, nullptr, nullptr);

    sqlite3_close(filteredDb);
    sqlite3_close(sourceDb);

    // Print summary
    std::cout << "[FileFilter] Filter complete:" << std::endl;
    std::cout << "  Total files:    " << stats.total_files << std::endl;
    std::cout << "  Included:       " << stats.included_files << std::endl;
    std::cout << "  Excluded:       " << stats.excluded_files << std::endl;
    std::cout << "  Filtered DB:    " << filteredDbPath << std::endl;

    AuditLog::instance().log("SYSTEM", "FILE_FILTER",
        "Profile: " + profile.name +
        ", Total: " + std::to_string(stats.total_files) +
        ", Included: " + std::to_string(stats.included_files) +
        ", Excluded: " + std::to_string(stats.excluded_files));

    return stats;
}

// ============================================================================
// Profile discovery
// ============================================================================

std::string FileFilter::findProfilesDirectory() {
    // Try multiple locations relative to executable and project root
    auto& pm = PathManager::instance();
    std::vector<std::string> candidates;

    if (pm.isInitialized()) {
        candidates.push_back((pm.getProjectRoot() / "config" / "filter_profiles").string());
        candidates.push_back((pm.getExeDir() / "config" / "filter_profiles").string());
        candidates.push_back((pm.getProjectRoot() / ".." / "config" / "filter_profiles").string());
    }

    // Relative to CWD
    candidates.push_back("config/filter_profiles");
    candidates.push_back("../config/filter_profiles");
    candidates.push_back("../../config/filter_profiles");

    for (const auto& candidate : candidates) {
        if (fs::exists(candidate) && fs::is_directory(candidate)) {
            return candidate;
        }
    }

    return "";
}

FilterStats FileFilter::applyFilterByName(const std::string& sourceDbPath,
                                          const std::string& filteredDbPath,
                                          const std::string& profileName) {
    std::string profilesDir = findProfilesDirectory();
    if (profilesDir.empty()) {
        throw std::runtime_error("Cannot find filter_profiles directory. "
                                 "Searched: config/filter_profiles, ../config/filter_profiles");
    }

    std::string profilePath = profilesDir + "/" + profileName + ".json";
    if (!fs::exists(profilePath)) {
        throw std::runtime_error("Filter profile not found: " + profilePath +
                                 "\nAvailable profiles in " + profilesDir + ":");
    }

    auto profile = loadProfile(profilePath);
    return applyFilter(sourceDbPath, filteredDbPath, profile);
}

} // namespace forensics
