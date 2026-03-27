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
    void run_analysis_job(const std::string& job_id, const std::string& task_id);
};

} // namespace forensics
