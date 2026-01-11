#include "HTTPserver.h"
#include "FullTextSearch/FullTextSearch.h"
#include "FullTextSearch/TextExtractor.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <filesystem>
#include <ctime>
#include <cstdlib>
/*
 * 一个合法的创建请求如下：
 * curl -X POST http://localhost:8080/tasks 
 * -H "Content-Type: application/json" 
 * -d '{"image_path": "/home/ymj68520/ForensicsProject/build/David_USB_8GB.e01"}'
 *   响应：
 * {"status":"created","task_id":"c95065c7-624e-4fc7-83d8-9bee17f556e3"}
 * 一个合法的查询任务状态请求如下：
 * curl -X GET http://localhost:8080/tasks/c95065c7-624e-4fc7-83d8-9bee17f556e3
 *   响应：
 * {
  "id": "c95065c7-624e-4fc7-83d8-9bee17f556e3",
  "image_path": "/home/ymj68520/ForensicsProject/build/David_USB_8GB.e01",
  "message": "Waiting to start",
  "status": "pending"
    }
 * 一个合法的结果查询请求如下：
 * curl -X GET http://localhost:8080/tasks/c95065c7-624e-4fc7-83d8-9bee17f556e3/results
 *   响应：
 *  "Task not completed yet"
*/
namespace forensics {

    // ApiResponse implementation
    nlohmann::json ApiResponse::to_json() const {
        nlohmann::json response;
        response["success"] = success;
        response["message"] = message;
        response["data"] = data;
        response["timestamp"] = timestamp;
        if (!pagination.empty()) {
            response["pagination"] = pagination;
        }
        if (!error_code.empty()) {
            response["error_code"] = error_code;
        }
        return response;
    }

    ApiResponse ApiResponse::create_success(const std::string& msg, const nlohmann::json& data) {
        ApiResponse response;
        response.success = true;
        response.message = msg;
        response.data = data ? data : nlohmann::json::object();
        auto now = std::chrono::system_clock::now();
        auto time_t = std::chrono::system_clock::to_time_t(now);
        response.timestamp = std::ctime(&time_t);
        response.timestamp = response.timestamp.substr(0, response.timestamp.length() - 1); // Remove newline
        return response;
    }

    ApiResponse ApiResponse::create_error(const std::string& msg, const std::string& error_code) {
        ApiResponse response;
        response.success = false;
        response.message = msg;
        response.error_code = error_code;
        auto now = std::chrono::system_clock::now();
        auto time_t = std::chrono::system_clock::to_time_t(now);
        response.timestamp = std::ctime(&time_t);
        response.timestamp = response.timestamp.substr(0, response.timestamp.length() - 1);
        return response;
    }

    // ConnectionPool implementation
    ConnectionPool::ConnectionPool(const std::string& db_path, size_t max_connections)
        : db_path_(db_path), max_connections_(max_connections) {
        connections_.reserve(max_connections_);
        mutexes_.reserve(max_connections_);
        
        // Initialize mutexes and connections
        for (size_t i = 0; i < max_connections_; ++i) {
            mutexes_.push_back(std::make_unique<std::mutex>());
            auto conn = std::make_unique<sqlite3*>();
            if (sqlite3_open(db_path.c_str(), conn.get()) == SQLITE_OK) {
                connections_.push_back(std::move(conn));
            }
        }
    }

    ConnectionPool::~ConnectionPool() {
        for (auto& conn : connections_) {
            if (conn && *conn) {
                sqlite3_close(*conn);
            }
        }
    }

    ConnectionPool::ConnectionGuard ConnectionPool::get_connection() {
        static size_t next_idx = 0;
        for (size_t i = 0; i < connections_.size(); ++i) {
            size_t idx = (next_idx + i) % connections_.size();
            if (connections_[idx] && mutexes_[idx]->try_lock()) {
                next_idx = (idx + 1) % connections_.size();
                return ConnectionGuard(*connections_[idx], mutexes_[idx].get());
            }
        }
        // Fallback: wait for the first connection
        mutexes_[0]->lock();
        return ConnectionGuard(*connections_[0], mutexes_[0].get());
    }

    // Static member definitions for SQLiteHelperEnhanced
    std::unordered_map<std::string, std::shared_ptr<ConnectionPool>> SQLiteHelperEnhanced::connection_pools_;
    std::mutex SQLiteHelperEnhanced::pool_mutex_;
    std::unordered_map<std::string, SQLiteHelperEnhanced::CacheEntry> SQLiteHelperEnhanced::query_cache_;
    std::mutex SQLiteHelperEnhanced::cache_mutex_;

    // SQLiteHelperEnhanced implementation - will be added from HTTPServerEnhanced.cpp
    // (Implementation will continue in the following section...)

