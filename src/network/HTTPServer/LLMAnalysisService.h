#pragma once

#include <string>
#include <vector>
#include <functional>
#include <memory>
#include <mutex>
#include "LLMIntegration/LLMDataTypes.h"
#include "LLMIntegration/FileAnalyzer.h"
#include "LLMIntegration/ModelRouter.h"
#include "ConfigManager/ConfigManager.h"
#include "DatabaseManager/FileClassifier/FileClassifier.h"
#include "DatabaseManager/DatabaseManagerDataTypes.h"

// Global-scope forward declaration (FileExtractor lives at global scope).
class FileExtractor;

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
        size_t maxFiles = 0;                 // Maximum files to analyze (0 = 全量, unlimited)
        size_t maxContentLength = 10000;     // Maximum content length per file
        std::vector<std::string> fileTypes;  // File types to analyze (empty = all)
        bool skipBinaryFiles = true;         // Skip binary files
    };

    /**
     * @brief Progress callback type
     * @param current Current file number
     * @param total Total files to analyze
     * @param currentFile Current file path
     * @return true to continue analysis, false to stop (task cancelled)
     */
    using ProgressCallback = std::function<bool(int current, int total, const std::string& currentFile)>;

    // How the last selectImportantFiles() call reached its result.
    //
    // The call has three reachable paths that all return a plausible list:
    // the model answered, the model's answer was rejected, or the pool already
    // fit the budget. A caller that only sees the returned size cannot tell a
    // 977-file model selection from a 977-file heuristic fallback, which is
    // exactly the ambiguity that hid the "0 usable paths" regressions.
    struct SelectionStats {
        std::string source;       // llm | llm_rejected | heuristic_fits | heuristic_fallback | empty
        size_t candidates = 0;    // rows the candidate pool returned
        size_t listed = 0;        // rows actually offered to the model
        size_t reply_usable = 0;  // paths the model's reply resolved to
        size_t selected = 0;      // paths returned to the caller
    };

    const SelectionStats& lastSelectionStats() const { return lastSelection_; }

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
    int analyzeAllFiles(const std::string& filesDbPath,
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
    int analyzeSmartFiles(const std::string& filesDbPath,
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
    void setImagePaths(const std::string& imagePath, const std::string& rawDbPath,
                       const std::string& taskId = "");

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
    std::string scratchTaskId_;

    // Lazily-created shared extractor for image-backed file resolution.
    // Opening the image + partitions + DB per file is far too slow.
    // TSK handles inside it are not safe to use from several threads, so every
    // extraction takes imageExtractorMutex_ even when analysis itself is concurrent.
    std::unique_ptr<::FileExtractor> imageExtractor_;
    std::mutex imageExtractorMutex_;

    // LLM_MAX_CONCURRENCY workers. 1 keeps the historical one-file-at-a-time loop.
    int llmConcurrency() const;

    // Last selection's provenance; see SelectionStats.
    SelectionStats lastSelection_;
    int runFileAnalyses(const std::string& filesDbPath,
                        const AnalysisOptions& options,
                        const std::vector<std::string>& files,
                        ProgressCallback progressCallback,
                        const char* modeLabel);

    // Internal helpers
    bool storeDescription(const std::string& dbPath,
                          const std::string& filePath,
                          const std::string& description,
                          const std::string& summary,
                          const std::vector<std::string>& keywords,
                          const std::string& modelUsed);
    std::vector<std::string> getFilesFromDatabase(const std::string& dbPath,
                                                   const AnalysisOptions& options);
    /**
     * @brief Best `budget` candidate paths in the whole database by forensic priority
     *
     * Scans every row (no insertion-order LIMIT), drops TSK `$`-virtual entries
     * and the noise bucket, and keeps a bounded top-N. Smart selection must see
     * registry hives, event logs and other late-table artefacts that a
     * LIMIT-based window never reaches on a real image.
     */
    std::vector<std::string> getPrioritizedCandidates(const std::string& dbPath,
                                                      size_t budget,
                                                      bool skipBinaryFiles);
    // True when the file's first bytes are a PE image or a zip container.
    // Suffix rules cannot see a dll renamed to .old; this can.
    static bool hasBinaryContainerHeader(const std::string& path);
    std::string buildFileListSummary(const std::vector<std::string>& files);
    std::vector<std::string> parseImportantFiles(const std::string& llmResponse,
                                                  const std::vector<std::string>& allFiles);

    /**
     * @brief Trim a model selection to `maxFiles` while keeping artefact variety
     *
     * The model often answers with (almost) the whole listing, in path order.
     * A plain prefix cut then keeps whichever family sorts first — on PC.E01
     * with a 200-file budget that was 197 Windows event logs, and every
     * registry hive, prefetch, jump list and the Quasar controller dropped out.
     * Round-robin across artefact families first, then fill the remainder in
     * the model's own order.
     */
    static std::vector<std::string> truncateWithDiversity(
        const std::vector<std::string>& ordered, size_t maxFiles);

    /**
     * @brief Coarse artefact family of a path, used to spread a budget
     *
     * Families are the investigation questions, not file formats: event logs
     * answer "what happened when", registry hives "what was configured",
     * execution evidence "what ran", user documents "what was taken".
     */
    static std::string artefactFamily(const std::string& path);

    /**
     * @brief Heuristic forensic importance score for a file path (higher = more important)
     *
     * Used to bound the smart-selection prompt and as fallback ordering when
     * the LLM selection call fails. Prioritises user artefacts, credentials,
     * shell histories, logs and databases over system libraries/fonts/certs.
     */
    static int forensicPathPriority(const std::string& path);

    /**
     * @brief Order files by forensic priority (stable) and truncate to maxFiles
     */
    static std::vector<std::string> selectByHeuristic(std::vector<std::string> files,
                                                      size_t maxFiles);

    // Test-only seam: unit tests assert on the heuristic ranking rules directly.
    friend struct LLMSelectionHeuristicTestAccess;

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
