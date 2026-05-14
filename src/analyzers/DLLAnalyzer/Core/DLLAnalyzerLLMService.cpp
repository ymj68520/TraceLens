// DLLAnalyzerLLMService.cpp
// DLL文件LLM分析服务实现
//
// 使用LLM对DLL/PE/ELF文件进行智能分析：
//   - 解释文件功能和目的
//   - 评估安全威胁
//   - 识别可疑行为特征
//   - 提供缓解建议

#include "DLLAnalyzerLLMService.h"
#include "analyzers/DLLAnalyzer/Common/DLLDataTypes.h"
#include "LLMIntegration/LLMDataTypes.h"
#include "ConfigManager/ConfigManager.h"
#include "core/Logger/Logger.h"
#include <nlohmann/json.hpp>
#include <sstream>
#include <algorithm>

namespace forensics {
namespace dll {

// 静态成员初始化
const std::string DLLAnalyzerLLMService::DEFAULT_ANALYSIS_PROMPT = R"(
你是一位专业的恶意软件分析专家和安全研究员。
请分析以下DLL/可执行文件的元数据，并提供专业的安全评估。

任务：
1. 总结该文件的主要功能和目的
2. 评估其潜在的安全风险级别
3. 识别可疑的API调用或依赖项
4. 如果这是已知的恶意软件家族，尝试识别或分类
5. 提供调查建议和缓解措施

请以JSON格式返回结果：
{
    "summary": "文件功能摘要（2-3句话）",
    "description": "详细分析报告（包括功能、风险、行为特征）",
    "keywords": ["关键词1", "关键词2", "关键词3"],
    "threat_assessment": "威胁级别：低/中/高/严重 - 理由",
    "behavior_analysis": "基于导入/导出函数的行为推测",
    "indicators": ["可疑指标1", "可疑指标2"],
    "recommendations": "建议措施"
}
)";

const std::string DLLAnalyzerLLMService::DEFAULT_THREAT_PROMPT = R"(
你是一位恶意软件威胁情报专家。
请基于以下技术指标评估该文件的威胁级别。

威胁评估指标：
- 数字签名状态
- 导入函数（特别是进程注入、注册表操作、网络通信等）
- 异常结构特征（高熵节、异常权限、非常见节名等）
- 编译时间戳和元数据异常
- 依赖项和加载行为

请提供：
1. 威胁级别（Benign/Low/Medium/High/Critical）
2. 主要威胁指标列表
3. 可能的攻击技术（基于MITRE ATT&CK框架）
4. 缓解建议
5. 进一步调查的方向

以JSON格式返回。
)";

// ============================================================================
// 构造/析构
// ============================================================================

DLLAnalyzerLLMService::DLLAnalyzerLLMService() = default;

DLLAnalyzerLLMService::~DLLAnalyzerLLMService() = default;

// ============================================================================
// 公共接口
// ============================================================================

bool DLLAnalyzerLLMService::initialize() {
    try {
        auto& configManager = ConfigManager::instance();
        if (!configManager.isLoaded()) {
            configManager.load();
        }

        // 使用文本模型配置
        auto config = configManager.getTextModelConfig();

        router_ = std::make_shared<llm::ModelRouter>();
        router_->addModel("dll_analyzer", config, llm::ModelInfo{
            "dll_analyzer",
            "DLL threat analysis specialist",
            {llm::ModelCapability::Analysis, llm::ModelCapability::TextGeneration}
        });

        fileAnalyzer_ = std::make_unique<llm::FileAnalyzer>(router_);
        fileAnalyzer_->setSummaryPrompt(DEFAULT_ANALYSIS_PROMPT);
        fileAnalyzer_->setDescriptionPrompt(DEFAULT_THREAT_PROMPT);

        initialized_ = true;
        LOG_INFO("DLLAnalyzerLLMService initialized successfully");
        return true;
    } catch (const std::exception& e) {
        lastError_ = std::string("Failed to initialize: ") + e.what();
        LOG_ERROR(lastError_);
        return false;
    }
}

