#include "../EventExtractor.h"
#include "DatabaseManager/SQL/event_extractor_sql.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <sstream>
#include <sqlite3.h>
#include <algorithm>

// Enum to string conversion functions
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

		// One prepared statement per table for the whole scan. Preparing and
		// finalizing per file re-parses the schema each time, which on the
		// spinning extraction disk costs more than the inserts themselves.
		auto prepare = [&](const char* sql) {
			sqlite3_stmt* prepared = nullptr;
			sqlite3_prepare_v2(eventDb_, sql, -1, &prepared, nullptr);
			return prepared;
		};
		sqlite3_stmt* creationInsert = prepare(
			"INSERT INTO creation_events (timestamp, file_path, inode, file_size, file_type) VALUES (?, ?, ?, ?, ?);");
		sqlite3_stmt* modificationInsert = prepare(
			"INSERT INTO modification_events (timestamp, file_path, inode, file_size, file_type) VALUES (?, ?, ?, ?, ?);");
		sqlite3_stmt* accessInsert = prepare(
			"INSERT INTO access_events (timestamp, file_path, inode, file_size, file_type) VALUES (?, ?, ?, ?, ?);");
		sqlite3_stmt* changeInsert = prepare(
			"INSERT INTO change_events (timestamp, file_path, inode, file_size, file_type, description) VALUES (?, ?, ?, ?, ?, ?);");
		sqlite3_stmt* deletionInsert = prepare(
			"INSERT INTO deletion_events (timestamp, file_path, inode, file_size, file_type) VALUES (?, ?, ?, ?, ?);");
		sqlite3_stmt* eventInsert = prepare(EventExtractorSQL::INSERT_EVENT);

		auto bindAndStepEvent = [](sqlite3_stmt* insert, const TimelineEvent& event) {
			sqlite3_reset(insert);
			sqlite3_clear_bindings(insert);
			sqlite3_bind_int64(insert, 1, event.timestamp);
			sqlite3_bind_text(insert, 2, event.eventType.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_text(insert, 3, event.filePath.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_int64(insert, 4, event.inode);
			sqlite3_bind_text(insert, 5, event.description.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_int64(insert, 6, event.fileSize);
			sqlite3_bind_text(insert, 7, event.fileType.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_text(insert, 8, event.systemContext.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_text(insert, 9, priorityToString(event.priority).c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_text(insert, 10, severityToString(event.severity).c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_text(insert, 11, sourceToString(event.source).c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_text(insert, 12, categoryToString(event.category).c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_text(insert, 13, event.normalizedType.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_text(insert, 14, event.sourceId.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_step(insert);
		};

		auto bindSubtype = [](sqlite3_stmt* insert, int64_t ts, const std::string& filePath,
		                      int64_t fileInode, int64_t fileSize, const std::string& fileType) {
			sqlite3_reset(insert);
			sqlite3_clear_bindings(insert);
			sqlite3_bind_int64(insert, 1, ts);
			sqlite3_bind_text(insert, 2, filePath.c_str(), -1, SQLITE_TRANSIENT);
			sqlite3_bind_int64(insert, 3, fileInode);
			sqlite3_bind_int64(insert, 4, fileSize);
			sqlite3_bind_text(insert, 5, fileType.c_str(), -1, SQLITE_TRANSIENT);
		};

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
				bindAndStepEvent(eventInsert, createBaseEvent(crtime, "CREATED", "File created"));
				bindSubtype(creationInsert, crtime, path, inode, size, type);
				sqlite3_step(creationInsert);
				eventCount++;
				creationCount++;
			}

			// Create event for file modification
			if (mtime > 0 && mtime != crtime) {
				bindAndStepEvent(eventInsert, createBaseEvent(mtime, "MODIFIED", "File content modified"));
				bindSubtype(modificationInsert, mtime, path, inode, size, type);
				sqlite3_step(modificationInsert);
				eventCount++;
				modificationCount++;
			}

			// Create event for file access
			if (atime > 0 && atime != mtime && atime != crtime) {
				bindAndStepEvent(eventInsert, createBaseEvent(atime, "ACCESSED", "File accessed/read"));
				bindSubtype(accessInsert, atime, path, inode, size, type);
				sqlite3_step(accessInsert);
				eventCount++;
				accessCount++;
			}

			// Create event for metadata change
			if (ctime > 0 && ctime != mtime && ctime != crtime) {
				bindAndStepEvent(eventInsert, createBaseEvent(ctime, "CHANGED", "Metadata changed"));
				bindSubtype(changeInsert, ctime, path, inode, size, type);
				sqlite3_bind_text(changeInsert, 6, "Metadata changed", -1, SQLITE_TRANSIENT);
				sqlite3_step(changeInsert);
				eventCount++;
				changeCount++;
			}

			// Create event for deleted files
			if (isDeleted) {
				int64_t deletionTime = std::max({ atime, mtime, ctime, crtime });
				bindAndStepEvent(eventInsert, createBaseEvent(deletionTime, "DELETED", "File deleted (unallocated)"));
				bindSubtype(deletionInsert, deletionTime, path, inode, size, type);
				sqlite3_step(deletionInsert);
				eventCount++;
				deletionCount++;
			}
		}

		sqlite3_finalize(stmt);
		for (sqlite3_stmt* prepared : {creationInsert, modificationInsert, accessInsert,
		                               changeInsert, deletionInsert, eventInsert}) {
			sqlite3_finalize(prepared);
		}

	// Commit transaction
	sqlite3_exec(eventDb_, "COMMIT;", nullptr, nullptr, nullptr);

	std::cout << "  Total events: " << eventCount << std::endl;
	return true;
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
