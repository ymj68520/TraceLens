#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

/**
 * @brief Event cluster AI analysis route handlers
 * Handles: /api/forensics/timeline/clusters/*
 */
class EventClusterRoutes {
public:
    explicit EventClusterRoutes(crow::App<>& app);
    
private:
    // Retired with the legacy C++ LLM cluster stack (SPEC D11); the route
    // registrations and handler bodies are kept under `#if 0` in the .cpp.
    // crow::response handle_analyze_event_cluster(const crow::request& req);
    // crow::response handle_batch_analyze_event_clusters(const crow::request& req);
    // crow::response handle_reanalyze_event_cluster(const crow::request& req);
    crow::response handle_get_analyzed_clusters(const crow::request& req);
};

} // namespace forensics
