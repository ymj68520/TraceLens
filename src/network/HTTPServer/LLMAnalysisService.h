#pragma once

#include <string>
#include <vector>
#include <functional>
#include <memory>
#include "LLMIntegration/LLMDataTypes.h"
#include "LLMIntegration/FileAnalyzer.h"
#include "LLMIntegration/ModelRouter.h"
#include "LLMIntegration/ConfigManager.h"

namespace forensics {

/**
 * @brief LLM Analysis Service for forensic file description generation
 * 
 * Provides two analysis modes:
 * - FULL: Analyze all files in the database
 * - SMART: LLM selects important files first, then analyzes them
 */
class LLMAnalysisService {
public:
    /**
     * @brief Analysis options for LLM file analysis
     */
    struct AnalysisOptions {
        size_t maxFiles = 1000;              // Maximum files to analyze
        size_t maxContentLength = 10000;     // Maximum content length per file
        std::vector<std::string> fileTypes;  // File types to analyze (empty = all)
        bool skipBinaryFiles = true;         // Skip binary files
    };

    /**
     * @brief Progress callback type
     * @param current Current file number
     * @param total Total files to analyze
     * @param currentFile Current file path
     */
    using ProgressCallback = std::function<void(int current, int total, const std::string& currentFile)>;

    /**
     * @brief Constructor
     */
    LLMAnalysisService();
    ~LLMAnalysisService();

    /**
     * @brief Initialize the service with LLM configuration
     * @return true if initialization successful
     */
    bool initialize();

    /**
     * @brief Full mode: Analyze all files matching criteria
     * 
     * Reads files from filesDbPath, generates descriptions using LLM,
     * and stores results in descriptionsDbPath.
     * 
     * @param filesDbPath Path to the classified files database
     * @param descriptionsDbPath Output path for descriptions database
     * @param options Analysis options
     * @param progressCallback Progress callback function
     * @return Number of files analyzed
     */
    int analyzeAllFiles(const std::string& filesDbPath,
                        const std::string& descriptionsDbPath,
                        const AnalysisOptions& options,
                        ProgressCallback progressCallback = nullptr);

    /**
     * @brief Smart mode: Let LLM select important files, then analyze them
     * 
     * First sends file list summary to LLM to identify important files,
     * then analyzes only those files.
     * 
     * @param filesDbPath Path to the classified files database
     * @param descriptionsDbPath Output path for descriptions database
     * @param options Analysis options
     * @param progressCallback Progress callback function
     * @return Number of files analyzed
     */
    int analyzeSmartFiles(const std::string& filesDbPath,
                          const std::string& descriptionsDbPath,
                          const AnalysisOptions& options,
                          ProgressCallback progressCallback = nullptr);

    /**
     * @brief Get list of important files selected by LLM
     * @param filesDbPath Path to the classified files database
     * @param maxFiles Maximum number of files to select
     * @return Vector of file paths deemed important
     */
    std::vector<std::string> selectImportantFiles(const std::string& filesDbPath,
                                                   size_t maxFiles = 100);

private:
    std::shared_ptr<llm::ModelRouter> router_;
    std::unique_ptr<llm::FileAnalyzer> fileAnalyzer_;
    bool initialized_ = false;

    // Internal helpers
    bool createDescriptionsDatabase(const std::string& dbPath);
    bool storeDescription(const std::string& dbPath, 
                          const std::string& filePath,
                          const std::string& description,
                          const std::string& summary,
                          const std::vector<std::string>& keywords);
    std::vector<std::string> getFilesFromDatabase(const std::string& dbPath,
                                                   const AnalysisOptions& options);
    std::string buildFileListSummary(const std::vector<std::string>& files);
    std::vector<std::string> parseImportantFiles(const std::string& llmResponse,
                                                  const std::vector<std::string>& allFiles);
};

} // namespace forensics
