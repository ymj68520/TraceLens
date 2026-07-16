#pragma once
#ifndef FILE_EXTRACTOR_H
#define FILE_EXTRACTOR_H

#include <string>
#include <vector>
#include <memory>
#include <functional>
#include <map>
#include <filesystem>
#include <optional>
#include <cstdint>
#include <tsk/libtsk.h>
#include "DatabaseManager/DatabaseManager.h"
#include "analyzers/AndroidAnalyzer/IFileExtractor.h"
#include "analyzers/ImageAnalyzer/XFSHelper.h"

/**
 * FileExtractor - Extract files from forensic images
 *
 * Features:
 * - Search files by name pattern (wildcard support)
 * - Search files by extension
 * - Extract file content from disk image
 * - Support for all filesystem types (NTFS, EXT, XFS, etc.)
 * - Multi-partition aware: opens every accessible filesystem and routes
 *   inode-based reads to the partition recorded for each file record.
 *
 * Implements IFileExtractor so AndroidAnalyzer can treat the TSK backend and
 * the logical-extraction backends (directory/zip) uniformly.
 */
class FileExtractor : public IFileExtractor {
public:
    enum class AtomicExtractionStatus : uint8_t {
        Extracted,
        Reused,
        Failed
    };

    struct AtomicExtractionResult {
        AtomicExtractionStatus status = AtomicExtractionStatus::Failed;
        std::filesystem::path output_path;
        uintmax_t previous_bytes = 0;
        uintmax_t output_bytes = 0;
        std::string error;
    };

    /**
     * Constructor
     * @param imagePath Path to disk image file
     * @param dbPath Path to database containing file metadata
     */
    FileExtractor(const std::string& imagePath, const std::string& dbPath);
    ~FileExtractor();

    /** Initialize extractor (open image, all accessible filesystems, database). */
    bool initialize() override;

    int extractByName(const std::string& pattern, const std::string& outputDir, bool overwrite = false, int* skippedCount = nullptr);
    int extractByExtension(const std::string& extensions, const std::string& outputDir, bool overwrite = false, int* skippedCount = nullptr);
    int extractAll(const std::string& outputDir, bool includeDeleted = false, bool overwrite = false, int* skippedCount = nullptr);
    int extractDeleted(const std::string& outputDir, bool overwrite = false, int* skippedCount = nullptr);
    bool extractFileByInode(int64_t inode, const std::string& outputPath, int partitionNum = -1);
    bool extractFileByPath(const std::string& filePath, const std::string& outputPath) override;

    static std::vector<FileRecord> queryRegularFilesOrdered(sqlite3* db,
                                                            std::string* error = nullptr);
    std::vector<FileRecord> listRegularFilesOrdered(std::string* error = nullptr);
    static std::optional<std::filesystem::path> resolveSafeOutputPath(
        const std::filesystem::path& outputRoot,
        const std::string& imagePath,
        std::string* error = nullptr);
    AtomicExtractionResult extractRecordAtomically(
        const FileRecord& record,
        const std::filesystem::path& outputRoot);

protected:
    virtual bool extractFile(const FileRecord& record, const std::string& outputPath,
                             bool overwrite, int* skippedCount);

private:
    std::string imagePath_;
    std::string dbPath_;
    TSK_IMG_INFO* imgInfo_;
    // One open filesystem per partition number. A record's partitionNum selects
    // which handle to use for inode-based reads, avoiding cross-partition inode
    // collisions. partition 0 is the legacy single-FS / whole-image case.
    std::map<int, TSK_FS_INFO*> fsByPartition_;
    // XFSHelper instances for partitions that TSK cannot open (XFS).
    // Key = partition number, value = lazily-initialized XFSHelper.
    std::map<int, std::unique_ptr<XFSHelper>> xfsByPartition_;
    // Partition offsets recorded during openFileSystem for XFS fallback init.
    std::map<int, uint64_t> xfsPartitionOffsets_;
    std::unique_ptr<DatabaseManager> dbManager_;

    bool openImage();
    bool openFileSystem();
    void closeImage();

    /**
     * Get the filesystem handle for a given partition number.
     * Falls back to the first opened handle if the specific one is missing
     * (e.g. older databases without partition_num).
     */
    TSK_FS_INFO* fsForPartition(int partitionNum) const;

    /**
     * Get or lazily-initialize an XFSHelper for a partition that TSK could not
     * open. Returns nullptr if the partition is not XFS or initialization fails.
     */
    XFSHelper* xfsForPartition(int partitionNum);

    std::vector<FileRecord> searchFiles(const std::string& whereClause);
    std::vector<FileRecord> searchFilesInTable(const std::string& tableName, const std::string& whereClause);

    ssize_t readFileContent(int64_t inode, char* buffer, size_t size, int partitionNum = 0);

    bool createDirectories(const std::string& path);
    bool matchWildcard(const std::string& filename, const std::string& pattern);
    std::string generateOutputPath(const std::string& outputDir, const FileRecord& record);
};

#endif // FILE_EXTRACTOR_H
