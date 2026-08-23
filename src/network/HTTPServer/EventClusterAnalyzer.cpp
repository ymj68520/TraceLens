#include "EventClusterAnalyzer.h"
#include "DatabaseManager/SQL/event_extractor_sql.h"
#include "integration/LLMIntegration/ModelRouter.h"
#include "integration/LLMIntegration/FileAnalyzer.h"
#include "core/ConfigManager/ConfigManager.h"
#include <nlohmann/json.hpp>
#include <sqlite3.h>
#include <iostream>
#include <sstream>
#include <algorithm>
#include <ctime>

namespace forensics {

EventClusterAnalyzer::EventClusterAnalyzer() = default;
EventClusterAnalyzer::~EventClusterAnalyzer() = default;

bool EventClusterAnalyzer::initialize() {
    try {
        auto& configManager = ConfigManager::instance();
        if (!configManager.isLoaded()) {
            configManager.load();
        }
        
        // Use standard text model config for forensics analysis
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
        std::cerr << "Failed to initialize EventClusterAnalyzer: " << e.what() << std::endl;
        return false;
    }
}

bool EventClusterAnalyzer::analyzeEventCluster(const std::string& eventsDbPath, 
                                           int64_t timeWindow, 
                                           const std::string& eventType, 
                                           const std::string& parentDirectory) {
    if (!initialized_) {
        if (!initialize()) {
            return false;
        }
    }

    try {
        // 获取事件簇的事件列表
        auto events = getClusterEvents(eventsDbPath, timeWindow, eventType, parentDirectory);
        if (events.empty()) {
            return false;
        }

        // 构建事件簇摘要
        std::string clusterSummary = buildClusterSummary(events);

        // 生成分析提示
        std::string prompt = R"(You are a digital forensics expert. Analyze the following event cluster and provide:

1. A concise summary of what happened in this cluster
2. A detailed description of the events and their significance
3. Key keywords related to this cluster
4. An assessment of whether this cluster is relevant to a forensic investigation (yes/no)

Event cluster details:
)" + clusterSummary + R"(

Format your response as JSON with the following fields:
{
  "summary": "...",
  "description": "...",
  "keywords": ["...", "..."],
  "is_relevant": true/false
}

Do not include any other text outside of the JSON object.)";

        // 调用LLM进行分析
        auto response = router_->chat(prompt);
        if (!response.success) {
            std::cerr << "LLM request failed: " << response.errorMessage << std::endl;
            return false;
        }

        // 解析LLM响应
        nlohmann::json result;
        try {
            result = nlohmann::json::parse(response.content);
        } catch (...) {
            std::cerr << "Failed to parse LLM response" << std::endl;
            return false;
        }

        // 提取分析结果
        std::string summary = result.value("summary", "");
        std::string description = result.value("description", "");
        std::vector<std::string> keywords;
        if (result.contains("keywords") && result["keywords"].is_array()) {
            for (const auto& keyword : result["keywords"]) {
                if (keyword.is_string()) {
                    keywords.push_back(keyword.get<std::string>());
                }
            }
        }
        bool isRelevant = result.value("is_relevant", false);

        // 存储分析结果
        return storeClusterDescription(eventsDbPath, timeWindow, eventType, parentDirectory, 
                                     summary, description, keywords, router_->getLastUsedModel(), isRelevant);
    } catch (const std::exception& e) {
        std::cerr << "Failed to analyze event cluster: " << e.what() << std::endl;
        return false;
    }
}

int EventClusterAnalyzer::analyzeEventClusters(const std::string& eventsDbPath,
                                            const std::vector<std::tuple<int64_t, std::string, std::string>>& clusters,
                                            ProgressCallback progressCallback) {
    if (!initialized_) {
        if (!initialize()) {
            return 0;
        }
    }

    int analyzed = 0;
    int total = clusters.size();

    for (size_t i = 0; i < clusters.size(); ++i) {
        auto [timeWindow, eventType, parentDirectory] = clusters[i];

        if (progressCallback) {
            if (!progressCallback(i + 1, total, eventType)) {
                std::cout << "Event cluster analysis stopped by callback after "
                          << i << "/" << total << " clusters" << std::endl;
                break;  // task cancelled
            }
        }

        if (analyzeEventCluster(eventsDbPath, timeWindow, eventType, parentDirectory)) {
            analyzed++;
        }
    }

    return analyzed;
}

int EventClusterAnalyzer::analyzeSmartEventClusters(const std::string& eventsDbPath,
                                                 size_t maxClusters,
                                                 ProgressCallback progressCallback) {
    if (!initialized_) {
        if (!initialize()) {
            return 0;
        }
    }

    // 选择重要的事件簇
    auto importantClusters = selectImportantEventClusters(eventsDbPath, maxClusters);
    if (importantClusters.empty()) {
        std::cerr << "No important event clusters selected" << std::endl;
        return 0;
    }

    // 分析重要的事件簇
    return analyzeEventClusters(eventsDbPath, importantClusters, std::move(progressCallback));
}

