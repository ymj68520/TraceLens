// android_analysis_sql_llm.h
// LLM analysis SQL statements for the Android forensic analysis database.
// Mirrors linux_analysis_sql_llm.h / windows_analysis_sql_llm.h: every artifact
// table carries the 5 llm_* columns (added by AndroidAnalysisDatabase::addLlmColumns),
// and a SELECT_*_PENDING_ANALYSIS statement fetches unanalyzed rows for a given type.

#pragma once
#ifndef ANDROID_ANALYSIS_SQL_LLM_H
#define ANDROID_ANALYSIS_SQL_LLM_H

namespace android_analysis_sql_llm {

// ============================================================================
// LLM Analysis SELECT Statements (Pending Analysis)
// Each selects the id first, then the forensically-relevant columns; rows are
// filtered to llm_analyzed_at IS NULL and ordered by relevance. LIMIT ? is the
// single placeholder substituted by getArtifactsFromDatabase().
// ============================================================================

inline constexpr const char* SELECT_SMS_PENDING_ANALYSIS =
    "SELECT id, address, person, date, date_sent, type, body, service_center "
    "FROM sms_messages WHERE llm_analyzed_at IS NULL ORDER BY date DESC LIMIT ?;";

inline constexpr const char* SELECT_WECHAT_MESSAGES_PENDING_ANALYSIS =
    "SELECT id, sender, receiver, content, timestamp, media_type, msg_type, is_send, "
    "chatroom_name, sender_nickname, talker "
    "FROM wechat_messages WHERE llm_analyzed_at IS NULL ORDER BY timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_WHATSAPP_PENDING_ANALYSIS =
    "SELECT id, sender, receiver, content, timestamp, media_type "
    "FROM whatsapp_messages WHERE llm_analyzed_at IS NULL ORDER BY timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_TELEGRAM_PENDING_ANALYSIS =
    "SELECT id, sender, receiver, content, timestamp, media_type "
    "FROM telegram_messages WHERE llm_analyzed_at IS NULL ORDER BY timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_CONTACTS_PENDING_ANALYSIS =
    "SELECT id, display_name, phone_number, email, account_type, account_name "
    "FROM contacts WHERE llm_analyzed_at IS NULL ORDER BY display_name LIMIT ?;";

inline constexpr const char* SELECT_CALL_LOGS_PENDING_ANALYSIS =
    "SELECT id, number, date, duration, type, name, geocoded_location "
    "FROM call_logs WHERE llm_analyzed_at IS NULL ORDER BY date DESC LIMIT ?;";

inline constexpr const char* SELECT_MIUI_MANIFEST_PENDING_ANALYSIS =
    "SELECT id, device, miui_version, backup_date, total_size, package_count, source_folder "
    "FROM miui_backup_manifest WHERE llm_analyzed_at IS NULL ORDER BY backup_date DESC LIMIT ?;";

inline constexpr const char* SELECT_INSTALLED_APPS_PENDING_ANALYSIS =
    "SELECT id, package_name, display_name, version_code, version_name, data_size, sd_size, bak_type, manifest_summary "
    "FROM installed_apps WHERE llm_analyzed_at IS NULL ORDER BY data_size DESC LIMIT ?;";

inline constexpr const char* SELECT_WECHAT_SQLITE_RECORDS_PENDING_ANALYSIS =
    "SELECT id, source_path, table_name, record_key, record_json, artifact_kind, is_sensitive "
    "FROM wechat_sqlite_records WHERE llm_analyzed_at IS NULL ORDER BY is_sensitive DESC, id LIMIT ?;";

inline constexpr const char* SELECT_WECHAT_KV_RECORDS_PENDING_ANALYSIS =
    // Prioritize sensitive tokens/identifiers (uin/imei/imei/mac/device).
    "SELECT id, source_path, namespace, key, value_type, value_text, is_sensitive, parse_status "
    "FROM wechat_kv_records WHERE llm_analyzed_at IS NULL ORDER BY is_sensitive DESC, id LIMIT ?;";

inline constexpr const char* SELECT_QQNT_SQLITE_RECORDS_PENDING_ANALYSIS =
    "SELECT id, source_path, table_name, record_key, record_json, artifact_kind, is_sensitive "
    "FROM qqnt_sqlite_records WHERE llm_analyzed_at IS NULL ORDER BY is_sensitive DESC, id LIMIT ?;";

inline constexpr const char* SELECT_SYSTEM_LOGS_PENDING_ANALYSIS =
    "SELECT id, timestamp, log_level, tag, process, pid, message, log_file, log_source "
    "FROM system_logs WHERE llm_analyzed_at IS NULL ORDER BY timestamp DESC LIMIT ?;";

inline constexpr const char* SELECT_DEVICE_IDENTIFIERS_PENDING_ANALYSIS =
    "SELECT id, identifier_type, value, package_name, source_path "
    "FROM device_identifiers WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_WIFI_NETWORKS_PENDING_ANALYSIS =
    "SELECT id, ssid, pre_shared_key, key_mgmt, last_connected "
    "FROM wifi_networks WHERE llm_analyzed_at IS NULL ORDER BY last_connected DESC LIMIT ?;";

// ============================================================================
// LLM Analysis Progress Tracking
// ============================================================================

inline constexpr const char* INSERT_ANDROID_ANALYSIS_PROGRESS =
    "INSERT INTO android_analysis_progress (task_id, table_name, total_artifacts, completed_artifacts, started_at, last_updated, status) "
    "VALUES (?, ?, 0, 0, ?, ?, 'running');";

inline constexpr const char* UPDATE_ANDROID_ANALYSIS_PROGRESS =
    "UPDATE android_analysis_progress SET completed_artifacts=?, last_updated=? WHERE task_id=?;";

inline constexpr const char* COMPLETE_ANDROID_ANALYSIS_PROGRESS =
    "UPDATE android_analysis_progress SET completed_artifacts=total_artifacts, status='completed', last_updated=? WHERE task_id=?;";

} // namespace android_analysis_sql_llm

#endif // ANDROID_ANALYSIS_SQL_LLM_H
