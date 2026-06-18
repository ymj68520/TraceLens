#include "AuditLog.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <filesystem>
#include <iomanip>
#include <cstring>

// Global atomic flag for signal-based shutdown request

// AuditLog query and maintenance methods.
// Split from AuditLog.cpp. Methods belong to the AuditLog singleton.

std::vector<AuditLogEntry> AuditLog::executeQuery(const std::string& sql,
                                                  const std::vector<std::string>& params,
                                                  int limit, int offset) {
    std::vector<AuditLogEntry> results;
    
    if (!db_) {
        return results;
    }
    
    // Build complete SQL with limit and offset
    std::string complete_sql = sql;
    if (limit > 0) {
        complete_sql += " LIMIT " + std::to_string(limit);
        if (offset > 0) {
            complete_sql += " OFFSET " + std::to_string(offset);
        }
    }
    
    sqlite3_stmt* stmt = nullptr;
    int rc = sqlite3_prepare_v2(db_, complete_sql.c_str(), -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to prepare query: " << sqlite3_errmsg(db_) << std::endl;
        return results;
    }
    
    // Bind parameters
    for (size_t i = 0; i < params.size(); ++i) {
        sqlite3_bind_text(stmt, static_cast<int>(i + 1), params[i].c_str(), -1, SQLITE_TRANSIENT);
    }
    
    // Execute and fetch results
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        int64_t id = sqlite3_column_int64(stmt, 0);
        const char* task_id = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        int64_t timestamp = sqlite3_column_int64(stmt, 2);
        const char* action = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        const char* details = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        const char* user_id = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
        
        results.push_back(AuditLogEntry::fromUnixMs(
            id,
            task_id ? task_id : "",
            timestamp,
            action ? action : "",
            details ? details : "",
            user_id ? user_id : ""
        ));
    }
    
    sqlite3_finalize(stmt);
    return results;
}

// Get task logs
std::vector<AuditLogEntry> AuditLog::getTaskLogs(const std::string& task_id,
                                                 int limit, int offset) {
    // Try cache first
    std::vector<AuditLogEntry> cached_results;
    if (tryGetFromCache(task_id, cached_results)) {
        // Apply limit/offset to cached results
        if (limit > 0 && offset < static_cast<int>(cached_results.size())) {
            auto begin = cached_results.begin() + offset;
            auto end = (offset + limit < static_cast<int>(cached_results.size()))
                ? begin + limit : cached_results.end();
            return std::vector<AuditLogEntry>(begin, end);
        }
        return cached_results;
    }
    
    // Query database
    std::string sql = 
        "SELECT id, task_id, timestamp, action, details, user_id "
        "FROM audit_logs WHERE task_id = ? ORDER BY timestamp DESC";
    
    auto results = executeQuery(sql, {task_id}, limit, offset);
    
    // Add to cache
    if (!results.empty() && limit == 0) {  // Only cache complete results
        std::lock_guard<std::mutex> lock(cache_mutex_);
        read_cache_[task_id] = std::list<AuditLogEntry>(results.begin(), results.end());
        current_cache_size_ = results.size();
        
        // Evict if cache is too large
        while (current_cache_size_ > config_.cache_size && !read_cache_.empty()) {
            auto it = read_cache_.begin();
            current_cache_size_ -= it->second.size();
            read_cache_.erase(it);
        }
    }
    
    return results;
}

// Get logs by time range
std::vector<AuditLogEntry> AuditLog::getLogsByTimeRange(
    const std::chrono::system_clock::time_point& start,
    const std::chrono::system_clock::time_point& end,
    int limit, int offset) {
    
    int64_t start_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        start.time_since_epoch()).count();
    int64_t end_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        end.time_since_epoch()).count();
    
    std::string sql = 
        "SELECT id, task_id, timestamp, action, details, user_id "
        "FROM audit_logs WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp DESC";
    
    return executeQuery(sql, {std::to_string(start_ms), std::to_string(end_ms)}, limit, offset);
}

// Get logs by action
std::vector<AuditLogEntry> AuditLog::getLogsByAction(const std::string& action,
                                                     int limit, int offset) {
    std::string sql = 
        "SELECT id, task_id, timestamp, action, details, user_id "
        "FROM audit_logs WHERE action = ? ORDER BY timestamp DESC";
    
    return executeQuery(sql, {action}, limit, offset);
}

// Try get from cache
bool AuditLog::tryGetFromCache(const std::string& task_id, std::vector<AuditLogEntry>& result) {
    std::lock_guard<std::mutex> lock(cache_mutex_);
    auto it = read_cache_.find(task_id);
    if (it != read_cache_.end()) {
        result.assign(it->second.begin(), it->second.end());
        return true;
    }
    return false;
}

// Get log count
int64_t AuditLog::getLogCount(const std::string& task_id) {
    if (!db_) {
        return 0;
    }
    
    std::string sql = task_id.empty()
        ? "SELECT COUNT(*) FROM audit_logs"
        : "SELECT COUNT(*) FROM audit_logs WHERE task_id = ?";
    
    sqlite3_stmt* stmt = nullptr;
    int rc = sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        return 0;
    }
    
    if (!task_id.empty()) {
        sqlite3_bind_text(stmt, 1, task_id.c_str(), -1, SQLITE_TRANSIENT);
    }
    
    int64_t count = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        count = sqlite3_column_int64(stmt, 0);
    }
    
    sqlite3_finalize(stmt);
    return count;
}

