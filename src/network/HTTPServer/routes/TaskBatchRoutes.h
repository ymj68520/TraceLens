#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"

namespace forensics {

class TaskBatchRoutes {
public:
    explicit TaskBatchRoutes(crow::App<>& app);
    
private:
    TaskManager& task_manager_;
    
    crow::response handle_batch_create_tasks(const crow::request& req);
    crow::response handle_batch_status(const crow::request& req);
    crow::response handle_batch_cancel(const crow::request& req);

    static void add_cors_headers(crow::response& res);
};

} // namespace forensics
