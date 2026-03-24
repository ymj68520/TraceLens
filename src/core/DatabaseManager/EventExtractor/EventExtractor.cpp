#include "EventExtractor.h"
#include "DatabaseManager/SQL/event_extractor_sql.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <sstream>
#include <sqlite3.h>
#include <algorithm>

EventExtractor::EventExtractor(const std::string& sourceDbPath,
	const std::string& eventDbPath)
	: sourceDbPath_(sourceDbPath), eventDbPath_(eventDbPath),
	sourceDb_(nullptr), eventDb_(nullptr) {
}

EventExtractor::~EventExtractor() {
	closeDatabases();
}

bool EventExtractor::extractEvents() {
	AuditLog::instance().log("SYSTEM", "EVENT_EXTRACTION_START", "Starting event extraction from: " + sourceDbPath_);
	
	if (!openDatabases()) {
		return false;
	}

	if (!createEventTables()) {
		return false;
	}

	if (!extractFileSystemEvents()) {
		return false;
	}

	// 标准化事件
	if (!standardizeEvents()) {
		std::cerr << "Failed to standardize events" << std::endl;
		return false;
	}

	std::cout << "Events extracted and standardized successfully" << std::endl;
	AuditLog::instance().log("SYSTEM", "EVENT_EXTRACTION_COMPLETE", "Events extracted to: " + eventDbPath_);

	return true;
}

bool EventExtractor::openDatabases() {
	int rc = sqlite3_open(sourceDbPath_.c_str(), &sourceDb_);
	if (rc != SQLITE_OK) {
		std::cerr << "Cannot open source database: " << sqlite3_errmsg(sourceDb_) << std::endl;
		return false;
	}

	rc = sqlite3_open(eventDbPath_.c_str(), &eventDb_);
	if (rc != SQLITE_OK) {
		std::cerr << "Cannot open event database: " << sqlite3_errmsg(eventDb_) << std::endl;
		return false;
	}

	return true;
}

bool EventExtractor::createEventTables() {
    using namespace EventExtractorSQL;
    
    char* errMsg = nullptr;
    
    // Create main events table
    int rc = sqlite3_exec(eventDb_, CREATE_EVENTS_TABLE, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to create events table: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }

    // Create category tables
    sqlite3_exec(eventDb_, CREATE_CREATION_EVENTS_TABLE, nullptr, nullptr, nullptr);
    sqlite3_exec(eventDb_, CREATE_MODIFICATION_EVENTS_TABLE, nullptr, nullptr, nullptr);
    sqlite3_exec(eventDb_, CREATE_ACCESS_EVENTS_TABLE, nullptr, nullptr, nullptr);
    sqlite3_exec(eventDb_, CREATE_CHANGE_EVENTS_TABLE, nullptr, nullptr, nullptr);
    sqlite3_exec(eventDb_, CREATE_DELETION_EVENTS_TABLE, nullptr, nullptr, nullptr);

    // Create system events table
    sqlite3_exec(eventDb_, CREATE_SYSTEM_EVENTS_TABLE, nullptr, nullptr, nullptr);

    // Create event correlations table
    sqlite3_exec(eventDb_, CREATE_EVENT_CORRELATIONS_TABLE, nullptr, nullptr, nullptr);

    // Create indices
    sqlite3_exec(eventDb_, CREATE_EVENT_INDICES, nullptr, nullptr, nullptr);

    // Create views
    sqlite3_exec(eventDb_, CREATE_TIMELINE_VIEW, nullptr, nullptr, nullptr);
    sqlite3_exec(eventDb_, CREATE_STATISTICS_VIEW, nullptr, nullptr, nullptr);
    sqlite3_exec(eventDb_, CREATE_HOURLY_ACTIVITY_VIEW, nullptr, nullptr, nullptr);
    sqlite3_exec(eventDb_, CREATE_SYSTEM_EVENT_VIEW, nullptr, nullptr, nullptr);
    sqlite3_exec(eventDb_, CREATE_EVENT_CORRELATION_VIEW, nullptr, nullptr, nullptr);
    sqlite3_exec(eventDb_, CREATE_ENHANCED_TIMELINE_VIEW, nullptr, nullptr, nullptr);
    sqlite3_exec(eventDb_, CREATE_ENHANCED_STATISTICS_VIEW, nullptr, nullptr, nullptr);

    return true;
}