std::vector<std::tuple<int64_t, std::string, std::string>> EventClusterAnalyzer::selectImportantEventClusters(
    const std::string& eventsDbPath, 
    size_t maxClusters) {
    if (!initialized_) {
        if (!initialize()) {
            return {};
        }
    }

    // 获取所有事件簇
    auto allClusters = getAllEventClusters(eventsDbPath);
    if (allClusters.empty()) {
        return {};
    }

    // 少于预算时无需让 LLM 选择
    if (allClusters.size() <= maxClusters) {
        return allClusters;
    }

    // 构建事件簇列表摘要
    std::stringstream ss;
    for (size_t i = 0; i < allClusters.size() && i < 100; ++i) {
        auto [timeWindow, eventType, parentDirectory] = allClusters[i];
        ss << "Cluster " << i + 1 << ": Time window=" << timeWindow 
           << ", Event type=" << eventType 
           << ", Directory=" << (parentDirectory.empty() ? "/" : parentDirectory) << "\n";
    }

    // 生成选择重要事件簇的提示
    std::string prompt = R"(You are a digital forensics expert. Analyze the following list of event clusters from a forensic investigation and identify the most important clusters for further analysis.

Consider:
- Clusters with suspicious activities
- Clusters involving system files or critical directories
- Clusters with a high number of events
- Clusters that might indicate malicious activity
- Clusters related to user activity or file modifications

Event clusters:
)" + ss.str() + R"(

Return ONLY a JSON array of cluster indices (0-based) that should be analyzed, limited to )" + std::to_string(maxClusters) + R"( most important clusters.
Format: [0, 1, 2, ...]
Do not include any explanation, only the JSON array.)";

    try {
        // 调用LLM选择重要事件簇
        auto response = router_->chat(prompt);
        if (!response.success) {
            std::cerr << "LLM request failed: " << response.errorMessage << std::endl;
            //  fallback: 返回前N个事件簇
            if (allClusters.size() > maxClusters) {
                allClusters.resize(maxClusters);
            }
            return allClusters;
        }

        // 解析LLM响应
        std::vector<size_t> selectedIndices;
        try {
            size_t start = response.content.find('[');
            size_t end = response.content.rfind(']');
            if (start != std::string::npos && end != std::string::npos && end > start) {
                std::string jsonStr = response.content.substr(start, end - start + 1);
                auto jsonArray = nlohmann::json::parse(jsonStr);
                for (const auto& item : jsonArray) {
                    if (item.is_number()) {
                        selectedIndices.push_back(item.get<size_t>());
                    }
                }
            }
        } catch (...) {
            std::cerr << "Failed to parse LLM response" << std::endl;
            //  fallback: 返回前N个事件簇
            if (allClusters.size() > maxClusters) {
                allClusters.resize(maxClusters);
            }
            return allClusters;
        }

        // 提取选中的事件簇
        std::vector<std::tuple<int64_t, std::string, std::string>> importantClusters;
        for (size_t index : selectedIndices) {
            if (index < allClusters.size()) {
                importantClusters.push_back(allClusters[index]);
            }
        }

        // The model responded but its indices resolved to nothing usable —
        // fall back to the first N clusters instead of skipping the whole stage.
        if (importantClusters.empty()) {
            std::cerr << "LLM cluster selection resolved to 0 clusters"
                      << " — falling back to first " << maxClusters << " clusters" << std::endl;
            if (allClusters.size() > maxClusters) {
                allClusters.resize(maxClusters);
            }
            return allClusters;
        }

        return importantClusters;
    } catch (const std::exception& e) {
        std::cerr << "Failed to select important event clusters: " << e.what() << std::endl;
        //  fallback: 返回前N个事件簇
        if (allClusters.size() > maxClusters) {
            allClusters.resize(maxClusters);
        }
        return allClusters;
    }
}

bool EventClusterAnalyzer::storeClusterDescription(const std::string& dbPath, 
                                               int64_t timeWindow, 
                                               const std::string& eventType, 
                                               const std::string& parentDirectory, 
                                               const std::string& summary, 
                                               const std::string& description, 
                                               const std::vector<std::string>& keywords, 
                                               const std::string& modelUsed, 
                                               bool isRelevant) {
    sqlite3* db = nullptr;
    int rc = sqlite3_open(dbPath.c_str(), &db);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to open database: " << dbPath << std::endl;
        return false;
    }

    // Convert keywords to comma-separated string
    std::stringstream ss;
    for (size_t i = 0; i < keywords.size(); ++i) {
        if (i > 0) ss << ",";
        ss << keywords[i];
    }
    std::string keywordsStr = ss.str();

    // Get current timestamp
    int64_t currentTime = static_cast<int64_t>(std::time(nullptr));

    // Use UPDATE_EVENT_CLUSTER_LLM_ANALYSIS from event_extractor_sql.h
    sqlite3_stmt* stmt = nullptr;
    rc = sqlite3_prepare_v2(db, EventExtractorSQL::UPDATE_EVENT_CLUSTER_LLM_ANALYSIS, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to prepare statement: " << sqlite3_errmsg(db) << std::endl;
        sqlite3_close(db);
        return false;
    }

    // Bind parameters
    sqlite3_bind_text(stmt, 1, summary.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, keywordsStr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 4, currentTime);
    sqlite3_bind_text(stmt, 5, modelUsed.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 6, isRelevant ? 1 : 0);
    sqlite3_bind_int64(stmt, 7, timeWindow);
    sqlite3_bind_text(stmt, 8, eventType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, parentDirectory.c_str(), -1, SQLITE_TRANSIENT);

    rc = sqlite3_step(stmt);
    int changes = sqlite3_changes(db);
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    if (rc != SQLITE_DONE) {
        std::cerr << "Failed to update LLM analysis for event cluster" << std::endl;
        return false;
    }

    if (changes == 0) {
        std::cerr << "Warning: No rows updated for event cluster" << std::endl;
        return false;
    }

    return true;
}

