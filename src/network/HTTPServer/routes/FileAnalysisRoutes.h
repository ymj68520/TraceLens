#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

class FileAnalysisRoutes {
public:
    explicit FileAnalysisRoutes(crow::App<>& app);
    
private:
    crow::response handle_files_largest(const crow::request& req);
    crow::response handle_files_recent(const crow::request& req);
    crow::response handle_files_suspicious(const crow::request& req);
    crow::response handle_files_duplicates(const crow::request& req);
    crow::response handle_files_extensions_analysis(const crow::request& req);
};

} // namespace forensics
