#include "SystemInfoRoutes.h"
#include "RouteHelpers.h"
#include <filesystem>

namespace forensics {

using json = nlohmann::json;

SystemInfoRoutes::SystemInfoRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    CROW_ROUTE(app, "/api/system/info").methods("GET"_method)([this](const crow::request& req) {
        return handle_system_info(req);
    });

    CROW_ROUTE(app, "/api/system/databases").methods("GET"_method)([this](const crow::request& req) {
        return handle_system_databases(req);
    });

    CROW_ROUTE(app, "/api/system/database-schema/<string>").methods("GET"_method)([this](const crow::request& req, const std::string& db_type) {
        return handle_system_database_schema(req, db_type);
    });

    CROW_ROUTE(app, "/api/export/<string>").methods("POST"_method)([this](const crow::request& req, const std::string& task_id) {
        return handle_export_results(req, task_id);
    });

    CROW_ROUTE(app, "/api/system/logs").methods("GET"_method)([this](const crow::request& req) {
        return handle_system_logs(req);
    });
}

crow::response SystemInfoRoutes::handle_system_info(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        json info = {
            {"name", "Forensics Analyzer"},
            {"version", "1.0.0"},
            {"description", "Digital forensics analysis platform"},
            {"features", {
                "Image analysis (E01, raw, dd)",
                "Timeline generation",
                "File classification",
                "Android forensics",
                "Full-text search",
                "LLM-powered file descriptions"
            }},
            {"api_version", "v1"},
            {"supported_formats", {
                "E01", "raw", "dd", "img", "dmg"
            }}
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

crow::response SystemInfoRoutes::handle_system_databases(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        std::string task_id = "";
        if (req.url_params.get("task_id") != nullptr) {
            task_id = req.url_params.get("task_id");
        }

        json databases = json::array();

        if (!task_id.empty()) {
            AnalysisTask task = task_manager_.get_task(task_id);
            if (!task.id.empty()) {
                if (!task.output_raw_db.empty() && std::filesystem::exists(task.output_raw_db)) {
                    databases.push_back({
                        {"type", "raw"},
                        {"path", task.output_raw_db},
                        {"size", std::filesystem::file_size(task.output_raw_db)}
                    });
                }
                if (!task.output_events_db.empty() && std::filesystem::exists(task.output_events_db)) {
                    databases.push_back({
                        {"type", "events"},
                        {"path", task.output_events_db},
                        {"size", std::filesystem::file_size(task.output_events_db)}
                    });
                }
                if (!task.output_files_db.empty() && std::filesystem::exists(task.output_files_db)) {
                    databases.push_back({
                        {"type", "files"},
                        {"path", task.output_files_db},
                        {"size", std::filesystem::file_size(task.output_files_db)}
                    });
                }
            }
        }

        json response = {
            {"task_id", task_id},
            {"databases", databases}
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

crow::response SystemInfoRoutes::handle_system_database_schema(const crow::request& req, const std::string& db_type) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        json schema;

        if (db_type == "raw") {
            schema = {
                {"type", "raw"},
                {"tables", {
                    {"files", {
                        {"columns", {"id", "path", "name", "size", "mtime", "atime", "ctime", "inode", "deleted", "content_hash"}}
                    }},
                    {"partitions", {
                        {"columns", {"id", "number", "start", "length", "description", "fs_type"}}
                    }}
                }}
            };
        } else if (db_type == "files") {
            schema = {
                {"type", "files"},
                {"tables", {
                    {"classified_files", {
                        {"columns", {"id", "path", "category", "mime_type", "extension", "size", "is_encrypted", "description"}}
                    }}
                }}
            };
        } else if (db_type == "events") {
            schema = {
                {"type", "events"},
                {"tables", {
                    {"timeline_events", {
                        {"columns", {"id", "timestamp", "event_type", "source", "description", "file_path"}}
                    }}
                }}
            };
        } else {
            json error = {{"error", "Unknown database type: " + db_type}};
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

crow::response SystemInfoRoutes::handle_export_results(const crow::request& req, const std::string& task_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        AnalysisTask task = task_manager_.get_task(task_id);

        if (task.id.empty()) {
            json error = {{"error", "Task not found"}, {"task_id", task_id}};
            res.code = 404;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        if (task.status != TaskStatus::COMPLETED) {
            json error = {{"error", "Task not completed"}, {"status", static_cast<int>(task.status)}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        std::string format = "json";
        try {
            auto body = json::parse(req.body);
            if (body.contains("format")) {
                format = body["format"];
            }
        } catch (...) {}

        json response = {
            {"task_id", task_id},
            {"format", format},
            {"files", {
                {"raw_db", task.output_raw_db},
                {"events_db", task.output_events_db},
                {"files_db", task.output_files_db}
            }},
            {"message", "Export available at specified database paths"}
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

crow::response SystemInfoRoutes::handle_system_logs(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    try {
        int lines = 100;
        if (const char* lines_str = req.url_params.get("lines"); lines_str != nullptr) {
            try {
                lines = std::min(std::stoi(lines_str), 1000);
            } catch (...) {}
        }

        json logs = json::array();

        std::vector<std::string> log_paths = {
            "logs/forensic_analyzer.log",
            "forensic_analyzer.log",
            "/tmp/forensic_analyzer.log"
        };

        std::string log_file;
        for (const auto& path : log_paths) {
            if (std::filesystem::exists(path)) {
                log_file = path;
                break;
            }
        }

        if (!log_file.empty()) {
            std::ifstream file(log_file);
            if (file.is_open()) {
                std::string line;
                std::vector<std::string> all_lines;

                while (std::getline(file, line)) {
                    all_lines.push_back(line);
                }

                int start = std::max(0, (int)all_lines.size() - lines);
                for (int i = start; i < (int)all_lines.size(); i++) {
                    std::string timestamp = "";
                    std::string level = "INFO";
                    std::string message = all_lines[i];

                    size_t close_bracket = all_lines[i].find(']');
                    if (all_lines[i][0] == '[' && close_bracket != std::string::npos) {
                        timestamp = all_lines[i].substr(1, close_bracket - 1);
                        size_t level_start = close_bracket + 2;
                        size_t level_end = all_lines[i].find(' ', level_start);
                        if (level_end != std::string::npos) {
                            level = all_lines[i].substr(level_start, level_end - level_start);
                            message = all_lines[i].substr(level_end + 1);
                        }
                    }

                    logs.push_back({
                        {"timestamp", timestamp.empty() ? "N/A" : timestamp},
                        {"level", level},
                        {"message", message}
                    });
                }
            }
        }

        json response = {
            {"service", "cpp-backend"},
            {"logs", logs},
            {"total_count", logs.size()}
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

} // namespace forensics
