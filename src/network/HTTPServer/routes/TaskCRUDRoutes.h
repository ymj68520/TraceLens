#pragma once

#include <crow.h>
#include "../FieldApp.h"
#include <nlohmann/json.hpp>
#include "../TaskManager.h"

namespace forensics {

/**
 * @brief Task CRUD operations
 */
class TaskCRUDRoutes {
public:
    explicit TaskCRUDRoutes(HttpApp& app);

private:
    HttpApp& app_;
    TaskManager& task_manager_;

    crow::response handle_create_task(const crow::request& req);
    crow::response handle_get_task(const crow::request& req, const std::string& task_id);
    crow::response handle_get_task_results(const crow::request& req, const std::string& task_id);
    crow::response handle_get_task_databases(const crow::request& req, const std::string& task_id);
    crow::response handle_list_tasks(const crow::request& req);
    crow::response handle_cancel_task(const crow::request& req, const std::string& task_id);
    crow::response handle_cleanup_tasks(const crow::request& req);
};

} // namespace forensics
