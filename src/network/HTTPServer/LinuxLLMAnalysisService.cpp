// LinuxLLMAnalysisService.cpp
// Implementation of Linux artifact LLM analysis service - Core functionality

#include "LinuxLLMAnalysisService.h"
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
                case ArtifactType::LOG_ENTRY:
                    result = analyzeLogArtifact(artifact);
                    break;
                case ArtifactType::USER_ACCOUNT:
                    result = analyzeUserArtifact(artifact);
                    break;
                case ArtifactType::LOGIN_RECORD:
                    result = analyzeLoginArtifact(artifact);
                    break;
                case ArtifactType::SHELL_HISTORY:
                    result = analyzeShellHistoryArtifact(artifact);
                    break;
                case ArtifactType::CRON_JOB:
                    result = analyzeCronArtifact(artifact);
                    break;
                case ArtifactType::SSH_KEY:
                case ArtifactType::SSH_KNOWN_HOST:
                    result = analyzeSSHArtifact(artifact);
                    break;
                case ArtifactType::PACKAGE:
                    result = analyzePackageArtifact(artifact);
                    break;
                case ArtifactType::NETWORK_CONNECTION:
                    result = analyzeNetworkArtifact(artifact);
                    break;
                case ArtifactType::SYSTEMD_SERVICE:
                    result = analyzeSystemdArtifact(artifact);
                    break;
                case ArtifactType::KERNEL_MODULE:
                    result = analyzeKernelModuleArtifact(artifact);
                    break;
                case ArtifactType::FIREWALL_RULE:
                    result = analyzeFirewallArtifact(artifact);
                    break;
                case ArtifactType::AUDIT_LOG:
                    result = analyzeAuditLogArtifact(artifact);
                    break;
                case ArtifactType::BROWSER_PROFILE:
                    result = analyzeBrowserProfileArtifact(artifact);
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
