// linux_analysis_sql_tables.h
// SQL CREATE TABLE statements for Linux forensic analysis database

#pragma once
#ifndef LINUX_ANALYSIS_SQL_TABLES_H
#define LINUX_ANALYSIS_SQL_TABLES_H

namespace linux_analysis_sql_tables {

inline constexpr const char* CREATE_ALL_TABLES = R"(
    -- Log Entries
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
        facility TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_log_timestamp ON linux_log_entries(unix_timestamp);
    CREATE INDEX IF NOT EXISTS idx_log_file ON linux_log_entries(log_file);
    CREATE INDEX IF NOT EXISTS idx_log_llm_analyzed ON linux_log_entries(llm_analyzed_at);

    -- User Accounts
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
        is_system_account INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_users_uid ON linux_users(uid);
    CREATE INDEX IF NOT EXISTS idx_users_llm_analyzed ON linux_users(llm_analyzed_at);

    -- Groups
    CREATE TABLE IF NOT EXISTS linux_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_name TEXT UNIQUE,
        gid INTEGER,
        members TEXT
    );

    -- Login Records
    CREATE TABLE IF NOT EXISTS linux_login_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        terminal TEXT,
        remote_host TEXT,
        login_time INTEGER,
        logout_time INTEGER,
        login_type TEXT,
        is_success INTEGER,
        pid INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_login_time ON linux_login_records(login_time);
    CREATE INDEX IF NOT EXISTS idx_login_user ON linux_login_records(username);
    CREATE INDEX IF NOT EXISTS idx_login_llm_analyzed ON linux_login_records(llm_analyzed_at);

    -- Shell History
    CREATE TABLE IF NOT EXISTS linux_shell_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        shell_type TEXT,
        command TEXT,
        timestamp INTEGER,
        line_number INTEGER,
        history_file TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_history_user ON linux_shell_history(username);
    CREATE INDEX IF NOT EXISTS idx_history_time ON linux_shell_history(timestamp);
    CREATE INDEX IF NOT EXISTS idx_history_llm_analyzed ON linux_shell_history(llm_analyzed_at);

    -- Cron Jobs
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
        cron_type TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_cron_llm_analyzed ON linux_cron_jobs(llm_analyzed_at);

    -- SSH Keys
    CREATE TABLE IF NOT EXISTS linux_ssh_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        key_type TEXT,
        public_key TEXT,
        key_path TEXT,
        comment TEXT,
        options TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_ssh_keys_llm_analyzed ON linux_ssh_keys(llm_analyzed_at);

    -- SSH Known Hosts
    CREATE TABLE IF NOT EXISTS linux_ssh_known_hosts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        hostname TEXT,
        key_type TEXT,
        public_key TEXT,
        is_hashed INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_ssh_known_hosts_llm_analyzed ON linux_ssh_known_hosts(llm_analyzed_at);

    -- Packages
    CREATE TABLE IF NOT EXISTS linux_packages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        version TEXT,
        architecture TEXT,
        install_time INTEGER,
        package_manager TEXT,
        status TEXT,
        description TEXT,
        maintainer TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_pkg_name ON linux_packages(name);
    CREATE INDEX IF NOT EXISTS idx_pkg_llm_analyzed ON linux_packages(llm_analyzed_at);

    -- Network Connections
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
        pid INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_network_llm_analyzed ON linux_network_connections(llm_analyzed_at);

    -- Systemd Services
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
        is_enabled INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_systemd_llm_analyzed ON linux_systemd_services(llm_analyzed_at);

    -- Kernel Modules
    CREATE TABLE IF NOT EXISTS linux_kernel_modules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module_name TEXT,
        size INTEGER,
        used_count INTEGER,
        used_by TEXT,
        state TEXT,
        filename TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_kernel_modules_llm_analyzed ON linux_kernel_modules(llm_analyzed_at);

    -- Firewall Rules
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
        rule_spec TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_firewall_llm_analyzed ON linux_firewall_rules(llm_analyzed_at);

    -- Audit Logs
    CREATE TABLE IF NOT EXISTS linux_audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        serial_number INTEGER,
        type TEXT,
        message TEXT,
        subject TEXT,
        object TEXT,
        action TEXT,
        result TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_audit_time ON linux_audit_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_audit_type ON linux_audit_logs(type);
    CREATE INDEX IF NOT EXISTS idx_audit_llm_analyzed ON linux_audit_logs(llm_analyzed_at);

    -- Browser Profiles
    CREATE TABLE IF NOT EXISTS linux_browser_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        browser_type INTEGER,
        browser_name TEXT,
        profile_name TEXT,
        profile_path TEXT,
        username TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_browser_profiles_llm_analyzed ON linux_browser_profiles(llm_analyzed_at);

    -- Docker Containers
    CREATE TABLE IF NOT EXISTS linux_docker_containers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        container_id TEXT,
        image_name TEXT,
        image_tag TEXT,
        command TEXT,
        created_at INTEGER,
        state TEXT,
        mounts TEXT,
        ports TEXT,
        network_mode TEXT,
        host_config TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_docker_container_id ON linux_docker_containers(container_id);
    CREATE INDEX IF NOT EXISTS idx_docker_container_state ON linux_docker_containers(state);

    -- Docker Images
    CREATE TABLE IF NOT EXISTS linux_docker_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        image_id TEXT,
        tags TEXT,
        size INTEGER,
        created_at INTEGER,
        layer_ids TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_docker_image_id ON linux_docker_images(image_id);

    -- Docker Volumes
    CREATE TABLE IF NOT EXISTS linux_docker_volumes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        volume_name TEXT,
        mountpoint TEXT,
        driver TEXT,
        created_at INTEGER,
        container_ids TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_docker_volume_name ON linux_docker_volumes(volume_name);

    -- Podman Containers
    CREATE TABLE IF NOT EXISTS linux_podman_containers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        container_id TEXT,
        image_name TEXT,
        pod_name TEXT,
        is_rootless INTEGER,
        state TEXT,
        created_at INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_podman_container_id ON linux_podman_containers(container_id);
    CREATE INDEX IF NOT EXISTS idx_podman_container_state ON linux_podman_containers(state);

    -- Podman Pods
    CREATE TABLE IF NOT EXISTS linux_podman_pods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pod_name TEXT,
        pod_id TEXT,
        container_ids TEXT,
        state TEXT,
        created_at INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_podman_pod_id ON linux_podman_pods(pod_id);
    CREATE INDEX IF NOT EXISTS idx_podman_pod_state ON linux_podman_pods(state);

    -- Apache Access Logs
    CREATE TABLE IF NOT EXISTS linux_apache_access_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        remote_ip TEXT,
        method TEXT,
        url TEXT,
        http_version TEXT,
        status_code INTEGER,
        response_size INTEGER,
        referer TEXT,
        user_agent TEXT,
        vhost TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_apache_access_timestamp ON linux_apache_access_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_apache_access_ip ON linux_apache_access_logs(remote_ip);
    CREATE INDEX IF NOT EXISTS idx_apache_access_status ON linux_apache_access_logs(status_code);

    -- Apache Virtual Hosts
    CREATE TABLE IF NOT EXISTS linux_apache_vhosts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_name TEXT,
        document_root TEXT,
        server_aliases TEXT,
        ssl_certificates TEXT,
        config_file_path TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_apache_vhost_name ON linux_apache_vhosts(server_name);

    -- Nginx Access Logs
    CREATE TABLE IF NOT EXISTS linux_nginx_access_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        remote_ip TEXT,
        method TEXT,
        url TEXT,
        status_code INTEGER,
        response_size INTEGER,
        referer TEXT,
        user_agent TEXT,
        request_time REAL,
        upstream_addr TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_nginx_access_timestamp ON linux_nginx_access_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_nginx_access_ip ON linux_nginx_access_logs(remote_ip);
    CREATE INDEX IF NOT EXISTS idx_nginx_access_status ON linux_nginx_access_logs(status_code);

    -- Nginx Server Blocks
    CREATE TABLE IF NOT EXISTS linux_nginx_server_blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_name TEXT,
        root TEXT,
        locations TEXT,
        ssl_certificate TEXT,
        ssl_certificate_key TEXT,
        upstreams TEXT,
        config_file_path TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_nginx_server_name ON linux_nginx_server_blocks(server_name);

    -- Setuid Files
    CREATE TABLE IF NOT EXISTS linux_setuid_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT,
        owner TEXT,
        group_name TEXT,
        permissions INTEGER,
        is_setuid INTEGER,
        is_setgid INTEGER,
        size INTEGER,
        md5_hash TEXT,
        sha256_hash TEXT,
        is_suspicious INTEGER,
        suspicious_reason TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_setuid_file_path ON linux_setuid_files(file_path);
    CREATE INDEX IF NOT EXISTS idx_setuid_suspicious ON linux_setuid_files(is_suspicious);

    -- File Capabilities
    CREATE TABLE IF NOT EXISTS linux_capabilities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT,
        capabilities TEXT,
        capability_set TEXT,
        is_inherited INTEGER,
        is_suspicious INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_capabilities_file_path ON linux_capabilities(file_path);
    CREATE INDEX IF NOT EXISTS idx_capabilities_suspicious ON linux_capabilities(is_suspicious);

    -- SELinux Status
    CREATE TABLE IF NOT EXISTS linux_selinux_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        is_enabled INTEGER,
        mode TEXT,
        policy_name TEXT,
        current_mode TEXT
    );

    -- SELinux AVC Denials
    CREATE TABLE IF NOT EXISTS linux_selinux_avc_denials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        source_context TEXT,
        target_context TEXT,
        object_class TEXT,
        permission TEXT,
        executable_path TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_selinux_avc_timestamp ON linux_selinux_avc_denials(timestamp);
    CREATE INDEX IF NOT EXISTS idx_selinux_avc_executable ON linux_selinux_avc_denials(executable_path);

    -- AppArmor Profiles
    CREATE TABLE IF NOT EXISTS linux_apparmor_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_name TEXT,
        mode TEXT,
        file_path TEXT,
        allowed_paths TEXT,
        denied_paths TEXT,
        is_enabled INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_apparmor_profile_name ON linux_apparmor_profiles(profile_name);
    CREATE INDEX IF NOT EXISTS idx_apparmor_profile_enabled ON linux_apparmor_profiles(is_enabled);

    -- AppArmor Violations
    CREATE TABLE IF NOT EXISTS linux_apparmor_violations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        profile TEXT,
        operation TEXT,
        target_path TEXT,
        executable TEXT,
        status TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_apparmor_violation_timestamp ON linux_apparmor_violations(timestamp);
    CREATE INDEX IF NOT EXISTS idx_apparmor_violation_profile ON linux_apparmor_violations(profile);

    -- Correlated Events
    CREATE TABLE IF NOT EXISTS linux_correlated_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_timestamp INTEGER,
        end_timestamp INTEGER,
        event_type TEXT,
        initiating_user TEXT,
        initiating_process TEXT,
        related_event_ids TEXT,
        description TEXT,
        severity INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_correlated_events_timestamp ON linux_correlated_events(start_timestamp);
    CREATE INDEX IF NOT EXISTS idx_correlated_events_severity ON linux_correlated_events(severity);

    -- Attack Chains
    CREATE TABLE IF NOT EXISTS linux_attack_chains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chain_id TEXT,
        attack_type TEXT,
        events TEXT,
        timeline TEXT,
        summary TEXT,
        confidence REAL
    );
    CREATE INDEX IF NOT EXISTS idx_attack_chains_chain_id ON linux_attack_chains(chain_id);
    CREATE INDEX IF NOT EXISTS idx_attack_chains_type ON linux_attack_chains(attack_type);

    -- Timeline Events
    CREATE TABLE IF NOT EXISTS linux_timeline_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        source_type TEXT,
        event_type TEXT,
        description TEXT,
        username TEXT,
        ip_address TEXT,
        details TEXT,
        confidence INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_timeline_events_timestamp ON linux_timeline_events(timestamp);
    CREATE INDEX IF NOT EXISTS idx_timeline_events_type ON linux_timeline_events(event_type);

    -- Timeline Gaps
    CREATE TABLE IF NOT EXISTS linux_timeline_gaps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_time INTEGER,
        end_time INTEGER,
        duration INTEGER,
        description TEXT,
        is_suspicious INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_timeline_gaps_time ON linux_timeline_gaps(start_time);
    CREATE INDEX IF NOT EXISTS idx_timeline_gaps_suspicious ON linux_timeline_gaps(is_suspicious);

    -- Anomalies
    CREATE TABLE IF NOT EXISTS linux_anomalies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        anomaly_type TEXT,
        description TEXT,
        severity INTEGER,
        confidence REAL,
        evidence_ids TEXT,
        mitigation TEXT,
        detected_at INTEGER,
        anomaly_subtype TEXT,
        additional_data TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_anomalies_type ON linux_anomalies(anomaly_type);
    CREATE INDEX IF NOT EXISTS idx_anomalies_severity ON linux_anomalies(severity);
    CREATE INDEX IF NOT EXISTS idx_anomalies_detected_at ON linux_anomalies(detected_at);
)";

inline constexpr const char* CREATE_LINUX_ANALYSIS_PROGRESS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_analysis_progress (
        task_id TEXT PRIMARY KEY,
        table_name TEXT,
        total_artifacts INTEGER,
        completed_artifacts INTEGER,
        started_at INTEGER,
        last_updated INTEGER,
        status TEXT DEFAULT 'running'
    );
)";

} // namespace linux_analysis_sql_tables

#endif // LINUX_ANALYSIS_SQL_TABLES_H
