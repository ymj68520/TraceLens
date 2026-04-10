// WindowsLLMAnalysisService.cpp
// Implementation of Windows artifact LLM analysis service - Core functionality

#include "WindowsLLMAnalysisService.h"
#include "DatabaseManager/SQL/windows_analysis_sql.h"
#include <sqlite3.h>
#include <iostream>
#include <ctime>

namespace forensics {

WindowsLLMAnalysisService::WindowsLLMAnalysisService()
    : initialized_(false) {
}

WindowsLLMAnalysisService::~WindowsLLMAnalysisService() = default;

bool WindowsLLMAnalysisService::initialize() {
    try {
        auto& configManager = ConfigManager::instance();
        if (!configManager.isLoaded()) {
            configManager.load();
        }

        // Use text model config for artifact analysis
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
        std::cerr << "Failed to initialize WindowsLLMAnalysisService: " << e.what() << std::endl;
        return false;
    }
}

int WindowsLLMAnalysisService::analyzeWindowsArtifacts(const std::string& windowsDbPath,
                                                         const AnalysisOptions& options,
                                                         ProgressCallback progressCallback) {
    if (!initialized_) {
        if (!initialize()) {
            return 0;
        }
    }

    int totalAnalyzed = 0;

    // Open database
    sqlite3* db = nullptr;
    int rc = sqlite3_open(windowsDbPath.c_str(), &db);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to open Windows database: " << windowsDbPath << std::endl;
        return 0;
    }

    // Analyze each artifact type based on options
    if (options.includeRegistry) {
        int count = analyzeArtifactType(windowsDbPath, ArtifactType::REGISTRY,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeEventLogs) {
        int count = analyzeArtifactType(windowsDbPath, ArtifactType::EVENT_LOG,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includePrefetch) {
        int count = analyzeArtifactType(windowsDbPath, ArtifactType::PREFETCH,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeLnk) {
        int count = analyzeArtifactType(windowsDbPath, ArtifactType::LNK,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeJumpLists) {
        int count = analyzeArtifactType(windowsDbPath, ArtifactType::JUMP_LIST,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeBrowser) {
        int count = analyzeArtifactType(windowsDbPath, ArtifactType::BROWSER_HISTORY,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;

        count = analyzeArtifactType(windowsDbPath, ArtifactType::BROWSER_DOWNLOAD,
                                    options.maxArtifacts, progressCallback);
        totalAnalyzed += count;

        count = analyzeArtifactType(windowsDbPath, ArtifactType::BROWSER_BOOKMARK,
                                    options.maxArtifacts, progressCallback);
        totalAnalyzed += count;

        count = analyzeArtifactType(windowsDbPath, ArtifactType::BROWSER_LOGIN,
                                    options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeSystem) {
        int count = analyzeArtifactType(windowsDbPath, ArtifactType::WINDOWS_SERVICE,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;

        count = analyzeArtifactType(windowsDbPath, ArtifactType::SCHEDULED_TASK,
                                    options.maxArtifacts, progressCallback);
        totalAnalyzed += count;

        count = analyzeArtifactType(windowsDbPath, ArtifactType::AMCACHE,
                                    options.maxArtifacts, progressCallback);
        totalAnalyzed += count;

        count = analyzeArtifactType(windowsDbPath, ArtifactType::SRUM,
                                    options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeMFT) {
        int count = analyzeArtifactType(windowsDbPath, ArtifactType::MFT_ENTRY,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    sqlite3_close(db);
    return totalAnalyzed;
}

int WindowsLLMAnalysisService::analyzeArtifactType(const std::string& windowsDbPath,
                                                    ArtifactType artifactType,
                                                    size_t maxArtifacts,
                                                    ProgressCallback progressCallback) {
    sqlite3* db = nullptr;
    int rc = sqlite3_open(windowsDbPath.c_str(), &db);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to open Windows database: " << windowsDbPath << std::endl;
        return 0;
    }

    std::string tableName = getTableNameForType(artifactType);
    std::string selectSQL = getSelectSQLForType(artifactType);

    // Get artifacts to analyze
    auto artifacts = getArtifactsFromDatabase(db, tableName, selectSQL, maxArtifacts);
    if (artifacts.empty()) {
        sqlite3_close(db);
        return 0;
    }

    int analyzed = 0;
    int total = artifacts.size();

    for (size_t i = 0; i < artifacts.size(); ++i) {
        const auto& artifact = artifacts[i];

        if (progressCallback) {
            std::string details = "Artifact ID: " + std::to_string(artifact.id);
            progressCallback(tableName, i + 1, total, details);
        }

        try {
            AnalysisResult result;

            // Route to appropriate analysis function
            switch (artifactType) {
                case ArtifactType::REGISTRY:
                    result = analyzeRegistryArtifact(artifact);
                    break;
                case ArtifactType::EVENT_LOG:
                    result = analyzeEventLogArtifact(artifact);
                    break;
                case ArtifactType::PREFETCH:
                    result = analyzePrefetchArtifact(artifact);
                    break;
                case ArtifactType::LNK:
                    result = analyzeLnkArtifact(artifact);
                    break;
                case ArtifactType::JUMP_LIST:
                    result = analyzeJumpListArtifact(artifact);
                    break;
                case ArtifactType::BROWSER_HISTORY:
                case ArtifactType::BROWSER_DOWNLOAD:
                case ArtifactType::BROWSER_BOOKMARK:
                case ArtifactType::BROWSER_LOGIN:
                    result = analyzeBrowserArtifact(artifact);
                    break;
                case ArtifactType::WINDOWS_SERVICE:
                case ArtifactType::SCHEDULED_TASK:
                case ArtifactType::AMCACHE:
                case ArtifactType::SRUM:
                    result = analyzeSystemArtifact(artifact);
                    break;
                case ArtifactType::MFT_ENTRY:
                    result = analyzeMftArtifact(artifact);
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
