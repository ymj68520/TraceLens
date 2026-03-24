#pragma once
#include <sqlite3.h>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>
#include <fstream>

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
     * @param limit Maximum number of records (default 1000)
     * @param offset Number of records to skip (default 0)
     * @param event_type Optional event type filter
     * @param cluster_events Whether to group similar events into clusters
     * @return JSON object with timeline events
     */
    static nlohmann::json get_comprehensive_timeline(const std::string& raw_db, const std::string& events_db,
                                                     const std::string& start_time = "", const std::string& end_time = "",
                                                     int limit = 1000, int offset = 0, const std::string& event_type = "",
                                                     bool cluster_events = false);

    /**
     * @brief Get detailed events within a specific cluster
     * @return JSON object with detailed events
     */
    static nlohmann::json get_timeline_details(const std::string& events_db, 
                                              int64_t time_window, 
                                              const std::string& event_type, 
                                              const std::string& parent_dir,
                                              int limit = 1000, int offset = 0,
                                              const std::string& search = "");

    /**
     * @brief Get chronological distribution of timeline events
     * @param events_db Path to events database
     * @return JSON object with timeline statistical distribution
     */
    static nlohmann::json get_timeline_distribution(const std::string& events_db);

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

    /**
     * @brief Get system events
     * @param events_db Path to events database
     * @param start_time Optional start timestamp filter
     * @param end_time Optional end timestamp filter
     * @param limit Maximum number of records
     * @param offset Number of records to skip
     * @return JSON object with system events
     */
    static nlohmann::json get_system_events(const std::string& events_db, const std::string& start_time = "", const std::string& end_time = "", int limit = 1000, int offset = 0);

    /**
     * @brief Get system event summary
     * @param events_db Path to events database
     * @return JSON object with system event summary
     */
    static nlohmann::json get_system_event_summary(const std::string& events_db);

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

    // Enhanced Timeline Analysis Endpoints
    /**
     * @brief Get timeline by event type
     * @param events_db Path to events database
     * @param event_type Event type filter (CREATED, MODIFIED, ACCESSED, CHANGED, DELETED)
     * @param limit Maximum number of events to return
     * @return JSON array of events filtered by type
     */
    static nlohmann::json get_timeline_by_type(const std::string& events_db, const std::string& event_type, int limit = 100);

    /**
     * @brief Get timeline with time range filter
     * @param events_db Path to events database
     * @param start_time Start timestamp
     * @param end_time End timestamp
     * @param limit Maximum number of events to return
     * @return JSON array of events in time range
     */
    static nlohmann::json get_timeline_by_time_range(const std::string& events_db, int64_t start_time, int64_t end_time, int limit = 100);

    /**
     * @brief Get timeline for specific files
     * @param events_db Path to events database
     * @param file_path File path to filter
     * @param limit Maximum number of events to return
     * @return JSON array of events for specific file
     */
    static nlohmann::json get_timeline_by_file(const std::string& events_db, const std::string& file_path, int limit = 100);

    /**
     * @brief Get timeline with full details
     * @param events_db Path to events database
     * @param limit Maximum number of events to return
     * @param offset Offset for pagination
     * @return JSON array of events with full details
     */
    static nlohmann::json get_timeline_full(const std::string& events_db, int limit = 100, int offset = 0);

    /**
     * @brief Get event statistics by time period
     * @param events_db Path to events database
     * @param period Period type (hour, day, week, month)
     * @return JSON object with event statistics
     */
    static nlohmann::json get_event_statistics_by_period(const std::string& events_db, const std::string& period = "day");

    // Event Export Endpoints
    /**
     * @brief Export events to JSON format
     * @param events_db Path to events database
     * @param output_file Output file path
     * @param query Optional SQL query for filtering
     * @return JSON object with export status
     */
    static nlohmann::json export_events_to_json(const std::string& events_db, const std::string& output_file, const std::string& query = "");

    /**
     * @brief Export events to CSV format
     * @param events_db Path to events database
     * @param output_file Output file path
     * @param query Optional SQL query for filtering
     * @return JSON object with export status
     */
    static nlohmann::json export_events_to_csv(const std::string& events_db, const std::string& output_file, const std::string& query = "");

    /**
     * @brief Export events for visualization (timeline format)
     * @param events_db Path to events database
     * @param output_file Output file path
     * @return JSON object with export status
     */
    static nlohmann::json export_events_for_visualization(const std::string& events_db, const std::string& output_file);

private:
    // Helper methods
    static sqlite3* open_database(const std::string& db_path, nlohmann::json& error_result);
    static nlohmann::json execute_query(sqlite3* db, const std::string& sql);
    static bool table_exists(sqlite3* db, const std::string& table_name);
    static std::string format_timestamp(int64_t timestamp);
    static int64_t parse_timestamp(const std::string& time_str);
    static bool is_suspicious_extension(const std::string& ext);
    static bool is_suspicious_path(const std::string& path);
    static int get_total_event_count(sqlite3* db);
};