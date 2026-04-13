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
#include "routes/CaseCRUDRoutes.h"

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
        CaseCRUDRoutes case_routes_;

        // Static file serving
        void setup_static_routes();
        std::string get_mime_type(const std::string& path);
        bool serve_static_file(crow::response& res, const std::string& relative_path);
    };
}