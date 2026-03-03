/**
 * @file OSSRoutes.cpp
 * @brief OSS分析HTTP API路由实现
 */

#include "OSSRoutes.h"
#include "../../Swagger/Swagger.h"
#include <random>
#include <sstream>
#include <iomanip>

namespace forensics {

using json = nlohmann::json;
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
    // 启动OSS分析
    CROW_ROUTE(app, "/api/forensics/oss/analyze").methods("POST"_method, "OPTIONS"_method)([this](const crow::request& req) {
        if (req.method == "OPTIONS"_method) {
            crow::response res;
            add_cors_headers(res);
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

    // 分析状态
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

    // 获取对象列表
    CROW_ROUTE(app, "/api/forensics/oss/objects").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_objects(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/objects", "GET",
        "Get OSS objects",
        "Retrieve analyzed OSS objects from the database.",
        {"Forensics", "OSS"},
        {{"task_id", "query", "Task ID", true}, {"bucket", "query", "Filter by bucket", false}, {"prefix", "query", "Filter by key prefix", false}, {"limit", "query", "Max results", false}},
        {{200, "List of OSS objects"}}
    );

    // 获取访问日志
    CROW_ROUTE(app, "/api/forensics/oss/logs").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_access_logs(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/logs", "GET",
        "Get OSS access logs",
        "Retrieve analyzed OSS access log entries.",
        {"Forensics", "OSS"},
        {{"task_id", "query", "Task ID", true}, {"start_time", "query", "Start timestamp", false}, {"end_time", "query", "End timestamp", false}, {"operation", "query", "Filter by operation", false}},
        {{200, "List of access log entries"}}
    );

    // 获取分析摘要
    CROW_ROUTE(app, "/api/forensics/oss/summary").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_summary(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/summary", "GET",
        "Get OSS analysis summary",
        "Get summary statistics of OSS analysis.",
        {"Forensics", "OSS"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "Analysis summary"}}
    );

    // 存储类型统计
    CROW_ROUTE(app, "/api/forensics/oss/statistics/storage-class").methods("GET"_method)([this](const crow::request& req) {
        return handle_storage_class_stats(req);
    });

    // 扩展名统计
    CROW_ROUTE(app, "/api/forensics/oss/statistics/extensions").methods("GET"_method)([this](const crow::request& req) {
        return handle_extension_stats(req);
    });

    // Bucket列表
    CROW_ROUTE(app, "/api/forensics/oss/buckets").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_buckets(req);
    });
}