bool EventExtractor::extractFileSystemEvents() {
	const char* query = R"(
        SELECT inode, path, atime, mtime, ctime, crtime, type, file_size, is_deleted
        FROM files
        WHERE type = 'REG';
    )";

	sqlite3_stmt* stmt;
	int rc = sqlite3_prepare_v2(sourceDb_, query, -1, &stmt, nullptr);

	if (rc != SQLITE_OK) {
		std::cerr << "Failed to prepare query: " << sqlite3_errmsg(sourceDb_) << std::endl;
		return false;
	}

	int eventCount = 0;
	int creationCount = 0;
	int modificationCount = 0;
	int accessCount = 0;
	int changeCount = 0;
	int deletionCount = 0;

	// Begin transaction for better performance
	sqlite3_exec(eventDb_, "BEGIN TRANSACTION;", nullptr, nullptr, nullptr);

	while (sqlite3_step(stmt) == SQLITE_ROW) {
		int64_t inode = sqlite3_column_int64(stmt, 0);
		const char* path_raw = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
		std::string path = path_raw ? path_raw : "";
		int64_t atime = sqlite3_column_int64(stmt, 2);
		int64_t mtime = sqlite3_column_int64(stmt, 3);
		int64_t ctime = sqlite3_column_int64(stmt, 4);
		int64_t crtime = sqlite3_column_int64(stmt, 5);
		const char* type_raw = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
		std::string type = type_raw ? type_raw : "";
		int64_t size = sqlite3_column_int64(stmt, 7);
		int isDeleted = sqlite3_column_int(stmt, 8);

		// Helper to create basic event
		auto createBaseEvent = [&](int64_t ts, const std::string& et, const std::string& desc) {
			TimelineEvent ev;
			ev.timestamp = ts;
			ev.eventType = et;
			ev.filePath = path;
			ev.inode = inode;
			ev.description = desc;
			ev.fileSize = size;
			ev.fileType = type;
			ev.systemContext = "";
			ev.priority = EventPriority::MEDIUM;
			ev.severity = EventSeverity::INFO;
			ev.source = EventSource::FILE_SYSTEM;
			ev.category = EventCategory::FILE_OPERATION;
			ev.normalizedType = normalizeEventType(et);
			ev.sourceId = getSourceId(ev);
			return ev;
		};

		// Create event for file creation (birth time)
		if (crtime > 0) {
			insertEvent(createBaseEvent(crtime, "CREATED", "File created"));

			// Insert into creation_events table
			std::string sql = R"(
                INSERT INTO creation_events (timestamp, file_path, inode, file_size, file_type)
                VALUES (?, ?, ?, ?, ?);
            )";
			sqlite3_stmt* insertStmt;
			sqlite3_prepare_v2(eventDb_, sql.c_str(), -1, &insertStmt, nullptr);
			sqlite3_bind_int64(insertStmt, 1, crtime);
			sqlite3_bind_text(insertStmt, 2, path.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_int64(insertStmt, 3, inode);
			sqlite3_bind_int64(insertStmt, 4, size);
			sqlite3_bind_text(insertStmt, 5, type.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_step(insertStmt);
			sqlite3_finalize(insertStmt);

			eventCount++;
			creationCount++;
		}

		// Create event for file modification
		if (mtime > 0 && mtime != crtime) {
			insertEvent(createBaseEvent(mtime, "MODIFIED", "File content modified"));

			// Insert into modification_events table
			std::string sql = R"(
                INSERT INTO modification_events (timestamp, file_path, inode, file_size, file_type)
                VALUES (?, ?, ?, ?, ?);
            )";
			sqlite3_stmt* insertStmt;
			sqlite3_prepare_v2(eventDb_, sql.c_str(), -1, &insertStmt, nullptr);
			sqlite3_bind_int64(insertStmt, 1, mtime);
			sqlite3_bind_text(insertStmt, 2, path.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_int64(insertStmt, 3, inode);
			sqlite3_bind_int64(insertStmt, 4, size);
			sqlite3_bind_text(insertStmt, 5, type.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_step(insertStmt);
			sqlite3_finalize(insertStmt);

			eventCount++;
			modificationCount++;
		}

		// Create event for file access
		if (atime > 0 && atime != mtime && atime != crtime) {
			insertEvent(createBaseEvent(atime, "ACCESSED", "File accessed/read"));

			// Insert into access_events table
			std::string sql = R"(
                INSERT INTO access_events (timestamp, file_path, inode, file_size, file_type)
                VALUES (?, ?, ?, ?, ?);
            )";
			sqlite3_stmt* insertStmt;
			sqlite3_prepare_v2(eventDb_, sql.c_str(), -1, &insertStmt, nullptr);
			sqlite3_bind_int64(insertStmt, 1, atime);
			sqlite3_bind_text(insertStmt, 2, path.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_int64(insertStmt, 3, inode);
			sqlite3_bind_int64(insertStmt, 4, size);
			sqlite3_bind_text(insertStmt, 5, type.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_step(insertStmt);
			sqlite3_finalize(insertStmt);

			eventCount++;
			accessCount++;
		}

		// Create event for metadata change
		if (ctime > 0 && ctime != mtime && ctime != crtime) {
			insertEvent(createBaseEvent(ctime, "CHANGED", "Metadata changed"));

			// Insert into change_events table
			std::string sql = R"(
                INSERT INTO change_events (timestamp, file_path, inode, file_size, file_type, description)
                VALUES (?, ?, ?, ?, ?, ?);
            )";
			sqlite3_stmt* insertStmt;
			sqlite3_prepare_v2(eventDb_, sql.c_str(), -1, &insertStmt, nullptr);
			sqlite3_bind_int64(insertStmt, 1, ctime);
			sqlite3_bind_text(insertStmt, 2, path.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_int64(insertStmt, 3, inode);
			sqlite3_bind_int64(insertStmt, 4, size);
			sqlite3_bind_text(insertStmt, 5, type.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_text(insertStmt, 6, "Metadata changed", -1, SQLITE_TRANSIENT);
			sqlite3_step(insertStmt);
			sqlite3_finalize(insertStmt);

			eventCount++;
			changeCount++;
		}

		// Create event for deleted files
		if (isDeleted) {
			int64_t deletionTime = std::max({ atime, mtime, ctime, crtime });
			insertEvent(createBaseEvent(deletionTime, "DELETED", "File deleted (unallocated)"));

			// Insert into deletion_events table
			std::string sql = R"(
                INSERT INTO deletion_events (timestamp, file_path, inode, file_size, file_type)
                VALUES (?, ?, ?, ?, ?);
            )";
			sqlite3_stmt* insertStmt;
			sqlite3_prepare_v2(eventDb_, sql.c_str(), -1, &insertStmt, nullptr);
			sqlite3_bind_int64(insertStmt, 1, deletionTime);
			sqlite3_bind_text(insertStmt, 2, path.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_int64(insertStmt, 3, inode);
			sqlite3_bind_int64(insertStmt, 4, size);
			sqlite3_bind_text(insertStmt, 5, type.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_step(insertStmt);
			sqlite3_finalize(insertStmt);

			eventCount++;
			deletionCount++;
		}
	}

	sqlite3_finalize(stmt);

	// Commit transaction
	sqlite3_exec(eventDb_, "COMMIT;", nullptr, nullptr, nullptr);

	std::cout << "  Total events: " << eventCount << std::endl;
	return true;
}

// 枚举到字符串的转换函数
std::string priorityToString(EventPriority priority) {
    switch (priority) {
        case EventPriority::LOW: return "LOW";
        case EventPriority::MEDIUM: return "MEDIUM";
        case EventPriority::HIGH: return "HIGH";
        case EventPriority::CRITICAL: return "CRITICAL";
        default: return "UNKNOWN";
    }
}

std::string severityToString(EventSeverity severity) {
    switch (severity) {
        case EventSeverity::INFO: return "INFO";
        case EventSeverity::WARNING: return "WARNING";
        case EventSeverity::ERROR: return "ERROR";
        case EventSeverity::CRITICAL: return "CRITICAL";
        default: return "UNKNOWN";
    }
}

std::string sourceToString(EventSource source) {
    switch (source) {
        case EventSource::FILE_SYSTEM: return "FILE_SYSTEM";
        case EventSource::WINDOWS_EVENT_LOG: return "WINDOWS_EVENT_LOG";
        case EventSource::LINUX_SYSLOG: return "LINUX_SYSLOG";
        case EventSource::ANDROID_LOG: return "ANDROID_LOG";
        case EventSource::WEB_BROWSER: return "WEB_BROWSER";
        case EventSource::SYSTEM: return "SYSTEM";
        case EventSource::NETWORK: return "NETWORK";
        case EventSource::SECURITY: return "SECURITY";
        case EventSource::APPLICATION: return "APPLICATION";
        case EventSource::UNKNOWN: return "UNKNOWN";
        default: return "UNKNOWN";
    }
}

std::string categoryToString(EventCategory category) {
    switch (category) {
        case EventCategory::FILE_OPERATION: return "FILE_OPERATION";
        case EventCategory::SYSTEM_ACTIVITY: return "SYSTEM_ACTIVITY";
        case EventCategory::USER_ACTIVITY: return "USER_ACTIVITY";
        case EventCategory::NETWORK_ACTIVITY: return "NETWORK_ACTIVITY";
        case EventCategory::SECURITY_EVENT: return "SECURITY_EVENT";
        case EventCategory::APPLICATION_EVENT: return "APPLICATION_EVENT";
        case EventCategory::DATABASE_ACTIVITY: return "DATABASE_ACTIVITY";
        case EventCategory::HARDWARE_EVENT: return "HARDWARE_EVENT";
        case EventCategory::EXTERNAL_SOURCE: return "EXTERNAL_SOURCE";
        case EventCategory::UNKNOWN_CATEGORY: return "UNKNOWN_CATEGORY";
        default: return "UNKNOWN_CATEGORY";
    }
}

bool EventExtractor::insertEvent(const TimelineEvent& event) {
	using namespace EventExtractorSQL;
    
	sqlite3_stmt* stmt;
	int rc = sqlite3_prepare_v2(eventDb_, INSERT_EVENT, -1, &stmt, nullptr);

	if (rc != SQLITE_OK) {
		return false;
	}

	sqlite3_bind_int64(stmt, 1, event.timestamp);
	sqlite3_bind_text(stmt, 2, event.eventType.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 3, event.filePath.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_int64(stmt, 4, event.inode);
	sqlite3_bind_text(stmt, 5, event.description.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_int64(stmt, 6, event.fileSize);
	sqlite3_bind_text(stmt, 7, event.fileType.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 8, event.systemContext.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 9, priorityToString(event.priority).c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 10, severityToString(event.severity).c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 11, sourceToString(event.source).c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 12, categoryToString(event.category).c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 13, event.normalizedType.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 14, event.sourceId.c_str(), -1, SQLITE_TRANSIENT);

	rc = sqlite3_step(stmt);
	sqlite3_finalize(stmt);

	return rc == SQLITE_DONE;
}

bool EventExtractor::importWindowsArtifacts(const std::string& windowsDbPath) {
    AuditLog::instance().log("SYSTEM", "TIMELINE_MERGE", "Importing Windows artifacts from: " + windowsDbPath);
    std::string attachSql = "ATTACH DATABASE '" + windowsDbPath + "' AS win_db;";
    sqlite3_exec(eventDb_, attachSql.c_str(), nullptr, nullptr, nullptr);

    // Import event logs
    const char* importLogsSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT timestamp, 'WIN_LOG_' || COALESCE(level, 'UNK'), log_source, 0, 'ID:' || event_id || ' ' || message, 0, 'LOG', '', 'LOW', 'INFO', 'WINDOWS_EVENT_LOG', 'SYSTEM_ACTIVITY', '', ''
        FROM win_db.event_logs;
    )";
    sqlite3_exec(eventDb_, importLogsSql, nullptr, nullptr, nullptr);

    // Import browser history
    const char* importBrowserSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT visit_time, 'WEB_HISTORY', url, 0, 'Title: ' || title, 0, 'WEB', '', 'LOW', 'INFO', 'WEB_BROWSER', 'USER_ACTIVITY', '', ''
        FROM win_db.browser_history;
    )";
    sqlite3_exec(eventDb_, importBrowserSql, nullptr, nullptr, nullptr);

    // Import browser downloads
    const char* importDownloadsSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT start_time, 'WEB_DOWNLOAD', url, 0, 'File: ' || file_name || ' Size: ' || file_size, file_size, 'FILE', '', 'LOW', 'INFO', 'WEB_BROWSER', 'USER_ACTIVITY', '', ''
        FROM win_db.browser_downloads;
    )";
    sqlite3_exec(eventDb_, importDownloadsSql, nullptr, nullptr, nullptr);

    // Import browser logins
    const char* importLoginsSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT last_used_time, 'WEB_LOGIN', origin_url, 0, 'User: ' || username, 0, 'SECURITY', '', 'HIGH', 'WARNING', 'WEB_BROWSER', 'SECURITY_EVENT', '', ''
        FROM win_db.browser_logins;
    )";
    sqlite3_exec(eventDb_, importLoginsSql, nullptr, nullptr, nullptr);

    // Import Windows services
    const char* importServicesSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT 0, 'WINDOWS_SERVICE', service_name, 0, 'Service: ' || display_name || ' State: ' || service_state, 0, 'SYSTEM', '', 'MEDIUM', 'INFO', 'SYSTEM', 'SYSTEM_ACTIVITY', '', ''
        FROM win_db.windows_services;
    )";
    sqlite3_exec(eventDb_, importServicesSql, nullptr, nullptr, nullptr);

    // Import scheduled tasks
    const char* importTasksSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT 0, 'SCHEDULED_TASK', task_path, 0, 'Task: ' || task_name || ' Action: ' || action_path, 0, 'SYSTEM', '', 'MEDIUM', 'INFO', 'SYSTEM', 'SYSTEM_ACTIVITY', '', ''
        FROM win_db.scheduled_tasks;
    )";
    sqlite3_exec(eventDb_, importTasksSql, nullptr, nullptr, nullptr);

    // Import prefetch files
    const char* importPrefetchSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT last_executed_time, 'PREFETCH_EXECUTION', file_path, 0, 'Executable: ' || executable_name || ' Run count: ' || run_count, file_size, 'SYSTEM', '', 'MEDIUM', 'INFO', 'SYSTEM', 'APPLICATION_EVENT', '', ''
        FROM win_db.prefetch_info;
    )";
    sqlite3_exec(eventDb_, importPrefetchSql, nullptr, nullptr, nullptr);

    // Import USB devices
    const char* importUSBSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT first_insert_time, 'USB_DEVICE_CONNECT', device_id, 0, 'Device: ' || device_name || ' Serial: ' || serial_number, 0, 'HARDWARE', '', 'MEDIUM', 'INFO', 'SYSTEM', 'HARDWARE_EVENT', '', ''
        FROM win_db.usb_devices;
    )";
    sqlite3_exec(eventDb_, importUSBSql, nullptr, nullptr, nullptr);

    // Import recycle bin entries
    const char* importRecycleBinSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT deletion_time, 'FILE_DELETED', original_path, 0, 'Deleted file: ' || original_name, file_size, 'FILE', '', 'HIGH', 'WARNING', 'FILE_SYSTEM', 'FILE_OPERATION', '', ''
        FROM win_db.recycle_bin_entries;
    )";
    sqlite3_exec(eventDb_, importRecycleBinSql, nullptr, nullptr, nullptr);

    // Import Amcache entries
    const char* importAmcacheSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT last_modified_time, 'AMCACHE_ENTRY', file_path, 0, 'File: ' || file_name || ' SHA1: ' || sha1_hash, file_size, 'FILE', '', 'MEDIUM', 'INFO', 'SYSTEM', 'FILE_OPERATION', '', ''
        FROM win_db.amcache_entries;
    )";
    sqlite3_exec(eventDb_, importAmcacheSql, nullptr, nullptr, nullptr);

    sqlite3_exec(eventDb_, "DETACH DATABASE win_db;", nullptr, nullptr, nullptr);
    
    // 标准化导入的事件
    standardizeEvents();
    
    return true;
}