    HTTPServer::HTTPServer(asio::io_context& ioc) : task_manager_(TaskManager::instance()), ioc_(ioc) {
        // Basic task management routes
        CROW_ROUTE(app_, "/tasks").methods("POST"_method)([this](const crow::request& req) {
            return handle_create_task(req);
        });

        CROW_ROUTE(app_, "/tasks/<string>").methods("GET"_method)([this](const crow::request& req, const std::string& task_id) {
            return handle_get_task(req, task_id);
        });

        CROW_ROUTE(app_, "/tasks/<string>/results").methods("GET"_method)([this](const crow::request& req, const std::string& task_id) {
            return handle_get_task_results(req, task_id);
        });

        // Enhanced task management routes
        CROW_ROUTE(app_, "/api/tasks/list").methods("GET"_method)([this](const crow::request& req) {
            return handle_list_tasks(req);
        });

        CROW_ROUTE(app_, "/api/tasks/<string>").methods("DELETE"_method)([this](const crow::request& req, const std::string& task_id) {
            return handle_cancel_task(req, task_id);
        });

        CROW_ROUTE(app_, "/api/tasks/<string>/progress").methods("GET"_method)([this](const crow::request& req, const std::string& task_id) {
            return handle_get_task_progress(req, task_id);
        });

        CROW_ROUTE(app_, "/api/tasks/statistics").methods("GET"_method)([this](const crow::request& req) {
            return handle_get_task_statistics(req);
        });

        CROW_ROUTE(app_, "/api/tasks/cleanup").methods("POST"_method)([this](const crow::request& req) {
            return handle_cleanup_tasks(req);
        });

        // Batch operations routes
        CROW_ROUTE(app_, "/api/tasks/batch-create").methods("POST"_method)([this](const crow::request& req) {
            return handle_batch_create_tasks(req);
        });

        CROW_ROUTE(app_, "/api/tasks/batch-status").methods("POST"_method)([this](const crow::request& req) {
            return handle_batch_status(req);
        });

        CROW_ROUTE(app_, "/api/tasks/batch-cancel").methods("POST"_method)([this](const crow::request& req) {
            return handle_batch_cancel(req);
        });

        // Advanced task features routes
        CROW_ROUTE(app_, "/api/tasks/<string>/audit-log").methods("GET"_method)([this](const crow::request& req, const std::string& task_id) {
            return handle_get_task_audit_log(req, task_id);
        });

        CROW_ROUTE(app_, "/api/tasks/<string>/priority").methods("PUT"_method)([this](const crow::request& req, const std::string& task_id) {
            return handle_update_task_priority(req, task_id);
        });

        // Timeline Analysis Routes
        CROW_ROUTE(app_, "/api/forensics/timeline/comprehensive").methods("GET"_method)([this](const crow::request& req) {
            return handle_timeline_comprehensive(req);
        });

        CROW_ROUTE(app_, "/api/forensics/timeline/file-activity").methods("GET"_method)([this](const crow::request& req) {
            return handle_timeline_file_activity(req);
        });

        CROW_ROUTE(app_, "/api/forensics/timeline/suspicious-patterns").methods("GET"_method)([this](const crow::request& req) {
            return handle_timeline_suspicious_patterns(req);
        });

        CROW_ROUTE(app_, "/api/forensics/timeline/user-activity").methods("GET"_method)([this](const crow::request& req) {
            return handle_timeline_user_activity(req);
        });

        // File Analysis Routes
        CROW_ROUTE(app_, "/api/forensics/files/largest").methods("GET"_method)([this](const crow::request& req) {
            return handle_files_largest(req);
        });

        CROW_ROUTE(app_, "/api/forensics/files/recent").methods("GET"_method)([this](const crow::request& req) {
            return handle_files_recent(req);
        });

        CROW_ROUTE(app_, "/api/forensics/files/suspicious").methods("GET"_method)([this](const crow::request& req) {
            return handle_files_suspicious(req);
        });

        CROW_ROUTE(app_, "/api/forensics/files/duplicates").methods("GET"_method)([this](const crow::request& req) {
            return handle_files_duplicates(req);
        });

        CROW_ROUTE(app_, "/api/forensics/files/extensions-analysis").methods("GET"_method)([this](const crow::request& req) {
            return handle_files_extensions_analysis(req);
        });

        // Android Forensics Specialized Routes
        CROW_ROUTE(app_, "/api/forensics/android/communication-summary").methods("GET"_method)([this](const crow::request& req) {
            return handle_android_communication_summary(req);
        });

        CROW_ROUTE(app_, "/api/forensics/android/app-usage").methods("GET"_method)([this](const crow::request& req) {
            return handle_android_app_usage(req);
        });

        CROW_ROUTE(app_, "/api/forensics/android/device-info").methods("GET"_method)([this](const crow::request& req) {
            return handle_android_device_info(req);
        });

        CROW_ROUTE(app_, "/api/forensics/android/media-analysis").methods("GET"_method)([this](const crow::request& req) {
            return handle_android_media_analysis(req);
        });

        // Statistical Analysis Routes
        CROW_ROUTE(app_, "/api/forensics/statistics/overview").methods("GET"_method)([this](const crow::request& req) {
            return handle_statistics_overview(req);
        });

        CROW_ROUTE(app_, "/api/forensics/statistics/file-distribution").methods("GET"_method)([this](const crow::request& req) {
            return handle_statistics_file_distribution(req);
        });

        CROW_ROUTE(app_, "/api/forensics/statistics/activity-patterns").methods("GET"_method)([this](const crow::request& req) {
            return handle_statistics_activity_patterns(req);
        });

        CROW_ROUTE(app_, "/api/forensics/statistics/deleted-files-analysis").methods("GET"_method)([this](const crow::request& req) {
            return handle_statistics_deleted_files_analysis(req);
        });

        // System Information and Monitoring Routes
        CROW_ROUTE(app_, "/api/system/health").methods("GET"_method)([this](const crow::request& req) {
            return handle_system_health(req);
        });

        CROW_ROUTE(app_, "/api/system/info").methods("GET"_method)([this](const crow::request& req) {
            return handle_system_info(req);
        });

        CROW_ROUTE(app_, "/api/system/databases").methods("GET"_method)([this](const crow::request& req) {
            return handle_system_databases(req);
        });

        CROW_ROUTE(app_, "/api/system/database-schema/<string>").methods("GET"_method)([this](const crow::request& req, const std::string& db_type) {
            return handle_system_database_schema(req, db_type);
        });

        // Full-Text Search Routes
        CROW_ROUTE(app_, "/api/search/fulltext").methods("GET"_method)([this](const crow::request& req) {
            return handle_fulltext_search(req);
        });

        CROW_ROUTE(app_, "/api/search/index").methods("POST"_method)([this](const crow::request& req) {
            return handle_fulltext_index(req);
        });

        // Utility Routes
        CROW_ROUTE(app_, "/api/docs/endpoints").methods("GET"_method)([this](const crow::request& req) {
            return handle_docs_endpoints(req);
        });

        CROW_ROUTE(app_, "/api/docs/database-schema").methods("GET"_method)([this](const crow::request& req) {
            return handle_docs_database_schema(req);
        });

        CROW_ROUTE(app_, "/api/export/<string>").methods("POST"_method)([this](const crow::request& req, const std::string& task_id) {
            return handle_export_results(req, task_id);
        });
    }

    void HTTPServer::run(int port) {
        std::cout << "Starting HTTP server on port " << port << std::endl;
        app_.port(port).multithreaded().run();
    }

    crow::response HTTPServer::handle_create_task(const crow::request& req) {
        crow::response res;
        try {
            auto body = json::parse(req.body);
            std::string image_path = body["image_path"];

            // Enhanced options for task creation
            TaskPriority priority = TaskPriority::NORMAL;
            if (body.contains("priority")) {
                priority = priority_from_string(body["priority"]);
            }

            std::map<std::string, std::string> metadata;
            if (body.contains("metadata")) {
                for (auto& [key, value] : body["metadata"].items()) {
                    metadata[key] = value.get<std::string>();
                }
            }

            std::vector<TaskDependency> dependencies;
            if (body.contains("dependencies")) {
                for (const auto& dep : body["dependencies"]) {
                    dependencies.push_back({dep["task_id"], dep.value("required", true)});
                }
            }

            bool android_analyze = false;
            if (body.contains("android_analyze")) {
                android_analyze = body["android_analyze"];
            }

            XFSMode xfs_mode = XFSMode::Auto;
            if (body.contains("xfs_mode")) {
                std::string mode_str = body["xfs_mode"];
                if (mode_str == "native") xfs_mode = XFSMode::Native;
                else if (mode_str == "pure") xfs_mode = XFSMode::Pure;
            }

            std::string db_output_dir = "";
            if (body.contains("db_output_dir")) {
                db_output_dir = body["db_output_dir"];
            }

            std::string task_id = task_manager_.create_task(image_path, priority, metadata, dependencies);
            task_manager_.set_android_analyze_options(task_id, android_analyze, xfs_mode, db_output_dir);

            // Check if task can start immediately (no dependencies)
            if (task_manager_.can_start_task(task_id)) {
                task_manager_.start_analysis(task_id);
            }

            json response = {
                {"task_id", task_id},
                {"status", "created"},
                {"priority", priority_to_string(priority)},
                {"dependencies_count", dependencies.size()}
            };

            res.code = 201;
            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } catch (const std::exception& e) {
            res.code = 400;
            res.write("Invalid request: " + std::string(e.what()));
        }
        return res;
    }

