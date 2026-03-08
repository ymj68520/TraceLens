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
    // Timeline Analysis
    /**
     * @brief Get comprehensive timeline from all sources
     * @param req The HTTP request
     * @return JSON response with timeline events
     */
    crow::response handle_timeline_comprehensive(const crow::request& req);

    /**
     * @brief Get detailed events within a specific cluster
     * @param req The HTTP request
     * @return JSON response with detailed events
     */
    crow::response handle_timeline_details(const crow::request& req);

    /**
     * @brief Get chronological distribution of timeline events
     * @param req The HTTP request
     * @return JSON response with timeline distribution
     */
    crow::response handle_timeline_distribution(const crow::request& req);

    /**
     * @brief Get file system activity timeline
     * @param req The HTTP request
     * @return JSON response with file activity events
     */
    crow::response handle_timeline_file_activity(const crow::request& req);

    /**
     * @brief Get suspicious activity patterns
     * @param req The HTTP request
     * @return JSON response with suspicious events
     */
    crow::response handle_timeline_suspicious_patterns(const crow::request& req);

    /**
     * @brief Get user activity timeline
     * @param req The HTTP request
     * @return JSON response with user events
     */
    crow::response handle_timeline_user_activity(const crow::request& req);
    
    // File Analysis
    // File Analysis
    /**
     * @brief Get largest files in the image
     * @param req The HTTP request
     * @return JSON response with largest files
     */
    crow::response handle_files_largest(const crow::request& req);

    /**
     * @brief Get most recently accessed/modified files
     * @param req The HTTP request
     * @return JSON response with recent files
     */
    crow::response handle_files_recent(const crow::request& req);

    /**
     * @brief Get potentially suspicious files
     * @param req The HTTP request
     * @return JSON response with suspicious files
     */
    crow::response handle_files_suspicious(const crow::request& req);

    /**
     * @brief Get duplicate files
     * @param req The HTTP request
     * @return JSON response with duplicates
     */
    crow::response handle_files_duplicates(const crow::request& req);

    /**
     * @brief Get file extension statistics
     * @param req The HTTP request
     * @return JSON response with extension analysis
     */
    crow::response handle_files_extensions_analysis(const crow::request& req);
    
    // File Extraction
    /**
     * @brief Start a file extraction job
     * @param req The HTTP request
     * @return JSON response with job ID
     */
    crow::response handle_extract_files(const crow::request& req);

    /**
     * @brief Get status of extraction job
     * @param req The HTTP request
     * @return JSON response with job status
     */
    crow::response handle_extraction_status(const crow::request& req);

    /**
     * @brief Worker method for extraction jobs
     * @param job_id The ID of the job to run
     */
    void run_extraction_job(const std::string& job_id);
    
    // Android Forensics
    // Android Forensics
    /**
     * @brief Get communication summary (calls, messages)
     * @param req The HTTP request
     * @return JSON response with communication stats
     */
    crow::response handle_android_communication_summary(const crow::request& req);

    /**
     * @brief Get installed application usage
     * @param req The HTTP request
     * @return JSON response with app usage stats
     */
    crow::response handle_android_app_usage(const crow::request& req);

    /**
     * @brief Get device information
     * @param req The HTTP request
     * @return JSON response with device info
     */
    crow::response handle_android_device_info(const crow::request& req);

    /**
     * @brief Get media file analysis
     * @param req The HTTP request
     * @return JSON response with media stats
     */
    crow::response handle_android_media_analysis(const crow::request& req);
    
    // Statistics
    /**
     * @brief Get overview of forensic statistics
     * @param req The HTTP request
     * @return JSON response with statistics overview
     */
    crow::response handle_statistics_overview(const crow::request& req);

    /**
     * @brief Get file size and type distribution statistics
     * @param req The HTTP request
     * @return JSON response with distribution stats
     */
    crow::response handle_statistics_file_distribution(const crow::request& req);

    /**
     * @brief Get activity pattern statistics
     * @param req The HTTP request
     * @return JSON response with activity patterns
     */
    crow::response handle_statistics_activity_patterns(const crow::request& req);

    /**
     * @brief Get statistics about deleted files
     * @param req The HTTP request
     * @return JSON response with deleted files stats
     */
    crow::response handle_statistics_deleted_files_analysis(const crow::request& req);
    
    // Export
    /**
     * @brief Export analysis results to TOON format
     * @param req The HTTP request
     * @return JSON response with export status or data
     */
    crow::response handle_export_toon(const crow::request& req);
    
    // Helper
    /**
     * @brief Helper to construct database file path
     * @param task_id The task ID
     * @param db_type The database type
     * @return Absolute path to the database file
     */
    std::string get_database_path(const std::string& task_id, const std::string& db_type);

    /**
     * @brief Helper to get image path associated with a task
     * @param task_id The task ID
     * @return Absolute path to the image file
     */
    std::string get_image_path_for_task(const std::string& task_id);

    // CORS helper
    static void add_cors_headers(crow::response& res);
};

} // namespace forensics

