#include "MemoryForensicsRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "../../Swagger/Swagger.h"
#include <sqlite3.h>

namespace forensics {
using json = nlohmann::json;

MemoryForensicsRoutes::MemoryForensicsRoutes(crow::App<>& app) {
    CROW_ROUTE(app, "/api/forensics/memory/summary").methods("GET"_method)([this](const crow::request& req){
        return handle_memory_summary(req); });
    CROW_ROUTE(app, "/api/forensics/memory/processes").methods("GET"_method)([this](const crow::request& req){
        return handle_memory_processes(req); });
    CROW_ROUTE(app, "/api/forensics/memory/network").methods("GET"_method)([this](const crow::request& req){
        return handle_memory_network(req); });
    CROW_ROUTE(app, "/api/forensics/memory/bash-history").methods("GET"_method)([this](const crow::request& req){
        return handle_memory_bash_history(req); });
    CROW_ROUTE(app, "/api/forensics/memory/boot-info").methods("GET"_method)([this](const crow::request& req){
        return handle_memory_boot_info(req); });
}

// Resolve the _memory.db path for the request's task_id via the shared helper
// (same helper AndroidForensicsRoutes uses with "android").
static crow::response taskNotFound() {
    crow::response r;
    RouteHelpers::add_cors_headers(r);
    r.set_header("Content-Type", "application/json");
    r.code = 404;
    r.write(R"({"error":"task not found"})");
    return r;
}

static std::string resolveMemoryDb(const crow::request& req) {
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    return RouteHelpers::get_database_path(task_id, "memory");
}

static crow::response jsonRows(const std::string& dbPath, const std::string& sql) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");
    json out = json::array();
    sqlite3* db = nullptr;
    if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
        res.code = 404; res.write(R"({"error":"memory db not found"})"); return res;
    }
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        res.code = 500; res.write(R"({"error":"query failed"})"); sqlite3_close(db); return res;
    }
    int n = sqlite3_column_count(stmt);
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        json row = json::object();
        for (int i = 0; i < n; ++i) {
            const char* name = sqlite3_column_name(stmt, i);
            const unsigned char* t = sqlite3_column_text(stmt, i);
            row[name] = t ? reinterpret_cast<const char*>(t) : "";
        }
        out.push_back(row);
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);
    res.write(out.dump());
    return res;
}

crow::response MemoryForensicsRoutes::handle_memory_summary(const crow::request& req) {
    crow::response res; RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");
    std::string dbPath;
    try { dbPath = resolveMemoryDb(req); }
    catch (const std::exception&) { return taskNotFound(); }
    sqlite3* db = nullptr;
    if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
        res.code = 404; res.write(R"({"error":"memory db not found"})"); return res;
    }
    auto count = [&](const char* t) -> long {
        sqlite3_stmt* s = nullptr; long c = 0;
        std::string q = std::string("SELECT COUNT(*) FROM ") + t + ";";
        if (sqlite3_prepare_v2(db, q.c_str(), -1, &s, nullptr) == SQLITE_OK) {
            if (sqlite3_step(s) == SQLITE_ROW) c = sqlite3_column_int64(s, 0);
        }
        sqlite3_finalize(s); return c;
    };
    json out;
    out["processes"] = count("processes");
    out["network_connections"] = count("network_connections");
    out["bash_history"] = count("bash_history");
    out["sockets"] = count("sockets");
    sqlite3_close(db);
    res.write(out.dump());
    return res;
}

crow::response MemoryForensicsRoutes::handle_memory_processes(const crow::request& req) {
    std::string dbPath;
    try { dbPath = resolveMemoryDb(req); }
    catch (const std::exception&) { return taskNotFound(); }
    auto params = crow::query_string(req.url_params);
    std::string search = params.get("search") ? params.get("search") : "";
    std::string sql = "SELECT pid, ppid, comm, uid, state, thread_count FROM processes";
    if (!search.empty()) {
        sql += " WHERE comm LIKE '%" + search + "%'";
    }
    sql += " ORDER BY pid LIMIT 1000;";
    return jsonRows(dbPath, sql);
}

crow::response MemoryForensicsRoutes::handle_memory_network(const crow::request& req) {
    std::string dbPath;
    try { dbPath = resolveMemoryDb(req); }
    catch (const std::exception&) { return taskNotFound(); }
    return jsonRows(dbPath,
        "SELECT pid, comm, protocol, local_addr, local_port, foreign_addr, foreign_port, state "
        "FROM network_connections ORDER BY pid LIMIT 1000;");
}

crow::response MemoryForensicsRoutes::handle_memory_bash_history(const crow::request& req) {
    std::string dbPath;
    try { dbPath = resolveMemoryDb(req); }
    catch (const std::exception&) { return taskNotFound(); }
    auto params = crow::query_string(req.url_params);
    std::string kw = params.get("keyword") ? params.get("keyword") : "";
    std::string sql = "SELECT pid, comm, command, history_index FROM bash_history";
    if (!kw.empty()) sql += " WHERE command LIKE '%" + kw + "%'";
    sql += " ORDER BY history_index LIMIT 1000;";
    return jsonRows(dbPath, sql);
}

crow::response MemoryForensicsRoutes::handle_memory_boot_info(const crow::request& req) {
    std::string dbPath;
    try { dbPath = resolveMemoryDb(req); }
    catch (const std::exception&) { return taskNotFound(); }
    return jsonRows(dbPath, "SELECT key, value FROM boot_info;");
}

} // namespace forensics
