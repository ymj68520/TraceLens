// windows_analysis_sql_crud.h
// SQL INSERT and SELECT statements for Windows forensic analysis database

#pragma once
#ifndef WINDOWS_ANALYSIS_SQL_CRUD_H
#define WINDOWS_ANALYSIS_SQL_CRUD_H

namespace windows_analysis_sql_crud {

// ============================================================================
// INSERT Statements
// ============================================================================

inline constexpr const char* INSERT_REGISTRY_VALUE =
    "INSERT INTO registry_values (hive_path, hive_type, key_path, value_name, value_type, value_data, last_modified, forensic_importance) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_EVENT_LOG =
    "INSERT INTO event_logs (record_id, log_source, event_id, level, timestamp, source, message, computer_name, user_sid, channel) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_PREFETCH_FILE =
    "INSERT INTO prefetch_files (file_path, executable_name, executable_path, prefetch_hash, run_count, last_run_time, creation_time, referenced_files, referenced_directories) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_LNK_FILE =
    "INSERT INTO lnk_files (lnk_path, target_path, working_directory, arguments, icon_location, creation_time, modification_time, access_time, target_size, drive_type, volume_serial, netbios_name, relative_path, description) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_JUMP_LIST_ENTRY =
    "INSERT INTO jump_list_entries (app_id, entry_path, entry_name, access_time, creation_time, access_count, is_pinned) "
    "VALUES (?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_USER_ACCOUNT =
    "INSERT INTO user_accounts (rid, username, full_name, comment, last_login, password_last_set, account_expires, password_expires, account_flags, is_admin, home_directory, profile_path) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_USB_DEVICE =
    "INSERT INTO usb_devices (vendor_id, product_id, serial_number, device_description, friendly_name, device_class, first_connected, last_connected, last_drive_letter) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_RECYCLE_BIN_ENTRY =
    "INSERT INTO recycle_bin (recycle_file_path, original_path, file_name, deletion_time, original_size, user_sid) "
    "VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_BROWSER_ARTIFACT =
    "INSERT INTO browser_artifacts (browser_name, artifact_type, url, title, timestamp, visit_count, local_path, file_size) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_MFT_ENTRY =
    "INSERT INTO mft_entries (entry_number, file_name, file_path, parent_entry, logical_size, physical_size, creation_time, modification_time, access_time, mft_modification_time, fn_creation_time, fn_modification_time, is_directory, is_deleted, has_ads, permissions) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_WINDOWS_SERVICE =
    "INSERT INTO windows_services (service_name, display_name, image_path, start_type, service_type, account_name, description, is_running) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_SCHEDULED_TASK =
    "INSERT INTO scheduled_tasks (task_name, task_path, author, description, action_type, action_path, arguments, trigger_type, last_run_time, next_run_time, status, run_as) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_AMCACHE_ENTRY =
    "INSERT INTO amcache_entries (file_path, file_hash, file_name, company_name, product_name, product_version, file_description, file_size, link_time, last_modified, language) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_SRUM_ENTRY =
    "INSERT INTO srum_entries (app_name, user_name, timestamp, bytes_received, bytes_sent, foreground_duration, background_duration, cpu_time_ms) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_WIFI_PROFILE =
    "INSERT INTO wifi_profiles (profile_name, ssid, connection_type, connection_mode, mac_address, first_connected, last_connected, dns_suffix, source_hive) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_RDP_CONNECTION =
    "INSERT INTO rdp_connections (server_address, username_hint, last_connection_time, entry_type, source_hive) "
    "VALUES (?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_SHIMCACHE_ENTRY =
    "INSERT INTO shimcache_entries (entry_path, last_modified_time, entry_size, execution_flag, data_source, source_hive) "
    "VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_USERASSIST_ENTRY =
    "INSERT INTO user_assist_entries (user_sid, entry_guid, rot13_path, decoded_path, run_count, focus_time, last_run_time, source_hive) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_SHELLBAG_ENTRY =
    "INSERT INTO shell_bag_entries (user_sid, bag_type, slot_index, shell_item_type, path, short_name, created_time, modified_time, accessed_time, source_hive) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_BROWSER_HISTORY =
    "INSERT INTO browser_history (browser_name, profile_name, url, title, visit_time, visit_duration, visit_count, visit_type, is_redirect, referrer) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_BROWSER_DOWNLOAD =
    "INSERT INTO browser_downloads (browser_name, profile_name, url, target_path, file_name, file_size, start_time, end_time, state, mime_type, referrer, received_bytes, danger_accepted) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_BROWSER_BOOKMARK =
    "INSERT INTO browser_bookmarks (browser_name, profile_name, url, title, folder_path, date_added, date_modified) "
    "VALUES (?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_BROWSER_COOKIE =
    "INSERT INTO browser_cookies (browser_name, profile_name, domain, name, path, creation_time, expiration_time, last_access_time, is_secure, is_http_only, is_persistent, same_site) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_BROWSER_LOGIN =
    "INSERT INTO browser_logins (browser_name, profile_name, url, action_url, username, encrypted_password, date_created, date_last_used, date_modified, times_used) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

// ============================================================================
// SELECT Statements
// ============================================================================

inline constexpr const char* SELECT_REGISTRY_VALUES_BASE =
    "SELECT hive_path, hive_type, key_path, value_name, value_type, value_data, last_modified, forensic_importance FROM registry_values";

inline constexpr const char* SELECT_EVENT_LOGS_BASE =
    "SELECT record_id, log_source, event_id, level, timestamp, source, message, computer_name, user_sid, channel FROM event_logs";

inline constexpr const char* SELECT_PREFETCH_FILES_BASE =
    "SELECT file_path, executable_name, executable_path, prefetch_hash, run_count, last_run_time, creation_time, referenced_files, referenced_directories FROM prefetch_files";

inline constexpr const char* SELECT_LNK_FILES_BASE =
    "SELECT lnk_path, target_path, working_directory, arguments, icon_location, creation_time, modification_time, access_time, target_size, drive_type, volume_serial, netbios_name, relative_path, description FROM lnk_files";

inline constexpr const char* SELECT_JUMP_LIST_ENTRIES_BASE =
    "SELECT app_id, entry_path, entry_name, access_time, creation_time, access_count, is_pinned FROM jump_list_entries";

inline constexpr const char* SELECT_USER_ACCOUNTS_BASE =
    "SELECT rid, username, full_name, comment, last_login, password_last_set, account_expires, password_expires, account_flags, is_admin, home_directory, profile_path FROM user_accounts";

inline constexpr const char* SELECT_USB_DEVICES_BASE =
    "SELECT vendor_id, product_id, serial_number, device_description, friendly_name, device_class, first_connected, last_connected, last_drive_letter FROM usb_devices";

inline constexpr const char* SELECT_RECYCLE_BIN_BASE =
    "SELECT recycle_file_path, original_path, file_name, deletion_time, original_size, user_sid FROM recycle_bin";

inline constexpr const char* SELECT_BROWSER_ARTIFACTS_BASE =
    "SELECT browser_name, artifact_type, url, title, timestamp, visit_count, local_path, file_size FROM browser_artifacts";

inline constexpr const char* SELECT_MFT_ENTRIES_BASE =
    "SELECT entry_number, file_name, file_path, parent_entry, logical_size, physical_size, creation_time, modification_time, access_time, mft_modification_time, fn_creation_time, fn_modification_time, is_directory, is_deleted, has_ads, permissions FROM mft_entries";

inline constexpr const char* SELECT_WINDOWS_SERVICES_BASE =
    "SELECT service_name, display_name, image_path, start_type, service_type, account_name, description, is_running FROM windows_services";

inline constexpr const char* SELECT_SCHEDULED_TASKS_BASE =
    "SELECT task_name, task_path, author, description, action_type, action_path, arguments, trigger_type, last_run_time, next_run_time, status, run_as FROM scheduled_tasks";

inline constexpr const char* SELECT_AMCACHE_ENTRIES_BASE =
    "SELECT file_path, file_hash, file_name, company_name, product_name, product_version, file_description, file_size, link_time, last_modified, language FROM amcache_entries";

inline constexpr const char* SELECT_SRUM_ENTRIES_BASE =
    "SELECT app_name, user_name, timestamp, bytes_received, bytes_sent, foreground_duration, background_duration, cpu_time_ms FROM srum_entries";

inline constexpr const char* SELECT_BROWSER_HISTORY_BASE =
    "SELECT browser_name, profile_name, url, title, visit_time, visit_duration, visit_count, visit_type, is_redirect, referrer FROM browser_history";

inline constexpr const char* SELECT_BROWSER_DOWNLOADS_BASE =
    "SELECT browser_name, profile_name, url, target_path, file_name, file_size, start_time, end_time, state, mime_type, referrer, received_bytes, danger_accepted FROM browser_downloads";

inline constexpr const char* SELECT_BROWSER_BOOKMARKS_BASE =
    "SELECT browser_name, profile_name, url, title, folder_path, date_added, date_modified FROM browser_bookmarks";

inline constexpr const char* SELECT_BROWSER_COOKIES_BASE =
    "SELECT browser_name, profile_name, domain, name, path, creation_time, expiration_time, last_access_time, is_secure, is_http_only, is_persistent, same_site FROM browser_cookies";

inline constexpr const char* SELECT_BROWSER_LOGINS_BASE =
    "SELECT browser_name, profile_name, url, action_url, username, encrypted_password, date_created, date_last_used, date_modified, times_used FROM browser_logins";

// ============================================================================
// DLL Analysis CRUD Operations
// ============================================================================

// DLL Base Info Operations
inline constexpr const char* INSERT_DLL_BASE_INFO = R"(
    INSERT INTO dll_base_info (
        inode, name, path, size, md5, sha1, sha256, imp_hash, rich_hash,
        file_format, machine_type, compile_timestamp, subsystem,
        entry_point, image_base, is_dll, characteristics,
        file_version, product_version, company_name, file_description,
        signature_status, signer_name, cert_issuer, cert_valid_from, cert_valid_to,
        mtime, ctime, atime, crtime, is_deleted, threat_score
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
)";

inline constexpr const char* SELECT_DLL_BY_INODE = R"(
    SELECT * FROM dll_base_info WHERE inode = ?;
)";

