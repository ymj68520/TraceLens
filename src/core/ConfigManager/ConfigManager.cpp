#include "ConfigManager/ConfigManager.h"
#include "dotenv.h"
#include "PathManager/PathManager.h"

#include <sstream>
#include <algorithm>
#include <filesystem>
#include <iostream>

namespace forensics {

ConfigManager& ConfigManager::instance() {
    static ConfigManager instance;
    return instance;
}

bool ConfigManager::load(const std::string& envPath) {
    std::vector<std::string> searchPaths = {
        envPath,
        "../" + envPath,
        "../../" + envPath,
        "../../../" + envPath
    };

    try {
        auto& pm = forensics::PathManager::instance();
        if (pm.isInitialized()) {
            searchPaths.insert(searchPaths.begin() + 1, (pm.getExeDir() / envPath).string());
            searchPaths.insert(searchPaths.begin() + 2, (pm.getProjectRoot() / envPath).string());
        }
    } catch (...) {}

    for (const auto& path : searchPaths) {
        if (!std::filesystem::exists(path)) continue;
        try {
            dotenv::env.load_dotenv(path, false, true);
            loaded_ = true;
            return true;
        } catch (...) {}
    }

    loaded_ = false;
    return false;
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
    if (value.empty()) return defaultValue;
    try {
        return std::stoi(value);
    } catch (...) {
        return defaultValue;
    }
}

double ConfigManager::getDouble(const std::string& key, double defaultValue) const {
    std::string value = get(key);
    if (value.empty()) return defaultValue;
    try {
        return std::stod(value);
    } catch (...) {
        return defaultValue;
    }
}

bool ConfigManager::getBool(const std::string& key, bool defaultValue) const {
    std::string value = get(key);
    if (value.empty()) return defaultValue;
    std::string lower_val = value;
    std::transform(lower_val.begin(), lower_val.end(), lower_val.begin(), ::tolower);
    if (lower_val == "true" || lower_val == "1" || lower_val == "yes" || lower_val == "on") return true;
    if (lower_val == "false" || lower_val == "0" || lower_val == "no" || lower_val == "off") return false;
    return defaultValue;
}

// --- LLM Analysis Settings ---
std::string ConfigManager::getLLMBaseUrl() const { return get("LLM_BASE_URL", "http://localhost:1234"); }
std::string ConfigManager::getLLMEndpoint() const { return get("LLM_ENDPOINT", "/v1/chat/completions"); }
std::string ConfigManager::getLLMApiKey() const { return get("LLM_API_KEY", ""); }
int ConfigManager::getLLMTimeoutSeconds() const { return getInt("LLM_TIMEOUT_SECONDS", 120); }
int ConfigManager::getLLMMaxRetries() const { return getInt("LLM_MAX_RETRIES", 3); }
int ConfigManager::getLLMMaxFiles() const { return getInt("LLM_MAX_FILES", 500); }
int ConfigManager::getLLMMaxContentLength() const { return getInt("LLM_MAX_CONTENT_LENGTH", 10000); }
bool ConfigManager::getLLMSkipBinary() const { return getBool("LLM_SKIP_BINARY", true); }

// Text Model Settings
std::string ConfigManager::getTextBaseUrl() const { return get("LLM_TEXT_BASE_URL", getLLMBaseUrl()); }
std::string ConfigManager::getTextModel() const { return get("LLM_TEXT_MODEL", "gpt-oss"); }
int ConfigManager::getTextMaxTokens() const { return getInt("LLM_TEXT_MAX_TOKENS", 2048); }
double ConfigManager::getTextTemperature() const { return getDouble("LLM_TEXT_TEMPERATURE", 0.7); }

llm::LLMConfig ConfigManager::getTextModelConfig() const {
    llm::LLMConfig config;
    config.baseUrl = getTextBaseUrl();
    config.endpoint = getLLMEndpoint();
    config.apiKey = getLLMApiKey();
    config.model = getTextModel();
    config.maxTokens = getTextMaxTokens();
    config.temperature = getTextTemperature();
    config.timeoutSeconds = getLLMTimeoutSeconds();
    config.maxRetries = getLLMMaxRetries();
    return config;
}

// Vision Model Settings
std::string ConfigManager::getVisionBaseUrl() const { return get("LLM_VISION_BASE_URL", getLLMBaseUrl()); }
std::string ConfigManager::getVisionModel() const { return get("LLM_VISION_MODEL", "qwen3-vl"); }
int ConfigManager::getVisionMaxTokens() const { return getInt("LLM_VISION_MAX_TOKENS", 4096); }
double ConfigManager::getVisionTemperature() const { return getDouble("LLM_VISION_TEMPERATURE", 0.5); }

llm::LLMConfig ConfigManager::getVisionModelConfig() const {
    llm::LLMConfig config;
    config.baseUrl = getVisionBaseUrl();
    config.endpoint = getLLMEndpoint();
    config.apiKey = getLLMApiKey();
    config.model = getVisionModel();
    config.maxTokens = getVisionMaxTokens();
    config.temperature = getVisionTemperature();
    config.timeoutSeconds = getLLMTimeoutSeconds();
    config.maxRetries = getLLMMaxRetries();
    return config;
}

// --- System & Performance Settings ---
int ConfigManager::getThreadPoolSize() const { return getInt("THREAD_POOL_SIZE", 4); }
int ConfigManager::getMaxBatchSize() const { return getInt("MAX_BATCH_SIZE", 100); }
int ConfigManager::getHTTPServerPort() const { return getInt("HTTP_SERVER_PORT", 8080); }
std::string ConfigManager::getHTTPServerHost() const { return get("HTTP_SERVER_HOST", "0.0.0.0"); }

// --- Database Performance Settings ---
int ConfigManager::getDBBusyTimeoutMs() const { return getInt("DB_BUSY_TIMEOUT_MS", 5000); }
std::string ConfigManager::getDBJournalMode() const { return get("DB_JOURNAL_MODE", "WAL"); }
bool ConfigManager::getDBSyncOff() const { return getBool("DB_SYNCHRONOUS_OFF", false); }

// --- Full-Text Search Settings ---
int ConfigManager::getSearchMaxCacheSize() const { return getInt("SEARCH_MAX_CACHE_SIZE", 1000); }
int ConfigManager::getSearchMaxContentLength() const { return getInt("SEARCH_MAX_CONTENT_LENGTH", 50000); }
int ConfigManager::getSearchSnippetLength() const { return getInt("SEARCH_SNIPPET_LENGTH", 150); }
int ConfigManager::getSearchDefaultLimit() const { return getInt("SEARCH_DEFAULT_LIMIT", 10); }

// --- Analysis Thresholds ---
int ConfigManager::getMaxLogDisplayFiles() const { return getInt("LOG_MAX_DISPLAY_FILES", 20); }

std::vector<std::string> ConfigManager::getExtraExtensions(const std::string& categoryName) const {
    std::string key = "EXTRA_" + categoryName + "_EXTS";
    std::string value = get(key, "");
    std::vector<std::string> exts;
    if (value.empty()) return exts;
    
    std::istringstream iss(value);
    std::string ext;
    while (std::getline(iss, ext, ',')) {
        ext.erase(0, ext.find_first_not_of(" \t"));
        ext.erase(ext.find_last_not_of(" \t") + 1);
        if (!ext.empty()) exts.push_back(ext);
    }
    return exts;
}
int ConfigManager::getFileAnalysisMaxContent() const { return getInt("FILE_ANALYSIS_MAX_CONTENT", 10000); }
int ConfigManager::getFileAnalysisMaxKeywords() const { return getInt("FILE_ANALYSIS_MAX_KEYWORDS", 10); }
int ConfigManager::getContextLength() const { return getInt("LLM_CONTEXT_LENGTH", 4096); }

// --- Storage & Logging ---
std::string ConfigManager::getDBOutputDir() const { return get("DB_OUTPUT_DIR", "./output"); }
std::string ConfigManager::getDBName() const { return get("DB_NAME", "forensics.db"); }
std::string ConfigManager::getLogLevel() const { return get("LOG_LEVEL", "INFO"); }
std::string ConfigManager::getLogFile() const { return get("LOG_FILE", "forensics.log"); }
std::string ConfigManager::getDebugOutputMode() const { return get("DEBUG_OUTPUT_MODE", "stdout"); }

} // namespace forensics
