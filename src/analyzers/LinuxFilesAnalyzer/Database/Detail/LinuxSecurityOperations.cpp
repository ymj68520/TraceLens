// LinuxSecurityOperations.cpp
// Database operations for security posture analysis (setuid, capabilities, SELinux, AppArmor)

#include "LinuxAnalysisDatabase.h"
#include "LinuxQueryBuilder.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include "Detail/LinuxDatabaseHelpers.h"
#include <mutex>
#include <sys/stat.h>

using namespace LinuxAnalysis;

// ============================================================================
// Setuid File Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSetuidFile(const SetuidFileInfo& file) {
    const char* sql = LinuxAnalysisSQL::INSERT_SETUID_FILE;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, file.filePath);
    BIND_TEXT(stmt, 2, file.owner);
    BIND_TEXT(stmt, 3, file.groupName);
    BIND_INT(stmt, 4, file.permissions);
    BIND_INT(stmt, 5, file.isSetuid ? 1 : 0);
    BIND_INT(stmt, 6, file.isSetgid ? 1 : 0);
    BIND_INT64(stmt, 7, file.size);
    BIND_TEXT(stmt, 8, file.md5Hash);
    BIND_TEXT(stmt, 9, file.sha256Hash);
    BIND_INT(stmt, 10, file.isSuspicious ? 1 : 0);
    BIND_TEXT(stmt, 11, file.suspiciousReason);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertSetuidFiles(const std::vector<SetuidFileInfo>& files) {
    beginTransaction();
    for (const auto& file : files) {
        if (!insertSetuidFile(file)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<SetuidFileInfo> LinuxAnalysisDatabase::querySetuidFiles(const std::string& whereClause) {
    std::vector<SetuidFileInfo> files;
    std::string sql = "SELECT file_path, owner, group_name, permissions, is_setuid, is_setgid, size, md5_hash, sha256_hash, is_suspicious, suspicious_reason FROM linux_setuid_files";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return files;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SetuidFileInfo file;
        file.filePath = safeColumnText(stmt, 0);
        file.owner = safeColumnText(stmt, 1);
        file.groupName = safeColumnText(stmt, 2);
        file.permissions = static_cast<mode_t>(sqlite3_column_int(stmt, 3));
        file.isSetuid = sqlite3_column_int(stmt, 4) != 0;
        file.isSetgid = sqlite3_column_int(stmt, 5) != 0;
        file.size = sqlite3_column_int64(stmt, 6);
        file.md5Hash = safeColumnText(stmt, 7);
        file.sha256Hash = safeColumnText(stmt, 8);
        file.isSuspicious = sqlite3_column_int(stmt, 9) != 0;
        file.suspiciousReason = safeColumnText(stmt, 10);
        files.push_back(file);
    }

    return files;
}

std::vector<SetuidFileInfo> LinuxAnalysisDatabase::querySetuidFilesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<SetuidFileInfo> files;

    std::string sql = "SELECT file_path, owner, group_name, permissions, is_setuid, is_setgid, size, md5_hash, sha256_hash, is_suspicious, suspicious_reason FROM linux_setuid_files";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return files;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return files;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SetuidFileInfo file;
        file.filePath = safeColumnText(stmt, 0);
        file.owner = safeColumnText(stmt, 1);
        file.groupName = safeColumnText(stmt, 2);
        file.permissions = static_cast<mode_t>(sqlite3_column_int(stmt, 3));
        file.isSetuid = sqlite3_column_int(stmt, 4) != 0;
        file.isSetgid = sqlite3_column_int(stmt, 5) != 0;
        file.size = sqlite3_column_int64(stmt, 6);
        file.md5Hash = safeColumnText(stmt, 7);
        file.sha256Hash = safeColumnText(stmt, 8);
        file.isSuspicious = sqlite3_column_int(stmt, 9) != 0;
        file.suspiciousReason = safeColumnText(stmt, 10);
        files.push_back(file);
    }

    return files;
}

