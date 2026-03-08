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

	std::cout << "Events extracted successfully" << std::endl;
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

    // Create indices
    sqlite3_exec(eventDb_, CREATE_EVENT_INDICES, nullptr, nullptr, nullptr);

    // Create views
    sqlite3_exec(eventDb_, CREATE_TIMELINE_VIEW, nullptr, nullptr, nullptr);
    sqlite3_exec(eventDb_, CREATE_STATISTICS_VIEW, nullptr, nullptr, nullptr);
    sqlite3_exec(eventDb_, CREATE_HOURLY_ACTIVITY_VIEW, nullptr, nullptr, nullptr);

    return true;
}

bool EventExtractor::extractFileSystemEvents() {
	const char* query = R"(
        SELECT inode, path, atime, mtime, ctime, crtime, type, size, is_deleted
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

bool EventExtractor::insertEvent(const TimelineEvent& event) {
	const char* sql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    )";

	sqlite3_stmt* stmt;
	int rc = sqlite3_prepare_v2(eventDb_, sql, -1, &stmt, nullptr);

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

	rc = sqlite3_step(stmt);
	sqlite3_finalize(stmt);

	return rc == SQLITE_DONE;
}

bool EventExtractor::importWindowsArtifacts(const std::string& windowsDbPath) {
    AuditLog::instance().log("SYSTEM", "TIMELINE_MERGE", "Importing Windows artifacts from: " + windowsDbPath);
    std::string attachSql = "ATTACH DATABASE '" + windowsDbPath + "' AS win_db;";
    sqlite3_exec(eventDb_, attachSql.c_str(), nullptr, nullptr, nullptr);

    const char* importLogsSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type)
        SELECT timestamp, 'WIN_LOG_' || COALESCE(level, 'UNK'), log_source, 0, 'ID:' || event_id || ' ' || message, 0, 'LOG'
        FROM win_db.event_logs;
    )";
    sqlite3_exec(eventDb_, importLogsSql, nullptr, nullptr, nullptr);

    const char* importBrowserSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type)
        SELECT visit_time, 'WEB_HISTORY', url, 0, 'Title: ' || title, 0, 'WEB'
        FROM win_db.browser_history;
    )";
    sqlite3_exec(eventDb_, importBrowserSql, nullptr, nullptr, nullptr);

    sqlite3_exec(eventDb_, "DETACH DATABASE win_db;", nullptr, nullptr, nullptr);
    return true;
}

bool EventExtractor::importLinuxArtifacts(const std::string& linuxDbPath) {
    AuditLog::instance().log("SYSTEM", "TIMELINE_MERGE", "Importing Linux artifacts from: " + linuxDbPath);
    std::string attachSql = "ATTACH DATABASE '" + linuxDbPath + "' AS lin_db;";
    sqlite3_exec(eventDb_, attachSql.c_str(), nullptr, nullptr, nullptr);

    const char* importSyslogSql = R"(
        INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type)
        SELECT unix_timestamp, 'LINUX_SYSLOG', log_file, 0, process || ': ' || message, 0, 'LOG'
        FROM lin_db.linux_log_entries;
    )";
    sqlite3_exec(eventDb_, importSyslogSql, nullptr, nullptr, nullptr);

    sqlite3_exec(eventDb_, "DETACH DATABASE lin_db;", nullptr, nullptr, nullptr);
    return true;
}

void EventExtractor::closeDatabases() {
	if (sourceDb_) sqlite3_close(sourceDb_);
	if (eventDb_) sqlite3_close(eventDb_);
}