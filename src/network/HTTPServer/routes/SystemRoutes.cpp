#include "SystemRoutes.h"
#include "SystemHealthRoutes.h"
#include "SystemInfoRoutes.h"
#include "SystemDocsRoutes.h"

namespace forensics {

SystemRoutes::SystemRoutes(crow::App<>& app) {
    // Delegate to modular route handlers
    SystemHealthRoutes health_routes(app);
    SystemInfoRoutes info_routes(app);
    SystemDocsRoutes docs_routes(app);
}

} // namespace forensics
