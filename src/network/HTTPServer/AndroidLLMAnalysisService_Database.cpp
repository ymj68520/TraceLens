// AndroidLLMAnalysisService_Database.cpp
// Database operations for Android artifact LLM analysis.
// Mirrors LinuxLLMAnalysisService_Database.cpp.

#include "AndroidLLMAnalysisService.h"
#include "DatabaseManager/SQL/android_analysis_sql_llm.h"
#include <sqlite3.h>
#include <iostream>
#include <sstream>
#include <ctime>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace forensics {

bool AndroidLLMAnalysisService::storeArtifactAnalysis(sqlite3* db,
                                                      const std::string& tableName,
                                                      int64_t artifactId,
                                                      const std::string& summary,
                                                      const std::string& description,
                                                      const std::vector<std::string>& keywords,
                                                      const std::string& modelUsed) {
    std::stringstream ss;
    for (size_t i = 0; i < keywords.size(); ++i) {
        if (i > 0) ss << ",";
        ss << keywords[i];
    }
    std::string keywordsStr = ss.str();

    int64_t currentTime = static_cast<int64_t>(std::time(nullptr));

    // Generic in-place UPDATE — same 5-column shape as Linux/Windows.
    std::string updateSQL = "UPDATE " + tableName +
        " SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? "
        "WHERE id=?;";

    sqlite3_stmt* stmt = nullptr;
    int rc = sqlite3_prepare_v2(db, updateSQL.c_str(), -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to prepare statement: " << sqlite3_errmsg(db) << std::endl;
        return false;
    }

    sqlite3_bind_text(stmt, 1, summary.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, keywordsStr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 4, currentTime);
    sqlite3_bind_text(stmt, 5, modelUsed.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 6, artifactId);

    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);

    return (rc == SQLITE_DONE);
}

std::vector<AndroidLLMAnalysisService::ArtifactRecord>
AndroidLLMAnalysisService::getArtifactsFromDatabase(sqlite3* db,
                                                    const std::string& tableName,
                                                    const std::string& selectSQL,
                                                    size_t limit) {
    std::vector<ArtifactRecord> artifacts;

    // The single LIMIT ? placeholder is substituted inline (mirrors Linux).
    std::string query = selectSQL;
    size_t pos = query.find("?");
    if (pos != std::string::npos) {
        query.replace(pos, 1, std::to_string(limit));
    }

    sqlite3_stmt* stmt = nullptr;
    int rc = sqlite3_prepare_v2(db, query.c_str(), -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to prepare query: " << sqlite3_errmsg(db) << std::endl;
        return artifacts;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        ArtifactRecord record;
        record.id = sqlite3_column_int64(stmt, 0);
        record.type = tableName;

        // Build a JSON representation of the remaining columns.
        json artifactJson;
        int columnCount = sqlite3_column_count(stmt);
        for (int i = 1; i < columnCount; ++i) {
            const char* colName = sqlite3_column_name(stmt, i);
            const char* colValue = reinterpret_cast<const char*>(sqlite3_column_text(stmt, i));
            if (colValue) {
                artifactJson[colName] = colValue;
            }
        }
        record.data = artifactJson.dump();
        artifacts.push_back(record);
    }

    sqlite3_finalize(stmt);
    return artifacts;
}

std::string AndroidLLMAnalysisService::getTableNameForType(ArtifactType type) {
    switch (type) {
        case ArtifactType::SMS: return "sms_messages";
        case ArtifactType::WECHAT_MESSAGE: return "wechat_messages";
        case ArtifactType::WHATSAPP: return "whatsapp_messages";
        case ArtifactType::TELEGRAM: return "telegram_messages";
        case ArtifactType::CONTACT: return "contacts";
        case ArtifactType::CALL_LOG: return "call_logs";
        case ArtifactType::MIUI_MANIFEST: return "miui_backup_manifest";
        case ArtifactType::INSTALLED_APP: return "installed_apps";
        case ArtifactType::WECHAT_SQLITE_RECORD: return "wechat_sqlite_records";
        case ArtifactType::WECHAT_KV_RECORD: return "wechat_kv_records";
        case ArtifactType::QQNT_SQLITE_RECORD: return "qqnt_sqlite_records";
        case ArtifactType::SYSTEM_LOG: return "system_logs";
        case ArtifactType::DEVICE_IDENTIFIER: return "device_identifiers";
        case ArtifactType::WIFI_NETWORK: return "wifi_networks";
        default: return "";
    }
}

std::string AndroidLLMAnalysisService::getSelectSQLForType(ArtifactType type) {
    namespace A = android_analysis_sql_llm;
    switch (type) {
        case ArtifactType::SMS: return A::SELECT_SMS_PENDING_ANALYSIS;
        case ArtifactType::WECHAT_MESSAGE: return A::SELECT_WECHAT_MESSAGES_PENDING_ANALYSIS;
        case ArtifactType::WHATSAPP: return A::SELECT_WHATSAPP_PENDING_ANALYSIS;
        case ArtifactType::TELEGRAM: return A::SELECT_TELEGRAM_PENDING_ANALYSIS;
        case ArtifactType::CONTACT: return A::SELECT_CONTACTS_PENDING_ANALYSIS;
        case ArtifactType::CALL_LOG: return A::SELECT_CALL_LOGS_PENDING_ANALYSIS;
        case ArtifactType::MIUI_MANIFEST: return A::SELECT_MIUI_MANIFEST_PENDING_ANALYSIS;
        case ArtifactType::INSTALLED_APP: return A::SELECT_INSTALLED_APPS_PENDING_ANALYSIS;
        case ArtifactType::WECHAT_SQLITE_RECORD: return A::SELECT_WECHAT_SQLITE_RECORDS_PENDING_ANALYSIS;
        case ArtifactType::WECHAT_KV_RECORD: return A::SELECT_WECHAT_KV_RECORDS_PENDING_ANALYSIS;
        case ArtifactType::QQNT_SQLITE_RECORD: return A::SELECT_QQNT_SQLITE_RECORDS_PENDING_ANALYSIS;
        case ArtifactType::SYSTEM_LOG: return A::SELECT_SYSTEM_LOGS_PENDING_ANALYSIS;
        case ArtifactType::DEVICE_IDENTIFIER: return A::SELECT_DEVICE_IDENTIFIERS_PENDING_ANALYSIS;
        case ArtifactType::WIFI_NETWORK: return A::SELECT_WIFI_NETWORKS_PENDING_ANALYSIS;
        default: return "";
    }
}

} // namespace forensics
