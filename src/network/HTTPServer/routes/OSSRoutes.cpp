#include "OSSRoutes.h"
#include "OSSAnalysisRoutes.h"
#include "OSSQueryRoutes.h"
#include "OSSStatsRoutes.h"

namespace forensics {

using namespace ForensicAnalyzer::OSS;

std::string OSSRoutes::generate_job_id() {
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, 15);
    const char* hex = "0123456789abcdef";
    std::stringstream ss;
    ss << "oss-";
    for (int i = 0; i < 8; i++) {
        ss << hex[dis(gen)];
    }
    return ss.str();
}

OSSRoutes::OSSRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    // Delegate to modular route handlers
    OSSAnalysisRoutes analysis_routes(app);
    OSSQueryRoutes query_routes(app);
    OSSStatsRoutes stats_routes(app);
}

} // namespace forensics