    crow::response HTTPServer::handle_get_task(const crow::request& req, const std::string& task_id) {
        crow::response res;
        AnalysisTask task = task_manager_.get_task(task_id);

        if (task.id.empty()) {
            json error = {{"error", "Task not found"}, {"task_id", task_id}};
            res.code = 404;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        json response = task_to_json(task);
        res.set_header("Content-Type", "application/json");
        res.write(response.dump());
        return res;
    }

    crow::response HTTPServer::handle_get_task_results(const crow::request& req, const std::string& task_id) {
        crow::response res;
        AnalysisTask task = task_manager_.get_task(task_id);

        if (task.id.empty()) {
            json error = {{"error", "Task not found"}, {"task_id", task_id}};
            res.code = 404;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        if (task.status != TaskStatus::COMPLETED) {
            json response = {
                {"status", status_to_string(task.status)},
                {"message", "Task not completed yet"},
                {"task_id", task_id}
            };
            res.code = 202;
            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
            return res;
        }

        try {
            // Check for cached results first
            std::string cached_result = task_manager_.get_cached_result(task_id);
            if (!cached_result.empty()) {
                res.set_header("Content-Type", "application/json");
                res.write(cached_result);
                return res;
            }

            auto summary = SQLiteHelper::get_file_summary(task.output_files_db);
            json response = {
                {"task_id", task_id},
                {"status", "completed"},
                {"results", summary},
                {"output_files_db", task.output_files_db}
            };

            // Cache the results
            task_manager_.cache_result(task_id, response.dump());

            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } catch (const std::exception& e) {
            json error = {
                {"error", "Failed to retrieve results"},
                {"message", e.what()},
                {"task_id", task_id}
            };
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    // Timeline Analysis Endpoints Implementation
    crow::response HTTPServer::handle_timeline_comprehensive(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");
        std::string start_time = params.get("start_time") ? params.get("start_time") : "";
        std::string end_time = params.get("end_time") ? params.get("end_time") : "";

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string raw_db = get_database_path(task_id, "raw");
            std::string events_db = get_database_path(task_id, "events");

            json result = SQLiteHelper::get_comprehensive_timeline(raw_db, events_db, start_time, end_time);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_timeline_file_activity(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");
        std::string file_path = params.get("file_path") ? params.get("file_path") : "";
        std::string inode_str = params.get("inode") ? params.get("inode") : "";

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string raw_db = get_database_path(task_id, "raw");
            std::string events_db = get_database_path(task_id, "events");

            int64_t inode = inode_str.empty() ? -1 : std::stoll(inode_str);

            json result = SQLiteHelper::get_file_activity_timeline(raw_db, events_db, file_path, inode);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_timeline_suspicious_patterns(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string raw_db = get_database_path(task_id, "raw");
            std::string events_db = get_database_path(task_id, "events");

            json result = SQLiteHelper::get_suspicious_patterns(raw_db, events_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_timeline_user_activity(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string raw_db = get_database_path(task_id, "raw");
            std::string events_db = get_database_path(task_id, "events");

            json result = SQLiteHelper::get_user_activity_analysis(raw_db, events_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    // File Analysis Endpoints Implementation
    crow::response HTTPServer::handle_files_largest(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");
        std::string limit_str = params.get("limit") ? params.get("limit") : "50";

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string files_db = get_database_path(task_id, "files");
            int limit = std::stoi(limit_str);

            json result = SQLiteHelper::get_largest_files(files_db, limit);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_files_recent(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");
        std::string hours = params.get("hours") ? params.get("hours") : "24";

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string files_db = get_database_path(task_id, "files");

            json result = SQLiteHelper::get_recent_files(files_db, hours);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_files_suspicious(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string raw_db = get_database_path(task_id, "raw");
            std::string files_db = get_database_path(task_id, "files");

            json result = SQLiteHelper::get_suspicious_files(raw_db, files_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_files_duplicates(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string files_db = get_database_path(task_id, "files");

            json result = SQLiteHelper::get_duplicate_files(files_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_files_extensions_analysis(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string files_db = get_database_path(task_id, "files");

            json result = SQLiteHelper::get_extensions_analysis(files_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    // Android Forensics Specialized Endpoints Implementation
    crow::response HTTPServer::handle_android_communication_summary(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string android_db = get_database_path(task_id, "android");

            json result = SQLiteHelper::get_android_communication_summary(android_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_android_app_usage(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string android_db = get_database_path(task_id, "android");

            json result = SQLiteHelper::get_android_app_usage(android_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_android_device_info(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string android_db = get_database_path(task_id, "android");

            json result = SQLiteHelper::get_android_device_info(android_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_android_media_analysis(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string android_db = get_database_path(task_id, "android");

            json result = SQLiteHelper::get_android_media_analysis(android_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    // Statistical Analysis Endpoints Implementation
    crow::response HTTPServer::handle_statistics_overview(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string raw_db = get_database_path(task_id, "raw");
            std::string files_db = get_database_path(task_id, "files");
            std::string events_db = get_database_path(task_id, "events");

            json result = SQLiteHelper::get_overview_statistics(raw_db, files_db, events_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_statistics_file_distribution(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string files_db = get_database_path(task_id, "files");

            json result = SQLiteHelper::get_file_distribution_analysis(files_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_statistics_activity_patterns(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string events_db = get_database_path(task_id, "events");

            json result = SQLiteHelper::get_activity_patterns(events_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_statistics_deleted_files_analysis(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            std::string raw_db = get_database_path(task_id, "raw");

            json result = SQLiteHelper::get_deleted_files_analysis(raw_db);

            res.set_header("Content-Type", "application/json");
            res.write(result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    // Helper methods implementation
    std::string HTTPServer::get_database_path(const std::string& task_id, const std::string& db_type) {
        AnalysisTask task = task_manager_.get_task(task_id);
        if (task.id.empty()) {
            throw std::runtime_error("Task not found: " + task_id);
        }

        if (db_type == "raw") {
            return task.output_raw_db;
        } else if (db_type == "events") {
            return task.output_events_db;
        } else if (db_type == "files") {
            return task.output_files_db;
        } else if (db_type == "android") {
            // Android database path might be different - look for it in task metadata
            if (task.metadata.find("android_db") != task.metadata.end()) {
                return task.metadata["android_db"];
            }
            // Default naming pattern
            return task.output_raw_db.substr(0, task.output_raw_db.find_last_of('.')) + "_android.db";
        } else {
            throw std::runtime_error("Unknown database type: " + db_type);
        }
      }

    // Enhanced task management endpoints implementations
    crow::response HTTPServer::handle_list_tasks(const crow::request& req) {
        crow::response res;
        try {
            std::string status_filter = "";
            std::string priority_filter = "";
            int limit = 100;
            int offset = 0;

            // Parse query parameters
            if (req.url_params.get("status") != nullptr) {
                status_filter = req.url_params.get("status");
            }
            if (req.url_params.get("priority") != nullptr) {
                priority_filter = req.url_params.get("priority");
            }
            if (req.url_params.get("limit") != nullptr) {
                limit = std::stoi(req.url_params.get("limit"));
            }
            if (req.url_params.get("offset") != nullptr) {
                offset = std::stoi(req.url_params.get("offset"));
            }

            auto all_tasks = task_manager_.get_all_tasks();
            std::vector<json> filtered_tasks;

            for (const auto& task : all_tasks) {
                bool matches = true;

                if (!status_filter.empty() && status_to_string(task.status) != status_filter) {
                    matches = false;
                }

                if (!priority_filter.empty() && priority_to_string(task.priority) != priority_filter) {
                    matches = false;
                }

                if (matches) {
                    filtered_tasks.push_back(task_to_json(task));
                }
            }

            // Apply pagination
            int total = filtered_tasks.size();
            auto start_it = filtered_tasks.begin() + std::min(offset, total);
            auto end_it = filtered_tasks.begin() + std::min(offset + limit, total);
            std::vector<json> paginated_tasks(start_it, end_it);

            json response = {
                {"tasks", paginated_tasks},
                {"pagination", {
                    {"total", total},
                    {"limit", limit},
                    {"offset", offset},
                    {"has_more", offset + limit < total}
                }},
                {"filters", {
                    {"status", status_filter.empty() ? "all" : status_filter},
                    {"priority", priority_filter.empty() ? "all" : priority_filter}
                }}
            };

            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    crow::response HTTPServer::handle_cancel_task(const crow::request& req, const std::string& task_id) {
        crow::response res;
        try {
            std::string reason = "Cancelled via API";

            // Try to parse request body for reason
            try {
                auto body = json::parse(req.body);
                if (body.contains("reason")) {
                    reason = body["reason"];
                }
            } catch (...) {
                // Body parsing failed, use default reason
            }

            bool success = task_manager_.cancel_task(task_id, reason);

            if (success) {
                json response = {
                    {"success", true},
                    {"task_id", task_id},
                    {"message", "Task cancelled successfully"},
                    {"reason", reason}
                };
                res.set_header("Content-Type", "application/json");
                res.write(response.dump());
            } else {
                json error = {
                    {"success", false},
                    {"task_id", task_id},
                    {"error", "Task not found or cannot be cancelled"}
                };
                res.code = 404;
                res.set_header("Content-Type", "application/json");
                res.write(error.dump());
            }
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    crow::response HTTPServer::handle_get_task_progress(const crow::request& req, const std::string& task_id) {
        crow::response res;
        try {
            AnalysisTask task = task_manager_.get_task(task_id);

            if (task.id.empty()) {
                json error = {{"error", "Task not found"}, {"task_id", task_id}};
                res.code = 404;
                res.set_header("Content-Type", "application/json");
                res.write(error.dump());
                return res;
            }

            TaskProgress progress = task_manager_.get_task_progress(task_id);

            json response = {
                {"task_id", task_id},
                {"status", status_to_string(task.status)},
                {"progress", {
                    {"current_phase", phase_to_string(progress.current_phase)},
                    {"phase_description", progress.phase_description},
                    {"phase_percentage", progress.phase_percentage},
                    {"overall_percentage", progress.overall_percentage}
                }}
            };

            // Add estimated completion time if available
            if (progress.estimated_completion > progress.phase_start_time) {
                auto now = std::chrono::steady_clock::now();
                auto remaining_seconds = std::chrono::duration_cast<std::chrono::seconds>(
                    progress.estimated_completion - now).count();
                if (remaining_seconds > 0) {
                    response["progress"]["estimated_completion_seconds"] = remaining_seconds;
                }
            }

            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    crow::response HTTPServer::handle_get_task_statistics(const crow::request& req) {
        crow::response res;
        try {
            auto stats = task_manager_.get_task_statistics();
            res.set_header("Content-Type", "application/json");
            res.write(stats.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    crow::response HTTPServer::handle_cleanup_tasks(const crow::request& req) {
        crow::response res;
        try {
            int max_age_hours = 24;

            // Try to parse request body for max_age_hours
            try {
                auto body = json::parse(req.body);
                if (body.contains("max_age_hours")) {
                    max_age_hours = body["max_age_hours"];
                }
            } catch (...) {
                // Body parsing failed, use default value
            }

            int removed_count = task_manager_.cleanup_completed_tasks(max_age_hours);

            json response = {
                {"success", true},
                {"removed_tasks_count", removed_count},
                {"max_age_hours", max_age_hours},
                {"message", "Completed tasks cleanup executed"}
            };

            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    // Batch operations implementations
    crow::response HTTPServer::handle_batch_create_tasks(const crow::request& req) {
        crow::response res;
        try {
            auto body = json::parse(req.body);
            auto image_paths = body["image_paths"].get<std::vector<std::string>>();

            TaskPriority priority = TaskPriority::NORMAL;
            if (body.contains("priority")) {
                priority = priority_from_string(body["priority"]);
            }

            auto task_ids = task_manager_.create_batch_tasks(image_paths, priority);

            // Start analysis for tasks without dependencies
            int started_immediately = 0;
            for (const auto& task_id : task_ids) {
                if (task_manager_.can_start_task(task_id)) {
                    task_manager_.start_analysis(task_id);
                    started_immediately++;
                }
            }

            json response = {
                {"success", true},
                {"task_ids", task_ids},
                {"count", task_ids.size()},
                {"started_immediately", started_immediately},
                {"priority", priority_to_string(priority)}
            };

            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    crow::response HTTPServer::handle_batch_status(const crow::request& req) {
        crow::response res;
        try {
            auto body = json::parse(req.body);
            auto task_ids = body["task_ids"].get<std::vector<std::string>>();

            json response = {
                {"tasks", json::array()},
                {"summary", {
                    {"total", task_ids.size()},
                    {"pending", 0},
                    {"running", 0},
                    {"completed", 0},
                    {"failed", 0},
                    {"cancelled", 0}
                }}
            };

            for (const auto& task_id : task_ids) {
                auto task = task_manager_.get_task(task_id);
                json task_json = task_to_json(task);
                response["tasks"].push_back(task_json);

                // Update summary counters
                std::string status = status_to_string(task.status);
                if (response["summary"].contains(status)) {
                    response["summary"][status] = response["summary"][status].get<int>() + 1;
                }
            }

            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    crow::response HTTPServer::handle_batch_cancel(const crow::request& req) {
        crow::response res;
        try {
            auto body = json::parse(req.body);
            auto task_ids = body["task_ids"].get<std::vector<std::string>>();
            std::string reason = body.value("reason", "Batch cancelled via API");

            auto cancelled_ids = task_manager_.cancel_multiple_tasks(task_ids, reason);

            json response = {
                {"success", true},
                {"cancelled_task_ids", cancelled_ids},
                {"requested_count", task_ids.size()},
                {"cancelled_count", cancelled_ids.size()},
                {"reason", reason}
            };

            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    // Advanced task features implementations
    crow::response HTTPServer::handle_get_task_audit_log(const crow::request& req, const std::string& task_id) {
        crow::response res;
        try {
            auto task = task_manager_.get_task(task_id);

            if (task.id.empty()) {
                json error = {{"error", "Task not found"}, {"task_id", task_id}};
                res.code = 404;
                res.set_header("Content-Type", "application/json");
                res.write(error.dump());
                return res;
            }

            // Get audit logs from AuditLog module
            auto audit_logs = task_manager_.get_audit_logs(task_id);
            
            json audit_entries = json::array();
            for (const auto& entry : audit_logs) {
                auto timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
                    entry.timestamp.time_since_epoch()).count();

                json log_entry = {
                    {"id", entry.id},
                    {"timestamp", timestamp},
                    {"action", entry.action},
                    {"details", entry.details},
                    {"user_id", entry.user_id}
                };
                audit_entries.push_back(log_entry);
            }

            json response = {
                {"task_id", task_id},
                {"audit_log", audit_entries},
                {"entry_count", audit_entries.size()}
            };

            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    crow::response HTTPServer::handle_update_task_priority(const crow::request& req, const std::string& task_id) {
        crow::response res;
        try {
            auto body = json::parse(req.body);
            auto new_priority = priority_from_string(body["priority"]);

            // Note: This would require implementing set_task_priority in TaskManager
            // For now, return a response indicating the feature is planned
            json response = {
                {"success", false},
                {"message", "Priority update feature to be implemented in TaskManager"},
                {"task_id", task_id},
                {"requested_priority", priority_to_string(new_priority)}
            };

            res.code = 501; // Not Implemented
            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    // Helper methods implementations
    json HTTPServer::task_to_json(const AnalysisTask& task) {
        auto created_time = std::chrono::duration_cast<std::chrono::milliseconds>(
            task.created_time.time_since_epoch()).count();
        auto started_time = std::chrono::duration_cast<std::chrono::milliseconds>(
            task.started_time.time_since_epoch()).count();
        auto completed_time = std::chrono::duration_cast<std::chrono::milliseconds>(
            task.completed_time.time_since_epoch()).count();

        // Format dependencies
        json dependencies_json = json::array();
        for (const auto& dep : task.dependencies) {
            dependencies_json.push_back({
                {"task_id", dep.task_id},
                {"required", dep.required}
            });
        }

        // Calculate execution time if completed
        long long execution_time_seconds = 0;
        if (task.status == TaskStatus::COMPLETED || task.status == TaskStatus::FAILED) {
            execution_time_seconds = std::chrono::duration_cast<std::chrono::seconds>(
                task.completed_time - task.started_time).count();
        }

        return json{
            {"id", task.id},
            {"image_path", task.image_path},
            {"status", status_to_string(task.status)},
            {"priority", priority_to_string(task.priority)},
            {"message", task.message},
            {"output_files_db", task.output_files_db},
            {"progress", {
                {"current_phase", phase_to_string(task.progress.current_phase)},
                {"phase_percentage", task.progress.phase_percentage},
                {"overall_percentage", task.progress.overall_percentage},
                {"phase_description", task.progress.phase_description}
            }},
            {"timestamps", {
                {"created", created_time},
                {"started", started_time},
                {"completed", completed_time},
                {"execution_time_seconds", execution_time_seconds}
            }},
            {"android_analyze", task.android_analyze},
            {"xfs_mode", task.xfs_mode == XFSMode::Native ? "native" :
                       task.xfs_mode == XFSMode::Pure ? "pure" : "auto"},
            {"db_output_dir", task.db_output_dir},
            {"cancellation_requested", task.cancellation_requested.load()},
            {"dependencies", dependencies_json},
            {"dependents_count", task.dependents.size()},
            {"metadata", task.metadata},
            {"error_details", task.error_details}
        };
    }

    TaskPriority HTTPServer::priority_from_string(const std::string& priority_str) {
        if (priority_str == "low") return TaskPriority::LOW;
        if (priority_str == "normal") return TaskPriority::NORMAL;
        if (priority_str == "high") return TaskPriority::HIGH;
        if (priority_str == "critical") return TaskPriority::CRITICAL;
        return TaskPriority::NORMAL; // Default
    }

    std::string HTTPServer::priority_to_string(TaskPriority priority) {
        switch (priority) {
            case TaskPriority::LOW: return "low";
            case TaskPriority::NORMAL: return "normal";
            case TaskPriority::HIGH: return "high";
            case TaskPriority::CRITICAL: return "critical";
            default: return "normal";
        }
    }

    std::string HTTPServer::phase_to_string(TaskPhase phase) {
        switch (phase) {
            case TaskPhase::INITIALIZING: return "initializing";
            case TaskPhase::IMAGE_ANALYSIS: return "image_analysis";
            case TaskPhase::EVENT_EXTRACTION: return "event_extraction";
            case TaskPhase::FILE_CLASSIFICATION: return "file_classification";
            case TaskPhase::ANDROID_ANALYSIS: return "android_analysis";
            case TaskPhase::FINALIZING: return "finalizing";
            default: return "unknown";
        }
    }

    std::string HTTPServer::status_to_string(TaskStatus status) {
        switch (status) {
            case TaskStatus::PENDING: return "pending";
            case TaskStatus::RUNNING: return "running";
            case TaskStatus::COMPLETED: return "completed";
            case TaskStatus::FAILED: return "failed";
            case TaskStatus::CANCELLED: return "cancelled";
            default: return "unknown";
        }
    }

    // System Information and Monitoring Endpoints Implementation
    crow::response HTTPServer::handle_system_health(const crow::request& req) {
        crow::response res;
        try {
            // Get system health metrics
            auto task_stats = task_manager_.get_task_statistics();

            // Check system resources
            json health = {
                {"status", "healthy"},
                {"timestamp", std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::steady_clock::now().time_since_epoch()).count()},
                {"version", "1.0.0"},
                {"uptime", "N/A"}, // Could be implemented if needed
                {"task_management", {
                    {"total_tasks", task_stats["total_tasks"]},
                    {"running_tasks", task_stats["by_status"]["running"]},
                    {"failed_tasks", task_stats["by_status"]["failed"]},
                    {"system_load", "low"}
                }},
                {"services", {
                    {"http_server", "running"},
                    {"task_manager", "running"},
                    {"database_access", "available"}
                }}
            };

            res.set_header("Content-Type", "application/json");
            res.write(health.dump());
        } catch (const std::exception& e) {
            json error = {{"status", "unhealthy"}, {"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    crow::response HTTPServer::handle_system_info(const crow::request& req) {
        crow::response res;
        try {
            json info = {
                {"api_name", "Forensic Analysis HTTP Server"},
                {"version", "1.0.0"},
                {"description", "Comprehensive REST API for digital forensics analysis"},
                {"supported_formats", {"E01", "DD"}},
                {"supported_filesystems", {"NTFS", "FAT", "EXT2/3/4", "XFS"}},
                {"capabilities", {
                    {"timeline_analysis", true},
                    {"file_classification", true},
                    {"android_forensics", true},
                    {"deleted_file_recovery", true},
                    {"batch_operations", true}
                }},
                {"endpoints_count", 40},
                {"database_types", {"raw", "events", "files", "android"}}
            };

            res.set_header("Content-Type", "application/json");
            res.write(info.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    crow::response HTTPServer::handle_system_databases(const crow::request& req) {
        crow::response res;
        auto params = crow::query_string(req.url_params);
        std::string task_id = params.get("task_id");

        if (task_id.empty()) {
            json error = {{"error", "task_id parameter is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            AnalysisTask task = task_manager_.get_task(task_id);
            if (task.id.empty()) {
                json error = {{"error", "Task not found"}, {"task_id", task_id}};
                res.code = 404;
                res.set_header("Content-Type", "application/json");
                res.write(error.dump());
                return res;
            }

            json databases = {
                {"task_id", task_id},
                {"databases", {
                    {
                        {"type", "raw"},
                        {"path", task.output_raw_db},
                        {"description", "Complete filesystem metadata"},
                        {"tables", {"files", "partitions"}}
                    },
                    {
                        {"type", "events"},
                        {"path", task.output_events_db},
                        {"description", "Timeline events and activity patterns"},
                        {"tables", {"events", "creation_events", "modification_events", "access_events", "change_events", "deletion_events"}}
                    },
                    {
                        {" type", "files"},
                        {"path", task.output_files_db},
                        {"description", "Categorized files in 24 categories"},
                        {"tables", {"files", "images", "videos", "audio", "documents", "archives", "executables", "databases", "source_code", "web_files", "email_files", "system_files", "encrypted_files", "os_config_files", "os_boot_files", "os_libraries", "fs_journal", "fs_metadata", "log_files", "cache_files", "temp_files", "backup_files", "font_files", "certificates", "unknown_files"}}
                    }
                }}
            };

            // Add Android database if Android analysis was enabled
            if (task.android_analyze) {
                std::string android_db = task.output_raw_db.substr(0, task.output_raw_db.find_last_of('.')) + "_android.db";
                if (std::filesystem::exists(android_db)) {
                    databases["databases"].push_back({
                        {"type", "android"},
                        {"path", android_db},
                        {"description", "Android-specific forensic data"},
                        {"tables", {"sms_messages", "whatsapp_messages", "contacts", "call_logs", "installed_packages", "system_build_properties", "framework_files"}}
                    });
                }
            }

            res.set_header("Content-Type", "application/json");
            res.write(databases.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    crow::response HTTPServer::handle_system_database_schema(const crow::request& req, const std::string& db_type) {
        crow::response res;
        try {
            json schema;

            if (db_type == "raw") {
                schema = {
                    {"database_type", "raw"},
                    {"description", "Complete filesystem metadata extracted from disk images"},
                    {"tables", {
                        {
                            {"name", "files"},
                            {"description", "All file system entries with metadata"},
                            {"columns", {
                                {"id", "INTEGER PRIMARY KEY"},
                                {"inode", "INTEGER"},
                                {"name", "TEXT"},
                                {"path", "TEXT"},
                                {"size", "INTEGER"},
                                {"atime", "INTEGER"},
                                {"mtime", "INTEGER"},
                                {"ctime", "INTEGER"},
                                {"crtime", "INTEGER"},
                                {"type", "TEXT"},
                                {"md5", "TEXT"},
                                {"is_deleted", "INTEGER"},
                                {"is_allocated", "INTEGER"},
                                {"permissions", "TEXT"},
                                {"uid", "INTEGER"},
                                {"gid", "INTEGER"}
                            }}
                        },
                        {
                            {"name", "partitions"},
                            {"description", "Disk partition information"},
                            {"columns", {
                                {"id", "INTEGER PRIMARY KEY"},
                                {"partition_num", "INTEGER"},
                                {"start_offset", "INTEGER"},
                                {"length", "INTEGER"},
                                {"description", "TEXT"},
                                {"fs_type", "TEXT"}
                            }}
                        }
                    }}
                };
            } else if (db_type == "events") {
                schema = {
                    {"database_type", "events"},
                    {"description", "Filesystem timeline events and activity analysis"},
                    {"tables", {
                        {
                            {"name", "events"},
                            {"description", "Consolidated timeline of all filesystem events"},
                            {"columns", {
                                {"id", "INTEGER PRIMARY KEY"},
                                {"timestamp", "INTEGER"},
                                {"event_type", "TEXT"},
                                {"file_path", "TEXT"},
                                {"inode", "INTEGER"},
                                {"description", "TEXT"},
                                {"file_size", "INTEGER"},
                                {"file_type", "TEXT"}
                            }}
                        }
                    }}
                };
            } else if (db_type == "files") {
                schema = {
                    {"database_type", "files"},
                    {"description", "Files categorized into 13 forensic-relevant categories"},
                    {"tables", {
                        {
                            {"name", "files"},
                            {"description", "Master table with all categorized files"},
                            {"columns", {
                                {"id", "INTEGER PRIMARY KEY"},
                                {"inode", "INTEGER"},
                                {"name", "TEXT"},
                                {"path", "TEXT"},
                                {"size", "INTEGER"},
                                {"extension", "TEXT"},
                                {"mtime", "INTEGER"},
                                {"ctime", "INTEGER"},
                                {"is_deleted", "INTEGER"},
                                {"md5", "TEXT"},
                                {"category", "TEXT"}
                            }}
                        }
                    }}
                };
            } else if (db_type == "android") {
                schema = {
                    {"database_type", "android"},
                    {"description", "Android-specific forensic data and artifacts"},
                    {"tables", {
                        {
                            {"name", "sms_messages"},
                            {"description", "SMS message records"},
                            {"columns", {
                                {"_id", "INTEGER PRIMARY KEY"},
                                {"address", "TEXT"},
                                {"person", "TEXT"},
                                {"date", "INTEGER"},
                                {"date_sent", "INTEGER"},
                                {"read", "INTEGER"},
                                {"type", "INTEGER"},
                                {"body", "TEXT"}
                            }}
                        }
                    }}
                };
            } else {
                json error = {
                    {"error", "Unknown database type"},
                    {"supported_types", {"raw", "events", "files", "android"}}
                };
                res.code = 400;
                res.set_header("Content-Type", "application/json");
                res.write(error.dump());
                return res;
            }

            res.set_header("Content-Type", "application/json");
            res.write(schema.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    // Utility Endpoints Implementation
    crow::response HTTPServer::handle_docs_endpoints(const crow::request& req) {
        crow::response res;
        try {
            json endpoints = {
                {"title", "Forensic Analysis HTTP Server API Documentation"},
                {"version", "1.0.0"},
                {"base_url", "/api"},
                {"categories", {
                    {
                        {"name", "Task Management"},
                        {"description", "Create and manage forensic analysis tasks"},
                        {"endpoints", {
                            {
                                {"method", "POST"},
                                {"path", "/tasks"},
                                {"description", "Create new forensic analysis task"},
                                {"parameters", {
                                    {"image_path", "string (required)", "Path to disk image file"},
                                    {"android_analyze", "boolean (optional)", "Enable Android analysis"},
                                    {"priority", "string (optional)", "Task priority: low/normal/high/critical"}
                                }}
                            },
                            {
                                {"method", "GET"},
                                {"path", "/tasks/{id}"},
                                {"description", "Get task status and details"}
                            },
                            {
                                {"method", "GET"},
                                {"path", "/tasks/{id}/results"},
                                {"description", "Get task analysis results"}
                            },
                            {
                                {"method", "GET"},
                                {"path", "/tasks/list"},
                                {"description", "List all tasks with filtering and pagination"}
                            },
                            {
                                {"method", "DELETE"},
                                {"path", "/tasks/{id}"},
                                {"description", "Cancel running task"}
                            }
                        }}
                    },
                    {
                        {"name", "Database Query"},
                        {"description", "Query forensic analysis databases directly"},
                        {"endpoints", {
                            {
                                {"method", "GET"},
                                {"path", "/raw/files"},
                                {"description", "Query raw filesystem files database"}
                            },
                            {
                                {"method", "GET"},
                                {"path", "/events/timeline"},
                                {"description", "Query timeline events database"}
                            },
                            {
                                {"method", "GET"},
                                {"path", "/files/category/{category}"},
                                {"description", "Query files by category (images, videos, etc.)"}
                            },
                            {
                                {"method", "GET"},
                                {"path", "/android/sms"},
                                {"description", "Query Android SMS messages"}
                            }
                        }}
                    },
                    {
                        {"name", "Forensic Analysis"},
                        {"description", "Specialized forensic analysis endpoints"},
                        {"endpoints", {
                            {
                                {"method", "GET"},
                                {"path", "/forensics/timeline/comprehensive"},
                                {"description", "Get comprehensive timeline analysis"}
                            },
                            {
                                {"method", "GET"},
                                {"path", "/forensics/files/suspicious"},
                                {"description", "Get suspicious files analysis"}
                            },
                            {
                                {"method", "GET"},
                                {"path", "/forensics/statistics/overview"},
                                {"description", "Get analysis overview statistics"}
                            }
                        }}
                    },
                    {
                        {"name", "System Information"},
                        {"description", "System health and information endpoints"},
                        {"endpoints", {
                            {
                                {"method", "GET"},
                                {"path", "/system/health"},
                                {"description", "Get system health status"}
                            },
                            {
                                {"method", "GET"},
                                {"path", "/system/info"},
                                {"description", "Get server capabilities and information"}
                            }
                        }}
                    }
                }},
                {"total_endpoints", 40}
            };

            res.set_header("Content-Type", "application/json");
            res.write(endpoints.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    crow::response HTTPServer::handle_docs_database_schema(const crow::request& req) {
        crow::response res;
        try {
            json docs = {
                {"title", "Database Schema Documentation"},
                {"description", "Complete database schemas for forensic analysis databases"},
                {"databases", {
                    {
                        {"name", "raw"},
                        {"description", "Complete filesystem metadata extracted from disk images"},
                        {"purpose", "Stores raw TSK extraction data including all files, metadata, and partition information"},
                        {"tables", {
                            {
                                {"name", "files"},
                                {"description", "All file system entries with comprehensive metadata"},
                                {"key_fields", {"inode", "name", "path", "size", "timestamps", "md5", "allocation_status"}},
                                {"indexes", {"inode", "path", "md5", "is_deleted", "is_allocated"}}
                            },
                            {
                                {"name", "partitions"},
                                {"description", "Disk partition layout and information"},
                                {"key_fields", {"partition_num", "start_offset", "length", "fs_type"}}
                            }
                        }}
                    },
                    {
                        {"name", "events"},
                        {"description", "Timeline events extracted from filesystem timestamps"},
                        {"purpose", "Provides chronological view of file system activities"},
                        {"tables", {
                            {
                                {"name", "events"},
                                {"description", "Consolidated timeline of all filesystem events"},
                                {"key_fields", {"timestamp", "event_type", "file_path", "inode"}},
                                {"event_types", {"created", "modified", "accessed", "changed", "deleted"}}
                            }
                        }}
                    },
                    {
                        {"name", "files"},
                        {"description", "Files categorized into forensic-relevant categories"},
                        {"purpose", "Enables efficient file analysis by type and category"},
                        {"tables", {
                            {
                                {"name", "files"},
                                {"description", "Master table with all categorized files"},
                                {"categories", {"images", "videos", "audio", "documents", "archives", "executables", "databases", "source_code", "web_files", "email_files", "system_files", "encrypted_files", "os_config_files", "os_boot_files", "os_libraries", "fs_journal", "fs_metadata", "log_files", "cache_files", "temp_files", "backup_files", "font_files", "certificates", "unknown_files"}}
                            }
                        }}
                    },
                    {
                        {"name", "android"},
                        {"description", "Android-specific forensic data and artifacts"},
                        {"purpose", "Stores extracted Android device data for mobile forensics"},
                        {"tables", {
                            {
                                {"name", "sms_messages"},
                                {"description", "SMS message records with content and metadata"}
                            },
                            {
                                {"name", "whatsapp_messages"},
                                {"description", "WhatsApp message conversations"}
                            },
                            {
                                {"name", "contacts"},
                                {"description", "Contact information and phonebook data"}
                            },
                            {
                                {"name", "call_logs"},
                                {"description", "Call history and duration records"}
                            }
                        }}
                    }
                }}
            };

            res.set_header("Content-Type", "application/json");
            res.write(docs.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }

    crow::response HTTPServer::handle_export_results(const crow::request& req, const std::string& task_id) {
        crow::response res;
        try {
            auto body = json::parse(req.body);
            std::string format = body.value("format", "json");
            std::string export_type = body.value("export_type", "summary");

            AnalysisTask task = task_manager_.get_task(task_id);
            if (task.id.empty()) {
                json error = {{"error", "Task not found"}, {"task_id", task_id}};
                res.code = 404;
                res.set_header("Content-Type", "application/json");
                res.write(error.dump());
                return res;
            }

            if (task.status != TaskStatus::COMPLETED) {
                json error = {
                    {"error", "Task not completed"},
                    {"status", status_to_string(task.status)},
                    {"task_id", task_id}
                };
                res.code = 400;
                res.set_header("Content-Type", "application/json");
                res.write(error.dump());
                return res;
            }

            json export_result = {
                {"task_id", task_id},
                {"export_type", export_type},
                {"format", format},
                {"timestamp", std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::steady_clock::now().time_since_epoch()).count()},
                {"status", "completed"}
            };

            if (export_type == "summary") {
                auto summary = SQLiteHelper::get_file_summary(task.output_files_db);
                export_result["summary"] = summary;
                export_result["task_details"] = task_to_json(task);
            } else if (export_type == "database") {
                export_result["databases"] = {
                    {
                        {"type", "raw"},
                        {"path", task.output_raw_db},
                        {"size", std::filesystem::file_size(task.output_raw_db)}
                    },
                    {
                        {"type", "events"},
                        {"path", task.output_events_db},
                        {"size", std::filesystem::file_size(task.output_events_db)}
                    },
                    {
                        {"type", "files"},
                        {"path", task.output_files_db},
                        {"size", std::filesystem::file_size(task.output_files_db)}
                    }
                };
            }

            res.set_header("Content-Type", "application/json");
            res.write(export_result.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
        return res;
    }


    // Full-Text Search Implementation
    crow::response HTTPServer::handle_fulltext_search(const crow::request& req) {
        crow::response res;

        auto params = crow::query_string(req.url_params);
        std::string query = params.get("q") ? params.get("q") : "";
        std::string index_path = params.get("index") ? params.get("index") : "search_index_xapian";
        std::string limit_str = params.get("limit") ? params.get("limit") : "10";
        std::string offset_str = params.get("offset") ? params.get("offset") : "0";

        if (query.empty()) {
            json error = {{"error", "Query parameter 'q' is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        try {
            // Check if index exists
            if (!std::filesystem::exists(index_path)) {
                json error = {
                    {"error", "Search index not found"},
                    {"index_path", index_path},
                    {"suggestion", "Use /api/search/index to create an index first"}
                };
                res.code = 404;
                res.set_header("Content-Type", "application/json");
                res.write(error.dump());
                return res;
            }

            XapianSearcher searcher(index_path);
            if (!searcher.isValid()) {
                json error = {{"error", "Failed to open search index"}};
                res.code = 500;
                res.set_header("Content-Type", "application/json");
                res.write(error.dump());
                return res;
            }

            size_t limit = std::stoi(limit_str);
            size_t offset = std::stoi(offset_str);

            auto results = searcher.search(query, limit, offset);

            json response = {
                {"query", query},
                {"total_documents", searcher.getTotalDocuments()},
                {"results_count", results.size()},
                {"limit", limit},
                {"offset", offset},
                {"results", json::array()}
            };

            for (const auto& r : results) {
                response["results"].push_back({
                    {"path", r.path},
                    {"score", r.score},
                    {"snippet", r.snippet},
                    {"file_size", r.fileSize},
                    {"extension", r.extension}
                });
            }

            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

    crow::response HTTPServer::handle_fulltext_index(const crow::request& req) {
        crow::response res;

        try {
            auto body = json::parse(req.body);
            std::string directory = body.value("directory", "");
            std::string index_path = body.value("index_path", "search_index_xapian");

            if (directory.empty()) {
                json error = {{"error", "'directory' field is required in request body"}};
                res.code = 400;
                res.set_header("Content-Type", "application/json");
                res.write(error.dump());
                return res;
            }

            if (!std::filesystem::exists(directory)) {
                json error = {{"error", "Directory not found"}, {"path", directory}};
                res.code = 404;
                res.set_header("Content-Type", "application/json");
                res.write(error.dump());
                return res;
            }

            XapianIndexer indexer(index_path);
            int count = 0;
            std::vector<std::string> indexed_files;

            for (const auto& entry : std::filesystem::recursive_directory_iterator(directory)) {
                if (entry.is_regular_file()) {
                    std::string path = entry.path().string();
                    std::string content = TextExtractor::extract(path, 100000);  // Limit 100KB per file

                    if (!content.empty()) {
                        auto meta = TextExtractor::extractMetadata(path);
                        FileMetadata fileMeta;
                        fileMeta.path = meta.path;
                        fileMeta.extension = meta.extension;
                        fileMeta.size = meta.size;
                        fileMeta.mtime = meta.mtime;

                        indexer.addDocument(path, content, fileMeta);
                        count++;

                        if (indexed_files.size() < 10) {
                            indexed_files.push_back(path);
                        }
                    }
                }
            }
            indexer.commit();

            json response = {
                {"status", "completed"},
                {"indexed_files_count", count},
                {"index_path", index_path},
                {"source_directory", directory},
                {"sample_files", indexed_files}
            };

            res.code = 201;
            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } catch (const json::exception& e) {
            json error = {{"error", "Invalid JSON body"}, {"details", e.what()}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        } catch (const std::exception& e) {
            json error = {{"error", e.what()}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }

        return res;
    }

}
