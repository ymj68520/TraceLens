#pragma once
#ifndef FILE_FILTER_H
#define FILE_FILTER_H

#include <string>
#include <vector>
#include <cstdint>
#include <sqlite3.h>

namespace forensics {

/**
 * @brief Filter condition for a single dimension (extensions, paths, etc.)
 */
struct FilterCondition {
    std::vector<std::string> extensions;       // e.g., {".pdf", ".doc"}
    std::vector<std::string> path_patterns;    // glob patterns, e.g., {"*/com.tencent.mm/*"}
    std::vector<std::string> filename_patterns; // glob patterns, e.g., {"*.log", "contacts*"}
    int64_t min_size = 0;                      // 0 = no limit
    int64_t max_size = 0;                      // 0 = no limit
    bool include_deleted = true;
    bool include_allocated = true;
};

/**
 * @brief Combine mode when both include and exclude match
 */
enum class FilterCombineMode {
    ExcludeWins,  // If exclude matches, file is excluded (default, conservative)
    IncludeWins,  // If include matches, file is included (even if exclude matches)
    IncludeOnly   // Only include rules apply; no exclude
};

/**
 * @brief A complete filter profile loaded from JSON
 */
struct FilterProfile {
    std::string name;
    std::string description;
    std::string version;
    FilterCondition include;
    FilterCondition exclude;
    FilterCombineMode combine_mode = FilterCombineMode::ExcludeWins;
};

/**
 * @brief Statistics after filtering
 */
struct FilterStats {
    int64_t total_files = 0;
    int64_t included_files = 0;
    int64_t excluded_files = 0;
};

/**
 * @brief Scenario-based file filter for forensic analysis pipelines
 *
 * Sits between ImageAnalyzer (raw.db) and FileClassifier (files.db) in the
 * analysis pipeline. Filters files based on configurable scenario profiles
 * to focus on relevant artifacts for specific investigation types.
 *
 * Usage:
 *   FileFilter filter;
 *   auto profile = FileFilter::loadProfile("config/filter_profiles/telecom_fraud.json");
 *   auto stats = filter.applyFilter("input_raw.db", "input_filtered.db", profile);
 */
class FileFilter {
public:
    FileFilter();
    ~FileFilter();

    /**
     * @brief Load a filter profile from a JSON configuration file
     * @param profilePath Path to the JSON profile file
     * @return Loaded FilterProfile
     * @throws std::runtime_error if file cannot be parsed
     */
    static FilterProfile loadProfile(const std::string& profilePath);

    /**
     * @brief List available profiles in a directory
     * @param profilesDir Path to the directory containing profile JSON files
     * @return Vector of (filename, profile_name, description) tuples
     */
    static std::vector<std::tuple<std::string, std::string, std::string>>
    listProfiles(const std::string& profilesDir);

    /**
     * @brief Apply filter to create a filtered database
     * @param sourceDbPath Path to the source raw.db
     * @param filteredDbPath Path for the output filtered database
     * @param profile The filter profile to apply
     * @return FilterStats with counts
     */
    FilterStats applyFilter(const std::string& sourceDbPath,
                           const std::string& filteredDbPath,
                           const FilterProfile& profile);

    /**
     * @brief Apply filter by profile name, searching in default config directory
     * @param sourceDbPath Path to the source raw.db
     * @param filteredDbPath Path for the output filtered database
     * @param profileName Name of the profile (without .json extension)
     * @return FilterStats with counts
     */
    FilterStats applyFilterByName(const std::string& sourceDbPath,
                                  const std::string& filteredDbPath,
                                  const std::string& profileName);

private:
    /**
     * @brief Check if a file record matches a filter condition
     */
    bool matchesCondition(const std::string& name, const std::string& path,
                         int64_t size, int is_deleted, int is_allocated,
                         const FilterCondition& condition);

    /**
     * @brief Check if a string matches a glob pattern
     * Supports: * (any chars), ? (single char)
     */
    bool matchGlob(const std::string& pattern, const std::string& text);

    /**
     * @brief Check if a path matches any pattern in the list
     */
    bool matchPathPatterns(const std::vector<std::string>& patterns,
                          const std::string& path);

    /**
     * @brief Check if a filename matches any pattern in the list
     */
    bool matchFilenamePatterns(const std::vector<std::string>& patterns,
                              const std::string& filename);

    /**
     * @brief Check if extension is in the list (case-insensitive)
     */
    bool matchExtensions(const std::vector<std::string>& extensions,
                        const std::string& filename);

    /**
     * @brief Get file extension (lowercase, with dot)
     */
    std::string getExtension(const std::string& filename);

    /**
     * @brief Create filtered database schema (same as raw.db files table)
     */
    bool createFilteredSchema(sqlite3* db);

    /**
     * @brief Find the default config/filter_profiles directory
     */
    static std::string findProfilesDirectory();
};

} // namespace forensics

#endif // FILE_FILTER_H
