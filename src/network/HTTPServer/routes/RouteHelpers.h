#pragma once

#include <crow.h>
#include <string>

namespace forensics {

/**
 * @brief Shared helper functions for route handlers
 */
class RouteHelpers {
public:
    /**
     * @brief Add CORS headers to response
     */
    static void add_cors_headers(crow::response& res);
    
    /**
     * @brief Generate unique job ID
     */
    static std::string generate_job_id();
    
    /**
     * @brief Get database path for task
     */
    static std::string get_database_path(const std::string& task_id, const std::string& db_type);
    
    /**
     * @brief Get image path for task
     */
    static std::string get_image_path_for_task(const std::string& task_id);
};

} // namespace forensics
