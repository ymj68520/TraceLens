// DLLAnalysisRoutes.h
// REST API endpoints for DLL analysis

#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

class DLLAnalysisRoutes {
public:
    explicit DLLAnalysisRoutes(crow::App<>& app);

private:
    crow::response handle_get_dll_list(const crow::request& req);
    crow::response handle_get_dll_by_id(const crow::request& req, int64_t dll_id);
    crow::response handle_get_suspicious_dlls(const crow::request& req);
    crow::response handle_get_dll_statistics(const crow::request& req);
    crow::response handle_get_dll_anomalies(const crow::request& req, int64_t dll_id);
    crow::response handle_analyze_single_dll(const crow::request& req);
};

} // namespace forensics