inline constexpr const char* SELECT_DLL_BY_PATH = R"(
    SELECT * FROM dll_base_info WHERE path = ?;
)";

inline constexpr const char* SELECT_DLL_BY_MD5 = R"(
    SELECT * FROM dll_base_info WHERE md5 = ?;
)";

inline constexpr const char* SELECT_DLL_BY_IMP_HASH = R"(
    SELECT * FROM dll_base_info WHERE imp_hash = ?;
)";

inline constexpr const char* SELECT_SUSPICIOUS_DLLS = R"(
    SELECT * FROM dll_base_info WHERE threat_score >= ? ORDER BY threat_score DESC;
)";

inline constexpr const char* SELECT_ALL_DLLS = R"(
    SELECT * FROM dll_base_info ORDER BY compile_timestamp DESC;
)";

inline constexpr const char* UPDATE_DLL_THREAT_SCORE = R"(
    UPDATE dll_base_info SET threat_score = ? WHERE id = ?;
)";

inline constexpr const char* UPDATE_DLL_ANALYSIS = R"(
    UPDATE dll_base_info SET
        file_format = ?, machine_type = ?, compile_timestamp = ?,
        subsystem = ?, entry_point = ?, image_base = ?, characteristics = ?,
        file_version = ?, product_version = ?, company_name = ?, file_description = ?,
        signature_status = ?, signer_name = ?,
        md5 = ?, sha1 = ?, sha256 = ?, imp_hash = ?,
        threat_score = ?
    WHERE id = ?;
)";

