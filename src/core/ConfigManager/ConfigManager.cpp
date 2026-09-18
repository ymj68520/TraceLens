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
std::string ConfigManager::getLLMBaseUrl() const { return get("LLM_BASE_URL", "http://192.168.31.170:1234"); }
std::string ConfigManager::getLLMEndpoint() const { return get("LLM_ENDPOINT", "/v1/chat/completions"); }
std::string ConfigManager::getLLMApiKey() const { return get("LLM_API_KEY", ""); }
int ConfigManager::getLLMTimeoutSeconds() const { return getInt("LLM_TIMEOUT_SECONDS", 120); }
int ConfigManager::getLLMMaxRetries() const { return getInt("LLM_MAX_RETRIES", 3); }
namespace {

int bounded_limit(const ConfigManager& config, const char* key, int defaultValue,
                  int maximum) {
    const std::string raw = config.get(key, "");
    if (raw == "0") return 0;  // Unlimited is explicit opt-in only.
    const int value = raw.empty() ? defaultValue : config.getInt(key, defaultValue);
    return std::clamp(value, 1, maximum);
}

}  // namespace

// All analysis stages have finite defaults. A larger workload requires an
// explicit configuration value; zero is retained only as an explicit opt-in.
int ConfigManager::getLLMMaxFiles() const { return bounded_limit(*this, "LLM_MAX_FILES", 500, 100000); }
int ConfigManager::getLLMMaxEventClusters() const { return bounded_limit(*this, "LLM_MAX_EVENT_CLUSTERS", 200, 100000); }
int ConfigManager::getLLMSmartCandidateFiles() const { return bounded_limit(*this, "LLM_SMART_CANDIDATE_FILES", 1000, 100000); }
int ConfigManager::getLLMMaxArtifacts() const { return bounded_limit(*this, "LLM_MAX_ARTIFACTS", 500, 100000); }
int ConfigManager::getLLMMaxContentLength() const { return bounded_limit(*this, "LLM_MAX_CONTENT_LENGTH", 10000, 1000000); }
// SPEC D: images go straight to the multimodal model; oversized ones fall
// back to metadata-only instead of shipping a huge base64 payload.
int ConfigManager::getLLMImageMaxBytes() const { return bounded_limit(*this, "LLM_IMAGE_MAX_BYTES", 8388608, 104857600); }
std::string ConfigManager::getLLMImageDetail() const {
    std::string detail = get("LLM_IMAGE_DETAIL", "low");
    return detail.empty() ? "low" : detail;
}
// SPEC C: artifacts are packed N per request (1 = legacy per-row calls).
int ConfigManager::getLLMArtifactBatchSize() const { return bounded_limit(*this, "LLM_ARTIFACT_BATCH_SIZE", 1, 64); }
int ConfigManager::getLLMArtifactBatchRetries() const { return bounded_limit(*this, "LLM_ARTIFACT_BATCH_RETRIES", 1, 5); }
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
std::string ConfigManager::getPythonServiceUrl() const { return get("PYTHON_SERVICE_URL", "http://localhost:" + std::to_string(getInt("PYTHON_HTTP_PORT", 8090))); }
std::string ConfigManager::getMCPHost() const { return get("MCP_HOST", "127.0.0.1"); }

std::vector<std::string> ConfigManager::getMCPAllowedPaths() const {
    std::vector<std::string> paths;
    std::string value = get("MCP_ALLOWED_PATHS", "");
    std::istringstream iss(value);
    std::string path;
    while (std::getline(iss, path, ',')) {
        path.erase(0, path.find_first_not_of(" \t"));
        path.erase(path.find_last_not_of(" \t") + 1);
        if (!path.empty()) paths.push_back(path);
    }
    return paths;
}

int ConfigManager::getMCPMaxReadBytes() const {
    return std::clamp(getInt("MCP_MAX_READ_BYTES", 1024 * 1024), 1, 100 * 1024 * 1024);
}

int ConfigManager::getMCPMaxListEntries() const {
    return std::clamp(getInt("MCP_MAX_LIST_ENTRIES", 10000), 1, 100000);
}

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
