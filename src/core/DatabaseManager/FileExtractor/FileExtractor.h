#pragma once
#ifndef FILE_EXTRACTOR_H
#define FILE_EXTRACTOR_H

#include <string>
#include <vector>
#include <memory>
#include <functional>
#include <tsk/libtsk.h>
#include "DatabaseManager/DatabaseManager.h"

/**
 * FileExtractor - Extract files from forensic images
 *
 * Features:
 * - Search files by name pattern (wildcard support)
 * - Search files by extension
 * - Extract file content from disk image
 * - Support for all filesystem types (NTFS, EXT, XFS, etc.)
 */
class FileExtractor {
public:
    /**
     * Constructor
     * @param imagePath Path to disk image file
     * @param dbPath Path to database containing file metadata
     */
    FileExtractor(const std::string& imagePath, const std::string& dbPath);
    ~FileExtractor();

    /**
     * Initialize extractor (open image and database)
     * @return true if successful
     */
    bool initialize();

    /**
     * Extract files by name pattern (supports wildcards: *, ?)
     * @param pattern File name pattern (e.g., "*.log", "config*", "vmlinuz*")
     * @param outputDir Output directory for extracted files
     * @return Number of files extracted
     */
    int extractByName(const std::string& pattern, const std::string& outputDir);

    /**
     * Extract files by extension(s)
     * @param extensions Comma-separated extensions (e.g., ".jpg,.png,.gif")
     * @param outputDir Output directory for extracted files
     * @return Number of files extracted
     */
    int extractByExtension(const std::string& extensions, const std::string& outputDir);

    /**
     * Extract all files from the image
     * @param outputDir Output directory for extracted files
     * @param includeDeleted Include deleted files (default: false)
     * @return Number of files extracted
     */
    int extractAll(const std::string& outputDir, bool includeDeleted = false);

    /**
     * Extract only deleted files from the image
     * @param outputDir Output directory for extracted files
     * @return Number of files extracted
     */
    int extractDeleted(const std::string& outputDir);

    /**
     * Extract a specific file by inode
     * @param inode File inode number
     * @param outputPath Output file path
     * @return true if successful
     */
    bool extractFileByInode(int64_t inode, const std::string& outputPath);

    /**
     * Extract a specific file by path
     * @param filePath File path in the image
     * @param outputPath Output file path
     * @return true if successful
     */
    bool extractFileByPath(const std::string& filePath, const std::string& outputPath);

private:
    std::string imagePath_;
    std::string dbPath_;
    TSK_IMG_INFO* imgInfo_;
    TSK_FS_INFO* fsInfo_;
    std::unique_ptr<DatabaseManager> dbManager_;
    uint64_t partitionOffset_;

    /**
     * Open disk image and filesystem
     */
    bool openImage();
    bool openFileSystem();
    void closeImage();

    /**
     * Search files in database by SQL query
     * @param whereClause SQL WHERE clause
     * @return List of matching file records
     */
    std::vector<FileRecord> searchFiles(const std::string& whereClause);
    std::vector<FileRecord> searchFilesInTable(const std::string& tableName, const std::string& whereClause);

    /**
     * Extract a single file from the image
     * @param record File record from database
     * @param outputPath Output file path
     * @return true if successful
     */
    bool extractFile(const FileRecord& record, const std::string& outputPath);

    /**
     * Read file content using TSK
     * @param inode File inode number
     * @param buffer Buffer to store file content
     * @param size Size of file to read
     * @return Number of bytes read
     */
    ssize_t readFileContent(int64_t inode, char* buffer, size_t size);

    /**
     * Create directory structure for output path
     * @param path Full path including filename
     * @return true if successful
     */
    bool createDirectories(const std::string& path);

    /**
     * Match filename against wildcard pattern
     * @param filename Filename to match
     * @param pattern Pattern with wildcards (*, ?)
     * @return true if matches
     */
    bool matchWildcard(const std::string& filename, const std::string& pattern);

    /**
     * Generate safe output path (handle path conflicts)
     * @param outputDir Base output directory
     * @param record File record
     * @return Full output path
     */
    std::string generateOutputPath(const std::string& outputDir, const FileRecord& record);
};

#endif // FILE_EXTRACTOR_H
