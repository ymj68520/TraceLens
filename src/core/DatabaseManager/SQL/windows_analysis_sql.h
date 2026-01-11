// windows_analysis_sql.h
// SQL statements for Windows forensic analysis database

#pragma once
#ifndef WINDOWS_ANALYSIS_SQL_H
#define WINDOWS_ANALYSIS_SQL_H

namespace WindowsAnalysisSQL {

// ============================================================================
// CREATE TABLE Statements
// ============================================================================

const char* CREATE_ALL_TABLES = R"(
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
        forensic_importance TEXT
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
        channel TEXT
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
        referenced_directories TEXT
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
        description TEXT
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
        is_pinned INTEGER
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
        referrer TEXT
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
        danger_accepted INTEGER
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
        date_modified INTEGER
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
        times_used INTEGER
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
        file_size INTEGER
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
        permissions TEXT
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
        is_running INTEGER
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
        run_as TEXT
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
        language TEXT
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
        cpu_time_ms INTEGER
    );
)";

// ============================================================================
// INSERT Statements
// ============================================================================

const char* INSERT_REGISTRY_VALUE = 
    "INSERT INTO registry_values (hive_path, hive_type, key_path, value_name, value_type, value_data, last_modified, forensic_importance) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_EVENT_LOG = 
    "INSERT INTO event_logs (record_id, log_source, event_id, level, timestamp, source, message, computer_name, user_sid, channel) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_PREFETCH_FILE = 
    "INSERT INTO prefetch_files (file_path, executable_name, executable_path, prefetch_hash, run_count, last_run_time, creation_time, referenced_files, referenced_directories) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_LNK_FILE = 
    "INSERT INTO lnk_files (lnk_path, target_path, working_directory, arguments, icon_location, creation_time, modification_time, access_time, target_size, drive_type, volume_serial, netbios_name, relative_path, description) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_JUMP_LIST_ENTRY = 
    "INSERT INTO jump_list_entries (app_id, entry_path, entry_name, access_time, creation_time, access_count, is_pinned) "
    "VALUES (?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_USER_ACCOUNT = 
    "INSERT INTO user_accounts (rid, username, full_name, comment, last_login, password_last_set, account_expires, password_expires, account_flags, is_admin, home_directory, profile_path) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_USB_DEVICE = 
    "INSERT INTO usb_devices (vendor_id, product_id, serial_number, device_description, friendly_name, device_class, first_connected, last_connected, last_drive_letter) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_RECYCLE_BIN_ENTRY = 
    "INSERT INTO recycle_bin (recycle_file_path, original_path, file_name, deletion_time, original_size, user_sid) "
    "VALUES (?, ?, ?, ?, ?, ?);";

const char* INSERT_BROWSER_ARTIFACT = 
    "INSERT INTO browser_artifacts (browser_name, artifact_type, url, title, timestamp, visit_count, local_path, file_size) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_MFT_ENTRY = 
    "INSERT INTO mft_entries (entry_number, file_name, file_path, parent_entry, logical_size, physical_size, creation_time, modification_time, access_time, mft_modification_time, fn_creation_time, fn_modification_time, is_directory, is_deleted, has_ads, permissions) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_WINDOWS_SERVICE = 
    "INSERT INTO windows_services (service_name, display_name, image_path, start_type, service_type, account_name, description, is_running) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_SCHEDULED_TASK = 
    "INSERT INTO scheduled_tasks (task_name, task_path, author, description, action_type, action_path, arguments, trigger_type, last_run_time, next_run_time, status, run_as) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_AMCACHE_ENTRY = 
    "INSERT INTO amcache_entries (file_path, file_hash, file_name, company_name, product_name, product_version, file_description, file_size, link_time, last_modified, language) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_SRUM_ENTRY = 
    "INSERT INTO srum_entries (app_name, user_name, timestamp, bytes_received, bytes_sent, foreground_duration, background_duration, cpu_time_ms) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_BROWSER_HISTORY = 
    "INSERT INTO browser_history (browser_name, profile_name, url, title, visit_time, visit_duration, visit_count, visit_type, is_redirect, referrer) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_BROWSER_DOWNLOAD = 
    "INSERT INTO browser_downloads (browser_name, profile_name, url, target_path, file_name, file_size, start_time, end_time, state, mime_type, referrer, received_bytes, danger_accepted) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_BROWSER_BOOKMARK = 
    "INSERT INTO browser_bookmarks (browser_name, profile_name, url, title, folder_path, date_added, date_modified) "
    "VALUES (?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_BROWSER_COOKIE = 
    "INSERT INTO browser_cookies (browser_name, profile_name, domain, name, path, creation_time, expiration_time, last_access_time, is_secure, is_http_only, is_persistent, same_site) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

