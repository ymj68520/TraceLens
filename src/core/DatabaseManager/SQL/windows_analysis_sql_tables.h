// windows_analysis_sql_tables.h
// SQL CREATE TABLE statements for Windows forensic analysis database

#pragma once
#ifndef WINDOWS_ANALYSIS_SQL_TABLES_H
#define WINDOWS_ANALYSIS_SQL_TABLES_H

namespace windows_analysis_sql_tables {

inline constexpr const char* CREATE_ALL_TABLES = R"(
    -- Registry Values
    CREATE TABLE IF NOT EXISTS registry_values (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hive_path TEXT,
        hive_type TEXT,
        key_path TEXT,
        value_name TEXT,
        value_type TEXT,
        value_data TEXT,
        last_modified INTEGER,
        forensic_importance TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- Event Log Entries
    CREATE TABLE IF NOT EXISTS event_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id INTEGER,
        log_source TEXT,
        event_id INTEGER,
        level TEXT,
        timestamp INTEGER,
        source TEXT,
        message TEXT,
        computer_name TEXT,
        user_sid TEXT,
        channel TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- Prefetch Files
    CREATE TABLE IF NOT EXISTS prefetch_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT,
        executable_name TEXT,
        executable_path TEXT,
        prefetch_hash TEXT,
        run_count INTEGER,
        last_run_time INTEGER,
        creation_time INTEGER,
        referenced_files TEXT,
        referenced_directories TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- LNK Files
    CREATE TABLE IF NOT EXISTS lnk_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lnk_path TEXT,
        target_path TEXT,
        working_directory TEXT,
        arguments TEXT,
        icon_location TEXT,
        creation_time INTEGER,
        modification_time INTEGER,
        access_time INTEGER,
        target_size INTEGER,
        drive_type TEXT,
        volume_serial TEXT,
        netbios_name TEXT,
        relative_path TEXT,
        description TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- Jump List Entries
    CREATE TABLE IF NOT EXISTS jump_list_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id TEXT,
        entry_path TEXT,
        entry_name TEXT,
        access_time INTEGER,
        creation_time INTEGER,
        access_count INTEGER,
        is_pinned INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- User Accounts
    CREATE TABLE IF NOT EXISTS user_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rid INTEGER,
        username TEXT,
        full_name TEXT,
        comment TEXT,
        last_login INTEGER,
        password_last_set INTEGER,
        account_expires INTEGER,
        password_expires INTEGER,
        account_flags TEXT,
        is_admin INTEGER,
        home_directory TEXT,
        profile_path TEXT
    );

