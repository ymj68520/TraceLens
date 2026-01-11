# AuditLog

## Overview
The AuditLog module provides a high-performance, persistent auditing system for the forensics tools. Optimized for low-memory environments, it uses SQLite for storage with intelligent caching and asynchronous flushing strategies.

## Features
- **Persistence**: Stores all logs in a local SQLite database.
- **Performance**: Implements write buffering, batch insertion, and LRU read caching.
- **Thread Safety**: Fully thread-safe design for concurrent access from multiple modules.
- **Management**: Supports automatic log rotation, retention policies, and export to JSON/CSV.

## Components
- **Core**:
  - `AuditLog`: Singleton class managing the logging lifecycle.
- **Data Structures**:
  - `AuditLogConfig`: Configuration for database path, cache size, retention, etc.
  - `AuditLogEntry`: Represents a single log event.

## Usage
The module is typically used via its singleton instance:

```cpp
// Initialize (optional configuration)
AuditLogConfig config;
config.db_path = "audit.db";
AuditLog::instance(config);

// Log an event
AuditLog::instance().log(taskId, "ACTION_TYPE", "Details about the event");

// Query logs
auto logs = AuditLog::instance().getTaskLogs(taskId);
```

## Dependencies
- **SQLite3**: For underlying storage.
- **nlohmann/json**: For statistics and export.
- **C++20**: Uses modern C++ features (filesystem, chrono).

