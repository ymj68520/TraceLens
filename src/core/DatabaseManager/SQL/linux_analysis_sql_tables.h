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
