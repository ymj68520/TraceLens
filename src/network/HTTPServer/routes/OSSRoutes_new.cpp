#include "OSSRoutes_new.h"
#include "OSSAnalysisRoutes.h"
#include "OSSQueryRoutes.h"
#include "OSSStatsRoutes.h"

namespace forensics {

OSSRoutes::OSSRoutes(crow::App<>& app) {
    OSSAnalysisRoutes analysis(app);
    OSSQueryRoutes query(app);
    OSSStatsRoutes stats(app);
}

} // namespace forensics
