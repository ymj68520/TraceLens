#pragma once

#include <crow.h>
#include "../FieldApp.h"
#include <nlohmann/json.hpp>
#include "../TaskManager.h"

namespace forensics {

class OSSQueryRoutes {
public:
    explicit OSSQueryRoutes(HttpApp& app);
    
private:
    TaskManager& task_manager_;
    
    crow::response handle_get_objects(const crow::request& req);
    crow::response handle_get_access_logs(const crow::request& req);
};

} // namespace forensics
