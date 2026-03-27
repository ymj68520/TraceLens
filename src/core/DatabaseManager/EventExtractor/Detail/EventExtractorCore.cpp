#include "../EventExtractor.h"
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

        // Convert enums to strings
        std::string priority, severity, source, category;
        switch (standardizedEvent.priority) {
            case EventPriority::LOW: priority = "LOW"; break;
            case EventPriority::MEDIUM: priority = "MEDIUM"; break;
            case EventPriority::HIGH: priority = "HIGH"; break;
            case EventPriority::CRITICAL: priority = "CRITICAL"; break;
            default: priority = "UNKNOWN"; break;
        }

        switch (standardizedEvent.severity) {
            case EventSeverity::INFO: severity = "INFO"; break;
            case EventSeverity::WARNING: severity = "WARNING"; break;
            case EventSeverity::ERROR: severity = "ERROR"; break;
            case EventSeverity::CRITICAL: severity = "CRITICAL"; break;
            default: severity = "UNKNOWN"; break;
        }

        switch (standardizedEvent.source) {
            case EventSource::FILE_SYSTEM: source = "FILE_SYSTEM"; break;
            case EventSource::WINDOWS_EVENT_LOG: source = "WINDOWS_EVENT_LOG"; break;
            case EventSource::LINUX_SYSLOG: source = "LINUX_SYSLOG"; break;
            case EventSource::ANDROID_LOG: source = "ANDROID_LOG"; break;
            case EventSource::WEB_BROWSER: source = "WEB_BROWSER"; break;
            case EventSource::SYSTEM: source = "SYSTEM"; break;
            case EventSource::NETWORK: source = "NETWORK"; break;
            case EventSource::SECURITY: source = "SECURITY"; break;
            case EventSource::APPLICATION: source = "APPLICATION"; break;
            default: source = "UNKNOWN"; break;
        }

        switch (standardizedEvent.category) {
            case EventCategory::FILE_OPERATION: category = "FILE_OPERATION"; break;
            case EventCategory::SYSTEM_ACTIVITY: category = "SYSTEM_ACTIVITY"; break;
            case EventCategory::USER_ACTIVITY: category = "USER_ACTIVITY"; break;
            case EventCategory::NETWORK_ACTIVITY: category = "NETWORK_ACTIVITY"; break;
            case EventCategory::SECURITY_EVENT: category = "SECURITY_EVENT"; break;
            case EventCategory::APPLICATION_EVENT: category = "APPLICATION_EVENT"; break;
            case EventCategory::DATABASE_ACTIVITY: category = "DATABASE_ACTIVITY"; break;
            case EventCategory::HARDWARE_EVENT: category = "HARDWARE_EVENT"; break;
            case EventCategory::EXTERNAL_SOURCE: category = "EXTERNAL_SOURCE"; break;
            default: category = "UNKNOWN_CATEGORY"; break;
        }

        sqlite3_bind_text(updateStmt, 1, priority.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(updateStmt, 2, severity.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(updateStmt, 3, source.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(updateStmt, 4, category.c_str(), -1, SQLITE_TRANSIENT);
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

void EventExtractor::closeDatabases() {
	if (sourceDb_) sqlite3_close(sourceDb_);
	if (eventDb_) sqlite3_close(eventDb_);
}
