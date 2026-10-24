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
#include <atomic>
#include <mutex>
#include <thread>

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

int EventClusterAnalyzer::llmConcurrency() const {
    auto& configManager = ConfigManager::instance();
    if (!configManager.isLoaded()) {
        configManager.load();
    }
    int workers = configManager.getLLMMaxConcurrency();
    return workers < 1 ? 1 : workers;
}

bool EventClusterAnalyzer::analyzeEventCluster(const std::string& eventsDbPath, 
                                           int64_t timeWindow, 
                                           const std::string& eventType, 
                                           const std::string& parentDirectory) {
    return analyzeEventCluster(router_, eventsDbPath, timeWindow, eventType, parentDirectory);
}

bool EventClusterAnalyzer::analyzeEventCluster(const std::shared_ptr<llm::ModelRouter>& router,
                                           const std::string& eventsDbPath, 
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

        // 调用LLM进行分析。并发时每个工作线程传入自己的 router，避免共享
        // LLMClient 把 chat() 锁成串行。
        auto response = router->chat(prompt);
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
                                     summary, description, keywords, router->getLastUsedModel(), isRelevant);
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

    const int total = static_cast<int>(clusters.size());
    if (total == 0) {
        return 0;
    }

    // Same knob as file analysis. Each worker builds its own router because
    // one LLMClient serialises every chat() on a single httplib handle.
    int workers = llmConcurrency();
    if (workers > total) {
        workers = total;
    }

    std::atomic<int> next{0};
    std::atomic<int> analyzed{0};
    std::atomic<bool> stop{false};
    std::mutex progressMutex;

    auto worker = [&]() {
        auto router = std::make_shared<llm::ModelRouter>();
        router->addModel("default", ConfigManager::instance().getTextModelConfig(), llm::ModelInfo{
            "default",
            "text",
            {llm::ModelCapability::TextGeneration, llm::ModelCapability::Analysis}
        });

        while (!stop.load()) {
            const int index = next.fetch_add(1);
            if (index >= total) {
                return;
            }
            auto [timeWindow, eventType, parentDirectory] = clusters[static_cast<size_t>(index)];

            if (progressCallback) {
                std::lock_guard<std::mutex> lock(progressMutex);
                if (!stop.load() && !progressCallback(index + 1, total, eventType)) {
                    std::cout << "Event cluster analysis stopped by callback after "
                              << index << "/" << total << " clusters" << std::endl;
                    stop.store(true);
                    return;
                }
            }
            if (stop.load()) {
                return;
            }

            if (analyzeEventCluster(router, eventsDbPath, timeWindow, eventType, parentDirectory)) {
                analyzed.fetch_add(1);
            }
        }
    };

    if (workers == 1) {
        worker();
    } else {
        std::cout << "Event cluster analysis running with concurrency "
                  << workers << " (" << total << " clusters)" << std::endl;
        std::vector<std::thread> pool;
        pool.reserve(static_cast<size_t>(workers));
        for (int i = 0; i < workers; ++i) {
            pool.emplace_back(worker);
        }
        for (auto& thread : pool) {
            thread.join();
        }
    }
    return analyzed.load();
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

    // 少于预算时无需让 LLM 选择；0 means no upper limit.
    if (maxClusters > 0 && allClusters.size() <= maxClusters) {
        return allClusters;
    }

    const size_t selectionLimit = maxClusters > 0 ? maxClusters : allClusters.size();

    auto truncateToConfiguredLimit = [&]() {
        if (maxClusters > 0 && allClusters.size() > maxClusters) {
            allClusters.resize(maxClusters);
        }
        return allClusters;
    };

    // 构建事件簇列表摘要。没有隐藏的固定 100 条上限；调用方的
    // LLM_MAX_EVENT_CLUSTERS 配置只限制最终分析数量。
    //
    // The list is bounded by characters, not by cluster count. A PC.E01 image
    // produced enough clusters with long parent-directory paths to build a
    // 27 MB prompt, which the provider rejected four times with "input exceeds
    // the context limit" and the whole selection call was lost. Paths are
    // clipped and the list stops at the prompt budget; clusters beyond it keep
    // their natural order and remain eligible through the truncation fallback.
    constexpr size_t kMaxClusterPromptChars = 48000;
    constexpr size_t kMaxDirectoryChars = 200;
    auto clipDir = [](const std::string& value, size_t limit) {
        if (value.size() <= limit) return value;
        std::string out = value.substr(0, limit);
        while (!out.empty() && (static_cast<unsigned char>(out.back()) & 0xC0) == 0x80) {
            out.pop_back();
        }
        return out + "…";
    };
    std::stringstream ss;
    size_t listedClusters = 0;
    for (size_t i = 0; i < allClusters.size(); ++i) {
        auto [timeWindow, eventType, parentDirectory] = allClusters[i];
        ss << "Cluster " << i + 1 << ": Time window=" << timeWindow
           << ", Event type=" << eventType
           << ", Directory=" << (parentDirectory.empty() ? "/" : clipDir(parentDirectory, kMaxDirectoryChars))
           << "\n";
        listedClusters++;
        if (ss.str().size() >= kMaxClusterPromptChars) {
            ss << "... (" << (allClusters.size() - listedClusters)
               << " more clusters omitted from the selection prompt)\n";
            break;
        }
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

Return ONLY a JSON array of cluster indices (0-based) that should be analyzed, limited to )" + std::to_string(selectionLimit) + R"( most important clusters.
Format: [0, 1, 2, ...]
Do not include any explanation, only the JSON array.)";

    try {
        // 调用LLM选择重要事件簇
        // Cluster selection is a ranking task; sampling made the chosen set
        // differ between runs over the same database.
        auto response = router_->chat(prompt, "", 0.0);
        if (!response.success) {
            std::cerr << "LLM request failed: " << response.errorMessage << std::endl;
            return truncateToConfiguredLimit();
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
            return truncateToConfiguredLimit();
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
                      << " — falling back to first " << selectionLimit << " clusters" << std::endl;
            return truncateToConfiguredLimit();
        }

        if (maxClusters > 0 && importantClusters.size() > maxClusters) {
            importantClusters.resize(maxClusters);
        }
        return importantClusters;
    } catch (const std::exception& e) {
        std::cerr << "Failed to select important event clusters: " << e.what() << std::endl;
        return truncateToConfiguredLimit();
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
    // Convert keywords to comma-separated string
    std::stringstream ss;
    for (size_t i = 0; i < keywords.size(); ++i) {
        if (i > 0) ss << ",";
        ss << keywords[i];
    }
    std::string keywordsStr = ss.str();

    // Get current timestamp
    int64_t currentTime = static_cast<int64_t>(std::time(nullptr));

    // Event clustering runs 32 workers against the same events.db while the
    // file-analysis writers are still finishing. Without a busy timeout and a
    // retry, a SQLITE_BUSY here discarded the cluster analysis outright: a
    // PC.E01 run lost 122 clusters with "Failed to update LLM analysis for
    // event cluster". A contended database must delay a result, never drop it.
    constexpr int kBusyTimeoutMs = 30000;
    constexpr int kAttempts = 5;
    constexpr int kBaseSleepMs = 250;

    for (int attempt = 1; attempt <= kAttempts; ++attempt) {
        sqlite3* db = nullptr;
        if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
            std::cerr << "Failed to open database: " << dbPath << std::endl;
            if (db) sqlite3_close(db);
            return false;
        }
        sqlite3_busy_timeout(db, kBusyTimeoutMs);

        sqlite3_stmt* stmt = nullptr;
        int rc = sqlite3_prepare_v2(db, EventExtractorSQL::UPDATE_EVENT_CLUSTER_LLM_ANALYSIS,
                                    -1, &stmt, nullptr);
        if (rc != SQLITE_OK) {
            std::cerr << "Failed to prepare statement: " << sqlite3_errmsg(db) << std::endl;
            sqlite3_close(db);
            return false;
        }

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

        if (rc == SQLITE_DONE) {
            if (changes == 0) {
                std::cerr << "Warning: No rows updated for event cluster" << std::endl;
                return false;
            }
            return true;
        }

        const bool retryable = (rc == SQLITE_BUSY || rc == SQLITE_LOCKED);
        if (!retryable || attempt == kAttempts) {
            std::cerr << "Failed to update LLM analysis for event cluster"
                      << " (rc=" << rc << ", attempt " << attempt << "/" << kAttempts << ")"
                      << std::endl;
            return false;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(kBaseSleepMs * attempt));
    }
    return false;
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

    // Each field is clipped before it reaches the prompt. Only the event count
    // was bounded before, so a cluster whose event descriptions carried large
    // payloads produced a 27 MB request that the provider rejected four times
    // with "input exceeds the context limit" and the cluster analysis was lost.
    // A prompt is a summary: long fields are truncated, not passed through.
    constexpr size_t kMaxPathChars = 512;
    constexpr size_t kMaxDescriptionChars = 512;
    constexpr size_t kMaxSummaryChars = 24000;
    auto clip = [](const std::string& value, size_t limit) {
        if (value.size() <= limit) return value;
        std::string out = value.substr(0, limit);
        // Do not split a UTF-8 sequence in half.
        while (!out.empty() && (static_cast<unsigned char>(out.back()) & 0xC0) == 0x80) {
            out.pop_back();
        }
        out += "…";
        return out;
    };

    ss << "Events:\n";
    for (size_t i = 0; i < events.size() && i < 20; ++i) {
        auto [timestamp, eventType, filePath, fileSize, description] = events[i];
        ss << "- Timestamp: " << timestamp << ", Type: " << clip(eventType, 64)
           << ", Path: " << clip(filePath, kMaxPathChars)
           << ", Size: " << fileSize;
        if (!description.empty()) {
            ss << ", Description: " << clip(description, kMaxDescriptionChars);
        }
        ss << "\n";
        if (ss.str().size() >= kMaxSummaryChars) {
            ss << "... summary truncated at the prompt budget\n";
            break;
        }
    }

    if (events.size() > 20) {
        ss << "... and " << (events.size() - 20) << " more events\n";
    }

    std::string summary = ss.str();
    if (summary.size() > kMaxSummaryChars) {
        summary = clip(summary, kMaxSummaryChars);
    }
    return summary;
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