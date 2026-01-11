// LinuxAnalysisDatabase.cpp
// Implementation of LinuxAnalysisDatabase

#include "LinuxAnalysisDatabase.h"
#include "LinuxQueryBuilder.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include <iostream>
#include <sstream>
#include <mutex>

using namespace LinuxAnalysis;

LinuxAnalysisDatabase::LinuxAnalysisDatabase(const std::string& dbPath)
    : dbPath_(dbPath), db_(nullptr), lastError_() {
}

LinuxAnalysisDatabase::~LinuxAnalysisDatabase() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (db_) {
        sqlite3_close(db_);
        db_ = nullptr;
    }
}

bool LinuxAnalysisDatabase::initialize() {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    
    int rc = sqlite3_open(dbPath_.c_str(), &db_);
    if (rc != SQLITE_OK) {
        setError(ErrorCode::DATABASE_OPEN_FAILED, sqlite3_errmsg(db_));
        std::cerr << "Cannot open database: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }
    return createTables();
}

bool LinuxAnalysisDatabase::createTables() {
    using namespace LinuxAnalysisSQL;
    
    // Execute all create statements
    if (!executeSQL(CREATE_LOG_ENTRIES_TABLE) ||
        !executeSQL(CREATE_USERS_TABLE) ||
        !executeSQL(CREATE_GROUPS_TABLE) ||
        !executeSQL(CREATE_LOGIN_RECORDS_TABLE) ||
        !executeSQL(CREATE_SHELL_HISTORY_TABLE) ||
        !executeSQL(CREATE_CRON_JOBS_TABLE) ||
        !executeSQL(CREATE_SSH_KEYS_TABLE) ||
        !executeSQL(CREATE_SSH_KNOWN_HOSTS_TABLE) ||
        !executeSQL(CREATE_PACKAGES_TABLE) ||
        !executeSQL(CREATE_NETWORK_CONNECTIONS_TABLE) ||
        !executeSQL(CREATE_SYSTEMD_SERVICES_TABLE) ||
        !executeSQL(CREATE_KERNEL_MODULES_TABLE) ||
        !executeSQL(CREATE_FIREWALL_RULES_TABLE) ||
        !executeSQL(CREATE_AUDIT_LOGS_TABLE) ||
        !executeSQL(CREATE_BROWSER_PROFILES_TABLE)) {
        setError(ErrorCode::DATABASE_CREATE_TABLE_FAILED);
        return false;
    }
    return true;
}

bool LinuxAnalysisDatabase::executeSQL(const std::string& sql) {
    char* errMsg = nullptr;
    int rc = sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::string errorStr = errMsg ? errMsg : "Unknown SQL error";
        std::cerr << "SQL error: " << errorStr << std::endl;
        sqlite3_free(errMsg);
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, errorStr);
        return false;
    }
    return true;
}

// Error handling helpers
void LinuxAnalysisDatabase::setError(ErrorCode code, const std::string& details) {
    lastError_ = LinuxAnalyzerError(code, details);
}

void LinuxAnalysisDatabase::setError(const LinuxAnalyzerError& error) {
    lastError_ = error;
}

LinuxAnalyzerError LinuxAnalysisDatabase::getSQLiteError(ErrorCode code) const {
    const char* errMsg = sqlite3_errmsg(db_);
    return LinuxAnalyzerError(code, errMsg ? errMsg : "Unknown SQLite error");
}

bool LinuxAnalysisDatabase::beginTransaction() {
    std::lock_guard<std::mutex> lock(mutex_);
    return executeSQL("BEGIN TRANSACTION");
}

bool LinuxAnalysisDatabase::commitTransaction() {
    std::lock_guard<std::mutex> lock(mutex_);
    return executeSQL("COMMIT");
}

bool LinuxAnalysisDatabase::rollbackTransaction() {
    std::lock_guard<std::mutex> lock(mutex_);
    return executeSQL("ROLLBACK");
}

// Helper macros for binding
#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)

