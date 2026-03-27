#include "ForensicsRoutes.h"
#include "TimelineRoutes.h"
#include "EventClusterRoutes.h"
#include "ExportRoutes.h"
#include "FileAnalysisRoutes.h"
#include "FileExtractionRoutes.h"
#include "StatisticsRoutes.h"
#include "AndroidForensicsRoutes.h"
#include "SystemEventRoutes.h"
#include <random>
#include <sstream>

namespace forensics {

using json = nlohmann::json;

// Generate unique job ID
static std::string generate_job_id() {
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, 15);
    const char* hex = "0123456789abcdef";
    std::stringstream ss;
    ss << "ext-";
    for (int i = 0; i < 8; i++) {
        ss << hex[dis(gen)];
    }
    return ss.str();
}

ForensicsRoutes::ForensicsRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    // Register all specialized route handlers
    TimelineRoutes timeline_routes(app);
    EventClusterRoutes event_cluster_routes(app);
    ExportRoutes export_routes(app);
    FileAnalysisRoutes file_analysis_routes(app);
    FileExtractionRoutes file_extraction_routes(app);
    StatisticsRoutes statistics_routes(app);
    AndroidForensicsRoutes android_forensics_routes(app);
    SystemEventRoutes system_event_routes(app);
}

// Extraction job tracking methods
// Note: File extraction routes handle their own job tracking
// These methods are kept for potential backward compatibility

std::string ForensicsRoutes::create_extraction_job(const std::string& task_id,
                                                      const std::vector<std::string>& file_ids) {
    std::lock_guard<std::mutex> lock(extraction_mutex_);

    std::string job_id = generate_job_id();
    ExtractionJob job;
    job.id = job_id;
    job.task_id = task_id;
    job.status = ExtractionStatus::PENDING;
    job.created_time = std::chrono::system_clock::now();
    job.total_files = file_ids.size();

    extraction_jobs_[job_id] = job;

    return job_id;
}

ExtractionJob ForensicsRoutes::get_extraction_job(const std::string& job_id) {
    std::lock_guard<std::mutex> lock(extraction_mutex_);

    auto it = extraction_jobs_.find(job_id);
    if (it != extraction_jobs_.end()) {
        return it->second;
    }

    ExtractionJob empty_job;
    empty_job.id = "";
    return empty_job;
}

void ForensicsRoutes::update_extraction_job_status(const std::string& job_id,
                                                     const std::string& status_str,
                                                     const std::string& output_path) {
    std::lock_guard<std::mutex> lock(extraction_mutex_);

    auto it = extraction_jobs_.find(job_id);
    if (it != extraction_jobs_.end()) {
        // Convert string status to enum
        if (status_str == "pending") {
            it->second.status = ExtractionStatus::PENDING;
        } else if (status_str == "running") {
            it->second.status = ExtractionStatus::RUNNING;
        } else if (status_str == "completed") {
            it->second.status = ExtractionStatus::COMPLETED;
            it->second.completed_time = std::chrono::system_clock::now();
        } else if (status_str == "failed") {
            it->second.status = ExtractionStatus::FAILED;
            it->second.completed_time = std::chrono::system_clock::now();
        }
        if (!output_path.empty()) {
            it->second.output_path = output_path;
        }
    }
}

void ForensicsRoutes::cleanup_old_jobs(int max_age_seconds) {
    std::lock_guard<std::mutex> lock(extraction_mutex_);

    auto now = std::chrono::system_clock::now();
    auto cutoff = now - std::chrono::seconds(max_age_seconds);

    for (auto it = extraction_jobs_.begin(); it != extraction_jobs_.end();) {
        if (it->second.created_time < cutoff) {
            it = extraction_jobs_.erase(it);
        } else {
            ++it;
        }
    }
}

} // namespace forensics
