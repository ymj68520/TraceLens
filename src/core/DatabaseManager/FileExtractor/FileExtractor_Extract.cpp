#include "FileExtractor.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <fstream>
#include <filesystem>
#include <sstream>
#include <algorithm>
#include <cstring>

#ifdef _WIN32
#include <Windows.h>
#endif

namespace fs = std::filesystem;

// File extraction operations. Split from FileExtractor.cpp.

int FileExtractor::extractByName(const std::string& pattern, const std::string& outputDir, bool overwrite, int* skippedCount) {
    std::cout << "Searching files matching patterns: " << pattern << std::endl;

    // Parse patterns (comma-separated)
    std::vector<std::string> patterns;
    std::stringstream ss(pattern);
    std::string item;
    while (std::getline(ss, item, ',')) {
        // Trim whitespace
        item.erase(0, item.find_first_not_of(" \t"));
        item.erase(item.find_last_not_of(" \t") + 1);
        if (!item.empty()) {
            patterns.push_back(item);
        }
    }

    if (patterns.empty()) {
        return 0;
    }

    // Get all files from database
    auto files = searchFiles("type='REG' AND is_allocated=1");

    std::vector<FileRecord> matches;
    for (const auto& file : files) {
        bool matched = false;
        for (const auto& p : patterns) {
            // Check if it's an exact path match or a wildcard filename match
            if (file.path == p || matchWildcard(file.name, p)) {
                matched = true;
                break;
            }
        }
        if (matched) {
            matches.push_back(file);
        }
    }

    std::cout << "Found " << matches.size() << " matching files" << std::endl;

    if (matches.empty()) {
        return 0;
    }

    // Extract each file
    int extracted = 0;
    for (const auto& file : matches) {
        std::string outputPath = generateOutputPath(outputDir, file);
        std::cout << "Extracting: " << file.path << " -> " << outputPath << std::endl;

        if (extractFile(file, outputPath, overwrite, skippedCount)) {
            extracted++;
        } else {
            std::cerr << "  Failed to extract: " << file.path << std::endl;
        }
    }

    return extracted;
}

int FileExtractor::extractByExtension(const std::string& extensions, const std::string& outputDir, bool overwrite, int* skippedCount) {
    std::cout << "Searching files with extensions: " << extensions << std::endl;

    // Parse extensions
    std::vector<std::string> extList;
    std::stringstream ss(extensions);
    std::string ext;
    while (std::getline(ss, ext, ',')) {
        // Trim whitespace
        ext.erase(0, ext.find_first_not_of(" \t"));
        ext.erase(ext.find_last_not_of(" \t") + 1);
        // Ensure leading dot
        if (!ext.empty() && ext[0] != '.') {
            ext = "." + ext;
        }
        extList.push_back(ext);
    }

    // Build SQL WHERE clause
    std::stringstream whereClause;
    whereClause << "type='REG' AND is_allocated=1 AND (";
    for (size_t i = 0; i < extList.size(); i++) {
        if (i > 0) whereClause << " OR ";
        whereClause << "name LIKE '%" << extList[i] << "'";
    }
    whereClause << ")";

    auto files = searchFiles(whereClause.str());
    std::cout << "Found " << files.size() << " matching files" << std::endl;

    if (files.empty()) {
        return 0;
    }

    // Extract each file
    int extracted = 0;
    for (const auto& file : files) {
        std::string outputPath = generateOutputPath(outputDir, file);
        std::cout << "Extracting: " << file.path << " -> " << outputPath << std::endl;

        if (extractFile(file, outputPath, overwrite, skippedCount)) {
            extracted++;
        } else {
            std::cerr << "  Failed to extract: " << file.path << std::endl;
        }
    }

    return extracted;
}

int FileExtractor::extractAll(const std::string& outputDir, bool includeDeleted, bool overwrite, int* skippedCount) {
    std::cout << "Extracting all files..." << std::endl;

    // Extract from main files table
    std::string whereClause = "type = 'REG'";
    if (!includeDeleted) {
        whereClause += " AND is_deleted=0";
    }

    auto files = searchFiles(whereClause);
    std::cout << "Found " << files.size() << " files to extract" << std::endl;

    if (files.empty()) {
        return 0;
    }

    // Extract each file
    int extracted = 0;
    for (size_t i = 0; i < files.size(); i++) {
        const auto& file = files[i];
        std::string outputPath = generateOutputPath(outputDir, file);

        if (i < 10 || i % 50 == 0) {
            std::cout << "Extracting [" << (i + 1) << "/" << files.size() << "]: "
                      << file.path << std::endl;
        }

        if (extractFile(file, outputPath, overwrite, skippedCount)) {
            extracted++;
        }
    }

    return extracted;
}

int FileExtractor::extractDeleted(const std::string& outputDir, bool overwrite, int* skippedCount) {
    std::cout << "Extracting deleted files (Metadata Recovery)..." << std::endl;

    // files where is_deleted = 1
    std::string whereClause = "is_deleted=1";

    auto files = searchFiles(whereClause);
    std::cout << "Found " << files.size() << " deleted files to recover" << std::endl;

    if (files.empty()) {
        return 0;
    }

    int extracted = 0;
    for (size_t i = 0; i < files.size(); i++) {
        const auto& file = files[i];
        std::string outputPath = generateOutputPath(outputDir, file);
        
        // Add "recovered_" prefix or similar if needed? 
        // No, keep original name structure, but maybe ensure outputDir is distinct.
        
        if (i < 10 || i % 50 == 0) {
            std::cout << "Recovering [" << (i + 1) << "/" << files.size() << "]: " 
                      << file.path << std::endl;
        }

        if (extractFile(file, outputPath, overwrite, skippedCount)) {
            extracted++;
        } else {
             std::cerr << "  Failed to recover: " << file.path << " (Content might be overwritten)" << std::endl;
        }
    }

    return extracted;
}

