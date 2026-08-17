#pragma once

#include "LLMDataTypes.h"
#include "ModelRouter.h"
#include <memory>
#include <string>
#include <vector>
#include <functional>
#include <regex>

namespace forensics {
namespace llm {

/**
 * @brief File content analyzer using LLM
 * 
 * Reads file contents and uses LLM to:
 * - Generate summaries
 * - Extract keywords
 * - Create descriptions
 * - Identify file type and purpose
 */
class FileAnalyzer {
public:
    /**
     * @brief Constructor
     * @param router Model router for LLM requests
     */
    explicit FileAnalyzer(std::shared_ptr<ModelRouter> router);
    ~FileAnalyzer();
    
    // Non-copyable
    FileAnalyzer(const FileAnalyzer&) = delete;
    FileAnalyzer& operator=(const FileAnalyzer&) = delete;
    
    /**
     * @brief Analyze a single file
     * @param filePath Path to the file
     * @param maxContentLength Maximum content length to send to LLM
     * @return Analysis result with summary, keywords, description
     */
    AnalysisResult analyzeFile(const std::string& filePath, 
                               size_t maxContentLength = 10000,
                               const std::string& taskId = "");
    
    /**
     * @brief Analyze multiple files
     * @param request Batch analysis request
     * @return Vector of analysis results
     */
    std::vector<AnalysisResult> analyzeBatch(const BatchAnalysisRequest& request);
    
    /**
     * @brief Generate a summary for file content
     * @param content File content to summarize
     * @param context Optional context (file path, type, etc.)
     * @return Summary text
     */
    std::string summarize(const std::string& content, 
                          const std::string& context = "");
    
    /**
     * @brief Generate a natural language description
     * @param filePath Path to the file
     * @return Description text
     */
    std::string generateDescription(const std::string& filePath);
    
    /**
     * @brief Generate description for multiple files
     * @param filePaths Paths to files
     * @return Combined description
     */
    std::string generateDescription(const std::vector<std::string>& filePaths);
    
    /**
     * @brief Extract keywords from content
     * @param content Content to analyze
     * @param maxKeywords Maximum number of keywords
     * @return Vector of keywords
     */
    std::vector<std::string> extractKeywords(const std::string& content, 
                                              size_t maxKeywords = 10);
    
    /**
     * @brief Set custom system prompts
     */
    void setSummaryPrompt(const std::string& prompt);
    void setDescriptionPrompt(const std::string& prompt);
    void setKeywordPrompt(const std::string& prompt);
    
    /**
     * @brief Set progress callback for batch operations
     */
    using ProgressCallback = std::function<void(size_t current, size_t total, 
                                                 const std::string& currentFile)>;
    void setProgressCallback(ProgressCallback callback);
    
    /**
     * @brief Set chunk configuration for large file handling
     * @param config Chunk configuration
     */
    void setChunkConfig(const ChunkConfig& config);
    
    /**
     * @brief Get current chunk configuration
     */
    const ChunkConfig& getChunkConfig() const;
    
    // ===== Context Window Management =====
    
    /**
     * @brief Estimate token count for given content
     * @param content Content to estimate
     * @param charsPerToken Characters per token ratio (default 4.0 for English)
     * @return Estimated token count
     */
    static size_t estimateTokens(const std::string& content, double charsPerToken = 4.0);
    
    /**
     * @brief Calculate maximum content length based on context window
     * @return Maximum content length in characters
     */
    size_t calculateMaxContentLength() const;
    
    /**
     * @brief Smart content truncation with boundary awareness
     * @param content Content to truncate
     * @param maxLength Maximum length in characters
     * @return Truncated content
     */
    std::string truncateContent(const std::string& content, size_t maxLength) const;
    
    /**
     * @brief Analyze large file using chunked approach
     * @param filePath Path to the file
     * @return Merged analysis result
     */
    AnalysisResult analyzeFileChunked(const std::string& filePath);

private:
    std::shared_ptr<ModelRouter> router_;
    std::string summaryPrompt_;
    std::string descriptionPrompt_;
    std::string keywordPrompt_;
    ProgressCallback progressCallback_;
    ChunkConfig chunkConfig_;
    
    // Pre-compiled regex patterns for response parsing (Issue 9)
    static const std::regex SUMMARY_REGEX;
    static const std::regex DESCRIPTION_REGEX;
    static const std::regex KEYWORD_REGEX;
    
    std::string readFileContent(const std::string& path, size_t maxBytes);
    std::string detectFileType(const std::string& path);
    std::vector<std::string> parseKeywords(const std::string& llmResponse);
    void initDefaultPrompts();
    
    /**
     * @brief Split content into overlapping chunks
     */
    std::vector<std::string> splitIntoChunks(const std::string& content) const;
    
    /**
     * @brief Find smart boundary for truncation (sentence/paragraph end)
     */
    size_t findSmartBoundary(const std::string& content, size_t targetPos) const;
    
    /**
     * @brief Merge multiple chunk analysis results
     */
    AnalysisResult mergeChunkResults(const std::vector<AnalysisResult>& results, 
                                      const std::string& filePath) const;
};

} // namespace llm
} // namespace forensics