bool EventExtractor::importLinuxArtifacts(const std::string& linuxDbPath) {
    AuditLog::instance().log("SYSTEM", "TIMELINE_MERGE", "Importing Linux artifacts from: " + linuxDbPath);
    std::string attachSql = "ATTACH DATABASE '" + linuxDbPath + "' AS lin_db;";
    sqlite3_exec(eventDb_, attachSql.c_str(), nullptr, nullptr, nullptr);

    // Import system logs
    const char* importSyslogSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT unix_timestamp, 'LINUX_SYSLOG', log_file, 0, process || ': ' || message, 0, 'LOG', '', 'LOW', 'INFO', 'LINUX_SYSLOG', 'SYSTEM_ACTIVITY', '', ''
        FROM lin_db.linux_log_entries;
    )";
    sqlite3_exec(eventDb_, importSyslogSql, nullptr, nullptr, nullptr);

    // Import login records
    const char* importLoginSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT login_time, CASE WHEN is_success = 1 THEN 'LOGIN_SUCCESS' ELSE 'LOGIN_FAILURE' END, remote_host, 0, 'User: ' || username || ' Terminal: ' || terminal || ' Type: ' || login_type, 0, 'SECURITY', '', 'HIGH', 'INFO', 'LINUX_SYSLOG', 'USER_ACTIVITY', '', ''
        FROM lin_db.linux_login_records;
    )";
    sqlite3_exec(eventDb_, importLoginSql, nullptr, nullptr, nullptr);

    // Import shell history
    const char* importShellHistorySql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT timestamp, 'SHELL_COMMAND', history_file, 0, 'User: ' || username || ' Shell: ' || shell_type || ' Command: ' || command, 0, 'SYSTEM', '', 'LOW', 'INFO', 'LINUX_SYSLOG', 'USER_ACTIVITY', '', ''
        FROM lin_db.linux_shell_history;
    )";
    sqlite3_exec(eventDb_, importShellHistorySql, nullptr, nullptr, nullptr);

    // Import cron jobs
    const char* importCronSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT 0, 'CRON_JOB', cron_file, 0, 'User: ' || username || ' Command: ' || command || ' Schedule: ' || minute || ' ' || hour || ' ' || day_of_month || ' ' || month || ' ' || day_of_week, 0, 'SYSTEM', '', 'MEDIUM', 'INFO', 'LINUX_SYSLOG', 'SYSTEM_ACTIVITY', '', ''
        FROM lin_db.linux_cron_jobs;
    )";
    sqlite3_exec(eventDb_, importCronSql, nullptr, nullptr, nullptr);

    // Import SSH keys
    const char* importSSHKeysSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT 0, 'SSH_KEY', key_path, 0, 'User: ' || username || ' Type: ' || key_type || ' Comment: ' || comment, 0, 'SECURITY', '', 'HIGH', 'INFO', 'LINUX_SYSLOG', 'SECURITY_EVENT', '', ''
        FROM lin_db.linux_ssh_keys;
    )";
    sqlite3_exec(eventDb_, importSSHKeysSql, nullptr, nullptr, nullptr);

    // Import package installations
    const char* importPackagesSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT install_time, 'PACKAGE_INSTALL', '', 0, 'Package: ' || name || ' Version: ' || version || ' Manager: ' || package_manager, 0, 'SYSTEM', '', 'MEDIUM', 'INFO', 'LINUX_SYSLOG', 'SYSTEM_ACTIVITY', '', ''
        FROM lin_db.linux_packages;
    )";
    sqlite3_exec(eventDb_, importPackagesSql, nullptr, nullptr, nullptr);

    // Import network connections
    const char* importNetworkSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT 0, 'NETWORK_CONNECTION', '', 0, 'Process: ' || process || ' Protocol: ' || protocol || ' Local: ' || local_address || ':' || local_port || ' Remote: ' || remote_address || ':' || remote_port || ' State: ' || state, 0, 'NETWORK', '', 'MEDIUM', 'INFO', 'LINUX_SYSLOG', 'NETWORK_ACTIVITY', '', ''
        FROM lin_db.linux_network_connections;
    )";
    sqlite3_exec(eventDb_, importNetworkSql, nullptr, nullptr, nullptr);

    // Import systemd services
    const char* importSystemdSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT 0, 'SYSTEMD_SERVICE', unit_file, 0, 'Service: ' || service_name || ' Description: ' || description || ' State: ' || active_state || '/' || sub_state, 0, 'SYSTEM', '', 'MEDIUM', 'INFO', 'LINUX_SYSLOG', 'SYSTEM_ACTIVITY', '', ''
        FROM lin_db.linux_systemd_services;
    )";
    sqlite3_exec(eventDb_, importSystemdSql, nullptr, nullptr, nullptr);

    // Import audit logs
    const char* importAuditSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT timestamp, 'AUDIT_LOG', '', 0, 'Type: ' || type || ' Subject: ' || subject || ' Action: ' || action || ' Result: ' || result || ' Message: ' || message, 0, 'SECURITY', '', 'HIGH', 'INFO', 'LINUX_SYSLOG', 'SECURITY_EVENT', '', ''
        FROM lin_db.linux_audit_logs;
    )";
    sqlite3_exec(eventDb_, importAuditSql, nullptr, nullptr, nullptr);

    sqlite3_exec(eventDb_, "DETACH DATABASE lin_db;", nullptr, nullptr, nullptr);
    
    // 标准化导入的事件
    standardizeEvents();
    
    return true;
}

