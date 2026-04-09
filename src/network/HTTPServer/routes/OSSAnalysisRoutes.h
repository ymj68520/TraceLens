#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"
#include "../HTTPServerDataTypes.h"
#include "OSSAnalyzer/OSSAnalyzer.h"
#include <mutex>
#include <unordered_map>
#include <thread>
#include <random>
#include <sstream>

namespace forensics {

class OSSAnalysisRoutes {
public:
    explicit OSSAnalysisRoutes(crow::App<>& app);

private:
    TaskManager& task_manager_;
    std::unordered_map<std::string, std::string> job_ids_;  // job_id -> task_id
    std::mutex jobs_mutex_;

    static std::string generate_job_id();

    crow::response handle_analyze_start(const crow::request& req);
    crow::response handle_analyze_status(const crow::request& req);

    /**
     * @brief Start AI filtering of OSS objects
     * POST /api/forensics/oss/ai/filter
     */
    crow::response handle_ai_filter_start(const crow::request& req);

    /**
     * @brief Start AI analysis of OSS objects
     * POST /api/forensics/oss/ai/analyze
     */
    crow::response handle_ai_analyze_start(const crow::request& req);

    /**
     * @brief Download OSS object for analysis
     * POST /api/forensics/oss/download
     */
    crow::response handle_download_object(const crow::request& req);

    /**
     * @brief Get AI analysis status
     * GET /api/forensics/oss/ai/status
     */
    crow::response handle_ai_analysis_status(const crow::request& req);

    void run_analysis_job(const std::string& job_id, const std::string& task_id);
};

} // namespace forensics
