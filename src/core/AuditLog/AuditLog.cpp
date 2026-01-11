#include "AuditLog.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <filesystem>
#include <iomanip>
#include <cstring>

// Global atomic flag for signal-based shutdown request
// This is async-signal-safe since std::atomic<sig_atomic_t> is safe to access from signal handlers
static volatile std::sig_atomic_t g_signal_received = 0;

// Signal handler - ONLY set flag, do NOT call any non-async-signal-safe functions
static void auditLogSignalHandler(int signum) {
    g_signal_received = signum;
}

// Atexit handler for normal program termination
static void auditLogAtexitHandler();

// Global pointer for atexit handler access
static AuditLog* g_audit_log_instance = nullptr;

// Install signal handlers
static void installSignalHandlers() {
    static bool installed = false;
    if (!installed) {
        // Install signal handlers
        std::signal(SIGINT, auditLogSignalHandler);
        std::signal(SIGTERM, auditLogSignalHandler);
#ifndef _WIN32
        std::signal(SIGHUP, auditLogSignalHandler);
#endif
        // Register atexit handler
        std::atexit(auditLogAtexitHandler);
        installed = true;
    }
}

// Atexit handler implementation
static void auditLogAtexitHandler() {
    if (g_audit_log_instance) {
        g_audit_log_instance->flush();
    }
}

// Singleton instance
AuditLog& AuditLog::instance(const AuditLogConfig& config) {
    static AuditLog instance(config);
    g_audit_log_instance = &instance;
    installSignalHandlers();
    return instance;
}

// Constructor
AuditLog::AuditLog(const AuditLogConfig& config)
    : config_(config), db_(nullptr), insert_stmt_(nullptr), current_cache_size_(0) {
    
    if (!initDatabase()) {
        std::cerr << "Failed to initialize audit log database" << std::endl;
    }
    
    if (config_.async_write) {
        startFlushThread();
    }
}

// Destructor
AuditLog::~AuditLog() {
    stopFlushThread();
    flush();
    
    if (insert_stmt_) {
        sqlite3_finalize(insert_stmt_);
        insert_stmt_ = nullptr;
    }
    
    if (db_) {
        sqlite3_close(db_);
        db_ = nullptr;
    }
    
    g_audit_log_instance = nullptr;
}

// Initialize database
bool AuditLog::initDatabase() {
    // Create parent directory if needed
    std::filesystem::path db_path(config_.db_path);
    if (db_path.has_parent_path()) {
        std::filesystem::create_directories(db_path.parent_path());
    }
    
    // Open database
    int rc = sqlite3_open(config_.db_path.c_str(), &db_);
    if (rc != SQLITE_OK) {
        std::cerr << "Cannot open audit log database: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }
    
    // Enable WAL mode for better concurrency
    if (config_.enable_wal) {
        char* errMsg = nullptr;
        rc = sqlite3_exec(db_, "PRAGMA journal_mode=WAL;", nullptr, nullptr, &errMsg);
        if (rc != SQLITE_OK) {
            std::cerr << "Failed to enable WAL mode: " << errMsg << std::endl;
            sqlite3_free(errMsg);
        }
    }
    
    // Set synchronous mode for better performance
    sqlite3_exec(db_, "PRAGMA synchronous=NORMAL;", nullptr, nullptr, nullptr);
    
    // Create table
    const char* create_table_sql = R"(
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            user_id TEXT,
            created_at INTEGER DEFAULT (cast(strftime('%s', 'now') as integer) * 1000)
        );
    )";
    
    char* errMsg = nullptr;
    rc = sqlite3_exec(db_, create_table_sql, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to create audit_logs table: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }
    
    // Create indexes
    const char* create_indexes_sql = R"(
        CREATE INDEX IF NOT EXISTS idx_task_id ON audit_logs(task_id);
        CREATE INDEX IF NOT EXISTS idx_timestamp ON audit_logs(timestamp);
        CREATE INDEX IF NOT EXISTS idx_action ON audit_logs(action);
    )";
    
    rc = sqlite3_exec(db_, create_indexes_sql, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to create indexes: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        // Non-fatal, continue
    }
    
    // Prepare insert statement
    const char* insert_sql = 
        "INSERT INTO audit_logs (task_id, timestamp, action, details, user_id) "
        "VALUES (?, ?, ?, ?, ?);";
    
    rc = sqlite3_prepare_v2(db_, insert_sql, -1, &insert_stmt_, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to prepare insert statement: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }
    
    return true;
}

// Log an entry
void AuditLog::log(const std::string& task_id, const std::string& action,
                   const std::string& details, const std::string& user_id) {
    AuditLogEntry entry;
    entry.task_id = task_id;
    entry.timestamp = std::chrono::system_clock::now();
    entry.action = action;
    entry.details = details;
    entry.user_id = user_id;
    
    addToWriteBuffer(entry);
}

