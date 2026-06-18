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

// Query & maintenance methods (executeQuery, getTaskLogs, getLogsBy*,
// getStatistics, cleanup, rotate, exportToFile, ...) live in AuditLog_Queries.cpp

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
