// LinuxQueryBuilder.h
// Type-safe SQL query builder to prevent SQL injection
// Part of LinuxFilesAnalyzer module improvements

#pragma once
#ifndef LINUX_QUERY_BUILDER_H
#define LINUX_QUERY_BUILDER_H

#include <string>
#include <vector>
#include <variant>
#include <optional>
#include <stdexcept>
#include <sqlite3.h>

namespace LinuxAnalysis {

// Supported column names for query validation (whitelist)
namespace Columns {
    // Log entries
    inline const char* LOG_FILE = "log_file";
    inline const char* TIMESTAMP = "timestamp";
    inline const char* UNIX_TIMESTAMP = "unix_timestamp";
    inline const char* HOSTNAME = "hostname";
    inline const char* PROCESS = "process";
    inline const char* PID = "pid";
    inline const char* MESSAGE = "message";
    inline const char* LEVEL = "level";
    inline const char* FACILITY = "facility";
    
    // Users
    inline const char* USERNAME = "username";
    inline const char* UID = "uid";
    inline const char* GID = "gid";
    inline const char* FULL_NAME = "full_name";
    inline const char* HOME_DIRECTORY = "home_directory";
    inline const char* SHELL = "shell";
    inline const char* IS_LOCKED = "is_locked";
    inline const char* IS_SYSTEM_ACCOUNT = "is_system_account";
    
    // Login records
    inline const char* TERMINAL = "terminal";
    inline const char* REMOTE_HOST = "remote_host";
    inline const char* LOGIN_TIME = "login_time";
    inline const char* LOGOUT_TIME = "logout_time";
    inline const char* LOGIN_TYPE = "login_type";
    inline const char* IS_SUCCESS = "is_success";
    
    // Shell history
    inline const char* SHELL_TYPE = "shell_type";
    inline const char* COMMAND = "command";
    inline const char* LINE_NUMBER = "line_number";
    inline const char* HISTORY_FILE = "history_file";
    
    // Cron jobs
    inline const char* MINUTE = "minute";
    inline const char* HOUR = "hour";
    inline const char* DAY_OF_MONTH = "day_of_month";
    inline const char* MONTH = "month";
    inline const char* DAY_OF_WEEK = "day_of_week";
    inline const char* CRON_FILE = "cron_file";
    inline const char* CRON_TYPE = "cron_type";
    
    // SSH keys
    inline const char* KEY_TYPE = "key_type";
    inline const char* PUBLIC_KEY = "public_key";
    inline const char* KEY_PATH = "key_path";
    inline const char* COMMENT = "comment";
    inline const char* OPTIONS = "options";
    
    // Packages
    inline const char* NAME = "name";
    inline const char* VERSION = "version";
    inline const char* ARCHITECTURE = "architecture";
    inline const char* INSTALL_TIME = "install_time";
    inline const char* PACKAGE_MANAGER = "package_manager";
    inline const char* STATUS = "status";
    inline const char* DESCRIPTION = "description";
    inline const char* MAINTAINER = "maintainer";
    
    // Network
    inline const char* PROTOCOL = "protocol";
    inline const char* LOCAL_ADDRESS = "local_address";
    inline const char* LOCAL_PORT = "local_port";
    inline const char* REMOTE_ADDRESS = "remote_address";
    inline const char* REMOTE_PORT = "remote_port";
    inline const char* STATE = "state";
    inline const char* INODE = "inode";
    
    // Systemd
    inline const char* SERVICE_NAME = "service_name";
    inline const char* LOAD_STATE = "load_state";
    inline const char* ACTIVE_STATE = "active_state";
    inline const char* SUB_STATE = "sub_state";
    inline const char* UNIT_FILE = "unit_file";
    inline const char* EXEC_START = "exec_start";
    inline const char* USER = "user";
    inline const char* IS_ENABLED = "is_enabled";
    
    // Firewall
    inline const char* CHAIN = "chain";
    inline const char* TABLE_NAME = "table_name";
    inline const char* SOURCE = "source";
    inline const char* DESTINATION = "destination";
    inline const char* SOURCE_PORT = "source_port";
    inline const char* DESTINATION_PORT = "destination_port";
    inline const char* ACTION = "action";
    inline const char* RULE_SPEC = "rule_spec";
    
    // Audit
    inline const char* SERIAL_NUMBER = "serial_number";
    inline const char* TYPE = "type";
    inline const char* SUBJECT = "subject";
    inline const char* OBJECT = "object";
    inline const char* RESULT = "result";
    
