#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"

namespace forensics {

/**
 * @brief Full-text search route handlers
 * Handles: /api/search/*
 */
class SearchRoutes {
public:
    explicit SearchRoutes(crow::App<>& app);

private:
    // Search operations
    // Search operations
    /**
     * @brief Perform full-text search
     * @param req The HTTP request containing search parameters
     * @return JSON response with search results
     */
    crow::response handle_fulltext_search(const crow::request& req);

    /**
     * @brief Create or update search index
     * @param req The HTTP request containing indexing parameters
     * @return JSON response with indexing status
     */
    crow::response handle_fulltext_index(const crow::request& req);
};

} // namespace forensics