bool EventExtractor::importAndroidArtifacts(const std::string& androidDbPath) {
    AuditLog::instance().log("SYSTEM", "TIMELINE_MERGE", "Importing Android artifacts from: " + androidDbPath);
    std::string attachSql = "ATTACH DATABASE '" + androidDbPath + "' AS android_db;";
    sqlite3_exec(eventDb_, attachSql.c_str(), nullptr, nullptr, nullptr);

    const char* importSystemLogsSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
        SELECT timestamp, 'ANDROID_LOG', log_file, 0, process || '[' || pid || ']' || ': ' || message, 0, 'LOG', '', 'LOW', 'INFO', 'ANDROID_LOG', 'SYSTEM_ACTIVITY', '', ''
        FROM android_db.system_logs;
    )";
    sqlite3_exec(eventDb_, importSystemLogsSql, nullptr, nullptr, nullptr);

    sqlite3_exec(eventDb_, "DETACH DATABASE android_db;", nullptr, nullptr, nullptr);
    
    // 标准化导入的事件
    standardizeEvents();
    
    return true;
}

bool EventExtractor::insertSystemEvent(const SystemEvent& event) {
    using namespace EventExtractorSQL;
    
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, INSERT_SYSTEM_EVENT, -1, &stmt, nullptr);
    
    if (rc != SQLITE_OK) {
        return false;
    }
    
    sqlite3_bind_int64(stmt, 1, event.timestamp);
    sqlite3_bind_text(stmt, 2, event.eventType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, event.source.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, event.user.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, event.process.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, event.ipAddress.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 7, event.port);
    sqlite3_bind_text(stmt, 8, event.service.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, event.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, event.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 11, event.systemContext.c_str(), -1, SQLITE_TRANSIENT);
    
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    return rc == SQLITE_DONE;
}

