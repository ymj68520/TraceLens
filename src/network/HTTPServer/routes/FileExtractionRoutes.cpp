#include "FileExtractionRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "../../core/PathManager/PathManager.h"
#include "../../Swagger/Swagger.h"
#include <filesystem>
#include <thread>
#include <sstream>
#include <typeinfo>

namespace forensics {

using json = nlohmann::json;

FileExtractionRoutes::~FileExtractionRoutes() {
    for (auto& worker : workers_) {
        if (worker.joinable()) worker.join();
    }
}

FileExtractionRoutes::FileExtractionRoutes(crow::App<>& app) {
    CROW_ROUTE(app, "/api/forensics/extract").methods("POST"_method, "OPTIONS"_method)([this](const crow::request& req) {
        if (req.method == "OPTIONS"_method) {
            crow::response res;
            RouteHelpers::add_cors_headers(res);
            res.code = 204;
            return res;
        }
        return handle_extract_files(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/extract", "POST",
        "Extract files",
        "Start a background job to extract files from the image.",
        {"Forensics", "Extraction"},
        {},
        {{202, "Extraction job started"}, {400, "Invalid request"}}
    );

    CROW_ROUTE(app, "/api/forensics/extract/<string>").methods("GET"_method)([this](const crow::request& req, const std::string& job_id) {
        return handle_extraction_status(req);
    });

    CROW_ROUTE(app, "/api/forensics/extract/status").methods("GET"_method)([this](const crow::request& req) {
        return handle_extraction_status(req);
    });
}

crow::response FileExtractionRoutes::handle_extract_files(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        json body = json::parse(req.body);

        if (!body.contains("task_id") || body["task_id"].get<std::string>().empty()) {
            json error = {{"error", "task_id is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        std::string task_id = body["task_id"].get<std::string>();
        if (task_id.empty()) {
            json error = {{"error", "task_id is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        try {
            if (RouteHelpers::get_image_path_for_task(task_id).empty() ||
                RouteHelpers::get_database_path(task_id, "raw").empty()) {
                json error = {{"error", "task extraction inputs are not ready"}};
                res.code = 409;
                res.write(error.dump());
                return res;
            }
        } catch (const std::exception&) {
            json error = {{"error", "task not found"}};
            res.code = 404;
            res.write(error.dump());
            return res;
        }

        ExtractionJob job;
        job.id = RouteHelpers::generate_job_id();
        job.task_id = task_id;
        job.status = ExtractionStatus::PENDING;
        job.created_time = std::chrono::system_clock::now();

        const std::string mode = body.value("mode", "all");
        if (mode == "all") job.config.mode = ExtractionMode::ALL;
        else if (mode == "extension") job.config.mode = ExtractionMode::EXTENSION;
        else if (mode == "name") job.config.mode = ExtractionMode::NAME;
        else if (mode == "deleted") job.config.mode = ExtractionMode::DELETED;
        else {
            json error = {{"error", "mode must be one of: all, extension, name, deleted"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        if (body.contains("pattern")) job.config.pattern = body["pattern"].get<std::string>();
        if ((job.config.mode == ExtractionMode::EXTENSION || job.config.mode == ExtractionMode::NAME) &&
            job.config.pattern.find_first_not_of(" \t,.") == std::string::npos) {
            json error = {{"error", "pattern is required for extension/name mode"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        std::string user_output;
        if (body.contains("output_dir")) {
            user_output = body["output_dir"].get<std::string>();
        }

        namespace fs = std::filesystem;
        fs::path base = PathManager::instance().getTaskExtractDir(task_id);
        fs::path task_extract_dir = base;
        if (!user_output.empty() && user_output != "extracted_files") {
            // Contain the extraction target under the per-task extract root:
            // reject absolute paths and any ".." traversal so image contents can
            // never be written to arbitrary locations (e.g. ~/.ssh, /etc/cron.d).
            fs::path user_path(user_output);
            bool has_dotdot = false;
            for (const auto& part : user_path) { if (part == "..") has_dotdot = true; }
            if (user_path.is_absolute() || has_dotdot) {
                json error = {{"error", "output_dir must be a relative path under the task extract directory"}};
                res.code = 400;
                res.write(error.dump());
                return res;
            }
            fs::path base_canon = fs::weakly_canonical(base);
            fs::path candidate = fs::weakly_canonical(base / user_path);
            fs::path rel = candidate.lexically_relative(base_canon);
            if (rel.empty() || (*rel.begin()) == "..") {
                json error = {{"error", "output_dir escapes the task extract directory"}};
                res.code = 400;
                res.write(error.dump());
                return res;
            }
            task_extract_dir = candidate;
        }
        job.config.output_dir = task_extract_dir.string();
        job.output_path = task_extract_dir.string();

        if (body.contains("include_deleted")) {
            job.config.include_deleted = body["include_deleted"].get<bool>();
        }

        if (body.contains("overwrite")) {
            job.config.overwrite = body["overwrite"].get<bool>();
        }

        auto parse_nonnegative_limit = [&](const char* key, int64_t& target) -> bool {
            if (!body.contains(key)) return true;
            if (!body[key].is_number_integer()) return false;
            target = body[key].get<int64_t>();
            return target >= 0;
        };
        if (!parse_nonnegative_limit("max_files", job.config.max_files) ||
            !parse_nonnegative_limit("max_total_size", job.config.max_total_size) ||
            !parse_nonnegative_limit("max_file_size", job.config.max_file_size)) {
            json error = {{"error", "extraction limits must be non-negative integers"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        {
            std::lock_guard<std::mutex> lock(extraction_mutex_);
            extraction_jobs_[job.id] = job;
        }

        std::string job_id_copy = job.id;
        workers_.emplace_back([this, job_id_copy]() {
            run_extraction_job(job_id_copy);
        });

        json response = {
            {"success", true},
            {"message", "Extraction job started"},
            {"job_id", job.id},
            {"status", "pending"}
        };
        res.code = 202;
        res.write(response.dump());

    } catch (const json::exception& e) {
        json error = {{"error", std::string("Invalid JSON: ") + e.what()}};
        res.code = 400;
        res.write(error.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response FileExtractionRoutes::handle_extraction_status(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    auto params = crow::query_string(req.url_params);
    std::string job_id = params.get("job_id") ? params.get("job_id") : "";

    if (job_id.empty()) {
        std::string url = req.url;
        size_t pos = url.find("/api/forensics/extract/");
        if (pos != std::string::npos) {
            job_id = url.substr(pos + 23);
            if (!job_id.empty() && job_id.back() == '/') {
                job_id.pop_back();
            }
        }
    }

    if (job_id.empty()) {
        json error = {{"error", "job_id parameter is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    std::lock_guard<std::mutex> lock(extraction_mutex_);
    auto it = extraction_jobs_.find(job_id);
    if (it == extraction_jobs_.end()) {
        json error = {{"error", "Job not found: " + job_id}};
        res.code = 404;
        res.write(error.dump());
        return res;
    }

    const ExtractionJob& job = it->second;

    std::string status_str;
    switch (job.status) {
        case ExtractionStatus::PENDING: status_str = "pending"; break;
        case ExtractionStatus::RUNNING: status_str = "running"; break;
        case ExtractionStatus::COMPLETED: status_str = "completed"; break;
        case ExtractionStatus::FAILED: status_str = "failed"; break;
        case ExtractionStatus::CANCELLED: status_str = "cancelled"; break;
    }

    std::string mode_str;
    switch (job.config.mode) {
        case ExtractionMode::ALL: mode_str = "all"; break;
        case ExtractionMode::EXTENSION: mode_str = "extension"; break;
        case ExtractionMode::NAME: mode_str = "name"; break;
        case ExtractionMode::DELETED: mode_str = "deleted"; break;
    }

    int progress = 0;
    if (job.total_files > 0) {
        progress = job.total_files > 0 ? job.processed_files * 100 / job.total_files : 0;
    }

    json response = {
        {"job_id", job.id},
        {"task_id", job.task_id},
        {"status", status_str},
        {"mode", mode_str},
        {"pattern", job.config.pattern},
        {"output_dir", job.config.output_dir},
        {"total_files", job.total_files},
        {"processed_files", job.processed_files},
        {"extracted_files", job.extracted_files},
        {"skipped_files", job.skipped_files},
        {"failed_files", job.failed_files},
        {"bounded", job.bounded},
        {"limit_reason", job.limit_reason},
        {"progress", progress},
        {"current_file", job.current_file},
        {"message", job.message},
        {"error_details", job.error_details},
        {"output_path", job.output_path}
    };

    res.write(response.dump());
    return res;
}

void FileExtractionRoutes::run_extraction_job(const std::string& job_id) {
    ExtractionJob snapshot;
    {
        std::lock_guard<std::mutex> lock(extraction_mutex_);
        auto it = extraction_jobs_.find(job_id);
        if (it == extraction_jobs_.end()) return;
        it->second.status = ExtractionStatus::RUNNING;
        it->second.started_time = std::chrono::system_clock::now();
        it->second.message = "Initializing extraction...";
        snapshot = it->second;
    }
    const std::string task_id = snapshot.task_id;
    const ExtractionConfig config = snapshot.config;

    try {
        std::string image_path = RouteHelpers::get_image_path_for_task(task_id);
        std::string raw_db = RouteHelpers::get_database_path(task_id, "raw");

        auto extractor = std::make_unique<FileExtractor>(image_path, raw_db);
        if (!extractor->initialize()) {
            std::lock_guard<std::mutex> lock(extraction_mutex_);
            auto it = extraction_jobs_.find(job_id);
            if (it == extraction_jobs_.end()) return;
            it->second.status = ExtractionStatus::FAILED;
            it->second.error_details = "Failed to initialize file extractor";
            it->second.completed_time = std::chrono::system_clock::now();
            return;
        }

        {
            std::lock_guard<std::mutex> lock(extraction_mutex_);
            auto it = extraction_jobs_.find(job_id);
            if (it == extraction_jobs_.end()) return;
            it->second.message = "Extracting files...";
            it->second.output_path = config.output_dir;
        }

        int extracted = 0;
        int skipped = 0;
        int failed = 0;
        int total = 0;
        int processed = 0;
        int64_t extractedBytes = 0;
        bool bounded = false;
        std::string limitReason;
        std::vector<std::string> errors;
        FileExtractor::ExtractionLimits limits{
            config.max_files,
            config.max_total_size,
            config.max_file_size,
            &failed,
            &total,
            &processed,
            &extractedBytes,
            &bounded,
            &limitReason,
            &errors,
        };
        switch (config.mode) {
            case ExtractionMode::ALL:
                extracted = extractor->extractAll(config.output_dir, config.include_deleted, config.overwrite, &skipped, &limits);
                break;
            case ExtractionMode::EXTENSION:
                extracted = extractor->extractByExtension(config.pattern, config.output_dir, config.overwrite, &skipped, &limits);
                break;
            case ExtractionMode::NAME:
                extracted = extractor->extractByName(config.pattern, config.output_dir, config.overwrite, &skipped, &limits);
                break;
            case ExtractionMode::DELETED:
                extracted = extractor->extractDeleted(config.output_dir, config.overwrite, &skipped, &limits);
                break;
        }

        {
            std::lock_guard<std::mutex> lock(extraction_mutex_);
            auto it = extraction_jobs_.find(job_id);
            if (it == extraction_jobs_.end()) return;
            it->second.extracted_files = extracted;
            it->second.skipped_files = skipped;
            it->second.failed_files = failed;
            it->second.total_files = total;
            it->second.processed_files = processed;
            it->second.bounded = bounded;
            it->second.limit_reason = limitReason;
            it->second.error_details.clear();
            for (const auto& error : errors) {
                if (!it->second.error_details.empty()) it->second.error_details += "; ";
                it->second.error_details += error;
            }
            it->second.status = ExtractionStatus::COMPLETED;
            std::stringstream msg;
            msg << "Extraction completed: " << extracted << " extracted, "
                << skipped << " skipped, " << failed << " failed";
            if (bounded) msg << " (bounded by " << limitReason << ")";
            it->second.message = msg.str();
            it->second.completed_time = std::chrono::system_clock::now();
        }

    } catch (const std::exception& e) {
        std::lock_guard<std::mutex> lock(extraction_mutex_);
        auto it = extraction_jobs_.find(job_id);
        if (it == extraction_jobs_.end()) return;
        it->second.status = ExtractionStatus::FAILED;
        it->second.error_details = typeid(e).name();
        it->second.message = "Extraction failed";
        it->second.completed_time = std::chrono::system_clock::now();
    }
}

} // namespace forensics
