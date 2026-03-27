#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"

namespace forensics {

class SystemInfoRoutes {
public:
    explicit SystemInfoRoutes(crow::App<>& app);
    
private:
    TaskManager& task_manager_;
    
    crow::response handle_system_info(const crow::request& req);
    crow::response handle_system_databases(const crow::request& req);
    crow::response handle_system_database_schema(const crow::request& req, const std::string& db_type);
    crow::response handle_export_results(const crow::request& req, const std::string& task_id);
    crow::response handle_system_logs(const crow::request& req);
};

} // namespace forensics