// ============================================================================
// File Capability Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertFileCapability(const FileCapability& capability) {
    const char* sql = LinuxAnalysisSQL::INSERT_FILE_CAPABILITY;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, capability.filePath);
    BIND_TEXT(stmt, 2, vectorToJson(capability.capabilities));
    BIND_TEXT(stmt, 3, capability.capabilitySet);
    BIND_INT(stmt, 4, capability.isInherited ? 1 : 0);
    BIND_INT(stmt, 5, capability.isSuspicious ? 1 : 0);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertFileCapabilities(const std::vector<FileCapability>& capabilities) {
    beginTransaction();
    for (const auto& capability : capabilities) {
        if (!insertFileCapability(capability)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<FileCapability> LinuxAnalysisDatabase::queryFileCapabilities(const std::string& whereClause) {
    std::vector<FileCapability> capabilities;
    std::string sql = "SELECT file_path, capabilities, capability_set, is_inherited, is_suspicious FROM linux_capabilities";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return capabilities;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileCapability capability;
        capability.filePath = safeColumnText(stmt, 0);
        capability.capabilities = jsonToVector<std::string>(safeColumnText(stmt, 1));
        capability.capabilitySet = safeColumnText(stmt, 2);
        capability.isInherited = sqlite3_column_int(stmt, 3) != 0;
        capability.isSuspicious = sqlite3_column_int(stmt, 4) != 0;
        capabilities.push_back(capability);
    }

    return capabilities;
}

std::vector<FileCapability> LinuxAnalysisDatabase::queryFileCapabilitiesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<FileCapability> capabilities;

    std::string sql = "SELECT file_path, capabilities, capability_set, is_inherited, is_suspicious FROM linux_capabilities";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return capabilities;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return capabilities;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileCapability capability;
        capability.filePath = safeColumnText(stmt, 0);
        capability.capabilities = jsonToVector<std::string>(safeColumnText(stmt, 1));
        capability.capabilitySet = safeColumnText(stmt, 2);
        capability.isInherited = sqlite3_column_int(stmt, 3) != 0;
        capability.isSuspicious = sqlite3_column_int(stmt, 4) != 0;
        capabilities.push_back(capability);
    }

    return capabilities;
}

// ============================================================================
// SELinux Status Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSELinuxStatus(const SELinuxStatus& status) {
    const char* sql = LinuxAnalysisSQL::INSERT_SELINUX_STATUS;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT(stmt, 1, status.isEnabled ? 1 : 0);
    BIND_TEXT(stmt, 2, status.mode);
    BIND_TEXT(stmt, 3, status.policyName);
    BIND_TEXT(stmt, 4, status.currentMode);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

std::vector<SELinuxStatus> LinuxAnalysisDatabase::querySELinuxStatus(const std::string& whereClause) {
    std::vector<SELinuxStatus> statuses;
    std::string sql = "SELECT is_enabled, mode, policy_name, current_mode FROM linux_selinux_status";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return statuses;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SELinuxStatus status;
        status.isEnabled = sqlite3_column_int(stmt, 0) != 0;
        status.mode = safeColumnText(stmt, 1);
        status.policyName = safeColumnText(stmt, 2);
        status.currentMode = safeColumnText(stmt, 3);
        statuses.push_back(status);
    }

    return statuses;
}

std::vector<SELinuxStatus> LinuxAnalysisDatabase::querySELinuxStatusSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<SELinuxStatus> statuses;

    std::string sql = "SELECT is_enabled, mode, policy_name, current_mode FROM linux_selinux_status";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return statuses;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return statuses;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SELinuxStatus status;
        status.isEnabled = sqlite3_column_int(stmt, 0) != 0;
        status.mode = safeColumnText(stmt, 1);
        status.policyName = safeColumnText(stmt, 2);
        status.currentMode = safeColumnText(stmt, 3);
        statuses.push_back(status);
    }

    return statuses;
}

// ============================================================================
// SELinux AVC Denial Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSELinuxAVCDenial(const SELinuxAVCDenial& denial) {
    const char* sql = LinuxAnalysisSQL::INSERT_SELINUX_AVC_DENIAL;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT64(stmt, 1, denial.timestamp);
    BIND_TEXT(stmt, 2, denial.sourceContext);
    BIND_TEXT(stmt, 3, denial.targetContext);
    BIND_TEXT(stmt, 4, denial.objectClass);
    BIND_TEXT(stmt, 5, denial.permission);
    BIND_TEXT(stmt, 6, denial.executablePath);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertSELinuxAVCDenials(const std::vector<SELinuxAVCDenial>& denials) {
    beginTransaction();
    for (const auto& denial : denials) {
        if (!insertSELinuxAVCDenial(denial)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<SELinuxAVCDenial> LinuxAnalysisDatabase::querySELinuxAVCDenials(const std::string& whereClause) {
    std::vector<SELinuxAVCDenial> denials;
    std::string sql = "SELECT timestamp, source_context, target_context, object_class, permission, executable_path FROM linux_selinux_avc_denials";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return denials;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SELinuxAVCDenial denial;
        denial.timestamp = sqlite3_column_int64(stmt, 0);
        denial.sourceContext = safeColumnText(stmt, 1);
        denial.targetContext = safeColumnText(stmt, 2);
        denial.objectClass = safeColumnText(stmt, 3);
        denial.permission = safeColumnText(stmt, 4);
        denial.executablePath = safeColumnText(stmt, 5);
        denials.push_back(denial);
    }

    return denials;
}

std::vector<SELinuxAVCDenial> LinuxAnalysisDatabase::querySELinuxAVCDenialsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<SELinuxAVCDenial> denials;

    std::string sql = "SELECT timestamp, source_context, target_context, object_class, permission, executable_path FROM linux_selinux_avc_denials";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return denials;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return denials;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SELinuxAVCDenial denial;
        denial.timestamp = sqlite3_column_int64(stmt, 0);
        denial.sourceContext = safeColumnText(stmt, 1);
        denial.targetContext = safeColumnText(stmt, 2);
        denial.objectClass = safeColumnText(stmt, 3);
        denial.permission = safeColumnText(stmt, 4);
        denial.executablePath = safeColumnText(stmt, 5);
        denials.push_back(denial);
    }

    return denials;
}