const char* INSERT_BROWSER_LOGIN = 
    "INSERT INTO browser_logins (browser_name, profile_name, url, action_url, username, encrypted_password, date_created, date_last_used, date_modified, times_used) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

// ============================================================================
// SELECT Statements
// ============================================================================

const char* SELECT_REGISTRY_VALUES_BASE = 
    "SELECT hive_path, hive_type, key_path, value_name, value_type, value_data, last_modified, forensic_importance FROM registry_values";

const char* SELECT_EVENT_LOGS_BASE = 
    "SELECT record_id, log_source, event_id, level, timestamp, source, message, computer_name, user_sid, channel FROM event_logs";

const char* SELECT_PREFETCH_FILES_BASE = 
    "SELECT file_path, executable_name, executable_path, prefetch_hash, run_count, last_run_time, creation_time, referenced_files, referenced_directories FROM prefetch_files";

const char* SELECT_LNK_FILES_BASE = 
    "SELECT lnk_path, target_path, working_directory, arguments, icon_location, creation_time, modification_time, access_time, target_size, drive_type, volume_serial, netbios_name, relative_path, description FROM lnk_files";

const char* SELECT_JUMP_LIST_ENTRIES_BASE = 
    "SELECT app_id, entry_path, entry_name, access_time, creation_time, access_count, is_pinned FROM jump_list_entries";

const char* SELECT_USER_ACCOUNTS_BASE = 
    "SELECT rid, username, full_name, comment, last_login, password_last_set, account_expires, password_expires, account_flags, is_admin, home_directory, profile_path FROM user_accounts";

const char* SELECT_USB_DEVICES_BASE = 
    "SELECT vendor_id, product_id, serial_number, device_description, friendly_name, device_class, first_connected, last_connected, last_drive_letter FROM usb_devices";

const char* SELECT_RECYCLE_BIN_BASE = 
    "SELECT recycle_file_path, original_path, file_name, deletion_time, original_size, user_sid FROM recycle_bin";

const char* SELECT_BROWSER_ARTIFACTS_BASE = 
    "SELECT browser_name, artifact_type, url, title, timestamp, visit_count, local_path, file_size FROM browser_artifacts";

const char* SELECT_MFT_ENTRIES_BASE = 
    "SELECT entry_number, file_name, file_path, parent_entry, logical_size, physical_size, creation_time, modification_time, access_time, mft_modification_time, fn_creation_time, fn_modification_time, is_directory, is_deleted, has_ads, permissions FROM mft_entries";

const char* SELECT_WINDOWS_SERVICES_BASE = 
    "SELECT service_name, display_name, image_path, start_type, service_type, account_name, description, is_running FROM windows_services";

const char* SELECT_SCHEDULED_TASKS_BASE = 
    "SELECT task_name, task_path, author, description, action_type, action_path, arguments, trigger_type, last_run_time, next_run_time, status, run_as FROM scheduled_tasks";

const char* SELECT_AMCACHE_ENTRIES_BASE = 
    "SELECT file_path, file_hash, file_name, company_name, product_name, product_version, file_description, file_size, link_time, last_modified, language FROM amcache_entries";

const char* SELECT_SRUM_ENTRIES_BASE = 
    "SELECT app_name, user_name, timestamp, bytes_received, bytes_sent, foreground_duration, background_duration, cpu_time_ms FROM srum_entries";

const char* SELECT_BROWSER_HISTORY_BASE = 
    "SELECT browser_name, profile_name, url, title, visit_time, visit_duration, visit_count, visit_type, is_redirect, referrer FROM browser_history";

const char* SELECT_BROWSER_DOWNLOADS_BASE = 
    "SELECT browser_name, profile_name, url, target_path, file_name, file_size, start_time, end_time, state, mime_type, referrer, received_bytes, danger_accepted FROM browser_downloads";

const char* SELECT_BROWSER_BOOKMARKS_BASE = 
    "SELECT browser_name, profile_name, url, title, folder_path, date_added, date_modified FROM browser_bookmarks";

const char* SELECT_BROWSER_COOKIES_BASE = 
    "SELECT browser_name, profile_name, domain, name, path, creation_time, expiration_time, last_access_time, is_secure, is_http_only, is_persistent, same_site FROM browser_cookies";

const char* SELECT_BROWSER_LOGINS_BASE = 
    "SELECT browser_name, profile_name, url, action_url, username, encrypted_password, date_created, date_last_used, date_modified, times_used FROM browser_logins";

} // namespace WindowsAnalysisSQL

#endif // WINDOWS_ANALYSIS_SQL_H
