#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

class AndroidForensicsRoutes {
public:
    explicit AndroidForensicsRoutes(crow::App<>& app);
    
private:
    crow::response handle_android_communication_summary(const crow::request& req);
    crow::response handle_android_app_usage(const crow::request& req);
    crow::response handle_android_device_info(const crow::request& req);
    crow::response handle_android_media_analysis(const crow::request& req);
};

} // namespace forensics
