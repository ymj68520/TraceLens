// android_analysis_sql.h
// SQL statements for Android forensic analysis database

#pragma once
#ifndef ANDROID_ANALYSIS_SQL_H
#define ANDROID_ANALYSIS_SQL_H

namespace AndroidAnalysisSQL {

// ============================================================================
// CREATE TABLE Statements
// ============================================================================

inline constexpr const char* CREATE_ALL_TABLES = R"(
    CREATE TABLE IF NOT EXISTS system_build_properties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_key TEXT NOT NULL UNIQUE,
        property_value TEXT
    );
    CREATE TABLE IF NOT EXISTS system_apps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT NOT NULL,
        apk_path TEXT NOT NULL,
        version_name TEXT,
        version_code TEXT,
        is_system_app INTEGER DEFAULT 1,
        is_privileged INTEGER DEFAULT 0,
        UNIQUE(package_name, apk_path)
    );
    CREATE TABLE IF NOT EXISTS framework_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL UNIQUE,
        file_type TEXT,
        file_size INTEGER
    );
    CREATE TABLE IF NOT EXISTS sms_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id INTEGER,
        address TEXT,
        person TEXT,
        date INTEGER,
        date_sent INTEGER,
        read INTEGER,
        status INTEGER,
        type INTEGER,
        body TEXT,
        service_center TEXT
    );
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_contact_id INTEGER,
        display_name TEXT,
        phone_number TEXT,
        email TEXT,
        account_type TEXT,
        account_name TEXT
    );
    CREATE TABLE IF NOT EXISTS call_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT,
        date INTEGER,
        duration INTEGER,
        type INTEGER,
        name TEXT,
        geocoded_location TEXT
    );
    CREATE TABLE IF NOT EXISTS whatsapp_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT,
        receiver TEXT,
        content TEXT,
        timestamp INTEGER,
        media_url TEXT,
        media_type TEXT
    );
    CREATE TABLE IF NOT EXISTS telegram_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT,
        receiver TEXT,
        content TEXT,
        timestamp INTEGER,
        media_url TEXT,
        media_type TEXT
    );
    CREATE TABLE IF NOT EXISTS wechat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_path TEXT,
        sender TEXT,
        receiver TEXT,
        content TEXT,
        timestamp INTEGER,
        media_url TEXT,
        media_type TEXT,
        msg_type INTEGER DEFAULT 1,
        is_send INTEGER DEFAULT 0,
        chatroom_name TEXT,
        sender_nickname TEXT,
        talker TEXT
    );
    CREATE TABLE IF NOT EXISTS wechat_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        nickname TEXT,
        remark TEXT,
        avatar_path TEXT,
        type INTEGER,
        chatroom_flag INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS wechat_chatrooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chatroom_name TEXT UNIQUE,
        owner TEXT,
        member_list TEXT,
        member_count INTEGER,
        create_time INTEGER
    );
    CREATE TABLE IF NOT EXISTS wechat_owner_info (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        nickname TEXT,
        uin INTEGER,
        imei TEXT
    );
    CREATE TABLE IF NOT EXISTS wifi_networks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ssid TEXT NOT NULL,
        pre_shared_key TEXT,
        key_mgmt TEXT,
        last_connected INTEGER
    );
    CREATE TABLE IF NOT EXISTS chrome_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL,
        title TEXT,
        visit_count INTEGER,
        last_visit_time INTEGER,
        typed_count INTEGER
    );
    CREATE TABLE IF NOT EXISTS installed_packages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT NOT NULL UNIQUE,
        code_path TEXT,
        native_library_path TEXT,
        first_install_time INTEGER,
        last_update_time INTEGER,
        version TEXT,
        installer TEXT
    );
    CREATE TABLE IF NOT EXISTS usage_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT,
        total_time_foreground INTEGER,
        last_time_used INTEGER,
        interval_start INTEGER
    );
    CREATE TABLE IF NOT EXISTS app_database_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT NOT NULL,
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_size INTEGER DEFAULT 0,
        UNIQUE(package_name, file_path)
    );
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        log_level TEXT,
        tag TEXT,
        process TEXT,
        pid INTEGER,
        message TEXT,
        log_file TEXT,
        log_source TEXT
    );
    -- Android SSAID / per-app "Android ID" values from settings_ssaid.xml
    CREATE TABLE IF NOT EXISTS device_identifiers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        identifier_type TEXT NOT NULL,
        value TEXT NOT NULL,
        package_name TEXT,
        source_path TEXT
    );
    -- Notes recovered from plaintext note-taking app databases (generic)
    CREATE TABLE IF NOT EXISTS app_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT NOT NULL,
        note_id TEXT,
        title TEXT,
        content TEXT,
        tags TEXT,
        is_private INTEGER DEFAULT 0,
        source_db TEXT
    );
    -- Inventory of SQLCipher-encrypted app databases with their discovered key
    -- hints (password.json / shared_prefs). Whether the DB can be opened
    -- depends on the app's KDF; the hint itself is the contest answer.
    CREATE TABLE IF NOT EXISTS encrypted_db_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT NOT NULL,
        db_path TEXT NOT NULL,
        key_hint_type TEXT,
        key_hint_value TEXT,
        key_source_path TEXT,
        open_status TEXT
    );
)";