DLLLLMResult DLLAnalyzerLLMService::analyzeDLL(const DLLAnalysisResult& result,
                                               const DLLAnalysisOptions& options) {
    DLLLLMResult llmResult;

    if (!initialized_) {
        if (!initialize()) {
            llmResult.errorMessage = "Failed to initialize LLM service";
            return llmResult;
        }
    }

    try {
        // 构建prompt
        std::string prompt = buildDLLAnalysisPrompt(result, options);

        // 调用LLM
        llm::ChatMessage userMessage("user", prompt);
        std::vector<llm::ChatMessage> messages = {userMessage};
        auto response = router_->chat(messages);

        if (!response.success) {
            llmResult.errorMessage = response.errorMessage;
            llmResult.success = false;
            return llmResult;
        }

        // 解析响应
        llmResult = parseLLMResponse(
            llm::AnalysisResult{
                result.filePath,
                "",  // summary
                response.content,
                {},
                "application/x-dll",
                static_cast<int64_t>(result.fileSize),
                true,
                "",
                "dll_analyzer",
                response.promptTokens + response.completionTokens,
                0.0
            },
            result
        );

        llmResult.success = true;
        llmResult.modelUsed = "dll_analyzer";
        llmResult.tokensUsed = response.promptTokens + response.completionTokens;

    } catch (const std::exception& e) {
        llmResult.errorMessage = std::string("Analysis failed: ") + e.what();
        llmResult.success = false;
    }

    return llmResult;
}

std::vector<DLLLLMResult> DLLAnalyzerLLMService::analyzeBatch(
    const std::vector<DLLAnalysisResult>& results,
    const DLLAnalysisOptions& options,
    std::function<void(size_t, size_t, const std::string&)> progressCallback) {

    std::vector<DLLLLMResult> llmResults;
    llmResults.reserve(results.size());

    size_t total = results.size();
    for (size_t i = 0; i < results.size(); ++i) {
        const auto& result = results[i];

        if (progressCallback) {
            progressCallback(i + 1, total, result.fileName);
        }

        auto llmResult = analyzeDLL(result, options);
        llmResults.push_back(llmResult);
    }

    return llmResults;
}

std::vector<DLLLLMResult> DLLAnalyzerLLMService::analyzeHighThreatDLLs(
    const std::vector<DLLAnalysisResult>& results,
    int minThreatScore,
    const DLLAnalysisOptions& options) {

    std::vector<DLLAnalysisResult> highThreatResults;

    // 筛选高威胁DLL
    for (const auto& result : results) {
        if (result.threatScore >= minThreatScore) {
            highThreatResults.push_back(result);
        }
    }

    // 批量分析
    return analyzeBatch(highThreatResults, options);
}

bool DLLAnalyzerLLMService::isAvailable() const {
    return initialized_ && router_ != nullptr;
}

std::string DLLAnalyzerLLMService::getLastError() const {
    return lastError_;
}

// ============================================================================
// Prompt构建
// ============================================================================

std::string DLLAnalyzerLLMService::buildDLLAnalysisPrompt(const DLLAnalysisResult& result,
                                                            const DLLAnalysisOptions& options) {
    std::ostringstream prompt;

    prompt << DEFAULT_ANALYSIS_PROMPT << "\n\n";
    prompt << "=== DLL文件元数据 ===\n\n";
    prompt << formatDLLMetadata(result) << "\n\n";

    if (options.analyzeThreats && !result.anomalies.empty()) {
        prompt << "=== 异常检测结果 ===\n\n";
        prompt << formatAnomalies(result.anomalies) << "\n\n";
    }

    if (options.analyzeBehavior && !result.imports.empty()) {
        prompt << "=== 导入函数 ===\n\n";
        prompt << formatImports(result.imports) << "\n\n";
    }

    if (!result.exports.empty()) {
        prompt << "=== 导出函数 ===\n\n";
        prompt << formatExports(result.exports) << "\n\n";
    }

    prompt << "请基于以上信息提供详细的安全分析报告。";

    return prompt.str();
}

std::string DLLAnalyzerLLMService::buildThreatAnalysisPrompt(const DLLAnalysisResult& result) {
    std::ostringstream prompt;

    prompt << DEFAULT_THREAT_PROMPT << "\n\n";
    prompt << "=== 威胁指标 ===\n\n";
    prompt << "- 威胁评分: " << result.threatScore << "/100\n";
    prompt << "- 数字签名: " << result.signatureStatus << "\n";
    prompt << "- 文件大小: " << result.fileSize << " bytes\n";
    prompt << "- 文件类型: " << (result.peHeader.isValid ? "PE" : "ELF") << "\n\n";

    if (!result.anomalies.empty()) {
        prompt << formatAnomalies(result.anomalies) << "\n\n";
    }

    prompt << "=== 可疑特征 ===\n";
    if (result.threatScore > 50) {
        prompt << "- 威胁评分较高（>50），需要重点分析\n";
    }
    if (result.signatureStatus == "Unsigned") {
        prompt << "- 无数字签名\n";
    }

    return prompt.str();
}

