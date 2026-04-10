// linux_analysis_sql_crud.h
// SQL INSERT and SELECT statements for Linux forensic analysis database

#pragma once
#ifndef LINUX_ANALYSIS_SQL_CRUD_H
#define LINUX_ANALYSIS_SQL_CRUD_H

namespace linux_analysis_sql_crud {

// ============================================================================
// INSERT Statements
// ============================================================================

inline constexpr const char* INSERT_LOG_ENTRY =
    "INSERT INTO linux_log_entries "
    "(log_file, timestamp, unix_timestamp, hostname, process, pid, message, level, facility) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_USER_INFO =
    "INSERT OR REPLACE INTO linux_users "
    "(username, uid, gid, full_name, home_directory, shell, password_hash, "
    "last_password_change, password_max_age, password_min_age, password_warn_days, "
    "inactive_days, account_expires, is_locked, is_system_account) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_GROUP_INFO =
    "INSERT OR REPLACE INTO linux_groups (group_name, gid, members) VALUES (?, ?, ?);";

inline constexpr const char* INSERT_LOGIN_RECORD =
    "INSERT INTO linux_login_records "
    "(username, terminal, remote_host, login_time, logout_time, login_type, is_success, pid) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_SHELL_HISTORY =
    "INSERT INTO linux_shell_history "
    "(username, shell_type, command, timestamp, line_number, history_file) "
    "VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_CRON_JOB =
    "INSERT INTO linux_cron_jobs "
    "(username, minute, hour, day_of_month, month, day_of_week, command, cron_file, cron_type) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_SSH_KEY =
    "INSERT INTO linux_ssh_keys "
    "(username, key_type, public_key, key_path, comment, options) "
    "VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_SSH_KNOWN_HOST =
    "INSERT INTO linux_ssh_known_hosts "
    "(username, hostname, key_type, public_key, is_hashed) "
    "VALUES (?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_PACKAGE_INFO =
    "INSERT INTO linux_packages "
    "(name, version, architecture, install_time, package_manager, status, description, maintainer) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_NETWORK_CONNECTION =
    "INSERT INTO linux_network_connections "
    "(protocol, local_address, local_port, remote_address, remote_port, state, uid, inode, process, pid) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_SYSTEMD_SERVICE =
    "INSERT INTO linux_systemd_services "
    "(service_name, description, load_state, active_state, sub_state, unit_file, exec_start, user, is_enabled) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_KERNEL_MODULE =
    "INSERT INTO linux_kernel_modules "
    "(module_name, size, used_count, used_by, state, filename) "
    "VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_FIREWALL_RULE =
    "INSERT INTO linux_firewall_rules "
    "(chain, table_name, protocol, source, destination, source_port, destination_port, action, rule_spec) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_AUDIT_LOG =
    "INSERT INTO linux_audit_logs "
    "(timestamp, serial_number, type, message, subject, object, action, result) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_BROWSER_PROFILE =
    "INSERT INTO linux_browser_profiles "
    "(browser_type, browser_name, profile_name, profile_path, username) "
    "VALUES (?, ?, ?, ?, ?);";

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

} // namespace linux_analysis_sql_crud

#endif // LINUX_ANALYSIS_SQL_CRUD_H