crow::response OSSRoutes::handle_analyze_start(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
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

        // 创建分析任务
        OSSAnalysisJob job;
        job.id = generate_job_id();
        job.task_id = task_id;
        job.status = OSSAnalysisStatus::PENDING;
        job.created_time = std::chrono::system_clock::now();

        // 解析导出类型
        std::string export_type_str = body.value("export_type", "local_directory");
        if (export_type_str == "direct_api") {
            job.export_type = OSSExportType::DIRECT_API;
        } else if (export_type_str == "inventory_csv") {
            job.export_type = OSSExportType::INVENTORY_CSV;
        } else if (export_type_str == "access_log") {
            job.export_type = OSSExportType::ACCESS_LOG;
        } else {
            job.export_type = OSSExportType::LOCAL_DIRECTORY;
        }

        // 源路径
        if (body.contains("source_path")) {
            job.source_path = body["source_path"].get<std::string>();
        }

        // 存储任务
        {
            std::lock_guard<std::mutex> lock(jobs_mutex_);
            analysis_jobs_[job.id] = job;
        }

        // 启动异步分析
        std::string job_id = job.id;
        std::thread([this, job_id]() {
            run_analysis_job(job_id);
        }).detach();

        json response = {
            {"success", true},
            {"message", "OSS analysis job started"},
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

crow::response OSSRoutes::handle_analyze_status(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    auto params = crow::query_string(req.url_params);
    std::string job_id = params.get("job_id") ? params.get("job_id") : "";

    if (job_id.empty()) {
        json error = {{"error", "job_id parameter is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    std::lock_guard<std::mutex> lock(jobs_mutex_);
    auto it = analysis_jobs_.find(job_id);
    if (it == analysis_jobs_.end()) {
        json error = {{"error", "Job not found"}};
        res.code = 404;
        res.write(error.dump());
        return res;
    }

    const auto& job = it->second;
    std::string status_str;
    switch (job.status) {
        case OSSAnalysisStatus::PENDING: status_str = "pending"; break;
        case OSSAnalysisStatus::RUNNING: status_str = "running"; break;
        case OSSAnalysisStatus::COMPLETED: status_str = "completed"; break;
        case OSSAnalysisStatus::FAILED: status_str = "failed"; break;
    }

    json response = {
        {"job_id", job.id},
        {"task_id", job.task_id},
        {"status", status_str},
        {"objects_analyzed", job.objects_analyzed},
        {"logs_analyzed", job.logs_analyzed}
    };

    if (job.status == OSSAnalysisStatus::FAILED) {
        response["error"] = job.error_message;
    }

    res.write(response.dump());
    return res;
}

void OSSRoutes::run_analysis_job(const std::string& job_id) {
    OSSAnalysisJob job;
    {
        std::lock_guard<std::mutex> lock(jobs_mutex_);
        auto it = analysis_jobs_.find(job_id);
        if (it == analysis_jobs_.end()) return;
        job = it->second;
        it->second.status = OSSAnalysisStatus::RUNNING;
    }

    try {
        // 获取任务信息
        AnalysisTask task = task_manager_.get_task(job.task_id);
        if (task.id.empty()) {
            throw std::runtime_error("Task not found: " + job.task_id);
        }

        // 创建OSS数据库路径
        std::string oss_db_path = task.output_raw_db.substr(0, task.output_raw_db.find_last_of('.')) + "_oss.db";

        // 创建分析器
        OSSAnalyzer analyzer;
        analyzer.setOutputDbPath(oss_db_path);
        analyzer.setProgressCallback([&job, this](const std::string& phase, int64_t current, int64_t total) {
            std::lock_guard<std::mutex> lock(jobs_mutex_);
            auto it = analysis_jobs_.find(job.id);
            if (it != analysis_jobs_.end()) {
                it->second.objects_analyzed = current;
            }
        });

        if (!analyzer.initialize()) {
            throw std::runtime_error("Failed to initialize OSS analyzer");
        }

        // 根据导出类型执行分析
        bool success = false;
        switch (job.export_type) {
            case OSSExportType::LOCAL_DIRECTORY:
                success = analyzer.analyzeFromLocalDirectory(job.source_path);
                break;
            case OSSExportType::INVENTORY_CSV:
                success = analyzer.analyzeFromInventory(job.source_path);
                break;
            case OSSExportType::ACCESS_LOG:
                success = analyzer.analyzeAccessLogs(job.source_path);
                break;
            case OSSExportType::DIRECT_API:
                // API模式需要配置凭证
                success = analyzer.analyzeFromAPI();
                break;
        }

        if (!success) {
            throw std::runtime_error(analyzer.getLastError());
        }

        // 获取分析结果统计
        auto summary = analyzer.getAnalysisSummary();

        // 更新任务状态
        {
            std::lock_guard<std::mutex> lock(jobs_mutex_);
            auto it = analysis_jobs_.find(job_id);
            if (it != analysis_jobs_.end()) {
                it->second.status = OSSAnalysisStatus::COMPLETED;
                it->second.objects_analyzed = summary.totalObjects;
                it->second.logs_analyzed = summary.logEntriesCount;
                it->second.completed_time = std::chrono::system_clock::now();
            }
        }

        // OSS分析db路径按约定在 get_oss_database_path 中推算，无需额外持久化
        std::cerr << "[OSS] Analysis complete, oss_db: " << oss_db_path << std::endl;

    } catch (const std::exception& e) {
        std::lock_guard<std::mutex> lock(jobs_mutex_);
        auto it = analysis_jobs_.find(job_id);
        if (it != analysis_jobs_.end()) {
            it->second.status = OSSAnalysisStatus::FAILED;
            it->second.error_message = e.what();
            it->second.completed_time = std::chrono::system_clock::now();
        }
    }
}

crow::response OSSRoutes::handle_get_objects(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string bucket = params.get("bucket") ? params.get("bucket") : "";
    std::string prefix = params.get("prefix") ? params.get("prefix") : "";
    int limit = params.get("limit") ? std::stoi(params.get("limit")) : 100;

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    try {
        std::string oss_db_path = get_oss_database_path(task_id);
        OSSAnalysisDatabase db(oss_db_path);
        if (!db.initialize()) {
            throw std::runtime_error("Failed to open OSS database");
        }

        std::vector<OSSObjectInfo> objects;
        if (!bucket.empty() && !prefix.empty()) {
            objects = db.getObjectsByPrefix(bucket, prefix);
        } else if (!bucket.empty()) {
            objects = db.getObjectsByBucket(bucket);
        } else {
            objects = db.getAllObjects();
        }

        json result = json::array();
        int count = 0;
        for (const auto& obj : objects) {
            if (count >= limit) break;
            result.push_back({
                {"bucket", obj.bucket},
                {"key", obj.key},
                {"size", obj.size},
                {"etag", obj.etag},
                {"last_modified", obj.lastModified},
                {"storage_class", obj.storageClass},
                {"content_type", obj.contentType},
                {"is_deleted", obj.isDeleted}
            });
            count++;
        }

        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response OSSRoutes::handle_get_access_logs(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    int64_t start_time = params.get("start_time") ? std::stoll(params.get("start_time")) : 0;
    int64_t end_time = params.get("end_time") ? std::stoll(params.get("end_time")) : 0;
    std::string operation = params.get("operation") ? params.get("operation") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    try {
        std::string oss_db_path = get_oss_database_path(task_id);
        OSSAnalysisDatabase db(oss_db_path);
        if (!db.initialize()) {
            throw std::runtime_error("Failed to open OSS database");
        }

        std::vector<OSSAccessLogEntry> logs;
        if (!operation.empty()) {
            logs = db.getAccessLogsByOperation(operation);
        } else {
            logs = db.getAccessLogsByTimeRange(start_time, end_time);
        }

        json result = json::array();
        for (const auto& log : logs) {
            result.push_back({
                {"request_id", log.requestId},
                {"timestamp", log.timestamp},
                {"operation", log.operation},
                {"bucket", log.bucket},
                {"object_key", log.objectKey},
                {"remote_ip", log.remoteIP},
                {"user_agent", log.userAgent},
                {"http_status", log.httpStatus},
                {"bytes_sent", log.bytesSent}
            });
        }

        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response OSSRoutes::handle_get_summary(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    try {
        std::string oss_db_path = get_oss_database_path(task_id);
        OSSAnalysisDatabase db(oss_db_path);
        if (!db.initialize()) {
            throw std::runtime_error("Failed to open OSS database");
        }

        auto summary = db.getAnalysisSummary();

        json storage_class_stats = json::object();
        for (const auto& [cls, count] : summary.objectsByStorageClass) {
            storage_class_stats[cls] = count;
        }

        json operation_stats = json::object();
        for (const auto& [op, count] : summary.operationCounts) {
            operation_stats[op] = count;
        }

        json result = {
            {"total_objects", summary.totalObjects},
            {"total_size", summary.totalSize},
            {"deleted_objects", summary.deletedObjects},
            {"log_entries_count", summary.logEntriesCount},
            {"objects_by_storage_class", storage_class_stats},
            {"operation_counts", operation_stats}
        };

        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response OSSRoutes::handle_storage_class_stats(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    try {
        std::string oss_db_path = get_oss_database_path(task_id);
        OSSAnalysisDatabase db(oss_db_path);
        if (!db.initialize()) {
            throw std::runtime_error("Failed to open OSS database");
        }

        auto stats = db.getObjectCountByStorageClass();
        json result = json::array();
        for (const auto& [cls, pair] : stats) {
            result.push_back({
                {"storage_class", cls},
                {"count", pair.first},
                {"total_size", pair.second}
            });
        }

        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response OSSRoutes::handle_extension_stats(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    try {
        std::string oss_db_path = get_oss_database_path(task_id);
        OSSAnalysisDatabase db(oss_db_path);
        if (!db.initialize()) {
            throw std::runtime_error("Failed to open OSS database");
        }

        auto stats = db.getObjectCountByExtension();
        json result = json::array();
        for (const auto& [ext, pair] : stats) {
            result.push_back({
                {"extension", ext},
                {"count", pair.first},
                {"total_size", pair.second}
            });
        }

        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response OSSRoutes::handle_get_buckets(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    try {
        std::string oss_db_path = get_oss_database_path(task_id);
        OSSAnalysisDatabase db(oss_db_path);
        if (!db.initialize()) {
            throw std::runtime_error("Failed to open OSS database");
        }

        auto buckets = db.getAllBuckets();
        json result = json::array();
        for (const auto& bucket : buckets) {
            result.push_back({
                {"name", bucket.name},
                {"region", bucket.region},
                {"acl", bucket.acl},
                {"storage_class", bucket.storageClass},
                {"object_count", bucket.objectCount},
                {"total_size", bucket.totalSize},
                {"versioning_enabled", bucket.versioningEnabled},
                {"logging_enabled", bucket.loggingEnabled}
            });
        }

        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

std::string OSSRoutes::get_oss_database_path(const std::string& task_id) {
    AnalysisTask task = task_manager_.get_task(task_id);
    if (task.id.empty()) {
        throw std::runtime_error("Task not found: " + task_id);
    }

    if (task.metadata.find("oss_db") != task.metadata.end()) {
        return task.metadata.at("oss_db");
    }

    return task.output_raw_db.substr(0, task.output_raw_db.find_last_of('.')) + "_oss.db";
}

void OSSRoutes::add_cors_headers(crow::response& res) {
    res.set_header("Access-Control-Allow-Origin", "*");
    res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
    res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
}

} // namespace forensics
