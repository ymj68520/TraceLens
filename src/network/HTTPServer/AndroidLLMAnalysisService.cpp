// AndroidLLMAnalysisService.cpp
// Implementation of Android artifact LLM analysis service - Core functionality.
// Mirrors LinuxLLMAnalysisService.cpp.

#include "AndroidLLMAnalysisService.h"
#include "DatabaseManager/SQL/android_analysis_sql_llm.h"
#include <sqlite3.h>
#include <iostream>
#include <ctime>

namespace forensics {

AndroidLLMAnalysisService::AndroidLLMAnalysisService()
    : initialized_(false) {
}

AndroidLLMAnalysisService::~AndroidLLMAnalysisService() = default;

bool AndroidLLMAnalysisService::initialize() {
    try {
        auto& configManager = ConfigManager::instance();
        if (!configManager.isLoaded()) {
            configManager.load();
        }

        // Use the text model config for artifact analysis.
        auto config = configManager.getTextModelConfig();

        router_ = std::make_shared<llm::ModelRouter>();
        router_->addModel("default", config, llm::ModelInfo{
            "default",
            "text",
            {llm::ModelCapability::TextGeneration, llm::ModelCapability::Analysis}
        });

        initialized_ = true;
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Failed to initialize AndroidLLMAnalysisService: " << e.what() << std::endl;
        return false;
    }
}

int AndroidLLMAnalysisService::analyzeAndroidArtifacts(const std::string& androidDbPath,
                                                       const AnalysisOptions& options,
                                                       ProgressCallback progressCallback) {
    if (!initialized_) {
        if (!initialize()) {
            return 0;
        }
    }

    int totalAnalyzed = 0;

    sqlite3* db = nullptr;
    int rc = sqlite3_open(androidDbPath.c_str(), &db);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to open Android database: " << androidDbPath << std::endl;
        return 0;
    }
    sqlite3_close(db);  // analyzeArtifactType opens its own connection per type.

    if (options.includeMessages) {
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::SMS,
                                             options.maxArtifacts, progressCallback);
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::WECHAT_MESSAGE,
                                             options.maxArtifacts, progressCallback);
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::WHATSAPP,
                                             options.maxArtifacts, progressCallback);
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::TELEGRAM,
                                             options.maxArtifacts, progressCallback);
    }

    if (options.includeContacts) {
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::CONTACT,
                                             options.maxArtifacts, progressCallback);
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::CALL_LOG,
                                             options.maxArtifacts, progressCallback);
    }

    if (options.includeMiui) {
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::MIUI_MANIFEST,
                                             options.maxArtifacts, progressCallback);
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::INSTALLED_APP,
                                             options.maxArtifacts, progressCallback);
    }

    if (options.includeWechatEvidence) {
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::WECHAT_SQLITE_RECORD,
                                             options.maxArtifacts, progressCallback);
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::WECHAT_KV_RECORD,
                                             options.maxArtifacts, progressCallback);
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::QQNT_SQLITE_RECORD,
                                             options.maxArtifacts, progressCallback);
    }

    if (options.includeSystem) {
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::SYSTEM_LOG,
                                             options.maxArtifacts, progressCallback);
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::DEVICE_IDENTIFIER,
                                             options.maxArtifacts, progressCallback);
        totalAnalyzed += analyzeArtifactType(androidDbPath, ArtifactType::WIFI_NETWORK,
                                             options.maxArtifacts, progressCallback);
    }

    return totalAnalyzed;
}

int AndroidLLMAnalysisService::analyzeArtifactType(const std::string& androidDbPath,
                                                   ArtifactType artifactType,
                                                   size_t maxArtifacts,
                                                   ProgressCallback progressCallback) {
    sqlite3* db = nullptr;
    int rc = sqlite3_open(androidDbPath.c_str(), &db);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to open Android database: " << androidDbPath << std::endl;
        return 0;
    }

    std::string tableName = getTableNameForType(artifactType);
    std::string selectSQL = getSelectSQLForType(artifactType);
    if (tableName.empty() || selectSQL.empty()) {
        sqlite3_close(db);
        return 0;
    }

    auto artifacts = getArtifactsFromDatabase(db, tableName, selectSQL, maxArtifacts);
    if (artifacts.empty()) {
        sqlite3_close(db);
        return 0;
    }

    int analyzed = 0;
    int total = static_cast<int>(artifacts.size());

    for (size_t i = 0; i < artifacts.size(); ++i) {
        const auto& artifact = artifacts[i];

        if (progressCallback) {
            std::string details = "Artifact ID: " + std::to_string(artifact.id);
            progressCallback(tableName, static_cast<int>(i + 1), total, details);
        }

        try {
            AnalysisResult result;
            switch (artifactType) {
                case ArtifactType::SMS:
                    result = analyzeSmsArtifact(artifact);
                    break;
                case ArtifactType::WECHAT_MESSAGE:
                    result = analyzeWechatMessageArtifact(artifact);
                    break;
                case ArtifactType::WHATSAPP:
                    result = analyzeGenericMessageArtifact(artifact, "WhatsApp");
                    break;
                case ArtifactType::TELEGRAM:
                    result = analyzeGenericMessageArtifact(artifact, "Telegram");
                    break;
                case ArtifactType::CONTACT:
                    result = analyzeContactArtifact(artifact);
                    break;
                case ArtifactType::CALL_LOG:
                    result = analyzeCallLogArtifact(artifact);
                    break;
                case ArtifactType::MIUI_MANIFEST:
                    result = analyzeMiuiManifestArtifact(artifact);
                    break;
                case ArtifactType::INSTALLED_APP:
                    result = analyzeInstalledAppArtifact(artifact);
                    break;
                case ArtifactType::WECHAT_SQLITE_RECORD:
                    result = analyzeSqliteRecordArtifact(artifact, "WeChat");
                    break;
                case ArtifactType::WECHAT_KV_RECORD:
                    result = analyzeWechatKvArtifact(artifact);
                    break;
                case ArtifactType::QQNT_SQLITE_RECORD:
                    result = analyzeSqliteRecordArtifact(artifact, "QQ");
                    break;
                case ArtifactType::SYSTEM_LOG:
                    result = analyzeSystemLogArtifact(artifact);
                    break;
                case ArtifactType::DEVICE_IDENTIFIER:
                    result = analyzeDeviceIdentifierArtifact(artifact);
                    break;
                case ArtifactType::WIFI_NETWORK:
                    result = analyzeWifiNetworkArtifact(artifact);
                    break;
                default:
                    continue;
            }

            if (result.success) {
                if (storeArtifactAnalysis(db, tableName, artifact.id,
                                         result.summary, result.description,
                                         result.keywords, result.modelUsed)) {
                    analyzed++;
                }
            }
        } catch (const std::exception& e) {
            std::cerr << "Failed to analyze artifact " << artifact.id << ": " << e.what() << std::endl;
        }
    }

    sqlite3_close(db);
    return analyzed;
}

} // namespace forensics
