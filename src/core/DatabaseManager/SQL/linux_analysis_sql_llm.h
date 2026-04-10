// linux_analysis_sql_llm.h
// LLM analysis SQL statements for Linux forensic analysis database

#pragma once
#ifndef LINUX_ANALYSIS_SQL_LLM_H
#define LINUX_ANALYSIS_SQL_LLM_H

namespace linux_analysis_sql_llm {

// ============================================================================
// LLM Analysis UPDATE Statements
// ============================================================================

inline constexpr const char* UPDATE_LOG_ENTRY_LLM_ANALYSIS =
    "UPDATE linux_log_entries SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_USER_LLM_ANALYSIS =
    "UPDATE linux_users SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_LOGIN_RECORD_LLM_ANALYSIS =
    "UPDATE linux_login_records SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_SHELL_HISTORY_LLM_ANALYSIS =
    "UPDATE linux_shell_history SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_CRON_JOB_LLM_ANALYSIS =
    "UPDATE linux_cron_jobs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_SSH_KEY_LLM_ANALYSIS =
    "UPDATE linux_ssh_keys SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_SSH_KNOWN_HOST_LLM_ANALYSIS =
    "UPDATE linux_ssh_known_hosts SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_PACKAGE_LLM_ANALYSIS =
    "UPDATE linux_packages SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_NETWORK_CONNECTION_LLM_ANALYSIS =
    "UPDATE linux_network_connections SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_SYSTEMD_SERVICE_LLM_ANALYSIS =
    "UPDATE linux_systemd_services SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_KERNEL_MODULE_LLM_ANALYSIS =
    "UPDATE linux_kernel_modules SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_FIREWALL_RULE_LLM_ANALYSIS =
    "UPDATE linux_firewall_rules SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_AUDIT_LOG_LLM_ANALYSIS =
    "UPDATE linux_audit_logs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_BROWSER_PROFILE_LLM_ANALYSIS =
    "UPDATE linux_browser_profiles SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

// ============================================================================
// LLM Analysis SELECT Statements (Pending Analysis)
// ============================================================================

inline constexpr const char* SELECT_LOG_ENTRIES_PENDING_ANALYSIS =
    "SELECT id, log_file, timestamp, hostname, process, message FROM linux_log_entries WHERE llm_analyzed_at IS NULL ORDER BY unix_timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_USERS_PENDING_ANALYSIS =
    "SELECT id, username, uid, shell, home_directory, is_system_account FROM linux_users WHERE llm_analyzed_at IS NULL ORDER BY uid LIMIT ?;";

inline constexpr const char* SELECT_LOGIN_RECORDS_PENDING_ANALYSIS =
    "SELECT id, username, terminal, remote_host, login_time, login_type, is_success FROM linux_login_records WHERE llm_analyzed_at IS NULL ORDER BY login_time DESC LIMIT ?;";

inline constexpr const char* SELECT_SHELL_HISTORY_PENDING_ANALYSIS =
    "SELECT id, username, shell_type, command, timestamp FROM linux_shell_history WHERE llm_analyzed_at IS NULL ORDER BY timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_CRON_JOBS_PENDING_ANALYSIS =
    "SELECT id, username, minute, hour, day_of_month, month, day_of_week, command FROM linux_cron_jobs WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_SSH_KEYS_PENDING_ANALYSIS =
    "SELECT id, username, key_type, key_path, comment FROM linux_ssh_keys WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_SSH_KNOWN_HOSTS_PENDING_ANALYSIS =
    "SELECT id, username, hostname, key_type FROM linux_ssh_known_hosts WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_PACKAGES_PENDING_ANALYSIS =
    "SELECT id, name, version, package_manager, description FROM linux_packages WHERE llm_analyzed_at IS NULL ORDER BY name LIMIT ?;";

inline constexpr const char* SELECT_NETWORK_CONNECTIONS_PENDING_ANALYSIS =
    "SELECT id, protocol, local_address, local_port, remote_address, remote_port, state, process FROM linux_network_connections WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_SYSTEMD_SERVICES_PENDING_ANALYSIS =
    "SELECT id, service_name, description, active_state, sub_state, exec_start FROM linux_systemd_services WHERE llm_analyzed_at IS NULL ORDER BY service_name LIMIT ?;";

inline constexpr const char* SELECT_KERNEL_MODULES_PENDING_ANALYSIS =
    "SELECT id, module_name, size, used_count, used_by, state FROM linux_kernel_modules WHERE llm_analyzed_at IS NULL ORDER BY module_name LIMIT ?;";

inline constexpr const char* SELECT_FIREWALL_RULES_PENDING_ANALYSIS =
    "SELECT id, chain, table_name, protocol, source, destination, action FROM linux_firewall_rules WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_AUDIT_LOGS_PENDING_ANALYSIS =
    "SELECT id, timestamp, type, message, subject, object, action, result FROM linux_audit_logs WHERE llm_analyzed_at IS NULL ORDER BY timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_BROWSER_PROFILES_PENDING_ANALYSIS =
    "SELECT id, browser_type, browser_name, profile_name, profile_path, username FROM linux_browser_profiles WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

// ============================================================================
// LLM Analysis Progress Tracking
// ============================================================================

inline constexpr const char* INSERT_LINUX_ANALYSIS_PROGRESS =
    "INSERT INTO linux_analysis_progress (task_id, table_name, total_artifacts, completed_artifacts, started_at, last_updated, status) "
    "VALUES (?, ?, 0, 0, ?, ?, 'running');";

inline constexpr const char* UPDATE_LINUX_ANALYSIS_PROGRESS =
    "UPDATE linux_analysis_progress SET completed_artifacts=?, last_updated=? WHERE task_id=?;";

inline constexpr const char* COMPLETE_LINUX_ANALYSIS_PROGRESS =
    "UPDATE linux_analysis_progress SET completed_artifacts=total_artifacts, status='completed', last_updated=? WHERE task_id=?;";

} // namespace linux_analysis_sql_llm

#endif // LINUX_ANALYSIS_SQL_LLM_H
