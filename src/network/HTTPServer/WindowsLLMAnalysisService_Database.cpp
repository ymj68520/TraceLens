// WindowsLLMAnalysisService_Database.cpp
// Database operations for Windows artifact LLM analysis

#include "WindowsLLMAnalysisService.h"
#include "DatabaseManager/SQL/windows_analysis_sql.h"
#include <sqlite3.h>
#include <iostream>
#include <sstream>
#include <ctime>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace forensics {

bool WindowsLLMAnalysisService::storeArtifactAnalysis(sqlite3* db,
                                                       const std::string& tableName,
                                                       int64_t artifactId,
                                                       const std::string& summary,
                                                       const std::string& description,
                                                       const std::vector<std::string>& keywords,
                                                       const std::string& modelUsed) {
    // Convert keywords to comma-separated string
    std::stringstream ss;
    for (size_t i = 0; i < keywords.size(); ++i) {
        if (i > 0) ss << ",";
        ss << keywords[i];
    }
    std::string keywordsStr = ss.str();

    // Get current timestamp
    int64_t currentTime = static_cast<int64_t>(std::time(nullptr));

    // Build UPDATE SQL based on table name
    std::string updateSQL = "UPDATE " + tableName +
        " SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? "
        "WHERE id=?";

    sqlite3_stmt* stmt = nullptr;
    int rc = sqlite3_prepare_v2(db, updateSQL.c_str(), -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to prepare statement: " << sqlite3_errmsg(db) << std::endl;
        return false;
    }

    // Bind parameters
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

std::vector<WindowsLLMAnalysisService::ArtifactRecord>
WindowsLLMAnalysisService::getArtifactsFromDatabase(sqlite3* db,
                                                     const std::string& tableName,
                                                     const std::string& selectSQL,
                                                     size_t limit) {
    std::vector<ArtifactRecord> artifacts;

    // Prepare the query with limit
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

        // Build JSON representation of the artifact
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

std::string WindowsLLMAnalysisService::getTableNameForType(ArtifactType type) {
    switch (type) {
        case ArtifactType::REGISTRY: return "registry_values";
        case ArtifactType::EVENT_LOG: return "event_logs";
        case ArtifactType::PREFETCH: return "prefetch_files";
        case ArtifactType::LNK: return "lnk_files";
        case ArtifactType::JUMP_LIST: return "jump_list_entries";
        case ArtifactType::BROWSER_HISTORY: return "browser_history";
        case ArtifactType::BROWSER_DOWNLOAD: return "browser_downloads";
        case ArtifactType::BROWSER_BOOKMARK: return "browser_bookmarks";
        case ArtifactType::BROWSER_LOGIN: return "browser_logins";
        case ArtifactType::MFT_ENTRY: return "mft_entries";
        case ArtifactType::WINDOWS_SERVICE: return "windows_services";
        case ArtifactType::SCHEDULED_TASK: return "scheduled_tasks";
        case ArtifactType::AMCACHE: return "amcache_entries";
        case ArtifactType::SRUM: return "srum_entries";
        default: return "";
    }
}

std::string WindowsLLMAnalysisService::getSelectSQLForType(ArtifactType type) {
    switch (type) {
        case ArtifactType::REGISTRY: return WindowsAnalysisSQL::SELECT_REGISTRY_PENDING_ANALYSIS;
        case ArtifactType::EVENT_LOG: return WindowsAnalysisSQL::SELECT_EVENT_LOGS_PENDING_ANALYSIS;
        case ArtifactType::PREFETCH: return WindowsAnalysisSQL::SELECT_PREFETCH_PENDING_ANALYSIS;
        case ArtifactType::LNK: return WindowsAnalysisSQL::SELECT_LNK_PENDING_ANALYSIS;
        case ArtifactType::JUMP_LIST: return WindowsAnalysisSQL::SELECT_JUMP_LIST_PENDING_ANALYSIS;
        case ArtifactType::BROWSER_HISTORY: return WindowsAnalysisSQL::SELECT_BROWSER_HISTORY_PENDING_ANALYSIS;
        case ArtifactType::BROWSER_DOWNLOAD: return WindowsAnalysisSQL::SELECT_BROWSER_DOWNLOAD_PENDING_ANALYSIS;
        case ArtifactType::BROWSER_BOOKMARK: return WindowsAnalysisSQL::SELECT_BROWSER_BOOKMARK_PENDING_ANALYSIS;
        case ArtifactType::BROWSER_LOGIN: return WindowsAnalysisSQL::SELECT_BROWSER_LOGIN_PENDING_ANALYSIS;
        case ArtifactType::MFT_ENTRY: return WindowsAnalysisSQL::SELECT_MFT_PENDING_ANALYSIS;
        case ArtifactType::WINDOWS_SERVICE: return WindowsAnalysisSQL::SELECT_WINDOWS_SERVICE_PENDING_ANALYSIS;
        case ArtifactType::SCHEDULED_TASK: return WindowsAnalysisSQL::SELECT_SCHEDULED_TASK_PENDING_ANALYSIS;
        case ArtifactType::AMCACHE: return WindowsAnalysisSQL::SELECT_AMCACHE_PENDING_ANALYSIS;
        case ArtifactType::SRUM: return WindowsAnalysisSQL::SELECT_SRUM_PENDING_ANALYSIS;
        default: return "";
    }
}

} // namespace forensics