// ============================================================================
// Log Entry Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertLogEntry(const LinuxLogEntry& entry) {
    const char* sql = LinuxAnalysisSQL::INSERT_LOG_ENTRY;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, entry.logFile);
    BIND_TEXT(stmt, 2, entry.timestamp);
    BIND_INT64(stmt, 3, entry.unixTimestamp);
    BIND_TEXT(stmt, 4, entry.hostname);
    BIND_TEXT(stmt, 5, entry.process);
    BIND_INT(stmt, 6, entry.pid);
    BIND_TEXT(stmt, 7, entry.message);
    BIND_TEXT(stmt, 8, entry.level);
    BIND_TEXT(stmt, 9, entry.facility);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertLogEntries(const std::vector<LinuxLogEntry>& entries) {
    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertLogEntry(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<LinuxLogEntry> LinuxAnalysisDatabase::queryLogEntries(const std::string& whereClause) {
    std::vector<LinuxLogEntry> entries;
    std::string sql = "SELECT log_file, timestamp, unix_timestamp, hostname, process, pid, message, level, facility FROM linux_log_entries";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return entries;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxLogEntry entry;
        entry.logFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        entry.timestamp = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        entry.unixTimestamp = sqlite3_column_int64(stmt, 2);
        entry.hostname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        entry.process = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        entry.pid = sqlite3_column_int(stmt, 5);
        entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        entry.level = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        entry.facility = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8) ?: (const unsigned char*)"");
        entries.push_back(entry);
    }
    
    sqlite3_finalize(stmt);
    return entries;
}

// ============================================================================
// User Account Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertUserInfo(const LinuxUserInfo& user) {
    const char* sql = LinuxAnalysisSQL::INSERT_USER_INFO;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, user.username);
    BIND_INT(stmt, 2, user.uid);
    BIND_INT(stmt, 3, user.gid);
    BIND_TEXT(stmt, 4, user.fullName);
    BIND_TEXT(stmt, 5, user.homeDirectory);
    BIND_TEXT(stmt, 6, user.shell);
    BIND_TEXT(stmt, 7, user.passwordHash);
    BIND_INT64(stmt, 8, user.lastPasswordChange);
    BIND_INT(stmt, 9, user.passwordMaxAge);
    BIND_INT(stmt, 10, user.passwordMinAge);
    BIND_INT(stmt, 11, user.passwordWarnDays);
    BIND_INT(stmt, 12, user.inactiveDays);
    BIND_INT64(stmt, 13, user.accountExpires);
    BIND_INT(stmt, 14, user.isLocked ? 1 : 0);
    BIND_INT(stmt, 15, user.isSystemAccount ? 1 : 0);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertUserInfos(const std::vector<LinuxUserInfo>& users) {
    beginTransaction();
    for (const auto& user : users) {
        if (!insertUserInfo(user)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<LinuxUserInfo> LinuxAnalysisDatabase::queryUserAccounts(const std::string& whereClause) {
    std::vector<LinuxUserInfo> users;
    std::string sql = "SELECT username, uid, gid, full_name, home_directory, shell, password_hash, "
                      "last_password_change, password_max_age, password_min_age, password_warn_days, "
                      "inactive_days, account_expires, is_locked, is_system_account FROM linux_users";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return users;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxUserInfo user;
        user.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        user.uid = sqlite3_column_int(stmt, 1);
        user.gid = sqlite3_column_int(stmt, 2);
        user.fullName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        user.homeDirectory = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        user.shell = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        user.passwordHash = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        user.lastPasswordChange = sqlite3_column_int64(stmt, 7);
        user.passwordMaxAge = sqlite3_column_int(stmt, 8);
        user.passwordMinAge = sqlite3_column_int(stmt, 9);
        user.passwordWarnDays = sqlite3_column_int(stmt, 10);
        user.inactiveDays = sqlite3_column_int(stmt, 11);
        user.accountExpires = sqlite3_column_int64(stmt, 12);
        user.isLocked = sqlite3_column_int(stmt, 13) != 0;
        user.isSystemAccount = sqlite3_column_int(stmt, 14) != 0;
        users.push_back(user);
    }
    
    sqlite3_finalize(stmt);
    return users;
}

// ============================================================================
// Group Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertGroupInfo(const LinuxGroupInfo& group) {
    const char* sql = LinuxAnalysisSQL::INSERT_GROUP_INFO;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, group.groupName);
    BIND_INT(stmt, 2, group.gid);
    
    // Join members with comma
    std::string membersStr;
    for (size_t i = 0; i < group.members.size(); ++i) {
        if (i > 0) membersStr += ",";
        membersStr += group.members[i];
    }
    BIND_TEXT(stmt, 3, membersStr);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

std::vector<LinuxGroupInfo> LinuxAnalysisDatabase::queryGroups(const std::string& whereClause) {
    std::vector<LinuxGroupInfo> groups;
    std::string sql = "SELECT group_name, gid, members FROM linux_groups";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return groups;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxGroupInfo group;
        group.groupName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        group.gid = sqlite3_column_int(stmt, 1);
        std::string membersStr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        // Parse comma-separated members
        std::istringstream ss(membersStr);
        std::string member;
        while (std::getline(ss, member, ',')) {
            if (!member.empty()) group.members.push_back(member);
        }
        groups.push_back(group);
    }
    
    sqlite3_finalize(stmt);
    return groups;
}