// Add to write buffer
void AuditLog::addToWriteBuffer(const AuditLogEntry& entry) {
    std::lock_guard<std::mutex> lock(write_mutex_);
    write_buffer_.push_back(entry);
    
    // Always flush immediately if not using async write, or if buffer is full
    // This ensures data is persisted promptly to prevent loss on crash
    if (!config_.async_write || write_buffer_.size() >= config_.batch_size) {
        flushWriteBuffer();
    }
}

// Flush write buffer
void AuditLog::flushWriteBuffer() {
    // Note: Caller must hold write_mutex_
    if (write_buffer_.empty()) {
        return;
    }
    
    // Move buffer to local variable for processing
    std::vector<AuditLogEntry> entries_to_insert;
    entries_to_insert.swap(write_buffer_);
    
    // Release lock during database operation
    write_mutex_.unlock();
    bool success = insertBatch(entries_to_insert);
    write_mutex_.lock();
    
    if (!success) {
        std::cerr << "Failed to flush write buffer, re-queuing entries" << std::endl;
        // Re-add failed entries to buffer
        write_buffer_.insert(write_buffer_.begin(),
                            entries_to_insert.begin(), entries_to_insert.end());
    }
}

// Public flush
void AuditLog::flush() {
    std::lock_guard<std::mutex> lock(write_mutex_);
    flushWriteBuffer();
}

// Insert batch
bool AuditLog::insertBatch(const std::vector<AuditLogEntry>& entries) {
    if (entries.empty() || !db_ || !insert_stmt_) {
        return false;
    }
    
    // Begin transaction
    char* errMsg = nullptr;
    int rc = sqlite3_exec(db_, "BEGIN TRANSACTION;", nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to begin transaction: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }
    
    bool success = true;
    for (const auto& entry : entries) {
        sqlite3_reset(insert_stmt_);
        sqlite3_clear_bindings(insert_stmt_);
        
        // Bind parameters
        sqlite3_bind_text(insert_stmt_, 1, entry.task_id.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_int64(insert_stmt_, 2, entry.timestampToUnixMs());
        sqlite3_bind_text(insert_stmt_, 3, entry.action.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(insert_stmt_, 4, entry.details.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(insert_stmt_, 5, entry.user_id.c_str(), -1, SQLITE_TRANSIENT);
        
        rc = sqlite3_step(insert_stmt_);
        if (rc != SQLITE_DONE) {
            std::cerr << "Failed to insert audit log: " << sqlite3_errmsg(db_) << std::endl;
            success = false;
            break;
        }
    }
    
    // Commit or rollback
    if (success) {
        rc = sqlite3_exec(db_, "COMMIT;", nullptr, nullptr, &errMsg);
        if (rc != SQLITE_OK) {
            std::cerr << "Failed to commit transaction: " << errMsg << std::endl;
            sqlite3_free(errMsg);
            success = false;
        }
    } else {
        sqlite3_exec(db_, "ROLLBACK;", nullptr, nullptr, nullptr);
    }
    
    return success;
}

// Execute query
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
void AuditLog::flushThreadFunc() {
    while (!stop_flush_thread_) {
        std::unique_lock<std::mutex> lock(flush_mtx_);
        flush_cv_.wait_for(lock, std::chrono::seconds(config_.flush_interval_seconds),
                          [this]() { return stop_flush_thread_.load() || g_signal_received != 0; });
        
        // Check for signal - perform graceful shutdown
        if (g_signal_received != 0) {
            int sig = g_signal_received;
            g_signal_received = 0;  // Reset for potential re-use
            
            // Flush all pending writes
            {
                std::lock_guard<std::mutex> write_lock(write_mutex_);
                flushWriteBuffer();
            }
            
            // Stop this thread
            stop_flush_thread_ = true;
            
            // Restore default handler and re-raise signal
            std::signal(sig, SIG_DFL);
            std::raise(sig);
            break;
        }
        
        if (stop_flush_thread_) {
            break;
        }
        
        // Flush write buffer
        {
            std::lock_guard<std::mutex> write_lock(write_mutex_);
            flushWriteBuffer();
        }
    }
}

// Start flush thread
void AuditLog::startFlushThread() {
    stop_flush_thread_ = false;
    flush_thread_ = std::thread(&AuditLog::flushThreadFunc, this);
}

// Stop flush thread
void AuditLog::stopFlushThread() {
    if (flush_thread_.joinable()) {
        stop_flush_thread_ = true;
        flush_cv_.notify_all();
        flush_thread_.join();
    }
}