inline constexpr const char* CREATE_MIUI_TABLES = R"(
    CREATE TABLE IF NOT EXISTS miui_backup_manifest (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device TEXT, miui_version TEXT, backup_date INTEGER,
        total_size INTEGER, package_count INTEGER, source_folder TEXT
    );
    CREATE TABLE IF NOT EXISTS installed_apps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT, display_name TEXT, version_code TEXT,
        version_name TEXT, data_size INTEGER, sd_size INTEGER,
        bak_type INTEGER, manifest_summary TEXT
    );
    CREATE TABLE IF NOT EXISTS app_db_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT, db_path TEXT, table_name TEXT,
        row_count INTEGER, columns TEXT, open_status TEXT
    );
    -- External storage (sdcard/) ships beside miui_backup/ in a full MIUI
    -- export. Media and documents there are evidence in their own right, so
    -- they get a file-level inventory instead of being dropped with the .bak
    -- tar members.
    CREATE TABLE IF NOT EXISTS miui_external_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        relative_path TEXT NOT NULL,
        file_name TEXT, extension TEXT, category TEXT,
        size INTEGER DEFAULT 0, modified_time INTEGER DEFAULT 0,
        UNIQUE(relative_path)
    );
    CREATE TABLE IF NOT EXISTS qqnt_artifact_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT NOT NULL, source_path TEXT NOT NULL,
        bak_file TEXT, artifact_category TEXT, format TEXT,
        size INTEGER, modified_time INTEGER, type_flag TEXT,
        parse_status TEXT, summary TEXT, source_hash TEXT,
        UNIQUE(package_name, source_path)
    );
    CREATE TABLE IF NOT EXISTS qqnt_kv_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_path TEXT NOT NULL, namespace TEXT, key TEXT NOT NULL,
        value_type TEXT, value_text TEXT, value_hash TEXT,
        is_sensitive INTEGER DEFAULT 0, parse_status TEXT
    );
    CREATE TABLE IF NOT EXISTS qqnt_sqlite_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_path TEXT NOT NULL, table_name TEXT NOT NULL,
        record_key TEXT, record_json TEXT, artifact_kind TEXT,
        is_sensitive INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS qqnt_log_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_path TEXT NOT NULL, event_time INTEGER,
        level TEXT, tag TEXT, message TEXT,
        parse_status TEXT, is_sensitive INTEGER DEFAULT 0
    );
    -- WeChat (com.tencent.mm) evidence mirrors the QQNT inventory tables so
    -- the MIUI backup page can present file-evidence + recovered structured
    -- records alongside the existing decrypted-content tables.
    CREATE TABLE IF NOT EXISTS wechat_artifact_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT NOT NULL, source_path TEXT NOT NULL,
        bak_file TEXT, artifact_category TEXT, format TEXT,
        size INTEGER, modified_time INTEGER, type_flag TEXT,
        parse_status TEXT, summary TEXT, source_hash TEXT,
        UNIQUE(package_name, source_path)
    );
    CREATE TABLE IF NOT EXISTS wechat_kv_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_path TEXT NOT NULL, namespace TEXT, key TEXT NOT NULL,
        value_type TEXT, value_text TEXT, value_hash TEXT,
        is_sensitive INTEGER DEFAULT 0, parse_status TEXT
    );
    CREATE TABLE IF NOT EXISTS wechat_sqlite_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_path TEXT NOT NULL, table_name TEXT NOT NULL,
        record_key TEXT, record_json TEXT, artifact_kind TEXT,
        is_sensitive INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS wechat_log_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_path TEXT NOT NULL, event_time INTEGER,
        level TEXT, tag TEXT, message TEXT,
        parse_status TEXT, is_sensitive INTEGER DEFAULT 0
    );
)";

// ============================================================================
// INSERT Statements
// ============================================================================

inline constexpr const char* INSERT_BUILD_PROPERTY = 
    "INSERT OR REPLACE INTO system_build_properties (property_key, property_value) VALUES (?, ?);";

inline constexpr const char* INSERT_SYSTEM_APP = 
    "INSERT OR IGNORE INTO system_apps (package_name, apk_path, version_name, version_code, is_system_app, is_privileged) "
    "VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_FRAMEWORK_FILE = 
    "INSERT OR IGNORE INTO framework_files (file_name, file_path, file_type, file_size) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_SMS = 
    "INSERT INTO sms_messages (address, body, date, type) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_CONTACT = 
    "INSERT INTO contacts (display_name, phone_number) VALUES (?, ?);";

