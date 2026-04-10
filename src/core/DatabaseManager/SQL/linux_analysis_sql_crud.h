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

// ============================================================================
// INSERT Statements - New Tables (Containers, Web Servers, Security, Enhanced)
// ============================================================================

inline constexpr const char* INSERT_DOCKER_CONTAINER =
    "INSERT INTO linux_docker_containers "
    "(container_id, image_name, image_tag, command, created_at, state, mounts, ports, network_mode, host_config) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_DOCKER_IMAGE =
    "INSERT INTO linux_docker_images "
    "(image_id, tags, size, created_at, layer_ids) "
    "VALUES (?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_DOCKER_VOLUME =
    "INSERT INTO linux_docker_volumes "
    "(volume_name, mountpoint, driver, created_at, container_ids) "
    "VALUES (?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_PODMAN_CONTAINER =
    "INSERT INTO linux_podman_containers "
    "(container_id, image_name, pod_name, is_rootless, state, created_at) "
    "VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_PODMAN_POD =
    "INSERT INTO linux_podman_pods "
    "(pod_name, pod_id, container_ids, state, created_at) "
    "VALUES (?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_APACHE_ACCESS_LOG =
    "INSERT INTO linux_apache_access_logs "
    "(timestamp, remote_ip, method, url, http_version, status_code, response_size, referer, user_agent, vhost) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_APACHE_VHOST =
    "INSERT INTO linux_apache_vhosts "
    "(server_name, document_root, server_aliases, ssl_certificates, config_file_path) "
    "VALUES (?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_NGINX_ACCESS_LOG =
    "INSERT INTO linux_nginx_access_logs "
    "(timestamp, remote_ip, method, url, status_code, response_size, referer, user_agent, request_time, upstream_addr) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_NGINX_SERVER_BLOCK =
    "INSERT INTO linux_nginx_server_blocks "
    "(server_name, root, locations, ssl_certificate, ssl_certificate_key, upstreams, config_file_path) "
    "VALUES (?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_SETUID_FILE =
    "INSERT INTO linux_setuid_files "
    "(file_path, owner, group_name, permissions, is_setuid, is_setgid, size, md5_hash, sha256_hash, is_suspicious, suspicious_reason) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_FILE_CAPABILITY =
    "INSERT INTO linux_capabilities "
    "(file_path, capabilities, capability_set, is_inherited, is_suspicious) "
    "VALUES (?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_SELINUX_STATUS =
    "INSERT INTO linux_selinux_status "
    "(is_enabled, mode, policy_name, current_mode) "
    "VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_SELINUX_AVC_DENIAL =
    "INSERT INTO linux_selinux_avc_denials "
    "(timestamp, source_context, target_context, object_class, permission, executable_path) "
    "VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_APPARMOR_PROFILE =
    "INSERT INTO linux_apparmor_profiles "
    "(profile_name, mode, file_path, allowed_paths, denied_paths, is_enabled) "
    "VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_APPARMOR_VIOLATION =
    "INSERT INTO linux_apparmor_violations "
    "(timestamp, profile, operation, target_path, executable, status) "
    "VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_CORRELATED_EVENT =
    "INSERT INTO linux_correlated_events "
    "(start_timestamp, end_timestamp, event_type, initiating_user, initiating_process, related_event_ids, description, severity) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_ATTACK_CHAIN =
    "INSERT INTO linux_attack_chains "
    "(chain_id, attack_type, events, timeline, summary, confidence) "
    "VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_TIMELINE_EVENT =
    "INSERT INTO linux_timeline_events "
    "(timestamp, source_type, event_type, description, username, ip_address, details, confidence) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_TIMELINE_GAP =
    "INSERT INTO linux_timeline_gaps "
    "(start_time, end_time, duration, description, is_suspicious) "
    "VALUES (?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_ANOMALY =
    "INSERT INTO linux_anomalies "
    "(anomaly_type, description, severity, confidence, evidence_ids, mitigation, detected_at, anomaly_subtype, additional_data) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

// ============================================================================
// SELECT Statements - New Tables (Containers, Web Servers, Security, Enhanced)
// ============================================================================

