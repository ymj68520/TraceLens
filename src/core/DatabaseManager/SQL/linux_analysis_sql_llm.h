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

inline constexpr const char* UPDATE_AUDIT_EVENT_LLM_ANALYSIS =
    "UPDATE linux_audit_events SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_TAMPERING_FINDING_LLM_ANALYSIS =
    "UPDATE linux_tampering_findings SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_PERSISTENCE_ENTRY_LLM_ANALYSIS =
    "UPDATE linux_persistence_entries SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_JOURNAL_ENTRY_LLM_ANALYSIS =
    "UPDATE linux_journal_entries SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_WEB_ERROR_LOG_LLM_ANALYSIS =
    "UPDATE linux_web_error_logs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_MIDDLEWARE_LOG_LLM_ANALYSIS =
    "UPDATE linux_middleware_logs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_CONTAINER_LOG_LLM_ANALYSIS =
    "UPDATE linux_container_logs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_CONTAINER_SECURITY_FINDING_LLM_ANALYSIS =
    "UPDATE linux_container_security_findings SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_PACKAGE_LOG_LLM_ANALYSIS =
    "UPDATE linux_package_logs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_SUSPICIOUS_PACKAGE_LLM_ANALYSIS =
    "UPDATE linux_suspicious_packages SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_ACCOUNT_SECURITY_FINDING_LLM_ANALYSIS =
    "UPDATE linux_account_security_findings SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_SSH_SECURITY_FINDING_LLM_ANALYSIS =
    "UPDATE linux_ssh_security_findings SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_DATABASE_LOG_LLM_ANALYSIS =
    "UPDATE linux_database_logs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_DATABASE_SECURITY_FINDING_LLM_ANALYSIS =
    "UPDATE linux_database_security_findings SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_EMAIL_LOG_LLM_ANALYSIS =
    "UPDATE linux_email_logs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_EMAIL_SECURITY_FINDING_LLM_ANALYSIS =
    "UPDATE linux_email_security_findings SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_VPN_LOG_LLM_ANALYSIS =
    "UPDATE linux_vpn_logs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_VPN_SECURITY_FINDING_LLM_ANALYSIS =
    "UPDATE linux_vpn_security_findings SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_FIREWALL_LOG_LLM_ANALYSIS =
    "UPDATE linux_firewall_logs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_SECURITY_PRODUCT_LOG_LLM_ANALYSIS =
    "UPDATE linux_security_product_logs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_SECURITY_PRODUCT_FINDING_LLM_ANALYSIS =
    "UPDATE linux_security_product_findings SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_MODSECURITY_LOG_LLM_ANALYSIS =
    "UPDATE linux_modsecurity_logs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

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

inline constexpr const char* SELECT_AUDIT_EVENTS_PENDING_ANALYSIS =
    "SELECT id, event_id, timestamp, serial_number, event_type, syscall, exe, argv, auid, uid FROM linux_audit_events WHERE llm_analyzed_at IS NULL ORDER BY timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_TAMPERING_FINDINGS_PENDING_ANALYSIS =
    "SELECT id, tampering_type, severity, description, affected_log, timestamp_start FROM linux_tampering_findings WHERE llm_analyzed_at IS NULL ORDER BY severity DESC LIMIT ?;";

inline constexpr const char* SELECT_PERSISTENCE_ENTRIES_PENDING_ANALYSIS =
    "SELECT id, persistence_type, file_path, command, username, is_suspicious, risk_level FROM linux_persistence_entries WHERE llm_analyzed_at IS NULL ORDER BY risk_level DESC LIMIT ?;";

inline constexpr const char* SELECT_JOURNAL_ENTRIES_PENDING_ANALYSIS =
    "SELECT id, realtime_timestamp, boot_id, systemd_unit, pid, uid, comm, exe, message, priority FROM linux_journal_entries WHERE llm_analyzed_at IS NULL ORDER BY realtime_timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_WEB_ERROR_LOGS_PENDING_ANALYSIS =
    "SELECT id, timestamp, source, level, message, client_ip, error_code FROM linux_web_error_logs WHERE llm_analyzed_at IS NULL ORDER BY timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_MIDDLEWARE_LOGS_PENDING_ANALYSIS =
    "SELECT id, timestamp, source, level, message, component FROM linux_middleware_logs WHERE llm_analyzed_at IS NULL ORDER BY timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_CONTAINER_LOGS_PENDING_ANALYSIS =
    "SELECT id, timestamp, container_id, container_name, pod_name, namespace, stream, message FROM linux_container_logs WHERE llm_analyzed_at IS NULL ORDER BY timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_CONTAINER_SECURITY_FINDINGS_PENDING_ANALYSIS =
    "SELECT id, container_id, container_name, finding_type, severity, description FROM linux_container_security_findings WHERE llm_analyzed_at IS NULL ORDER BY severity DESC LIMIT ?;";

