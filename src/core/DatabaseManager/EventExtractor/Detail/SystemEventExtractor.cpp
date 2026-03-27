#include "../EventExtractor.h"
#include "DatabaseManager/SQL/event_extractor_sql.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <sstream>
#include <sqlite3.h>
#include <algorithm>

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
