#include "../SQLiteHelper.h"
#include <iostream>
#include <fstream>
#include <algorithm>
#include <ctime>
#include <regex>
#include <sstream>
#include <iomanip>

using json = nlohmann::json;

// ============================================================================
// EVENT EXPORT IMPLEMENTATION
// ============================================================================

json SQLiteHelper::export_events_to_json(const std::string& events_db, const std::string& output_file, const std::string& query) {
    json result;
    sqlite3* db = open_database(events_db, result);
    if (!db) return result;

    std::string sql = query.empty() ? "SELECT * FROM events ORDER BY timestamp DESC" : query;
    json events = execute_query(db, sql);

    try {
        std::ofstream file(output_file);
        if (!file.is_open()) {
            result["error"] = "Cannot open output file: " + output_file;
            sqlite3_close(db);
            return result;
        }

        file << events.dump(4);
        file.close();

        result["success"] = true;
        result["output_file"] = output_file;
        result["events_count"] = events.size();
        result["format"] = "json";
    } catch (const std::exception& e) {
        result["error"] = "Export failed: " + std::string(e.what());
    }

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::export_events_to_csv(const std::string& events_db, const std::string& output_file, const std::string& query) {
    json result;
    sqlite3* db = open_database(events_db, result);
    if (!db) return result;

    std::string sql = query.empty() ? "SELECT * FROM events ORDER BY timestamp DESC" : query;

    try {
        sqlite3_stmt* stmt;
        int rc = sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr);
        if (rc != SQLITE_OK) {
            result["error"] = "Query preparation failed";
            sqlite3_close(db);
            return result;
        }

        std::ofstream file(output_file);
        if (!file.is_open()) {
            result["error"] = "Cannot open output file: " + output_file;
            sqlite3_finalize(stmt);
            sqlite3_close(db);
            return result;
        }

        int event_count = 0;

        // Write CSV header
        int column_count = sqlite3_column_count(stmt);
        for (int i = 0; i < column_count; i++) {
            if (i > 0) file << ",";
            file << sqlite3_column_name(stmt, i);
        }
        file << "\n";

        // Write data rows
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            for (int i = 0; i < column_count; i++) {
                if (i > 0) file << ",";

                const char* value = reinterpret_cast<const char*>(sqlite3_column_text(stmt, i));
                if (value) {
                    file << "\"" << value << "\"";
                } else {
                    file << "";
                }
            }
            file << "\n";
            event_count++;
        }

        file.close();
        sqlite3_finalize(stmt);

        result["success"] = true;
        result["output_file"] = output_file;
        result["events_count"] = event_count;
        result["format"] = "csv";
    } catch (const std::exception& e) {
        result["error"] = "Export failed: " + std::string(e.what());
    }

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::export_events_for_visualization(const std::string& events_db, const std::string& output_file) {
    json result;
    sqlite3* db = open_database(events_db, result);
    if (!db) return result;

    std::string sql = R"(
        SELECT
            timestamp,
            event_type,
            file_path,
            file_size,
            description,
            event_source
        FROM events
        ORDER BY timestamp DESC
        LIMIT 10000
    )";

    try {
        sqlite3_stmt* stmt;
        int rc = sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr);
        if (rc != SQLITE_OK) {
            result["error"] = "Query preparation failed";
            sqlite3_close(db);
            return result;
        }

        std::ofstream file(output_file);
        if (!file.is_open()) {
            result["error"] = "Cannot open output file: " + output_file;
            sqlite3_finalize(stmt);
            sqlite3_close(db);
            return result;
        }

        file << "[\n";

        int event_count = 0;
        bool first = true;
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            if (!first) {
                file << ",\n";
            }
            first = false;

            file << "  {\n";

            for (int i = 0; i < sqlite3_column_count(stmt); i++) {
                const char* name = sqlite3_column_name(stmt, i);
                const char* value = reinterpret_cast<const char*>(sqlite3_column_text(stmt, i));

                file << "    \"" << name << "\": ";
                if (value) {
                    if (i == 0) { // timestamp
                        file << sqlite3_column_int64(stmt, i);
                    } else if (i == 3) { // file_size (number)
                        file << sqlite3_column_int64(stmt, i);
                    } else {
                        file << "\"" << value << "\"";
                    }
                } else {
                    file << "null";
                }

                if (i < sqlite3_column_count(stmt) - 1) {
                    file << ",";
                }
                file << "\n";
            }

            file << "  }";
            event_count++;
        }

        file << "\n]\n";
        file.close();
        sqlite3_finalize(stmt);

        result["success"] = true;
        result["output_file"] = output_file;
        result["events_count"] = event_count;
        result["format"] = "visualization_json";
    } catch (const std::exception& e) {
        result["error"] = "Export failed: " + std::string(e.what());
    }

    sqlite3_close(db);
    return result;
}
