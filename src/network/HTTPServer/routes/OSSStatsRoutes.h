#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"

namespace forensics {

class OSSStatsRoutes {
public:
    explicit OSSStatsRoutes(crow::App<>& app);
    
private:
    TaskManager& task_manager_;
    
    crow::response handle_get_summary(const crow::request& req);
    crow::response handle_storage_class_stats(const crow::request& req);
    crow::response handle_extension_stats(const crow::request& req);
    crow::response handle_get_buckets(const crow::request& req);
};

} // namespace forensics
