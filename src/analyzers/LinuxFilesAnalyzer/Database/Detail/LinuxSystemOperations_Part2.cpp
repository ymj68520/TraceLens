// LinuxSystemOperations_Part2.cpp
// System-related database operations: network, systemd, kernel, firewall, and browser

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
