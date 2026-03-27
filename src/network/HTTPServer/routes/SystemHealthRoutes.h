#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

class SystemHealthRoutes {
public:
    explicit SystemHealthRoutes(crow::App<>& app);
    
private:
    crow::response handle_system_health(const crow::request& req);
    crow::response handle_health_live(const crow::request& req);
    crow::response handle_health_ready(const crow::request& req);
    crow::response handle_health_dependencies(const crow::request& req);
};

} // namespace forensics
