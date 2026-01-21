#pragma once
#include <sqlite3.h>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>

class SQLiteHelper {
public:
    // Original function
    static nlohmann::json get_file_summary(const std::string& db_path);

    // Timeline Analysis Endpoints
    // Timeline Analysis Endpoints
    /**
     * @brief Get comprehensive timeline from all sources
     * @param raw_db Path to raw database
     * @param events_db Path to events database
     * @param start_time Optional start timestamp filter
     * @param end_time Optional end timestamp filter
     * @return JSON object with timeline events
     */
    static nlohmann::json get_comprehensive_timeline(const std::string& raw_db, const std::string& events_db,
                                                     const std::string& start_time = "", const std::string& end_time = "");

    /**
     * @brief Get file system activity timeline
     * @param raw_db Path to raw database
     * @param events_db Path to events database
     * @param file_path Optional file path filter
     * @param inode Optional inode filter
     * @return JSON object with file activity
     */
    static nlohmann::json get_file_activity_timeline(const std::string& raw_db, const std::string& events_db,
                                                     const std::string& file_path = "", int64_t inode = -1);

    /**
     * @brief Analyze suspicious patterns
     * @param raw_db Path to raw database
     * @param events_db Path to events database
     * @return JSON object with suspicious patterns
     */
    static nlohmann::json get_suspicious_patterns(const std::string& raw_db, const std::string& events_db);

    /**
     * @brief Analyze user activity
     * @param raw_db Path to raw database
     * @param events_db Path to events database
     * @return JSON object with user activity analysis
     */
    static nlohmann::json get_user_activity_analysis(const std::string& raw_db, const std::string& events_db);

    // File Analysis Endpoints
    // File Analysis Endpoints
    /**
     * @brief Get largest files
     * @param files_db Path to files database
     * @param limit Maximum number of files to return
     * @return JSON array of largest files
     */
    static nlohmann::json get_largest_files(const std::string& files_db, int limit = 50);

    /**
     * @brief Get recently modified/accessed files
     * @param files_db Path to files database
     * @param hours Time window in hours (string)
     * @return JSON array of recent files
     */
    static nlohmann::json get_recent_files(const std::string& files_db, const std::string& hours = "24");

    /**
     * @brief Identify suspicious files
     * @param raw_db Path to raw database
     * @param files_db Path to files database
     * @return JSON array of suspicious files
     */
    static nlohmann::json get_suspicious_files(const std::string& raw_db, const std::string& files_db);

    /**
     * @brief Find duplicate files
     * @param files_db Path to files database
     * @return JSON array of duplicate file groups
     */
    static nlohmann::json get_duplicate_files(const std::string& files_db);

    /**
     * @brief Analyze file extension distribution
     * @param files_db Path to files database
     * @return JSON object with extension stats
     */
    static nlohmann::json get_extensions_analysis(const std::string& files_db);

    /**
     * @brief Get LLM analysis results
     * @param descriptions_db Path to descriptions database
     * @return JSON array of LLM results
     */
    static nlohmann::json get_llm_results(const std::string& descriptions_db);

    // Android Forensics Specialized Endpoints
    // Android Forensics Specialized Endpoints
    /**
     * @brief Get Android communication summary
     * @param android_db Path to Android database
     * @return JSON object with communication stats
     */
    static nlohmann::json get_android_communication_summary(const std::string& android_db);

    /**
     * @brief Get Android app usage stats
     * @param android_db Path to Android database
     * @return JSON object with app usage stats
     */
    static nlohmann::json get_android_app_usage(const std::string& android_db);

    /**
     * @brief Get Android device info
     * @param android_db Path to Android database
     * @return JSON object with device info
     */
    static nlohmann::json get_android_device_info(const std::string& android_db);

    /**
     * @brief Analyze Android media files
     * @param android_db Path to Android database
     * @return JSON object with media stats
     */
    static nlohmann::json get_android_media_analysis(const std::string& android_db);

    // Statistical Analysis Endpoints
    // Statistical Analysis Endpoints
    /**
     * @brief Get overview statistics
     * @param raw_db Path to raw database
     * @param files_db Path to files database
     * @param events_db Path to events database
     * @return JSON object with overview stats
     */
    static nlohmann::json get_overview_statistics(const std::string& raw_db, const std::string& files_db, const std::string& events_db);

    /**
     * @brief Analyze file distribution
     * @param files_db Path to files database
     * @return JSON object with distribution stats
     */
    static nlohmann::json get_file_distribution_analysis(const std::string& files_db);

    /**
     * @brief Analyze activity patterns
     * @param events_db Path to events database
     * @return JSON object with activity patterns
     */
    static nlohmann::json get_activity_patterns(const std::string& events_db);

    /**
     * @brief Analyze deleted files
     * @param raw_db Path to raw database
     * @return JSON object with deleted files stats
     */
    static nlohmann::json get_deleted_files_analysis(const std::string& raw_db);

private:
    // Helper methods
    static sqlite3* open_database(const std::string& db_path, nlohmann::json& error_result);
    static nlohmann::json execute_query(sqlite3* db, const std::string& sql);
    static std::string format_timestamp(int64_t timestamp);
    static int64_t parse_timestamp(const std::string& time_str);
    static bool is_suspicious_extension(const std::string& ext);
    static bool is_suspicious_path(const std::string& path);
};