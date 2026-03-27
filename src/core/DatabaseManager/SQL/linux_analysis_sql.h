// linux_analysis_sql.h
// SQL statements for Linux forensic analysis database

#pragma once
#ifndef LINUX_ANALYSIS_SQL_H
#define LINUX_ANALYSIS_SQL_H

namespace LinuxAnalysisSQL {

// ============================================================================
// CREATE TABLE Statements
// ============================================================================

inline constexpr const char* CREATE_LOG_ENTRIES_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_log_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_file TEXT,
        timestamp TEXT,
        unix_timestamp INTEGER,
        hostname TEXT,
        process TEXT,
        pid INTEGER,
        message TEXT,
        level TEXT,
        facility TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_log_timestamp ON linux_log_entries(unix_timestamp);
    CREATE INDEX IF NOT EXISTS idx_log_file ON linux_log_entries(log_file);
)";

inline constexpr const char* CREATE_USERS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        uid INTEGER,
        gid INTEGER,
        full_name TEXT,
        home_directory TEXT,
        shell TEXT,
        password_hash TEXT,
        last_password_change INTEGER,
        password_max_age INTEGER,
        password_min_age INTEGER,
        password_warn_days INTEGER,
        inactive_days INTEGER,
        account_expires INTEGER,
        is_locked INTEGER,
        is_system_account INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_users_uid ON linux_users(uid);
)";

inline constexpr const char* CREATE_GROUPS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_name TEXT UNIQUE,
        gid INTEGER,
        members TEXT
    );
)";

inline constexpr const char* CREATE_LOGIN_RECORDS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_login_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        terminal TEXT,
        remote_host TEXT,
        login_time INTEGER,
        logout_time INTEGER,
        login_type TEXT,
        is_success INTEGER,
        pid INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_login_time ON linux_login_records(login_time);
    CREATE INDEX IF NOT EXISTS idx_login_user ON linux_login_records(username);
)";

inline constexpr const char* CREATE_SHELL_HISTORY_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_shell_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        shell_type TEXT,
        command TEXT,
        timestamp INTEGER,
        line_number INTEGER,
        history_file TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_history_user ON linux_shell_history(username);
    CREATE INDEX IF NOT EXISTS idx_history_time ON linux_shell_history(timestamp);
)";

inline constexpr const char* CREATE_CRON_JOBS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_cron_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        minute TEXT,
        hour TEXT,
        day_of_month TEXT,
        month TEXT,
        day_of_week TEXT,
        command TEXT,
        cron_file TEXT,
        cron_type TEXT
    );
)";

inline constexpr const char* CREATE_SSH_KEYS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_ssh_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        key_type TEXT,
        public_key TEXT,
        key_path TEXT,
        comment TEXT,
        options TEXT
    );
)";

inline constexpr const char* CREATE_SSH_KNOWN_HOSTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_ssh_known_hosts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        hostname TEXT,
        key_type TEXT,
        public_key TEXT,
        is_hashed INTEGER
    );
)";

inline constexpr const char* CREATE_PACKAGES_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_packages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        version TEXT,
        architecture TEXT,
        install_time INTEGER,
        package_manager TEXT,
        status TEXT,
        description TEXT,
        maintainer TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_pkg_name ON linux_packages(name);
)";

inline constexpr const char* CREATE_NETWORK_CONNECTIONS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_network_connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        protocol TEXT,
        local_address TEXT,
        local_port INTEGER,
        remote_address TEXT,
        remote_port INTEGER,
        state TEXT,
        uid INTEGER,
        inode INTEGER,
        process TEXT,
        pid INTEGER
    );
)";

inline constexpr const char* CREATE_SYSTEMD_SERVICES_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_systemd_services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_name TEXT,
        description TEXT,
        load_state TEXT,
        active_state TEXT,
        sub_state TEXT,
        unit_file TEXT,
        exec_start TEXT,
        user TEXT,
        is_enabled INTEGER
    );
)";

inline constexpr const char* CREATE_KERNEL_MODULES_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_kernel_modules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module_name TEXT,
        size INTEGER,
        used_count INTEGER,
        used_by TEXT,
        state TEXT,
        filename TEXT
    );
)";

inline constexpr const char* CREATE_FIREWALL_RULES_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_firewall_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chain TEXT,
        table_name TEXT,
        protocol TEXT,
        source TEXT,
        destination TEXT,
        source_port INTEGER,
        destination_port INTEGER,
        action TEXT,
        rule_spec TEXT
    );
)";

inline constexpr const char* CREATE_AUDIT_LOGS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        serial_number INTEGER,
        type TEXT,
        message TEXT,
        subject TEXT,
        object TEXT,
        action TEXT,
        result TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_audit_time ON linux_audit_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_audit_type ON linux_audit_logs(type);
)";

inline constexpr const char* CREATE_BROWSER_PROFILES_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_browser_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        browser_type INTEGER,
        browser_name TEXT,
        profile_name TEXT,
        profile_path TEXT,
        username TEXT
    );
)";

// ============================================================================
// INSERT Statements
// ============================================================================

inline constexpr const char* INSERT_LOG_ENTRY = 
    "INSERT INTO linux_log_entries "
    "(log_file, timestamp, unix_timestamp, hostname, process, pid, message, level, facility) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_USER_INFO = 
    "INSERT OR REPLACE INTO linux_users "
    "(username, uid, gid, full_name, home_directory, shell, password_hash, "
    "last_password_change, password_max_age, password_min_age, password_warn_days, "
    "inactive_days, account_expires, is_locked, is_system_account) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_GROUP_INFO = 
    "INSERT OR REPLACE INTO linux_groups (group_name, gid, members) VALUES (?, ?, ?)";