// ============================================================================
// AppArmor Profile Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertAppArmorProfile(const AppArmorProfile& profile) {
    const char* sql = LinuxAnalysisSQL::INSERT_APPARMOR_PROFILE;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, profile.profileName);
    BIND_TEXT(stmt, 2, profile.mode);
    BIND_TEXT(stmt, 3, profile.filePath);
    BIND_TEXT(stmt, 4, vectorToJson(profile.allowedPaths));
    BIND_TEXT(stmt, 5, vectorToJson(profile.deniedPaths));
    BIND_INT(stmt, 6, profile.isEnabled ? 1 : 0);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertAppArmorProfiles(const std::vector<AppArmorProfile>& profiles) {
    beginTransaction();
    for (const auto& profile : profiles) {
        if (!insertAppArmorProfile(profile)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<AppArmorProfile> LinuxAnalysisDatabase::queryAppArmorProfiles(const std::string& whereClause) {
    std::vector<AppArmorProfile> profiles;
    std::string sql = "SELECT profile_name, mode, file_path, allowed_paths, denied_paths, is_enabled FROM linux_apparmor_profiles";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return profiles;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AppArmorProfile profile;
        profile.profileName = safeColumnText(stmt, 0);
        profile.mode = safeColumnText(stmt, 1);
        profile.filePath = safeColumnText(stmt, 2);
        profile.allowedPaths = jsonToVector<std::string>(safeColumnText(stmt, 3));
        profile.deniedPaths = jsonToVector<std::string>(safeColumnText(stmt, 4));
        profile.isEnabled = sqlite3_column_int(stmt, 5) != 0;
        profiles.push_back(profile);
    }

    return profiles;
}

std::vector<AppArmorProfile> LinuxAnalysisDatabase::queryAppArmorProfilesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<AppArmorProfile> profiles;

    std::string sql = "SELECT profile_name, mode, file_path, allowed_paths, denied_paths, is_enabled FROM linux_apparmor_profiles";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return profiles;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return profiles;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AppArmorProfile profile;
        profile.profileName = safeColumnText(stmt, 0);
        profile.mode = safeColumnText(stmt, 1);
        profile.filePath = safeColumnText(stmt, 2);
        profile.allowedPaths = jsonToVector<std::string>(safeColumnText(stmt, 3));
        profile.deniedPaths = jsonToVector<std::string>(safeColumnText(stmt, 4));
        profile.isEnabled = sqlite3_column_int(stmt, 5) != 0;
        profiles.push_back(profile);
    }

    return profiles;
}

// ============================================================================
// AppArmor Violation Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertAppArmorViolation(const AppArmorViolation& violation) {
    const char* sql = LinuxAnalysisSQL::INSERT_APPARMOR_VIOLATION;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT64(stmt, 1, violation.timestamp);
    BIND_TEXT(stmt, 2, violation.profile);
    BIND_TEXT(stmt, 3, violation.operation);
    BIND_TEXT(stmt, 4, violation.targetPath);
    BIND_TEXT(stmt, 5, violation.executable);
    BIND_TEXT(stmt, 6, violation.status);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertAppArmorViolations(const std::vector<AppArmorViolation>& violations) {
    beginTransaction();
    for (const auto& violation : violations) {
        if (!insertAppArmorViolation(violation)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<AppArmorViolation> LinuxAnalysisDatabase::queryAppArmorViolations(const std::string& whereClause) {
    std::vector<AppArmorViolation> violations;
    std::string sql = "SELECT timestamp, profile, operation, target_path, executable, status FROM linux_apparmor_violations";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return violations;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AppArmorViolation violation;
        violation.timestamp = sqlite3_column_int64(stmt, 0);
        violation.profile = safeColumnText(stmt, 1);
        violation.operation = safeColumnText(stmt, 2);
        violation.targetPath = safeColumnText(stmt, 3);
        violation.executable = safeColumnText(stmt, 4);
        violation.status = safeColumnText(stmt, 5);
        violations.push_back(violation);
    }

    return violations;
}

std::vector<AppArmorViolation> LinuxAnalysisDatabase::queryAppArmorViolationsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<AppArmorViolation> violations;

    std::string sql = "SELECT timestamp, profile, operation, target_path, executable, status FROM linux_apparmor_violations";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return violations;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return violations;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AppArmorViolation violation;
        violation.timestamp = sqlite3_column_int64(stmt, 0);
        violation.profile = safeColumnText(stmt, 1);
        violation.operation = safeColumnText(stmt, 2);
        violation.targetPath = safeColumnText(stmt, 3);
        violation.executable = safeColumnText(stmt, 4);
        violation.status = safeColumnText(stmt, 5);
        violations.push_back(violation);
    }

    return violations;
}