// ============================================================================
// Login Record Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertLoginRecord(const LinuxLoginRecord& record) {
    const char* sql = LinuxAnalysisSQL::INSERT_LOGIN_RECORD;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, record.username);
    BIND_TEXT(stmt, 2, record.terminal);
    BIND_TEXT(stmt, 3, record.remoteHost);
    BIND_INT64(stmt, 4, record.loginTime);
    BIND_INT64(stmt, 5, record.logoutTime);
    BIND_TEXT(stmt, 6, record.loginType);
    BIND_INT(stmt, 7, record.isSuccess ? 1 : 0);
    BIND_INT(stmt, 8, record.pid);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertLoginRecords(const std::vector<LinuxLoginRecord>& records) {
    beginTransaction();
    for (const auto& record : records) {
        if (!insertLoginRecord(record)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<LinuxLoginRecord> LinuxAnalysisDatabase::queryLoginRecords(const std::string& whereClause) {
    std::vector<LinuxLoginRecord> records;
    std::string sql = "SELECT username, terminal, remote_host, login_time, logout_time, login_type, is_success, pid FROM linux_login_records";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return records;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxLoginRecord record;
        record.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        record.terminal = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        record.remoteHost = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        record.loginTime = sqlite3_column_int64(stmt, 3);
        record.logoutTime = sqlite3_column_int64(stmt, 4);
        record.loginType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        record.isSuccess = sqlite3_column_int(stmt, 6) != 0;
        record.pid = sqlite3_column_int(stmt, 7);
        records.push_back(record);
    }
    
    sqlite3_finalize(stmt);
    return records;
}

// ============================================================================
// Shell History Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertShellHistory(const ShellHistoryEntry& entry) {
    const char* sql = LinuxAnalysisSQL::INSERT_SHELL_HISTORY;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, entry.username);
    BIND_TEXT(stmt, 2, entry.shellType);
    BIND_TEXT(stmt, 3, entry.command);
    BIND_INT64(stmt, 4, entry.timestamp);
    BIND_INT(stmt, 5, entry.lineNumber);
    BIND_TEXT(stmt, 6, entry.historyFile);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertShellHistories(const std::vector<ShellHistoryEntry>& entries) {
    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertShellHistory(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<ShellHistoryEntry> LinuxAnalysisDatabase::queryShellHistory(const std::string& whereClause) {
    std::vector<ShellHistoryEntry> entries;
    std::string sql = "SELECT username, shell_type, command, timestamp, line_number, history_file FROM linux_shell_history";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return entries;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        ShellHistoryEntry entry;
        entry.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        entry.shellType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        entry.command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        entry.timestamp = sqlite3_column_int64(stmt, 3);
        entry.lineNumber = sqlite3_column_int(stmt, 4);
        entry.historyFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        entries.push_back(entry);
    }
    
    sqlite3_finalize(stmt);
    return entries;
}

// ============================================================================
// Cron Job Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertCronJob(const CronJobEntry& job) {
    const char* sql = LinuxAnalysisSQL::INSERT_CRON_JOB;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, job.username);
    BIND_TEXT(stmt, 2, job.minute);
    BIND_TEXT(stmt, 3, job.hour);
    BIND_TEXT(stmt, 4, job.dayOfMonth);
    BIND_TEXT(stmt, 5, job.month);
    BIND_TEXT(stmt, 6, job.dayOfWeek);
    BIND_TEXT(stmt, 7, job.command);
    BIND_TEXT(stmt, 8, job.cronFile);
    BIND_TEXT(stmt, 9, job.cronType);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertCronJobs(const std::vector<CronJobEntry>& jobs) {
    beginTransaction();
    for (const auto& job : jobs) {
        if (!insertCronJob(job)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<CronJobEntry> LinuxAnalysisDatabase::queryCronJobs(const std::string& whereClause) {
    std::vector<CronJobEntry> jobs;
    std::string sql = "SELECT username, minute, hour, day_of_month, month, day_of_week, command, cron_file, cron_type FROM linux_cron_jobs";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return jobs;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        CronJobEntry job;
        job.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        job.minute = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        job.hour = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        job.dayOfMonth = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        job.month = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        job.dayOfWeek = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        job.command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        job.cronFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        job.cronType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8) ?: (const unsigned char*)"");
        jobs.push_back(job);
    }
    
    sqlite3_finalize(stmt);
    return jobs;
}

// ============================================================================
// SSH Key Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSSHKey(const SSHKeyInfo& key) {
    const char* sql = LinuxAnalysisSQL::INSERT_SSH_KEY;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, key.username);
    BIND_TEXT(stmt, 2, key.keyType);
    BIND_TEXT(stmt, 3, key.publicKey);
    BIND_TEXT(stmt, 4, key.keyPath);
    BIND_TEXT(stmt, 5, key.comment);
    BIND_TEXT(stmt, 6, key.options);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertSSHKeys(const std::vector<SSHKeyInfo>& keys) {
    beginTransaction();
    for (const auto& key : keys) {
        if (!insertSSHKey(key)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<SSHKeyInfo> LinuxAnalysisDatabase::querySSHKeys(const std::string& whereClause) {
    std::vector<SSHKeyInfo> keys;
    std::string sql = "SELECT username, key_type, public_key, key_path, comment, options FROM linux_ssh_keys";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return keys;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SSHKeyInfo key;
        key.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        key.keyType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        key.publicKey = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        key.keyPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        key.comment = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        key.options = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        keys.push_back(key);
    }
    
    sqlite3_finalize(stmt);
    return keys;
}

// ============================================================================
// SSH Known Host Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSSHKnownHost(const SSHKnownHost& host) {
    const char* sql = LinuxAnalysisSQL::INSERT_SSH_KNOWN_HOST;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, host.username);
    BIND_TEXT(stmt, 2, host.hostname);
    BIND_TEXT(stmt, 3, host.keyType);
    BIND_TEXT(stmt, 4, host.publicKey);
    BIND_INT(stmt, 5, host.isHashed ? 1 : 0);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

std::vector<SSHKnownHost> LinuxAnalysisDatabase::querySSHKnownHosts(const std::string& whereClause) {
    std::vector<SSHKnownHost> hosts;
    std::string sql = "SELECT username, hostname, key_type, public_key, is_hashed FROM linux_ssh_known_hosts";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return hosts;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SSHKnownHost host;
        host.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        host.hostname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        host.keyType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        host.publicKey = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        host.isHashed = sqlite3_column_int(stmt, 4) != 0;
        hosts.push_back(host);
    }
    
    sqlite3_finalize(stmt);
    return hosts;
}

