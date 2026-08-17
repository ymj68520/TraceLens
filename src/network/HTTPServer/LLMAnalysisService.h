#pragma once

#include <string>
#include <vector>
#include <functional>
#include <memory>
#include "LLMIntegration/LLMDataTypes.h"
#include "LLMIntegration/FileAnalyzer.h"
#include "LLMIntegration/ModelRouter.h"
#include "ConfigManager/ConfigManager.h"
#include "DatabaseManager/FileClassifier/FileClassifier.h"
#include "DatabaseManager/DatabaseManagerDataTypes.h"

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
     * and stores results directly in the files table (llm_* columns).
     * 
     * @param filesDbPath Path to the classified files database (_files.db)
     * @param options Analysis options
     * @param progressCallback Progress callback function
     * @return Number of files analyzed
     */
    int analyzeAllFiles(const std::string& task_id,
                        const std::string& filesDbPath,
                        const AnalysisOptions& options,
                        ProgressCallback progressCallback = nullptr);

    /**
     * @brief Smart mode: Let LLM select important files, then analyze them
     * 
     * First sends file list summary to LLM to identify important files,
     * then analyzes only those files and stores results in files table.
     * 
     * @param filesDbPath Path to the classified files database (_files.db)
     * @param options Analysis options
     * @param progressCallback Progress callback function
     * @return Number of files analyzed
     */
    int analyzeSmartFiles(const std::string& task_id,
                          const std::string& filesDbPath,
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

    /**
     * @brief Set the scene type for scene-aware prioritization
     * @param scene The scene type to use for prioritization
     */
    void setSceneType(SceneType scene);

    /**
     * @brief Set the forensic image path for extracting files from within images
     *
     * Files selected for LLM analysis live inside a disk image, not on the host
     * filesystem. When imagePath is set, each file is extracted via TSK to a
     * temporary directory before analysis.
     *
     * @param imagePath Path to the forensic disk image (E01, DD, etc.)
     * @param rawDbPath Path to the _raw.db containing file metadata/inodes
     */
    void setImagePaths(const std::string& imagePath, const std::string& rawDbPath);

    /**
     * @brief Get the current scene type
     * @return Current scene type
     */
    SceneType getSceneType() const;

    /**
     * @brief Check if a file should be skipped based on scene priority
     * @param file The file record to check
     * @return true if the file should be skipped (irrelevant to current scene)
     */
    bool shouldSkipFile(const FileRecord& file);

    /**
     * @brief Get scene-specific analysis prompt for a file
     * @param file The file record to generate prompt for
     * @return Scene-specific analysis prompt string
     */
    std::string getSceneSpecificPrompt(const FileRecord& file);

    /**
     * @brief Get files prioritized by scene relevance
     * @param db SQLite database handle
     * @param limit Maximum number of files to return
     * @return Vector of FileRecord ordered by scene priority
     */
    std::vector<FileRecord> getScenePrioritizedFiles(sqlite3* db, int limit);

private:
    std::shared_ptr<llm::ModelRouter> router_;
    std::unique_ptr<llm::FileAnalyzer> fileAnalyzer_;
    bool initialized_ = false;

    // Scene type for prioritization
    SceneType sceneType_ = SceneType::NONE;

    // Forensic image paths for extracting files from within images
    std::string imagePath_;
    std::string rawDbPath_;

    // Internal helpers
    bool storeDescription(const std::string& dbPath,
                          const std::string& filePath,
                          const std::string& description,
                          const std::string& summary,
                          const std::vector<std::string>& keywords,
                          const std::string& modelUsed);
    std::vector<std::string> getFilesFromDatabase(const std::string& dbPath,
                                                   const AnalysisOptions& options);
    std::string buildFileListSummary(const std::vector<std::string>& files);
    std::vector<std::string> parseImportantFiles(const std::string& llmResponse,
                                                  const std::vector<std::string>& allFiles);

    /**
     * @brief Resolve a file path from the image to a host-filesystem path
     *
     * If imagePath_ is set, extracts the file from the forensic image to a
     * temporary directory and returns the host path. Returns the original
     * path unchanged when no image is configured (e.g. analyzing loose files).
     * Returns empty string on extraction failure.
     */
    std::string resolveFileForAnalysis(const std::string& filePath);
};

} // namespace forensics
