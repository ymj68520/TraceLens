#include "SystemDocsRoutes.h"
#include "RouteHelpers.h"
#include "../../Swagger/Swagger.h"

namespace forensics {

using json = nlohmann::json;

SystemDocsRoutes::SystemDocsRoutes(crow::App<>& app) {
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
}

crow::response SystemDocsRoutes::handle_docs_endpoints(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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

crow::response SystemDocsRoutes::handle_docs_database_schema(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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

crow::response SystemDocsRoutes::handle_docs_openapi(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    try {
        json openapi = Swagger::instance().GetSwaggerJSON();
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

crow::response SystemDocsRoutes::handle_docs_ui(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

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

} // namespace forensics
