#pragma once

#include <string>
#include <vector>
#include <list>
#include <unordered_map>
#include <mutex>
#include <thread>
#include <atomic>
#include <condition_variable>
#include <chrono>
#include <memory>
#include <csignal>
#include <cstdlib>
#include <sqlite3.h>
#include <nlohmann/json.hpp>

#include "AuditLogDataTypes.h"



/**
 * @brief Audit Log Manager
 * 
 * Provides efficient audit logging with file-based persistence and memory cache.
 * Features:
 * - SQLite-based persistent storage
 * - Write buffer for batch insert (reduces disk I/O)
 * - LRU read cache for frequently accessed logs
 * - Async background flush thread
 * - Thread-safe operations
 * - Log rotation and cleanup
 */
class AuditLog {
public:
    /**
     * @brief Get singleton instance
     * @param config Configuration (only used on first call)
     * @return Reference to singleton instance
     */
    static AuditLog& instance(const AuditLogConfig& config = {});
    
    /**
     * @brief Log an audit entry
     * @param task_id Associated task ID
     * @param action Action type (e.g., "CREATED", "STATUS_CHANGE")
     * @param details Detailed information
     * @param user_id User identifier (optional)
     */
    void log(const std::string& task_id, const std::string& action,
             const std::string& details, const std::string& user_id = "");
    
    /**
     * @brief Force flush write buffer to database
     */
    void flush();
    
    /**
     * @brief Get audit logs for a specific task
     * @param task_id Task ID
     * @param limit Maximum number of entries (0 = no limit)
     * @param offset Offset for pagination
     * @return Vector of audit log entries
     */
    std::vector<AuditLogEntry> getTaskLogs(const std::string& task_id,
                                           int limit = 0, int offset = 0);
    
    /**
     * @brief Get audit logs within a time range
     * @param start Start time
     * @param end End time
     * @param limit Maximum number of entries (0 = no limit)
     * @param offset Offset for pagination
     * @return Vector of audit log entries
     */
    std::vector<AuditLogEntry> getLogsByTimeRange(
        const std::chrono::system_clock::time_point& start,
        const std::chrono::system_clock::time_point& end,
        int limit = 0, int offset = 0);
    
    /**
     * @brief Get audit logs by action type
     * @param action Action type
     * @param limit Maximum number of entries (0 = no limit)
     * @param offset Offset for pagination
     * @return Vector of audit log entries
     */
    std::vector<AuditLogEntry> getLogsByAction(const std::string& action,
                                               int limit = 0, int offset = 0);
    
    /**
     * @brief Get total log count
     * @param task_id Task ID (empty = all tasks)
     * @return Total number of log entries
     */
    int64_t getLogCount(const std::string& task_id = "");
    
    /**
     * @brief Get statistics about audit logs
     * @return JSON object with statistics
     */
    nlohmann::json getStatistics();
    
    /**
     * @brief Cleanup old logs
     * @param retention_days Log retention period (-1 = use config value)
     */
    void cleanup(int retention_days = -1);
    
    /**
     * @brief Rotate log database
     * 
     * Renames current database and creates a new one if size exceeds limit.
     */
    void rotate();
    
    /**
     * @brief Export logs to file
     * @param output_path Output file path
     * @param format Export format ("json" or "csv")
     */
    void exportToFile(const std::string& output_path,
                     const std::string& format = "json");
    
    /**
     * @brief Destructor - ensures all buffers are flushed
     */
    ~AuditLog();
    
    // Disable copy and move
    AuditLog(const AuditLog&) = delete;
    AuditLog& operator=(const AuditLog&) = delete;
    AuditLog(AuditLog&&) = delete;
    AuditLog& operator=(AuditLog&&) = delete;
    
private:
    /**
     * @brief Private constructor for singleton
     */
    explicit AuditLog(const AuditLogConfig& config);
    
    /**
     * @brief Initialize database connection and schema
     * @return true if successful
     */
    bool initDatabase();
    
    /**
     * @brief Insert a batch of entries into database
     * @param entries Vector of log entries
     * @return true if successful
     */
    bool insertBatch(const std::vector<AuditLogEntry>& entries);
    
    /**
     * @brief Add entry to write buffer
     * @param entry Log entry
     */
    void addToWriteBuffer(const AuditLogEntry& entry);
    
    /**
     * @brief Flush write buffer to database
     */
    void flushWriteBuffer();
    
    /**
     * @brief Add entry to read cache (LRU)
     * @param entry Log entry
     */
    void addToReadCache(const AuditLogEntry& entry);
    
    /**
     * @brief Try to get entries from read cache
     * @param task_id Task ID
     * @param result Output vector
     * @return true if found in cache
     */
    bool tryGetFromCache(const std::string& task_id, std::vector<AuditLogEntry>& result);
    
    /**
     * @brief Background flush thread function
     */
    void flushThreadFunc();
    
    /**
     * @brief Start background flush thread
     */
    void startFlushThread();
    
    /**
     * @brief Stop background flush thread
     */
    void stopFlushThread();
    
    /**
     * @brief Get database file size in MB
     * @return File size in megabytes
     */
    size_t getDatabaseSizeMB();
    
    /**
     * @brief Execute a query and return results
     * @param sql SQL query
     * @param params Query parameters
     * @param limit Result limit
     * @param offset Result offset
     * @return Vector of log entries
     */
    std::vector<AuditLogEntry> executeQuery(const std::string& sql,
                                            const std::vector<std::string>& params = {},
                                            int limit = 0, int offset = 0);
    
    AuditLogConfig config_;
    sqlite3* db_;
    
    // Write buffer (pending flush to database)
    std::vector<AuditLogEntry> write_buffer_;
    std::mutex write_mutex_;
    // Set once we've warned about dropping entries because the DB is
    // uninitialized, so the warning is not repeated for every flush.
    bool drop_warning_emitted_ = false;

    // Read cache (LRU, recently queried entries)
    // Key: task_id, Value: list of entries for that task
    std::unordered_map<std::string, std::list<AuditLogEntry>> read_cache_;
    size_t current_cache_size_;
    std::mutex cache_mutex_;
    
    // Background flush thread
    std::thread flush_thread_;
    std::atomic<bool> stop_flush_thread_{false};
    std::condition_variable flush_cv_;
    std::mutex flush_mtx_;
    
    // Prepared statements for performance
    sqlite3_stmt* insert_stmt_;
};