inline constexpr const char* SELECT_PACKAGE_LOGS_PENDING_ANALYSIS =
    "SELECT id, timestamp, package_manager, operation, package_name, package_version FROM linux_package_logs WHERE llm_analyzed_at IS NULL ORDER BY timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_SUSPICIOUS_PACKAGES_PENDING_ANALYSIS =
    "SELECT id, package_name, finding_type, severity, description FROM linux_suspicious_packages WHERE llm_analyzed_at IS NULL ORDER BY severity DESC LIMIT ?;";

inline constexpr const char* SELECT_ACCOUNT_SECURITY_FINDINGS_PENDING_ANALYSIS =
    "SELECT id, finding_type, severity, username, description FROM linux_account_security_findings WHERE llm_analyzed_at IS NULL ORDER BY severity DESC LIMIT ?;";

inline constexpr const char* SELECT_SSH_SECURITY_FINDINGS_PENDING_ANALYSIS =
    "SELECT id, finding_type, severity, username, hostname, description FROM linux_ssh_security_findings WHERE llm_analyzed_at IS NULL ORDER BY severity DESC LIMIT ?;";

inline constexpr const char* SELECT_DATABASE_LOGS_PENDING_ANALYSIS =
    "SELECT id, db_type, timestamp_unix, severity, message, operation FROM linux_database_logs WHERE llm_analyzed_at IS NULL ORDER BY timestamp_unix DESC LIMIT ?;";

inline constexpr const char* SELECT_DATABASE_SECURITY_FINDINGS_PENDING_ANALYSIS =
    "SELECT id, db_type, finding_type, severity, description FROM linux_database_security_findings WHERE llm_analyzed_at IS NULL ORDER BY severity DESC LIMIT ?;";

inline constexpr const char* SELECT_EMAIL_LOGS_PENDING_ANALYSIS =
    "SELECT id, service_type, timestamp_unix, status, from_addr, to_addr, subject FROM linux_email_logs WHERE llm_analyzed_at IS NULL ORDER BY timestamp_unix DESC LIMIT ?;";

inline constexpr const char* SELECT_EMAIL_SECURITY_FINDINGS_PENDING_ANALYSIS =
    "SELECT id, service_type, finding_type, severity, description FROM linux_email_security_findings WHERE llm_analyzed_at IS NULL ORDER BY severity DESC LIMIT ?;";

inline constexpr const char* SELECT_VPN_LOGS_PENDING_ANALYSIS =
    "SELECT id, service_type, timestamp_unix, username, event_type, remote_ip FROM linux_vpn_logs WHERE llm_analyzed_at IS NULL ORDER BY timestamp_unix DESC LIMIT ?;";

inline constexpr const char* SELECT_VPN_SECURITY_FINDINGS_PENDING_ANALYSIS =
    "SELECT id, service_type, finding_type, severity, username, description FROM linux_vpn_security_findings WHERE llm_analyzed_at IS NULL ORDER BY severity DESC LIMIT ?;";

inline constexpr const char* SELECT_FIREWALL_LOGS_PENDING_ANALYSIS =
    "SELECT id, tool_type, timestamp_unix, action, src_addr, dst_addr, protocol FROM linux_firewall_logs WHERE llm_analyzed_at IS NULL ORDER BY timestamp_unix DESC LIMIT ?;";

inline constexpr const char* SELECT_SECURITY_PRODUCT_LOGS_PENDING_ANALYSIS =
    "SELECT id, tool_type, timestamp_unix, event_type, result, target FROM linux_security_product_logs WHERE llm_analyzed_at IS NULL ORDER BY timestamp_unix DESC LIMIT ?;";

inline constexpr const char* SELECT_SECURITY_PRODUCT_FINDINGS_PENDING_ANALYSIS =
    "SELECT id, tool_type, finding_type, severity, description FROM linux_security_product_findings WHERE llm_analyzed_at IS NULL ORDER BY severity DESC LIMIT ?;";

inline constexpr const char* SELECT_MODSECURITY_LOGS_PENDING_ANALYSIS =
    "SELECT id, timestamp, client_ip, request_method, request_uri, rule_id, action FROM linux_modsecurity_logs WHERE llm_analyzed_at IS NULL ORDER BY timestamp DESC LIMIT ?;";

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