bool EventExtractor::extractSystemEvents() {
    AuditLog::instance().log("SYSTEM", "SYSTEM_EVENT_EXTRACTION_START", "Starting system event extraction");
    
    int systemEventCount = 0;
    
    // Extract system events from platform-specific sources
    // This would involve parsing Windows Event Logs, Linux syslog, Android logcat, etc.
    // For now, we focus on extracting system events that may already be in the source database
    
    // Check if there are any platform-specific event tables
    const char* checkTablesSql = R"(
        SELECT name FROM sqlite_master WHERE type='table' 
        AND (name LIKE '%event%' OR name LIKE '%log%' OR name LIKE '%syslog%' OR name LIKE '%audit%')
    )";
    
    sqlite3_stmt* checkStmt;
    int rc = sqlite3_prepare_v2(sourceDb_, checkTablesSql, -1, &checkStmt, nullptr);
    if (rc == SQLITE_OK) {
        std::vector<std::string> platformTables;
        while (sqlite3_step(checkStmt) == SQLITE_ROW) {
            const char* tableName = reinterpret_cast<const char*>(sqlite3_column_text(checkStmt, 0));
            if (tableName) {
                platformTables.push_back(tableName);
            }
        }
        sqlite3_finalize(checkStmt);
        
        // Extract events from platform-specific tables
        for (const auto& tableName : platformTables) {
            std::string query = "SELECT * FROM " + tableName + " LIMIT 10000";
            sqlite3_stmt* extractStmt;
            rc = sqlite3_prepare_v2(sourceDb_, query.c_str(), -1, &extractStmt, nullptr);
            if (rc == SQLITE_OK) {
                int columnCount = sqlite3_column_count(extractStmt);
                
                // Begin transaction for better performance
                sqlite3_exec(eventDb_, "BEGIN TRANSACTION;", nullptr, nullptr, nullptr);
                
                while (sqlite3_step(extractStmt) == SQLITE_ROW) {
                    // Extract event data from the row
                    // This is a simplified extraction that would need to be customized
                    // based on the actual table structure
                    SystemEvent sysEvent;
                    sysEvent.timestamp = sqlite3_column_int64(extractStmt, 0);
                    sysEvent.eventType = "SYSTEM_EVENT";
                    sysEvent.source = tableName;
                    sysEvent.user = "";
                    sysEvent.process = "";
                    sysEvent.ipAddress = "";
                    sysEvent.port = 0;
                    sysEvent.service = "";
                    sysEvent.description = "System event from " + tableName;
                    sysEvent.severity = "INFO";
                    sysEvent.systemContext = "";
                    
                    if (insertSystemEvent(sysEvent)) {
                        systemEventCount++;
                    }
                }
                
                // Commit transaction
                sqlite3_exec(eventDb_, "COMMIT;", nullptr, nullptr, nullptr);
                sqlite3_finalize(extractStmt);
            }
        }
    }
    
    // Additionally, we can create system events from file system events
    // This converts certain file operations into system events
    const char* convertToSystemEventsSql = R"(
        SELECT timestamp, file_path, inode, file_size, file_type
        FROM files
        WHERE type = 'REG' AND (file_path LIKE '%/etc/%' OR file_path LIKE '%/system32/%' OR file_path LIKE '%/System/%')
    )";
    
    sqlite3_stmt* convertStmt;
    rc = sqlite3_prepare_v2(sourceDb_, convertToSystemEventsSql, -1, &convertStmt, nullptr);
    if (rc == SQLITE_OK) {
        // Begin transaction
        sqlite3_exec(eventDb_, "BEGIN TRANSACTION;", nullptr, nullptr, nullptr);
        
        while (sqlite3_step(convertStmt) == SQLITE_ROW) {
            SystemEvent sysEvent;
            sysEvent.timestamp = sqlite3_column_int64(convertStmt, 0);
            sysEvent.eventType = "SYSTEM_FILE_ACCESS";
            const char* path = reinterpret_cast<const char*>(sqlite3_column_text(convertStmt, 1));
            sysEvent.source = path ? path : "";
            sysEvent.user = "";
            sysEvent.process = "";
            sysEvent.ipAddress = "";
            sysEvent.port = 0;
            sysEvent.service = "filesystem";
            sysEvent.description = std::string("System file access: ") + (path ? path : "");
            sysEvent.severity = "INFO";
            sysEvent.systemContext = "";
            
            if (insertSystemEvent(sysEvent)) {
                systemEventCount++;
            }
        }
        
        // Commit transaction
        sqlite3_exec(eventDb_, "COMMIT;", nullptr, nullptr, nullptr);
        sqlite3_finalize(convertStmt);
    }
    
    AuditLog::instance().log("SYSTEM", "SYSTEM_EVENT_EXTRACTION_COMPLETE", "System event extraction completed. Total events: " + std::to_string(systemEventCount));
    
    return true;
}

