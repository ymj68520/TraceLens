#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

class SystemEventRoutes {
public:
    explicit SystemEventRoutes(crow::App<>& app);
    
private:
    crow::response handle_system_events(const crow::request& req);
    crow::response handle_system_event_summary(const crow::request& req);
};

} // namespace forensics
