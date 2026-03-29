#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"

namespace forensics {

class TaskMonitoringRoutes {
public:
    explicit TaskMonitoringRoutes(crow::App<>& app);

private:
    TaskManager& task_manager_;

    crow::response handle_get_task_progress(const crow::request& req, const std::string& task_id);
    crow::response handle_get_task_statistics(const crow::request& req);
    crow::response handle_get_task_audit_log(const crow::request& req, const std::string& task_id);
    crow::response handle_update_task_priority(const crow::request& req, const std::string& task_id);
};

} // namespace forensics
