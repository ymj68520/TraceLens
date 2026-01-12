#pragma once

#include "LLMDataTypes.h"
#include <string>
#include <vector>

namespace forensics {
namespace llm {

/**
 * @brief Configuration manager that loads settings from .env files
 * 
 * Uses cpp-dotenv to load configuration from .env file at project root.
 * Provides typed access to all LLMIntegration configuration values.
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
    
    // LLM Settings - Common
    std::string getLLMBaseUrl() const;
    std::string getLLMEndpoint() const;
    std::string getLLMApiKey() const;
    int getLLMTimeoutSeconds() const;
    int getLLMMaxRetries() const;
    
    // Text Model Settings (GPT OSS)
    LLMConfig getTextModelConfig() const;
    std::string getTextBaseUrl() const;
    std::string getTextModel() const;
    int getTextMaxTokens() const;
    double getTextTemperature() const;
    
    // Vision Model Settings (Qwen3 VL)
    LLMConfig getVisionModelConfig() const;
    std::string getVisionBaseUrl() const;
    std::string getVisionModel() const;
    int getVisionMaxTokens() const;
    double getVisionTemperature() const;
    
    // Legacy support - returns text model config
    LLMConfig getLLMConfig() const;
    
    // MCP Settings
    int getMCPServerPort() const;
    std::string getMCPServerHost() const;
    std::vector<std::string> getMCPAllowedPaths() const;
    
    // File Analysis Settings
    int getFileAnalysisMaxContent() const;
    int getFileAnalysisMaxKeywords() const;
    
    // Database Settings
    std::string getDBOutputDir() const;
    std::string getDBName() const;
    
    // HTTP Server Settings
    int getHTTPServerPort() const;
    std::string getHTTPServerHost() const;
    
    // Logging Settings
    std::string getLogLevel() const;
    std::string getLogFile() const;
    
    // Performance Settings
    int getThreadPoolSize() const;
    int getMaxBatchSize() const;
    
    /**
     * @brief Get raw value by key (returns empty string if not found)
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
    
private:
    ConfigManager() = default;
    ~ConfigManager() = default;
    
    // Non-copyable
    ConfigManager(const ConfigManager&) = delete;
    ConfigManager& operator=(const ConfigManager&) = delete;
    
    bool loaded_ = false;
};

} // namespace llm
} // namespace forensics
