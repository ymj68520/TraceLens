#pragma once
#ifndef AUDIT_LOG_DATA_TYPES_H
#define AUDIT_LOG_DATA_TYPES_H

#include <string>
#include <cstdint>
#include <chrono>
#include <nlohmann/json.hpp>

/**
 * @brief Audit log entry structure
 * 
 * Represents a single audit log entry with timestamp, action, and details.
 */
struct AuditLogEntry {
    int64_t id = 0;                                          // Database primary key (auto-increment)
    std::string task_id;                                     // Associated task ID
    std::chrono::system_clock::time_point timestamp;         // Timestamp (human-readable)
    std::string action;                                      // Action type (e.g., "CREATED", "STATUS_CHANGE")
    std::string details;                                     // Detailed information
    std::string user_id;                                     // User identifier (optional)
    
    // Helper method to convert timestamp to Unix milliseconds
    int64_t timestampToUnixMs() const {
        return std::chrono::duration_cast<std::chrono::milliseconds>(
            timestamp.time_since_epoch()).count();
    }
    
    // Helper method to create from Unix milliseconds
    static AuditLogEntry fromUnixMs(int64_t id, const std::string& task_id,
                                    int64_t timestamp_ms, const std::string& action,
                                    const std::string& details, const std::string& user_id) {
        AuditLogEntry entry;
        entry.id = id;
        entry.task_id = task_id;
        entry.timestamp = std::chrono::system_clock::time_point(
            std::chrono::milliseconds(timestamp_ms));
        entry.action = action;
        entry.details = details;
        entry.user_id = user_id;
        return entry;
    }
};

/**
 * @brief Configuration for AuditLog system
 */
struct AuditLogConfig {
    std::string db_path = "forensics_audit.db";              // Database file path
    size_t cache_size = 100;                                 // Number of entries in read cache
    size_t batch_size = 1;                                   // Batch write threshold (1 = immediate write for safety)
    int flush_interval_seconds = 3;                          // Auto-flush interval (for async mode only)
    bool async_write = false;                                // Disable async write by default for data safety
    size_t max_db_size_mb = 100;                             // Max database size before rotation
    int retention_days = 30;                                 // Log retention period
    bool enable_wal = true;                                  // Enable SQLite WAL mode
};

// JSON serialization support
namespace nlohmann {
    template <>
    struct adl_serializer<AuditLogEntry> {
        static void to_json(json& j, const AuditLogEntry& entry) {
            auto time_t_value = std::chrono::system_clock::to_time_t(entry.timestamp);
            j = json{
                {"id", entry.id},
                {"task_id", entry.task_id},
                {"timestamp", entry.timestampToUnixMs()},
                {"timestamp_readable", std::ctime(&time_t_value)},
                {"action", entry.action},
                {"details", entry.details},
                {"user_id", entry.user_id}
            };
        }
    };
}

#endif // AUDIT_LOG_DATA_TYPES_H