// Get statistics
nlohmann::json AuditLog::getStatistics() {
    nlohmann::json stats;
    
    if (!db_) {
        return stats;
    }
    
    // Total count
    stats["total_logs"] = getLogCount();
    
    // Count by action
    const char* action_sql = 
        "SELECT action, COUNT(*) as count FROM audit_logs GROUP BY action ORDER BY count DESC";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, action_sql, -1, &stmt, nullptr) == SQLITE_OK) {
        nlohmann::json actions = nlohmann::json::object();
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* action = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            int64_t count = sqlite3_column_int64(stmt, 1);
            if (action) {
                actions[action] = count;
            }
        }
        stats["by_action"] = actions;
        sqlite3_finalize(stmt);
    }
    
    // Database size
    stats["db_size_mb"] = getDatabaseSizeMB();
    
    // Cache stats
    stats["cache_size"] = current_cache_size_;
    stats["cache_limit"] = config_.cache_size;
    
    // Write buffer
    std::lock_guard<std::mutex> lock(write_mutex_);
    stats["pending_writes"] = write_buffer_.size();
    
    return stats;
}

// Cleanup
void AuditLog::cleanup(int retention_days) {
    if (retention_days < 0) {
        retention_days = config_.retention_days;
    }
    
    auto cutoff_time = std::chrono::system_clock::now() - std::chrono::hours(retention_days * 24);
    int64_t cutoff_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        cutoff_time.time_since_epoch()).count();
    
    std::string sql = "DELETE FROM audit_logs WHERE timestamp < ?";
    
    sqlite3_stmt* stmt = nullptr;
    int rc = sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to prepare cleanup statement: " << sqlite3_errmsg(db_) << std::endl;
        return;
    }
    
    sqlite3_bind_int64(stmt, 1, cutoff_ms);
    
    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        std::cerr << "Failed to cleanup old logs: " << sqlite3_errmsg(db_) << std::endl;
    } else {
        int deleted = sqlite3_changes(db_);
        std::cout << "Cleaned up " << deleted << " old audit log entries" << std::endl;
    }
    
    sqlite3_finalize(stmt);
    
    // Vacuum to reclaim space
    sqlite3_exec(db_, "VACUUM;", nullptr, nullptr, nullptr);
    
    // Clear cache
    std::lock_guard<std::mutex> lock(cache_mutex_);
    read_cache_.clear();
    current_cache_size_ = 0;
}

// Rotate database
void AuditLog::rotate() {
    size_t current_size = getDatabaseSizeMB();
    
    if (current_size < config_.max_db_size_mb) {
        return;  // No rotation needed
    }
    
    std::cout << "Rotating audit log database (current size: " << current_size << " MB)" << std::endl;
    
    // Flush and close
    flush();
    
    if (insert_stmt_) {
        sqlite3_finalize(insert_stmt_);
        insert_stmt_ = nullptr;
    }
    
    if (db_) {
        sqlite3_close(db_);
        db_ = nullptr;
    }
    
    // Rename old database
    auto now = std::chrono::system_clock::now();
    auto time_t_now = std::chrono::system_clock::to_time_t(now);
    std::tm tm_now;
    localtime_r(&time_t_now, &tm_now);
    
    std::ostringstream oss;
    oss << config_.db_path << "."
        << std::put_time(&tm_now, "%Y%m%d_%H%M%S")
        << ".backup";
    
    std::filesystem::rename(config_.db_path, oss.str());
    
    // Reinitialize
    initDatabase();
    
    std::cout << "Database rotated to: " << oss.str() << std::endl;
}

// Export to file
void AuditLog::exportToFile(const std::string& output_path, const std::string& format) {
    // Flush pending writes first
    flush();
    
    // Get all logs
    std::string sql = 
        "SELECT id, task_id, timestamp, action, details, user_id "
        "FROM audit_logs ORDER BY timestamp DESC";
    
    auto logs = executeQuery(sql);
    
    if (format == "json") {
        nlohmann::json j = logs;
        std::ofstream ofs(output_path);
        ofs << j.dump(2);
        ofs.close();
    } else if (format == "csv") {
        std::ofstream ofs(output_path);
        ofs << "id,task_id,timestamp,action,details,user_id\n";
        for (const auto& log : logs) {
            ofs << log.id << ","
                << log.task_id << ","
                << log.timestampToUnixMs() << ","
                << log.action << ","
                << "\"" << log.details << "\","
                << log.user_id << "\n";
        }
        ofs.close();
    }
    
    std::cout << "Exported " << logs.size() << " audit log entries to " << output_path << std::endl;
}

// Get database size
size_t AuditLog::getDatabaseSizeMB() {
    try {
        if (std::filesystem::exists(config_.db_path)) {
            auto size_bytes = std::filesystem::file_size(config_.db_path);
            return size_bytes / (1024 * 1024);
        }
    } catch (const std::exception& e) {
        std::cerr << "Failed to get database size: " << e.what() << std::endl;
    }
    return 0;
}

// Flush thread function
