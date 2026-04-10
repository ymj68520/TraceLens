// LinuxDatabaseHelpers.h
// Shared helper functions and macros for Linux database operations

#pragma once
#ifndef LINUX_DATABASE_HELPERS_H
#define LINUX_DATABASE_HELPERS_H

#include <nlohmann/json.hpp>
#include <sqlite3.h>
#include <iostream>
#include <vector>
#include <string>

// Helper macros for binding
#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)

#define BIND_DOUBLE(stmt, index, val) \
    sqlite3_bind_double(stmt, index, val)

// RAII wrapper for sqlite3_stmt
class StmtGuard {
public:
    explicit StmtGuard(sqlite3_stmt* stmt) : stmt_(stmt) {}
    ~StmtGuard() { if (stmt_) sqlite3_finalize(stmt_); }
    operator sqlite3_stmt*() const { return stmt_; }
    sqlite3_stmt* get() const { return stmt_; }
private:
    sqlite3_stmt* stmt_;
};

// Helper function to convert vector<string> to JSON string
template<typename T>
std::string vectorToJson(const std::vector<T>& vec) {
    try {
        nlohmann::json j = vec;
        return j.dump();
    } catch (const std::exception& e) {
        std::cerr << "JSON serialization error: " << e.what() << std::endl;
        return "[]";
    }
}

// Helper function to parse JSON string to vector<string>
template<typename T>
std::vector<T> jsonToVector(const std::string& jsonStr) {
    try {
        if (jsonStr.empty()) return {};
        nlohmann::json j = nlohmann::json::parse(jsonStr);
        return j.get<std::vector<T>>();
    } catch (const std::exception& e) {
        std::cerr << "JSON parsing error: " << e.what() << std::endl;
        return {};
    }
}

// Helper function to safely get text from SQLite column
inline const char* safeColumnText(sqlite3_stmt* stmt, int col) {
    const unsigned char* text = sqlite3_column_text(stmt, col);
    return text ? reinterpret_cast<const char*>(text) : "";
}

#endif // LINUX_DATABASE_HELPERS_H
