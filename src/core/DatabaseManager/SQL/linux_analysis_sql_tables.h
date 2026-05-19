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

    -- Aggregated Audit Events (multi-line events grouped by serial)
    CREATE TABLE IF NOT EXISTS linux_audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT UNIQUE,
        timestamp INTEGER,
        serial_number INTEGER,
        syscall INTEGER,
        syscall_name TEXT,
        success INTEGER,
        exit_code INTEGER,
        pid INTEGER,
        ppid INTEGER,
        uid INTEGER,
        gid INTEGER,
        euid INTEGER,
        egid INTEGER,
        auid INTEGER,
        session_id INTEGER,
        exe TEXT,
        comm TEXT,
        terminal TEXT,
        audit_key TEXT,
        argv TEXT,
        argc INTEGER,
        cwd TEXT,
        proctitle TEXT,
        auth_user TEXT,
        auth_op TEXT,
        auth_addr TEXT,
        avc_action TEXT,
        avc_class TEXT,
        avc_permission TEXT,
        event_type TEXT,
        severity INTEGER,
        path_list TEXT,
        raw_lines TEXT,
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_audit_events_time ON linux_audit_events(timestamp);
    CREATE INDEX IF NOT EXISTS idx_audit_events_type ON linux_audit_events(event_type);
    CREATE INDEX IF NOT EXISTS idx_audit_events_pid ON linux_audit_events(pid);
    CREATE INDEX IF NOT EXISTS idx_audit_events_auid ON linux_audit_events(auid);
    CREATE INDEX IF NOT EXISTS idx_audit_events_severity ON linux_audit_events(severity);
    CREATE INDEX IF NOT EXISTS idx_audit_events_llm_analyzed ON linux_audit_events(llm_analyzed_at);

    -- Log Tampering Findings
    CREATE TABLE IF NOT EXISTS linux_tampering_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tampering_type TEXT NOT NULL,
        severity INTEGER DEFAULT 0,
        description TEXT,
        log_source TEXT,
        timestamp_start INTEGER,
        timestamp_end INTEGER,
        evidence TEXT,
        related_files TEXT,
        parser_name TEXT,
        parser_version TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_tampering_type ON linux_tampering_findings(tampering_type);
    CREATE INDEX IF NOT EXISTS idx_tampering_severity ON linux_tampering_findings(severity);
    CREATE INDEX IF NOT EXISTS idx_tampering_time ON linux_tampering_findings(timestamp_start);
    CREATE INDEX IF NOT EXISTS idx_tampering_llm_analyzed ON linux_tampering_findings(llm_analyzed_at);

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
    -- Journal Entries (Phase 2)
    CREATE TABLE IF NOT EXISTS linux_journal_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        realtime_timestamp INTEGER,
        monotonic_timestamp INTEGER,
        boot_id TEXT,
        systemd_unit TEXT,
        user_unit TEXT,
        pid INTEGER,
        uid INTEGER,
        gid INTEGER,
        comm TEXT,
        exe TEXT,
        cmdline TEXT,
        transport TEXT,
        message TEXT,
        message_id TEXT,
        syslog_identifier TEXT,
        priority TEXT,
        cursor_id TEXT,
        -- Evidence provenance
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        source_offset INTEGER,
        source_inode INTEGER,
        source_hash TEXT,
        parse_error TEXT,
        raw_record TEXT,
        confidence INTEGER DEFAULT 100,
        -- LLM analysis columns
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_journal_timestamp ON linux_journal_entries(realtime_timestamp);
    CREATE INDEX IF NOT EXISTS idx_journal_boot_id ON linux_journal_entries(boot_id);
    CREATE INDEX IF NOT EXISTS idx_journal_unit ON linux_journal_entries(systemd_unit);
    CREATE INDEX IF NOT EXISTS idx_journal_pid ON linux_journal_entries(pid);
    CREATE INDEX IF NOT EXISTS idx_journal_uid ON linux_journal_entries(uid);
    CREATE INDEX IF NOT EXISTS idx_journal_priority ON linux_journal_entries(priority);
    CREATE INDEX IF NOT EXISTS idx_journal_llm_analyzed ON linux_journal_entries(llm_analyzed_at);

    -- Boot Sessions (Phase 2)
    CREATE TABLE IF NOT EXISTS linux_boot_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        boot_id TEXT UNIQUE,
        start_time INTEGER,
        end_time INTEGER,
        entry_count INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_boot_session_start ON linux_boot_sessions(start_time);

    -- Journal Anomalies (Phase 2)
    CREATE TABLE IF NOT EXISTS linux_journal_anomalies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        anomaly_type TEXT,
        description TEXT,
        timestamp INTEGER,
        severity INTEGER,
        -- Evidence provenance
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_journal_anomaly_type ON linux_journal_anomalies(anomaly_type);
    CREATE INDEX IF NOT EXISTS idx_journal_anomaly_severity ON linux_journal_anomalies(severity);

    -- Persistence Mechanisms (Phase 6)
    CREATE TABLE IF NOT EXISTS linux_persistence_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        persistence_type TEXT NOT NULL,
        risk_level TEXT,
        file_path TEXT,
        entry_name TEXT,
        command TEXT,
        arguments TEXT,
        username TEXT,
        schedule TEXT,
        is_enabled INTEGER,
        is_suspicious INTEGER,
        suspicious_reason TEXT,
        raw_content TEXT,
        -- Evidence provenance
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        source_line INTEGER,
        -- LLM analysis
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_persistence_type ON linux_persistence_entries(persistence_type);
    CREATE INDEX IF NOT EXISTS idx_persistence_risk ON linux_persistence_entries(risk_level);
    CREATE INDEX IF NOT EXISTS idx_persistence_suspicious ON linux_persistence_entries(is_suspicious);
    CREATE INDEX IF NOT EXISTS idx_persistence_llm_analyzed ON linux_persistence_entries(llm_analyzed_at);

    -- Web Error Logs (Phase 7: Web and Middleware Log Enhancement)
    CREATE TABLE IF NOT EXISTS linux_web_error_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        level TEXT,
        source TEXT,
        client_ip TEXT,
        message TEXT,
        module TEXT,
        pid TEXT,
        file_path TEXT,
        -- Evidence provenance
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        raw_record TEXT,
        -- LLM analysis
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_web_error_timestamp ON linux_web_error_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_web_error_level ON linux_web_error_logs(level);
    CREATE INDEX IF NOT EXISTS idx_web_error_source ON linux_web_error_logs(source);
    CREATE INDEX IF NOT EXISTS idx_web_error_llm_analyzed ON linux_web_error_logs(llm_analyzed_at);

    -- Middleware Logs (Phase 7: Web and Middleware Log Enhancement)
    CREATE TABLE IF NOT EXISTS linux_middleware_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        level TEXT,
        source TEXT,
        logger TEXT,
        message TEXT,
        thread TEXT,
        exception TEXT,
        pid TEXT,
        file_path TEXT,
        -- Evidence provenance
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        raw_record TEXT,
        -- LLM analysis
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_middleware_timestamp ON linux_middleware_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_middleware_level ON linux_middleware_logs(level);
    CREATE INDEX IF NOT EXISTS idx_middleware_source ON linux_middleware_logs(source);
    CREATE INDEX IF NOT EXISTS idx_middleware_llm_analyzed ON linux_middleware_logs(llm_analyzed_at);

    -- ModSecurity Audit Log Entries (Phase 7)
    CREATE TABLE IF NOT EXISTS linux_modsecurity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        client_ip TEXT,
        method TEXT,
        uri TEXT,
        rule_id TEXT,
        rule_message TEXT,
        severity TEXT,
        action TEXT,
        file_path TEXT,
        -- Evidence provenance
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        raw_record TEXT,
        -- LLM analysis
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_modsecurity_timestamp ON linux_modsecurity_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_modsecurity_client ON linux_modsecurity_logs(client_ip);
    CREATE INDEX IF NOT EXISTS idx_modsecurity_rule ON linux_modsecurity_logs(rule_id);
    CREATE INDEX IF NOT EXISTS idx_modsecurity_llm_analyzed ON linux_modsecurity_logs(llm_analyzed_at);

    -- Container Runtime Logs (Phase 8)
    CREATE TABLE IF NOT EXISTS linux_container_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        stream TEXT,
        message TEXT,
        container_id TEXT,
        container_name TEXT,
        pod_name TEXT,
        namespace TEXT,
        runtime_type TEXT,
        file_path TEXT,
        -- Evidence provenance
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        raw_record TEXT,
        -- LLM analysis
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_container_log_timestamp ON linux_container_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_container_log_container ON linux_container_logs(container_id);
    CREATE INDEX IF NOT EXISTS idx_container_log_pod ON linux_container_logs(pod_name);
    CREATE INDEX IF NOT EXISTS idx_container_log_namespace ON linux_container_logs(namespace);
    CREATE INDEX IF NOT EXISTS idx_container_log_llm_analyzed ON linux_container_logs(llm_analyzed_at);

    -- Container Security Findings (Phase 8)
    CREATE TABLE IF NOT EXISTS linux_container_security_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        finding_type TEXT NOT NULL,
        severity TEXT,
        container_id TEXT,
        container_name TEXT,
        pod_name TEXT,
        namespace TEXT,
        description TEXT,
        evidence TEXT,
        file_path TEXT,
        -- Evidence provenance
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        -- LLM analysis
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_container_sec_type ON linux_container_security_findings(finding_type);
    CREATE INDEX IF NOT EXISTS idx_container_sec_severity ON linux_container_security_findings(severity);
    CREATE INDEX IF NOT EXISTS idx_container_sec_container ON linux_container_security_findings(container_id);
    CREATE INDEX IF NOT EXISTS idx_container_sec_llm_analyzed ON linux_container_security_findings(llm_analyzed_at);

    CREATE TABLE IF NOT EXISTS linux_package_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        package_manager TEXT,
        package_name TEXT,
        package_version TEXT,
        architecture TEXT,
        operation TEXT,
        operation_detail TEXT,
        status TEXT,
        user_name TEXT,
        command_line TEXT,
        file_path TEXT,
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        raw_record TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_pkg_logs_timestamp ON linux_package_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_pkg_logs_manager ON linux_package_logs(package_manager);
    CREATE INDEX IF NOT EXISTS idx_pkg_logs_package ON linux_package_logs(package_name);
    CREATE INDEX IF NOT EXISTS idx_pkg_logs_operation ON linux_package_logs(operation);
    CREATE INDEX IF NOT EXISTS idx_pkg_logs_llm_analyzed ON linux_package_logs(llm_analyzed_at);

    CREATE TABLE IF NOT EXISTS linux_suspicious_packages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        finding_type TEXT,
        severity TEXT,
        package_name TEXT,
        package_version TEXT,
        description TEXT,
        evidence TEXT,
        file_path TEXT,
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_susp_pkg_type ON linux_suspicious_packages(finding_type);
    CREATE INDEX IF NOT EXISTS idx_susp_pkg_severity ON linux_suspicious_packages(severity);
    CREATE INDEX IF NOT EXISTS idx_susp_pkg_package ON linux_suspicious_packages(package_name);
    CREATE INDEX IF NOT EXISTS idx_susp_pkg_llm_analyzed ON linux_suspicious_packages(llm_analyzed_at);

    CREATE TABLE IF NOT EXISTS linux_account_security_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        finding_type TEXT,
        severity TEXT,
        username TEXT,
        description TEXT,
        evidence TEXT,
        file_path TEXT,
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_acct_sec_type ON linux_account_security_findings(finding_type);
    CREATE INDEX IF NOT EXISTS idx_acct_sec_severity ON linux_account_security_findings(severity);
    CREATE INDEX IF NOT EXISTS idx_acct_sec_user ON linux_account_security_findings(username);
    CREATE INDEX IF NOT EXISTS idx_acct_sec_llm_analyzed ON linux_account_security_findings(llm_analyzed_at);

    CREATE TABLE IF NOT EXISTS linux_ssh_security_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        finding_type TEXT,
        severity TEXT,
        description TEXT,
        evidence TEXT,
        file_path TEXT,
        username TEXT,
        hostname TEXT,
        key_type TEXT,
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_ssh_sec_type ON linux_ssh_security_findings(finding_type);
    CREATE INDEX IF NOT EXISTS idx_ssh_sec_severity ON linux_ssh_security_findings(severity);
    CREATE INDEX IF NOT EXISTS idx_ssh_sec_user ON linux_ssh_security_findings(username);
    CREATE INDEX IF NOT EXISTS idx_ssh_sec_host ON linux_ssh_security_findings(hostname);
    CREATE INDEX IF NOT EXISTS idx_ssh_sec_llm_analyzed ON linux_ssh_security_findings(llm_analyzed_at);

    CREATE TABLE IF NOT EXISTS linux_analysis_progress (
        task_id TEXT PRIMARY KEY,
        table_name TEXT,
        total_artifacts INTEGER,
        completed_artifacts INTEGER,
        started_at INTEGER,
        last_updated INTEGER,
        status TEXT DEFAULT 'running'
    );

    -- Phase 11: Database, Email, VPN, Firewall, Security Product Logs

    -- Database Service Logs (MySQL, PostgreSQL, MongoDB, Redis)
    CREATE TABLE IF NOT EXISTS linux_database_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        timestamp_unix INTEGER,
        db_type TEXT,
        severity TEXT,
        component TEXT,
        message TEXT,
        source_file TEXT,
        line_number INTEGER,
        username TEXT,
        database_name TEXT,
        client_addr TEXT,
        query_text TEXT,
        error_code INTEGER,
        parser_name TEXT,
        parser_version TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_db_log_type ON linux_database_logs(db_type);
    CREATE INDEX IF NOT EXISTS idx_db_log_severity ON linux_database_logs(severity);
    CREATE INDEX IF NOT EXISTS idx_db_log_ts ON linux_database_logs(timestamp_unix);
    CREATE INDEX IF NOT EXISTS idx_db_log_llm ON linux_database_logs(llm_analyzed_at);

    -- Database Security Findings
    CREATE TABLE IF NOT EXISTS linux_database_security_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        finding_type TEXT,
        severity TEXT,
        description TEXT,
        evidence TEXT,
        source_file TEXT,
        db_type TEXT,
        username TEXT,
        client_addr TEXT,
        parser_name TEXT,
        parser_version TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_db_sec_type ON linux_database_security_findings(finding_type);
    CREATE INDEX IF NOT EXISTS idx_db_sec_severity ON linux_database_security_findings(severity);
    CREATE INDEX IF NOT EXISTS idx_db_sec_llm ON linux_database_security_findings(llm_analyzed_at);

    -- Email Service Logs (Postfix, Exim, Dovecot)
    CREATE TABLE IF NOT EXISTS linux_email_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        timestamp_unix INTEGER,
        service_type TEXT,
        severity TEXT,
        component TEXT,
        message_id TEXT,
        message TEXT,
        source_file TEXT,
        line_number INTEGER,
        sender TEXT,
        recipient TEXT,
        client_addr TEXT,
        relay_host TEXT,
        message_size INTEGER,
        status TEXT,
        parser_name TEXT,
        parser_version TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_email_type ON linux_email_logs(service_type);
    CREATE INDEX IF NOT EXISTS idx_email_status ON linux_email_logs(status);
    CREATE INDEX IF NOT EXISTS idx_email_ts ON linux_email_logs(timestamp_unix);
    CREATE INDEX IF NOT EXISTS idx_email_llm ON linux_email_logs(llm_analyzed_at);

    -- Email Security Findings
    CREATE TABLE IF NOT EXISTS linux_email_security_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        finding_type TEXT,
        severity TEXT,
        description TEXT,
        evidence TEXT,
        source_file TEXT,
        service_type TEXT,
        client_addr TEXT,
        parser_name TEXT,
        parser_version TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_email_sec_type ON linux_email_security_findings(finding_type);
    CREATE INDEX IF NOT EXISTS idx_email_sec_severity ON linux_email_security_findings(severity);
    CREATE INDEX IF NOT EXISTS idx_email_sec_llm ON linux_email_security_findings(llm_analyzed_at);

    -- VPN Service Logs (OpenVPN, WireGuard)
    CREATE TABLE IF NOT EXISTS linux_vpn_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        timestamp_unix INTEGER,
        service_type TEXT,
        severity TEXT,
        message TEXT,
        source_file TEXT,
        line_number INTEGER,
        username TEXT,
        client_addr TEXT,
        virtual_addr TEXT,
        server_addr TEXT,
        common_name TEXT,
        bytes_sent INTEGER,
        bytes_received INTEGER,
        parser_name TEXT,
        parser_version TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_vpn_type ON linux_vpn_logs(service_type);
    CREATE INDEX IF NOT EXISTS idx_vpn_user ON linux_vpn_logs(username);
    CREATE INDEX IF NOT EXISTS idx_vpn_ts ON linux_vpn_logs(timestamp_unix);
    CREATE INDEX IF NOT EXISTS idx_vpn_llm ON linux_vpn_logs(llm_analyzed_at);

    -- VPN Security Findings
    CREATE TABLE IF NOT EXISTS linux_vpn_security_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        finding_type TEXT,
        severity TEXT,
        description TEXT,
        evidence TEXT,
        source_file TEXT,
        service_type TEXT,
        username TEXT,
        client_addr TEXT,
        parser_name TEXT,
        parser_version TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_vpn_sec_type ON linux_vpn_security_findings(finding_type);
    CREATE INDEX IF NOT EXISTS idx_vpn_sec_severity ON linux_vpn_security_findings(severity);
    CREATE INDEX IF NOT EXISTS idx_vpn_sec_llm ON linux_vpn_security_findings(llm_analyzed_at);

    -- Firewall Logs (UFW, firewalld)
    CREATE TABLE IF NOT EXISTS linux_firewall_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        timestamp_unix INTEGER,
        tool_type TEXT,
        severity TEXT,
        message TEXT,
        source_file TEXT,
        line_number INTEGER,
        action TEXT,
        protocol TEXT,
        src_addr TEXT,
        src_port INTEGER,
        dst_addr TEXT,
        dst_port INTEGER,
        interface_name TEXT,
        chain_name TEXT,
        parser_name TEXT,
        parser_version TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_fw_type ON linux_firewall_logs(tool_type);
    CREATE INDEX IF NOT EXISTS idx_fw_action ON linux_firewall_logs(action);
    CREATE INDEX IF NOT EXISTS idx_fw_src ON linux_firewall_logs(src_addr);
    CREATE INDEX IF NOT EXISTS idx_fw_ts ON linux_firewall_logs(timestamp_unix);
    CREATE INDEX IF NOT EXISTS idx_fw_llm ON linux_firewall_logs(llm_analyzed_at);

    -- Security Product Logs (fail2ban, ClamAV, rkhunter, OSSEC, AIDE)
    CREATE TABLE IF NOT EXISTS linux_security_product_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        timestamp_unix INTEGER,
        tool_type TEXT,
        severity TEXT,
        message TEXT,
        source_file TEXT,
        line_number INTEGER,
        event_type TEXT,
        target_file TEXT,
        result TEXT,
        parser_name TEXT,
        parser_version TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_secprod_type ON linux_security_product_logs(tool_type);
    CREATE INDEX IF NOT EXISTS idx_secprod_event ON linux_security_product_logs(event_type);
    CREATE INDEX IF NOT EXISTS idx_secprod_result ON linux_security_product_logs(result);
    CREATE INDEX IF NOT EXISTS idx_secprod_ts ON linux_security_product_logs(timestamp_unix);
    CREATE INDEX IF NOT EXISTS idx_secprod_llm ON linux_security_product_logs(llm_analyzed_at);

    -- Security Product Findings
    CREATE TABLE IF NOT EXISTS linux_security_product_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        finding_type TEXT,
        severity TEXT,
        description TEXT,
        evidence TEXT,
        source_file TEXT,
        tool_type TEXT,
        target_file TEXT,
        parser_name TEXT,
        parser_version TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_secprod_find_type ON linux_security_product_findings(finding_type);
    CREATE INDEX IF NOT EXISTS idx_secprod_find_severity ON linux_security_product_findings(severity);
    CREATE INDEX IF NOT EXISTS idx_secprod_find_llm ON linux_security_product_findings(llm_analyzed_at);

    -- USB Events
    CREATE TABLE IF NOT EXISTS linux_usb_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        event_type TEXT,
        vendor_id TEXT,
        product_id TEXT,
        serial_number TEXT,
        manufacturer TEXT,
        product TEXT,
        device_path TEXT,
        mount_point TEXT,
        filesystem TEXT,
        capacity_bytes INTEGER,
        kernel_device TEXT,
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        source_offset INTEGER,
        source_inode INTEGER,
        source_hash TEXT,
        parse_error TEXT,
        raw_record TEXT,
        confidence INTEGER DEFAULT 100,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_usb_timestamp ON linux_usb_events(timestamp);
    CREATE INDEX IF NOT EXISTS idx_usb_type ON linux_usb_events(event_type);
    CREATE INDEX IF NOT EXISTS idx_usb_vid ON linux_usb_events(vendor_id);
    CREATE INDEX IF NOT EXISTS idx_usb_pid ON linux_usb_events(product_id);
    CREATE INDEX IF NOT EXISTS idx_usb_llm ON linux_usb_events(llm_analyzed_at);

    -- Mount Entries
    CREATE TABLE IF NOT EXISTS linux_mount_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        device TEXT,
        mount_point TEXT,
        filesystem TEXT,
        mount_options TEXT,
        total_bytes INTEGER,
        used_bytes INTEGER,
        available_bytes INTEGER,
        is_external INTEGER DEFAULT 0,
        is_network INTEGER DEFAULT 0,
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        source_offset INTEGER,
        source_inode INTEGER,
        source_hash TEXT,
        parse_error TEXT,
        raw_record TEXT,
        confidence INTEGER DEFAULT 100,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_mount_device ON linux_mount_entries(device);
    CREATE INDEX IF NOT EXISTS idx_mount_point ON linux_mount_entries(mount_point);
    CREATE INDEX IF NOT EXISTS idx_mount_external ON linux_mount_entries(is_external);
    CREATE INDEX IF NOT EXISTS idx_mount_llm ON linux_mount_entries(llm_analyzed_at);

    -- Cloud Provider Logs
    CREATE TABLE IF NOT EXISTS linux_cloud_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        provider TEXT,
        agent_name TEXT,
        event_type TEXT,
        level TEXT,
        module TEXT,
        message TEXT,
        instance_id TEXT,
        region TEXT,
        availability_zone TEXT,
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        source_offset INTEGER,
        source_inode INTEGER,
        source_hash TEXT,
        parse_error TEXT,
        raw_record TEXT,
        confidence INTEGER DEFAULT 100,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_cloud_timestamp ON linux_cloud_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_cloud_provider ON linux_cloud_logs(provider);
    CREATE INDEX IF NOT EXISTS idx_cloud_agent ON linux_cloud_logs(agent_name);
    CREATE INDEX IF NOT EXISTS idx_cloud_type ON linux_cloud_logs(event_type);
    CREATE INDEX IF NOT EXISTS idx_cloud_llm ON linux_cloud_logs(llm_analyzed_at);

    -- Extended History (Python, MySQL, Git, Docker, Kube, Cloud credentials)
    CREATE TABLE IF NOT EXISTS linux_extended_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        tool_type TEXT,
        username TEXT,
        command TEXT,
        database_name TEXT,
        working_dir TEXT,
        source_file TEXT,
        is_sensitive INTEGER DEFAULT 0,
        sensitive_reason TEXT,
        parser_name TEXT,
        parser_version TEXT,
        source_offset INTEGER,
        source_inode INTEGER,
        source_hash TEXT,
        parse_error TEXT,
        raw_record TEXT,
        confidence INTEGER DEFAULT 100,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_ext_hist_tool ON linux_extended_history(tool_type);
    CREATE INDEX IF NOT EXISTS idx_ext_hist_user ON linux_extended_history(username);
    CREATE INDEX IF NOT EXISTS idx_ext_hist_sensitive ON linux_extended_history(is_sensitive);
    CREATE INDEX IF NOT EXISTS idx_ext_hist_llm ON linux_extended_history(llm_analyzed_at);

    -- Security Bypass Findings
    CREATE TABLE IF NOT EXISTS linux_security_bypass (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        finding_type TEXT,
        severity INTEGER DEFAULT 0,
        file_path TEXT,
        description TEXT,
        evidence TEXT,
        username TEXT,
        is_confirmed INTEGER DEFAULT 0,
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        source_offset INTEGER,
        source_inode INTEGER,
        source_hash TEXT,
        parse_error TEXT,
        raw_record TEXT,
        confidence INTEGER DEFAULT 100,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_sec_bypass_type ON linux_security_bypass(finding_type);
    CREATE INDEX IF NOT EXISTS idx_sec_bypass_severity ON linux_security_bypass(severity);
    CREATE INDEX IF NOT EXISTS idx_sec_bypass_user ON linux_security_bypass(username);
    CREATE INDEX IF NOT EXISTS idx_sec_bypass_llm ON linux_security_bypass(llm_analyzed_at);

    -- Rule Matches
    CREATE TABLE IF NOT EXISTS linux_rule_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id TEXT,
        rule_type TEXT,
        rule_name TEXT,
        description TEXT,
        matched_event_ids TEXT,
        attck_technique TEXT,
        attack_stage TEXT,
        severity INTEGER DEFAULT 0,
        confidence REAL DEFAULT 0.0,
        parser_name TEXT,
        parser_version TEXT,
        source_file TEXT,
        source_offset INTEGER,
        source_inode INTEGER,
        source_hash TEXT,
        parse_error TEXT,
        raw_record TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_rule_id ON linux_rule_matches(rule_id);
    CREATE INDEX IF NOT EXISTS idx_rule_type ON linux_rule_matches(rule_type);
    CREATE INDEX IF NOT EXISTS idx_rule_technique ON linux_rule_matches(attck_technique);
    CREATE INDEX IF NOT EXISTS idx_rule_stage ON linux_rule_matches(attack_stage);
    CREATE INDEX IF NOT EXISTS idx_rule_severity ON linux_rule_matches(severity);
    CREATE INDEX IF NOT EXISTS idx_rule_llm ON linux_rule_matches(llm_analyzed_at);
)";

} // namespace linux_analysis_sql_tables

#endif // LINUX_ANALYSIS_SQL_TABLES_H