// ============================================================================
// 格式化辅助函数
// ============================================================================

std::string DLLAnalyzerLLMService::formatDLLMetadata(const DLLAnalysisResult& result) {
    std::ostringstream oss;

    oss << "文件名: " << result.fileName << "\n";
    oss << "文件路径: " << result.filePath << "\n";
    oss << "文件大小: " << result.fileSize << " bytes\n";

    if (result.peHeader.isValid) {
        oss << "格式: " << result.peHeader.format << "\n";
        oss << "机器类型: " << static_cast<int>(result.peHeader.machine) << "\n";
        oss << "时间戳: " << result.peHeader.timestamp << "\n";
        oss << "入口点: 0x" << std::hex << result.peHeader.entryPointRVA << std::dec << "\n";

        if (!result.peHeader.sections.empty()) {
            oss << "节数量: " << result.peHeader.sections.size() << "\n";
            for (const auto& section : result.peHeader.sections) {
                oss << "  - " << section.name
                    << " (VA: 0x" << std::hex << section.virtualAddress
                    << ", Size: " << std::dec << section.virtualSize
                    << ", Entropy: " << std::fixed << std::setprecision(2) << section.entropy << ")\n";
            }
        }
    }

    oss << "\n哈希:\n";
    oss << "  MD5:    " << result.md5Hash << "\n";
    oss << "  SHA1:   " << result.sha1Hash << "\n";
    oss << "  SHA256: " << result.sha256Hash << "\n";
    if (!result.impHash.empty()) {
        oss << "  ImpHash: " << result.impHash << "\n";
    }

    oss << "\n数字签名: " << result.signatureStatus << "\n";
    if (!result.signerName.empty()) {
        oss << "签名者: " << result.signerName << "\n";
    }

    oss << "\n威胁评分: " << result.threatScore << "/100\n";

    return oss.str();
}

std::string DLLAnalyzerLLMService::formatImports(const std::vector<ImportedDLL>& imports) {
    std::ostringstream oss;

    for (const auto& dll : imports) {
        oss << "[" << dll.name << "]\n";
        for (const auto& func : dll.functions) {
            oss << "  - " << func << "\n";
        }
    }

    return oss.str();
}

std::string DLLAnalyzerLLMService::formatExports(const std::vector<ExportedFunction>& exports) {
    std::ostringstream oss;

    for (const auto& exp : exports) {
        oss << "  - " << exp.name;
        if (exp.ordinal > 0) {
            oss << " (ordinal: " << exp.ordinal << ")";
        }
        oss << "\n";
    }

    return oss.str();
}

std::string DLLAnalyzerLLMService::formatAnomalies(const std::vector<Anomaly>& anomalies) {
    std::ostringstream oss;

    for (const auto& anomaly : anomalies) {
        oss << "- [" << anomaly.type << "] "
            << anomaly.description
            << " (风险分数: " << anomaly.riskScore << ")\n";
    }

    return oss.str();
}

std::string DLLAnalyzerLLMService::formatDependencies(const std::vector<ELFDependency>& deps) {
    std::ostringstream oss;

    for (const auto& dep : deps) {
        oss << "- " << dep.name
            << " (类型: " << dep.type
            << ")\n";
    }

    return oss.str();
}

// ============================================================================
// 响应解析
// ============================================================================