bool EventExtractor::insertEventCorrelation(const EventCorrelation& correlation) {
    using namespace EventExtractorSQL;
    
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, INSERT_EVENT_CORRELATION, -1, &stmt, nullptr);
    
    if (rc != SQLITE_OK) {
        return false;
    }
    
    sqlite3_bind_int64(stmt, 1, correlation.eventId1);
    sqlite3_bind_int64(stmt, 2, correlation.eventId2);
    sqlite3_bind_text(stmt, 3, correlation.correlationType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_double(stmt, 4, correlation.confidence);
    sqlite3_bind_text(stmt, 5, correlation.description.c_str(), -1, SQLITE_TRANSIENT);
    
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    return rc == SQLITE_DONE;
}

bool EventExtractor::analyzeEventCorrelations() {
    AuditLog::instance().log("SYSTEM", "EVENT_CORRELATION_START", "Starting event correlation analysis");
    
    // 创建事件关联规则引擎
    EventCorrelationEngine::EventCorrelationEngine engine(eventDbPath_);
    
    // 初始化引擎
    if (!engine.initialize()) {
        std::cerr << "Failed to initialize event correlation engine" << std::endl;
        return false;
    }
    
    // 执行关联分析
    if (!engine.analyzeCorrelations()) {
        std::cerr << "Failed to analyze correlations" << std::endl;
        return false;
    }
    
    // 执行事件链分析
    auto chains = engine.analyzeEventChains();
    
    // 发现因果关系
    auto causalRelationships = engine.discoverCausalRelationships();
    
    // 导出结果
    engine.exportCorrelations(eventDbPath_ + "_correlations.json");
    engine.exportEventChains(eventDbPath_ + "_event_chains.json");
    engine.exportCausalRelationships(eventDbPath_ + "_causal_relationships.json");
    
    // 生成可视化
    std::string correlationsDot = engine.visualizeCorrelations();
    std::string eventChainsDot = engine.visualizeEventChains();
    std::string causalRelationshipsDot = engine.visualizeCausalRelationships();
    
    // 保存可视化结果
    std::ofstream corrDotFile(eventDbPath_ + "_correlations.dot");
    corrDotFile << correlationsDot;
    corrDotFile.close();
    
    std::ofstream chainsDotFile(eventDbPath_ + "_event_chains.dot");
    chainsDotFile << eventChainsDot;
    chainsDotFile.close();
    
    std::ofstream causalDotFile(eventDbPath_ + "_causal_relationships.dot");
    causalDotFile << causalRelationshipsDot;
    causalDotFile.close();
    
    AuditLog::instance().log("SYSTEM", "EVENT_CORRELATION_COMPLETE", "Event correlation analysis completed");
    return true;
}

void EventExtractor::closeDatabases() {
	if (sourceDb_) sqlite3_close(sourceDb_);
	if (eventDb_) sqlite3_close(eventDb_);
}

// 标准化事件类型
std::string EventExtractor::normalizeEventType(const std::string& eventType) {
    // 标准化文件系统事件
    if (eventType == "CREATED") return "FILE_CREATED";
    if (eventType == "MODIFIED") return "FILE_MODIFIED";
    if (eventType == "ACCESSED") return "FILE_ACCESSED";
    if (eventType == "CHANGED") return "FILE_METADATA_CHANGED";
    if (eventType == "DELETED") return "FILE_DELETED";
    if (eventType == "FILE_DELETED") return "FILE_DELETED";
    
    // 标准化Windows事件
    if (eventType.find("WIN_LOG_") == 0) return "WINDOWS_EVENT";
    if (eventType == "WEB_HISTORY") return "WEB_BROWSER_ACTIVITY";
    if (eventType == "WEB_DOWNLOAD") return "WEB_BROWSER_DOWNLOAD";
    if (eventType == "WEB_LOGIN") return "WEB_BROWSER_LOGIN";
    if (eventType == "WINDOWS_SERVICE") return "WINDOWS_SERVICE";
    if (eventType == "SCHEDULED_TASK") return "SCHEDULED_TASK";
    if (eventType == "PREFETCH_EXECUTION") return "PROCESS_EXECUTION";
    if (eventType == "USB_DEVICE_CONNECT") return "HARDWARE_CONNECTION";
    if (eventType == "AMCACHE_ENTRY") return "FILE_METADATA";
    
    // 标准化Linux事件
    if (eventType == "LINUX_SYSLOG") return "LINUX_SYSTEM_LOG";
    if (eventType == "LOGIN_SUCCESS") return "USER_LOGIN_SUCCESS";
    if (eventType == "LOGIN_FAILURE") return "USER_LOGIN_FAILURE";
    if (eventType == "SHELL_COMMAND") return "SHELL_EXECUTION";
    if (eventType == "CRON_JOB") return "SCHEDULED_TASK";
    if (eventType == "SSH_KEY") return "SECURITY_KEY";
    if (eventType == "PACKAGE_INSTALL") return "SOFTWARE_INSTALL";
    if (eventType == "NETWORK_CONNECTION") return "NETWORK_CONNECTION";
    if (eventType == "SYSTEMD_SERVICE") return "SYSTEM_SERVICE";
    if (eventType == "AUDIT_LOG") return "SECURITY_AUDIT";
    
    // 标准化Android事件
    if (eventType == "ANDROID_LOG") return "ANDROID_SYSTEM_LOG";
    
    // 标准化系统事件
    if (eventType == "SYSTEM_START") return "SYSTEM_STARTUP";
    if (eventType == "LOGIN") return "USER_LOGIN";
    if (eventType == "PROCESS_CREATE") return "PROCESS_CREATED";
    if (eventType == "SECURITY_EVENT") return "SECURITY_ALERT";
    if (eventType == "SERVICE_START") return "SERVICE_STARTED";
    
    return "UNKNOWN_EVENT";
}