// DLL Section Operations
inline constexpr const char* INSERT_DLL_SECTION = R"(
    INSERT INTO dll_sections (
        dll_id, section_name, virtual_address, virtual_size,
        raw_data_size, characteristics, entropy,
        is_writeable, is_executable, is_readable
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
)";

inline constexpr const char* SELECT_DLL_SECTIONS = R"(
    SELECT * FROM dll_sections WHERE dll_id = ?;
)";

// DLL Import/Export Operations
inline constexpr const char* INSERT_DLL_IMPORT = R"(
    INSERT INTO dll_imports (dll_id, imported_dll_name, imported_function, import_ordinal, is_delayed)
    VALUES (?, ?, ?, ?, ?);
)";

inline constexpr const char* INSERT_DLL_EXPORT = R"(
    INSERT INTO dll_exports (dll_id, function_name, export_ordinal, export_rva)
    VALUES (?, ?, ?, ?);
)";

inline constexpr const char* SELECT_DLL_IMPORTS = R"(
    SELECT * FROM dll_imports WHERE dll_id = ?;
)";

inline constexpr const char* SELECT_DLL_EXPORTS = R"(
    SELECT * FROM dll_exports WHERE dll_id = ?;
)";

// DLL Anomaly Operations
inline constexpr const char* INSERT_DLL_ANOMALY = R"(
    INSERT INTO dll_anomalies (dll_id, anomaly_type, description, risk_level, risk_score, details)
    VALUES (?, ?, ?, ?, ?, ?);
)";

inline constexpr const char* SELECT_DLL_ANOMALIES = R"(
    SELECT * FROM dll_anomalies WHERE dll_id = ?;
)";

// DLL Dependency Operations
inline constexpr const char* INSERT_DLL_DEPENDENCY = R"(
    INSERT INTO dll_dependencies (parent_dll_id, child_dll_id, depth, is_resolved)
    VALUES (?, ?, ?, ?);
)";

inline constexpr const char* SELECT_DLL_DEPENDENCIES = R"(
    SELECT * FROM dll_dependencies WHERE parent_dll_id = ?;
)";

// DLL Forensic Link Operations
inline constexpr const char* INSERT_DLL_FORENSIC_LINK = R"(
    INSERT INTO dll_forensic_links (dll_id, link_type, source_id, source_data, detected_at)
    VALUES (?, ?, ?, ?, ?);
)";

inline constexpr const char* SELECT_DLL_FORENSIC_LINKS = R"(
    SELECT * FROM dll_forensic_links WHERE dll_id = ?;
)";

} // namespace windows_analysis_sql_crud

#endif // WINDOWS_ANALYSIS_SQL_CRUD_H
