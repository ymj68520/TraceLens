#pragma once
#ifndef EVENT_CLUSTER_ANALYZER_H
#define EVENT_CLUSTER_ANALYZER_H

#include <string>
#include <vector>
#include <functional>
#include <memory>

namespace forensics {
namespace llm {
    class ModelRouter;
    struct AnalysisResult;
}

class EventClusterAnalyzer {
public:
    EventClusterAnalyzer();
    ~EventClusterAnalyzer();

    bool initialize();

    // 进度回调类型：返回 false 表示任务已取消，应停止分析
    using ProgressCallback = std::function<bool(int, int, const std::string&)>;

    // 分析单个事件簇
    bool analyzeEventCluster(const std::string& eventsDbPath, 
                           int64_t timeWindow, 
                           const std::string& eventType, 
                           const std::string& parentDirectory);

    // 批量分析事件簇
    int analyzeEventClusters(const std::string& eventsDbPath,
                            const std::vector<std::tuple<int64_t, std::string, std::string>>& clusters,
                            ProgressCallback progressCallback = nullptr);

    // 智能分析（只分析重要的事件簇）
    int analyzeSmartEventClusters(const std::string& eventsDbPath,
                                 size_t maxClusters,
                                 ProgressCallback progressCallback = nullptr);

    // 选择重要的事件簇
    std::vector<std::tuple<int64_t, std::string, std::string>> selectImportantEventClusters(
        const std::string& eventsDbPath, 
        size_t maxClusters);

    // 存储事件簇描述
    bool storeClusterDescription(const std::string& dbPath, 
                               int64_t timeWindow, 
                               const std::string& eventType, 
                               const std::string& parentDirectory, 
                               const std::string& summary, 
                               const std::string& description, 
                               const std::vector<std::string>& keywords, 
                               const std::string& modelUsed, 
                               bool isRelevant);

    // 获取所有事件簇
    std::vector<std::tuple<int64_t, std::string, std::string>> getAllEventClusters(
        const std::string& eventsDbPath);

private:
    bool initialized_ = false;
    std::shared_ptr<llm::ModelRouter> router_;

    // 获取事件簇的事件列表
    std::vector<std::tuple<int64_t, std::string, std::string, int64_t, std::string>> getClusterEvents(
        const std::string& eventsDbPath, 
        int64_t timeWindow, 
        const std::string& eventType, 
        const std::string& parentDirectory);

    // 构建事件簇摘要
    std::string buildClusterSummary(
        const std::vector<std::tuple<int64_t, std::string, std::string, int64_t, std::string>>& events);

    // 解析LLM返回的重要事件簇
    std::vector<std::tuple<int64_t, std::string, std::string>> parseImportantClusters(
        const std::string& llmResponse, 
        const std::vector<std::tuple<int64_t, std::string, std::string>>& allClusters);
};

} // namespace forensics

#endif // EVENT_CLUSTER_ANALYZER_H