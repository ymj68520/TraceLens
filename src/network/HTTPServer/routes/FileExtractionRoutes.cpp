#include "FileExtractionRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "../../core/PathManager/PathManager.h"
#include "../../Swagger/Swagger.h"
#include <filesystem>
#include <thread>
#include <sstream>

namespace forensics {

using json = nlohmann::json;

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

        ExtractionJob job;
        job.id = RouteHelpers::generate_job_id();
        job.task_id = task_id;
        job.status = ExtractionStatus::PENDING;
        job.created_time = std::chrono::system_clock::now();

        if (body.contains("mode")) {
            std::string mode = body["mode"].get<std::string>();
            if (mode == "all") job.config.mode = ExtractionMode::ALL;
            else if (mode == "extension") job.config.mode = ExtractionMode::EXTENSION;
            else if (mode == "name") job.config.mode = ExtractionMode::NAME;
            else if (mode == "deleted") job.config.mode = ExtractionMode::DELETED;
        }

        if (body.contains("pattern")) {
            job.config.pattern = body["pattern"].get<std::string>();
        }

        if (body.contains("output_dir")) {
            job.config.output_dir = body["output_dir"].get<std::string>();
        }

        std::filesystem::path task_extract_dir = PathManager::instance().getTaskExtractDir(task_id);
        if (!job.config.output_dir.empty() && job.config.output_dir != "extracted_files") {
            std::filesystem::path user_path(job.config.output_dir);
            if (user_path.is_absolute()) {
                task_extract_dir = user_path;
            } else {
                task_extract_dir = std::filesystem::absolute(user_path);
            }
        }
        job.config.output_dir = task_extract_dir.string();
        job.output_path = task_extract_dir.string();

        if (body.contains("include_deleted")) {
            job.config.include_deleted = body["include_deleted"].get<bool>();
        }

        if (body.contains("overwrite")) {
            job.config.overwrite = body["overwrite"].get<bool>();
        }

        if (body.contains("max_files")) {
            job.config.max_files = body["max_files"].get<int>();
        }
        if (body.contains("max_total_size")) {
            job.config.max_total_size = body["max_total_size"].get<int64_t>();
        }

        {
            std::lock_guard<std::mutex> lock(extraction_mutex_);
            extraction_jobs_[job.id] = job;
        }

        std::string job_id_copy = job.id;
        std::thread([this, job_id_copy]() {
            run_extraction_job(job_id_copy);
        }).detach();

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
        progress = (job.extracted_files + job.failed_files) * 100 / job.total_files;
    }

    json response = {
        {"job_id", job.id},
        {"task_id", job.task_id},
        {"status", status_str},
        {"mode", mode_str},
        {"pattern", job.config.pattern},
        {"output_dir", job.config.output_dir},
        {"total_files", job.total_files},
        {"extracted_files", job.extracted_files},
        {"skipped_files", job.skipped_files},
        {"failed_files", job.failed_files},
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
    ExtractionJob* job_ptr = nullptr;
    std::string task_id;
    ExtractionConfig config;

    {
        std::lock_guard<std::mutex> lock(extraction_mutex_);
        auto it = extraction_jobs_.find(job_id);
        if (it == extraction_jobs_.end()) return;

        job_ptr = &it->second;
        job_ptr->status = ExtractionStatus::RUNNING;
        job_ptr->started_time = std::chrono::system_clock::now();
        job_ptr->message = "Initializing extraction...";
        task_id = job_ptr->task_id;
        config = job_ptr->config;
    }

    try {
        std::string image_path = RouteHelpers::get_image_path_for_task(task_id);
        std::string raw_db = RouteHelpers::get_database_path(task_id, "raw");

        auto extractor = std::make_unique<FileExtractor>(image_path, raw_db);
        if (!extractor->initialize()) {
            std::lock_guard<std::mutex> lock(extraction_mutex_);
            job_ptr->status = ExtractionStatus::FAILED;
            job_ptr->error_details = "Failed to initialize file extractor";
            job_ptr->completed_time = std::chrono::system_clock::now();
            return;
        }

        {
            std::lock_guard<std::mutex> lock(extraction_mutex_);
            job_ptr->message = "Extracting files...";
            job_ptr->output_path = config.output_dir;
        }

        int extracted = 0;
        int skipped = 0;
        switch (config.mode) {
            case ExtractionMode::ALL:
                extracted = extractor->extractAll(config.output_dir, config.include_deleted, config.overwrite, &skipped);
                break;
            case ExtractionMode::EXTENSION:
                extracted = extractor->extractByExtension(config.pattern, config.output_dir, config.overwrite, &skipped);
                break;
            case ExtractionMode::NAME:
                extracted = extractor->extractByName(config.pattern, config.output_dir, config.overwrite, &skipped);
                break;
            case ExtractionMode::DELETED:
                extracted = extractor->extractDeleted(config.output_dir, config.overwrite, &skipped);
                break;
        }

        {
            std::lock_guard<std::mutex> lock(extraction_mutex_);
            job_ptr->extracted_files = extracted;
            job_ptr->skipped_files = skipped;
            job_ptr->total_files = extracted + skipped;
            job_ptr->status = ExtractionStatus::COMPLETED;

            std::stringstream msg;
            msg << "Extraction completed: " << extracted << " extracted, " << skipped << " skipped";
            job_ptr->message = msg.str();

            job_ptr->completed_time = std::chrono::system_clock::now();
        }

    } catch (const std::exception& e) {
        std::lock_guard<std::mutex> lock(extraction_mutex_);
        job_ptr->status = ExtractionStatus::FAILED;
        job_ptr->error_details = e.what();
        job_ptr->message = "Extraction failed";
        job_ptr->completed_time = std::chrono::system_clock::now();
    }
}

} // namespace forensics