inline constexpr const char* INSERT_LOGIN_RECORD = 
    "INSERT INTO linux_login_records "
    "(username, terminal, remote_host, login_time, logout_time, login_type, is_success, pid) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_SHELL_HISTORY = 
    "INSERT INTO linux_shell_history "
    "(username, shell_type, command, timestamp, line_number, history_file) "
    "VALUES (?, ?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_CRON_JOB = 
    "INSERT INTO linux_cron_jobs "
    "(username, minute, hour, day_of_month, month, day_of_week, command, cron_file, cron_type) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_SSH_KEY = 
    "INSERT INTO linux_ssh_keys "
    "(username, key_type, public_key, key_path, comment, options) "
    "VALUES (?, ?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_SSH_KNOWN_HOST = 
    "INSERT INTO linux_ssh_known_hosts "
    "(username, hostname, key_type, public_key, is_hashed) "
    "VALUES (?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_PACKAGE_INFO = 
    "INSERT INTO linux_packages "
    "(name, version, architecture, install_time, package_manager, status, description, maintainer) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_NETWORK_CONNECTION = 
    "INSERT INTO linux_network_connections "
    "(protocol, local_address, local_port, remote_address, remote_port, state, uid, inode, process, pid) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_SYSTEMD_SERVICE = 
    "INSERT INTO linux_systemd_services "
    "(service_name, description, load_state, active_state, sub_state, unit_file, exec_start, user, is_enabled) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_KERNEL_MODULE = 
    "INSERT INTO linux_kernel_modules "
    "(module_name, size, used_count, used_by, state, filename) "
    "VALUES (?, ?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_FIREWALL_RULE = 
    "INSERT INTO linux_firewall_rules "
    "(chain, table_name, protocol, source, destination, source_port, destination_port, action, rule_spec) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_AUDIT_LOG = 
    "INSERT INTO linux_audit_logs "
    "(timestamp, serial_number, type, message, subject, object, action, result) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)";

inline constexpr const char* INSERT_BROWSER_PROFILE = 
    "INSERT INTO linux_browser_profiles "
    "(browser_type, browser_name, profile_name, profile_path, username) "
    "VALUES (?, ?, ?, ?, ?)";

// ============================================================================
// SELECT Statements
// ============================================================================

inline constexpr const char* SELECT_LOG_ENTRIES_BASE = 
    "SELECT log_file, timestamp, unix_timestamp, hostname, process, pid, message, level, facility "
    "FROM linux_log_entries";

inline constexpr const char* SELECT_USERS_BASE = 
    "SELECT username, uid, gid, full_name, home_directory, shell, password_hash, "
    "last_password_change, password_max_age, password_min_age, password_warn_days, "
    "inactive_days, account_expires, is_locked, is_system_account FROM linux_users";

inline constexpr const char* SELECT_GROUPS_BASE = 
    "SELECT group_name, gid, members FROM linux_groups";

inline constexpr const char* SELECT_LOGIN_RECORDS_BASE = 
    "SELECT username, terminal, remote_host, login_time, logout_time, login_type, is_success, pid "
    "FROM linux_login_records";

inline constexpr const char* SELECT_SHELL_HISTORY_BASE = 
    "SELECT username, shell_type, command, timestamp, line_number, history_file "
    "FROM linux_shell_history";

inline constexpr const char* SELECT_CRON_JOBS_BASE = 
    "SELECT username, minute, hour, day_of_month, month, day_of_week, command, cron_file, cron_type "
    "FROM linux_cron_jobs";

inline constexpr const char* SELECT_SSH_KEYS_BASE = 
    "SELECT username, key_type, public_key, key_path, comment, options FROM linux_ssh_keys";

inline constexpr const char* SELECT_SSH_KNOWN_HOSTS_BASE = 
    "SELECT username, hostname, key_type, public_key, is_hashed FROM linux_ssh_known_hosts";

inline constexpr const char* SELECT_PACKAGES_BASE = 
    "SELECT name, version, architecture, install_time, package_manager, status, description, maintainer "
    "FROM linux_packages";

inline constexpr const char* SELECT_NETWORK_CONNECTIONS_BASE = 
    "SELECT protocol, local_address, local_port, remote_address, remote_port, state, uid, inode, process, pid "
    "FROM linux_network_connections";

inline constexpr const char* SELECT_SYSTEMD_SERVICES_BASE = 
    "SELECT service_name, description, load_state, active_state, sub_state, unit_file, exec_start, user, is_enabled "
    "FROM linux_systemd_services";

inline constexpr const char* SELECT_KERNEL_MODULES_BASE = 
    "SELECT module_name, size, used_count, used_by, state, filename FROM linux_kernel_modules";

inline constexpr const char* SELECT_FIREWALL_RULES_BASE = 
    "SELECT chain, table_name, protocol, source, destination, source_port, destination_port, action, rule_spec "
    "FROM linux_firewall_rules";

inline constexpr const char* SELECT_AUDIT_LOGS_BASE = 
    "SELECT timestamp, serial_number, type, message, subject, object, action, result FROM linux_audit_logs";

inline constexpr const char* SELECT_BROWSER_PROFILES_BASE = 
    "SELECT browser_type, browser_name, profile_name, profile_path, username FROM linux_browser_profiles";

} // namespace LinuxAnalysisSQL

#endif // LINUX_ANALYSIS_SQL_H
