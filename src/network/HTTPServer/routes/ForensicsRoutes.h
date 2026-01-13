#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"
#include "../SQLiteHelper.h"
#include "../HTTPServerDataTypes.h"
#include <mutex>
#include <unordered_map>
#include <thread>

namespace forensics {

/**
 * @brief Forensics analysis route handlers
 * Handles: /api/forensics/*
 */
class ForensicsRoutes {
public:
    explicit ForensicsRoutes(crow::App<>& app);
    
private:
    TaskManager& task_manager_;
    
    // Extraction job tracking
    std::unordered_map<std::string, ExtractionJob> extraction_jobs_;
    std::mutex extraction_mutex_;
    
    // Timeline Analysis
    crow::response handle_timeline_comprehensive(const crow::request& req);
    crow::response handle_timeline_file_activity(const crow::request& req);
    crow::response handle_timeline_suspicious_patterns(const crow::request& req);
    crow::response handle_timeline_user_activity(const crow::request& req);
    
    // File Analysis
    crow::response handle_files_largest(const crow::request& req);
    crow::response handle_files_recent(const crow::request& req);
    crow::response handle_files_suspicious(const crow::request& req);
    crow::response handle_files_duplicates(const crow::request& req);
    crow::response handle_files_extensions_analysis(const crow::request& req);
    
    // File Extraction
    crow::response handle_extract_files(const crow::request& req);
    crow::response handle_extraction_status(const crow::request& req);
    void run_extraction_job(const std::string& job_id);
    
    // Android Forensics
    crow::response handle_android_communication_summary(const crow::request& req);
    crow::response handle_android_app_usage(const crow::request& req);
    crow::response handle_android_device_info(const crow::request& req);
    crow::response handle_android_media_analysis(const crow::request& req);
    
    // Statistics
    crow::response handle_statistics_overview(const crow::request& req);
    crow::response handle_statistics_file_distribution(const crow::request& req);
    crow::response handle_statistics_activity_patterns(const crow::request& req);
    crow::response handle_statistics_deleted_files_analysis(const crow::request& req);
    
    // Helper
    std::string get_database_path(const std::string& task_id, const std::string& db_type);
    std::string get_image_path_for_task(const std::string& task_id);

    // CORS helper
    static void add_cors_headers(crow::response& res);
};

} // namespace forensics

