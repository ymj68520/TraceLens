#pragma once

#include <crow.h>
#include "../FieldApp.h"
#include <nlohmann/json.hpp>
#include "SystemHealthRoutes.h"
#include "SystemInfoRoutes.h"
#include "SystemDocsRoutes.h"

namespace forensics {

/**
 * @brief System information and monitoring route handlers
 * Handles: /api/system/*, /api/docs/*, /api/export/*
 */
class SystemRoutes {
public:
    explicit SystemRoutes(HttpApp& app);

private:
    SystemHealthRoutes health_routes_;
    SystemInfoRoutes info_routes_;
    SystemDocsRoutes docs_routes_;
};

} // namespace forensics