std::string DLLAnalyzerLLMService::extractJSONFromText(const std::string& text) {
    // 查找markdown代码块 ```json ... ```
    std::string jsonBlockStart = "```json";
    size_t jsonBlockPos = text.find(jsonBlockStart);
    if (jsonBlockPos != std::string::npos) {
        size_t jsonStart = jsonBlockPos + jsonBlockStart.length();
        // 跳过可能的换行符
        while (jsonStart < text.length() && (text[jsonStart] == '\n' || text[jsonStart] == '\r')) {
            jsonStart++;
        }
        size_t jsonEnd = text.find("```", jsonStart);
        if (jsonEnd != std::string::npos) {
            return text.substr(jsonStart, jsonEnd - jsonStart);
        }
    }

    // 查找通用代码块 ``` ... ```
    std::string blockStart = "```";
    size_t blockPos = text.find(blockStart);
    if (blockPos != std::string::npos) {
        size_t contentStart = blockPos + blockStart.length();
        // 跳过语言标识符（如果有）
        while (contentStart < text.length() && text[contentStart] != '\n' && text[contentStart] != '\r') {
            contentStart++;
        }
        // 跳过换行符
        while (contentStart < text.length() && (text[contentStart] == '\n' || text[contentStart] == '\r')) {
            contentStart++;
        }
        size_t contentEnd = text.find("```", contentStart);
        if (contentEnd != std::string::npos) {
            std::string candidate = text.substr(contentStart, contentEnd - contentStart);
            // 验证是否为有效JSON（以{或[开头）
            if (!candidate.empty() && (candidate[0] == '{' || candidate[0] == '[')) {
                return candidate;
            }
        }
    }

    // 如果没有代码块，检查整个文本是否就是JSON
    std::string trimmed = text;
    // 去除前导空白
    size_t firstNonSpace = trimmed.find_first_not_of(" \t\n\r");
    if (firstNonSpace != std::string::npos) {
        trimmed = trimmed.substr(firstNonSpace);
    }
    // 去除尾部空白
    size_t lastNonSpace = trimmed.find_last_not_of(" \t\n\r");
    if (lastNonSpace != std::string::npos) {
        trimmed = trimmed.substr(0, lastNonSpace + 1);
    }

    if (!trimmed.empty() && (trimmed[0] == '{' || trimmed[0] == '[')) {
        return trimmed;
    }

    return "";
}

DLLLLMResult DLLAnalyzerLLMService::parseLLMResponse(const llm::AnalysisResult& llmResult,
                                                             const DLLAnalysisResult& input) {
    DLLLLMResult result;

    // 首先复制基本字段
    result.success = llmResult.success;
    result.modelUsed = llmResult.modelUsed;
    result.tokensUsed = llmResult.tokensUsed;
    result.analysisTimeMs = llmResult.analysisTimeMs;

    if (!llmResult.success) {
        result.errorMessage = llmResult.errorMessage;
        return result;
    }

    // 尝试从description中提取JSON格式的响应
    std::string description = llmResult.description;

    // 清理markdown代码块标记
    std::string jsonStr = extractJSONFromText(description);

    if (!jsonStr.empty()) {
        // 尝试解析JSON响应
        DLLLLMResult jsonResult = parseJSONResponse(jsonStr);
        if (jsonResult.success) {
            // 合并JSON解析结果
            result.summary = jsonResult.summary.empty() ? llmResult.summary : jsonResult.summary;
            result.description = jsonResult.description.empty() ? description : jsonResult.description;
            result.keywords = jsonResult.keywords.empty() ? llmResult.keywords : jsonResult.keywords;
            result.threatAssessment = jsonResult.threatAssessment;
            result.behaviorAnalysis = jsonResult.behaviorAnalysis;
            result.indicators = jsonResult.indicators;
            result.recommendations = jsonResult.recommendations;
            return result;
        }
    }

    // 回退：使用原始文本响应
    result.summary = llmResult.summary;
    result.description = description;
    result.keywords = llmResult.keywords;

    return result;
}

DLLLLMResult DLLAnalyzerLLMService::parseJSONResponse(const std::string& jsonResponse) {
    DLLLLMResult result;

    try {
        auto j = nlohmann::json::parse(jsonResponse);

        if (j.contains("summary")) {
            result.summary = j["summary"].get<std::string>();
        }
        if (j.contains("description")) {
            result.description = j["description"].get<std::string>();
        }
        if (j.contains("keywords") && j["keywords"].is_array()) {
            for (const auto& kw : j["keywords"]) {
                result.keywords.push_back(kw.get<std::string>());
            }
        }
        if (j.contains("threat_assessment")) {
            result.threatAssessment = j["threat_assessment"].get<std::string>();
        }
        if (j.contains("behavior_analysis")) {
            result.behaviorAnalysis = j["behavior_analysis"].get<std::string>();
        }
        if (j.contains("indicators") && j["indicators"].is_array()) {
            for (const auto& ind : j["indicators"]) {
                result.indicators.push_back(ind.get<std::string>());
            }
        }
        if (j.contains("recommendations")) {
            result.recommendations = j["recommendations"].get<std::string>();
        }

        result.success = true;
    } catch (const nlohmann::json::exception& e) {
        result.errorMessage = std::string("JSON parsing failed: ") + e.what();
        result.success = false;
    }

    return result;
}

} // namespace dll
} // namespace forensics
