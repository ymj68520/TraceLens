#pragma once

#ifndef WINDOWS_LLM_ANALYSIS_SERVICE_H
#define WINDOWS_LLM_ANALYSIS_SERVICE_H

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
 * @brief LLM Analysis Service for Windows forensic artifacts
 *
 * Analyzes Windows system artifacts (registry, event logs, prefetch files,
 * browser history, services, scheduled tasks, etc.) and generates AI-powered
 * descriptions and insights for forensic investigation.
 *
 * This is a MANDATORY analysis step for Windows forensics, not optional.
 */
class WindowsLLMAnalysisService {
public:
    /**
     * @brief Artifact types that can be analyzed
     */
    enum class ArtifactType {
        REGISTRY,
        EVENT_LOG,
        PREFETCH,
        LNK,
        JUMP_LIST,
        BROWSER_HISTORY,
        BROWSER_DOWNLOAD,
        BROWSER_BOOKMARK,
        BROWSER_LOGIN,
        MFT_ENTRY,
        WINDOWS_SERVICE,
        SCHEDULED_TASK,
        AMCACHE,
        SRUM,
        ALL
    };

    /**
     * @brief Analysis options for Windows artifact analysis
     */
    struct AnalysisOptions {
        size_t maxArtifacts = 1000;         // Maximum artifacts per type to analyze
        bool includeRegistry = true;        // Analyze registry values
        bool includeEventLogs = true;       // Analyze event logs
        bool includePrefetch = true;        // Analyze prefetch files
        bool includeLnk = true;             // Analyze LNK files
        bool includeJumpLists = true;       // Analyze jump lists
        bool includeBrowser = true;         // Analyze browser artifacts
        bool includeSystem = true;          // Analyze services/tasks/Amcache/SRUM
        bool includeMFT = false;            // Analyze MFT entries (can be very large)
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
    WindowsLLMAnalysisService();
    ~WindowsLLMAnalysisService();

    /**
     * @brief Initialize the service with LLM configuration
     * @return true if initialization successful
     */
    bool initialize();

    /**
     * @brief Analyze all Windows artifacts in the database
     *
     * This is a MANDATORY step for Windows forensics. All system artifacts
     * are analyzed by AI to provide contextual understanding for investigation.
     *
     * @param windowsDbPath Path to the Windows artifacts database (_windows.db)
     * @param options Analysis options
     * @param progressCallback Progress callback function
     * @return Total number of artifacts analyzed
     */
    int analyzeWindowsArtifacts(const std::string& windowsDbPath,
                                 const AnalysisOptions& options,
                                 ProgressCallback progressCallback = nullptr);

    /**
     * @brief Analyze a specific artifact type
     * @param windowsDbPath Path to the Windows artifacts database
     * @param artifactType Type of artifact to analyze
     * @param maxArtifacts Maximum number of artifacts to analyze
     * @param progressCallback Progress callback function
     * @return Number of artifacts analyzed
     */
    int analyzeArtifactType(const std::string& windowsDbPath,
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

    AnalysisResult analyzeRegistryArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeEventLogArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzePrefetchArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeLnkArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeJumpListArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeBrowserArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeSystemArtifact(const ArtifactRecord& artifact);
    AnalysisResult analyzeMftArtifact(const ArtifactRecord& artifact);

    std::string buildArtifactSummary(const ArtifactRecord& artifact, const std::string& artifactType);
    std::string getTableNameForType(ArtifactType type);
    std::string getUpdateSQLForType(ArtifactType type);
    std::string getSelectSQLForType(ArtifactType type);
};

} // namespace forensics

#endif // WINDOWS_LLM_ANALYSIS_SERVICE_H
