#include "../SQLiteHelper.h"
#include <iostream>
#include <algorithm>
#include <cctype>
#include <ctime>
#include <regex>
#include <sstream>
#include <iomanip>
#include <vector>

using json = nlohmann::json;

// ============================================================================
// HELPER METHODS IMPLEMENTATION
// ============================================================================

sqlite3* SQLiteHelper::open_database(const std::string& db_path, json& error_result) {
    sqlite3* db;
    if (sqlite3_open(db_path.c_str(), &db) != SQLITE_OK) {
        error_result["error"] = "Cannot open database: " + db_path;
        if (db) sqlite3_close(db);
        return nullptr;
    }
    return db;
}

json SQLiteHelper::execute_query(sqlite3* db, const std::string& sql) {
    json result = json::array();
    sqlite3_stmt* stmt = nullptr;

    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        int column_count = sqlite3_column_count(stmt);

        while (sqlite3_step(stmt) == SQLITE_ROW) {
            json row = json::object();

            for (int i = 0; i < column_count; i++) {
                const char* column_name = sqlite3_column_name(stmt, i);

                switch (sqlite3_column_type(stmt, i)) {
                    case SQLITE_INTEGER:
                        row[column_name] = sqlite3_column_int64(stmt, i);
                        break;
                    case SQLITE_FLOAT:
                        row[column_name] = sqlite3_column_double(stmt, i);
                        break;
                    case SQLITE_TEXT:
                        row[column_name] = std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, i)));
                        break;
                    case SQLITE_BLOB:
                        row[column_name] = "<BLOB_DATA>";
                        break;
                    case SQLITE_NULL:
                        row[column_name] = nullptr;
                        break;
                }
            }

            result.push_back(row);
        }
    } else {
        std::cerr << "SQL error: " << sqlite3_errmsg(db) << std::endl;
    }

    sqlite3_finalize(stmt);
    return result;
}

json SQLiteHelper::execute_query(sqlite3* db, const std::string& sql,
                                 const std::vector<std::string>& params) {
    json result = json::array();
    sqlite3_stmt* stmt = nullptr;

    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "SQL error: " << sqlite3_errmsg(db) << std::endl;
        sqlite3_finalize(stmt);
        return result;
    }
    for (size_t i = 0; i < params.size(); ++i) {
        sqlite3_bind_text(stmt, static_cast<int>(i + 1), params[i].c_str(), -1, SQLITE_TRANSIENT);
    }
    int column_count = sqlite3_column_count(stmt);
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        json row = json::object();
        for (int i = 0; i < column_count; i++) {
            const char* column_name = sqlite3_column_name(stmt, i);
            switch (sqlite3_column_type(stmt, i)) {
                case SQLITE_INTEGER: row[column_name] = sqlite3_column_int64(stmt, i); break;
                case SQLITE_FLOAT:   row[column_name] = sqlite3_column_double(stmt, i); break;
                case SQLITE_TEXT:    row[column_name] = std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, i))); break;
                case SQLITE_BLOB:    row[column_name] = "<BLOB_DATA>"; break;
                case SQLITE_NULL:    row[column_name] = nullptr; break;
            }
        }
        result.push_back(row);
    }
    sqlite3_finalize(stmt);
    return result;
}

int SQLiteHelper::clamp_limit(int limit, int def_val, int max_val) {
    if (limit <= 0) return def_val;
    return limit > max_val ? max_val : limit;
}

int SQLiteHelper::clamp_offset(int offset) {
    return offset < 0 ? 0 : offset;
}

// Shared token blocklist check: returns true if `upper` (already upper-cased)
// contains any forbidden keyword as a whole word.
static bool contains_forbidden_token(const std::string& upper,
                                     const std::vector<std::string>& tokens) {
    auto is_word_char = [](char c) {
        return std::isalnum(static_cast<unsigned char>(c)) || c == '_';
    };
    for (const auto& tok : tokens) {
        size_t pos = 0;
        while ((pos = upper.find(tok, pos)) != std::string::npos) {
            bool left_ok = (pos == 0) || !is_word_char(upper[pos - 1]);
            size_t end = pos + tok.size();
            bool right_ok = (end >= upper.size()) || !is_word_char(upper[end]);
            if (left_ok && right_ok) return true;
            pos = end;
        }
    }
    return false;
}

bool SQLiteHelper::is_readonly_select(const std::string& sql) {
    // Trim leading/trailing whitespace.
    size_t b = sql.find_first_not_of(" \t\r\n");
    if (b == std::string::npos) return true;  // empty -> caller uses default
    size_t e = sql.find_last_not_of(" \t\r\n");
    std::string trimmed = sql.substr(b, e - b + 1);

    // No SQL comments (could hide a second statement or bypass checks).
    if (trimmed.find("--") != std::string::npos || trimmed.find("/*") != std::string::npos) {
        return false;
    }
    // Single statement only: allow a single optional trailing ';'.
    size_t semi = trimmed.find(';');
    if (semi != std::string::npos && semi != trimmed.size() - 1) return false;

    std::string upper = trimmed;
    std::transform(upper.begin(), upper.end(), upper.begin(), ::toupper);
    // Must begin with SELECT or WITH (CTE ending in SELECT).
    if (upper.rfind("SELECT", 0) != 0 && upper.rfind("WITH", 0) != 0) return false;

    return !contains_forbidden_token(upper,
        {"ATTACH", "DETACH", "PRAGMA", "INSERT", "UPDATE", "DELETE", "DROP",
         "ALTER", "CREATE", "REPLACE", "VACUUM", "REINDEX"});
}

