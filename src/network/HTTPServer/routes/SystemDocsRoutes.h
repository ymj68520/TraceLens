#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

class SystemDocsRoutes {
public:
    explicit SystemDocsRoutes(crow::App<>& app);
    
private:
    crow::response handle_docs_endpoints(const crow::request& req);
    crow::response handle_docs_database_schema(const crow::request& req);
    crow::response handle_docs_openapi(const crow::request& req);
    crow::response handle_docs_ui(const crow::request& req);
};

} // namespace forensics
