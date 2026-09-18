// AndroidLLMAnalysisService.cpp
// Implementation of Android artifact LLM analysis service - Core functionality.
// Mirrors LinuxLLMAnalysisService.cpp.

#include "AndroidLLMAnalysisService.h"
#include "LLMBatchAnalysis.h"
#include "ConfigManager/ConfigManager.h"
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

    // Per-item analysis — the legacy floor (llm-throughput-hardening SPEC C3).
    auto analyzeSingle = [&](const ArtifactRecord& artifact) -> AnalysisResult {
        switch (artifactType) {
            case ArtifactType::SMS:
                return analyzeSmsArtifact(artifact);
            case ArtifactType::WECHAT_MESSAGE:
                return analyzeWechatMessageArtifact(artifact);
            case ArtifactType::WHATSAPP:
                return analyzeGenericMessageArtifact(artifact, "WhatsApp");
            case ArtifactType::TELEGRAM:
                return analyzeGenericMessageArtifact(artifact, "Telegram");
            case ArtifactType::CONTACT:
                return analyzeContactArtifact(artifact);
            case ArtifactType::CALL_LOG:
                return analyzeCallLogArtifact(artifact);
            case ArtifactType::MIUI_MANIFEST:
                return analyzeMiuiManifestArtifact(artifact);
            case ArtifactType::INSTALLED_APP:
                return analyzeInstalledAppArtifact(artifact);
            case ArtifactType::WECHAT_SQLITE_RECORD:
                return analyzeSqliteRecordArtifact(artifact, "WeChat");
            case ArtifactType::WECHAT_KV_RECORD:
                return analyzeWechatKvArtifact(artifact);
            case ArtifactType::QQNT_SQLITE_RECORD:
                return analyzeSqliteRecordArtifact(artifact, "QQ");
            case ArtifactType::SYSTEM_LOG:
                return analyzeSystemLogArtifact(artifact);
            case ArtifactType::DEVICE_IDENTIFIER:
                return analyzeDeviceIdentifierArtifact(artifact);
            case ArtifactType::WIFI_NETWORK:
                return analyzeWifiNetworkArtifact(artifact);
            default:
                return AnalysisResult{};
        }
    };

    auto reportProgress = [&](size_t zeroBasedIndex, const ArtifactRecord& artifact) {
        if (progressCallback) {
            std::string details = "Artifact ID: " + std::to_string(artifact.id);
            progressCallback(tableName, static_cast<int>(zeroBasedIndex + 1), total, details);
        }
    };

    auto storeOne = [&](const ArtifactRecord& artifact, const AnalysisResult& result) {
        if (result.success) {
            if (storeArtifactAnalysis(db, tableName, artifact.id,
                                      result.summary, result.description,
                                      result.keywords, result.modelUsed)) {
                analyzed++;
            }
        }
    };

    const int batchSize = ConfigManager::instance().getLLMArtifactBatchSize();
    if (batchSize > 1) {
        // SPEC C: pack N records per request; unresolved items fall back to
        // analyzeSingle so coverage never drops below the legacy floor.
        std::vector<llmbatch::Item> chunk;
        chunk.reserve(static_cast<size_t>(batchSize));
        size_t chunkStart = 0;
        for (size_t i = 0; i < artifacts.size(); ++i) {
            const auto& artifact = artifacts[i];
            chunk.push_back({std::to_string(artifact.id), artifact.data});

            const bool last = (i + 1 == artifacts.size());
            if (chunk.size() < static_cast<size_t>(batchSize) && !last) {
                continue;
            }

            llmbatch::Outcome outcome;
            llmbatch::analyzeWithLadder(*router_, tableName, chunk,
                                        ConfigManager::instance().getLLMArtifactBatchRetries(),
                                        outcome);

            for (size_t j = 0; j < chunk.size(); ++j) {
                reportProgress(chunkStart + j, artifacts[chunkStart + j]);
                const auto& record = artifacts[chunkStart + j];
                auto it = outcome.results.find(std::to_string(record.id));
                if (it != outcome.results.end()) {
                    AnalysisResult r{};
                    r.success = true;
                    const auto& entry = it->second;
                    r.summary = entry.value("summary", "");
                    r.description = entry.value("description", "");
                    if (entry.contains("keywords") && entry["keywords"].is_array()) {
                        for (const auto& kw : entry["keywords"]) {
                            if (kw.is_string()) r.keywords.push_back(kw.get<std::string>());
                        }
                    }
                    if (r.summary.empty() && r.description.empty()) {
                        storeOne(record, analyzeSingle(record));
                        continue;
                    }
                    r.modelUsed = router_->getConfig().model;
                    storeOne(record, r);
                } else {
                    storeOne(record, analyzeSingle(record));
                }
            }
            chunkStart = i + 1;
            chunk.clear();
        }
        sqlite3_close(db);
        return analyzed;
    }

    for (size_t i = 0; i < artifacts.size(); ++i) {
        const auto& artifact = artifacts[i];

        reportProgress(i, artifact);

        try {
            AnalysisResult result = analyzeSingle(artifact);

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
