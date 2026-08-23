#pragma once

#include <string>
#include <vector>
#include <cstdint>
#include <tsk/libtsk.h>
#include <map>
#include <functional>
#include <chrono>

/**
 * @brief File signature definition for carving
 */
struct CarvingSignature {
    std::string name;              // Human-readable name
    std::string extension;         // File extension
    std::vector<uint8_t> header;   // Header magic bytes
    std::vector<uint8_t> footer;   // Optional footer magic bytes
    size_t maxSize;                // Maximum file size to carve
    int headerOffset = 0;          // Offset from match to actual file start
    bool hasFixedSize = false;     // If true, maxSize is exact size
};

/**
 * @brief Information about a carved file
 */
struct CarvedFileInfo {
    std::string path;              // Output file path
    std::string signatureName;     // Which signature matched
    std::string extension;         // File extension
    uint64_t sourceOffset;         // Offset in source image
    uint64_t size;                 // Actual carved size
    bool validated;                // Whether file passed validation
    std::string validationMessage; // Validation result message
};

/**
 * @brief Overall carving statistics
 */
struct CarvingStatistics {
    int totalFilesCarved = 0;
    uint64_t totalBytesCarved = 0;
    int validFiles = 0;
    int invalidFiles = 0;
    int errors = 0;
    std::map<std::string, int> filesByType;   // Count per signature type
    double elapsedSeconds = 0.0;
    uint64_t blocksScanned = 0;
    uint64_t unallocatedBlocks = 0;
};

/**
 * @brief Progress callback type
 * @param current Current block being processed
 * @param total Total blocks to process
 * @param currentFile Currently carving file (empty if not carving)
 */
using CarvingProgressCallback = std::function<void(uint64_t current, uint64_t total, const std::string& currentFile)>;
using CarvingCancelCallback = std::function<bool()>;

/**
 * @brief File carving class for recovering deleted files from unallocated space
 */
class FileCarver {
public:
    FileCarver();
    ~FileCarver();

    /**
     * @brief Scan unallocated space in the image/partition for deleted files
     * @param imagePath Path to the raw image file
     * @param outputDir Directory to save recovered files
     * @param partitionOffset Offset of the partition (in bytes), 0 if full disk or image is partition
     * @return Number of files recovered
     */
    int carve(const std::string& imagePath, const std::string& outputDir, uint64_t partitionOffset = 0);
    
    /**
     * @brief Get all registered file signatures
     */
    const std::vector<CarvingSignature>& getSignatures() const { return signatures_; }
    
    /**
     * @brief Get list of carved files from last carve operation
     */
    const std::vector<CarvedFileInfo>& getCarvedFiles() const { return carvedFiles_; }
    
    /**
     * @brief Get statistics from last carve operation
     */
    const CarvingStatistics& getStatistics() const { return statistics_; }
    
    /**
     * @brief Set progress callback for UI integration
     */
    void setProgressCallback(CarvingProgressCallback callback) { progressCallback_ = callback; }
    
    /**
     * @brief Set database path for logging carved files
     * @param dbPath Path to SQLite database (will create carved_files table)
     */
    void setDatabasePath(const std::string& dbPath) { databasePath_ = dbPath; }
    
    /**
     * @brief Enable or disable file validation after carving
     */
    void setValidationEnabled(bool enabled) { validationEnabled_ = enabled; }

    // Stop a long carve promptly when the owning task is cancelled.
    void setCancelCallback(CarvingCancelCallback callback) { cancelCallback_ = std::move(callback); }
    
    /**
     * @brief Add a custom signature for carving
     */
    void addSignature(const CarvingSignature& sig) { signatures_.push_back(sig); }

private:
    void initializeSignatures();
    // Carve unallocated blocks of ONE open filesystem into outputDir.
    int carveFilesystem(TSK_FS_INFO* fs_info, const std::string& outputDir,
                        uint64_t progressBase = 0, uint64_t progressTotal = 0);
    void processUnallocatedBlock(const void* data, size_t len, uint64_t addr);
    void extractFile(TSK_FS_INFO* fs, uint64_t startBlock, const CarvingSignature& sig, const std::string& outputDir);

protected:
    // Validation methods
    bool validateCarvedFile(const std::string& filepath, const CarvingSignature& sig, std::string& message);
    bool validateJPEG(const std::string& filepath, std::string& message);
    bool validatePNG(const std::string& filepath, std::string& message);
    bool validatePDF(const std::string& filepath, std::string& message);
    bool validateZIP(const std::string& filepath, std::string& message);

private:
    // Database logging
    void logToDatabase(const CarvedFileInfo& info);
    void initDatabaseTable();
    
    // Internal callback wrapper
    friend TSK_WALK_RET_ENUM carving_block_walk_ctx(const TSK_FS_BLOCK* block, void* ptr);

    std::vector<CarvingSignature> signatures_;
    std::vector<CarvedFileInfo> carvedFiles_;
    CarvingStatistics statistics_;
    CarvingProgressCallback progressCallback_;
    CarvingCancelCallback cancelCallback_;
    std::string databasePath_;
    bool validationEnabled_ = true;
    
    // Track carved regions to avoid duplicates
    std::vector<std::pair<uint64_t, uint64_t>> carvedRegions_;
};
