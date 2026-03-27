#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

class StatisticsRoutes {
public:
    explicit StatisticsRoutes(crow::App<>& app);
    
private:
    crow::response handle_statistics_overview(const crow::request& req);
    crow::response handle_statistics_file_distribution(const crow::request& req);
    crow::response handle_statistics_activity_patterns(const crow::request& req);
    crow::response handle_statistics_deleted_files_analysis(const crow::request& req);
};

} // namespace forensics
