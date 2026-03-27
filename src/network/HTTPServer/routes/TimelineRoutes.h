#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include <string>

namespace forensics {

/**
 * @brief Timeline analysis route handlers
 * Handles: /api/forensics/timeline/*
 */
class TimelineRoutes {
public:
    explicit TimelineRoutes(crow::App<>& app);
    
private:
    crow::response handle_timeline_comprehensive(const crow::request& req);
    crow::response handle_timeline_details(const crow::request& req);
    crow::response handle_timeline_distribution(const crow::request& req);
    crow::response handle_timeline_file_activity(const crow::request& req);
    crow::response handle_timeline_suspicious_patterns(const crow::request& req);
    crow::response handle_timeline_user_activity(const crow::request& req);
    crow::response handle_timeline_by_type(const crow::request& req);
    crow::response handle_timeline_by_time_range(const crow::request& req);
    crow::response handle_timeline_by_file(const crow::request& req);
    crow::response handle_timeline_full(const crow::request& req);
    crow::response handle_event_statistics_by_period(const crow::request& req);
};

} // namespace forensics
