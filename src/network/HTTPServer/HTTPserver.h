#pragma once

#include <crow.h>
#include <asio.hpp>
#include <asio/co_spawn.hpp>
#include <asio/detached.hpp>
#include <asio/awaitable.hpp>
#include <asio/use_awaitable.hpp>
#include <memory>
#include <string>
#include <nlohmann/json.hpp>
#include <chrono>
#include <unordered_map>
#include <mutex>
#include <thread>
#include <sqlite3.h>
#include "TaskManager.h"
#include "SQLiteHelper.h"
#include "Utils.h"

namespace forensics {
    using json = nlohmann::json;

    // Standard API response wrapper
    struct ApiResponse {
        bool success = true;
        std::string message;
        nlohmann::json data;
        std::string timestamp;
        nlohmann::json pagination;
        std::string error_code;

        nlohmann::json to_json() const;
        static ApiResponse create_success(const std::string& msg = "", const nlohmann::json& data = nullptr);
        static ApiResponse create_error(const std::string& msg, const std::string& error_code = "");
    };

    // Database connection pool
    class ConnectionPool {
    private:
        std::vector<std::unique_ptr<sqlite3*>> connections_;
        std::vector<std::unique_ptr<std::mutex>> mutexes_;
        std::string db_path_;
        size_t max_connections_;

    public:
        ConnectionPool(const std::string& db_path, size_t max_connections = 5);
        ~ConnectionPool();

        struct ConnectionGuard {
            sqlite3* conn;
            std::mutex* mutex;
            ConnectionGuard(sqlite3* c, std::mutex* m) : conn(c), mutex(m) {}
            ~ConnectionGuard() {
                if (mutex) mutex->unlock();
            }
        };

        ConnectionGuard get_connection();
    };

    // Enhanced SQLite Helper with caching and performance optimizations
    class SQLiteHelperEnhanced {
    private:
        static std::unordered_map<std::string, std::shared_ptr<ConnectionPool>> connection_pools_;
        static std::mutex pool_mutex_;

        // Cache for expensive queries
        struct CacheEntry {
            nlohmann::json data;
            std::chrono::steady_clock::time_point timestamp;
            int ttl_seconds;
        };
        static std::unordered_map<std::string, CacheEntry> query_cache_;
        static std::mutex cache_mutex_;

        static std::shared_ptr<ConnectionPool> get_connection_pool(const std::string& db_path);
        static nlohmann::json get_cached_result(const std::string& cache_key);
        static void cache_result(const std::string& cache_key, const nlohmann::json& data, int ttl_seconds = 300);
        static nlohmann::json execute_query_with_timeout(const std::string& db_path, const std::string& sql, int timeout_seconds = 30);

    public:
        static nlohmann::json get_database_schema(const std::string& db_path, const std::string& table_pattern = "%");
        static nlohmann::json get_database_info(const std::string& db_path);
        static nlohmann::json export_data(const std::string& db_path, const std::string& table_name,
                                         const std::string& format = "json", int limit = 1000, int offset = 0);
        static void clear_cache();
        static nlohmann::json get_cache_stats();
        static nlohmann::json get_task_databases(const std::string& task_id);
    };

    class HTTPServer {
    public:
        HTTPServer(asio::io_context& ioc);
        ~HTTPServer() = default;

        void run(int port = 8080);

    private:
        crow::App<> app_;
        TaskManager& task_manager_;
        asio::io_context& ioc_;

        // Basic task management
        crow::response handle_create_task(const crow::request& req);
        crow::response handle_get_task(const crow::request& req, const std::string& task_id);
        crow::response handle_get_task_results(const crow::request& req, const std::string& task_id);

        // Enhanced task management endpoints
        crow::response handle_list_tasks(const crow::request& req);
        crow::response handle_cancel_task(const crow::request& req, const std::string& task_id);
        crow::response handle_get_task_progress(const crow::request& req, const std::string& task_id);
        crow::response handle_get_task_statistics(const crow::request& req);
        crow::response handle_cleanup_tasks(const crow::request& req);

        // Batch operations
        crow::response handle_batch_create_tasks(const crow::request& req);
        crow::response handle_batch_status(const crow::request& req);
        crow::response handle_batch_cancel(const crow::request& req);

