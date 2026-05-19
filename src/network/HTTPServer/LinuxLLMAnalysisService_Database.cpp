// LinuxLLMAnalysisService_Database.cpp
// Database operations for Linux artifact LLM analysis

#include "LinuxLLMAnalysisService.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include <sqlite3.h>
#include <iostream>
#include <sstream>
#include <ctime>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace forensics {

bool LinuxLLMAnalysisService::storeArtifactAnalysis(sqlite3* db,
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

std::vector<LinuxLLMAnalysisService::ArtifactRecord>
LinuxLLMAnalysisService::getArtifactsFromDatabase(sqlite3* db,
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

std::string LinuxLLMAnalysisService::getTableNameForType(ArtifactType type) {
    switch (type) {
        case ArtifactType::LOG_ENTRY: return "linux_log_entries";
        case ArtifactType::USER_ACCOUNT: return "linux_users";
        case ArtifactType::LOGIN_RECORD: return "linux_login_records";
        case ArtifactType::SHELL_HISTORY: return "linux_shell_history";
        case ArtifactType::CRON_JOB: return "linux_cron_jobs";
        case ArtifactType::SSH_KEY: return "linux_ssh_keys";
        case ArtifactType::SSH_KNOWN_HOST: return "linux_ssh_known_hosts";
        case ArtifactType::PACKAGE: return "linux_packages";
        case ArtifactType::NETWORK_CONNECTION: return "linux_network_connections";
        case ArtifactType::SYSTEMD_SERVICE: return "linux_systemd_services";
        case ArtifactType::KERNEL_MODULE: return "linux_kernel_modules";
        case ArtifactType::FIREWALL_RULE: return "linux_firewall_rules";
        case ArtifactType::AUDIT_LOG: return "linux_audit_logs";
        case ArtifactType::BROWSER_PROFILE: return "linux_browser_profiles";
        case ArtifactType::JOURNAL_ENTRY: return "linux_journal_entries";
        case ArtifactType::BOOT_SESSION: return "linux_boot_sessions";
        case ArtifactType::AGGREGATED_AUDIT_EVENT: return "linux_audit_events";
        case ArtifactType::TAMPERING_INDICATOR: return "linux_tampering_findings";
        case ArtifactType::PERSISTENCE_ENTRY: return "linux_persistence_entries";
        case ArtifactType::ERROR_LOG: return "linux_web_error_logs";
        case ArtifactType::MIDDLEWARE_LOG: return "linux_middleware_logs";
        case ArtifactType::CONTAINER_LOG: return "linux_container_logs";
        case ArtifactType::PACKAGE_OPERATION: return "linux_package_logs";
        case ArtifactType::ACCOUNT_ANOMALY: return "linux_account_security_findings";
        case ArtifactType::DATABASE_LOG: return "linux_database_logs";
        case ArtifactType::EMAIL_LOG: return "linux_email_logs";
        case ArtifactType::VPN_LOG: return "linux_vpn_logs";
        case ArtifactType::FIREWALL_LOG: return "linux_firewall_logs";
        case ArtifactType::SECURITY_PRODUCT_LOG: return "linux_security_product_logs";
        default: return "";
    }
}

std::string LinuxLLMAnalysisService::getSelectSQLForType(ArtifactType type) {
    switch (type) {
        case ArtifactType::LOG_ENTRY: return LinuxAnalysisSQL::SELECT_LOG_ENTRIES_PENDING_ANALYSIS;
        case ArtifactType::USER_ACCOUNT: return LinuxAnalysisSQL::SELECT_USERS_PENDING_ANALYSIS;
        case ArtifactType::LOGIN_RECORD: return LinuxAnalysisSQL::SELECT_LOGIN_RECORDS_PENDING_ANALYSIS;
        case ArtifactType::SHELL_HISTORY: return LinuxAnalysisSQL::SELECT_SHELL_HISTORY_PENDING_ANALYSIS;
        case ArtifactType::CRON_JOB: return LinuxAnalysisSQL::SELECT_CRON_JOBS_PENDING_ANALYSIS;
        case ArtifactType::SSH_KEY: return LinuxAnalysisSQL::SELECT_SSH_KEYS_PENDING_ANALYSIS;
        case ArtifactType::SSH_KNOWN_HOST: return LinuxAnalysisSQL::SELECT_SSH_KNOWN_HOSTS_PENDING_ANALYSIS;
        case ArtifactType::PACKAGE: return LinuxAnalysisSQL::SELECT_PACKAGES_PENDING_ANALYSIS;
        case ArtifactType::NETWORK_CONNECTION: return LinuxAnalysisSQL::SELECT_NETWORK_CONNECTIONS_PENDING_ANALYSIS;
        case ArtifactType::SYSTEMD_SERVICE: return LinuxAnalysisSQL::SELECT_SYSTEMD_SERVICES_PENDING_ANALYSIS;
        case ArtifactType::KERNEL_MODULE: return LinuxAnalysisSQL::SELECT_KERNEL_MODULES_PENDING_ANALYSIS;
        case ArtifactType::FIREWALL_RULE: return LinuxAnalysisSQL::SELECT_FIREWALL_RULES_PENDING_ANALYSIS;
        case ArtifactType::AUDIT_LOG: return LinuxAnalysisSQL::SELECT_AUDIT_LOGS_PENDING_ANALYSIS;
        case ArtifactType::BROWSER_PROFILE: return LinuxAnalysisSQL::SELECT_BROWSER_PROFILES_PENDING_ANALYSIS;
        case ArtifactType::JOURNAL_ENTRY: return LinuxAnalysisSQL::SELECT_JOURNAL_ENTRIES_PENDING_ANALYSIS;
        case ArtifactType::AGGREGATED_AUDIT_EVENT: return LinuxAnalysisSQL::SELECT_AUDIT_EVENTS_PENDING_ANALYSIS;
        case ArtifactType::TAMPERING_INDICATOR: return LinuxAnalysisSQL::SELECT_TAMPERING_FINDINGS_PENDING_ANALYSIS;
        case ArtifactType::PERSISTENCE_ENTRY: return LinuxAnalysisSQL::SELECT_PERSISTENCE_ENTRIES_PENDING_ANALYSIS;
        case ArtifactType::ERROR_LOG: return LinuxAnalysisSQL::SELECT_WEB_ERROR_LOGS_PENDING_ANALYSIS;
        case ArtifactType::MIDDLEWARE_LOG: return LinuxAnalysisSQL::SELECT_MIDDLEWARE_LOGS_PENDING_ANALYSIS;
        case ArtifactType::CONTAINER_LOG: return LinuxAnalysisSQL::SELECT_CONTAINER_LOGS_PENDING_ANALYSIS;
        case ArtifactType::PACKAGE_OPERATION: return LinuxAnalysisSQL::SELECT_PACKAGE_LOGS_PENDING_ANALYSIS;
        case ArtifactType::ACCOUNT_ANOMALY: return LinuxAnalysisSQL::SELECT_ACCOUNT_SECURITY_FINDINGS_PENDING_ANALYSIS;
        case ArtifactType::DATABASE_LOG: return LinuxAnalysisSQL::SELECT_DATABASE_LOGS_PENDING_ANALYSIS;
        case ArtifactType::EMAIL_LOG: return LinuxAnalysisSQL::SELECT_EMAIL_LOGS_PENDING_ANALYSIS;
        case ArtifactType::VPN_LOG: return LinuxAnalysisSQL::SELECT_VPN_LOGS_PENDING_ANALYSIS;
        case ArtifactType::FIREWALL_LOG: return LinuxAnalysisSQL::SELECT_FIREWALL_LOGS_PENDING_ANALYSIS;
        case ArtifactType::SECURITY_PRODUCT_LOG: return LinuxAnalysisSQL::SELECT_SECURITY_PRODUCT_LOGS_PENDING_ANALYSIS;
        default: return "";
    }
}

} // namespace forensics
