/**
 * @file HTTPserver.cpp
 * @brief Implementation of the HTTP Server and helper classes
 */

#include "HTTPserver.h"
#include "FullTextSearch/FullTextSearch.h"
#include "FullTextSearch/TextExtractor.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <filesystem>
#include <ctime>
#include <cstdlib>

namespace fs = std::filesystem;

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

    HTTPServer::HTTPServer(asio::io_context& ioc)
        : app_(),
          task_manager_(TaskManager::instance()),
          ioc_(ioc),
          task_routes_(app_),
          forensics_routes_(app_),
          system_routes_(app_),
          search_routes_(app_)
    {
        // Route handlers are initialized in their respective classes
    }

    void HTTPServer::run(int port) {
        std::cout << "Starting HTTP server on port " << port << std::endl;

        // Setup static file serving for React frontend
        setup_static_routes();

        app_.port(port).multithreaded().run();
    }

    void HTTPServer::setup_static_routes() {
        // Add CORS headers to all responses
        app_.loglevel(crow::LogLevel::Warning);

        // Global CORS middleware - handles OPTIONS and adds CORS headers to all responses
        auto cors_middleware = [](crow::request& req, crow::response& res){
            res.set_header("Access-Control-Allow-Origin", "*");
            res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
            res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");

            // Handle OPTIONS preflight request
            if (req.method == "OPTIONS"_method) {
                res.code = 204;
                res.end();
                return true;
            }
            return false;
        };

        // Register global middleware - but we need to use it differently
        // For now, let's just add catch-all routes after the specific routes

        // SPA fallback route - all paths fallback to index.html for client-side routing
        CROW_ROUTE(app_, "/<path>")
        .methods("GET"_method)
        ([this](const crow::request& req, const std::string& path){
            crow::response res;

            // Add CORS headers
            res.set_header("Access-Control-Allow-Origin", "*");
            res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
            res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");

            // Try to serve file from web/dist directory
            std::string web_dir = "web/dist"; // Relative to binary location
            std::string file_path = web_dir + "/" + path;

            if (serve_static_file(res, file_path)) {
                return res;
            }

            // Fallback to index.html for SPA routing
            std::string index_path = web_dir + "/index.html";
            if (serve_static_file(res, index_path)) {
                return res;
            }

            // File not found
            res.code = 404;
            res.write("Not Found");
            return res;
        });

        // Root route
        CROW_ROUTE(app_, "/")
        .methods("GET"_method)
        ([this](const crow::request& req){
            crow::response res;
            std::string index_path = "web/dist/index.html";

            // Add CORS headers
            res.set_header("Access-Control-Allow-Origin", "*");
            res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
            res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");

            if (serve_static_file(res, index_path)) {
                res.set_header("Content-Type", "text/html");
            } else {
                res.code = 404;
                res.write("Frontend not built. Run: cd web && npm install && npm run build && cp -r dist ../build/web/");
            }

            return res;
        });
    }

    bool HTTPServer::serve_static_file(crow::response& res, const std::string& file_path) {
        if (!fs::exists(file_path) || !fs::is_regular_file(file_path)) {
            return false;
        }

        // Read file content
        std::ifstream file(file_path, std::ios::binary);
        if (!file.is_open()) {
            return false;
        }

        std::ostringstream content;
        content << file.rdbuf();

        // Set content type
        std::string mime_type = get_mime_type(file_path);
        res.set_header("Content-Type", mime_type);

        // Add cache headers for static assets
        std::string ext = fs::path(file_path).extension().string();
        if (ext == ".js" || ext == ".css" || ext == ".png" ||
            ext == ".jpg" || ext == ".jpeg" || ext == ".gif" ||
            ext == ".svg" || ext == ".ico" || ext == ".woff" ||
            ext == ".woff2" || ext == ".ttf") {
            res.set_header("Cache-Control", "public, max-age=31536000"); // 1 year
        }

        res.code = 200;
        res.write(content.str());
        return true;
    }

    std::string HTTPServer::get_mime_type(const std::string& path) {
        std::string ext = fs::path(path).extension().string();

        if (ext == ".html") return "text/html";
        if (ext == ".css") return "text/css";
        if (ext == ".js") return "application/javascript";
        if (ext == ".json") return "application/json";
        if (ext == ".png") return "image/png";
        if (ext == ".jpg" || ext == ".jpeg") return "image/jpeg";
        if (ext == ".gif") return "image/gif";
        if (ext == ".svg") return "image/svg+xml";
        if (ext == ".ico") return "image/x-icon";
        if (ext == ".woff") return "font/woff";
        if (ext == ".woff2") return "font/woff2";
        if (ext == ".ttf") return "font/ttf";
        if (ext == ".eot") return "application/vnd.ms-fontobject";

        return "application/octet-stream";
    }

} // namespace forensics
