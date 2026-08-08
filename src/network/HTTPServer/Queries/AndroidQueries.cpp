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

    // Full per-DB table inventory (package x db_path x table_name)
    if (table_exists(db, "app_db_inventory")) {
        result["inventory"] = execute_query(db, R"(
            SELECT package_name, db_path, table_name, row_count,
                   columns, open_status
            FROM app_db_inventory
            ORDER BY package_name, db_path, table_name
        )");
    } else {
        result["inventory"] = json::array();
    }

    // Per-package aggregate summary (db count + total rows + decryption status)
    if (table_exists(db, "app_db_inventory")) {
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
        result["package_summary"] = json::array();
    }

    sqlite3_close(db);
    return result;
}