    // Browser
    inline const char* BROWSER_TYPE = "browser_type";
    inline const char* BROWSER_NAME = "browser_name";
    inline const char* PROFILE_NAME = "profile_name";
    inline const char* PROFILE_PATH = "profile_path";
}

// Parameter value type
using ParamValue = std::variant<std::string, int, int64_t, double, bool>;

// Query condition types
enum class ConditionType {
    EQUALS,
    NOT_EQUALS,
    LESS_THAN,
    LESS_EQUAL,
    GREATER_THAN,
    GREATER_EQUAL,
    LIKE,
    NOT_LIKE,
    IN,
    IS_NULL,
    IS_NOT_NULL
};

// Single query condition
struct QueryCondition {
    std::string column;
    ConditionType type;
    std::vector<ParamValue> values;  // Multiple for IN clause
    
    QueryCondition(const std::string& col, ConditionType t, const ParamValue& val)
        : column(col), type(t), values({val}) {}
    
    QueryCondition(const std::string& col, ConditionType t, const std::vector<ParamValue>& vals)
        : column(col), type(t), values(vals) {}
    
    // For IS_NULL / IS_NOT_NULL
    QueryCondition(const std::string& col, ConditionType t)
        : column(col), type(t) {}
};

// Sort direction
enum class SortOrder {
    ASC,
    DESC
};

// Sort specification
struct SortSpec {
    std::string column;
    SortOrder order;
    
    SortSpec(const std::string& col, SortOrder ord = SortOrder::ASC)
        : column(col), order(ord) {}
};

/**
 * @brief Type-safe SQL query builder to prevent SQL injection
 * 
 * Usage:
 *   QueryBuilder qb;
 *   qb.where(Columns::USERNAME, ConditionType::EQUALS, "admin")
 *     .andWhere(Columns::IS_LOCKED, ConditionType::EQUALS, false)
 *     .orderBy(Columns::UID, SortOrder::ASC)
 *     .limit(100);
 */
class QueryBuilder {
public:
    QueryBuilder() = default;
    
    // Add WHERE condition (first condition)
    QueryBuilder& where(const std::string& column, ConditionType type, const ParamValue& value) {
        validateColumn(column);
        conditions_.emplace_back(column, type, value);
        conjunctions_.push_back("WHERE");
        return *this;
    }
    
    // Add WHERE IS NULL / IS NOT NULL
    QueryBuilder& whereNull(const std::string& column, bool isNull = true) {
        validateColumn(column);
        conditions_.emplace_back(column, isNull ? ConditionType::IS_NULL : ConditionType::IS_NOT_NULL);
        conjunctions_.push_back("WHERE");
        return *this;
    }
    
    // Add AND condition
    QueryBuilder& andWhere(const std::string& column, ConditionType type, const ParamValue& value) {
        validateColumn(column);
        conditions_.emplace_back(column, type, value);
        conjunctions_.push_back("AND");
        return *this;
    }
    
    // Add OR condition
    QueryBuilder& orWhere(const std::string& column, ConditionType type, const ParamValue& value) {
        validateColumn(column);
        conditions_.emplace_back(column, type, value);
        conjunctions_.push_back("OR");
        return *this;
    }
    
    // Add IN clause
    QueryBuilder& whereIn(const std::string& column, const std::vector<ParamValue>& values) {
        validateColumn(column);
        conditions_.emplace_back(column, ConditionType::IN, values);
        conjunctions_.push_back("WHERE");
        return *this;
    }
    
    // Add ORDER BY
    QueryBuilder& orderBy(const std::string& column, SortOrder order = SortOrder::ASC) {
        validateColumn(column);
        sortSpecs_.emplace_back(column, order);
        return *this;
    }
    
    // Set LIMIT
    QueryBuilder& limit(int count) {
        limit_ = count;
        return *this;
    }
    
    // Set OFFSET
    QueryBuilder& offset(int count) {
        offset_ = count;
        return *this;
    }
    
    // Build the WHERE clause (without SELECT part)
    std::string buildWhereClause() const {
        if (conditions_.empty()) {
            return "";
        }
        
        std::string clause;
        for (size_t i = 0; i < conditions_.size(); ++i) {
            if (i > 0) {
                clause += " " + conjunctions_[i] + " ";
            }
            clause += buildCondition(conditions_[i], i);
        }
        return clause;
    }
    
    // Build ORDER BY clause
    std::string buildOrderByClause() const {
        if (sortSpecs_.empty()) {
            return "";
        }
        
        std::string clause = " ORDER BY ";
        for (size_t i = 0; i < sortSpecs_.size(); ++i) {
            if (i > 0) clause += ", ";
            clause += sortSpecs_[i].column;
            clause += (sortSpecs_[i].order == SortOrder::ASC) ? " ASC" : " DESC";
        }
        return clause;
    }
    
