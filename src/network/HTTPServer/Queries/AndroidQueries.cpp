#include "../SQLiteHelper.h"
#include <iostream>
#include <algorithm>
#include <ctime>
#include <regex>
#include <sstream>
#include <iomanip>

using json = nlohmann::json;

// ============================================================================
// ANDROID FORENSICS IMPLEMENTATION
// ============================================================================

json SQLiteHelper::get_android_communication_summary(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    // SMS summary
    if (table_exists(db, "sms_messages")) {
        result["sms_summary"] = execute_query(db, "SELECT COUNT(*) as total_sms FROM sms_messages");
        result["sms_by_type"] = execute_query(db, "SELECT type, COUNT(*) as count FROM sms_messages GROUP BY type");
    } else {
        result["sms_summary"] = json::array();
        result["sms_by_type"] = json::array();
    }

    // WhatsApp summary
    if (table_exists(db, "whatsapp_messages")) {
        result["whatsapp_summary"] = execute_query(db, "SELECT COUNT(*) as total_messages FROM whatsapp_messages");
        result["whatsapp_by_type"] = execute_query(db, R"(
            SELECT CASE
                WHEN message_from_me = 1 THEN 'sent'
                ELSE 'received'
            END as direction, COUNT(*) as count
            FROM whatsapp_messages
            GROUP BY message_from_me
        )");
    } else {
        result["whatsapp_summary"] = json::array();
        result["whatsapp_by_type"] = json::array();
    }

    // Contacts
    if (table_exists(db, "contacts")) {
        result["contacts_summary"] = execute_query(db, "SELECT COUNT(*) as total_contacts FROM contacts");
    } else {
        result["contacts_summary"] = json::array();
    }

    // Call logs
    if (table_exists(db, "call_logs")) {
        result["call_summary"] = execute_query(db, "SELECT COUNT(*) as total_calls FROM call_logs");
        result["call_by_type"] = execute_query(db, "SELECT type, COUNT(*) as count FROM call_logs GROUP BY type");
    } else {
        result["call_summary"] = json::array();
        result["call_by_type"] = json::array();
    }

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_android_app_usage(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    // Installed apps
    if (table_exists(db, "installed_packages")) {
        result["installed_apps"] = execute_query(db, R"(
            SELECT package_name, app_name, version_code, version_name,
                   first_install_time, last_update_time
            FROM installed_packages
            ORDER BY last_update_time DESC
        )");
    } else {
        result["installed_apps"] = json::array();
    }

    // Usage stats
    if (table_exists(db, "usage_stats")) {
        result["usage_statistics"] = execute_query(db, R"(
            SELECT package_name, total_time_in_foreground, last_time_used,
                   total_time_in_foreground / 1000 as seconds_used
            FROM usage_stats
            WHERE total_time_in_foreground > 0
            ORDER BY total_time_in_foreground DESC
            LIMIT 100
        )");
    } else {
        result["usage_statistics"] = json::array();
    }

    // System apps
    if (table_exists(db, "system_apps")) {
        result["system_apps_count"] = execute_query(db, "SELECT COUNT(*) as system_app_count FROM system_apps");
    } else {
        result["system_apps_count"] = json::array();
    }

    // App database files
    if (table_exists(db, "app_database_files")) {
        result["app_database_files"] = execute_query(db, R"(
            SELECT package_name, file_name, file_path, file_size
            FROM app_database_files
            ORDER BY package_name, file_name
        )");
    } else {
        result["app_database_files"] = json::array();
    }

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_android_device_info(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    // Build properties
    if (table_exists(db, "system_build_properties")) {
        result["build_properties"] = execute_query(db, "SELECT property_name, property_value FROM system_build_properties");
    } else {
        result["build_properties"] = json::array();
    }

    // WiFi networks
    if (table_exists(db, "wifi_networks")) {
        result["wifi_networks"] = execute_query(db, R"(
            SELECT ssid, bssid, frequency, level, capabilities
            FROM wifi_networks
            ORDER BY level DESC
        )");
    } else {
        result["wifi_networks"] = json::array();
    }

    // Chrome history
    if (table_exists(db, "chrome_history")) {
        result["chrome_history"] = execute_query(db, R"(
            SELECT url, title, visit_count, last_visit_time
            FROM chrome_history
            ORDER BY visit_count DESC
            LIMIT 50
        )");
    } else {
        result["chrome_history"] = json::array();
    }

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_android_media_analysis(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    // Framework media files
    if (table_exists(db, "framework_files")) {
        json media_files = execute_query(db, R"(
            SELECT file_path, file_size, mime_type
            FROM framework_files
            WHERE mime_type LIKE 'image/%' OR mime_type LIKE 'video/%' OR mime_type LIKE 'audio/%'
            ORDER BY file_size DESC
            LIMIT 100
        )");

        // Media files by type
        json media_by_type = execute_query(db, R"(
            SELECT
                CASE
                    WHEN mime_type LIKE 'image/%' THEN 'images'
                    WHEN mime_type LIKE 'video/%' THEN 'videos'
                    WHEN mime_type LIKE 'audio/%' THEN 'audio'
                    ELSE 'other'
                END as media_type,
                COUNT(*) as file_count,
                SUM(file_size) as total_size
            FROM framework_files
            WHERE mime_type IS NOT NULL
            GROUP BY media_type
        )");

        result["media_files"] = media_files;
        result["media_by_type"] = media_by_type;
    } else {
        result["media_files"] = json::array();
        result["media_by_type"] = json::array();
    }

    sqlite3_close(db);
    return result;
}

// ============================================================================
// MIUI OFFLINE-BACKUP FORENSICS IMPLEMENTATION
// These tables are populated only by the miui-backup source mode
// (MiuiBackupExtractor + MiuiArtifactParsers):
//   miui_backup_manifest, installed_apps, app_db_inventory
// ============================================================================

json SQLiteHelper::get_miui_backup_overview(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    // Backup manifest (single row)
    if (table_exists(db, "miui_backup_manifest")) {
        json manifest = execute_query(db, R"(
            SELECT device, miui_version, backup_date, total_size,
                   package_count, source_folder
            FROM miui_backup_manifest
            LIMIT 1
        )");
        // execute_query returns an array of row-objects; take the first row
        result["manifest"] = manifest.empty() ? json::object() : manifest[0];
    } else {
        result["manifest"] = json::object();
    }

    // App-DB decryption status distribution, sourced from app_db_inventory.
    if (table_exists(db, "app_db_inventory")) {
        result["decryption_status"] = execute_query(db, R"(
            SELECT open_status, COUNT(*) as count
            FROM app_db_inventory
            GROUP BY open_status
            ORDER BY count DESC
        )");
    } else {
        result["decryption_status"] = json::array();
    }

    // WeChat graph data is written into the same Android result database.
    // Expose a compact summary so the MIUI page can link to the graph without
    // making a second task/database discovery request.
    json wechat = {
        {"available", false},
        {"status", "not_found"},
        {"messages", 0},
        {"contacts", 0},
        {"chatrooms", 0},
        {"owners", 0},
    };
    const auto countRows = [&](const char* table) -> int64_t {
        if (!table_exists(db, table)) return 0;
        const std::string sql = std::string("SELECT COUNT(*) AS count FROM ") + table;
        const json rows = execute_query(db, sql);
        return rows.empty() ? 0 : rows[0].value("count", 0);
    };
    const int64_t messages = countRows("wechat_messages");
    const int64_t contacts = countRows("wechat_contacts");
    const int64_t chatrooms = countRows("wechat_chatrooms");
    const int64_t owners = countRows("wechat_owner_info");
    wechat["messages"] = messages;
    wechat["contacts"] = contacts;
    wechat["chatrooms"] = chatrooms;
    wechat["owners"] = owners;
    wechat["available"] = messages > 0 || contacts > 0 || chatrooms > 0 || owners > 0;
    if (wechat["available"].get<bool>()) {
        wechat["status"] = "parsed";
    } else if (table_exists(db, "app_db_inventory")) {
        const json locked = execute_query(db, R"(
            SELECT open_status, COUNT(*) AS count
            FROM app_db_inventory
            WHERE package_name = 'com.tencent.mm'
            GROUP BY open_status
            ORDER BY CASE open_status
                WHEN 'decrypted' THEN 1
                WHEN 'recognized' THEN 2
                WHEN 'encrypted_locked' THEN 3
                ELSE 4 END
        )");
        if (!locked.empty()) {
            wechat["status"] = locked[0].value("open_status", "recognized");
        }
    }
    result["wechat_summary"] = wechat;

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_miui_installed_apps(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    // Per-package manifest rows (one per backed-up package/feature)
    if (table_exists(db, "installed_apps")) {
        result["apps"] = execute_query(db, R"(
            SELECT package_name, display_name, version_code, version_name,
                   data_size, sd_size, bak_type, manifest_summary
            FROM installed_apps
            ORDER BY data_size DESC
        )");
    } else {
        result["apps"] = json::array();
    }

    // bak_type summary: 1 = system app, 2 = user app
    if (table_exists(db, "installed_apps")) {
        result["bak_type_summary"] = execute_query(db, R"(
            SELECT bak_type, COUNT(*) as count
            FROM installed_apps
            GROUP BY bak_type
            ORDER BY bak_type
        )");
    } else {
        result["bak_type_summary"] = json::array();
    }

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_miui_db_inventory(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    if (table_exists(db, "app_db_inventory")) {
        result["inventory"] = execute_query(db, R"(
            SELECT package_name, db_path, table_name, row_count,
                   columns, open_status
            FROM app_db_inventory
            ORDER BY package_name, db_path, table_name
        )");
        result["package_summary"] = execute_query(db, R"(
            SELECT package_name,
                   COUNT(DISTINCT db_path) AS db_count,
                   COUNT(*) AS table_count,
                   SUM(row_count) AS total_rows
            FROM app_db_inventory
            GROUP BY package_name
            ORDER BY db_count DESC, package_name
        )");
    } else {
        result["inventory"] = json::array();
        result["package_summary"] = json::array();
    }

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_miui_qqnt_overview(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    result["artifact_categories"] = table_exists(db, "qqnt_artifact_inventory")
        ? execute_query(db, "SELECT artifact_category, parse_status, COUNT(*) AS count "
                            "FROM qqnt_artifact_inventory "
                            "GROUP BY artifact_category, parse_status "
                            "ORDER BY artifact_category, parse_status")
        : json::array();
    auto countRows = [&](const char* tableName) -> int64_t {
        if (!table_exists(db, tableName)) return 0;
        const json rows = execute_query(db, "SELECT COUNT(*) AS count FROM " + std::string(tableName));
        return rows.empty() ? 0 : rows[0].value("count", 0LL);
    };
    result["record_counts"] = {
        {"kv", countRows("qqnt_kv_records")},
        {"sqlite", countRows("qqnt_sqlite_records")},
        {"logs", countRows("qqnt_log_events")}
    };
    result["log_time_range"] = table_exists(db, "qqnt_log_events")
        ? execute_query(db, "SELECT MIN(event_time) AS start_time, MAX(event_time) AS end_time "
                            "FROM qqnt_log_events WHERE event_time > 0")
        : json::array();

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_miui_qqnt_artifacts(const std::string& android_db,
                                           const std::string& category,
                                           const std::string& status,
                                           const std::string& query,
                                           int limit, int offset) {
    json result = {{"items", json::array()}, {"total", 0}};
    sqlite3* db = open_database(android_db, result);
    if (!db || !table_exists(db, "qqnt_artifact_inventory")) {
        if (db) sqlite3_close(db);
        return result;
    }

    limit = std::clamp(limit, 1, 500);
    offset = std::max(offset, 0);
    std::string where = " WHERE 1=1";
    std::vector<std::string> parameters;
    if (!category.empty()) {
        where += " AND artifact_category = ?";
        parameters.push_back(category);
    }
    if (!status.empty()) {
        where += " AND parse_status = ?";
        parameters.push_back(status);
    }
    if (!query.empty()) {
        where += " AND (source_path LIKE ? OR summary LIKE ?)";
        const std::string pattern = "%" + query + "%";
        parameters.push_back(pattern);
        parameters.push_back(pattern);
    }

    const json count = execute_query(db,
        "SELECT COUNT(*) AS count FROM qqnt_artifact_inventory" + where, parameters);
    result["total"] = count.empty() ? 0 : count[0].value("count", 0);
    std::vector<std::string> itemParameters = parameters;
    itemParameters.push_back(std::to_string(limit));
    itemParameters.push_back(std::to_string(offset));
    result["items"] = execute_query(db,
        "SELECT id, source_path, bak_file, artifact_category, format, size, modified_time, "
        "type_flag, parse_status, summary, source_hash FROM qqnt_artifact_inventory" + where +
        " ORDER BY modified_time DESC, source_path LIMIT ? OFFSET ?", itemParameters);
    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_miui_qqnt_records(const std::string& android_db,
                                         const std::string& kind, const std::string& query,
                                         int limit, int offset, bool revealSensitive) {
    json result = {{"items", json::array()}, {"total", 0}};
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;
    limit = std::clamp(limit, 1, 500);
    offset = std::max(offset, 0);
    std::string source;
    std::string projection;
    std::string searchable;
    if (kind == "sqlite") {
        source = "qqnt_sqlite_records";
        projection = "id, source_path, table_name AS label, record_key, record_json AS value_text, "
                     "artifact_kind AS value_type, is_sensitive, 'sqlite' AS record_kind";
        searchable = "source_path || ' ' || table_name || ' ' || record_json";
    } else if (kind == "logs") {
        source = "qqnt_log_events";
        projection = "id, source_path, tag AS label, CAST(event_time AS TEXT) AS record_key, "
                     "message AS value_text, level AS value_type, is_sensitive, 'logs' AS record_kind";
        searchable = "source_path || ' ' || tag || ' ' || message";
    } else if (kind == "kv") {
        source = "qqnt_kv_records";
        projection = "id, source_path, key AS label, namespace AS record_key, value_text, "
                     "value_type, is_sensitive, 'kv' AS record_kind";
        searchable = "source_path || ' ' || key || ' ' || value_text";
    } else {
        result["error"] = "kind must be one of: kv, sqlite, logs";
        sqlite3_close(db);
        return result;
    }
    if (!table_exists(db, source)) {
        sqlite3_close(db);
        return result;
    }

    // Surface the per-artifact AI analysis columns when present (added by
    // AndroidLLMAnalysisService via AndroidAnalysisDatabase::addLlmColumns).
    if (column_exists(db, source, "llm_summary")) {
        projection += ", llm_summary, llm_description, llm_keywords, llm_analyzed_at, llm_model_used";
    } else {
        projection += ", NULL AS llm_summary, NULL AS llm_description, NULL AS llm_keywords, "
                      "NULL AS llm_analyzed_at, NULL AS llm_model_used";
    }

    const std::string where = query.empty() ? "" : " WHERE " + searchable + " LIKE ?";
    std::vector<std::string> parameters;
    if (!query.empty()) parameters.push_back("%" + query + "%");
    const json count = execute_query(db, "SELECT COUNT(*) AS count FROM " + source + where, parameters);
    result["total"] = count.empty() ? 0 : count[0].value("count", 0);
    parameters.push_back(std::to_string(limit));
    parameters.push_back(std::to_string(offset));
    json items = execute_query(db, "SELECT " + projection + " FROM " + source + where +
                                " ORDER BY id DESC LIMIT ? OFFSET ?", parameters);
    if (!revealSensitive) {
        for (auto& item : items) {
            if (item.value("is_sensitive", 0) != 0) item["value_text"] = "[已脱敏：点击显示原值]";
        }
    }
    result["items"] = std::move(items);
    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_miui_wechat_overview(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    result["artifact_categories"] = table_exists(db, "wechat_artifact_inventory")
        ? execute_query(db, "SELECT artifact_category, parse_status, COUNT(*) AS count "
                            "FROM wechat_artifact_inventory "
                            "GROUP BY artifact_category, parse_status "
                            "ORDER BY artifact_category, parse_status")
        : json::array();
    auto countRows = [&](const char* tableName) -> int64_t {
        if (!table_exists(db, tableName)) return 0;
        const json rows = execute_query(db, "SELECT COUNT(*) AS count FROM " + std::string(tableName));
        return rows.empty() ? 0 : rows[0].value("count", 0LL);
    };
    result["record_counts"] = {
        {"kv", countRows("wechat_kv_records")},
        {"sqlite", countRows("wechat_sqlite_records")},
        {"logs", countRows("wechat_log_events")}
    };
    result["log_time_range"] = table_exists(db, "wechat_log_events")
        ? execute_query(db, "SELECT MIN(event_time) AS start_time, MAX(event_time) AS end_time "
                            "FROM wechat_log_events WHERE event_time > 0")
        : json::array();

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_miui_wechat_artifacts(const std::string& android_db,
                                             const std::string& category,
                                             const std::string& status,
                                             const std::string& query,
                                             int limit, int offset) {
    json result = {{"items", json::array()}, {"total", 0}};
    sqlite3* db = open_database(android_db, result);
    if (!db || !table_exists(db, "wechat_artifact_inventory")) {
        if (db) sqlite3_close(db);
        return result;
    }

    limit = std::clamp(limit, 1, 500);
    offset = std::max(offset, 0);
    std::string where = " WHERE 1=1";
    std::vector<std::string> parameters;
    if (!category.empty()) {
        where += " AND artifact_category = ?";
        parameters.push_back(category);
    }
    if (!status.empty()) {
        where += " AND parse_status = ?";
        parameters.push_back(status);
    }
    if (!query.empty()) {
        where += " AND (source_path LIKE ? OR summary LIKE ?)";
        const std::string pattern = "%" + query + "%";
        parameters.push_back(pattern);
        parameters.push_back(pattern);
    }

    const json count = execute_query(db,
        "SELECT COUNT(*) AS count FROM wechat_artifact_inventory" + where, parameters);
    result["total"] = count.empty() ? 0 : count[0].value("count", 0);
    std::vector<std::string> itemParameters = parameters;
    itemParameters.push_back(std::to_string(limit));
    itemParameters.push_back(std::to_string(offset));
    result["items"] = execute_query(db,
        "SELECT id, source_path, bak_file, artifact_category, format, size, modified_time, "
        "type_flag, parse_status, summary, source_hash FROM wechat_artifact_inventory" + where +
        " ORDER BY modified_time DESC, source_path LIMIT ? OFFSET ?", itemParameters);
    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_miui_wechat_records(const std::string& android_db,
                                           const std::string& kind, const std::string& query,
                                           int limit, int offset, bool revealSensitive) {
    json result = {{"items", json::array()}, {"total", 0}};
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;
    limit = std::clamp(limit, 1, 500);
    offset = std::max(offset, 0);
    std::string source;
    std::string projection;
    std::string searchable;
    if (kind == "sqlite") {
        source = "wechat_sqlite_records";
        projection = "id, source_path, table_name AS label, record_key, record_json AS value_text, "
                     "artifact_kind AS value_type, is_sensitive, 'sqlite' AS record_kind";
        searchable = "source_path || ' ' || table_name || ' ' || record_json";
    } else if (kind == "logs") {
        source = "wechat_log_events";
        projection = "id, source_path, tag AS label, CAST(event_time AS TEXT) AS record_key, "
                     "message AS value_text, level AS value_type, is_sensitive, 'logs' AS record_kind";
        searchable = "source_path || ' ' || tag || ' ' || message";
    } else if (kind == "kv") {
        source = "wechat_kv_records";
        projection = "id, source_path, key AS label, namespace AS record_key, value_text, "
                     "value_type, is_sensitive, 'kv' AS record_kind";
        searchable = "source_path || ' ' || key || ' ' || value_text";
    } else {
        result["error"] = "kind must be one of: kv, sqlite, logs";
        sqlite3_close(db);
        return result;
    }
    if (!table_exists(db, source)) {
        sqlite3_close(db);
        return result;
    }

    // Surface the per-artifact AI analysis columns when present.
    if (column_exists(db, source, "llm_summary")) {
        projection += ", llm_summary, llm_description, llm_keywords, llm_analyzed_at, llm_model_used";
    } else {
        projection += ", NULL AS llm_summary, NULL AS llm_description, NULL AS llm_keywords, "
                      "NULL AS llm_analyzed_at, NULL AS llm_model_used";
    }

    const std::string where = query.empty() ? "" : " WHERE " + searchable + " LIKE ?";
    std::vector<std::string> parameters;
    if (!query.empty()) parameters.push_back("%" + query + "%");
    const json count = execute_query(db, "SELECT COUNT(*) AS count FROM " + source + where, parameters);
    result["total"] = count.empty() ? 0 : count[0].value("count", 0);
    parameters.push_back(std::to_string(limit));
    parameters.push_back(std::to_string(offset));
    json items = execute_query(db, "SELECT " + projection + " FROM " + source + where +
                                " ORDER BY id DESC LIMIT ? OFFSET ?", parameters);
    if (!revealSensitive) {
        for (auto& item : items) {
            if (item.value("is_sensitive", 0) != 0) item["value_text"] = "[已脱敏：点击显示原值]";
        }
    }
    result["items"] = std::move(items);
    sqlite3_close(db);
    return result;
}
// Aggregate per-table AI-analysis coverage (analyzed vs total) plus a small
// sample of analyzed rows, used by the Android page's AI-overview card.
json SQLiteHelper::get_android_llm_summary(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    // Tables covered by AndroidLLMAnalysisService, with a human-readable label.
    struct TableSpec { const char* name; const char* label; };
    static const TableSpec kTables[] = {
        {"sms_messages",          "短信"},
        {"wechat_messages",       "微信消息"},
        {"whatsapp_messages",     "WhatsApp 消息"},
        {"telegram_messages",     "Telegram 消息"},
        {"contacts",              "联系人"},
        {"call_logs",             "通话记录"},
        {"miui_backup_manifest",  "备份清单"},
        {"installed_apps",        "已安装应用"},
        {"wechat_sqlite_records", "微信 SQLite 记录"},
        {"wechat_kv_records",     "微信键值记录"},
        {"qqnt_sqlite_records",   "QQ SQLite 记录"},
        {"system_logs",           "系统日志"},
        {"device_identifiers",    "设备标识"},
        {"wifi_networks",         "WiFi 网络"}
    };

    json coverage = json::array();
    int64_t totalArtifacts = 0;
    int64_t totalAnalyzed = 0;
    for (const auto& spec : kTables) {
        if (!table_exists(db, spec.name) || !column_exists(db, spec.name, "llm_analyzed_at")) {
            continue;
        }
        const json totalRow = execute_query(db,
            "SELECT COUNT(*) AS total FROM " + std::string(spec.name));
        const json analyzedRow = execute_query(db,
            "SELECT COUNT(*) AS analyzed FROM " + std::string(spec.name) +
            " WHERE llm_analyzed_at IS NOT NULL");
        int64_t total = totalRow.empty() ? 0 : totalRow[0].value("total", 0LL);
        int64_t analyzed = analyzedRow.empty() ? 0 : analyzedRow[0].value("analyzed", 0LL);
        if (total == 0) continue;
        coverage.push_back({
            {"table", spec.name}, {"label", spec.label},
            {"total", total}, {"analyzed", analyzed}
        });
        totalArtifacts += total;
        totalAnalyzed += analyzed;
    }
    result["coverage"] = std::move(coverage);
    result["totals"] = {{"total", totalArtifacts}, {"analyzed", totalAnalyzed}};

    sqlite3_close(db);
    return result;
}