inline constexpr const char* INSERT_CALL_LOG = 
    "INSERT INTO call_logs (number, date, duration, type) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_WHATSAPP = 
    "INSERT INTO whatsapp_messages (sender, receiver, content, timestamp) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_TELEGRAM = 
    "INSERT INTO telegram_messages (sender, receiver, content, timestamp) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_WECHAT =
    "INSERT INTO wechat_messages (sender, receiver, content, timestamp) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_WECHAT_ENHANCED =
    "INSERT INTO wechat_messages (sender, receiver, content, timestamp, msg_type, is_send, chatroom_name, sender_nickname, talker) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_WECHAT_CONTACT =
    "INSERT OR IGNORE INTO wechat_contacts (username, nickname, remark, avatar_path, type, chatroom_flag) VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_WECHAT_CHATROOM =
    "INSERT OR IGNORE INTO wechat_chatrooms (chatroom_name, owner, member_list, member_count, create_time) VALUES (?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_WECHAT_OWNER =
    "INSERT OR REPLACE INTO wechat_owner_info (username, nickname, uin, imei) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_WIFI = 
    "INSERT INTO wifi_networks (ssid, pre_shared_key, key_mgmt) VALUES (?, ?, ?);";

inline constexpr const char* INSERT_CHROME_HISTORY = 
    "INSERT INTO chrome_history (url, title, visit_count, last_visit_time) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_INSTALLED_PACKAGE = 
    "INSERT OR REPLACE INTO installed_packages (package_name, code_path, version, installer) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_USAGE_STAT = 
    "INSERT INTO usage_stats (package_name, total_time_foreground, last_time_used, interval_start) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_APP_DATABASE_FILE = 
    "INSERT OR IGNORE INTO app_database_files (package_name, file_name, file_path, file_size) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_SYSTEM_LOG = 
    "INSERT INTO system_logs (timestamp, log_level, tag, process, pid, message, log_file, log_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

// ============================================================================
// LLM analysis progress tracking table (mirrors linux/windows *_analysis_progress)
// ============================================================================
inline constexpr const char* CREATE_ANALYSIS_PROGRESS =
    "CREATE TABLE IF NOT EXISTS android_analysis_progress ("
    "  task_id TEXT, table_name TEXT, total_artifacts INTEGER, completed_artifacts INTEGER,"
    "  started_at INTEGER, last_updated INTEGER, status TEXT"
    ");";

inline constexpr const char* CREATE_SOURCE_COVERAGE =
    "CREATE TABLE IF NOT EXISTS android_source_coverage ("
    "  artifact_kind TEXT NOT NULL, source_path TEXT NOT NULL, status TEXT NOT NULL,"
    "  detail TEXT, updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),"
    "  PRIMARY KEY (artifact_kind, source_path)"
    ");";

// Container-only provenance; original Android artifact tables are unchanged.
inline constexpr const char* CREATE_CONTAINER_PROVENANCE =
    "CREATE TABLE IF NOT EXISTS android_source_provenance ("
    "  source_container TEXT NOT NULL, source_container_sha256 TEXT NOT NULL,"
    "  source_member_path TEXT NOT NULL, normalized_android_path TEXT NOT NULL,"
    "  member_size INTEGER NOT NULL, member_sha256 TEXT NOT NULL,"
    "  adapter_type TEXT NOT NULL, adapter_version TEXT NOT NULL,"
    "  PRIMARY KEY (normalized_android_path, source_member_path)"
    ");"
    "CREATE TABLE IF NOT EXISTS android_container_coverage ("
    "  source_path TEXT NOT NULL, normalized_path TEXT NOT NULL, adapter TEXT NOT NULL,"
    "  status TEXT NOT NULL CHECK(status IN ('FOUND','PARSED','NOT_FOUND','EXTRACT_FAILED','LOCKED','UNSUPPORTED','MALFORMED')),"
    "  reason TEXT, PRIMARY KEY(source_path, normalized_path, adapter)"
    ");";

// Image-derived paths are separate from archive members. Existing artifact
// parser tables remain unchanged; every staged file has partition/inode proof.
inline constexpr const char* CREATE_FILESYSTEM_PROVENANCE =
    "CREATE TABLE IF NOT EXISTS android_filesystem_provenance ("
    "  source_evidence_id TEXT NOT NULL, source_image_sha256 TEXT NOT NULL,"
    "  container_type TEXT NOT NULL, partition_number INTEGER NOT NULL,"
    "  partition_name TEXT NOT NULL, partition_start_offset INTEGER NOT NULL,"
    "  filesystem_type TEXT NOT NULL, filesystem_object_id TEXT NOT NULL,"
    "  filesystem_path TEXT NOT NULL, normalized_android_path TEXT NOT NULL,"
    "  file_size INTEGER NOT NULL, file_sha256 TEXT NOT NULL,"
    "  reader TEXT NOT NULL, reader_version TEXT NOT NULL,"
    "  PRIMARY KEY(source_evidence_id,partition_start_offset,filesystem_object_id,normalized_android_path)"
    ");"
    "CREATE TABLE IF NOT EXISTS android_filesystem_metrics ("
    "  source_image TEXT PRIMARY KEY, filesystem_type TEXT NOT NULL,"
    "  reader TEXT NOT NULL, walk_milliseconds INTEGER NOT NULL,"
    "  indexed_file_count INTEGER NOT NULL, extracted_member_count INTEGER NOT NULL,"
    "  bytes_read INTEGER NOT NULL, analysis_milliseconds INTEGER NOT NULL"
    ");";

} // namespace AndroidAnalysisSQL

#endif // ANDROID_ANALYSIS_SQL_H
