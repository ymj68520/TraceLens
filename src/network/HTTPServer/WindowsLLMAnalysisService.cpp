// WindowsLLMAnalysisService.cpp
// Implementation of Windows artifact LLM analysis service - Core functionality

#include "WindowsLLMAnalysisService.h"
#include "LLMBatchAnalysis.h"
#include "ConfigManager/ConfigManager.h"
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

    // Per-item analysis — the legacy floor (llm-throughput-hardening SPEC C3).
    auto analyzeSingle = [&](const ArtifactRecord& artifact) -> AnalysisResult {
        switch (artifactType) {
            case ArtifactType::REGISTRY:
                return analyzeRegistryArtifact(artifact);
            case ArtifactType::EVENT_LOG:
                return analyzeEventLogArtifact(artifact);
            case ArtifactType::PREFETCH:
                return analyzePrefetchArtifact(artifact);
            case ArtifactType::LNK:
                return analyzeLnkArtifact(artifact);
            case ArtifactType::JUMP_LIST:
                return analyzeJumpListArtifact(artifact);
            case ArtifactType::BROWSER_HISTORY:
            case ArtifactType::BROWSER_DOWNLOAD:
            case ArtifactType::BROWSER_BOOKMARK:
            case ArtifactType::BROWSER_LOGIN:
                return analyzeBrowserArtifact(artifact);
            case ArtifactType::WINDOWS_SERVICE:
            case ArtifactType::SCHEDULED_TASK:
            case ArtifactType::AMCACHE:
            case ArtifactType::SRUM:
                return analyzeSystemArtifact(artifact);
            case ArtifactType::MFT_ENTRY:
                return analyzeMftArtifact(artifact);
            default:
                return AnalysisResult{};
        }
    };

    auto reportProgress = [&](size_t zeroBasedIndex, const ArtifactRecord& artifact) {
        if (progressCallback) {
            std::string details = "Artifact ID: " + std::to_string(artifact.id);
            progressCallback(tableName, static_cast<int>(zeroBasedIndex) + 1,
                             static_cast<int>(total), details);
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
