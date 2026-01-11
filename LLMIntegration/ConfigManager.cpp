#include "ConfigManager.h"
#include "dotenv.h"

#include <sstream>
#include <algorithm>

namespace forensics {
namespace llm {

ConfigManager& ConfigManager::instance() {
    static ConfigManager instance;
    return instance;
}

bool ConfigManager::load(const std::string& envPath) {
    try {
        dotenv::env.load_dotenv(envPath, false, true);
        loaded_ = true;
        return true;
    } catch (...) {
        loaded_ = false;
        return false;
    }
}

bool ConfigManager::isLoaded() const {
    return loaded_;
}

std::string ConfigManager::get(const std::string& key, const std::string& defaultValue) const {
    std::string value = dotenv::env[key];
    return value.empty() ? defaultValue : value;
}

int ConfigManager::getInt(const std::string& key, int defaultValue) const {
    std::string value = get(key);
    if (value.empty()) {
        return defaultValue;
    }
    try {
        return std::stoi(value);
    } catch (...) {
        return defaultValue;
    }
}

double ConfigManager::getDouble(const std::string& key, double defaultValue) const {
    std::string value = get(key);
    if (value.empty()) {
        return defaultValue;
    }
    try {
        return std::stod(value);
    } catch (...) {
        return defaultValue;
    }
}

// LLM Settings
LLMConfig ConfigManager::getLLMConfig() const {
    LLMConfig config;
    config.baseUrl = getLLMBaseUrl();
    config.endpoint = getLLMEndpoint();
    config.apiKey = getLLMApiKey();
    config.model = getLLMModel();
    config.maxTokens = getLLMMaxTokens();
    config.temperature = getLLMTemperature();
    config.timeoutSeconds = getLLMTimeoutSeconds();
    config.maxRetries = getLLMMaxRetries();
    return config;
}

std::string ConfigManager::getLLMBaseUrl() const {
    return get("LLM_BASE_URL", "http://localhost:1234");
}

std::string ConfigManager::getLLMEndpoint() const {
    return get("LLM_ENDPOINT", "/v1/chat/completions");
}

std::string ConfigManager::getLLMApiKey() const {
    return get("LLM_API_KEY", "");
}

std::string ConfigManager::getLLMModel() const {
    return get("LLM_MODEL", "");
}

int ConfigManager::getLLMMaxTokens() const {
    return getInt("LLM_MAX_TOKENS", 2048);
}

double ConfigManager::getLLMTemperature() const {
    return getDouble("LLM_TEMPERATURE", 0.7);
}

int ConfigManager::getLLMTimeoutSeconds() const {
    return getInt("LLM_TIMEOUT_SECONDS", 60);
}

int ConfigManager::getLLMMaxRetries() const {
    return getInt("LLM_MAX_RETRIES", 3);
}

// MCP Settings
int ConfigManager::getMCPServerPort() const {
    return getInt("MCP_SERVER_PORT", 8890);
}

std::string ConfigManager::getMCPServerHost() const {
    return get("MCP_SERVER_HOST", "localhost");
}

std::vector<std::string> ConfigManager::getMCPAllowedPaths() const {
    std::vector<std::string> paths;
    std::string value = get("MCP_ALLOWED_PATHS", "");
    
    if (value.empty()) {
        return paths;
    }
    
    std::istringstream iss(value);
    std::string path;
    while (std::getline(iss, path, ',')) {
        // Trim whitespace
        path.erase(0, path.find_first_not_of(" \t"));
        path.erase(path.find_last_not_of(" \t") + 1);
        if (!path.empty()) {
            paths.push_back(path);
        }
    }
    
    return paths;
}

// File Analysis Settings
int ConfigManager::getFileAnalysisMaxContent() const {
    return getInt("FILE_ANALYSIS_MAX_CONTENT", 10000);
}

int ConfigManager::getFileAnalysisMaxKeywords() const {
    return getInt("FILE_ANALYSIS_MAX_KEYWORDS", 10);
}

// Database Settings
std::string ConfigManager::getDBOutputDir() const {
    return get("DB_OUTPUT_DIR", "./output");
}

std::string ConfigManager::getDBName() const {
    return get("DB_NAME", "forensics.db");
}

// HTTP Server Settings
int ConfigManager::getHTTPServerPort() const {
    return getInt("HTTP_SERVER_PORT", 8080);
}

std::string ConfigManager::getHTTPServerHost() const {
    return get("HTTP_SERVER_HOST", "0.0.0.0");
}

// Logging Settings
std::string ConfigManager::getLogLevel() const {
    return get("LOG_LEVEL", "INFO");
}

std::string ConfigManager::getLogFile() const {
    return get("LOG_FILE", "forensics.log");
}

// Performance Settings
int ConfigManager::getThreadPoolSize() const {
    return getInt("THREAD_POOL_SIZE", 4);
}

int ConfigManager::getMaxBatchSize() const {
    return getInt("MAX_BATCH_SIZE", 100);
}

} // namespace llm
} // namespace forensics
