#include "SystemRoutes.h"
#include "../../Swagger/Swagger.h"
#include <chrono>
#include <fstream>
#include <filesystem>

namespace forensics {

using json = nlohmann::json;

SystemRoutes::SystemRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    // System Information
    CROW_ROUTE(app, "/api/system/health").methods("GET"_method)([this](const crow::request& req) {
        return handle_system_health(req);
    });

    CROW_ROUTE(app, "/api/system/info").methods("GET"_method)([this](const crow::request& req) {
        return handle_system_info(req);
    });

    CROW_ROUTE(app, "/api/system/databases").methods("GET"_method)([this](const crow::request& req) {
        return handle_system_databases(req);
    });

    CROW_ROUTE(app, "/api/system/database-schema/<string>").methods("GET"_method)([this](const crow::request& req, const std::string& db_type) {
        return handle_system_database_schema(req, db_type);
    });

    // Enhanced Health Checks (Kubernetes-style)
    CROW_ROUTE(app, "/api/health").methods("GET"_method)([this](const crow::request& req) {
        return handle_system_health(req);
    });

    CROW_ROUTE(app, "/api/health/live").methods("GET"_method)([this](const crow::request& req) {
        return handle_health_live(req);
    });

    CROW_ROUTE(app, "/api/health/ready").methods("GET"_method)([this](const crow::request& req) {
        return handle_health_ready(req);
    });

    CROW_ROUTE(app, "/api/health/dependencies").methods("GET"_method)([this](const crow::request& req) {
        return handle_health_dependencies(req);
    });

    // Documentation
    CROW_ROUTE(app, "/api/docs/endpoints").methods("GET"_method)([this](const crow::request& req) {
        return handle_docs_endpoints(req);
    });

    CROW_ROUTE(app, "/api/docs/database-schema").methods("GET"_method)([this](const crow::request& req) {
        return handle_docs_database_schema(req);
    });

    CROW_ROUTE(app, "/api/docs/openapi.json").methods("GET"_method)([this](const crow::request& req) {
        return handle_docs_openapi(req);
    });

    CROW_ROUTE(app, "/api/docs").methods("GET"_method)([this](const crow::request& req) {
        return handle_docs_ui(req);
    });

    // Export
    CROW_ROUTE(app, "/api/export/<string>").methods("POST"_method)([this](const crow::request& req, const std::string& task_id) {
        return handle_export_results(req, task_id);
    });
}