std::vector<std::tuple<int64_t, std::string, std::string, int64_t, std::string>> EventClusterAnalyzer::getClusterEvents(
    const std::string& eventsDbPath, 
    int64_t timeWindow, 
    const std::string& eventType, 
    const std::string& parentDirectory) {
    std::vector<std::tuple<int64_t, std::string, std::string, int64_t, std::string>> events;

    sqlite3* db = nullptr;
    int rc = sqlite3_open(eventsDbPath.c_str(), &db);
    if (rc != SQLITE_OK) {
        return events;
    }

    // Build query to get events in this cluster
    std::string sql = "SELECT timestamp, event_type, file_path, file_size, description FROM events WHERE (timestamp / 60) = ? AND event_type = ?";

    if (!parentDirectory.empty()) {
        if (parentDirectory == "/") {
            sql += " AND (file_path NOT LIKE '%/%' OR file_path LIKE '/%')";
        } else {
            sql += " AND file_path LIKE ?";
        }
    }

    sql += " ORDER BY timestamp ASC";

    sqlite3_stmt* stmt = nullptr;
    rc = sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        sqlite3_close(db);
        return events;
    }

    // Bind parameters
    sqlite3_bind_int64(stmt, 1, timeWindow);
    sqlite3_bind_text(stmt, 2, eventType.c_str(), -1, SQLITE_TRANSIENT);
    
    if (!parentDirectory.empty() && parentDirectory != "/") {
        std::string likePattern = parentDirectory + "%";
        sqlite3_bind_text(stmt, 3, likePattern.c_str(), -1, SQLITE_TRANSIENT);
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        int64_t timestamp = sqlite3_column_int64(stmt, 0);
        std::string eventType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        std::string filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        int64_t fileSize = sqlite3_column_int64(stmt, 3);
        std::string description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));

        events.emplace_back(timestamp, eventType, filePath, fileSize, description);
    }

    sqlite3_finalize(stmt);
    sqlite3_close(db);

    return events;
}

std::string EventClusterAnalyzer::buildClusterSummary(
    const std::vector<std::tuple<int64_t, std::string, std::string, int64_t, std::string>>& events) {
    std::stringstream ss;

    ss << "Total events: " << events.size() << "\n";
    
    if (!events.empty()) {
        auto [firstTimestamp, e1, e2, e3, e4] = events[0];
        auto [lastTimestamp, e5, e6, e7, e8] = events.back();
        ss << "Time range: " << firstTimestamp << " to " << lastTimestamp << "\n";
    }

    ss << "Events:\n";
    for (size_t i = 0; i < events.size() && i < 20; ++i) {
        auto [timestamp, eventType, filePath, fileSize, description] = events[i];
        ss << "- Timestamp: " << timestamp << ", Type: " << eventType 
           << ", Path: " << filePath 
           << ", Size: " << fileSize;
        if (!description.empty()) {
            ss << ", Description: " << description;
        }
        ss << "\n";
    }

    if (events.size() > 20) {
        ss << "... and " << (events.size() - 20) << " more events\n";
    }

    return ss.str();
}

std::vector<std::tuple<int64_t, std::string, std::string>> EventClusterAnalyzer::getAllEventClusters(
    const std::string& eventsDbPath) {
    std::vector<std::tuple<int64_t, std::string, std::string>> clusters;

    sqlite3* db = nullptr;
    int rc = sqlite3_open(eventsDbPath.c_str(), &db);
    if (rc != SQLITE_OK) {
        return clusters;
    }

    // Query to get all unique clusters
    std::string sql = R"(
        SELECT 
            (timestamp / 60) as time_window, 
            event_type, 
            CASE WHEN file_path LIKE '%/%' THEN RTRIM(file_path, REPLACE(file_path, '/', '')) ELSE '' END as parent_directory
        FROM events
        GROUP BY time_window, event_type, parent_directory
        ORDER BY COUNT(*) DESC
    )";

    sqlite3_stmt* stmt = nullptr;
    rc = sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        sqlite3_close(db);
        return clusters;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        int64_t timeWindow = sqlite3_column_int64(stmt, 0);
        std::string eventType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        std::string parentDirectory = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));

        clusters.emplace_back(timeWindow, eventType, parentDirectory);
    }

    sqlite3_finalize(stmt);
    sqlite3_close(db);

    return clusters;
}

} // namespace forensics