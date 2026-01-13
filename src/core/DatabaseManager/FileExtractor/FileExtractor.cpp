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

FileExtractor::FileExtractor(const std::string& imagePath, const std::string& dbPath)
    : imagePath_(imagePath)
    , dbPath_(dbPath)
    , imgInfo_(nullptr)
    , fsInfo_(nullptr)
    , partitionOffset_(0) {
}

FileExtractor::~FileExtractor() {
    closeImage();
}

bool FileExtractor::initialize() {
    std::cout << "Initializing file extractor..." << std::endl;
    std::cout << "  Image: " << imagePath_ << std::endl;
    std::cout << "  Database: " << dbPath_ << std::endl;

    // Open database
    dbManager_ = std::make_unique<DatabaseManager>(dbPath_);
    // Database should already exist, just open it
    if (!dbManager_->initialize()) {
        std::cerr << "Error: Cannot open database: " << dbPath_ << std::endl;
        std::cerr << "Please run analysis first to create the database." << std::endl;
        AuditLog::instance().log("SYSTEM", "EXTRACTOR_INIT_FAILED", "Failed to initialize file extractor: " + dbPath_);
        return false;
    }

    // Open image
    if (!openImage()) {
        std::cerr << "Error: Failed to open image" << std::endl;
        return false;
    }

    // Open filesystem
    if (!openFileSystem()) {
        std::cerr << "Error: Failed to open filesystem" << std::endl;
        return false;
    }

    std::cout << "File extractor initialized successfully" << std::endl;
    AuditLog::instance().log("SYSTEM", "EXTRACTOR_INIT", "File extractor initialized: " + imagePath_);
    return true;
}

bool FileExtractor::openImage() {
    TSK_IMG_TYPE_ENUM imgType = TSK_IMG_TYPE_DETECT;

#ifdef _WIN32
    // Windows: Convert UTF-8 to wide char
    int len = MultiByteToWideChar(CP_UTF8, 0, imagePath_.c_str(), -1, nullptr, 0);
    if (len <= 0) return false;

    TSK_TCHAR* imgPathCstr = new TSK_TCHAR[len];
    if (MultiByteToWideChar(CP_UTF8, 0, imagePath_.c_str(), -1, imgPathCstr, len) == 0) {
        delete[] imgPathCstr;
        return false;
    }

    imgInfo_ = tsk_img_open(1, &imgPathCstr, imgType, 0);
    if (!imgInfo_) {
        imgType = TSK_IMG_TYPE_RAW;
        imgInfo_ = tsk_img_open(1, &imgPathCstr, imgType, 0);
    }
    delete[] imgPathCstr;
#else
    // Linux: Use path directly
    const char* imgPathCstr = imagePath_.c_str();
    imgInfo_ = tsk_img_open(1, &imgPathCstr, imgType, 0);
    if (!imgInfo_) {
        imgType = TSK_IMG_TYPE_RAW;
        imgInfo_ = tsk_img_open(1, &imgPathCstr, imgType, 0);
    }
#endif

    if (!imgInfo_) {
        std::cerr << "Error opening image: " << tsk_error_get() << std::endl;
        return false;
    }

    return true;
}

bool FileExtractor::openFileSystem() {
    // Try to open volume system first
    TSK_VS_INFO* vsInfo = tsk_vs_open(imgInfo_, 0, TSK_VS_TYPE_DETECT);

    if (vsInfo) {
        // Find first allocated partition with filesystem
        for (TSK_PNUM_T i = 0; i < vsInfo->part_count; i++) {
            const TSK_VS_PART_INFO* part = tsk_vs_part_get(vsInfo, i);
            if (part && (part->flags & TSK_VS_PART_FLAG_ALLOC)) {
                TSK_OFF_T offset = part->start * vsInfo->block_size;
                partitionOffset_ = offset;

                fsInfo_ = tsk_fs_open_img(imgInfo_, offset, TSK_FS_TYPE_DETECT);
                if (fsInfo_) {
                    tsk_vs_close(vsInfo);
                    return true;
                }
            }
        }
        tsk_vs_close(vsInfo);
    }

    // Try direct filesystem access
    fsInfo_ = tsk_fs_open_img(imgInfo_, 0, TSK_FS_TYPE_DETECT);
    if (!fsInfo_) {
        std::cerr << "Error opening filesystem: " << tsk_error_get() << std::endl;
        return false;
    }

    return true;
}

void FileExtractor::closeImage() {
    if (fsInfo_) {
        tsk_fs_close(fsInfo_);
        fsInfo_ = nullptr;
    }
    if (imgInfo_) {
        tsk_img_close(imgInfo_);
        imgInfo_ = nullptr;
    }
}

std::vector<FileRecord> FileExtractor::searchFiles(const std::string& whereClause) {
    std::vector<FileRecord> results;

    std::string sql = "SELECT inode, name, path, size, mtime, ctime, type, is_deleted, md5 "
                      "FROM files WHERE " + whereClause;

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(dbManager_->getDb(), sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing query: " << sqlite3_errmsg(dbManager_->getDb()) << std::endl;
        return results;
    }

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
    return results;
}