// ============================================================================
// Package Info Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertPackageInfo(const PackageInfo& pkg) {
    const char* sql = LinuxAnalysisSQL::INSERT_PACKAGE_INFO;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, pkg.name);
    BIND_TEXT(stmt, 2, pkg.version);
    BIND_TEXT(stmt, 3, pkg.architecture);
    BIND_INT64(stmt, 4, pkg.installTime);
    BIND_TEXT(stmt, 5, pkg.packageManager);
    BIND_TEXT(stmt, 6, pkg.status);
    BIND_TEXT(stmt, 7, pkg.description);
    BIND_TEXT(stmt, 8, pkg.maintainer);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertPackageInfos(const std::vector<PackageInfo>& pkgs) {
    beginTransaction();
    for (const auto& pkg : pkgs) {
        if (!insertPackageInfo(pkg)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<PackageInfo> LinuxAnalysisDatabase::queryPackages(const std::string& whereClause) {
    std::vector<PackageInfo> packages;
    std::string sql = "SELECT name, version, architecture, install_time, package_manager, status, description, maintainer FROM linux_packages";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return packages;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        PackageInfo pkg;
        pkg.name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        pkg.version = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        pkg.architecture = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        pkg.installTime = sqlite3_column_int64(stmt, 3);
        pkg.packageManager = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        pkg.status = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        pkg.description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        pkg.maintainer = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        packages.push_back(pkg);
    }
    
    sqlite3_finalize(stmt);
    return packages;
}

// ============================================================================
// Network Connection Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertNetworkConnection(const NetworkConnection& conn) {
    const char* sql = LinuxAnalysisSQL::INSERT_NETWORK_CONNECTION;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, conn.protocol);
    BIND_TEXT(stmt, 2, conn.localAddress);
    BIND_INT(stmt, 3, conn.localPort);
    BIND_TEXT(stmt, 4, conn.remoteAddress);
    BIND_INT(stmt, 5, conn.remotePort);
    BIND_TEXT(stmt, 6, conn.state);
    BIND_INT(stmt, 7, conn.uid);
    BIND_INT(stmt, 8, conn.inode);
    BIND_TEXT(stmt, 9, conn.process);
    BIND_INT(stmt, 10, conn.pid);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

std::vector<NetworkConnection> LinuxAnalysisDatabase::queryNetworkConnections(const std::string& whereClause) {
    std::vector<NetworkConnection> conns;
    std::string sql = "SELECT protocol, local_address, local_port, remote_address, remote_port, state, uid, inode, process, pid FROM linux_network_connections";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return conns;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        NetworkConnection conn;
        conn.protocol = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        conn.localAddress = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        conn.localPort = sqlite3_column_int(stmt, 2);
        conn.remoteAddress = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        conn.remotePort = sqlite3_column_int(stmt, 4);
        conn.state = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        conn.uid = sqlite3_column_int(stmt, 6);
        conn.inode = sqlite3_column_int(stmt, 7);
        conn.process = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8) ?: (const unsigned char*)"");
        conn.pid = sqlite3_column_int(stmt, 9);
        conns.push_back(conn);
    }
    
    sqlite3_finalize(stmt);
    return conns;
}

