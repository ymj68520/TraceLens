// LinuxUserOperations.cpp
// User, group, login, and SSH database operations

#include "LinuxAnalysisDatabase.h"
#include "LinuxQueryBuilder.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include <iostream>
#include <sstream>
#include <mutex>

using namespace LinuxAnalysis;

// Helper macros for binding
#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)

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
// Safe Query Methods (using QueryBuilder for SQL injection protection)
// ============================================================================

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
