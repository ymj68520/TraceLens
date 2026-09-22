#pragma once

#include "LLMDataTypes.h"
#include <string>
#include <vector>

namespace forensics {

/**
 * @brief Global configuration manager for the Forensics C++ Service
 * 
 * Centralized settings management that coordinates with Python services via .env.
 * Provides typed access to performance, security, and analysis parameters.
 */
class ConfigManager {
public:
    /**
     * @brief Get singleton instance
     */
    static ConfigManager& instance();
    
    /**
     * @brief Load configuration from .env file
     * @param envPath Path to .env file (default: ".env")
     * @return true if loaded successfully
     */
    bool load(const std::string& envPath = ".env");
    
    /**
     * @brief Check if configuration is loaded
     */
    bool isLoaded() const;
    
    // --- LLM Analysis Settings ---
    std::string getLLMBaseUrl() const;
    std::string getLLMEndpoint() const;
    std::string getLLMApiKey() const;
    int getLLMTimeoutSeconds() const;
    int getLLMMaxRetries() const;
    // LLM 分析数量上限约定：0 = 全量（不截断），负值按 0 处理。
    int getLLMMaxFiles() const;             // LLM_MAX_FILES：文件级分析上限
    int getLLMMaxEventClusters() const;     // LLM_MAX_EVENT_CLUSTERS：smart 模式事件簇分析上限
    int getLLMSmartCandidateFiles() const;  // LLM_SMART_CANDIDATE_FILES：smart 选择阶段的候选文件扫描上限
    int getLLMMaxArtifacts() const;         // LLM_MAX_ARTIFACTS：平台工件（Android/Linux/Windows）分析上限
    int getLLMMaxContentLength() const;
    // llm-throughput-hardening SPEC D: image vision-analysis bounds.
    int getLLMImageMaxBytes() const;
    std::string getLLMImageDetail() const;
    int getLLMArtifactBatchSize() const;
    int getLLMArtifactBatchRetries() const;
    bool getLLMSkipBinary() const;
    
    // Text Model Settings
    llm::LLMConfig getTextModelConfig() const;
    std::string getTextBaseUrl() const;
    std::string getTextModel() const;
    int getTextMaxTokens() const;
    double getTextTemperature() const;
    std::string getLLMThinkingMode() const;
    
    // Vision Model Settings
    llm::LLMConfig getVisionModelConfig() const;
    std::string getVisionBaseUrl() const;
    std::string getVisionModel() const;
    int getVisionMaxTokens() const;
    double getVisionTemperature() const;
    
    // --- System & Performance Settings ---
    int getThreadPoolSize() const;
    int getMaxBatchSize() const;
    int getHTTPServerPort() const;
    std::string getHTTPServerHost() const;
    std::string getPythonServiceUrl() const;
    std::string getMCPHost() const;
    std::vector<std::string> getMCPAllowedPaths() const;
    int getMCPMaxReadBytes() const;
    int getMCPMaxListEntries() const;
    
    // --- Database Settings ---
    int getDBBusyTimeoutMs() const;
    std::string getDBJournalMode() const;
    bool getDBSyncOff() const;
    
    // --- Full-Text Search Settings ---
    int getSearchMaxCacheSize() const;
    int getSearchMaxContentLength() const;
    int getSearchSnippetLength() const;
    int getSearchDefaultLimit() const;
    
    // --- Analysis Thresholds ---
    int getMaxLogDisplayFiles() const;
    int getFileAnalysisMaxContent() const;
    int getFileAnalysisMaxKeywords() const;
    int getContextLength() const;
    
    /**
     * @brief Get extra extensions for a category from config
     * @param categoryName e.g., "IMAGE", "VIDEO"
     * @return List of extensions from .env (e.g., EXTRA_IMAGE_EXTS="webp,avif")
     */
    std::vector<std::string> getExtraExtensions(const std::string& categoryName) const;
    
    // --- Storage & Logging ---
    std::string getDBOutputDir() const;
    std::string getDBName() const;
    std::string getLogLevel() const;
    std::string getLogFile() const;
    std::string getDebugOutputMode() const;

    /**
     * @brief Get raw value by key
     */
    std::string get(const std::string& key, const std::string& defaultValue = "") const;
    
    /**
     * @brief Get integer value by key
     */
    int getInt(const std::string& key, int defaultValue = 0) const;
    
    /**
     * @brief Get double value by key
     */
    double getDouble(const std::string& key, double defaultValue = 0.0) const;
    
    /**
     * @brief Get boolean value by key
     */
    bool getBool(const std::string& key, bool defaultValue = false) const;
    
private:
    ConfigManager() = default;
    ~ConfigManager() = default;
    
    ConfigManager(const ConfigManager&) = delete;
    ConfigManager& operator=(const ConfigManager&) = delete;
    
    bool loaded_ = false;
};

} // namespace forensics
