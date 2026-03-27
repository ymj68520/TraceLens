#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

/**
 * @brief System information and monitoring route handlers
 * Handles: /api/system/*, /api/docs/*, /api/export/*
 */
class SystemRoutes {
public:
    explicit SystemRoutes(crow::App<>& app);
};

} // namespace forensics