bool FileExtractor::extractFileByInode(int64_t inode, const std::string& outputPath) {
    auto files = searchFiles("inode=" + std::to_string(inode));
    if (files.empty()) {
        std::cerr << "Error: File with inode " << inode << " not found" << std::endl;
        return false;
    }

    // In multi-partition images, the same inode can exist in several partitions.
    // Pick the record whose partition we actually have an open handle for; this
    // avoids reading the wrong partition's content via a colliding inode.
    const FileRecord* chosen = nullptr;
    for (const auto& f : files) {
        if (fsByPartition_.find(f.partitionNum) != fsByPartition_.end()) {
            chosen = &f;
            break;
        }
    }
    if (!chosen) {
        chosen = &files[0];  // fallback: best-effort with first record
    }

    // Single file extraction implies overwrite intent usually
    return extractFile(*chosen, outputPath, true, nullptr);
}

bool FileExtractor::extractFileByPath(const std::string& filePath, const std::string& outputPath) {
    // Use parameterized query to prevent SQL injection
    std::vector<FileRecord> results;

    std::string sql = "SELECT inode, name, path, size, mtime, ctime, type, is_deleted, md5, "
                      "COALESCE(partition_num, 0) "
                      "FROM files WHERE path = ?";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(dbManager_->getDb(), sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing query: " << sqlite3_errmsg(dbManager_->getDb()) << std::endl;
        return false;
    }

    sqlite3_bind_text(stmt, 1, filePath.c_str(), -1, SQLITE_STATIC);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileRecord record;
        record.inode = sqlite3_column_int64(stmt, 0);
        record.name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        record.path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        record.size = sqlite3_column_int64(stmt, 3);
        record.mtime = sqlite3_column_int64(stmt, 4);
        record.ctime = sqlite3_column_int64(stmt, 5);
        record.type = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
        record.isDeleted = sqlite3_column_int(stmt, 7);
        const char* md5Ptr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
        record.md5 = md5Ptr ? md5Ptr : "";
        record.partitionNum = sqlite3_column_int(stmt, 9);

        // Set defaults for missing fields
        record.atime = record.mtime;
        record.crtime = record.ctime;
        record.isAllocated = 1;
        record.permissions = "0644";
        record.uid = 0;
        record.gid = 0;

        results.push_back(record);
    }

    sqlite3_finalize(stmt);

    if (results.empty()) {
        std::cerr << "Error: File with path " << filePath << " not found" << std::endl;
        return false;
    }

    return extractFile(results[0], outputPath, true, nullptr);
}

bool FileExtractor::extractFile(const FileRecord& record, const std::string& outputPath, bool overwrite, int* skippedCount) {
    // Skip directories
    if (record.type == "DIR") {
        return false;
    }
    
    // Check if file exists
    if (fs::exists(outputPath)) {
        if (!overwrite) {
            // Check if size matches
            try {
                if (fs::file_size(outputPath) == static_cast<uintmax_t>(record.size)) {
                    // File exists and size matches - skip
                    if (skippedCount) {
                        (*skippedCount)++;
                    }
                    return true; // Treat as success
                }
            } catch (const std::exception& e) {
                // If checking size fails, proceed to overwrite attempt
            }
        }
    }

    // Skip empty files (create empty file)
    if (record.size == 0) {
        createDirectories(outputPath);
        std::ofstream ofs(outputPath);
        return ofs.good();
    }

    // Read file content using TSK. Route to the filesystem handle for this
    // file's partition so inode reads don't hit the wrong partition.
    TSK_FS_INFO* fs = fsForPartition(record.partitionNum);
    if (!fs) {
        std::cerr << "Error: No filesystem handle for partition " << record.partitionNum
                  << " (inode " << record.inode << ")" << std::endl;
        return false;
    }
    TSK_FS_FILE* fsFile = tsk_fs_file_open_meta(fs, nullptr, record.inode);
    if (!fsFile) {
        std::cerr << "Error: Cannot open file inode " << record.inode
                  << " (part " << record.partitionNum << ", fs "
                  << tsk_fs_type_toname(fs->ftype) << "): " << tsk_error_get() << std::endl;
        return false;
    }

    // Create output directory
    if (!createDirectories(outputPath)) {
        tsk_fs_file_close(fsFile);
        return false;
    }

    // Read and write file content
    std::ofstream ofs(outputPath, std::ios::binary);
    if (!ofs) {
        std::cerr << "Error: Cannot create output file: " << outputPath << std::endl;
        tsk_fs_file_close(fsFile);
        return false;
    }

    const size_t BUFFER_SIZE = 1024 * 1024; // 1MB buffer
    char* buffer = new char[BUFFER_SIZE];
    TSK_OFF_T offset = 0;
    TSK_OFF_T remaining = record.size;

    while (remaining > 0) {
        size_t toRead = (remaining > BUFFER_SIZE) ? BUFFER_SIZE : remaining;
        ssize_t bytesRead = tsk_fs_file_read(fsFile, offset, buffer, toRead,
                                             TSK_FS_FILE_READ_FLAG_NONE);

        if (bytesRead < 0) {
            std::cerr << "Error reading file at offset " << offset << std::endl;
            break;
        }

        if (bytesRead == 0) {
            break; // EOF
        }

        ofs.write(buffer, bytesRead);
        offset += bytesRead;
        remaining -= bytesRead;
    }

    delete[] buffer;
    ofs.close();
    tsk_fs_file_close(fsFile);

    return remaining == 0;
}

