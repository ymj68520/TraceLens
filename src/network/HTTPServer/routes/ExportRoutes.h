#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

class ExportRoutes {
public:
    explicit ExportRoutes(crow::App<>& app);
    
private:
    crow::response handle_export_toon(const crow::request& req);
    crow::response handle_export_events_json(const crow::request& req);
    crow::response handle_export_events_csv(const crow::request& req);
    crow::response handle_export_events_visualization(const crow::request& req);
};

} // namespace forensics