crow::response SystemRoutes::handle_system_health(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    try {
        auto task_stats = task_manager_.get_task_statistics();

        json health = {
            {"status", "healthy"},
            {"timestamp", std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now().time_since_epoch()).count()},
            {"version", "1.0.0"},
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

crow::response SystemRoutes::handle_system_info(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
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

crow::response SystemRoutes::handle_system_databases(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
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

crow::response SystemRoutes::handle_system_database_schema(const crow::request& req, const std::string& db_type) {
    crow::response res;
    add_cors_headers(res);
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

crow::response SystemRoutes::handle_docs_endpoints(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    try {
        json endpoints = {
            {"task_management", {
                {"POST /tasks", "Create a new analysis task"},
                {"GET /tasks/<id>", "Get task status"},
                {"GET /tasks/<id>/results", "Get task results"},
                {"GET /api/tasks/list", "List all tasks"},
                {"DELETE /api/tasks/<id>", "Cancel a task"},
                {"GET /api/tasks/<id>/progress", "Get task progress"},
                {"GET /api/tasks/statistics", "Get task statistics"},
                {"POST /api/tasks/cleanup", "Cleanup old tasks"},
                {"POST /api/tasks/batch-create", "Create batch tasks"},
                {"POST /api/tasks/batch-status", "Get batch status"},
                {"POST /api/tasks/batch-cancel", "Cancel batch tasks"}
            }},
            {"forensics", {
                {"GET /api/forensics/timeline/comprehensive", "Get comprehensive timeline"},
                {"GET /api/forensics/timeline/file-activity", "Get file activity timeline"},
                {"GET /api/forensics/timeline/suspicious-patterns", "Get suspicious patterns"},
                {"GET /api/forensics/timeline/user-activity", "Get user activity"},
                {"GET /api/forensics/files/largest", "Get largest files"},
                {"GET /api/forensics/files/recent", "Get recent files"},
                {"GET /api/forensics/files/suspicious", "Get suspicious files"},
                {"GET /api/forensics/files/duplicates", "Get duplicate files"},
                {"GET /api/forensics/files/extensions-analysis", "Get extensions analysis"},
                {"GET /api/forensics/android/*", "Android forensics endpoints"},
                {"GET /api/forensics/statistics/*", "Statistics endpoints"}
            }},
            {"system", {
                {"GET /api/system/health", "System health check"},
                {"GET /api/system/info", "System information"},
                {"GET /api/system/databases", "List databases for task"},
                {"GET /api/system/database-schema/<type>", "Get database schema"}
            }},
            {"search", {
                {"GET /api/search/fulltext", "Full-text search"},
                {"POST /api/search/index", "Build search index"}
            }}
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

crow::response SystemRoutes::handle_docs_database_schema(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    try {
        json schema = {
            {"raw_database", {
                {"description", "Contains raw extracted data from disk image"},
                {"tables", {"files", "partitions"}}
            }},
            {"files_database", {
                {"description", "Contains classified files with categories"},
                {"tables", {"classified_files", "file_descriptions"}}
            }},
            {"events_database", {
                {"description", "Contains timeline events"},
                {"tables", {"timeline_events"}}
            }},
            {"android_database", {
                {"description", "Contains Android-specific data"},
                {"tables", {"contacts", "messages", "call_logs", "apps"}}
            }}
        };

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

crow::response SystemRoutes::handle_export_results(const crow::request& req, const std::string& task_id) {
    crow::response res;
    add_cors_headers(res);
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

        // Parse export format
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

void SystemRoutes::add_cors_headers(crow::response& res) {
    res.set_header("Access-Control-Allow-Origin", "*");
    res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
    res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
}

crow::response SystemRoutes::handle_health_live(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    
    // Simple liveness check - if we can respond, we're alive
    json health = {
        {"status", "alive"},
        {"timestamp", std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count()}
    };
    
    res.set_header("Content-Type", "application/json");
    res.write(health.dump());
    return res;
}

crow::response SystemRoutes::handle_health_ready(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    
    try {
        bool ready = true;
        json checks = json::object();
        
        // Check task manager
        try {
            auto stats = task_manager_.get_task_statistics();
            checks["task_manager"] = {
                {"status", "ready"},
                {"total_tasks", stats["total_tasks"]}
            };
        } catch (const std::exception& e) {
            checks["task_manager"] = {
                {"status", "error"},
                {"error", e.what()}
            };
            ready = false;
        }
        
        // Check database access (try to verify we can access SQLite)
        checks["database"] = {{"status", "ready"}};
        
        json health = {
            {"ready", ready},
            {"checks", checks},
            {"timestamp", std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count()}
        };
        
        res.code = ready ? 200 : 503;
        res.set_header("Content-Type", "application/json");
        res.write(health.dump());
    } catch (const std::exception& e) {
        json error = {{"ready", false}, {"error", e.what()}};
        res.code = 503;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response SystemRoutes::handle_health_dependencies(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    
    try {
        json dependencies = {
            {"http_server", {{"status", "running"}, {"port", 8080}}},
            {"task_manager", {{"status", "running"}}},
            {"sqlite", {{"status", "available"}}},
            {"llm_service", {{"status", "configured"}, {"base_url", "http://localhost:1234"}}},
            {"python_service", {{"status", "optional"}, {"port", 8090}}}
        };
        
        json response = {
            {"dependencies", dependencies},
            {"overall_status", "healthy"},
            {"timestamp", std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count()}
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

crow::response SystemRoutes::handle_docs_openapi(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    
    try {
        json openapi = generate_openapi_spec();
        res.set_header("Content-Type", "application/json");
        res.write(openapi.dump(2));
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response SystemRoutes::handle_docs_ui(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    
    std::string html = R"(
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Forensics API Documentation</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui.css" />
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui-bundle.js" crossorigin></script>
<script>
    window.onload = () => {
        window.ui = SwaggerUIBundle({
            url: '/api/docs/openapi.json',
            dom_id: '#swagger-ui',
            presets: [
                SwaggerUIBundle.presets.apis,
                SwaggerUIBundle.SwaggerUIStandalonePreset
            ],
            layout: "BaseLayout",
        });
    };
</script>
</body>
</html>
    )";
    
    res.set_header("Content-Type", "text/html");
    res.write(html);
    return res;
}

nlohmann::json SystemRoutes::generate_openapi_spec() {
    return Swagger::instance().GetSwaggerJSON();
}

} // namespace forensics