        // Advanced task features
        crow::response handle_get_task_audit_log(const crow::request& req, const std::string& task_id);
        crow::response handle_update_task_priority(const crow::request& req, const std::string& task_id);

        // Timeline Analysis Endpoints
        crow::response handle_timeline_comprehensive(const crow::request& req);
        crow::response handle_timeline_file_activity(const crow::request& req);
        crow::response handle_timeline_suspicious_patterns(const crow::request& req);
        crow::response handle_timeline_user_activity(const crow::request& req);

        // File Analysis Endpoints
        crow::response handle_files_largest(const crow::request& req);
        crow::response handle_files_recent(const crow::request& req);
        crow::response handle_files_suspicious(const crow::request& req);
        crow::response handle_files_duplicates(const crow::request& req);
        crow::response handle_files_extensions_analysis(const crow::request& req);

        // Android Forensics Specialized Endpoints
        crow::response handle_android_communication_summary(const crow::request& req);
        crow::response handle_android_app_usage(const crow::request& req);
        crow::response handle_android_device_info(const crow::request& req);
        crow::response handle_android_media_analysis(const crow::request& req);

        // Statistical Analysis Endpoints
        crow::response handle_statistics_overview(const crow::request& req);
        crow::response handle_statistics_file_distribution(const crow::request& req);
        crow::response handle_statistics_activity_patterns(const crow::request& req);
        crow::response handle_statistics_deleted_files_analysis(const crow::request& req);

        // Raw Database Query Endpoints
        crow::response handle_raw_files(const crow::request& req);
        crow::response handle_raw_partitions(const crow::request& req);
        crow::response handle_raw_search(const crow::request& req);

        // Events Database Query Endpoints
        crow::response handle_events_timeline(const crow::request& req);
        crow::response handle_events_statistics(const crow::request& req);
        crow::response handle_events_hourly_activity(const crow::request& req);

        // Files Database Query Endpoints
        crow::response handle_files_category(const crow::request& req, const std::string& category);
        crow::response handle_files_deleted(const crow::request& req);
        crow::response handle_files_extensions(const crow::request& req);

        // Android Database Query Endpoints
        crow::response handle_android_sms(const crow::request& req);
        crow::response handle_android_contacts(const crow::request& req);
        crow::response handle_android_call_logs(const crow::request& req);

        // Advanced Query Endpoint
        crow::response handle_advanced_query(const crow::request& req);

        // Full-Text Search Endpoints
        crow::response handle_fulltext_search(const crow::request& req);
        crow::response handle_fulltext_index(const crow::request& req);

        // System Information and Monitoring Endpoints (from HTTPServerEnhanced)
        crow::response handle_health_check(const crow::request& req);
        crow::response handle_system_health(const crow::request& req);
        crow::response handle_system_info(const crow::request& req);
        crow::response handle_system_databases(const crow::request& req);
        crow::response handle_list_databases(const crow::request& req, const std::string& task_id);
        crow::response handle_database_schema(const crow::request& req, const std::string& type);
        crow::response handle_system_database_schema(const crow::request& req, const std::string& db_type);

        // Utility Endpoints (merged from both)
        crow::response handle_docs_endpoints(const crow::request& req);
        crow::response handle_api_docs(const crow::request& req);
        crow::response handle_docs_database_schema(const crow::request& req);
        crow::response handle_database_schema_docs(const crow::request& req);
        crow::response handle_export_results(const crow::request& req, const std::string& task_id);
        crow::response handle_export_data(const crow::request& req, const std::string& task_id);

        // Helper methods
        json task_to_json(const AnalysisTask& task);
        TaskPriority priority_from_string(const std::string& priority_str);
        std::string priority_to_string(TaskPriority priority);
        std::string phase_to_string(TaskPhase phase);
        std::string status_to_string(TaskStatus status);

        // Helper methods from HTTPServerEnhanced
        crow::response create_standard_response(const ApiResponse& api_response, int status_code = 200);
        crow::response create_error_response(const std::string& message, const std::string& error_code = "", int status_code = 400);
        nlohmann::json get_system_capabilities();
        nlohmann::json get_endpoint_documentation();
        nlohmann::json get_database_schema_documentation();

        // Database helper methods
        std::string get_database_path(const std::string& task_id, const std::string& db_type);
    };
}