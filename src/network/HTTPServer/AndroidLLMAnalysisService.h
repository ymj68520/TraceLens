#pragma once

#ifndef ANDROID_LLM_ANALYSIS_SERVICE_H
#define ANDROID_LLM_ANALYSIS_SERVICE_H

#include <string>
#include <vector>
#include <functional>
#include <memory>
#include <sqlite3.h>
#include "LLMIntegration/LLMDataTypes.h"
#include "LLMIntegration/ModelRouter.h"
#include "ConfigManager/ConfigManager.h"

namespace forensics {

/**
 * @brief LLM Analysis Service for Android forensic artifacts
 *
 * Analyzes Android artifacts (SMS, WeChat/WhatsApp/Telegram messages, contacts,
 * call logs, MIUI backup manifest, WeChat/QQ structured records, system logs,
 * device identifiers, WiFi networks) and generates AI-powered descriptions and
 * insights for forensic investigation.
 *
 * Mirrors LinuxLLMAnalysisService / WindowsLLMAnalysisService: each artifact
 * table carries 5 llm_* columns, a SELECT_*_PENDING_ANALYSIS statement fetches
 * unanalyzed rows, an inline JSON prompt is sent to ModelRouter::chat(), and the
 * result is written back via an in-place UPDATE.
 */
class AndroidLLMAnalysisService {
public:
    /**
     * @brief Android artifact types that can be analyzed
     */
    enum class ArtifactType {
        SMS,
        WECHAT_MESSAGE,
        WHATSAPP,
        TELEGRAM,
        CONTACT,
        CALL_LOG,
        MIUI_MANIFEST,
        INSTALLED_APP,
        WECHAT_SQLITE_RECORD,
        WECHAT_KV_RECORD,
        QQNT_SQLITE_RECORD,
        SYSTEM_LOG,
        DEVICE_IDENTIFIER,
        WIFI_NETWORK,
        ALL
    };

    /**
     * @brief Analysis options for Android artifact analysis
     */
    struct AnalysisOptions {
        size_t maxArtifacts = 1000;            // Maximum artifacts per type to analyze
        bool includeMessages = true;           // SMS / WeChat / WhatsApp / Telegram
        bool includeContacts = true;           // contacts + call logs
        bool includeMiui = true;               // backup manifest + installed apps
        bool includeWechatEvidence = true;     // wechat_sqlite_records + wechat_kv_records
        bool includeSystem = true;             // system_logs + device_identifiers + wifi
    };

    /**
     * @brief Artifact record for analysis
     */
    struct ArtifactRecord {
        int64_t id;
        std::string type;
        std::string data;  // JSON-formatted artifact data
    };

    /**
     * @brief Analysis result
     */
    struct AnalysisResult {
        bool success = false;
        std::string summary;
        std::string description;
        std::vector<std::string> keywords;
        std::string modelUsed;
    };

    /**
     * @brief Progress callback type
     * @param artifactType Current artifact type being analyzed
     * @param current Current artifact number
     * @param total Total artifacts to analyze
     * @param details Current artifact details
     */
    using ProgressCallback = std::function<void(const std::string& artifactType,
                                                int current, int total,
                                                const std::string& details)>;

    AndroidLLMAnalysisService();
    ~AndroidLLMAnalysisService();

    /**
     * @brief Initialize the service with LLM configuration
     * @return true if initialization successful
     */
    bool initialize();

    /**
     * @brief Analyze all Android artifacts in the database
     *
     * @param androidDbPath Path to the Android artifacts database (_android.db)
     * @param options Analysis options
     * @param progressCallback Progress callback function
     * @return Total number of artifacts analyzed
     */
    int analyzeAndroidArtifacts(const std::string& androidDbPath,
                                const AnalysisOptions& options,
                                ProgressCallback progressCallback = nullptr);

    /**
     * @brief Analyze a specific artifact type
     * @param androidDbPath Path to the Android artifacts database
     * @param artifactType Type of artifact to analyze
     * @param maxArtifacts Maximum number of artifacts to analyze
     * @param progressCallback Progress callback function
     * @return Number of artifacts analyzed
     */
    int analyzeArtifactType(const std::string& androidDbPath,
                            ArtifactType artifactType,
                            size_t maxArtifacts,
                            ProgressCallback progressCallback = nullptr);

private:
    std::shared_ptr<llm::ModelRouter> router_;
    bool initialized_ = false;

    // Internal helpers
    bool storeArtifactAnalysis(sqlite3* db,
                               const std::string& tableName,
                               int64_t artifactId,
                               const std::string& summary,
                               const std::string& description,
                               const std::vector<std::string>& keywords,
                               const std::string& modelUsed);

    std::vector<ArtifactRecord> getArtifactsFromDatabase(sqlite3* db,
                                                         const std::string& tableName,
                                                         const std::string& selectSQL,
                                                         size_t limit);

    // Per-type artifact analyzers (build prompt, call router, parse JSON).
    AnalysisResult analyzeSmsArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeWechatMessageArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeGenericMessageArtifact(const ArtifactRecord& artifact,
                                                 const char* platformLabel);
    AnalysisResult analyzeContactArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeCallLogArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeMiuiManifestArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeInstalledAppArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeSqliteRecordArtifact(const ArtifactRecord& artifact,
                                               const char* platformLabel);
    AnalysisResult analyzeWechatKvArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeSystemLogArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeDeviceIdentifierArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeWifiNetworkArtifact(const ArtifactRecord& artifact);

    std::string getTableNameForType(ArtifactType type);
    std::string getSelectSQLForType(ArtifactType type);

    // Shared helper: build a prompt for a single artifact given a forensic
    // role description, call the router, and parse the JSON response.
    AnalysisResult analyzeWithPrompt(const std::string& roleDescription,
                                     const std::string& artifactJson,
                                     const std::string& guidance);
};

} // namespace forensics

#endif // ANDROID_LLM_ANALYSIS_SERVICE_H