// 获取事件来源ID
std::string EventExtractor::getSourceId(const TimelineEvent& event) {
    // 基于事件类型和文件路径生成唯一ID
    if (event.source == EventSource::FILE_SYSTEM) {
        return "FS_" + std::to_string(event.inode);
    } else if (event.source == EventSource::WINDOWS_EVENT_LOG) {
        return "WIN_LOG_" + event.eventType;
    } else if (event.source == EventSource::LINUX_SYSLOG) {
        return "LINUX_LOG_" + event.eventType;
    } else if (event.source == EventSource::ANDROID_LOG) {
        return "ANDROID_LOG_" + event.eventType;
    } else if (event.source == EventSource::WEB_BROWSER) {
        return "WEB_" + event.filePath.substr(0, 32);
    } else {
        return "SYS_" + event.eventType;
    }
}

// 检测是否为安全事件
bool EventExtractor::isSecurityEvent(const TimelineEvent& event) {
    // 检查事件类型
    if (event.eventType.find("SECURITY") != std::string::npos) return true;
    if (event.eventType.find("AUTH") != std::string::npos) return true;
    if (event.eventType.find("LOGIN") != std::string::npos) return true;
    if (event.eventType.find("FAIL") != std::string::npos) return true;
    
    // 检查描述内容
    std::string desc = event.description;
    if (desc.find("security") != std::string::npos) return true;
    if (desc.find("authentication") != std::string::npos) return true;
    if (desc.find("password") != std::string::npos) return true;
    if (desc.find("access denied") != std::string::npos) return true;
    if (desc.find("privilege") != std::string::npos) return true;
    
    return false;
}

// 检测是否为可疑活动
bool EventExtractor::isSuspiciousActivity(const TimelineEvent& event) {
    // 检查文件路径
    std::string path = event.filePath;
    if (path.find("/tmp/") != std::string::npos) return true;
    if (path.find("/var/tmp/") != std::string::npos) return true;
    if (path.find("/proc/") != std::string::npos) return true;
    if (path.find("/sys/") != std::string::npos) return true;
    
    // 检查文件类型
    std::string type = event.fileType;
    if (type == "executable") return true;
    if (type == "script") return true;
    
    // 检查描述内容
    std::string desc = event.description;
    if (desc.find("error") != std::string::npos) return true;
    if (desc.find("fail") != std::string::npos) return true;
    if (desc.find("warning") != std::string::npos) return true;
    if (desc.find("suspicious") != std::string::npos) return true;
    
    return false;
}

// 标准化单个事件
TimelineEvent EventExtractor::standardizeEvent(const TimelineEvent& event) {
    TimelineEvent standardizedEvent = event;
    
    // 识别事件来源
    standardizedEvent.source = identifySource(event);
    
    // 分类事件
    standardizedEvent.category = classifyEvent(event);
    
    // 评估优先级
    standardizedEvent.priority = assessPriority(event);
    
    // 评估严重程度
    standardizedEvent.severity = assessSeverity(event);
    
    // 标准化事件类型
    standardizedEvent.normalizedType = normalizeEventType(event.eventType);
    
    // 生成来源ID
    standardizedEvent.sourceId = getSourceId(standardizedEvent);
    
    return standardizedEvent;
}

