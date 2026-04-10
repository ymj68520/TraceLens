#pragma once

#ifndef LINUX_LLM_ANALYSIS_SERVICE_H
#define LINUX_LLM_ANALYSIS_SERVICE_H

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
 * @brief LLM Analysis Service for Linux forensic artifacts
 *
 * Analyzes Linux system artifacts (system logs, user accounts, shell history,
 * cron jobs, SSH keys, packages, network connections, systemd services, etc.)
 * and generates AI-powered descriptions and insights for forensic investigation.
 *
 * This is a MANDATORY analysis step for Linux forensics, not optional.
 */
class LinuxLLMAnalysisService {
public:
    /**
     * @brief Artifact types that can be analyzed
     */
    enum class ArtifactType {
        LOG_ENTRY,
        USER_ACCOUNT,
        LOGIN_RECORD,
        SHELL_HISTORY,
        CRON_JOB,
        SSH_KEY,
        SSH_KNOWN_HOST,
        PACKAGE,
        NETWORK_CONNECTION,
        SYSTEMD_SERVICE,
        KERNEL_MODULE,
        FIREWALL_RULE,
        AUDIT_LOG,
        BROWSER_PROFILE,
        ALL
    };

    /**
     * @brief Analysis options for Linux artifact analysis
     */
    struct AnalysisOptions {
        size_t maxArtifacts = 1000;         // Maximum artifacts per type to analyze
        bool includeLogs = true;            // Analyze system logs
        bool includeUsers = true;           // Analyze user accounts
        bool includeLogins = true;          // Analyze login records
        bool includeShellHistory = true;    // Analyze shell history
        bool includeCron = true;            // Analyze cron jobs
        bool includeSSH = true;             // Analyze SSH keys/known hosts
        bool includePackages = true;        // Analyze installed packages
        bool includeNetwork = true;         // Analyze network connections
        bool includeSystemd = true;         // Analyze systemd services
        bool includeKernel = true;          // Analyze kernel modules
        bool includeFirewall = true;        // Analyze firewall rules
        bool includeAudit = true;           // Analyze audit logs
        bool includeBrowser = true;         // Analyze browser profiles
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
        bool success;
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

    /**
     * @brief Constructor
     */
    LinuxLLMAnalysisService();
    ~LinuxLLMAnalysisService();

    /**
     * @brief Initialize the service with LLM configuration
     * @return true if initialization successful
     */
    bool initialize();

    /**
     * @brief Analyze all Linux artifacts in the database
     *
     * This is a MANDATORY step for Linux forensics. All system artifacts
     * are analyzed by AI to provide contextual understanding for investigation.
     *
     * @param linuxDbPath Path to the Linux artifacts database (_linux.db)
     * @param options Analysis options
     * @param progressCallback Progress callback function
     * @return Total number of artifacts analyzed
     */
    int analyzeLinuxArtifacts(const std::string& linuxDbPath,
                               const AnalysisOptions& options,
                               ProgressCallback progressCallback = nullptr);

    /**
     * @brief Analyze a specific artifact type
     * @param linuxDbPath Path to the Linux artifacts database
     * @param artifactType Type of artifact to analyze
     * @param maxArtifacts Maximum number of artifacts to analyze
     * @param progressCallback Progress callback function
     * @return Number of artifacts analyzed
     */
    int analyzeArtifactType(const std::string& linuxDbPath,
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

    AnalysisResult analyzeLogArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeUserArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeLoginArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeShellHistoryArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeCronArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeSSHArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzePackageArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeNetworkArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeSystemdArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeKernelModuleArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeFirewallArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeAuditLogArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeBrowserProfileArtifact(const ArtifactRecord& artifact);

    std::string getTableNameForType(ArtifactType type);
    std::string getSelectSQLForType(ArtifactType type);
};

} // namespace forensics

#endif // LINUX_LLM_ANALYSIS_SERVICE_H