inline constexpr const char* SELECT_DOCKER_CONTAINERS_BASE =
    "SELECT container_id, image_name, image_tag, command, created_at, state, mounts, ports, network_mode, host_config "
    "FROM linux_docker_containers";

inline constexpr const char* SELECT_DOCKER_IMAGES_BASE =
    "SELECT image_id, tags, size, created_at, layer_ids FROM linux_docker_images";

inline constexpr const char* SELECT_DOCKER_VOLUMES_BASE =
    "SELECT volume_name, mountpoint, driver, created_at, container_ids FROM linux_docker_volumes";

inline constexpr const char* SELECT_PODMAN_CONTAINERS_BASE =
    "SELECT container_id, image_name, pod_name, is_rootless, state, created_at FROM linux_podman_containers";

inline constexpr const char* SELECT_PODMAN_PODS_BASE =
    "SELECT pod_name, pod_id, container_ids, state, created_at FROM linux_podman_pods";

inline constexpr const char* SELECT_APACHE_ACCESS_LOGS_BASE =
    "SELECT timestamp, remote_ip, method, url, http_version, status_code, response_size, referer, user_agent, vhost "
    "FROM linux_apache_access_logs";

inline constexpr const char* SELECT_APACHE_VHOSTS_BASE =
    "SELECT server_name, document_root, server_aliases, ssl_certificates, config_file_path FROM linux_apache_vhosts";

inline constexpr const char* SELECT_NGINX_ACCESS_LOGS_BASE =
    "SELECT timestamp, remote_ip, method, url, status_code, response_size, referer, user_agent, request_time, upstream_addr "
    "FROM linux_nginx_access_logs";

inline constexpr const char* SELECT_NGINX_SERVER_BLOCKS_BASE =
    "SELECT server_name, root, locations, ssl_certificate, ssl_certificate_key, upstreams, config_file_path "
    "FROM linux_nginx_server_blocks";

inline constexpr const char* SELECT_SETUID_FILES_BASE =
    "SELECT file_path, owner, group_name, permissions, is_setuid, is_setgid, size, md5_hash, sha256_hash, is_suspicious, suspicious_reason "
    "FROM linux_setuid_files";

inline constexpr const char* SELECT_CAPABILITIES_BASE =
    "SELECT file_path, capabilities, capability_set, is_inherited, is_suspicious FROM linux_capabilities";

inline constexpr const char* SELECT_SELINUX_STATUS_BASE =
    "SELECT is_enabled, mode, policy_name, current_mode FROM linux_selinux_status";

inline constexpr const char* SELECT_SELINUX_AVC_DENIALS_BASE =
    "SELECT timestamp, source_context, target_context, object_class, permission, executable_path FROM linux_selinux_avc_denials";

inline constexpr const char* SELECT_APPARMOR_PROFILES_BASE =
    "SELECT profile_name, mode, file_path, allowed_paths, denied_paths, is_enabled FROM linux_apparmor_profiles";

inline constexpr const char* SELECT_APPARMOR_VIOLATIONS_BASE =
    "SELECT timestamp, profile, operation, target_path, executable, status FROM linux_apparmor_violations";

inline constexpr const char* SELECT_CORRELATED_EVENTS_BASE =
    "SELECT start_timestamp, end_timestamp, event_type, initiating_user, initiating_process, related_event_ids, description, severity "
    "FROM linux_correlated_events";

inline constexpr const char* SELECT_ATTACK_CHAINS_BASE =
    "SELECT chain_id, attack_type, events, timeline, summary, confidence FROM linux_attack_chains";

inline constexpr const char* SELECT_TIMELINE_EVENTS_BASE =
    "SELECT timestamp, source_type, event_type, description, username, ip_address, details, confidence FROM linux_timeline_events";

inline constexpr const char* SELECT_TIMELINE_GAPS_BASE =
    "SELECT start_time, end_time, duration, description, is_suspicious FROM linux_timeline_gaps";

inline constexpr const char* SELECT_ANOMALIES_BASE =
    "SELECT anomaly_type, description, severity, confidence, evidence_ids, mitigation, detected_at, anomaly_subtype, additional_data "
    "FROM linux_anomalies";

} // namespace linux_analysis_sql_crud

#endif // LINUX_ANALYSIS_SQL_CRUD_H