// 标准化所有事件
bool EventExtractor::standardizeEvents() {
    AuditLog::instance().log("SYSTEM", "EVENT_STANDARDIZATION_START", "Starting event standardization");
    
    // 开始事务
    sqlite3_exec(eventDb_, "BEGIN TRANSACTION;", nullptr, nullptr, nullptr);
    
    // 查询所有未标准化的事件
    const char* query = R"(
        SELECT id, timestamp, event_type, file_path, inode, description, file_size, file_type, system_context
        FROM events
        WHERE normalized_type IS NULL OR normalized_type = ''
    )";
    
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, query, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        return false;
    }
    
    int processedCount = 0;
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        // 读取事件数据
        int64_t id = sqlite3_column_int64(stmt, 0);
        int64_t timestamp = sqlite3_column_int64(stmt, 1);
        const char* eventType_raw = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        std::string eventType = eventType_raw ? eventType_raw : "";
        const char* filePath_raw = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        std::string filePath = filePath_raw ? filePath_raw : "";
        int64_t inode = sqlite3_column_int64(stmt, 4);
        const char* description_raw = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
        std::string description = description_raw ? description_raw : "";
        int64_t fileSize = sqlite3_column_int64(stmt, 6);
        const char* fileType_raw = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        std::string fileType = fileType_raw ? fileType_raw : "";
        const char* systemContext_raw = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
        std::string systemContext = systemContext_raw ? systemContext_raw : "";
        
        // 创建事件对象
        TimelineEvent event;
        event.timestamp = timestamp;
        event.eventType = eventType;
        event.filePath = filePath;
        event.inode = inode;
        event.description = description;
        event.fileSize = fileSize;
        event.fileType = fileType;
        event.systemContext = systemContext;
        
        // 标准化事件
        TimelineEvent standardizedEvent = standardizeEvent(event);
        
        // 更新数据库
        const char* updateSql = R"(
            UPDATE events SET 
                priority = ?, 
                severity = ?, 
                event_source = ?, 
                event_category = ?, 
                normalized_type = ?, 
                source_id = ?
            WHERE id = ?
        )";
        
        sqlite3_stmt* updateStmt;
        sqlite3_prepare_v2(eventDb_, updateSql, -1, &updateStmt, nullptr);
        sqlite3_bind_text(updateStmt, 1, priorityToString(standardizedEvent.priority).c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(updateStmt, 2, severityToString(standardizedEvent.severity).c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(updateStmt, 3, sourceToString(standardizedEvent.source).c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(updateStmt, 4, categoryToString(standardizedEvent.category).c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(updateStmt, 5, standardizedEvent.normalizedType.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(updateStmt, 6, standardizedEvent.sourceId.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_int64(updateStmt, 7, id);
        sqlite3_step(updateStmt);
        sqlite3_finalize(updateStmt);
        
        processedCount++;
    }
    
    sqlite3_finalize(stmt);
    
    // 提交事务
    sqlite3_exec(eventDb_, "COMMIT;", nullptr, nullptr, nullptr);
    
    std::cout << "Standardized " << processedCount << " events" << std::endl;
    AuditLog::instance().log("SYSTEM", "EVENT_STANDARDIZATION_COMPLETE", "Standardized " + std::to_string(processedCount) + " events");
    
    return true;
}

// 分类事件
EventCategory EventExtractor::classifyEvent(const TimelineEvent& event) {
    // 基于事件类型分类
    if (event.eventType == "CREATED" || event.eventType == "MODIFIED" || 
        event.eventType == "ACCESSED" || event.eventType == "CHANGED" || 
        event.eventType == "DELETED") {
        return EventCategory::FILE_OPERATION;
    }
    
    // 基于来源分类
    if (event.source == EventSource::SYSTEM) {
        return EventCategory::SYSTEM_ACTIVITY;
    }
    
    if (event.source == EventSource::NETWORK) {
        return EventCategory::NETWORK_ACTIVITY;
    }
    
    if (event.source == EventSource::SECURITY) {
        return EventCategory::SECURITY_EVENT;
    }
    
    if (event.source == EventSource::APPLICATION) {
        return EventCategory::APPLICATION_EVENT;
    }
    
    if (event.eventType.find("LOGIN") != std::string::npos || 
        event.eventType.find("USER") != std::string::npos) {
        return EventCategory::USER_ACTIVITY;
    }
    
    return EventCategory::UNKNOWN_CATEGORY;
}

// 评估事件优先级
EventPriority EventExtractor::assessPriority(const TimelineEvent& event) {
    // 基于事件类型
    if (event.eventType == "DELETED") return EventPriority::HIGH;
    if (event.eventType.find("SECURITY") != std::string::npos) return EventPriority::CRITICAL;
    if (event.eventType.find("ERROR") != std::string::npos) return EventPriority::HIGH;
    if (event.eventType.find("WARNING") != std::string::npos) return EventPriority::MEDIUM;
    
    // 基于文件类型
    if (event.fileType == "executable") return EventPriority::HIGH;
    if (event.fileType == "database") return EventPriority::MEDIUM;
    if (event.fileType == "system") return EventPriority::HIGH;
    
    // 基于文件大小
    if (event.fileSize > 100 * 1024 * 1024) return EventPriority::MEDIUM; // 大于100MB
    
    // 基于来源
    if (event.source == EventSource::SECURITY) return EventPriority::CRITICAL;
    if (event.source == EventSource::NETWORK) return EventPriority::MEDIUM;
    
    // 基于可疑活动
    if (isSuspiciousActivity(event)) return EventPriority::HIGH;
    
    return EventPriority::LOW;
}

// 评估事件严重程度
EventSeverity EventExtractor::assessSeverity(const TimelineEvent& event) {
    // 基于事件类型
    if (event.eventType.find("ERROR") != std::string::npos) return EventSeverity::ERROR;
    if (event.eventType.find("CRITICAL") != std::string::npos) return EventSeverity::CRITICAL;
    if (event.eventType.find("WARNING") != std::string::npos) return EventSeverity::WARNING;
    
    // 基于安全事件
    if (isSecurityEvent(event)) return EventSeverity::CRITICAL;
    
    // 基于可疑活动
    if (isSuspiciousActivity(event)) return EventSeverity::WARNING;
    
    // 基于文件类型
    if (event.fileType == "executable" && event.eventType == "CREATED") return EventSeverity::WARNING;
    if (event.fileType == "system" && event.eventType == "DELETED") return EventSeverity::ERROR;
    
    return EventSeverity::INFO;
}

// 识别事件来源
EventSource EventExtractor::identifySource(const TimelineEvent& event) {
    // 基于事件类型识别
    if (event.eventType == "CREATED" || event.eventType == "MODIFIED" || 
        event.eventType == "ACCESSED" || event.eventType == "CHANGED" || 
        event.eventType == "DELETED" || event.eventType == "FILE_DELETED") {
        return EventSource::FILE_SYSTEM;
    }
    
    if (event.eventType.find("WIN_LOG_") == 0 || 
        event.eventType == "WINDOWS_SERVICE" || 
        event.eventType == "SCHEDULED_TASK" || 
        event.eventType == "PREFETCH_EXECUTION" || 
        event.eventType == "AMCACHE_ENTRY") {
        return EventSource::WINDOWS_EVENT_LOG;
    }
    
    if (event.eventType == "WEB_HISTORY" || 
        event.eventType == "WEB_DOWNLOAD" || 
        event.eventType == "WEB_LOGIN") {
        return EventSource::WEB_BROWSER;
    }
    
    if (event.eventType == "LINUX_SYSLOG" || 
        event.eventType == "LOGIN_SUCCESS" || 
        event.eventType == "LOGIN_FAILURE" || 
        event.eventType == "SHELL_COMMAND" || 
        event.eventType == "CRON_JOB" || 
        event.eventType == "SSH_KEY" || 
        event.eventType == "PACKAGE_INSTALL" || 
        event.eventType == "SYSTEMD_SERVICE" || 
        event.eventType == "AUDIT_LOG") {
        return EventSource::LINUX_SYSLOG;
    }
    
    if (event.eventType == "ANDROID_LOG") {
        return EventSource::ANDROID_LOG;
    }
    
    if (event.eventType == "SYSTEM_START" || event.eventType == "SERVICE_START") {
        return EventSource::SYSTEM;
    }
    
    if (event.eventType == "NETWORK_CONNECT") {
        return EventSource::NETWORK;
    }
    
    if (event.eventType == "SECURITY_EVENT" || event.eventType == "WEB_LOGIN" || 
        event.eventType == "SSH_KEY" || event.eventType == "AUDIT_LOG") {
        return EventSource::SECURITY;
    }
    
    if (event.eventType == "PROCESS_CREATE" || event.eventType == "PREFETCH_EXECUTION" || 
        event.eventType == "SHELL_COMMAND") {
        return EventSource::APPLICATION;
    }
    
    if (event.eventType == "USB_DEVICE_CONNECT") {
        return EventSource::SYSTEM;
    }
    
    return EventSource::UNKNOWN;
}