#include "OSSAnalysisRoutes.h"
#include "RouteHelpers.h"
#include "../../Swagger/Swagger.h"
#include "OSSRoutes.h"
#include <random>
#include <sstream>

namespace forensics {

using json = nlohmann::json;

std::string OSSAnalysisRoutes::generate_job_id() {
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

OSSAnalysisRoutes::OSSAnalysisRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    CROW_ROUTE(app, "/api/forensics/oss/analyze").methods("POST"_method, "OPTIONS"_method)([this](const crow::request& req) {
        if (req.method == "OPTIONS"_method) {
            crow::response res;
            RouteHelpers::add_cors_headers(res);
            res.code = 204;
            return res;
        }
        return handle_analyze_start(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/analyze", "POST",
        "Start OSS analysis",
        "Start a background job to analyze Alibaba Cloud OSS data.",
        {"Forensics", "OSS"},
        {},
        {{202, "Analysis job started"}, {400, "Invalid request"}}
    );

    CROW_ROUTE(app, "/api/forensics/oss/analyze/status").methods("GET"_method)([this](const crow::request& req) {
        return handle_analyze_status(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/analyze/status", "GET",
        "Get OSS analysis job status",
        "Check the status of an OSS analysis job.",
        {"Forensics", "OSS"},
        {{"job_id", "query", "Analysis job ID", true}},
        {{200, "Job status"}, {404, "Job not found"}}
    );

    // AI Analysis Routes
    CROW_ROUTE(app, "/api/forensics/oss/ai/filter").methods("POST"_method, "OPTIONS"_method)([this](const crow::request& req) {
        if (req.method == "OPTIONS"_method) {
            crow::response res;
            RouteHelpers::add_cors_headers(res);
            res.code = 204;
            return res;
        }
        return handle_ai_filter_start(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/ai/filter", "POST",
        "Start AI filtering of OSS objects",
        "Filter OSS objects using AI to identify relevant files. Requires Python service.",
        {"Forensics", "OSS", "AI"},
        {},
        {{202, "Filter job started"}, {400, "Invalid request"}, {503, "Python service unavailable"}}
    );

    CROW_ROUTE(app, "/api/forensics/oss/ai/analyze").methods("POST"_method, "OPTIONS"_method)([this](const crow::request& req) {
        if (req.method == "OPTIONS"_method) {
            crow::response res;
            RouteHelpers::add_cors_headers(res);
            res.code = 204;
            return res;
        }
        return handle_ai_analyze_start(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/ai/analyze", "POST",
        "Start AI analysis of OSS objects",
        "Analyze OSS objects using AI to extract insights. Requires Python service.",
        {"Forensics", "OSS", "AI"},
        {},
        {{202, "Analysis job started"}, {400, "Invalid request"}, {503, "Python service unavailable"}}
    );

    CROW_ROUTE(app, "/api/forensics/oss/download").methods("POST"_method)([this](const crow::request& req) {
        return handle_download_object(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/download", "POST",
        "Download OSS object",
        "Download an object from OSS storage for analysis. Requires OSSClient integration.",
        {"Forensics", "OSS"},
        {},
        {{200, "Download started"}, {400, "Invalid request"}, {501, "Not implemented"}}
    );

    CROW_ROUTE(app, "/api/forensics/oss/ai/status").methods("GET"_method)([this](const crow::request& req) {
        return handle_ai_analysis_status(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/ai/status", "GET",
        "Get AI analysis status",
        "Check the status of an AI analysis job. Requires Python service.",
        {"Forensics", "OSS", "AI"},
        {{"job_id", "query", "Analysis job ID", true}},
        {{200, "Job status"}, {404, "Job not found"}, {503, "Python service unavailable"}}
    );
}

crow::response OSSAnalysisRoutes::handle_analyze_start(const crow::request& req) {
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

        // Create a simple job tracking entry
        std::string job_id = generate_job_id();

        {
            std::lock_guard<std::mutex> lock(jobs_mutex_);
            // Store job_id and task_id mapping
            job_ids_[job_id] = task_id;
        }

        // Start async analysis (placeholder)
        std::thread([this, job_id, task_id]() {
            run_analysis_job(job_id, task_id);
        }).detach();

        json response;
        response["success"] = true;
        response["message"] = "OSS analysis job started";
        response["job_id"] = job_id;
        response["status"] = "pending";

        res.code = 202;
        res.write(response.dump());

    } catch (const json::exception& e) {
        json error;
        error["error"] = std::string("Invalid JSON: ") + e.what();
        res.code = 400;
        res.write(error.dump());
    } catch (const std::exception& e) {
        json error;
        error["error"] = e.what();
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response OSSAnalysisRoutes::handle_analyze_status(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        std::string job_id = req.url_params.get("job_id") ? req.url_params.get("job_id") : "";

        if (job_id.empty()) {
            json error;
            error["error"] = "job_id is required";
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        std::string task_id;
        {
            std::lock_guard<std::mutex> lock(jobs_mutex_);
            auto it = job_ids_.find(job_id);
            if (it == job_ids_.end()) {
                json error;
                error["error"] = "Job not found";
                error["job_id"] = job_id;
                res.code = 404;
                res.write(error.dump());
                return res;
            }
            task_id = it->second;
        }

        json response;
        response["job_id"] = job_id;
        response["task_id"] = task_id;
        response["status"] = "completed";
        response["progress"] = 100;

        res.write(response.dump());

    } catch (const std::exception& e) {
        json error;
        error["error"] = e.what();
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

void OSSAnalysisRoutes::run_analysis_job(const std::string& job_id, const std::string& task_id) {
    // Placeholder implementation - actual analysis would go here
    // For now, just mark as completed after a brief delay
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    std::lock_guard<std::mutex> lock(jobs_mutex_);
    // Job completed - in a real implementation, this would update status
}

crow::response OSSAnalysisRoutes::handle_ai_filter_start(const crow::request& req) {
    // TODO: Integrate with Python service /api/forensics/oss/ai/filter
    // This will forward to OSSFilterService.filter_oss_objects()
    // See: python_service/httpserver/routes/oss_analysis.py
    // Implementation Plan: Tasks 8-11 (Python Service Implementation)

    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    json response;
    response["success"] = false;
    response["error"] = "Python LLM service not available";
    response["message"] = "AI filtering requires Python service integration (see Tasks 8-11 in implementation plan)";
    res.code = 503;  // Service Unavailable - Python service not yet integrated
    res.write(response.dump());

    return res;
}

crow::response OSSAnalysisRoutes::handle_ai_analyze_start(const crow::request& req) {
    // TODO: Integrate with Python service /api/forensics/oss/ai/analyze
    // This will forward to OSSAnalysisService.analyze_oss_objects()
    // See: python_service/httpserver/routes/oss_analysis.py
    // Implementation Plan: Tasks 8-11 (Python Service Implementation)

    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    json response;
    response["success"] = false;
    response["error"] = "Python LLM service not available";
    response["message"] = "AI analysis requires Python service integration (see Tasks 8-11 in implementation plan)";
    res.code = 503;  // Service Unavailable - Python service not yet integrated
    res.write(response.dump());

    return res;
}

crow::response OSSAnalysisRoutes::handle_download_object(const crow::request& req) {
    // TODO: Implement OSS object download functionality
    // This will use OSSClient.downloadObject() method
    // Implementation Plan: Task 6 (C++ Backend - Download Endpoint)
    //
    // Expected flow:
    // 1. Validate request contains bucket_name and object_key
    // 2. Call oss_client_->downloadObject()
    // 3. Store downloaded file in analysis workspace
    // 4. Return file path and metadata to client

    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    json response;
    response["success"] = false;
    response["error"] = "OSS download not yet implemented";
    response["message"] = "Download functionality requires OSSClient integration (see Task 6 in implementation plan)";
    res.code = 501;  // Not Implemented - C++ feature pending
    res.write(response.dump());

    return res;
}

crow::response OSSAnalysisRoutes::handle_ai_analysis_status(const crow::request& req) {
    // TODO: Integrate with Python service /api/forensics/oss/ai/status
    // This will query Python service job status and return aggregated results
    // See: python_service/httpserver/routes/oss_analysis.py
    // Implementation Plan: Tasks 8-11 (Python Service Implementation)
    //
    // Expected flow:
    // 1. Validate job_id parameter
    // 2. Query Python service for job status
    // 3. Return job progress, results, and status

    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    json response;
    response["success"] = false;
    response["error"] = "Python LLM service not available";
    response["message"] = "AI status tracking requires Python service integration (see Tasks 8-11 in implementation plan)";
    res.code = 503;  // Service Unavailable - Python service not yet integrated
    res.write(response.dump());

    return res;
}

} // namespace forensics
