#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

/**
 * @brief HTTP API routes for file filter profile management
 *
 * Exposes the C++ FileFilter profiles through REST endpoints:
 *   GET  /api/filter/profiles          - List available profiles
 *   GET  /api/filter/profiles/{name}   - Get profile details
 *   POST /api/filter/profiles          - Create or update a profile
 *   DELETE /api/filter/profiles/{name} - Delete a custom profile
 *   POST /api/filter/apply             - Apply filter to a task
 */
class FilterRoutes {
public:
    explicit FilterRoutes(crow::App<>& app);

private:
    crow::response handle_list_profiles(const crow::request& req);
    crow::response handle_get_profile(const crow::request& req, const std::string& name);
    crow::response handle_create_profile(const crow::request& req);
    crow::response handle_delete_profile(const crow::request& req, const std::string& name);
    crow::response handle_apply_filter(const crow::request& req);

    /**
     * @brief Get the path to the filter_profiles config directory
     */
    std::string getProfilesDirectory();

    /**
     * @brief Convert a FilterCondition struct to JSON
     */
    nlohmann::json conditionToJson(const struct FilterCondition& cond);

    /**
     * @brief Parse a FilterCondition from JSON
     */
    struct FilterCondition jsonToCondition(const nlohmann::json& j);
};

} // namespace forensics