    -- USB Devices
    CREATE TABLE IF NOT EXISTS usb_devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vendor_id TEXT,
        product_id TEXT,
        serial_number TEXT,
        device_description TEXT,
        friendly_name TEXT,
        device_class TEXT,
        first_connected INTEGER,
        last_connected INTEGER,
        last_drive_letter TEXT
    );

    -- Recycle Bin
    CREATE TABLE IF NOT EXISTS recycle_bin (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recycle_file_path TEXT,
        original_path TEXT,
        file_name TEXT,
        deletion_time INTEGER,
        original_size INTEGER,
        user_sid TEXT
    );

    -- Browser History (Detailed)
    CREATE TABLE IF NOT EXISTS browser_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        browser_name TEXT,
        profile_name TEXT,
        url TEXT,
        title TEXT,
        visit_time INTEGER,
        visit_duration INTEGER,
        visit_count INTEGER,
        visit_type TEXT,
        is_redirect INTEGER,
        referrer TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- Browser Downloads (Detailed)
    CREATE TABLE IF NOT EXISTS browser_downloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        browser_name TEXT,
        profile_name TEXT,
        url TEXT,
        target_path TEXT,
        file_name TEXT,
        file_size INTEGER,
        start_time INTEGER,
        end_time INTEGER,
        state TEXT,
        mime_type TEXT,
        referrer TEXT,
        received_bytes INTEGER,
        danger_accepted INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- Browser Bookmarks (Detailed)
    CREATE TABLE IF NOT EXISTS browser_bookmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        browser_name TEXT,
        profile_name TEXT,
        url TEXT,
        title TEXT,
        folder_path TEXT,
        date_added INTEGER,
        date_modified INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- Browser Cookies (Detailed)
    CREATE TABLE IF NOT EXISTS browser_cookies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        browser_name TEXT,
        profile_name TEXT,
        domain TEXT,
        name TEXT,
        path TEXT,
        creation_time INTEGER,
        expiration_time INTEGER,
        last_access_time INTEGER,
        is_secure INTEGER,
        is_http_only INTEGER,
        is_persistent INTEGER,
        same_site TEXT
    );

    -- Browser Logins (Detailed)
    CREATE TABLE IF NOT EXISTS browser_logins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        browser_name TEXT,
        profile_name TEXT,
        url TEXT,
        action_url TEXT,
        username TEXT,
        encrypted_password TEXT,
        date_created INTEGER,
        date_last_used INTEGER,
        date_modified INTEGER,
        times_used INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- Browser Artifacts (Legacy - for backwards compatibility)
    CREATE TABLE IF NOT EXISTS browser_artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        browser_name TEXT,
        artifact_type TEXT,
        url TEXT,
        title TEXT,
        timestamp INTEGER,
        visit_count INTEGER,
        local_path TEXT,
        file_size INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- MFT Entries
    CREATE TABLE IF NOT EXISTS mft_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_number INTEGER,
        file_name TEXT,
        file_path TEXT,
        parent_entry INTEGER,
        logical_size INTEGER,
        physical_size INTEGER,
        creation_time INTEGER,
        modification_time INTEGER,
        access_time INTEGER,
        mft_modification_time INTEGER,
        fn_creation_time INTEGER,
        fn_modification_time INTEGER,
        is_directory INTEGER,
        is_deleted INTEGER,
        has_ads INTEGER,
        permissions TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- Windows Services
    CREATE TABLE IF NOT EXISTS windows_services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_name TEXT,
        display_name TEXT,
        image_path TEXT,
        start_type TEXT,
        service_type TEXT,
        account_name TEXT,
        description TEXT,
        is_running INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- Scheduled Tasks
    CREATE TABLE IF NOT EXISTS scheduled_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_name TEXT,
        task_path TEXT,
        author TEXT,
        description TEXT,
        action_type TEXT,
        action_path TEXT,
        arguments TEXT,
        trigger_type TEXT,
        last_run_time INTEGER,
        next_run_time INTEGER,
        status TEXT,
        run_as TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- Amcache Entries
    CREATE TABLE IF NOT EXISTS amcache_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT,
        file_hash TEXT,
        file_name TEXT,
        company_name TEXT,
        product_name TEXT,
        product_version TEXT,
        file_description TEXT,
        file_size INTEGER,
        link_time INTEGER,
        last_modified INTEGER,
        language TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );

    -- SRUM Entries
    CREATE TABLE IF NOT EXISTS srum_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_name TEXT,
        user_name TEXT,
        timestamp INTEGER,
        bytes_received INTEGER,
        bytes_sent INTEGER,
        foreground_duration INTEGER,
        background_duration INTEGER,
        cpu_time_ms INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
)";

// Analysis progress tracking table
inline constexpr const char* CREATE_WINDOWS_ANALYSIS_PROGRESS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS windows_analysis_progress (
        task_id TEXT PRIMARY KEY,
        table_name TEXT,
        total_artifacts INTEGER,
        completed_artifacts INTEGER,
        started_at INTEGER,
        last_updated INTEGER,
        status TEXT DEFAULT 'running'
    );
)";

} // namespace windows_analysis_sql_tables

#endif // WINDOWS_ANALYSIS_SQL_TABLES_H
