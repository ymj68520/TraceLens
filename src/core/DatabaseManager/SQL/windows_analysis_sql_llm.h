// windows_analysis_sql_llm.h
// LLM analysis SQL statements for Windows forensic analysis database

#pragma once
#ifndef WINDOWS_ANALYSIS_SQL_LLM_H
#define WINDOWS_ANALYSIS_SQL_LLM_H

namespace windows_analysis_sql_llm {

// ============================================================================
// LLM Analysis UPDATE Statements
// ============================================================================

inline constexpr const char* UPDATE_REGISTRY_LLM_ANALYSIS =
    "UPDATE registry_values SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_EVENT_LOG_LLM_ANALYSIS =
    "UPDATE event_logs SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_PREFETCH_LLM_ANALYSIS =
    "UPDATE prefetch_files SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_LNK_LLM_ANALYSIS =
    "UPDATE lnk_files SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_JUMP_LIST_LLM_ANALYSIS =
    "UPDATE jump_list_entries SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_BROWSER_HISTORY_LLM_ANALYSIS =
    "UPDATE browser_history SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_BROWSER_DOWNLOAD_LLM_ANALYSIS =
    "UPDATE browser_downloads SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_BROWSER_BOOKMARK_LLM_ANALYSIS =
    "UPDATE browser_bookmarks SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_BROWSER_LOGIN_LLM_ANALYSIS =
    "UPDATE browser_logins SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_MFT_LLM_ANALYSIS =
    "UPDATE mft_entries SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_WINDOWS_SERVICE_LLM_ANALYSIS =
    "UPDATE windows_services SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_SCHEDULED_TASK_LLM_ANALYSIS =
    "UPDATE scheduled_tasks SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_AMCACHE_LLM_ANALYSIS =
    "UPDATE amcache_entries SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

inline constexpr const char* UPDATE_SRUM_LLM_ANALYSIS =
    "UPDATE srum_entries SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE id=?;";

// ============================================================================
// LLM Analysis SELECT Statements (Pending Analysis)
// ============================================================================

inline constexpr const char* SELECT_REGISTRY_PENDING_ANALYSIS =
    "SELECT id, hive_path, key_path, value_name, value_data FROM registry_values WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_EVENT_LOGS_PENDING_ANALYSIS =
    "SELECT id, record_id, event_id, level, source, message FROM event_logs WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_PREFETCH_PENDING_ANALYSIS =
    "SELECT id, file_path, executable_name, executable_path, run_count FROM prefetch_files WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_LNK_PENDING_ANALYSIS =
    "SELECT id, lnk_path, target_path, working_directory, arguments FROM lnk_files WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_JUMP_LIST_PENDING_ANALYSIS =
    "SELECT id, app_id, entry_path, entry_name, access_count FROM jump_list_entries WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_BROWSER_HISTORY_PENDING_ANALYSIS =
    "SELECT id, browser_name, url, title, visit_count FROM browser_history WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_BROWSER_DOWNLOAD_PENDING_ANALYSIS =
    "SELECT id, browser_name, url, file_name, file_size FROM browser_downloads WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_BROWSER_BOOKMARK_PENDING_ANALYSIS =
    "SELECT id, browser_name, url, title, folder_path FROM browser_bookmarks WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_BROWSER_LOGIN_PENDING_ANALYSIS =
    "SELECT id, browser_name, url, username FROM browser_logins WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_MFT_PENDING_ANALYSIS =
    "SELECT id, file_path, file_name, is_directory, is_deleted FROM mft_entries WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_WINDOWS_SERVICE_PENDING_ANALYSIS =
    "SELECT id, service_name, display_name, image_path, start_type FROM windows_services WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_SCHEDULED_TASK_PENDING_ANALYSIS =
    "SELECT id, task_name, task_path, action_type, action_path FROM scheduled_tasks WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_AMCACHE_PENDING_ANALYSIS =
    "SELECT id, file_path, file_name, company_name, product_name FROM amcache_entries WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

inline constexpr const char* SELECT_SRUM_PENDING_ANALYSIS =
    "SELECT id, app_name, user_name, timestamp, bytes_received FROM srum_entries WHERE llm_analyzed_at IS NULL ORDER BY id LIMIT ?;";

// ============================================================================
// LLM Analysis Progress Tracking
// ============================================================================

inline constexpr const char* INSERT_WINDOWS_ANALYSIS_PROGRESS =
    "INSERT INTO windows_analysis_progress (task_id, table_name, total_artifacts, completed_artifacts, started_at, last_updated, status) "
    "VALUES (?, ?, 0, 0, ?, ?, 'running');";

inline constexpr const char* UPDATE_WINDOWS_ANALYSIS_PROGRESS =
    "UPDATE windows_analysis_progress SET completed_artifacts=?, last_updated=? WHERE task_id=?;";

inline constexpr const char* COMPLETE_WINDOWS_ANALYSIS_PROGRESS =
    "UPDATE windows_analysis_progress SET completed_artifacts=total_artifacts, status='completed', last_updated=? WHERE task_id=?;";

} // namespace windows_analysis_sql_llm

#endif // WINDOWS_ANALYSIS_SQL_LLM_H