// ============================================================================
// Systemd Service Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSystemdService(const SystemdServiceInfo& service) {
    const char* sql = LinuxAnalysisSQL::INSERT_SYSTEMD_SERVICE;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, service.serviceName);
    BIND_TEXT(stmt, 2, service.description);
    BIND_TEXT(stmt, 3, service.loadState);
    BIND_TEXT(stmt, 4, service.activeState);
    BIND_TEXT(stmt, 5, service.subState);
    BIND_TEXT(stmt, 6, service.unitFile);
    BIND_TEXT(stmt, 7, service.execStart);
    BIND_TEXT(stmt, 8, service.user);
    BIND_INT(stmt, 9, service.isEnabled ? 1 : 0);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

std::vector<SystemdServiceInfo> LinuxAnalysisDatabase::querySystemdServices(const std::string& whereClause) {
    std::vector<SystemdServiceInfo> services;
    std::string sql = "SELECT service_name, description, load_state, active_state, sub_state, unit_file, exec_start, user, is_enabled FROM linux_systemd_services";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return services;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SystemdServiceInfo service;
        service.serviceName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        service.description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        service.loadState = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        service.activeState = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        service.subState = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        service.unitFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        service.execStart = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        service.user = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        service.isEnabled = sqlite3_column_int(stmt, 8) != 0;
        services.push_back(service);
    }
    
    sqlite3_finalize(stmt);
    return services;
}

// ============================================================================
// Kernel Module Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertKernelModule(const KernelModuleInfo& module) {
    const char* sql = LinuxAnalysisSQL::INSERT_KERNEL_MODULE;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, module.moduleName);
    BIND_INT64(stmt, 2, module.size);
    BIND_INT(stmt, 3, module.usedCount);
    
    // Join usedBy modules with comma
    std::string usedByStr;
    for (size_t i = 0; i < module.usedBy.size(); ++i) {
        if (i > 0) usedByStr += ",";
        usedByStr += module.usedBy[i];
    }
    BIND_TEXT(stmt, 4, usedByStr);
    BIND_TEXT(stmt, 5, module.state);
    BIND_TEXT(stmt, 6, module.filename);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

std::vector<KernelModuleInfo> LinuxAnalysisDatabase::queryKernelModules(const std::string& whereClause) {
    std::vector<KernelModuleInfo> modules;
    std::string sql = "SELECT module_name, size, used_count, used_by, state, filename FROM linux_kernel_modules";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return modules;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        KernelModuleInfo module;
        module.moduleName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        module.size = sqlite3_column_int64(stmt, 1);
        module.usedCount = sqlite3_column_int(stmt, 2);
        std::string usedByStr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        std::istringstream ss(usedByStr);
        std::string mod;
        while (std::getline(ss, mod, ',')) {
            if (!mod.empty()) module.usedBy.push_back(mod);
        }
        module.state = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        module.filename = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        modules.push_back(module);
    }
    
    sqlite3_finalize(stmt);
    return modules;
}

// ============================================================================
// Firewall Rule Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertFirewallRule(const FirewallRule& rule) {
    const char* sql = LinuxAnalysisSQL::INSERT_FIREWALL_RULE;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_TEXT(stmt, 1, rule.chain);
    BIND_TEXT(stmt, 2, rule.table);
    BIND_TEXT(stmt, 3, rule.protocol);
    BIND_TEXT(stmt, 4, rule.source);
    BIND_TEXT(stmt, 5, rule.destination);
    BIND_INT(stmt, 6, rule.sourcePort);
    BIND_INT(stmt, 7, rule.destinationPort);
    BIND_TEXT(stmt, 8, rule.action);
    BIND_TEXT(stmt, 9, rule.ruleSpec);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

std::vector<FirewallRule> LinuxAnalysisDatabase::queryFirewallRules(const std::string& whereClause) {
    std::vector<FirewallRule> rules;
    std::string sql = "SELECT chain, table_name, protocol, source, destination, source_port, destination_port, action, rule_spec FROM linux_firewall_rules";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return rules;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FirewallRule rule;
        rule.chain = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        rule.table = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        rule.protocol = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        rule.source = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        rule.destination = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        rule.sourcePort = sqlite3_column_int(stmt, 5);
        rule.destinationPort = sqlite3_column_int(stmt, 6);
        rule.action = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        rule.ruleSpec = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8) ?: (const unsigned char*)"");
        rules.push_back(rule);
    }
    
    sqlite3_finalize(stmt);
    return rules;
}

