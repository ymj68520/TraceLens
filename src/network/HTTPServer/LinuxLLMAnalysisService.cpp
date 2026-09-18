// LinuxLLMAnalysisService.cpp
// Implementation of Linux artifact LLM analysis service - Core functionality

#include "LinuxLLMAnalysisService.h"
#include "LLMBatchAnalysis.h"
#include "ConfigManager/ConfigManager.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include <sqlite3.h>
#include <iostream>
#include <ctime>

namespace forensics {

LinuxLLMAnalysisService::LinuxLLMAnalysisService()
    : initialized_(false) {
}

LinuxLLMAnalysisService::~LinuxLLMAnalysisService() = default;

bool LinuxLLMAnalysisService::initialize() {
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
        std::cerr << "Failed to initialize LinuxLLMAnalysisService: " << e.what() << std::endl;
        return false;
    }
}

int LinuxLLMAnalysisService::analyzeLinuxArtifacts(const std::string& linuxDbPath,
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
    int rc = sqlite3_open(linuxDbPath.c_str(), &db);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to open Linux database: " << linuxDbPath << std::endl;
        return 0;
    }

    // Analyze each artifact type based on options
    if (options.includeLogs) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::LOG_ENTRY,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeUsers) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::USER_ACCOUNT,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeLogins) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::LOGIN_RECORD,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeShellHistory) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::SHELL_HISTORY,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeCron) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::CRON_JOB,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeSSH) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::SSH_KEY,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;

        count = analyzeArtifactType(linuxDbPath, ArtifactType::SSH_KNOWN_HOST,
                                    options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includePackages) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::PACKAGE,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeNetwork) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::NETWORK_CONNECTION,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeSystemd) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::SYSTEMD_SERVICE,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeKernel) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::KERNEL_MODULE,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeFirewall) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::FIREWALL_RULE,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeAudit) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::AUDIT_LOG,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    if (options.includeBrowser) {
        int count = analyzeArtifactType(linuxDbPath, ArtifactType::BROWSER_PROFILE,
                                         options.maxArtifacts, progressCallback);
        totalAnalyzed += count;
    }

    sqlite3_close(db);
    return totalAnalyzed;
}

int LinuxLLMAnalysisService::analyzeArtifactType(const std::string& linuxDbPath,
                                                    ArtifactType artifactType,
                                                    size_t maxArtifacts,
                                                    ProgressCallback progressCallback) {
    sqlite3* db = nullptr;
    int rc = sqlite3_open(linuxDbPath.c_str(), &db);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to open Linux database: " << linuxDbPath << std::endl;
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
            case ArtifactType::LOG_ENTRY:
                return analyzeLogArtifact(artifact);
            case ArtifactType::USER_ACCOUNT:
                return analyzeUserArtifact(artifact);
            case ArtifactType::LOGIN_RECORD:
                return analyzeLoginArtifact(artifact);
            case ArtifactType::SHELL_HISTORY:
                return analyzeShellHistoryArtifact(artifact);
            case ArtifactType::CRON_JOB:
                return analyzeCronArtifact(artifact);
            case ArtifactType::SSH_KEY:
            case ArtifactType::SSH_KNOWN_HOST:
                return analyzeSSHArtifact(artifact);
            case ArtifactType::PACKAGE:
                return analyzePackageArtifact(artifact);
            case ArtifactType::NETWORK_CONNECTION:
                return analyzeNetworkArtifact(artifact);
            case ArtifactType::SYSTEMD_SERVICE:
                return analyzeSystemdArtifact(artifact);
            case ArtifactType::KERNEL_MODULE:
                return analyzeKernelModuleArtifact(artifact);
            case ArtifactType::FIREWALL_RULE:
                return analyzeFirewallArtifact(artifact);
            case ArtifactType::AUDIT_LOG:
                return analyzeAuditLogArtifact(artifact);
            case ArtifactType::BROWSER_PROFILE:
                return analyzeBrowserProfileArtifact(artifact);
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
        // SPEC C: pack N records per request. Anything the batch response
        // leaves unresolved falls back to analyzeSingle, so coverage never
        // drops below the legacy per-row floor.
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