bool SQLiteHelper::is_safe_filter_clause(const std::string& clause) {
    if (clause.find_first_not_of(" \t\r\n") == std::string::npos) return true;  // empty ok
    if (clause.find(';') != std::string::npos) return false;
    if (clause.find("--") != std::string::npos || clause.find("/*") != std::string::npos) return false;

    std::string upper = clause;
    std::transform(upper.begin(), upper.end(), upper.begin(), ::toupper);
    return !contains_forbidden_token(upper,
        {"ATTACH", "DETACH", "PRAGMA", "INSERT", "UPDATE", "DELETE", "DROP",
         "ALTER", "CREATE", "REPLACE", "VACUUM", "REINDEX", "UNION", "SELECT"});
}

bool SQLiteHelper::table_exists(sqlite3* db, const std::string& table_name) {
    std::string sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='" + table_name + "';";
    sqlite3_stmt* stmt;
    bool exists = false;

    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            exists = true;
        }
        sqlite3_finalize(stmt);
    }
    return exists;
}

bool SQLiteHelper::column_exists(sqlite3* db, const std::string& table_name,
                                 const std::string& column_name) {
    // pragma_table_info is safe against attacker-controlled names only when
    // table_name is itself validated (callers gate on table_exists first); the
    // column name is matched in code, not interpolated into SQL.
    std::string sql = "SELECT name FROM pragma_table_info('" + table_name + "');";
    sqlite3_stmt* stmt;
    bool exists = false;

    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (name && column_name == name) {
                exists = true;
                break;
            }
        }
        sqlite3_finalize(stmt);
    }
    return exists;
}

std::string SQLiteHelper::format_timestamp(int64_t timestamp) {
    if (timestamp <= 0) return "Unknown";

    std::time_t time = timestamp;
    std::stringstream ss;
    ss << std::put_time(std::gmtime(&time), "%Y-%m-%d %H:%M:%S UTC");
    return ss.str();
}

int64_t SQLiteHelper::parse_timestamp(const std::string& time_str) {
    if (time_str.empty()) return 0;

    // 1. 首先尝试纯 Unix 秒数字（最常见路径，保持性能）
    try { return std::stoll(time_str); } catch (...) {}

    // 2. 尝试 ISO 8601 日期格式 "YYYY-MM-DD"
    if (time_str.size() == 10) {
        std::tm tm = {};
        std::istringstream ss(time_str);
        ss >> std::get_time(&tm, "%Y-%m-%d");
        if (!ss.fail()) {
            tm.tm_isdst = -1;
            time_t t = std::mktime(&tm);
            if (t != -1) return static_cast<int64_t>(t);
        }
    }

    // 3. 尝试 ISO 8601 带时间 "YYYY-MM-DDTHH:MM:SS" 或 "YYYY-MM-DD HH:MM:SS"
    if (time_str.size() >= 19) {
        std::tm tm = {};
        std::string normalized = time_str.substr(0, 19);
        if (normalized[10] == 'T') normalized[10] = ' ';
        std::istringstream ss(normalized);
        ss >> std::get_time(&tm, "%Y-%m-%d %H:%M:%S");
        if (!ss.fail()) {
            tm.tm_isdst = -1;
            time_t t = std::mktime(&tm);
            if (t != -1) return static_cast<int64_t>(t);
        }
    }

    std::cerr << "[parse_timestamp] Unrecognized format: " << time_str << std::endl;
    return 0;
}

bool SQLiteHelper::is_suspicious_extension(const std::string& ext) {
    std::string lower_ext = ext;
    std::transform(lower_ext.begin(), lower_ext.end(), lower_ext.begin(), ::tolower);

    std::vector<std::string> suspicious = {
        ".bat", ".cmd", ".scr", ".vbs", ".js", ".jar", ".exe", ".com", ".pif"
    };

    return std::find(suspicious.begin(), suspicious.end(), lower_ext) != suspicious.end();
}

bool SQLiteHelper::is_suspicious_path(const std::string& path) {
    std::string lower_path = path;
    std::transform(lower_path.begin(), lower_path.end(), lower_path.begin(), ::tolower);

    std::vector<std::string> suspicious_patterns = {
        "/temp/", "/tmp/", "recycle", "$recycle", "system32"
    };

    for (const auto& pattern : suspicious_patterns) {
        if (lower_path.find(pattern) != std::string::npos) {
            return true;
        }
    }

    return false;
}

int SQLiteHelper::get_total_event_count(sqlite3* db) {
    sqlite3_stmt* stmt;
    int count = 0;

    if (sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM events", -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            count = sqlite3_column_int(stmt, 0);
        }
        sqlite3_finalize(stmt);
    }

    return count;
}