    // Build LIMIT clause
    std::string buildLimitClause() const {
        std::string clause;
        if (limit_ > 0) {
            clause = " LIMIT " + std::to_string(limit_);
            if (offset_ > 0) {
                clause += " OFFSET " + std::to_string(offset_);
            }
        }
        return clause;
    }
    
    // Build complete clause (WHERE + ORDER BY + LIMIT)
    std::string buildFullClause() const {
        std::string clause;
        std::string whereClause = buildWhereClause();
        if (!whereClause.empty()) {
            clause = " WHERE " + whereClause;
        }
        clause += buildOrderByClause();
        clause += buildLimitClause();
        return clause;
    }
    
    // Bind parameters to prepared statement
    bool bindParameters(sqlite3_stmt* stmt) const {
        int paramIndex = 1;
        
        for (const auto& cond : conditions_) {
            if (cond.type == ConditionType::IS_NULL || 
                cond.type == ConditionType::IS_NOT_NULL) {
                continue;  // No parameter for NULL checks
            }
            
            for (const auto& value : cond.values) {
                if (!bindValue(stmt, paramIndex++, value)) {
                    return false;
                }
            }
        }
        return true;
    }
    
    // Get parameter count
    size_t getParameterCount() const {
        size_t count = 0;
        for (const auto& cond : conditions_) {
            if (cond.type != ConditionType::IS_NULL && 
                cond.type != ConditionType::IS_NOT_NULL) {
                count += cond.values.size();
            }
        }
        return count;
    }
    
    // Check if query builder has any conditions
    bool empty() const {
        return conditions_.empty();
    }
    
    // Clear all conditions
    void clear() {
        conditions_.clear();
        conjunctions_.clear();
        sortSpecs_.clear();
        limit_ = 0;
        offset_ = 0;
    }

private:
    std::vector<QueryCondition> conditions_;
    std::vector<std::string> conjunctions_;  // WHERE, AND, OR
    std::vector<SortSpec> sortSpecs_;
    int limit_ = 0;
    int offset_ = 0;
    
    // Validate column name (prevent injection via column names)
    void validateColumn(const std::string& column) const {
        // Allow only alphanumeric and underscore
        for (char c : column) {
            if (!std::isalnum(c) && c != '_') {
                throw std::invalid_argument("Invalid column name: " + column);
            }
        }
    }
    
    // Build single condition string with placeholder
    std::string buildCondition(const QueryCondition& cond, size_t /*index*/) const {
        std::string result = cond.column;
        
        switch (cond.type) {
            case ConditionType::EQUALS:
                result += " = ?";
                break;
            case ConditionType::NOT_EQUALS:
                result += " != ?";
                break;
            case ConditionType::LESS_THAN:
                result += " < ?";
                break;
            case ConditionType::LESS_EQUAL:
                result += " <= ?";
                break;
            case ConditionType::GREATER_THAN:
                result += " > ?";
                break;
            case ConditionType::GREATER_EQUAL:
                result += " >= ?";
                break;
            case ConditionType::LIKE:
                result += " LIKE ?";
                break;
            case ConditionType::NOT_LIKE:
                result += " NOT LIKE ?";
                break;
            case ConditionType::IN: {
                result += " IN (";
                for (size_t i = 0; i < cond.values.size(); ++i) {
                    if (i > 0) result += ", ";
                    result += "?";
                }
                result += ")";
                break;
            }
            case ConditionType::IS_NULL:
                result += " IS NULL";
                break;
            case ConditionType::IS_NOT_NULL:
                result += " IS NOT NULL";
                break;
        }
        return result;
    }
    
    // Bind a single value to statement
    static bool bindValue(sqlite3_stmt* stmt, int index, const ParamValue& value) {
        return std::visit([stmt, index](auto&& arg) -> bool {
            using T = std::decay_t<decltype(arg)>;
            if constexpr (std::is_same_v<T, std::string>) {
                return sqlite3_bind_text(stmt, index, arg.c_str(), -1, SQLITE_TRANSIENT) == SQLITE_OK;
            } else if constexpr (std::is_same_v<T, int>) {
                return sqlite3_bind_int(stmt, index, arg) == SQLITE_OK;
            } else if constexpr (std::is_same_v<T, int64_t>) {
                return sqlite3_bind_int64(stmt, index, arg) == SQLITE_OK;
            } else if constexpr (std::is_same_v<T, double>) {
                return sqlite3_bind_double(stmt, index, arg) == SQLITE_OK;
            } else if constexpr (std::is_same_v<T, bool>) {
                return sqlite3_bind_int(stmt, index, arg ? 1 : 0) == SQLITE_OK;
            }
            return false;
        }, value);
    }
};

} // namespace LinuxAnalysis

#endif // LINUX_QUERY_BUILDER_H
