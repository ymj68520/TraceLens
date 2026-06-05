#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

/**
 * @brief Scene query API routes
 * Provides endpoints for querying scene statistics and artifacts.
 *
 * Endpoints:
 *   GET /api/tasks/{id}/scene-stats       - Scene statistics per type
 *   GET /api/tasks/{id}/scene-artifacts    - Scene artifacts (query param: scene_type)
 */
class SceneQueryRoutes {
public:
    explicit SceneQueryRoutes(crow::App<>& app);

private:
    crow::response handle_get_scene_stats(const crow::request& req, const std::string& task_id);
    crow::response handle_get_scene_artifacts(const crow::request& req, const std::string& task_id);
};

} // namespace forensics
