#pragma once

#include <crow.h>
#include "../FieldApp.h"
#include <nlohmann/json.hpp>

namespace forensics {

class SystemEventRoutes {
public:
    explicit SystemEventRoutes(HttpApp& app);
    
private:
    crow::response handle_system_events(const crow::request& req);
    crow::response handle_system_event_summary(const crow::request& req);
};

} // namespace forensics
