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
    /**
     * @brief Standard API response wrapper
     * Used for consistent JSON response format across all endpoints.
     */
    struct ApiResponse {
        bool success = true;        ///< Operation success status
        std::string message;        ///< Human-readable message
        nlohmann::json data;        ///< Response payload
        std::string timestamp;      ///< ISO 8601 server time
        nlohmann::json pagination;  ///< Pagination metadata
        std::string error_code;     ///< Application-specific error code

        /**
         * @brief Convert response to JSON object
         * @return nlohmann::json Serialized response
         */
        nlohmann::json to_json() const;

        /**
         * @brief Factory method for success response
         * @param msg Success message
         * @param data Response payload
         * @return ApiResponse Success object
         */
        static ApiResponse create_success(const std::string& msg = "", const nlohmann::json& data = nullptr);

        /**
         * @brief Factory method for error response
         * @param msg Error message
         * @param error_code Optional error code
         * @return ApiResponse Error object
         */
        static ApiResponse create_error(const std::string& msg, const std::string& error_code = "");
    };

    // Database connection pool
    /**
     * @brief Database connection pool
     * Manages a pool of SQLite connections for concurrent access.
     */
    class ConnectionPool {
    private:
        std::vector<std::unique_ptr<sqlite3*>> connections_;
        std::vector<std::unique_ptr<std::mutex>> mutexes_;
        std::string db_path_;
        size_t max_connections_;

    public:
        /**
         * @brief Construct a new Connection Pool
         * @param db_path Path to database
         * @param max_connections Maximum shared connections
         */
        ConnectionPool(const std::string& db_path, size_t max_connections = 5);
        ~ConnectionPool();

        /**
         * @brief RAII wrapper for a database connection
         */
        struct ConnectionGuard {
            sqlite3* conn;
            std::mutex* mutex;
            ConnectionGuard(sqlite3* c, std::mutex* m) : conn(c), mutex(m) {}
            ~ConnectionGuard() {
                if (mutex) mutex->unlock();
            }
        };

        /**
         * @brief Acquire a connection from the pool
         * Blocks if no connections are available.
         * @return ConnectionGuard RAII wrapper holding the connection
         */
        ConnectionGuard get_connection();
    };

    /**
     * @brief Enhanced SQLite Helper with caching and performance optimizations
     */
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

    /**
     * @brief Core HTTP Server class
     * Manages Crow app, routing, and server lifecycle.
     */
    class HTTPServer {
    public:
        /**
         * @brief Construct the HTTP Server
         * @param ioc ASIO IO context
         */
        HTTPServer(asio::io_context& ioc);
        ~HTTPServer() = default;

        /**
         * @brief Start the server loop
         * @param port Port to listen on (default 8080)
         */
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

        // Static file serving
        void setup_static_routes();
        std::string get_mime_type(const std::string& path);
        bool serve_static_file(crow::response& res, const std::string& relative_path);
    };
}