std::vector<FileRecord> FileExtractor::searchFilesInTable(const std::string& tableName, const std::string& whereClause) {
    std::vector<FileRecord> results;

    std::string sql = "SELECT inode, name, path, size, mtime, ctime, is_deleted, md5 "
                      "FROM " + tableName + " WHERE " + whereClause;

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(dbManager_->getDb(), sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing query: " << sqlite3_errmsg(dbManager_->getDb()) << std::endl;
        return results;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileRecord record;
        record.inode = sqlite3_column_int64(stmt, 0);
        record.name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        record.path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        record.size = sqlite3_column_int64(stmt, 3);
        record.mtime = sqlite3_column_int64(stmt, 4);
        record.ctime = sqlite3_column_int64(stmt, 5);
        record.isDeleted = sqlite3_column_int(stmt, 6);
        const char* md5Ptr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        record.md5 = md5Ptr ? md5Ptr : "";
        record.type = "REG";  // Assume regular file
        record.isAllocated = 1;  // Assume allocated

        results.push_back(record);
    }

    sqlite3_finalize(stmt);
    return results;
}

bool FileExtractor::matchWildcard(const std::string& filename, const std::string& pattern) {
    // Simple wildcard matching (* and ?)
    size_t fpos = 0, ppos = 0;
    size_t flen = filename.length(), plen = pattern.length();
    size_t starPos = std::string::npos, matchPos = 0;

    while (fpos < flen) {
        if (ppos < plen && (pattern[ppos] == '?' || pattern[ppos] == filename[fpos])) {
            fpos++;
            ppos++;
        } else if (ppos < plen && pattern[ppos] == '*') {
            starPos = ppos++;
            matchPos = fpos;
        } else if (starPos != std::string::npos) {
            ppos = starPos + 1;
            fpos = ++matchPos;
        } else {
            return false;
        }
    }

    while (ppos < plen && pattern[ppos] == '*') {
        ppos++;
    }

    return ppos == plen;
}

int FileExtractor::extractByName(const std::string& pattern, const std::string& outputDir, bool overwrite, int* skippedCount) {
    std::cout << "Searching files matching pattern: " << pattern << std::endl;

    // Get all files from database
    auto files = searchFiles("type='REG' AND is_allocated=1");

    std::vector<FileRecord> matches;
    for (const auto& file : files) {
        if (matchWildcard(file.name, pattern)) {
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

    // Single file extraction implies overwrite intent usually
    return extractFile(files[0], outputPath, true, nullptr);
}

bool FileExtractor::extractFileByPath(const std::string& filePath, const std::string& outputPath) {
    auto files = searchFiles("path='" + filePath + "'");
    if (files.empty()) {
        std::cerr << "Error: File with path " << filePath << " not found" << std::endl;
        return false;
    }

    return extractFile(files[0], outputPath, true, nullptr);
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

    // Read file content using TSK
    TSK_FS_FILE* fsFile = tsk_fs_file_open_meta(fsInfo_, nullptr, record.inode);
    if (!fsFile) {
        std::cerr << "Error: Cannot open file inode " << record.inode << std::endl;
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

ssize_t FileExtractor::readFileContent(int64_t inode, char* buffer, size_t size) {
    TSK_FS_FILE* fsFile = tsk_fs_file_open_meta(fsInfo_, nullptr, inode);
    if (!fsFile) {
        return -1;
    }

    ssize_t bytesRead = tsk_fs_file_read(fsFile, 0, buffer, size,
                                         TSK_FS_FILE_READ_FLAG_NONE);
    tsk_fs_file_close(fsFile);

    return bytesRead;
}

bool FileExtractor::createDirectories(const std::string& path) {
    try {
        fs::path p(path);
        fs::path dir = p.parent_path();

        if (!dir.empty() && !fs::exists(dir)) {
            fs::create_directories(dir);
        }
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Error creating directories: " << e.what() << std::endl;
        return false;
    }
}

std::string FileExtractor::generateOutputPath(const std::string& outputDir, const FileRecord& record) {
    fs::path outPath(outputDir);

    // Use relative path from image
    std::string relPath = record.path;

    // Remove leading slash
    if (!relPath.empty() && relPath[0] == '/') {
        relPath = relPath.substr(1);
    }

    // Build full output path
    outPath /= relPath;

    std::string pathStr = outPath.string();
    
    // Only resolve conflicts for deleted files map to same path (since inodes differ but path persists)
    // For allocated files, we assume path uniqueness (or we want to update the file at that path)
    if (record.isDeleted && fs::exists(pathStr)) {
        // Append inode to make unique
        fs::path p(pathStr);
        std::string stem = p.stem().string();
        std::string ext = p.extension().string();
        p.replace_filename(stem + "_" + std::to_string(record.inode) + ext);
        pathStr = p.string();
    }

    return pathStr;
}
