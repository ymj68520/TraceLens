// WindowsDBOperations_Registry.cpp
// Registry value insert/query operations

#include "WindowsAnalysisDatabase.h"
#include <sstream>

// Helper macro for binding text
#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

// Helper macro for binding int64
#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

// Helper macro for binding int
#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)

bool WindowsAnalysisDatabase::insertRegistryValue(const RegistryValue& value) {
    const char* sql = "INSERT INTO registry_values (hive_path, hive_type, key_path, value_name, value_type, value_data, last_modified, forensic_importance) VALUES (?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, value.hivePath);
    BIND_TEXT(stmt, 2, value.hiveType);
    BIND_TEXT(stmt, 3, value.keyPath);
    BIND_TEXT(stmt, 4, value.valueName);
    BIND_TEXT(stmt, 5, value.valueType);
    BIND_TEXT(stmt, 6, value.valueData);
    BIND_INT64(stmt, 7, value.lastModified);
    BIND_TEXT(stmt, 8, value.forensicImportance);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

bool WindowsAnalysisDatabase::insertRegistryValues(const std::vector<RegistryValue>& values) {
    if (values.empty()) return true;

    beginTransaction();
    for (const auto& value : values) {
        if (!insertRegistryValue(value)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<RegistryValue> WindowsAnalysisDatabase::queryRegistryValues(const std::string& whereClause) const {
    std::vector<RegistryValue> results;
    std::string sql = "SELECT hive_path, hive_type, key_path, value_name, value_type, value_data, last_modified, forensic_importance FROM registry_values";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        RegistryValue value;
        value.hivePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        value.hiveType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        value.keyPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        value.valueName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        value.valueType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4)) ?: "";
        value.valueData = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5)) ?: "";
        value.lastModified = sqlite3_column_int64(stmt, 6);
        value.forensicImportance = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7)) ?: "";
        results.push_back(value);
    }
    sqlite3_finalize(stmt);
    return results;
}