// ============================================================================
// Audit Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertAuditLog(const LinuxAuditLogEntry& entry) {
    const char* sql = LinuxAnalysisSQL::INSERT_AUDIT_LOG;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_INT64(stmt, 1, entry.timestamp);
    BIND_INT(stmt, 2, entry.serialNumber);
    BIND_TEXT(stmt, 3, entry.type);
    BIND_TEXT(stmt, 4, entry.message);
    BIND_TEXT(stmt, 5, entry.subject);
    BIND_TEXT(stmt, 6, entry.object);
    BIND_TEXT(stmt, 7, entry.action);
    BIND_TEXT(stmt, 8, entry.result);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertAuditLogs(const std::vector<LinuxAuditLogEntry>& entries) {
    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertAuditLog(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<LinuxAuditLogEntry> LinuxAnalysisDatabase::queryAuditLogs(const std::string& whereClause) {
    std::vector<LinuxAuditLogEntry> entries;
    std::string sql = "SELECT timestamp, serial_number, type, message, subject, object, action, result FROM linux_audit_logs";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return entries;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxAuditLogEntry entry;
        entry.timestamp = sqlite3_column_int64(stmt, 0);
        entry.serialNumber = sqlite3_column_int(stmt, 1);
        entry.type = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        entry.subject = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        entry.object = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        entry.action = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        entry.result = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        entries.push_back(entry);
    }
    
    sqlite3_finalize(stmt);
    return entries;
}

// ============================================================================
// Browser Profile Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertBrowserProfile(const LinuxBrowserProfile& profile) {
    const char* sql = LinuxAnalysisSQL::INSERT_BROWSER_PROFILE;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    BIND_INT(stmt, 1, static_cast<int>(profile.browserType));
    BIND_TEXT(stmt, 2, profile.browserName);
    BIND_TEXT(stmt, 3, profile.profileName);
    BIND_TEXT(stmt, 4, profile.profilePath);
    BIND_TEXT(stmt, 5, profile.username);
    
    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

std::vector<LinuxBrowserProfile> LinuxAnalysisDatabase::queryBrowserProfiles(const std::string& whereClause) {
    std::vector<LinuxBrowserProfile> profiles;
    std::string sql = "SELECT browser_type, browser_name, profile_name, profile_path, username FROM linux_browser_profiles";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return profiles;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxBrowserProfile profile;
        profile.browserType = static_cast<LinuxBrowserType>(sqlite3_column_int(stmt, 0));
        profile.browserName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        profile.profileName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        profile.profilePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        profile.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        profiles.push_back(profile);
    }
    
    sqlite3_finalize(stmt);
    return profiles;
}

// ============================================================================
// Safe Query Methods (using QueryBuilder for SQL injection protection)
// ============================================================================

std::vector<LinuxLogEntry> LinuxAnalysisDatabase::queryLogEntriesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<LinuxLogEntry> entries;
    
    std::string sql = "SELECT log_file, timestamp, unix_timestamp, hostname, process, pid, message, level, facility FROM linux_log_entries";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return entries;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return entries;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxLogEntry entry;
        entry.logFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        entry.timestamp = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        entry.unixTimestamp = sqlite3_column_int64(stmt, 2);
        entry.hostname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        entry.process = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        entry.pid = sqlite3_column_int(stmt, 5);
        entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        entry.level = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        entry.facility = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8) ?: (const unsigned char*)"");
        entries.push_back(entry);
    }
    
    sqlite3_finalize(stmt);
    return entries;
}

std::vector<LinuxUserInfo> LinuxAnalysisDatabase::queryUserAccountsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<LinuxUserInfo> users;
    
    std::string sql = "SELECT username, uid, gid, full_name, home_directory, shell, password_hash, "
                      "last_password_change, password_max_age, password_min_age, password_warn_days, "
                      "inactive_days, account_expires, is_locked, is_system_account FROM linux_users";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return users;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return users;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxUserInfo user;
        user.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        user.uid = sqlite3_column_int(stmt, 1);
        user.gid = sqlite3_column_int(stmt, 2);
        user.fullName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        user.homeDirectory = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        user.shell = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        user.passwordHash = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        user.lastPasswordChange = sqlite3_column_int64(stmt, 7);
        user.passwordMaxAge = sqlite3_column_int(stmt, 8);
        user.passwordMinAge = sqlite3_column_int(stmt, 9);
        user.passwordWarnDays = sqlite3_column_int(stmt, 10);
        user.inactiveDays = sqlite3_column_int(stmt, 11);
        user.accountExpires = sqlite3_column_int64(stmt, 12);
        user.isLocked = sqlite3_column_int(stmt, 13) != 0;
        user.isSystemAccount = sqlite3_column_int(stmt, 14) != 0;
        users.push_back(user);
    }
    
    sqlite3_finalize(stmt);
    return users;
}

