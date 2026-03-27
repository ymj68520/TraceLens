#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../HTTPServerDataTypes.h"
#include <mutex>
#include <unordered_map>

namespace forensics {

class FileExtractionRoutes {
public:
    explicit FileExtractionRoutes(crow::App<>& app);
    
private:
    std::unordered_map<std::string, ExtractionJob> extraction_jobs_;
    std::mutex extraction_mutex_;
    
    crow::response handle_extract_files(const crow::request& req);
    crow::response handle_extraction_status(const crow::request& req);
    void run_extraction_job(const std::string& job_id);
};

} // namespace forensics
