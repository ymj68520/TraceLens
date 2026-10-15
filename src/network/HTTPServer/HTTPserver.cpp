/**
 * @file HTTPserver.cpp
 * @brief Implementation of the HTTP Server and helper classes
 */

#include "HTTPserver.h"
#include "tracelens/build_identity.h"
#include "FullTextSearch/FullTextSearch.h"
#include "FullTextSearch/TextExtractor.h"
#include "ConfigManager/ConfigManager.h"
#include <httplib.h>
#include <iostream>
#include <fstream>
#include <sstream>
#include <filesystem>
#include <ctime>
#include <cstdlib>
#include <stdexcept>

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
        // NOTE: Do not use `data ? data : ...` here — nlohmann's operator bool()
        // converts the value to a bool and throws type_error.302 for any non-bool
        // JSON (e.g. an object or array). Use is_null() to detect "no payload".
        response.data = data.is_null() ? nlohmann::json::object() : data;
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
          search_routes_(app_),
          case_routes_(app_),
          filter_routes_(app_)
    {
        // Route handlers are initialized in their respective classes
    }

    void HTTPServer::run(int port) {
        std::cout << "Starting HTTP server on port " << port << std::endl;

        const char* configured = std::getenv("HTTP_SERVER_HOST");
        const std::string host = configured && *configured ? configured : "0.0.0.0";
        if (std::getenv("TRACELENS_REQUIRE_FIELD_AUTH") &&
            std::string(std::getenv("TRACELENS_REQUIRE_FIELD_AUTH")) == "1" &&
            (!std::getenv("TRACELENS_FIELD_AUTH") ||
             std::string(std::getenv("TRACELENS_FIELD_AUTH")) != "enabled")) {
            throw std::runtime_error("field authentication is required but not enabled");
        }
        if (std::getenv("TRACELENS_FIELD_AUTH") &&
            std::string(std::getenv("TRACELENS_FIELD_AUTH")) == "enabled") {
#ifndef TRACELENS_RELEASE_ID
#define TRACELENS_RELEASE_ID "UNFROZEN_WORKTREE"
#endif
            if (std::getenv("TRACELENS_REQUIRE_RELEASE_LAYOUT") &&
                std::string(std::getenv("TRACELENS_REQUIRE_RELEASE_LAYOUT")) == "1") {
                const char* expected = std::getenv("TRACELENS_RELEASE_ID");
                if (!expected || std::string(expected) != TRACELENS_RELEASE_ID ||
                    std::string(expected) == "UNFROZEN_WORKTREE") {
                    throw std::runtime_error("field release identity is not baked into this executable");
                }
            }
            if (!field_runtime_ready() || (host != "127.0.0.1" && host != "::1")) {
                throw std::runtime_error("field authentication or loopback binding is not configured");
            }
        }

        // Setup static file serving for React frontend
        setup_static_routes();

        app_.bindaddr(host).port(port).multithreaded().run();
    }

    void HTTPServer::setup_static_routes() {
        // Add CORS headers to all responses
        app_.loglevel(crow::LogLevel::Warning);

        CROW_ROUTE(app_, "/health/live").methods("GET"_method)([] {
            crow::response response;
            response.set_header("Content-Type", "application/json");
            response.set_header("Cache-Control", "no-store");
            response.write("{\"status\":\"alive\"}");
            return response;
        });

        CROW_ROUTE(app_, "/api/security/status").methods("GET"_method)([] {
            crow::response response;
            response.set_header("Content-Type", "application/json");
            response.set_header("Cache-Control", "no-store");
            const char* mode = std::getenv("FIELD_OUTBOUND_POLICY");
            const bool field = std::getenv("TRACELENS_FIELD_AUTH") &&
                std::string(std::getenv("TRACELENS_FIELD_AUTH")) == "enabled";
            const bool required = std::getenv("TRACELENS_REQUIRE_FIELD_AUTH") &&
                std::string(std::getenv("TRACELENS_REQUIRE_FIELD_AUTH")) == "1";
            response.write(nlohmann::json{{"field_security_version", "6a-v1"},
                {"release_id", TRACELENS_RELEASE_ID}, {"release_layout_version", "6c-v1"},
                {"source_commit", TRACELENS_SOURCE_COMMIT}, {"source_tree_sha256", TRACELENS_SOURCE_SHA256},
                {"field_auth", field}, {"required_auth", required},
                {"outbound_policy", mode ? mode : "disabled"}}.dump());
            return response;
        });

        // Global CORS middleware - handles OPTIONS and adds CORS headers to all responses
        auto cors_middleware = [](crow::request& req, crow::response& res){
            if (!std::getenv("TRACELENS_FIELD_AUTH") ||
                std::string(std::getenv("TRACELENS_FIELD_AUTH")) != "enabled")
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

        // Browser-facing "/python" gateway. The frontend release build sends
        // every Python-service call through the same-origin "/python" prefix
        // (runtime.js PYTHON_API_BASE_URL); forward those requests so pages
        // backed by the Python service (workbench, reports, knowledge graph,
        // dependency health) work without a direct cross-origin hop.
        CROW_ROUTE(app_, "/python/<path>")
            .methods("GET"_method, "POST"_method, "PUT"_method, "DELETE"_method, "PATCH"_method)
            ([this](const crow::request& req, const std::string& path) {
                return proxy_python_request(req, path);
            });

        // SPA fallback route - all paths fallback to index.html for client-side routing
        CROW_ROUTE(app_, "/<path>")
        .methods("GET"_method)
        ([this](const crow::request& req, const std::string& path){
            crow::response res;
            if (path == "api" || path.rfind("api/", 0) == 0 || path.rfind("python/", 0) == 0 ||
                path.rfind("cs-disabled/", 0) == 0) {
                res.code = 404;
                res.set_header("Content-Type", "application/json");
                res.write("{\"detail\":\"not found\"}");
                return res;
            }

            // Add CORS headers
            if (!std::getenv("TRACELENS_FIELD_AUTH") ||
                std::string(std::getenv("TRACELENS_FIELD_AUTH")) != "enabled")
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
            if (!std::getenv("TRACELENS_FIELD_AUTH") ||
                std::string(std::getenv("TRACELENS_FIELD_AUTH")) != "enabled")
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

    crow::response HTTPServer::proxy_python_request(const crow::request& req, const std::string& path) {
        const std::string query = req.raw_url.find('?') == std::string::npos
            ? std::string() : req.raw_url.substr(req.raw_url.find('?'));
        const std::string target = "/" + path + query;
        const std::string content_type = req.get_header_value("Content-Type");

        httplib::Client cli(ConfigManager::instance().getPythonServiceUrl());
        if (std::getenv("TRACELENS_FIELD_AUTH") &&
            std::string(std::getenv("TRACELENS_FIELD_AUTH")) == "enabled") {
            const char* token = std::getenv("FIELD_CPP_TO_PYTHON_TOKEN");
            cli.set_default_headers({{"X-TraceLens-Service-Token", token ? token : ""}});
        }
        cli.set_connection_timeout(10);
        cli.set_read_timeout(600);
        cli.set_write_timeout(600);

        httplib::Headers headers;
        const std::string authorization = req.get_header_value("Authorization");
        if (!authorization.empty()) headers.emplace("Authorization", authorization);
        const std::string accept = req.get_header_value("Accept");
        if (!accept.empty()) headers.emplace("Accept", accept);

        httplib::Result result;
        if (req.method == "POST"_method) {
            result = cli.Post(target, headers, req.body, content_type.c_str());
        } else if (req.method == "PUT"_method) {
            result = cli.Put(target, headers, req.body, content_type.c_str());
        } else if (req.method == "PATCH"_method) {
            result = cli.Patch(target, headers, req.body, content_type.c_str());
        } else if (req.method == "DELETE"_method) {
            result = cli.Delete(target, headers, req.body, content_type.c_str());
        } else if (req.method == "HEAD"_method) {
            result = cli.Head(target, headers);
        } else {
            result = cli.Get(target, headers);
        }

        crow::response res;
        if (!result) {
            res.code = 502;
            res.set_header("Content-Type", "application/json");
            res.write(nlohmann::json{{"detail", "python service unreachable"}}.dump());
            return res;
        }
        res.code = result->status;
        for (const auto& [name, value] : result->headers) {
            if (name == "Content-Type" || name == "Content-Disposition") {
                res.set_header(name, value);
            }
        }
        res.write(result->body);
        return res;
    }

    bool HTTPServer::serve_static_file(crow::response& res, const std::string& file_path) {        std::error_code ec;
        const fs::path root = fs::weakly_canonical("web/dist", ec);
        if (ec) return false;
        const fs::path target = fs::weakly_canonical(file_path, ec);
        if (ec) return false;
        const fs::path relative = target.lexically_relative(root);
        if (relative.empty() || relative.is_absolute() ||
            relative.begin() == relative.end() || *relative.begin() == ".." ||
            !fs::is_regular_file(target)) {
            return false;
        }

        // Read file content
        std::ifstream file(target, std::ios::binary);
        if (!file.is_open()) {
            return false;
        }

        std::ostringstream content;
        content << file.rdbuf();

        // Set content type
        std::string mime_type = get_mime_type(file_path);
        res.set_header("Content-Type", mime_type);
        if (std::getenv("TRACELENS_FIELD_AUTH") &&
            std::string(std::getenv("TRACELENS_FIELD_AUTH")) == "enabled") {
            res.set_header("X-Content-Type-Options", "nosniff");
            res.set_header("Referrer-Policy", "no-referrer");
            res.set_header("X-Frame-Options", "DENY");
            res.set_header("Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' blob: data:; font-src 'self' data:; connect-src 'self'; "
                "object-src 'none'; frame-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'");
        }

        // Add cache headers for static assets
        std::string ext = fs::path(file_path).extension().string();
        if (ext == ".js" || ext == ".css" || ext == ".png" ||
            ext == ".jpg" || ext == ".jpeg" || ext == ".gif" ||
            ext == ".svg" || ext == ".ico" || ext == ".woff" ||
            ext == ".woff2" || ext == ".ttf") {
            res.set_header("Cache-Control", "public, max-age=31536000"); // 1 year
        } else if (ext == ".html" || ext == ".htm") {
            // SPA entry point: hashed assets are content-addressed and safe to
            // cache for a year, but index.html itself must always be
            // revalidated so browsers never keep serving a stale frontend
            // bundle after a redeploy.
            res.set_header("Cache-Control", "no-cache");
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
