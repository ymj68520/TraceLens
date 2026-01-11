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
    static nlohmann::json get_comprehensive_timeline(const std::string& raw_db, const std::string& events_db,
                                                     const std::string& start_time = "", const std::string& end_time = "");
    static nlohmann::json get_file_activity_timeline(const std::string& raw_db, const std::string& events_db,
                                                     const std::string& file_path = "", int64_t inode = -1);
    static nlohmann::json get_suspicious_patterns(const std::string& raw_db, const std::string& events_db);
    static nlohmann::json get_user_activity_analysis(const std::string& raw_db, const std::string& events_db);

    // File Analysis Endpoints
    static nlohmann::json get_largest_files(const std::string& files_db, int limit = 50);
    static nlohmann::json get_recent_files(const std::string& files_db, const std::string& hours = "24");
    static nlohmann::json get_suspicious_files(const std::string& raw_db, const std::string& files_db);
    static nlohmann::json get_duplicate_files(const std::string& files_db);
    static nlohmann::json get_extensions_analysis(const std::string& files_db);

    // Android Forensics Specialized Endpoints
    static nlohmann::json get_android_communication_summary(const std::string& android_db);
    static nlohmann::json get_android_app_usage(const std::string& android_db);
    static nlohmann::json get_android_device_info(const std::string& android_db);
    static nlohmann::json get_android_media_analysis(const std::string& android_db);

    // Statistical Analysis Endpoints
    static nlohmann::json get_overview_statistics(const std::string& raw_db, const std::string& files_db, const std::string& events_db);
    static nlohmann::json get_file_distribution_analysis(const std::string& files_db);
    static nlohmann::json get_activity_patterns(const std::string& events_db);
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