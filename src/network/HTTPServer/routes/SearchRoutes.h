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
    crow::response handle_fulltext_search(const crow::request& req);
    crow::response handle_fulltext_index(const crow::request& req);
};

} // namespace forensics