std::vector<LinuxGroupInfo> LinuxAnalysisDatabase::queryGroupsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<LinuxGroupInfo> groups;
    
    std::string sql = "SELECT group_name, gid, members FROM linux_groups";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return groups;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return groups;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxGroupInfo group;
        group.groupName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        group.gid = sqlite3_column_int(stmt, 1);
        std::string membersStr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        std::istringstream ss(membersStr);
        std::string member;
        while (std::getline(ss, member, ',')) {
            if (!member.empty()) group.members.push_back(member);
        }
        groups.push_back(group);
    }
    
    sqlite3_finalize(stmt);
    return groups;
}

std::vector<LinuxLoginRecord> LinuxAnalysisDatabase::queryLoginRecordsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<LinuxLoginRecord> records;
    
    std::string sql = "SELECT username, terminal, remote_host, login_time, logout_time, login_type, is_success, pid FROM linux_login_records";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return records;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return records;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxLoginRecord record;
        record.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        record.terminal = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        record.remoteHost = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        record.loginTime = sqlite3_column_int64(stmt, 3);
        record.logoutTime = sqlite3_column_int64(stmt, 4);
        record.loginType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        record.isSuccess = sqlite3_column_int(stmt, 6) != 0;
        record.pid = sqlite3_column_int(stmt, 7);
        records.push_back(record);
    }
    
    sqlite3_finalize(stmt);
    return records;
}

std::vector<ShellHistoryEntry> LinuxAnalysisDatabase::queryShellHistorySafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<ShellHistoryEntry> entries;
    
    std::string sql = "SELECT username, shell_type, command, timestamp, line_number, history_file FROM linux_shell_history";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return entries;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return entries;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        ShellHistoryEntry entry;
        entry.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        entry.shellType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        entry.command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        entry.timestamp = sqlite3_column_int64(stmt, 3);
        entry.lineNumber = sqlite3_column_int(stmt, 4);
        entry.historyFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        entries.push_back(entry);
    }
    
    sqlite3_finalize(stmt);
    return entries;
}

std::vector<CronJobEntry> LinuxAnalysisDatabase::queryCronJobsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<CronJobEntry> jobs;
    
    std::string sql = "SELECT username, minute, hour, day_of_month, month, day_of_week, command, cron_file, cron_type FROM linux_cron_jobs";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return jobs;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return jobs;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        CronJobEntry job;
        job.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        job.minute = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        job.hour = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        job.dayOfMonth = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        job.month = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        job.dayOfWeek = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        job.command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        job.cronFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        job.cronType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8) ?: (const unsigned char*)"");
        jobs.push_back(job);
    }
    
    sqlite3_finalize(stmt);
    return jobs;
}

std::vector<SSHKeyInfo> LinuxAnalysisDatabase::querySSHKeysSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<SSHKeyInfo> keys;
    
    std::string sql = "SELECT username, key_type, public_key, key_path, comment, options FROM linux_ssh_keys";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return keys;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return keys;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SSHKeyInfo key;
        key.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        key.keyType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        key.publicKey = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        key.keyPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        key.comment = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        key.options = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        keys.push_back(key);
    }
    
    sqlite3_finalize(stmt);
    return keys;
}

std::vector<SSHKnownHost> LinuxAnalysisDatabase::querySSHKnownHostsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<SSHKnownHost> hosts;
    
    std::string sql = "SELECT username, hostname, key_type, public_key, is_hashed FROM linux_ssh_known_hosts";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return hosts;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return hosts;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SSHKnownHost host;
        host.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        host.hostname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        host.keyType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        host.publicKey = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        host.isHashed = sqlite3_column_int(stmt, 4) != 0;
        hosts.push_back(host);
    }
    
    sqlite3_finalize(stmt);
    return hosts;
}

std::vector<PackageInfo> LinuxAnalysisDatabase::queryPackagesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<PackageInfo> packages;
    
    std::string sql = "SELECT name, version, architecture, install_time, package_manager, status, description, maintainer FROM linux_packages";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return packages;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return packages;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        PackageInfo pkg;
        pkg.name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        pkg.version = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        pkg.architecture = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        pkg.installTime = sqlite3_column_int64(stmt, 3);
        pkg.packageManager = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        pkg.status = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        pkg.description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        pkg.maintainer = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        packages.push_back(pkg);
    }
    
    sqlite3_finalize(stmt);
    return packages;
}

