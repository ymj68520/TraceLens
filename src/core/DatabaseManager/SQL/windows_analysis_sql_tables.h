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

    -- ============================================================================
    -- DLL Analysis Tables
    -- ============================================================================

    -- DLL Base Information
    CREATE TABLE IF NOT EXISTS dll_base_info (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inode INTEGER NOT NULL,
        name TEXT NOT NULL,
        path TEXT UNIQUE NOT NULL,
        size INTEGER,
        md5 TEXT,
        sha1 TEXT,
        sha256 TEXT,
        imp_hash TEXT,
        rich_hash REAL,

        -- PE/ELF metadata
        file_format TEXT,
        machine_type TEXT,
        compile_timestamp INTEGER,
        subsystem INTEGER,
        entry_point INTEGER,
        image_base INTEGER,
        is_dll INTEGER DEFAULT 1,
        characteristics INTEGER,

        -- Version information
        file_version TEXT,
        product_version TEXT,
        company_name TEXT,
        file_description TEXT,

        -- Digital signature
        signature_status TEXT,
        signer_name TEXT,
        cert_issuer TEXT,
        cert_valid_from INTEGER,
        cert_valid_to INTEGER,

        -- File timestamps
        mtime INTEGER,
        ctime INTEGER,
        atime INTEGER,
        crtime INTEGER,

        -- Forensic correlation
        is_deleted INTEGER DEFAULT 0,
        threat_score INTEGER DEFAULT 0,

        -- LLM analysis fields
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT,

        created_at INTEGER DEFAULT (strftime('%s', 'now'))
    );

    -- DLL Sections
    CREATE TABLE IF NOT EXISTS dll_sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dll_id INTEGER NOT NULL,
        section_name TEXT NOT NULL,
        virtual_address INTEGER,
        virtual_size INTEGER,
        raw_data_size INTEGER,
        characteristics INTEGER,
        entropy REAL,
        is_writeable INTEGER DEFAULT 0,
        is_executable INTEGER DEFAULT 0,
        is_readable INTEGER DEFAULT 0,
        FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
    );

    -- DLL Imports
    CREATE TABLE IF NOT EXISTS dll_imports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dll_id INTEGER NOT NULL,
        imported_dll_name TEXT NOT NULL,
        imported_function TEXT,
        import_ordinal INTEGER,
        is_delayed INTEGER DEFAULT 0,
        FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
    );

    -- DLL Exports
    CREATE TABLE IF NOT EXISTS dll_exports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dll_id INTEGER NOT NULL,
        function_name TEXT NOT NULL,
        export_ordinal INTEGER,
        export_rva INTEGER,
        FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
    );

    -- DLL Anomalies
    CREATE TABLE IF NOT EXISTS dll_anomalies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dll_id INTEGER NOT NULL,
        anomaly_type TEXT NOT NULL,
        description TEXT,
        risk_level TEXT,
        risk_score INTEGER,
        details TEXT,
        detected_at INTEGER DEFAULT (strftime('%s', 'now')),
        FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
    );

    -- DLL Dependencies
    CREATE TABLE IF NOT EXISTS dll_dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_dll_id INTEGER NOT NULL,
        child_dll_id INTEGER NOT NULL,
        depth INTEGER,
        is_resolved INTEGER DEFAULT 1,
        FOREIGN KEY (parent_dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE,
        FOREIGN KEY (child_dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
    );

    -- DLL Forensic Links
    CREATE TABLE IF NOT EXISTS dll_forensic_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dll_id INTEGER NOT NULL,
        link_type TEXT NOT NULL,
        source_id TEXT,
        source_data TEXT,
        detected_at INTEGER,
        FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
    );
)";

// DLL Indices
inline constexpr const char* CREATE_DLL_INDICES = R"(
    CREATE INDEX IF NOT EXISTS idx_dll_base_inode ON dll_base_info(inode);
    CREATE INDEX IF NOT EXISTS idx_dll_base_md5 ON dll_base_info(md5);
    CREATE INDEX IF NOT EXISTS idx_dll_base_imp_hash ON dll_base_info(imp_hash);
    CREATE INDEX IF NOT EXISTS idx_dll_base_compile_ts ON dll_base_info(compile_timestamp);
    CREATE INDEX IF NOT EXISTS idx_dll_base_signature ON dll_base_info(signature_status);
    CREATE INDEX IF NOT EXISTS idx_dll_base_threat ON dll_base_info(threat_score);
    CREATE INDEX IF NOT EXISTS idx_dll_sections_dll_id ON dll_sections(dll_id);
    CREATE INDEX IF NOT EXISTS idx_dll_imports_dll_id ON dll_imports(dll_id);
    CREATE INDEX IF NOT EXISTS idx_dll_imports_function ON dll_imports(imported_function);
    CREATE INDEX IF NOT EXISTS idx_dll_exports_dll_id ON dll_exports(dll_id);
    CREATE INDEX IF NOT EXISTS idx_dll_anomalies_dll_id ON dll_anomalies(dll_id);
    CREATE INDEX IF NOT EXISTS idx_dll_anomalies_risk ON dll_anomalies(risk_level);
    CREATE INDEX IF NOT EXISTS idx_dll_deps_parent ON dll_dependencies(parent_dll_id);
    CREATE INDEX IF NOT EXISTS idx_dll_deps_child ON dll_dependencies(child_dll_id);
    CREATE INDEX IF NOT EXISTS idx_dll_links_dll_id ON dll_forensic_links(dll_id);
    CREATE INDEX IF NOT EXISTS idx_dll_links_type ON dll_forensic_links(link_type);
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
