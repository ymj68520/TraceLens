#pragma once

#include <crow.h>
#include "../FieldApp.h"
#include <nlohmann/json.hpp>

namespace forensics {

class SystemHealthRoutes {
public:
    explicit SystemHealthRoutes(HttpApp& app);
    
private:
    crow::response handle_system_health(const crow::request& req);
    crow::response handle_health_live(const crow::request& req);
    crow::response handle_health_ready(const crow::request& req);
    crow::response handle_health_dependencies(const crow::request& req);
};

} // namespace forensics