std::vector<NetworkConnection> LinuxAnalysisDatabase::queryNetworkConnectionsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<NetworkConnection> conns;
    
    std::string sql = "SELECT protocol, local_address, local_port, remote_address, remote_port, state, uid, inode, process, pid FROM linux_network_connections";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return conns;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return conns;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        NetworkConnection conn;
        conn.protocol = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        conn.localAddress = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        conn.localPort = sqlite3_column_int(stmt, 2);
        conn.remoteAddress = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        conn.remotePort = sqlite3_column_int(stmt, 4);
        conn.state = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        conn.uid = sqlite3_column_int(stmt, 6);
        conn.inode = sqlite3_column_int(stmt, 7);
        conn.process = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8) ?: (const unsigned char*)"");
        conn.pid = sqlite3_column_int(stmt, 9);
        conns.push_back(conn);
    }
    
    sqlite3_finalize(stmt);
    return conns;
}

std::vector<SystemdServiceInfo> LinuxAnalysisDatabase::querySystemdServicesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<SystemdServiceInfo> services;
    
    std::string sql = "SELECT service_name, description, load_state, active_state, sub_state, unit_file, exec_start, user, is_enabled FROM linux_systemd_services";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return services;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return services;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SystemdServiceInfo service;
        service.serviceName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        service.description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        service.loadState = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        service.activeState = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        service.subState = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        service.unitFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        service.execStart = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        service.user = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        service.isEnabled = sqlite3_column_int(stmt, 8) != 0;
        services.push_back(service);
    }
    
    sqlite3_finalize(stmt);
    return services;
}

std::vector<KernelModuleInfo> LinuxAnalysisDatabase::queryKernelModulesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<KernelModuleInfo> modules;
    
    std::string sql = "SELECT module_name, size, used_count, used_by, state, filename FROM linux_kernel_modules";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return modules;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return modules;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        KernelModuleInfo module;
        module.moduleName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        module.size = sqlite3_column_int64(stmt, 1);
        module.usedCount = sqlite3_column_int(stmt, 2);
        std::string usedByStr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        std::istringstream ss(usedByStr);
        std::string mod;
        while (std::getline(ss, mod, ',')) {
            if (!mod.empty()) module.usedBy.push_back(mod);
        }
        module.state = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        module.filename = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        modules.push_back(module);
    }
    
    sqlite3_finalize(stmt);
    return modules;
}

std::vector<FirewallRule> LinuxAnalysisDatabase::queryFirewallRulesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<FirewallRule> rules;
    
    std::string sql = "SELECT chain, table_name, protocol, source, destination, source_port, destination_port, action, rule_spec FROM linux_firewall_rules";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return rules;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return rules;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FirewallRule rule;
        rule.chain = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        rule.table = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        rule.protocol = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        rule.source = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        rule.destination = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        rule.sourcePort = sqlite3_column_int(stmt, 5);
        rule.destinationPort = sqlite3_column_int(stmt, 6);
        rule.action = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        rule.ruleSpec = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8) ?: (const unsigned char*)"");
        rules.push_back(rule);
    }
    
    sqlite3_finalize(stmt);
    return rules;
}

std::vector<LinuxAuditLogEntry> LinuxAnalysisDatabase::queryAuditLogsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<LinuxAuditLogEntry> entries;
    
    std::string sql = "SELECT timestamp, serial_number, type, message, subject, object, action, result FROM linux_audit_logs";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return entries;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return entries;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxAuditLogEntry entry;
        entry.timestamp = sqlite3_column_int64(stmt, 0);
        entry.serialNumber = sqlite3_column_int(stmt, 1);
        entry.type = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        entry.subject = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        entry.object = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        entry.action = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        entry.result = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        entries.push_back(entry);
    }
    
    sqlite3_finalize(stmt);
    return entries;
}

std::vector<LinuxBrowserProfile> LinuxAnalysisDatabase::queryBrowserProfilesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<LinuxBrowserProfile> profiles;
    
    std::string sql = "SELECT browser_type, browser_name, profile_name, profile_path, username FROM linux_browser_profiles";
    sql += qb.buildFullClause();
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return profiles;
    }
    
    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return profiles;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxBrowserProfile profile;
        profile.browserType = static_cast<LinuxBrowserType>(sqlite3_column_int(stmt, 0));
        profile.browserName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        profile.profileName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        profile.profilePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        profile.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        profiles.push_back(profile);
    }
    
    sqlite3_finalize(stmt);
    return profiles;
}
