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
    crow::response handle_miui_backup_overview(const crow::request& req);
    crow::response handle_miui_installed_apps(const crow::request& req);
    crow::response handle_miui_db_inventory(const crow::request& req);
    crow::response handle_miui_qqnt_overview(const crow::request& req);
    crow::response handle_miui_qqnt_artifacts(const crow::request& req);
    crow::response handle_miui_qqnt_records(const crow::request& req);
};

} // namespace forensics
