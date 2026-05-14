#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"
#include "../HTTPServerDataTypes.h"
#include "DLLAnalysisRoutes.h"
#include <mutex>
#include <unordered_map>
#include <chrono>
#include <string>
#include "TimelineRoutes.h"
#include "EventClusterRoutes.h"
#include "ExportRoutes.h"
#include "FileAnalysisRoutes.h"
#include "FileExtractionRoutes.h"
#include "StatisticsRoutes.h"
#include "AndroidForensicsRoutes.h"
#include "SystemEventRoutes.h"

namespace forensics {

/**
 * @brief Forensics analysis route orchestrator
 * Delegates to specialized route classes:
 * - TimelineRoutes
 * - EventClusterRoutes
 * - ExportRoutes
 * - FileAnalysisRoutes
 * - FileExtractionRoutes
 * - StatisticsRoutes
 * - AndroidForensicsRoutes
 * - SystemEventRoutes
 *
 * Also manages extraction job tracking for file extraction operations
 */
class ForensicsRoutes {
public:
    explicit ForensicsRoutes(crow::App<>& app);

    /**
     * @brief Create a new file extraction job
     * @param task_id Task ID
     * @param file_ids List of file IDs to extract
     * @return Job ID
     */
    std::string create_extraction_job(const std::string& task_id,
                                      const std::vector<std::string>& file_ids);

    /**
     * @brief Get extraction job details
     * @param job_id Job ID
     * @return Extraction job details
     */
    ExtractionJob get_extraction_job(const std::string& job_id);

    /**
     * @brief Update extraction job status
     * @param job_id Job ID
     * @param status New status
     * @param output_path Optional output path
     */
    void update_extraction_job_status(const std::string& job_id,
                                       const std::string& status,
                                       const std::string& output_path = "");

    /**
     * @brief Cleanup old extraction jobs
     * @param max_age_seconds Maximum age in seconds
     */
    void cleanup_old_jobs(int max_age_seconds);

private:
    TaskManager& task_manager_;

    // Sub-route handlers - must be members to avoid dangling pointers
    TimelineRoutes timeline_routes_;
    EventClusterRoutes event_cluster_routes_;
    ExportRoutes export_routes_;
    FileAnalysisRoutes file_analysis_routes_;
    FileExtractionRoutes file_extraction_routes_;
    StatisticsRoutes statistics_routes_;
    AndroidForensicsRoutes android_forensics_routes_;
    SystemEventRoutes system_event_routes_;
    DLLAnalysisRoutes dll_analysis_routes_;

    // Extraction job tracking
    std::unordered_map<std::string, ExtractionJob> extraction_jobs_;
    std::mutex extraction_mutex_;
};

} // namespace forensics
