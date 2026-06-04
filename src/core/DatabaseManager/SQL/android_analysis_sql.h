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
        username TEXT,
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

} // namespace AndroidAnalysisSQL

#endif // ANDROID_ANALYSIS_SQL_H
