#pragma once
#include <crow.h>
#include "../FieldApp.h"
#include <nlohmann/json.hpp>

namespace forensics {

class MemoryForensicsRoutes {
public:
    explicit MemoryForensicsRoutes(HttpApp& app);
private:
    crow::response handle_memory_summary(const crow::request& req);
    crow::response handle_memory_processes(const crow::request& req);
    crow::response handle_memory_network(const crow::request& req);
    crow::response handle_memory_bash_history(const crow::request& req);
    crow::response handle_memory_boot_info(const crow::request& req);
};

} // namespace forensics
