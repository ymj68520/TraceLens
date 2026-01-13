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
#include "routes/TaskRoutes.h"
#include "routes/ForensicsRoutes.h"
#include "routes/SystemRoutes.h"
#include "routes/SearchRoutes.h"

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

        // Modular Route Handlers
        TaskRoutes task_routes_;
        ForensicsRoutes forensics_routes_;
        SystemRoutes system_routes_;
        SearchRoutes search_routes_;
    };
}