#include "SystemRoutes.h"
#include "SystemHealthRoutes.h"
#include "SystemInfoRoutes.h"
#include "SystemDocsRoutes.h"

namespace forensics {

SystemRoutes::SystemRoutes(crow::App<>& app)
    : health_routes_(app),
      info_routes_(app),
      docs_routes_(app) {
    // Route handlers are registered by the sub-route constructors
}

} // namespace forensics
