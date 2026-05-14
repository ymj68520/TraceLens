// DLLAnalyzerLLMService.h
// LLM-powered analysis service for DLL/PE/ELF files
//
// 职责：
//   - 使用LLM分析DLL文件的元数据和特征
//   - 生成智能摘要和安全评估
//   - 提供威胁情报和缓解建议
//   - 识别潜在的恶意行为模式

#pragma once

#ifndef DLL_ANALYZER_LLM_SERVICE_H
#define DLL_ANALYZER_LLM_SERVICE_H

#include <string>
#include <vector>
#include <functional>
#include <memory>
#include "analyzers/DLLAnalyzer/Common/DLLDataTypes.h"
#include "LLMIntegration/LLMDataTypes.h"
#include "LLMIntegration/ModelRouter.h"
#include "LLMIntegration/FileAnalyzer.h"
#include "ConfigManager/ConfigManager.h"

namespace forensics {
namespace dll {

/**
 * @brief LLM分析选项
 */
struct DLLAnalysisOptions {
    size_t maxContentLength = 10000;       // 最大内容长度
    bool generateSummary = true;           // 生成摘要
    bool generateDescription = true;       // 生成描述
    bool extractKeywords = true;           // 提取关键词
    bool analyzeThreats = true;            // 威胁分析
    bool analyzeBehavior = true;           // 行为分析
    std::vector<std::string> focusAreas;   // 重点关注领域
};

/**
 * @brief LLM分析结果（扩展DLLAnalysisResult）
 */
struct DLLLLMResult {
    std::string summary;                   // 文件功能摘要
    std::string description;               // 详细描述
    std::vector<std::string> keywords;     // 关键词
    std::string threatAssessment;          // 威胁评估
    std::string behaviorAnalysis;          // 行为分析
    std::vector<std::string> indicators;   // 可疑指标列表
    std::string recommendations;           // 建议措施
    std::string modelUsed;                 // 使用的模型
    int tokensUsed = 0;                    // 使用的token数
    double analysisTimeMs = 0.0;           // 分析耗时
    bool success = false;                  // 是否成功
    std::string errorMessage;              // 错误信息
};

/**
 * @brief DLL文件的LLM分析服务
 *
 * 使用LLM对DLL分析结果进行深度分析：
 *   - 分析PE/ELF元数据和结构特征
 *   - 评估威胁级别和可疑特征
 *   - 提供安全建议和缓解措施
 *   - 生成IOC（入侵指标）列表
 */
class DLLAnalyzerLLMService {
public:
    /**
     * @brief 构造函数
     */
    DLLAnalyzerLLMService();
    ~DLLAnalyzerLLMService();

    // 禁止拷贝
    DLLAnalyzerLLMService(const DLLAnalyzerLLMService&) = delete;
    DLLAnalyzerLLMService& operator=(const DLLAnalyzerLLMService&) = delete;

    /**
     * @brief 初始化服务
     * @return true如果初始化成功
     */
    bool initialize();

    /**
     * @brief 分析单个DLL文件
     * @param result DLL分析结果
     * @param options 分析选项
     * @return LLM分析结果
     */
    DLLLLMResult analyzeDLL(const DLLAnalysisResult& result,
                            const DLLAnalysisOptions& options = {});

    /**
     * @brief 批量分析多个DLL文件
     * @param results DLL分析结果列表
     * @param options 分析选项
     * @param progressCallback 进度回调
     * @return LLM分析结果列表
     */
    std::vector<DLLLLMResult> analyzeBatch(
        const std::vector<DLLAnalysisResult>& results,
        const DLLAnalysisOptions& options = {},
        std::function<void(size_t, size_t, const std::string&)> progressCallback = nullptr);

    /**
     * @brief 仅对高威胁DLL进行分析
     * @param results DLL分析结果列表
     * @param minThreatScore 最低威胁评分
     * @param options 分析选项
     * @return LLM分析结果列表
     */
    std::vector<DLLLLMResult> analyzeHighThreatDLLs(
        const std::vector<DLLAnalysisResult>& results,
        int minThreatScore = 70,
        const DLLAnalysisOptions& options = {});

    /**
     * @brief 检查服务是否可用
     * @return true如果LLM服务已配置且可用
     */
    bool isAvailable() const;

    /**
     * @brief 获取最后错误信息
     */
    std::string getLastError() const;

private:
    /**
     * @brief 构建DLL分析的prompt
     */
    std::string buildDLLAnalysisPrompt(const DLLAnalysisResult& result,
                                       const DLLAnalysisOptions& options);

    /**
     * @brief 构建威胁分析prompt
     */
    std::string buildThreatAnalysisPrompt(const DLLAnalysisResult& result);

    /**
     * @brief 解析LLM响应
     */
    DLLLLMResult parseLLMResponse(const llm::AnalysisResult& llmResult,
                                  const DLLAnalysisResult& input);

    /**
     * @brief 从文本中提取JSON字符串
     * @param text 包含JSON的文本（可能包含markdown代码块）
     * @return 提取的JSON字符串，如果未找到则返回空
     */
    std::string extractJSONFromText(const std::string& text);

    /**
     * @brief 解析JSON格式的LLM响应
     */
    DLLLLMResult parseJSONResponse(const std::string& jsonResponse);

    /**
     * @brief 格式化DLL元数据为文本描述
     */
    std::string formatDLLMetadata(const DLLAnalysisResult& result);

    /**
     * @brief 格式化导入函数列表
     */
    std::string formatImports(const std::vector<ImportedDLL>& imports);

    /**
     * @brief 格式化导出函数列表
     */
    std::string formatExports(const std::vector<ExportedFunction>& exports);

    /**
     * @brief 格式化异常检测结果
     */
    std::string formatAnomalies(const std::vector<Anomaly>& anomalies);

    /**
     * @brief 格式化依赖项
     */
    std::string formatDependencies(const std::vector<ELFDependency>& deps);

    std::shared_ptr<llm::ModelRouter> router_;
    std::unique_ptr<llm::FileAnalyzer> fileAnalyzer_;
    bool initialized_ = false;
    std::string lastError_;

    // 默认prompts
    static const std::string DEFAULT_ANALYSIS_PROMPT;
    static const std::string DEFAULT_THREAT_PROMPT;
};

} // namespace dll
} // namespace forensics

#endif // DLL_ANALYZER_LLM_SERVICE_H
